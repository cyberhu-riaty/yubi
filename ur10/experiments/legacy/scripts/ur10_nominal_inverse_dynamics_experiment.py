from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

import mujoco
import numpy as np
from scipy.io import savemat

import ur10_inverse_dynamics_experiment as core


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "models" / "ur10_normal.xml",
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
        default=Path(__file__).resolve().parent.parent / "outputs" / "results_nominal",
    )
    parser.add_argument("--trajectory", type=int, default=None)
    parser.add_argument("--current-cutoff-hz", type=float, default=10.0)
    parser.add_argument("--state-cutoff-hz", type=float, default=10.0)
    parser.add_argument("--savgol-window-seconds", type=float, default=0.25)
    parser.add_argument("--trim-seconds", type=float, default=0.5)
    parser.add_argument(
        "--identified-summary",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "outputs" / "results" / "metrics_summary.csv",
        help="Existing identified-model summary used to produce a cross-model comparison.",
    )
    return parser.parse_args()


def analyze_file(
    path: Path,
    trajectory: int,
    model: mujoco.MjModel,
    args: argparse.Namespace,
) -> tuple[list[dict[str, object]], core.DatasetInfo]:
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
    actual_current = core.lowpass(
        samples[:, 12:18], sample_rate, args.current_cutoff_hz
    )
    target_moment = samples[:, 42:48]

    trim = int(round(args.trim_seconds * sample_rate))
    if 2 * trim >= len(time):
        raise ValueError(f"Trim removes all samples from {path.name}")
    use = slice(trim, len(time) - trim if trim else None)
    time = time[use]
    time -= time[0]
    q, dq, ddq = q[use], dq[use], ddq[use]
    actual_current = actual_current[use]
    target_moment = target_moment[use]

    torque_without_friction = core.inverse_dynamics(model, q, dq, ddq)
    torque_with_friction = torque_without_friction + core.nonlinear_friction(dq)
    measured_torque = actual_current * core.TORQUE_CONSTANT
    current_without_friction = torque_without_friction / core.TORQUE_CONSTANT
    current_with_friction = torque_with_friction / core.TORQUE_CONSTANT

    rows: list[dict[str, object]] = []
    for domain, measured, prediction_off, prediction_on in (
        (
            "torque_Nm",
            measured_torque,
            torque_without_friction,
            torque_with_friction,
        ),
        (
            "current_A",
            actual_current,
            current_without_friction,
            current_with_friction,
        ),
    ):
        rows.extend(
            core.metric_rows(
                trajectory,
                domain,
                "nominal_friction_off",
                prediction_off,
                measured,
            )
        )
        rows.extend(
            core.metric_rows(
                trajectory,
                domain,
                "nominal_nonlinear_friction",
                prediction_on,
                measured,
            )
        )

    friction = core.nonlinear_friction(dq)
    output_path = args.output_dir / f"trajectory_{trajectory}_nominal_results.mat"
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
            "nominal_torque_friction_off_Nm": torque_without_friction,
            "nominal_torque_nonlinear_friction_Nm": torque_with_friction,
            "nominal_current_friction_off_A": current_without_friction,
            "nominal_current_nonlinear_friction_A": current_with_friction,
            "nominal_torque_error_Nm": torque_with_friction - measured_torque,
            "nominal_current_error_A": current_with_friction - actual_current,
            "torque_constant_Nm_per_A": core.TORQUE_CONSTANT.reshape(1, -1),
        },
        do_compression=True,
    )
    print(f"Saved calculated data: {output_path}")

    info = core.DatasetInfo(
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_cross_model_comparison(
    output_path: Path,
    nominal_summary: list[dict[str, object]],
    identified_summary_path: Path,
) -> None:
    if not identified_summary_path.exists():
        return
    identified = read_csv(identified_summary_path)
    identified_index = {
        (row["domain"], row["variant"], int(row["joint"])): row
        for row in identified
    }
    comparison = []
    for nominal in nominal_summary:
        nominal_variant = str(nominal["variant"])
        if nominal_variant == "nominal_friction_off":
            identified_variant = "identified_friction_off"
        elif nominal_variant == "nominal_nonlinear_friction":
            identified_variant = "identified_nonlinear_friction"
        else:
            continue
        key = (str(nominal["domain"]), identified_variant, int(nominal["joint"]))
        if key not in identified_index:
            continue
        identified_row = identified_index[key]
        nominal_rmse = float(nominal["mean_rmse"])
        identified_rmse = float(identified_row["mean_rmse"])
        comparison.append(
            {
                "domain": nominal["domain"],
                "friction_case": (
                    "off" if nominal_variant.endswith("friction_off") else "nonlinear"
                ),
                "joint": nominal["joint"],
                "nominal_mean_rmse": nominal_rmse,
                "identified_mean_rmse": identified_rmse,
                "identified_rmse_change_percent_vs_nominal": (
                    100.0 * (identified_rmse - nominal_rmse) / nominal_rmse
                    if nominal_rmse
                    else np.nan
                ),
            }
        )
    core.write_csv(output_path, comparison)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    model = mujoco.MjModel.from_xml_path(str(args.model))
    if model.nq != 6 or model.nv != 6:
        raise ValueError(f"Expected a 6-DOF model, got nq={model.nq}, nv={model.nv}")

    xml_damping = model.dof_damping.copy()
    xml_frictionloss = model.dof_frictionloss.copy()
    xml_armature = model.dof_armature.copy()

    # Fair comparison: remove the nominal XML's empirical passive friction in
    # memory, then use exactly the same external friction law as the identified
    # model experiment. The source XML is never modified.
    model.dof_damping[:] = 0.0
    model.dof_frictionloss[:] = 0.0

    if args.trajectory is None:
        files = sorted(args.data_dir.glob("ur_rtde_newtraj_2021_*_data_noload.mat"))
    else:
        files = [
            args.data_dir
            / f"ur_rtde_newtraj_2021_{args.trajectory}_data_noload.mat"
        ]
    if not files or any(not path.exists() for path in files):
        raise FileNotFoundError(f"No matching data files found in {args.data_dir}")

    all_rows: list[dict[str, object]] = []
    dataset_info: list[core.DatasetInfo] = []
    for path in files:
        trajectory = int(path.stem.split("_")[4])
        print(f"Analyzing nominal model, trajectory {trajectory}: {path.name}")
        rows, info = analyze_file(path, trajectory, model, args)
        all_rows.extend(rows)
        dataset_info.append(info)

    detailed_path = args.output_dir / "metrics_by_trajectory.csv"
    summary_path = args.output_dir / "metrics_summary.csv"
    metadata_path = args.output_dir / "experiment_metadata.json"
    comparison_path = args.output_dir / "model_comparison.csv"

    nominal_summary = core.aggregate_metrics(all_rows)
    core.write_csv(detailed_path, all_rows)
    core.write_csv(summary_path, nominal_summary)
    write_cross_model_comparison(
        comparison_path, nominal_summary, args.identified_summary
    )

    metadata = {
        "experiment": "uncalibrated nominal UR10 inverse dynamics",
        "model": str(args.model.resolve()),
        "source_xml_was_modified": False,
        "xml_dof_armature_retained": xml_armature.tolist(),
        "xml_dof_damping_original": xml_damping.tolist(),
        "xml_dof_frictionloss_original": xml_frictionloss.tolist(),
        "runtime_dof_damping": model.dof_damping.tolist(),
        "runtime_dof_frictionloss": model.dof_frictionloss.tolist(),
        "external_nonlinear_friction_parameters": {
            "Fc": core.FRICTION_FC.tolist(),
            "Fv": core.FRICTION_FV.tolist(),
            "B": core.FRICTION_B.tolist(),
            "alpha": core.FRICTION_ALPHA.tolist(),
        },
        "torque_constant_Nm_per_A": core.TORQUE_CONSTANT.tolist(),
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
    print(f"Model comparison: {comparison_path}")
    print(f"Metadata:         {metadata_path}")


if __name__ == "__main__":
    main()
