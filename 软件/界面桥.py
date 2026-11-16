"""Legacy naming compatibility; new code imports ui_bridge."""
from __future__ import annotations

from functools import wraps
import ui_bridge as _implementation

_ALIASES = {'面板目标消息': 'PanelTargetMessage', '界面桥': 'UIBridge', '制作窗口类': 'make_window_class'}
_KEYWORDS = {'官方窗口基类': 'window_base'}

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
    runpy.run_module("ui_bridge", run_name="__main__")
