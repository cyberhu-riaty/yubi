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
   ⚠️ 前缀式 `_准备` **不管用**（下划线在第 1 个字符，`"_" in name[1:]` 为假）；
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

import os
import threading
import time
from typing import Any

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
                    NSColor, NSMakeRect, NSOpenGLPFAAccelerated, NSOpenGLPFAColorSize,
                    NSOpenGLPFADepthSize, NSOpenGLPFADoubleBuffer, NSOpenGLPFAOpenGLProfile,
                    NSOpenGLPixelFormat, NSOpenGLProfileVersionLegacy, NSOpenGLView, NSWindow,
                    NSWindowDidResizeNotification, NSWindowStyleMaskClosable,
                    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
                    NSWindowStyleMaskTitled)
from Foundation import NSNotificationCenter, NSObject, NSURL, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration

# 布局：下方 3D 视口，上方 Web 界面（与 P2 spike 的验收布局一致）
# 布局：**左 Web 界面 / 右 3D 视口**（横向切分）
#
# ★ 为什么从"上下切"改成"左右切"（这是用户明确要求的根本性修改）：
#   上下切的时候，3D 永远是窗口**底下的一条**，看起来像"界面下面挖了个黑窟窿"，
#   而不是"主画面"。实测反馈也确实是这么说的。
#   左右切之后 3D 是右侧**主区域**（占 60%+ 宽、整窗高），和参考项目一致：
#   左边是面板（资产/参数/日志），右边是场景。
默认网页宽比 = 0.40      # 左侧 Web 面板占窗口宽度的比例
网页最小宽 = 520.0       # 再窄就放不下活动栏 + 侧栏
视口最小宽 = 420.0       # 3D 再窄就没法看了
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
        # 最新状态快照：**仿真线程写、主线程读**。
        # 只做"整体替换一个引用"，所以不需要锁（CPython 的属性赋值是原子的）。
        self.最新状态 = None
        return self

    # ------------------------------------------------------------------
    # 装载：模型 + 渲染器（在独立线程里做，见教训 ③）
    # ------------------------------------------------------------------
    def 准_备(self, 模型路径: str, 画布: tuple[int, int] | None = None) -> None:
        """装载模型并起渲染线程。**渲染器在渲染线程里建**（见 `_渲染循环`）。"""
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
                相机.azimuth, 相机.elevation = 135.0, -16.0
                try:
                    import numpy as _np
                    # ★ 用 MuJoCo 自己算好的 `stat.center` / `stat.extent`。
                    #   我第一版用 `geom_pos` + `geom_rbound` 自己算包围球，结果是
                    #   半径 0.359 / 中心 z≈0.01 —— 因为 `geom_pos` 是**相对 body 的局部坐标**，
                    #   直接取平均会把"一堆挤在底座上的小几何"当成整台机器人，
                    #   于是相机被拉到 1.17 m，机械臂直接顶出画面。
                    #   `stat` 是 MuJoCo 在编译模型时按真实几何（含 mesh）算的，直接可用。
                    # ★ 用**世界坐标**下的几何包围球：`data.geom_xpos` + `geom_rbound`。
                    #   试过三个来源，只有这个对：
                    #     · `model.geom_pos` —— 局部坐标，平均后落在底座（半径 0.36，相机贴脸）
                    #     · `model.stat.extent` —— 1.325，对这条 1.1 m 的臂偏大（画面偏小）
                    #     · `data.geom_xpos`（本行）—— 世界坐标，实测半径 0.62，画面刚好
                    位置 = _np.asarray(数据.geom_xpos, dtype=float).reshape(-1, 3)
                    球径 = _np.asarray(模型.geom_rbound, dtype=float).ravel()
                    有效 = _np.isfinite(位置).all(axis=1) & _np.isfinite(球径)
                    if not bool(有效.any()):
                        raise ValueError("没有可用几何")
                    位置, 球径 = 位置[有效], 球径[有效]
                    # 只取"真几何"：半径过大的（贴地平面等）会把包围球撑爆
                    正常 = 球径 < 0.5
                    if bool(正常.any()):
                        位置, 球径 = 位置[正常], 球径[正常]
                    中心 = 位置.mean(axis=0)
                    半径 = float(_np.max(_np.linalg.norm(位置 - 中心, axis=1) + 球径))
                    if not _np.isfinite(中心).all() or 半径 <= 0:
                        raise ValueError("包围球计算失败")
                    # 竖直方向要留更多余量：机械臂是"高瘦"的，水平方向几乎不占地方，
                    # 只按包围球算会让它在竖直方向贴边。
                    # 取景系数：离屏实测"半径 0.851 + 系数 1.15"只占 54% 画高，偏小；
                    # 0.92 大约占 65~70%，是"整台机器人都看得清、又不空旷"的比例。
                    # 取景余量：0.92 时起始姿态占 67% 画高，但机器人**动起来之后**
                    # 会比起始姿态高（抬臂/正弦摆动的峰值都超出 home 姿态），
                    # 于是顶端被切掉。1.15 → 距离 2.36，给运动留出头部空间。
                    竖直余量 = 1.15
                    fovy = float(getattr(模型.vis.global_, "fovy", 45.0) or 45.0)
                    相机.lookat[:] = (float(中心[0]), float(中心[1]), float(中心[2]))
                    相机.distance = float(半径 * 竖直余量 / _np.tan(_np.radians(fovy) / 2.0))
                    记诊断(f"自动取景：中心={_np.round(中心, 3).tolist()} 半径={半径:.3f} "
                           f"fovy={fovy:.0f} 距离={相机.distance:.2f}")
                except Exception as _取景异常:                            # noqa: BLE001
                    相机.distance, 相机.elevation = 3.2, -16.0
                    相机.lookat[:] = (0.0, 0.0, 0.45)
                    记诊断(f"自动取景失败，退回默认视角：{_取景异常}")
                选项 = mujoco.MjvOption()
                mujoco.mjv_defaultOption(选项)
                # ★ **渲染器不在这里建**：`mujoco.Renderer` 会自建一套 GL 上下文，
                #   而"在哪建"和"在哪用"必须同一个线程 —— 在装载线程建、却在渲染线程用，
                #   实测会**卡死在第一次 render() 里**（不报错、不返回）。
                #   所以渲染器放到 `_渲染循环` 开头建。
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
                self.就绪 = True
                threading.Thread(target=self._渲染循环, daemon=True,
                                 name="3D渲染线程").start()
                self.请求渲染()
                记诊断(f"视口装载完成：{os.path.basename(模型路径)} "
                      f"nq={模型.nq} nu={模型.nu} 画布={self.画布尺寸}")
                print(f"  ✓ 3D 视口：已装载 {os.path.basename(模型路径)}"
                      f"（nq={模型.nq} nu={模型.nu}）", flush=True)
            except Exception as 异常:                                 # noqa: BLE001
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
                # 自上而下的渐变：顶部偏蓝、地平线附近发白（和参考项目那种"室外天光"接近）
                行 = _np.linspace(0.0, 1.0, 高, dtype=_np.float32)[:, None]
                顶 = _np.array([86, 128, 176], dtype=_np.float32)      # 上方天蓝
                底 = _np.array([226, 233, 240], dtype=_np.float32)     # 近地发白
                色带 = 顶[None, :] * (1.0 - 行) + 底[None, :] * 行      # (高, 3)
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
        self._拖拽起点 = (事件.locationInWindow().x, 事件.locationInWindow().y)
        self._拖拽中 = True
        # NSEventModifierFlagShift = 1 << 17
        self._平移中 = bool(事件.modifierFlags() & (1 << 17))

    def mouseUp_(self, 事件):
        self._拖拽中 = False

    def mouseDragged_(self, 事件):
        if not self.就绪:
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
        if not self.就绪:
            return
        self.相机.distance = max(0.4, min(40.0,
                                     self.相机.distance * (1.0 - 事件.scrollingDeltaY() * 0.02)))
        self.请求渲染()
        self.setNeedsDisplay_(True)

    def 视角_复位(self) -> None:
        if not self.就绪:
            return
        self.相机.distance, self.相机.azimuth, self.相机.elevation = 3.2, 135.0, -16.0
        self.相机.lookat[:] = (0.0, 0.0, 0.45)
        self.请求渲染()
        self.setNeedsDisplay_(True)


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
            if 模型路径 and os.path.exists(模型路径):
                self.视口.准_备(模型路径)
            else:
                提示 = f"没有可加载的模型（驭臂_当前模型={模型路径!r}）"
                self.视口.错误 = 提示
                print(f"  ⚠ 3D 视口：{提示}", flush=True)

        # ② Web 界面（上方）：加载**本机服务**的地址（同一个 React 产物）
        配置 = WKWebViewConfiguration.alloc().init()
        self.网页 = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, 网页宽 if self.视口 else 宽, round(高)),
            配置)
        内容.addSubview_(self.网页)
        self.网页.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(参数.地址)))

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
            print("  操作   : 拖拽=转视角 ／ 滚轮=缩放 ／ Shift+拖拽=平移 ／ R=复位",
                  flush=True)
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
        网页宽, 视口宽 = _切分宽度(宽)
        self.视口.setFrame_(NSMakeRect(网页宽, 0, 视口宽, round(高)))
        self.网页.setFrame_(NSMakeRect(0, 0, 网页宽, round(高)))
        # 视口像素尺寸变了 → 重算离屏画布（保持"渲染分辨率=显示分辨率"，见 按视口重算画布）
        self.视口.按视口重算画布()

    # ---- 主线程每帧：只做"拉状态 + 要求重绘" ----
    def _主线程每帧(self) -> None:
        try:
            self.主线程帧 += 1
            if self.视口 is not None and self.视口.就绪:
                状态 = self.视口.最新状态
                # 只在收到**新**快照时同步 + 请求渲染（静止时不白烧 CPU）
                if 状态 is not None and 状态 is not self.上次状态:
                    self.上次状态 = 状态
                    self.视口.同步_状态(状态)
                    self.视口.请求渲染()
                self.视口.setNeedsDisplay_(True)
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
        字 = 事件.charactersIgnoringModifiers()
        if 字 and 字.lower() == "r" and self.视口 is not None:
            self.视口.视角_复位()


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
