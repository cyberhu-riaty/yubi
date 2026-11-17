"""Windows 平台宿主：PySide6 主窗口 + Qt WebEngine + MuJoCo 3D。"""
from __future__ import annotations

import os
import env_config
from typing import Any

from .interface import PlatformCapabilities


class Windows(PlatformCapabilities):
    """React 工作台与原生 MuJoCo 视口组成同一个 Windows 桌面窗口。"""

    name = "Windows（PySide6 + Qt WebEngine + MuJoCo 3D）"

    def __init__(self) -> None:
        self._application: Any = None
        self._window: Any = None
        self._web_view: Any = None
        self._viewport: Any = None
        self._viewport_model_label: Any = None
        self._viewport_status_label: Any = None
        self._splitter: Any = None
        self._right_splitter: Any = None
        self._runtime_info: Any = None
        self._splitter_save_timer: Any = None
        self._splitter_save_enabled = False
        self._model_timer: Any = None
        self._viewport_slot: dict | None = None
        self._statistics = {
            'page_load_finished': False,
            'page_load_succeeded': False,
            'viewport_attached': False,
        }

    def is_available(self) -> tuple[bool, str]:
        try:
            import mujoco  # noqa: F401
            from PySide6.QtWidgets import QApplication  # noqa: F401
            from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        except (ImportError, OSError) as exc:
            return False, (
                f'缺 MuJoCo / PySide6 / Qt WebEngine（{type(exc).__name__}: {exc}）。\n'
                f"      建议使用仓库环境：.\\.venv\\Scripts\\python.exe "
                f"-m pip install -r requirements.lock")
        return True, ""

    def run(self, *, url: str, title: str, width: float, height: float,
           command_queue: Any = None, no_3d: bool = False,
           viewport_slot: dict | None = None) -> int:
        is_available, reason = self.is_available()
        if not is_available:
            raise SystemExit(f'✗ 起不了窗口：{reason}')

        from PySide6.QtCore import QCoreApplication, QTimer, Qt, QUrl
        from PySide6.QtWidgets import (
            QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
            QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
        )
        from PySide6.QtWebEngineWidgets import QWebEngineView

        application = QApplication.instance()
        if application is None:
            # Qt WebEngine 内部会使用图形上下文；共享属性必须在 QApplication
            # 创建前设置，否则部分显卡环境下网页区可能出现黑屏。
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
            application = QApplication([])
        application.setApplicationName(title)

        window = QMainWindow()
        window.setWindowTitle(title)
        window.resize(max(640, int(width)), max(480, int(height)))

        web_view = QWebEngineView(window)
        web_view.setMinimumWidth(480)
        web_view.loadFinished.connect(self._page_load_finished)
        web_view.setUrl(QUrl(url))

        if no_3d:
            window.setCentralWidget(web_view)
            window.statusBar().showMessage("Windows 桌面宿主 · 无 3D 模式")
            if viewport_slot is not None:
                viewport_slot['viewport'] = None
        else:
            from .windows_viewport import MuJoCoViewport
            from .windows_runtime_info import RuntimeInfoPanel

            model_path = env_config.read("YUBI_CURRENT_MODEL")
            viewport = MuJoCoViewport(model_path, window)

            # 3D 不再裸贴窗口边缘：外壳负责留白、边框和一条短工具栏，
            # 具体渲染仍完全由 MuJoCo视口 负责。
            viewport_shell = QWidget(window)
            viewport_shell.setObjectName("threeDPanel")
            viewport_shell.setMinimumWidth(380)
            viewport_shell.setMinimumHeight(320)
            viewport_shell_layout = QVBoxLayout(viewport_shell)
            viewport_shell_layout.setContentsMargins(10, 10, 10, 10)
            viewport_shell_layout.setSpacing(7)

            viewport_header = QFrame(viewport_shell)
            viewport_header.setObjectName("threeDHeader")
            header_layout = QHBoxLayout(viewport_header)
            header_layout.setContentsMargins(10, 5, 7, 5)
            header_layout.setSpacing(8)
            viewport_title = QLabel("3D 视口", viewport_header)
            viewport_title.setObjectName("threeDTitle")
            model_label = QLabel(self._model_display_name(model_path), viewport_header)
            model_label.setObjectName("threeDModel")
            model_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            status_label = QLabel("正在加载…", viewport_header)
            status_label.setObjectName("threeDStatus")
            status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            status_label.setToolTip("MuJoCo 3D 视口状态")
            trajectory_legend = QLabel(
                '<span style="color:#16c7df">●</span> 目标 '
                '<span style="color:#ff7514">●</span> 实际', viewport_header)
            trajectory_legend.setObjectName("trajectoryLegend")
            trajectory_legend.setToolTip("多航点实验运行时：青色为既定末端路径，橙色为实际走过的路径")
            fit_button = QPushButton("适配视角", viewport_header)
            fit_button.setObjectName("threeDButton")
            fit_button.setToolTip("让相机重新对准并完整显示当前模型（F / R / 双击视口）")
            fit_button.clicked.connect(viewport.fit_camera)
            header_layout.addWidget(viewport_title)
            header_layout.addWidget(model_label)
            header_layout.addWidget(status_label)
            header_layout.addWidget(trajectory_legend)
            header_layout.addWidget(fit_button)

            viewport_frame = QFrame(viewport_shell)
            viewport_frame.setObjectName("threeDFrame")
            viewport_layout = QVBoxLayout(viewport_frame)
            viewport_layout.setContentsMargins(1, 1, 1, 1)
            viewport_layout.addWidget(viewport)
            viewport_shell_layout.addWidget(viewport_header)
            viewport_shell_layout.addWidget(viewport_frame, 1)

            # 渲染线程可能很快发出“已加载”；先挂引用再连信号，避免首条状态丢失。
            self._viewport_model_label = model_label
            self._viewport_status_label = status_label

            viewport_shell.setStyleSheet("""
                QWidget#threeDPanel { background: #f1f3f5; }
                QFrame#threeDHeader {
                    background: #ffffff;
                    border: 1px solid #d9dfe6;
                    border-radius: 6px;
                }
                QLabel#threeDTitle { color: #1b1f24; font-weight: 600; }
                QLabel#threeDModel { color: #5f6b7a; }
                QLabel#threeDStatus { color: #7a8594; }
                QLabel#trajectoryLegend { color: #168fa8; font-size: 11px; }
                QPushButton#threeDButton {
                    color: #1b1f24;
                    background: #f6f7f9;
                    border: 1px solid #d9dfe6;
                    border-radius: 4px;
                    padding: 4px 9px;
                }
                QPushButton#threeDButton:hover { background: #e9edf2; border-color: #b9c3cf; }
                QPushButton#threeDButton:pressed { background: #dfe5ec; }
                QFrame#threeDFrame { background: #0a121e; border: 1px solid #cfd7e1; border-radius: 6px; }
            """)

            # 接收方是 Qt 自己的 QObject；渲染线程发信号时，Qt 会自动排到
            # 主线程更新顶栏状态，避免后台线程直接操作窗口。
            viewport.status_changed.connect(self._update_viewport_status)

            # 右列改为上下结构：3D 在上，状态/输入/诊断在下。
            # 运行信息面板只读视口收到的快照，不接触控制器和仿真线程 MjData。
            runtime_info = RuntimeInfoPanel(viewport, window)
            right_splitter = QSplitter(Qt.Orientation.Vertical, window)
            right_splitter.setObjectName("rightColumnSplitter")
            right_splitter.setChildrenCollapsible(False)
            right_splitter.setOpaqueResize(True)
            right_splitter.setHandleWidth(6)
            right_splitter.setStyleSheet("""
                QSplitter::handle { background: #d9dfe6; }
                QSplitter::handle:hover, QSplitter::handle:pressed { background: #2f6feb; }
            """)
            right_splitter.addWidget(viewport_shell)
            right_splitter.addWidget(runtime_info)
            right_splitter.setStretchFactor(0, 70)
            right_splitter.setStretchFactor(1, 30)
            target_right_sizes = self._read_right_splitter(int(height))
            right_splitter.setSizes(target_right_sizes)

            splitter = QSplitter(Qt.Orientation.Horizontal, window)
            splitter.setChildrenCollapsible(False)
            splitter.setOpaqueResize(True)
            splitter.setHandleWidth(6)
            splitter.setStyleSheet("""
                QSplitter::handle { background: #d9dfe6; }
                QSplitter::handle:hover, QSplitter::handle:pressed { background: #2f6feb; }
            """)
            splitter.addWidget(web_view)
            splitter.addWidget(right_splitter)
            splitter.setStretchFactor(0, 40)
            splitter.setStretchFactor(1, 60)
            target_sizes = self._read_splitter(int(width))
            splitter.setSizes(target_sizes)
            window.setCentralWidget(splitter)
            # Web 页面自己已有完整状态栏；桌面宿主的第二条状态栏只会显得重复。
            window.statusBar().hide()

            self._viewport = viewport
            self._splitter = splitter
            self._right_splitter = right_splitter
            self._runtime_info = runtime_info
            self._viewport_slot = viewport_slot
            self._statistics['viewport_attached'] = True
            if viewport_slot is not None:
                # GUI ← 仿真的唯一 3D 状态通道：入口随后会把 StateSnapshot
                # 交给 `视口.收_状态()`，不会共享仿真线程的 MjData。
                viewport_slot['viewport'] = viewport

            # 模型切换事件由仿真线程只写入槽；Qt 主线程定时取走并通知视口。
            model_timer = QTimer(window)
            model_timer.setInterval(150)
            model_timer.timeout.connect(self._check_model_switch)
            model_timer.start()
            self._model_timer = model_timer

            splitter_save_timer = QTimer(window)
            splitter_save_timer.setSingleShot(True)
            splitter_save_timer.setInterval(350)
            splitter_save_timer.timeout.connect(self._save_splitters)
            splitter.splitterMoved.connect(lambda *_: splitter_save_timer.start())
            right_splitter.splitterMoved.connect(lambda *_: splitter_save_timer.start())
            self._splitter_save_timer = splitter_save_timer
            # QSplitter 在窗口 show 之前还不知道最终可用宽度；显示后再应用一次比例。
            # 600 ms 之前不存盘，避免 Qt 的首次自动布局被误认成“用户拖动”。
            QTimer.singleShot(0, lambda size=target_sizes: splitter.setSizes(size))
            QTimer.singleShot(0, lambda size=target_right_sizes: right_splitter.setSizes(size))
            QTimer.singleShot(600, self._enable_splitter_save)
            application.aboutToQuit.connect(viewport.close)

        self._application = application
        self._window = window
        self._web_view = web_view
        self._statistics['url'] = url
        self._statistics['no_3d'] = bool(no_3d)

        window.show()
        return int(application.exec())

    def _page_load_finished(self, success: bool) -> None:
        self._statistics['page_load_finished'] = True
        self._statistics['page_load_succeeded'] = bool(success)
        if self._window is not None:
            if not success:
                self._window.statusBar().show()
                self._window.statusBar().showMessage("React 工作台加载失败，请检查本地 Web 服务")
            elif self._viewport is None:
                self._window.statusBar().showMessage("React 工作台已加载 · 无 3D 模式")
            elif self._viewport.ready:
                self._window.statusBar().showMessage("React 工作台与 MuJoCo 3D 已就绪")

    def _check_model_switch(self) -> None:
        if self._viewport is None or self._viewport_slot is None:
            return
        path = self._viewport_slot.get('pending_model')
        if not path:
            return
        self._viewport_slot['pending_model'] = None
        try:
            same_model = os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(
                os.path.abspath(str(self._viewport._model_path)))
        except Exception:
            same_model = str(path) == str(self._viewport._model_path)
        if not same_model:
            self._viewport.switch_model(str(path))
            if self._viewport_model_label is not None:
                self._viewport_model_label.setText(self._model_display_name(str(path)))

    @staticmethod
    def _model_display_name(path: str) -> str:
        if not path:
            return "等待模型"
        try:
            import model_bridge
            return str(model_bridge.display_name(path) or os.path.basename(path))
        except Exception:
            return os.path.basename(path)

    def _update_viewport_status(self, text: str) -> None:
        if self._viewport_status_label is None:
            return
        status_text = str(text or "")
        self._viewport_status_label.setToolTip(status_text)
        # 顶栏只放一句短状态；完整操作提示仍可从悬浮提示和帮助页查看。
        self._viewport_status_label.setText(status_text.split("\n", 1)[0][:36])

    @staticmethod
    def _read_splitter(total_width: int) -> list[int]:
        default_available = max(960, int(total_width) - 6)
        default_left = max(480, min(default_available - 480, int(default_available * 0.40)))
        default = [default_left, default_available - default_left]
        try:
            import model_bridge
            # 新布局的右列包含上下两块，使用新键，避免旧的 55:45 比例覆盖新版默认值。
            value = model_bridge.read_setting("windows_split_v2", None)
            if (isinstance(value, list) and len(value) == 2
                    and all(isinstance(x, (int, float)) and x > 0 for x in value)):
                total = float(value[0]) + float(value[1])
                if total > 0:
                    is_available = max(960, int(total_width) - 6)
                    left = max(480, min(is_available - 480, int(is_available * float(value[0]) / total)))
                    return [left, is_available - left]
        except Exception:
            pass
        return default

    @staticmethod
    def _read_right_splitter(total_height: int) -> list[int]:
        default_available = max(490, int(total_height) - 6)
        default_upper = max(320, min(default_available - 170, int(default_available * 0.70)))
        default = [default_upper, default_available - default_upper]
        try:
            import model_bridge
            value = model_bridge.read_setting("windows_right_split", None)
            if (isinstance(value, list) and len(value) == 2
                    and all(isinstance(x, (int, float)) and x > 0 for x in value)):
                total = float(value[0]) + float(value[1])
                if total > 0:
                    is_available = max(490, int(total_height) - 6)
                    upper = max(320, min(is_available - 170, int(is_available * float(value[0]) / total)))
                    return [upper, is_available - upper]
        except Exception:
            pass
        return default

    def _save_splitters(self) -> None:
        if self._splitter is None or not self._splitter_save_enabled:
            return
        try:
            import model_bridge
            model_bridge.write_setting("windows_split_v2", [int(x) for x in self._splitter.sizes()])
            if self._right_splitter is not None:
                model_bridge.write_setting(
                    "windows_right_split", [int(x) for x in self._right_splitter.sizes()])
        except Exception as exc:
            print(f'⚠ 保存 Windows 分栏失败：{type(exc).__name__}: {exc}', flush=True)

    def _enable_splitter_save(self) -> None:
        self._splitter_save_enabled = True

    def viewport_rectangle(self) -> tuple[int, int, int, int] | None:
        if self._viewport is None or self._window is None:
            return None
        from PySide6.QtCore import QPoint
        origin = self._viewport.mapTo(self._window, QPoint(0, 0))
        return (origin.x(), origin.y(), self._viewport.width(), self._viewport.height())

    def statistics(self) -> dict:
        result = dict(self._statistics)
        if self._viewport is not None:
            result["viewport"] = self._viewport.statistics()
        return result
