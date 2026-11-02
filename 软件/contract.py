"""English public API for the backend/frontend message contract."""
from __future__ import annotations

import 契约 as _legacy


VERSION = _legacy.版本
Field = _legacy.字段
Topic = _legacy.主题
ALL_TOPICS = _legacy.所有主题
OUTBOUND_TOPICS = _legacy.下行主题
INBOUND_TOPICS = _legacy.上行主题
BY_NAME = _legacy.按名
BY_CLASS_NAME = _legacy.按类名

get_topic = _legacy.取
type_markers = _legacy.类型记号们
to_dict = _legacy.转字典
class_name_to_topic = _legacy.类名到主题
validate = _legacy.校验
find_drift = _legacy.查漂移


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = [
    "VERSION", "Field", "Topic", "ALL_TOPICS", "OUTBOUND_TOPICS",
    "INBOUND_TOPICS", "BY_NAME", "BY_CLASS_NAME", "get_topic", "type_markers",
    "to_dict", "class_name_to_topic", "validate", "find_drift",
]
