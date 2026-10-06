"""
面板注册表.py —— 统一管理"我们自定义面板"的登记 / 侧栏托管 / 恢复 / 记忆

★ 它为什么长这样（两次真实踩坑 + 一次可行性验证的结论，改之前请先读完）：

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
          用户把两个面板拖到一起，ini 里就留下一个**脱离主布局的 DockNode**。
          下次启动 ImGui 把窗口塞进那个谁也不认领的节点里，窗口**有绘制次数、
          但屏幕上什么都没有**。
     F9 之所以"没反应"：它把面板设成可见了，却改不动 ini 里的停靠节点。
     → 所以现在：**不再持久化"面板被关掉"这个状态**，可见性每帧由容器统一广播；
       Shift+F9 / `--恢复默认界面` 负责清掉 ini 里的痕迹。

  【坑 ③ / 2026-10-06】"把自研面板停靠到官方 Options / Inspector 下面"这条路**已证伪**。
     9 组现场实验（切在官方之前/之后、`DockBuilderFinish` 调/不调、往 ini 里写 `DockId`、
     直接塞官方已有节点 `0x06`/`0x08`、整套 `RemoveNode→AddNode→切片→Finish` 重建）
     结论一致：**`DockId` 记得住，但 ImGui 永不真的启用停靠**（窗口一直浮在 60,60）；
     手写 ini 造出的空节点会被当空节点剪掉；整套重建的版面**下一帧就被官方抢回去**。
     证据与实验记录：`优化（软件优化的报告都放这里面来）/报告/界面侧栏改造_设计规格.md` §1.2。
     → 所以改成【侧栏】：纯窗口定位（`面板/侧栏.py`），收起时只占两侧各 26px，
       3D 视口一格不占。**不要再尝试 Dockspace 停靠。**

★ 现在的规矩（侧栏版）：
  ① 默认只有两条 26px 标签条：面板点标签才从边上抽出来，收起来就还给 3D
  ② 面板只有三态：收起 / 临时展开（鼠标移开 0.8 秒自动收）/ 钉住（常驻）
  ③ **F9 一键恢复**：标签条关了就打开、临时展开的都收起、钉住保留
  ④ **Shift+F9 重置版面**：清掉我们在 `~/.mujoco.ini` 里的窗口痕迹 + 记"重开一次"
     命令行等价物：`--恢复默认界面`（下次启动生效）
  ⑤ `独立窗口 = True` 的面板（展示=物理总闸 / 外观）**不进侧栏**，也不受标签条开关连坐
  ⑥ `不可关闭 = True` 的面板（模型库：选机械臂的唯一入口）弹出成独立窗口时没有 ×

用法（面板作者只需在 `画面板()` 开头加三行，见 曲线基类.py 的现成写法）：

    @messages.handler
    def 画面板(self, event: messages.BuildGuiEvent) -> bool:
        面板注册表.每帧(self)                 # ★ 必须放在"可见性检查"之前（F9 靠它）
        if not self.可见:
            return False
        if 面板注册表.画在容器里(self):        # ★ 由侧栏托管 → 本面板不自己开窗口
            ...
            return False
        ...

约定：
    · 面板名取 `面板显示名`（没有就用类名）—— 就是状态文件里的键
    · 页签名取 `页签名`（没有就用 `面板显示名`）—— 独立窗口的标题用它（只能 ASCII）
    · 本模块**没有** `面板类` 这个名字，所以 `启动.py` 的面板自动加载会跳过它
"""
from __future__ import annotations

import json
import os
import re

from mujoco.experimental.dear_imgui import dear_imgui as imgui

# ---------------------------------------------------------------------------
# 左右分组名单（谁能进侧栏、进哪一栏、标签怎么竖排）
#   ★ 放在注册表而不是侧栏里：这是"名册"数据，注册表是它的主人；
#     侧栏（面板/侧栏.py）只负责画，并从这里 import，避免两个模块互相 import 成环。
# ---------------------------------------------------------------------------
左栏 = ("模型库", "算法", "控制器参数", "参数辨识")     # 动作类：选模型、挂算法、调参数
右栏 = ("实时监控", "数据录制", "关于")                 # 观测类：看数据、录数据、看信息

# 标签条上的短名（竖排逐字绘制，太长会把条子撑得很高）
短名 = {
    "模型库": "Model",
    "算法": "Algo",
    "控制器参数": "Ctrl",
    "参数辨识": "SysID",
    "实时监控": "Monitor",
    "数据录制": "Recorder",
    "关于": "About",
}

# ---------------------------------------------------------------------------
# 状态文件：<包根>/输出/面板.json（版本 2）
#   ★ 只记"标签条开没开 / 哪些面板被钉住 / 上次展开过谁"，
#     **不记"面板被关掉"** —— 那条正是坑 ② 的来源（见文件头）。
# ---------------------------------------------------------------------------
_面板目录 = os.path.dirname(os.path.abspath(__file__))
_包根 = os.path.dirname(os.path.dirname(_面板目录))
状态文件 = os.path.join(_包根, "输出", "面板.json")
状态文件版本 = 2

# 老状态文件（记"每个面板关没关"）：只在第一次启动时读一次，把"用户明确关过面板"
# 这个意图迁移成"标签条收起"，之后就不再使用它了。文件本身不再改写。
_老状态文件 = os.path.join(_包根, "输出", "面板状态.json")

# 恢复全部面板的快捷键。★ F9 没被官方占用（官方用了 F2/F3/F6/F7 与 W/A/S/D/Q/E）
#   F9       = 全部恢复（显示标签条 + 收起临时展开 + 保留钉住）
#   Shift+F9 = 重置版面（清我们窗口的记录，下次启动回出厂位置）
恢复快捷键 = imgui.Key.F9

# ImGui 的配置文件（窗口位置/停靠信息都在里面）
_IMGUI配置 = os.path.expanduser("~/.mujoco.ini")
_待重开标记 = os.path.join(_包根, "输出", "重启界面.flag")

# 我们自己的窗口名（重置版面时只清这些，不动官方那 19 个面板的布局）
#   ★ "Workbench" 是旧版页签容器的窗口名，留着它只为了把历史遗留段清干净。
_我们的窗口名 = ("Appearance", "About", "Monitor (metrics)", "Recorder",
                "Controller params", "System identification", "Model library",
                "Workbench")

_面板: dict[str, object] = {}        # 名字 → 面板实例（供侧栏/菜单/F9 用）
_钉住: dict[str, bool] = {}          # 名字 → 是否钉住（常驻展开）
_已读 = False
_标签条可见 = True                   # 两条 26px 标签条开没开
_展开中 = ""                         # 当前"临时展开"的面板名（"" = 没展开）
_上次展开 = ""                       # 上一次临时展开过谁（只记录、启动不自动展开）
_上一帧 = -1
_注册首帧 = -1
_已提醒卡住 = False
_侧栏已就位 = False
_已迁移 = False


def _名字(面板) -> str:
    """面板在状态文件里的键（优先 面板显示名，退化到类名）。"""
    return str(getattr(面板, "面板显示名", None) or type(面板).__name__)


def 页签名(面板) -> str:
    """独立窗口的标题（只能 ASCII：官方 UI 字体没有中文字形）。"""
    名 = str(getattr(面板, "页签名", "") or "")
    return 名 or _名字(面板)


def 分栏(名: str) -> str:
    """某个面板该在哪一栏（`""` = 它不进侧栏）。"""
    if 名 in 左栏:
        return "左"
    if 名 in 右栏:
        return "右"
    return ""


def 标签文字(名: str) -> str:
    """标签条上要竖排画的那串字（短名优先）。"""
    return 短名.get(名, 名)


def 重置缓存() -> None:
    """把本模块的内存状态清空（重新从状态文件读）。

    ★ 它是给**自检**用的（`验证/面板注册表自检.py` 要反复换状态文件验证语义）。
      正常运行不需要它：进程启动时 `_已读=False`，第一次 `每帧()` 自然会读一次。
    """
    global _已读, _标签条可见, _展开中, _上次展开, _钉住
    global _上一帧, _注册首帧, _已提醒卡住, _侧栏已就位, _已迁移
    _面板.clear()
    _钉住 = {}
    _已读 = False
    _标签条可见 = True
    _展开中 = ""
    _上次展开 = ""
    _上一帧 = -1
    _注册首帧 = -1
    _已提醒卡住 = False
    _侧栏已就位 = False
    _已迁移 = False


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------
def _读取() -> None:
    global _已读, _标签条可见, _展开中, _上次展开, _钉住
    if _已读:
        return
    _已读 = True
    try:
        with open(状态文件, encoding="utf-8") as f:
            数据 = json.load(f)
    except FileNotFoundError:
        _迁移老状态()
        return
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 面板状态读取失败（按「全部显示」处理）：{type(异常).__name__}: {异常}")
        return
    if not isinstance(数据, dict):
        return
    # 标签条开关：v2 用「标签条可见」；v1 的「容器可见」是同义的旧名，照收
    if "标签条可见" in 数据:
        _标签条可见 = bool(数据.get("标签条可见", True))
    elif "容器可见" in 数据:
        _标签条可见 = bool(数据.get("容器可见", True))
    # ★ v1 的「弹出」「当前页签」**不迁移**：
    #   「弹出」= 独立浮动窗口，迁移成"钉住"会让用户一开软件就有面板压着 3D，
    #   而"默认零遮挡"是这一版的硬要求（设计规格 §2 目标 1）。
    _展开中 = ""
    _上次展开 = str(数据.get("上次展开") or "")
    钉 = 数据.get("钉住") or {}
    if isinstance(钉, dict):
        _钉住 = {str(k): bool(v) for k, v in 钉.items() if v}


def _迁移老状态() -> None:
    """第一次跑新版：把老的"每个面板关没关"迁移成"标签条开没开"。

    老文件里如果**所有**面板都是关的，说明用户当时想清屏 → 标签条默认收起；
    否则标签条默认打开（面板一律回到侧栏，不再有"某几个不见了"）。
    """
    global _标签条可见
    try:
        with open(_老状态文件, encoding="utf-8") as f:
            老 = json.load(f)
        if isinstance(老, dict) and 老 and not any(bool(v) for v in 老.values()):
            _标签条可见 = False
            print("【面板】检测到旧版把面板全关了 → 这次也从「标签条已收起」开始，按 F9 或 "
                  "菜单 Panels → Reveal all 打开", flush=True)
    except FileNotFoundError:
        pass
    except Exception:                                                    # noqa: BLE001
        pass


def _保存() -> None:
    global _上次展开
    if _展开中:
        _上次展开 = _展开中
    try:
        os.makedirs(os.path.dirname(状态文件), exist_ok=True)
        with open(状态文件, "w", encoding="utf-8") as f:
            json.dump({"版本": 状态文件版本,
                       "标签条可见": _标签条可见,
                       "钉住": _钉住,
                       "上次展开": _上次展开},
                      f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 面板状态保存失败（不影响使用）：{type(异常).__name__}: {异常}")


# ---------------------------------------------------------------------------
# 对外查询（侧栏 / 菜单 / 各面板用）
# ---------------------------------------------------------------------------
def 全部面板() -> list:
    """按侧栏顺序返回已登记的面板（侧栏画标签、菜单列条目都用它）。"""
    顺序 = 侧栏顺序()
    return [_面板[名] for 名 in 顺序 if 名 in _面板]


def 侧栏顺序() -> list[str]:
    """侧栏里的面板顺序：左栏 4 格 + 右栏 3 格（未登记的跳过，末尾补漏网的面板）。

    ★ 排除两类，和旧容器的 `_可切换面板()` 同一套判断：
      · 侧栏**自己**（不然会递归地给自己画一格）
      · `独立窗口 = True` 的面板（展示 / 外观 —— 它们永远以自己的窗口出现）
    """
    def 能进侧栏(名: str) -> bool:
        面板 = _面板.get(名)
        if 面板 is None:
            return False
        if type(面板).__name__ == "侧栏面板":
            return False
        return not bool(getattr(面板, "独立窗口", False))

    名单 = [名 for 名 in 左栏 + 右栏 if 能进侧栏(名)]
    名单 += [名 for 名 in _面板 if 名 not in 名单 and 能进侧栏(名) and 分栏(名) == ""]
    return 名单


def 左栏名单() -> list[str]:
    return [名 for 名 in 左栏 if 名 in _面板]


def 右栏名单() -> list[str]:
    return [名 for 名 in 右栏 if 名 in _面板]


def 标签条可见() -> bool:
    return _标签条可见


def 设标签条可见(值: bool) -> None:
    global _标签条可见
    # ★ 先 `_读取()`：状态文件是**懒加载**的，如果调用方在任何 `每帧()` 之前就设值，
    #   晚一步的读取会把刚设的值覆盖掉（自检里实测踩到）。设置器必须先物化状态。
    _读取()
    if _标签条可见 != bool(值):
        _标签条可见 = bool(值)
        _保存()
        print(f"【面板】侧栏标签条 → {'已显示' if _标签条可见 else '已收起（菜单 Panels 或 F9 找回）'}",
              flush=True)


def 展开中() -> str:
    return _展开中


def 上次展开() -> str:
    """上一次临时展开过谁（只用于菜单/排查；**启动时不自动展开**，理由见 `_读取`）。"""
    return _上次展开


def 设展开(名: str) -> None:
    """把「临时展开」设成某个面板（`""` = 全部收起）。

    ★ 状态层只保存**一个**名字，所以"同一时刻只允许一侧临时展开"是天然成立的。
    """
    global _展开中
    _读取()                                 # 同 设标签条可见：先物化状态，别被覆盖
    if 名 and 分栏(名) == "":
        return                                   # 不在侧栏名单里的面板，展开它没有意义
    if _展开中 != 名:
        _展开中 = 名
        _保存()


def 切换展开(名: str) -> None:
    """点标签用：已经是它 → 收起；否则展开它（另一侧那个临时展开会被挤掉）。"""
    设展开("" if _展开中 == 名 else 名)


def _名字或面板(面板或名) -> str:
    return 面板或名 if isinstance(面板或名, str) else _名字(面板或名)


def 是钉住(面板或名) -> bool:
    名 = _名字或面板(面板或名)
    return bool(_钉住.get(名, False))


def 设钉住(面板或名, 值: bool) -> None:
    """钉住 = 常驻展开（鼠标移开也不收）。取消钉住时让它以"临时展开"身份留着，
    这样用户不会觉得"一点图钉面板就没了"。"""
    名 = _名字或面板(面板或名)
    if not 名:
        return
    _读取()                                 # 同 设标签条可见：先物化状态，别被覆盖
    if bool(值):
        _钉住[名] = True
    else:
        _钉住.pop(名, None)
    _保存()
    print(f"【面板】{名} → {'已钉住（常驻展开）' if 值 else '已取消钉住'}", flush=True)
    if not 值:
        设展开(名)


def 钉住集合() -> list[str]:
    """当前钉住的面板名（过滤掉名单里已经不存在的名字 —— 改名/删面板后不许崩）。"""
    return sorted(名 for 名 in _钉住 if 分栏(名) or 名 in _面板)


def 是展开中(面板) -> bool:
    """侧栏这一帧是不是正在画它的内容（= 临时展开的就是它，或者它被钉住）。"""
    名 = _名字(面板)
    return bool(名) and (_展开中 == 名 or 是钉住(名))


def 收起全部(*, 保留钉住: bool = True) -> None:
    """收起所有「临时展开」；`保留钉住=False` 时连钉住一起清掉。"""
    global _钉住
    设展开("")
    if not 保留钉住 and _钉住:
        _钉住 = {}
        _保存()


def 有容器() -> bool:
    """侧栏在不在这一批面板里。"""
    return any(type(p).__name__ == "侧栏面板" for p in _面板.values())


def 确保状态文件() -> None:
    """侧栏启动时调：① 保证状态文件一定存在 ② 只做一次地清掉旧版留下的坏停靠记录。

    ★ 两件事都必须发生在**第一帧之前**（侧栏一被实例化就调），因为
      `~/.mujoco.ini` 是 ImGui 在启动时读进去的 —— 晚一帧就没用了。
    """
    _读取()
    _保存()
    清理旧停靠记录()


def 画在容器里(面板) -> bool:
    """这一帧本面板的内容应该由侧栏画（= 不要自己开窗口）。

    ★ 三条边界，缺一条就会出现"面板两头都不画、用户以为不见了"：
      · 标签条收起时：谁都不画（`每帧()` 已经把 `面板.可见` 设成 False）
      · `独立窗口 = True`：永远不进侧栏
      · **不在名单里的面板**：让它自己开窗口（否则它既不在侧栏、又不自己画 = 消失）
    ★ 这里必须和 `每帧()` 用同一套判断（含第 1 帧的"侧栏即将出现"预判），
      否则第 1 帧本面板会抢在侧栏前面自己开一个浮动窗口（实测：闪一下）。
    """
    if not _标签条可见:
        return False
    if bool(getattr(面板, "独立窗口", False)):
        return False
    if not 分栏(_名字(面板)):
        return False
    return 有容器() or _侧栏即将出现()


def _侧栏即将出现() -> bool:
    """侧栏文件在不在（只用来兜住"第 1 帧侧栏还没登记"这个空档）。

    ★ 为什么需要它：面板的 `画面板` 处理器按**文件名顺序**注册，`侧栏.py` 可能排在
      其它面板后面 → 第 1 帧侧栏还没进 `_面板`。没有这个预判，其它面板会在第 1 帧
      各自开一个浮动窗口闪一下。
    """
    global _侧栏已就位
    if _侧栏已就位:
        return True
    try:
        _侧栏已就位 = os.path.exists(os.path.join(_面板目录, "侧栏.py"))
    except Exception:                                                    # noqa: BLE001
        _侧栏已就位 = False
    return _侧栏已就位


def 记录(面板) -> None:
    """面板自己开的窗口里，`imgui.Begin(...)` **之后**调用。

    ★ 侧栏时代这个方法**什么也不做**，但它必须继续存在：面板文件里都在调它。
      旧语义是"点 × = 收回页签容器"；现在面板要么归侧栏管（自己不开窗口），
      要么是 `独立窗口`（要不要关由它自己决定，例如【外观】用菜单开关）。
    """
    return None


# ---------------------------------------------------------------------------
# 面板每一帧要调的两个函数
# ---------------------------------------------------------------------------
def 每帧(面板) -> bool:
    """面板的 `画面板()` **开头**调用（必须在 `if not self.可见` 之前）。

    做四件事：登记面板 → 处理快捷键 → 广播可见性 → 返回这一帧该不该画。

    ★ 可见性规则：`标签条可见 and 侧栏在`；但 **`独立窗口 = True` 的面板不受连坐**
      ——【展示】是"加载重力/冻结"的物理总闸，标签条一收起就把它一起藏了，
      用户会以为软件坏了。
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

    独立 = bool(getattr(面板, "独立窗口", False))
    容器在 = 有容器() or _侧栏即将出现()
    面板.可见 = True if 独立 else bool(_标签条可见 and 容器在)
    面板._不可关闭生效 = bool(getattr(面板, "不可关闭", False))
    return bool(getattr(面板, "可见", True))


# ---------------------------------------------------------------------------
# 一键恢复 / 重置版面
# ---------------------------------------------------------------------------
def 全部显示() -> None:
    """F9：显示标签条 + 收起所有临时展开（钉住保留）。

    ★ 顺手把已登记面板的 `可见` 立刻置 True：面板的可见性是每帧由 `每帧()` 广播的，
      如果只改标签条状态，得等下一帧才看见效果（自检里就会读出"还是不可见"）。
    """
    设标签条可见(True)
    收起全部(保留钉住=True)
    for 面板 in _面板.values():
        if not bool(getattr(面板, "独立窗口", False)):
            try:
                面板.可见 = True
            except Exception:                                            # noqa: BLE001
                continue
    print("【面板】已恢复：标签条显示、临时展开的都收起了（钉住的保留）。"
          "点标签即可展开，或看菜单 Panels", flush=True)


def 重置版面() -> None:
    """Shift+F9：清掉 ~/.mujoco.ini 里我们这些窗口的痕迹，下次启动回到出厂位置。

    ★ 为什么需要它：ImGui 会把窗口位置/停靠信息写进 ini。用户把窗口拖到屏幕外、
      或者旧版本留下一个"脱离主布局的 DockNode"时，窗口就会**画了但看不见**，
      而且在运行中没有任何办法把它拽回来（那是 ini 加载时就决定的）。
      唯一可靠的办法就是清掉那些记录 + 重开软件。
    """
    收起全部(保留钉住=False)
    设标签条可见(True)
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


def 清理旧停靠记录() -> bool:
    """**只做一次**：把 `~/.mujoco.ini` 里我们这些窗口的旧停靠记录清掉。

    ★ 它修的是用户遇到的那个真实故障：老版本里用户把两个浮动面板拖到一起，ImGui 就在
      ini 里留下一个**脱离主布局的 DockNode**（`DockId=0x00000009`）。之后每次启动，
      ImGui 都把窗口塞进那个没人认领的节点里 → **窗口有绘制次数，屏幕上什么都没有**。
      新版面板归侧栏管、不再产生这种节点，所以这条清理只需要跑一次。
    """
    global _已迁移
    if _已迁移:
        return False
    # ★ 用**新**标记文件：容器换侧栏是一次机制变更，得让它再清一次，
    #   把旧版【工作台】窗口（`[Window][Workbench]`）与它那个悬浮停靠节点一并抹掉。
    _需要清理 = os.path.join(_包根, "输出", ".侧栏已迁移")
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
            f.write("面板改侧栏后已经清理过一次 ~/.mujoco.ini 里的旧停靠记录。\n"
                    "删掉本文件会在下次启动时再清理一次。\n")
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 迁移标记写入失败（不影响使用，下次启动会再清理一次）：{type(异常).__name__}: {异常}")
    if 清过:
        print("【面板】检测到旧版的窗口停靠记录（会让面板「画了但看不见」）—— "
              "已清理 ~/.mujoco.ini 里我们这些窗口的段落，本次启动即生效", flush=True)
    return 清过


def _清理ini() -> bool:
    """把 ~/.mujoco.ini 里我们自己的窗口段落与停靠记录删掉。

    只删"我们的窗口名"对应的 `[Window][xxx]` 段，以及所有 `DockId=` 行
    （官方那 19 个面板的布局由官方 `configure_docking_layout()` 重建，
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


# ---------------------------------------------------------------------------
# 快捷键
# ---------------------------------------------------------------------------
def 有界面上下文() -> bool:
    """ImGui 上下文在不在。

    ★ 为什么必须问这一句：`imgui.IsKeyPressed(...)` 在没有上下文时不是抛异常，
      而是**直接段错误**（实测）。本模块在"没开窗口"的场合也会被用到
      （例如 `验证/面板注册表自检.py` 直接调 每帧/全部显示），
      所以凡是要碰 ImGui 的地方都先过这一关。
    """
    try:
        问 = getattr(imgui, "GetCurrentContext", None)
        return bool(问()) if 问 is not None else False
    except Exception:                                                    # noqa: BLE001
        return False


_有界面上下文 = 有界面上下文          # 旧名保留（模块内与老脚本都在用）


def _帧号() -> int:
    """当前帧号；**没有 ImGui 上下文时返回 -1**（`GetFrameCount()` 无上下文会段错误）。"""
    if not 有界面上下文():
        return -1
    try:
        return int(imgui.GetFrameCount())
    except Exception:                                                    # noqa: BLE001
        return -1


def 处理快捷键() -> None:
    """轮询快捷键。每帧只真正轮询一次（面板有 7 个，都会调本函数）。"""
    global _上一帧
    if not 有界面上下文():
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
    """万一侧栏没画出来（界面被拖到屏幕外等），终端要吭声，而不是让用户干瞪眼。"""
    global _已提醒卡住
    if _已提醒卡住 or _注册首帧 < 0 or not 有容器():
        return
    帧 = _帧号()
    if 帧 < 0 or 帧 - _注册首帧 < 180:          # 约 3 秒
        return
    _已提醒卡住 = True
    if not _标签条可见:
        print("【面板】侧栏标签条当前是【收起】状态。按 F9 或菜单 Panels → Reveal all 打开；"
              "Shift+F9 = 重置版面（下次启动回到出厂位置）", flush=True)
