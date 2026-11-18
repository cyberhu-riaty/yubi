"""Legacy naming compatibility; new code imports highlight_bridge."""
from __future__ import annotations

from functools import wraps
import highlight_bridge as _implementation

_ALIASES = {'发送函数': 'send', '包根': 'package_root', '_发送': '_send', '_包根': '_package_root', '_线程': '_thread', '_上次': '_last_report', '收命令': 'receive_command', '命令': 'command', '动作': 'action', '项': 'items', '说明': 'description', '时间': 'time', '耗时': 'elapsed_time', '路径': 'path', '出': 'output', '文件': 'file', '状态': 'state', '参数': 'parameters', '插件': 'plugins', '发现': 'discovered', '字节': 'bytes', '清单': 'manifest', '高亮命令': 'HighlightCommand', '关节': 'joint', '秒': 'seconds', '_锁': '_lock', '_当前关节': '_current_joint', '_到期': '_expires_at', '设高亮': 'set_highlight', '清高亮': 'clear_highlight', '取高亮': 'get_highlight', '时长': 'duration'}
_KEYWORDS = _ALIASES

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
    runpy.run_module("highlight_bridge", run_name="__main__")
