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


class RuntimeInfoPanel(QWidget):
    """显示状态、qpos/qvel/ctrl 和 3D 渲染诊断。"""

    def __init__(self, viewport: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._viewport = viewport
        self._last_diagnostic = ""
        self.setObjectName("runtimePanel")
        self.setMinimumHeight(170)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        title = QLabel("运行信息", self)
        title.setObjectName("runtimeTitle")
        layout.addWidget(title)

        tabs = QTabWidget(self)
        tabs.setObjectName("runtimeTabs")
        tabs.setDocumentMode(True)
        layout.addWidget(tabs, 1)

        state_page = QWidget(tabs)
        state_form = QFormLayout(state_page)
        state_form.setContentsMargins(10, 8, 10, 8)
        state_form.setHorizontalSpacing(18)
        state_form.setVerticalSpacing(7)
        self._time_label = QLabel("0.000 s", state_page)
        self._model_label = QLabel("等待模型", state_page)
        self._sync_label = QLabel("等待状态", state_page)
        self._fps_label = QLabel("0.0 fps", state_page)
        state_form.addRow("仿真时间", self._time_label)
        state_form.addRow("当前模型", self._model_label)
        state_form.addRow("状态同步", self._sync_label)
        state_form.addRow("3D帧率", self._fps_label)
        tabs.addTab(state_page, "状态")

        self._input_table = QTableWidget(0, 4, tabs)
        self._input_table.setHorizontalHeaderLabels(("索引", "qpos", "qvel", "ctrl"))
        self._input_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._input_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._input_table.setAlternatingRowColors(True)
        self._input_table.verticalHeader().setVisible(False)
        self._input_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(1, 4):
            self._input_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self._input_table.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        tabs.addTab(self._input_table, "输入")

        self._diagnostic = QPlainTextEdit(tabs)
        self._diagnostic.setReadOnly(True)
        self._diagnostic.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._diagnostic.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        tabs.addTab(self._diagnostic, "3D诊断")

        self.setStyleSheet("""
            QWidget#runtimePanel { background: #f1f3f5; }
            QLabel#runtimeTitle { color: #1b1f24; font-weight: 600; }
            QTabWidget::pane { background: #ffffff; border: 1px solid #d9dfe6; }
            QTabBar::tab { padding: 5px 12px; color: #5f6b7a; }
            QTabBar::tab:selected { color: #1f6feb; font-weight: 600; }
            QTableWidget, QPlainTextEdit { background: #ffffff; border: 0; }
        """)

        timer = QTimer(self)
        timer.setInterval(120)
        timer.timeout.connect(self._refresh)
        timer.start()
        self._timer = timer
        self._refresh()

    @staticmethod
    def _numeric_values(value: Any) -> list[float]:
        if value is None:
            return []
        try:
            return [float(x) for x in value]
        except (TypeError, ValueError):
            return []

    def _set_cell(self, row: int, column: int, text: str) -> None:
        """更新已有单元格；只有单元格不存在时才交给 QTableWidget 接管。"""
        item = self._input_table.item(row, column)
        if item is None:
            self._input_table.setItem(row, column, QTableWidgetItem(text))
        else:
            item.setText(text)

    def _write_input_table(
        self,
        qpos: list[float],
        qvel: list[float],
        ctrl: list[float],
        waiting_for_state: bool,
    ) -> None:
        row_count = max(len(qpos), len(qvel), len(ctrl))
        if row_count == 0:
            self._input_table.setRowCount(1)
            hint = "等待新模型状态…" if waiting_for_state else "当前模型无关节"
            texts = ("—", hint, "—", "—")
            for column, text in enumerate(texts):
                self._set_cell(0, column, text)
            return
        self._input_table.setRowCount(row_count)
        for row in range(row_count):
            values = (
                str(row),
                f'{qpos[row]: .6f}' if row < len(qpos) else "—",
                f'{qvel[row]: .6f}' if row < len(qvel) else "—",
                f'{ctrl[row]: .6f}' if row < len(ctrl) else "—",
            )
            for column, text in enumerate(values):
                self._set_cell(row, column, text)

    def _refresh(self) -> None:
        info = self._viewport.runtime_info()
        statistics = self._viewport.statistics()
        self._time_label.setText(
            "—" if info.get('simulation_time') is None else f"{float(info['simulation_time']):.3f} s")
        self._model_label.setText(str(info.get('model') or "等待模型"))
        self._sync_label.setText(f"{int(statistics.get('state_syncs', 0))} 次")
        self._fps_label.setText(f"{float(statistics.get('fps', 0.0)):.1f} fps")

        self._write_input_table(
            self._numeric_values(info.get("qpos")),
            self._numeric_values(info.get("qvel")),
            self._numeric_values(info.get("ctrl")),
            waiting_for_state=info.get('simulation_time') is None,
        )

        error = str(statistics.get('error') or "")
        diagnostic = "\n".join((
            f"3D状态       : {('就绪' if self._viewport.ready else '未就绪')}",
            f"模型         : {info.get('model') or '—'}",
            f"渲染帧       : {int(statistics.get('rendered_frames', 0))}",
            f"显示帧       : {int(statistics.get('displayed_frames', 0))}",
            f"状态同步次数 : {int(statistics.get('state_syncs', 0))}",
            f"当前帧率     : {float(statistics.get('fps', 0.0)):.1f} fps",
            f"错误         : {error or '无'}",
            "",
            "完整系统诊断请使用左侧“诊断”页面。",
        ))
        if diagnostic != self._last_diagnostic:
            self._last_diagnostic = diagnostic
            self._diagnostic.setPlainText(diagnostic)
