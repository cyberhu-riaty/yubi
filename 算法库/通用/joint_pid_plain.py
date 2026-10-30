"""Pure joint-space PID feedback controller for comparison experiments."""
from __future__ import annotations

import numpy as np

import 插件系统 as studio
from 插件系统 import 控制插件, 每步
from 界面桥 import 面板目标消息


class JointPIDPlainController(控制插件):
    名称 = "关节 PID 纯反馈"
    英文名 = "Joint PID (feedback only)"
    版本 = "1.0"
    作者 = "数字样机"
    说明 = "在纯 PD 基础上增加误差积分；不加入重力前馈。"
    接管控制 = True

    # 与另外两组共用 KP/KD，只增加 KI，便于解释差异来源。
    KP = 86.0
    KI = 40.0
    KD = 70.0
    积分上限 = 1.0

    def __init__(self) -> None:
        self.目标 = None
        self.界面目标 = None
        self.积分 = None
        self.当前误差 = float("nan")
        self.最大误差 = 0.0
        self.最后力矩 = np.zeros(0)

    def 模型兼容性(self, 模型) -> str:
        nq, nv, nu = int(模型.nq), int(模型.nv), int(模型.nu)
        if nq == 0 or nu == 0:
            return "模型没有关节或执行器"
        if not (nq == nv == nu):
            return f"当前对比控制器要求 nq==nv==nu（实际 {nq}/{nv}/{nu}）"
        return ""

    @每步
    def 收到面板目标(self, 消息: 面板目标消息) -> bool:
        try:
            target = np.asarray(消息.ctrl_target, dtype=float).copy()
            if (self.界面目标 is None or self.界面目标.shape != target.shape
                    or not np.allclose(self.界面目标, target, rtol=0.0, atol=1e-12)):
                self.界面目标 = target
                if self.积分 is not None and self.积分.shape == target.shape:
                    self.积分.fill(0.0)
        except Exception:                                             # noqa: BLE001
            pass
        return False

    @每步
    def 每步控制(self, event: studio.messages.StepEvent) -> bool:
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
        dt = max(float(model.opt.timestep), 1e-9)
        self.积分 = np.clip(
            self.积分 + error * dt, -self.积分上限, self.积分上限)
        torque = self.KP * error + self.KI * self.积分 - self.KD * data.qvel
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

    def 可调参数(self) -> dict:
        return {
            "KP": {"值": self.KP, "范围": (1.0, 5000.0), "步长": 1.0},
            "KI": {"值": self.KI, "范围": (0.0, 1000.0), "步长": 0.5},
            "KD": {"值": self.KD, "范围": (0.0, 500.0), "步长": 0.5},
            "积分上限": {"值": self.积分上限, "范围": (0.01, 2.0), "步长": 0.01, "单位": "rad·s"},
        }

    def 指标(self) -> dict:
        if not np.isfinite(self.当前误差):
            return {}
        return {
            "最大误差(deg)": float(np.degrees(self.当前误差)),
            "力矩峰值(Nm)": float(np.max(np.abs(self.最后力矩))) if self.最后力矩.size else 0.0,
            "积分峰值": float(np.max(np.abs(self.积分))) if self.积分 is not None else 0.0,
        }


插件类 = JointPIDPlainController
