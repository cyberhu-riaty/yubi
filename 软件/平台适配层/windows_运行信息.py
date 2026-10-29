"""Windows 右下角的运行信息面板。

它只读取 3D 视口已经收到的状态快照，不接触仿真线程里的 MjData，
因此布局变化不会影响控制器、轨迹规划或物理步进。
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView, QFormLayout, QHeaderView, QLabel, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)


class 运行信息面板(QWidget):
    """显示状态、qpos/qvel/ctrl 和 3D 渲染诊断。"""

    def __init__(self, 视口: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._视口 = 视口
        self._上次诊断 = ""
        self.setObjectName("runtimePanel")
        self.setMinimumHeight(170)

        布局 = QVBoxLayout(self)
        布局.setContentsMargins(10, 8, 10, 10)
        布局.setSpacing(6)

        标题 = QLabel("运行信息", self)
        标题.setObjectName("runtimeTitle")
        布局.addWidget(标题)

        页签 = QTabWidget(self)
        页签.setObjectName("runtimeTabs")
        页签.setDocumentMode(True)
        布局.addWidget(页签, 1)

        状态页 = QWidget(页签)
        状态表 = QFormLayout(状态页)
        状态表.setContentsMargins(10, 8, 10, 8)
        状态表.setHorizontalSpacing(18)
        状态表.setVerticalSpacing(7)
        self._时间 = QLabel("0.000 s", 状态页)
        self._模型 = QLabel("等待模型", 状态页)
        self._同步 = QLabel("等待状态", 状态页)
        self._帧率 = QLabel("0.0 fps", 状态页)
        状态表.addRow("仿真时间", self._时间)
        状态表.addRow("当前模型", self._模型)
        状态表.addRow("状态同步", self._同步)
        状态表.addRow("3D帧率", self._帧率)
        页签.addTab(状态页, "状态")

        self._输入表 = QTableWidget(0, 4, 页签)
        self._输入表.setHorizontalHeaderLabels(("索引", "qpos", "qvel", "ctrl"))
        self._输入表.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._输入表.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._输入表.setAlternatingRowColors(True)
        self._输入表.verticalHeader().setVisible(False)
        self._输入表.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for 列 in range(1, 4):
            self._输入表.horizontalHeader().setSectionResizeMode(列, QHeaderView.ResizeMode.Stretch)
        self._输入表.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        页签.addTab(self._输入表, "输入")

        self._诊断 = QPlainTextEdit(页签)
        self._诊断.setReadOnly(True)
        self._诊断.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._诊断.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        页签.addTab(self._诊断, "3D诊断")

        self.setStyleSheet("""
            QWidget#runtimePanel { background: #f1f3f5; }
            QLabel#runtimeTitle { color: #1b1f24; font-weight: 600; }
            QTabWidget::pane { background: #ffffff; border: 1px solid #d9dfe6; }
            QTabBar::tab { padding: 5px 12px; color: #5f6b7a; }
            QTabBar::tab:selected { color: #1f6feb; font-weight: 600; }
            QTableWidget, QPlainTextEdit { background: #ffffff; border: 0; }
        """)

        计时器 = QTimer(self)
        计时器.setInterval(120)
        计时器.timeout.connect(self._刷新)
        计时器.start()
        self._计时器 = 计时器
        self._刷新()

    @staticmethod
    def _数值们(值: Any) -> list[float]:
        if 值 is None:
            return []
        try:
            return [float(x) for x in 值]
        except (TypeError, ValueError):
            return []

    def _设置单元格(self, 行: int, 列: int, 文本: str) -> None:
        """更新已有单元格；只有单元格不存在时才交给 QTableWidget 接管。"""
        项 = self._输入表.item(行, 列)
        if 项 is None:
            self._输入表.setItem(行, 列, QTableWidgetItem(文本))
        else:
            项.setText(文本)

    def _写输入表(
        self,
        qpos: list[float],
        qvel: list[float],
        ctrl: list[float],
        等待状态: bool,
    ) -> None:
        行数 = max(len(qpos), len(qvel), len(ctrl))
        if 行数 == 0:
            self._输入表.setRowCount(1)
            提示 = "等待新模型状态…" if 等待状态 else "当前模型无关节"
            文本们 = ("—", 提示, "—", "—")
            for 列, 文本 in enumerate(文本们):
                self._设置单元格(0, 列, 文本)
            return
        self._输入表.setRowCount(行数)
        for 行 in range(行数):
            值们 = (
                str(行),
                f"{qpos[行]: .6f}" if 行 < len(qpos) else "—",
                f"{qvel[行]: .6f}" if 行 < len(qvel) else "—",
                f"{ctrl[行]: .6f}" if 行 < len(ctrl) else "—",
            )
            for 列, 文本 in enumerate(值们):
                self._设置单元格(行, 列, 文本)

    def _刷新(self) -> None:
        信息 = self._视口.运行信息()
        统计 = self._视口.统计()
        self._时间.setText(
            "—" if 信息.get("仿真时间") is None else f"{float(信息['仿真时间']):.3f} s")
        self._模型.setText(str(信息.get("模型") or "等待模型"))
        self._同步.setText(f"{int(统计.get('状态同步', 0))} 次")
        self._帧率.setText(f"{float(统计.get('fps', 0.0)):.1f} fps")

        self._写输入表(
            self._数值们(信息.get("qpos")),
            self._数值们(信息.get("qvel")),
            self._数值们(信息.get("ctrl")),
            等待状态=信息.get("仿真时间") is None,
        )

        错误 = str(统计.get("错误") or "")
        诊断 = "\n".join((
            f"3D状态       : {'就绪' if self._视口.就绪 else '未就绪'}",
            f"模型         : {信息.get('模型') or '—'}",
            f"渲染帧       : {int(统计.get('渲染帧', 0))}",
            f"显示帧       : {int(统计.get('显示帧', 0))}",
            f"状态同步次数 : {int(统计.get('状态同步', 0))}",
            f"当前帧率     : {float(统计.get('fps', 0.0)):.1f} fps",
            f"错误         : {错误 or '无'}",
            "",
            "完整系统诊断请使用左侧“诊断”页面。",
        ))
        if 诊断 != self._上次诊断:
            self._上次诊断 = 诊断
            self._诊断.setPlainText(诊断)
