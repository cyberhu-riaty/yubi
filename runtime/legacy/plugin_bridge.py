"""Legacy naming compatibility; new code imports plugin_bridge."""
from __future__ import annotations

from functools import wraps
import plugin_bridge as _implementation

_ALIASES = {'发送函数': 'send', '包根': 'package_root', '_发送': '_send', '_包根': '_package_root', '_线程': '_thread', '_上次': '_last_report', '收命令': 'receive_command', '命令': 'command', '动作': 'action', '项': 'items', '说明': 'description', '时间': 'time', '耗时': 'elapsed_time', '路径': 'path', '出': 'output', '文件': 'file', '状态': 'state', '参数': 'parameters', '插件': 'plugins', '发现': 'discovered', '字节': 'bytes', '清单': 'manifest', '_被项目使用': '_projects_using_plugins', '_读类属性': '_read_class_attributes', '使用表': 'usage', '元': 'metadata', '元信息字段': 'METADATA_FIELDS', '启用顺序': 'enabled_order', '子': 'child', '当前算法': 'current_algorithms', '当前顺序': 'current_order', '数量': 'count', '文件名们': 'filenames', '显示名': 'display_name', '标识': 'identifier', '树': 'tree', '节点': 'node'}
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
    runpy.run_module("plugin_bridge", run_name="__main__")
