"""English public API for validated GUI-to-simulation commands."""
from __future__ import annotations

import 命令桥 as _legacy


create_message = _legacy.造消息
enqueue_command = _legacy.命令入队
drain_and_inject = _legacy.排空并注入
forward_pending_commands = _legacy.转发待发命令
status = _legacy.状态


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = [
    "create_message", "enqueue_command", "drain_and_inject",
    "forward_pending_commands", "status",
]
