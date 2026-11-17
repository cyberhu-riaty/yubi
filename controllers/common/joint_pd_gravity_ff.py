"""Joint PD feedback plus model-based gravity feedforward."""
from __future__ import annotations

import numpy as np

import plugin_system as studio
from plugin_system import ControlPlugin, step_handler
from ui_bridge import PanelTargetMessage
from trajectory_runtime import matching_reference_velocity


class JointPDGravityFeedforwardController(ControlPlugin):
    name = "关节 PD＋重力前馈"
    english_name = "Joint PD + gravity feedforward"
    version = "1.0"
    author = "数字样机"
    description = "使用位置/速度误差，并叠加由 MuJoCo 模型计算的纯重力力矩。"
    takes_control = True

    KP = 86.0
    KD = 70.0

    def __init__(self) -> None:
        self.target = None
        self.panel_target = None
        self.current_error = float("nan")
        self.max_error = 0.0
        self.last_torque = np.zeros(0)
        self.last_gravity_torque = np.zeros(0)
        self._model_id = None
        self._gravity_data = None

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

    def _gravity_torque(self, model, data) -> np.ndarray:
        # 使用独立 MjData，不修改正在运行的 qvel。把速度置零后，qfrc_bias 中
        # 不再含科氏/离心项，得到与当前姿态对应的重力前馈。
        if self._gravity_data is None or self._model_id != id(model):
            self._model_id = id(model)
            self._gravity_data = studio.mujoco.MjData(model)
        scratch = self._gravity_data
        scratch.qpos[:] = data.qpos
        scratch.qvel[:] = 0.0
        scratch.qacc[:] = 0.0
        if scratch.ctrl.size:
            scratch.ctrl[:] = 0.0
        studio.mujoco.mj_forward(model, scratch)
        return np.asarray(scratch.qfrc_bias, dtype=float).copy()

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
        gravity = self._gravity_torque(model, data)
        torque = self.KP * error + self.KD * velocity_error + gravity
        data.ctrl[:] = self._limit_torque(model, torque)
        self.current_error = float(np.max(np.abs(error)))
        self.max_error = max(self.max_error, self.current_error)
        self.last_torque = data.ctrl.copy()
        self.last_gravity_torque = gravity
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
            "重力前馈峰值(Nm)": float(np.max(np.abs(self.last_gravity_torque))) if self.last_gravity_torque.size else 0.0,
        }


plugin_class = JointPDGravityFeedforwardController
