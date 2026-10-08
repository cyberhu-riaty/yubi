"""
面板/面板窗.py —— 【Panels】窗口：钉在右栏、紧挨官方 `Inspector` 页签的一个"假页签" + 竖排折叠列表

它取代了两件事（都已完成历史使命）：
  · 旧的【工作台】页签容器（面板容器.py，2026-10-06 删）
  · 中间过渡版的"两条 26px 侧栏按钮条"（用户反馈：Panels 菜单里已经有面板名，两边再放一排按钮是多余的）

★ 为什么是"**假**页签"（改之前必读）：
    用户要的位置是"紧挨着官方 Inspector 页签的空位"，那属于**官方 Dockspace 的页签栏**。
    而我们已经用 9 组现场实验证明：**自研窗口停靠不进官方 Dockspace**
    （`DockId` 记得住但 ImGui 永不启用；手写 ini 造的节点会被剪掉；整套重建的版面下一帧被官方抢回去）。
    证据：`优化（软件优化的报告都放这里面来）/报告/界面侧栏改造_设计规格.md` §1.2。
    所以这里换一条路：**画一个跟官方页签长得一样的按钮**，位置紧挨着 `Inspector`，
    内容窗摆在页签栏正下方（右栏内）——
        · 点我们的页签 → 开/关面板窗
        · 点官方 `Inspector` 页签那一小块 → 自动关掉面板窗（让官方内容露出来）
    于是那一行看起来就是 `[Inspector][Panels]` 两个页签，行为也是互斥切换的。

★ 两个必须记住的绘制细节：
    ① 本面板的 `画面板` 注册在 **priority=0（官方 INTERNAL 之后）**：只有这样我们的窗口才会
       被 ImGui **后画**、从而盖在官方 Inspector 内容之上。默认优先级（USER）是在官方之前，
       那样面板窗会被官方面板盖住（看不见）。
    ② 窗口矩形每帧从官方 `ux.configure_docking_layout()` 返回的 3D 矩形 + 窗口宽度反推
       （右栏 = 3D 矩形右边界 .. 窗口右边界），官方改版面我们不用改代码。
"""
from __future__ import annotations

import os as _os
import sys as _sys

_外壳目录 = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _外壳目录 not in _sys.path:
    _sys.path.insert(0, _外壳目录)
_面板目录 = _os.path.dirname(_os.path.abspath(__file__))
if _面板目录 not in _sys.path:
    _sys.path.insert(0, _面板目录)

from mujoco.experimental.dear_imgui import dear_imgui as imgui       # noqa: E402
from mujoco.experimental.studio import messages, viewer_protocol      # noqa: E402

import 面板注册表                                                     # noqa: E402
import 菜单栏                                                         # noqa: E402

# ---------------------------------------------------------------------------
# 常量（与 验证/面板窗自检.py 同步；这些是"看起来对不对"的量，改前先量一下）
# ---------------------------------------------------------------------------
页签条高 = 24.0          # 官方页签栏那一行的高度（菜单栏 24 + 页签条 ≈ 24）
# ★ 官方 `Inspector` 页签实际占多宽：**这个值是按用户截屏校准的，不是按字体算的**。
#   实测字号 16、CalcTextSize("Inspector")=52、FramePadding.x=7（按公式只有 67），
#   但截屏里那个页签块实际约 118px 宽 —— 所以别用公式，用这个常量。
#   调法：我们的页签跟官方页签**叠在一起**就调大，**离得太远**就调小（唯一的一个旋钮）。
官方页签宽 = 124.0
页签最小宽 = 56.0
最小可画宽 = 120.0
最小可画高 = 200.0


# ---------------------------------------------------------------------------
# 纯函数：几何（不碰 imgui，能被自检脚本逐条钉住）
# ---------------------------------------------------------------------------
def 右栏矩形(三D: tuple[float, float, float, float],
            窗口宽: float) -> tuple[float, float, float, float]:
    """官方右栏（Inspector 那一列）的矩形：3D 区右边界到窗口右边界。"""
    x, y, 宽, 高 = (float(v) for v in 三D)
    return (x + 宽, y, max(0.0, float(窗口宽) - (x + 宽)), 高)


def 算页签条矩形(三D, 窗口宽) -> tuple[float, float, float, float]:
    """整条页签栏（右栏那一行）—— **由我们接管**，所以点击一定落在我们手上。

    ★ 为什么接管整条而不是只放一个小页签：只放小页签时，"点官方 Inspector 切回去"
      要靠"鼠标坐标是否落在官方页签上"来猜 —— 实测点不动（用户反馈"inspector 怎么点不了了"）。
      接管整条之后，`Inspector` / `Panels` 两个格都由我们画、都由我们收点击，切换必定生效。
    """
    x, y, 宽, _ = 右栏矩形(三D, 窗口宽)
    if 宽 <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (x, y, 宽, 页签条高)


def 算页签格矩形(三D, 窗口宽, 序号: int, 文字宽: float = 46.0) -> tuple[float, float, float, float]:
    """页签栏里的第 N 格：0 = 官方 `Inspector`，1 = 我们的 `Panels`。"""
    x, y, 宽, 高 = 算页签条矩形(三D, 窗口宽)
    if 宽 <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    官方宽 = min(官方页签宽, max(页签最小宽, 宽 - 页签最小宽 - 6.0))
    if 序号 == 0:
        return (x, y, 官方宽, 高)
    余 = max(0.0, 宽 - 官方宽 - 2.0)
    页宽 = max(页签最小宽, min(float(文字宽) + 24.0, 余)) if 余 > 0 else 0.0
    return (x + 官方宽 + 2.0, y, 页宽, 高)


def 官方页签矩形(三D, 窗口宽) -> tuple[float, float, float, float]:
    """官方 `Inspector` 那一格（保留旧名，自检与说明都还在用）。"""
    return 算页签格矩形(三D, 窗口宽, 0)


def 算面板窗矩形(三D, 窗口宽) -> tuple[float, float, float, float]:
    """面板内容窗：右栏内、页签条正下方（盖住官方 Inspector 的内容区）。"""
    x, y, 宽, 高 = 右栏矩形(三D, 窗口宽)
    if 宽 <= 0 or 高 <= 页签条高:
        return (0.0, 0.0, 0.0, 0.0)
    return (x, y + 页签条高, 宽, 高 - 页签条高)


def 能画吗(三D, 窗口宽) -> bool:
    """几何够不够画（首帧拿不到 3D 矩形、窗口被拉得极窄时都不画）。"""
    try:
        _, _, 宽, 高 = 右栏矩形(三D, 窗口宽)
    except Exception:                                                    # noqa: BLE001
        return False
    if 宽 != 宽 or 高 != 高:                # NaN
        return False
    return 宽 >= 最小可画宽 and 高 >= 最小可画高


# ---------------------------------------------------------------------------
# 官方版面矩形：每帧从 ux.configure_docking_layout() 的返回值里取（幂等包装）
# ---------------------------------------------------------------------------
_三D: dict = {"矩形": (0.0, 0.0, 0.0, 0.0), "次数": 0}
_探针已装 = False


def 安装版面探针() -> None:
    global _探针已装
    if _探针已装:
        return
    try:
        from mujoco.experimental.studio import ux
        原版 = ux.configure_docking_layout
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 面板窗：拿不到官方版面接口，面板窗不会出现（{type(异常).__name__}: {异常}）")
        return

    def 包装(*args, **kwargs):
        结果 = 原版(*args, **kwargs)
        try:
            _三D["矩形"] = tuple(float(v) for v in 结果)
            _三D["次数"] += 1
        except Exception:                                                # noqa: BLE001
            pass
        return 结果

    try:
        ux.configure_docking_layout = 包装
        _探针已装 = True
        print("【面板窗】已接上官方版面矩形：位置每帧按 3D 视口实算（不写死像素）", flush=True)
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 面板窗：无法包装官方版面接口（{type(异常).__name__}: {异常}）")


def 当前三D() -> tuple[float, float, float, float]:
    return _三D["矩形"]                     # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 面板窗本体
# ---------------------------------------------------------------------------
class 面板窗:
    """【Panels】窗：一个假页签 + 一列可折叠的面板段。"""

    面板显示名 = "面板窗"
    页签名 = "Panels"

    # ★ 它不进自己的名册（名册里是那 7 个面板），也不受"窗口开关"连坐（它就是被开关的那个）
    独立窗口 = True

    # ★ 这里**故意不加** NoBringToFrontOnFocus：我们的窗口必须盖在官方 Inspector 内容之上，
    #   而 ImGui 的显示层级 = "最后被聚焦的窗口在最前"。所以每帧 Begin 之前显式
    #   `SetNextWindowFocus()` 把它顶到最前（加了 NoBringToFrontOnFocus 反而会阻止这件事）。
    窗口标志 = (int(imgui.WindowFlags.NoTitleBar) | int(imgui.WindowFlags.NoResize)
              | int(imgui.WindowFlags.NoMove) | int(imgui.WindowFlags.NoCollapse)
              | int(imgui.WindowFlags.NoSavedSettings) | int(imgui.WindowFlags.NoNavFocus))

    悬停标志 = imgui.HoveredFlags.RootAndChildWindows.value

    def __init__(self):
        self.viewer = None
        self.可见 = True
        self.绘制次数 = 0
        self.错误次数 = 0
        self._帧 = 0
        self._上一快捷键帧 = -1
        self._要滚到 = ""                 # 菜单跳转：下一帧把这一段滚进视野
        self._实例: dict[str, object] = {}
        self._报过位置 = False
        self._调试 = bool(_os.environ.get("面板窗_调试"))
        面板注册表.确保状态文件()
        菜单栏.安装包装()
        安装版面探针()

    # ------------------------------------------------------------------
    @messages.handler(priority=messages.Priority.CRITICAL)
    def 记下窗口(self, event: viewer_protocol.ViewerInitEvent) -> bool:
        self.viewer = getattr(event, "viewer", None)
        return False

    # ------------------------------------------------------------------
    # 快捷键：Esc = 关面板窗；Ctrl+1..7 = 打开第 N 段（并把窗口显示出来）
    # ------------------------------------------------------------------
    @messages.handler(priority=messages.Priority.CRITICAL)
    def 每帧(self, event: messages.UpdateEvent) -> bool:
        self._帧 += 1
        if not 面板注册表.有界面上下文():
            return False
        try:
            帧 = int(imgui.GetFrameCount())
        except Exception:                                                # noqa: BLE001
            return False
        if 帧 == self._上一快捷键帧:
            return False
        self._上一快捷键帧 = 帧
        try:
            if imgui.IsKeyPressed(imgui.Key.Escape):
                面板注册表.设面板窗可见(False)
            if imgui.GetIO().KeyCtrl:
                键表 = (imgui.Key.N1, imgui.Key.N2, imgui.Key.N3, imgui.Key.N4,
                        imgui.Key.N5, imgui.Key.N6, imgui.Key.N7)
                名单 = 面板注册表.面板顺序()
                for i, 键 in enumerate(键表):
                    if i < len(名单) and imgui.IsKeyPressed(键):
                        面板注册表.跳到段(名单[i])
                        self._要滚到 = 名单[i]
                        break
        except Exception:                                                # noqa: BLE001
            pass
        return False

    # ------------------------------------------------------------------
    # 绘制（★ priority=0：排在官方 INTERNAL 之后，才能盖在官方 Inspector 内容上）
    # ------------------------------------------------------------------
    @messages.handler(priority=0)
    def 画面板(self, event: messages.BuildGuiEvent) -> bool:
        面板注册表.每帧(self)
        if not self.可见:
            return False
        self.绘制次数 += 1
        try:
            窗口宽 = float(imgui.GetIO().DisplaySize.x)
        except Exception:                                                # noqa: BLE001
            return False
        三D = 当前三D()
        if not 能画吗(三D, 窗口宽):
            return False                    # 首帧还没有几何：只登记，不画
        try:
            self._实例 = {面板注册表._名字(p): p for p in 面板注册表.全部面板()}
            实测 = self._画页签条(三D, 窗口宽)
            if 面板注册表.面板窗可见():
                实测内容 = self._画内容窗(三D, 窗口宽)
            else:
                实测内容 = None
            if not self._报过位置:
                self._报过位置 = True
                说 = "【面板窗】位置（我们算的／窗口自己量的）："
                print(说 + f"页签条 算={tuple(round(v) for v in 算页签条矩形(三D, 窗口宽))}"
                          f" 实={实测}", flush=True)
                print(" " * len(说) + f"内容 算={tuple(round(v) for v in 算面板窗矩形(三D, 窗口宽))}"
                                      f" 实={实测内容}｜3D={tuple(round(v) for v in 三D)}"
                                      f"｜窗口宽={窗口宽:.0f}", flush=True)
        except Exception as 异常:                                        # noqa: BLE001
            self.错误次数 += 1
            if self.错误次数 <= 2:
                print(f"⚠ 面板窗绘制出错：{type(异常).__name__}: {异常}")
        return False

    # -- 假页签 --------------------------------------------------------
    def _画页签条(self, 三D, 窗口宽: float):
        """整条页签栏：`Inspector`（官方内容） + `Panels`（我们的），点哪个切哪个。"""
        x, y, w, h = 算页签条矩形(三D, 窗口宽)
        if w <= 0:
            return None
        可见 = 面板注册表.面板窗可见()
        文字宽 = float(imgui.CalcTextSize("Panels").x) if 面板注册表.有界面上下文() else 46.0
        格0 = 算页签格矩形(三D, 窗口宽, 0, 文字宽)
        格1 = 算页签格矩形(三D, 窗口宽, 1, 文字宽)
        # ★ 背景取官方页签栏的配色（那一行原本就比面板底色暗一点）
        try:
            底色 = imgui.GetStyleColorVec4(int(imgui.Col.TabDimmed))
        except Exception:                                                # noqa: BLE001
            底色 = imgui.Vec4(0.16, 0.16, 0.18, 1.0)
        imgui.PushStyleColor(int(imgui.Col.WindowBg), 底色)
        try:
            imgui.SetNextWindowPos(imgui.Vec2(x, y), imgui.Cond.Always.value)
            imgui.SetNextWindowSize(imgui.Vec2(w, h), imgui.Cond.Always.value)
            imgui.SetNextWindowFocus()          # ★ 顶到最前（否则会被官方页签栏盖住）
            展开, _ = imgui.Begin("##面板窗页签条", None, int(面板窗.窗口标志))
            实测 = None
            try:
                if 展开:
                    p = imgui.GetWindowPos()
                    实测 = (round(p.x), round(p.y), 可见, bool(imgui.IsWindowFocused()))
                    # 格 0：官方 Inspector —— 选中态 = 我们的窗口关着
                    if imgui.Selectable("Inspector##官方页签格", not 可见, 0,
                                        imgui.Vec2(max(8.0, 格0[2] - 2.0), max(8.0, h - 4.0))):
                        面板注册表.设面板窗可见(False)
                    imgui.SameLine(0.0, 2.0)
                    # 格 1：我们的 Panels —— 选中态 = 窗口开着
                    if 格1[2] > 0 and imgui.Selectable("Panels##面板窗页签格", 可见, 0,
                                                       imgui.Vec2(max(8.0, 格1[2] - 2.0),
                                                                  max(8.0, h - 4.0))):
                        面板注册表.设面板窗可见(True)
            finally:
                imgui.End()
        finally:
            imgui.PopStyleColor()
        return 实测

    # -- 内容窗 --------------------------------------------------------
    def _画内容窗(self, 三D, 窗口宽: float):
        x, y, w, h = 算面板窗矩形(三D, 窗口宽)
        if w <= 0 or h <= 0:
            return None
        名单 = 面板注册表.面板顺序()
        imgui.SetNextWindowPos(imgui.Vec2(x, y), imgui.Cond.Always.value)
        imgui.SetNextWindowSize(imgui.Vec2(w, h), imgui.Cond.Always.value)
        imgui.SetNextWindowFocus()              # ★ 顶到最前（盖住官方 Inspector 内容）
        实测 = None
        展开, _ = imgui.Begin("##面板窗", None, int(面板窗.窗口标志))
        try:
            if 展开:
                p = imgui.GetWindowPos()
                s = imgui.GetWindowSize()
                实测 = (round(p.x), round(p.y), round(s.x), round(s.y),
                        bool(imgui.IsWindowFocused()))
            if not 展开:
                return 实测
            self._画标题行(名单)
            imgui.Separator()
            for i, 名 in enumerate(名单):
                打开 = 面板注册表.段展开(名)
                标记 = "v" if 打开 else ">"
                if imgui.Selectable(f"{标记} {名}##段{i}", 打开):
                    面板注册表.设段展开(名, not 打开)
                if self._要滚到 == 名:
                    try:
                        imgui.SetScrollHereY(0.0)
                    except Exception:                                    # noqa: BLE001
                        pass
                    self._要滚到 = ""
                if not 打开:
                    continue
                面板 = self._实例.get(名)
                if 面板 is None:
                    imgui.TextDisabled("  (this panel is not loaded)")
                    continue
                imgui.Indent()
                try:
                    面板._画内容()
                except Exception as 异常:                                # noqa: BLE001
                    面板.错误次数 = int(getattr(面板, "错误次数", 0)) + 1
                    if 面板.错误次数 <= 2:
                        print(f"⚠ 面板【{名}】在面板窗里绘制出错：{type(异常).__name__}: {异常}")
                    imgui.TextDisabled(f"  [fail] {type(异常).__name__}")
                    imgui.TextDisabled("  (details in the terminal; the rest keeps working)")
                imgui.Unindent()
                imgui.Separator()
        finally:
            imgui.End()
        return 实测

    def _画标题行(self, 名单) -> None:
        开数 = sum(1 for 名 in 名单 if 面板注册表.段展开(名))
        imgui.TextDisabled(f"Panels  ({开数}/{len(名单)} open)")
        imgui.SameLine()
        if imgui.SmallButton("all##面板窗全开"):
            面板注册表.全部段(True)
        imgui.SameLine()
        if imgui.SmallButton("none##面板窗全收"):
            面板注册表.全部段(False)
        imgui.SameLine()
        if imgui.SmallButton("x##面板窗关闭"):
            面板注册表.设面板窗可见(False)
        imgui.SameLine()
        imgui.TextDisabled("Ctrl+1..7 jumps | Esc closes")


# 启动器约定：模块里叫"面板类"的就是要实例化的面板
面板类 = 面板窗
