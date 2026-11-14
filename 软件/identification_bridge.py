"""English public API for parameter-identification commands and status."""
from __future__ import annotations

import 辨识桥 as _legacy


IdentificationCommand = _legacy.辨识命令
IdentificationState = _legacy.辨识状态
class Publisher(_legacy.发布器):
    """English method surface for the legacy identification publisher."""

    def maybe_publish(self, registry, wall_clock: float) -> bool:
        return super().也许发布(registry, wall_clock)


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = ["IdentificationCommand", "IdentificationState", "Publisher"]
