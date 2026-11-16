"""Legacy naming compatibility; new code imports recording_bridge."""
from __future__ import annotations

from functools import wraps
import recording_bridge as _implementation

_ALIASES = {'录制命令': 'RecordingCommand', '动作': 'action', '频率': 'frequency', '备注': 'note'}
_KEYWORDS = {'录制命令': 'RecordingCommand', '动作': 'action', '频率': 'frequency', '备注': 'note'}

def __getattr__(name):
    value = getattr(_implementation, _ALIASES.get(name, name))
    if callable(value) and not isinstance(value, type) and _KEYWORDS:
        @wraps(value)
        def call(*args, **kwargs):
            mapped = {}
            for key, item in kwargs.items():
                translated = _KEYWORDS.get(key, key)
                if translated in mapped:
                    raise TypeError(f"Multiple values for argument {translated!r}")
                mapped[translated] = item
            return value(*args, **mapped)
        return call
    return value

def __dir__():
    return sorted(set(globals()) | set(dir(_implementation)) | set(_ALIASES))

if __name__ == "__main__":
    import runpy
    runpy.run_module("recording_bridge", run_name="__main__")
