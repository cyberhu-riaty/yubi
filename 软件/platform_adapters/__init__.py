"""English public API for selecting the native desktop platform adapter."""
from __future__ import annotations

import 平台适配层 as _legacy


UnavailablePlatform = _legacy.无可用平台
available_platforms = _legacy.可用平台
get_implementation = _legacy.取实现
describe = _legacy.说明


def is_available(implementation) -> tuple[bool, str]:
    return implementation.可用()


def display_name(implementation) -> str:
    return str(implementation.名称)


def run(implementation, *, url: str, title: str, width: float, height: float,
        command_queue, no_3d: bool, viewport_slot) -> int:
    return implementation.起(
        地址=url,
        标题=title,
        宽=width,
        高=height,
        命令队列=command_queue,
        无3D=no_3d,
        视口槽=viewport_slot,
    )


def push_viewport_state(viewport, snapshot) -> None:
    viewport.收_状态(snapshot)


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = [
    "UnavailablePlatform", "available_platforms", "get_implementation", "describe",
    "is_available", "display_name", "run", "push_viewport_state",
]
