"""English public API for validated GUI-to-simulation commands."""
from __future__ import annotations

import 命令桥 as _legacy


create_message = _legacy.造消息
status = _legacy.状态


def enqueue_command(queue, topic_name: str, payload: dict,
                    print_result: bool = True) -> tuple[bool, str]:
    return _legacy.命令入队(queue, topic_name, payload, 打印=print_result)


def drain_and_inject(queue, print_result: bool = True) -> int:
    return _legacy.排空并注入(queue, 打印=print_result)


def forward_pending_commands(viewer, print_result: bool = True) -> int:
    return _legacy.转发待发命令(viewer, 打印=print_result)


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = [
    "create_message", "enqueue_command", "drain_and_inject",
    "forward_pending_commands", "status",
]
