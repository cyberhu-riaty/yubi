"""
平台适配层 —— 换一个平台，最少要实现什么？

    from platform_adapters import get_implementation
    platform = get_implementation()
    available, reason = platform.is_available()

平台接口见 `interface.py`，各平台实现在同目录的独立模块里。

★ macOS 实现委托 `软件/native_host.py`；Windows 实现使用 PySide6。
  两边都遵守同一契约，入口和仿真业务不需要知道窗口由什么技术实现。
"""
from __future__ import annotations

import sys

from .interface import PlatformCapabilities

__all__ = ["get_implementation", "available_platforms", "describe", "PlatformCapabilities", "UnavailablePlatform"]


class UnavailablePlatform(RuntimeError):
    """当前系统没有可用的窗口实现。"""


_cache: dict[str, PlatformCapabilities] = {}


def available_platforms() -> list[str]:
    """返回当前系统上**登记过**的平台名（不代表它现在能用，见 `可用()`）。"""
    return ["macos", "windows"]


def get_implementation() -> PlatformCapabilities:
    """按当前系统取实现。取不到抛 `无可用平台`（带人话说明）。"""
    key = sys.platform
    if key in _cache:
        return _cache[key]
    if key == "darwin":
        from .macos import MacOS
        instance: PlatformCapabilities = MacOS()
    elif key == "win32":
        from .windows import Windows
        instance = Windows()
    else:
        raise UnavailablePlatform(
            f"当前系统 {sys.platform!r} 还没有窗口实现。\n"
            f"  已实现：macOS（darwin）、Windows（win32）\n"
            f"  要加一个平台：在 `软件/platform_adapters/` 中实现 "
            f"`interface.PlatformCapabilities`。\n"
            f"  临时替代：run_yubi_web.py（用外部浏览器看同一个界面，跨平台可用）")
    _cache[key] = instance
    return instance


def describe() -> str:
    """一行可读的能力说明（自检与日志用）。"""
    try:
        platform = get_implementation()
    except UnavailablePlatform as exc:
        return f'✗ 无可用平台：{exc}'
    is_available, reason = platform.is_available()
    return f"{('✓' if is_available else '✗')} {platform.name}" + (f'（{reason}）' if reason else "")


