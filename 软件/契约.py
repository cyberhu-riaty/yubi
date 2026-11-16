"""Legacy names for contract metadata; new application code imports contract.

The compatibility properties and constructor keywords support old extensions.
Wire serialization remains owned by contract.to_dict().
"""
from __future__ import annotations

from functools import wraps
import contract as _contract


_FIELD_ALIASES = {"名": "name", "类型": "type", "说明": "description"}
_TOPIC_ALIASES = {
    "名": "name", "类名": "class_name", "方向": "direction",
    "种类": "kind", "摘要": "summary", "字段": "fields",
}
_LEGACY_EXPORTS = {
    "版本": "VERSION", "字段": "Field", "主题": "Topic",
    "_下行": "_OUTBOUND", "_上行": "_INBOUND",
    "所有主题": "ALL_TOPICS", "下行主题": "OUTBOUND_TOPICS", "上行主题": "INBOUND_TOPICS",
    "按名": "BY_NAME", "按类名": "BY_CLASS_NAME", "取": "get_topic",
    "类型记号们": "type_markers", "转字典": "to_dict", "_符合": "_matches_type",
    "_枚举": "_ENUM_VALUES", "_范围": "_VALUE_RANGES",
    "类名到主题": "class_name_to_topic", "校验": "validate", "查漂移": "find_drift",
}


def _accept_legacy_keywords(function, aliases):
    @wraps(function)
    def call(*args, **kwargs):
        mapped = {}
        for key, value in kwargs.items():
            name = aliases.get(key, key)
            if name in mapped:
                raise TypeError(f"Multiple values for argument {name!r}")
            mapped[name] = value
        return function(*args, **mapped)
    return call


def _install_metadata_aliases(cls, aliases):
    if not getattr(cls.__init__, "_legacy_keywords_installed", False):
        initializer = _accept_legacy_keywords(cls.__init__, aliases)
        initializer._legacy_keywords_installed = True
        cls.__init__ = initializer
    for old_name, name in aliases.items():
        setattr(cls, old_name, property(lambda instance, key=name: getattr(instance, key)))


_install_metadata_aliases(_contract.Field, _FIELD_ALIASES)
_install_metadata_aliases(_contract.Topic, _TOPIC_ALIASES)
_LEGACY_FUNCTIONS = {
    "取": _accept_legacy_keywords(_contract.get_topic, {"名": "name"}),
    "_符合": _accept_legacy_keywords(_contract._matches_type, {"值": "value", "类型": "type_marker"}),
    "校验": _accept_legacy_keywords(_contract.validate, {"主题名": "topic_name", "负载": "payload"}),
}
__all__ = [*_contract.__all__, *[name for name in _LEGACY_EXPORTS if not name.startswith("_")]]


def __getattr__(name: str):
    if name in _LEGACY_FUNCTIONS:
        return _LEGACY_FUNCTIONS[name]
    return getattr(_contract, _LEGACY_EXPORTS.get(name, name))


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_contract)) | set(_LEGACY_EXPORTS))


if __name__ == "__main__":
    import runpy
    runpy.run_module("contract", run_name="__main__")
