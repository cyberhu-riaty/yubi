"""Joint PID torque-control example for the reusable plugin interface."""
from __future__ import annotations

import numpy as np
import plugin_system as studio
from plugin_system import ControlPlugin, step_handler
from ui_bridge import PanelTargetMessage


class JointPIDController(ControlPlugin):
    parameter_aliases = {'积分上限': 'integral_limit'}
    name = "关节 PID 位置控制"
    english_name = "Joint PID position control"
    version = "1.0"
    author = "数字样机"
    description = "按关节计算 PID 力矩，带重力补偿、积分限幅和执行器限幅。"
    takes_control = True

    KP = 200.0
    KI = 12.0
    KD = 30.0
    integral_limit = 0.35

    def __init__(self) -> None:
        self.target = None
        self.panel_target = None
        self.integral = None
        self.last_error = float("nan")
        self.max_error = 0.0
        self.step_count = 0
        self.last_torque = np.zeros(0)

    def check_model_compatibility(self, model) -> str:
        nq, nv, nu = int(model.nq), int(model.nv), int(model.nu)
        if nq == 0 or nu == 0:
            return "模型没有关节或执行器"
        if not (nq == nv == nu):
            return f"当前 PID 示例要求 nq==nv==nu（实际 {nq}/{nv}/{nu}）"
        return ""

    @step_handler
    def on_panel_target(self, message: PanelTargetMessage) -> bool:
        try:
            new_target = np.asarray(message.ctrl_target, dtype=float).copy()
            if (self.panel_target is None
                    or self.panel_target.shape != new_target.shape
                    or not np.allclose(self.panel_target, new_target, rtol=0.0, atol=1e-12)):
                self.panel_target = new_target
                # 只有目标真的改变时才清积分，避免旧目标积累的误差影响新实验。
                if self.integral is not None and self.integral.shape == new_target.shape:
                    self.integral.fill(0.0)
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
            if len(self.target) >= 3:
                self.target[1] += 0.35
                self.target[2] -= 0.35
            self.integral = np.zeros_like(data.qpos)
        target = self.target
        if self.panel_target is not None and len(self.panel_target) == len(data.qpos):
            target = self.panel_target
        error = target - data.qpos
        dt = max(float(model.opt.timestep), 1e-9)
        self.integral = np.clip(self.integral + error * dt, -self.integral_limit, self.integral_limit)
        torque = self.KP * error + self.KI * self.integral - self.KD * data.qvel + data.qfrc_bias
        try:
            limited = np.asarray(model.actuator_ctrllimited, dtype=bool)
            ranges = np.asarray(model.actuator_ctrlrange, dtype=float)
            torque[limited] = np.clip(torque[limited], ranges[limited, 0], ranges[limited, 1])
        except Exception:                                             # noqa: BLE001
            pass
        data.ctrl[:] = torque
        self.last_error = float(np.max(np.abs(error)))
        self.max_error = max(self.max_error, self.last_error)
        self.step_count += 1
        self.last_torque = torque.copy()
        return False

    def adjustable_parameters(self) -> dict:
        return {
            "KP": {"value": self.KP, "range": (1.0, 5000.0), "step": 1.0},
            "KI": {"value": self.KI, "range": (0.0, 1000.0), "step": 0.5},
            "KD": {"value": self.KD, "range": (0.0, 500.0), "step": 0.5},
            "积分上限": {"value": self.integral_limit, "range": (0.01, 2.0), "step": 0.01, "unit": "rad·s"},
        }

    def metrics(self) -> dict:
        if not np.isfinite(self.last_error):
            return {}
        return {
            "最大误差(deg)": float(np.degrees(self.last_error)),
            "力矩峰值(Nm)": float(np.max(np.abs(self.last_torque))) if self.last_torque.size else 0.0,
            "积分峰值": float(np.max(np.abs(self.integral))) if self.integral is not None else 0.0,
        }

    def status(self) -> dict:
        if self.target is None:
            return {"状态": "等待第一步"}
        return {
            "步数": self.step_count,
            "当前误差": f'{np.degrees(self.last_error):.3f}°',
            "历史最大": f'{np.degrees(self.max_error):.3f}°',
            "目标来源": "实验/界面目标" if self.panel_target is not None else "控制器默认目标",
        }


plugin_class = JointPIDController
