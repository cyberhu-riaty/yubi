#!/usr/bin/env python3
"""Panda抓取自检.py —— 23 秒 headless 抓取闭环（脚本化状态机）。

检查：
  ① 模型/站点/传感器齐全，插件预检通过；
  ② 方块被抬起（最高点 > 10 cm）；
  ③ 最终 box-target < 15 mm（官方任务的搬运成功阈值）；
  ④ 没有异常。

用法：
    .venv/bin/python 工具/验证/Panda抓取自检.py
退出码：0 通过；1 失败。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import mujoco

包根 = Path(__file__).resolve().parents[2]
if str(包根 / "软件") not in sys.path:
    sys.path.insert(0, str(包根 / "软件"))

from official_api import messages                                            # noqa: E402

模型路径 = 包根 / "模型" / "panda_mjpc" / "task.xml"
插件路径 = 包根 / "算法库" / "通用" / "panda_pick_place.py"


def 加载插件():
    spec = importlib.util.spec_from_file_location("Panda_抓取演示", 插件路径)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载抓取插件")
    模块 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(模块)
    return 模块.PandaPickPlaceController


def main() -> int:
    模型 = mujoco.MjModel.from_xml_path(str(模型路径))
    数据 = mujoco.MjData(模型)
    键 = mujoco.mj_name2id(模型, mujoco.mjtObj.mjOBJ_KEY, "home")
    if 键 >= 0:
        mujoco.mj_resetDataKeyframe(模型, 数据, 键)
    mujoco.mj_forward(模型, 数据)

    插件 = 加载插件()()
    兼容 = 插件.check_model_compatibility(模型)
    if 兼容:
        print(f"  ✗ 插件预检失败：{兼容}")
        return 1
    事件 = messages.StepEvent(model=模型, data=数据)
    最高 = float(数据.sensor("box").data[2])
    步数 = int(23.0 / max(模型.opt.timestep, 1e-9))
    for _ in range(步数):
        插件.step(事件)
        mujoco.mj_step(模型, 数据)
        最高 = max(最高, float(数据.sensor("box").data[2]))

    指标 = 插件.metrics()
    状态 = 插件.status()
    box目标 = float(指标.get("box-target(mm)", 9999.0))
    print(f"  模型 nq/nv/nu = {模型.nq}/{模型.nv}/{模型.nu}")
    print(f"  最高 box-z = {最高 * 1000:.1f} mm（起点 20 mm）")
    print(f"  最终 box-target = {box目标:.1f} mm；成功 = {指标.get('成功')}")
    print(f"  状态：{状态}")
    通过 = 最高 > 0.10 and box目标 < 15.0 and float(指标.get("成功", 0)) == 1.0
    print("  结果：" + ("✓ 抓取闭环通过" if 通过 else "✗ 抓取闭环未通过"))
    return 0 if 通过 else 1


if __name__ == "__main__":
    raise SystemExit(main())
