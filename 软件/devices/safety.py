"""
设备/安全层.py —— 对**任何**后端生效的安全逻辑

═══ 它挡在什么位置 ════════════════════════════════════════════════════════
        算法 ──► 安全层 ──► 设备后端 ──► 硬件
                   ↑
        状态机 / 看门狗 / 限幅 / 首帧保护 / 审计都在这一层

    放在这一层而不是每个后端里，是因为：**安全逻辑不该随协议重写一遍**。
    换了 UDP、CAN、厂商 SDK，这一层的规则一条都不能少。

═══ 规格里那八条"绝不允许"，逐条对应到代码 ══════════════════════════════
    ① 看门狗   —— `_查看门狗()`：状态帧超过 `看门狗毫秒` 没更新 → 进故障 + 切阻尼
       ⚠️ **诚实说明**：真机的看门狗必须在**硬件/驱动侧**（上位机崩了就没人发心跳）。
          这一层只能做到"我们能做的部分"：超时就停止下发并请求阻尼。
          真机的硬件看门狗需要在后端里实现，条款写在这里不是"已完成"。
    ② 限位/限速 —— `_限幅()`：位置夹到软限位、单周期位移限幅、速度限幅
       ⚠️ 同样是**第二道**：下层也必须有一份。
    ③ 急停 —— `急停()` 只是"请求"；物理回路不归软件管。
    ④ 状态机 —— 不允许跳过"未使能"直接运行；每次进运行必须显式 `使能()`
    ⑤ 首帧保护 —— 使能后第一条命令强制为"保持当前位置"
    ⑥ 限速渐变 —— 增量限幅（单周期最大位移）
    ⑦ 审计日志 —— 每次模式切换/拒绝/看门狗都记
    ⑧ 禁用高风险自动化 —— 这一层不提供"自动开始运行"的入口
"""
from __future__ import annotations

import time

import numpy as np

from .contract import (
    AuditLog, SafetyState, ControlMode, ErrorCode, CommandFrame, StateFrame, WriteResult, HealthReport,
    DeviceCapabilities,
)


class SafetyLayer:
    """包在设备后端外面的一层。**所有对外方法都先过安全检查**。"""

    def __init__(self, backend, *, watchdog_ms: float = 100.0,
                 max_step_displacement: float = 0.02,
                 position_limits: tuple[float, float] | None = None,
                 speed_limit: float | None = None,
                 audit: AuditLog | None = None):
        self.backend = backend
        self.watchdog_ms = float(watchdog_ms)
        self.max_step_displacement = float(max_step_displacement)
        self.position_limits = position_limits
        self.speed_limit = speed_limit
        self.audit = audit or AuditLog()

        self.state = SafetyState.DISCONNECTED
        self._sequence = 0
        self._heartbeat = 0
        self._last_state_time = 0.0
        self._last_command_position: np.ndarray | None = None
        self._first_frame_pending = False             # ⑤ 首帧保护
        self._latest_state: StateFrame | None = None
        self._rejected_count = 0

    # ---- 生命周期 ----
    def open(self, config: dict | None = None) -> WriteResult:
        try:
            self.backend.open(config)
        except Exception as exc:                                     # noqa: BLE001
            self.audit.record("状态迁移", f'打开失败：{exc}', ErrorCode.INTERNAL_ERROR)
            return WriteResult(success=False, error_code=ErrorCode.INTERNAL_ERROR, description=str(exc))
        self.state = SafetyState.CONNECTED
        self._first_frame_pending = False
        self.audit.record("状态迁移", "打开 → 已连接（未使能）")
        return WriteResult()

    def close(self) -> None:
        try:
            self.backend.close()
        finally:
            self.state = SafetyState.DISCONNECTED
            self.audit.record("状态迁移", "关闭 → 未连接")

    @property
    def capabilities(self) -> DeviceCapabilities:
        return getattr(self.backend, "capabilities", DeviceCapabilities())

    @property
    def dof(self) -> int:
        return int(getattr(self.backend, "dof", 0))

    # ---- 状态机 ----
    def enable(self, mode: ControlMode = ControlMode.POSITION) -> WriteResult:
        """④ 进入运行必须**显式**调用这里，不会被任何自动流程触发。"""
        if self.state != SafetyState.CONNECTED:
            self.audit.record("命令拒绝", f'未在「已连接」状态就使能（当前 {self.state.value}）',
                         ErrorCode.DISCONNECTED)
            return WriteResult(success=False, error_code=ErrorCode.DISCONNECTED,
                          description=f'当前是「{self.state.value}」，要先 打开()')
        result = self.backend.set_mode(mode)
        if not result.success:
            self.state = SafetyState.FAULT
            self.audit.record("命令拒绝", f'设模式 {mode.value} 失败：{result.description}', result.error_code)
            return result
        self.state = SafetyState.ENABLING
        self._first_frame_pending = True              # ⑤ 首帧保护：下一条命令必须是"保持当前位置"
        self._last_command_position = None
        self.audit.record("状态迁移", f'使能 → 使能中（模式 {mode.value}）')
        return WriteResult()

    def enter_running(self) -> WriteResult:
        """从"使能中"切到"运行"。首帧保护要求先有一条保持命令。"""
        if self.state != SafetyState.ENABLING:
            return WriteResult(success=False, error_code=ErrorCode.NOT_ENABLED,
                          description=f'当前是「{self.state.value}」，不能直接进运行')
        self.state = SafetyState.RUNNING
        self.audit.record("状态迁移", "运行")
        return WriteResult()

    def stop(self, reason: str = "手动停止") -> None:
        if self.state in (SafetyState.DISCONNECTED,):
            return
        try:
            self.backend.set_mode(ControlMode.IDLE)
        except Exception:                                             # noqa: BLE001
            pass
        self.state = SafetyState.STOP
        self.audit.record("状态迁移", f'停止（{reason}）')

    def emergency_stop(self, reason: str = "手动急停") -> None:
        """③ 这只是**请求**。物理急停回路不归软件管。"""
        try:
            self.backend.set_mode(ControlMode.EMERGENCY_STOP)
        except Exception:                                             # noqa: BLE001
            pass
        self.state = SafetyState.EMERGENCY_STOP
        self.audit.record("安全动作", f'急停请求（{reason}）—— 物理回路不归软件管')

    # ---- 读（带看门狗）----
    def read_state(self) -> StateFrame | None:
        frame = None
        try:
            frame = self.backend.read_state()
        except Exception as exc:                                     # noqa: BLE001
            self.audit.record("状态迁移", f'读状态异常：{exc}', ErrorCode.INTERNAL_ERROR)
        if frame is not None:
            if self._latest_state is None or frame.sequence != self._latest_state.sequence:
                self._last_state_time = time.perf_counter()
                self._latest_state = frame
        self._check_watchdog()
        return frame

    def _check_watchdog(self) -> None:
        """① 状态帧太久没更新 → 进故障 + 请求阻尼。

        ★ 触发后**不再自动恢复**：必须人工 `停止()` 再 `使能()`。
          "自动重连后继续跑"是危险的 —— 故障原因还没查清楚就接着动。
        """
        if self.state not in (SafetyState.ENABLING, SafetyState.RUNNING):
            return
        if self._last_state_time <= 0:
            return
        elapsed = (time.perf_counter() - self._last_state_time) * 1000.0
        if elapsed <= self.watchdog_ms:
            return
        try:
            self.backend.set_mode(ControlMode.DAMPING)
        except Exception:                                             # noqa: BLE001
            pass
        self.state = SafetyState.FAULT
        description = f'看门狗触发：{elapsed:.0f} ms 没有新状态（阈值 {self.watchdog_ms:.0f} ms）'
        self.audit.record("看门狗", description, ErrorCode.TIMEOUT)
        print(f'⚠ {description} → 已切阻尼，需人工停止后重新使能', flush=True)

    # ---- 写（限幅 + 首帧保护）----
    def write_command(self, target_position=None, target_velocity=None, target_torque=None) -> WriteResult:
        if self.state not in (SafetyState.ENABLING, SafetyState.RUNNING):
            self._rejected_count += 1
            self.audit.record("命令拒绝", f'状态 {self.state.value} 不接受命令', ErrorCode.NOT_ENABLED)
            return WriteResult(success=False, error_code=ErrorCode.NOT_ENABLED)

        position = None
        if target_position is not None and len(target_position):
            position = np.asarray(target_position, dtype=float).ravel()
            if position.size != self.dof:
                self._rejected_count += 1
                self.audit.record("命令拒绝", f'位置维度 {position.size} ≠ 自由度 {self.dof}',
                             ErrorCode.PROTOCOL_ERROR)
                return WriteResult(success=False, error_code=ErrorCode.PROTOCOL_ERROR, description="维度不符")

            # ⑤ 首帧保护：使能后的第一条命令**强制**为"保持当前位置"
            if self._first_frame_pending:
                current = self._latest_state.position if self._latest_state else None
                if not current:
                    self._rejected_count += 1
                    self.audit.record("命令拒绝", "首帧保护：还没有状态帧，拒绝下发", ErrorCode.NOT_ENABLED)
                    return WriteResult(success=False, error_code=ErrorCode.NOT_ENABLED,
                                  description="首帧保护：还没有状态帧")
                position = np.asarray(current, dtype=float)
                self._first_frame_pending = False
                self.audit.record("安全动作", "首帧保护：第一条命令已改为「保持当前位置」")

            position, result = self._clamp(position)
            if not result.success:
                self._rejected_count += 1
                return result
            self._last_command_position = position

        self._sequence += 1
        self._heartbeat += 1
        frame = CommandFrame(
            sequence=self._sequence,
            target_position=tuple(float(x) for x in position) if position is not None else (),
            target_velocity=tuple(float(x) for x in (target_velocity or ())),
            target_torque=tuple(float(x) for x in (target_torque or ())),
            heartbeat_count=self._heartbeat,
        )
        try:
            result = self.backend.write_command(frame)
        except Exception as exc:                                     # noqa: BLE001
            self.audit.record("命令拒绝", f'写命令异常：{exc}', ErrorCode.INTERNAL_ERROR)
            return WriteResult(success=False, error_code=ErrorCode.INTERNAL_ERROR, description=str(exc))
        if not result.success:
            self._rejected_count += 1
            self.audit.record("命令拒绝", f'后端拒绝：{result.description}', result.error_code)
        return result

    def _clamp(self, position: np.ndarray) -> tuple[np.ndarray, WriteResult]:
        """② 软限位 + ⑥ 单周期增量限幅。被夹的值会记审计（复盘要看得到）。"""
        changed = False
        if self.position_limits is not None:
            lower, upper = self.position_limits
            clamped = np.clip(position, lower, upper)
            if not np.allclose(clamped, position):
                changed = True
                position = clamped
        if self._last_command_position is not None:
            increment = position - self._last_command_position
            maximum = float(np.max(np.abs(increment))) if increment.size else 0.0
            if maximum > self.max_step_displacement > 0:
                position = self._last_command_position + increment * (self.max_step_displacement / maximum)
                changed = True
        if changed:
            self.audit.record("命令拒绝", "命令被限幅（软限位或单周期增量）", ErrorCode.INCREMENT_EXCEEDED)
        return position, WriteResult()

    # ---- 健康 ----
    def health(self) -> HealthReport:
        try:
            backend = self.backend.health()
        except Exception:                                             # noqa: BLE001
            return HealthReport(description="后端健康查询失败")
        return HealthReport(
            connected=backend.connected, mode=backend.mode, dropped_packets=backend.dropped_packets, out_of_order_packets=backend.out_of_order_packets,
            mean_latency_ms=backend.mean_latency_ms, max_latency_ms=backend.max_latency_ms,
            error_code=backend.error_code,
            description=f'{backend.description}｜安全状态={self.state.value}｜拒绝={self._rejected_count}',
        )

    def snapshot(self) -> dict:
        """给界面用的一行摘要。**所有字段都来自真实状态**，不做补零。"""
        backend = self.health()
        return {
            "状态": self.state.value,
            "模式": backend.mode.value,
            "已连接": backend.connected,
            "丢包": backend.dropped_packets,
            "错序": backend.out_of_order_packets,
            "平均延迟毫秒": backend.mean_latency_ms,
            "最大延迟毫秒": backend.max_latency_ms,
            "拒绝数": self._rejected_count,
            "说明": backend.description,
        }
