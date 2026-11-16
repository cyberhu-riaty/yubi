"""
设备/模拟后端.py —— 在仿真里"当硬件用"的后端

═══ 它为什么重要 ═══════════════════════════════════════════════════════════
    没有真机的时候，唯一能验证整条链路（连接→使能→运行→超时→安全动作）的办法，
    就是有一个**行为像硬件**的后端。它不是"假数据生成器"，
    而是"一个可以被劣化的、可复现的假硬件"。

═══ 劣化注入不是加 sleep（规格明确要求）═══════════════════════════════════
    · **延迟**：状态帧不是立刻可见，而是排队到 deadline 之后才被 `读状态()` 取走。
      这是接口级的（`采集时刻` 与 `接收时刻` 真的不同），不是 `time.sleep` 拖慢整个进程。
    · **抖动**：每帧延迟加随机偏移（固定种子 → 可复现）。
    · **丢包**：按概率直接丢弃状态帧（于是序号会跳，`错序数` 能统计到）。
    · **量化**：位置按编码器分辨率取整（真机就是这样，控制器的抖动可能来自这里）。
    · **单步保持**：硬件按固定周期出状态，不是每次调用都出新帧 ——
      所以连续调用 `读状态()` 可能拿到同一帧（真实链路就是这样）。

═══ 物理模型 ═══════════════════════════════════════════════════════════════
    默认是一个**每关节独立的二阶系统**（惯量 + 阻尼 + 位置 PD），
    足够验证延迟对稳定性的影响，又完全不依赖 mujoco —— 这一层不该被仿真器绑架。
    需要更高保真时，构造时传 `物理=`（任何有 `步进(位置, 速度, 力矩, dt)` 的对象）。
"""
from __future__ import annotations

import random
import time
from typing import Any

import numpy as np

from .contract import (
    ControlMode, WriteResult, StateFrame, CommandFrame, HealthReport, DeviceCapabilities, ErrorCode,
)


class SimplePhysics:
    """每关节独立的二阶系统：`m·q̈ = τ - b·q̇ - k·(q - q_ref)`。

    ★ 为什么用这么简单的东西：这一层要验证的是**链路与安全**，不是动力学保真度。
      把 MuJoCo 拖进设备层会让"设备抽象"变成"MuJoCo 的包装"，那是倒退。
    """

    def __init__(self, dof: int, inertia: float = 0.05, damping: float = 0.6,
                 stiffness: float = 8.0):
        self.n = int(dof)
        self.q = np.zeros(self.n)
        self.qd = np.zeros(self.n)
        self.torque = np.zeros(self.n)
        self.reference = np.zeros(self.n)
        self.m, self.b, self.k = inertia, damping, stiffness

    def set_reference(self, position: np.ndarray | None) -> None:
        if position is not None and np.size(position) == self.n:
            self.reference = np.asarray(position, dtype=float).copy()

    def step(self, dt: float, torque: np.ndarray | None = None) -> None:
        dt = max(1e-6, min(float(dt), 0.05))
        external_torque = np.zeros(self.n) if torque is None else np.asarray(torque, dtype=float)
        # 半隐式欧拉：先加速度、再速度、再位置（比显式稳，够用）
        acceleration = (external_torque - self.b * self.qd - self.k * (self.q - self.reference)) / self.m
        self.qd = self.qd + acceleration * dt
        self.q = self.q + self.qd * dt


class SimulatedBackend:
    """满足 `设备后端` 协议的仿真后端。"""

    name = "模拟后端"
    version = "1.0"

    def __init__(self, dof: int = 6, *,
                 latency_ms: float = 0.0, jitter_ms: float = 0.0,
                 packet_loss_rate: float = 0.0, encoder_resolution: float = 0.0,
                 frame_interval_ms: float = 2.0, random_seed: int = 20261020,
                 physics: Any = None):
        self.dof = int(dof)
        self.capabilities = DeviceCapabilities(
            can_read_position=True, can_read_velocity=True, can_read_torque=False, can_read_temperature=False,
            supports_position_mode=True, supports_velocity_mode=False, supports_torque_mode=True,
            encoder_resolution=float(encoder_resolution),
            max_command_frequency=500.0,
        )
        # 劣化参数（公开可变：界面上的滑块直接改它们，便于现场演示）
        self.latency_ms = float(latency_ms)
        self.jitter_ms = float(jitter_ms)
        self.packet_loss_rate = float(packet_loss_rate)
        self.frame_interval_ms = float(frame_interval_ms)
        self._random = random.Random(int(random_seed))

        self._physics = physics if physics is not None else SimplePhysics(self.dof)
        self._connected = False
        self._mode = ControlMode.IDLE
        self._sequence = 0
        self._command_sequence = 0
        self._last_frame_time = 0.0
        self._pending: list[tuple[float, StateFrame]] = []     # (可见时刻, 帧)
        self._latest: StateFrame | None = None
        self._dropped_packets = 0
        self._out_of_order = 0
        self._latencies: list[float] = []
        self._error = ErrorCode.OK

    # ---- 生命周期 ----
    def open(self, config: dict | None = None) -> None:
        config = config or {}
        # 允许从外部覆盖劣化参数（部署界面用）
        for key, attribute in (("延迟毫秒", "latency_ms"), ("抖动毫秒", "jitter_ms"),
                         ("丢包率", "packet_loss_rate"), ("编码器分辨率", "encoder_resolution")):
            if key in config:
                if key == "编码器分辨率":
                    self.capabilities = DeviceCapabilities(**{**self.capabilities.__dict__, attribute: float(config[key])})
                else:
                    setattr(self, attribute, float(config[key]))
        self._connected = True
        self._mode = ControlMode.IDLE
        self._sequence = 0
        self._dropped_packets = 0
        self._out_of_order = 0
        self._latencies.clear()
        self._pending.clear()
        self._latest = None
        self._last_frame_time = 0.0

    def close(self) -> None:
        self._connected = False
        self._mode = ControlMode.EMERGENCY_STOP

    # ---- 模式 ----
    def set_mode(self, mode: ControlMode) -> WriteResult:
        if not self._connected:
            return WriteResult(success=False, error_code=ErrorCode.DISCONNECTED, description="还没打开")
        if not self.capabilities.supports(mode):
            self._error = ErrorCode.UNSUPPORTED_CAPABILITY
            return WriteResult(success=False, error_code=ErrorCode.UNSUPPORTED_CAPABILITY,
                          description=f'这个后端不支持「{mode.value}」')
        self._mode = mode
        return WriteResult()

    # ---- 写 ----
    def write_command(self, command: CommandFrame) -> WriteResult:
        if not self._connected:
            return WriteResult(success=False, error_code=ErrorCode.DISCONNECTED)
        if self._mode == ControlMode.EMERGENCY_STOP:
            return WriteResult(success=False, error_code=ErrorCode.NOT_ENABLED, description="急停中，拒绝所有命令")
        self._command_sequence = int(command.sequence)
        target = command.target_position
        if target and self._mode == ControlMode.POSITION:
            self._physics.set_reference(np.asarray(target, dtype=float))
        torque = command.target_torque
        self._physics.torque = (np.zeros(self.dof) if not torque
                        else np.asarray(torque, dtype=float))
        return WriteResult()

    # ---- 读（非阻塞，可能返回同一帧或 None）----
    def read_state(self) -> StateFrame | None:
        if not self._connected:
            return None
        now = time.perf_counter()
        # 出帧：硬件按固定周期产生状态，不是每次调用都出新帧（单步保持）
        if (now - self._last_frame_time) * 1000.0 >= self.frame_interval_ms:
            self._last_frame_time = now
            self._physics.step(self.frame_interval_ms / 1000.0, self._physics.torque)
            self._produce_frame(now)
        # 把到期的帧放出来（延迟在这里体现，而不是 sleep）
        while self._pending and self._pending[0][0] <= now:
            _, frame = self._pending.pop(0)
            frame = StateFrame(**{**frame.__dict__, "received_at": now})
            latency = frame.latency_ms()
            if np.isfinite(latency):
                self._latencies.append(latency)
                del self._latencies[:-200]
            if self._latest is not None and frame.sequence < self._latest.sequence:
                self._out_of_order += 1
            self._latest = frame
        return self._latest

    def _produce_frame(self, now: float) -> None:
        self._sequence += 1
        if self._random.random() < self.packet_loss_rate:
            self._dropped_packets += 1
            return                  # 丢包：序号会跳，调用方能看到
        position = np.array(self._physics.q, dtype=float)
        if self.capabilities.encoder_resolution > 0:
            position = np.round(position / self.capabilities.encoder_resolution) * self.capabilities.encoder_resolution
        frame = StateFrame(
            sequence=self._sequence,
            position=tuple(float(x) for x in position),
            velocity=tuple(float(x) for x in self._physics.qd),
            torque=(),                       # 能力表里说读不到力矩 → 就是空，不是 0
            temperature=(),                       # 没有传感器 → 空
            sampled_at=now,
            received_at=0.0,
            mode=self._mode,
        )
        latency = self.latency_ms + (self._random.uniform(0.0, self.jitter_ms) if self.jitter_ms else 0.0)
        self._pending.append((now + latency / 1000.0, frame))

    # ---- 健康 ----
    def health(self) -> HealthReport:
        latency = self._latencies
        return HealthReport(
            connected=self._connected,
            mode=self._mode,
            dropped_packets=self._dropped_packets,
            out_of_order_packets=self._out_of_order,
            mean_latency_ms=float(np.mean(latency)) if latency else float("nan"),
            max_latency_ms=float(np.max(latency)) if latency else float("nan"),
            error_code=self._error,
            description="模拟后端（劣化注入见 延迟/抖动/丢包/量化）",
        )
