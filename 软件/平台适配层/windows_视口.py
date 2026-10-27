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


class MuJoCo视口(QWidget):
    """把 MuJoCo 离屏渲染结果显示在 Qt 控件中。"""

    帧就绪 = Signal(object)
    状态改变 = Signal(str)

    def __init__(self, 模型路径: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(360, 280)
        self.setMouseTracking(True)

        self.最新状态: Any = None
        self.就绪 = False
        self.切换中 = True
        self.错误 = ""
        self._模型路径 = ""
        self._画面: QImage | None = None
        self._拖拽点 = None
        self._平移中 = False

        self._停止 = threading.Event()
        self._唤醒 = threading.Event()
        self._操作: queue.SimpleQueue[tuple] = queue.SimpleQueue()
        self._待换模型 = str(模型路径)
        self._待画布 = (960, 640)
        self._最新锁 = threading.Lock()
        self._统计 = {
            "渲染帧": 0,
            "显示帧": 0,
            "状态同步": 0,
            "fps": 0.0,
            "错误": "",
        }

        self.帧就绪.connect(self._接收帧)
        self.状态改变.connect(self._接收状态)

        # 调整分栏时分两拍更新：拖动中约 20 Hz 跟手，停止 180 ms 后再提交最终尺寸。
        # 旧实现只等“安静 180 ms”才更新，所以分割线在动、3D 画面却像卡住了。
        self._尺寸计时器 = QTimer(self)
        self._尺寸计时器.setSingleShot(True)
        self._尺寸计时器.setInterval(50)
        self._尺寸计时器.timeout.connect(self._提交画布尺寸)
        self._尺寸最终计时器 = QTimer(self)
        self._尺寸最终计时器.setSingleShot(True)
        self._尺寸最终计时器.setInterval(180)
        self._尺寸最终计时器.timeout.connect(self._提交画布尺寸)

        self._线程 = threading.Thread(
            target=self._渲染循环, daemon=True, name="Windows-3D渲染线程")
        self._线程.start()

    # ---------- 仿真线程 / 宿主窗口调用的最小接口 ----------
    def 收_状态(self, 快照: Any) -> None:
        """仿真线程调用：只替换最新快照，不触碰 Qt 和 MuJoCo 对象。"""
        with self._最新锁:
            self.最新状态 = 快照
        self._唤醒.set()

    def 换_模型(self, 模型路径: str) -> bool:
        if not 模型路径 or not os.path.isfile(模型路径):
            self.错误 = f"模型文件不存在：{模型路径}"
            self._统计["错误"] = self.错误
            return False
        self.切换中 = True
        self._待换模型 = str(模型路径)
        with self._最新锁:
            self.最新状态 = None
        self._唤醒.set()
        return True

    def 关闭(self) -> None:
        self._停止.set()
        self._唤醒.set()
        if self._线程.is_alive():
            self._线程.join(timeout=3.0)

    @Slot()
    def 适配视角(self) -> None:
        """供 3D 顶栏按钮调用；与双击视口、F/R 键使用同一套相机逻辑。"""
        self._操作.put(("适配",))
        self._唤醒.set()

    def 统计(self) -> dict:
        return dict(self._统计)

    # ---------- Qt 主线程：显示与输入 ----------
    @Slot(object)
    def _接收帧(self, 图像: QImage) -> None:
        self._画面 = 图像
        self._统计["显示帧"] += 1
        self.update()

    @Slot(str)
    def _接收状态(self, 文字: str) -> None:
        self.setToolTip(文字)
        self.update()

    def paintEvent(self, _事件) -> None:
        画笔 = QPainter(self)
        画笔.fillRect(self.rect(), QColor(10, 18, 30))
        if self._画面 is not None:
            目标 = self._画面.size().scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x = (self.width() - 目标.width()) // 2
            y = (self.height() - 目标.height()) // 2
            画笔.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            画笔.drawImage(x, y, self._画面.scaled(
                目标, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            画笔.setPen(QColor(190, 203, 220))
            文字 = f"3D 视口加载失败\n{self.错误}" if self.错误 else "正在加载 MuJoCo 3D 视口…"
            画笔.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 文字)

    def resizeEvent(self, 事件) -> None:
        super().resizeEvent(事件)
        # 先立刻重绘：用已有图像填充新矩形，拖动分割线时不会留下静止旧画面。
        self.update()
        if not self._尺寸计时器.isActive():
            self._尺寸计时器.start()
        self._尺寸最终计时器.start()

    def _提交画布尺寸(self) -> None:
        比例 = max(1.0, float(self.devicePixelRatioF()))
        宽, 高 = max(320, int(self.width() * 比例)), max(240, int(self.height() * 比例))
        # 极大窗口按面积等比缩小，避免无意义地渲染数百万以上像素。
        面积上限 = 2_500_000
        if 宽 * 高 > 面积上限:
            缩放 = (面积上限 / (宽 * 高)) ** 0.5
            宽, 高 = int(宽 * 缩放), int(高 * 缩放)
        self._待画布 = (宽, 高)
        self._唤醒.set()

    def mousePressEvent(self, 事件: QMouseEvent) -> None:
        if 事件.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._拖拽点 = 事件.position()
            self._平移中 = bool(事件.modifiers() & Qt.KeyboardModifier.ShiftModifier)

    def mouseMoveEvent(self, 事件: QMouseEvent) -> None:
        if self._拖拽点 is None or not (事件.buttons() & Qt.MouseButton.LeftButton):
            return
        点 = 事件.position()
        dx, dy = 点.x() - self._拖拽点.x(), 点.y() - self._拖拽点.y()
        self._拖拽点 = 点
        self._操作.put(("平移" if self._平移中 else "旋转", float(dx), float(dy)))
        self._唤醒.set()

    def mouseReleaseEvent(self, 事件: QMouseEvent) -> None:
        if 事件.button() == Qt.MouseButton.LeftButton:
            self._拖拽点 = None

    def mouseDoubleClickEvent(self, _事件: QMouseEvent) -> None:
        self._操作.put(("适配",))
        self._唤醒.set()

    def wheelEvent(self, 事件: QWheelEvent) -> None:
        self._操作.put(("缩放", float(事件.angleDelta().y())))
        self._唤醒.set()
        事件.accept()

    def keyPressEvent(self, 事件: QKeyEvent) -> None:
        if 事件.key() in (Qt.Key.Key_F, Qt.Key.Key_R):
            self._操作.put(("适配",))
            self._唤醒.set()
            return
        super().keyPressEvent(事件)

    # ---------- 后台线程：独占 MuJoCo 模型、MjData 与 Renderer ----------
    @staticmethod
    def _适配相机(模型, 相机) -> None:
        中心 = getattr(模型.stat, "center", (0.0, 0.0, 0.4))
        尺度 = max(0.2, float(getattr(模型.stat, "extent", 1.0)))
        相机.lookat[:] = 中心
        相机.distance = max(0.5, 尺度 * 2.35)
        相机.azimuth = 135.0
        相机.elevation = -24.0

    def _处理相机操作(self, 相机, 模型) -> bool:
        改了 = False
        while True:
            try:
                操作 = self._操作.get_nowait()
            except queue.Empty:
                break
            if 操作[0] == "旋转":
                相机.azimuth -= 操作[1] * 0.4
                相机.elevation = max(-89.0, min(89.0, 相机.elevation - 操作[2] * 0.4))
            elif 操作[0] == "平移":
                比例 = max(0.0002, float(相机.distance) * 0.0015)
                相机.lookat[0] -= 操作[1] * 比例
                相机.lookat[2] += 操作[2] * 比例
            elif 操作[0] == "缩放":
                倍率 = 0.88 if 操作[1] > 0 else 1.14
                相机.distance = max(0.08, min(100.0, float(相机.distance) * 倍率))
            elif 操作[0] == "适配":
                self._适配相机(模型, 相机)
            改了 = True
        return 改了

    def _渲染循环(self) -> None:
        import mujoco
        import numpy as np
        import 模型加载

        模型 = 数据 = 相机 = 选项 = 渲染器 = None
        当前画布 = (0, 0)
        上次快照 = None
        帧时刻: list[float] = []

        try:
            while not self._停止.is_set():
                被唤醒 = self._唤醒.wait(0.1)
                self._唤醒.clear()
                if self._停止.is_set():
                    break
                if not 被唤醒:
                    continue

                待换 = self._待换模型
                if 待换:
                    self._待换模型 = ""
                    if 渲染器 is not None:
                        渲染器.close()
                        渲染器 = None
                    模型 = 模型加载.加载模型(mujoco, 待换)
                    数据 = mujoco.MjData(模型)
                    mujoco.mj_forward(模型, 数据)
                    相机 = mujoco.MjvCamera()
                    mujoco.mjv_defaultFreeCamera(模型, 相机)
                    self._适配相机(模型, 相机)
                    选项 = mujoco.MjvOption()
                    mujoco.mjv_defaultOption(选项)
                    当前画布 = (0, 0)
                    上次快照 = None
                    self._模型路径 = 待换
                    self.就绪 = True
                    self.切换中 = False
                    self.错误 = ""
                    self.状态改变.emit(
                        f"3D 已加载：{os.path.basename(待换)}\n"
                        "左键拖动旋转 · Shift+拖动平移 · 滚轮缩放 · 双击/F 适配")

                if 模型 is None:
                    continue

                画布 = self._待画布
                尺寸改了 = 渲染器 is None or 当前画布 != 画布
                if 尺寸改了:
                    if 渲染器 is not None:
                        渲染器.close()
                    宽, 高 = 画布
                    模型.vis.global_.offwidth = max(int(模型.vis.global_.offwidth), 宽)
                    模型.vis.global_.offheight = max(int(模型.vis.global_.offheight), 高)
                    渲染器 = mujoco.Renderer(模型, height=高, width=宽)
                    当前画布 = 画布

                with self._最新锁:
                    快照 = self.最新状态
                有新状态 = 快照 is not None and 快照 is not 上次快照
                if 有新状态:
                    状态 = np.asarray(快照.state, dtype=np.float64)
                    签名 = int(getattr(
                        快照, "state_sig", int(mujoco.mjtState.mjSTATE_INTEGRATION)))
                    期望 = int(mujoco.mj_stateSize(模型, 签名))
                    if 状态.size == 期望:
                        mujoco.mj_setState(模型, 数据, 状态, 签名)
                        mujoco.mj_forward(模型, 数据)
                        self._统计["状态同步"] += 1
                        上次快照 = 快照

                相机改了 = self._处理相机操作(相机, 模型)
                # 唤醒来自新状态、相机、尺寸或模型；每次只画最新状态，旧帧不排队。
                if not (有新状态 or 相机改了 or 尺寸改了
                        or self._统计["渲染帧"] == 0):
                    continue
                # 仿真可以是 500 Hz，但显示器通常只有 60 Hz。这里只取最新状态，
                # 不为每个物理步都排一张图，避免 Qt 事件队列越积越多。
                if 帧时刻:
                    剩余 = (1.0 / 60.0) - (time.perf_counter() - 帧时刻[-1])
                    if 剩余 > 0:
                        time.sleep(剩余)
                渲染器.update_scene(数据, camera=相机, scene_option=选项)
                图 = np.ascontiguousarray(渲染器.render())
                高, 宽, _ = 图.shape
                q图 = QImage(图.data, 宽, 高, int(图.strides[0]), QImage.Format.Format_RGB888).copy()
                self._统计["渲染帧"] += 1
                现在 = time.perf_counter()
                帧时刻.append(现在)
                del 帧时刻[:-60]
                if len(帧时刻) > 1 and 帧时刻[-1] - 帧时刻[0] > 0.2:
                    self._统计["fps"] = (len(帧时刻) - 1) / (帧时刻[-1] - 帧时刻[0])
                self.帧就绪.emit(q图)
        except Exception as 异常:  # 渲染失败要留在视口里显示，不能拖垮整个工作台。
            self.就绪 = False
            self.切换中 = False
            self.错误 = f"{type(异常).__name__}: {异常}"
            self._统计["错误"] = self.错误
            self.状态改变.emit(f"3D 视口失败：{self.错误}")
        finally:
            if 渲染器 is not None:
                try:
                    渲染器.close()
                except Exception:
                    pass
