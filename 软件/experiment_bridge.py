"""Connect registered experiments to the shared simulation controls and GUI state."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace
import time
from typing import Callable

from official_api import messages
from experiment_registry import Experiment, experiment_registry
from experiment_results import ExperimentResultRecorder
from simulation_control import SimulationControlCommand


@dataclasses.dataclass(frozen=True)
class ExperimentCommand(messages.Snapshot):
    """Request loading an experiment by its registry key.

    The field names remain part of the existing frontend contract.  They can be
    migrated only together with the contract and React client.
    """

    动作: str = "加载"
    实验: str = ""


@dataclasses.dataclass(frozen=True)
class ExperimentState(messages.Snapshot):
    """Latest experiment state published to the workbench."""

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


# The Web bridge currently routes messages by Python class name.  Preserve the
# existing wire names while exposing English source-level class names.
ExperimentCommand.__name__ = "实验命令"
ExperimentCommand.__qualname__ = "实验命令"
ExperimentState.__name__ = "实验状态"
ExperimentState.__qualname__ = "实验状态"

# Explicit wire aliases keep the current contract stable while the Python source
# uses English class names.  Contract validation reads this mapping as data.
WIRE_CLASS_ALIASES = {
    "ExperimentCommand": "实验命令",
    "ExperimentState": "实验状态",
}
实验命令 = ExperimentCommand
实验状态 = ExperimentState


class ExperimentRunner:
    """Attach an :class:`Experiment` to Run/Pause/Reset and result export.

    This class contains no robot-specific or controller-specific logic.  Model,
    project and trajectory selection stay in the experiment definition and the
    callbacks supplied by the simulation runtime.
    """

    name = "实验运行器"
    version = "1.0"
    takes_control = False

    # Plugin metadata is still read by the existing plugin runtime using these
    # legacy attribute names.  Keep them until that metadata contract migrates.
    名称 = name
    版本 = version
    接管控制 = takes_control

    def __init__(
        self,
        send,
        load_experiment: Callable[[str], tuple[Experiment | None, str]],
        pause: Callable[[], None],
        reset_target: Callable[[Experiment], None],
        initial_experiment: Experiment | None = None,
        clear_observations: Callable[[], None] | None = None,
    ) -> None:
        self._send = send
        self._load_experiment = load_experiment
        self._pause = pause
        self._reset_target = reset_target
        self._clear_observations = clear_observations
        self._experiment = initial_experiment
        self._model = None
        self._data = None
        self._recorder: ExperimentResultRecorder | None = None
        self._start_simulation_time = 0.0
        self._status = "已加载" if initial_experiment is not None else "未选择"
        self._description = (
            "点击开始运行实验" if initial_experiment is not None else "请先选择并加载实验"
        )
        self._result_directory = ""
        self._next_publish_wall_time = 0.0
        self._available = self._read_available()

    @staticmethod
    def _read_available() -> list[dict]:
        items: list[dict] = []
        for key in experiment_registry.keys():
            try:
                experiment = experiment_registry.create(key)
                items.append({
                    "注册名": experiment.key,
                    "名称": experiment.name,
                    "模型": experiment.model,
                    "项目": experiment.project,
                    "控制器": list(experiment.controllers),
                    "停止秒": experiment.duration,
                    "说明": experiment.description,
                })
            except Exception as exc:                                  # noqa: BLE001
                items.append({"注册名": key, "名称": key, "错误": str(exc)})
        return items

    def receive_model(self, event) -> None:
        self._model = getattr(event, "model", None)
        self._data = getattr(event, "data", None)

    @messages.handler
    def on_experiment_command(self, command: ExperimentCommand) -> bool:
        action = str(getattr(command, "动作", "加载") or "加载")
        name = str(getattr(command, "实验", "") or "").strip()
        if action not in ("加载", "load"):
            self._description = f"不支持的实验动作：{action}"
            self.publish(force=True)
            return False
        experiment, reason = self._load_experiment(name)
        if experiment is None:
            self._status = "加载失败"
            self._description = reason
            self.publish(force=True)
            return False
        self._experiment = experiment
        self._recorder = None
        self._start_simulation_time = float(getattr(self._data, "time", 0.0))
        self._status = "已加载"
        self._description = reason or "实验已加载，点击开始运行"
        self._result_directory = ""
        self.publish(force=True)
        return False

    @messages.handler
    def on_simulation_command(self, command: SimulationControlCommand) -> bool:
        if self._experiment is None:
            return False
        action = str(getattr(command, "动作", "暂停") or "暂停")
        if action in ("运行", "run"):
            if self._status == "完成":
                self._description = "实验已完成；请先复位或重新加载再运行"
                self._pause()
                self.publish(force=True)
                return False
            if self._recorder is None:
                self._recorder = ExperimentResultRecorder(
                    self._experiment,
                    float(self._experiment.recording.get("frequency_hz", 100.0)),
                )
                self._start_simulation_time = float(getattr(self._data, "time", 0.0))
                self._record_current_state()
            self._status = "运行中"
            self._description = "正在自动记录；达到停止时间后自动暂停并导出"
        elif action in ("暂停", "pause") and self._status == "运行中":
            self._status = "已暂停"
            self._description = "记录保留；再次开始将继续本次实验"
        elif action in ("复位", "reset"):
            if self._clear_observations is not None:
                self._clear_observations()
            self._recorder = None
            self._result_directory = ""
            self._start_simulation_time = float(getattr(self._data, "time", 0.0))
            self._reset_target(self._experiment)
            self._status = "已加载"
            self._description = "实验已复位，点击开始重新运行"
        self.publish(force=True)
        return False

    @messages.handler
    def on_step(self, event: messages.StepEvent) -> bool:
        self._model, self._data = event.model, event.data
        if self._experiment is None or self._recorder is None or self._status != "运行中":
            self.publish()
            return False
        self._record_current_state()
        elapsed = max(0.0, float(event.data.time) - self._start_simulation_time)
        if elapsed + 1e-12 >= self._experiment.duration:
            self._pause()
            try:
                output = self._recorder.export()
                self._result_directory = str(output)
                self._status = "完成"
                self._description = "已自动暂停并导出 CSV、指标和曲线"
                print(f"【实验】✓ {self._experiment.key} 完成 → {output}", flush=True)
            except Exception as exc:                                  # noqa: BLE001
                self._status = "导出失败"
                self._description = f"{type(exc).__name__}: {exc}"
                print(f"⚠ 【实验】结果导出失败：{self._description}", flush=True)
            self.publish(force=True)
        else:
            self.publish()
        return False

    def _record_current_state(self) -> None:
        if self._recorder is None or self._data is None:
            return
        try:
            from trajectory_runtime import current_reference
            target_qpos, target_qvel = current_reference(self._data)
        except Exception:                                             # noqa: BLE001
            target_qpos, target_qvel = None, None
        joint_names = []
        ctrlrange = []
        if self._model is not None:
            ctrlrange = self._model.actuator_ctrlrange
            try:
                from official_api import mujoco
                joint_names = [
                    str(mujoco.mj_id2name(
                        self._model, mujoco.mjtObj.mjOBJ_JOINT, index)
                        or f"joint_{index}")
                    for index in range(int(self._model.njnt))
                ]
            except Exception:                                         # noqa: BLE001
                joint_names = []
        self._recorder.observe(SimpleNamespace(
            time=float(self._data.time),
            qpos=self._data.qpos,
            qvel=self._data.qvel,
            ctrl=self._data.ctrl,
            target_qpos=target_qpos,
            target_qvel=target_qvel,
            ctrlrange=ctrlrange,
            joint_names=joint_names,
        ))

    def publish(self, force: bool = False) -> None:
        now = time.perf_counter()
        if not force and now < self._next_publish_wall_time:
            return
        self._next_publish_wall_time = now + 0.2
        experiment = self._experiment
        elapsed = 0.0
        if experiment is not None and self._recorder is not None:
            elapsed = max(
                0.0,
                float(getattr(self._data, "time", 0.0)) - self._start_simulation_time,
            )
        self._send(ExperimentState(
            当前=experiment.key if experiment else "",
            名称=experiment.name if experiment else "",
            状态=self._status,
            可选=self._available,
            模型=experiment.model if experiment else "",
            项目=experiment.project if experiment else "",
            控制器=list(experiment.controllers) if experiment else [],
            停止秒=experiment.duration if experiment else 0.0,
            已运行秒=elapsed,
            结果目录=self._result_directory,
            说明=self._description,
        ))


__all__ = [
    "ExperimentCommand", "ExperimentState", "ExperimentRunner",
    "实验命令", "实验状态", "WIRE_CLASS_ALIASES",
]
