"""
macos.py —— 平台适配层的 macOS 实现

★ 它的写法是**薄委托**：真正的窗口逻辑仍然在 `软件/宿主窗口.py`（那是 P3-a 的成果，
  实测 60.0 fps、状态一步不漏）。这一层只做两件事：
    ① 把"平台能力"这套接口翻译成 宿主窗口 的调用
    ② 把"能不能用"变成**可查询**的（缺 PyObjC 时给结论，而不是抛栈）

  为什么不在这一层重写窗口：P3-a 的坑（NSTimer 不触发、GL 上下文建用同线程、
  delegate 抛异常静默失效…）都是真金白银换来的，重写等于把坑再踩一遍。
"""
from __future__ import annotations

from typing import Any

from .契约 import 平台能力


class MacOS(平台能力):
    名称 = "macOS（PyObjC + AppKit/WebKit）"

    def 可用(self) -> tuple[bool, str]:
        try:
            import objc  # noqa: F401
            import AppKit  # noqa: F401
            import WebKit  # noqa: F401
        except ImportError as 异常:
            return False, (
                f"缺 PyObjC 组件（{type(异常).__name__}: {异常}）。\n"
                f"      装：.venv/bin/python -m pip install "
                f"pyobjc-framework-Cocoa pyobjc-framework-WebKit pyobjc-framework-Quartz\n"
                f"      临时替代：软件/主程序Web.py（用外部浏览器看同一个界面）")
        return True, ""

    def 起(self, *, 地址: str, 标题: str, 宽: float, 高: float,
           命令队列: list | None = None, 无3D: bool = False,
           视口槽: dict | None = None) -> int:
        可用, 原因 = self.可用()
        if not 可用:
            raise SystemExit(f"✗ 起不了窗口：{原因}")

        import 宿主窗口

        # 视口槽由 宿主窗口 的**模块级**变量承载：窗口是单例形态（一个进程一个窗口），
        # 用模块级最简单，也避免把 PyObjC 对象塞进 Python 对象的属性里。
        if 视口槽 is not None:
            宿主窗口.视口槽 = 视口槽

        return 宿主窗口.跑(地址, 标题=标题, 宽=宽, 高=高,
                         命令队列=命令队列, 无3D=无3D)

    def 视口矩形(self) -> tuple[int, int, int, int] | None:
        try:
            import 宿主窗口
            return 宿主窗口.取视口矩形()
        except Exception:                                             # noqa: BLE001
            return None

    def 统计(self) -> dict:
        try:
            import 宿主窗口
            return 宿主窗口.取统计()
        except Exception as 异常:                                     # noqa: BLE001
            return {"错误": f"{type(异常).__name__}: {异常}"}
