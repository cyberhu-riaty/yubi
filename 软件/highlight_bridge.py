"""
高亮桥.py —— Web 界面 → 原生 3D 的「关节高亮」窄通道（P5 · B 阶段）

它解决什么问题：
    日志/诊断里出现「J4」时，用户需要知道 J4 在模型哪里。3D 是原生
    NSOpenGLView，Web 端不能直接改它的相机或几何；但仿真与窗口在**同一进程**，
    所以用一条最小的进程内共享状态把"要亮哪个关节"传过去：

        Web 命令 ──► 命令桥 ──► 高亮应用器（仿真注册表）──► 高亮桥.设高亮
                                                              │
                                     宿主主线程每 6 帧读一次 ──┘
                                            │
                                      Viewport.画_装饰 画标记

    这条通道只做"视觉诊断"，**不改变物理、不改变模型、不决定控制**。
    高亮有超时（默认 8 s），不会永久留在画面上；`关节=-1` 可显式清除。

为什么不做成下行主题：
    3D 视口不经过 WebSocket，也不该为了一个闪烁标记在 500 Hz 状态快照里
    加字段。进程内共享一个带锁的整数即可；Web 端只需要收到命令回执。
"""
from __future__ import annotations

import dataclasses
from wire_compatibility import legacy_wire
import threading
import time

from official_api import messages          # 全部走适配层，见 软件/official_api.py


@legacy_wire('高亮命令', {'joint': '关节', 'seconds': '秒'})
@dataclasses.dataclass(frozen=True)
class HighlightCommand(messages.Snapshot):
    """界面 → 仿真注册表：亮一个关节。`关节=-1` 清除。"""

    joint: int = -1
    seconds: float = 8.0


_lock = threading.Lock()
_current_joint = -1
_expires_at = 0.0


def set_highlight(joint: int, seconds: float = 8.0) -> None:
    global _current_joint, _expires_at
    try:
        value = int(joint)
    except Exception:                                                 # noqa: BLE001
        value = -1
    duration = max(0.0, min(60.0, float(seconds)))
    with _lock:
        _current_joint = value
        _expires_at = time.time() + duration if value >= 0 and duration > 0 else 0.0


def clear_highlight() -> None:
    set_highlight(-1, 0.0)


def get_highlight() -> int | None:
    """返回当前应高亮的关节；过期/未设置返回 None。"""
    with _lock:
        if _current_joint < 0 or time.time() > _expires_at:
            return None
        return int(_current_joint)


class HighlightApplier:
    """内置插件：只收 `高亮命令`，不参与任何控制/物理。"""

    @messages.handler
    def receive_command(self, command: HighlightCommand) -> bool:
        try:
            print(f'【高亮】收到命令：关节={command.joint} 秒={command.seconds}', flush=True)
            set_highlight(command.joint, command.seconds)
            return True
        except Exception:                                             # noqa: BLE001
            return False


__all__ = ["HighlightCommand", "HighlightApplier", "set_highlight", "clear_highlight", "get_highlight"]

WIRE_CLASS_ALIASES = {'HighlightCommand': '高亮命令'}
