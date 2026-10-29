"""主程序入口的控制台兼容处理。"""
from __future__ import annotations

import os
import sys


def 准备输出() -> None:
    """避免 Windows 默认 GBK 因界面日志中的 Unicode 符号而退出。"""
    if os.name != "nt":
        return
    for 流 in (sys.stdout, sys.stderr):
        try:
            流.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # IDE、测试框架可能把标准输出替换成不支持 reconfigure 的对象。
            pass
