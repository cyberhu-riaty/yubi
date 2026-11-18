"""Legacy naming compatibility; new code imports official_interface_inventory."""
from __future__ import annotations

from functools import wraps
import official_interface_inventory as _implementation

_ALIASES = {'_取值缓存': '_value_cache', '_可包装模块属性': '_wrappable_attributes', '_是类': '_is_class', '_有属性': '_has_attributes', '_模块缓存': '_module_cache', '_签名里有': '_signature_contains', '_返回元组长度': '_returns_tuple_length', '位置': 'position', '修复': 'remediation', '值': 'value', '全量检查': 'check_all', '原值': 'original', '参数名': 'parameter_names', '取': 'get', '取值': 'expression', '只列失败': 'failures_only', '名字': 'names', '名字集': 'names', '基': 'base', '基类名': 'base_class_name', '失败': 'failed', '好': 'passed', '官方包前缀': 'OFFICIAL_PACKAGE_PREFIX', '对象': 'value', '属性名': 'attribute_names', '异常': 'exc', '所在模块': 'module_key', '打印': 'print_result', '接口项': 'InterfaceItem', '检查': 'check', '检查一条': 'check_item', '模块': 'MODULES', '模块名': 'module_name', '模块对象': 'module_path', '模块键': 'module_key', '正常': 'passed_count', '清单': 'INTERFACES', '环境': 'namespace', '签名': 'signature', '结果': 'result', '编号': 'identifier', '缺': 'missing', '被谁用': 'consumers', '说明': 'description', '返回': 'result', '键': 'key', '长度': 'length', '项': 'item'}
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
    runpy.run_module("official_interface_inventory", run_name="__main__")
