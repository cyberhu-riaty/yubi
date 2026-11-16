"""
参数辨识.py —— D3 的核心算法（已用"已知真值"闭环验证）

它做什么：
    给定"真机"上采到的一段数据（状态 + 控制量），反推机器人的惯性参数
    （各连杆质量、质心位置…）。这就是"让仿真像真机"的关键一步。

怎么用（三步）：
    from 参数辨识 import 采数据, 辨识, 参数定义

    数据 = 采数据(模型路径, 时长=2.0)                    # 在你的真机/高保真模型上激励
    结果 = 辨识(模型路径, 数据, 待辨识的参数, 初值)        # 反推参数
    print(结果.对比表())                                  # 看估计值 vs 初值 vs 真值

★ 最关键的一条经验（踩了一整轮才明白，务必别重犯）：
    **残差必须用"一步预测误差"，不能用"自由滚动轨迹误差"。**
        · 自由滚动：让候选参数自己跑 1 秒再比轨迹 → 参数稍偏，轨迹就跑到别处（混沌），
          残差变成噪声、对参数不敏感 → 优化撞边界、4 个参数全不收敛（实测残差只降 2 倍）。
        · 一步预测：每个采样点把仿真**重置到记录的真状态**，只推进一步再比 →
          误差不累积，残差对参数敏感且光滑 → 同样数据下 4 个参数全部收敛到 0.1%（实测）。
    这也是 mujoco.sysid 这类工具的核心思想。

为什么不用官方 sysid 的 optimize()：
    它的残差函数接口有"隐式批量/广播"语义（有限差分会把参数广播成矩阵），
    实测试了 6 种返回形状组合都对不上。改用它只做参数管理（ParameterDict 带边界/存档/对比表），
    优化用下面自实现的 Gauss-Newton（算法透明、好调试）。
"""
from __future__ import annotations

import dataclasses
import time

import numpy as np

import mujoco
import model_loader

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class ParameterDefinition:
    """一个待辨识参数的元信息。

    ★ 必须显式给出"要写进模型的哪个对象"，不要靠名字猜：
      参数名是给你看的（比如 upperarm_mass），模型里的名字往往不同
      （upper_arm_link）。早期版本按 `名称[:-5]` 去查 body，结果
      spec.body("upperarm") 返回 None，报 "'NoneType' object has no attribute 'mass'"
      （实测踩过）。所以这里明确写下 (body名, 字段)。

    目标字段：
        ("forearm_link", "mass")        → 连杆质量
        ("forearm_link", "com_x")       → 质心 x 分量
    """

    name: str
    target: tuple[str, str]
    initial: float
    lower: float
    upper: float
    reference: float | None = None      # 做闭环验证时填；真实辨识时留 None
    unit: str = ""


@dataclasses.dataclass
class CollectedData:
    """一段激励实验的记录。"""

    time: np.ndarray
    qpos: np.ndarray
    qvel: np.ndarray
    ctrl: np.ndarray
    model_path: str = ""
    note: str = ""

    @property
    def step_count(self) -> int:
        return len(self.time)


@dataclasses.dataclass
class IdentificationResult:
    parameters: list[ParameterDefinition]
    estimates: np.ndarray
    residual_history: list[float]
    rollout_count: int
    elapsed_time: float

    def rows(self) -> list[tuple[str, float, float, float | None, float | None]]:
        """返回 [(名称, 初值, 估计值, 真值, 相对误差%), …]。"""
        out = []
        for i, p in enumerate(self.parameters):
            error = None
            if p.reference is not None and abs(p.reference) > 1e-9:
                error = abs(self.estimates[i] - p.reference) / abs(p.reference) * 100
            out.append((p.name, p.initial, float(self.estimates[i]), p.reference, error))
        return out

    def comparison_table(self) -> str:
        lines = [f"{'参数':<18}{'初值':>10}{'估计值':>12}{'真值':>10}{'误差':>10}"]
        for name, initial, estimate, reference, error in self.rows():
            reference_text = f'{reference:>10.3f}' if reference is not None else f"{'—':>10}"
            error_text = f'{error:>9.1f}%' if error is not None else f"{'—':>10}"
            lines.append(f'{name:<18}{initial:>10.3f}{estimate:>12.4f}{reference_text}{error_text}')
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ① 采数据（闭环激励 —— 别用开环大力矩，会把机械臂甩飞）
# ---------------------------------------------------------------------------
def default_excitation(t: float, home: np.ndarray, amplitude: float = 0.25) -> np.ndarray:
    """一段平滑的多关节正弦目标（闭环跟踪用）。

    ★ 形状自动跟随 home 的长度 —— 以前这里写死了 6 个分量（UR5e 是 6 轴），
      换成 Franka Panda / iiwa14 / xArm7（都是 7 轴）会直接广播错误
      （实测：`operands could not be broadcast together with shapes (7,) (6,)`）。
      现在：能激励几个关节就激励几个，6 轴时的取值与前完全一致。
    """
    excitation = np.zeros_like(np.asarray(home, dtype=float))
    n = excitation.size
    if n >= 2:
        excitation[1] = np.sin(2*np.pi*0.5*t)
    if n >= 3:
        excitation[2] = np.sin(2*np.pi*0.5*t + 1.0)
    if n >= 4:
        excitation[3] = 0.6*np.sin(2*np.pi*0.8*t + 0.5)
    return np.asarray(home, dtype=float) + amplitude * excitation


def collect_data(model_path: str, duration: float = 2.0, mass_overrides: dict | None = None,
           KP: float = 400.0, KD: float = 40.0, note: str = "") -> CollectedData:
    """在模型上做闭环激励并记录 q/v/τ。

    参数
      质量覆盖: {连杆名: 质量} —— 用来造"真机"（做闭环验证时给真值）；
                真实辨识时传 None（直接在真机数据上跑）。
    为什么要闭环：开环大力矩激励会让机械臂 2 秒内甩到几百度外（实测），
                  闭环 PD 跟踪平滑轨迹才能得到有界且信息量足够的数据。
    """
    spec = model_loader.load_spec(mujoco, model_path)
    for body, mass in (mass_overrides or {}).items():
        spec.body(body).mass = float(mass)
    model = spec.compile()
    d = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, d, 0)
    mujoco.mj_forward(model, d)
    home = d.qpos.copy()

    time, qs, vs, us = [], [], [], []
    for k in range(int(duration / model.opt.timestep)):
        t = k * model.opt.timestep
        desired = default_excitation(t + model.opt.timestep, home)
        torque = KP*(desired - d.qpos) - KD*d.qvel + d.qfrc_bias
        d.ctrl[:] = np.clip(torque, -150, 150)
        mujoco.mj_step(model, d)
        time.append(d.time); qs.append(d.qpos.copy())
        vs.append(d.qvel.copy()); us.append(d.ctrl.copy())
    return CollectedData(np.array(time), np.array(qs), np.array(vs), np.array(us),
                    model_path=model_path, note=note)


# ---------------------------------------------------------------------------
# ② 辨识（Gauss-Newton + 一步预测残差）
# ---------------------------------------------------------------------------
def _make_model(model_path: str, value: dict, parameter_definitions: list[ParameterDefinition]) -> mujoco.MjModel:
    """按参数值造模型（带边界夹取，避免非法模型让编译器抛错）。"""
    spec = model_loader.load_spec(mujoco, model_path)
    for p in parameter_definitions:
        v = float(np.clip(value[p.name], p.lower, p.upper))
        write_parameter(spec, p.target, v)
    return spec.compile()


def write_parameter(spec: mujoco.MjSpec, target: tuple[str, str], value: float) -> None:
    """把参数值写进模型。`目标` = (body名, 字段)，字段为 mass / com_x / com_y / com_z。"""
    body_name, field_name = target
    body = spec.body(body_name)
    if body is None:
        raise KeyError(f'模型里没有连杆「{body_name}」')
    if field_name == "mass":
        body.mass = value
        return
    if field_name in ("com_x", "com_y", "com_z"):
        index = {"com_x": 0, "com_y": 1, "com_z": 2}[field_name]
        ipos = np.asarray(body.ipos, dtype=float).copy()
        ipos[index] = value
        body.ipos = ipos
        return
    raise KeyError(f'不支持的字段「{field_name}」（支持 mass / com_x / com_y / com_z）')


def identify(data: CollectedData, parameter_definitions: list[ParameterDefinition], stride: int = 5,
         max_iterations: int = 25, print_result=print) -> IdentificationResult:
    """用一步预测误差做 Gauss-Newton 辨识。返回 辨识结果。"""
    model_path = data.model_path
    parameter_name = [p.name for p in parameter_definitions]
    lower_bounds = np.array([p.lower for p in parameter_definitions], dtype=float)
    upper_bounds = np.array([p.upper for p in parameter_definitions], dtype=float)
    x = np.array([p.initial for p in parameter_definitions], dtype=float)

    indices = np.arange(1, len(data.time), max(1, int(stride)))
    total = [0]

    # ★ 关节数从数据里取，不要写死 —— 以前这里硬编码 6（UR5e 是 6 轴），
    #   换成 Franka Panda / iiwa14 / xArm7（7 轴）会报
    #   `could not broadcast input array from shape (7,) into shape (6,)`（实测）。
    dof = int(np.asarray(data.qpos).shape[-1])

    def residual(values):
        """一步预测误差：每个采样点重置到记录真状态，只推进一步。"""
        value = {name: float(v) for name, v in zip(parameter_name, np.asarray(values).ravel())}
        try:
            model = _make_model(model_path, value, parameter_definitions)
        except Exception:                                        # noqa: BLE001
            return np.full(len(indices) * dof, 1e3)
        d = mujoco.MjData(model)
        offset = np.empty((len(indices), dof))
        for index, k in enumerate(indices):
            d.qpos[:] = data.qpos[k - 1]
            d.qvel[:] = data.qvel[k - 1]
            mujoco.mj_forward(model, d)
            d.ctrl[:] = data.ctrl[k]         # 偏移 1：τ[k] 把状态从 q[k-1] 推到 q[k]
            mujoco.mj_step(model, d)
            offset[index] = d.qpos - data.qpos[k]
        total[0] += 1
        return offset.ravel()

    t0 = time.time()
    r = residual(x)
    cost = float(r @ r)
    history = [cost]
    print_result(f'  初值 {np.round(x, 4)} → 残差 {cost:.8f}')

    for iteration in range(max_iterations):
        J = np.zeros((r.size, x.size))
        for j in range(x.size):
            step = max(1e-6, 1e-4 * abs(x[j]))
            xj = x.copy()
            xj[j] = np.clip(xj[j] + step, lower_bounds[j], upper_bounds[j])
            actual_step = xj[j] - x[j]
            if actual_step == 0:
                continue
            J[:, j] = (residual(xj) - r) / actual_step
        JTJ = J.T @ J + 1e-9 * np.eye(x.size)
        g = J.T @ r
        gain, improvement = 1.0, False
        for _ in range(12):                       # 回溯线搜索
            attempt = np.clip(x - gain * np.linalg.solve(JTJ, g), lower_bounds, upper_bounds)
            if np.allclose(attempt, x):
                break
            new_residual = residual(attempt)
            new_cost = float(new_residual @ new_residual)
            if new_cost < cost:
                x, r, cost = attempt, new_residual, new_cost
                improvement = True
                break
            gain *= 0.5
        history.append(cost)
        if iteration % 5 == 0 or not improvement:
            print_result(f'  轮 {iteration + 1:2d}: 残差 {cost:.10f}  参数 {np.round(x, 4)}')
        if not improvement and gain < 1e-3:
            print_result(f'  轮 {iteration + 1:2d}: 无法继续改进，停止')
            break

    return IdentificationResult(parameters=parameter_definitions, estimates=x, residual_history=history,
                    rollout_count=total[0], elapsed_time=time.time() - t0)
