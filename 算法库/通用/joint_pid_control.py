"""Joint PID torque-control example for the reusable plugin interface."""
from __future__ import annotations

import numpy as np
import plugin_system as studio
from plugin_system import ControlPlugin, step_handler
from ui_bridge import PanelTargetMessage


class JointPIDController(ControlPlugin):
    name = "关节 PID 位置控制"
    english_name = "Joint PID position control"
    version = "1.0"
    author = "数字样机"
    description = "按关节计算 PID 力矩，带重力补偿、积分限幅和执行器限幅。"
    takes_control = True

    KP = 200.0
    KI = 12.0
    KD = 30.0
    积分上限 = 0.35

    def __init__(self) -> None:
        self.目标 = None
        self.界面目标 = None
        self.积分 = None
        self.最后误差 = float("nan")
        self.最大误差 = 0.0
        self.步数 = 0
        self.最后力矩 = np.zeros(0)

    def check_model_compatibility(self, 模型) -> str:
        nq, nv, nu = int(模型.nq), int(模型.nv), int(模型.nu)
        if nq == 0 or nu == 0:
            return "模型没有关节或执行器"
        if not (nq == nv == nu):
            return f"当前 PID 示例要求 nq==nv==nu（实际 {nq}/{nv}/{nu}）"
        return ""

    @step_handler
    def on_panel_target(self, 消息: PanelTargetMessage) -> bool:
        try:
            new_target = np.asarray(消息.ctrl_target, dtype=float).copy()
            if (self.界面目标 is None
                    or self.界面目标.shape != new_target.shape
                    or not np.allclose(self.界面目标, new_target, rtol=0.0, atol=1e-12)):
                self.界面目标 = new_target
                # 只有目标真的改变时才清积分，避免旧目标积累的误差影响新实验。
                if self.积分 is not None and self.积分.shape == new_target.shape:
                    self.积分.fill(0.0)
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
            if len(self.目标) >= 3:
                self.目标[1] += 0.35
                self.目标[2] -= 0.35
            self.积分 = np.zeros_like(data.qpos)
        target = self.目标
        if self.界面目标 is not None and len(self.界面目标) == len(data.qpos):
            target = self.界面目标
        error = target - data.qpos
        dt = max(float(model.opt.timestep), 1e-9)
        self.积分 = np.clip(self.积分 + error * dt, -self.积分上限, self.积分上限)
        torque = self.KP * error + self.KI * self.积分 - self.KD * data.qvel + data.qfrc_bias
        try:
            limited = np.asarray(model.actuator_ctrllimited, dtype=bool)
            ranges = np.asarray(model.actuator_ctrlrange, dtype=float)
            torque[limited] = np.clip(torque[limited], ranges[limited, 0], ranges[limited, 1])
        except Exception:                                             # noqa: BLE001
            pass
        data.ctrl[:] = torque
        self.最后误差 = float(np.max(np.abs(error)))
        self.最大误差 = max(self.最大误差, self.最后误差)
        self.步数 += 1
        self.最后力矩 = torque.copy()
        return False

    def adjustable_parameters(self) -> dict:
        return {
            "KP": {"value": self.KP, "range": (1.0, 5000.0), "step": 1.0},
            "KI": {"value": self.KI, "range": (0.0, 1000.0), "step": 0.5},
            "KD": {"value": self.KD, "range": (0.0, 500.0), "step": 0.5},
            "积分上限": {"value": self.积分上限, "range": (0.01, 2.0), "step": 0.01, "unit": "rad·s"},
        }

    def metrics(self) -> dict:
        if not np.isfinite(self.最后误差):
            return {}
        return {
            "最大误差(deg)": float(np.degrees(self.最后误差)),
            "力矩峰值(Nm)": float(np.max(np.abs(self.最后力矩))) if self.最后力矩.size else 0.0,
            "积分峰值": float(np.max(np.abs(self.积分))) if self.积分 is not None else 0.0,
        }

    def status(self) -> dict:
        if self.目标 is None:
            return {"状态": "等待第一步"}
        return {
            "步数": self.步数,
            "当前误差": f"{np.degrees(self.最后误差):.3f}°",
            "历史最大": f"{np.degrees(self.最大误差):.3f}°",
            "目标来源": "实验/界面目标" if self.界面目标 is not None else "控制器默认目标",
        }


plugin_class = JointPIDController
