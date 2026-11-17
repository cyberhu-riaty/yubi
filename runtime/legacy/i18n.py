"""Legacy naming compatibility; new code imports i18n."""
from __future__ import annotations

from functools import wraps
import i18n as _implementation

_ALIASES = {'_写设置': '_write_settings', '_包根': '_package_root', '_读设置': '_read_settings', '不改': 'UNTRANSLATED_LABELS', '中文': 'ZH', '值': 'values', '写存档': 'write_saved_language', '决定启动语言': 'resolve_startup_language', '切换': 'toggle_language', '别名': 'aliases', '原文': 'original', '取': 'get_text', '另一个': 'other_language', '合法语言': 'SUPPORTED_LANGUAGES', '名': 'name', '命令行语言': 'cli_language', '字体有汉字': 'font_has_cjk', '存档': 'saved', '对': 'pair', '异常': 'exc', '当前语言': 'current_language', '数据': 'data', '文本': 'text', '文案默认语言': 'DEFAULT_LANGUAGE', '有': 'has_text', '格式化': 'format_text', '状态': 'translate_status', '环境': 'environment', '界面文字': 'ascii_text', '英文': 'EN', '表': 'TEXT', '记住': 'remember', '设置路径': 'SETTINGS_PATH', '设语言': 'set_language', '语': 'language_code', '语言': 'language', '语言名': 'LANGUAGE_NAMES', '语言显示名': 'language_display_name', '读存档': 'read_saved_language', '量宽': 'measure_width', '键': 'key', '面板名': 'panel_name', '面板名表': 'PANEL_NAMES', '默认': 'default'}
_KEYWORDS = {'_写设置': '_write_settings', '_包根': '_package_root', '_读设置': '_read_settings', '不改': 'UNTRANSLATED_LABELS', '中文': 'ZH', '值': 'values', '写存档': 'write_saved_language', '决定启动语言': 'resolve_startup_language', '切换': 'toggle_language', '别名': 'aliases', '原文': 'original', '取': 'get_text', '另一个': 'other_language', '合法语言': 'SUPPORTED_LANGUAGES', '名': 'name', '命令行语言': 'cli_language', '字体有汉字': 'font_has_cjk', '存档': 'saved', '对': 'pair', '异常': 'exc', '当前语言': 'current_language', '数据': 'data', '文本': 'text', '文案默认语言': 'DEFAULT_LANGUAGE', '有': 'has_text', '格式化': 'format_text', '状态': 'translate_status', '环境': 'environment', '界面文字': 'ascii_text', '英文': 'EN', '表': 'TEXT', '记住': 'remember', '设置路径': 'SETTINGS_PATH', '设语言': 'set_language', '语': 'language_code', '语言': 'language', '语言名': 'LANGUAGE_NAMES', '语言显示名': 'language_display_name', '读存档': 'read_saved_language', '量宽': 'measure_width', '键': 'key', '面板名': 'panel_name', '面板名表': 'PANEL_NAMES', '默认': 'default'}

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
    runpy.run_module("i18n", run_name="__main__")
