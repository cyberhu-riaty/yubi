"""Rebuild UR10 torque comparison/error figures using the packaged friction.

Archived rigid-body torques reproduce the original curves. Optional MuJoCo
recalculation diagnoses differences from the historical inverse-dynamics run.

重画 legacy 的「六种模型组合」力矩对比图/误差图。所有摩擦统一来自 friction 包，
本文件只有两个施加点：law.torque(dq)（纯摩擦）和 inverse_dynamics(..., law)
（刚体+摩擦）。默认 archived 路径：刚体力矩用存档值保证逐点复现，只重算摩擦。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")  # 批量出图，不能弹窗
import matplotlib.pyplot as plt
from matplotlib import font_manager
import mujoco
import numpy as np
from scipy.io import loadmat, savemat

ROOT = Path(__file__).resolve().parents[1]   # ur10/ 的路径
sys.path.insert(0, str(ROOT))
from friction import inverse_dynamics  # noqa: E402
from friction.files import FileFriction, load_friction, load_robot, read_json  # noqa: E402
from friction.model import JOINT_NAMES  # noqa: E402


CASES = {
    "nominal_xml": ("nominal_rigid_original_xml_friction_torque_Nm", "原始刚体＋原始XML摩擦", "原始完整"),  # 原始刚体，摩擦来自 XML：damping=[10,10,5,2,2,2]
    "nominal_off": ("nominal_rigid_friction_off_torque_Nm", "原始刚体＋无摩擦", "原始无摩擦"),
    "nominal_identified_friction": ("nominal_rigid_identified_nonlinear_friction_torque_Nm", "原始刚体＋辨识非线性摩擦", "原始＋辨识摩擦"),  # 原始刚体，摩擦来自外挂 law.torque(dq)
    "identified_off": ("identified_rigid_friction_off_torque_Nm", "标定刚体＋无摩擦", "标定无摩擦"),
    "identified_xml_default": ("identified_rigid_original_xml_friction_torque_Nm", "标定刚体＋原始XML默认摩擦", "XML默认摩擦"),  # 标定刚体，但摩擦换回 XML 的线性阻尼：用来回答「不做摩擦辨识能到多准」
    "identified_nonlinear": ("identified_rigid_identified_nonlinear_friction_torque_Nm", "标定刚体＋辨识非线性摩擦", "完整标定"),    # 标定刚体 + 外挂辨识摩擦：唯一的「完整模型」
}

MODES = {
    "full_model_comparison": ("nominal_xml", "identified_nonlinear", "原始完整模型与完整标定模型对比"),
    "identified_friction_effect": ("identified_off", "identified_nonlinear", "标定刚体参数下的摩擦模型对比"),  # 同一刚体只切摩擦有无 → 单独量化摩擦项的贡献（RMSE 13.45 → 1.92 N·m）
    "rigid_parameter_effect": ("nominal_off", "identified_off", "无摩擦条件下的刚体参数对比"),
    "nominal_friction_effect": ("nominal_off", "nominal_identified_friction", "原始刚体参数下的摩擦模型对比"),
    "xml_default_friction_effect": ("identified_xml_default", "identified_nonlinear", "原始XML默认摩擦与非线性摩擦对比"),  # 线性阻尼 vs 非线性摩擦：验证「|v|^α + 库仑 + 偏置」比线性阻尼好多少
}


@dataclass(frozen=True)
class RunConfig:
    """运行参数的结构；具体取值统一放在文件末尾的 CONFIG。"""

    source_dir: Path
    output_root: Path
    identified_model_file: Path
    nominal_model_file: Path
    friction_model_file: Path
    friction_params_file: Path
    identified_dynamics_file: Path | None
    nominal_dynamics_file: Path | None
    measurement_params_file: Path | None
    trajectories: tuple[int, ...] | None
    modes: tuple[str, ...]
    rigid_source: str
    plot_torque: bool
    plot_torque_error: bool
    save_mat: bool
    image_dpi: int


def parser() -> argparse.ArgumentParser:
    """命令行仅覆盖文件末尾 CONFIG 中显式指定的项目。"""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-dir", type=Path)
    p.add_argument("--output-dir", type=Path, help="Override CONFIG.output_root")
    p.add_argument("--model-dir", type=Path)
    for name in ("identified-model-file", "nominal-model-file", "friction-model-file", "friction-params-file",
                 "identified-dynamics-file", "nominal-dynamics-file", "measurement-params-file"):
        p.add_argument("--" + name, type=Path)
    p.add_argument("--trajectory", type=int, action="append", help="Repeat to select several trajectories")
    p.add_argument("--mode", choices=tuple(MODES) + ("all",), action="append", help="Repeat to select several modes")
    # archived：刚体力矩取存档，只重算摩擦（曲线可逐点复现）；recompute：重跑 mj_inverse
    p.add_argument("--rigid-source", choices=("archived", "recompute"),
                   help="Archived rigid torques preserve original curves; recompute reruns MuJoCo")
    return p


def cli_config(config: RunConfig) -> RunConfig:
    """保留旧命令行用法；未传的选项沿用 CONFIG。"""
    args = parser().parse_args()
    changes = {}
    for option in ("source_dir", "rigid_source", "identified_model_file", "nominal_model_file",
                   "friction_model_file", "friction_params_file", "identified_dynamics_file", "nominal_dynamics_file", "measurement_params_file"):
        value = getattr(args, option)
        if value is not None:
            changes[option] = value
    if args.model_dir is not None:
        changes.setdefault("identified_model_file", args.model_dir / "ur10_extfric.xml")
        changes.setdefault("nominal_model_file", args.model_dir / "ur10_normal.xml")
    if args.output_dir is not None:
        changes["output_root"] = args.output_dir
    if args.trajectory is not None:
        changes["trajectories"] = tuple(args.trajectory)
    if args.mode is not None:
        changes["modes"] = tuple(args.mode)
    return replace(config, **changes)


def load_models(config: RunConfig, law: FileFriction) -> dict[str, mujoco.MjModel]:
    """作用：编译 4 个模型（标定/原始刚体 × 有无 XML 阻尼），只在 recompute 路径用。"""
    # 标定刚体：damping/frictionloss 全 0，摩擦留给外挂 law
    identified_off = load_robot(config.identified_model_file, config.identified_dynamics_file)
    identified_off.dof_damping[:] = 0
    identified_off.dof_frictionloss[:] = 0
    # 原始模型：自带 damping=[10,10,5,2,2,2]、frictionloss=0、armature 全 0.1
    nominal_xml = load_robot(config.nominal_model_file, config.nominal_dynamics_file)
    # 标定刚体 + 原始 XML 的阻尼：只改内存对象，不动 xml。
    # 这样「刚体」和「摩擦」两个因素被拆开，阻尼由 mj_inverse 扣，不能再加 law.torque。
    identified_xml_default = load_robot(config.identified_model_file, config.identified_dynamics_file)
    identified_xml_default.dof_damping[:] = nominal_xml.dof_damping
    identified_xml_default.dof_frictionloss[:] = nominal_xml.dof_frictionloss  # 实为 0，写全是表态
    # 原始刚体 + 无摩擦：清零阻尼后才等价于「纯刚体」
    nominal_off = load_robot(config.nominal_model_file, config.nominal_dynamics_file)
    nominal_off.dof_damping[:] = 0
    nominal_off.dof_frictionloss[:] = 0
    for model in (identified_off, nominal_xml, identified_xml_default, nominal_off):
        if model.nq != 6 or model.nv != 6 or not np.array_equal(law.dof_indices(model), np.arange(6)):
            raise ValueError("XML must have six hinge DOFs in the same order as friction joint_names and MAT columns")
    law.validate_model(identified_off)
    return dict(identified_off=identified_off, nominal_xml=nominal_xml,
                identified_xml_default=identified_xml_default, nominal_off=nominal_off)


def rigid_inverse(model: mujoco.MjModel, q: np.ndarray, dq: np.ndarray, ddq: np.ndarray) -> np.ndarray:
    """作用：跑 mj_inverse 求刚体力矩，不加外挂摩擦。

    注意「without friction」只指不加 law.torque。qfrc_inverse 本身已扣掉模型
    自带被动项：对 *_off 模型是纯刚体，对 nominal_xml / identified_xml_default
    则已含黏性阻尼——名字里的 rigid 不是「物理上无摩擦」。
    """
    data = mujoco.MjData(model)
    result = np.empty_like(q)
    for i in range(len(q)):
        data.qpos[:] = q[i]
        data.qvel[:] = dq[i]      # 被动阻尼只依赖速度
        data.qacc[:] = ddq[i]     # 不给的话惯性项为 0
        mujoco.mj_inverse(model, data)
        result[i] = data.qfrc_inverse   # 刻意不 + law.torque(...)
    return result


def recompute(archive: dict, models: dict[str, mujoco.MjModel], law: FileFriction) -> dict:
    """作用：用存档的 q/dq/ddq 重算 6 条力矩曲线（摩擦按当前 friction 包计算）。"""
    q, dq, ddq = (archive[name] for name in ("q_actual_rad", "dq_actual_rad_s", "ddq_actual_rad_s2"))
    identified_off = rigid_inverse(models["identified_off"], q, dq, ddq)
    nominal_off = rigid_inverse(models["nominal_off"], q, dq, ddq)
    return {
        "time_s": archive["time_s"],
        "actual_torque_est_from_filtered_current_Nm": archive["actual_torque_est_from_filtered_current_Nm"],
        "identified_nonlinear_friction_torque_Nm": law.torque(dq),
        "identified_rigid_friction_off_torque_Nm": identified_off,
        # 刚体 + 摩擦：封装版 inverse_dynamics 内部已做 mj_inverse + law.torque
        "identified_rigid_identified_nonlinear_friction_torque_Nm": inverse_dynamics(models["identified_off"], q, dq, ddq, law),
        # 阻尼在模型里，用 rigid_inverse 即可，再叠加外挂摩擦就是算两遍
        "identified_rigid_original_xml_friction_torque_Nm": rigid_inverse(models["identified_xml_default"], q, dq, ddq),
        "nominal_rigid_friction_off_torque_Nm": nominal_off,
        "nominal_rigid_identified_nonlinear_friction_torque_Nm": inverse_dynamics(models["nominal_off"], q, dq, ddq, law),
        "nominal_rigid_original_xml_friction_torque_Nm": rigid_inverse(models["nominal_xml"], q, dq, ddq),
    }


def from_archived_rigid(archive: dict, law: FileFriction) -> dict:
    """作用：用存档刚体力矩 + 重算摩擦，拼出 6 条曲线，保证与历史逐点一致。

    刚体力矩不重算，只把摩擦用当前的 friction 包重算再加回去。
    """
    dq = archive["dq_actual_rad_s"]
    friction = law.torque(dq)   # 摩擦只依赖速度的符号与大小
    identified_off = archive["identified_rigid_friction_off_torque_Nm"]
    nominal_off = archive["nominal_rigid_friction_off_torque_Nm"]
    return {
        "time_s": archive["time_s"],
        "actual_torque_est_from_filtered_current_Nm": archive["actual_torque_est_from_filtered_current_Nm"],
        "identified_nonlinear_friction_torque_Nm": friction,
        "identified_rigid_friction_off_torque_Nm": identified_off,
        # 真实方程 M q̈+Cq̇+g = τ_motor − τ_f，mj_inverse 给的是左边，所以是移项相加
        "identified_rigid_identified_nonlinear_friction_torque_Nm": identified_off + friction,
        # 这两条带 XML 阻尼，qfrc_inverse 已含，直接沿用存档，不能再加外挂摩擦
        "identified_rigid_original_xml_friction_torque_Nm": archive["identified_rigid_original_xml_friction_torque_Nm"],
        "nominal_rigid_friction_off_torque_Nm": nominal_off,
        "nominal_rigid_identified_nonlinear_friction_torque_Nm": nominal_off + friction,
        "nominal_rigid_original_xml_friction_torque_Nm": archive["nominal_rigid_original_xml_friction_torque_Nm"],
    }


def configure_font() -> None:
    """作用：挑一个系统里有的中文字体，否则中文标题全是方块。"""
    names = {font.name for font in font_manager.fontManager.ttflist}
    for name in ("PingFang SC", "Heiti SC", "Noto Sans CJK SC", "Arial Unicode MS"):
        if name in names:
            plt.rcParams["font.sans-serif"] = [name]
            break
    plt.rcParams["axes.unicode_minus"] = False


def make_figure(data: dict, trajectory: int, mode: str, kind: str, output: Path, dpi: int, friction_label: str) -> None:
    """作用：画 3×2 六关节子图，kind='torque' 出力矩对比，'error' 出残差。"""
    first, second, title = MODES[mode]
    key1, label1, short1 = CASES[first]
    key2, label2, short2 = CASES[second]
    label1 = label1.replace("辨识非线性摩擦", friction_label)
    label2 = label2.replace("辨识非线性摩擦", friction_label)
    if mode == "xml_default_friction_effect":
        title = f"原始XML默认摩擦与{friction_label}对比"
    measured = data["actual_torque_est_from_filtered_current_Nm"]   # 电流×Kt 估的基准
    y1, y2 = data[key1], data[key2]
    t = data["time_s"].ravel()
    fig, axes = plt.subplots(3, 2, figsize=(15, 10), sharex=True, constrained_layout=True)
    fig.suptitle(f"轨迹{trajectory}：{title}" if kind == "torque" else
                 f"轨迹{trajectory}：力矩误差（模型－真机估算值）", fontweight="bold")
    for joint, ax in enumerate(axes.flat):
        if kind == "torque":
            ax.plot(t, measured[:, joint], color="black", lw=1.2, label="真机估算力矩（Kt I）")
            left, right = y1[:, joint], y2[:, joint]
            metric1 = np.sqrt(np.mean((left - measured[:, joint]) ** 2))
            metric2 = np.sqrt(np.mean((right - measured[:, joint]) ** 2))
            ax.set_title(f"关节{joint + 1} RMSE：{short1} {metric1:.3f}；{short2} {metric2:.3f} N·m")
            ax.set_ylabel("力矩（N·m）")
        else:
            ax.axhline(0, color="black", lw=0.7)
            left = y1[:, joint] - measured[:, joint]
            right = y2[:, joint] - measured[:, joint]
            ax.set_title(f"关节{joint + 1} Bias：{short1} {np.mean(left):.3f}；{short2} {np.mean(right):.3f} N·m")
            ax.set_ylabel("力矩误差（N·m）")
        ax.plot(t, left, color=(0.466, 0.674, 0.188), lw=1.0, label=label1 + ("误差" if kind == "error" else ""))
        ax.plot(t, right, color=(0, 0.447, 0.741), lw=1.1, label=label2 + ("误差" if kind == "error" else ""))
        ax.grid(True)
        ax.set_xlabel("时间（s）")
        if joint == 0:   # 图例只放第一个子图
            ax.legend(loc="best", fontsize=8)
    fig.savefig(output, dpi=dpi)
    plt.close(fig)


def run(config: RunConfig) -> None:
    """作用：主流程——选存档文件 → 生成 6 条曲线 → 每种模式出两类图。"""
    if config.rigid_source not in ("archived", "recompute"):
        raise ValueError("rigid_source must be 'archived' or 'recompute'")
    if config.image_dpi <= 0:
        raise ValueError("image_dpi must be positive")
    if config.rigid_source == "archived" and (config.identified_dynamics_file or config.nominal_dynamics_file):
        raise ValueError("Dynamics parameter files require rigid_source='recompute'; archived uses saved rigid torques")
    modes = tuple(MODES) if "all" in config.modes else config.modes
    if not modes or any(mode not in MODES for mode in modes):
        raise ValueError(f"modes must contain 'all' or names from {tuple(MODES)}")
    paths = ([config.source_dir / f"trajectory_{n}_all_combinations.mat" for n in config.trajectories]
             if config.trajectories is not None else sorted(config.source_dir.glob("trajectory_*_all_combinations.mat")))
    if not paths or any(not p.is_file() for p in paths):
        raise FileNotFoundError("No archived trajectory MAT files found; check --source-dir and --trajectory")
    output_dir = config.output_root / ("archived_rigid" if config.rigid_source == "archived" else "recomputed_rigid")
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_font()
    law = load_friction(config.friction_model_file, config.friction_params_file)  # 加载摩擦
    if config.rigid_source == "archived" and law.joint_names != JOINT_NAMES:
        raise ValueError("Archived MAT columns use the original UR10 joint order; joint_names must match")
    models = load_models(config, law) if config.rigid_source == "recompute" else None
    print(f"Friction: {law.label}; rigid_source={config.rigid_source}")
    if models is None:
        print("Archived rigid torques are used; XML files are not loaded in this mode.")
    with (output_dir / "run_config.json").open("w", encoding="utf-8") as stream:
        json.dump(vars(config), stream, default=str, ensure_ascii=False, indent=2)
    for path in paths:
        n = int(path.stem.split("_")[1])   # trajectory_0_all_combinations → 0
        archive = loadmat(path)
        if config.measurement_params_file is not None:
            measurement = read_json(config.measurement_params_file)
            kt = np.asarray(measurement["torque_constant_Nm_per_A"], dtype=float)
            if kt.shape != (6,) or not np.all(np.isfinite(kt)) or np.any(kt <= 0):
                raise ValueError("torque_constant_Nm_per_A must contain six positive finite values")
            archive["actual_torque_est_from_filtered_current_Nm"] = archive["actual_current_filtered_A"] * kt
        data = (from_archived_rigid(archive, law) if models is None else recompute(archive, models, law))
        if config.save_mat:
            savemat(output_dir / f"trajectory_{n}_recomputed_torque.mat", data, do_compression=True)
        figure_types = []
        if config.plot_torque:
            figure_types.append(("torque", "torque"))
        if config.plot_torque_error:
            figure_types.append(("error", "torque_error"))
        for mode in modes:
            for kind, suffix in figure_types:
                output = output_dir / f"trajectory_{n}_{mode}_{suffix}.png"
                make_figure(data, n, mode, kind, output, config.image_dpi, law.label)
                print(output)



CONFIG = RunConfig(
    source_dir=ROOT / "experiments" / "legacy" / "outputs" / "results_all_combinations",  # 存档 .mat 目录
    output_root=ROOT / "experiments" / "reproduced",  # 输出的地址
    identified_model_file=ROOT / "models" / "ur10_extfric.xml",  # 辨识后的完整 XML；
    nominal_model_file=ROOT / "models" / "ur10_normal.xml",  # 对照模型 XML；
    friction_model_file=ROOT / "configs" / "power_friction.json",  # 摩擦模型定义 JSON 或自定义 .py
    friction_params_file=ROOT / "configs" / "ur10_identified_friction.json",  # 摩擦辨识参数
    identified_dynamics_file=None,  # 可选动力学参数 JSON；None 表示使用 XML 内的参数
    nominal_dynamics_file=None,  # 可选对照模型动力学参数 JSON
    measurement_params_file=None,  # 可选电流-力矩系数 JSON；None 沿用存档参考力矩
    trajectories=None,  # None=全部；0 = 只跑第0条；(0, 1)=跑两条
    modes=("all",),  # 拿哪两条曲线放一张图里对比，例：("identified_friction_effect", "full_model_comparison")
    rigid_source="archived",  # （在这个例子里面结果一模一样）archived = 复现旧曲线；recompute = 跑 MuJoCo 刚体逆动力学
    plot_torque=True,  # 是否出力矩对比图
    plot_torque_error=True,  # 是否出力矩误差图
    save_mat=True,  # 是否另存画图用的数据 .mat
    image_dpi=200,  # 出图分辨率（PNG dpi）
)



if __name__ == "__main__":
    run(cli_config(CONFIG))


# CONFIG = RunConfig(
#     source_dir=Path("/本地/ur5/准备好的MAT结果"),
#     output_root=Path("/本地/ur5/输出"),

#     identified_model_file=Path("/本地/ur5/ur5_identified.xml"),
#     nominal_model_file=Path("/本地/ur5/ur5_nominal.xml"),

#     friction_model_file=Path("/本地/ur5/power_friction.json"),
#     friction_params_file=Path("/本地/ur5/friction_identified.json"),

#     identified_dynamics_file=Path("/本地/ur5/dynamics_identified.json"),
#     nominal_dynamics_file=None,
#     measurement_params_file=Path("/本地/ur5/torque_constants.json"),

#     trajectories=None,
#     modes=("all",),
#     rigid_source="recompute",
#     # 其余绘图设置……
# )