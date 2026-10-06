"""
面板/侧栏.py —— 【侧栏】容器：两条 26px 竖向标签条 + 从边上抽出的面板

它取代了旧的【工作台】页签容器（面板容器.py）。为什么换（完整论证见
`优化（软件优化的报告都放这里面来）/报告/界面侧栏改造_设计规格.md` §1.2）：

    ★ 我们的窗口**停靠不进**官方 Dockspace —— 9 组现场实验一致结论：
      `DockId` 记得住，但 ImGui 永不真的启用停靠；手写 ini 造出的节点会被当空节点剪掉；
      整套重建的版面下一帧就被官方抢回去。所以"把面板停靠到 Options / Inspector 下面"
      这条路是死的。
    ★ 可行的做法是**纯窗口定位**：官方 `ux.configure_docking_layout()` 每帧返回 3D 视口的
      矩形（实测 `(296,22,678,746)`），我们据此把标签条贴在它内侧 26px、把展开面板
      摆到边上。收起状态下 3D 中央一格不占。

本文件分两层，**刻意分开**：
    · 上半：纯函数（几何计算 + "该不该自动收起"）—— 不碰 imgui，能被自检脚本逐条钉住；
    · 下半：`侧栏面板`（窗口绘制）—— 由 `软件/启动.py` 的面板自动加载约定加载。

★ 面板上的文字**只能是 ASCII**（官方 UI 字体没有中文字形）；控件 ID 一律用 ASCII 序号，
  不要拿中文面板名进 `##`（ImGui 解析会歧义，仓库踩过）。
"""
from __future__ import annotations

import os as _os
import sys as _sys

_外壳目录 = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _外壳目录 not in _sys.path:
    _sys.path.insert(0, _外壳目录)

from mujoco.experimental.dear_imgui import dear_imgui as imgui       # noqa: E402
from mujoco.experimental.studio import messages, viewer_protocol      # noqa: E402

# ★ 名册（谁能进侧栏、进哪一栏、标签怎么竖排）的唯一真源在【面板注册表】——
#   本模块只负责画。方向是 侧栏 → 注册表 单向 import，避免两个模块互相 import 成环。
import 面板注册表                                                     # noqa: E402
from 面板注册表 import 左栏, 右栏, 短名, 分栏, 标签文字            # noqa: E402,F401

import 菜单栏                                                         # noqa: E402

# ---------------------------------------------------------------------------
# 常量（数值来自设计规格 §3，改动要同步规格与 验证/侧栏自检.py）
# ---------------------------------------------------------------------------
标签条宽 = 26.0          # 收起态每侧只占这么宽
展开宽 = 300.0           # 抽出面板的宽度（两侧同时钉住时按可用宽度收缩）
展开最高 = 600.0
展开上边距 = 8.0         # 展开面板顶部相对 3D 区顶部的留白
展开下边距 = 16.0
自动收起宽限 = 0.8       # 秒；鼠标移出后这么久才收（钉住的不收）
最小可画宽 = 2 * 标签条宽 + 120.0      # 172：比这更窄就别画了（两边都摆不下）
最小可画高 = 200.0


# ---------------------------------------------------------------------------
# 纯函数：几何
# ---------------------------------------------------------------------------
def _合法侧(侧: str) -> bool:
    return 侧 in ("左", "右")


def 能画吗(三D: tuple[float, float, float, float]) -> bool:
    """拿到可用的 3D 矩形了吗。

    ★ 第一帧时官方 `configure_docking_layout()` 还没被调用 → 返回的可能是 `(0,0,0,0)`。
      这一帧必须**只登记、不绘制**：拿零矩形去算会得到负宽窗口，ImGui 会画出鬼影。
    """
    try:
        _, _, 宽, 高 = (float(v) for v in 三D)
    except Exception:                                                    # noqa: BLE001
        return False
    宽, 高 = _夹宽高(宽, 高)
    return 宽 >= 最小可画宽 and 高 >= 最小可画高


def _夹宽高(宽: float, 高: float) -> tuple[float, float]:
    """把异常几何（NaN / 负数 / 非数）夹成 0，免得算出负宽窗口。"""
    if 宽 != 宽 or 高 != 高:                # NaN
        return 0.0, 0.0
    return max(0.0, 宽), max(0.0, 高)


def 算标签条矩形(三D: tuple[float, float, float, float], 侧: str) -> tuple[float, float, float, float]:
    """标签条贴在该侧 3D 边缘的**内侧**（官方 Options / Inspector 一格都不盖）。"""
    if not _合法侧(侧):
        return (0.0, 0.0, 0.0, 0.0)
    x, y, 宽, 高 = (float(v) for v in 三D)
    if 侧 == "左":
        return (x, y, 标签条宽, 高)
    return (x + 宽 - 标签条宽, y, 标签条宽, 高)


def 单侧最大宽(三D: tuple[float, float, float, float]) -> float:
    """两侧同时展开也不重叠时，每侧最多能有多宽（再窄也保底 60）。"""
    _, _, 宽, _ = (float(v) for v in 三D)
    return max(60.0, (宽 - 2.0 * 标签条宽) / 2.0)


def 算展开面板矩形(三D: tuple[float, float, float, float], 侧: str) -> tuple[float, float, float, float]:
    """抽出面板的位置尺寸：紧贴标签条外侧，顶部与 3D 区顶部对齐（+8）。"""
    if not _合法侧(侧):
        return (0.0, 0.0, 0.0, 0.0)
    x, y, 宽, 高 = (float(v) for v in 三D)
    面板宽 = min(展开宽, 单侧最大宽(三D))
    面板高 = max(120.0, min(展开最高, 高 - 展开下边距))
    面板y = y + 展开上边距
    if 侧 == "左":
        return (x + 标签条宽, 面板y, 面板宽, 面板高)
    return (x + 宽 - 标签条宽 - 面板宽, 面板y, 面板宽, 面板高)


# ---------------------------------------------------------------------------
# 纯函数：状态判定
# ---------------------------------------------------------------------------
def 该自动收起(悬停中: bool, 已钉住: bool, 移出时刻: float, 现在: float,
               宽限: float = 自动收起宽限) -> bool:
    """鼠标移出后过了宽限时间就该收起。

    `移出时刻 = 0` 表示"从来没移出过"（窗口刚开、或者鼠标一直在上面）→ 永不因此收起。
    钉住（图钉）时不收 —— 那是用户明确要求常驻。
    """
    if 悬停中 or 已钉住:
        return False
    if not 移出时刻:                       # 0 或 None
        return False
    # ★ 加一个极小的容差：ImGui 的秒是 float32/float64 混着来的，
    #   实测 `100.8 - 100.0 = 0.7999999999999972`，"恰好到点"会被判成没收。
    #   语义上"到点即收"，所以这里往"收"的方向容错。
    return (float(现在) - float(移出时刻)) + 1e-6 >= float(宽限)


# ---------------------------------------------------------------------------
# 官方版面矩形：每帧从 ux.configure_docking_layout() 的返回值里取
#   ★ 为什么包它：它就是官方 "Options(左) / 3D(中) / Inspector(右)" 的权威几何，
#     每帧都会算一次并返回中央工作区矩形（实测 (296,22,678,746)）。
#     我们据此把标签条贴到 3D 区内侧 —— 官方将来改版面，我们一行都不用改。
#   ★ 必须在**第一帧之前**装好（侧栏实例化时就装，见 __init__）。
# ---------------------------------------------------------------------------
_三D: dict = {"矩形": (0.0, 0.0, 0.0, 0.0), "次数": 0}
_探针已装 = False


def 安装版面探针() -> None:
    """包装 `ux.configure_docking_layout`，把中央 3D 矩形每帧记下来（幂等）。"""
    global _探针已装
    if _探针已装:
        return
    try:
        from mujoco.experimental.studio import ux
        原版 = ux.configure_docking_layout
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 侧栏：拿不到官方版面接口，侧栏不会出现（{type(异常).__name__}: {异常}）")
        return

    def 包装(*args, **kwargs):
        结果 = 原版(*args, **kwargs)
        try:
            _三D["矩形"] = tuple(float(v) for v in 结果)
            _三D["次数"] += 1
        except Exception:                                                # noqa: BLE001
            pass                          # 几何取不到就保持上一帧的，绝不影响官方版面
        return 结果

    try:
        ux.configure_docking_layout = 包装
        _探针已装 = True
        print("【侧栏】已接上官方版面矩形：标签条位置每帧按 3D 视口实算（不写死像素）",
              flush=True)
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 侧栏：无法包装官方版面接口（{type(异常).__name__}: {异常}）")


def 当前三D() -> tuple[float, float, float, float]:
    return _三D["矩形"]                     # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 侧栏容器本体
# ---------------------------------------------------------------------------
class 侧栏面板:
    """【侧栏】容器：两条 26px 标签条 + 从边上抽出的面板。

    它自己也是一个"面板"（`面板类 = 侧栏面板`），这样 `软件/启动.py` 的面板自动加载
    约定能把它拉起来，**不用改任何外壳文件**（外壳核心文件被 `零改动自检.py` 钉着哈希）。
    """

    面板显示名 = "侧栏"
    页签名 = "Rails"

    # ★ 它不进自己画的名册（也不受标签条开关连坐）：它自己就是画标签条的那一个
    独立窗口 = True

    # 窗口标志：两个标签条与抽出的面板都不许被拖动/缩放/折叠（位置由我们每帧实算）
    #   ★ 这个绑定里枚举**不能**用 `|` 组合（实测 TypeError），必须 int() 之后按位或
    窗口标志 = (int(imgui.WindowFlags.NoTitleBar) | int(imgui.WindowFlags.NoResize)
              | int(imgui.WindowFlags.NoMove) | int(imgui.WindowFlags.NoScrollbar)
              | int(imgui.WindowFlags.NoCollapse) | int(imgui.WindowFlags.NoSavedSettings)
              | int(imgui.WindowFlags.NoBringToFrontOnFocus) | int(imgui.WindowFlags.NoNavFocus))

    悬停标志 = imgui.HoveredFlags.RootAndChildWindows.value

    def __init__(self):
        self.viewer = None
        self.可见 = True
        self.绘制次数 = 0
        self.错误次数 = 0
        self._帧 = 0
        self._上一快捷键帧 = -1
        self._悬停中 = False
        self._移出时刻 = 0.0
        self._实例: dict[str, object] = {}
        # ★ 必须在第一帧之前：① 状态文件与旧停靠记录 ② 菜单栏挂载 ③ 版面矩形探针
        面板注册表.确保状态文件()
        菜单栏.安装包装()
        安装版面探针()

    # ------------------------------------------------------------------
    @messages.handler(priority=messages.Priority.CRITICAL)
    def 记下窗口(self, event: viewer_protocol.ViewerInitEvent) -> bool:
        self.viewer = getattr(event, "viewer", None)
        return False

    # ------------------------------------------------------------------
    # 快捷键：Esc = 收起临时展开；Ctrl+1..7 = 直接展开第 N 格
    #   ★ 轮询要"每帧只做一次"（7 个面板都会调 面板注册表.每帧 → 本类也可能被多次触发）
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
            io = imgui.GetIO()
            if imgui.IsKeyPressed(imgui.Key.Escape):
                面板注册表.收起全部(保留钉住=True)
            if io.KeyCtrl:
                键表 = (imgui.Key.N1, imgui.Key.N2, imgui.Key.N3, imgui.Key.N4,
                        imgui.Key.N5, imgui.Key.N6, imgui.Key.N7)
                名单 = 面板注册表.侧栏顺序()
                for i, 键 in enumerate(键表):
                    if i < len(名单) and imgui.IsKeyPressed(键):
                        面板注册表.切换展开(名单[i])
                        break
        except Exception:                                                # noqa: BLE001
            pass                     # 快捷键失败绝不能影响面板绘制
        return False

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    @messages.handler
    def 画面板(self, event: messages.BuildGuiEvent) -> bool:
        面板注册表.每帧(self)                 # ★ 必须在可见性检查之前（F9 靠它）
        if not self.可见:
            return False
        self.绘制次数 += 1
        三D = 当前三D()
        if not 能画吗(三D):
            # 第一帧还没有几何（官方版面函数还没被调用）→ 只登记，不画，免得画出鬼影
            return False
        try:
            self._实例 = {面板注册表._名字(p): p for p in 面板注册表.全部面板()}
            悬停 = False
            if 面板注册表.标签条可见():
                悬停 = self._画标签条(三D, "左") or 悬停
                悬停 = self._画标签条(三D, "右") or 悬停
            悬停 = self._画展开面板(三D, "左") or 悬停
            悬停 = self._画展开面板(三D, "右") or 悬停
            self._推进自动收起(悬停)
        except Exception as 异常:                                        # noqa: BLE001
            self.错误次数 += 1
            if self.错误次数 <= 2:
                print(f"⚠ 侧栏绘制出错：{type(异常).__name__}: {异常}")
        return False

    # -- 标签条 --------------------------------------------------------
    def _画标签条(self, 三D, 侧: str) -> bool:
        名单 = 面板注册表.左栏名单() if 侧 == "左" else 面板注册表.右栏名单()
        if not 名单:
            return False
        x, y, 宽, 高 = 算标签条矩形(三D, 侧)
        imgui.SetNextWindowPos(imgui.Vec2(x, y), imgui.Cond.Always.value)
        imgui.SetNextWindowSize(imgui.Vec2(宽, 高), imgui.Cond.Always.value)
        展开, _ = imgui.Begin(f"##标签条{侧}", None, int(侧栏面板.窗口标志))
        悬停 = False
        try:
            if not 展开:
                return False
            悬停 = bool(imgui.IsWindowHovered(int(侧栏面板.悬停标志)))
            for i, 名 in enumerate(名单):
                选中 = bool(面板注册表.展开中() == 名 or 面板注册表.是钉住(名))
                竖排 = "\n".join(面板注册表.标签文字(名))
                颜色压栈 = 0
                if 选中:
                    imgui.PushStyleColor(int(imgui.Col.Button), imgui.Vec4(0.20, 0.45, 0.75, 1.0))
                    颜色压栈 = 1
                try:
                    if imgui.Button(f"{竖排}##{侧}标签{i}"):
                        面板注册表.切换展开(名)
                finally:
                    if 颜色压栈:
                        imgui.PopStyleColor()
        finally:
            imgui.End()
        return 悬停

    # -- 抽出的面板 ----------------------------------------------------
    def _画展开面板(self, 三D, 侧: str) -> bool:
        名单 = 面板注册表.左栏名单() if 侧 == "左" else 面板注册表.右栏名单()
        要画 = [名 for 名 in 名单 if 面板注册表.是钉住(名)]
        展开中 = 面板注册表.展开中()
        if 展开中 in 名单 and 展开中 not in 要画:
            要画.append(展开中)
        if not 要画:
            return False
        x, y, 宽, 高 = 算展开面板矩形(三D, 侧)
        悬停 = False
        for i, 名 in enumerate(要画):
            面板 = self._实例.get(名)
            if 面板 is None:
                continue
            窗口名 = f"{面板注册表.页签名(面板)}##侧栏{侧}{i}"
            imgui.SetNextWindowPos(imgui.Vec2(x, y), imgui.Cond.Always.value)
            imgui.SetNextWindowSize(imgui.Vec2(宽, 高), imgui.Cond.Always.value)
            展开, _ = imgui.Begin(窗口名, None, int(侧栏面板.窗口标志))
            try:
                悬停 = bool(imgui.IsWindowHovered(int(侧栏面板.悬停标志))) or 悬停
                if not 展开:
                    continue
                self._画面板标题条(名, 侧, i)
                imgui.Separator()
                try:
                    面板._画内容()
                except Exception as 异常:                                    # noqa: BLE001
                    面板.错误次数 = int(getattr(面板, "错误次数", 0)) + 1
                    if 面板.错误次数 <= 2:
                        print(f"⚠ 面板【{名}】在侧栏里绘制出错：{type(异常).__name__}: {异常}")
                    imgui.TextDisabled(f"[fail] this panel raised an error: {type(异常).__name__}")
                    imgui.TextDisabled("(details printed in the terminal; the rest keeps working)")
            finally:
                imgui.End()
        return 悬停

    def _画面板标题条(self, 名: str, 侧: str, 序号: int) -> None:
        """面板自己的一行小标题：名字 + [pin] + [x]（面板上只能 ASCII）。"""
        钉 = 面板注册表.是钉住(名)
        imgui.TextDisabled(面板注册表.标签文字(名))
        imgui.SameLine()
        if imgui.SmallButton(f"{'unpin' if 钉 else 'pin'}##侧栏钉{侧}{序号}"):
            面板注册表.设钉住(名, not 钉)
        imgui.SameLine()
        if imgui.SmallButton(f"x##侧栏关{侧}{序号}"):
            if 钉:
                面板注册表.设钉住(名, False)
            面板注册表.设展开("")
        imgui.SameLine()
        imgui.TextDisabled("(pin = keep it open | x = collapse)")

    # -- 自动收起 ------------------------------------------------------
    def _推进自动收起(self, 悬停中: bool) -> None:
        展开中 = 面板注册表.展开中()
        钉住 = bool(展开中) and 面板注册表.是钉住(展开中)
        if not 展开中 or 钉住:
            self._移出时刻 = 0.0
            self._悬停中 = 悬停中
            return
        现在 = float(imgui.GetTime()) if 面板注册表.有界面上下文() else 0.0
        if 悬停中:
            self._移出时刻 = 0.0                   # 鼠标回来了 → 重新计时
        elif not self._悬停中 and self._移出时刻 == 0.0:
            self._移出时刻 = 现在                   # 刚移出的那一刻
        if 该自动收起(悬停中, 钉住, self._移出时刻, 现在):
            面板注册表.设展开("")
            self._移出时刻 = 0.0
        self._悬停中 = 悬停中


# 启动器约定：模块里叫"面板类"的就是要实例化的面板
面板类 = 侧栏面板
