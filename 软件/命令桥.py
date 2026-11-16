"""Legacy naming compatibility; new code imports command_bridge."""
from __future__ import annotations

from functools import wraps
import command_bridge as _implementation

_ALIASES = {'_取消息类': 'get_message_class', '造消息': 'create_message', '_放入队列': '_put_message', '命令入队': 'enqueue_command', '排空并注入': 'drain_and_inject', '_同步界面侧共享状态': '_sync_ui_state', '转发待发命令': 'forward_pending_commands', '状态': 'status', '源模块': 'SOURCE_MODULES', '已转发': 'forwarded_count', '失败': 'failure_count'}
_KEYWORDS = {'主题名': 'topic_name', '负载': 'payload', '队列': 'queue', '打印': 'print_result', '类名': 'class_name', '消息': 'message'}

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
    runpy.run_module("command_bridge", run_name="__main__")
