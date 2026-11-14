"""English public API for simulation/viewer target messages."""
from __future__ import annotations

import 界面桥 as _legacy


PanelTargetMessage = _legacy.面板目标消息
UIBridge = _legacy.界面桥
make_window_class = _legacy.制作窗口类


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = ["PanelTargetMessage", "UIBridge", "make_window_class"]
