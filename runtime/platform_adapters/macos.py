"""macOS 平台适配，探测 PyObjC 依赖并委托 native_host 管理窗口。"""
from __future__ import annotations

from typing import Any

from .interface import PlatformCapabilities


class MacOS(PlatformCapabilities):
    name = "macOS（PyObjC + AppKit/WebKit）"

    def is_available(self) -> tuple[bool, str]:
        try:
            import objc  # noqa: F401
            import AppKit  # noqa: F401
            import WebKit  # noqa: F401
        except ImportError as exc:
            return False, (
                f'缺 PyObjC 组件（{type(exc).__name__}: {exc}）。\n'
                f"      装：.venv/bin/python -m pip install "
                f"pyobjc-framework-Cocoa pyobjc-framework-WebKit pyobjc-framework-Quartz\n"
                f"      临时替代：run_yubi_web.py（用外部浏览器看同一个界面）")
        return True, ""

    def run(self, *, url: str, title: str, width: float, height: float,
           command_queue: Any = None, no_3d: bool = False,
           viewport_slot: dict | None = None) -> int:
        is_available, reason = self.is_available()
        if not is_available:
            raise SystemExit(f'✗ 起不了窗口：{reason}')

        import native_host

        # 视口槽由 宿主窗口 的**模块级**变量承载：窗口是单例形态（一个进程一个窗口），
        # 用模块级最简单，也避免把 PyObjC 对象塞进 Python 对象的属性里。
        if viewport_slot is not None:
            native_host.viewport_slot = viewport_slot

        return native_host.run(url, title=title, width=width, height=height,
                         command_queue=command_queue, no_3d=no_3d)

    def viewport_rectangle(self) -> tuple[int, int, int, int] | None:
        try:
            import native_host
            return native_host.get_viewport_rectangle()
        except Exception:                                             # noqa: BLE001
            return None

    def statistics(self) -> dict:
        try:
            import native_host
            return native_host.get_statistics()
        except Exception as exc:                                     # noqa: BLE001
            return {'error': f'{type(exc).__name__}: {exc}'}
