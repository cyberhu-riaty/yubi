"""Legacy naming compatibility; new code imports ascii_text."""
from __future__ import annotations

from functools import wraps
import ascii_text as _implementation

_ALIASES = {'_不支持': '_unsupported', '_单位表': '_unit_rules', '_已提醒': '_warned', '_有中文': '_chinese_pattern', '_短语表': '_phrases', '中': 'chinese', '允许的非ASCII': 'ALLOWED_NON_ASCII', '关键': 'key', '原样': 'original', '可用': 'is_supported', '安全': 'sanitize', '换过': 'translated', '提醒一次': 'warn_once', '文本': 'text', '替代': 'replacement', '替换': 'replacement', '有非ASCII': 'contains_non_ascii', '术语表': 'TERMS', '结果': 'result', '英': 'english', '英文': 'to_english', '规则': 'pattern', '默认': 'default'}
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
    runpy.run_module("ascii_text", run_name="__main__")
