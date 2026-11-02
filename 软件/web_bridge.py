"""English public API for the local HTTP/WebSocket bridge."""
from __future__ import annotations

import Web桥 as _legacy


DEFAULT_PORT = _legacy.默认端口
DEFAULT_HOST = _legacy.默认主机
FRONTEND_DIRECTORY = _legacy.前端目录

Server = _legacy.服务端
Faucet = _legacy.水龙头
publish = _legacy.投递
health = _legacy.健康
close = _legacy.关闭
get_faucet = _legacy.取水龙头
get_commands = _legacy.取命令
record_dispatch = _legacy.记派发
install_faucet = _legacy.安装水龙头


def start(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST) -> Server:
    """Start the local bridge using English keyword names."""
    return _legacy.启动(端口=port, 主机=host)


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = [
    "DEFAULT_PORT", "DEFAULT_HOST", "FRONTEND_DIRECTORY", "Server", "Faucet",
    "start", "publish", "health", "close", "get_faucet", "get_commands",
    "record_dispatch", "install_faucet",
]
