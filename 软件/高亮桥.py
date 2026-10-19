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
import threading
import time

from 官方层 import messages          # 全部走适配层，见 软件/官方层.py


@dataclasses.dataclass(frozen=True)
class 高亮命令(messages.Snapshot):
    """界面 → 仿真注册表：亮一个关节。`关节=-1` 清除。"""

    关节: int = -1
    秒: float = 8.0


_锁 = threading.Lock()
_当前关节 = -1
_到期 = 0.0


def 设高亮(关节: int, 秒: float = 8.0) -> None:
    global _当前关节, _到期
    try:
        值 = int(关节)
    except Exception:                                                 # noqa: BLE001
        值 = -1
    时长 = max(0.0, min(60.0, float(秒)))
    with _锁:
        _当前关节 = 值
        _到期 = time.time() + 时长 if 值 >= 0 and 时长 > 0 else 0.0


def 清高亮() -> None:
    设高亮(-1, 0.0)


def 取高亮() -> int | None:
    """返回当前应高亮的关节；过期/未设置返回 None。"""
    with _锁:
        if _当前关节 < 0 or time.time() > _到期:
            return None
        return int(_当前关节)


class 高亮应用器:
    """内置插件：只收 `高亮命令`，不参与任何控制/物理。"""

    @messages.handler
    def 收命令(self, 命令: 高亮命令) -> bool:
        try:
            print(f"【高亮】收到命令：关节={命令.关节} 秒={命令.秒}", flush=True)
            设高亮(命令.关节, 命令.秒)
            return True
        except Exception:                                             # noqa: BLE001
            return False


__all__ = ["高亮命令", "高亮应用器", "设高亮", "清高亮", "取高亮"]
