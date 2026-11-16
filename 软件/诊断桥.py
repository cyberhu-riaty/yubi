"""Legacy naming compatibility; new code imports diagnostics_bridge."""
from __future__ import annotations

from functools import wraps
import diagnostics_bridge as _implementation

_ALIASES = {'发送函数': 'send', '包根': 'package_root', '_发送': '_send', '_包根': '_package_root', '_线程': '_thread', '_上次': '_last_report', '收命令': 'receive_command', '命令': 'command', '动作': 'action', '项': 'items', '说明': 'description', '时间': 'time', '耗时': 'elapsed_time', '路径': 'path', '出': 'output', '文件': 'file', '状态': 'state', '参数': 'parameters', '插件': 'plugins', '发现': 'discovered', '字节': 'bytes', '清单': 'manifest', '诊断命令': 'DiagnosticsCommand', '诊断报告': 'DiagnosticsReport', '运行中': 'running', '通过': 'passed', '总数': 'total', '耗时秒': 'elapsed_seconds', '套件表': 'SUITES', '单项超时秒': 'SUITE_TIMEOUT_SECONDS', '_跑一项': '_run_suite', '起': 'started_at', '行们': 'lines', '关键词': 'keywords', '候选': 'candidates', '错误行': 'error_lines', '运行全部': 'run_all', '脚本': 'script', '运行次数': 'run_count', '开始': 'start', '_跑': '_run', '重发上次': 'resend_last'}
_KEYWORDS = {'发送函数': 'send', '包根': 'package_root', '_发送': '_send', '_包根': '_package_root', '_线程': '_thread', '_上次': '_last_report', '收命令': 'receive_command', '命令': 'command', '动作': 'action', '项': 'items', '说明': 'description', '时间': 'time', '耗时': 'elapsed_time', '路径': 'path', '出': 'output', '文件': 'file', '状态': 'state', '参数': 'parameters', '插件': 'plugins', '发现': 'discovered', '字节': 'bytes', '清单': 'manifest', '诊断命令': 'DiagnosticsCommand', '诊断报告': 'DiagnosticsReport', '运行中': 'running', '通过': 'passed', '总数': 'total', '耗时秒': 'elapsed_seconds', '套件表': 'SUITES', '单项超时秒': 'SUITE_TIMEOUT_SECONDS', '_跑一项': '_run_suite', '起': 'started_at', '行们': 'lines', '关键词': 'keywords', '候选': 'candidates', '错误行': 'error_lines', '运行全部': 'run_all', '脚本': 'script', '运行次数': 'run_count', '开始': 'start', '_跑': '_run', '重发上次': 'resend_last'}

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
    runpy.run_module("diagnostics_bridge", run_name="__main__")
