"""
设备/契约.py —— 设备抽象层的**唯一**类型与协议定义

═══ 这一层解决什么 ════════════════════════════════════════════════════════
    现在算出来的轨迹只能看，不能交给任何硬件 —— 因为没有"往哪写"这回事。
    每接一台新机器人就从头写一遍"连接 + 限位 + 超时 + 状态机"，既慢又危险。

    这一层把**与协议无关**的部分固定下来：
        算法只产出「期望位置/速度/力矩」→ 设备抽象 → 传输层（Sim/UDP/CAN/…）

═══ 三条不可让步的设计（都是有理由的，不是风格）════════════════════════════
    ① **时间戳是接口的一部分**，不是可选项。
       没有它就没法回答"这条状态是几毫秒前的"，于是既做不了实时性诊断，
       也做不了安全检查（拿 200 ms 前的状态算力矩是危险的）。
    ② **读写都非阻塞**。`读状态()` 不该等网络；`写命令()` 不该等到对方确认。
       真机链路上任何一次阻塞都会把控制周期拖垮。
    ③ **能力声明必须被真正使用**。声明"只支持位置模式"的硬件，
       控制器就得走另一条代码路径。声明了却不读 = 假抽象。

═══ 这一层**不**负责什么 ═══════════════════════════════════════════════════
    · 不做安全决策（看门狗/限幅/状态机在 `安全层.py`，对所有后端生效）
    · 不做单位换算以外的语义（协议细节各自后端负责）
    · **不承担人身安全职责** —— 真机必须有独立的物理急停回路，
      软件里的急停只是"请求"。这句话写在规格里，也写在这里。
"""
from __future__ import annotations

import dataclasses
import enum
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class ControlMode(enum.Enum):
    IDLE = "空闲"
    POSITION = "位置"
    VELOCITY = "速度"
    TORQUE = "力矩"
    DAMPING = "阻尼"         # 看门狗触发后的"软着陆"：只加阻尼，不出力
    EMERGENCY_STOP = "急停"         # 请求切断使能（真机由物理回路保证）


class SafetyState(enum.Enum):
    """状态机。**不允许跳过"未使能"直接进入"运行"**（规格 B3-4）。"""
    DISCONNECTED = "未连接"
    CONNECTED = "已连接（未使能）"
    ENABLING = "使能中"
    RUNNING = "运行"
    STOP = "停止"
    FAULT = "故障"
    EMERGENCY_STOP = "急停"


class ErrorCode(enum.Enum):
    """错误码要能区分"哪一类问题"，不能糊成一个 False。"""
    OK = "正常"
    DISCONNECTED = "未连接"
    NOT_ENABLED = "未使能"
    TIMEOUT = "超时"
    LIMIT_EXCEEDED = "越限位"
    INCREMENT_EXCEEDED = "增量超限"
    UNSUPPORTED_CAPABILITY = "能力不支持"
    PROTOCOL_ERROR = "协议错误"
    INTERNAL_ERROR = "内部错误"


# ---------------------------------------------------------------------------
# 能力
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class DeviceCapabilities:
    """后端**如实**声明自己能干什么。控制器按它选代码路径。

    ★ 一张"什么都能"的能力表是最省事的，也是最假的 —— 所以这里的字段
      都以"控制器真的会读它"为准，不预留没人用的位。
    """
    can_read_position: bool = True
    can_read_velocity: bool = True
    can_read_torque: bool = False
    can_read_temperature: bool = False          # 没有热模型/没有传感器时**必须为 False**
    supports_position_mode: bool = True
    supports_velocity_mode: bool = False
    supports_torque_mode: bool = False
    encoder_resolution: float = 0.0       # 米或弧度；0 = 未知（不做事后量化）
    max_command_frequency: float = 0.0       # Hz；0 = 不限

    def supports(self, mode: ControlMode) -> bool:
        if mode in (ControlMode.IDLE, ControlMode.DAMPING, ControlMode.EMERGENCY_STOP):
            return True             # 这三个任何后端都必须支持（安全动作不能可选）
        return {
            ControlMode.POSITION: self.supports_position_mode,
            ControlMode.VELOCITY: self.supports_velocity_mode,
            ControlMode.TORQUE: self.supports_torque_mode,
        }.get(mode, False)


# ---------------------------------------------------------------------------
# 帧
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class CommandFrame:
    """一次"往哪走"的请求。**非阻塞写**，所以带序号便于对账。"""
    sequence: int
    target_position: tuple = ()            # (n,) 目标位置；空 = 不控制位置
    target_velocity: tuple = ()            # (n,) 目标速度
    target_torque: tuple = ()            # (n,) 前馈力矩
    effective_at: float = 0.0       # 墙钟（perf_counter 基准）；0 = 尽快
    heartbeat_count: int = 0               # 看门狗用；**真机的看门狗必须在硬件侧**


@dataclasses.dataclass(frozen=True)
class StateFrame:
    """一次"现在在哪"的反馈。**时间戳是接口的一部分**。"""
    sequence: int
    position: tuple = ()
    velocity: tuple = ()
    torque: tuple = ()
    temperature: tuple = ()                # 没有传感器就该是空 tuple，不是 0
    sampled_at: float = 0.0           # 硬件/仿真侧产生这一帧的时刻
    received_at: float = 0.0           # 本进程收到的时刻
    mode: ControlMode = ControlMode.IDLE

    def latency_ms(self) -> float:
        """这一帧在路上花了多久。两个时刻都来自**同一个时钟基准**才有效。"""
        if self.received_at <= 0 or self.sampled_at <= 0:
            return float("nan")
        return (self.received_at - self.sampled_at) * 1000.0


@dataclasses.dataclass(frozen=True)
class WriteResult:
    success: bool = True
    error_code: ErrorCode = ErrorCode.OK
    description: str = ""


@dataclasses.dataclass(frozen=True)
class HealthReport:
    connected: bool = False
    mode: ControlMode = ControlMode.IDLE
    dropped_packets: int = 0
    out_of_order_packets: int = 0
    mean_latency_ms: float = float("nan")
    max_latency_ms: float = float("nan")
    error_code: ErrorCode = ErrorCode.OK
    description: str = ""


# ---------------------------------------------------------------------------
# 后端协议
# ---------------------------------------------------------------------------
@runtime_checkable
class DeviceBackend(Protocol):
    """任何传输层（Sim / UDP / CAN / ROS2 / 厂商 SDK）都要满足它。

    ★ 用 Protocol 而不是基类：第三方写驱动时**不需要** import 我们的基类，
      结构对了就能用。这也让"契约测试"能对任意对象跑。
    """
    name: str
    version: str
    capabilities: DeviceCapabilities
    dof: int

    def open(self, config: dict | None = None) -> None: ...
    def close(self) -> None: ...
    def set_mode(self, mode: ControlMode) -> WriteResult: ...
    def write_command(self, command: CommandFrame) -> WriteResult: ...
    def read_state(self) -> StateFrame | None: ...
    def health(self) -> HealthReport: ...


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class AuditEntry:
    timestamp: float
    category: str            # 模式切换 / 命令拒绝 / 看门狗 / 状态迁移 / 安全动作
    content: str
    error_code: ErrorCode = ErrorCode.OK


class AuditLog:
    """安全层与后端的**唯一**事后依据。

    ★ 为什么不只 print：真机出问题时要能导出、能按时间对齐外部日志。
      所以这里存结构化条目，界面上可导出 CSV。
    """

    def __init__(self, limit: int = 5000):
        self._entries: list[AuditEntry] = []
        self._limit = int(limit)

    def record(self, category: str, content: str, error_code: ErrorCode = ErrorCode.OK,
          timestamp: float | None = None) -> None:
        import time as _t
        self._entries.append(AuditEntry(
            timestamp=float(timestamp if timestamp is not None else _t.perf_counter()),
            category=str(category), content=str(content), error_code=error_code))
        if len(self._entries) > self._limit:
            del self._entries[:len(self._entries) - self._limit]

    def all_entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    def latest(self, entry_count: int = 50) -> tuple[AuditEntry, ...]:
        return tuple(self._entries[-int(entry_count):])

    def clear(self) -> None:
        self._entries.clear()

    def export_csv(self, path: str) -> int:
        """写 CSV。返回写了多少条。"""
        import csv
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["时刻(perf_counter)", "类别", "内容", "错误码"])
            for entry in self._entries:
                w.writerow([f'{entry.timestamp:.6f}', entry.category, entry.content, entry.error_code.value])
        return len(self._entries)
