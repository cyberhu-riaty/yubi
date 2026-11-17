"""
macos.py —— 平台适配层的 macOS 实现

★ 它的写法是**薄委托**：真正的窗口逻辑仍然在 `runtime/宿主窗口.py`（那是 P3-a 的成果，
  实测 60.0 fps、状态一步不漏）。这一层只做两件事：
    ① 把"平台能力"这套接口翻译成 宿主窗口 的调用
    ② 把"能不能用"变成**可查询**的（缺 PyObjC 时给结论，而不是抛栈）

  为什么不在这一层重写窗口：P3-a 的坑（NSTimer 不触发、GL 上下文建用同线程、
  delegate 抛异常静默失效…）都是真金白银换来的，重写等于把坑再踩一遍。
"""
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
