"""按轨迹编号使用原始target状态计算无摩擦UR10逆动力学总力矩。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mujoco
from scipy.io import savemat

import ur10_inverse_dynamics_experiment as core


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trajectory",
        type=int,
        choices=range(10),
        default=0,
        help="轨迹编号0～9，默认使用轨迹0。",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "models" / "ur10_extfric.xml",
        help="标定刚体参数且XML内部damping/frictionloss为零的模型。",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(
            r"C:\Users\asteroid\Desktop\ur10数据-2106采集\ur10数据-2106采集"
        ),
        help="包含10条真机原始轨迹MAT文件的文件夹。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "outputs" / "results_target_inverse_dynamics",
        help="按轨迹编号分别保存结果，已有同编号结果会被更新。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    data_file = (
        args.data_dir
        / f"ur_rtde_newtraj_2021_{args.trajectory}_data_noload.mat"
    )
    if not data_file.exists():
        raise FileNotFoundError(f"找不到轨迹{args.trajectory}数据：{data_file}")

    model = mujoco.MjModel.from_xml_path(str(args.model))
    core.validate_model(model)

    # 直接读取原始49列数据，不滤波、不去重、不截首尾。
    samples = core.load_rtde_mat(data_file)
    if samples.shape[1] != 49:
        raise ValueError(f"原始数据应为49列，实际为{samples.shape}")

    target_q = samples[:, 18:24]
    target_dq = samples[:, 24:30]
    target_ddq = samples[:, 30:36]

    # MuJoCo无摩擦逆动力学总力矩：tau=M(q)qdd+c(q,qd)。
    total_torque = core.inverse_dynamics(model, target_q, target_dq, target_ddq)

    output_path = args.output_dir / (
        f"trajectory_{args.trajectory}_target_inverse_torque.mat"
    )
    savemat(
        output_path,
        {"mujoco_inverse_torque_Nm": total_torque},
        do_compression=True,
    )

    # 每条轨迹使用独立说明文件，避免切换轨迹后混淆计算条件。
    metadata = {
        "purpose": "原始target状态的无摩擦MuJoCo逆动力学总力矩计算",
        "trajectory": args.trajectory,
        "model": str(args.model.resolve()),
        "data_file": str(data_file.resolve()),
        "sample_count": int(len(samples)),
        "input_columns_one_based": {
            "target_q": "19-24",
            "target_dq": "25-30",
            "target_ddq": "31-36",
        },
        "preprocessing": {
            "filtering": False,
            "timestamp_deduplication": False,
            "endpoint_trimming": False,
            "numerical_differentiation": False,
        },
        "friction": {
            "xml_damping": model.dof_damping.tolist(),
            "xml_frictionloss": model.dof_frictionloss.tolist(),
            "external_friction_added": False,
        },
        "mat_output": {
            "variable": "mujoco_inverse_torque_Nm",
            "shape": [int(len(samples)), 6],
            "unit": "N*m",
            "columns": "joint1 to joint6",
            "meaning": "MuJoCo无摩擦总逆动力学力矩",
        },
    }
    metadata_path = args.output_dir / (
        f"trajectory_{args.trajectory}_target_inverse_torque_metadata.json"
    )
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"轨迹编号：{args.trajectory}")
    print(f"样本数：{len(samples)}")
    print(f"MAT结果：{output_path}")
    print(f"计算说明：{metadata_path}")


if __name__ == "__main__":
    main()
