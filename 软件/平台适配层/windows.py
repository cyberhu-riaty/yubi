"""Windows 平台宿主：PySide6 主窗口 + Qt WebEngine + MuJoCo 3D。"""
from __future__ import annotations

import os
from typing import Any

from .契约 import 平台能力


class Windows(平台能力):
    """React 工作台与原生 MuJoCo 视口组成同一个 Windows 桌面窗口。"""

    名称 = "Windows（PySide6 + Qt WebEngine + MuJoCo 3D）"

    def __init__(self) -> None:
        self._应用: Any = None
        self._窗口: Any = None
        self._网页: Any = None
        self._视口: Any = None
        self._视口模型标签: Any = None
        self._视口状态标签: Any = None
        self._分隔: Any = None
        self._右分隔: Any = None
        self._运行信息: Any = None
        self._分隔保存计时器: Any = None
        self._允许保存分栏 = False
        self._模型计时器: Any = None
        self._视口槽: dict | None = None
        self._统计数据 = {
            "页面加载完成": False,
            "页面加载成功": False,
            "3D已接入": False,
        }

    def 可用(self) -> tuple[bool, str]:
        try:
            import mujoco  # noqa: F401
            from PySide6.QtWidgets import QApplication  # noqa: F401
            from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        except (ImportError, OSError) as 异常:
            return False, (
                f"缺 MuJoCo / PySide6 / Qt WebEngine（{type(异常).__name__}: {异常}）。\n"
                f"      建议使用仓库环境：.\\.venv\\Scripts\\python.exe "
                f"-m pip install -r requirements.lock")
        return True, ""

    def 起(self, *, 地址: str, 标题: str, 宽: float, 高: float,
           命令队列: Any = None, 无3D: bool = False,
           视口槽: dict | None = None) -> int:
        可用, 原因 = self.可用()
        if not 可用:
            raise SystemExit(f"✗ 起不了窗口：{原因}")

        from PySide6.QtCore import QCoreApplication, QTimer, Qt, QUrl
        from PySide6.QtWidgets import (
            QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow,
            QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
        )
        from PySide6.QtWebEngineWidgets import QWebEngineView

        应用 = QApplication.instance()
        if 应用 is None:
            # Qt WebEngine 内部会使用图形上下文；共享属性必须在 QApplication
            # 创建前设置，否则部分显卡环境下网页区可能出现黑屏。
            QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
            应用 = QApplication([])
        应用.setApplicationName(标题)

        窗口 = QMainWindow()
        窗口.setWindowTitle(标题)
        窗口.resize(max(640, int(宽)), max(480, int(高)))

        网页 = QWebEngineView(窗口)
        网页.setMinimumWidth(480)
        网页.loadFinished.connect(self._页面加载结束)
        网页.setUrl(QUrl(地址))

        if 无3D:
            窗口.setCentralWidget(网页)
            窗口.statusBar().showMessage("Windows 桌面宿主 · 无 3D 模式")
            if 视口槽 is not None:
                视口槽["视口"] = None
        else:
            from .windows_视口 import MuJoCo视口
            from .windows_运行信息 import 运行信息面板

            模型路径 = os.environ.get("驭臂_当前模型", "")
            视口 = MuJoCo视口(模型路径, 窗口)

            # 3D 不再裸贴窗口边缘：外壳负责留白、边框和一条短工具栏，
            # 具体渲染仍完全由 MuJoCo视口 负责。
            三维外壳 = QWidget(窗口)
            三维外壳.setObjectName("threeDPanel")
            三维外壳.setMinimumWidth(380)
            三维外壳.setMinimumHeight(320)
            三维布局 = QVBoxLayout(三维外壳)
            三维布局.setContentsMargins(10, 10, 10, 10)
            三维布局.setSpacing(7)

            三维顶栏 = QFrame(三维外壳)
            三维顶栏.setObjectName("threeDHeader")
            顶栏布局 = QHBoxLayout(三维顶栏)
            顶栏布局.setContentsMargins(10, 5, 7, 5)
            顶栏布局.setSpacing(8)
            三维标题 = QLabel("3D 视口", 三维顶栏)
            三维标题.setObjectName("threeDTitle")
            模型标签 = QLabel(self._模型显示名(模型路径), 三维顶栏)
            模型标签.setObjectName("threeDModel")
            模型标签.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            状态标签 = QLabel("正在加载…", 三维顶栏)
            状态标签.setObjectName("threeDStatus")
            状态标签.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            状态标签.setToolTip("MuJoCo 3D 视口状态")
            适配按钮 = QPushButton("适配视角", 三维顶栏)
            适配按钮.setObjectName("threeDButton")
            适配按钮.setToolTip("让相机重新对准并完整显示当前模型（F / R / 双击视口）")
            适配按钮.clicked.connect(视口.适配视角)
            顶栏布局.addWidget(三维标题)
            顶栏布局.addWidget(模型标签)
            顶栏布局.addWidget(状态标签)
            顶栏布局.addWidget(适配按钮)

            视口边框 = QFrame(三维外壳)
            视口边框.setObjectName("threeDFrame")
            视口布局 = QVBoxLayout(视口边框)
            视口布局.setContentsMargins(1, 1, 1, 1)
            视口布局.addWidget(视口)
            三维布局.addWidget(三维顶栏)
            三维布局.addWidget(视口边框, 1)

            # 渲染线程可能很快发出“已加载”；先挂引用再连信号，避免首条状态丢失。
            self._视口模型标签 = 模型标签
            self._视口状态标签 = 状态标签

            三维外壳.setStyleSheet("""
                QWidget#threeDPanel { background: #f1f3f5; }
                QFrame#threeDHeader {
                    background: #ffffff;
                    border: 1px solid #d9dfe6;
                    border-radius: 6px;
                }
                QLabel#threeDTitle { color: #1b1f24; font-weight: 600; }
                QLabel#threeDModel { color: #5f6b7a; }
                QLabel#threeDStatus { color: #7a8594; }
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
            视口.状态改变.connect(self._更新三维状态)

            # 右列改为上下结构：3D 在上，状态/输入/诊断在下。
            # 运行信息面板只读视口收到的快照，不接触控制器和仿真线程 MjData。
            运行信息 = 运行信息面板(视口, 窗口)
            右分隔 = QSplitter(Qt.Orientation.Vertical, 窗口)
            右分隔.setObjectName("rightColumnSplitter")
            右分隔.setChildrenCollapsible(False)
            右分隔.setOpaqueResize(True)
            右分隔.setHandleWidth(6)
            右分隔.setStyleSheet("""
                QSplitter::handle { background: #d9dfe6; }
                QSplitter::handle:hover, QSplitter::handle:pressed { background: #2f6feb; }
            """)
            右分隔.addWidget(三维外壳)
            右分隔.addWidget(运行信息)
            右分隔.setStretchFactor(0, 70)
            右分隔.setStretchFactor(1, 30)
            右目标分栏 = self._读取右分栏(int(高))
            右分隔.setSizes(右目标分栏)

            分隔 = QSplitter(Qt.Orientation.Horizontal, 窗口)
            分隔.setChildrenCollapsible(False)
            分隔.setOpaqueResize(True)
            分隔.setHandleWidth(6)
            分隔.setStyleSheet("""
                QSplitter::handle { background: #d9dfe6; }
                QSplitter::handle:hover, QSplitter::handle:pressed { background: #2f6feb; }
            """)
            分隔.addWidget(网页)
            分隔.addWidget(右分隔)
            分隔.setStretchFactor(0, 40)
            分隔.setStretchFactor(1, 60)
            目标分栏 = self._读取分栏(int(宽))
            分隔.setSizes(目标分栏)
            窗口.setCentralWidget(分隔)
            # Web 页面自己已有完整状态栏；桌面宿主的第二条状态栏只会显得重复。
            窗口.statusBar().hide()

            self._视口 = 视口
            self._分隔 = 分隔
            self._右分隔 = 右分隔
            self._运行信息 = 运行信息
            self._视口槽 = 视口槽
            self._统计数据["3D已接入"] = True
            if 视口槽 is not None:
                # GUI ← 仿真的唯一 3D 状态通道：入口随后会把 StateSnapshot
                # 交给 `视口.收_状态()`，不会共享仿真线程的 MjData。
                视口槽["视口"] = 视口

            # 模型切换事件由仿真线程只写入槽；Qt 主线程定时取走并通知视口。
            模型计时器 = QTimer(窗口)
            模型计时器.setInterval(150)
            模型计时器.timeout.connect(self._检查模型切换)
            模型计时器.start()
            self._模型计时器 = 模型计时器

            分隔保存计时器 = QTimer(窗口)
            分隔保存计时器.setSingleShot(True)
            分隔保存计时器.setInterval(350)
            分隔保存计时器.timeout.connect(self._保存分栏)
            分隔.splitterMoved.connect(lambda *_: 分隔保存计时器.start())
            右分隔.splitterMoved.connect(lambda *_: 分隔保存计时器.start())
            self._分隔保存计时器 = 分隔保存计时器
            # QSplitter 在窗口 show 之前还不知道最终可用宽度；显示后再应用一次比例。
            # 600 ms 之前不存盘，避免 Qt 的首次自动布局被误认成“用户拖动”。
            QTimer.singleShot(0, lambda 尺寸=目标分栏: 分隔.setSizes(尺寸))
            QTimer.singleShot(0, lambda 尺寸=右目标分栏: 右分隔.setSizes(尺寸))
            QTimer.singleShot(600, self._启用分栏保存)
            应用.aboutToQuit.connect(视口.关闭)

        self._应用 = 应用
        self._窗口 = 窗口
        self._网页 = 网页
        self._统计数据["地址"] = 地址
        self._统计数据["无3D"] = bool(无3D)

        窗口.show()
        return int(应用.exec())

    def _页面加载结束(self, 成功: bool) -> None:
        self._统计数据["页面加载完成"] = True
        self._统计数据["页面加载成功"] = bool(成功)
        if self._窗口 is not None:
            if not 成功:
                self._窗口.statusBar().show()
                self._窗口.statusBar().showMessage("React 工作台加载失败，请检查本地 Web 服务")
            elif self._视口 is None:
                self._窗口.statusBar().showMessage("React 工作台已加载 · 无 3D 模式")
            elif self._视口.就绪:
                self._窗口.statusBar().showMessage("React 工作台与 MuJoCo 3D 已就绪")

    def _检查模型切换(self) -> None:
        if self._视口 is None or self._视口槽 is None:
            return
        路径 = self._视口槽.get("待换模型")
        if not 路径:
            return
        self._视口槽["待换模型"] = None
        try:
            同一个 = os.path.normcase(os.path.abspath(str(路径))) == os.path.normcase(
                os.path.abspath(str(self._视口._模型路径)))
        except Exception:
            同一个 = str(路径) == str(self._视口._模型路径)
        if not 同一个:
            self._视口.换_模型(str(路径))
            if self._视口模型标签 is not None:
                self._视口模型标签.setText(self._模型显示名(str(路径)))

    @staticmethod
    def _模型显示名(路径: str) -> str:
        if not 路径:
            return "等待模型"
        try:
            import 模型桥
            return str(模型桥.显示名(路径) or os.path.basename(路径))
        except Exception:
            return os.path.basename(路径)

    def _更新三维状态(self, 文字: str) -> None:
        if self._视口状态标签 is None:
            return
        文 = str(文字 or "")
        self._视口状态标签.setToolTip(文)
        # 顶栏只放一句短状态；完整操作提示仍可从悬浮提示和帮助页查看。
        self._视口状态标签.setText(文.split("\n", 1)[0][:36])

    @staticmethod
    def _读取分栏(总宽: int) -> list[int]:
        可用默认 = max(960, int(总宽) - 6)
        左默认 = max(480, min(可用默认 - 480, int(可用默认 * 0.40)))
        默认 = [左默认, 可用默认 - 左默认]
        try:
            import 模型桥
            # 新布局的右列包含上下两块，使用新键，避免旧的 55:45 比例覆盖新版默认值。
            值 = 模型桥.读取设置("Windows主分栏V2", None)
            if (isinstance(值, list) and len(值) == 2
                    and all(isinstance(x, (int, float)) and x > 0 for x in 值)):
                合计 = float(值[0]) + float(值[1])
                if 合计 > 0:
                    可用 = max(960, int(总宽) - 6)
                    左 = max(480, min(可用 - 480, int(可用 * float(值[0]) / 合计)))
                    return [左, 可用 - 左]
        except Exception:
            pass
        return 默认

    @staticmethod
    def _读取右分栏(总高: int) -> list[int]:
        可用默认 = max(490, int(总高) - 6)
        上默认 = max(320, min(可用默认 - 170, int(可用默认 * 0.70)))
        默认 = [上默认, 可用默认 - 上默认]
        try:
            import 模型桥
            值 = 模型桥.读取设置("Windows右列分栏", None)
            if (isinstance(值, list) and len(值) == 2
                    and all(isinstance(x, (int, float)) and x > 0 for x in 值)):
                合计 = float(值[0]) + float(值[1])
                if 合计 > 0:
                    可用 = max(490, int(总高) - 6)
                    上 = max(320, min(可用 - 170, int(可用 * float(值[0]) / 合计)))
                    return [上, 可用 - 上]
        except Exception:
            pass
        return 默认

    def _保存分栏(self) -> None:
        if self._分隔 is None or not self._允许保存分栏:
            return
        try:
            import 模型桥
            模型桥.写入设置("Windows主分栏V2", [int(x) for x in self._分隔.sizes()])
            if self._右分隔 is not None:
                模型桥.写入设置(
                    "Windows右列分栏", [int(x) for x in self._右分隔.sizes()])
        except Exception as 异常:
            print(f"⚠ 保存 Windows 分栏失败：{type(异常).__name__}: {异常}", flush=True)

    def _启用分栏保存(self) -> None:
        self._允许保存分栏 = True

    def 视口矩形(self) -> tuple[int, int, int, int] | None:
        if self._视口 is None or self._窗口 is None:
            return None
        from PySide6.QtCore import QPoint
        起点 = self._视口.mapTo(self._窗口, QPoint(0, 0))
        return (起点.x(), 起点.y(), self._视口.width(), self._视口.height())

    def 统计(self) -> dict:
        结果 = dict(self._统计数据)
        if self._视口 is not None:
            结果["3D"] = self._视口.统计()
        return 结果
