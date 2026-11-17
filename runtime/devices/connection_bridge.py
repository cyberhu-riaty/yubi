"""
设备/连接桥.py —— 把设备链路接到界面上的桥（部署页的控制端）

═══ 它连哪几样 ════════════════════════════════════════════════════════════
    界面 ──命令──► 连接桥 ──► 安全层 ──► 模拟后端
                      │
                      └──快照──► 界面（安全状态 / 遥测 / 审计）

═══ 三条必须守住的规矩 ═════════════════════════════════════════════════════
    ① **界面只能"请求"，不能"命令"**。
       进「运行」必须由人显式点按（规格 B3-8：禁用高风险自动化），
       所以这里没有任何"连上就自动跑"的入口。
    ② **来自真实硬件的量，没有硬件就显示"未接入"，不能显示 0**。
       现在只有模拟后端，所以 `后端=模拟` 会一路带到界面上，让人看得见。
    ③ **审计要能导出**。这是事后复盘的唯一依据，不能只留在内存里。

═══ 为什么把安全层建在这里，而不是建在界面里 ══════════════════════════════
    安全逻辑必须与 UI 无关：UI 崩了、关了，安全状态机不该跟着消失。
    所以连接桥持有 `安全层` 实例，UI 只是它的一个观察者。
"""
from __future__ import annotations

import dataclasses
from wire_compatibility import legacy_wire
import os
import time
from typing import Any, Callable

from official_api import messages

from .contract import ControlMode, SafetyState
from .safety import SafetyLayer
from .simulated_backend import SimulatedBackend


# ---------------------------------------------------------------------------
# 界面 → 仿真侧
# ---------------------------------------------------------------------------
@legacy_wire('连接命令', {'action': '动作', 'latency_ms': '延迟毫秒', 'jitter_ms': '抖动毫秒', 'packet_loss_rate': '丢包率', 'encoder_resolution': '编码器分辨率'})
@dataclasses.dataclass(frozen=True)
class ConnectionCommand(messages.Snapshot):
    action: str = "快照"     # 打开 / 使能 / 进运行 / 停止 / 急停 / 设劣化 / 演练断线 / 导出审计
    latency_ms: float = -1.0        # <0 = 不改
    jitter_ms: float = -1.0
    packet_loss_rate: float = -1.0
    encoder_resolution: float = -1.0


# ---------------------------------------------------------------------------
# 仿真侧 → 界面
# ---------------------------------------------------------------------------
@legacy_wire('连接状态', {'backend': '后端', 'connected': '已连接', 'safety_state': '安全状态', 'mode': '模式', 'dof': '自由度', 'latency_ms': '延迟毫秒', 'jitter_ms': '抖动毫秒', 'packet_loss_rate': '丢包率', 'encoder_resolution': '编码器分辨率', 'measured_mean_latency': '实测平均延迟', 'measured_max_latency': '实测最大延迟', 'dropped_packets': '丢包数', 'out_of_order_packets': '错序数', 'rejected_count': '拒绝数', 'latest_position': '最近位置', 'audit': '审计', 'description': '说明'})
@dataclasses.dataclass(frozen=True)
class ConnectionState(messages.Snapshot):
    backend: str = ""                  # ★ 永远带上后端名字，界面据此显示"模拟"而不是假装真机
    connected: bool = False
    safety_state: str = "未连接"
    mode: str = "空闲"
    dof: int = 0
    # ---- 劣化参数（界面上可调，改完立即生效）----
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_rate: float = 0.0
    encoder_resolution: float = 0.0
    # ---- 实测遥测（全部来自真链路，不补零）----
    measured_mean_latency: float = 0.0
    measured_max_latency: float = 0.0
    dropped_packets: int = 0
    out_of_order_packets: int = 0
    rejected_count: int = 0
    latest_position: tuple = ()            # 空 = 还没有状态帧
    # ---- 审计（最近若干条，给界面列表用）----
    audit: tuple = ()                # 每项 {时刻, 类别, 内容, 错误码}
    description: str = ""


class DeviceBridge:
    name = "设备连接"
    version = "0.1"

    def __init__(self, send: Callable[[Any], None], package_root: str = "",
                 dof: int = 6):
        self._send = send
        self._package_root = package_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._dof = int(dof)
        self.safety_layer: SafetyLayer | None = None
        self.backend: SimulatedBackend | None = None
        self.open_count = 0
        self.latest: ConnectionState | None = None

    # ---- 懒建后端：界面不点"打开"就不占资源 ----
    def _build(self) -> SafetyLayer:
        if self.safety_layer is None:
            self.backend = SimulatedBackend(self._dof)
            self.safety_layer = SafetyLayer(self.backend, watchdog_ms=100.0,
                             max_step_displacement=0.02, position_limits=(-3.0, 3.0))
        return self.safety_layer

    @messages.handler
    def receive_command(self, command: ConnectionCommand) -> bool:
        action = str(getattr(command, "action", ""))
        try:
            if action == "打开":
                self._open()
            elif action == "使能":
                self._build().enable(ControlMode.POSITION)
            elif action == "进运行":
                self._build().enter_running()
            elif action == "停止":
                self._build().stop("界面请求")
            elif action == "急停":
                self._build().emergency_stop("界面请求")
            elif action == "设劣化":
                self._set_impairments(command)
            elif action == "演练断线":
                self._simulate_disconnect()
            elif action == "导出审计":
                self._export_audit()
        except Exception as exc:                                         # noqa: BLE001
            print(f'⚠ 设备命令「{action}」失败：{type(exc).__name__}: {exc}', flush=True)
        self._publish()
        return False

    # ---- 各个动作 ----
    def _open(self) -> None:
        safety_layer = self._build()
        safety_layer.open()
        self.open_count += 1
        print(f'【设备】已打开模拟后端（自由度 {self._dof}）—— 注意：**不是真机**',
              flush=True)

    def _set_impairments(self, command: ConnectionCommand) -> None:
        safety_layer = self._build()
        backend = self.backend
        if backend is None:
            return
        for name in ("latency_ms", "jitter_ms", "packet_loss_rate", "encoder_resolution"):
            value = float(getattr(command, name, -1.0))
            if value < 0:
                continue
            if name == "encoder_resolution":
                # 能力表是不可变的，改量化要重建一份（如实反映"换了编码器"）
                backend.capabilities = dataclasses.replace(backend.capabilities, encoder_resolution=value)
            else:
                setattr(backend, name, value)
        safety_layer.audit.record("模式切换",
                    f'劣化参数：延迟 {backend.latency_ms:.0f}ms、抖动 {backend.jitter_ms:.0f}ms、'
                    f'丢包 {backend.packet_loss_rate * 100:.0f}%、量化 {backend.capabilities.encoder_resolution:g}')

    def _simulate_disconnect(self) -> None:
        """把后端"拔线"：之后不再出状态帧，看门狗应当触发。

        ★ 这是**演练**，不是故障注入接口 —— 它模拟的是"网线掉了"这一类事件。
        """
        safety_layer = self._build()
        if self.backend is not None:
            self.backend.close()
        safety_layer.audit.record("安全动作", "演练：模拟断线（后端关闭，不再出状态帧）")
        print("【设备】演练断线：后端已关闭，等看门狗触发", flush=True)

    def _export_audit(self) -> None:
        safety_layer = self._build()
        directory = os.path.join(self._package_root, "输出", "06_部署审计")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"审计_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        entry_count = safety_layer.audit.export_csv(path)
        safety_layer.audit.record("安全动作", f'导出审计 {entry_count} 条 → {os.path.basename(path)}')
        print(f'【设备】审计已导出 {entry_count} 条 → {path}', flush=True)

    # ---- 泵：由仿真循环周期调用 ----
    def maybe_pump(self, wall_clock: float, interval_seconds: float = 0.02) -> None:
        """驱动一次链路：读状态（喂看门狗）+ 按 50 Hz 发布。

        ★ 为什么必须有人泵：`读状态()` 是**拉式**接口 ——
          没人调用它，就不会有遥测，**看门狗也不会触发**（它只在读取时检查）。
          这也是真机上"控制循环必须活着"的同一件事：循环停了，安全逻辑就停了。
        """
        if self.safety_layer is None:
            return
        try:
            self.safety_layer.read_state()
        except Exception:                                             # noqa: BLE001
            pass
        if wall_clock >= getattr(self, "_next_publish_time", 0.0):
            self._next_publish_time = wall_clock + float(interval_seconds)
            self._publish()

    # ---- 发布 ----
    def maybe_publish(self, wall_clock: float) -> None:
        self._publish()

    def _publish(self) -> None:
        safety_layer = self.safety_layer
        backend = self.backend
        if safety_layer is None or backend is None:
            state = ConnectionState(backend="（未打开）", description="点「打开」才会创建模拟后端")
        else:
            health = safety_layer.health()
            latest_position: tuple = ()
            if safety_layer._latest_state is not None and safety_layer._latest_state.position:      # noqa: SLF001
                latest_position = tuple(float(x) for x in safety_layer._latest_state.position)  # noqa: SLF001
            audit = tuple({
                "时刻": round(entry.timestamp, 3), "类别": entry.category,
                "内容": entry.content, "错误码": entry.error_code.value,
            } for entry in safety_layer.audit.latest(30))
            state = ConnectionState(
                backend=backend.name,
                connected=bool(health.connected),
                safety_state=safety_layer.state.value,
                mode=health.mode.value,
                dof=int(backend.dof),
                latency_ms=float(backend.latency_ms),
                jitter_ms=float(backend.jitter_ms),
                packet_loss_rate=float(backend.packet_loss_rate),
                encoder_resolution=float(backend.capabilities.encoder_resolution),
                measured_mean_latency=float(health.mean_latency_ms if health.mean_latency_ms == health.mean_latency_ms else 0.0),
                measured_max_latency=float(health.max_latency_ms if health.max_latency_ms == health.max_latency_ms else 0.0),
                dropped_packets=int(health.dropped_packets),
                out_of_order_packets=int(health.out_of_order_packets),
                rejected_count=int(getattr(safety_layer, "_rejected_count", 0)),
                latest_position=latest_position,
                audit=audit,
                description=health.description,
            )
        self.latest = state
        try:
            self._send(state)
        except Exception:                                             # noqa: BLE001
            pass

WIRE_CLASS_ALIASES = {'ConnectionState': '连接状态', 'ConnectionCommand': '连接命令'}
