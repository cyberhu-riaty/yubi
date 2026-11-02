"""English public API for selecting the native desktop platform adapter."""
from __future__ import annotations

import 平台适配层 as _legacy


UnavailablePlatform = _legacy.无可用平台
available_platforms = _legacy.可用平台
get_implementation = _legacy.取实现
describe = _legacy.说明


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = ["UnavailablePlatform", "available_platforms", "get_implementation", "describe"]
