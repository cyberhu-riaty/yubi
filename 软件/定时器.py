"""
定时器.py —— 一个**在本机真的会触发**的 run loop 定时器

为什么需要它（这是 P3 花时间最多的一个坑，值得单独成文）：
    PyObjC 的 `NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_`
    在本机**完全不触发** —— 中文方法名（`画一帧_:`）和 ASCII 方法名（`probeTick_:`）都试过，
    **而且不报任何错**：`isValid()` 返回 True、对象正常、就是不回调。

    这个坑极难发现，因为它伪装成别的问题：
      · P2 的 spike 看起来"能跑"（`GL 实际出帧数 350`），但那是**窗口系统的 drawRect_
        自己在画**（`setNeedsDisplay_` 由窗口系统驱动），**跟定时器无关**；
      · P2 验收里的 60.1 fps 也是这么来的。
      · 于是"验收通过"了，而真正依赖定时器的东西（每帧同步状态、排空命令）一直没跑。

    判别方法（一条命令）：往一个能跑的界面里插一个 0.8 秒一次性定时器，
    看它有没有打印。不打印 = 定时器这条路不可用。

    解法：用 **CoreFoundation 的 `CFRunLoopTimer`** —— 它走纯 C 回调，不过 PyObjC 的
    选择器机制。实测稳定触发（见 `工具/spike/` 的验证记录与本文件末尾自测）。

用法：
    定时器 = 起(1.0 / 60.0, 每帧函数)        # 返回句柄
    定时器.停()
    一次性(0.5, 某函数)
"""
from __future__ import annotations

import objc
from Foundation import NSRunLoop
from Quartz import (CFAbsoluteTimeGetCurrent, CFRunLoopAddTimer, CFRunLoopGetCurrent,
                    CFRunLoopRemoveTimer, CFRunLoopTimerCreate, kCFRunLoopDefaultMode)

# ★ 回调**直接传 Python 函数**即可 —— PyObjC 会按 `CFRunLoopTimerCreate` 的元数据
#   自动包装。不要自己造 `objc.FUNCTYPE`（本机 PyObjC 12 没这个名字）或
#   `ctypes.CFUNCTYPE`（PyObjC 拒收，报 "argument 1: TypeError: wrong type"）。
_保活: list = []          # 回调对象必须一直被引用，否则会被回收、定时器随即失效


def 起(间隔秒: float, 函数, 首次延迟: float | None = None) -> "句柄":
    """起一个**重复**的 run loop 定时器。`函数()` 不接受参数。"""
    return _起(间隔秒, 函数, 重复=True, 首次延迟=首次延迟)


def 一次性(延迟秒: float, 函数) -> "句柄":
    """起一个只触发一次的定时器。"""
    return _起(延迟秒, 函数, 重复=False, 首次延迟=延迟秒)


class 句柄:
    def __init__(self, 定时器, 回调):
        self._定时器 = 定时器
        self._回调 = 回调
        self._已停 = False

    def 停(self) -> None:
        if self._已停:
            return
        self._已停 = True
        try:
            CFRunLoopRemoveTimer(CFRunLoopGetCurrent(), self._定时器, kCFRunLoopDefaultMode)
        except Exception:                                             # noqa: BLE001
            pass


def _起(间隔秒: float, 函数, 重复: bool, 首次延迟: float | None) -> 句柄:
    间隔 = max(1e-4, float(间隔秒))
    延迟 = float(首次延迟) if 首次延迟 is not None else 间隔

    def 包装(_定时器, _信息):
        try:
            函数()
        except Exception as 异常:                                     # noqa: BLE001
            # 回调里出错绝不能把 run loop 弄崩；打一次就够，避免刷屏
            if not getattr(包装, "_报过错", False):
                包装._报过错 = True
                print(f"⚠ 定时器回调出错（后续不再重复报）："
                      f"{type(异常).__name__}: {异常}", flush=True)

    回调 = 包装
    _保活.append(回调)
    del _保活[:-64]                                   # 只留最近 64 个，别无限增长
    定时器 = CFRunLoopTimerCreate(
        None,
        CFAbsoluteTimeGetCurrent() + 延迟,
        间隔 if 重复 else 0,                          # interval=0 → 只触发一次
        0, 0, 回调, None)
    # ★ 关键：不仅要加到 default mode，还要加到**所有 common modes**。
    #   实测：只加 default mode 时，AppKit 的活动（窗口拖动、菜单跟踪、事件等待）
    #   会把 run loop 切到 `NSEventTrackingRunLoopMode` 等别的 mode，
    #   于是定时器**在那些 mode 下完全不触发** —— 表现为"窗口在、界面不动"，
    #   而且不报任何错。`NSRunLoopCommonModes` 是 Cocoa 给的标准做法。
    循环 = CFRunLoopGetCurrent()
    CFRunLoopAddTimer(循环, 定时器, kCFRunLoopDefaultMode)
    # ⚠️ 别在这里 print 循环对象。排查时我曾打过一行
    #    `print(f"... {循环} ...")`，而 `CFRunLoop` 的 `__str__` 会把**整个 run loop
    #    （所有 source / observer / timer / mode）dump 出来**，一次几十行。
    #    日志因此被彻底淹没（真正有用的诊断被埋在中间）。
    try:
        CFRunLoopAddTimer(循环, 定时器, "kCFRunLoopCommonModes")
    except Exception:                                                 # noqa: BLE001
        pass
    return 句柄(定时器, 回调)


# ---------------------------------------------------------------------------
# 自测：不依赖任何界面，直接泵 run loop 看定时器会不会来
#   .venv/bin/python 软件/定时器.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from Quartz import CFRunLoopRunInMode

    计数 = {"重复": 0, "一次": 0}
    甲 = 起(0.05, lambda: 计数.__setitem__("重复", 计数["重复"] + 1))
    乙 = 一次性(0.4, lambda: 计数.__setitem__("一次", 计数["一次"] + 1))

    print("=" * 62)
    print("  定时器自测（泵 run loop 1 秒）")
    print("=" * 62)
    结束 = CFAbsoluteTimeGetCurrent() + 1.0
    while CFAbsoluteTimeGetCurrent() < 结束:
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.02, False)
    甲.停()
    print(f"  重复定时器（50ms）：触发 {计数['重复']} 次（期望约 20）")
    print(f"  一次性定时器（400ms）：触发 {计数['一次']} 次（期望 1）")
    好 = 计数["重复"] >= 10 and 计数["一次"] == 1
    print(f"\n  结论：{'✓ 可用' if 好 else '✗ 不可用'}")
    raise SystemExit(0 if 好 else 1)
