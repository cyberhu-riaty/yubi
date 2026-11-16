"""
观测核心.py —— 病态检出（把"看数"变成"下结论"）

═══ 一句话说明它在解决什么 ════════════════════════════════════════════════
    监控页现在告诉你「误差 = 29.8」——那是**体温计**：给了数，判断留给人。
    这里要变成**监护仪**：看一段时间的**形状**，然后说
    「12.3–14.1 秒，误差以 4.7 Hz 周期性过零、振幅 12°，且不衰减 → 关节在振荡」。

═══ 为什么需要环形缓冲（而不是只看当前值）══════════════════════════════════
    「周期性」「不衰减」「持续超差」都是**一段时间上的性质**。
    只有当前值的话，一条抖动的曲线和一个在爬升的曲线看起来一样。

═══ 判定原则（这几条决定了它有没有用）════════════════════════════════════
    ① **宁可少报，不可乱报**。误报几次之后，人就会开始无视所有告警 ——
       那时这套东西的价值是负的。所以每个判定都要求"样本够多、时间够长"。
    ② **只说有证据的结论**。每条告警都带量化证据（频率/振幅/斜率/时段），
       而不是"看起来不太对"。
    ③ **建议是经验规则，不是自动整定**。界面上要写明这一点。
    ④ **不猜没有的量**。没有热模型就没有温度；没有真机就没有驱动器侧跟随误差。

═══ 现在能检出哪几类 ═════════════════════════════════════════════════════
    当前控制器稳定提供的是“最大绝对误差”“最大绝对力矩”和“饱和关节数”。
    其中只有：最大绝对误差 → 跟踪超差，饱和关节数 → 饱和，证据充分。

    振荡 / 发散判定器仍保留给未来的“逐关节有符号误差”使用，但不再对最大绝对值
    或力矩峰值下结论：这些聚合量会因轨迹换向、负载变化、最大关节切换而产生台阶，
    把台阶叫成振荡/发散会误导人。宁可暂时少报，也不要假装已经定位故障。

    **模型失配**暂时不做：它需要把 `qfrc_bias` 回推的期望加速度与实际加速度
    逐关节对比，那是**逐关节**的量，而当前 `指标()` 只到聚合级（最大值）。
    要做的话得先扩指标 —— 放在后面，不在这里假装能测。
"""
from __future__ import annotations

import dataclasses
from wire_compatibility import legacy_wire
import math
from collections import deque
from typing import Any

from official_api import messages          # 全部走适配层，见 软件/official_api.py


# ---------------------------------------------------------------------------
# 环形缓冲
# ---------------------------------------------------------------------------
class SignalBuffer:
    """按**时间**存一条信号。容量满了丢最老的。

    ★ 为什么自己写而不用 deque + 遍历：
      判定要反复取"最近 W 秒"的窗口，每秒判定一次。deque 每次都要从头扫，
      而这里用 numpy 数组 + 双指针，取窗口是切片。
      不过为了让代码短、可读，这里用 deque 存 (t, v)，再在取值时转数组 ——
      20 Hz × 60 s = 1200 个点，转换成本可以忽略（实测 < 0.1 ms）。
    """

    def __init__(self, retention_seconds: float = 60.0):
        self.retention_seconds = float(retention_seconds)
        self._points: deque[tuple[float, float]] = deque()

    def record(self, t: float, v: float) -> None:
        if not (isinstance(t, (int, float)) and isinstance(v, (int, float))):
            return
        if not (math.isfinite(t) and math.isfinite(v)):
            return                      # NaN/Inf 不进缓冲：它们会把均值与极值全毁掉
        self._points.append((float(t), float(v)))
        while self._points and self._points[0][0] < t - self.retention_seconds:
            self._points.popleft()

    def get_values(self, recent_seconds: float | None = None) -> tuple[list[float], list[float]]:
        if not self._points:
            return [], []
        if recent_seconds is None:
            ts = [p[0] for p in self._points]
            vs = [p[1] for p in self._points]
            return ts, vs
        cutoff = self._points[-1][0] - float(recent_seconds)
        ts, vs = [], []
        for t, v in self._points:
            if t >= cutoff:
                ts.append(t)
                vs.append(v)
        return ts, vs

    def span_seconds(self) -> float:
        if len(self._points) < 2:
            return 0.0
        return self._points[-1][0] - self._points[0][0]

    def point_count(self) -> int:
        return len(self._points)


# ---------------------------------------------------------------------------
# 告警
# ---------------------------------------------------------------------------
@legacy_wire('告警', {'kind': '类型', 'severity': '严重度', 'signal': '信号', 'start_seconds': '开始秒', 'end_seconds': '结束秒', 'evidence': '证据', 'recommendation': '建议', 'curve': '曲线', 'curve_times': '曲线t', 'last_seen': '最后见'})
@dataclasses.dataclass
class Alert:
    kind: str                    # 振荡 / 发散 / 跟踪超差 / 饱和
    severity: str                  # 严重 / 警告
    signal: str                    # 哪个指标（"关节 PD 位置控制·最大误差(deg)"）
    start_seconds: float                # 仿真时间
    end_seconds: float
    evidence: str                    # 一句话的量化证据
    recommendation: str                    # 经验建议（界面上要标明"不是自动整定"）
    curve: tuple = ()             # 该时段的抽样曲线（给界面画小图）
    curve_times: tuple = ()
    last_seen: float = 0.0          # 墙钟：最后一次仍被判为病态的时间

    def key(self) -> str:
        return f'{self.kind}|{self.signal}'


@legacy_wire('告警消息', {'active': '活动', 'detected_count': '已检出'})
@dataclasses.dataclass(frozen=True)
class AlertSnapshot(messages.Snapshot):
    """仿真侧 → 界面：当前**活动**的告警列表。

    ★ 只发"活动"的，不发历史流水：
      流水会无限增长，而且界面要的是"现在有什么问题、怎么办"。
    """
    active: tuple = ()
    detected_count: int = 0


# ---------------------------------------------------------------------------
# 阈值
# ---------------------------------------------------------------------------
# ★ 为什么阈值要写在明处并按信号给：这些数全是**经验值**，
#   换个机器人、换个单位就不成立。所以：
#   ① 按信号名里的关键词匹配（"误差" / "力矩" / "饱和"）；
#   ② 匹配不到的信号**不判定**（而不是拿一个通用阈值乱判）。
#   宁可漏掉一个信号，也不要在没标定的量上瞎报警。
@legacy_wire('阈值', {'oscillation_amplitude': '振荡振幅', 'tracking_error_mean': '超差均值', 'divergence_ratio': '发散倍数', 'detectors': '判定们'})
@dataclasses.dataclass(frozen=True)
class Threshold:
    oscillation_amplitude: float              # 峰峰值的一半超过它才算"在振"
    tracking_error_mean: float              # 均值超过它算"跟不上"
    divergence_ratio: float = 2.0        # 窗口内包络涨这么多倍算"在发散"
    # ★ 每个信号**只跑适用的判定器**。这一条是测试逼出来的：
    #   第一版对所有信号跑全部四个判定器，于是「饱和」判定落到了「误差」上 ——
    #   误差 10° 天然 ≥1，被判成"100% 的采样里至少 1 个关节饱和（最多 16 个）"。
    #   这是典型的**看起来很有依据的胡说**，也正是告警系统最不能犯的错。
    detectors: tuple = ("振荡", "发散", "跟踪超差")


THRESHOLDS: tuple[tuple[str, Threshold], ...] = (
    # “有符号误差”才保留振荡/发散能力。当前控制器尚未发布这种逐关节指标，
    # 这条是为以后扩展准备的，不能退回去匹配“最大绝对误差”。
    ("有符号误差", Threshold(oscillation_amplitude=0.8, tracking_error_mean=5.0)),
    # 当前控制器发布的是六关节最大绝对误差：只适合回答“是否持续跟不上”。
    ("最大误差", Threshold(
        oscillation_amplitude=0.8, tracking_error_mean=5.0, detectors=("跟踪超差",))),
    # 不为“力矩峰值”登记阈值：最大绝对力矩会因轨迹和负载正常变化，不能据此
    # 单独确认振荡或发散。执行器是否顶住由下面的“饱和关节数”直接判断。
    # 饱和关节数：只要有一个关节长时间顶在上限就报。
    #   它是个**计数**，只能跑「饱和」这一个判定器（见 阈值.判定们 的说明）
    ("饱和", Threshold(oscillation_amplitude=0.5, tracking_error_mean=0.5, detectors=("饱和",))),
)


def get_threshold(signal: str) -> Threshold | None:
    for keyword, threshold in THRESHOLDS:
        if keyword in signal:
            return threshold
    return None


# 判定参数（都要求"够长够多"，这是防误报的第一道闸）
MIN_WINDOW_SECONDS = 3.0        # 少于这么长的数据不判定
MIN_SAMPLE_COUNT = 30         # 20 Hz 下 3 秒 = 60 个点；30 是下限
MIN_OSCILLATION_CROSSINGS = 8        # 少于 4 个完整周期不算"振荡"（避免把台阶当振荡）
TRACKING_ERROR_DURATION_SECONDS = 2.0        # 均值超限要**持续**这么久才算
ALERT_RETENTION_SECONDS = 12.0       # 墙钟：这么久没再被判为病态就自动消失


# ---------------------------------------------------------------------------
# 判定器
# ---------------------------------------------------------------------------
def _mean(vs: list[float]) -> float:
    return sum(vs) / len(vs) if vs else 0.0


def _half_peak_to_peak(vs: list[float]) -> float:
    return (max(vs) - min(vs)) / 2.0 if vs else 0.0


def detect_oscillation(ts: list[float], vs: list[float], threshold: Threshold) -> dict | None:
    """周期性过零 + 振幅够大 + 不衰减 → 振荡。

    「周期性」用**过零次数**近似，而不是做 FFT：
      · FFT 对不等间隔采样、短窗、有趋势的信号都不稳；
      · 而"来回过零"本身就是振荡最朴素的定义，也最好解释给人听。
    """
    count = len(vs)
    if count < MIN_SAMPLE_COUNT or count < 2:
        return None
    mean = _mean(vs)
    centered = [v - mean for v in vs]
    crossings = 0
    previous_sign = 0
    for v in centered:
        if v == 0:
            continue
        sign = 1 if v > 0 else -1
        if previous_sign and sign != previous_sign:
            crossings += 1
        previous_sign = sign
    span = max(ts[-1] - ts[0], 1e-9)
    frequency = crossings / (2.0 * span)
    amplitude = _half_peak_to_peak(vs)
    if crossings < MIN_OSCILLATION_CROSSINGS or amplitude < threshold.oscillation_amplitude:
        return None
    # 不衰减：后 1/3 的振幅不低于前 1/3 的 70%
    third = max(1, count // 3)
    initial_amplitude = _half_peak_to_peak(vs[:third])
    final_amplitude = _half_peak_to_peak(vs[-third:])
    if initial_amplitude > 1e-9 and final_amplitude / initial_amplitude < 0.7:
        return None                     # 在收敛 → 是正常的调节过程，不是病态
    return {
        "频率": frequency, "振幅": amplitude, "过零": crossings,
        "证据": f'{frequency:.1f} Hz、振幅 {amplitude:.2f}、{crossings} 次过零且不衰减',
    }


def detect_divergence(ts: list[float], vs: list[float], threshold: Threshold) -> dict | None:
    """包络（分箱后的 |v| 最大值）持续上涨 → 发散。"""
    count = len(vs)
    if count < MIN_SAMPLE_COUNT:
        return None
    # 分 4 箱取每箱 |v| 最大值，作为"包络"
    bin_count = 4
    bin_size = max(1, count // bin_count)
    envelope = []
    for i in range(bin_count):
        chunk = vs[i * bin_size:(i + 1) * bin_size] if i < bin_count - 1 else vs[i * bin_size:]
        if chunk:
            envelope.append(max(abs(v) for v in chunk))
    if len(envelope) < 3:
        return None
    growth = envelope[-1] / max(envelope[0], 1e-9)
    if growth < threshold.divergence_ratio:
        return None
    # 比例增长本身不等于危险：轨迹换向时，误差可能从 0.2° 正常涨到 0.6°，
    # 倍数很大但绝对值仍很小。只有窗口末端仍超过该信号的超差阈值，才称为发散。
    if abs(vs[-1]) < threshold.tracking_error_mean:
        return None
    # 再要求**单调**：至少 3 段里逐段不降（允许一点抖动）
    monotonic_count = sum(1 for a, b in zip(envelope, envelope[1:]) if b >= a * 0.98)
    if monotonic_count < len(envelope) - 1:
        return None
    return {"倍数": growth, "证据": f'包络在窗口内涨了 {growth:.1f} 倍且逐段上升'}


def detect_tracking_error(ts: list[float], vs: list[float], threshold: Threshold) -> dict | None:
    """均值超限且持续够久 → 跟踪超差。"""
    if len(vs) < MIN_SAMPLE_COUNT:
        return None
    mean = _mean([abs(v) for v in vs])
    if mean < threshold.tracking_error_mean:
        return None
    if ts[-1] - ts[0] < TRACKING_ERROR_DURATION_SECONDS:
        return None
    return {"均值": mean, "证据": f'{ts[-1] - ts[0]:.1f} 秒内均值 {mean:.2f}（阈值 {threshold.tracking_error_mean:g}）'}


def detect_saturation(ts: list[float], vs: list[float], threshold: Threshold) -> dict | None:
    """饱和关节数长时间 ≥1 → 饱和。"""
    if len(vs) < MIN_SAMPLE_COUNT:
        return None
    saturated = [v for v in vs if v >= 1]
    if not saturated:
        return None
    fraction = len(saturated) / len(vs)
    if fraction < 0.6:                      # 偶尔顶一下不算，要"长期顶着"
        return None
    maximum = max(saturated)
    return {"占比": fraction, "证据": f'{fraction * 100:.0f}% 的采样里至少 1 个关节顶在上限（最多 {maximum:.0f} 个）'}


DETECTORS = (
    ("振荡", detect_oscillation, "警告",
     "先降增益（KP 降一半），再考虑提高阻尼（KD）。振荡是增益过高最典型的表现。"),
    ("发散", detect_divergence, "严重",
     "立刻停止：误差在放大，继续跑会撞限位。检查符号（正反馈）与目标是否越界。"),
    ("跟踪超差", detect_tracking_error, "警告",
     "增益不够或目标变化太快。先看目标轨迹的加速度是否超出机器人能力。"),
    ("饱和", detect_saturation, "严重",
     "执行器已经到极限，继续加增益不会有任何改善。降目标速度/加速度，或换更大的执行器。"),
)


# ---------------------------------------------------------------------------
# 观测核心
# ---------------------------------------------------------------------------
class ObservationCore:
    """喂数据 → 出告警。

    用法（外壳里）：
        核心 = 观测核心(发送函数)
        每帧:  核心.记录(仿真时间, 指标发布.最近)      # 只在指标真的刷新时
        定时:  核心.判定(仿真时间, 墙钟)               # 内部 1 Hz 节流
    """

    def __init__(self, send, retention_seconds: float = 60.0, evaluation_interval: float = 1.0):
        self._send = send
        self._buffers: dict[str, SignalBuffer] = {}
        self._retention_seconds = float(retention_seconds)
        self._evaluation_interval = float(evaluation_interval)
        self._next_evaluation = 0.0
        self._active: dict[str, Alert] = {}
        self._last_simulation_time = 0.0
        self.evaluation_count = 0
        self.detected_count = 0
        self.published_count = 0

    # ---- 喂 ----
    def record(self, simulation_time: float, values: dict[str, Any]) -> None:
        for name, value in (values or {}).items():
            try:
                self._buffers.setdefault(str(name), SignalBuffer(self._retention_seconds)).record(
                    simulation_time, float(value))
            except (TypeError, ValueError):
                continue            # 非数值指标（字符串状态之类）不参与判定
        self._last_simulation_time = float(simulation_time)

    # ---- 判 ----
    def evaluate(self, simulation_time: float, wall_clock: float) -> bool:
        if wall_clock < self._next_evaluation:
            return False
        self._next_evaluation = wall_clock + self._evaluation_interval
        self.evaluation_count += 1
        now = wall_clock

        for signal, buffer in self._buffers.items():
            threshold = get_threshold(signal)
            if threshold is None:
                continue            # 没标定过的量不判定（宁可漏，不乱报）
            if buffer.point_count() < MIN_SAMPLE_COUNT:
                continue            # 数据还不够，别急着下结论
            ts, vs = buffer.get_values(recent_seconds=MIN_WINDOW_SECONDS if buffer.span_seconds() >= MIN_WINDOW_SECONDS else None)
            if len(vs) < MIN_SAMPLE_COUNT:
                continue
            for kind, detector, severity, recommendation in DETECTORS:
                if kind not in threshold.detectors:
                    continue            # 这个信号不适用这个判定器（见 阈值.判定们）
                try:
                    result = detector(ts, vs, threshold)
                except Exception:                                     # noqa: BLE001
                    continue            # 单个判定器出错不许影响其它判定，更不许影响仿真
                if result is None:
                    continue
                key = f'{kind}|{signal}'
                previous = self._active.get(key)
                # ★ 抽样窗口只取**最近 6 秒**，并且最多 60 个点。
                #   第一版取"整段 + 12 个点"：一条 3.7 Hz 的振荡跨 24 秒，
                #   12 个点画出来只有两个起伏 —— 卡片上写"3.7 Hz"、配图却像 0.1 Hz，
                #   图和结论自相矛盾。**配图必须能支撑它旁边的那个数字**。
                window = min(6.0, max(ts[-1] - ts[0], 1e-9))
                window_start = ts[-1] - window
                indices = [i for i, tv in enumerate(ts) if tv >= window_start] or [len(ts) - 1]
                sample_size = max(4, min(60, len(indices)))
                get_values = [indices[int(k * (len(indices) - 1) / max(sample_size - 1, 1))] for k in range(sample_size)]
                new_alert = Alert(
                    kind=kind, severity=severity, signal=signal,
                    start_seconds=previous.start_seconds if previous else ts[0],
                    end_seconds=ts[-1],
                    evidence=str(result.get("证据", "")),
                    recommendation=recommendation,
                    curve=tuple(round(vs[i], 4) for i in get_values),
                    curve_times=tuple(round(ts[i] - ts[0], 3) for i in get_values),
                    last_seen=now,
                )
                if previous is None:
                    self.detected_count += 1
                    print(f'⚠ 检出【{kind}】{signal}：{new_alert.evidence}', flush=True)
                self._active[key] = new_alert

        # 过期清理：一段时间没再被判为病态 → 认为已恢复
        expired = [k for k, a in self._active.items() if now - a.last_seen > ALERT_RETENTION_SECONDS]
        for k in expired:
            self._active.pop(k, None)

        self._publish()
        return True

    def _publish(self) -> None:
        table = sorted(self._active.values(), key=lambda a: (a.severity != "严重", a.kind))
        try:
            self._send(AlertSnapshot(
                active=tuple({
                    "类型": a.kind, "严重度": a.severity, "信号": a.signal,
                    "开始秒": a.start_seconds, "结束秒": a.end_seconds,
                    "证据": a.evidence, "建议": a.recommendation,
                    "曲线": list(a.curve), "曲线t": list(a.curve_times),
                } for a in table),
                detected_count=int(self.detected_count),
            ))
            self.published_count += 1
        except Exception:                                             # noqa: BLE001
            pass

    # ---- 给界面/自检用 ----
    def active_alerts(self) -> list[Alert]:
        return sorted(self._active.values(), key=lambda a: (a.severity != "严重", a.kind))

    def clear(self, reset_count: bool = True) -> None:
        """开始新实验/复位/换模型时清除旧时序与旧告警，并立即通知界面。"""
        self._active.clear()
        self._buffers.clear()
        self._last_simulation_time = 0.0
        if reset_count:
            self.detected_count = 0
        self._publish()


WIRE_CLASS_ALIASES = {'Threshold': '阈值', 'AlertSnapshot': '告警消息', 'Alert': '告警'}
