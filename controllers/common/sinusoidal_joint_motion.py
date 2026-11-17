"""
sinusoidal_joint_motion.py —— 一个会"动"的最小例子（算法只有几行）

前面的插件都是"走到某个姿势就停住"。这个插件让关节一直按正弦摆动，
用来演示：**控制律可以依赖时间**（data.time），也就是轨迹跟踪的雏形。

和其他插件的关系：
    两个插件都会写 ctrl[:]，**按注册顺序，后面的覆盖前面的**。
    本插件在主程序里排在「关节 PD 位置控制」前面，所以会被它盖掉；
    想看本插件单独工作，就把主程序插件清单里的关节 PD 注释掉。
"""
from __future__ import annotations

import numpy as np

import plugin_system as studio
from plugin_system import ControlPlugin, step_handler


class SinusoidalJointMotionController(ControlPlugin):
    name = "正弦摆动（轨迹跟踪雏形）"
    version = "1.0"
    english_name = "Sinusoid swing"
    description = "让 shoulder_lift 绕初始姿势做正弦摆动 —— 演示控制律如何随时间变化。"
    author = "数字样机"

    # ---- 调参入口 ----
    amplitude = 0.35        # 摆动幅度（rad），0.35 rad ≈ 20°
    frequency = 0.3         # 摆动频率（Hz）
    KP = 200.0
    KD = 30.0

    def __init__(self):
        self.baseline = None
        self.step_count = 0
        self.current_target = None

    def check_model_compatibility(self, model) -> str:
        """要求 nu == nq（同样要写 `ctrl[:]`）且至少有 3 个关节。

        ★ 关于"摆哪个关节"的诚实说明：下面的代码固定摆 `qpos[1]`（第 2 个关节），
          这在 UR5e 上是 shoulder_lift，在 7 轴手臂上则是另一个关节 ——
          **不会报错，但摆的不是你以为的那个关节**。这一点没法从 model 上自动判断，
          所以这里只挡"必然出错"的情况（关节太少 / 执行器对不上），
          关节语义的差别留在注释里提示。
        """
        nq = int(getattr(model, "nq", 0))
        nu = int(getattr(model, "nu", 0))
        if nq < 3 or nu == 0:
            return f"需要至少 3 个关节且带执行器（本模型 nq={nq}、nu={nu}）"
        if nu != nq:
            return f"需要 nu==nq 的扭矩模型（本模型 nq={nq}、nu={nu}）"
        return ""

    @step_handler
    def step(self, event: studio.messages.StepEvent) -> bool:
        data = event.data
        # ★ 空场景没有关节：直接返回，别让 目标[1] 越界（越界会被"出错隔离"停用插件）
        if data.qpos.size < 3 or data.ctrl.size == 0:
            self.baseline = None
            return False
        if self.baseline is None:                       # 第一次：记住初始姿势当摆动中心
            self.baseline = data.qpos.copy()

        target = self.baseline.copy()
        target[1] += self.amplitude * np.sin(2 * np.pi * self.frequency * data.time)
        self.current_target = target

        data.ctrl[:] = self.KP * (target - data.qpos) - self.KD * data.qvel + data.qfrc_bias
        self.step_count += 1
        return False

    def status(self) -> dict:
        if self.current_target is None:
            return {"状态": "等待第一步"}
        return {"步数": self.step_count,
                "摆动到": f'{np.degrees(self.current_target[1] - self.baseline[1]):+.1f}°'}


plugin_class = SinusoidalJointMotionController
