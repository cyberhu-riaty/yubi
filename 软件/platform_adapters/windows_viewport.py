"""Windows 的 MuJoCo 3D 视口。

仿真线程只把 ``StateSnapshot`` 放进来；本模块维护独立的 MjData，并在
独立渲染线程中把 MuJoCo 场景生成 RGB 图像。Qt 主线程只负责显示图像和接收
鼠标操作，避免跨线程共享仿真数据或 OpenGL 上下文。
"""
from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QWidget


class MuJoCoViewport(QWidget):
    """把 MuJoCo 离屏渲染结果显示在 Qt 控件中。"""

    frame_ready = Signal(object)
    status_changed = Signal(str)

    def __init__(self, model_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(360, 280)
        self.setMouseTracking(True)

        self.latest_state: Any = None
        self.ready = False
        self.switching = True
        self.error = ""
        self._model_path = ""
        self._status_text = "正在加载…"
        self._frame_image: QImage | None = None
        self._drag_point = None
        self._panning = False

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._actions: queue.SimpleQueue[tuple] = queue.SimpleQueue()
        self._pending_model = str(model_path)
        self._pending_canvas = (960, 640)
        self._latest_lock = threading.Lock()
        self._statistics = {
            "渲染帧": 0,
            "显示帧": 0,
            "状态同步": 0,
            "fps": 0.0,
            "错误": "",
        }

        self.frame_ready.connect(self._receive_frame)
        self.status_changed.connect(self._receive_status)

        # 调整分栏时分两拍更新：拖动中约 20 Hz 跟手，停止 180 ms 后再提交最终尺寸。
        # 旧实现只等“安静 180 ms”才更新，所以分割线在动、3D 画面却像卡住了。
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self._commit_canvas_size)
        self._final_resize_timer = QTimer(self)
        self._final_resize_timer.setSingleShot(True)
        self._final_resize_timer.setInterval(180)
        self._final_resize_timer.timeout.connect(self._commit_canvas_size)

        self._thread = threading.Thread(
            target=self._render_loop, daemon=True, name="Windows-3D渲染线程")
        self._thread.start()

    # ---------- 仿真线程 / 宿主窗口调用的最小接口 ----------
    def receive_state(self, snapshot: Any) -> None:
        """仿真线程调用：只替换最新快照，不触碰 Qt 和 MuJoCo 对象。"""
        with self._latest_lock:
            self.latest_state = snapshot
        self._wake.set()

    def switch_model(self, model_path: str) -> bool:
        if not model_path or not os.path.isfile(model_path):
            self.error = f'模型文件不存在：{model_path}'
            self._statistics["错误"] = self.error
            return False
        self.switching = True
        self._pending_model = str(model_path)
        with self._latest_lock:
            self.latest_state = None
        self._wake.set()
        return True

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    @Slot()
    def fit_camera(self) -> None:
        """供 3D 顶栏按钮调用；与双击视口、F/R 键使用同一套相机逻辑。"""
        self._actions.put(("适配",))
        self._wake.set()

    def statistics(self) -> dict:
        return dict(self._statistics)

    def runtime_info(self) -> dict:
        """供 Qt 右下信息面板读取；只返回快照副本，不暴露渲染线程对象。"""
        with self._latest_lock:
            snapshot = self.latest_state
        return {
            "模型": os.path.basename(self._model_path) if self._model_path else "",
            "仿真时间": getattr(snapshot, "time", None) if snapshot is not None else None,
            "qpos": getattr(snapshot, "qpos", ()) if snapshot is not None else (),
            "qvel": getattr(snapshot, "qvel", ()) if snapshot is not None else (),
            "ctrl": getattr(snapshot, "ctrl", ()) if snapshot is not None else (),
            "状态": self._status_text,
        }

    # ---------- Qt 主线程：显示与输入 ----------
    @Slot(object)
    def _receive_frame(self, image: QImage) -> None:
        self._frame_image = image
        self._statistics["显示帧"] += 1
        self.update()

    @Slot(str)
    def _receive_status(self, text: str) -> None:
        self._status_text = str(text or "")
        self.setToolTip(text)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(10, 18, 30))
        if self._frame_image is not None:
            target = self._frame_image.size().scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x = (self.width() - target.width()) // 2
            y = (self.height() - target.height()) // 2
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(x, y, self._frame_image.scaled(
                target, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            painter.setPen(QColor(190, 203, 220))
            text = f'3D 视口加载失败\n{self.error}' if self.error else "正在加载 MuJoCo 3D 视口…"
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 先立刻重绘：用已有图像填充新矩形，拖动分割线时不会留下静止旧画面。
        self.update()
        if not self._resize_timer.isActive():
            self._resize_timer.start()
        self._final_resize_timer.start()

    def _commit_canvas_size(self) -> None:
        ratio = max(1.0, float(self.devicePixelRatioF()))
        width, height = max(320, int(self.width() * ratio)), max(240, int(self.height() * ratio))
        # 极大窗口按面积等比缩小，避免无意义地渲染数百万以上像素。
        max_area = 2_500_000
        if width * height > max_area:
            zoom = (max_area / (width * height)) ** 0.5
            width, height = int(width * zoom), int(height * zoom)
        self._pending_canvas = (width, height)
        self._wake.set()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._drag_point = event.position()
            self._panning = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_point is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        point = event.position()
        dx, dy = point.x() - self._drag_point.x(), point.y() - self._drag_point.y()
        self._drag_point = point
        self._actions.put(("平移" if self._panning else "旋转", float(dx), float(dy)))
        self._wake.set()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_point = None

    def mouseDoubleClickEvent(self, _event: QMouseEvent) -> None:
        self._actions.put(("适配",))
        self._wake.set()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._actions.put(("缩放", float(event.angleDelta().y())))
        self._wake.set()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_F, Qt.Key.Key_R):
            self._actions.put(("适配",))
            self._wake.set()
            return
        super().keyPressEvent(event)

    # ---------- 后台线程：独占 MuJoCo 模型、MjData 与 Renderer ----------
    @staticmethod
    def _fit_camera(model, camera) -> None:
        center = getattr(model.stat, "center", (0.0, 0.0, 0.4))
        scale = max(0.2, float(getattr(model.stat, "extent", 1.0)))
        camera.lookat[:] = center
        camera.distance = max(0.5, scale * 2.35)
        camera.azimuth = 135.0
        camera.elevation = -24.0

    def _process_camera_actions(self, camera, model) -> bool:
        changed = False
        while True:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                break
            if action[0] == "旋转":
                camera.azimuth -= action[1] * 0.4
                camera.elevation = max(-89.0, min(89.0, camera.elevation - action[2] * 0.4))
            elif action[0] == "平移":
                ratio = max(0.0002, float(camera.distance) * 0.0015)
                camera.lookat[0] -= action[1] * ratio
                camera.lookat[2] += action[2] * ratio
            elif action[0] == "缩放":
                factor = 0.88 if action[1] > 0 else 1.14
                camera.distance = max(0.08, min(100.0, float(camera.distance) * factor))
            elif action[0] == "适配":
                self._fit_camera(model, camera)
            changed = True
        return changed

    @staticmethod
    def _add_line(scene, mujoco, np, start, end, color, width: float) -> None:
        if scene is None or scene.ngeom >= scene.maxgeom:
            return
        geometry = scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(
            geometry, int(mujoco.mjtGeom.mjGEOM_LINE),
            np.array([float(width), 0.0, 0.0], dtype=float),
            np.zeros(3, dtype=float), np.eye(3).reshape(9),
            np.asarray(color, dtype=np.float32))
        mujoco.mjv_connector(
            geometry, int(mujoco.mjtGeom.mjGEOM_LINE), float(width),
            np.asarray(start, dtype=float), np.asarray(end, dtype=float))
        geometry.category = int(mujoco.mjtCatBit.mjCAT_DECOR)
        scene.ngeom += 1

    def _draw_experiment_trajectory(self, scene, mujoco, np) -> None:
        """青色为既定末端轨迹，橙色为当前实验实际走过的轨迹。"""
        from trajectory_runtime import current_trajectory_visualization

        snapshot = current_trajectory_visualization()
        if not snapshot.experiment_key:
            return
        planned = snapshot.planned
        actual = snapshot.actual
        # 限制装饰几何数量；长实验只做显示降采样，不改变原始记录与指标。
        for points, color, width in (
                (planned, (0.10, 0.86, 1.00, 0.72), 5.0),
                (actual, (1.00, 0.46, 0.08, 1.00), 2.5)):
            if len(points) > 301:
                indices = np.linspace(0, len(points) - 1, 301).astype(int)
                points = points[indices]
            for start, end in zip(points[:-1], points[1:]):
                self._add_line(scene, mujoco, np, start, end, color, width)
        for points, color, radius in (
                (planned, (0.10, 0.86, 1.00, 1.0), 0.012),
                (actual, (1.00, 0.46, 0.08, 1.0), 0.015)):
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
        import mujoco
        import numpy as np
        import model_loader

        model = data = camera = options = renderer = None
        current_canvas = (0, 0)
        previous_snapshot = None
        frame_time: list[float] = []

        try:
            while not self._stop.is_set():
                woken = self._wake.wait(0.1)
                self._wake.clear()
                if self._stop.is_set():
                    break
                if not woken:
                    continue

                pending_model = self._pending_model
                if pending_model:
                    self._pending_model = ""
                    if renderer is not None:
                        renderer.close()
                        renderer = None
                    model = model_loader.load_model(mujoco, pending_model)
                    data = mujoco.MjData(model)
                    mujoco.mj_forward(model, data)
                    camera = mujoco.MjvCamera()
                    mujoco.mjv_defaultFreeCamera(model, camera)
                    self._fit_camera(model, camera)
                    options = mujoco.MjvOption()
                    mujoco.mjv_defaultOption(options)
                    current_canvas = (0, 0)
                    previous_snapshot = None
                    self._model_path = pending_model
                    self.ready = True
                    self.switching = False
                    self.error = ""
                    self.status_changed.emit(
                        f'3D 已加载：{os.path.basename(pending_model)}\n'
                        "左键拖动旋转 · Shift+拖动平移 · 滚轮缩放 · 双击/F 适配")

                if model is None:
                    continue

                canvas = self._pending_canvas
                size_changed = renderer is None or current_canvas != canvas
                if size_changed:
                    if renderer is not None:
                        renderer.close()
                    width, height = canvas
                    model.vis.global_.offwidth = max(int(model.vis.global_.offwidth), width)
                    model.vis.global_.offheight = max(int(model.vis.global_.offheight), height)
                    renderer = mujoco.Renderer(model, height=height, width=width)
                    current_canvas = canvas

                with self._latest_lock:
                    snapshot = self.latest_state
                has_new_state = snapshot is not None and snapshot is not previous_snapshot
                if has_new_state:
                    state = np.asarray(snapshot.state, dtype=np.float64)
                    signature = int(getattr(
                        snapshot, "state_sig", int(mujoco.mjtState.mjSTATE_INTEGRATION)))
                    desired = int(mujoco.mj_stateSize(model, signature))
                    if state.size == desired:
                        mujoco.mj_setState(model, data, state, signature)
                        mujoco.mj_forward(model, data)
                        self._statistics["状态同步"] += 1
                        previous_snapshot = snapshot

                camera_changed = self._process_camera_actions(camera, model)
                # 唤醒来自新状态、相机、尺寸或模型；每次只画最新状态，旧帧不排队。
                if not (has_new_state or camera_changed or size_changed
                        or self._statistics["渲染帧"] == 0):
                    continue
                # 仿真可以是 500 Hz，但显示器通常只有 60 Hz。这里只取最新状态，
                # 不为每个物理步都排一张图，避免 Qt 事件队列越积越多。
                if frame_time:
                    remaining = (1.0 / 60.0) - (time.perf_counter() - frame_time[-1])
                    if remaining > 0:
                        time.sleep(remaining)
                renderer.update_scene(data, camera=camera, scene_option=options)
                self._draw_experiment_trajectory(renderer.scene, mujoco, np)
                image = np.ascontiguousarray(renderer.render())
                height, width, _ = image.shape
                qimage = QImage(image.data, width, height, int(image.strides[0]), QImage.Format.Format_RGB888).copy()
                self._statistics["渲染帧"] += 1
                now = time.perf_counter()
                frame_time.append(now)
                del frame_time[:-60]
                if len(frame_time) > 1 and frame_time[-1] - frame_time[0] > 0.2:
                    self._statistics["fps"] = (len(frame_time) - 1) / (frame_time[-1] - frame_time[0])
                self.frame_ready.emit(qimage)
        except Exception as exc:  # 渲染失败要留在视口里显示，不能拖垮整个工作台。
            self.ready = False
            self.switching = False
            self.error = f'{type(exc).__name__}: {exc}'
            self._statistics["错误"] = self.error
            self.status_changed.emit(f'3D 视口失败：{self.error}')
        finally:
            if renderer is not None:
                try:
                    renderer.close()
                except Exception:
                    pass
