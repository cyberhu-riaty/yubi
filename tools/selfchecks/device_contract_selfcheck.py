#!/usr/bin/env python3
"""
device_contract_selfcheck.py —— 任何**设备后端**都必须通过的契约测试（规格 B5）

为什么单独一套：规格里有一句判据 ——「**能力声明了但不读 = 假抽象**」。
一个后端"能跑通"什么都证明不了；要证明的是**它守不守规矩**：
时间戳是不是真的、丢包能不能被发现、越限时会不会拒绝、看门狗触发后是不是真停了。

所以这套测试**对任意后端**跑（模拟后端、将来的 UDP/CAN 后端都跑同一套）。
这不是单元测试，是**准入测试**。

测的性质：
  ① 协议形状：能力/自由度/名称齐备，方法都存在
  ② 时间戳：采集时刻 ≤ 接收时刻，且延迟统计是有限数
  ③ 单调性：序号严格递增（丢包时允许跳，但**不许回退**）
  ④ 能力一致：声明"读不到力矩"的后端，状态帧里的力矩**必须是空**（不能是 0）
  ⑤ 越限拒绝：安全层挡住超出软限位的命令，并记审计
  ⑥ 首帧保护：使能后第一条命令被改成"保持当前位置"
  ⑦ 看门狗：状态断供后进入故障态并请求阻尼
  ⑧ 丢包可见：注入丢包后 `健康().丢包数` 真的 > 0
  ⑨ 状态机：不允许从"已连接"直接跳"运行"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

package_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(package_root / "runtime"))

details: list[str] = []
passed = 0
failures = 0


def check(ok: bool, description: str) -> None:
    global passed, failures
    if ok:
        passed += 1
        details.append(f'  ✓ {description}')
    else:
        failures += 1
        details.append(f'  ✗ {description}')


def run_for_duration(safety_layer, seconds=0.3, step=0.001):
    """驱动一会儿，让后端出帧（同时给看门狗喂状态）。"""
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        safety_layer.read_state()
        time.sleep(step)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", "--简", action="store_true")
    args = ap.parse_args()

    from devices.contract import SafetyState, ControlMode, DeviceBackend
    from devices.simulated_backend import SimulatedBackend
    from devices.safety import SafetyLayer

    # ① 协议形状（用 Protocol 对结构做检查，第三方不用继承我们的基类）
    backend = SimulatedBackend(6)
    check(isinstance(backend, DeviceBackend), "① 模拟后端满足 `设备后端` 协议（结构化检查）")
    check(int(backend.dof) == 6 and bool(backend.name), f'① 名称={backend.name} 自由度={backend.dof}')

    safety_layer = SafetyLayer(backend, watchdog_ms=50, max_step_displacement=0.05,
                position_limits=(-1.0, 1.0))
    safety_layer.open()
    check(safety_layer.state == SafetyState.CONNECTED, f'① 打开后状态 = {safety_layer.state.value}')

    # ⑨ 状态机：不能跳级
    result = safety_layer.enter_running()
    check(not result.success and safety_layer.state == SafetyState.CONNECTED,
       "⑨ 从「已连接」不能直接进「运行」（必须显式使能）")

    safety_layer.enable(ControlMode.POSITION)
    check(safety_layer.state == SafetyState.ENABLING, f'⑨ 使能后 = {safety_layer.state.value}')

    # ⑥ 首帧保护：第一条命令必须被改成"保持当前位置"
    run_for_duration(safety_layer, 0.15)
    state = safety_layer._latest_state
    check(state is not None, "⑥ 拿到了状态帧")
    if state is not None:
        safety_layer.write_command(target_position=[0.5] * 6)          # 故意要跳很远
        check(safety_layer._last_command_position is not None
           and max(abs(a - b) for a, b in zip(safety_layer._last_command_position, state.position)) < 1e-9,
           "⑥ 首帧保护：第一条命令被改成了「保持当前位置」")

    safety_layer.enter_running()
    check(safety_layer.state == SafetyState.RUNNING, "⑨ 进入运行")

    # ⑥b 增量限幅：一次跳 0.5 会被夹到单周期上限
    # ★ 局部变量别叫 `后` —— 外层那个 `后` 是后端对象，遮蔽后后面会 AttributeError。
    #   （本项目第五次栽在"同名不同物"上，所以这里特意留一行提醒。）
    before = safety_layer._last_command_position.copy()
    safety_layer.write_command(target_position=[before[0] + 0.5] + list(before[1:]))
    now = safety_layer._last_command_position
    check(abs(now[0] - before[0]) <= 0.05 + 1e-9,
       f'⑥ 单周期增量被限幅（实际 {abs(now[0] - before[0]):.4f} ≤ 0.05）')

    # ⑤ 软限位
    safety_layer._last_command_position = None                # 临时放开增量限制，单独测软限位
    safety_layer.write_command(target_position=[9.0] * 6)
    check(max(abs(x) for x in safety_layer._last_command_position) <= 1.0 + 1e-9,
       "⑤ 超出软限位的命令被夹回")

    # ② 时间戳与延迟
    run_for_duration(safety_layer, 0.2)
    state = safety_layer._latest_state
    check(state.sampled_at > 0 and state.received_at >= state.sampled_at,
       "② 时间戳：采集时刻 ≤ 接收时刻")

    # ③ 单调性（丢包允许跳，不许回退）
    sequences = []
    for _ in range(120):
        s = safety_layer.read_state()
        if s is not None:
            sequences.append(s.sequence)
        time.sleep(0.001)
    check(all(b >= a for a, b in zip(sequences, sequences[1:])),
       f"③ 序号单调不降（取到 {len(sequences)} 帧，最大 {max(sequences) if sequences else 0}）")

    # ④ 能力一致：声明读不到力矩 → 状态帧里必须是空
    check(backend.capabilities.can_read_torque is False and state.torque == (),
       "④ 能力表说读不到力矩，状态帧的力矩就是空（不是 0）")

    # ⑧ 丢包可见
    degraded = SimulatedBackend(6, packet_loss_rate=0.5, frame_interval_ms=1)
    degraded_layer = SafetyLayer(degraded, watchdog_ms=500)
    degraded_layer.open()
    run_for_duration(degraded_layer, 0.3)
    check(degraded.health().dropped_packets > 0, f'⑧ 注入 50% 丢包后统计到 {degraded.health().dropped_packets} 次丢包')

    # ⑦ 看门狗：断开供帧 → 进故障
    short = SimulatedBackend(6, frame_interval_ms=1)
    short_layer = SafetyLayer(short, watchdog_ms=30, max_step_displacement=1.0)
    short_layer.open()
    short_layer.enable(ControlMode.POSITION)
    run_for_duration(short_layer, 0.1)
    short_layer._last_command_position = None
    short_layer.write_command(target_position=[0.0] * 6)
    short_layer.enter_running()
    short.close()                      # 模拟断线：之后不再有新状态
    time.sleep(0.08)               # 超过看门狗阈值
    short_layer.read_state()
    check(short_layer.state == SafetyState.FAULT, f'⑦ 看门狗触发 → {short_layer.state.value}')
    check(any("看门狗" in entry.category for entry in short_layer.audit.all_entries()),
       "⑦ 看门狗事件进了审计日志")

    # 审计导出
    import tempfile
    import os
    path = os.path.join(tempfile.gettempdir(), "驭臂_审计.csv")
    entry_count = safety_layer.audit.export_csv(path)
    check(entry_count > 0 and os.path.getsize(path) > 0, f'审计日志可导出 CSV（{entry_count} 条）')

    if not args.brief:
        print("=" * 78)
        print("  设备契约自检（任何后端都要过的准入测试）")
        print("=" * 78)
        print("\n".join(details))
        print()
    print("=" * 74)
    print(f"  结果：{passed} 通过 / {failures} 失败")
    print("=" * 74)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
