"""
平台适配层 —— 换一个平台，最少要实现什么？

    from 平台适配层 import 取实现, 说明
    平台 = 取实现()                 # 按 sys.platform 选实现
    可用, 原因 = 平台.可用()         # **起窗口之前**就能问
    平台.起(地址=..., 标题=..., 宽=..., 高=...)

四个能力（+ 主循环）的约定见 `契约.py`；各平台实现在同目录的独立模块里。

★ macOS 实现继续委托 `软件/宿主窗口.py`；Windows 实现使用 PySide6。
  两边都遵守同一契约，入口和仿真业务不需要知道窗口由什么技术实现。
"""
from __future__ import annotations

import sys

from .interface import PlatformCapabilities

__all__ = ["get_implementation", "available_platforms", "describe", "PlatformCapabilities", "UnavailablePlatform", "is_available", "display_name", "run", "push_viewport_state"]


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
            f"  要加一个平台：在 `软件/平台适配层/` 里仿照 macos.py 实现"
            f"`契约.平台能力` 的那几个方法即可（只有五个：建窗口/挂网页/"
            f"取视口矩形/同级组合/进主循环）。\n"
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


def is_available(implementation) -> tuple[bool, str]:
    return implementation.is_available()


def display_name(implementation) -> str:
    return str(implementation.name)


def run(implementation, *, url: str, title: str, width: float, height: float,
        command_queue, no_3d: bool, viewport_slot) -> int:
    return implementation.run(url=url, title=title, width=width, height=height,
                              command_queue=command_queue, no_3d=no_3d,
                              viewport_slot=viewport_slot)


def push_viewport_state(viewport, snapshot) -> None:
    viewport.receive_state(snapshot)
