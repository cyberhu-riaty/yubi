"""
菜单栏.py —— 把 `Appearance` / `Panels` 两个菜单挂进**官方那一行**（File / Simulation / View / Help 右边）

★ 为什么必须这样挂（实测结论，改之前先看）：
    官方菜单栏是 `viewer_app.build_gui()` 里 `BeginMainMenuBar() … EndMainMenuBar()` 画的。
    我们的处理器排在官方之后（`Priority.INTERNAL` 之后），那时菜单栏**已经关掉了** ——
    旧容器那个 `Panels` 菜单就是这么写的：实测它**一个条目都没提交过**，等于从来没画出来。
    包装 `imgui.EndMainMenuBar`（官方每帧必调）就能在"关掉之前"把菜单插进去：
    实测条目落在顶行 `y=1`、尺寸 `79×20`，和 File/Help 同一行。

★ 两条硬要求：
    ① **幂等**：反复调 `安装包装()` 只包一层（包两层会让菜单画两遍）。
    ② **无 ImGui 上下文时什么都不做**：那个绑定在没有上下文时调用任何 imgui 函数会
       **直接段错误**（实测），而本模块会被"不开窗"的自检脚本导入并调用。

★ 安装时机：必须在**第一帧之前**。由 `面板/侧栏.py` 的 `__init__` 调用（它在窗口起来之前执行）。
"""
from __future__ import annotations

import os as _os
import sys as _sys

_外壳目录 = _os.path.dirname(_os.path.abspath(__file__))
if _外壳目录 not in _sys.path:
    _sys.path.insert(0, _外壳目录)
_面板目录 = _os.path.join(_外壳目录, "面板")
if _面板目录 not in _sys.path:
    _sys.path.insert(0, _面板目录)

from mujoco.experimental.dear_imgui import dear_imgui as imgui       # noqa: E402

import 皮肤桥                                                         # noqa: E402
import 面板注册表                                                     # noqa: E402

# 官方三套基底主题（皮肤关掉时用它兜底）。键名与 皮肤桥._主题表 一致。
基底主题表 = (("LIGHT", "Light"), ("DARK", "Dark"), ("CLASSIC", "Classic"))

已安装 = False
_原结束菜单栏 = None
_出错次数 = 0


def _有界面上下文() -> bool:
    """ImGui 上下文在不在（没有时绝不能碰 imgui）。

    ★ 任务 3 会把这一小段统一到 `面板注册表.有界面上下文()`，避免三处各写一份。
    """
    try:
        问 = getattr(imgui, "GetCurrentContext", None)
        return bool(问()) if 问 is not None else False
    except Exception:                                                    # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# 外观开关：那个"完整外观面板"（色卡/实时预览/FPS）的小窗口开不开
# ---------------------------------------------------------------------------
def 外观面板可见() -> bool:
    return 皮肤桥.完整面板可见()


def 设外观面板可见(值: bool) -> None:
    皮肤桥.设完整面板可见(bool(值))
    print(f"【菜单栏】外观面板（完整版）→ {'打开' if 值 else '关闭'}", flush=True)


# ---------------------------------------------------------------------------
# 给绘制用的只读快照（自检脚本直接测它，不用开窗）
# ---------------------------------------------------------------------------
def 菜单数据() -> dict:
    """{"皮肤": [(键, 显示名, 是否当前), …], "基底": [(键, 显示名, 是否当前), …], "外观面板": bool}"""
    皮肤 = [(名, 皮肤桥.界面名(名), 名 == 皮肤桥.当前风格) for 名 in 皮肤桥.选择项()]
    当前基底 = 皮肤桥.用户基底主题()
    基底 = [(键, 显示, 键 == 当前基底) for 键, 显示 in 基底主题表]
    return {"皮肤": 皮肤, "基底": 基底, "外观面板": 皮肤桥.完整面板可见()}


# ---------------------------------------------------------------------------
# 画菜单（只允许在"官方菜单栏关掉之前"这一刻调用）
# ---------------------------------------------------------------------------
def _画外观菜单() -> None:
    if not imgui.BeginMenu("Appearance"):
        return
    数据 = 菜单数据()
    开 = bool(数据["外观面板"])
    if imgui.MenuItem("Open Appearance panel (swatches / preview / FPS)", "", 开):
        设外观面板可见(not 开)
    imgui.Separator()
    imgui.TextDisabled("  skin (ours)      F10 cycles")
    for 键, 显示, 选中 in 数据["皮肤"]:
        if imgui.MenuItem(f"    {显示}", "", 选中):
            if not 选中:
                皮肤桥.设风格(键)
    imgui.Separator()
    imgui.TextDisabled("  base theme       (used when the skin is off)")
    for 键, 显示, 选中 in 数据["基底"]:
        if imgui.MenuItem(f"    {显示}", "", 选中):
            if not 选中:
                皮肤桥.设用户基底主题(键)
    imgui.EndMenu()


def _画面板菜单() -> None:
    if not imgui.BeginMenu("Panels"):
        return
    if imgui.MenuItem("Reveal all (F9)"):
        面板注册表.全部显示()
    if imgui.MenuItem("Reset panel layout (Shift+F9)"):
        面板注册表.重置版面()
    # ★ 每个面板的「展开 / 钉住」条目由侧栏提供（见 面板注册表.侧栏顺序 / 设展开 / 设钉住）
    侧栏顺序 = getattr(面板注册表, "侧栏顺序", None)
    是钉住 = getattr(面板注册表, "是钉住", None)
    设钉住 = getattr(面板注册表, "设钉住", None)
    设展开 = getattr(面板注册表, "设展开", None)
    if callable(侧栏顺序) and callable(设展开):
        名单 = 侧栏顺序()
        if 名单:
            imgui.Separator()
            imgui.TextDisabled("  panels           (Ctrl+1 .. Ctrl+7)")
            for i, 名 in enumerate(名单):
                快捷键 = f"Ctrl+{i + 1}" if i < 9 else ""
                钉 = bool(是钉住(名)) if callable(是钉住) else False
                if imgui.MenuItem(f"    {名}##菜单展开{i}", 快捷键, 钉):
                    设展开(名)
                if callable(设钉住):
                    挂 = f"pin##菜单钉住{i}"
                    if imgui.MenuItem(f"    {挂}", "", 钉):
                        设钉住(名, not 钉)
    imgui.TextDisabled("  F9 = reveal all   Shift+F9 = reset layout")
    imgui.EndMenu()


def 画菜单() -> None:
    """把两个菜单追加到官方菜单栏右侧（内部函数；由 安装包装 的包装体调用）。"""
    global _出错次数
    try:
        _画外观菜单()
    except Exception as 异常:                                            # noqa: BLE001
        _出错次数 += 1
        if _出错次数 <= 2:
            print(f"⚠ 菜单栏：Appearance 菜单绘制出错（已隔离）：{type(异常).__name__}: {异常}")
    try:
        _画面板菜单()
    except Exception as 异常:                                            # noqa: BLE001
        _出错次数 += 1
        if _出错次数 <= 2:
            print(f"⚠ 菜单栏：Panels 菜单绘制出错（已隔离）：{type(异常).__name__}: {异常}")


# ---------------------------------------------------------------------------
# 安装包装（幂等）
# ---------------------------------------------------------------------------
def 安装包装() -> None:
    """把 `imgui.EndMainMenuBar` 包一层（可以反复调）。"""
    global 已安装, _原结束菜单栏
    if 已安装:
        return
    try:
        原版 = imgui.EndMainMenuBar
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 菜单栏：拿不到 imgui.EndMainMenuBar，Appearance 菜单不会出现（{异常}）")
        return
    _原结束菜单栏 = 原版

    def 包装(*args, **kwargs):
        # ★ 顺序要紧：先把我们的菜单挂进这一行，再让官方真正结束菜单栏
        try:
            if _有界面上下文():
                画菜单()
        except Exception as 异常:                                        # noqa: BLE001
            print(f"⚠ 菜单栏包装体出错（已隔离）：{type(异常).__name__}: {异常}")
        return 原版(*args, **kwargs)

    try:
        imgui.EndMainMenuBar = 包装
        已安装 = True
        print("【菜单栏】Appearance / Panels 已挂进官方菜单栏（与 File / Help 同一行）", flush=True)
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 菜单栏：无法包装 imgui.EndMainMenuBar（Appearance 菜单不会出现）：{异常}")
