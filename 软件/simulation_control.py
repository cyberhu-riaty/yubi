"""English public API for gravity and global simulation control messages."""
from __future__ import annotations

import 重力桥 as _legacy


set_ui_gravity = _legacy.设界面重力
GravityState = _legacy.重力状态
SimulationControlCommand = _legacy.仿真控制命令
SimulationState = _legacy.仿真状态
GravityApplier = _legacy.重力应用器
Publisher = _legacy.发布器
SimulationStatePublisher = _legacy.仿真状态发布器


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = [
    "set_ui_gravity", "GravityState", "SimulationControlCommand", "SimulationState",
    "GravityApplier", "Publisher", "SimulationStatePublisher",
]
