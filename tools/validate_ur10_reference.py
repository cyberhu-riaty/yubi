"""Recompute the supplied UR10 reference trajectories and retain a dated run.

Inputs are already filtered reference MAT files, not raw RTDE recordings.
Outputs distinguish independently recomputed model predictions from copied
measurement/reference data. No model settings are changed to force agreement.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mujoco
import numpy as np
import scipy
from scipy.io import loadmat, savemat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ur10"))
from friction.files import load_friction  # noqa: E402


def file_record(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_comparison(data, trajectory, kind, path):
    is_torque = kind == "torque"
    unit = "Nm" if is_torque else "A"
    measured = data["actual_torque_est_Nm" if is_torque else "actual_current_A"]
    first = data[f"identified_{kind}_friction_off_{unit}"]
    second = data[f"identified_{kind}_nonlinear_friction_{unit}"]
    times = data["time_s"].ravel()
    fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True)
    fig.suptitle(f"Trajectory {trajectory}: {kind} comparison", fontsize=14)
    for joint, ax in enumerate(axes.flat):
        ax.plot(times, measured[:, joint], color="black", lw=1, label="measured")
        ax.plot(times, first[:, joint], color="#2986d9", lw=.9, label="identified model, friction off")
        ax.plot(times, second[:, joint], color="red", lw=.9, label="identified model + nonlinear friction")
        if is_torque:
            ax.plot(times, data["target_moment_Nm"][:, joint], color="#59bd59", lw=.7, label="UR target moment")
        ax.set_title(f"Joint {joint + 1}", fontsize=12)
        ax.set_ylabel("Torque (N m)" if is_torque else "Current (A)")
        ax.grid(alpha=.35)
        if joint >= 4:
            ax.set_xlabel("Time (s)")
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .95), ncol=len(labels), frameon=False)
    fig.subplots_adjust(top=.85, bottom=.065, left=.06, right=.99, hspace=.2, wspace=.13)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dir", type=Path, required=True,
                        help="Directory containing results/trajectory_N_identified_results.mat")
    parser.add_argument("--output-root", type=Path, default=ROOT / "输出/UR10复现结果")
    parser.add_argument("--model", type=Path, default=ROOT / "ur10/models/ur10_extfric.xml")
    parser.add_argument("--friction-model", type=Path, default=ROOT / "ur10/configs/power_friction.json")
    parser.add_argument("--friction-parameters", type=Path, default=ROOT / "ur10/configs/ur10_identified_friction.json")
    parser.add_argument("--trajectory", type=int, action="append")
    args = parser.parse_args()
    inputs = sorted((args.reference_dir / "results").glob("trajectory_*_identified_results.mat"))
    if args.trajectory is not None:
        inputs = [p for p in inputs if int(p.stem.split("_")[1]) in args.trajectory]
    if not inputs:
        raise FileNotFoundError("No reference identified_results MAT files found")
    law = load_friction(args.friction_model, args.friction_parameters)
    model = mujoco.MjModel.from_xml_path(str(args.model.resolve()))
    if model.nq != 6 or model.nv != 6 or not np.array_equal(law.validate_model(model), np.arange(6)):
        raise ValueError("Expected the same six hinge joint columns as the reference")
    output = args.output_root / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    directories = {name: output / name for name in ("python图像", "MAT数据", "CSV数据", "参考快照", "配置快照")}
    for path in directories.values():
        path.mkdir()
    for path in (args.model, args.friction_model, args.friction_parameters):
        shutil.copy2(path, directories["配置快照"] / path.name)
    metadata = args.reference_dir / "results/experiment_metadata.json"
    if metadata.is_file():
        shutil.copy2(metadata, directories["参考快照"] / metadata.name)
    comparisons, metrics, summaries, input_records, image_records = [], [], [], [], []
    fields = {
        "friction_torque_Nm": 1e-12,
        "identified_torque_friction_off_Nm": 1e-5,
        "identified_torque_nonlinear_friction_Nm": 1e-5,
        "identified_current_friction_off_A": 1e-6,
        "identified_current_nonlinear_friction_A": 1e-6,
        "identified_torque_error_Nm": 1e-5,
        "identified_current_error_A": 1e-6,
    }
    for source in inputs:
        trajectory = int(source.stem.split("_")[1])
        reference = {k: v for k, v in loadmat(source).items() if not k.startswith("_")}
        times = reference["time_s"].ravel()
        q, dq, ddq = (reference[k] for k in ("q_actual_rad", "dq_actual_rad_s", "ddq_actual_rad_s2"))
        if (q.shape != (len(times), 6) or dq.shape != q.shape or ddq.shape != q.shape
                or not all(np.isfinite(x).all() for x in (q, dq, ddq, times))
                or not np.all(np.diff(times) > 0)):
            raise ValueError(f"Invalid processed kinematics in {source}")
        kt = reference["torque_constant_Nm_per_A"].reshape(6)
        if not np.isfinite(kt).all() or np.any(kt == 0):
            raise ValueError(f"Invalid torque constants in {source}")
        rigid = np.empty_like(q)
        contacts = []
        data = mujoco.MjData(model)
        for index in range(len(times)):
            data.qpos[:] = q[index]
            data.qvel[:] = dq[index]
            data.qacc[:] = ddq[index]
            mujoco.mj_inverse(model, data)
            rigid[index] = data.qfrc_inverse
            contacts.append(int(data.ncon))
        friction = law.torque(dq)
        total = rigid + friction
        result = dict(reference)
        result.update({
            "friction_torque_Nm": friction,
            "identified_torque_friction_off_Nm": rigid,
            "identified_torque_nonlinear_friction_Nm": total,
            "identified_current_friction_off_A": rigid / kt,
            "identified_current_nonlinear_friction_A": total / kt,
            "identified_torque_error_Nm": total - reference["actual_torque_est_Nm"],
            "identified_current_error_A": total / kt - reference["actual_current_A"],
            "recomputed_contact_count": np.asarray(contacts).reshape(-1, 1),
        })
        savemat(directories["MAT数据"] / source.name, result, do_compression=True)
        shutil.copy2(source, directories["参考快照"] / source.name)
        input_records.append(file_record(source))
        all_pass = True
        for field, tolerance in fields.items():
            delta = result[field] - reference[field]
            for joint in range(6):
                error = delta[:, joint]
                worst = int(np.argmax(np.abs(error)))
                passed = bool(np.max(np.abs(error)) <= tolerance)
                all_pass = all_pass and passed
                comparisons.append({"trajectory": trajectory, "field": field, "joint": joint + 1,
                    "max_abs_difference": float(np.max(np.abs(error))),
                    "rmse_difference": float(np.sqrt(np.mean(error ** 2))),
                    "worst_time_s": float(times[worst]), "contacts_at_worst": contacts[worst],
                    "absolute_tolerance": tolerance, "passed": passed})
        for kind, actual_field, unit in (("torque", "actual_torque_est_Nm", "Nm"), ("current", "actual_current_A", "A")):
            for variant in ("friction_off", "nonlinear_friction"):
                field = f"identified_{kind}_{variant}_{unit}"
                for joint in range(6):
                    error = result[field][:, joint] - reference[actual_field][:, joint]
                    old_error = reference[field][:, joint] - reference[actual_field][:, joint]
                    metrics.append({"trajectory": trajectory, "domain": kind, "variant": variant, "joint": joint + 1,
                        "rmse": float(np.sqrt(np.mean(error ** 2))), "mae": float(np.mean(np.abs(error))),
                        "bias": float(np.mean(error)), "max_abs_error": float(np.max(np.abs(error))),
                        "reference_rmse": float(np.sqrt(np.mean(old_error ** 2)))})
            image_path = directories["python图像"] / f"trajectory_{trajectory}_{kind}.png"
            plot_comparison(result, trajectory, kind, image_path)
            ref_image = args.reference_dir / "results/python图像" / image_path.name
            if ref_image.is_file():
                ref_images = directories["参考快照"] / "python图像"
                ref_images.mkdir(exist_ok=True)
                shutil.copy2(ref_image, ref_images / ref_image.name)
                image_records.append(file_record(ref_image))
        csv_fields = ("q_actual_rad", "dq_actual_rad_s", "ddq_actual_rad_s2", "actual_current_A",
                      "actual_torque_est_Nm", "target_moment_Nm", *fields)
        rows = []
        for index, elapsed in enumerate(times):
            row = {"time_s": float(elapsed), "contact_count": contacts[index]}
            for field in csv_fields:
                for joint in range(6):
                    row[f"{field}_J{joint + 1}"] = float(result[field][index, joint])
            rows.append(row)
        write_csv(directories["CSV数据"] / f"trajectory_{trajectory}.csv", rows)
        max_difference = float(np.max(np.abs(total - reference["identified_torque_nonlinear_friction_Nm"])))
        summaries.append({"trajectory": trajectory, "samples": len(times), "duration_s": float(times[-1]),
                          "passed": all_pass, "max_torque_difference_Nm": max_difference,
                          "samples_with_contacts": sum(n > 0 for n in contacts)})
        print(f"Trajectory {trajectory}: {'PASS' if all_pass else 'DIFF'}; max torque difference {max_difference:.9g} N m")
    write_csv(output / "逐点数值对比.csv", comparisons)
    write_csv(output / "误差指标.csv", metrics)
    manifest = {
        "created_at": datetime.now().astimezone().isoformat(), "mode": "recompute_inverse_dynamics_from_processed_reference",
        "input_stage": "already filtered q/dq/ddq and measured current; not raw RTDE reprocessing",
        "torque_source": "mj_inverse qfrc_inverse; same model contact/constraint settings retained",
        "model": file_record(args.model), "friction_model": file_record(args.friction_model),
        "friction_parameters": file_record(args.friction_parameters), "inputs": input_records,
        "reference_images": image_records, "absolute_tolerances": fields,
        "versions": {"python": sys.version.split()[0], "mujoco": mujoco.__version__, "numpy": np.__version__,
                     "scipy": scipy.__version__, "matplotlib": matplotlib.__version__},
        "summary": summaries,
    }
    (output / "运行配置与校验.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# UR10 参考图重算结果", "", "本目录保存当前模型独立重算的结果，包含有差异的轨迹，未调整模型强行对齐。",
             "输入是参考结果 MAT 内已经滤波的 q/dq/ddq、电流与目标力矩；本次未重做原始 RTDE 去重和滤波。",
             "", "- python图像：本次重算的同名力矩图/电流图（2380×1700，170 dpi）。",
             "- MAT数据 / CSV数据：本次完整数值；实际电流、目标力矩与输入运动学来自参考数据。",
             "- 参考快照：参考 MAT、PNG 与元信息，便于直接核对。",
             "- 逐点数值对比.csv：对每条轨迹、每种量、每个关节计算全部采样点差异，并记录最大差异时刻。",
             "- 误差指标.csv：当前模型对测量值的 RMSE、MAE、Bias 与参考 RMSE。",
             "- 运行配置与校验.json：输入哈希、模型、参数、软件版本、容差和汇总。", "",
             "判断采用明确的数值容差，不保证 PNG 的字体、布局或像素完全相同；图片不是验收数据源。",
             "这是离线逆动力学复现检查，尚未作为数据模式接入实时软件界面。", "",
             "| 轨迹编号 | 采样点 | 最大力矩差异 N·m | 有接触的采样点 | 数值检查 |", "|---|---:|---:|---:|---|"]
    for row in summaries:
        lines.append(f"| {row['trajectory']} | {row['samples']} | {row['max_torque_difference_Nm']:.9g} | {row['samples_with_contacts']} | {'通过' if row['passed'] else '有差异'} |")
    lines.extend(["", "轨迹中的接触参与了约束力计算。接触出现与差异相关不等于已经定位全部原因；本次保留模型原有设置。",
                  "模型 XML 的快照需要原工程中的网格资源才能独立加载。"])
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.output_root / "最近一次运行.json").write_text(
        json.dumps({"directory": str(output.resolve()), "passed": sum(s["passed"] for s in summaries),
                    "trajectories": len(summaries)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Results: {output.resolve()}")


if __name__ == "__main__":
    main()
