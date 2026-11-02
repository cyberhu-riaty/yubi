"""English public API for damped-least-squares inverse kinematics."""
from __future__ import annotations

import 逆解 as _legacy


IKError = _legacy.逆解失败
find_end_effector = _legacy.找末端
solve_ik = _legacy.逆解
cartesian_to_joint = _legacy.笛卡尔转关节


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = ["IKError", "find_end_effector", "solve_ik", "cartesian_to_joint"]
