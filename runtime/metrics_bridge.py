"""
Collect controller metrics and publish them to the workbench.

它解决什么问题：
    官方 19 个面板能看内置量（关节角、接触力…），但**看不到你的控制律算出来的中间量**
    —— 比如"末端跟踪误差""力矩峰值""我自己的指标"。
    这个模块把这些量统一采集起来，发给窗口侧的面板去画实时曲线。

怎么用（对写控制算法的人）：
    在你的插件里加一个方法，返回你想看的数（键=曲线名，值=数字）：

        class MyPlugin(ControlPlugin):
            def metrics(self) -> dict:
                return {"跟踪误差(mm)": self.误差*1000, "力矩峰值": float(np.abs(数据.ctrl).max())}

    就这样。**不需要改外壳、不需要改面板** —— 面板会自动按"指标名字"建曲线。
    不写 `metrics()` 的插件就不出现在面板里，没有任何影响。

数据流（和界面桥同一条已验证的路子）：
    仿真侧：启动.py 每约 1/30 秒 → 指标桥.发布指标(注册表, 发送函数)
                    ↓ 自定义 Snapshot 消息（最新覆盖，不排队）
    窗口侧：面板/监控面板.py 每帧读 → 画实时曲线
"""
from __future__ import annotations

import dataclasses
from wire_compatibility import legacy_wire
import time
from typing import Any, Callable

from official_api import messages          # 全部走适配层，见 runtime/official_api.py

# 发布频率上限：物理是 500 Hz，但曲线不需要那么密（30 Hz 足够顺滑），
# 而且能避免把通道塞满、避免面板画图成为瓶颈。想改就改这个数。
PUBLISH_RATE = 30.0


@legacy_wire('MetricsSnapshot', {'simulation_time': '时间', 'wall_clock': '墙钟', 'values': '数值'})
@dataclasses.dataclass(frozen=True)
class MetricsSnapshot(messages.Snapshot):
    """一帧指标快照。Snapshot = 只保留最新一条（旧的不排队，天然适合实时曲线）。

    ★ 必须加 @dataclasses.dataclass，否则 pybind 侧取不到字段（实测踩过）。
    """

    simulation_time: float            # 仿真时间（秒）
    wall_clock: float            # 真实时间（秒），面板用它做横轴更平稳
    values: dict             # {指标名: 数字}


def collect_metrics(registry) -> dict[str, float]:
    """向每个插件要一次指标。插件没写 `metrics()`、或写错了，都只跳过它，不影响别人。"""
    result: dict[str, float] = {}
    for plugin in getattr(registry, "_targets", []):
        # 跳过内置的步进插件（它没有指标）
        getter = getattr(plugin, "metrics", None)
        if getter is None:
            continue
        name_prefix = str(getattr(plugin, "name", type(plugin).__name__))
        try:
            values = getter() or {}
        except Exception as exc:                                  # noqa: BLE001
            # 指标采集失败不该影响控制回路
            print(f"⚠ 插件【{name_prefix}】的 metrics() 出错（已跳过）：{type(exc).__name__}: {exc}")
            continue
        for key, value in values.items():
            try:
                result[f"{name_prefix}·{key}"] = float(value)
            except (TypeError, ValueError):
                continue          # 非数字的指标（比如字符串状态）不上曲线
    return result


class Publisher:
    """限频发布指标。放在仿真循环里每圈调一次 `也许发布()` 即可。"""

    def __init__(self, send: Callable[[Any], None], frequency: float = PUBLISH_RATE):
        self._send = send
        self._interval = 1.0 / max(frequency, 1e-6)
        self._next_publish = 0.0
        self.published_count = 0
        self.latest: dict[str, float] = {}

    def maybe_publish(self, registry, simulation_time: float, monotonic_time: float) -> bool:
        """到了时间就采集并发一帧。返回是否真的发了。

        限频用 ``perf_counter`` 这类单调时钟；但发给前端的横轴必须是
        Unix 墙钟 ``time.time()``。两者混用会让“最近更新”变成十几亿秒前。
        """
        if monotonic_time < self._next_publish:
            return False
        self._next_publish = monotonic_time + self._interval
        metrics = collect_metrics(registry)
        self.latest = metrics
        try:
            self._send(MetricsSnapshot(simulation_time=simulation_time, wall_clock=time.time(), values=metrics))
            self.published_count += 1
            return True
        except Exception as exc:                                       # noqa: BLE001
            # 通道出问题（比如窗口刚关）不该拖垮仿真
            if self.published_count == 0:
                print(f"⚠ 指标发布失败（不影响控制）：{type(exc).__name__}: {exc}")
            return False
