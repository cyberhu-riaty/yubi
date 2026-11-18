"""macOS 桌面宿主，组合 WKWebView 和原生 3D 视口。

AppKit 和纹理上传在主线程执行。仿真与离屏渲染各用独立线程和
MjData，视口通过状态快照同步。MuJoCo Renderer 在渲染线程创建。

PyObjC 类名须用 ASCII。尾下划线表示 Objective-C 选择器，
纯 Python 方法须避免被注册为选择器。窗口尺寸由通知中心监听，
状态同步由 runloop_timers 驱动，主线程通过 setNeedsDisplay_ 请求重绘。
"""
from __future__ import annotations

import math
import os
import env_config
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
    import highlight_bridge as _highlight_bridge
except Exception:                                                     # noqa: BLE001
    _highlight_bridge = None

# 左侧是 Web 工作台，右侧是 3D 视口与运行信息。
DEFAULT_WEB_WIDTH_RATIO = 0.40      # 左侧 Web 面板占窗口宽度的比例
MIN_WEB_WIDTH = 500.0       # 再窄就放不下活动栏 + 侧栏
MIN_VIEWPORT_WIDTH = 560.0       # 3D 再窄就不好操作了（原 420 太窄，曲线/机械臂都挤）
def _split_widths(total_width: float) -> tuple[float, float]:
    """把窗口宽度切成 (左 Web 宽, 右 3D 宽)，两边都有下限。

    ★ 为什么要有下限：窗口很窄时按比例分会出现"Web 只剩 200px"或"3D 只剩 100px"，
      两个都看不清。宁可让 3D 少一点，也要保证 Web 面板正常
      （活动栏 48 + 侧栏最小 180 = 228，留余量取 520）。
    """
    total = float(total_width)
    web_width = max(float(MIN_WEB_WIDTH), min(total * DEFAULT_WEB_WIDTH_RATIO, total - float(MIN_VIEWPORT_WIDTH)))
    web_width = round(web_width)
    return web_width, round(total) - web_width


def _engineering_panel_height(viewport_width: float, total_height: float) -> float:
    """3D 变窄时，底部工程面板应占的高度（0 = 不显示）。

    ★ 判据不是"窗口比例"，而是 3D 视口的**宽高比**：3D 越窄越高，画面越容易
      在上下留黑边。目标比 0.95 ≈「还能看清机械臂、又不用整窗高」；低于它时，
      把差额让给底部工程面板，3D 仍贴着窗口上边。
    ★ 下限 190 px：内容少时不要占太高的空间；需要时再调。
    总高的 45% 上限：防止面板把 3D 挤没。
    """
    width = max(1.0, float(viewport_width))
    height = max(1.0, float(total_height))
    if width >= height * 0.95:
        return 0.0
    difference = height - width / 0.95
    return max(190.0, min(height * 0.50, difference))


DEFAULT_WINDOW_SIZE = (1440.0, 920.0)

# 诊断文件：delegate 里抛异常时 stdout 可能被别的东西占着，所以关键节点写一份文件。
# 排查用：驭臂_宿主诊断=/tmp/宿主.log
# 视口槽：入口（主程序窗口）注册状态观察者后，把建好的视口回填到这里，
# 这样"仿真线程 → 视口"这条线不需要视口自己去认识启动模块。
viewport_slot: dict = {'viewport': None}

# 最后建成的宿主实例。给平台适配层取"视口矩形 / 统计"用 ——
# 窗口是单例形态（一个进程一个窗口），所以模块级变量就够，不必搞注册表。
_last_host = None

def get_viewport_rectangle() -> tuple[int, int, int, int] | None:
    """原生 3D 渲染面当前占的矩形 (x, y, 宽, 高)，逻辑像素；没有则 None。"""
    host = _last_host
    if host is None or host.viewport is None:
        return None
    try:
        f = host.viewport.frame()
        return (int(f.origin.x), int(f.origin.y), int(f.size.width), int(f.size.height))
    except Exception:                                                 # noqa: BLE001
        return None


def get_statistics() -> dict:
    """运行统计（帧率、帧数、错误…）。排查用，**不参与业务**。"""
    host = _last_host
    if host is None:
        return {'state': "窗口未启动"}
    v = host.viewport
    output = {
        'main_thread_frames': host.main_thread_frames,
        'web_view': host.web_view is not None,
        'viewport_rectangle': get_viewport_rectangle(),
    }
    if v is not None:
        output.update({
            'viewport_ready': bool(v.ready),
            'viewport_rendered_frames': v.statistics.get('rendered_frames', 0),
            'viewport_displayed_frames': v.statistics.get('displayed_frames', 0),
            'viewport_fps': round(float(v.statistics.get("fps", 0.0)), 1),
            'viewport_state_syncs': v.statistics.get('state_syncs', 0),
            'viewport_error': v.error,
        })
    else:
        output['viewport_ready'] = False
    return output

_diagnostic_path = env_config.read("YUBI_DIAGNOSTIC")
_diagnostic_sequence = [0]


def record_diagnostic(content: str) -> None:
    """关键节点写一行到诊断文件（没设环境变量就什么也不做）。"""
    if not _diagnostic_path:
        return
    try:
        _diagnostic_sequence[0] += 1
        with open(_diagnostic_path, "a", encoding="utf-8") as f:
            f.write(f"{_diagnostic_sequence[0]:3d} [{time.strftime('%H:%M:%S')}] {content}\n")
    except Exception:                                                 # noqa: BLE001
        pass


def _model_bounds(model, data) -> tuple[Any, Any, float]:
    """用世界坐标几何算视觉包围盒（给自动取景/网格定尺用）。

    为什么不用 `geom_pos`：那是 body 局部坐标，直接平均会落在底座附近，
    相机贴脸、机械臂顶出画面（实测半径 0.36 vs 真实 ~0.85）。
    为什么不用 `stat.extent`：模型自带值对 1 m 臂偏大，画面偏小。
    为什么用 `geom_xpos + geom_rbound`：MuJoCo 已按真实 mesh 算好世界坐标包围球。

    排除面片/高度场和 worldbody 装饰（地面、天空盒），否则包围盒会被撑到无穷大。
    """
    import mujoco
    import numpy as np

    position = np.asarray(data.geom_xpos, dtype=float).reshape(-1, 3)
    radius = np.asarray(model.geom_rbound, dtype=float).ravel()
    kind = np.asarray(model.geom_type).ravel()
    owner = np.asarray(model.geom_bodyid).ravel()
    valid = np.isfinite(position).all(axis=1) & np.isfinite(radius) & (radius > 0)
    valid &= ~np.isin(kind, [int(mujoco.mjtGeom.mjGEOM_PLANE),
                          int(mujoco.mjtGeom.mjGEOM_HFIELD)])
    valid &= (owner != 0)
    if not bool(valid.any()):
        # 有些模型把整台机器人放在 worldbody 里；此时退回“只排面片”
        valid = np.isfinite(position).all(axis=1) & np.isfinite(radius) & (radius > 0)
    position, radius = position[valid], radius[valid]
    # 防御：贴地大平面 / 环境装饰的半径会远大于机器人部件
    median = float(np.median(radius)) if len(radius) else 0.0
    normal = radius < max(1.0, median * 8.0)
    if bool(normal.any()):
        position, radius = position[normal], radius[normal]
    lower = (position - radius[:, None]).min(axis=0)
    height = (position + radius[:, None]).max(axis=0)
    if not np.isfinite(lower).all() or not np.isfinite(height).all() or bool((height <= lower).any()):
        raise ValueError("包围盒退化")
    return lower, height, float(np.max(height - lower))


def _frame_model(model, data, width: int, height: int, azimuth: float, elevation: float,
          padding_factor: float = 1.10) -> tuple[Any, float, float]:
    """按包围盒 + 真实投影方向算相机（中心、距离、模型尺度）。

    ★ 不再用“包围球半径 / tan(fovy/2)”：那会把相机拉得比需要远 40%+
      （机器人只占 50% 画面高），而且中心是几何平均点，画面会偏。
      这里把包围盒 8 个角投到相机的 right/up 上，分别按水平/竖直视场求最小距离。
    """
    import mujoco
    import numpy as np

    lower, box_height, scale = _model_bounds(model, data)
    center = (lower + box_height) / 2.0
    half = (box_height - lower) / 2.0

    fovy = float(getattr(model.vis.global_, "fovy", 45.0) or 45.0)
    tan_v = math.tan(math.radians(fovy) / 2.0)
    tan_h = tan_v * (float(width) / max(1.0, float(height)))
    if tan_h <= 1e-9 or tan_v <= 1e-9:
        raise ValueError("视场角退化")

    # 用距离 1 的临时相机取 MuJoCo 的相机基（right/up/forward），
    # 这样取景方向与真正渲染时完全一致，不用自己推一遍符号。
    options = mujoco.MjvOption()
    mujoco.mjv_defaultOption(options)
    temporary = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, temporary)
    temporary.azimuth, temporary.elevation = float(azimuth), float(elevation)
    temporary.lookat[:] = center
    temporary.distance = 1.0
    scene = mujoco.MjvScene(model, maxgeom=1000)
    mujoco.mjv_updateScene(model, data, options, None, temporary,
                           mujoco.mjtCatBit.mjCAT_ALL, scene)
    initial_camera = scene.camera[0]
    camera_position = np.asarray(initial_camera.pos, dtype=float)
    before = np.asarray(initial_camera.forward, dtype=float)
    upper = np.asarray(initial_camera.up, dtype=float)
    right = np.cross(before, upper)
    right /= max(1e-9, float(np.linalg.norm(right)))
    upper /= max(1e-9, float(np.linalg.norm(upper)))

    margin = float(max(half)) * 0.04
    corners = np.array([
        [x, y, z]
        for x in (lower[0] - margin, box_height[0] + margin)
        for y in (lower[1] - margin, box_height[1] + margin)
        for z in (lower[2] - margin, box_height[2] + margin)
    ])
    needed = 0.0
    for point in corners:
        relative = point - camera_position
        depth_zero = float(np.dot(relative, before))
        x = float(np.dot(relative, right))
        y = float(np.dot(relative, upper))
        # 相机后退 Δ 后深度变成 深0+Δ；要求 |x|/深 <= tan_h、|y|/深 <= tan_v
        needed = max(needed, abs(x) / tan_h, abs(y) / tan_v)
    if not math.isfinite(needed) or needed <= 0.05:
        raise ValueError("取景距离退化")
    return center, float(needed * padding_factor), scale


def _grid_dimensions(scale: float) -> tuple[float, int]:
    """网格步长/半径：小机器人 0.1 m 一格，大场景 0.5/1 m 一格。"""
    if scale < 2.0:
        return 0.1, 10
    if scale < 8.0:
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
        attributes = [NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersionLegacy,
               NSOpenGLPFAColorSize, 24, NSOpenGLPFADepthSize, 24,
               NSOpenGLPFADoubleBuffer, NSOpenGLPFAAccelerated, 0]
        pixel_format = NSOpenGLPixelFormat.alloc().initWithAttributes_(attributes)
        self = objc.super(Viewport, self).initWithFrame_pixelFormat_(frame, pixel_format)
        if self is None:
            return None
        self.ready = False
        self.error = ""
        self.model = None
        self.data = None
        self.camera = None
        self.options = None
        self.renderer = None
        self.state_buffer = None
        self.buffers: dict = {}
        # 画面由渲染线程写、主线程只读；用"代"号避免重复上传纹理
        self.frame_image = None
        self.frame_generation = 0
        self.uploaded_generation = -1
        self.texture = 0
        self.statistics = {"fps": 0.0, 'rendered_frames': 0, 'displayed_frames': 0, 'state_syncs': 0}
        self._frame_times: list[float] = []
        self._should_stop = False
        self._render_thread = None
        self._model_generation = 0
        self._model_path = ""
        self.switching = False
        # 用 Event 唤醒渲染线程，避免忙等占用 GIL。
        import threading as _th
        self._render_requested = _th.Event()
        # 离屏分辨率独立于窗口尺寸，以控制渲染成本。
        # 离屏渲染分辨率。0×0 表示"还没算过"，首次 `按视口重算画布()` 会填上
        # （= 视口的原生像素尺寸，渲染与显示 1:1，不缩放 → 不糊）。
        self.canvas_size = (760, 420)
        self._canvas_target = (760, 420)
        self._canvas_rebuild_pending = False
        # 只有极端情况（5K 全屏 + 高 DPI）才碰这个上限；正常窗口远低于它
        self._canvas_limit = (2560, 1600)
        self._sky = None            # 缓存的天渐变（尺寸变了才重建，见 `_铺天空`）
        self._drag_origin = (0.0, 0.0)
        self._dragging = False
        self._drag_action = ""
        # 分隔条拖动期间锁住 3D 相机输入：分隔条拖动只应该改尺寸，
        # 不允许滚轮/拖拽事件漏进视口把相机拉近（用户报过"拖动后机械臂顶到脸上"）。
        self.interaction_locked = False
        # 最新状态快照：**仿真线程写、主线程读**。
        # 只做"整体替换一个引用"，所以不需要锁（CPython 的属性赋值是原子的）。
        self.latest_state = None
        # 相机：默认相机在装载时按模型算一次；复位回到它，适配则按当前姿态重算。
        self.default_camera = None
        self.grid_enabled = True
        self.end_effector_axes_enabled = True
        self.highlighted_joint = None
        self._grid = (0.1, 10)
        self._scale = 1.0
        # 第一次收到仿真状态后按**真实姿态**再取一次景：
        # 装载时的 model 默认姿态与仿真线程发来的首帧可能不同（实测机械臂会偏到右边）
        self._first_frame_framed = False
        return self

    # ------------------------------------------------------------------
    # 装载：模型 + 渲染器（在独立线程里做，见教训 ③）
    # ------------------------------------------------------------------
    def switch_model(self, model_path: str) -> bool:
        """主线程调用：停旧渲染线程、清状态、装载新模型。"""
        if not model_path or not os.path.exists(model_path):
            self.error = f'模型文件不存在：{model_path}'
            record_diagnostic(f'✗ 换模型：{self.error}')
            return False
        self.switching = True
        self.stop_render_thread()
        self._model_generation += 1          # 让尚未完成的旧装载线程作废
        self.ready = False
        self.error = ""
        self.model = None
        self.data = None
        self.camera = None
        self.options = None
        self.state_buffer = None
        self.buffers = {}
        self.latest_state = None
        self.default_camera = None
        self._first_frame_framed = False
        # 新模型加载时保留上一帧，避免视口闪黑。
        self.prepare_viewport(model_path)
        self.setNeedsDisplay_(True)
        record_diagnostic(f'换模型：开始装载 {os.path.basename(model_path)}')
        return True

    def stop_render_thread(self) -> None:
        """停掉旧渲染线程并等它退出（渲染器在它自己的线程里 close）。"""
        self._should_stop = True
        self._render_requested.set()
        t = self._render_thread
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        self._render_thread = None
        self.renderer = None

    def prepare_viewport(self, model_path: str, canvas: tuple[int, int] | None = None) -> None:
        """装载模型并起渲染线程。**渲染器在渲染线程里建**（见 `_渲染循环`）。"""
        self._model_path = model_path
        self._model_generation += 1
        generation = self._model_generation
        if canvas:
            self.canvas_size = (int(canvas[0]), int(canvas[1]))
        else:
            # 用"按视口算出来的目标尺寸"起步，避免第一帧还是默认比例
            self.canvas_size = self._canvas_target
            self._canvas_rebuild_pending = False

        def load_resources():
            try:
                import mujoco
                import numpy as np
                model = mujoco.MjModel.from_xml_path(model_path)
                data = mujoco.MjData(model)
                mujoco.mj_forward(model, data)
                # ★ 离屏帧缓冲默认只有 640×480，渲更大会
                #   `ValueError: Image width 760 > framebuffer width 640`（P2 教训）
                model.vis.global_.offwidth = max(1280, self.canvas_size[0])
                model.vis.global_.offheight = max(720, self.canvas_size[1])
                camera = mujoco.MjvCamera()
                mujoco.mjv_defaultFreeCamera(model, camera)
                # 默认视角要能看清整台机器人（默认视角常在模型外面）
                #
                # ★ 改成**按模型包围球自动取景**：原来写死 distance=3.2 / lookat z=0.45，
                #   对 Franka（约 1 m）勉强，换成 UR10e / iiwa14 就不合适了 ——
                #   小模型会缩成一点，大模型会顶出画面。这才是"模型看着太小"的原因。
                #   用 `geom_pos` 与 `geom_rbound` 算包围球（MuJoCo 白送的字段）。
                # ★ 自动取景：包围盒 8 个角投到相机平面，按水平/竖直视场求距离。
                #   旧版用“包围球半径 / tan(fovy/2)”，Franka 只占约 54% 画高，
                #   而且中心取的是几何平均点（偏上），所以画面看起来“又小又靠下”。
                camera.azimuth, camera.elevation = 135.0, -24.0
                try:
                    canvas_width, canvas_height = self.canvas_size
                    center, distance, scale = _frame_model(
                        model, data, canvas_width, canvas_height,
                        azimuth=camera.azimuth, elevation=camera.elevation, padding_factor=1.10)
                    camera.lookat[:] = center
                    camera.distance = float(distance)
                    self.default_camera = (center.copy(), float(distance),
                                     float(camera.azimuth), float(camera.elevation))
                    self._scale = float(scale)
                    self._grid = _grid_dimensions(self._scale)
                    record_diagnostic(f'自动取景：中心={center.round(3).tolist()} '
                           f'尺度={scale:.3f} 距离={camera.distance:.3f} '
                           f'网格={self._grid[0]}m')
                except Exception as _framing_error:                            # noqa: BLE001
                    camera.distance, camera.elevation = 2.6, -24.0
                    camera.lookat[:] = (0.0, 0.0, 0.45)
                    self.default_camera = (camera.lookat.copy(), 2.6, 135.0, -24.0)
                    self._scale = 1.0
                    self._grid = (0.1, 10)
                    record_diagnostic(f'自动取景失败，退回默认视角：{_framing_error}')
                options = mujoco.MjvOption()
                mujoco.mjv_defaultOption(options)
                # Renderer 在渲染线程创建，避免 OpenGL 上下文跨线程使用。
                if generation != self._model_generation:
                    return
                self.model, self.data = model, data
                self.camera, self.options = camera, options
                # 状态缓冲区按发布方的状态签名分配。
                self.buffers = {
                    int(mujoco.mjtState.mjSTATE_INTEGRATION): np.zeros(
                        mujoco.mj_stateSize(model, int(mujoco.mjtState.mjSTATE_INTEGRATION)),
                        np.float64),
                    int(mujoco.mjtState.mjSTATE_FULLPHYSICS): np.zeros(
                        mujoco.mj_stateSize(model, int(mujoco.mjtState.mjSTATE_FULLPHYSICS)),
                        np.float64),
                }
                self.state_buffer = self.buffers[int(mujoco.mjtState.mjSTATE_INTEGRATION)]
                if generation != self._model_generation:
                    return
                self.ready = True
                self.switching = False
                self._first_frame_framed = False
                self._should_stop = False
                self._render_thread = threading.Thread(target=self._render_loop, daemon=True,
                                                  name="3D渲染线程")
                self._render_thread.start()
                self.request_render()
                record_diagnostic(f'视口装载完成：{os.path.basename(model_path)} '
                      f'nq={model.nq} nu={model.nu} 画布={self.canvas_size}')
                print(f'  ✓ 3D 视口：已装载 {os.path.basename(model_path)}'
                      f'（nq={model.nq} nu={model.nu}）', flush=True)
            except Exception as exc:                                 # noqa: BLE001
                if generation == self._model_generation:
                    self.switching = False
                self.error = f'{type(exc).__name__}: {exc}'
                record_diagnostic(f'视口装载失败：{self.error}')
                print(f'  ✗ 3D 视口装载失败：{self.error}', flush=True)

        threading.Thread(target=load_resources, daemon=True, name="viewport-loader").start()

    # ------------------------------------------------------------------
    # 状态同步（只在渲染线程或主线程调；两边都不并发写）
    # ------------------------------------------------------------------
    def sync_state(self, state_message: Any) -> bool:
        """把状态快照灌进**自己那份** mjData。

        ★ 为什么不共享 MjData：仿真在后台线程、渲染在渲染线程，共享可变对象就要加锁；
          而"拷一份集成状态"只有几十个 double，代价可忽略，还完全没有竞态。
        """
        if not self.ready or state_message is None or self.state_buffer is None:
            return False
        try:
            import mujoco
            state = state_message.state
            signature = int(getattr(state_message, "state_sig",
                             int(mujoco.mjtState.mjSTATE_INTEGRATION)))
            # 按签名挑正确尺寸的缓冲：尺寸与签名不匹配时 mj_setState 会直接报错
            buffer = self.buffers.get(signature)
            if buffer is None or len(buffer) != len(state):
                buffer = self.ensure_state_buffer(signature, len(state))
            if buffer is None:
                self.error = f'状态尺寸不匹配：签名={signature} 长度={len(state)}'
                return False
            buffer[:] = state
            self.state_buffer = buffer
            mujoco.mj_setState(self.model, self.data, buffer, signature)
            mujoco.mj_forward(self.model, self.data)
            self.statistics['state_syncs'] += 1
            # 首帧按仿真侧的真实姿态重新取景（装载时用的是模型默认姿态）
            if not self._first_frame_framed and self.ready:
                self._first_frame_framed = True
                try:
                    self.fit_view()
                    record_diagnostic("首帧状态到达：已按真实姿态重新取景")
                except Exception as _framing_error:                            # noqa: BLE001
                    record_diagnostic(f'首帧取景失败（保留装载取景）：{_framing_error}')
            return True
        except Exception as exc:                                     # noqa: BLE001
            self.error = f'同步状态失败：{type(exc).__name__}: {exc}'
            return False

    def ensure_state_buffer(self, signature: int, length: int):
        """签名没见过就按需开一个正好长度的缓冲（并记下来复用）。"""
        try:
            import numpy as np
            if self.buffers.get(signature) is not None and len(self.buffers[signature]) != length:
                del self.buffers[signature]
            buffer = np.zeros(length, np.float64)
            self.buffers[signature] = buffer
            return buffer
        except Exception:                                             # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 渲染线程：按需渲染，产出像素放进 self.画面
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 画布比例
    # ------------------------------------------------------------------
    # ---- 让离屏画布的比例跟上视口，否则画面会被"信箱式"留黑边 ----
    def resize_canvas_for_viewport(self) -> None:
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
        size = self.convertRectToBacking_(self.bounds()).size
        width = max(1, int(size.width))
        height = max(1, int(size.height))
        if width <= 1 or height <= 1:
            # 首次布局时 bounds 可能还没就绪 → 用窗口逻辑尺寸 × 2（Retina）估一份，
            # 等真正的 resize 通知到了会再校正一次。
            width, height = 1440, 900
        # ★ 上限按**总像素**扣，不是按单边截断。
        #   我第一版写成 `宽=min(宽,2560); 高=min(高,1600)`，结果视口高 1750 被截到 1600
        #   → 画布比例与视口不一致 → 上屏只能等比缩放 → **上下各留一条黑边**。
        #   按面积等比缩，比例永远不变，代价只是极端大窗口下略微柔和。
        area = width * height
        max_area = 4_200_000            # ≈ 2048×2048，实测 ≈8.7ms/帧，够 100+ fps
        if area > max_area:
            factor = (max_area / area) ** 0.5
            width = max(1, int(width * factor))
            height = max(1, int(height * factor))
        if (width, height) != self._canvas_target:
            self._canvas_target = (width, height)
            self._canvas_rebuild_pending = True

    # ------------------------------------------------------------------
    # 背景：把纯黑换成渐变天空
    # ------------------------------------------------------------------
    def paint_sky_background(self, image) -> None:
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
            height, width = image.shape[0], image.shape[1]
            # ★ 用"位或"算掩码：三次逐通道比较 + 两次逻辑与，比 max(axis=2) 便宜得多
            #   （后者要分配一个 2.7MB 的临时数组，每帧分配会明显拖慢）。
            mask = (image[:, :, 0] | image[:, :, 1] | image[:, :, 2]) < 4
            if self._sky is None or self._sky.shape[0] != height or self._sky.shape[1] != width:
                # 深色工程场景：顶部深蓝、地平线略亮、近地再压暗。
                # 旧版是"上蓝下白"，灰色机器人压在浅底上对比很弱；
                # 网格线是浅色不透明线，在这层背景上还能保持可见（不会变成暗点）。
                row = _np.linspace(0.0, 1.0, height, dtype=_np.float32)[:, None]
                top = _np.array([22, 36, 54], dtype=_np.float32)
                middle = _np.array([55, 74, 96], dtype=_np.float32)
                bottom = _np.array([38, 52, 70], dtype=_np.float32)
                upper_half = _np.clip(row / 0.55, 0.0, 1.0)
                lower_half = _np.clip((row - 0.55) / 0.45, 0.0, 1.0)
                color_band = top[None, :] * (1.0 - upper_half) + middle[None, :] * upper_half
                color_band = color_band * (1.0 - lower_half) + bottom[None, :] * lower_half
                self._sky = _np.repeat(color_band[:, None, :], width, axis=1).astype(_np.uint8)
            # ★ 这里原来写的是 `图[掩码] = self._天空[掩码]`（布尔索引），
            #   实测 **57.5 ms/帧**，帧率从 60 掉到 11.8 —— 肉眼可见地卡。
            #   布尔索引会为 3×2.7M 个元素各建一份临时数组；换成逐通道
            #   `np.where` 后是 **7.3 ms/帧**（快 8 倍），60 fps 稳态不受影响。
            #   （另外两种也量过：copyto 15.4ms，仅 copy 0.4ms）
            for _c in range(3):
                image[:, :, _c] = _np.where(mask, self._sky[:, :, _c], image[:, :, _c])
        except Exception:                                             # noqa: BLE001
            pass          # 天空只是观感，失败绝不影响 3D 本身

    # ------------------------------------------------------------------
    # 场景装饰：地面网格 / 世界坐标 / 末端坐标
    # ------------------------------------------------------------------
    def add_line(self, scene, start, end, color, width: float = 1.0) -> None:
        """往 MjvScene 里追加一条装饰线段（不动物理、不改 MJCF）。"""
        import mujoco
        import numpy as np
        if scene is None or scene.ngeom >= scene.maxgeom:
            return
        geometry = scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(
            geometry, int(mujoco.mjtGeom.mjGEOM_LINE),
            np.array([float(width), 0.0, 0.0], dtype=float),
            np.zeros(3, dtype=float), np.eye(3).reshape(9),
            np.array(color, dtype=np.float32))
        mujoco.mjv_connector(
            geometry, int(mujoco.mjtGeom.mjGEOM_LINE), float(width),
            np.asarray(start, dtype=float), np.asarray(end, dtype=float))
        geometry.category = int(mujoco.mjtCatBit.mjCAT_DECOR)
        scene.ngeom += 1

    def draw_decorations(self, scene) -> None:
        """网格 + 世界轴 + 末端坐标。颜色/线宽都是装饰，不参与任何判定。"""
        import numpy as np
        if scene is None:
            return
        if self.grid_enabled:
            step, cell_count = self._grid
            bounds = float(step) * int(cell_count)
            for i in range(-cell_count, cell_count + 1):
                if i == 0:
                    continue
                major_grid = (i % 5 == 0)
                color = (0.52, 0.60, 0.70, 1.0) if major_grid else (0.30, 0.36, 0.43, 1.0)
                width = 2.0 if major_grid else 1.0
                value = i * step
                self.add_line(scene, (value, -bounds, 0.0), (value, bounds, 0.0), color, width)
                self.add_line(scene, (-bounds, value, 0.0), (bounds, value, 0.0), color, width)
            # 世界坐标：X 红 / Y 绿 / Z 蓝。只画 3 格长，避免 Z 轴穿出机器人头顶像一条杂线。
            axis_length = 3.0 * float(step)
            self.add_line(scene, (0, 0, 0), (axis_length, 0, 0), (0.95, 0.28, 0.28, 1), 3)
            self.add_line(scene, (0, 0, 0), (0, axis_length, 0), (0.28, 0.85, 0.38, 1), 3)
            self.add_line(scene, (0, 0, 0), (0, 0, axis_length), (0.35, 0.55, 1.0, 1), 3)
            # 原点标记（小球）：一眼看出世界原点在哪
            if scene.ngeom < scene.maxgeom:
                import mujoco
                geometry = scene.geoms[scene.ngeom]
                mujoco.mjv_initGeom(
                    geometry, int(mujoco.mjtGeom.mjGEOM_SPHERE),
                    np.array([0.012, 0.0, 0.0], dtype=float),
                    np.zeros(3, dtype=float), np.eye(3).reshape(9),
                    np.array([0.85, 0.92, 1.0, 1.0], dtype=np.float32))
                geometry.category = int(mujoco.mjtCatBit.mjCAT_DECOR)
                scene.ngeom += 1
        if self.end_effector_axes_enabled:
            self.draw_end_effector_axes(scene)
        self.draw_experiment_trajectory(scene)
        # 关节高亮：日志里的 Jn 点击后到这里画一个橙色球 + 三条短线。
        # 只做视觉标记，不改变任何物理量。
        if self.highlighted_joint is not None and self.model is not None and self.data is not None:
            try:
                import mujoco
                joint = int(self.highlighted_joint)
                if 0 <= joint < int(self.model.njnt):
                    position = np.asarray(self.data.xanchor[joint], dtype=float).reshape(3)
                    radius = max(0.04, min(0.09, float(self._scale) * 0.055))
                    # 关节锚点常在连杆内部，只画球会被挡住：从锚点向上引一根
                    # 橙色针，针顶再画球/坐标轴，保证在模型外面也看得见。
                    marker_length = max(0.18, min(0.38, float(self._scale) * 0.18))
                    marker_tip = position + np.array([0.0, 0.0, marker_length], dtype=float)
                    self.add_line(scene, position, marker_tip, (1.0, 0.50, 0.08, 1), 4.0)
                    for sphere_position in (position, marker_tip):
                        if scene.ngeom < scene.maxgeom:
                            geometry = scene.geoms[scene.ngeom]
                            mujoco.mjv_initGeom(
                                geometry, int(mujoco.mjtGeom.mjGEOM_SPHERE),
                                np.array([radius, 0.0, 0.0], dtype=float),
                                sphere_position, np.eye(3).reshape(9),
                                np.array([1.0, 0.55, 0.08, 1.0], dtype=np.float32))
                            geometry.category = int(mujoco.mjtCatBit.mjCAT_DECOR)
                            scene.ngeom += 1
                    length = max(0.10, min(0.22, float(self._scale) * 0.14))
                    for axis, shade in enumerate(((1.0, 0.45, 0.10, 1),
                                             (1.0, 0.80, 0.20, 1),
                                             (0.35, 0.75, 1.00, 1))):
                        direction = np.zeros(3, dtype=float)
                        direction[axis] = length
                        self.add_line(scene, marker_tip, marker_tip + direction, shade, 3.0)
            except Exception:                                         # noqa: BLE001
                pass

    def draw_end_effector_axes(self, scene) -> None:
        """在末端 site（没有就最后一个 body）画一小段 RGB 坐标轴。"""
        import mujoco
        import numpy as np
        if self.model is None or self.data is None:
            return
        position = None
        rotation = None
        site = -1
        for i in range(int(self.model.nsite)):
            name = mujoco.mj_id2name(self.model, int(mujoco.mjtObj.mjOBJ_SITE), i) or ""
            lowercase = name.lower()
            if any(k in lowercase for k in ("attach", "ee_", "tool", "tcp", "grip", "flange")):
                site = i
                break
        if site < 0 and int(self.model.nsite) > 0:
            site = int(self.model.nsite) - 1
        if site >= 0:
            position = np.asarray(self.data.site_xpos[site], dtype=float)
            rotation = np.asarray(self.data.site_xmat[site], dtype=float).reshape(3, 3)
        elif int(self.model.nbody) > 1:
            body = int(self.model.nbody) - 1
            position = np.asarray(self.data.xpos[body], dtype=float)
            rotation = np.asarray(self.data.xmat[body], dtype=float).reshape(3, 3)
        if position is None or rotation is None:
            return
        length = 0.08
        for axis, color in enumerate(((0.95, 0.35, 0.35, 1),
                                  (0.35, 0.90, 0.45, 1),
                                  (0.40, 0.60, 1.00, 1))):
            self.add_line(scene, position, position + rotation[:, axis] * length, color, 2.0)

    def draw_experiment_trajectory(self, scene) -> None:
        """把实验发布的末端目标/实际路径作为装饰画进 3D，不参与物理。"""
        import mujoco
        import numpy as np
        from trajectory_runtime import current_trajectory_visualization

        snapshot = current_trajectory_visualization()
        if not snapshot.experiment_key:
            return
        for points, color, width in (
                (snapshot.planned, (0.10, 0.86, 1.00, 0.72), 5.0),
                (snapshot.actual, (1.00, 0.46, 0.08, 1.00), 2.5)):
            if len(points) > 301:
                indices = np.linspace(0, len(points) - 1, 301).astype(int)
                points = points[indices]
            for start, end in zip(points[:-1], points[1:]):
                self.add_line(scene, start, end, color, width)
        for points, color, radius in (
                (snapshot.planned, (0.10, 0.86, 1.00, 1.0), 0.012),
                (snapshot.actual, (1.00, 0.46, 0.08, 1.0), 0.015)):
            if len(points) == 0 or scene.ngeom >= scene.maxgeom:
                continue
            geometry = scene.geoms[scene.ngeom]
            mujoco.mjv_initGeom(
                geometry, int(mujoco.mjtGeom.mjGEOM_SPHERE),
                np.array([radius, 0.0, 0.0], dtype=float),
                np.asarray(points[-1], dtype=float), np.eye(3).reshape(9),
                np.asarray(color, dtype=np.float32))
            geometry.category = int(mujoco.mjtCatBit.mjCAT_DECOR)
            scene.ngeom += 1

    def _render_loop(self) -> None:
        import time as _t
        while not self._should_stop:
            if self.renderer is None:
                # 在**本线程**建渲染器（GL 上下文的"建"与"用"必须同线程）
                import mujoco
                self.renderer = mujoco.Renderer(self.model, height=self.canvas_size[1],
                                            width=self.canvas_size[0])
                record_diagnostic(f'渲染线程：渲染器已建（画布={self.canvas_size}）')
                self.request_render()
            # 等 100 ms；超时也不做事，只是给"该停了"一个检查点。
            # 不用忙等（见 `_要渲` 的说明）。
            if not self._render_requested.wait(0.1):
                continue
            self._render_requested.clear()
            try:
                # 视口比例变了就**重建**渲染器（GL 上下文同线程，见教训 ③）。
                #   mujoco.Renderer 不提供 setSize，只能重建 —— 所以这一步故意做成
                #   "只在比例变化时"才发生，拖动窗口的过程中最多重建几次。
                if self._canvas_rebuild_pending and self.model is not None:
                    self._canvas_rebuild_pending = False
                    self.canvas_size = self._canvas_target
                    # ★ 必须同步抬高 MuJoCo 的离屏帧缓冲上限，否则会报
                    #   `ValueError: Image width N > framebuffer width M`
                    #   （这条坑 P2 就踩过一次，改分辨率时最容易复发）。
                    self.model.vis.global_.offwidth = max(
                        int(self.model.vis.global_.offwidth), int(self.canvas_size[0]))
                    self.model.vis.global_.offheight = max(
                        int(self.model.vis.global_.offheight), int(self.canvas_size[1]))
                    try:
                        self.renderer.close()
                    except Exception:                                 # noqa: BLE001
                        pass
                    self.renderer = mujoco.Renderer(self.model, height=self.canvas_size[1],
                                                  width=self.canvas_size[0])
                    record_diagnostic(f'渲染线程：画布重建为 {self.canvas_size}')
                self.renderer.update_scene(self.data, camera=self.camera,
                                       scene_option=self.options)
                # ★ 装饰必须加在 update_scene 之后：它每帧会重置 ngeom。
                self.draw_decorations(self.renderer.scene)
                image = self.renderer.render()
                # 把 MuJoCo 的**纯黑背景**换成渐变天空（视觉，不改任何物理）
                self.paint_sky_background(image)
                # OpenGL 纹理坐标是下到上；copy 让主线程安全读（切片本身是视图）
                self.frame_image = image[::-1].copy()
                self.frame_generation += 1
                self.statistics['rendered_frames'] += 1
                now = _t.perf_counter()
                self._frame_times.append(now)
                del self._frame_times[:-90]
                if len(self._frame_times) >= 2:
                    span = self._frame_times[-1] - self._frame_times[0]
                    if span > 0.2:
                        self.statistics["fps"] = (len(self._frame_times) - 1) / span
            except Exception as exc:                                     # noqa: BLE001
                self.error = f'渲染线程：{type(exc).__name__}: {exc}'
                record_diagnostic(f'✗ {self.error}')
                _t.sleep(0.5)
        try:
            if self.renderer is not None:
                self.renderer.close()
        except Exception:                                             # noqa: BLE001
            pass
        self.renderer = None
        self.statistics['render_thread_exited'] = 1

    def request_render(self) -> None:
        """叫渲染线程渲一帧（有新状态或相机变了就调这个）。"""
        self._render_requested.set()

    def receive_state(self, snapshot) -> None:
        """仿真线程调用：只把快照放好，别的都不做（不能碰 AppKit）。"""
        self.latest_state = snapshot

    # ------------------------------------------------------------------
    # 绘制（主线程）：只上传纹理 + 贴屏，不做 MuJoCo 渲染
    # ------------------------------------------------------------------
    def prepareOpenGL(self):
        """只做上下文自己的事。**绝不在这里建渲染器**（教训 ③）。"""
        objc.super(Viewport, self).prepareOpenGL()
        self.openGLContext().makeCurrentContext()
        record_diagnostic("视口：prepareOpenGL 完成")

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

    def drawRect_(self, _dirty_rectangle):
        from OpenGL import GL
        try:
            context = self.openGLContext()
            context.makeCurrentContext()
            # ★ 每帧绘制前再 update 一次：窗口/分隔条 resize 时，
            #   AppKit 的 reshape 和我们的 layout 都可能比 drawable 快一拍；
            #   如果 drawable 还是旧尺寸而 glViewport 已经用新尺寸，
            #   画面就会被裁切/放大（用户报的"机械臂顶到脸上"）。
            try:
                context.update()
            except Exception:                                         # noqa: BLE001
                pass
            size = self.convertRectToBacking_(self.bounds()).size
            width, height = max(1, int(size.width)), max(1, int(size.height))
            GL.glViewport(0, 0, width, height)
            GL.glClearColor(0.020, 0.047, 0.086, 1.0)     # 与界面底色一致
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            image = self.frame_image
            if image is not None:
                import numpy as np
                image = np.ascontiguousarray(image)
                image_height, image_width, _ = image.shape
                if self.texture == 0:
                    self.texture = GL.glGenTextures(1)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                else:
                    GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
                if self.frame_generation != self.uploaded_generation:              # 有新画面才重传
                    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, image_width, image_height, 0,
                                    GL.GL_RGB, GL.GL_UNSIGNED_BYTE, image.tobytes())
                    self.uploaded_generation = self.frame_generation
                # 等比铺满，两侧留底色（比拉伸好看）
                image_aspect = image_width / image_height
                viewport_aspect = width / height
                if image_aspect > viewport_aspect:
                    half_width, half_height = 1.0, (viewport_aspect / image_aspect)
                else:
                    half_width, half_height = (image_aspect / viewport_aspect), 1.0
                GL.glMatrixMode(GL.GL_PROJECTION); GL.glLoadIdentity()
                GL.glOrtho(0, 1, 0, 1, -1, 1)
                GL.glMatrixMode(GL.GL_MODELVIEW); GL.glLoadIdentity()
                GL.glEnable(GL.GL_TEXTURE_2D)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
                GL.glColor3f(1, 1, 1)
                GL.glBegin(GL.GL_QUADS)
                GL.glTexCoord2f(0, 0); GL.glVertex2f(0.5 - half_width / 2, 0.5 - half_height / 2)
                GL.glTexCoord2f(1, 0); GL.glVertex2f(0.5 + half_width / 2, 0.5 - half_height / 2)
                GL.glTexCoord2f(1, 1); GL.glVertex2f(0.5 + half_width / 2, 0.5 + half_height / 2)
                GL.glTexCoord2f(0, 1); GL.glVertex2f(0.5 - half_width / 2, 0.5 + half_height / 2)
                GL.glEnd()
                GL.glDisable(GL.GL_TEXTURE_2D)
                self.statistics['displayed_frames'] += 1
            context.flushBuffer()
        except Exception as exc:                                         # noqa: BLE001
            if self.statistics['displayed_frames'] == 0:
                self.error = f'drawRect_: {type(exc).__name__}: {exc}'
                record_diagnostic(f'✗ 绘制失败：{self.error}')

    # ------------------------------------------------------------------
    # 轨道相机：左键拖动旋转、右键拖动平移、滚轮缩放
    #   ★ 手感对齐 MuJoCo Studio：不自己写角度增量，直接调官方 mjv_moveCamera；
    #     位移按"占视口宽/高的比例"传，窗口大小不同手感一致。
    # ------------------------------------------------------------------
    def acceptsFirstResponder(self) -> bool:
        return True

    def move_camera(self, action, dx: float, dy: float) -> None:
        """把屏幕位移交给 MuJoCo 自己的相机逻辑。

        ★ 完全照官方 viewer 的喂法（simulate.cc）：
            `mjv_moveCamera(model, action, dx / r.height, -dy / r.height, &cam)`
        ★ AppKit 的 `locationInWindow` 是左下原点、y 向上；官方平台层也先把
          GLFW 的 y 翻成向上（`y = height - y`），再统一取负。所以这里也要
          **取负**：不取负的话，右键上下平移和左键上下旋转都会反。
        """
        if not self.ready or self.camera is None or self.model is None:
            return
        import mujoco
        height = max(1.0, float(self.bounds().size.height))
        mujoco.mjv_moveCamera(self.model, action, dx / height, -dy / height, self.camera)
        self.request_render()
        self.setNeedsDisplay_(True)

    def begin_drag(self, event, action: str) -> None:
        if getattr(self, 'interaction_locked', False):
            return
        # 点进 3D 才让视口拿键盘焦点：这样 R/F/G 不会和网页输入框抢键。
        try:
            self.window().makeFirstResponder_(self)
        except Exception:                                             # noqa: BLE001
            pass
        self._drag_origin = (event.locationInWindow().x, event.locationInWindow().y)
        self._dragging = True
        self._drag_action = action

    def drag_to(self, event) -> None:
        if not self._dragging or getattr(self, 'interaction_locked', False):
            return
        if not self.ready or self.camera is None:
            return
        import mujoco
        x, y = event.locationInWindow().x, event.locationInWindow().y
        dx, dy = x - self._drag_origin[0], y - self._drag_origin[1]
        self._drag_origin = (x, y)
        # 对齐官方 viewer：右键是 MOVE_V（真正的屏幕二维平移），
        # 左键是 ROTATE_V；MOVE_H / ROTATE_H 是按住 Shift 才用的平面版。
        action = (mujoco.mjtMouse.mjMOUSE_MOVE_V if self._drag_action == "平移"
              else mujoco.mjtMouse.mjMOUSE_ROTATE_V)
        self.move_camera(action, dx, dy)

    def mouseDown_(self, event):
        if int(event.clickCount()) >= 2:
            if not getattr(self, 'interaction_locked', False):
                self.fit_view()
            return
        # Shift+左键保留为平移别名：触控板单手时比右键方便。
        # NSEventModifierFlagShift = 1 << 17
        pan = bool(event.modifierFlags() & (1 << 17))
        self.begin_drag(event, "平移" if pan else "旋转")

    def mouseUp_(self, event):
        self._dragging = False
        self._drag_action = ""

    def mouseDragged_(self, event):
        self.drag_to(event)

    def rightMouseDown_(self, event):
        # 与 MuJoCo Studio 一致：右键拖动 = 平移相机。
        # 覆盖后不再走 NSView 默认的右键菜单。
        self.begin_drag(event, "平移")

    def rightMouseUp_(self, event):
        self._dragging = False
        self._drag_action = ""

    def rightMouseDragged_(self, event):
        self.drag_to(event)

    def scrollWheel_(self, event):
        if not self.ready or getattr(self, 'interaction_locked', False):
            return
        # 分隔条刚被点/拖过时，吞掉惯性滚动：否则触控板/鼠标的残余滚动
        # 会把 3D 相机一下拉到 0.4 的最近距离（机械臂顶满画面）。
        host = globals().get('_last_host')
        # 分隔条拖动/窗口调整后，触控板惯性滚动经常还会持续一两秒；
        # 0.8s 不够，残余滚动会把相机推进机械臂（用户看到的"巨大局部"）。
        if host is not None and time.monotonic() - getattr(host, 'splitter_interaction_time', 0.0) < 2.0:
            return
        # 0.4/0.8 都仍然会进入"机械臂占满画面"的距离。默认适配距离约 1.84，
        # 1.50 留出整机取景；要近看请用 F/适配或后续专门的聚焦，不靠滚轮钻进去。
        before = float(self.camera.distance)
        self.camera.distance = max(1.50, min(40.0,
                                     self.camera.distance * (1.0 - event.scrollingDeltaY() * 0.014)))
        if abs(self.camera.distance - before) > 0.001:
            record_diagnostic(f'相机滚轮：{before:.2f} -> {self.camera.distance:.2f}')
        self.request_render()
        self.setNeedsDisplay_(True)

    def fit_view(self) -> None:
        """按**当前姿态**重新适配（双击 3D 或按 F）。方向保持用户当前视角。"""
        if not self.ready or self.model is None or self.data is None:
            return
        try:
            width, height = self._canvas_target
            center, distance, scale = _frame_model(
                self.model, self.data, width, height,
                azimuth=float(self.camera.azimuth), elevation=float(self.camera.elevation),
                padding_factor=1.10)
            self.camera.lookat[:] = center
            self.camera.distance = float(distance)
            self.default_camera = (center.copy(), float(distance),
                             float(self.camera.azimuth), float(self.camera.elevation))
            self._scale = float(scale)
            self._grid = _grid_dimensions(self._scale)
            record_diagnostic(f'适配视图：中心={center.round(3).tolist()} 距离={distance:.3f}')
        except Exception as exc:                                         # noqa: BLE001
            record_diagnostic(f'适配视图失败：{type(exc).__name__}: {exc}')
        self.request_render()
        self.setNeedsDisplay_(True)

    def reset_camera(self) -> None:
        """回到装载时算好的取景（R 键）。不再写死 3.2 / z=0.45。"""
        if not self.ready:
            return
        if self.default_camera is not None:
            center, distance, azimuth, elevation = self.default_camera
            self.camera.lookat[:] = center
            self.camera.distance = float(distance)
            self.camera.azimuth = float(azimuth)
            self.camera.elevation = float(elevation)
        else:
            self.camera.distance, self.camera.azimuth, self.camera.elevation = 2.6, 135.0, -24.0
            self.camera.lookat[:] = (0.0, 0.0, 0.45)
        self.request_render()
        self.setNeedsDisplay_(True)

    def toggle_grid(self) -> None:
        self.grid_enabled = not self.grid_enabled
        record_diagnostic(f"网格：{('开' if self.grid_enabled else '关')}")
        self.request_render()
        self.setNeedsDisplay_(True)

    def toggle_end_effector_axes(self) -> None:
        self.end_effector_axes_enabled = not self.end_effector_axes_enabled
        self.request_render()
        self.setNeedsDisplay_(True)

    def keyDown_(self, event):
        """视口获得焦点后的快捷键。R 复位 / F 适配 / G 网格 / E 末端坐标。"""
        text = (event.charactersIgnoringModifiers() or "").lower()
        if text == "r":
            self.reset_camera()
            return
        if text == "f":
            self.fit_view()
            return
        if text == "g":
            self.toggle_grid()
            return
        if text == "e":
            self.toggle_end_effector_axes()
            return
        objc.super(Viewport, self).keyDown_(event)


class Splitter(NSView):
    """Web / 3D 之间的原生分隔条（可左右拖）。

    WebView 与原生视口是同级视图；这里放一条 7px 的 NSView 盖在交界处。
    拖它只改两个子视图的 frame 与 3D 画布尺寸，不碰任何业务状态。
    """

    def initWithHost_(self, host):
        self = objc.super(Splitter, self).init()
        if self is None:
            return None
        self.host = host
        self._start_x = 0.0
        self._start_width = 0.0
        return self

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), NSCursor.resizeLeftRightCursor())

    def drawRect_(self, rectangle):
        NSColor.colorWithCalibratedWhite_alpha_(0.45, 0.42).setFill()
        NSBezierPath.fillRect_(self.bounds())
        NSColor.colorWithCalibratedWhite_alpha_(0.92, 0.72).setFill()
        width = self.bounds().size.width
        height = self.bounds().size.height
        for offset in (-10.0, 0.0, 10.0):
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect((width - 3.0) / 2.0, height / 2.0 + offset, 3.0, 3.0)).fill()

    def acceptsFirstMouse_(self, _event):
        # 窗口不是 key 时，第一次点击也能开始拖分隔条。
        return True

    def mouseDown_(self, event):
        if int(event.clickCount()) >= 2:
            self.host.reset_splitter()
            return
        self._start_x = float(event.locationInWindow().x)
        self._start_width = float(self.host.get_web_width())
        self.host.begin_splitter_drag()

    def mouseDragged_(self, event):
        dx = float(event.locationInWindow().x) - self._start_x
        self.host.set_web_width(self._start_width + dx)

    def mouseUp_(self, _event):
        self.host.end_splitter_drag()


class PanelGrip(NSView):
    """工程面板顶部 7px 抓手：拖动调高度，双击收起/展开。"""

    def initWithPanel_(self, panel):
        self = objc.super(PanelGrip, self).init()
        if self is None:
            return None
        self.panel = panel
        self._start_y = 0.0
        self._start_height = 0.0
        return self

    def resetCursorRects(self):
        self.addCursorRect_cursor_(self.bounds(), NSCursor.resizeUpDownCursor())

    def drawRect_(self, _rectangle):
        NSColor.colorWithCalibratedWhite_alpha_(0.78, 1.0).setFill()
        NSBezierPath.fillRect_(NSMakeRect(0, self.bounds().size.height - 2, self.bounds().size.width, 1))
        NSColor.colorWithCalibratedWhite_alpha_(0.55, 1.0).setFill()
        width = self.bounds().size.width
        for offset in (-5.0, 0.0, 5.0):
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(width / 2.0 + offset, (self.bounds().size.height - 2) / 2.0, 2.0, 2.0)).fill()

    def acceptsFirstMouse_(self, _event):
        return True

    def mouseDown_(self, event):
        host = getattr(self.panel, 'host', None)
        if host is None:
            return
        if int(event.clickCount()) >= 2:
            host.toggle_engineering_panel()
            return
        self._start_y = float(event.locationInWindow().y)
        self._start_height = float(getattr(host, 'panel_height', 0.0) or 190.0)
        if getattr(host, '_panel_collapsed', False):
            host._panel_collapsed = False
            self._start_height = 190.0
        host.begin_panel_drag()

    def mouseDragged_(self, event):
        host = getattr(self.panel, 'host', None)
        if host is None:
            return
        dy = float(event.locationInWindow().y) - self._start_y
        host.set_panel_height(self._start_height + dy)

    def mouseUp_(self, _event):
        host = getattr(self.panel, 'host', None)
        if host is not None:
            host.end_panel_drag()


class ConsolePanel(NSView):
    """全宽工程面板（C 阶段）：原生日志镜像。

    为什么用原生而不是第二个 WKWebView：
      · 第二个 WebView 需要一套跨页日志/命令同步，成本和回归面都很大；
      · 这个面板只需要**展示**真实日志（由 Web 端经 WKScriptMessageHandler 发来），
        不需要 React/DOM；原生 NSTextView 足够稳定。
      · 命令输入仍留在 Web 端；本面板不假装是 shell。
    """

    def initWithFrame_(self, rectangle):
        self = objc.super(ConsolePanel, self).initWithFrame_(rectangle)
        if self is None:
            return None
        self._rows = []
        self._total = 0
        self._state_sync = False
        self._primary_filter = "无筛选"
        self._filter = "全部"
        self._header_height = 64.0
        self._collapsed = False
        self.host = None
        self._background_color = NSColor.colorWithCalibratedWhite_alpha_(0.975, 1.0)
        self._header_color = NSColor.colorWithCalibratedWhite_alpha_(0.935, 1.0)
        self._text_color = NSColor.colorWithCalibratedWhite_alpha_(0.13, 1.0)
        self._secondary_color = NSColor.colorWithCalibratedWhite_alpha_(0.42, 1.0)
        try:
            # 工程面板固定用浅色：它夹在浅色 Web 与深色 3D 之间，
            # 黑底小字是上一版用户反馈"看不清"的直接原因。
            self.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameAqua"))
        except Exception:                                             # noqa: BLE001
            pass
        self._title = NSTextField.alloc().initWithFrame_(NSMakeRect(10, 0, 260, 22))
        self._title.setStringValue_("工程面板 · 主日志镜像")
        self._title.setFont_(NSFont.systemFontOfSize_weight_(12.0, 0.4))
        self._title.setTextColor_(self._text_color)
        self._title.setDrawsBackground_(False)
        self._title.setBordered_(False)
        self._title.setEditable_(False)
        self._title.setSelectable_(False)
        self._title.setToolTip_("与左侧控制台使用同一份日志；筛选/清空会同步")
        self.addSubview_(self._title)

        self._count = NSTextField.alloc().initWithFrame_(NSMakeRect(250, 0, 160, 22))
        self._count.setStringValue_("0 / 0 条")
        self._count.setFont_(NSFont.systemFontOfSize_(10.0))
        self._count.setTextColor_(self._secondary_color)
        self._count.setDrawsBackground_(False)
        self._count.setBordered_(False)
        self._count.setEditable_(False)
        self._count.setSelectable_(False)
        self.addSubview_(self._count)

        self._filter_control = NSSegmentedControl.alloc().initWithFrame_(NSMakeRect(375, 0, 230, 22))
        self._filter_control.setSegmentCount_(4)
        for i, label in enumerate(("全部", "信息", "注意", "错误")):
            self._filter_control.setLabel_forSegment_(label, i)
        self._filter_control.setSelectedSegment_(0)
        self._filter_control.setTarget_(self)
        self._filter_control.setAction_("filterChanged:")
        self.addSubview_(self._filter_control)

        self._clear_button = NSButton.alloc().initWithFrame_(NSMakeRect(565, 0, 60, 22))
        self._clear_button.setTitle_("清空")
        self._clear_button.setBezelStyle_(NSBezelStyleRounded)
        self._clear_button.setTarget_(self)
        self._clear_button.setAction_("clearLog:")
        self.addSubview_(self._clear_button)

        self._collapse_button = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 60, 22))
        self._collapse_button.setTitle_("收起")
        self._collapse_button.setBezelStyle_(NSBezelStyleRounded)
        self._collapse_button.setTarget_(self)
        self._collapse_button.setAction_("toggleCollapsed:")
        self.addSubview_(self._collapse_button)

        self._grip = PanelGrip.alloc().initWithPanel_(self)
        self._grip.setToolTip_("拖动调整工程面板高度；双击收起/展开")
        self.addSubview_(self._grip)

        self._scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(8, 6, 700, 120))
        self._scroll_view.setHasVerticalScroller_(True)
        self._scroll_view.setDrawsBackground_(True)
        self._scroll_view.setBackgroundColor_(NSColor.whiteColor())
        self._scroll_view.setBorderType_(0)
        self._text = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, 700, 120))
        self._text.setEditable_(False)
        self._text.setSelectable_(True)
        self._text.setRichText_(False)
        self._text.setDrawsBackground_(True)
        self._text.setBackgroundColor_(NSColor.whiteColor())
        self._text.setTextColor_(self._text_color)
        self._text.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11.0, 0.0))
        self._text.setTextContainerInset_(NSMakeSize(6.0, 4.0))
        self._text.setMinSize_(NSMakeSize(0.0, 120.0))
        self._text.setMaxSize_(NSMakeSize(100000.0, 100000.0))
        self._text.setVerticallyResizable_(True)
        self._text.setHorizontallyResizable_(False)
        self._text.textContainer().setWidthTracksTextView_(True)
        self._scroll_view.setDocumentView_(self._text)
        self.addSubview_(self._scroll_view)
        return self

    def drawRect_(self, _rectangle):
        self._background_color.setFill()
        NSBezierPath.fillRect_(self.bounds())
        try:
            height = self.bounds().size.height
            width = self.bounds().size.width
            header_height = min(float(self._header_height), height)
            self._header_color.setFill()
            NSBezierPath.fillRect_(NSMakeRect(0.0, height - header_height, width, header_height))
            NSColor.colorWithCalibratedWhite_alpha_(0.78, 1.0).setStroke()
            line = NSBezierPath.bezierPath()
            line.moveToPoint_(NSMakePoint(0.0, height - header_height))
            line.lineToPoint_(NSMakePoint(width, height - header_height))
            line.stroke()
        except Exception:                                             # noqa: BLE001
            pass

    def layout_panel(self, width: float, height: float) -> None:
        width = max(1.0, float(width))
        height = max(1.0, float(height))
        # 统一两行头：第一行标题/计数/收起，第二行筛选/清空。
        # 这样 560~900px 的右列都不会把控件挤成一条。
        self._header_height = 34.0 if self._collapsed else 64.0
        upper = height - 25
        self._title.setFrame_(NSMakeRect(10, upper, max(100, width - 330), 20))
        self._count.setFrame_(NSMakeRect(max(120, width - 300), upper, 120, 20))
        self._collapse_button.setFrame_(NSMakeRect(width - 76, upper - 1, 60, 22))
        if self._collapsed:
            self._title.setStringValue_("工程面板 · 已收起（点展开或拖上沿）")
            self._filter_control.setHidden_(True)
            self._clear_button.setHidden_(True)
            self._scroll_view.setHidden_(True)
            self._grip.setFrame_(NSMakeRect(0, height - 7, width, 7))
            return
        self._title.setStringValue_("工程面板 · 主日志镜像")
        self._filter_control.setHidden_(False)
        self._clear_button.setHidden_(False)
        self._scroll_view.setHidden_(False)
        self._filter_control.setFrame_(NSMakeRect(10, height - 53, 230, 22))
        self._clear_button.setFrame_(NSMakeRect(252, height - 53, 60, 22))
        bottom = height - 70
        self._scroll_view.setFrame_(NSMakeRect(8, 6, width - 16, max(30, bottom - 6)))
        self._text.setFrameSize_(NSMakeSize(width - 16, max(30, bottom - 6)))
        self._grip.setFrame_(NSMakeRect(0, height - 7, width, 7))

    def set_collapsed(self, collapsed: bool) -> None:
        if bool(collapsed) == self._collapsed:
            return
        self._collapsed = bool(collapsed)
        self._collapse_button.setTitle_("展开" if self._collapsed else "收起")
        if self.host is not None:
            try:
                self.layout_panel(self.frame().size.width, self.frame().size.height)
            except Exception:                                     # noqa: BLE001
                pass

    def toggleCollapsed_(self, _sender):
        host = self.host or globals().get('_last_host')
        if host is not None:
            host.toggle_engineering_panel()
        else:
            self.set_collapsed(not self._collapsed)

    def set_state(self, row: list, total_count: int, summary: str, level: str) -> None:
        """接收 Web 主日志的**完整筛选结果**；计数、筛选、清空都以它为准。"""
        try:
            self._rows = [dict(r) for r in row][-800:]
            self._total = max(0, int(total_count))
            self._primary_filter = str(summary or "无筛选")
            self._state_sync = True
            if level == "全部":
                self._filter = "全部"
                self._filter_control.setSelectedSegment_(0)
            elif level == "信息":
                self._filter = "信息"
                self._filter_control.setSelectedSegment_(1)
            elif level == "注意":
                self._filter = "注意"
                self._filter_control.setSelectedSegment_(2)
            elif level == "错误":
                self._filter = "错误"
                self._filter_control.setSelectedSegment_(3)
            self.redraw_panel()
        except Exception:                                             # noqa: BLE001
            pass

    def add_row(self, row: dict) -> None:
        try:
            if self._state_sync:
                # 状态同步后，单行消息丢弃；否则会绕过主日志筛选，计数对不上。
                return
            self._rows.append(dict(row))
            del self._rows[:-800]
            self.redraw_panel()
        except Exception:                                             # noqa: BLE001
            pass

    def should_display(self, row: dict) -> bool:
        if self._filter == "全部":
            return True
        return str(row.get("等级", "")) == self._filter

    def redraw_panel(self) -> None:
        try:
            self._text.setString_("")
            display = self._rows if self._state_sync else [r for r in self._rows if self.should_display(r)]
            total_count = self._total if self._state_sync else len(self._rows)
            self._count.setStringValue_(f'{len(display)} / {total_count} 条')
            try:
                self._count.setToolTip_(f'与左侧控制台同一份日志；{self._primary_filter}')
            except Exception:                                     # noqa: BLE001
                pass
            for row in display[-500:]:
                try:
                    timestamp = ""
                    try:
                        import time as _t
                        timestamp = _t.strftime("%H:%M:%S", _t.localtime(float(row.get("墙钟", 0)) / 1000.0))
                    except Exception:                                 # noqa: BLE001
                        timestamp = str(row.get("时", ""))
                    level = str(row.get("等级", ""))
                    source = str(row.get("来源", ""))
                    plugin = str(row.get("插件", "") or "")
                    joint = row.get("关节")
                    header = f'{timestamp} {level} {source}'
                    if plugin:
                        header += f' · {plugin}'
                    if isinstance(joint, (int, float)) and int(joint) >= 0:
                        header += f' · J{int(joint)}'
                    text = f"{header}\n  {row.get('文本', '')}"
                    details = str(row.get("细节", "") or "")
                    if details:
                        text += f'\n  {details}'
                    shade = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.20, 0.26, 1.0)
                    if level == "注意":
                        shade = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.63, 0.34, 0.02, 1.0)
                    elif level == "错误":
                        shade = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.70, 0.10, 0.10, 1.0)
                    attributes = {
                        NSForegroundColorAttributeName: shade,
                        NSFontAttributeName: NSFont.monospacedSystemFontOfSize_weight_(11.0, 0.0),
                    }
                    rendered_text = NSAttributedString.alloc().initWithString_attributes_(text + "\n", attributes)
                    self._text.textStorage().appendAttributedString_(rendered_text)
                except Exception:                                     # noqa: BLE001
                    continue
            self._text.scrollToEndOfDocument_(None)
        except Exception:                                             # noqa: BLE001
            pass

    def filterChanged_(self, _sender):
        try:
            selection = int(self._filter_control.selectedSegment())
            self._filter = ("全部", "信息", "注意", "错误")[max(0, min(3, selection))]
            # 先本地立刻反馈；Web 状态回来后以同一份筛选结果为准。
            self._state_sync = False
            self.redraw_panel()
            host = globals().get('_last_host')
            if host is not None:
                host.send_log_action("筛选", self._filter)
        except Exception:                                             # noqa: BLE001
            pass

    def clearLog_(self, _sender):
        self._rows = []
        self._total = 0
        self._state_sync = True
        self.redraw_panel()
        try:
            host = globals().get('_last_host')
            if host is not None:
                host.send_log_action("清空", "")
        except Exception:                                             # noqa: BLE001
            pass


class LogBridge(NSObject):
    """WKWebView → 原生工程面板的单向日志桥。只接受对象，失败静默。"""

    def initWithPanel_(self, panel):
        self = objc.super(LogBridge, self).init()
        if self is None:
            return None
        self.panel = panel
        return self

    def userContentController_didReceiveScriptMessage_(self, _controller, message):
        try:
            body = dict(message.body())
            if self.panel is None:
                return
            if body.get("类型") == "日志状态":
                self.panel.set_state(
                    body.get("行", []) or [],
                    int(body.get("总数", 0) or 0),
                    str(body.get("筛选", "") or ""),
                    str(body.get("等级", "全部") or "全部"),
                )
            else:
                self.panel.add_row(body)
        except Exception:                                             # noqa: BLE001
            pass


class HostApp(NSObject):
    """窗口 + 每帧驱动。所有 AppKit 回调都在主线程。"""

    def init(self):
        self = objc.super(HostApp, self).init()
        if self is None:
            return None
        self.parameters = None
        self.window = None
        self.web_view = None
        self.viewport = None
        self.command_queue = None
        self.main_thread_frames = 0
        self.previous_state = None
        self.viewport_toolbar = None
        self.viewport_hint = None
        self.viewport_fps_label = None
        self.viewport_legend = None
        self.grid_button = None
        self.splitter = None
        self.current_web_width = None
        self.requested_web_width = None
        self.splitter_dragging = False
        self.splitter_interaction_time = 0.0
        self._splitter_camera = None
        self.current_model_path = env_config.read("YUBI_CURRENT_MODEL")
        self.pending_model_path = None
        self.pending_model_time = 0.0
        self.switch_label = None
        self.engineering_panel = None
        self.log_bridge = None
        self.panel_height = 0.0
        self._panel_previously_open = False
        self._panel_height_override = None
        self._panel_collapsed = False
        self._panel_dragging = False
        try:
            preferences = NSUserDefaults.standardUserDefaults()
            saved_height = preferences.objectForKey_("驭臂.工程面板高")
            if saved_height is not None:
                self._panel_height_override = float(saved_height)
            self._panel_collapsed = bool(preferences.boolForKey_("驭臂.工程面板收起"))
        except Exception:                                             # noqa: BLE001
            pass
        return self

    def applicationDidFinishLaunching_(self, _notification):
        try:
            self._create_window()
        except Exception as exc:                                     # noqa: BLE001
            # 教训 ⑦：delegate 里抛异常 = 静默失效，宁可打出来
            import traceback
            record_diagnostic(f'✗ 建窗口失败：{type(exc).__name__}: {exc}')
            print(f'  ✗ 建窗口失败：{type(exc).__name__}: {exc}', flush=True)
            traceback.print_exc()
            return
        record_diagnostic("delegate：建窗口完成")

        import runloop_timers as timers
        # 使用 runloop_timers 的 CFRunLoopTimer 驱动窗口刷新。
        self._frame_timer = timers.start(1.0 / 60.0, self._main_thread_tick)
        self._diagnostic_timer = timers.once(2.0, self._self_diagnose)
        record_diagnostic("delegate：定时器已起，delegate 结束")

    # ---- 3D 视图工具条（原生浮层，不经过 Web / 不破坏"界面只走仓库"的约定）----
    def create_viewport_toolbar(self, content, web_width: float, viewport_width: float, height: float) -> None:
        if self.viewport is None:
            return
        toolbar = NSView.alloc().initWithFrame_(NSMakeRect(web_width + 12, height - 44, 560, 32))
        try:
            toolbar.setWantsLayer_(True)
            toolbar.layer().setBackgroundColor_(
                NSColor.colorWithCalibratedWhite_alpha_(0.055, 0.62).CGColor())
            toolbar.layer().setCornerRadius_(7.0)
        except Exception as exc:                                         # noqa: BLE001
            record_diagnostic(f'工具条背景失败（不影响按钮）：{type(exc).__name__}: {exc}')

        title = NSTextField.alloc().initWithFrame_(NSMakeRect(9, 8, 54, 16))
        title.setStringValue_("3D")
        title.setFont_(NSFont.systemFontOfSize_(10.0))
        title.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.95, 0.9))
        title.setDrawsBackground_(False)
        title.setBordered_(False)
        title.setEditable_(False)
        title.setSelectable_(False)
        toolbar.addSubview_(title)
        self.viewport_fps_label = title

        def add_button(text: str, x: float, width: float,
                   action: str, switch: bool = False) -> Any:
            button = NSButton.alloc().initWithFrame_(NSMakeRect(x, 4, width, 24))
            button.setTitle_(text)
            button.setBezelStyle_(NSBezelStyleRounded)
            button.setFont_(NSFont.systemFontOfSize_(11.0))
            button.setTarget_(self)
            button.setAction_(action)
            if switch:
                button.setButtonType_(NSButtonTypeToggle)
            else:
                # 普通按钮也允许按一次后自动弹回
                button.setButtonType_(0)
            toolbar.addSubview_(button)
            return button

        add_button("适配", 64, 58, "fitView:")
        add_button("复位", 126, 58, "resetView:")
        self.grid_button = add_button("网格开", 188, 58, "toggleGrid:", switch=True)
        self.grid_button.setState_(1 if self.viewport.grid_enabled else 0)

        hint = NSTextField.alloc().initWithFrame_(NSMakeRect(260, 8, 292, 16))
        hint.setStringValue_("左键拖动旋转 · 右键拖动平移 · 滚轮缩放 · R 复位 · F 适配")
        hint.setFont_(NSFont.systemFontOfSize_(10.0))
        hint.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.88, 0.82))
        hint.setDrawsBackground_(False)
        hint.setBordered_(False)
        hint.setEditable_(False)
        hint.setSelectable_(False)
        toolbar.addSubview_(hint)

        legend = NSTextField.alloc().initWithFrame_(NSMakeRect(web_width + 14, 12, 340, 16))
        legend.setStringValue_("X 红 · Y 绿 · Z 蓝 · 网格 0.1m（粗线 0.5m）")
        legend.setFont_(NSFont.systemFontOfSize_(10.0))
        legend.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.88, 0.82))
        legend.setDrawsBackground_(True)
        legend.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.02, 0.55))
        legend.setBordered_(False)
        legend.setEditable_(False)
        legend.setSelectable_(False)

        switch = NSTextField.alloc().initWithFrame_(NSMakeRect(web_width + 12, height - 78, 280, 22))
        switch.setStringValue_("正在切换模型…")
        switch.setFont_(NSFont.systemFontOfSize_(12.0))
        switch.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.96, 0.95))
        switch.setDrawsBackground_(True)
        switch.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.02, 0.72))
        switch.setBordered_(False)
        switch.setEditable_(False)
        switch.setSelectable_(False)
        switch.setHidden_(True)

        self.viewport_toolbar, self.viewport_hint, self.viewport_legend = toolbar, hint, legend
        self.switch_label = switch
        content.addSubview_(toolbar)
        content.addSubview_(legend)
        content.addSubview_(switch)
        self.layout_viewport_toolbar(web_width, viewport_width, height)

    def layout_viewport_toolbar(self, web_width: float, viewport_width: float, height: float, bottom: float = 0.0) -> None:
        if self.viewport_toolbar is None:
            return
        width = max(300.0, min(560.0, float(viewport_width) - 24.0))
        self.viewport_toolbar.setFrame_(NSMakeRect(web_width + 12, height - 44, width, 32))
        if self.viewport_hint is not None:
            self.viewport_hint.setFrame_(NSMakeRect(260, 8, max(60.0, width - 268.0), 16))
            self.viewport_hint.setHidden_(width < 430)
        if self.viewport_legend is not None:
            image_width = max(120.0, min(360.0, float(viewport_width) - 28.0))
            self.viewport_legend.setFrame_(NSMakeRect(web_width + 14, float(bottom) + 12, image_width, 16))
            self.viewport_legend.setHidden_(image_width < 160)
        if self.switch_label is not None:
            label_width = max(120.0, min(300.0, float(viewport_width) - 28.0))
            self.switch_label.setFrame_(NSMakeRect(web_width + 12, height - 78, label_width, 22))
            self.switch_label.setHidden_(True)

    def begin_panel_drag(self) -> None:
        self._panel_dragging = True

    def end_panel_drag(self) -> None:
        self._panel_dragging = False
        if self.viewport is not None:
            try:
                self.viewport.resize_canvas_for_viewport()
                self.viewport.openGLContext().update()
                self.viewport.setNeedsDisplay_(True)
                self.viewport.displayIfNeeded()
            except Exception:                                         # noqa: BLE001
                pass

    def set_panel_height(self, height: float) -> None:
        self._panel_collapsed = False
        self._panel_height_override = max(190.0, min(float(self.window.contentView().bounds().size.height) * 0.70,
                                       float(height)))
        try:
            preferences = NSUserDefaults.standardUserDefaults()
            preferences.setDouble_forKey_(self._panel_height_override, "驭臂.工程面板高")
            preferences.setBool_forKey_(False, "驭臂.工程面板收起")
        except Exception:                                             # noqa: BLE001
            pass
        if self.window is not None:
            content = self.window.contentView()
            self.layout_views(float(content.bounds().size.width), float(content.bounds().size.height))

    def toggle_engineering_panel(self) -> None:
        self._panel_collapsed = not self._panel_collapsed
        try:
            NSUserDefaults.standardUserDefaults().setBool_forKey_(self._panel_collapsed, "驭臂.工程面板收起")
        except Exception:                                             # noqa: BLE001
            pass
        if self.window is not None:
            content = self.window.contentView()
            self.layout_views(float(content.bounds().size.width), float(content.bounds().size.height))

    def reset_panel_height(self) -> None:
        self._panel_height_override = None
        self._panel_collapsed = False
        self._panel_dragging = False
        try:
            preferences = NSUserDefaults.standardUserDefaults()
            saved_height = preferences.objectForKey_("驭臂.工程面板高")
            if saved_height is not None:
                self._panel_height_override = float(saved_height)
            self._panel_collapsed = bool(preferences.boolForKey_("驭臂.工程面板收起"))
        except Exception:                                             # noqa: BLE001
            pass
        if self.window is not None:
            content = self.window.contentView()
            self.layout_views(float(content.bounds().size.width), float(content.bounds().size.height))

    def send_log_action(self, kind: str, value: str) -> None:
        """原生工程面板 → Web 主日志：筛选/清空回到同一份日志状态。"""
        if self.web_view is None:
            return
        try:
            kind_text = str(kind).replace("'", "")
            value_text = str(value).replace("'", "")
            self.web_view.evaluateJavaScript_completionHandler_(
                "window.dispatchEvent(new CustomEvent('驭臂.日志操作',"
                "{detail:{类型:'" + kind_text + "',值:'" + value_text + "'}}));",
                None)
        except Exception:                                             # noqa: BLE001
            pass

    def _sync_panel_events(self) -> None:
        """3D 变窄/变宽时，通知 Web 收起/恢复它自己的控制台（避免两份重复）。"""
        enabled = self.panel_height > 0.5
        if enabled == self._panel_previously_open:
            return
        self._panel_previously_open = enabled
        if self.web_view is None:
            return
        try:
            value = "true" if enabled else "false"
            label = "1" if enabled else "0"
            # ★ WKWebView 的 API 是 evaluateJavaScript:completionHandler:，
            #   没有单参数版本；写 `evaluateJavaScript_` 会被静默拒掉。
            self.web_view.evaluateJavaScript_completionHandler_(
                "document.documentElement.setAttribute('data-native-panel','" + label + "');"
                "window.dispatchEvent(new CustomEvent('驭臂.工程面板',"
                "{detail:{开:" + value + "}}));",
                None)
            record_diagnostic(f'工程面板事件 -> {enabled}')
        except Exception as exc:                                     # noqa: BLE001
            record_diagnostic(f'工程面板事件失败：{type(exc).__name__}: {exc}')

    def begin_splitter_drag(self) -> None:
        self.splitter_dragging = True
        self.splitter_interaction_time = time.monotonic()
        record_diagnostic(f'分栏开始：当前网页宽={self.get_web_width():.0f}')
        v = self.viewport
        if v is None:
            return
        v.interaction_locked = True
        # 只快照已经完成首帧取景的相机；否则会把"首帧适配"也一起回滚。
        if v.camera is not None and getattr(v, '_first_frame_framed', False):
            try:
                self._splitter_camera = (
                    v.camera.lookat.copy(),
                    float(v.camera.distance),
                    float(v.camera.azimuth),
                    float(v.camera.elevation),
                )
            except Exception:                                         # noqa: BLE001
                self._splitter_camera = None
        else:
            self._splitter_camera = None

    def end_splitter_drag(self) -> None:
        self.splitter_dragging = False
        self.splitter_interaction_time = time.monotonic()
        v = self.viewport
        if v is None:
            return
        v.interaction_locked = False
        if self._splitter_camera is not None and v.camera is not None:
            try:
                center, distance, azimuth, elevation = self._splitter_camera
                v.camera.lookat[:] = center
                v.camera.distance = max(1.50, float(distance))
                v.camera.azimuth = azimuth
                v.camera.elevation = elevation
                v.request_render()
            except Exception:                                     # noqa: BLE001
                pass
        if v.camera is not None:
            try:
                if float(v.camera.distance) < 1.50:
                    record_diagnostic(f'相机兜底：{float(v.camera.distance):.2f} -> 1.50')
                    v.camera.distance = 1.50
                    v.request_render()
            except Exception:                                     # noqa: BLE001
                pass
        self._splitter_camera = None
        record_diagnostic(f'分栏结束：网页宽={self.get_web_width():.0f} 画布目标={v._canvas_target}')
        # 拖动期间故意不重建渲染器；松手后再按最终尺寸重建一次。
        try:
            v.openGLContext().update()
        except Exception:                                         # noqa: BLE001
            pass
        v.resize_canvas_for_viewport()
        v.setNeedsDisplay_(True)
        v.displayIfNeeded()

    def reset_splitter(self) -> None:
        """双击分隔条：回到默认 40/60，并让 C 面板按新比例重新判定。"""
        self.requested_web_width = None
        if self.window is None:
            return
        content = self.window.contentView()
        self.layout_views(float(content.bounds().size.width), float(content.bounds().size.height))

    def get_web_width(self) -> float:
        if self.current_web_width is not None:
            return float(self.current_web_width)
        if self.window is None:
            return float(MIN_WEB_WIDTH)
        width = float(self.window.contentView().bounds().size.width)
        return float(_split_widths(width)[0])

    def set_web_width(self, width: float) -> None:
        if self.window is None or self.viewport is None:
            return
        content = self.window.contentView()
        total_width = float(content.bounds().size.width)
        height = float(content.bounds().size.height)
        self.requested_web_width = max(float(MIN_WEB_WIDTH),
                              min(float(width), total_width - float(MIN_VIEWPORT_WIDTH)))
        self.layout_views(total_width, height)

    def layout_views(self, width: float, height: float) -> None:
        """按当前窗口尺寸排 Web / 3D / 分隔条 / 工具条。"""
        if self.web_view is None:
            return
        if self.viewport is None:
            self.current_web_width = round(width)
            self.web_view.setFrame_(NSMakeRect(0, 0, round(width), round(height)))
            return
        if self.requested_web_width is not None:
            web_width = max(float(MIN_WEB_WIDTH),
                        min(float(self.requested_web_width), float(width) - float(MIN_VIEWPORT_WIDTH)))
        else:
            web_width = _split_widths(width)[0]
        web_width = round(web_width)
        viewport_width = round(width) - web_width
        self.current_web_width = web_width
        automatic_height = round(_engineering_panel_height(viewport_width, height))
        if automatic_height <= 0:
            panel_height = 0
        elif self._panel_collapsed:
            panel_height = 34
        elif self._panel_height_override is not None:
            panel_height = int(max(190.0, min(float(height) * 0.70, float(self._panel_height_override))))
        else:
            panel_height = automatic_height
        self.panel_height = float(panel_height)
        top_height = round(height) - panel_height
        # 3D 贴窗口上边；面板只在右列（3D 下方），**不碰左下角 Web 状态栏**。
        # Web 保持整窗高：蓝色状态栏仍在最左下；右列被分成 3D（上）+ 工程面板（下）。
        self.viewport.setFrame_(NSMakeRect(web_width, panel_height, viewport_width, top_height))
        self.web_view.setFrame_(NSMakeRect(0, 0, web_width, round(height)))
        if self.splitter is not None:
            self.splitter.setFrame_(NSMakeRect(web_width - 3, 0, 7, round(height)))
        if self.engineering_panel is not None:
            self.engineering_panel.setHidden_(panel_height <= 0)
            if panel_height > 0:
                self.engineering_panel.set_collapsed(self._panel_collapsed)
            self.engineering_panel.setFrame_(NSMakeRect(web_width, 0, viewport_width, panel_height))
            if panel_height > 0:
                self.engineering_panel.layout_panel(viewport_width, panel_height)
        self._sync_panel_events()
        # 拖动分隔条时先不重建 MuJoCo 渲染器：老画面按新比例等比铺开即可，
        # 松手后由 结束_分栏拖动() 统一重建。这样既不会每拖一像素重建一次，
        # 也避开"渲染器重建/旧纹理同帧"导致的画面异常。
        if not self.splitter_dragging and not self._panel_dragging:
            self.viewport.resize_canvas_for_viewport()
        # ★ NSOpenGLView 的 drawable 不会自动跟着 setFrame_ 立刻换尺寸。
        #   不 update 就直接 glViewport 到新尺寸，会把旧 drawable 的一部分放大/裁切
        #   （用户拖动分隔条时看到的"机械臂突然顶到脸上"就是这个）。
        try:
            self.viewport.openGLContext().update()
        except Exception:                                             # noqa: BLE001
            pass
        self.viewport.setNeedsDisplay_(True)
        self.viewport.displayIfNeeded()
        self.layout_viewport_toolbar(web_width, viewport_width, height, panel_height)

    def fitView_(self, _sender):
        if self.viewport is not None:
            self.viewport.fit_view()

    def resetView_(self, _sender):
        if self.viewport is not None:
            self.viewport.reset_camera()

    def toggleGrid_(self, sender):
        if self.viewport is not None:
            self.viewport.toggle_grid()
            try:
                sender.setState_(1 if self.viewport.grid_enabled else 0)
                sender.setTitle_("网格开" if self.viewport.grid_enabled else "网格关")
            except Exception:                                             # noqa: BLE001
                pass

    def _create_window(self) -> None:
        parameters = self.parameters
        width, height = parameters.width, parameters.height

        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(120, 120, width, height),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered, False)
        window.setTitle_(parameters.title)
        window.setBackgroundColor_(NSColor.blackColor())
        # 用通知中心接收窗口尺寸变化。
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            # ⚠️ 这里传的是**选择器字符串**，不是 Python 方法名：
            #    选择器里用**冒号**表示参数，所以是 `"windowResized:"` 而不是 `"窗口改尺寸_:"`。
            #    写成尾下划线会被原样当选择器名，运行期报
            #    `unrecognized selector sent to instance`（而且只在有 resize 时才炸）。
            self, "windowResized:", NSWindowDidResizeNotification, window)
        self.window = window

        content = window.contentView()
        # ★ 整数像素：小数会让两个视图在边界重叠 ~1px（状态栏被盖掉半行就是这么来的）
        web_width, viewport_width = _split_widths(width)

        # ⓪ 全宽工程面板（C）：先建好、默认隐藏；日志由 Web 经 WKScriptMessageHandler 镜像进来。
        self.engineering_panel = ConsolePanel.alloc().initWithFrame_(NSMakeRect(0, 0, round(width), 0))
        self.engineering_panel.host = self
        self.engineering_panel.setHidden_(True)
        content.addSubview_(self.engineering_panel)
        self.log_bridge = LogBridge.alloc().initWithPanel_(self.engineering_panel)

        # ① 3D 视口（**右侧主区域**）
        if parameters.no_3d:
            self.viewport = None
        else:
            self.viewport = Viewport.alloc().initWithFrame_(
                NSMakeRect(web_width, 0, viewport_width, round(height)))
            # ★ 建窗口时就要算一次画布比例：`窗口改尺寸_` 只在**真的改尺寸**时触发，
            #   启动时不会触发 —— 我第一版只在 resize 里算，于是启动永远用默认 760×420，
            #   画面上就一直是"两边留黑边"的样子（还以为是渲染器的事）。
            self.viewport.resize_canvas_for_viewport()
            content.addSubview_(self.viewport)
            viewport_slot['viewport'] = self.viewport
            model_path = env_config.read("YUBI_CURRENT_MODEL")
            self.current_model_path = model_path
            if model_path and os.path.exists(model_path):
                self.viewport.prepare_viewport(model_path)
            else:
                hint = f'没有可加载的模型（驭臂_当前模型={model_path!r}）'
                self.viewport.error = hint
                print(f'  ⚠ 3D 视口：{hint}', flush=True)

        # ② Web 界面（上方）：加载**本机服务**的地址（同一个 React 产物）
        configuration = WKWebViewConfiguration.alloc().init()
        try:
            configuration.userContentController().addScriptMessageHandler_name_(self.log_bridge, "驭臂日志")
        except Exception as exc:                                     # noqa: BLE001
            print(f'  ⚠ 日志镜像桥不可用：{type(exc).__name__}: {exc}', flush=True)
        try:
            # 在文档开始就监听：宿主打开/关闭全宽工程面板时，用它把 Web 自己的控制台藏起来。
            # CSS 负责立刻隐藏（即使 React 还没处理完事件），避免出现"上下两份日志"。
            script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
                "window.addEventListener('驭臂.工程面板', function(e){"
                "document.documentElement.setAttribute('data-native-panel',"
                "(e && e.detail && e.detail.开) ? '1' : '0');});",
                WKUserScriptInjectionTimeAtDocumentStart, True)
            configuration.userContentController().addUserScript_(script)
        except Exception as exc:                                     # noqa: BLE001
            print(f'  ⚠ 工程面板脚本注入失败：{type(exc).__name__}: {exc}', flush=True)
        self.web_view = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, web_width if self.viewport else width, round(height)),
            configuration)
        content.addSubview_(self.web_view)
        # ★ 加版本查询串，强制 WKWebView 重新取 index.html：
        #   Web 产物每次构建都会换 assets 哈希，但 WKWebView 会缓存 index.html，
        #   结果就是"明明重新 build 了，界面还是旧的控制台"（本轮真实踩到）。
        #   查询串不影响 Vite/React 路由；只让入口 HTML 不进缓存。
        load_url = parameters.url
        load_url += ("&" if "?" in load_url else "?") + f"v={time.time_ns()}"
        self.web_view.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(load_url)))

        # ③ Web / 3D 分隔条（原生 NSView，可左右拖）
        if self.viewport is not None:
            self.splitter = Splitter.alloc().initWithHost_(self)
            self.splitter.setFrame_(NSMakeRect(web_width - 3, 0, 7, round(height)))
            try:
                self.splitter.setToolTip_("拖动调整 Web / 3D 宽度；双击恢复默认 40/60")
            except Exception:                                         # noqa: BLE001
                pass
            content.addSubview_(self.splitter)
            self.current_web_width = round(web_width)

        # ④ 3D 视图工具条（原生 NSView，浮在 3D 顶部；Web 界面完全不知道它）
        if self.viewport is not None:
            self.create_viewport_toolbar(content, web_width, viewport_width, height)

        window.makeKeyAndOrderFront_(None)

        print("=" * 80, flush=True)
        print(f'  {parameters.title}', flush=True)
        print("=" * 80, flush=True)
        if self.viewport:
            print(f'  窗口   : {width:.0f}×{height:.0f}'
                  f'（左 Web {web_width:.0f}px ／ 右 3D 视口 {viewport_width:.0f}px）', flush=True)
        else:
            print(f'  窗口   : {width:.0f}×{height:.0f}（--无3D：Web 界面铺满）', flush=True)
        print(f'  界面   : {parameters.url}（我们窗口里的 WKWebView，不是外部浏览器）', flush=True)
        if self.viewport:
            print("  操作   : 左键拖动=转视角 ／ 右键拖动=平移 ／ 滚轮=缩放 ／ "
                  "R=复位 ／ F=适配 ／ G=网格 ／ 双击=适配", flush=True)
        print("=" * 80, flush=True)

    # ---- resize：按比例重排（通知触发，不是 delegate）----
    def windowResized_(self, _notification):
        if self.window is None:
            return
        content = self.window.contentView()
        width = content.bounds().size.width
        height = content.bounds().size.height
        # ★ 整数像素：小数会让两个视图在边界重叠 ~1px
        #   （表现就是"状态栏被盖掉半行"）。
        if self.viewport is None:
            self.web_view.setFrame_(NSMakeRect(0, 0, round(width), round(height)))
            return
        self.layout_views(width, height)

    # ---- 主线程每帧：只做"拉状态 + 要求重绘" ----
    def _main_thread_tick(self) -> None:
        try:
            self.main_thread_frames += 1
            if self.viewport is not None:
                # 换模型：仿真线程的模型观察者只把路径放进槽里，这里在主线程重装。
                # 不能在仿真线程碰 AppKit/GL；重装本身会停旧渲染线程、清状态、
                # 重新按新模型取景，再启动新的渲染线程。
                pending_model = viewport_slot.get('pending_model')
                if pending_model:
                    viewport_slot['pending_model'] = None
                    self.pending_model_path = str(pending_model)
                    self.pending_model_time = time.monotonic()
                # 连续点模型时合并：最后一次点击后安静 0.15s 再重装，
                # 避免每个中间模型都停一次渲染线程、黑一下。
                if (self.pending_model_path
                        and time.monotonic() - self.pending_model_time >= 0.15):
                    target = self.pending_model_path
                    self.pending_model_path = None
                    try:
                        same_path = os.path.normpath(str(target)) == os.path.normpath(str(self.current_model_path))
                    except Exception:                                     # noqa: BLE001
                        same_path = str(target) == str(self.current_model_path)
                    if not same_path:
                        if self.viewport.switch_model(str(target)) and self.switch_label is not None:
                            self.switch_label.setStringValue_(
                                f'正在切换模型：{os.path.basename(str(target))}')
                if self.switch_label is not None:
                    self.switch_label.setHidden_(not bool(getattr(self.viewport, 'switching', False)))
                # 只有真正装载完成才更新“当前路径”；加载失败时保持旧路径，
                # 这样下一次点同一路径会重试，而不是被误判成“已经是它了”。
                if self.viewport.ready and getattr(self.viewport, '_model_path', ""):
                    self.current_model_path = str(self.viewport._model_path)
            if self.viewport is not None and self.viewport.ready:
                state = self.viewport.latest_state
                # 只在收到**新**快照时同步 + 请求渲染（静止时不白烧 CPU）
                if state is not None and state is not self.previous_state:
                    self.previous_state = state
                    self.viewport.sync_state(state)
                    self.viewport.request_render()
                self.viewport.setNeedsDisplay_(True)
                # 防御相机被旧版本/漏出的滚轮推进到机械臂内部；正常缩放最低 0.8。
                if self.viewport.camera is not None and float(self.viewport.camera.distance) < 1.50:
                    record_diagnostic(f'相机每帧兜底：{float(self.viewport.camera.distance):.2f} -> 1.50')
                    self.viewport.camera.distance = 1.50
                    self.viewport.request_render()
                # 关节高亮：进程内共享状态，10 Hz 轮询足够；过期自动消失。
                if _highlight_bridge is not None and self.main_thread_frames % 6 == 0:
                    try:
                        joint = _highlight_bridge.get_highlight()
                        if joint != self.viewport.highlighted_joint:
                            self.viewport.highlighted_joint = joint
                            record_diagnostic(f'高亮关节 -> {joint}')
                            self.viewport.request_render()
                            self.viewport.setNeedsDisplay_(True)
                    except Exception:                                 # noqa: BLE001
                        pass
                if self.main_thread_frames % 30 == 0:
                    try:
                        fps = float(self.viewport.statistics.get("fps", 0.0))
                        if self.viewport_fps_label is not None:
                            self.viewport_fps_label.setStringValue_(f"3D {fps:.0f}fps")
                        if self.viewport_legend is not None:
                            step = float(self.viewport._grid[0])
                            highlight = self.viewport.highlighted_joint
                            suffix = f' · 高亮 J{int(highlight)}' if highlight is not None else ""
                            self.viewport_legend.setStringValue_(
                                f'X 红 · Y 绿 · Z 蓝 · 网格 {step:g}m（粗线 {step * 5:g}m）{suffix}')
                    except Exception:                                     # noqa: BLE001
                        pass
        except Exception as exc:                                         # noqa: BLE001
            if self.main_thread_frames < 3:
                record_diagnostic(f'✗ 每帧回调异常：{type(exc).__name__}: {exc}')

    def _self_diagnose(self) -> None:
        v = self.viewport
        if v is None:
            record_diagnostic(f'★ 自诊断：主线程帧={self.main_thread_frames}（--无3D）')
            print(f'  [自诊断] 主线程帧={self.main_thread_frames}（--无3D，没有 3D 视口）', flush=True)
            return
        record_diagnostic(f'★ 自诊断：主线程帧={self.main_thread_frames} 就绪={v.ready} '
              f"渲染帧={v.statistics['rendered_frames']} 显示帧={v.statistics['displayed_frames']} "
              f"fps={v.statistics['fps']:.1f} 同步={v.statistics['state_syncs']} 错误={v.error!r}")
        if v.ready:
                print(f"  [自诊断] 3D：渲染 {v.statistics['rendered_frames']} 帧 / 显示 {v.statistics['displayed_frames']} 帧"
                  f" ／ {v.statistics['fps']:.1f} fps ／ 状态同步 {v.statistics['state_syncs']} 次"
                  f' ／ 主线程帧 {self.main_thread_frames}', flush=True)
        else:
            print(f'  [自诊断] 3D 不可用：{v.error}', flush=True)

    def keyDown_(self, event):
        # 窗口层的兜底：视口没拿到焦点时（极少见）也能用同样的键
        text = (event.charactersIgnoringModifiers() or "").lower()
        if self.viewport is None or not text:
            return
        if text == "r":
            self.viewport.reset_camera()
        elif text == "f":
            self.viewport.fit_view()
        elif text == "g":
            self.viewport.toggle_grid()
        elif text == "e":
            self.viewport.toggle_end_effector_axes()


_parameters = None


def run(url: str, title: str = "小软件 · 机器人仿真工作台",
       width: float = DEFAULT_WINDOW_SIZE[0], height: float = DEFAULT_WINDOW_SIZE[1],
       command_queue: list | None = None, no_3d: bool = False) -> int:
    """起窗口并进入 AppKit 主循环。返回进程退出码。

    ★ 调用前必须：① Web 服务已起 ② 仿真正在**后台线程**跑 ③ `驭臂_当前模型` 已设。
    """
    import argparse

    parameters = argparse.Namespace(url=url, title=title, width=float(width), height=float(height), no_3d=no_3d)
    application = NSApplication.sharedApplication()
    application.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    host = HostApp.alloc().init()
    host.parameters = parameters
    host.command_queue = command_queue
    application.setDelegate_(host)
    global _last_host
    _last_host = host
    application.activateIgnoringOtherApps_(True)
    record_diagnostic("跑()：即将进入 app.run()")
    application.run()
    record_diagnostic("跑()：app.run() 已返回")
    return 0
