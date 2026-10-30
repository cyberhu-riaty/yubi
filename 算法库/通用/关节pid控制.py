"""通用关节 PID 力矩控制器示例；用于验证新增算法无需修改 GUI/仿真引擎。"""
from __future__ import annotations

import numpy as np
import 插件系统 as 插件
from 插件系统 import 控制插件, 每步
from 界面桥 import 面板目标消息


class 关节PID控制插件(控制插件):
    名称 = "关节 PID 位置控制"
    英文名 = "Joint PID position control"
    版本 = "1.0"
    作者 = "数字样机"
    说明 = "按关节计算 PID 力矩，带重力补偿、积分限幅和执行器限幅。"
    接管控制 = True

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

    def 模型兼容性(self, 模型) -> str:
        nq, nv, nu = int(模型.nq), int(模型.nv), int(模型.nu)
        if nq == 0 or nu == 0:
            return "模型没有关节或执行器"
        if not (nq == nv == nu):
            return f"当前 PID 示例要求 nq==nv==nu（实际 {nq}/{nv}/{nu}）"
        return ""

    @每步
    def 收到面板目标(self, 消息: 面板目标消息) -> bool:
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

    @每步
    def 每步控制(self, event: 插件.messages.StepEvent) -> bool:
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

    def 可调参数(self) -> dict:
        return {
            "KP": {"值": self.KP, "范围": (1.0, 5000.0), "步长": 1.0},
            "KI": {"值": self.KI, "范围": (0.0, 1000.0), "步长": 0.5},
            "KD": {"值": self.KD, "范围": (0.0, 500.0), "步长": 0.5},
            "积分上限": {"值": self.积分上限, "范围": (0.01, 2.0), "步长": 0.01, "单位": "rad·s"},
        }

    def 指标(self) -> dict:
        if not np.isfinite(self.最后误差):
            return {}
        return {
            "最大误差(deg)": float(np.degrees(self.最后误差)),
            "力矩峰值(Nm)": float(np.max(np.abs(self.最后力矩))) if self.最后力矩.size else 0.0,
            "积分峰值": float(np.max(np.abs(self.积分))) if self.积分 is not None else 0.0,
        }

    def 插件状态(self) -> dict:
        if self.目标 is None:
            return {"状态": "等待第一步"}
        return {
            "步数": self.步数,
            "当前误差": f"{np.degrees(self.最后误差):.3f}°",
            "历史最大": f"{np.degrees(self.最大误差):.3f}°",
            "目标来源": "实验/界面目标" if self.界面目标 is not None else "控制器默认目标",
        }


插件类 = 关节PID控制插件
