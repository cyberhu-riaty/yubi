"""
宿主窗口.py —— P3 的核心：**我们自己的窗口**，Web 界面 + 原生 3D 视口同级并列

它和另外两个入口的关系：

    | 入口 | 窗口 | 界面 | 3D |
    |---|---|---|---|
    | `主程序.py`        | 官方 Studio 窗口 | 官方 ImGui + 自研面板 | 官方 Filament |
    | `主程序Web.py`     | 无（外部浏览器） | 浏览器里的 React | ❌ 占位 |
    | **`主程序窗口.py`** | **我们自己的 NSWindow** | **窗口内 WKWebView 里的 React** | **✅ 原生 OpenGL 视口** |

为什么可行：P2 验过（`报告/02_决策与架构方案/P2_Spike结论_同级视图.md`，14/14 自动验收）。

═══ 线程排法（本项目的硬约束，没有例外）═══════════════════════════════════
    AppKit **必须占主线程**（macOS 硬要求）→ 窗口与 3D 都在主线程；
    仿真退回**后台线程**（`启动.启动外壳(无窗=True, 后台线程=True)`）；
    MuJoCo 的**渲染**在第三个线程。
    三者之间只走消息，**不共享 `MjData`** —— 视口有自己那份，靠状态快照同步。

═══ 这个文件踩过的坑（每一条都花了很久，别再犯）═════════════════════════
① **ObjC 类名必须是 ASCII**：`class 视口(...)` 报
   `'视口' not a valid Objective-C class name`。所以类名是 `Viewport` / `HostApp`。

② **方法名决定它会不会被注册成 ObjC 选择器**（规则在 `objc/_transform.py` 的
   `default_selector()`）：**名字里第 2 个字符起若含 `_`、且不以 `_` 结尾 → 纯 Python 方法**。
     · `drawRect_` / `mouseDown_` / `窗口改尺寸_`：**故意**要注册成选择器 → 尾巴一个下划线；
     · 纯内部方法 → `准_备` / `同步_状态` / `视角_复位`（中间下划线）。
   ⚠️ **前缀式 `_准备` 也不行**：实测 `default_selector("_加线")` 返回一个 0 参
      选择器 `_加线`，PyObjC 会把它当 ObjC 方法注册，然后因为 Python 实现带了 4 个
      参数而直接 `BadPrototypeError`（本次真的踩到）。内部方法统一用**中间**下划线
      （`加_线` / `准_备` / `适配_视图`），不要用前缀。
   ⚠️ 尾下划线 `准备_` 会被当选择器 `准备:`（要 0 参、实现有 1 参 → 报错）；
   ⚠️ 无下划线的 `同步状态` 被当 0 参选择器 → 同样报错。
   自查：`objc._transform.default_selector("方法名")`，返回 None 才是纯 Python 方法。

③ **绝不在 AppKit 回调里建第二套 GL 上下文**：`mujoco.Renderer` 自建 CGL 上下文，
   在 `prepareOpenGL` / `drawRect_` / run loop 回调里建它会**直接 SIGTRAP**，
   Python 侧连 traceback 都没有（`faulthandler` 抓不到、`setObjCExceptionHandler` 也不触发）。
   → 渲染器只在**独立线程**里建。

④ **`NSOpenGLView` 是被动绘制的**：没人 `setNeedsDisplay_` 就一帧都不画。

⑤ **别给窗口装 delegate 收 resize**：实测 `窗口.setDelegate_(任意对象)` 会 SIGTRAP
   （与那个对象是否实现 `windowDidResize_` 无关）→ 用 `NSNotificationCenter`。

⑥ **PyObjC 的 `NSTimer` target-selector 在本机完全不触发、也不报错**
   （中文名与 ASCII 名都试过，`isValid()` 返回 True，就是不回调）。
   它还会伪装成"能跑"：`setNeedsDisplay_` 由**窗口系统**驱动，所以界面看着在刷新，
   而真正依赖定时器的东西（状态同步、命令搬运）一直没跑。
   → 用 `软件/定时器.py`（CoreFoundation 的 `CFRunLoopTimer`），走纯 C 回调，实测稳定。

⑦ **委托方法里抛异常 = 静默失效**：AppKit 回调里抛出的 Python 异常会变成 ObjC 异常
   （输出一行 `<class 'NameError'>: ...`），**而且异常之后的代码全部不执行**。
   本次两次"定时器不触发"的真正原因，都是我在 delegate 末尾插的代码里有 `NameError`
   （`定时器` / `记诊断` 未定义），于是"起定时器"那两行从来没被执行到。
   教训：**delegate 里任何改动之后，都要确认它末尾真的执行到了**
   （本文件用 `记诊断()` 写文件来做这件事：`驭臂_宿主诊断=/tmp/宿主.log`）。

⑧ **不要在 run loop 回调里做重活**：主线程的核心动画有硬截止时间，
   在回调里做重活会被 CF 直接杀掉进程（崩溃报告里是 `hard deadline`）。
   所以主线程每帧只做一次 `setNeedsDisplay_`，渲染全在渲染线程。

═══ 为什么渲染要单独一个线程 ═══════════════════════════════════════════════
    MuJoCo 离屏渲染一帧约 7.6 ms（760×420，实测）。看着 60 fps 放得下，
    但放在主线程的绘制路径里会与 AppKit 的显示事务互相干扰（教训 ③⑧）。
    放渲染线程后，主线程每帧只剩一次纹理上传（几十微秒）。

    渲染线程**按需渲染**：只有"有新状态"或"相机变了"才渲一帧，否则空转。
    机器人静止时几乎不耗 CPU；动起来时自然跑到 60 fps。
"""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Any

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
                    NSBezelStyleRounded, NSBezierPath, NSButton, NSButtonTypeToggle, NSColor, NSFont,
                    NSCursor, NSMakeRect, NSOpenGLPFAAccelerated, NSOpenGLPFAColorSize,
                    NSAttributedString, NSAppearance, NSFontAttributeName, NSForegroundColorAttributeName, NSMakeSize, NSMakePoint,
                    NSScrollView, NSSegmentedControl, NSTextView,
                    NSOpenGLPFADepthSize, NSOpenGLPFADoubleBuffer, NSOpenGLPFAOpenGLProfile,
                    NSOpenGLPixelFormat, NSOpenGLProfileVersionLegacy, NSOpenGLView,
                    NSTextField, NSView, NSWindow, NSWindowDidResizeNotification,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
                    NSWindowStyleMaskResizable, NSWindowStyleMaskTitled)
from Foundation import NSNotificationCenter, NSObject, NSURL, NSURLRequest, NSUserDefaults
from WebKit import (WKWebView, WKWebViewConfiguration, WKUserScript,
                   WKUserScriptInjectionTimeAtDocumentStart)

try:
    import 高亮桥 as _高亮桥
except Exception:                                                     # noqa: BLE001
    _高亮桥 = None

# 布局：下方 3D 视口，上方 Web 界面（与 P2 spike 的验收布局一致）
# 布局：**左 Web 界面 / 右 3D 视口**（横向切分）
#
# ★ 为什么从"上下切"改成"左右切"（这是用户明确要求的根本性修改）：
#   上下切的时候，3D 永远是窗口**底下的一条**，看起来像"界面下面挖了个黑窟窿"，
#   而不是"主画面"。实测反馈也确实是这么说的。
#   左右切之后 3D 是右侧**主区域**（占 60%+ 宽、整窗高），和参考项目一致：
#   左边是面板（资产/参数/日志），右边是场景。
默认网页宽比 = 0.40      # 左侧 Web 面板占窗口宽度的比例
网页最小宽 = 500.0       # 再窄就放不下活动栏 + 侧栏
视口最小宽 = 560.0       # 3D 再窄就不好操作了（原 420 太窄，曲线/机械臂都挤）
def _切分宽度(总宽: float) -> tuple[float, float]:
    """把窗口宽度切成 (左 Web 宽, 右 3D 宽)，两边都有下限。

    ★ 为什么要有下限：窗口很窄时按比例分会出现"Web 只剩 200px"或"3D 只剩 100px"，
      两个都看不清。宁可让 3D 少一点，也要保证 Web 面板正常
      （活动栏 48 + 侧栏最小 180 = 228，留余量取 520）。
    """
    总 = float(总宽)
    网 = max(float(网页最小宽), min(总 * 默认网页宽比, 总 - float(视口最小宽)))
    网 = round(网)
    return 网, round(总) - 网


def _工程面板高度(视口宽: float, 总高: float) -> float:
    """3D 变窄时，底部工程面板应占的高度（0 = 不显示）。

    ★ 判据不是"窗口比例"，而是 3D 视口的**宽高比**：3D 越窄越高，画面越容易
      在上下留黑边。目标比 0.95 ≈「还能看清机械臂、又不用整窗高」；低于它时，
      把差额让给底部工程面板，3D 仍贴着窗口上边。
    ★ 下限 190 px：内容少时不要占太高的空间；需要时再调。
    总高的 45% 上限：防止面板把 3D 挤没。
    """
    宽 = max(1.0, float(视口宽))
    高 = max(1.0, float(总高))
    if 宽 >= 高 * 0.95:
        return 0.0
    差 = 高 - 宽 / 0.95
    return max(190.0, min(高 * 0.50, 差))


默认窗口 = (1440.0, 920.0)

# 诊断文件：delegate 里抛异常时 stdout 可能被别的东西占着，所以关键节点写一份文件。
# 排查用：驭臂_宿主诊断=/tmp/宿主.log
# 视口槽：入口（主程序窗口）注册状态观察者后，把建好的视口回填到这里，
# 这样"仿真线程 → 视口"这条线不需要视口自己去认识启动模块。
视口槽: dict = {"视口": None}

# 最后建成的宿主实例。给平台适配层取"视口矩形 / 统计"用 ——
# 窗口是单例形态（一个进程一个窗口），所以模块级变量就够，不必搞注册表。
_最后主人 = None

def 取视口矩形() -> tuple[int, int, int, int] | None:
    """原生 3D 渲染面当前占的矩形 (x, y, 宽, 高)，逻辑像素；没有则 None。"""
    主人 = _最后主人
    if 主人 is None or 主人.视口 is None:
        return None
    try:
        f = 主人.视口.frame()
        return (int(f.origin.x), int(f.origin.y), int(f.size.width), int(f.size.height))
    except Exception:                                                 # noqa: BLE001
        return None


def 取统计() -> dict:
    """运行统计（帧率、帧数、错误…）。排查用，**不参与业务**。"""
    主人 = _最后主人
    if 主人 is None:
        return {"状态": "窗口未启动"}
    v = 主人.视口
    出 = {
        "主线程帧": 主人.主线程帧,
        "网页": 主人.网页 is not None,
        "视口矩形": 取视口矩形(),
    }
    if v is not None:
        出.update({
            "3D就绪": bool(v.就绪),
            "3D渲染帧": v.统计.get("渲染帧", 0),
            "3D显示帧": v.统计.get("显示帧", 0),
            "3D帧率": round(float(v.统计.get("fps", 0.0)), 1),
            "3D同步次数": v.统计.get("同步", 0),
            "3D错误": v.错误,
        })
    else:
        出["3D就绪"] = False
    return 出

_诊断路径 = os.environ.get("驭臂_宿主诊断", "")
_诊断序号 = [0]


def 记诊断(内容: str) -> None:
    """关键节点写一行到诊断文件（没设环境变量就什么也不做）。"""
    if not _诊断路径:
        return
    try:
        _诊断序号[0] += 1
        with open(_诊断路径, "a", encoding="utf-8") as f:
            f.write(f"{_诊断序号[0]:3d} [{time.strftime('%H:%M:%S')}] {内容}\n")
    except Exception:                                                 # noqa: BLE001
        pass


def _模型包围盒(模型, 数据) -> tuple[Any, Any, float]:
    """用世界坐标几何算视觉包围盒（给自动取景/网格定尺用）。

    为什么不用 `geom_pos`：那是 body 局部坐标，直接平均会落在底座附近，
    相机贴脸、机械臂顶出画面（实测半径 0.36 vs 真实 ~0.85）。
    为什么不用 `stat.extent`：模型自带值对 1 m 臂偏大，画面偏小。
    为什么用 `geom_xpos + geom_rbound`：MuJoCo 已按真实 mesh 算好世界坐标包围球。

    排除面片/高度场和 worldbody 装饰（地面、天空盒），否则包围盒会被撑到无穷大。
    """
    import mujoco
    import numpy as np

    位置 = np.asarray(数据.geom_xpos, dtype=float).reshape(-1, 3)
    半径 = np.asarray(模型.geom_rbound, dtype=float).ravel()
    类型 = np.asarray(模型.geom_type).ravel()
    所属 = np.asarray(模型.geom_bodyid).ravel()
    有效 = np.isfinite(位置).all(axis=1) & np.isfinite(半径) & (半径 > 0)
    有效 &= ~np.isin(类型, [int(mujoco.mjtGeom.mjGEOM_PLANE),
                          int(mujoco.mjtGeom.mjGEOM_HFIELD)])
    有效 &= (所属 != 0)
    if not bool(有效.any()):
        # 有些模型把整台机器人放在 worldbody 里；此时退回“只排面片”
        有效 = np.isfinite(位置).all(axis=1) & np.isfinite(半径) & (半径 > 0)
    位置, 半径 = 位置[有效], 半径[有效]
    # 防御：贴地大平面 / 环境装饰的半径会远大于机器人部件
    中位 = float(np.median(半径)) if len(半径) else 0.0
    正常 = 半径 < max(1.0, 中位 * 8.0)
    if bool(正常.any()):
        位置, 半径 = 位置[正常], 半径[正常]
    低 = (位置 - 半径[:, None]).min(axis=0)
    高 = (位置 + 半径[:, None]).max(axis=0)
    if not np.isfinite(低).all() or not np.isfinite(高).all() or bool((高 <= 低).any()):
        raise ValueError("包围盒退化")
    return 低, 高, float(np.max(高 - 低))


def _取景(模型, 数据, 宽: int, 高: int, 方位: float, 仰角: float,
          余量: float = 1.10) -> tuple[Any, float, float]:
    """按包围盒 + 真实投影方向算相机（中心、距离、模型尺度）。

    ★ 不再用“包围球半径 / tan(fovy/2)”：那会把相机拉得比需要远 40%+
      （机器人只占 50% 画面高），而且中心是几何平均点，画面会偏。
      这里把包围盒 8 个角投到相机的 right/up 上，分别按水平/竖直视场求最小距离。
    """
    import mujoco
    import numpy as np

    低, 高盒, 尺度 = _模型包围盒(模型, 数据)
    中心 = (低 + 高盒) / 2.0
    半 = (高盒 - 低) / 2.0

    fovy = float(getattr(模型.vis.global_, "fovy", 45.0) or 45.0)
    tan_v = math.tan(math.radians(fovy) / 2.0)
    tan_h = tan_v * (float(宽) / max(1.0, float(高)))
    if tan_h <= 1e-9 or tan_v <= 1e-9:
        raise ValueError("视场角退化")

    # 用距离 1 的临时相机取 MuJoCo 的相机基（right/up/forward），
    # 这样取景方向与真正渲染时完全一致，不用自己推一遍符号。
    选项 = mujoco.MjvOption()
    mujoco.mjv_defaultOption(选项)
    临时 = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(模型, 临时)
    临时.azimuth, 临时.elevation = float(方位), float(仰角)
    临时.lookat[:] = 中心
    临时.distance = 1.0
    场景 = mujoco.MjvScene(模型, maxgeom=1000)
    mujoco.mjv_updateScene(模型, 数据, 选项, None, 临时,
                           mujoco.mjtCatBit.mjCAT_ALL, 场景)
    相机0 = 场景.camera[0]
    相机位 = np.asarray(相机0.pos, dtype=float)
    前 = np.asarray(相机0.forward, dtype=float)
    上 = np.asarray(相机0.up, dtype=float)
    右 = np.cross(前, 上)
    右 /= max(1e-9, float(np.linalg.norm(右)))
    上 /= max(1e-9, float(np.linalg.norm(上)))

    边距 = float(max(半)) * 0.04
    角们 = np.array([
        [x, y, z]
        for x in (低[0] - 边距, 高盒[0] + 边距)
        for y in (低[1] - 边距, 高盒[1] + 边距)
        for z in (低[2] - 边距, 高盒[2] + 边距)
    ])
    需要 = 0.0
    for 点 in 角们:
        相对 = 点 - 相机位
        深0 = float(np.dot(相对, 前))
        x = float(np.dot(相对, 右))
        y = float(np.dot(相对, 上))
        # 相机后退 Δ 后深度变成 深0+Δ；要求 |x|/深 <= tan_h、|y|/深 <= tan_v
        需要 = max(需要, abs(x) / tan_h, abs(y) / tan_v)
    if not math.isfinite(需要) or 需要 <= 0.05:
        raise ValueError("取景距离退化")
    return 中心, float(需要 * 余量), 尺度


def _网格定尺(尺度: float) -> tuple[float, int]:
    """网格步长/半径：小机器人 0.1 m 一格，大场景 0.5/1 m 一格。"""
    if 尺度 < 2.0:
        return 0.1, 10
    if 尺度 < 8.0:
        return 0.5, 10
    return 1.0, 10


class Viewport(NSOpenGLView):
    """原生 3D 视口：MuJoCo 场景 + 轨道相机。

    三块数据分清楚，免得混：
      ① **模型** `模型`：自己装一份（只读）
      ② **数据** `数据`：自己那份 `MjData`，由渲染线程从状态快照同步（不与仿真共享）
      ③ **相机** `相机`：方位角/仰角/距离/注视点，主线程写、渲染线程读
    """

    def initWithFrame_(self, frame):
        属性 = [NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersionLegacy,
               NSOpenGLPFAColorSize, 24, NSOpenGLPFADepthSize, 24,
               NSOpenGLPFADoubleBuffer, NSOpenGLPFAAccelerated, 0]
        格式 = NSOpenGLPixelFormat.alloc().initWithAttributes_(属性)
        self = objc.super(Viewport, self).initWithFrame_pixelFormat_(frame, 格式)
        if self is None:
            return None
        self.就绪 = False
        self.错误 = ""
        self.模型 = None
        self.数据 = None
        self.相机 = None
        self.选项 = None
        self.渲染器 = None
        self.状态缓冲 = None
        self.缓冲表: dict = {}
        # 画面由渲染线程写、主线程只读；用"代"号避免重复上传纹理
        self.画面 = None
        self.画面代 = 0
        self.已传代 = -1
        self.纹理 = 0
        self.统计 = {"fps": 0.0, "渲染帧": 0, "显示帧": 0, "同步": 0}
        self._帧时刻: list[float] = []
        self._该停 = False
        self._渲染线程 = None
        self._模型代 = 0
        self._模型路径 = ""
        self.切换中 = False
        # ★ 用 Event 等"该渲染了"，**不要用 sleep 忙等**：忙等会一直抢 GIL，
        #   把主线程饿死（实测表现为主线程在跑、而渲染/显示一帧都没有）。
        import threading as _th
        self._要渲 = _th.Event()
        # ★ 画布（离屏渲染分辨率）与窗口大小**解耦**：窗口拉伸只是把这张图放大，
        #   不重新渲染。理由是渲染成本随像素数涨得很快：
        #   760×420 ≈ 7.6 ms/帧，而 1280×464 ≈ 258 ms/帧（实测，约 34 倍）。
        #   视口是"看机器人姿态"用的，760×420 足够；真要更清晰再单独调这里。
        # 离屏渲染分辨率。0×0 表示"还没算过"，首次 `按视口重算画布()` 会填上
        # （= 视口的原生像素尺寸，渲染与显示 1:1，不缩放 → 不糊）。
        self.画布尺寸 = (760, 420)
        self._画布目标 = (760, 420)
        self._画布要重建 = False
        # 只有极端情况（5K 全屏 + 高 DPI）才碰这个上限；正常窗口远低于它
        self._画布上限 = (2560, 1600)
        self._天空 = None            # 缓存的天渐变（尺寸变了才重建，见 `_铺天空`）
        self._拖拽起点 = (0.0, 0.0)
        self._拖拽中 = False
        self._平移中 = False
        # 分隔条拖动期间锁住 3D 相机输入：分隔条拖动只应该改尺寸，
        # 不允许滚轮/拖拽事件漏进视口把相机拉近（用户报过"拖动后机械臂顶到脸上"）。
        self.交互锁定 = False
        # 最新状态快照：**仿真线程写、主线程读**。
        # 只做"整体替换一个引用"，所以不需要锁（CPython 的属性赋值是原子的）。
        self.最新状态 = None
        # 相机：默认相机在装载时按模型算一次；复位回到它，适配则按当前姿态重算。
        self.默认相机 = None
        self.网格开 = True
        self.末端坐标开 = True
        self.高亮关节 = None
        self._网格 = (0.1, 10)
        self._尺度 = 1.0
        # 第一次收到仿真状态后按**真实姿态**再取一次景：
        # 装载时的 model 默认姿态与仿真线程发来的首帧可能不同（实测机械臂会偏到右边）
        self._首帧已取景 = False
        return self

    # ------------------------------------------------------------------
    # 装载：模型 + 渲染器（在独立线程里做，见教训 ③）
    # ------------------------------------------------------------------
    def 换_模型(self, 模型路径: str) -> bool:
        """主线程调用：停旧渲染线程、清状态、装载新模型。"""
        if not 模型路径 or not os.path.exists(模型路径):
            self.错误 = f"模型文件不存在：{模型路径}"
            记诊断(f"✗ 换模型：{self.错误}")
            return False
        self.切换中 = True
        self.停止_渲染线程()
        self._模型代 += 1          # 让尚未完成的旧装载线程作废
        self.就绪 = False
        self.错误 = ""
        self.模型 = None
        self.数据 = None
        self.相机 = None
        self.选项 = None
        self.状态缓冲 = None
        self.缓冲表 = {}
        self.最新状态 = None
        self.默认相机 = None
        self._首帧已取景 = False
        # ★ 不清 self.画面 / 纹理：新模型装载期间继续显示上一帧，
        #   避免"点一下先黑屏再出现"。新帧到达后由渲染线程自然覆盖。
        self.准_备(模型路径)
        self.setNeedsDisplay_(True)
        记诊断(f"换模型：开始装载 {os.path.basename(模型路径)}")
        return True

    def 停止_渲染线程(self) -> None:
        """停掉旧渲染线程并等它退出（渲染器在它自己的线程里 close）。"""
        self._该停 = True
        self._要渲.set()
        t = self._渲染线程
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        self._渲染线程 = None
        self.渲染器 = None

    def 准_备(self, 模型路径: str, 画布: tuple[int, int] | None = None) -> None:
        """装载模型并起渲染线程。**渲染器在渲染线程里建**（见 `_渲染循环`）。"""
        self._模型路径 = 模型路径
        self._模型代 += 1
        代 = self._模型代
        if 画布:
            self.画布尺寸 = (int(画布[0]), int(画布[1]))
        else:
            # 用"按视口算出来的目标尺寸"起步，避免第一帧还是默认比例
            self.画布尺寸 = self._画布目标
            self._画布要重建 = False

        def 装载_干活():
            try:
                import mujoco
                import numpy as np
                模型 = mujoco.MjModel.from_xml_path(模型路径)
                数据 = mujoco.MjData(模型)
                mujoco.mj_forward(模型, 数据)
                # ★ 离屏帧缓冲默认只有 640×480，渲更大会
                #   `ValueError: Image width 760 > framebuffer width 640`（P2 教训）
                模型.vis.global_.offwidth = max(1280, self.画布尺寸[0])
                模型.vis.global_.offheight = max(720, self.画布尺寸[1])
                相机 = mujoco.MjvCamera()
                mujoco.mjv_defaultFreeCamera(模型, 相机)
                # 默认视角要能看清整台机器人（默认视角常在模型外面）
                #
                # ★ 改成**按模型包围球自动取景**：原来写死 distance=3.2 / lookat z=0.45，
                #   对 Franka（约 1 m）勉强，换成 UR10e / iiwa14 就不合适了 ——
                #   小模型会缩成一点，大模型会顶出画面。这才是"模型看着太小"的原因。
                #   用 `geom_pos` 与 `geom_rbound` 算包围球（MuJoCo 白送的字段）。
                # ★ 自动取景：包围盒 8 个角投到相机平面，按水平/竖直视场求距离。
                #   旧版用“包围球半径 / tan(fovy/2)”，Franka 只占约 54% 画高，
                #   而且中心取的是几何平均点（偏上），所以画面看起来“又小又靠下”。
                相机.azimuth, 相机.elevation = 135.0, -24.0
                try:
                    宽画布, 高画布 = self.画布尺寸
                    中心, 距离, 尺度 = _取景(
                        模型, 数据, 宽画布, 高画布,
                        方位=相机.azimuth, 仰角=相机.elevation, 余量=1.10)
                    相机.lookat[:] = 中心
                    相机.distance = float(距离)
                    self.默认相机 = (中心.copy(), float(距离),
                                     float(相机.azimuth), float(相机.elevation))
                    self._尺度 = float(尺度)
                    self._网格 = _网格定尺(self._尺度)
                    记诊断(f"自动取景：中心={中心.round(3).tolist()} "
                           f"尺度={尺度:.3f} 距离={相机.distance:.3f} "
                           f"网格={self._网格[0]}m")
                except Exception as _取景异常:                            # noqa: BLE001
                    相机.distance, 相机.elevation = 2.6, -24.0
                    相机.lookat[:] = (0.0, 0.0, 0.45)
                    self.默认相机 = (相机.lookat.copy(), 2.6, 135.0, -24.0)
                    self._尺度 = 1.0
                    self._网格 = (0.1, 10)
                    记诊断(f"自动取景失败，退回默认视角：{_取景异常}")
                选项 = mujoco.MjvOption()
                mujoco.mjv_defaultOption(选项)
                # ★ **渲染器不在这里建**：`mujoco.Renderer` 会自建一套 GL 上下文，
                #   而"在哪建"和"在哪用"必须同一个线程 —— 在装载线程建、却在渲染线程用，
                #   实测会**卡死在第一次 render() 里**（不报错、不返回）。
                #   所以渲染器放到 `_渲染循环` 开头建。
                if 代 != self._模型代:
                    return
                self.模型, self.数据 = 模型, 数据
                self.相机, self.选项 = 相机, 选项
                # ★ 缓冲尺寸必须与**发布方的签名**一致。仿真那边发的是
                #   `mjSTATE_INTEGRATION`（nq+nv 个数），这里若按 FULLPHYSICS 开缓冲，
                #   `mj_setState` 会报 `state size should equal mj_stateSize(m, sig)`。
                #   所以两种尺寸都备好，按快照里的签名选（见 `同步_状态`）。
                self.缓冲表 = {
                    int(mujoco.mjtState.mjSTATE_INTEGRATION): np.zeros(
                        mujoco.mj_stateSize(模型, int(mujoco.mjtState.mjSTATE_INTEGRATION)),
                        np.float64),
                    int(mujoco.mjtState.mjSTATE_FULLPHYSICS): np.zeros(
                        mujoco.mj_stateSize(模型, int(mujoco.mjtState.mjSTATE_FULLPHYSICS)),
                        np.float64),
                }
                self.状态缓冲 = self.缓冲表[int(mujoco.mjtState.mjSTATE_INTEGRATION)]
                if 代 != self._模型代:
                    return
                self.就绪 = True
                self.切换中 = False
                self._首帧已取景 = False
                self._该停 = False
                self._渲染线程 = threading.Thread(target=self._渲染循环, daemon=True,
                                                  name="3D渲染线程")
                self._渲染线程.start()
                self.请求渲染()
                记诊断(f"视口装载完成：{os.path.basename(模型路径)} "
                      f"nq={模型.nq} nu={模型.nu} 画布={self.画布尺寸}")
                print(f"  ✓ 3D 视口：已装载 {os.path.basename(模型路径)}"
                      f"（nq={模型.nq} nu={模型.nu}）", flush=True)
            except Exception as 异常:                                 # noqa: BLE001
                if 代 == self._模型代:
                    self.切换中 = False
                self.错误 = f"{type(异常).__name__}: {异常}"
                记诊断(f"视口装载失败：{self.错误}")
                print(f"  ✗ 3D 视口装载失败：{self.错误}", flush=True)

        threading.Thread(target=装载_干活, daemon=True, name="视口装载").start()

    # ------------------------------------------------------------------
    # 状态同步（只在渲染线程或主线程调；两边都不并发写）
    # ------------------------------------------------------------------
    def 同步_状态(self, 状态消息: Any) -> bool:
        """把状态快照灌进**自己那份** mjData。

        ★ 为什么不共享 MjData：仿真在后台线程、渲染在渲染线程，共享可变对象就要加锁；
          而"拷一份集成状态"只有几十个 double，代价可忽略，还完全没有竞态。
        """
        if not self.就绪 or 状态消息 is None or self.状态缓冲 is None:
            return False
        try:
            import mujoco
            状态 = 状态消息.state
            签名 = int(getattr(状态消息, "state_sig",
                             int(mujoco.mjtState.mjSTATE_INTEGRATION)))
            # 按签名挑正确尺寸的缓冲：尺寸与签名不匹配时 mj_setState 会直接报错
            缓冲 = self.缓冲表.get(签名)
            if 缓冲 is None or len(缓冲) != len(状态):
                缓冲 = self.按需_开缓冲(签名, len(状态))
            if 缓冲 is None:
                self.错误 = f"状态尺寸不匹配：签名={签名} 长度={len(状态)}"
                return False
            缓冲[:] = 状态
            self.状态缓冲 = 缓冲
            mujoco.mj_setState(self.模型, self.数据, 缓冲, 签名)
            mujoco.mj_forward(self.模型, self.数据)
            self.统计["同步"] += 1
            # 首帧按仿真侧的真实姿态重新取景（装载时用的是模型默认姿态）
            if not self._首帧已取景 and self.就绪:
                self._首帧已取景 = True
                try:
                    self.适配_视图()
                    记诊断("首帧状态到达：已按真实姿态重新取景")
                except Exception as _取景异常:                            # noqa: BLE001
                    记诊断(f"首帧取景失败（保留装载取景）：{_取景异常}")
            return True
        except Exception as 异常:                                     # noqa: BLE001
            self.错误 = f"同步状态失败：{type(异常).__name__}: {异常}"
            return False

    def 按需_开缓冲(self, 签名: int, 长度: int):
        """签名没见过就按需开一个正好长度的缓冲（并记下来复用）。"""
        try:
            import numpy as np
            if self.缓冲表.get(签名) is not None and len(self.缓冲表[签名]) != 长度:
                del self.缓冲表[签名]
            缓冲 = np.zeros(长度, np.float64)
            self.缓冲表[签名] = 缓冲
            return 缓冲
        except Exception:                                             # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 渲染线程：按需渲染，产出像素放进 self.画面
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 画布比例
    # ------------------------------------------------------------------
    # ---- 让离屏画布的比例跟上视口，否则画面会被"信箱式"留黑边 ----
    def 按视口重算画布(self) -> None:
        """离屏画布 = 视口的**原生像素尺寸**（渲染多少就显示多少，1:1 不缩放）。

        ★ 这一版是踩了两个坑之后才定下来的，两个坑都直接是用户报的 bug：

        坑 ①（模糊）：原来画布固定 760×420，再放大到 2880 宽的视口上 ——
          放大约 2.6 倍，画面必然糊。当时压小画布的理由是"渲染成本随像素数猛涨"，
          那条依据来自早期一次测量（760×420 ≈ 7.6ms，1280×464 ≈ 258ms）。
          **这次重新测了一遍，结论是错的**：
              760×420   4.3 ms   1440×900   6.9 ms   2400×1400  8.7 ms
          像素数涨 10 倍，耗时只从 4.3ms 到 8.7ms。所以"为了性能压小画布"没有依据，
          按原生分辨率渲染完全跑得动（2.1MP ≈ 7.4ms ≈ 135fps）。

        坑 ②（缩放窗口时"视角变了"）：原来按**宽高比**算画布，窗口一变比例，
          画布比例跟着变；而 MuJoCo 的 fovy 是**竖直**方向的，
          竖直不动、横向范围变 → 看起来就是"视角/远近被改了"。
          现在画布=视口原样，横向纵向都按真实比例，窗口拉伸就只是"看到更多/更少"，
          和任何 3D 软件一致，不再有"视角自己动了"的错觉。

        性能兜底：给一个很宽松的上限（见 `_画布上限`），只防 5K 全屏这种极端情况。
        """
        尺寸 = self.convertRectToBacking_(self.bounds()).size
        宽 = max(1, int(尺寸.width))
        高 = max(1, int(尺寸.height))
        if 宽 <= 1 or 高 <= 1:
            # 首次布局时 bounds 可能还没就绪 → 用窗口逻辑尺寸 × 2（Retina）估一份，
            # 等真正的 resize 通知到了会再校正一次。
            宽, 高 = 1440, 900
        # ★ 上限按**总像素**扣，不是按单边截断。
        #   我第一版写成 `宽=min(宽,2560); 高=min(高,1600)`，结果视口高 1750 被截到 1600
        #   → 画布比例与视口不一致 → 上屏只能等比缩放 → **上下各留一条黑边**。
        #   按面积等比缩，比例永远不变，代价只是极端大窗口下略微柔和。
        面积 = 宽 * 高
        上限面积 = 4_200_000            # ≈ 2048×2048，实测 ≈8.7ms/帧，够 100+ fps
        if 面积 > 上限面积:
            因子 = (上限面积 / 面积) ** 0.5
            宽 = max(1, int(宽 * 因子))
            高 = max(1, int(高 * 因子))
        if (宽, 高) != self._画布目标:
            self._画布目标 = (宽, 高)
            self._画布要重建 = True

    # ------------------------------------------------------------------
    # 背景：把纯黑换成渐变天空
    # ------------------------------------------------------------------
    def 画面_铺天空(self, 图) -> None:
        """把渲染结果里**接近纯黑**的像素替换成渐变天空色。

        ★ 为什么这样做，而不是给模型加 skybox：
          skybox 必须写进 MJCF（`<texture type="skybox">` + `<visual skybox>`），
          而我们的模型是第三方资产，改 XML 会带来"路径/包含/校验和"一堆副作用，
          还会让"加载的模型"和"磁盘上的模型"不再一致。
          渲染完之后在**像素层**替换背景，对模型零侵入。

        ★ 阈值取得很严（三通道都 < 4）。机器人的深色部件（黑色夹爪等）
          实测最暗也在 10 以上，不会被误伤；而 MuJoCo 的背景是精确的 (0,0,0)。

        ★ 只在**真的存在黑像素**时才做替换，且用三次逐通道比较而不是
          `max(axis=2)` —— 后者要分配一个 2.7MB 的临时数组，每帧都分配会拖慢帧率。
        """
        try:
            import numpy as _np
            高, 宽 = 图.shape[0], 图.shape[1]
            # ★ 用"位或"算掩码：三次逐通道比较 + 两次逻辑与，比 max(axis=2) 便宜得多
            #   （后者要分配一个 2.7MB 的临时数组，每帧分配会明显拖慢）。
            掩码 = (图[:, :, 0] | 图[:, :, 1] | 图[:, :, 2]) < 4
            if self._天空 is None or self._天空.shape[0] != 高 or self._天空.shape[1] != 宽:
                # 深色工程场景：顶部深蓝、地平线略亮、近地再压暗。
                # 旧版是"上蓝下白"，灰色机器人压在浅底上对比很弱；
                # 网格线是浅色不透明线，在这层背景上还能保持可见（不会变成暗点）。
                行 = _np.linspace(0.0, 1.0, 高, dtype=_np.float32)[:, None]
                顶 = _np.array([22, 36, 54], dtype=_np.float32)
                中 = _np.array([55, 74, 96], dtype=_np.float32)
                底 = _np.array([38, 52, 70], dtype=_np.float32)
                上半 = _np.clip(行 / 0.55, 0.0, 1.0)
                下半 = _np.clip((行 - 0.55) / 0.45, 0.0, 1.0)
                色带 = 顶[None, :] * (1.0 - 上半) + 中[None, :] * 上半
                色带 = 色带 * (1.0 - 下半) + 底[None, :] * 下半
                self._天空 = _np.repeat(色带[:, None, :], 宽, axis=1).astype(_np.uint8)
            # ★ 这里原来写的是 `图[掩码] = self._天空[掩码]`（布尔索引），
            #   实测 **57.5 ms/帧**，帧率从 60 掉到 11.8 —— 肉眼可见地卡。
            #   布尔索引会为 3×2.7M 个元素各建一份临时数组；换成逐通道
            #   `np.where` 后是 **7.3 ms/帧**（快 8 倍），60 fps 稳态不受影响。
            #   （另外两种也量过：copyto 15.4ms，仅 copy 0.4ms）
            for _c in range(3):
                图[:, :, _c] = _np.where(掩码, self._天空[:, :, _c], 图[:, :, _c])
        except Exception:                                             # noqa: BLE001
            pass          # 天空只是观感，失败绝不影响 3D 本身

    # ------------------------------------------------------------------
    # 场景装饰：地面网格 / 世界坐标 / 末端坐标
    # ------------------------------------------------------------------
    def 加_线(self, 场景, 起, 止, 颜色, 宽: float = 1.0) -> None:
        """往 MjvScene 里追加一条装饰线段（不动物理、不改 MJCF）。"""
        import mujoco
        import numpy as np
        if 场景 is None or 场景.ngeom >= 场景.maxgeom:
            return
        几何 = 场景.geoms[场景.ngeom]
        mujoco.mjv_initGeom(
            几何, int(mujoco.mjtGeom.mjGEOM_LINE),
            np.array([float(宽), 0.0, 0.0], dtype=float),
            np.zeros(3, dtype=float), np.eye(3).reshape(9),
            np.array(颜色, dtype=np.float32))
        mujoco.mjv_connector(
            几何, int(mujoco.mjtGeom.mjGEOM_LINE), float(宽),
            np.asarray(起, dtype=float), np.asarray(止, dtype=float))
        几何.category = int(mujoco.mjtCatBit.mjCAT_DECOR)
        场景.ngeom += 1

    def 画_装饰(self, 场景) -> None:
        """网格 + 世界轴 + 末端坐标。颜色/线宽都是装饰，不参与任何判定。"""
        import numpy as np
        if 场景 is None:
            return
        if self.网格开:
            步长, 格数 = self._网格
            范围 = float(步长) * int(格数)
            for i in range(-格数, 格数 + 1):
                if i == 0:
                    continue
                主格 = (i % 5 == 0)
                颜色 = (0.52, 0.60, 0.70, 1.0) if 主格 else (0.30, 0.36, 0.43, 1.0)
                宽 = 2.0 if 主格 else 1.0
                值 = i * 步长
                self.加_线(场景, (值, -范围, 0.0), (值, 范围, 0.0), 颜色, 宽)
                self.加_线(场景, (-范围, 值, 0.0), (范围, 值, 0.0), 颜色, 宽)
            # 世界坐标：X 红 / Y 绿 / Z 蓝。只画 3 格长，避免 Z 轴穿出机器人头顶像一条杂线。
            轴长 = 3.0 * float(步长)
            self.加_线(场景, (0, 0, 0), (轴长, 0, 0), (0.95, 0.28, 0.28, 1), 3)
            self.加_线(场景, (0, 0, 0), (0, 轴长, 0), (0.28, 0.85, 0.38, 1), 3)
            self.加_线(场景, (0, 0, 0), (0, 0, 轴长), (0.35, 0.55, 1.0, 1), 3)
            # 原点标记（小球）：一眼看出世界原点在哪
            if 场景.ngeom < 场景.maxgeom:
                import mujoco
                几何 = 场景.geoms[场景.ngeom]
                mujoco.mjv_initGeom(
                    几何, int(mujoco.mjtGeom.mjGEOM_SPHERE),
                    np.array([0.012, 0.0, 0.0], dtype=float),
                    np.zeros(3, dtype=float), np.eye(3).reshape(9),
                    np.array([0.85, 0.92, 1.0, 1.0], dtype=np.float32))
                几何.category = int(mujoco.mjtCatBit.mjCAT_DECOR)
                场景.ngeom += 1
        if self.末端坐标开:
            self.画_末端坐标(场景)
        # 关节高亮：日志里的 Jn 点击后到这里画一个橙色球 + 三条短线。
        # 只做视觉标记，不改变任何物理量。
        if self.高亮关节 is not None and self.模型 is not None and self.数据 is not None:
            try:
                import mujoco
                关节 = int(self.高亮关节)
                if 0 <= 关节 < int(self.模型.njnt):
                    位置 = np.asarray(self.数据.xanchor[关节], dtype=float).reshape(3)
                    半径 = max(0.04, min(0.09, float(self._尺度) * 0.055))
                    # 关节锚点常在连杆内部，只画球会被挡住：从锚点向上引一根
                    # 橙色针，针顶再画球/坐标轴，保证在模型外面也看得见。
                    针长 = max(0.18, min(0.38, float(self._尺度) * 0.18))
                    针顶 = 位置 + np.array([0.0, 0.0, 针长], dtype=float)
                    self.加_线(场景, 位置, 针顶, (1.0, 0.50, 0.08, 1), 4.0)
                    for 球位置 in (位置, 针顶):
                        if 场景.ngeom < 场景.maxgeom:
                            几何 = 场景.geoms[场景.ngeom]
                            mujoco.mjv_initGeom(
                                几何, int(mujoco.mjtGeom.mjGEOM_SPHERE),
                                np.array([半径, 0.0, 0.0], dtype=float),
                                球位置, np.eye(3).reshape(9),
                                np.array([1.0, 0.55, 0.08, 1.0], dtype=np.float32))
                            几何.category = int(mujoco.mjtCatBit.mjCAT_DECOR)
                            场景.ngeom += 1
                    长 = max(0.10, min(0.22, float(self._尺度) * 0.14))
                    for 轴, 色 in enumerate(((1.0, 0.45, 0.10, 1),
                                             (1.0, 0.80, 0.20, 1),
                                             (0.35, 0.75, 1.00, 1))):
                        方向 = np.zeros(3, dtype=float)
                        方向[轴] = 长
                        self.加_线(场景, 针顶, 针顶 + 方向, 色, 3.0)
            except Exception:                                         # noqa: BLE001
                pass

    def 画_末端坐标(self, 场景) -> None:
        """在末端 site（没有就最后一个 body）画一小段 RGB 坐标轴。"""
        import mujoco
        import numpy as np
        if self.模型 is None or self.数据 is None:
            return
        位置 = None
        旋转 = None
        站点 = -1
        for i in range(int(self.模型.nsite)):
            名 = mujoco.mj_id2name(self.模型, int(mujoco.mjtObj.mjOBJ_SITE), i) or ""
            小写 = 名.lower()
            if any(k in 小写 for k in ("attach", "ee_", "tool", "tcp", "grip", "flange")):
                站点 = i
                break
        if 站点 < 0 and int(self.模型.nsite) > 0:
            站点 = int(self.模型.nsite) - 1
        if 站点 >= 0:
            位置 = np.asarray(self.数据.site_xpos[站点], dtype=float)
            旋转 = np.asarray(self.数据.site_xmat[站点], dtype=float).reshape(3, 3)
        elif int(self.模型.nbody) > 1:
            体 = int(self.模型.nbody) - 1
            位置 = np.asarray(self.数据.xpos[体], dtype=float)
            旋转 = np.asarray(self.数据.xmat[体], dtype=float).reshape(3, 3)
        if 位置 is None or 旋转 is None:
            return
        长 = 0.08
        for 轴, 颜色 in enumerate(((0.95, 0.35, 0.35, 1),
                                  (0.35, 0.90, 0.45, 1),
                                  (0.40, 0.60, 1.00, 1))):
            self.加_线(场景, 位置, 位置 + 旋转[:, 轴] * 长, 颜色, 2.0)

    def _渲染循环(self) -> None:
        import time as _t
        while not self._该停:
            if self.渲染器 is None:
                # 在**本线程**建渲染器（GL 上下文的"建"与"用"必须同线程）
                import mujoco
                self.渲染器 = mujoco.Renderer(self.模型, height=self.画布尺寸[1],
                                            width=self.画布尺寸[0])
                记诊断(f"渲染线程：渲染器已建（画布={self.画布尺寸}）")
                self.请求渲染()
            # 等 100 ms；超时也不做事，只是给"该停了"一个检查点。
            # 不用忙等（见 `_要渲` 的说明）。
            if not self._要渲.wait(0.1):
                continue
            self._要渲.clear()
            try:
                # 视口比例变了就**重建**渲染器（GL 上下文同线程，见教训 ③）。
                #   mujoco.Renderer 不提供 setSize，只能重建 —— 所以这一步故意做成
                #   "只在比例变化时"才发生，拖动窗口的过程中最多重建几次。
                if self._画布要重建 and self.模型 is not None:
                    self._画布要重建 = False
                    self.画布尺寸 = self._画布目标
                    # ★ 必须同步抬高 MuJoCo 的离屏帧缓冲上限，否则会报
                    #   `ValueError: Image width N > framebuffer width M`
                    #   （这条坑 P2 就踩过一次，改分辨率时最容易复发）。
                    self.模型.vis.global_.offwidth = max(
                        int(self.模型.vis.global_.offwidth), int(self.画布尺寸[0]))
                    self.模型.vis.global_.offheight = max(
                        int(self.模型.vis.global_.offheight), int(self.画布尺寸[1]))
                    try:
                        self.渲染器.close()
                    except Exception:                                 # noqa: BLE001
                        pass
                    self.渲染器 = mujoco.Renderer(self.模型, height=self.画布尺寸[1],
                                                  width=self.画布尺寸[0])
                    记诊断(f"渲染线程：画布重建为 {self.画布尺寸}")
                self.渲染器.update_scene(self.数据, camera=self.相机,
                                       scene_option=self.选项)
                # ★ 装饰必须加在 update_scene 之后：它每帧会重置 ngeom。
                self.画_装饰(self.渲染器.scene)
                图 = self.渲染器.render()
                # 把 MuJoCo 的**纯黑背景**换成渐变天空（视觉，不改任何物理）
                self.画面_铺天空(图)
                # OpenGL 纹理坐标是下到上；copy 让主线程安全读（切片本身是视图）
                self.画面 = 图[::-1].copy()
                self.画面代 += 1
                self.统计["渲染帧"] += 1
                现在 = _t.perf_counter()
                self._帧时刻.append(现在)
                del self._帧时刻[:-90]
                if len(self._帧时刻) >= 2:
                    跨度 = self._帧时刻[-1] - self._帧时刻[0]
                    if 跨度 > 0.2:
                        self.统计["fps"] = (len(self._帧时刻) - 1) / 跨度
            except Exception as 异常:                                     # noqa: BLE001
                self.错误 = f"渲染线程：{type(异常).__name__}: {异常}"
                记诊断(f"✗ {self.错误}")
                _t.sleep(0.5)
        try:
            if self.渲染器 is not None:
                self.渲染器.close()
        except Exception:                                             # noqa: BLE001
            pass
        self.渲染器 = None
        self.统计["渲染线程退出"] = 1

    def 请求渲染(self) -> None:
        """叫渲染线程渲一帧（有新状态或相机变了就调这个）。"""
        self._要渲.set()

    def 收_状态(self, 快照) -> None:
        """仿真线程调用：只把快照放好，别的都不做（不能碰 AppKit）。"""
        self.最新状态 = 快照

    # ------------------------------------------------------------------
    # 绘制（主线程）：只上传纹理 + 贴屏，不做 MuJoCo 渲染
    # ------------------------------------------------------------------
    def prepareOpenGL(self):
        """只做上下文自己的事。**绝不在这里建渲染器**（教训 ③）。"""
        objc.super(Viewport, self).prepareOpenGL()
        self.openGLContext().makeCurrentContext()
        记诊断("视口：prepareOpenGL 完成")

    def reshape(self):
        objc.super(Viewport, self).reshape()
        try:
            self.openGLContext().update()
        except Exception:                                             # noqa: BLE001
            pass
        self.setNeedsDisplay_(True)

    def viewDidChangeBackingProperties(self):
        objc.super(Viewport, self).viewDidChangeBackingProperties()
        self.setNeedsDisplay_(True)

    def drawRect_(self, _脏区):
        from OpenGL import GL
        try:
            上下文 = self.openGLContext()
            上下文.makeCurrentContext()
            # ★ 每帧绘制前再 update 一次：窗口/分隔条 resize 时，
            #   AppKit 的 reshape 和我们的 layout 都可能比 drawable 快一拍；
            #   如果 drawable 还是旧尺寸而 glViewport 已经用新尺寸，
            #   画面就会被裁切/放大（用户报的"机械臂顶到脸上"）。
            try:
                上下文.update()
            except Exception:                                         # noqa: BLE001
                pass
            尺寸 = self.convertRectToBacking_(self.bounds()).size
            宽, 高 = max(1, int(尺寸.width)), max(1, int(尺寸.height))
            GL.glViewport(0, 0, 宽, 高)
            GL.glClearColor(0.020, 0.047, 0.086, 1.0)     # 与界面底色一致
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            图 = self.画面
            if 图 is not None:
                import numpy as np
                图 = np.ascontiguousarray(图)
                高图, 宽图, _ = 图.shape
                if self.纹理 == 0:
                    self.纹理 = GL.glGenTextures(1)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self.纹理)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                else:
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self.纹理)
                if self.画面代 != self.已传代:              # 有新画面才重传
                    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, 宽图, 高图, 0,
                                    GL.GL_RGB, GL.GL_UNSIGNED_BYTE, 图.tobytes())
                    self.已传代 = self.画面代
                # 等比铺满，两侧留底色（比拉伸好看）
                图比 = 宽图 / 高图
                视比 = 宽 / 高
                if 图比 > 视比:
                    半宽, 半高 = 1.0, (视比 / 图比)
                else:
                    半宽, 半高 = (图比 / 视比), 1.0
                GL.glMatrixMode(GL.GL_PROJECTION); GL.glLoadIdentity()
                GL.glOrtho(0, 1, 0, 1, -1, 1)
                GL.glMatrixMode(GL.GL_MODELVIEW); GL.glLoadIdentity()
                GL.glEnable(GL.GL_TEXTURE_2D)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self.纹理)
                GL.glColor3f(1, 1, 1)
                GL.glBegin(GL.GL_QUADS)
                GL.glTexCoord2f(0, 0); GL.glVertex2f(0.5 - 半宽 / 2, 0.5 - 半高 / 2)
                GL.glTexCoord2f(1, 0); GL.glVertex2f(0.5 + 半宽 / 2, 0.5 - 半高 / 2)
                GL.glTexCoord2f(1, 1); GL.glVertex2f(0.5 + 半宽 / 2, 0.5 + 半高 / 2)
                GL.glTexCoord2f(0, 1); GL.glVertex2f(0.5 - 半宽 / 2, 0.5 + 半高 / 2)
                GL.glEnd()
                GL.glDisable(GL.GL_TEXTURE_2D)
                self.统计["显示帧"] += 1
            上下文.flushBuffer()
        except Exception as 异常:                                         # noqa: BLE001
            if self.统计["显示帧"] == 0:
                self.错误 = f"drawRect_: {type(异常).__name__}: {异常}"
                记诊断(f"✗ 绘制失败：{self.错误}")

    # ------------------------------------------------------------------
    # 轨道相机：拖拽转、滚轮缩放、Shift 拖拽平移
    # ------------------------------------------------------------------
    def acceptsFirstResponder(self) -> bool:
        return True

    def mouseDown_(self, 事件):
        if getattr(self, "交互锁定", False):
            return
        # 点进 3D 才让视口拿键盘焦点：这样 R/F/G 不会和网页输入框抢键。
        try:
            self.window().makeFirstResponder_(self)
        except Exception:                                             # noqa: BLE001
            pass
        if int(事件.clickCount()) >= 2:
            self.适配_视图()
            return
        self._拖拽起点 = (事件.locationInWindow().x, 事件.locationInWindow().y)
        self._拖拽中 = True
        # NSEventModifierFlagShift = 1 << 17
        self._平移中 = bool(事件.modifierFlags() & (1 << 17))

    def mouseUp_(self, 事件):
        self._拖拽中 = False

    def mouseDragged_(self, 事件):
        if not self.就绪 or getattr(self, "交互锁定", False):
            return
        import math
        x, y = 事件.locationInWindow().x, 事件.locationInWindow().y
        dx, dy = x - self._拖拽起点[0], y - self._拖拽起点[1]
        self._拖拽起点 = (x, y)
        if self._平移中:
            比例 = self.相机.distance * 0.0018
            方位 = math.radians(self.相机.azimuth)
            self.相机.lookat[0] += (-dx * abs(math.cos(方位))
                                  + dy * abs(math.sin(方位))) * 比例
            self.相机.lookat[1] += (dx * abs(math.sin(方位))
                                  + dy * abs(math.cos(方位))) * 比例
        else:
            self.相机.azimuth -= dx * 0.4
            self.相机.elevation = max(-89.0, min(89.0, self.相机.elevation - dy * 0.4))
        self.请求渲染()
        self.setNeedsDisplay_(True)

    def scrollWheel_(self, 事件):
        if not self.就绪 or getattr(self, "交互锁定", False):
            return
        # 分隔条刚被点/拖过时，吞掉惯性滚动：否则触控板/鼠标的残余滚动
        # 会把 3D 相机一下拉到 0.4 的最近距离（机械臂顶满画面）。
        主人 = globals().get("_最后主人")
        # 分隔条拖动/窗口调整后，触控板惯性滚动经常还会持续一两秒；
        # 0.8s 不够，残余滚动会把相机推进机械臂（用户看到的"巨大局部"）。
        if 主人 is not None and time.monotonic() - getattr(主人, "分栏交互时刻", 0.0) < 2.0:
            return
        # 0.4/0.8 都仍然会进入"机械臂占满画面"的距离。默认适配距离约 1.84，
        # 1.50 留出整机取景；要近看请用 F/适配或后续专门的聚焦，不靠滚轮钻进去。
        前 = float(self.相机.distance)
        self.相机.distance = max(1.50, min(40.0,
                                     self.相机.distance * (1.0 - 事件.scrollingDeltaY() * 0.014)))
        if abs(self.相机.distance - 前) > 0.001:
            记诊断(f"相机滚轮：{前:.2f} -> {self.相机.distance:.2f}")
        self.请求渲染()
        self.setNeedsDisplay_(True)

    def 适配_视图(self) -> None:
        """按**当前姿态**重新适配（双击 3D 或按 F）。方向保持用户当前视角。"""
        if not self.就绪 or self.模型 is None or self.数据 is None:
            return
        try:
            宽, 高 = self._画布目标
            中心, 距离, 尺度 = _取景(
                self.模型, self.数据, 宽, 高,
                方位=float(self.相机.azimuth), 仰角=float(self.相机.elevation),
                余量=1.10)
            self.相机.lookat[:] = 中心
            self.相机.distance = float(距离)
            self.默认相机 = (中心.copy(), float(距离),
                             float(self.相机.azimuth), float(self.相机.elevation))
            self._尺度 = float(尺度)
            self._网格 = _网格定尺(self._尺度)
            记诊断(f"适配视图：中心={中心.round(3).tolist()} 距离={距离:.3f}")
        except Exception as 异常:                                         # noqa: BLE001
            记诊断(f"适配视图失败：{type(异常).__name__}: {异常}")
        self.请求渲染()
        self.setNeedsDisplay_(True)

    def 视角_复位(self) -> None:
        """回到装载时算好的取景（R 键）。不再写死 3.2 / z=0.45。"""
        if not self.就绪:
            return
        if self.默认相机 is not None:
            中心, 距离, 方位, 仰角 = self.默认相机
            self.相机.lookat[:] = 中心
            self.相机.distance = float(距离)
            self.相机.azimuth = float(方位)
            self.相机.elevation = float(仰角)
        else:
            self.相机.distance, self.相机.azimuth, self.相机.elevation = 2.6, 135.0, -24.0
            self.相机.lookat[:] = (0.0, 0.0, 0.45)
        self.请求渲染()
        self.setNeedsDisplay_(True)

    def 切换_网格(self) -> None:
        self.网格开 = not self.网格开
        记诊断(f"网格：{'开' if self.网格开 else '关'}")
        self.请求渲染()
        self.setNeedsDisplay_(True)

    def 切换_末端坐标(self) -> None:
        self.末端坐标开 = not self.末端坐标开
        self.请求渲染()
        self.setNeedsDisplay_(True)

    def keyDown_(self, 事件):
        """视口获得焦点后的快捷键。R 复位 / F 适配 / G 网格 / E 末端坐标。"""
        字 = (事件.charactersIgnoringModifiers() or "").lower()
        if 字 == "r":
            self.视角_复位()
            return
        if 字 == "f":
            self.适配_视图()
            return
        if 字 == "g":
            self.切换_网格()
            return
        if 字 == "e":
            self.切换_末端坐标()
            return
        objc.super(Viewport, self).keyDown_(事件)


class Splitter(NSView):
    """Web / 3D 之间的原生分隔条（可左右拖）。

    WebView 与原生视口是同级视图；这里放一条 7px 的 NSView 盖在交界处。
    拖它只改两个子视图的 frame 与 3D 画布尺寸，不碰任何业务状态。
    """

    def initWithHost_(self, 宿主):
        self = objc.super(Splitter, self).init()
        if self is None:
            return None
        self.宿主 = 宿主
        self._起点x = 0.0
        self._起点宽 = 0.0
        return self

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), NSCursor.resizeLeftRightCursor())

    def drawRect_(self, 矩形):
        NSColor.colorWithCalibratedWhite_alpha_(0.45, 0.42).setFill()
        NSBezierPath.fillRect_(self.bounds())
        NSColor.colorWithCalibratedWhite_alpha_(0.92, 0.72).setFill()
        宽 = self.bounds().size.width
        高 = self.bounds().size.height
        for 偏移 in (-10.0, 0.0, 10.0):
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect((宽 - 3.0) / 2.0, 高 / 2.0 + 偏移, 3.0, 3.0)).fill()

    def acceptsFirstMouse_(self, _事件):
        # 窗口不是 key 时，第一次点击也能开始拖分隔条。
        return True

    def mouseDown_(self, 事件):
        if int(事件.clickCount()) >= 2:
            self.宿主.重置_分栏()
            return
        self._起点x = float(事件.locationInWindow().x)
        self._起点宽 = float(self.宿主.取_网页宽())
        self.宿主.开始_分栏拖动()

    def mouseDragged_(self, 事件):
        dx = float(事件.locationInWindow().x) - self._起点x
        self.宿主.设_网页宽(self._起点宽 + dx)

    def mouseUp_(self, _事件):
        self.宿主.结束_分栏拖动()


class PanelGrip(NSView):
    """工程面板顶部 7px 抓手：拖动调高度，双击收起/展开。"""

    def initWithPanel_(self, 面板):
        self = objc.super(PanelGrip, self).init()
        if self is None:
            return None
        self.面板 = 面板
        self._起y = 0.0
        self._起高 = 0.0
        return self

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), NSCursor.resizeUpDownCursor())

    def drawRect_(self, _矩形):
        NSColor.colorWithCalibratedWhite_alpha_(0.78, 1.0).setFill()
        NSBezierPath.fillRect_(NSMakeRect(0, self.bounds().size.height - 2, self.bounds().size.width, 1))
        NSColor.colorWithCalibratedWhite_alpha_(0.55, 1.0).setFill()
        宽 = self.bounds().size.width
        for 偏移 in (-5.0, 0.0, 5.0):
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(宽 / 2.0 + 偏移, (self.bounds().size.height - 2) / 2.0, 2.0, 2.0)).fill()

    def acceptsFirstMouse_(self, _事件):
        return True

    def mouseDown_(self, 事件):
        宿主 = getattr(self.面板, "宿主", None)
        if 宿主 is None:
            return
        if int(事件.clickCount()) >= 2:
            宿主.切换_工程面板收起()
            return
        self._起y = float(事件.locationInWindow().y)
        self._起高 = float(getattr(宿主, "面板高", 0.0) or 190.0)
        if getattr(宿主, "_面板收起", False):
            宿主._面板收起 = False
            self._起高 = 190.0
        宿主.开始_工程面板拖动()

    def mouseDragged_(self, 事件):
        宿主 = getattr(self.面板, "宿主", None)
        if 宿主 is None:
            return
        dy = float(事件.locationInWindow().y) - self._起y
        宿主.设_面板高(self._起高 + dy)

    def mouseUp_(self, _事件):
        宿主 = getattr(self.面板, "宿主", None)
        if 宿主 is not None:
            宿主.结束_工程面板拖动()


class ConsolePanel(NSView):
    """全宽工程面板（C 阶段）：原生日志镜像。

    为什么用原生而不是第二个 WKWebView：
      · 第二个 WebView 需要一套跨页日志/命令同步，成本和回归面都很大；
      · 这个面板只需要**展示**真实日志（由 Web 端经 WKScriptMessageHandler 发来），
        不需要 React/DOM；原生 NSTextView 足够稳定。
      · 命令输入仍留在 Web 端；本面板不假装是 shell。
    """

    def initWithFrame_(self, 矩形):
        self = objc.super(ConsolePanel, self).initWithFrame_(矩形)
        if self is None:
            return None
        self._行 = []
        self._总 = 0
        self._状态同步 = False
        self._主筛选 = "无筛选"
        self._筛 = "全部"
        self._头高 = 64.0
        self._收起 = False
        self.宿主 = None
        self._色背景 = NSColor.colorWithCalibratedWhite_alpha_(0.975, 1.0)
        self._色头 = NSColor.colorWithCalibratedWhite_alpha_(0.935, 1.0)
        self._色文字 = NSColor.colorWithCalibratedWhite_alpha_(0.13, 1.0)
        self._色次 = NSColor.colorWithCalibratedWhite_alpha_(0.42, 1.0)
        try:
            # 工程面板固定用浅色：它夹在浅色 Web 与深色 3D 之间，
            # 黑底小字是上一版用户反馈"看不清"的直接原因。
            self.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameAqua"))
        except Exception:                                             # noqa: BLE001
            pass
        self._标题 = NSTextField.alloc().initWithFrame_(NSMakeRect(10, 0, 260, 22))
        self._标题.setStringValue_("工程面板 · 主日志镜像")
        self._标题.setFont_(NSFont.systemFontOfSize_weight_(12.0, 0.4))
        self._标题.setTextColor_(self._色文字)
        self._标题.setDrawsBackground_(False)
        self._标题.setBordered_(False)
        self._标题.setEditable_(False)
        self._标题.setSelectable_(False)
        self._标题.setToolTip_("与左侧控制台使用同一份日志；筛选/清空会同步")
        self.addSubview_(self._标题)

        self._计数 = NSTextField.alloc().initWithFrame_(NSMakeRect(250, 0, 160, 22))
        self._计数.setStringValue_("0 / 0 条")
        self._计数.setFont_(NSFont.systemFontOfSize_(10.0))
        self._计数.setTextColor_(self._色次)
        self._计数.setDrawsBackground_(False)
        self._计数.setBordered_(False)
        self._计数.setEditable_(False)
        self._计数.setSelectable_(False)
        self.addSubview_(self._计数)

        self._筛选 = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(375, 0, 230, 22))
        self._筛选.setSegmentCount_(4)
        for i, 标 in enumerate(("全部", "信息", "注意", "错误")):
            self._筛选.setLabel_forSegment_(标, i)
        self._筛选.setSelectedSegment_(0)
        self._筛选.setTarget_(self)
        self._筛选.setAction_("筛选:")
        self.addSubview_(self._筛选)

        self._清空 = NSButton.alloc().initWithFrame_(NSMakeRect(565, 0, 60, 22))
        self._清空.setTitle_("清空")
        self._清空.setBezelStyle_(NSBezelStyleRounded)
        self._清空.setTarget_(self)
        self._清空.setAction_("清空:")
        self.addSubview_(self._清空)

        self._折叠 = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 60, 22))
        self._折叠.setTitle_("收起")
        self._折叠.setBezelStyle_(NSBezelStyleRounded)
        self._折叠.setTarget_(self)
        self._折叠.setAction_("折叠:")
        self.addSubview_(self._折叠)

        self._抓手 = PanelGrip.alloc().initWithPanel_(self)
        self._抓手.setToolTip_("拖动调整工程面板高度；双击收起/展开")
        self.addSubview_(self._抓手)

        self._滚动 = NSScrollView.alloc().initWithFrame_(NSMakeRect(8, 6, 700, 120))
        self._滚动.setHasVerticalScroller_(True)
        self._滚动.setDrawsBackground_(True)
        self._滚动.setBackgroundColor_(NSColor.whiteColor())
        self._滚动.setBorderType_(0)
        self._文本 = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 700, 120))
        self._文本.setEditable_(False)
        self._文本.setSelectable_(True)
        self._文本.setRichText_(False)
        self._文本.setDrawsBackground_(True)
        self._文本.setBackgroundColor_(NSColor.whiteColor())
        self._文本.setTextColor_(self._色文字)
        self._文本.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11.0, 0.0))
        self._文本.setTextContainerInset_(NSMakeSize(6.0, 4.0))
        self._文本.setMinSize_(NSMakeSize(0.0, 120.0))
        self._文本.setMaxSize_(NSMakeSize(100000.0, 100000.0))
        self._文本.setVerticallyResizable_(True)
        self._文本.setHorizontallyResizable_(False)
        self._文本.textContainer().setWidthTracksTextView_(True)
        self._滚动.setDocumentView_(self._文本)
        self.addSubview_(self._滚动)
        return self

    def drawRect_(self, _矩形):
        self._色背景.setFill()
        NSBezierPath.fillRect_(self.bounds())
        try:
            高 = self.bounds().size.height
            宽 = self.bounds().size.width
            头高 = min(float(self._头高), 高)
            self._色头.setFill()
            NSBezierPath.fillRect_(NSMakeRect(0.0, 高 - 头高, 宽, 头高))
            NSColor.colorWithCalibratedWhite_alpha_(0.78, 1.0).setStroke()
            线 = NSBezierPath.bezierPath()
            线.moveToPoint_(NSMakePoint(0.0, 高 - 头高))
            线.lineToPoint_(NSMakePoint(宽, 高 - 头高))
            线.stroke()
        except Exception:                                             # noqa: BLE001
            pass

    def 排_面板(self, 宽: float, 高: float) -> None:
        宽 = max(1.0, float(宽))
        高 = max(1.0, float(高))
        # 统一两行头：第一行标题/计数/收起，第二行筛选/清空。
        # 这样 560~900px 的右列都不会把控件挤成一条。
        self._头高 = 34.0 if self._收起 else 64.0
        上 = 高 - 25
        self._标题.setFrame_(NSMakeRect(10, 上, max(100, 宽 - 330), 20))
        self._计数.setFrame_(NSMakeRect(max(120, 宽 - 300), 上, 120, 20))
        self._折叠.setFrame_(NSMakeRect(宽 - 76, 上 - 1, 60, 22))
        if self._收起:
            self._标题.setStringValue_("工程面板 · 已收起（点展开或拖上沿）")
            self._筛选.setHidden_(True)
            self._清空.setHidden_(True)
            self._滚动.setHidden_(True)
            self._抓手.setFrame_(NSMakeRect(0, 高 - 7, 宽, 7))
            return
        self._标题.setStringValue_("工程面板 · 主日志镜像")
        self._筛选.setHidden_(False)
        self._清空.setHidden_(False)
        self._滚动.setHidden_(False)
        self._筛选.setFrame_(NSMakeRect(10, 高 - 53, 230, 22))
        self._清空.setFrame_(NSMakeRect(252, 高 - 53, 60, 22))
        底 = 高 - 70
        self._滚动.setFrame_(NSMakeRect(8, 6, 宽 - 16, max(30, 底 - 6)))
        self._文本.setFrameSize_(NSMakeSize(宽 - 16, max(30, 底 - 6)))
        self._抓手.setFrame_(NSMakeRect(0, 高 - 7, 宽, 7))

    def 设_收起(self, 收起: bool) -> None:
        if bool(收起) == self._收起:
            return
        self._收起 = bool(收起)
        self._折叠.setTitle_("展开" if self._收起 else "收起")
        if self.宿主 is not None:
            try:
                self.排_面板(self.frame().size.width, self.frame().size.height)
            except Exception:                                     # noqa: BLE001
                pass

    def 折叠_(self, _发送者):
        宿主 = self.宿主 or globals().get("_最后主人")
        if 宿主 is not None:
            宿主.切换_工程面板收起()
        else:
            self.设_收起(not self._收起)

    def 设_状态(self, 行: list, 总数: int, 摘要: str, 等级: str) -> None:
        """接收 Web 主日志的**完整筛选结果**；计数、筛选、清空都以它为准。"""
        try:
            self._行 = [dict(r) for r in 行][-800:]
            self._总 = max(0, int(总数))
            self._主筛选 = str(摘要 or "无筛选")
            self._状态同步 = True
            if 等级 == "全部":
                self._筛 = "全部"
                self._筛选.setSelectedSegment_(0)
            elif 等级 == "信息":
                self._筛 = "信息"
                self._筛选.setSelectedSegment_(1)
            elif 等级 == "注意":
                self._筛 = "注意"
                self._筛选.setSelectedSegment_(2)
            elif 等级 == "错误":
                self._筛 = "错误"
                self._筛选.setSelectedSegment_(3)
            self.重_画()
        except Exception:                                             # noqa: BLE001
            pass

    def 加_行(self, 行: dict) -> None:
        try:
            if self._状态同步:
                # 状态同步后，单行消息丢弃；否则会绕过主日志筛选，计数对不上。
                return
            self._行.append(dict(行))
            del self._行[:-800]
            self.重_画()
        except Exception:                                             # noqa: BLE001
            pass

    def 要_显示(self, 行: dict) -> bool:
        if self._筛 == "全部":
            return True
        return str(行.get("等级", "")) == self._筛

    def 重_画(self) -> None:
        try:
            self._文本.setString_("")
            显示 = self._行 if self._状态同步 else [r for r in self._行 if self.要_显示(r)]
            总数 = self._总 if self._状态同步 else len(self._行)
            self._计数.setStringValue_(f"{len(显示)} / {总数} 条")
            try:
                self._计数.setToolTip_(f"与左侧控制台同一份日志；{self._主筛选}")
            except Exception:                                     # noqa: BLE001
                pass
            for 行 in 显示[-500:]:
                try:
                    时 = ""
                    try:
                        import time as _t
                        时 = _t.strftime("%H:%M:%S", _t.localtime(float(行.get("墙钟", 0)) / 1000.0))
                    except Exception:                                 # noqa: BLE001
                        时 = str(行.get("时", ""))
                    等级 = str(行.get("等级", ""))
                    来源 = str(行.get("来源", ""))
                    插件 = str(行.get("插件", "") or "")
                    关节 = 行.get("关节")
                    头 = f"{时} {等级} {来源}"
                    if 插件:
                        头 += f" · {插件}"
                    if isinstance(关节, (int, float)) and int(关节) >= 0:
                        头 += f" · J{int(关节)}"
                    文本 = f"{头}\n  {行.get('文本', '')}"
                    细节 = str(行.get("细节", "") or "")
                    if 细节:
                        文本 += f"\n  {细节}"
                    色 = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.20, 0.26, 1.0)
                    if 等级 == "注意":
                        色 = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.63, 0.34, 0.02, 1.0)
                    elif 等级 == "错误":
                        色 = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.70, 0.10, 0.10, 1.0)
                    属性 = {
                        NSForegroundColorAttributeName: 色,
                        NSFontAttributeName: NSFont.monospacedSystemFontOfSize_weight_(11.0, 0.0),
                    }
                    串 = NSAttributedString.alloc().initWithString_attributes_(文本 + "\n", 属性)
                    self._文本.textStorage().appendAttributedString_(串)
                except Exception:                                     # noqa: BLE001
                    continue
            self._文本.scrollToEndOfDocument_(None)
        except Exception:                                             # noqa: BLE001
            pass

    def 筛选_(self, _发送者):
        try:
            选 = int(self._筛选.selectedSegment())
            self._筛 = ("全部", "信息", "注意", "错误")[max(0, min(3, 选))]
            # 先本地立刻反馈；Web 状态回来后以同一份筛选结果为准。
            self._状态同步 = False
            self.重_画()
            主人 = globals().get("_最后主人")
            if 主人 is not None:
                主人.发_日志操作("筛选", self._筛)
        except Exception:                                             # noqa: BLE001
            pass

    def 清空_(self, _发送者):
        self._行 = []
        self._总 = 0
        self._状态同步 = True
        self.重_画()
        try:
            主人 = globals().get("_最后主人")
            if 主人 is not None:
                主人.发_日志操作("清空", "")
        except Exception:                                             # noqa: BLE001
            pass


class LogBridge(NSObject):
    """WKWebView → 原生工程面板的单向日志桥。只接受对象，失败静默。"""

    def initWithPanel_(self, 面板):
        self = objc.super(LogBridge, self).init()
        if self is None:
            return None
        self.面板 = 面板
        return self

    def userContentController_didReceiveScriptMessage_(self, _控制器, 消息):
        try:
            体 = dict(消息.body())
            if self.面板 is None:
                return
            if 体.get("类型") == "日志状态":
                self.面板.设_状态(
                    体.get("行", []) or [],
                    int(体.get("总数", 0) or 0),
                    str(体.get("筛选", "") or ""),
                    str(体.get("等级", "全部") or "全部"),
                )
            else:
                self.面板.加_行(体)
        except Exception:                                             # noqa: BLE001
            pass


class HostApp(NSObject):
    """窗口 + 每帧驱动。所有 AppKit 回调都在主线程。"""

    def init(self):
        self = objc.super(HostApp, self).init()
        if self is None:
            return None
        self.参数 = None
        self.窗口 = None
        self.网页 = None
        self.视口 = None
        self.命令队列 = None
        self.主线程帧 = 0
        self.上次状态 = None
        self.视口工具条 = None
        self.视口提示 = None
        self.视口帧率标签 = None
        self.视口图例 = None
        self.网格按钮 = None
        self.分栏 = None
        self.网页宽当前 = None
        self.网页宽请求 = None
        self.分栏拖动中 = False
        self.分栏交互时刻 = 0.0
        self._分栏相机 = None
        self.当前模型路径 = os.environ.get("驭臂_当前模型", "")
        self.待换模型路径 = None
        self.待换模型时刻 = 0.0
        self.切换标签 = None
        self.工程面板 = None
        self.日志桥 = None
        self.面板高 = 0.0
        self._面板开上次 = False
        self._面板高覆盖 = None
        self._面板收起 = False
        self._面板拖动中 = False
        try:
            偏好 = NSUserDefaults.standardUserDefaults()
            存高 = 偏好.objectForKey_("驭臂.工程面板高")
            if 存高 is not None:
                self._面板高覆盖 = float(存高)
            self._面板收起 = bool(偏好.boolForKey_("驭臂.工程面板收起"))
        except Exception:                                             # noqa: BLE001
            pass
        return self

    def applicationDidFinishLaunching_(self, _通知):
        try:
            self._建窗口()
        except Exception as 异常:                                     # noqa: BLE001
            # 教训 ⑦：delegate 里抛异常 = 静默失效，宁可打出来
            import traceback
            记诊断(f"✗ 建窗口失败：{type(异常).__name__}: {异常}")
            print(f"  ✗ 建窗口失败：{type(异常).__name__}: {异常}", flush=True)
            traceback.print_exc()
            return
        记诊断("delegate：建窗口完成")

        import 定时器
        # ★ 用 `定时器`（CFRunLoopTimer），**不要用 PyObjC 的 NSTimer**（教训 ⑥）
        self._每帧定时 = 定时器.起(1.0 / 60.0, self._主线程每帧)
        self._诊断定时 = 定时器.一次性(2.0, self._自诊断)
        记诊断("delegate：定时器已起，delegate 结束")

    # ---- 3D 视图工具条（原生浮层，不经过 Web / 不破坏"界面只走仓库"的约定）----
    def 建_视口工具条(self, 内容, 网页宽: float, 视口宽: float, 高: float) -> None:
        if self.视口 is None:
            return
        工具条 = NSView.alloc().initWithFrame_(NSMakeRect(网页宽 + 12, 高 - 44, 560, 32))
        try:
            工具条.setWantsLayer_(True)
            工具条.layer().setBackgroundColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.055, 0.62).CGColor())
            工具条.layer().setCornerRadius_(7.0)
        except Exception as 异常:                                         # noqa: BLE001
            记诊断(f"工具条背景失败（不影响按钮）：{type(异常).__name__}: {异常}")

        标题 = NSTextField.alloc().initWithFrame_(NSMakeRect(9, 8, 54, 16))
        标题.setStringValue_("3D")
        标题.setFont_(NSFont.systemFontOfSize_(10.0))
        标题.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.95, 0.9))
        标题.setDrawsBackground_(False)
        标题.setBordered_(False)
        标题.setEditable_(False)
        标题.setSelectable_(False)
        工具条.addSubview_(标题)
        self.视口帧率标签 = 标题

        def 加按钮(文字: str, x: float, 宽: float,
                   动作: str, 切换: bool = False) -> Any:
            按钮 = NSButton.alloc().initWithFrame_(NSMakeRect(x, 4, 宽, 24))
            按钮.setTitle_(文字)
            按钮.setBezelStyle_(NSBezelStyleRounded)
            按钮.setFont_(NSFont.systemFontOfSize_(11.0))
            按钮.setTarget_(self)
            按钮.setAction_(动作)
            if 切换:
                按钮.setButtonType_(NSButtonTypeToggle)
            else:
                # 普通按钮也允许按一次后自动弹回
                按钮.setButtonType_(0)
            工具条.addSubview_(按钮)
            return 按钮

        加按钮("适配", 64, 58, "fitView:")
        加按钮("复位", 126, 58, "resetView:")
        self.网格按钮 = 加按钮("网格开", 188, 58, "toggleGrid:", 切换=True)
        self.网格按钮.setState_(1 if self.视口.网格开 else 0)

        提示 = NSTextField.alloc().initWithFrame_(NSMakeRect(260, 8, 292, 16))
        提示.setStringValue_("拖拽旋转 · Shift+拖拽平移 · 滚轮缩放 · R 复位 · F 适配")
        提示.setFont_(NSFont.systemFontOfSize_(10.0))
        提示.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.88, 0.82))
        提示.setDrawsBackground_(False)
        提示.setBordered_(False)
        提示.setEditable_(False)
        提示.setSelectable_(False)
        工具条.addSubview_(提示)

        图例 = NSTextField.alloc().initWithFrame_(NSMakeRect(网页宽 + 14, 12, 340, 16))
        图例.setStringValue_("X 红 · Y 绿 · Z 蓝 · 网格 0.1m（粗线 0.5m）")
        图例.setFont_(NSFont.systemFontOfSize_(10.0))
        图例.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.88, 0.82))
        图例.setDrawsBackground_(True)
        图例.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.02, 0.55))
        图例.setBordered_(False)
        图例.setEditable_(False)
        图例.setSelectable_(False)

        切换 = NSTextField.alloc().initWithFrame_(NSMakeRect(网页宽 + 12, 高 - 78, 280, 22))
        切换.setStringValue_("正在切换模型…")
        切换.setFont_(NSFont.systemFontOfSize_(12.0))
        切换.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.96, 0.95))
        切换.setDrawsBackground_(True)
        切换.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.02, 0.72))
        切换.setBordered_(False)
        切换.setEditable_(False)
        切换.setSelectable_(False)
        切换.setHidden_(True)

        self.视口工具条, self.视口提示, self.视口图例 = 工具条, 提示, 图例
        self.切换标签 = 切换
        内容.addSubview_(工具条)
        内容.addSubview_(图例)
        内容.addSubview_(切换)
        self.排_视口工具条(网页宽, 视口宽, 高)

    def 排_视口工具条(self, 网页宽: float, 视口宽: float, 高: float, 底: float = 0.0) -> None:
        if self.视口工具条 is None:
            return
        宽 = max(300.0, min(560.0, float(视口宽) - 24.0))
        self.视口工具条.setFrame_(NSMakeRect(网页宽 + 12, 高 - 44, 宽, 32))
        if self.视口提示 is not None:
            self.视口提示.setFrame_(NSMakeRect(260, 8, max(60.0, 宽 - 268.0), 16))
            self.视口提示.setHidden_(宽 < 430)
        if self.视口图例 is not None:
            图宽 = max(120.0, min(360.0, float(视口宽) - 28.0))
            self.视口图例.setFrame_(NSMakeRect(网页宽 + 14, float(底) + 12, 图宽, 16))
            self.视口图例.setHidden_(图宽 < 160)
        if self.切换标签 is not None:
            标宽 = max(120.0, min(300.0, float(视口宽) - 28.0))
            self.切换标签.setFrame_(NSMakeRect(网页宽 + 12, 高 - 78, 标宽, 22))
            self.切换标签.setHidden_(True)

    def 开始_工程面板拖动(self) -> None:
        self._面板拖动中 = True

    def 结束_工程面板拖动(self) -> None:
        self._面板拖动中 = False
        if self.视口 is not None:
            try:
                self.视口.按视口重算画布()
                self.视口.openGLContext().update()
                self.视口.setNeedsDisplay_(True)
                self.视口.displayIfNeeded()
            except Exception:                                         # noqa: BLE001
                pass

    def 设_面板高(self, 高: float) -> None:
        self._面板收起 = False
        self._面板高覆盖 = max(190.0, min(float(self.窗口.contentView().bounds().size.height) * 0.70,
                                       float(高)))
        try:
            偏好 = NSUserDefaults.standardUserDefaults()
            偏好.setDouble_forKey_(self._面板高覆盖, "驭臂.工程面板高")
            偏好.setBool_forKey_(False, "驭臂.工程面板收起")
        except Exception:                                             # noqa: BLE001
            pass
        if self.窗口 is not None:
            内容 = self.窗口.contentView()
            self.排_布局(float(内容.bounds().size.width), float(内容.bounds().size.height))

    def 切换_工程面板收起(self) -> None:
        self._面板收起 = not self._面板收起
        try:
            NSUserDefaults.standardUserDefaults().setBool_forKey_(self._面板收起, "驭臂.工程面板收起")
        except Exception:                                             # noqa: BLE001
            pass
        if self.窗口 is not None:
            内容 = self.窗口.contentView()
            self.排_布局(float(内容.bounds().size.width), float(内容.bounds().size.height))

    def 重置_工程面板高(self) -> None:
        self._面板高覆盖 = None
        self._面板收起 = False
        self._面板拖动中 = False
        try:
            偏好 = NSUserDefaults.standardUserDefaults()
            存高 = 偏好.objectForKey_("驭臂.工程面板高")
            if 存高 is not None:
                self._面板高覆盖 = float(存高)
            self._面板收起 = bool(偏好.boolForKey_("驭臂.工程面板收起"))
        except Exception:                                             # noqa: BLE001
            pass
        if self.窗口 is not None:
            内容 = self.窗口.contentView()
            self.排_布局(float(内容.bounds().size.width), float(内容.bounds().size.height))

    def 发_日志操作(self, 类型: str, 值: str) -> None:
        """原生工程面板 → Web 主日志：筛选/清空回到同一份日志状态。"""
        if self.网页 is None:
            return
        try:
            类型s = str(类型).replace("'", "")
            值s = str(值).replace("'", "")
            self.网页.evaluateJavaScript_completionHandler_(
                "window.dispatchEvent(new CustomEvent('驭臂.日志操作',"
                "{detail:{类型:'" + 类型s + "',值:'" + 值s + "'}}));",
                None)
        except Exception:                                             # noqa: BLE001
            pass

    def _同步面板事件(self) -> None:
        """3D 变窄/变宽时，通知 Web 收起/恢复它自己的控制台（避免两份重复）。"""
        开 = self.面板高 > 0.5
        if 开 == self._面板开上次:
            return
        self._面板开上次 = 开
        if self.网页 is None:
            return
        try:
            值 = "true" if 开 else "false"
            标 = "1" if 开 else "0"
            # ★ WKWebView 的 API 是 evaluateJavaScript:completionHandler:，
            #   没有单参数版本；写 `evaluateJavaScript_` 会被静默拒掉。
            self.网页.evaluateJavaScript_completionHandler_(
                "document.documentElement.setAttribute('data-工程面板','" + 标 + "');"
                "window.dispatchEvent(new CustomEvent('驭臂.工程面板',"
                "{detail:{开:" + 值 + "}}));",
                None)
            记诊断(f"工程面板事件 -> {开}")
        except Exception as 异常:                                     # noqa: BLE001
            记诊断(f"工程面板事件失败：{type(异常).__name__}: {异常}")

    def 开始_分栏拖动(self) -> None:
        self.分栏拖动中 = True
        self.分栏交互时刻 = time.monotonic()
        记诊断(f"分栏开始：当前网页宽={self.取_网页宽():.0f}")
        v = self.视口
        if v is None:
            return
        v.交互锁定 = True
        # 只快照已经完成首帧取景的相机；否则会把"首帧适配"也一起回滚。
        if v.相机 is not None and getattr(v, "_首帧已取景", False):
            try:
                self._分栏相机 = (
                    v.相机.lookat.copy(),
                    float(v.相机.distance),
                    float(v.相机.azimuth),
                    float(v.相机.elevation),
                )
            except Exception:                                         # noqa: BLE001
                self._分栏相机 = None
        else:
            self._分栏相机 = None

    def 结束_分栏拖动(self) -> None:
        self.分栏拖动中 = False
        self.分栏交互时刻 = time.monotonic()
        v = self.视口
        if v is None:
            return
        v.交互锁定 = False
        if self._分栏相机 is not None and v.相机 is not None:
            try:
                中心, 距离, 方位, 仰角 = self._分栏相机
                v.相机.lookat[:] = 中心
                v.相机.distance = max(1.50, float(距离))
                v.相机.azimuth = 方位
                v.相机.elevation = 仰角
                v.请求渲染()
            except Exception:                                     # noqa: BLE001
                pass
        if v.相机 is not None:
            try:
                if float(v.相机.distance) < 1.50:
                    记诊断(f"相机兜底：{float(v.相机.distance):.2f} -> 1.50")
                    v.相机.distance = 1.50
                    v.请求渲染()
            except Exception:                                     # noqa: BLE001
                pass
        self._分栏相机 = None
        记诊断(f"分栏结束：网页宽={self.取_网页宽():.0f} 画布目标={v._画布目标}")
        # 拖动期间故意不重建渲染器；松手后再按最终尺寸重建一次。
        try:
            v.openGLContext().update()
        except Exception:                                         # noqa: BLE001
            pass
        v.按视口重算画布()
        v.setNeedsDisplay_(True)
        v.displayIfNeeded()

    def 重置_分栏(self) -> None:
        """双击分隔条：回到默认 40/60，并让 C 面板按新比例重新判定。"""
        self.网页宽请求 = None
        if self.窗口 is None:
            return
        内容 = self.窗口.contentView()
        self.排_布局(float(内容.bounds().size.width), float(内容.bounds().size.height))

    def 取_网页宽(self) -> float:
        if self.网页宽当前 is not None:
            return float(self.网页宽当前)
        if self.窗口 is None:
            return float(网页最小宽)
        宽 = float(self.窗口.contentView().bounds().size.width)
        return float(_切分宽度(宽)[0])

    def 设_网页宽(self, 宽: float) -> None:
        if self.窗口 is None or self.视口 is None:
            return
        内容 = self.窗口.contentView()
        总宽 = float(内容.bounds().size.width)
        高 = float(内容.bounds().size.height)
        self.网页宽请求 = max(float(网页最小宽),
                              min(float(宽), 总宽 - float(视口最小宽)))
        self.排_布局(总宽, 高)

    def 排_布局(self, 宽: float, 高: float) -> None:
        """按当前窗口尺寸排 Web / 3D / 分隔条 / 工具条。"""
        if self.网页 is None:
            return
        if self.视口 is None:
            self.网页宽当前 = round(宽)
            self.网页.setFrame_(NSMakeRect(0, 0, round(宽), round(高)))
            return
        if self.网页宽请求 is not None:
            网页宽 = max(float(网页最小宽),
                        min(float(self.网页宽请求), float(宽) - float(视口最小宽)))
        else:
            网页宽 = _切分宽度(宽)[0]
        网页宽 = round(网页宽)
        视口宽 = round(宽) - 网页宽
        self.网页宽当前 = 网页宽
        自动高 = round(_工程面板高度(视口宽, 高))
        if 自动高 <= 0:
            面板高 = 0
        elif self._面板收起:
            面板高 = 34
        elif self._面板高覆盖 is not None:
            面板高 = int(max(190.0, min(float(高) * 0.70, float(self._面板高覆盖))))
        else:
            面板高 = 自动高
        self.面板高 = float(面板高)
        顶高 = round(高) - 面板高
        # 3D 贴窗口上边；面板只在右列（3D 下方），**不碰左下角 Web 状态栏**。
        # Web 保持整窗高：蓝色状态栏仍在最左下；右列被分成 3D（上）+ 工程面板（下）。
        self.视口.setFrame_(NSMakeRect(网页宽, 面板高, 视口宽, 顶高))
        self.网页.setFrame_(NSMakeRect(0, 0, 网页宽, round(高)))
        if self.分栏 is not None:
            self.分栏.setFrame_(NSMakeRect(网页宽 - 3, 0, 7, round(高)))
        if self.工程面板 is not None:
            self.工程面板.setHidden_(面板高 <= 0)
            if 面板高 > 0:
                self.工程面板.设_收起(self._面板收起)
            self.工程面板.setFrame_(NSMakeRect(网页宽, 0, 视口宽, 面板高))
            if 面板高 > 0:
                self.工程面板.排_面板(视口宽, 面板高)
        self._同步面板事件()
        # 拖动分隔条时先不重建 MuJoCo 渲染器：老画面按新比例等比铺开即可，
        # 松手后由 结束_分栏拖动() 统一重建。这样既不会每拖一像素重建一次，
        # 也避开"渲染器重建/旧纹理同帧"导致的画面异常。
        if not self.分栏拖动中 and not self._面板拖动中:
            self.视口.按视口重算画布()
        # ★ NSOpenGLView 的 drawable 不会自动跟着 setFrame_ 立刻换尺寸。
        #   不 update 就直接 glViewport 到新尺寸，会把旧 drawable 的一部分放大/裁切
        #   （用户拖动分隔条时看到的"机械臂突然顶到脸上"就是这个）。
        try:
            self.视口.openGLContext().update()
        except Exception:                                             # noqa: BLE001
            pass
        self.视口.setNeedsDisplay_(True)
        self.视口.displayIfNeeded()
        self.排_视口工具条(网页宽, 视口宽, 高, 面板高)

    def fitView_(self, _发送者):
        if self.视口 is not None:
            self.视口.适配_视图()

    def resetView_(self, _发送者):
        if self.视口 is not None:
            self.视口.视角_复位()

    def toggleGrid_(self, 发送者):
        if self.视口 is not None:
            self.视口.切换_网格()
            try:
                发送者.setState_(1 if self.视口.网格开 else 0)
                发送者.setTitle_("网格开" if self.视口.网格开 else "网格关")
            except Exception:                                             # noqa: BLE001
                pass

    def _建窗口(self) -> None:
        参数 = self.参数
        宽, 高 = 参数.宽, 参数.高

        窗口 = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(120, 120, 宽, 高),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered, False)
        窗口.setTitle_(参数.标题)
        窗口.setBackgroundColor_(NSColor.blackColor())
        # ★ 不设窗口 delegate（教训 ⑤），用通知收 resize
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            # ⚠️ 这里传的是**选择器字符串**，不是 Python 方法名：
            #    选择器里用**冒号**表示参数，所以是 `"窗口改尺寸:"` 而不是 `"窗口改尺寸_:"`。
            #    写成尾下划线会被原样当选择器名，运行期报
            #    `unrecognized selector sent to instance`（而且只在有 resize 时才炸）。
            self, "窗口改尺寸:", NSWindowDidResizeNotification, 窗口)
        self.窗口 = 窗口

        内容 = 窗口.contentView()
        # ★ 整数像素：小数会让两个视图在边界重叠 ~1px（状态栏被盖掉半行就是这么来的）
        网页宽, 视口宽 = _切分宽度(宽)

        # ⓪ 全宽工程面板（C）：先建好、默认隐藏；日志由 Web 经 WKScriptMessageHandler 镜像进来。
        self.工程面板 = ConsolePanel.alloc().initWithFrame_(NSMakeRect(0, 0, round(宽), 0))
        self.工程面板.宿主 = self
        self.工程面板.setHidden_(True)
        内容.addSubview_(self.工程面板)
        self.日志桥 = LogBridge.alloc().initWithPanel_(self.工程面板)

        # ① 3D 视口（**右侧主区域**）
        if 参数.无3D:
            self.视口 = None
        else:
            self.视口 = Viewport.alloc().initWithFrame_(
                NSMakeRect(网页宽, 0, 视口宽, round(高)))
            # ★ 建窗口时就要算一次画布比例：`窗口改尺寸_` 只在**真的改尺寸**时触发，
            #   启动时不会触发 —— 我第一版只在 resize 里算，于是启动永远用默认 760×420，
            #   画面上就一直是"两边留黑边"的样子（还以为是渲染器的事）。
            self.视口.按视口重算画布()
            内容.addSubview_(self.视口)
            视口槽["视口"] = self.视口
            模型路径 = os.environ.get("驭臂_当前模型", "")
            self.当前模型路径 = 模型路径
            if 模型路径 and os.path.exists(模型路径):
                self.视口.准_备(模型路径)
            else:
                提示 = f"没有可加载的模型（驭臂_当前模型={模型路径!r}）"
                self.视口.错误 = 提示
                print(f"  ⚠ 3D 视口：{提示}", flush=True)

        # ② Web 界面（上方）：加载**本机服务**的地址（同一个 React 产物）
        配置 = WKWebViewConfiguration.alloc().init()
        try:
            配置.userContentController().addScriptMessageHandler_name_(self.日志桥, "驭臂日志")
        except Exception as 异常:                                     # noqa: BLE001
            print(f"  ⚠ 日志镜像桥不可用：{type(异常).__name__}: {异常}", flush=True)
        try:
            # 在文档开始就监听：宿主打开/关闭全宽工程面板时，用它把 Web 自己的控制台藏起来。
            # CSS 负责立刻隐藏（即使 React 还没处理完事件），避免出现"上下两份日志"。
            脚本 = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
                "window.addEventListener('驭臂.工程面板', function(e){"
                "document.documentElement.setAttribute('data-工程面板',"
                "(e && e.detail && e.detail.开) ? '1' : '0');});",
                WKUserScriptInjectionTimeAtDocumentStart, True)
            配置.userContentController().addUserScript_(脚本)
        except Exception as 异常:                                     # noqa: BLE001
            print(f"  ⚠ 工程面板脚本注入失败：{type(异常).__name__}: {异常}", flush=True)
        self.网页 = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, 网页宽 if self.视口 else 宽, round(高)),
            配置)
        内容.addSubview_(self.网页)
        # ★ 加版本查询串，强制 WKWebView 重新取 index.html：
        #   Web 产物每次构建都会换 assets 哈希，但 WKWebView 会缓存 index.html，
        #   结果就是"明明重新 build 了，界面还是旧的控制台"（本轮真实踩到）。
        #   查询串不影响 Vite/React 路由；只让入口 HTML 不进缓存。
        加载地址 = 参数.地址
        加载地址 += ("&" if "?" in 加载地址 else "?") + f"v={time.time_ns()}"
        self.网页.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(加载地址)))

        # ③ Web / 3D 分隔条（原生 NSView，可左右拖）
        if self.视口 is not None:
            self.分栏 = Splitter.alloc().initWithHost_(self)
            self.分栏.setFrame_(NSMakeRect(网页宽 - 3, 0, 7, round(高)))
            try:
                self.分栏.setToolTip_("拖动调整 Web / 3D 宽度；双击恢复默认 40/60")
            except Exception:                                         # noqa: BLE001
                pass
            内容.addSubview_(self.分栏)
            self.网页宽当前 = round(网页宽)

        # ④ 3D 视图工具条（原生 NSView，浮在 3D 顶部；Web 界面完全不知道它）
        if self.视口 is not None:
            self.建_视口工具条(内容, 网页宽, 视口宽, 高)

        窗口.makeKeyAndOrderFront_(None)

        print("=" * 80, flush=True)
        print(f"  {参数.标题}", flush=True)
        print("=" * 80, flush=True)
        if self.视口:
            print(f"  窗口   : {宽:.0f}×{高:.0f}"
                  f"（左 Web {网页宽:.0f}px ／ 右 3D 视口 {视口宽:.0f}px）", flush=True)
        else:
            print(f"  窗口   : {宽:.0f}×{高:.0f}（--无3D：Web 界面铺满）", flush=True)
        print(f"  界面   : {参数.地址}（我们窗口里的 WKWebView，不是外部浏览器）", flush=True)
        if self.视口:
            print("  操作   : 拖拽=转视角 ／ 滚轮=缩放 ／ Shift+拖拽=平移 ／ "
                  "R=复位 ／ F=适配 ／ G=网格 ／ 双击=适配", flush=True)
        print("=" * 80, flush=True)

    # ---- resize：按比例重排（通知触发，不是 delegate）----
    def 窗口改尺寸_(self, _通知):
        if self.窗口 is None:
            return
        内容 = self.窗口.contentView()
        宽 = 内容.bounds().size.width
        高 = 内容.bounds().size.height
        # ★ 整数像素：小数会让两个视图在边界重叠 ~1px
        #   （表现就是"状态栏被盖掉半行"）。
        if self.视口 is None:
            self.网页.setFrame_(NSMakeRect(0, 0, round(宽), round(高)))
            return
        self.排_布局(宽, 高)

    # ---- 主线程每帧：只做"拉状态 + 要求重绘" ----
    def _主线程每帧(self) -> None:
        try:
            self.主线程帧 += 1
            if self.视口 is not None:
                # 换模型：仿真线程的模型观察者只把路径放进槽里，这里在主线程重装。
                # 不能在仿真线程碰 AppKit/GL；重装本身会停旧渲染线程、清状态、
                # 重新按新模型取景，再启动新的渲染线程。
                待换 = 视口槽.get("待换模型")
                if 待换:
                    视口槽["待换模型"] = None
                    self.待换模型路径 = str(待换)
                    self.待换模型时刻 = time.monotonic()
                # 连续点模型时合并：最后一次点击后安静 0.15s 再重装，
                # 避免每个中间模型都停一次渲染线程、黑一下。
                if (self.待换模型路径
                        and time.monotonic() - self.待换模型时刻 >= 0.15):
                    目标 = self.待换模型路径
                    self.待换模型路径 = None
                    try:
                        同路径 = os.path.normpath(str(目标)) == os.path.normpath(str(self.当前模型路径))
                    except Exception:                                     # noqa: BLE001
                        同路径 = str(目标) == str(self.当前模型路径)
                    if not 同路径:
                        if self.视口.换_模型(str(目标)) and self.切换标签 is not None:
                            self.切换标签.setStringValue_(
                                f"正在切换模型：{os.path.basename(str(目标))}")
                if self.切换标签 is not None:
                    self.切换标签.setHidden_(not bool(getattr(self.视口, "切换中", False)))
                # 只有真正装载完成才更新“当前路径”；加载失败时保持旧路径，
                # 这样下一次点同一路径会重试，而不是被误判成“已经是它了”。
                if self.视口.就绪 and getattr(self.视口, "_模型路径", ""):
                    self.当前模型路径 = str(self.视口._模型路径)
            if self.视口 is not None and self.视口.就绪:
                状态 = self.视口.最新状态
                # 只在收到**新**快照时同步 + 请求渲染（静止时不白烧 CPU）
                if 状态 is not None and 状态 is not self.上次状态:
                    self.上次状态 = 状态
                    self.视口.同步_状态(状态)
                    self.视口.请求渲染()
                self.视口.setNeedsDisplay_(True)
                # 防御相机被旧版本/漏出的滚轮推进到机械臂内部；正常缩放最低 0.8。
                if self.视口.相机 is not None and float(self.视口.相机.distance) < 1.50:
                    记诊断(f"相机每帧兜底：{float(self.视口.相机.distance):.2f} -> 1.50")
                    self.视口.相机.distance = 1.50
                    self.视口.请求渲染()
                # 关节高亮：进程内共享状态，10 Hz 轮询足够；过期自动消失。
                if _高亮桥 is not None and self.主线程帧 % 6 == 0:
                    try:
                        关节 = _高亮桥.取高亮()
                        if 关节 != self.视口.高亮关节:
                            self.视口.高亮关节 = 关节
                            记诊断(f"高亮关节 -> {关节}")
                            self.视口.请求渲染()
                            self.视口.setNeedsDisplay_(True)
                    except Exception:                                 # noqa: BLE001
                        pass
                if self.主线程帧 % 30 == 0:
                    try:
                        fps = float(self.视口.统计.get("fps", 0.0))
                        if self.视口帧率标签 is not None:
                            self.视口帧率标签.setStringValue_(f"3D {fps:.0f}fps")
                        if self.视口图例 is not None:
                            步长 = float(self.视口._网格[0])
                            高亮 = self.视口.高亮关节
                            后缀 = f" · 高亮 J{int(高亮)}" if 高亮 is not None else ""
                            self.视口图例.setStringValue_(
                                f"X 红 · Y 绿 · Z 蓝 · 网格 {步长:g}m（粗线 {步长 * 5:g}m）{后缀}")
                    except Exception:                                     # noqa: BLE001
                        pass
        except Exception as 异常:                                         # noqa: BLE001
            if self.主线程帧 < 3:
                记诊断(f"✗ 每帧回调异常：{type(异常).__name__}: {异常}")

    def _自诊断(self) -> None:
        v = self.视口
        if v is None:
            记诊断(f"★ 自诊断：主线程帧={self.主线程帧}（--无3D）")
            print(f"  [自诊断] 主线程帧={self.主线程帧}（--无3D，没有 3D 视口）", flush=True)
            return
        记诊断(f"★ 自诊断：主线程帧={self.主线程帧} 就绪={v.就绪} "
              f"渲染帧={v.统计['渲染帧']} 显示帧={v.统计['显示帧']} "
              f"fps={v.统计['fps']:.1f} 同步={v.统计['同步']} 错误={v.错误!r}")
        if v.就绪:
                print(f"  [自诊断] 3D：渲染 {v.统计['渲染帧']} 帧 / 显示 {v.统计['显示帧']} 帧"
                  f" ／ {v.统计['fps']:.1f} fps ／ 状态同步 {v.统计['同步']} 次"
                  f" ／ 主线程帧 {self.主线程帧}", flush=True)
        else:
            print(f"  [自诊断] 3D 不可用：{v.错误}", flush=True)

    def keyDown_(self, 事件):
        # 窗口层的兜底：视口没拿到焦点时（极少见）也能用同样的键
        字 = (事件.charactersIgnoringModifiers() or "").lower()
        if self.视口 is None or not 字:
            return
        if 字 == "r":
            self.视口.视角_复位()
        elif 字 == "f":
            self.视口.适配_视图()
        elif 字 == "g":
            self.视口.切换_网格()
        elif 字 == "e":
            self.视口.切换_末端坐标()


_参数 = None


def 跑(地址: str, 标题: str = "小软件 · 机器人仿真工作台",
       宽: float = 默认窗口[0], 高: float = 默认窗口[1],
       命令队列: list | None = None, 无3D: bool = False) -> int:
    """起窗口并进入 AppKit 主循环。返回进程退出码。

    ★ 调用前必须：① Web 服务已起 ② 仿真正在**后台线程**跑 ③ `驭臂_当前模型` 已设。
    """
    import argparse

    参数 = argparse.Namespace(地址=地址, 标题=标题, 宽=float(宽), 高=float(高), 无3D=无3D)
    应用 = NSApplication.sharedApplication()
    应用.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    主人 = HostApp.alloc().init()
    主人.参数 = 参数
    主人.命令队列 = 命令队列
    应用.setDelegate_(主人)
    global _最后主人
    _最后主人 = 主人
    应用.activateIgnoringOtherApps_(True)
    记诊断("跑()：即将进入 app.run()")
    应用.run()
    记诊断("跑()：app.run() 已返回")
    return 0
