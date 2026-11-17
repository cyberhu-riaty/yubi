"""
辨识桥.py —— 参数辨识面板与后端之间的消息（第 4 步 D3 界面化）

两条消息，方向相反：
    辨识命令（界面 → 仿真侧）："去采样" / "去辨识"
    辨识状态（仿真侧 → 界面）：当前状态、结果表、拟合残差、日志

★ 为什么状态要带"拟合残差"而不只是参数值：
    辨识出的参数"像不像真的"没法直接验证（我们没有真机当参考）。
    但可以看"用这组参数去预测这段数据，残差是不是更小" ——
    残差显著下降，说明这组参数确实更贴合数据。
    **注意**：这只说明"比原始标称值更贴合这段数据"，不等于"找到了真值"。
    证明算法能找到真值的证据是离线那个闭环实验（造已知真值 → 误差 1.47%）。
"""
from __future__ import annotations

import dataclasses
from wire_compatibility import legacy_wire

from official_api import messages          # 全部走适配层，见 runtime/official_api.py


@legacy_wire('辨识命令', {'action': '动作', 'duration': '时长'})
@dataclasses.dataclass(frozen=True)
class IdentificationCommand(messages.Snapshot):
    """界面 → 仿真侧。"""

    action: str = "空闲"        # "采样" / "辨识"
    duration: float = 1.0         # 采样时长（秒）


@legacy_wire('辨识状态', {'state': '状态', 'progress': '进度', 'sample_count': '采样步数', 'results': '结果', 'fit': '拟合', 'elapsed_time': '耗时', 'log': '日志'})
@dataclasses.dataclass(frozen=True)
class IdentificationState(messages.Snapshot):
    """仿真侧 → 界面。"""

    state: str = "空闲"        # 空闲 / 采样中 / 辨识中
    progress: str = ""
    sample_count: int = 0
    results: list = dataclasses.field(default_factory=list)   # [(名称, 标称, 估计值, 误差%)]
    fit: dict = dataclasses.field(default_factory=dict)   # {"标称": r0, "辨识后": r1}
    elapsed_time: float = 0.0
    log: list = dataclasses.field(default_factory=list)


class Publisher:
    """周期性把辨识状态发给界面（默认 5 Hz —— 采样/辨识都是秒级过程，不需要更密）。"""

    def __init__(self, send, frequency: float = 5.0):
        self._send = send
        self._interval = 1.0 / max(frequency, 1e-6)
        self._next_publish_time = 0.0
        self.published_count = 0

    def maybe_publish(self, registry, wall_clock: float) -> bool:
        if wall_clock < self._next_publish_time:
            return False
        self._next_publish_time = wall_clock + self._interval
        state = None
        for plugin in getattr(registry, "_targets", []):
            get_state = getattr(plugin, "state_message", None)
            if get_state is None:
                continue
            try:
                state = get_state()
                break
            except Exception:                                        # noqa: BLE001
                continue
        if state is None:
            return False
        try:
            self._send(state)
            self.published_count += 1
            return True
        except Exception as exc:                                     # noqa: BLE001
            if self.published_count == 0:
                print(f'⚠ 辨识状态发布失败（不影响控制）：{type(exc).__name__}: {exc}')
            return False

WIRE_CLASS_ALIASES = {'IdentificationCommand': '辨识命令', 'IdentificationState': '辨识状态'}
