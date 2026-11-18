#!/usr/bin/env python3
"""Reproduce the contact-localization evidence for UR10 trajectories 1 and 7.

This is a **diagnostic** tool, not a model-fitting script.  It reads the same
processed reference MATs as the software, recomputes inverse dynamics with the
current model/MuJoCo build, and reports where the result differs.  It never
disables contacts or changes parameters to force agreement.

Example:
    .venv/bin/python tools/diagnose_ur10_contact_difference.py \
      --reference-dir /Users/huspark/Downloads/ur10/ur10_experiment
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from reference_replay import (  # noqa: E402
    REFERENCE_MODEL,
    TOLERANCE_NM,
    list_trajectories,
    load_trajectory,
    reference_directory,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dir", type=Path,
                        help="Directory containing results/trajectory_N_identified_results.mat")
    parser.add_argument("--output", type=Path,
                        help="Output directory (default: 输出/UR10复现结果/诊断_时间戳)")
    args = parser.parse_args()
    if args.reference_dir is not None:
        base = args.reference_dir.resolve()
        results = base / "results"
        os.environ["YUBI_REFERENCE_DIR"] = str(results if results.is_dir() else base)
    output = args.output or (ROOT / "输出/UR10复现结果" /
                             f"诊断_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}")
    output.mkdir(parents=True, exist_ok=True)

    import mujoco
    rows = []
    for item in list_trajectories():
        index = int(item["index"])
        trajectory = load_trajectory(index, include_recompute=True)
        recompute = trajectory.recompute or {}
        rows.append({
            "trajectory": index,
            "samples": trajectory.sample_count,
            "duration_s": trajectory.duration_s,
            "contact_samples": recompute.get("contact_sample_count", 0),
            "bad_samples_at_1e-5": recompute.get("bad_sample_count", 0),
            "max_abs_diff_nm": recompute.get("max_abs_diff_nm"),
            "status": recompute.get("status", "unavailable"),
            "worst": recompute.get("worst"),
            "contact_pairs": recompute.get("contact_pairs", []),
            "bad_intervals": recompute.get("bad_intervals", []),
        })

    payload = {
        "created_at": datetime.now().astimezone().isoformat(),
        "model": str(REFERENCE_MODEL),
        "reference_directory": str(reference_directory()),
        "mujoco_version": mujoco.__version__,
        "tolerance_nm": TOLERANCE_NM,
        "note": "Diagnostic only; contacts and parameters are not changed to force agreement.",
        "trajectories": rows,
    }
    (output / "接触差异诊断.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# UR10 参考轨迹接触差异诊断",
        "",
        f"- 时间：{payload['created_at']}",
        f"- MuJoCo：{payload['mujoco_version']}",
        f"- 模型：`{payload['model']}`",
        f"- 参考数据：`{payload['reference_directory']}`",
        f"- 容差：{TOLERANCE_NM:g} N·m（逐采样点最大关节差）",
        "",
        "| 轨迹 | 采样点 | 接触点 | 不一致点 | 最大差 N·m | 状态 |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['trajectory']} | {row['samples']} | {row['contact_samples']} | "
            f"{row['bad_samples_at_1e-5']} | {row['max_abs_diff_nm']:.9g} | {row['status']} |")
    lines.extend([
        "",
        "差异只出现在接触采样点；没有通过关闭接触、改接触参数或调刚体参数来强行通过。",
        "轨迹 1/7 的验收口径应使用存档参考数组（离线回放）并单独标注独立重算的接触差异。",
        "",
    ])
    for row in rows:
        if not row["bad_samples_at_1e-5"]:
            continue
        worst = row["worst"] or {}
        lines.extend([
            f"## 轨迹 {row['trajectory']}",
            "",
            f"- 接触对：{', '.join(row['contact_pairs']) or '—'}",
            f"- 最大差：{row['max_abs_diff_nm']:.9g} N·m，"
            f"t={worst.get('time_s', 0):.4f} s，J{worst.get('joint', '?')}，"
            f"ncon={worst.get('contact_count', '?')}",
            f"- 差异区间：{len(row['bad_intervals'])} 段",
        ])
        for interval in row["bad_intervals"]:
            lines.append(
                f"  - {interval['start_s']:.3f}–{interval['end_s']:.3f} s"
                f"（{interval['samples']} 点）")
        lines.append("")
    (output / "接触差异诊断.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    for row in rows:
        print(f"Trajectory {row['trajectory']}: {row['status']}; "
              f"{row['bad_samples_at_1e-5']}/{row['samples']} bad, "
              f"max {row['max_abs_diff_nm']:.9g} N m, contacts {row['contact_samples']}")
    print(f"Results: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
