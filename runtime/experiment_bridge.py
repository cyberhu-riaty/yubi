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

    action: str = "load"
    experiment: str = ""


@dataclasses.dataclass(frozen=True)
class ExperimentState(messages.Snapshot):
    """Latest experiment state published to the workbench."""

    current: str = ""
    name: str = ""
    status: str = "not_selected"
    available: list = dataclasses.field(default_factory=list)
    model: str = ""
    project: str = ""
    controllers: list = dataclasses.field(default_factory=list)
    duration_s: float = 0.0
    elapsed_s: float = 0.0
    result_directory: str = ""
    description: str = ""


class ExperimentRunner:
    """Attach an :class:`Experiment` to Run/Pause/Reset and result export.

    This class contains no robot-specific or controller-specific logic.  Model,
    project and trajectory selection stay in the experiment definition and the
    callbacks supplied by the simulation runtime.
    """

    name = "实验运行器"
    version = "1.0"
    takes_control = False


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
        self._status = "loaded" if initial_experiment is not None else "not_selected"
        self._description = (
            "点击开始运行实验" if initial_experiment is not None else "请先选择并加载实验"
        )
        self._result_directory = ""
        self._next_publish_wall_time = 0.0
        self._available = self._read_available()
        self._tracking_revision = 0

    def tracking_context(self):
        """Read-only identity and time origin for the independent display stream."""
        return (self._experiment, self._tracking_revision,
                self._start_simulation_time, self._status)

    @staticmethod
    def _read_available() -> list[dict]:
        items: list[dict] = []
        for key in experiment_registry.keys():
            try:
                experiment = experiment_registry.create(key)
                items.append({
                    "key": experiment.key,
                    "name": experiment.name,
                    "model": experiment.model,
                    "project": experiment.project,
                    "controllers": list(experiment.controllers),
                    "duration_s": experiment.duration,
                    "description": experiment.description,
                })
            except Exception as exc:                                  # noqa: BLE001
                items.append({"key": key, "name": key, "error": str(exc)})
        return items

    def receive_model(self, event) -> None:
        new_model = getattr(event, "model", None)
        if new_model is not self._model:
            self._tracking_revision += 1
            self._recorder = None
            self._start_simulation_time = float(getattr(getattr(event, "data", None), "time", 0.0))
            # A model lifecycle event has no file path. Any replacement of an
            # existing model invalidates its experiment. Loading an experiment
            # explicitly selects the new definition after model assembly.
            if self._model is not None:
                self._experiment = None
                self._status = "not_selected"
                self._description = "模型已切换；请重新加载实验"
        self._model = getattr(event, "model", None)
        self._data = getattr(event, "data", None)

    @messages.handler
    def on_experiment_command(self, command: ExperimentCommand) -> bool:
        action = str(getattr(command, "action", "load") or "load")
        name = str(getattr(command, "experiment", "") or "").strip()
        if action != "load":
            self._description = f"不支持的实验动作：{action}"
            self.publish(force=True)
            return False
        experiment, reason = self._load_experiment(name)
        if experiment is None:
            self._status = "load_failed"
            self._description = reason
            self.publish(force=True)
            return False
        self._experiment = experiment
        self._tracking_revision += 1
        self._recorder = None
        self._start_simulation_time = float(getattr(self._data, "time", 0.0))
        self._status = "loaded"
        self._description = reason or "实验已加载，点击开始运行"
        self._result_directory = ""
        self.publish(force=True)
        return False

    @messages.handler
    def on_simulation_command(self, command: SimulationControlCommand) -> bool:
        if self._experiment is None:
            return False
        action = str(getattr(command, "action", "pause") or "pause")
        if action in ("运行", "run"):
            if self._status == "completed":
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
            self._status = "running"
            self._description = "正在自动记录；达到停止时间后自动暂停并导出"
        elif action in ("暂停", "pause") and self._status == "running":
            self._status = "paused"
            self._description = "记录保留；再次开始将继续本次实验"
        elif action in ("复位", "reset"):
            self._tracking_revision += 1
            if self._clear_observations is not None:
                self._clear_observations()
            self._recorder = None
            self._result_directory = ""
            self._start_simulation_time = float(getattr(self._data, "time", 0.0))
            self._reset_target(self._experiment)
            self._status = "loaded"
            self._description = "实验已复位，点击开始重新运行"
        self.publish(force=True)
        return False

    @messages.handler
    def on_step(self, event: messages.StepEvent) -> bool:
        self._model, self._data = event.model, event.data
        if self._experiment is None or self._recorder is None or self._status != "running":
            self.publish()
            return False
        self._record_current_state()
        elapsed = max(0.0, float(event.data.time) - self._start_simulation_time)
        if elapsed + 1e-12 >= self._experiment.duration:
            self._pause()
            try:
                output = self._recorder.export()
                self._result_directory = str(output)
                self._status = "completed"
                self._description = "已自动暂停并导出 CSV、指标和曲线"
                print(f"【实验】✓ {self._experiment.key} 完成 → {output}", flush=True)
            except Exception as exc:                                  # noqa: BLE001
                self._status = "export_failed"
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
            current=experiment.key if experiment else "",
            name=experiment.name if experiment else "",
            status=self._status,
            available=self._available,
            model=experiment.model if experiment else "",
            project=experiment.project if experiment else "",
            controllers=list(experiment.controllers) if experiment else [],
            duration_s=experiment.duration if experiment else 0.0,
            elapsed_s=elapsed,
            result_directory=self._result_directory,
            description=self._description,
        ))


__all__ = ["ExperimentCommand", "ExperimentState", "ExperimentRunner"]
