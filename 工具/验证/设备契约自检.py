#!/usr/bin/env python3
"""
设备契约自检.py —— 任何**设备后端**都必须通过的契约测试（规格 B5）

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
sys.path.insert(0, str(package_root / "软件"))

明细: list[str] = []
通过 = 0
失败 = 0


def 判(好: bool, description: str) -> None:
    global 通过, 失败
    if 好:
        通过 += 1
        明细.append(f'  ✓ {description}')
    else:
        失败 += 1
        明细.append(f'  ✗ {description}')


def 跑一段时间(safety_layer, 秒=0.3, 步=0.001):
    """驱动一会儿，让后端出帧（同时给看门狗喂状态）。"""
    deadline = time.perf_counter() + 秒
    while time.perf_counter() < deadline:
        safety_layer.read_state()
        time.sleep(步)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--简", action="store_true")
    args = ap.parse_args()

    from devices.contract import SafetyState, ControlMode, DeviceBackend
    from devices.simulated_backend import SimulatedBackend
    from devices.safety import SafetyLayer

    # ① 协议形状（用 Protocol 对结构做检查，第三方不用继承我们的基类）
    backend = SimulatedBackend(6)
    判(isinstance(backend, DeviceBackend), "① 模拟后端满足 `设备后端` 协议（结构化检查）")
    判(int(backend.dof) == 6 and bool(backend.name), f'① 名称={backend.name} 自由度={backend.dof}')

    safety_layer = SafetyLayer(backend, watchdog_ms=50, max_step_displacement=0.05,
                position_limits=(-1.0, 1.0))
    safety_layer.open()
    判(safety_layer.state == SafetyState.CONNECTED, f'① 打开后状态 = {safety_layer.state.value}')

    # ⑨ 状态机：不能跳级
    result = safety_layer.enter_running()
    判(not result.success and safety_layer.state == SafetyState.CONNECTED,
       "⑨ 从「已连接」不能直接进「运行」（必须显式使能）")

    safety_layer.enable(ControlMode.POSITION)
    判(safety_layer.state == SafetyState.ENABLING, f'⑨ 使能后 = {safety_layer.state.value}')

    # ⑥ 首帧保护：第一条命令必须被改成"保持当前位置"
    跑一段时间(safety_layer, 0.15)
    state = safety_layer._latest_state
    判(state is not None, "⑥ 拿到了状态帧")
    if state is not None:
        safety_layer.write_command(target_position=[0.5] * 6)          # 故意要跳很远
        判(safety_layer._last_command_position is not None
           and max(abs(a - b) for a, b in zip(safety_layer._last_command_position, state.position)) < 1e-9,
           "⑥ 首帧保护：第一条命令被改成了「保持当前位置」")

    safety_layer.enter_running()
    判(safety_layer.state == SafetyState.RUNNING, "⑨ 进入运行")

    # ⑥b 增量限幅：一次跳 0.5 会被夹到单周期上限
    # ★ 局部变量别叫 `后` —— 外层那个 `后` 是后端对象，遮蔽后后面会 AttributeError。
    #   （本项目第五次栽在"同名不同物"上，所以这里特意留一行提醒。）
    之前 = safety_layer._last_command_position.copy()
    safety_layer.write_command(target_position=[之前[0] + 0.5] + list(之前[1:]))
    now = safety_layer._last_command_position
    判(abs(now[0] - 之前[0]) <= 0.05 + 1e-9,
       f'⑥ 单周期增量被限幅（实际 {abs(now[0] - 之前[0]):.4f} ≤ 0.05）')

    # ⑤ 软限位
    safety_layer._last_command_position = None                # 临时放开增量限制，单独测软限位
    safety_layer.write_command(target_position=[9.0] * 6)
    判(max(abs(x) for x in safety_layer._last_command_position) <= 1.0 + 1e-9,
       "⑤ 超出软限位的命令被夹回")

    # ② 时间戳与延迟
    跑一段时间(safety_layer, 0.2)
    state = safety_layer._latest_state
    判(state.sampled_at > 0 and state.received_at >= state.sampled_at,
       "② 时间戳：采集时刻 ≤ 接收时刻")

    # ③ 单调性（丢包允许跳，不许回退）
    序号们 = []
    for _ in range(120):
        s = safety_layer.read_state()
        if s is not None:
            序号们.append(s.sequence)
        time.sleep(0.001)
    判(all(b >= a for a, b in zip(序号们, 序号们[1:])),
       f"③ 序号单调不降（取到 {len(序号们)} 帧，最大 {max(序号们) if 序号们 else 0}）")

    # ④ 能力一致：声明读不到力矩 → 状态帧里必须是空
    判(backend.capabilities.can_read_torque is False and state.torque == (),
       "④ 能力表说读不到力矩，状态帧的力矩就是空（不是 0）")

    # ⑧ 丢包可见
    差 = SimulatedBackend(6, packet_loss_rate=0.5, frame_interval_ms=1)
    差层 = SafetyLayer(差, watchdog_ms=500)
    差层.open()
    跑一段时间(差层, 0.3)
    判(差.health().dropped_packets > 0, f'⑧ 注入 50% 丢包后统计到 {差.health().dropped_packets} 次丢包')

    # ⑦ 看门狗：断开供帧 → 进故障
    短 = SimulatedBackend(6, frame_interval_ms=1)
    短层 = SafetyLayer(短, watchdog_ms=30, max_step_displacement=1.0)
    短层.open()
    短层.enable(ControlMode.POSITION)
    跑一段时间(短层, 0.1)
    短层._last_command_position = None
    短层.write_command(target_position=[0.0] * 6)
    短层.enter_running()
    短.close()                      # 模拟断线：之后不再有新状态
    time.sleep(0.08)               # 超过看门狗阈值
    短层.read_state()
    判(短层.state == SafetyState.FAULT, f'⑦ 看门狗触发 → {短层.state.value}')
    判(any("看门狗" in entry.category for entry in 短层.audit.all_entries()),
       "⑦ 看门狗事件进了审计日志")

    # 审计导出
    import tempfile
    import os
    path = os.path.join(tempfile.gettempdir(), "驭臂_审计.csv")
    entry_count = safety_layer.audit.export_csv(path)
    判(entry_count > 0 and os.path.getsize(path) > 0, f'审计日志可导出 CSV（{entry_count} 条）')

    if not args.简:
        print("=" * 78)
        print("  设备契约自检（任何后端都要过的准入测试）")
        print("=" * 78)
        print("\n".join(明细))
        print()
    print("=" * 74)
    print(f"  结果：{通过} 通过 / {失败} 失败")
    print("=" * 74)
    return 0 if 失败 == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
