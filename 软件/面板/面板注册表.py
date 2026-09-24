"""
面板注册表.py —— 统一管理"我们自定义面板"的登记 / 收进容器 / 恢复 / 记忆

★ 它为什么长这样（两次真实踩坑的结论，改之前请先读完）：

  【坑 ①】官方的 `ux.configure_docking_layout()` **只停靠官方那 19 个面板**，
     我们自己的面板不在停靠布局里 → ImGui 只能把它们渲染成**一堆独立浮动窗口**，
     一开软件就堆在 3D 视图上面；而且面板原来写的是 `imgui.Begin(标题, None, 0)`，
     ImGui 规定 `p_open=None` 就不画关闭按钮 → **既挪不走也关不掉**。
     （修法：`Begin` 传 p_open，右上角有 ×。）

  【坑 ②】也就是用户真正遇到的那个：**"打开软件 5 个面板全不见了，按 F9 也没反应"**。
     两个原因叠在一起：
       a) 关掉的状态被写进了 `输出/面板状态.json`，下次启动先按它把所有面板设成不可见
          → 面板**根本没被画**，自然"看不见"；
       b) 更阴的一条 —— ImGui 把浮动窗口的停靠信息存在 `~/.mujoco.ini` 里，
          用户以前把两个面板拖到一起，ini 里就留下了一个**脱离主布局的 DockNode**
          （`DockId=0x00000009`）。下次启动 ImGui 把窗口塞进那个谁也不认领的节点里，
          窗口**有绘制次数、但屏幕上什么都没有**（实测：外观/模型库绘制次数 299 次，
          屏幕上 0 个像素）。
     F9 之所以"没反应"：它把面板设成可见了，却改不动 ini 里的停靠节点 —— 见 a/b 两条。

★ 所以现在的规矩（第 3 步重构）：

  ① **默认只有一个窗口**：所有自研面板收进 `面板容器.py` 的【工作台】里，用页签切换
     （和 Model library / Appearance 以前那种"叠在一起"的样子一致，但只有一个窗口、
     一个 ×，不会再产生脱离主布局的 DockNode）。
  ② **不再持久化"面板被关掉"这个状态**。开关由容器自己记（`输出/面板.json` 的
     `容器可见`），面板的可见性每帧由容器统一广播 → 不会再有"上次关了，这次全不见"。
  ③ **F9 一键恢复**：容器关了就打开它、面板弹出了就收回去、状态文件丢了也不怕。
  ④ **Shift+F9 重置版面**：清掉我们在 ~/.mujoco.ini 里的窗口痕迹 + 记录"重开一次"
     → 解决"窗口被拖到屏幕外/卡在不存在的停靠节点里"这类再也找不回来的情况。
     命令行等价物：`--恢复默认界面`（下次启动生效）。
  ⑤ 每个面板仍然**可以单独弹出去**（页签右边的 `[pop out]`）：弹出后就是一个普通浮动窗口，
     有自己的 ×，位置由 ImGui 记住（`~/.mujoco.ini`）。
  ⑥ `不可关闭 = True` 的面板（模型库：选机械臂的唯一入口）在容器里由容器统一管开关，
     弹出后才恢复"没有 ×、关不掉"的老行为。

用法（面板作者只需在 `画面板()` 开头加三行，见 曲线基类.py 的现成写法）：

    @messages.handler
    def 画面板(self, event: messages.BuildGuiEvent) -> bool:
        面板注册表.每帧(self)                 # ★ 必须放在"可见性检查"之前（F9 靠它）
        if not self.可见:
            return False
        if 面板注册表.画在容器里(self):        # ★ 收在容器里 → 本面板不自己开窗口
            ...
            return False
        ...

约定：
    · 面板名取 `面板显示名`（没有就用类名）—— 就是状态文件里的键
    · 页签名取 `页签名`（没有就用 `面板显示名`）
    · 本模块**没有** `面板类` 这个名字，所以 `启动.py` 的面板自动加载会跳过它
      （它只是个工具模块，不是面板）
"""
from __future__ import annotations

import json
import os
import re
import time

from mujoco.experimental.dear_imgui import dear_imgui as imgui

# ---------------------------------------------------------------------------
# 状态文件：<包根>/输出/面板.json
#   ★ 只记"容器开没开 / 哪个面板被弹出去了 / 当前是哪个页签"，
#     **不记"面板被关掉"** —— 那条正是坑 ② 的来源（见文件头）。
# ---------------------------------------------------------------------------
_面板目录 = os.path.dirname(os.path.abspath(__file__))
_包根 = os.path.dirname(os.path.dirname(_面板目录))
状态文件 = os.path.join(_包根, "输出", "面板.json")

# 老状态文件（记"每个面板关没关"）：只在第一次启动时读一次，把"用户明确关过容器里的面板"
# 这个意图迁移成"容器可见 = False"，之后就不再使用它了。文件本身不再改写。
_老状态文件 = os.path.join(_包根, "输出", "面板状态.json")

# 恢复全部面板的快捷键。★ F9 没被官方占用（官方用了 F2/F3/F6/F7 与 W/A/S/D/Q/E）
#   F9       = 全部恢复（打开工作台 + 收回弹出去的窗口）
#   Shift+F9 = 重置版面（清掉 ini 里我们的窗口记录，下次启动回出厂位置）
恢复快捷键 = imgui.Key.F9

# ImGui 的配置文件（窗口位置/停靠信息都在里面）
_IMGUI配置 = os.path.expanduser("~/.mujoco.ini")
_待重开标记 = os.path.join(_包根, "输出", "重启界面.flag")
# 我们自己的窗口名（重置版面时只清这些，不动官方那 19 个面板的布局）
_我们的窗口名 = ("Appearance", "About", "Monitor (metrics)", "Recorder",
                "Controller params", "System identification", "Model library",
                "Workbench")

_面板: dict[str, object] = {}        # 名字 → 面板实例（供容器/F9 用）
_弹出: dict[str, bool] = {}          # 名字 → 是否被单独弹成浮动窗口
_已读 = False
_容器可见 = True                     # 容器（工作台）开没开
_当前页签 = ""                       # 容器当前选中的页签
_上一帧 = -1
_注册首帧 = -1
_已提醒卡住 = False
_容器已就位 = False
_已迁移 = False


def _名字(面板) -> str:
    """面板在状态文件里的键（优先 面板显示名，退化到类名）。"""
    return str(getattr(面板, "面板显示名", None) or type(面板).__name__)


def 页签名(面板) -> str:
    """面板在容器里的页签标题（只能 ASCII：官方 UI 字体没有中文字形）。"""
    名 = str(getattr(面板, "页签名", "") or "")
    return 名 or _名字(面板)


def 重置缓存() -> None:
    """把本模块的内存状态清空（重新从状态文件读）。

    ★ 它是给**自检**用的（优化（软件优化的报告都放这里面来）/验证/面板注册表自检.py 要反复换状态文件验证语义）。
      正常运行不需要它：进程启动时 `_已读=False`，第一次 `每帧()` 自然会读一次。
    """
    global _已读, _容器可见, _当前页签, _弹出, _上一帧, _注册首帧, _已提醒卡住, _容器已就位, _已迁移
    _面板.clear()
    _弹出 = {}
    _已读 = False
    _容器可见 = True
    _当前页签 = ""
    _上一帧 = -1
    _注册首帧 = -1
    _已提醒卡住 = False
    _容器已就位 = False
    _已迁移 = False


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------
def _读取() -> None:
    global _已读, _容器可见, _弹出, _当前页签
    if _已读:
        return
    _已读 = True
    try:
        with open(状态文件, encoding="utf-8") as f:
            数据 = json.load(f)
        if isinstance(数据, dict):
            _容器可见 = bool(数据.get("容器可见", True))
            _当前页签 = str(数据.get("当前页签", "") or "")
            弹出 = 数据.get("弹出") or {}
            if isinstance(弹出, dict):
                _弹出 = {str(k): bool(v) for k, v in 弹出.items()}
    except FileNotFoundError:
        _迁移老状态()
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 面板状态读取失败（按「全部显示」处理）：{type(异常).__name__}: {异常}")


def _迁移老状态() -> None:
    """第一次跑新版：把老的"每个面板关没关"迁移成"容器开没开"。

    老文件里如果**所有**面板都是关的，说明用户当时想清屏 → 容器默认关；
    否则容器默认开（面板一律回到容器里，不再有"某几个不见了"）。
    """
    global _容器可见
    try:
        with open(_老状态文件, encoding="utf-8") as f:
            老 = json.load(f)
        if isinstance(老, dict) and 老 and not any(bool(v) for v in 老.values()):
            _容器可见 = False
            print("【面板】检测到旧版把面板全关了 → 这次也从「工作台已收起」开始，按 F9 或 "
                  "菜单 Panels → Show workbench 打开", flush=True)
    except FileNotFoundError:
        pass
    except Exception:                                                    # noqa: BLE001
        pass


def _保存() -> None:
    try:
        os.makedirs(os.path.dirname(状态文件), exist_ok=True)
        with open(状态文件, "w", encoding="utf-8") as f:
            json.dump({"容器可见": _容器可见, "当前页签": _当前页签, "弹出": _弹出},
                      f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 面板状态保存失败（不影响使用）：{type(异常).__name__}: {异常}")


# ---------------------------------------------------------------------------
# 对外查询（容器与各面板用）
# ---------------------------------------------------------------------------
def 全部面板() -> list:
    """按页签顺序返回已登记的面板（容器画页签用）。"""
    顺序 = _页签顺序()
    return [_面板[名] for 名 in 顺序 if 名 in _面板]


def 容器可见() -> bool:
    return _容器可见


def 设容器可见(值: bool) -> None:
    global _容器可见
    if _容器可见 != bool(值):
        _容器可见 = bool(值)
        _保存()
        print(f"【面板】工作台 → {'已打开' if _容器可见 else '已收起（菜单 Panels 或 F9 找回）'}",
              flush=True)


def 确保状态文件() -> None:
    """容器启动时调：① 保证状态文件一定存在 ② 只做一次地清掉旧版留下的坏停靠记录。

    ★ 两件事都必须发生在**第一帧之前**（容器一被实例化就调），因为
      `~/.mujoco.ini` 是 ImGui 在启动时读进去的 —— 晚一帧就没用了。
    """
    _读取()
    _保存()
    清理旧停靠记录()


def 当前页签() -> str:
    return _当前页签


def 存档页签() -> str:
    """状态文件里记着的页签（**先读文件**再回答）。

    ★ 为什么不能直接用 `当前页签()`：容器是在自己的 `__init__` 里决定"启动时显示哪个
      页签"的，而那时候还没有任何面板跑过 `每帧()` → `_读取()` 还没发生 →
      `_当前页签` 还是空串。实测的后果：用户在【参数辨识】页签关掉软件，
      下次启动却回到【模型库】（第一帧的默认页签），而且立刻把这个错的选择存了回去。
    """
    _读取()
    return _当前页签


def 清理旧停靠记录() -> bool:
    """**只做一次**：把 `~/.mujoco.ini` 里我们这些窗口的旧停靠记录清掉。

    ★ 它修的是用户遇到的那个真实故障：老版本里用户把两个浮动面板拖到一起，ImGui 就在
      ini 里留下一个**脱离主布局的 DockNode**（`DockId=0x00000009`）。之后每次启动，
      ImGui 都把窗口塞进那个没人认领的节点里 → **窗口有绘制次数，屏幕上什么都没有**，
      而且在运行中没法把它拽回来（位置是读 ini 时就定下的）。
      新版面板全在容器里、不再产生这种节点，所以这条清理只需要跑一次。
    """
    global _已迁移
    if _已迁移:
        return False
    _需要清理 = os.path.join(_包根, "输出", ".界面已迁移")
    if os.path.exists(_需要清理):
        _已迁移 = True
        return False
    清过 = _清理ini()
    if not 清过:
        # ★ 这次没清成（比如 ini 不可写）→ **不写标记**，下次启动再试。
        return False
    _已迁移 = True
    try:
        os.makedirs(os.path.dirname(_需要清理), exist_ok=True)
        with open(_需要清理, "w", encoding="utf-8") as f:
            f.write("面板容器改版后已经清理过一次 ~/.mujoco.ini 里的旧停靠记录。\n"
                    "删掉本文件会在下次启动时再清理一次。\n")
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 迁移标记写入失败（不影响使用，下次启动会再清理一次）：{type(异常).__name__}: {异常}")
    if 清过:
        print("【面板】检测到旧版的窗口停靠记录（会让面板「画了但看不见」）—— "
              "已清理 ~/.mujoco.ini 里我们这些窗口的段落，本次启动即生效", flush=True)
    return 清过


def 设当前页签(名: str) -> None:
    global _当前页签
    if 名 and _当前页签 != 名:
        _当前页签 = 名
        _保存()


def 是当前页签(面板) -> bool:
    """容器现在选中的是不是本面板（没记过页签时按第一个算）。"""
    顺序 = _页签顺序()
    if not 顺序:
        return False
    当前 = _当前页签 or 顺序[0]
    return 当前 == _名字(面板)


def 画在容器里(面板) -> bool:
    """这一帧本面板的内容应该由容器画（= 不要自己开窗口）。

    ★ 这里必须和 `每帧()` 用同一套判断（含第 1 帧的"容器即将出现"预判），
      否则第 1 帧本面板会抢在容器前面自己开一个浮动窗口（实测：闪一下）。
    ★ 工作台收起时（`_容器可见=False`）：`每帧()` 已经把 `面板.可见` 设成 False，
      所以面板根本走不到这里；这里再兜一道，语义是"容器关着 = 谁都不画"。
    """
    if not _容器可见:
        return False
    return not 是弹出(面板) and (有容器() or _容器即将出现())


def 是弹出(面板) -> bool:
    return bool(_弹出.get(_名字(面板), False))


def 设弹出(面板, 值: bool) -> None:
    名 = _名字(面板)
    if bool(_弹出.get(名, False)) != bool(值):
        _弹出[名] = bool(值)
        _保存()
        print(f"【面板】{名} → {'已弹出为独立窗口' if 值 else '已收回工作台（页签）'}", flush=True)


def 有容器() -> bool:
    """容器（面板容器.面板容器）在不在这一批面板里。"""
    return any(type(p).__name__ == "面板容器" for p in _面板.values())


def _页签顺序() -> list[str]:
    """页签顺序：容器里写死的偏好顺序优先，没登记的按登记顺序跟在后面。"""
    偏好 = ["模型库", "外观", "控制器参数", "参数辨识", "数据录制", "实时监控", "关于"]
    结果 = [名 for 名 in 偏好 if 名 in _面板]
    结果 += [名 for 名 in _面板 if 名 not in 结果]
    return 结果


def 画弹出提示(面板) -> None:
    """面板被收进容器时，页签里显示一句"它现在在哪儿"的小提示。"""
    imgui.TextDisabled(f"{页签名(面板)} is shown as a tab of the Workbench window.")
    imgui.TextDisabled("Use the [pop out] button on the tab bar to detach it into its own window.")
    imgui.Separator()
    if imgui.Button(f"Show {页签名(面板)}"):
        设弹出(面板, True)


# ---------------------------------------------------------------------------
# 面板每一帧要调的两个函数
# ---------------------------------------------------------------------------
def 每帧(面板) -> bool:
    """面板的 `画面板()` **开头**调用（必须在 `if not self.可见` 之前）。

    做四件事：登记面板 → 处理快捷键 → 广播容器可见性 → 返回这一帧该不该画。

    ★ `不可关闭 = True` 的面板（模型库）在容器里由容器统一管开关（它能被收起，
      因为选机械臂还有"菜单 Panels → 页签"这条路）；只有被弹成独立窗口时才
      恢复"没有 ×、关不掉"的老行为。
    """
    global _注册首帧
    _读取()
    名 = _名字(面板)
    if 名 not in _面板:
        _面板[名] = 面板
        if _注册首帧 < 0:
            _注册首帧 = _帧号()
    处理快捷键()
    _安全网()

    弹出中 = 是弹出(面板)
    # ★ 容器的 `画面板` 排在文件名最后（工作台），所以第 1 帧容器还没来得及登记。
    #   这一帧先别自己开窗口（否则会闪一下浮动窗口），用"预判"顶上。
    #   ★ 语义：容器**收起 = 自研面板全体隐藏**（连弹出去的小窗口也一起收起来，
    #     否则"收起工作台"只收一半，用户会以为关不掉）。
    容器在 = 有容器() or _容器即将出现()
    面板.可见 = _容器可见 and 容器在
    不可关闭 = bool(getattr(面板, "不可关闭", False)) and 弹出中
    面板._不可关闭生效 = 不可关闭
    return bool(getattr(面板, "可见", True))


def _容器即将出现() -> bool:
    """容器文件在不在（只用来兜住"第 1 帧容器还没登记"这个空档）。

    ★ 为什么需要它：面板的 `画面板` 处理器按**文件名顺序**注册，`面板容器.py`
      排在最后 → 第 1 帧容器还没进 `_面板`。没有这个预判，其它面板会在第 1 帧
      各自开一个浮动窗口闪一下。
    """
    global _容器已就位
    if _容器已就位:
        return True
    try:
        _容器已就位 = os.path.exists(os.path.join(_面板目录, "面板容器.py"))
    except Exception:                                                    # noqa: BLE001
        _容器已就位 = False
    return _容器已就位


def 记录(面板) -> None:
    """面板自己开的窗口里，`imgui.Begin(...)` **之后**调用：处理用户点 × 的结果。

    ★ 现在的语义变了：点 × **不再**写"这个面板永久关闭"（坑 ② 就是那个记忆造成的），
      而是"弹出去的窗口收回来"——下次还在容器页签里，不会再丢。
    """
    if getattr(面板, "_不可关闭生效", False):
        return
    if not getattr(面板, "可见", True) and 是弹出(面板):
        设弹出(面板, False)


# ---------------------------------------------------------------------------
# 一键恢复 / 重置版面
# ---------------------------------------------------------------------------
def 全部显示() -> None:
    """F9：把工作台打开、把所有弹出去的面板收回页签。

    ★ 顺手把已登记面板的 `可见` 立刻置 True：面板的可见性是每帧由 `每帧()` 广播的，
      如果只改容器状态，得等下一帧才看见效果（自检里就会读出"还是不可见"）。
    """
    global _弹出
    关了 = [名 for 名, 弹 in _弹出.items() if 弹]
    _弹出 = {}
    设容器可见(True)
    _保存()
    for 面板 in _面板.values():
        try:
            面板.可见 = True
        except Exception:                                                # noqa: BLE001
            continue
    if 关了:
        print(f"【面板】已收回弹出的面板：{'、'.join(关了)}", flush=True)
    print("【面板】已恢复全部自研面板（都在【工作台】的页签里）", flush=True)


def 重置版面() -> None:
    """Shift+F9：清掉 ~/.mujoco.ini 里我们这些窗口的痕迹，下次启动回到出厂位置。

    ★ 为什么需要它：ImGui 会把窗口位置/停靠信息写进 ini。用户把窗口拖到屏幕外、
      或者旧版本留下一个"脱离主布局的 DockNode"时，窗口就会**画了但看不见**，
      而且在运行中没有任何办法把它拽回来（那是 ini 加载时就决定的）。
      唯一可靠的办法就是清掉那些记录 + 重开软件。
    """
    global _弹出
    _弹出 = {}
    设容器可见(True)
    _保存()
    清过 = _清理ini()
    try:
        os.makedirs(os.path.dirname(_待重开标记), exist_ok=True)
        with open(_待重开标记, "w", encoding="utf-8") as f:
            f.write("请手动关闭本窗口再打开一次（或直接跑 启动.sh），版面即回到出厂状态。\n")
    except Exception:                                                    # noqa: BLE001
        pass
    print("\n" + "=" * 78, flush=True)
    print("【面板】已重置版面：清理了 ~/.mujoco.ini 里我们这些窗口的记录"
          f"（{'成功' if 清过 else '无需清理'}）", flush=True)
    print("        ★ 请关闭本窗口再打开一次（关窗口 = 存盘，重开 = 生效）", flush=True)
    print("=" * 78 + "\n", flush=True)


def _清理ini() -> bool:
    """把 ~/.mujoco.ini 里我们自己的窗口段落与停靠记录删掉。

    只删"我们的窗口名"对应的 `[Window][xxx]` 段，以及所有 `DockId=` 行
    （官方那 19 个面板的布局由官方 `configure_docking_layout()` 每次重建，
      所以删掉 DockId 不会破坏官方界面；反而能清掉那些没人认领的 DockNode）。

    ★ 踩过的坑：判断"跳过"的那一位**必须在遇到任何新的段落头时复位**，否则删掉
      `[Window][Model library]` 之后会把后面所有段落（包括官方的 `[Docking][Data]`、
      主题 `[Studio][UX]`）一起吞掉 —— 实测把官方布局和主题都删没了。
    """
    try:
        if not os.path.exists(_IMGUI配置):
            return False
        with open(_IMGUI配置, encoding="utf-8") as f:
            行 = f.readlines()
        结果, 跳过 = [], False
        for 原行 in 行:
            内容 = 原行.rstrip("\n")
            if 内容.startswith("[") and 内容.endswith("]"):
                # 新的段落头：先复位"跳过"，再判断这一段是不是我们的
                跳过 = (内容.startswith("[Window][")
                        and any(内容[len("[Window]["):-1] == 名 or
                                内容[len("[Window]["):-1].startswith(名)
                                for 名 in _我们的窗口名))
                if 跳过:
                    continue
            elif 跳过:
                continue
            if re.match(r"^\s*DockId\s*=", 内容):
                continue
            结果.append(原行)
        with open(_IMGUI配置, "w", encoding="utf-8") as f:
            f.writelines(结果)
        return True
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 清理 {_IMGUI配置} 失败（不影响使用）：{type(异常).__name__}: {异常}")
        return False


def _帧号() -> int:
    """当前帧号；**没有 ImGui 上下文时返回 -1**。

    ★ `imgui.GetFrameCount()` 在没有上下文时不是抛异常，而是**直接段错误**（实测），
      所以这里必须先问上下文（见 `_有界面上下文`）。
    """
    if not _有界面上下文():
        return -1
    try:
        return int(imgui.GetFrameCount())
    except Exception:                                                    # noqa: BLE001
        return -1


def _有界面上下文() -> bool:
    """ImGui 上下文在不在。

    ★ 为什么必须问这一句：`imgui.IsKeyPressed(...)` 在没有上下文时不是抛异常，
      而是**直接段错误**（实测）。本模块在"没开窗口"的场合也会被用到
      （例如 优化（软件优化的报告都放这里面来）/验证/面板注册表自检.py 直接调 每帧/全部显示），
      所以凡是要碰 ImGui 的地方都先过这一关。
    """
    try:
        问 = getattr(imgui, "GetCurrentContext", None)
        return bool(问()) if 问 is not None else True
    except Exception:                                                    # noqa: BLE001
        return False


def 处理快捷键() -> None:
    """轮询快捷键。每帧只真正轮询一次（面板有 7 个，都会调本函数）。"""
    global _上一帧
    if not _有界面上下文():
        return
    帧 = _帧号()
    if 帧 >= 0 and 帧 == _上一帧:
        return                                   # 同一帧已经处理过
    _上一帧 = 帧
    try:
        if not imgui.IsKeyPressed(恢复快捷键):
            return
        if imgui.GetIO().KeyShift:
            重置版面()
        else:
            全部显示()
    except Exception:                                                # noqa: BLE001
        pass                                     # 快捷键失败绝不能影响面板绘制


def _安全网() -> None:
    """万一容器没画出来（界面被拖到屏幕外等），终端要吭声，而不是让用户干瞪眼。"""
    global _已提醒卡住
    if _已提醒卡住 or _注册首帧 < 0 or not 有容器():
        return
    帧 = _帧号()
    if 帧 < 0 or 帧 - _注册首帧 < 180:          # 约 3 秒
        return
    _已提醒卡住 = True
    if not _容器可见:
        print("【面板】工作台当前是【收起】状态（自研面板都在它的页签里）。"
              "按 F9 或菜单 Panels → Show workbench 打开；"
              "Shift+F9 = 重置版面（下次启动回到出厂位置）", flush=True)
