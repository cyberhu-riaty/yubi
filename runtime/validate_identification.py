"""
验证参数辨识.py —— 一键跑"已知真值"的闭环验证（D3 验收）

它做什么：
    ① 造一个"真机"（把 UR5e 的几个连杆质量改成指定值）
    ② 在它上面做闭环激励、采数据
    ③ 从**故意给错的初值**出发做辨识
    ④ 打印"估计值 vs 真值"的对比表，看能不能找回来

用法：
    cd "$HOME/Desktop/驭臂"
    .venv/bin/python runtime/validate_identification.py

实测结果（本机）：
    3 个连杆质量：从 1.0/5.0/0.8 的错初值 → 收敛到真值 2.5/10.0/1.5，误差 1~3%，耗时约 1 秒。
    质心位置（com_x/com_y）：**不可辨识** —— 这段轨迹对它们不敏感，估计值基本不动。
      （这是真实结论，不是 bug：要辨识质心需要更丰富的激励或不同构型的多组数据。）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parameter_identification import ParameterDefinition, identify, collect_data  # noqa: E402

# 默认模型：按"候选路径"依次找，找到第一个存在的。
# 为什么要这样：这个外壳会被整体复制到别处（比如打包成资料包），目录层级会变，
# 写死一条相对路径换个位置就跑不起来（实测踩过）。
model_filename = "ur5e_torque.xml"
_here = os.path.dirname(os.path.abspath(__file__))
candidate_models = [
    # ① 原工程结构：studio_shell → 03_实施 → 调研成果 → 数字样机 → 教程/…
    os.path.normpath(os.path.join(_here, "..", "..", "..", "教程", "MuJoCo教程",
                                  "03_模型库", "menagerie", "universal_robots_ur5e", model_filename)),
    # ② 打包后的资料包结构：03_实施与验收/studio_shell → 05_模型资产/ur5e
    os.path.normpath(os.path.join(_here, "..", "..", "05_模型资产", "ur5e", model_filename)),
    # ③ 资料包里的完整模型库
    os.path.normpath(os.path.join(_here, "..", "..", "03_模型库", "menagerie",
                                  "universal_robots_ur5e", model_filename)),
    # ④ 当前包结构：<包根>/runtime → <包根>/模型/universal_robots_ur5e
    os.path.normpath(os.path.join(_here, "..", "模型", "universal_robots_ur5e", model_filename)),
    # ⑤ 模型就放在脚本旁边
    os.path.normpath(os.path.join(_here, model_filename)),
]
model = next((p for p in candidate_models if os.path.exists(p)), candidate_models[0])

# 待辨识参数：名称 / 目标(body, 字段) / 初值 / 界 / 真值
parameter_specifications = [
    ("forearm_mass",  ("forearm_link",   "mass"), 1.0, (0.3, 6.0),  2.5),
    ("upperarm_mass", ("upper_arm_link", "mass"), 5.0, (1.0, 20.0), 10.0),
    ("wrist_mass",    ("wrist_1_link",   "mass"), 0.8, (0.2, 4.0),  1.5),
]


def main() -> int:
    print("=" * 74)
    print("参数辨识闭环验证（D3）")
    print("=" * 74)
    print(f'  模型：{os.path.basename(model)}')
    print(f'  待辨识：{len(parameter_specifications)} 个连杆质量')
    print()

    print("① 造真机并做闭环激励（PD 跟踪平滑轨迹，记录 q/v/τ）")
    overrides = {}
    for name, (body_name, field_name), initial, bounds, reference in parameter_specifications:
        if field_name == "mass":
            overrides[body_name] = reference
    data = collect_data(model, duration=2.0, mass_overrides=overrides, note="D3 闭环验证")
    deviation = 0.0
    print(f'   采到 {data.step_count} 步；控制量峰值 {abs(data.ctrl).max():.1f} N·m')
    print()

    print("② 辨识（初值全部给错）")
    parameter_definitions = [ParameterDefinition(name, target, initial, bounds[0], bounds[1], reference=reference)
              for name, target, initial, bounds, reference in parameter_specifications]
    result = identify(data, parameter_definitions, stride=5)
    print()

    print("③ 结果")
    print(result.comparison_table())
    error = [lines[4] for lines in result.rows() if lines[4] is not None]
    print()
    print(f'   耗时 {result.elapsed_time:.1f}s，模型前向 {result.rollout_count} 次，'
          f'残差 {result.residual_history[0]:.3e} → {result.residual_history[-1]:.3e}')
    print(f'   最大相对误差 {max(error):.2f}%')
    print(f"   [结论] {('✅ 辨识成功（<5%）' if max(error) < 5 else '⚠ 有参数未收敛')}")
    print()
    print("   备注：本例只辨识连杆质量。实测**质心位置在这段轨迹上不可辨识**")
    print("         （估计值基本不动），要辨识它需要更丰富的激励或多组不同构型的数据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
