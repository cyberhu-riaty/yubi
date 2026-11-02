"""English public API for the pinned MuJoCo and experimental Studio imports."""
from __future__ import annotations

import 官方层 as _legacy


MUJOCO_VERSION_REQUIREMENT = _legacy.MUJOCO版本要求
KNOWN_GOOD_VERSIONS = _legacy.已知可用版本
self_check = _legacy.自检


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = ["MUJOCO_VERSION_REQUIREMENT", "KNOWN_GOOD_VERSIONS", "self_check"]
