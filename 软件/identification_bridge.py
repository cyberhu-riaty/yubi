"""English public API for parameter-identification commands and status."""
from __future__ import annotations

import 辨识桥 as _legacy


IdentificationCommand = _legacy.辨识命令
IdentificationState = _legacy.辨识状态
Publisher = _legacy.发布器


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = ["IdentificationCommand", "IdentificationState", "Publisher"]
