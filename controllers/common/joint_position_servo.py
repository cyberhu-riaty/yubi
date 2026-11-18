"""Forward joint targets to explicitly validated MJCF position servos."""
from __future__ import annotations

import numpy as np

import plugin_system as studio
from plugin_system import ControlPlugin, step_handler
from ui_bridge import PanelTargetMessage


class JointPositionServo(ControlPlugin):
    name = "关节位置伺服"
    english_name = "Joint position servo"
    description = "向模型的位置伺服执行器发送关节角目标；ctrl 单位为 rad。"
    version = "1.0"
    takes_control = True

    def __init__(self) -> None:
        self._target = None
        self._qpos = []

    def check_model_compatibility(self, model) -> str:
        mj = studio.mujoco
        if model.nu == 0:
            return "模型没有位置伺服执行器"
        for actuator in range(model.nu):
            joint = int(model.actuator_trnid[actuator, 0])
            gain = float(model.actuator_gainprm[actuator, 0])
            if (model.actuator_trntype[actuator] != mj.mjtTrn.mjTRN_JOINT
                    or joint < 0 or model.jnt_type[joint] != mj.mjtJoint.mjJNT_HINGE
                    or model.actuator_gaintype[actuator] != mj.mjtGain.mjGAIN_FIXED
                    or model.actuator_biastype[actuator] != mj.mjtBias.mjBIAS_AFFINE
                    or gain <= 0
                    or not np.isclose(model.actuator_biasprm[actuator, 1], -gain)
                    or not np.isclose(model.actuator_gear[actuator, 0], 1.0)):
                return "需要 gear=1 的独立 hinge 位置伺服执行器，不能使用力矩电机"
        return ""

    def receive_model(self, event) -> None:
        model, data = event.model, event.data
        self._qpos = [int(model.jnt_qposadr[int(model.actuator_trnid[i, 0])])
                      for i in range(model.nu)]
        self._target = data.qpos.copy()
        data.ctrl[:] = self._target[self._qpos]

    @step_handler
    def on_target(self, message: PanelTargetMessage) -> bool:
        value = np.asarray(message.ctrl_target, dtype=float).reshape(-1)
        if np.all(np.isfinite(value)):
            self._target = value.copy()
        return False

    @step_handler
    def step(self, event: studio.messages.StepEvent) -> bool:
        if self._target is not None and self._target.size == event.model.nq:
            event.data.ctrl[:] = self._target[self._qpos]
        return False


plugin_class = JointPositionServo
