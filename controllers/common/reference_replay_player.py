"""Replay one processed UR10 reference trajectory in the native 3D viewport.

This is deliberately a **replay**, not a forward-control reproduction.  The
archived q/dq samples are written to ``data.qpos``/``data.qvel`` after the
physics step and ``mj_forward`` refreshes the kinematics used by the viewport.
The independent inverse-dynamics recompute is exposed separately by
``runtime/reference_replay.py``; it is not used to move the robot here.
"""
from __future__ import annotations

import os

import numpy as np

import plugin_system as studio
from plugin_system import ControlPlugin, step_handler
from simulation_control import SimulationControlCommand
from experiment_registry import experiment_registry
from reference_replay import JOINT_NAMES, load_trajectory, trajectory_indices


class ReferenceReplayPlayer(ControlPlugin):
    name = "UR10 参考轨迹回放"
    english_name = "UR10 reference trajectory replay"
    version = "1.0"
    author = "驭臂"
    description = "按处理后的实机参考 q/dq 回放 3D 运动，仅用于同步查看参考曲线；不代表正向控制复现。"
    takes_control = False
    # 参数面板显示为「参考轨迹」；0–9 对应 trajectory_N_identified_results.mat
    trajectory = 0.0

    def __init__(self) -> None:
        self._model = None
        self._data = None
        self._index = 0
        self._index_initialized = False
        self._reference = None
        self._qpos_addresses: tuple[int, ...] = ()
        self._dof_addresses: tuple[int, ...] = ()
        self._start_time: float | None = None
        self._last_time: float | None = None
        self._last_error = ""

    def check_model_compatibility(self, model) -> str:
        mj = studio.mujoco
        hinges = [int(index) for index in range(model.njnt)
                  if model.jnt_type[index] == mj.mjtJoint.mjJNT_HINGE]
        if len(hinges) != 6:
            return f"参考回放需要 6 个 hinge 关节，当前模型有 {len(hinges)} 个"
        return ""

    def receive_model(self, event) -> None:
        self._model = getattr(event, "model", None)
        self._data = getattr(event, "data", None)
        self._reference = None
        # Keep an already selected trajectory across receive_model: project
        # parameter restore calls set_parameter() before ModelEvent delivery.
        self._start_time = None
        self._last_time = None
        model = self._model
        if model is None:
            self._qpos_addresses = ()
            self._dof_addresses = ()
            return
        hinges = [int(index) for index in range(model.njnt)
                  if model.jnt_type[index] == studio.mujoco.mjtJoint.mjJNT_HINGE]
        self._qpos_addresses = tuple(int(model.jnt_qposadr[joint]) for joint in hinges)
        self._dof_addresses = tuple(int(model.jnt_dofadr[joint]) for joint in hinges)

    def _experiment_index(self) -> int | None:
        key = str(os.environ.get("YUBI_CURRENT_EXPERIMENT", "") or "").strip()
        if not key:
            return None
        try:
            experiment = experiment_registry.create(key)
        except Exception:                                               # noqa: BLE001
            return None
        if str(experiment.trajectory.get("type") or "") != "reference_playback":
            return None
        try:
            return int(experiment.trajectory.get("index", 0))
        except (TypeError, ValueError):
            return 0

    def _ensure_reference(self) -> None:
        if self._reference is not None:
            return
        if not self._index_initialized:
            from_experiment = self._experiment_index()
            if from_experiment is not None:
                self._index = from_experiment
            self._index_initialized = True
        index = self._index
        if index not in trajectory_indices():
            self._last_error = f"参考轨迹 {index} 不存在"
            return
        try:
            self._reference = load_trajectory(index, include_recompute=False)
            self._index = index
            self._last_error = ""
        except Exception as exc:                                        # noqa: BLE001
            self._last_error = f"{type(exc).__name__}: {exc}"

    def _apply(self, elapsed_s: float) -> None:
        if self._reference is None or self._model is None or self._data is None:
            return
        q, dq = self._reference.interpolate_state(elapsed_s)
        data = self._data
        for column, address in enumerate(self._qpos_addresses):
            data.qpos[address] = q[column]
        for column, address in enumerate(self._dof_addresses):
            data.qvel[address] = dq[column]
        # The model has position-servo actuators; keep their target on the
        # replayed state so the physics step does not fight the replay.
        if int(data.ctrl.size) == len(q):
            data.ctrl[:] = q
        data.qfrc_applied[:] = 0.0
        studio.mujoco.mj_forward(self._model, data)

    @step_handler
    def on_simulation_command(self, command: SimulationControlCommand) -> bool:
        action = str(getattr(command, "action", "") or "")
        if action in ("run", "运行"):
            self._ensure_reference()
            self._start_time = float(getattr(self._data, "time", 0.0))
            self._last_time = self._start_time
            self._apply(0.0)
        elif action in ("reset", "复位"):
            self._start_time = None
            self._last_time = None
            if self._reference is None:
                self._ensure_reference()
            self._apply(0.0)
        return False

    @step_handler
    def step(self, event: studio.messages.StepEvent) -> bool:
        self._model = event.model
        self._data = event.data
        self._ensure_reference()
        if self._reference is None:
            return False
        data_time = float(event.data.time)
        if self._start_time is None or (self._last_time is not None and data_time + 1e-12 < self._last_time):
            self._start_time = data_time
        self._last_time = data_time
        elapsed = max(0.0, data_time - float(self._start_time))
        self._apply(elapsed)
        return False

    def adjustable_parameters(self) -> dict:
        indices = trajectory_indices()
        low = float(min(indices)) if indices else 0.0
        high = float(max(indices)) if indices else 0.0
        return {
            "trajectory": {
                "value": float(self._index),
                "range": (low, high),
                "step": 1.0,
                "unit": "index",
                "label": "参考轨迹",
            },
        }

    def set_parameter(self, name: str, value: float) -> str:
        if name != "trajectory":
            return super().set_parameter(name, value)
        index = int(round(float(value)))
        if index not in trajectory_indices():
            return f"参考轨迹 {index} 不存在"
        self._index = index
        self._index_initialized = True
        self._reference = None
        self._start_time = None
        self._last_time = None
        self._ensure_reference()
        self._apply(0.0)
        return self._last_error

    def status(self) -> dict:
        if self._reference is None:
            return {"参考轨迹": "未加载", "来源": "处理后的参考数据"}
        duration = self._reference.duration_s
        elapsed = 0.0
        if self._start_time is not None and self._data is not None:
            elapsed = max(0.0, float(self._data.time) - self._start_time)
        return {
            "参考轨迹": self._index,
            "回放": f"{min(elapsed, duration):.2f}/{duration:.2f} s",
            "来源": "处理后的参考数据（非原始 RTDE）",
        }


plugin_class = ReferenceReplayPlayer
