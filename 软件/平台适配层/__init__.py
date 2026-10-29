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

from .契约 import 平台能力

__all__ = ["取实现", "可用平台", "说明", "平台能力", "无可用平台"]


class 无可用平台(RuntimeError):
    """当前系统没有可用的窗口实现。"""


_缓存: dict[str, 平台能力] = {}


def 可用平台() -> list[str]:
    """返回当前系统上**登记过**的平台名（不代表它现在能用，见 `可用()`）。"""
    return ["macos", "windows"]


def 取实现() -> 平台能力:
    """按当前系统取实现。取不到抛 `无可用平台`（带人话说明）。"""
    键 = sys.platform
    if 键 in _缓存:
        return _缓存[键]
    if 键 == "darwin":
        from .macos import MacOS
        实例: 平台能力 = MacOS()
    elif 键 == "win32":
        from .windows import Windows
        实例 = Windows()
    else:
        raise 无可用平台(
            f"当前系统 {sys.platform!r} 还没有窗口实现。\n"
            f"  已实现：macOS（darwin）、Windows（win32）\n"
            f"  要加一个平台：在 `软件/平台适配层/` 里仿照 macos.py 实现"
            f"`契约.平台能力` 的那几个方法即可（只有五个：建窗口/挂网页/"
            f"取视口矩形/同级组合/进主循环）。\n"
            f"  临时替代：软件/主程序Web.py（用外部浏览器看同一个界面，跨平台可用）")
    _缓存[键] = 实例
    return 实例


def 说明() -> str:
    """一行可读的能力说明（自检与日志用）。"""
    try:
        平台 = 取实现()
    except 无可用平台 as 异常:
        return f"✗ 无可用平台：{异常}"
    可用, 原因 = 平台.可用()
    return f"{'✓' if 可用 else '✗'} {平台.名称}" + (f"（{原因}）" if 原因 else "")
