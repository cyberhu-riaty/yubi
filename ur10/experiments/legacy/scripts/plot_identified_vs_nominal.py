from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mujoco
import numpy as np
from scipy.io import savemat

import ur10_inverse_dynamics_experiment as core


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Overlay identified and nominal UR10 inverse-dynamics results."
    )
    parser.add_argument(
        "--identified-model",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "models" / "ur10_extfric.xml",
    )
    parser.add_argument(
        "--nominal-model",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "models" / "ur10_normal.xml",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(r"C:\Users\asteroid\Desktop\ur10数据-2106采集\ur10数据-2106采集"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "outputs" / "results_model_overlay",
    )
    parser.add_argument("--trajectory", type=int, default=None)
    parser.add_argument("--current-cutoff-hz", type=float, default=10.0)
    parser.add_argument("--state-cutoff-hz", type=float, default=10.0)
    parser.add_argument("--savgol-window-seconds", type=float, default=0.25)
    parser.add_argument("--trim-seconds", type=float, default=0.5)
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Export MATLAB data only; do not generate PNG figures.",
    )
    return parser.parse_args()


def prepare_models(args: argparse.Namespace) -> tuple[mujoco.MjModel, mujoco.MjModel]:
    identified = mujoco.MjModel.from_xml_path(str(args.identified_model))
    core.validate_model(identified)

    nominal = mujoco.MjModel.from_xml_path(str(args.nominal_model))
    if nominal.nq != 6 or nominal.nv != 6:
        raise ValueError(
            f"Expected a 6-DOF nominal model, got nq={nominal.nq}, nv={nominal.nv}"
        )
    # Both models use the same external nonlinear friction law. Remove the
    # nominal XML's built-in passive terms in memory to avoid double counting.
    nominal.dof_damping[:] = 0.0
    nominal.dof_frictionloss[:] = 0.0
    return identified, nominal


def compute_curves(
    path: Path,
    identified: mujoco.MjModel,
    nominal: mujoco.MjModel,
    args: argparse.Namespace,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = core.load_rtde_mat(path)
    samples = core.keep_last_sample_per_timestamp(raw)
    timestamp = samples[:, 48]
    time = timestamp - timestamp[0]
    sample_rate = 1.0 / float(np.median(np.diff(time)))

    q, dq, ddq = core.reconstruct_kinematics(
        samples[:, 0:6],
        sample_rate,
        args.state_cutoff_hz,
        args.savgol_window_seconds,
    )
    measured = core.lowpass(samples[:, 12:18], sample_rate, args.current_cutoff_hz)

    trim = int(round(args.trim_seconds * sample_rate))
    if 2 * trim >= len(time):
        raise ValueError(f"Trim removes all samples from {path.name}")
    use = slice(trim, len(time) - trim if trim else None)
    time = time[use]
    time -= time[0]
    q, dq, ddq, measured = q[use], dq[use], ddq[use], measured[use]

    friction = core.nonlinear_friction(dq)
    identified_current = (
        core.inverse_dynamics(identified, q, dq, ddq) + friction
    ) / core.TORQUE_CONSTANT
    nominal_current = (
        core.inverse_dynamics(nominal, q, dq, ddq) + friction
    ) / core.TORQUE_CONSTANT
    return time, measured, identified_current, nominal_current


def plot_overlay(
    output_path: Path,
    trajectory: int,
    time: np.ndarray,
    measured: np.ndarray,
    identified: np.ndarray,
    nominal: np.ndarray,
) -> None:
    fig, axes = plt.subplots(6, 2, figsize=(16, 18), sharex="col")
    for joint in range(6):
        signal_axis, error_axis = axes[joint]
        signal_axis.plot(time, measured[:, joint], "k", linewidth=1.1, label="真机")
        signal_axis.plot(
            time,
            identified[:, joint],
            color="#377eb8",
            linewidth=0.95,
            label="标定",
        )
        signal_axis.plot(
            time,
            nominal[:, joint],
            color="#ff7f00",
            linewidth=0.9,
            label="未标定",
        )
        signal_axis.set_ylabel(f"J{joint + 1} current (A)")
        signal_axis.grid(True, alpha=0.25)

        identified_error = identified[:, joint] - measured[:, joint]
        nominal_error = nominal[:, joint] - measured[:, joint]
        error_axis.axhline(0.0, color="black", linewidth=0.7, alpha=0.5)
        error_axis.plot(
            time,
            identified_error,
            color="#377eb8",
            linewidth=0.95,
            label="标定",
        )
        error_axis.plot(
            time,
            nominal_error,
            color="#ff7f00",
            linewidth=0.9,
            label="未标定",
        )
        error_axis.set_ylabel(f"J{joint + 1} error (A)")
        error_axis.grid(True, alpha=0.25)

    axes[-1, 0].set_xlabel("Time (s)")
    axes[-1, 1].set_xlabel("Time (s)")
    axes[0, 0].legend(loc="upper right", frameon=False, ncol=3)
    axes[0, 1].legend(loc="upper right", frameon=False, ncol=2)
    fig.suptitle(
        f"第 {trajectory}条轨迹: 标定与未标定比较\n"
        "左: 真机电流、标定前、标定后; 右: 仿真与真机误差值",
        y=0.997,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(output_path, dpi=170)
    plt.close(fig)


def export_matlab_data(
    output_path: Path,
    trajectory: int,
    time: np.ndarray,
    measured: np.ndarray,
    identified: np.ndarray,
    nominal: np.ndarray,
) -> None:
    """Save plot-ready signals using MATLAB-friendly variable names."""
    savemat(
        output_path,
        {
            "trajectory": np.array([[trajectory]], dtype=np.int32),
            "time_s": time.reshape(-1, 1),
            "actual_current_A": measured,
            "identified_current_A": identified,
            "nominal_current_A": nominal,
            "identified_error_A": identified - measured,
            "nominal_error_A": nominal - measured,
            "torque_constant_Nm_per_A": core.TORQUE_CONSTANT.reshape(1, -1),
            "actual_torque_est_Nm": measured * core.TORQUE_CONSTANT,
            "identified_torque_Nm": identified * core.TORQUE_CONSTANT,
            "nominal_torque_Nm": nominal * core.TORQUE_CONSTANT,
        },
        do_compression=True,
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    identified, nominal = prepare_models(args)

    if args.trajectory is None:
        files = sorted(args.data_dir.glob("ur_rtde_newtraj_2021_*_data_noload.mat"))
    else:
        files = [
            args.data_dir / f"ur_rtde_newtraj_2021_{args.trajectory}_data_noload.mat"
        ]
    if not files or any(not path.exists() for path in files):
        raise FileNotFoundError(f"No matching data files found in {args.data_dir}")

    for path in files:
        trajectory = int(path.stem.split("_")[4])
        print(f"Processing trajectory {trajectory}: {path.name}")
        curves = compute_curves(path, identified, nominal, args)
        mat_path = args.output_dir / f"trajectory_{trajectory}_model_comparison.mat"
        export_matlab_data(mat_path, trajectory, *curves)
        print(f"Saved MATLAB data: {mat_path}")
        if not args.no_plot:
            output_path = args.output_dir / f"trajectory_{trajectory}_model_overlay.png"
            plot_overlay(output_path, trajectory, *curves)
            print(f"Saved figure: {output_path}")


if __name__ == "__main__":
    main()
