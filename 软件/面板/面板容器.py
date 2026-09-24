"""
面板/面板容器.py —— 【工作台】：把 6 个自研面板收进**一个窗口**，用页签来回切换

它解决什么问题（用户原话："把 6 个面板都装在一个弹窗里，并可以来回切换，
就像 Model library 和 Appearance 那种布局"）：

    以前 7 个自研面板是 7 个**独立浮动窗口**，一开软件就糊在 3D 视图上；
    点 × 关掉后状态被记住 → 下次启动"面板全不见了"，而 ImGui 还存在
    `~/.mujoco.ini` 里的停靠节点（脱离主布局的那种）会把窗口画到看不见的地方，
    于是"按 F9 也没反应"（详见 面板注册表.py 文件头的两个坑）。

    现在：**一个窗口 = 一个 ×**，里面 6 个页签：

        [ Model library | Appearance | Controller params | SysID | Recorder | Monitor | About ]

    · 页签切换 = 点一下，来回切，状态（当前页签）会被记住
    · 顶部菜单 `Panels` 是**永远都在的入口**：开关工作台、跳到某个页签、
      把某个面板单独弹出去 / 收回来、重置版面 —— 不依赖快捷键，也不会找不到
    · 页签右边有个 `[pop out]`：想同时看两个面板时，把它弹成独立窗口就行

★ 为什么本文件是个"面板"（有 `面板类`）：
    `启动.py` 的约定是"面板目录里每个 .py 只要有 `面板类` 就被加载"，
    所以这里不需要改任何外壳文件（外壳的 4 个核心文件被 `零改动自检.py` 钉住了）。
    它自己也是一个面板（名字：工作台），只是它的"内容"是别人的页签。

★ 面板上的文字**只能是 ASCII**：官方 UI 字体（Atkinson Hyperlegible）没有中文字形，
  画中文会变成一串 `?`（中文只出现在终端与文档里）。
  校验：./.venv/bin/python 优化（软件优化的报告都放这里面来）/验证/字体覆盖.py
"""
from __future__ import annotations

import os as _os
import sys as _sys

_外壳目录 = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _外壳目录 not in _sys.path:
    _sys.path.insert(0, _外壳目录)

from mujoco.experimental.dear_imgui import dear_imgui as imgui       # noqa: E402
from mujoco.experimental.studio import messages, viewer_protocol      # noqa: E402

import 面板注册表                                                     # noqa: E402

# 页签顺序（面板显示名）。模型库放第一个：它是"选机械臂"的入口，用户最常来这儿。
# 算法紧跟模型库：选完机械臂，下一步通常就是"给它挂哪几个算法"
页签偏好 = ["模型库", "算法", "外观", "控制器参数", "参数辨识", "数据录制", "实时监控", "关于"]

# 菜单里显示用的英文名（面板上的文字只能 ASCII）
菜单英文名 = {
    "模型库": "Model library",
    "算法": "Algorithms",
    "外观": "Appearance",
    "控制器参数": "Controller params",
    "参数辨识": "System identification",
    "数据录制": "Recorder",
    "实时监控": "Monitor (metrics)",
    "关于": "About",
}

# 窗口第一次出现时放哪、多大（只在 FirstUseEver 生效，之后由 ImGui 记住用户拖的位置）
# ★ 把左上角那一条（x=12）让给【Display】小方框（展示模式开关），工作台右移一列，
#   避免两个窗口第一次出现时叠在一起（实测：都放 12 会完全重叠）。
初始位置 = (256.0, 52.0)
初始大小 = (430.0, 620.0)


class 面板容器:
    """【工作台】窗口：把所有自研面板装进一个窗口的页签里。"""

    面板显示名 = "工作台"
    页签名 = "Workbench"

    def __init__(self):
        self.viewer = None
        self.可见 = True
        self.绘制次数 = 0
        self.错误次数 = 0
        self._摆放过 = False
        self._要置顶 = False       # 下一帧把工作台窗口顶到最前面
        # ★ 「要显示哪一页」由我们说了算（ImGui 那边切页签的接口不可靠，见 _画内容 的说明）；
        #   启动时先按上次选的页签（存档），用户点页签、或 ImGui 那边对上了，就交还给 ImGui。
        self._要显示 = 面板注册表.存档页签()
        self._菜单页签 = ""        # 菜单里给哪个页签打勾（ImGui 的高亮可能晚一两帧）
        self._上一数字帧 = -1
        # ★ 状态文件 + 旧版坏停靠记录清理：都必须赶在第一帧之前（见该函数的说明）。
        面板注册表.确保状态文件()
        # ★ 存档里的页签如果已经不在了（面板改名/删掉），退回第一页，免得一帧都不画。
        if self._要显示 not in self._页签名表():
            self._要显示 = ""

    # ------------------------------------------------------------------
    @messages.handler(priority=messages.Priority.CRITICAL)
    def 记下窗口(self, event: viewer_protocol.ViewerInitEvent) -> bool:
        self.viewer = getattr(event, "viewer", None)
        return False

    # ------------------------------------------------------------------
    # 快捷键：Ctrl+1..9 = 直接跳到第 N 个页签
    #   ★ 为什么用"自己换内容"而不是 SetSelected：实测这个 Python 绑定里
    #     `ImGuiTabItemFlags_SetSelected` 不可靠（4 个页签时完全不生效，
    #     见 文档/驭臂_完整工作报告.md「面板容器」一节的实测记录），所以跳页签只能由我们说了算：
    #     内容立刻换成目标页，ImGui 的页签高亮会在用户下一次点击时重新对齐。
    # ------------------------------------------------------------------
    @messages.handler(priority=messages.Priority.CRITICAL)
    def 轮询数字键(self, event: messages.UpdateEvent) -> bool:
        if not 面板注册表.容器可见():
            return False
        try:
            帧 = int(imgui.GetFrameCount())
        except Exception:                                                  # noqa: BLE001
            return False
        if 帧 == self._上一数字帧:
            return False
        self._上一数字帧 = 帧
        try:
            if not imgui.GetIO().KeyCtrl:
                return False
            键表 = (imgui.Key.N1, imgui.Key.N2, imgui.Key.N3, imgui.Key.N4,
                    imgui.Key.N5, imgui.Key.N6, imgui.Key.N7, imgui.Key.N8,
                    imgui.Key.N9)
            for i, 键 in enumerate(键表):
                if imgui.IsKeyPressed(键):
                    面板 = self._可切换面板()
                    if i < len(面板):
                        self.要跳到页签(面板注册表._名字(面板[i]))
                    break
        except Exception:                                                  # noqa: BLE001
            pass                     # 快捷键失败绝不能影响面板绘制
        return False

    def 要跳到页签(self, 名: str) -> None:
        """把工作台切到指定页签（菜单与 Ctrl+数字 共用这一个入口）。

        ★ 只切"内容"：ImGui 在这个绑定里没有可靠的"程序化选中页签"接口
          （SetSelected 实测不生效），所以页签高亮会停在原处，等用户点一下才对齐。
          菜单里的打勾用 `_菜单页签` 跟着我们自己的选择走，免得看起来像没切。
        """
        if not 名:
            return
        self._要显示 = 名         # 决定页签内容画谁（见 `_画内容`）
        self._菜单页签 = 名       # 决定菜单里给谁打勾（ImGui 的高亮会晚一步对齐）
        self._要置顶 = True
        面板注册表.设容器可见(True)

    # ------------------------------------------------------------------
    # 顶部菜单：永远都在的入口（不依赖快捷键）
    #   ★ 官方自己的菜单栏在 viewer_app 里 BeginMainMenuBar/EndMainMenuBar，
    #     本处理器排在 INTERNAL 之后 → 我们是在官方菜单栏右侧续写，不新建一条。
    # ------------------------------------------------------------------
    @messages.handler(priority=messages.Priority.INTERNAL - 1)
    def 画菜单(self, event: messages.BuildGuiEvent) -> bool:
        try:
            if imgui.BeginMenu("Panels"):
                if imgui.MenuItem("Show workbench (all custom panels)", "", False,
                                  bool(面板注册表.容器可见())):
                    面板注册表.设容器可见(True)
                if imgui.MenuItem("Hide workbench", "", False,
                                  not bool(面板注册表.容器可见())):
                    面板注册表.设容器可见(False)
                imgui.Separator()
                imgui.TextDisabled("  jump to tab  (or press Ctrl+1 .. Ctrl+9)")
                for i, 面板 in enumerate(self._可切换面板()):
                    名 = 面板注册表._名字(面板)
                    标签 = 菜单英文名.get(名, 面板注册表.页签名(面板))
                    快捷键 = f"Ctrl+{i + 1}" if i < 9 else ""
                    当前 = (self._要显示 or 面板注册表.当前页签()) == 名
                    if imgui.MenuItem(f"    {标签}", 快捷键, 当前 and bool(面板注册表.容器可见())):
                        self.要跳到页签(名)
                imgui.Separator()
                imgui.TextDisabled("  windows")
                for 面板 in self._可切换面板():
                    名 = 面板注册表._名字(面板)
                    标签 = 菜单英文名.get(名, 面板注册表.页签名(面板))
                    if imgui.MenuItem(f"    Pop out {标签}", "", bool(面板注册表.是弹出(面板))):
                        面板注册表.设弹出(面板, not 面板注册表.是弹出(面板))
                imgui.Separator()
                if imgui.MenuItem("Reveal all (F9)"):
                    面板注册表.全部显示()
                if imgui.MenuItem("Reset panel layout (Shift+F9)"):
                    面板注册表.重置版面()
                imgui.TextDisabled("  F9 = reveal all   Shift+F9 = reset layout")
                imgui.EndMenu()
        except Exception as 异常:                                          # noqa: BLE001
            if self.错误次数 <= 2:
                self.错误次数 += 1
                print(f"⚠ 工作台菜单绘制出错：{type(异常).__name__}: {异常}")
        return False

    @staticmethod
    def _可切换面板() -> list:
        """可以"切过去"的面板（按页签顺序）。

        排除两类：
          · 容器自己（不然会递归）
          · 声明了 `独立窗口 = True` 的面板（它们永远以自己的小窗口出现，
            例如左上角的【Display】展示开关 —— 收进页签就失去"一眼可见"的意义了）
        """
        return [p for p in 面板注册表.全部面板()
                if type(p).__name__ != "面板容器"
                and not getattr(p, "独立窗口", False)]

    @classmethod
    def _页签名表(cls) -> list:
        """所有页签的内部名（用于校验"存档里的页签还在不在"）。"""
        return [面板注册表._名字(p) for p in cls._可切换面板()]

    # ------------------------------------------------------------------
    @messages.handler
    def 画面板(self, event: messages.BuildGuiEvent) -> bool:
        # ★ 必须在"可见性检查"之前：容器自己也要能被 F9 打开
        面板注册表.每帧(self)
        if not self.可见:
            return False
        self.绘制次数 += 1
        if not self._摆放过:
            self._摆放过 = True
            imgui.SetNextWindowPos(imgui.Vec2(*初始位置), imgui.Cond.FirstUseEver.value)
            imgui.SetNextWindowSize(imgui.Vec2(*初始大小), imgui.Cond.FirstUseEver.value)
        if self._要置顶:
            # ★ 必须排在 Begin 之前（SetNextWindowFocus 只管"紧接着的那一个窗口"）。
            #   菜单里点了"跳到某页签"、或点了 [pop out] 时用一次，把工作台顶到最前面。
            self._要置顶 = False
            try:
                imgui.SetNextWindowFocus()
            except Exception:                                              # noqa: BLE001
                pass
        # ★ NoCollapse：ImGui 里"双击标题栏区域 = 折叠窗口"，而**页签就画在标题栏区域里**
        #   —— 双击/连点页签会把整个工作台折起来（用户看到的"闪一下就没"）。
        #   这个窗口绝不该被折叠，直接禁掉。
        展开, self.可见 = imgui.Begin("Workbench", self.可见, imgui.WindowFlags.NoCollapse)
        面板注册表.记录(self)
        try:
            if not 展开:
                return False
            self._画内容()
        except Exception as 异常:                                          # noqa: BLE001
            self.错误次数 += 1
            if self.错误次数 <= 2:
                print(f"⚠ 工作台绘制出错：{type(异常).__name__}: {异常}")
        finally:
            imgui.End()
        return False

    # ------------------------------------------------------------------
    def _画内容(self) -> None:
        if not self.可见:
            return
        面板列表 = [p for p in 面板注册表.全部面板()
                    if type(p).__name__ != "面板容器"
                    and not getattr(p, "独立窗口", False)]
        if not 面板列表:
            imgui.TextDisabled("No custom panels found.")
            return

        # ---- 显示哪一页：看 `self._要显示`；页签**绘制**永远让 ImGui 自己来 ----
        #   ★ 为什么不用"程序化选中页签"（SetSelected）：实测这个 Python 绑定里它不可靠
        #     （4 个页签时完全不生效），而且一旦拿"我们记的页签"去反推"该不该传它"，
        #     记忆和 ImGui 的实际选中差一帧就会每帧打架 → 两个页签同时返回 True、
        #     内容互相覆盖（实测）。
        #   ★ 所以分工是：
        #       · 页签**画**什么、高亮谁  → ImGui（点击 + ini 持久化，天然可靠）
        #       · 页签里**显示哪一页的内容** → `self._要显示`（我们说了算）
        #     两者在"用户点了页签"或"ImGui 恰好也选中了那一页"时合并，之后一直听 ImGui 的。
        #   实测证据：文档/驭臂_完整工作报告.md「第 7 步」一节

        # 顶部一行小状态（面板上只能 ASCII）
        打开数 = sum(1 for p in 面板列表 if 面板注册表.是弹出(p))
        状态 = f"{len(面板列表)} panels in one window"
        if 打开数:
            状态 += f" | {打开数} popped out"
        imgui.TextDisabled(状态 + " | F9 = reveal all | Ctrl+1..9 = jump to tab")

        if not imgui.BeginTabBar("##workbench_tabs"):
            return

        # ---- 显示哪一页：**只由我们自己的状态决定**（`_要显示`）----
        #   ★★ 这里是被用户打回来三次的地方，最终结论写清楚：
        #     ① `BeginTabItem` 的返回值（谁被选中）在这个绑定里**不可信** —— 实测点击切换后
        #        它仍然一直只对第一页返回 True（日志：`ImGui报True的页签=('模型库',)` 从头到尾不变）。
        #     ② 之前有一版逻辑会在"ImGui 说选中的和我画的是同一页"时把 `_要显示` 清成空，
        #        而 ImGui 的不变上报让这个条件**每帧成立** → 清了就退回第一页，于是
        #        "闪一下就回来"（用户的原始描述）。清空这件事必须彻底删掉。
        #     所以现在的规则只有两条，再没有别的分支能改它：
        #        · 用户点了页签（本帧 IsItemClicked / 悬停+按下）→ `_要显示 = 被点的`
        #        · Ctrl+数字 或菜单跳转 → `_要显示 = 目标页`
        #     页签的**高亮**仍然由 ImGui 自己管（点击会让它高亮，这部分在测试窗口里验证过是好的）。
        页签名表 = [面板注册表._名字(p) for p in 面板列表]
        要显示 = self._要显示 or 页签名表[0]
        if 要显示 not in 页签名表:                 # 记忆里的页签已经不在了 → 退回第一页
            要显示 = 页签名表[0]

        被点的 = ""          # 这一帧用户点了哪个页签
        for i, 面板 in enumerate(面板列表):
            名 = 面板注册表._名字(面板)
            标签 = 菜单英文名.get(名, 面板注册表.页签名(面板))
            弹出 = 面板注册表.是弹出(面板)
            标识 = f"tab{i}"                        # ID 用序号：中文名进 ID 容易被 ## 解析搞歧义
            打开页签 = imgui.BeginTabItem(f"{标签}*##{标识}" if 弹出 else f"{标签}##{标识}")
            # 点没点：必须在 BeginTabItem 之后、画别的东西之前问（item 状态会被后面的控件覆盖）
            悬停 = bool(imgui.IsItemHovered())
            if bool(imgui.IsItemClicked()) or (悬停 and bool(imgui.IsMouseClicked(0))):
                被点的 = 名
            if 名 == 要显示:
                self._画一个页签(面板, 名, 标签, 弹出, 标识)
            if 打开页签:
                imgui.EndTabItem()

        imgui.EndTabBar()

        # ---- 点击 → 换页（这是唯一会改变"显示哪一页"的地方）----
        if 被点的:
            if 被点的 != 要显示:
                print(f"【面板】点了页签 → 切到「{被点的}」", flush=True)
            self._要显示 = 被点的
            self._菜单页签 = ""
            self._要置顶 = True
            要显示 = 被点的
        面板注册表.设当前页签(要显示)

    # ------------------------------------------------------------------
    def _画一个页签(self, 面板, 名: str, 标签: str, 弹出: bool, 标识: str) -> None:
        """画当前页签里的东西：弹出按钮 + 面板内容（出错隔离，一个面板坏了不牵连别人）。

        `标识` = 该页签的 ASCII 序号（见 `_画内容` 里的说明）：**控件 ID 一律用它**，
        不要把中文面板名塞进 `##`，免得 ImGui 解析 `##` 时出歧义。
        """
        if imgui.SmallButton(f"pop out##{标识}"):
            面板注册表.设弹出(面板, not 弹出)
            self._要置顶 = True          # 弹出去了：下一帧把工作台顶到最前面
            imgui.SameLine()
            imgui.TextDisabled("(detach this panel into its own window)")
        else:
            imgui.SameLine()
            imgui.TextDisabled("F9 = reveal all | Shift+F9 = reset layout")
        imgui.Separator()

        if 弹出:
            imgui.TextDisabled(f"{标签} is popped out into its own window.")
            if imgui.Button(f"Bring back##{标识}"):
                面板注册表.设弹出(面板, False)
            return

        # ★ 直接画在页签里（不套 BeginChild）。实测怀疑：套一层子窗口会让 ImGui 的页签
        #   选中上报卡死在第一页（点击切不动的现象）。
        try:
            面板._画内容()
        except Exception as 异常:                                          # noqa: BLE001
            面板.错误次数 = int(getattr(面板, "错误次数", 0)) + 1
            if 面板.错误次数 <= 2:
                print(f"⚠ 面板【{名}】在工作台里绘制出错：{type(异常).__name__}: {异常}")
            imgui.TextDisabled(f"[fail] this panel raised an error: {type(异常).__name__}")
            imgui.TextDisabled("(details printed in the terminal; the rest keeps working)")


# 启动器约定：模块里叫"面板类"的就是要实例化的面板
面板类 = 面板容器
