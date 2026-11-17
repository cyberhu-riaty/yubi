"""运行内核自检：线程安全队列、就绪信号和可控退出。"""
from __future__ import annotations

import os
from pathlib import Path
import queue
import sys
import threading
import types


ROOT = Path(__file__).resolve().parents[2]
SOFTWARE = ROOT / "软件"
if str(SOFTWARE) not in sys.path:
    sys.path.insert(0, str(SOFTWARE))

# 自检不占 Web 端口，也不创建窗口。
os.environ["YUBI_DISABLE_WEB"] = "1"

import console_support as console  # noqa: E402

console.prepare_output()

import runtime_engine as runtime  # noqa: E402
import plugin_system as plugins  # noqa: E402
import command_bridge  # noqa: E402
import simulation_control  # noqa: E402
import control_bridge  # noqa: E402


def check_queue() -> None:
    pending = runtime.command_queue()
    assert isinstance(pending, queue.Queue), "本地命令通道必须使用线程安全 Queue"
    runtime.drain_local_queue()

    def producer(number: int) -> None:
        for index in range(200):
            pending.put_nowait((number, index))

    threads = [threading.Thread(target=producer, args=(number,)) for number in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    result = runtime.drain_local_queue()
    assert len(result) == 800, f"并发入队后应收到 800 条，实际 {len(result)}"
    assert len(set(result)) == 800, "队列中出现重复或丢失"

    ok, reason = command_bridge.enqueue_command(
        pending, "command.gravity", {"gravity_enabled": False}, print_result=False)
    assert ok, reason
    ok, reason = command_bridge.enqueue_command(
        pending, "command.simulation", {"action": "pause"}, print_result=False)
    assert ok, reason
    assert len(runtime.drain_local_queue()) == 2, "Web 命令没有进入线程安全队列"


def check_simulation_control() -> None:
    reset_calls: list[str] = []
    state_calls: list[str] = []
    applier = simulation_control.GravityApplier(
        simulation_reset=lambda: (reset_calls.append("reset") or "已重建算法"),
        state_callback=lambda: state_calls.append("state"),
    )
    # 单元检查不需要真的向官方 StepControl 发快照；这里只验证三种动作的状态语义。
    applier._send_official_pause = lambda paused: None              # noqa: SLF001

    applier.on_simulation_command(
        simulation_control.SimulationControlCommand(action="run"))
    assert applier.running, "Run 应打开步进闸门"
    assert applier.gravity_enabled, "Run 不应改写重力设置"
    assert not reset_calls, "Run 不应触发复位"

    applier.on_gravity_state(simulation_control.GravityState(gravity_enabled=False))
    assert applier.running, "关闭重力不应顺带暂停仿真"
    assert not applier.gravity_enabled, "重力命令没有独立生效"

    applier.on_simulation_command(
        simulation_control.SimulationControlCommand(action="pause"))
    assert not applier.running, "Pause 应关闭步进闸门"
    assert not applier.gravity_enabled, "Pause 不应改写重力设置"
    assert not reset_calls, "Pause 必须保持当前位置，不能偷偷复位"

    applier.on_simulation_command(
        simulation_control.SimulationControlCommand(action="reset"))
    assert not applier.running, "Reset 后应保持暂停"
    assert reset_calls == ["reset"], "Reset 应且只应重建当前算法一次"
    assert applier.reset_count == 1, "Reset 次数没有记账"
    assert len(state_calls) == 4, "运行控制与重力修改都应主动回报真实状态"

    published = []
    publisher = simulation_control.SimulationStatePublisher(published.append)
    assert publisher.publish(applier, 0.0, force=True)
    assert (published[-1].state == "paused"
            and not published[-1].gravity_enabled
            and published[-1].simulation_time == 0.0)


def check_control_target() -> None:
    forwarded: list = []
    applier = control_bridge.ControlTargetApplier(lambda target: forwarded.append(target.copy()))
    model = types.SimpleNamespace(nq=2)
    data = types.SimpleNamespace(qpos=__import__("numpy").array([0.1, -0.2]))
    applier.receive_model(types.SimpleNamespace(model=model, data=data))
    applier.receive_target(control_bridge.ControlTargetCommand(target=[0.3, -0.4]))
    assert len(forwarded) == 2, "模型初始化与手动目标都应转发"
    assert applier.source == "手动输入"
    assert applier.target.tolist() == [0.3, -0.4]

    applier.receive_target(control_bridge.ControlTargetCommand(target=[1.0]))
    assert applier.target.tolist() == [0.3, -0.4], "维度错误的目标不应覆盖已接受目标"


def check_lifecycle() -> None:
    model_path = ROOT / "模型" / "空场景.xml"
    assert model_path.is_file(), f"缺少自检模型：{model_path}"

    # 模型加载会正常地记住“上次模型”。自检不能改变用户下一次启动时的选择，
    # 所以完整保存并恢复这个本地设置文件。
    settings_path = ROOT / "输出" / "设置.json"
    original_settings = settings_path.read_bytes() if settings_path.exists() else None

    try:
        registry = plugins.SafeRegistry([])
        config = plugins.viewer_protocol.ViewerConfig(
            title="运行内核自检", width=640, height=480, gfx="")
        code = runtime.start(
            config, str(model_path), None, [], registry,
            plugins.notify_model_loaded, project_name="", headless=True,
            background_thread=True)
        assert code == 0, f"后台仿真启动返回 {code}"

        ok, reason = runtime.wait_until_ready(10.0)
        assert ok, reason
        ok, reason = runtime.stop(3.0)
        assert ok, reason
    finally:
        runtime.stop(3.0)
        if original_settings is None:
            settings_path.unlink(missing_ok=True)
        else:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_bytes(original_settings)


def main() -> int:
    check_queue()
    print("[PASS] 线程安全命令队列")
    check_simulation_control()
    print("[PASS] Run / Pause / Reset 语义")
    check_control_target()
    print("[PASS] 关节控制目标通道")
    check_lifecycle()
    print("[PASS] 仿真就绪信号与可控退出")
    print("运行内核自检：4 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
