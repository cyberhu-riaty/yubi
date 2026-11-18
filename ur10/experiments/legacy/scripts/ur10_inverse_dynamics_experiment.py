from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import mujoco
import numpy as np
from scipy.io import loadmat, savemat
from scipy.signal import butter, filtfilt, savgol_filter

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from friction import UR10Friction  # noqa: E402

# Units: N*m/A.
# 关节力矩系数
TORQUE_CONSTANT = np.array(
    [14.7336, 14.3300, 11.5476, 11.2487, 11.5000, 11.5000], dtype=float
)

# 表3-11摩擦模型各系数数据；统一取自独立摩擦模块。
FRICTION_MODEL = UR10Friction()
FRICTION_FC = np.asarray(FRICTION_MODEL.fc)
FRICTION_FV = np.asarray(FRICTION_MODEL.fv)
FRICTION_B = np.asarray(FRICTION_MODEL.b)
FRICTION_ALPHA = np.asarray(FRICTION_MODEL.alpha)

# 单条轨迹的数据集信息（样本数、采样率、起止时间等），最终写入metadata
@dataclass
class DatasetInfo:
    file: str
    raw_samples: int
    unique_samples: int
    duplicate_samples_removed: int
    sample_rate_hz: float
    start_time_s: float
    duration_s: float
    analyzed_samples: int

# 解析命令行参数：模型路径、数据目录、输出目录以及各项滤波参数
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "models" / "ur10_extfric.xml",
        help="MuJoCo model with built-in damping and frictionloss set to zero.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(r"C:\Users\asteroid\Desktop\ur10数据-2106采集\ur10数据-2106采集"),
        help="Folder containing *_data_noload.mat files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "outputs" / "results",
        help="Output folder for MAT, CSV and JSON results.",
    )
    parser.add_argument(
        "--trajectory",
        type=int,
        default=None,
        help="Only process one trajectory number. Default: process all ten.",
    )
    parser.add_argument("--current-cutoff-hz", type=float, default=10.0)
    parser.add_argument(
        "--state-cutoff-hz",
        type=float,
        default=10.0,
        help="Low-pass cutoff applied before differentiating measured position.",
    )
    parser.add_argument(
        "--savgol-window-seconds",
        type=float,
        default=0.25,
        help="Window used to reconstruct smooth q, dq and ddq from actual_q.",
    )
    parser.add_argument(
        "--trim-seconds",
        type=float,
        default=0.5,
        help="Discard this amount from both ends after filtering.",
    )
    return parser.parse_args()


# 将MATLAB的cell数组按行拼接成数值矩阵，并检查转换后是否为49列
def cell_matrix_to_numeric(raw: np.ndarray) -> np.ndarray:
    if raw.dtype != object:
        return np.asarray(raw, dtype=float)
    rows: list[np.ndarray] = []
    for row in range(raw.shape[0]):
        pieces = [np.asarray(raw[row, col]).reshape(-1) for col in range(raw.shape[1])]
        rows.append(np.concatenate(pieces))
    result = np.vstack(rows).astype(float)
    if result.shape[1] != 49:
        raise ValueError(
            f"Expected 49 columns after cell2mat conversion, got {result.shape}"
        )
    return result


# 读取MAT文件中的ur_state_data，并转换成可计算的数值矩阵
def load_rtde_mat(path: Path) -> np.ndarray:
    content = loadmat(path)
    if "ur_state_data" not in content:
        raise KeyError(f"ur_state_data is missing from {path}")
    return cell_matrix_to_numeric(content["ur_state_data"])


# 同一控制器时间戳可能重复采集，只保留最后一条，并检查时间严格递增
def keep_last_sample_per_timestamp(samples: np.ndarray) -> np.ndarray:
    """Keep the last acquired row for every controller timestamp."""
    timestamps = samples[:, 48]
    _, reverse_indices = np.unique(timestamps[::-1], return_index=True)
    keep = len(timestamps) - 1 - reverse_indices
    keep.sort()
    cleaned = samples[keep]
    if np.any(np.diff(cleaned[:, 48]) <= 0):
        raise ValueError("Timestamps are not strictly increasing after de-duplication")
    return cleaned


# 四阶Butterworth零相位低通滤波，前后各滤一次避免相位延迟
def lowpass(signal: np.ndarray, sample_rate: float, cutoff: float) -> np.ndarray:
    if not 0 < cutoff < sample_rate / 2:
        raise ValueError(
            f"Cutoff {cutoff:g} Hz must be between zero and Nyquist "
            f"({sample_rate / 2:g} Hz)"
        )
    b, a = butter(4, cutoff / (sample_rate / 2), btype="low")
    return filtfilt(b, a, signal, axis=0)


# Savitzky-Golay窗口必须为奇数，且不能超过样本总数
def odd_window(sample_rate: float, seconds: float, sample_count: int) -> int:
    window = max(7, int(round(sample_rate * seconds)))
    if window % 2 == 0:
        window += 1
    largest = sample_count if sample_count % 2 == 1 else sample_count - 1
    return min(window, largest)


# 先低通再用Savitzky-Golay多项式同时求位置、速度、加速度，保证三者相互一致
def reconstruct_kinematics(
    actual_q: np.ndarray,
    sample_rate: float,
    state_cutoff_hz: float,
    window_seconds: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return mutually consistent smooth q, dq and ddq from measured position."""
    q_lowpass = lowpass(actual_q, sample_rate, state_cutoff_hz)
    window = odd_window(sample_rate, window_seconds, len(actual_q))
    polyorder = min(5, window - 2)
    dt = 1.0 / sample_rate
    q = savgol_filter(q_lowpass, window, polyorder, deriv=0, axis=0, mode="interp")
    dq = savgol_filter(
        q_lowpass, window, polyorder, deriv=1, delta=dt, axis=0, mode="interp"
    )
    ddq = savgol_filter(
        q_lowpass, window, polyorder, deriv=2, delta=dt, axis=0, mode="interp"
    )
    return q, dq, ddq

# 摩擦模型,计算摩擦力矩
def nonlinear_friction(velocity: np.ndarray) -> np.ndarray:
    return FRICTION_MODEL.torque(velocity)

# 采样点（关节位置、速度、加速度）赋值及mujoco逆动力学计算
def inverse_dynamics(
    model: mujoco.MjModel,
    q: np.ndarray,
    dq: np.ndarray,
    ddq: np.ndarray,
) -> np.ndarray:
    data = mujoco.MjData(model)
    result = np.empty_like(q)
    for sample in range(len(q)):
        data.qpos[:] = q[sample]
        data.qvel[:] = dq[sample]
        data.qacc[:] = ddq[sample]
        mujoco.mj_inverse(model, data)
        result[sample] = data.qfrc_inverse
    return result


# 均方根误差，反映整体误差大小
def rmse(predicted: np.ndarray, measured: np.ndarray) -> np.ndarray:
    return np.sqrt(np.mean((predicted - measured) ** 2, axis=0))


# 平均绝对误差
def mae(predicted: np.ndarray, measured: np.ndarray) -> np.ndarray:
    return np.mean(np.abs(predicted - measured), axis=0)


# 平均偏差（预测减实测），反映是否存在系统性高估或低估
def bias(predicted: np.ndarray, measured: np.ndarray) -> np.ndarray:
    return np.mean(predicted - measured, axis=0)


# 决定系数R²，越接近1表示拟合越好，实测方差为零时返回NaN
def r_squared(predicted: np.ndarray, measured: np.ndarray) -> np.ndarray:
    residual = np.sum((measured - predicted) ** 2, axis=0)
    total = np.sum((measured - np.mean(measured, axis=0)) ** 2, axis=0)
    return np.where(total > 0, 1.0 - residual / total, np.nan)


# 计算一条轨迹的误差指标，并按关节展开成6行记录
def metric_rows(
    trajectory: int,
    domain: str,
    variant: str,
    predicted: np.ndarray,
    measured: np.ndarray,
) -> list[dict[str, float | int | str]]:
    values_rmse = rmse(predicted, measured)
    values_mae = mae(predicted, measured)
    values_bias = bias(predicted, measured)
    values_r2 = r_squared(predicted, measured)
    values_max = np.max(np.abs(predicted - measured), axis=0)
    rows = []
    for joint in range(6):
        rows.append(
            {
                "trajectory": trajectory,
                "domain": domain,
                "variant": variant,
                "joint": joint + 1,
                "rmse": float(values_rmse[joint]),
                "mae": float(values_mae[joint]),
                "bias": float(values_bias[joint]),
                "max_abs_error": float(values_max[joint]),
                "r2": float(values_r2[joint]),
            }
        )
    return rows


# 将字典列表写成CSV，utf-8-sig编码便于Excel直接打开中文
def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


# 处理单条轨迹：读取数据、去重滤波、逆动力学计算、误差统计并保存结果
def analyze_file(
    path: Path,
    trajectory: int,
    model: mujoco.MjModel,
    args: argparse.Namespace,
) -> tuple[list[dict[str, object]], DatasetInfo]:
    # 读取原始数据，按时间戳去重，并根据中位时间间隔确定采样率
    raw = load_rtde_mat(path)
    samples = keep_last_sample_per_timestamp(raw)
    timestamp = samples[:, 48]
    time = timestamp - timestamp[0]
    dt = float(np.median(np.diff(time)))
    sample_rate = 1.0 / dt

    # 取出关节实际位置(0-5)、实际电流(12-17)和UR目标力矩(42-47)
    actual_q_raw = samples[:, 0:6]
    actual_current_raw = samples[:, 12:18]
    target_moment = samples[:, 42:48]

    # 重构平滑的位置、速度、加速度，并对实测电流做低通滤波
    q, dq, ddq = reconstruct_kinematics(
        actual_q_raw,
        sample_rate,
        args.state_cutoff_hz,
        args.savgol_window_seconds,
    )
    actual_current = lowpass(actual_current_raw, sample_rate, args.current_cutoff_hz)

    # 去掉首尾各一段数据，避免零相位滤波在边界产生的失真
    trim = round(args.trim_seconds * sample_rate) 
    if 2 * trim >= len(time):
        raise ValueError(f"Trim removes all samples from {path.name}")
    use = slice(trim, len(time) - trim if trim else None)
    time = time[use]
    time -= time[0]
    q, dq, ddq = q[use], dq[use], ddq[use]
    actual_current = actual_current[use]
    target_moment = target_moment[use]

    # 将辨识的非线性摩擦力矩补偿到MuJoCo返回的无摩擦关节力矩中
    torque_without_friction = inverse_dynamics(model, q, dq, ddq)
    friction = nonlinear_friction(dq)
    torque_with_friction = torque_without_friction + friction

    # 真机电流乘力矩系数得到估算力矩，模型力矩除力矩系数得到预测电流
    measured_torque = actual_current * TORQUE_CONSTANT
    current_without_friction = torque_without_friction / TORQUE_CONSTANT
    current_with_friction = torque_with_friction / TORQUE_CONSTANT

    # 分别计算力矩域和电流域中无摩擦、有摩擦两种结果的误差指标
    rows: list[dict[str, object]] = []
    metric_cases = (
        (
            "torque_Nm",
            "identified_friction_off",
            torque_without_friction,
            measured_torque,
        ),
        (
            "torque_Nm",
            "identified_nonlinear_friction",
            torque_with_friction,
            measured_torque,
        ),
        (
            "current_A",
            "identified_friction_off",
            current_without_friction,
            actual_current,
        ),
        (
            "current_A",
            "identified_nonlinear_friction",
            current_with_friction,
            actual_current,
        ),
    )
    for domain, variant, predicted, measured in metric_cases:
        rows.extend(
            metric_rows(
                trajectory,
                domain,
                variant,
                predicted,
                measured,
            )
        )

    # 保存本条轨迹的关节状态、摩擦力矩、预测结果和误差，供MATLAB绘图
    output_path = args.output_dir / f"trajectory_{trajectory}_identified_results.mat"
    savemat(
        output_path,
        {
            "trajectory": np.array([[trajectory]], dtype=np.int32),
            "time_s": time.reshape(-1, 1),
            "q_actual_rad": q,
            "dq_actual_rad_s": dq,
            "ddq_actual_rad_s2": ddq,
            "actual_current_A": actual_current,
            "actual_torque_est_Nm": measured_torque,
            "target_moment_Nm": target_moment,
            "friction_torque_Nm": friction,
            "identified_torque_friction_off_Nm": torque_without_friction,
            "identified_torque_nonlinear_friction_Nm": torque_with_friction,
            "identified_current_friction_off_A": current_without_friction,
            "identified_current_nonlinear_friction_A": current_with_friction,
            "identified_torque_error_Nm": torque_with_friction - measured_torque,
            "identified_current_error_A": current_with_friction - actual_current,
            "torque_constant_Nm_per_A": TORQUE_CONSTANT.reshape(1, -1),
        },
        do_compression=True,
    )
    print(f"Saved calculated data: {output_path}")

    # 记录原始数据量、去重后的采样率以及实际参与计算的数据量
    info = DatasetInfo(
        file=path.name,
        raw_samples=len(raw),
        unique_samples=len(samples),
        duplicate_samples_removed=len(raw) - len(samples),
        sample_rate_hz=sample_rate,
        start_time_s=float(timestamp[0]),
        duration_s=float(timestamp[-1] - timestamp[0]),
        analyzed_samples=len(time),
    )
    return rows, info


# 将所有轨迹按数据域、摩擦方案和关节编号分组，计算平均误差指标
def aggregate_metrics(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, int], list[dict[str, object]]] = {}
    for row in rows:
        key = (str(row["domain"]), str(row["variant"]), int(row["joint"]))
        groups.setdefault(key, []).append(row)
    result = []
    for (domain, variant, joint), group in sorted(groups.items()):
        result.append(
            {
                "domain": domain,
                "variant": variant,
                "joint": joint,
                "trajectory_count": len(group),
                "mean_rmse": float(np.mean([float(x["rmse"]) for x in group])),
                "mean_mae": float(np.mean([float(x["mae"]) for x in group])),
                "mean_bias": float(np.mean([float(x["bias"]) for x in group])),
                "mean_max_abs_error": float(
                    np.mean([float(x["max_abs_error"]) for x in group])
                ),
                "mean_r2": float(np.mean([float(x["r2"]) for x in group])),
            }
        )
    return result
    

# 检查模型自由度，并确保XML内部阻尼和干摩擦已清零，避免重复计算摩擦
def validate_model(model: mujoco.MjModel) -> None:
    if model.nq != 6 or model.nv != 6:
        raise ValueError(f"Expected a 6-DOF model, got nq={model.nq}, nv={model.nv}")
    if not np.allclose(model.dof_damping, 0):
        raise ValueError(f"Model damping must be zero, got {model.dof_damping}")
    if not np.allclose(model.dof_frictionloss, 0):
        raise ValueError(
            f"Model frictionloss must be zero, got {model.dof_frictionloss}"
        )


def main() -> None:
    # 读取命令行参数并创建结果输出文件夹
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 加载标定后的MuJoCo模型并检查模型设置
    model = mujoco.MjModel.from_xml_path(str(args.model))
    validate_model(model)

    # 默认处理全部10条轨迹，也可以通过--trajectory只处理指定轨迹
    if args.trajectory is None:
        files = sorted(args.data_dir.glob("ur_rtde_newtraj_2021_*_data_noload.mat"))
    else:
        files = [
            args.data_dir / f"ur_rtde_newtraj_2021_{args.trajectory}_data_noload.mat"
        ]
    if not files or any(not path.exists() for path in files):
        raise FileNotFoundError(f"No matching data files found in {args.data_dir}")

    # 逐条轨迹进行数据预处理、逆动力学计算和结果导出
    all_rows: list[dict[str, object]] = []
    dataset_info: list[DatasetInfo] = []
    for path in files:
        trajectory = int(path.stem.split("_")[4])
        print(f"Analyzing trajectory {trajectory}: {path.name}")
        rows, info = analyze_file(path, trajectory, model, args)
        all_rows.extend(rows)
        dataset_info.append(info)

    # 保存每条轨迹的误差指标以及10条轨迹的平均误差指标
    detailed_path = args.output_dir / "metrics_by_trajectory.csv"
    summary_path = args.output_dir / "metrics_summary.csv"
    metadata_path = args.output_dir / "experiment_metadata.json"
    write_csv(detailed_path, all_rows)
    write_csv(summary_path, aggregate_metrics(all_rows))

    # 保存模型路径、摩擦参数、滤波参数和各轨迹采样信息，便于复现实验
    metadata = {
        "model": str(args.model.resolve()),
        "data_dir": str(args.data_dir.resolve()),
        "torque_constant_Nm_per_A": TORQUE_CONSTANT.tolist(),
        "friction_Fc": FRICTION_FC.tolist(),
        "friction_Fv": FRICTION_FV.tolist(),
        "friction_B": FRICTION_B.tolist(),
        "friction_alpha": FRICTION_ALPHA.tolist(),
        "current_cutoff_hz": args.current_cutoff_hz,
        "state_cutoff_hz": args.state_cutoff_hz,
        "savgol_window_seconds": args.savgol_window_seconds,
        "trim_seconds_each_end": args.trim_seconds,
        "datasets": [asdict(info) for info in dataset_info],
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Detailed metrics: {detailed_path}")
    print(f"Summary metrics:  {summary_path}")
    print(f"Metadata:         {metadata_path}")


# 直接运行脚本时执行主流程
if __name__ == "__main__":
    main()
