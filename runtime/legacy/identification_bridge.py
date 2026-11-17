"""Legacy naming compatibility; new code imports identification_bridge."""
from __future__ import annotations

from functools import wraps
import identification_bridge as _implementation

_ALIASES = {'辨识命令': 'IdentificationCommand', '辨识状态': 'IdentificationState', '动作': 'action', '时长': 'duration', '状态': 'state', '进度': 'progress', '采样步数': 'sample_count', '结果': 'results', '拟合': 'fit', '耗时': 'elapsed_time', '日志': 'log', '发布器': 'Publisher', '发送函数': 'send', '频率': 'frequency', '_发送': '_send', '_间隔': '_interval', '_下次': '_next_publish_time', '已发布': 'published_count', '也许发布': 'maybe_publish', '注册表': 'registry', '墙钟': 'wall_clock', '插件': 'plugin', '取': 'get_state', '异常': 'exc'}
_KEYWORDS = {'辨识命令': 'IdentificationCommand', '辨识状态': 'IdentificationState', '动作': 'action', '时长': 'duration', '状态': 'state', '进度': 'progress', '采样步数': 'sample_count', '结果': 'results', '拟合': 'fit', '耗时': 'elapsed_time', '日志': 'log', '发布器': 'Publisher', '发送函数': 'send', '频率': 'frequency', '_发送': '_send', '_间隔': '_interval', '_下次': '_next_publish_time', '已发布': 'published_count', '也许发布': 'maybe_publish', '注册表': 'registry', '墙钟': 'wall_clock', '插件': 'plugin', '取': 'get_state', '异常': 'exc'}

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
    runpy.run_module("identification_bridge", run_name="__main__")
