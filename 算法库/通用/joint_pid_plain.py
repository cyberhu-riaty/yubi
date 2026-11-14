"""Pure joint-space PID feedback controller for comparison experiments."""
from __future__ import annotations

import numpy as np

import plugin_system as studio
from plugin_system import ControlPlugin, step_handler
from ui_bridge import PanelTargetMessage
from trajectory_runtime import matching_reference_velocity


class JointPIDPlainController(ControlPlugin):
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
    积分上限 = 1.0
    # 连续轨迹每个控制周期都会更新目标，不能因此清积分；只有明显的人工跳变
    # 才视为换任务。实验复位会重建控制器，本身也会自然清空积分。
    目标跳变阈值 = np.deg2rad(10.0)

    def __init__(self) -> None:
        self.目标 = None
        self.界面目标 = None
        self.积分 = None
        self.当前误差 = float("nan")
        self.最大误差 = 0.0
        self.最后力矩 = np.zeros(0)

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
            target = np.asarray(消息.ctrl_target, dtype=float).copy()
            形状变化 = self.界面目标 is not None and self.界面目标.shape != target.shape
            大幅跳变 = (
                self.界面目标 is not None
                and self.界面目标.shape == target.shape
                and float(np.max(np.abs(target - self.界面目标))) >= self.目标跳变阈值
            )
            self.界面目标 = target
            if (形状变化 or 大幅跳变) and self.积分 is not None:
                self.积分 = np.zeros_like(target)
        except Exception:                                             # noqa: BLE001
            pass
        return False

    @step_handler
    def step(self, event: studio.messages.StepEvent) -> bool:
        model, data = event.model, event.data
        if data.qpos.size == 0 or data.ctrl.size == 0:
            self.目标 = self.积分 = None
            return False
        if self.目标 is None or len(self.目标) != len(data.qpos):
            self.目标 = data.qpos.copy()
            self.积分 = np.zeros_like(data.qpos)
        target = self.目标
        if self.界面目标 is not None and len(self.界面目标) == len(data.qpos):
            target = self.界面目标

        error = target - data.qpos
        target_velocity = matching_reference_velocity(data, target)
        velocity_error = target_velocity - data.qvel
        dt = max(float(model.opt.timestep), 1e-9)
        old_integral = self.积分.copy()
        candidate_integral = np.clip(
            old_integral + error * dt, -self.积分上限, self.积分上限)
        candidate_torque = (
            self.KP * error + self.KI * candidate_integral + self.KD * velocity_error)
        limited_torque = self._限制力矩(model, candidate_torque)

        # 条件积分抗饱和：若某关节已经触及力矩上/下限，而且当前误差会让积分
        # 继续把它推向限位，就暂停该关节积分；脱离饱和后自动恢复。
        saturated = np.abs(candidate_torque - limited_torque) > 1e-10
        pushes_further = np.logical_or(
            np.logical_and(candidate_torque > limited_torque, error > 0.0),
            np.logical_and(candidate_torque < limited_torque, error < 0.0),
        )
        block = np.logical_and(saturated, pushes_further)
        self.积分 = np.where(block, old_integral, candidate_integral)
        torque = self.KP * error + self.KI * self.积分 + self.KD * velocity_error
        data.ctrl[:] = self._限制力矩(model, torque)
        self.当前误差 = float(np.max(np.abs(error)))
        self.最大误差 = max(self.最大误差, self.当前误差)
        self.最后力矩 = data.ctrl.copy()
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
            "KI": {"value": self.KI, "range": (0.0, 1000.0), "step": 0.5},
            "KD": {"value": self.KD, "range": (0.0, 500.0), "step": 0.5},
            "积分上限": {"value": self.积分上限, "range": (0.01, 2.0), "step": 0.01, "unit": "rad·s"},
        }

    def metrics(self) -> dict:
        if not np.isfinite(self.当前误差):
            return {}
        return {
            "最大误差(deg)": float(np.degrees(self.当前误差)),
            "力矩峰值(Nm)": float(np.max(np.abs(self.最后力矩))) if self.最后力矩.size else 0.0,
            "积分峰值": float(np.max(np.abs(self.积分))) if self.积分 is not None else 0.0,
        }


plugin_class = JointPIDPlainController
