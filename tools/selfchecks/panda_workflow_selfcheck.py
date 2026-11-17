#!/usr/bin/env python3
"""panda_workflow_selfcheck.py —— 用一次 headless 仿真验证 MJPC Panda 的接入链路。

它检查的是"接得对不对"，不是"抓得好不好"：
  ① 模型能加载，尺寸/传感器/手臂关节数符合预期；
  ② 资产库能列出 panda_mjpc；
  ③ 项目声明的模型和算法能对上，插件预检通过；
  ④ 插件真的会规划、写 ctrl，并在 5 s 内把手往方块方向移动；
  ⑤ 运行期间没有线程错误（规划线程的异常会记在 指标.错误次数）。

用法：
    .venv/bin/python tools/selfchecks/panda_workflow_selfcheck.py
退出码：0 = 通过；1 = 有失败。
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import mujoco

ROOT = Path(__file__).resolve().parents[2]
SOFTWARE = ROOT / "软件"
for path in (str(SOFTWARE),):
    if path not in sys.path:
        sys.path.insert(0, path)

import model_loader                                                       # noqa: E402
import project_registry as _project                                       # noqa: E402
import model_bridge                                                       # noqa: E402
from official_api import messages                                            # noqa: E402

model_path = ROOT / "模型" / "panda_mjpc" / "task.xml"
project_name = "Panda_MJPC"
plugin_path = ROOT / "controllers" / "common" / "panda_mjpc_port.py"
required_sensors = ("hand", "box", "box1", "box2", "target1", "target2")


def hand_to_box(data) -> float:
    return float((data.sensor("hand").data - data.sensor("box").data).dot(
        (data.sensor("hand").data - data.sensor("box").data)) ** 0.5)


def load_plugin_class():
    spec = importlib.util.spec_from_file_location("Panda_官方MPC移植", plugin_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载插件：{plugin_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin_class = getattr(module, "PandaMPCController", None)
    if plugin_class is None:
        raise RuntimeError("插件文件里没有 Panda官方MPC插件")
    return plugin_class


def main() -> int:
    failures: list[str] = []

    def check(condition: bool, reason: str, evidence: str = "") -> None:
        if condition:
            print(f"  ✓ {reason}" + (f"（{evidence}）" if evidence else ""))
        else:
            failures.append(reason + (f" —— {evidence}" if evidence else ""))
            print(f"  ✗ {reason}" + (f" —— {evidence}" if evidence else ""))

    print("=" * 78)
    print("  Panda 流程自检")
    print("=" * 78)

    # ---- ① 模型 ----
    print("\n[1] 模型")
    model = model_loader.load_model(mujoco, str(model_path))
    check((model.nq, model.nv, model.nu) == (16, 15, 7),
         "task.xml 尺寸 nq/nv/nu = 16/15/7",
         f"{model.nq}/{model.nv}/{model.nu}")
    missing = [name for name in required_sensors
            if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, name) < 0]
    check(not missing, "6 个残差传感器齐全", "缺 " + "、".join(missing) if missing else "")
    check(model_bridge.arm_joint_count(model) == 7, "手臂关节数 = 7",
         str(model_bridge.arm_joint_count(model)))

    # ---- ② 资产库 ----
    print("\n[2] 资产库")
    inventory = model_bridge.asset_manifest().get("models", [])
    entries = next((m for m in inventory if m.get("id") == "panda_mjpc"), None)
    check(entries is not None, "资产库列出 panda_mjpc")
    if entries is not None:
        check(entries.get("category") == "arm_task", "类别 = arm_task", str(entries.get("category")))
        check(entries.get("controllable") is False, "可控制 = false（不是关节力矩模型）")

    # ---- ③ 项目 / 插件 ----
    print("\n[3] 项目与插件")
    data = _project.load_project(project_name)
    check(data is not None, f"项目 {project_name}.json 存在")
    if data:
        declared_model = str(data.get("model", data.get("模型", ""))).replace("\\", "/")
        check(declared_model.endswith("panda_mjpc/task.xml"),
             "项目模型指向 panda_mjpc/task.xml", declared_model)
        algorithm = _project.parse_algorithms(data)
        plugin_name = [str(x.get("插件", "")) for x in algorithm]
        check("panda_mjpc_port" in plugin_name, "项目声明了 MPC 插件", str(plugin_name))
    plugin_class = load_plugin_class()
    plugin = plugin_class()
    compatible = plugin.check_model_compatibility(model)
    check(compatible == "", "插件模型预检通过", compatible or "ok")

    # ---- ④ 5 秒 headless 仿真 ----
    print("\n[4] 5 秒 headless 仿真")
    model_data = mujoco.MjData(model)
    key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
    if key >= 0:
        mujoco.mj_resetDataKeyframe(model, model_data, key)
    mujoco.mj_forward(model, model_data)
    start_time = hand_to_box(model_data)
    event = messages.StepEvent(model=model, data=model_data)
    steps = int(5.0 / max(model.opt.timestep, 1e-9))
    try:
        next_tick = time.perf_counter()
        for _ in range(steps):
            plugin.step(event)
            mujoco.mj_step(model, model_data)
            # 按真实时间推进，让 20 Hz 规划线程有机会跑（否则 5 s 仿真会在一瞬间跑完）
            next_tick += max(model.opt.timestep, 1e-9)
            remaining = next_tick - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
        end_time = hand_to_box(model_data)
        metrics = plugin.metrics()
        print("  指标：" + "  ".join(
            f"{key}={metrics.get(key)}" for key in
            ("hand-box(mm)", "box-target(mm)", "cost_手", "cost_目标",
             "cost_动作", "动作范数", "动作峰值", "夹爪")))
    finally:
        plugin.close()

    check(end_time < start_time - 0.05,
         "5 s 内手到方块至少缩短 50 mm",
         f"{start_time*1000:.1f} → {end_time*1000:.1f} mm")
    check(float(metrics.get("规划次数", 0)) >= 10,
         "规划线程在工作", f"规划 {metrics.get('规划次数')} 次")
    check(float(metrics.get("错误次数", 0)) == 0,
         "规划线程无错误", f"错误 {metrics.get('错误次数')} 次")

    print("\n" + "=" * 78)
    if failures:
        print(f"  结果：{len(failures)} 项失败")
        for item in failures:
            print(f"    ✗ {item}")
        print("=" * 78)
        return 1
    print("  结果：✓ 全部通过（能接近，不代表能抓取；抓取见报告）")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
