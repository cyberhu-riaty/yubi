"""
设备/跟踪回路.py —— 把控制器接到设备链路上，让"延迟"真的咬人

═══ 为什么需要这一层 ═══════════════════════════════════════════════════════
    上一版做完设备抽象后，延迟注入只影响**观测**：模拟后端自带"伺服跟参考"，
    延迟再大动力学也稳。这不是 bug，是**闭环里没有控制器**。

    真机上的失稳链条是这样的：
        控制器用**收到的（旧的）状态**算指令 → 指令迟到 → 实际状态更偏 → 指令更大 …
    要把这条链在仿真里复现，就必须让"用延迟状态算指令"这一步真的存在于回路中。

═══ 两个诚实声明 ═══════════════════════════════════════════════════════════
    ① 这一层是**演示与控制律验证**用的最小闭环（位置 PD + 重力/无重力一视同仁），
       不是"真机控制器"。真机还要考虑摩擦、柔性、电机环、限幅动力学。
    ② 它的价值在于**能定量回答一个问题**：
       "同一个增益，延迟从 0 增到多少毫秒会开始振荡？" —— 这个数在真机上试是撞机，
       在这里试是改一行参数。
"""
from __future__ import annotations

import time

import numpy as np


class TrackingLoop:
    """用**收到的状态**算位置 PD 指令，经安全层下发。

    ★ 关键点：`步进()` 里读到的状态可能是**上一帧甚至更早**的 ——
      这不是缺陷，正是要复现的现实。真机控制器永远拿不到"此刻"的真实状态。
    """

    def __init__(self, safety_layer, *, kp: float = 60.0, kd: float = 8.0, timestep: float = 0.002):
        self.safety_layer = safety_layer
        self.kp = float(kp)
        self.kd = float(kd)
        self.timestep = float(timestep)
        self.target: np.ndarray | None = None
        self.history: list[tuple[float, float, float]] = []   # (墙钟, 指令, 实际)
        self._last_command: np.ndarray | None = None

    def set_target(self, target) -> None:
        self.target = np.asarray(target, dtype=float).ravel()

    def step(self) -> bool:
        """走一步。返回是否真的下发了指令。

        ★ 只读**一帧**：`读状态()` 是非阻塞的，可能拿到旧帧（单步保持）
          或同一帧（没出新帧）—— 这两种都算"这一刻我只有这些信息"，
          控制器就该基于它做决定。这正是延迟影响的来源。
        """
        state = self.safety_layer.read_state()
        if state is None or not state.position:
            return False
        actual = np.asarray(state.position, dtype=float)
        velocity = np.asarray(state.velocity, dtype=float) if state.velocity else np.zeros_like(actual)
        target = self.target if self.target is not None else actual
        if target.size != actual.size:
            return False
        # 位置 PD：指令 = 目标 + Kp·误差 - Kd·速度（再用安全层的增量限幅管住突变）
        error = target - actual
        command = target + self.kp * error * self.timestep - self.kd * velocity * self.timestep
        result = self.safety_layer.write_command(target_position=command)
        if result.success:
            self._last_command = command
            now = time.perf_counter()
            self.history.append((now, float(np.max(np.abs(command))), float(np.max(np.abs(actual)))))
            del self.history[:-4000]
            return True
        return False


def step_response(latency_ms: float, kp: float = 60.0, kd: float = 8.0,
             duration: float = 3.0) -> dict:
    """跑一次"0 → 1"的位置阶跃，返回超调/稳态误差/是否发散等指标。

    这是 L2 最该回答的问题：**同一个增益，延迟到多少会失控**。
    """
    from .contract import ControlMode
    from .simulated_backend import SimulatedBackend
    from .safety import SafetyLayer

    backend = SimulatedBackend(1, latency_ms=latency_ms, frame_interval_ms=2)
    safety_layer = SafetyLayer(backend, watchdog_ms=1000, max_step_displacement=1.0, position_limits=(-10, 10))
    safety_layer.open()
    safety_layer.enable(ControlMode.POSITION)

    # 预热：等到真的收到状态帧（不能拍固定毫秒数 —— 延迟大于预热时长就收不到）
    deadline = time.perf_counter() + 2.0
    while safety_layer._latest_state is None and time.perf_counter() < deadline:
        safety_layer.read_state()
        time.sleep(0.001)
    if safety_layer._latest_state is None:
        return {"可达": False}

    loop = TrackingLoop(safety_layer, kp=kp, kd=kd)
    loop.set_target([1.0])
    loop.step()                      # 首帧保护会把这条改成"保持"
    safety_layer.enter_running()

    peak = 0.0
    final = None
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < duration:
        loop.step()
        time.sleep(0.001)
        if backend._physics.q.size:
            final = float(backend._physics.q[0])
            peak = max(peak, final)
    actual_latency = backend.health().mean_latency_ms
    return {
        "可达": True, "峰值": peak, "超调%": (peak - 1.0) * 100.0,
        "稳态误差": abs((final if final is not None else 0.0) - 1.0),
        "平均延迟毫秒": actual_latency,
        "发散": peak > 5.0 or (final is not None and abs(final) > 5.0),
        "安全状态": safety_layer.state.value,
    }
