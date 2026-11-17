"""Pure joint-space PD feedback controller for comparison experiments."""
from __future__ import annotations

import numpy as np

import plugin_system as studio
from plugin_system import ControlPlugin, step_handler
from ui_bridge import PanelTargetMessage
from trajectory_runtime import matching_reference_velocity


class JointPDPlainController(ControlPlugin):
    name = "关节 PD 纯反馈"
    english_name = "Joint PD (feedback only)"
    version = "1.0"
    author = "数字样机"
    description = "使用位置误差和目标/实际速度误差，不加入积分或重力前馈。"
    takes_control = True

    KP = 86.0
    KD = 70.0

    def __init__(self) -> None:
        self.target = None
        self.panel_target = None
        self.current_error = float("nan")
        self.max_error = 0.0
        self.last_torque = np.zeros(0)

    def check_model_compatibility(self, model) -> str:
        nq, nv, nu = int(model.nq), int(model.nv), int(model.nu)
        if nq == 0 or nu == 0:
            return "模型没有关节或执行器"
        if not (nq == nv == nu):
            return f"当前对比控制器要求 nq==nv==nu（实际 {nq}/{nv}/{nu}）"
        return ""

    @step_handler
    def on_panel_target(self, message: PanelTargetMessage) -> bool:
        try:
            self.panel_target = np.asarray(message.ctrl_target, dtype=float).copy()
        except Exception:                                             # noqa: BLE001
            pass
        return False

    @step_handler
    def step(self, event: studio.messages.StepEvent) -> bool:
        model, data = event.model, event.data
        if data.qpos.size == 0 or data.ctrl.size == 0:
            self.target = None
            return False
        if self.target is None or len(self.target) != len(data.qpos):
            self.target = data.qpos.copy()
        target = self.target
        if self.panel_target is not None and len(self.panel_target) == len(data.qpos):
            target = self.panel_target

        error = target - data.qpos
        target_velocity = matching_reference_velocity(data, target)
        velocity_error = target_velocity - data.qvel
        torque = self.KP * error + self.KD * velocity_error
        data.ctrl[:] = self._limit_torque(model, torque)
        self.current_error = float(np.max(np.abs(error)))
        self.max_error = max(self.max_error, self.current_error)
        self.last_torque = data.ctrl.copy()
        return False

    @staticmethod
    def _limit_torque(model, torque: np.ndarray) -> np.ndarray:
        result = np.asarray(torque, dtype=float).copy()
        limited = np.asarray(model.actuator_ctrllimited, dtype=bool)
        ranges = np.asarray(model.actuator_ctrlrange, dtype=float)
        if limited.size == result.size and ranges.shape == (result.size, 2):
            result[limited] = np.clip(result[limited], ranges[limited, 0], ranges[limited, 1])
        return result

    def adjustable_parameters(self) -> dict:
        return {
            "KP": {"value": self.KP, "range": (1.0, 5000.0), "step": 1.0},
            "KD": {"value": self.KD, "range": (0.0, 500.0), "step": 0.5},
        }

    def metrics(self) -> dict:
        if not np.isfinite(self.current_error):
            return {}
        return {
            "最大误差(deg)": float(np.degrees(self.current_error)),
            "力矩峰值(Nm)": float(np.max(np.abs(self.last_torque))) if self.last_torque.size else 0.0,
        }


plugin_class = JointPDPlainController
