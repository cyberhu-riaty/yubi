"""实验选择、运行状态和自动结果导出的 GUI 接缝。"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace
import time
from typing import Callable

from 官方层 import messages
from experiment_registry import Experiment, experiment_registry
from experiment_results import ExperimentResultRecorder
from 重力桥 import 仿真控制命令


@dataclasses.dataclass(frozen=True)
class 实验命令(messages.Snapshot):
    动作: str = "加载"
    实验: str = ""


@dataclasses.dataclass(frozen=True)
class 实验状态(messages.Snapshot):
    当前: str = ""
    名称: str = ""
    状态: str = "未选择"
    可选: list = dataclasses.field(default_factory=list)
    模型: str = ""
    项目: str = ""
    控制器: list = dataclasses.field(default_factory=list)
    停止秒: float = 0.0
    已运行秒: float = 0.0
    结果目录: str = ""
    说明: str = ""


class 实验应用器:
    """把实验注册表接到现有 Run/Pause/Reset，不包含任何具体机器人逻辑。"""

    名称 = "实验运行器"
    版本 = "1.0"
    接管控制 = False

    def __init__(
        self,
        发送函数,
        加载回调: Callable[[str], tuple[Experiment | None, str]],
        暂停回调: Callable[[], None],
        重置目标回调: Callable[[Experiment], None],
        初始实验: Experiment | None = None,
    ) -> None:
        self._发 = 发送函数
        self._加载 = 加载回调
        self._暂停 = 暂停回调
        self._重置目标 = 重置目标回调
        self._实验 = 初始实验
        self._model = None
        self._data = None
        self._记录器: ExperimentResultRecorder | None = None
        self._起始仿真时刻 = 0.0
        self._状态 = "已加载" if 初始实验 is not None else "未选择"
        self._说明 = "点击开始运行实验" if 初始实验 is not None else "请先选择并加载实验"
        self._结果目录 = ""
        self._下次发布墙钟 = 0.0
        self._可选 = self._读取可选()

    @staticmethod
    def _读取可选() -> list[dict]:
        items: list[dict] = []
        for key in experiment_registry.keys():
            try:
                exp = experiment_registry.create(key)
                items.append({
                    "注册名": exp.key,
                    "名称": exp.name,
                    "模型": exp.model,
                    "项目": exp.project,
                    "控制器": list(exp.controllers),
                    "停止秒": exp.duration,
                    "说明": exp.description,
                })
            except Exception as exc:                                  # noqa: BLE001
                items.append({"注册名": key, "名称": key, "错误": str(exc)})
        return items

    def 收到模型(self, event) -> None:
        self._model = getattr(event, "model", None)
        self._data = getattr(event, "data", None)

    @messages.handler
    def 收实验命令(self, command: 实验命令) -> bool:
        action = str(getattr(command, "动作", "加载") or "加载")
        name = str(getattr(command, "实验", "") or "").strip()
        if action not in ("加载", "load"):
            self._说明 = f"不支持的实验动作：{action}"
            self.发布(强制=True)
            return False
        experiment, reason = self._加载(name)
        if experiment is None:
            self._状态 = "加载失败"
            self._说明 = reason
            self.发布(强制=True)
            return False
        self._实验 = experiment
        self._记录器 = None
        self._起始仿真时刻 = float(getattr(self._data, "time", 0.0))
        self._状态 = "已加载"
        self._说明 = reason or "实验已加载，点击开始运行"
        self._结果目录 = ""
        self.发布(强制=True)
        return False

    @messages.handler
    def 收仿真命令(self, command: 仿真控制命令) -> bool:
        if self._实验 is None:
            return False
        action = str(getattr(command, "动作", "暂停") or "暂停")
        if action in ("运行", "run"):
            if self._状态 == "完成":
                self._说明 = "实验已完成；请先复位或重新加载再运行"
                self._暂停()
                self.发布(强制=True)
                return False
            if self._记录器 is None:
                self._记录器 = ExperimentResultRecorder(
                    self._实验, float(self._实验.recording.get("frequency_hz", 100.0)))
                self._起始仿真时刻 = float(getattr(self._data, "time", 0.0))
                self._记录当前状态()
            self._状态 = "运行中"
            self._说明 = "正在自动记录；达到停止时间后自动暂停并导出"
        elif action in ("暂停", "pause") and self._状态 == "运行中":
            self._状态 = "已暂停"
            self._说明 = "记录保留；再次开始将继续本次实验"
        elif action in ("复位", "reset"):
            self._记录器 = None
            self._结果目录 = ""
            self._起始仿真时刻 = float(getattr(self._data, "time", 0.0))
            self._重置目标(self._实验)
            self._状态 = "已加载"
            self._说明 = "实验已复位，点击开始重新运行"
        self.发布(强制=True)
        return False

    @messages.handler
    def 每步记录(self, event: messages.StepEvent) -> bool:
        self._model, self._data = event.model, event.data
        if self._实验 is None or self._记录器 is None or self._状态 != "运行中":
            self.发布()
            return False
        self._记录当前状态()
        elapsed = max(0.0, float(event.data.time) - self._起始仿真时刻)
        if elapsed + 1e-12 >= self._实验.duration:
            self._暂停()
            try:
                output = self._记录器.export()
                self._结果目录 = str(output)
                self._状态 = "完成"
                self._说明 = "已自动暂停并导出 CSV、指标和曲线"
                print(f"【实验】✓ {self._实验.key} 完成 → {output}", flush=True)
            except Exception as exc:                                  # noqa: BLE001
                self._状态 = "导出失败"
                self._说明 = f"{type(exc).__name__}: {exc}"
                print(f"⚠ 【实验】结果导出失败：{self._说明}", flush=True)
            self.发布(强制=True)
        else:
            self.发布()
        return False

    def _记录当前状态(self) -> None:
        if self._记录器 is None or self._data is None:
            return
        self._记录器.observe(SimpleNamespace(
            time=float(self._data.time),
            qpos=self._data.qpos,
            qvel=self._data.qvel,
            ctrl=self._data.ctrl,
        ))

    def 发布(self, 强制: bool = False) -> None:
        now = time.perf_counter()
        if not 强制 and now < self._下次发布墙钟:
            return
        self._下次发布墙钟 = now + 0.2
        exp = self._实验
        elapsed = 0.0
        if exp is not None and self._记录器 is not None:
            elapsed = max(0.0, float(getattr(self._data, "time", 0.0)) - self._起始仿真时刻)
        self._发(实验状态(
            当前=exp.key if exp else "",
            名称=exp.name if exp else "",
            状态=self._状态,
            可选=self._可选,
            模型=exp.model if exp else "",
            项目=exp.project if exp else "",
            控制器=list(exp.controllers) if exp else [],
            停止秒=exp.duration if exp else 0.0,
            已运行秒=elapsed,
            结果目录=self._结果目录,
            说明=self._说明,
        ))

