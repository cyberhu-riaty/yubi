"""
two_point_task_space.py —— 任务空间控制插件（把教程 10 号脚本的算法搬进外壳）

和第 1 个插件的区别（这正是"换个算法 = 换个文件"要展示的东西）：
    关节PD控制   ：目标是"6 个关节角"      → 不需要逆运动学，3 行搞定
    本插件       ：目标是"末端在空间中的点" → 需要 雅可比(Task Space PD) + 逆运动学 + 轨迹插值

算法本体（比关节 PD 多两件事）：
    ① 末端位置误差 → 虚拟力：  F = KP*(p_des - p) + KD*(v_des - v)
    ② 虚拟力 → 关节力矩：      τ = Jᵀ·F + 重力补偿        ← J 是位置雅可比
    ③ 目标点不是一步跳过去的，而是用 smootherstep 在两秒内平滑滑过去（轨迹规划）

★ 两个插件同时挂上时谁说了算？—— 看**装配顺序**，不是看 Priority。

    本外壳的派发是"逐个插件依次调用"（为了做出错隔离，见 软件/plugin_system.py），
    顺序 = 项目文件里 `算法` 列表的顺序，**排在最后的那个最后写 ctrl[:]，它赢**。
    `messages.Priority` 在本外壳的**跨插件**派发里不参与排序 —— 官方
    `PluginRegistry.dispatch` 会按它降序排，但我们没用官方那条路。

    ⚠️ 所以下面 `@step_handler(priority=Priority.USER - 1)` 的 priority **不起作用**：
      它只是把档位信息记在处理器上，本外壳不读它。保留写法是为了贴合官方语义、
      也方便日后真按它排序（那时这个声明就自然生效了）。
      想让某个算法赢 → 在界面【Algorithms】面板把它调到列表最后，或改项目文件的算法列表。
      历史上这里踩过坑：曾经 5 个项目都写 `"算法": "*"`，扫描顺序让【正弦摆动】排在最后，
      于是它偷偷盖住了关节 PD，表现为"机械臂按正弦来回摆"。详见 CHANGELOG v0.4.1。
"""
from __future__ import annotations

import numpy as np

import plugin_system as studio
from plugin_system import (
    ControlPlugin,
    Priority,
    step_handler,
)

END_EFFECTOR_SITE = "attachment_site"       # UR5e 法兰往外 0.1 m 的工具中心点（TCP）


class TwoPointTaskSpaceController(ControlPlugin):
    name = "末端两点运动（任务空间 PD）"
    version = "1.0"
    english_name = "Two-point task-space motion"
    description = "让末端在世界坐标里的两个点之间来回走：雅可比转置 + 重力补偿 + 平滑轨迹。"
    author = "数字样机"

    # ---- 调参入口 ----
    KP = 2500.0                       # 末端位置刚度（N/m）：越大跟得越紧
    KD = 90.0                         # 末端阻尼：临界阻尼 ≈ 2√KP
    START_POSITION = np.array([0.45, 0.10, 0.50])   # 世界坐标（m）；机器人会先被摆到这里
    END_POSITION = np.array([0.30, -0.20, 0.35])
    leg_duration = 2.0                    # 从一点走到另一点用几秒
    round_trip = True                     # True=来回走；False=走到终点就停住

    # 工具姿态：让法兰面朝下（末端竖直下探），这也是工业上最常用的姿势
    TOOL_DOWN_ROTATION = np.array([[1.0, 0.0, 0.0],
                           [0.0, 0.0, 1.0],
                           [0.0, -1.0, 0.0]])

    def __init__(self):
        self.model = None
        self.positioned = False
        self.start_time = 0.0
        self.step_count = 0
        self.max_tracking_error = 0.0
        self.positioning_residual = None

    # ------------------------------------------------------------------
    # 兼容性预检：外壳换模型时会先问一句"这个模型你能跑吗"
    #   （契约见 软件/plugin_system.py 的 `ControlPlugin`）
    # ------------------------------------------------------------------
    def check_model_compatibility(self, model) -> str:
        """要求 6 自由度 + 有 `attachment_site` 这个末端站点。

        ★ 为什么是 6：下面的 `_逆运动学()` 解的是 **6 维任务**（3 位置 + 3 姿态），
          用 6×nq 的雅可比做阻尼最小二乘，并且直接下标 `qpos[:6]`。
          7 轴手臂（Panda / iiwa14 / xArm7）不是不能做，而是**本实现的假设不成立**：
          7 轴时任务维度(6) < 关节数(7)，最小二乘解不唯一，
          当前代码会把它当成 6 轴处理 —— 结果是把第 7 轴晾在一边，
          而且 `起点`/`终点` 那两个世界坐标点是**照着 UR5e 的工作空间写死的**
          （见类属性 `起点` / `终点`），换台手臂多半够不着。
          与其"跑起来乱走"，不如明说"这个算法是给 6 轴 UR 写的"。

        ★ 站点检查用 `模型.body()` / `mj_name2id` 的老路子也行，但这里只需要知道
          "有没有这个站点"，用 `模型.site(...)` 之外最省事的方式即可；
          为了不依赖 data，这里按名字查 site 的 id。
        """
        import mujoco

        nq = int(getattr(model, "nq", 0))
        if nq != 6:
            return (f"需要 6 轴手臂（本模型 {nq} 轴；本算法按 6 维任务做了逆运动学，"
                    f"且起止点是照 UR5e 工作空间标定的）")
        if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, END_EFFECTOR_SITE) < 0:
            return f'模型里没有末端站点「{END_EFFECTOR_SITE}」（逆运动学要拿它当控制点）'
        return ""

    # ------------------------------------------------------------------
    # 可选：模型加载后调一次（拿到 model/data 引用，用于做逆运动学）
    # ------------------------------------------------------------------
    def receive_model(self, event) -> None:
        self.model, self.data = event.model, event.data

    # ------------------------------------------------------------------
    # ★ 每转一圈仿真调用一次
    # ------------------------------------------------------------------
    @step_handler(priority=Priority.USER - 1) # priority 在本外壳里不起作用（见文件头说明）
                                              #   谁说了算由装配顺序决定：排最后的赢
    def step(self, event: studio.messages.StepEvent) -> bool:
        model, data = event.model, event.data

        # ★ 空场景（模型/空场景.xml）里没有任何关节与站点。
        #   直接往下走会在 `数据.site(末端站点)` 抛异常 → 插件被"出错隔离"停用
        #   → 换了真模型也不会被控制。所以先挡一道。
        if data.qpos.size == 0 or data.ctrl.size == 0 or data.site(END_EFFECTOR_SITE) is None:
            self.positioned = False
            return False

        # ---- 第一次：用逆运动学把机器人摆到「起点」，并记下时间基准 ----
        if not self.positioned:
            solution, position_residual, orientation_residual = self._inverse_kinematics(model, data, self.START_POSITION)
            data.qpos[:] = solution
            data.qvel[:] = 0.0
            import mujoco
            mujoco.mj_forward(model, data)
            self.positioned = True
            self.start_time = float(data.time)
            self.positioning_residual = position_residual
            if position_residual > 1e-3:
                print(f'⚠ 【{self.name}】起点解不出来（残差 {position_residual * 1000:.1f} mm）：'
                      f"机器人会被摆到最接近的位形，实际起点与设定不同。")

        # ---- 算这一刻的期望点（轨迹插值）----
        elapsed = float(data.time) - self.start_time
        segment = int(elapsed / self.leg_duration)
        segment = min(segment, 1) if not self.round_trip else segment
        outbound = (segment % 2 == 0)
        a, b = (self.START_POSITION, self.END_POSITION) if outbound else (self.END_POSITION, self.START_POSITION)
        p_des, v_des = self._interpolate(elapsed - segment * self.leg_duration, self.leg_duration, a, b)

        # ---- 控制律：任务空间 PD + 重力补偿 ----
        position = data.site(END_EFFECTOR_SITE).xpos
        Jp = np.zeros((3, model.nv))
        import mujoco
        mujoco.mj_jacSite(model, data, Jp, None, data.site(END_EFFECTOR_SITE).id)
        end_effector_velocity = Jp @ data.qvel
        virtual_force = self.KP * (p_des - position) + self.KD * (v_des - end_effector_velocity)
        data.ctrl[:] = np.clip(Jp.T @ virtual_force + data.qfrc_bias,
                               -model.actuator_ctrlrange[:, 1], model.actuator_ctrlrange[:, 1])

        self.step_count += 1
        self.max_tracking_error = max(self.max_tracking_error, float(np.linalg.norm(p_des - position)))
        return False

    # ------------------------------------------------------------------
    # 工具：smootherstep 插值（两端速度、加速度都为 0）
    # ------------------------------------------------------------------
    @staticmethod
    def _interpolate(t, duration, p0, p1):
        s = float(np.clip(t / duration, 0.0, 1.0))
        u = s * s * s * (s * (6.0 * s - 15.0) + 10.0)
        du = 30.0 * s * s * (1.0 - s) ** 2 / duration
        return p0 + (p1 - p0) * u, (p1 - p0) * du

    # ------------------------------------------------------------------
    # 工具：数值逆运动学（6 自由度 DLS，位置 + 姿态一起管）
    #   只用来"摆到起点"，不参与控制回路 —— 所以慢一点没关系
    # ------------------------------------------------------------------
    def _inverse_kinematics(self, model, data, target_position, iteration_limit=300, damping=0.03, tolerance=1e-4):
        import mujoco
        site = data.site(END_EFFECTOR_SITE)
        q = data.qpos.copy()

        def forward_kinematics(q_):
            data.qpos[:] = q_
            mujoco.mj_kinematics(model, data)
            return data.site(END_EFFECTOR_SITE).xpos.copy(), data.site(END_EFFECTOR_SITE).xmat.reshape(3, 3).copy()

        def orientation_error(current_rotation, desired_rotation):
            rotation_delta = desired_rotation @ current_rotation.T
            angle = float(np.arccos(np.clip((np.trace(rotation_delta) - 1.0) / 2.0, -1.0, 1.0)))
            if angle < 1e-9:
                return np.zeros(3)
            axis = np.array([rotation_delta[2, 1] - rotation_delta[1, 2], rotation_delta[0, 2] - rotation_delta[2, 0], rotation_delta[1, 0] - rotation_delta[0, 1]])
            return axis / (2.0 * np.sin(angle)) * angle

        position_residual = orientation_residual = np.inf
        for _ in range(iteration_limit):
            p, current_rotation = forward_kinematics(q)
            e_p = target_position - p
            e_R = orientation_error(current_rotation, self.TOOL_DOWN_ROTATION)
            position_residual, orientation_residual = float(np.linalg.norm(e_p)), float(np.linalg.norm(e_R))
            if position_residual < tolerance and orientation_residual < tolerance:
                break
            e = np.concatenate([e_p, e_R])
            J = np.zeros((6, model.nq))
            h = 1e-6
            for j in range(model.nq):
                qp = q.copy()
                qp[j] += h
                pp, Rp = forward_kinematics(qp)
                J[:3, j] = (pp - p) / h
                J[3:, j] = orientation_error(current_rotation, Rp) / h
            q = np.clip(q + J.T @ np.linalg.solve(J @ J.T + damping ** 2 * np.eye(6), e),
                        model.jnt_range[:, 0], model.jnt_range[:, 1])
        return q, position_residual, orientation_residual

    # ------------------------------------------------------------------
    def status(self) -> dict:
        if not self.positioned:
            return {"状态": "等待第一步"}
        row = {"步数": self.step_count, "最大跟踪误差": f'{self.max_tracking_error * 1000:.2f} mm'}
        if self.positioning_residual is not None and self.positioning_residual > 1e-3:
            row["⚠起点残差"] = f'{self.positioning_residual * 1000:.1f} mm'
        return row


plugin_class = TwoPointTaskSpaceController
