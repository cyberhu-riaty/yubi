"""计算UR10标定/原始刚体参数与不同摩擦模型的标准组合并导出MAT文件。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mujoco
import numpy as np
from scipy.io import savemat

import ur10_inverse_dynamics_experiment as core


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--identified-model",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "models" / "ur10_extfric.xml",
        help="标定刚体参数，XML内部damping和frictionloss为零。",
    )
    parser.add_argument(
        "--nominal-model",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "models" / "ur10_normal.xml",
        help="原始刚体参数与原始XML被动参数。",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(
            r"C:\Users\asteroid\Desktop\ur10数据-2106采集\ur10数据-2106采集"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "outputs" / "results_all_combinations",
    )
    parser.add_argument("--trajectory", type=int, default=None)
    parser.add_argument("--current-cutoff-hz", type=float, default=10.0)
    parser.add_argument("--state-cutoff-hz", type=float, default=10.0)
    parser.add_argument("--savgol-window-seconds", type=float, default=0.25)
    parser.add_argument("--trim-seconds", type=float, default=0.5)
    return parser.parse_args()


def load_models(args: argparse.Namespace) -> dict[str, mujoco.MjModel]:
    # 标定刚体模型：XML内部摩擦为零，外部按需要添加辨识非线性摩擦。
    identified_off = mujoco.MjModel.from_xml_path(str(args.identified_model))
    core.validate_model(identified_off)

    # 原始完整模型：保留原始XML继承得到的damping、frictionloss和armature。
    nominal_xml = mujoco.MjModel.from_xml_path(str(args.nominal_model))

    # 标定刚体+原始XML默认摩擦：保留标定刚体和armature，只将原始模型的
    # damping与frictionloss复制到内存模型中，不修改任何源XML文件。
    identified_xml_default = mujoco.MjModel.from_xml_path(str(args.identified_model))
    identified_xml_default.dof_damping[:] = nominal_xml.dof_damping
    identified_xml_default.dof_frictionloss[:] = nominal_xml.dof_frictionloss

    # 原始无摩擦模型：重新加载后仅在内存中清零被动摩擦，不修改源XML。
    nominal_off = mujoco.MjModel.from_xml_path(str(args.nominal_model))
    nominal_off.dof_damping[:] = 0.0
    nominal_off.dof_frictionloss[:] = 0.0

    for name, model in {
        "identified_xml_default": identified_xml_default,
        "nominal_xml": nominal_xml,
        "nominal_off": nominal_off,
    }.items():
        if model.nq != 6 or model.nv != 6:
            raise ValueError(f"{name}不是6自由度模型：nq={model.nq}, nv={model.nv}")

    return {
        "identified_off": identified_off,
        "identified_xml_default": identified_xml_default,
        "nominal_xml": nominal_xml,
        "nominal_off": nominal_off,
    }


def analyze_file(
    path: Path,
    trajectory: int,
    models: dict[str, mujoco.MjModel],
    args: argparse.Namespace,
) -> dict[str, object]:
    raw = core.load_rtde_mat(path)
    samples = core.keep_last_sample_per_timestamp(raw)
    timestamp = samples[:, 48]
    time = timestamp - timestamp[0]
    sample_rate = 1.0 / float(np.median(np.diff(time)))

    actual_q_raw = samples[:, 0:6]
    actual_current_raw = samples[:, 12:18]
    target_moment = samples[:, 42:48]
    q, dq, ddq = core.reconstruct_kinematics(
        actual_q_raw,
        sample_rate,
        args.state_cutoff_hz,
        args.savgol_window_seconds,
    )
    actual_current_filtered = core.lowpass(
        actual_current_raw, sample_rate, args.current_cutoff_hz
    )

    trim = int(round(args.trim_seconds * sample_rate))
    if 2 * trim >= len(time):
        raise ValueError(f"首尾截除后无有效样本：{path.name}")
    use = slice(trim, len(time) - trim if trim else None)
    time = time[use]
    time -= time[0]
    q, dq, ddq = q[use], dq[use], ddq[use]
    actual_current_raw = actual_current_raw[use]
    actual_current_filtered = actual_current_filtered[use]
    target_moment = target_moment[use]

    # 由同一组actual q/dq/ddq计算各刚体/摩擦组合，确保控制变量一致。
    identified_rigid_off = core.inverse_dynamics(
        models["identified_off"], q, dq, ddq
    )
    nominal_rigid_off = core.inverse_dynamics(models["nominal_off"], q, dq, ddq)
    nominal_original_xml = core.inverse_dynamics(models["nominal_xml"], q, dq, ddq)
    identified_original_xml_friction = core.inverse_dynamics(
        models["identified_xml_default"], q, dq, ddq
    )
    identified_nonlinear_friction = core.nonlinear_friction(dq)
    identified_rigid_nonlinear = (
        identified_rigid_off + identified_nonlinear_friction
    )
    nominal_rigid_nonlinear = nominal_rigid_off + identified_nonlinear_friction

    kt = core.TORQUE_CONSTANT
    actual_torque_est = actual_current_filtered * kt

    # 变量名完整写出刚体参数和摩擦模型，避免MATLAB分析时混淆。
    result = {
        "trajectory": np.array([[trajectory]], dtype=np.int32),
        "time_s": time.reshape(-1, 1),
        "sample_rate_Hz": np.array([[sample_rate]]),
        "q_actual_rad": q,
        "dq_actual_rad_s": dq,
        "ddq_actual_rad_s2": ddq,
        "actual_current_raw_A": actual_current_raw,
        "actual_current_filtered_A": actual_current_filtered,
        "actual_torque_est_from_filtered_current_Nm": actual_torque_est,
        "target_moment_Nm": target_moment,
        "torque_constant_Nm_per_A": kt.reshape(1, -1),
        "identified_nonlinear_friction_torque_Nm": identified_nonlinear_friction,
        "identified_rigid_friction_off_torque_Nm": identified_rigid_off,
        "identified_rigid_friction_off_current_A": identified_rigid_off / kt,
        "identified_rigid_identified_nonlinear_friction_torque_Nm": identified_rigid_nonlinear,
        "identified_rigid_identified_nonlinear_friction_current_A": identified_rigid_nonlinear / kt,
        "identified_rigid_original_xml_friction_torque_Nm": identified_original_xml_friction,
        "identified_rigid_original_xml_friction_current_A": identified_original_xml_friction / kt,
        "nominal_rigid_friction_off_torque_Nm": nominal_rigid_off,
        "nominal_rigid_friction_off_current_A": nominal_rigid_off / kt,
        "nominal_rigid_identified_nonlinear_friction_torque_Nm": nominal_rigid_nonlinear,
        "nominal_rigid_identified_nonlinear_friction_current_A": nominal_rigid_nonlinear / kt,
        "nominal_rigid_original_xml_friction_torque_Nm": nominal_original_xml,
        "nominal_rigid_original_xml_friction_current_A": nominal_original_xml / kt,
    }
    output_path = args.output_dir / f"trajectory_{trajectory}_all_combinations.mat"
    savemat(output_path, result, do_compression=True)
    print(f"已导出：{output_path}")

    return {
        "trajectory": trajectory,
        "source_file": path.name,
        "raw_samples": len(raw),
        "unique_samples": len(samples),
        "analyzed_samples": len(time),
        "sample_rate_Hz": sample_rate,
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    models = load_models(args)

    if args.trajectory is None:
        files = sorted(args.data_dir.glob("ur_rtde_newtraj_2021_*_data_noload.mat"))
    else:
        files = [
            args.data_dir / f"ur_rtde_newtraj_2021_{args.trajectory}_data_noload.mat"
        ]
    if not files or any(not path.exists() for path in files):
        raise FileNotFoundError(f"未找到轨迹数据：{args.data_dir}")

    datasets = []
    for path in files:
        trajectory = int(path.stem.split("_")[4])
        print(f"计算轨迹{trajectory}：{path.name}")
        datasets.append(analyze_file(path, trajectory, models, args))

    metadata = {
        "model_meanings": {
            "identified_model": "标定刚体参数，XML内部摩擦清零",
            "identified_with_original_xml_friction": "标定刚体参数+原始XML默认damping/frictionloss",
            "nominal_model": "原始刚体参数+原始XML被动参数",
        },
        "identified_model_path": str(args.identified_model.resolve()),
        "nominal_model_path": str(args.nominal_model.resolve()),
        "original_xml_damping_used_for_identified_model": models[
            "nominal_xml"
        ].dof_damping.tolist(),
        "original_xml_frictionloss_used_for_identified_model": models[
            "nominal_xml"
        ].dof_frictionloss.tolist(),
        "data_dir": str(args.data_dir.resolve()),
        "current_filter_cutoff_Hz": args.current_cutoff_hz,
        "state_filter_cutoff_Hz": args.state_cutoff_hz,
        "savgol_window_seconds": args.savgol_window_seconds,
        "trim_seconds_each_end": args.trim_seconds,
        "torque_constant_Nm_per_A": core.TORQUE_CONSTANT.tolist(),
        "datasets": datasets,
    }
    metadata_path = args.output_dir / "all_combinations_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"说明文件：{metadata_path}")


if __name__ == "__main__":
    main()
