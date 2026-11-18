"""Publish joint tracking samples in simulation time without touching the plant.

The transport keeps only the latest snapshot. Each message therefore repeats a
short numbered tail; the frontend deduplicates it and marks unrecoverable gaps.
Full experiment recording remains independent of this display stream.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import uuid

import mujoco
import numpy as np

from official_api import messages
from trajectory_runtime import current_reference, JointTrajectory


@dataclass(frozen=True)
class LiveTrackingState(messages.Snapshot):
    run_id: str = ""
    experiment_name: str = ""
    model_name: str = ""
    status: str = "idle"
    joint_names: list = field(default_factory=list)
    elapsed_s: float = 0.0
    duration_s: object = None
    compensation_state: str = "unavailable"
    samples: list = field(default_factory=list)
    description: str = ""


class LiveTrackingPublisher:
    """Read a coherent post-controller state, at most 25 times per wall second."""

    def __init__(self, send, frequency: float = 25.0) -> None:
        self._send = send
        self._period = 1.0 / max(frequency, 1.0)
        self._next_publish = 0.0
        self._signature = None
        self._run_id = ""
        self._tail: deque[dict] = deque(maxlen=100)
        self._last_sample_time: float | None = None
        self._sample_index = 0
        self._last_status = ""
        self._joint_names: list[str] = []
        self._qpos_indices: list[int] = []
        self._dof_indices: list[int] = []
        self._scratch = None

    def _new_run(self, model, signature) -> None:
        self._signature = signature
        self._run_id = uuid.uuid4().hex
        self._tail.clear()
        self._last_sample_time = None
        self._sample_index = 0
        self._next_publish = 0.0
        self._last_status = ""
        self._joint_names = []
        self._qpos_indices = []
        self._dof_indices = []
        # This panel reports rotational joints only. nq/nv/nu are not assumed
        # interchangeable (e.g. free bases, grippers, actuator transmissions).
        for joint in range(model.njnt):
            if model.jnt_type[joint] != mujoco.mjtJoint.mjJNT_HINGE:
                continue
            self._joint_names.append(
                mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
                or f"joint_{joint}")
            self._qpos_indices.append(int(model.jnt_qposadr[joint]))
            self._dof_indices.append(int(model.jnt_dofadr[joint]))
        self._scratch = mujoco.MjData(model)

    @staticmethod
    def _vector(values, indices) -> list[float | None]:
        if values is None:
            return [None] * len(indices)
        return [float(values[i]) if i < len(values) and math.isfinite(float(values[i]))
                else None for i in indices]

    def maybe_publish(self, model, data, runner, simulation, now: float) -> bool:
        experiment, revision, origin, runner_status = (
            runner.tracking_context() if runner is not None else (None, 0, 0.0, "idle"))
        signature = (id(model), int(simulation.reset_count), revision)
        if signature != self._signature:
            self._new_run(model, signature)
        status = {
            "not_selected": "idle", "loaded": "ready", "load_failed": "error",
            "export_failed": "error",
        }.get(runner_status, runner_status)
        if experiment is None:
            status = "idle" if status != "error" else status
        elif status == "running" and not simulation.running:
            status = "paused"
        changed = status != self._last_status
        if now < self._next_publish and not changed:
            return False
        self._next_publish = now + (self._period if status == "running" else 0.2)
        elapsed = max(0.0, float(data.time) - origin) if experiment is not None else 0.0
        if (experiment is not None and self._joint_names
                and (self._last_sample_time is None or elapsed > self._last_sample_time + 1e-10)):
            # Reference playback has no joint-waypoint reference at all; its
            # curves live in the dedicated reference endpoint.  Still publish
            # elapsed/status so the comparison panel gets a playback cursor.
            try:
                reference, _ = current_reference(data)
            except Exception:                                       # noqa: BLE001
                reference = None
            # While loaded/at t=0 a joint-waypoint plugin has not stepped yet.
            # The declared first waypoint is still a valid planned reference.
            if reference is None and status == "ready":
                try:
                    reference = JointTrajectory(experiment.trajectory).sample(0.0).qpos
                except Exception:                                   # noqa: BLE001
                    reference = None
            # mj_step leaves some derived forces at the preceding step. Evaluate
            # the current q/v/ctrl/activation together in a private data object.
            # This also handles position servos, gear ratios and force clamps;
            # raw data.ctrl is deliberately never presented as joint torque.
            mujoco.mj_copyData(self._scratch, model, data)
            mujoco.mj_forward(model, self._scratch)
            position = self._vector(data.qpos, self._qpos_indices)
            target = self._vector(reference, self._qpos_indices)
            self._sample_index += 1
            self._tail.append({
                "sample_index": self._sample_index,
                "elapsed_s": elapsed,
                "position_rad": position,
                "reference_rad": target,
                "velocity_rad_s": self._vector(data.qvel, self._dof_indices),
                "error_rad": [r - q if r is not None and q is not None else None
                              for r, q in zip(target, position)],
                "actuator_torque_nm": self._vector(
                    self._scratch.qfrc_actuator, self._dof_indices),
                "compensation_torque_nm": None,
            })
            self._last_sample_time = elapsed
        self._last_status = status
        self._send(LiveTrackingState(
            run_id=self._run_id,
            experiment_name=experiment.name if experiment else "",
            model_name=mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_MODEL, 0) or "",
            status=status,
            joint_names=list(self._joint_names),
            elapsed_s=elapsed,
            duration_s=float(experiment.duration) if experiment else None,
            # No controller in this first integration applies friction feedforward.
            # The calibrated model's passive damping/friction are not compensation.
            compensation_state="unavailable",
            samples=list(self._tail),
            description="simulation; torque evaluated at current state/control",
        ))
        return True
