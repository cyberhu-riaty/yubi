"""Legacy naming compatibility; new code imports deployment_bridge."""
from __future__ import annotations

from functools import wraps
import deployment_bridge as _implementation

_ALIASES = {'发送函数': 'send', '包根': 'package_root', '_发送': '_send', '_包根': '_package_root', '_线程': '_thread', '_上次': '_last_report', '收命令': 'receive_command', '命令': 'command', '动作': 'action', '项': 'items', '说明': 'description', '时间': 'time', '耗时': 'elapsed_time', '路径': 'path', '出': 'output', '文件': 'file', '状态': 'state', '参数': 'parameters', '插件': 'plugins', '发现': 'discovered', '字节': 'bytes', '清单': 'manifest', '部署命令': 'DeploymentCommand', '部署状态': 'DeploymentState', '文件数': 'file_count', '_项目目录': '_deployment_directory', '导出': 'export', '时间戳': 'timestamp', '安全名': 'safe_name', '算法目录': 'algorithm_directory', '记': 'record', '大小': 'size', '用到': 'used_plugins', '源': 'source', '模型相对': 'relative_model_path', '模型绝对': 'absolute_model_path', '行们': 'lines', '标签': 'label', '算法行': 'algorithm_lines', '参数行': 'parameter_lines', '值表': 'values', '总字节': 'total_bytes', '导出次数': 'export_count', '_模型桥': '_model_bridge'}
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
    runpy.run_module("deployment_bridge", run_name="__main__")
