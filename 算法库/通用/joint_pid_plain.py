"""Pure joint-space PID feedback controller for comparison experiments."""
from __future__ import annotations

import numpy as np

import plugin_system as studio
from plugin_system import ControlPlugin, step_handler
from ui_bridge import PanelTargetMessage
from trajectory_runtime import matching_reference_velocity


class JointPIDPlainController(ControlPlugin):
    parameter_aliases = {'积分上限': 'integral_limit'}
    name = "关节 PID 纯反馈"
    english_name = "Joint PID (feedback only)"
    version = "1.0"
    author = "数字样机"
    description = "使用位置/速度误差并增加误差积分；不加入重力前馈。"
    takes_control = True

    # 与另外两组共用 KP/KD，只增加 KI，便于解释差异来源。
    KP = 86.0
    KI = 40.0
    KD = 70.0
    integral_limit = 1.0
    # 连续轨迹每个控制周期都会更新目标，不能因此清积分；只有明显的人工跳变
    # 才视为换任务。实验复位会重建控制器，本身也会自然清空积分。
    target_jump_threshold = np.deg2rad(10.0)

    def __init__(self) -> None:
        self.target = None
        self.panel_target = None
        self.integral = None
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
            target = np.asarray(message.ctrl_target, dtype=float).copy()
            shape_changed = self.panel_target is not None and self.panel_target.shape != target.shape
            large_jump = (
                self.panel_target is not None
                and self.panel_target.shape == target.shape
                and float(np.max(np.abs(target - self.panel_target))) >= self.target_jump_threshold
            )
            self.panel_target = target
            if (shape_changed or large_jump) and self.integral is not None:
                self.integral = np.zeros_like(target)
        except Exception:                                             # noqa: BLE001
            pass
        return False

    @step_handler
    def step(self, event: studio.messages.StepEvent) -> bool:
        model, data = event.model, event.data
        if data.qpos.size == 0 or data.ctrl.size == 0:
            self.target = self.integral = None
            return False
        if self.target is None or len(self.target) != len(data.qpos):
            self.target = data.qpos.copy()
            self.integral = np.zeros_like(data.qpos)
        target = self.target
        if self.panel_target is not None and len(self.panel_target) == len(data.qpos):
            target = self.panel_target

        error = target - data.qpos
        target_velocity = matching_reference_velocity(data, target)
        velocity_error = target_velocity - data.qvel
        dt = max(float(model.opt.timestep), 1e-9)
        old_integral = self.integral.copy()
        candidate_integral = np.clip(
            old_integral + error * dt, -self.integral_limit, self.integral_limit)
        candidate_torque = (
            self.KP * error + self.KI * candidate_integral + self.KD * velocity_error)
        limited_torque = self._limit_torque(model, candidate_torque)

        # 条件积分抗饱和：若某关节已经触及力矩上/下限，而且当前误差会让积分
        # 继续把它推向限位，就暂停该关节积分；脱离饱和后自动恢复。
        saturated = np.abs(candidate_torque - limited_torque) > 1e-10
        pushes_further = np.logical_or(
            np.logical_and(candidate_torque > limited_torque, error > 0.0),
            np.logical_and(candidate_torque < limited_torque, error < 0.0),
        )
        block = np.logical_and(saturated, pushes_further)
        self.integral = np.where(block, old_integral, candidate_integral)
        torque = self.KP * error + self.KI * self.integral + self.KD * velocity_error
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
            "KI": {"value": self.KI, "range": (0.0, 1000.0), "step": 0.5},
            "KD": {"value": self.KD, "range": (0.0, 500.0), "step": 0.5},
            "积分上限": {"value": self.integral_limit, "range": (0.01, 2.0), "step": 0.01, "unit": "rad·s"},
        }

    def metrics(self) -> dict:
        if not np.isfinite(self.current_error):
            return {}
        return {
            "最大误差(deg)": float(np.degrees(self.current_error)),
            "力矩峰值(Nm)": float(np.max(np.abs(self.last_torque))) if self.last_torque.size else 0.0,
            "积分峰值": float(np.max(np.abs(self.integral))) if self.integral is not None else 0.0,
        }


plugin_class = JointPIDPlainController
