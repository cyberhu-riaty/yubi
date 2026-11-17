#!/usr/bin/env python3
"""panda_grasp_selfcheck.py —— 23 秒 headless 抓取闭环（脚本化状态机）。

检查：
  ① 模型/站点/传感器齐全，插件预检通过；
  ② 方块被抬起（最高点 > 10 cm）；
  ③ 最终 box-target < 15 mm（官方任务的搬运成功阈值）；
  ④ 没有异常。

用法：
    .venv/bin/python tools/selfchecks/panda_grasp_selfcheck.py
退出码：0 通过；1 失败。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import mujoco

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "runtime") not in sys.path:
    sys.path.insert(0, str(ROOT / "runtime"))

from official_api import messages                                            # noqa: E402

model_path = ROOT / "模型" / "panda_mjpc" / "task.xml"
plugin_path = ROOT / "controllers" / "common" / "panda_pick_place.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location("panda_grasp_selfcheck_plugin", plugin_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载抓取插件")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PandaPickPlaceController


def main() -> int:
    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
    if key >= 0:
        mujoco.mj_resetDataKeyframe(model, data, key)
    mujoco.mj_forward(model, data)

    plugin = load_plugin()()
    compatible = plugin.check_model_compatibility(model)
    if compatible:
        print(f"  ✗ 插件预检失败：{compatible}")
        return 1
    event = messages.StepEvent(model=model, data=data)
    max_height = float(data.sensor("box").data[2])
    steps = int(23.0 / max(model.opt.timestep, 1e-9))
    for _ in range(steps):
        plugin.step(event)
        mujoco.mj_step(model, data)
        max_height = max(max_height, float(data.sensor("box").data[2]))

    metrics = plugin.metrics()
    state = plugin.status()
    box_goal = float(metrics.get("box-target(mm)", 9999.0))
    print(f"  模型 nq/nv/nu = {model.nq}/{model.nv}/{model.nu}")
    print(f"  最高 box-z = {max_height * 1000:.1f} mm（起点 20 mm）")
    print(f"  最终 box-target = {box_goal:.1f} mm；成功 = {metrics.get('成功')}")
    print(f"  状态：{state}")
    passed = max_height > 0.10 and box_goal < 15.0 and float(metrics.get("成功", 0)) == 1.0
    print("  结果：" + ("✓ 抓取闭环通过" if passed else "✗ 抓取闭环未通过"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
