"""English public API for recording and replay commands."""
from __future__ import annotations

import 录制桥 as _legacy


RecordingCommand = _legacy.录制命令


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = ["RecordingCommand"]
