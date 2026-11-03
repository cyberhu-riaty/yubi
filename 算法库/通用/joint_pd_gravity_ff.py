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
        self.目标 = None
        self.界面目标 = None
        self.当前误差 = float("nan")
        self.最大误差 = 0.0
        self.最后力矩 = np.zeros(0)
        self.最后重力力矩 = np.zeros(0)
        self._模型标识 = None
        self._重力数据 = None

    def check_model_compatibility(self, 模型) -> str:
        nq, nv, nu = int(模型.nq), int(模型.nv), int(模型.nu)
        if nq == 0 or nu == 0:
            return "模型没有关节或执行器"
        if not (nq == nv == nu):
            return f"当前对比控制器要求 nq==nv==nu（实际 {nq}/{nv}/{nu}）"
        return ""

    @step_handler
    def on_panel_target(self, 消息: PanelTargetMessage) -> bool:
        try:
            self.界面目标 = np.asarray(消息.ctrl_target, dtype=float).copy()
        except Exception:                                             # noqa: BLE001
            pass
        return False

    def _重力力矩(self, model, data) -> np.ndarray:
        # 使用独立 MjData，不修改正在运行的 qvel。把速度置零后，qfrc_bias 中
        # 不再含科氏/离心项，得到与当前姿态对应的重力前馈。
        if self._重力数据 is None or self._模型标识 != id(model):
            self._模型标识 = id(model)
            self._重力数据 = studio.mujoco.MjData(model)
        scratch = self._重力数据
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
            self.目标 = None
            return False
        if self.目标 is None or len(self.目标) != len(data.qpos):
            self.目标 = data.qpos.copy()
        target = self.目标
        if self.界面目标 is not None and len(self.界面目标) == len(data.qpos):
            target = self.界面目标

        error = target - data.qpos
        target_velocity = matching_reference_velocity(data, target)
        velocity_error = target_velocity - data.qvel
        gravity = self._重力力矩(model, data)
        torque = self.KP * error + self.KD * velocity_error + gravity
        data.ctrl[:] = self._限制力矩(model, torque)
        self.当前误差 = float(np.max(np.abs(error)))
        self.最大误差 = max(self.最大误差, self.当前误差)
        self.最后力矩 = data.ctrl.copy()
        self.最后重力力矩 = gravity
        return False

    @staticmethod
    def _限制力矩(model, torque: np.ndarray) -> np.ndarray:
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
        if not np.isfinite(self.当前误差):
            return {}
        return {
            "最大误差(deg)": float(np.degrees(self.当前误差)),
            "力矩峰值(Nm)": float(np.max(np.abs(self.最后力矩))) if self.最后力矩.size else 0.0,
            "重力前馈峰值(Nm)": float(np.max(np.abs(self.最后重力力矩))) if self.最后重力力矩.size else 0.0,
        }


plugin_class = JointPDGravityFeedforwardController
