#!/usr/bin/env python3
"""Panda流程自检.py —— 用一次 headless 仿真验证 MJPC Panda 的接入链路。

它检查的是"接得对不对"，不是"抓得好不好"：
  ① 模型能加载，尺寸/传感器/手臂关节数符合预期；
  ② 资产库能列出 panda_mjpc；
  ③ 项目声明的模型和算法能对上，插件预检通过；
  ④ 插件真的会规划、写 ctrl，并在 5 s 内把手往方块方向移动；
  ⑤ 运行期间没有线程错误（规划线程的异常会记在 指标.错误次数）。

用法：
    .venv/bin/python 工具/验证/Panda流程自检.py
退出码：0 = 通过；1 = 有失败。
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import mujoco

包根 = Path(__file__).resolve().parents[2]
软件目录 = 包根 / "软件"
for 路径 in (str(软件目录),):
    if 路径 not in sys.path:
        sys.path.insert(0, 路径)

import model_loader                                                       # noqa: E402
import project_registry as _project                                       # noqa: E402
import model_bridge                                                       # noqa: E402
from official_api import messages                                            # noqa: E402

模型路径 = 包根 / "模型" / "panda_mjpc" / "task.xml"
项目名 = "Panda_MJPC"
插件路径 = 包根 / "算法库" / "通用" / "panda_mjpc_port.py"
需要传感器 = ("hand", "box", "box1", "box2", "target1", "target2")


def 手到方块(数据) -> float:
    return float((数据.sensor("hand").data - 数据.sensor("box").data).dot(
        (数据.sensor("hand").data - 数据.sensor("box").data)) ** 0.5)


def 加载插件类():
    spec = importlib.util.spec_from_file_location("Panda_官方MPC移植", 插件路径)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载插件：{插件路径}")
    模块 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(模块)
    类 = getattr(模块, "Panda官方MPC插件", None)
    if 类 is None:
        raise RuntimeError("插件文件里没有 Panda官方MPC插件")
    return 类


def main() -> int:
    失败: list[str] = []

    def 检查(条件: bool, 说明: str, 证据: str = "") -> None:
        if 条件:
            print(f"  ✓ {说明}" + (f"（{证据}）" if 证据 else ""))
        else:
            失败.append(说明 + (f" —— {证据}" if 证据 else ""))
            print(f"  ✗ {说明}" + (f" —— {证据}" if 证据 else ""))

    print("=" * 78)
    print("  Panda 流程自检")
    print("=" * 78)

    # ---- ① 模型 ----
    print("\n[1] 模型")
    模型 = model_loader.load_model(mujoco, str(模型路径))
    检查((模型.nq, 模型.nv, 模型.nu) == (16, 15, 7),
         "task.xml 尺寸 nq/nv/nu = 16/15/7",
         f"{模型.nq}/{模型.nv}/{模型.nu}")
    缺失 = [名 for 名 in 需要传感器
            if mujoco.mj_name2id(模型, mujoco.mjtObj.mjOBJ_SENSOR, 名) < 0]
    检查(not 缺失, "6 个残差传感器齐全", "缺 " + "、".join(缺失) if 缺失 else "")
    检查(model_bridge.arm_joint_count(模型) == 7, "手臂关节数 = 7",
         str(model_bridge.arm_joint_count(模型)))

    # ---- ② 资产库 ----
    print("\n[2] 资产库")
    清单 = model_bridge.asset_manifest().get("models", [])
    条目 = next((m for m in 清单 if m.get("id") == "panda_mjpc"), None)
    检查(条目 is not None, "资产库列出 panda_mjpc")
    if 条目 is not None:
        检查(条目.get("category") == "arm_task", "类别 = arm_task", str(条目.get("category")))
        检查(条目.get("controllable") is False, "可控制 = false（不是关节力矩模型）")

    # ---- ③ 项目 / 插件 ----
    print("\n[3] 项目与插件")
    数据 = _project.load_project(项目名)
    检查(数据 is not None, f"项目 {项目名}.json 存在")
    if 数据:
        声明模型 = str(数据.get("模型", "")).replace("\\", "/")
        检查(声明模型.endswith("panda_mjpc/task.xml"),
             "项目模型指向 panda_mjpc/task.xml", 声明模型)
        算法 = _project.parse_algorithms(数据)
        插件名 = [str(x.get("插件", "")) for x in 算法]
        检查("panda_mjpc_port" in 插件名, "项目声明了 MPC 插件", str(插件名))
    类 = 加载插件类()
    插件 = 类()
    兼容 = 插件.check_model_compatibility(模型)
    检查(兼容 == "", "插件模型预检通过", 兼容 or "ok")

    # ---- ④ 5 秒 headless 仿真 ----
    print("\n[4] 5 秒 headless 仿真")
    数据对象 = mujoco.MjData(模型)
    键 = mujoco.mj_name2id(模型, mujoco.mjtObj.mjOBJ_KEY, "home")
    if 键 >= 0:
        mujoco.mj_resetDataKeyframe(模型, 数据对象, 键)
    mujoco.mj_forward(模型, 数据对象)
    开始 = 手到方块(数据对象)
    事件 = messages.StepEvent(model=模型, data=数据对象)
    步数 = int(5.0 / max(模型.opt.timestep, 1e-9))
    try:
        下一时刻 = time.perf_counter()
        for _ in range(步数):
            插件.step(事件)
            mujoco.mj_step(模型, 数据对象)
            # 按真实时间推进，让 20 Hz 规划线程有机会跑（否则 5 s 仿真会在一瞬间跑完）
            下一时刻 += max(模型.opt.timestep, 1e-9)
            剩余 = 下一时刻 - time.perf_counter()
            if 剩余 > 0:
                time.sleep(剩余)
        结束 = 手到方块(数据对象)
        指标 = 插件.metrics()
        print("  指标：" + "  ".join(
            f"{键}={指标.get(键)}" for 键 in
            ("hand-box(mm)", "box-target(mm)", "cost_手", "cost_目标",
             "cost_动作", "动作范数", "动作峰值", "夹爪")))
    finally:
        插件.close()

    检查(结束 < 开始 - 0.05,
         "5 s 内手到方块至少缩短 50 mm",
         f"{开始*1000:.1f} → {结束*1000:.1f} mm")
    检查(float(指标.get("规划次数", 0)) >= 10,
         "规划线程在工作", f"规划 {指标.get('规划次数')} 次")
    检查(float(指标.get("错误次数", 0)) == 0,
         "规划线程无错误", f"错误 {指标.get('错误次数')} 次")

    print("\n" + "=" * 78)
    if 失败:
        print(f"  结果：{len(失败)} 项失败")
        for 条 in 失败:
            print(f"    ✗ {条}")
        print("=" * 78)
        return 1
    print("  结果：✓ 全部通过（能接近，不代表能抓取；抓取见报告）")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
