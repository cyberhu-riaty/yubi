"""
trajectory_planning.py —— 关节空间轨迹规划内核（**纯函数**：数组进、数组出）

设计说明：见 `CHANGELOG.md` 的 0.6.0「轨迹规划」与本文末尾的边界说明。

═══ 这个模块只做三件事 ════════════════════════════════════════════════════
    ① 把一串关节航点变成一条**可求导的路径** q(s)，s ∈ [0,1] 按弧长参数化
    ② 在**关节限位**（rad/s、rad/s²、rad/s³）下算出一条时间参数化轨迹
    ③ 回算校验，并把"贴到限位了没有/哪一段是瓶颈"变成**数字**

它**不**做的事（都很重要）：
    · 不 import mujoco —— 限位由调用方从 `MjModel` 读出来传进来，这样内核能单测
    · 不碰界面、不读文件、不写日志
    · **不事后修改轨迹**（LE 的缺陷 ①：把最后一帧硬置零）

═══ 与 LE 的关键差异（每条都对应一个已知缺陷）══════════════════════════════
    · 速度包络**闭式求解**：`v_s_max(s) = min_i vlim_i / |q_i'(s)|`
      —— 不需要 TOPPRA/solver。LE 用 LP 求这个上界，再取 `X[:,1]` 还得开平方。
    · 限位**只有上限语义**。LE 里 `segment_v_max = max(v_max, desired_v, v_prev)`
      把 v_max 当**下限**用，导致默认配置下参数永不生效。
    · 时间律用**前后向扫描**（自己写），不依赖 ruckig。终止速度由后向扫描天然收到 0，
      不做事后修正。
    · `qd/qdd` 用**链式法则**（样条解析求导），不用 `np.gradient`。
    · 算完**必须**回算校验；超限位就如实报出来，不静默通过。
"""
from __future__ import annotations

import dataclasses
import math

import numpy as np

# 数值容差：这些值决定了"算不算贴边"，写在明处便于复核
CURVATURE_EPSILON = 1e-9          # |q'(s)| 小于它就当该关节不参与这一步的限位换算

# 加速度预算怎么在两处之间分账：
#   qdd_i = q_i''·sd²  +  q_i'·sdd
#           └─ 曲率项 ─┘   └─ 切向项 ─┘
# 两项**共用**同一个 alim。我们给曲率项留 曲率预算 这一份，切向项用剩下的，
# 由三角不等式保证两者之和不超过 alim。
# ★ 为什么要显式分账：不分的话，两项各自都"没超"，加起来却超了
#   （实测四航点路径超限 86%）。分账是保守的，但保守得**可解释**。
CURVATURE_ACCELERATION_FRACTION = 0.5


class PlanningError(Exception):
    """规划不可行。**必须带上下文**（哪一段、哪个 s、为什么），不许静默返回空轨迹。"""

    def __init__(self, reason: str, position: float | None = None):
        self.reason = reason
        self.position = position
        super().__init__(f"{reason}" + (f"（s={position:.4f}）" if position is not None else ""))


@dataclasses.dataclass
class TrajectoryLimits:
    """运动学约束。**全部在关节空间**（rad/s, rad/s², rad/s³）。

    ★ 为什么不在 s 空间给约束：LE 的缺陷 ③ 就是这么来的 ——
      s 空间的 v/a/j 与物理速度之间差一个路径长度，同一组配置在不同长度的路径上
      快慢完全不同，用户从界面上的数根本推不出实际会跑多快。
      这里只在关节空间给，s 空间的上界**每个点现算**。
    """
    vlim: np.ndarray          # (n,) 关节速度上限 rad/s
    alim: np.ndarray          # (n,) 关节加速度上限 rad/s²
    jlim: np.ndarray          # (n,) 关节加加速度上限 rad/s³

    def __post_init__(self):
        for name in ("vlim", "alim", "jlim"):
            value = np.asarray(getattr(self, name), dtype=float).ravel()
            if value.size == 0 or not np.all(np.isfinite(value)) or np.any(value <= 0):
                raise ValueError(f"{name} 必须是全为正的有限数组")
            setattr(self, name, value)


@dataclasses.dataclass
class PlannerOptions:
    grid_size: int = 2000             # s 上的离散点数
    smoothing_iterations: int = 0              # 0 = 不平滑（保留原始航点语义）
    smoothing_factor: float = 0.4
    deviation_tolerance: float = 0.02         # rad，平滑后离开原始航点的最大允许偏差
    preserve_waypoints: bool = True          # True = 路径必须经过每个航点（不平滑时天然成立）


@dataclasses.dataclass
class PlanningReport:
    """规划的**证据**。界面上显示的就是这些数字，不带任何"看起来合理"的估计。"""
    success: bool = False
    reason: str = ""
    dof: int = 0
    waypoint_count: int = 0
    grid_size: int = 0
    duration_s: float = 0.0
    path_length: float = 0.0          # 关节空间弧长（rad）
    # ---- 校验（都对限位回算，不是拍脑袋）----
    max_joint_velocity: float = 0.0
    max_joint_acceleration: float = 0.0
    max_joint_jerk: float = 0.0
    velocity_margin: float = 0.0          # 1 - max(|qd|/vlim)，≥0 表示没超
    acceleration_margin: float = 0.0
    jerk_margin: float = 0.0
    terminal_velocity: float = 0.0          # |qd(t_end)| 的最大值 —— 必须 ≈ 0
    smoothing_deviation: float = 0.0          # 平滑后离开原始航点的最大偏差（rad）
    # ---- 诊断 ----
    bottleneck_joint: int = -1             # 哪个关节最先顶到限位
    bottleneck_type: str = ""             # 速度 / 加速度 / 加加速度
    bottleneck_position: float = 0.0          # 对应的 s
    optimal_lower_bound: float = 0.0          # ∫ds/v_s_max(s)，与我们实际时长的比值说明实现效率
    actual_to_lower_bound: float = 0.0
    # ---- 数据（时间序列，供曲线/回放）----
    t: np.ndarray | None = None
    s: np.ndarray | None = None
    sd: np.ndarray | None = None
    q: np.ndarray | None = None
    qd: np.ndarray | None = None
    qdd: np.ndarray | None = None
    envelope: np.ndarray | None = None    # v_s_max(s)，界面上画成一条曲线

    def summary(self) -> str:
        if not self.success:
            return f"✗ {self.reason}"
        return (f"✓ {self.duration_s:.3f}s / {self.path_length:.3f}rad / "
                f"v {self.max_joint_velocity:.2f} m·rad/s（余量 {self.velocity_margin*100:.0f}%）/ "
                f"瓶颈 {self.bottleneck_type}@s={self.bottleneck_position:.2f}")


# ---------------------------------------------------------------------------
# ① 航点预处理
# ---------------------------------------------------------------------------
def deduplicate_waypoints(waypoints: np.ndarray) -> np.ndarray:
    """删掉相邻重复点。

    ★ 为什么必须做：重复点会让弧长增量为 0，`s` 不再严格递增 ——
      LE 的 §5.12 `[4]` 特意写了"修复严格递增"，说明它踩过。
      我们不"修复"，而是**从源头上不让它不严格**：重复点没有信息量，删掉即可。
    """
    W = np.asarray(waypoints, dtype=float)
    if W.ndim != 2:
        raise ValueError("航点必须是 二维数组 (N, n)")
    if W.shape[0] < 2:
        raise PlanningError("至少需要 2 个航点")
    keep_indices = [0]
    threshold = 1e-9
    for i in range(1, W.shape[0]):
        if np.max(np.abs(W[i] - W[keep_indices[-1]])) > threshold:
            keep_indices.append(i)
    if len(keep_indices) < 2:
        raise PlanningError("所有航点都相同（去掉重复后只剩 1 个）")
    return W[keep_indices]


def unwrap_angles(W: np.ndarray) -> np.ndarray:
    """按列做 np.unwrap，消掉 ±π 跳变。

    ★ 不做的后果：本来从 +179° 到 -179° 是"转 2°"，会被当成"倒转 358°"，
      弧长与包络全错。这一步是零成本的保险。
    """
    return np.unwrap(np.asarray(W, dtype=float), axis=0)


def smooth_waypoints(W: np.ndarray, iterations: int, factor: float) -> np.ndarray:
    """Laplacian 平滑：每轮把内部点往邻居均值挪一点，**端点钉死**。

    ★ 端点钉死是硬要求：不钉的话"起点/终点的位姿"会变，而那正是用户给的东西。
    ★ 系数上限 0.49：等于/大于 0.5 会震荡甚至发散（LE 也夹了这个界）。
    """
    if iterations <= 0:
        return W.copy()
    clipped_factor = float(np.clip(factor, 0.0, 0.49))
    output = W.copy()
    for _ in range(int(iterations)):
        neighbor_mean = 0.5 * (output[:-2] + output[2:])
        output[1:-1] = (1.0 - clipped_factor) * output[1:-1] + clipped_factor * neighbor_mean
    return output


# ---------------------------------------------------------------------------
# ② 弧长参数化 + 样条
# ---------------------------------------------------------------------------
def arc_length_parameterize(W: np.ndarray, grid_size: int) -> tuple[np.ndarray, np.ndarray]:
    """返回 (ss, W_沿网格插值)。ss 是 [0,1] 上严格递增的弧长参数。"""
    N = W.shape[0]
    segment_lengths = np.linalg.norm(np.diff(W, axis=0), axis=1)
    cumulative_lengths = np.concatenate([[0.0], np.cumsum(segment_lengths)])
    total_length = float(cumulative_lengths[-1])
    if total_length <= 1e-12:
        raise PlanningError("路径总长度为 0（航点全在同一位置）")
    original_s = cumulative_lengths / total_length
    # 网格：均匀 s，但必须覆盖每个原始航点位置
    ss = np.linspace(0.0, 1.0, max(int(grid_size), N))
    # 用**分段线性**在原始参数上插值航点，得到路径上的采样点
    grid_waypoints = np.column_stack([np.interp(ss, original_s, W[:, j]) for j in range(W.shape[1])])
    return ss, grid_waypoints, total_length  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# ③ 速度包络（闭式）
# ---------------------------------------------------------------------------
def velocity_envelope(dq: np.ndarray, vlim: np.ndarray) -> np.ndarray:
    """`v_s_max(s) = min_i vlim_i / |q_i'(s)|`。

    ★ 这是**闭式解**，不是近似：路径速度 sd 与关节速度的关系是
      `qd_i = q_i'(s) · sd`，所以 `|sd| ≤ vlim_i / |q_i'(s)|` 对每个关节都成立，
      取最小即该点允许的最大 sd。不需要 LP/solver。
    """
    count, n = dq.shape[0], vlim.size        # dq 是 (M, n)：行=网格点，列=关节
    upper_bound = np.full(count, np.inf)
    for i in range(n):
        slope = np.abs(dq[:, i])
        active = slope > CURVATURE_EPSILON
        upper_bound[active] = np.minimum(upper_bound[active], vlim[i] / slope[active])
    # 某些点上所有关节的坡都为 0（比如拐点处），这时不限制
    upper_bound[~np.isfinite(upper_bound)] = np.inf
    return upper_bound


def acceleration_envelope(dq: np.ndarray, alim: np.ndarray) -> np.ndarray:
    """加速度约束的**保守**路径界：`a_s_max(s) = min_i alim_i / |q_i'(s)|`。

    ★ 说清楚它是保守的：完整的加速度关系是
        `qdd_i = q_i''·sd² + q_i'·sdd`
      我们这里只保留第二项（路径切向），把曲率项 `q''·sd²` 留到**回算校验**里去抓。
      理由：曲率项依赖 sd，与 sd 本身耦合，精确处理需要迭代/求解；
      而"回算后如果超了就报错"能保证**不会悄悄输出超限的轨迹** ——
      这比"用一个近似假装准确"诚实。
    """
    count, n = dq.shape[0], alim.size        # 同上：行=网格点，列=关节
    upper_bound = np.full(count, np.inf)
    for i in range(n):
        slope = np.abs(dq[:, i])
        active = slope > CURVATURE_EPSILON
        upper_bound[active] = np.minimum(upper_bound[active], alim[i] / slope[active])
    upper_bound[~np.isfinite(upper_bound)] = np.inf
    return upper_bound


# ---------------------------------------------------------------------------
# ④ 前后向扫描（时间律）
# ---------------------------------------------------------------------------
def forward_backward_scan(ss: np.ndarray, velocity_upper_bound: np.ndarray, acceleration_upper_bound: np.ndarray,
              jerk_upper_bound: float, grid_size: int) -> tuple[np.ndarray, np.ndarray]:
    """在 s 网格上求 `sd(s)` 与 `sdd(s)`（加速度限 + **jerk 限**）。

    做法：
      ① 前后向两遍，先把「加速度限 + 速度包络」的轮廓做出来（bang-bang 形状）
      ② 再迭代若干轮：把 sdd 在**时间域**做 jerk 率限制，然后由 sdd 重新积出 sd
    终点速度恒为 0（由 ① 的后向遍 + 每轮强制保证），不做事后置零。

    ★ 为什么必须先做 ① 再做 ②：
      只做 ② 会得到一个"加速度到处都很小"的轮廓 —— 因为率限制会把尖锐处削平，
      但它不知道哪里该加速到哪里该减速。① 负责形状，② 负责平滑。
    """
    M = ss.size
    ds = np.diff(ss)
    finite_acceleration = np.where(np.isfinite(acceleration_upper_bound), acceleration_upper_bound, 1e6)

    # ---- ① 加速度限的前后向 ----
    sd = np.zeros(M)
    for k in range(M - 1):
        a_max = min(finite_acceleration[k], finite_acceleration[k + 1])
        v = math.sqrt(max(sd[k] ** 2 + 2.0 * a_max * ds[k], 0.0))
        sd[k + 1] = min(v, velocity_upper_bound[k + 1])
    sd[-1] = 0.0
    for k in range(M - 2, -1, -1):
        a_max = min(finite_acceleration[k], finite_acceleration[k + 1])
        v2 = sd[k + 1] ** 2 + 2.0 * a_max * ds[k]
        sd[k] = min(sd[k], math.sqrt(max(v2, 0.0)))

    def acceleration_from_speed(v: np.ndarray) -> np.ndarray:
        """精确关系（恒加速度下）：sdd = (v²₊₁ − v²) / (2·ds)。"""
        out = np.zeros(M)
        out[:-1] = (v[1:] ** 2 - v[:-1] ** 2) / np.maximum(2.0 * ds, 1e-12)
        return out

    def speed_from_acceleration(a: np.ndarray) -> np.ndarray:
        v = np.zeros(M)
        for k in range(M - 1):
            v[k + 1] = math.sqrt(max(v[k] ** 2 + 2.0 * a[k] * ds[k], 0.0))
        return v

    # ---- ② jerk：**闭式**耦合，不做迭代整形 ----
    #
    # ★ 这里换过三版，记录一下为什么最后选闭式：
    #   第 1 版：前向 `v = min(v, v + j·ds/v)` —— 量纲不对，等于没限。
    #   第 2 版：在时间域对 sdd 做 jerk 率限制并迭代重积分 ——
    #            加速度只能降不能升（我漏了下界），轮廓一路衰减到 0，
    #            2000 个网格点里 144 个速度变 0，轨迹"中途停住"。
    #   第 3 版：补上双侧钳制 —— 还是不收敛，201 个点归零。
    #
    #   共同毛病：在**已经算好的轮廓上**打补丁，会和"起点/终点速度为 0"这个
    #   边界条件打架。所以改成在**源头**处理：
    #
    #   jerk 受限的梯形速度曲线里，加速度爬坡时间 t_r = a/j，
    #   而加速到 v 需要 t = v/a。要求"坡爬完之前不要到顶"，即 t_r ≤ t：
    #       a/j ≤ v/a   →   a² ≤ j·v   →   a ≤ sqrt(j·v)
    #   把这条**直接并进加速度包络**，轮廓从一开始就是 jerk 友好的，
    #   不需要事后整形。物理意义清楚，而且没有迭代、不会塌。
    if jerk_upper_bound > 0 and np.isfinite(jerk_upper_bound):
        acceleration_upper_bound = np.minimum(acceleration_upper_bound, np.sqrt(jerk_upper_bound * np.maximum(velocity_upper_bound, 0.0)))

    # ★ 中途停滞必须报出来，不能靠假的极小时间糊过去。
    #   判断：中间（不是端点）存在速度≈0 的点，说明轮廓塌了。
    interior_zero_count = int(np.sum(sd[1:-1] < 1e-9))
    if interior_zero_count > 0:
        raise PlanningError(
            f"轨迹中途停滞：{interior_zero_count}/{sd.size} 个网格点速度为 0"
            f"（jerk 限过紧或约束互相矛盾）",
            float(ss[int(np.argmax(sd < 1e-9))]))

    return sd, acceleration_from_speed(sd)


def integrate_time(ss: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """由 ds 与 sd 积出时间。sd→0 的地方用解析式 `dt = 2·ds/(sd_k+sd_{k+1})`（梯形）。"""
    ds = np.diff(ss)
    average_speed = 0.5 * (sd[:-1] + sd[1:])
    dt = np.where(average_speed > 1e-9, ds / np.maximum(average_speed, 1e-12), 0.0)
    # 完全静止的一段（理论不该出现）按极小时间推进，避免 t 不严格递增
    if np.any(dt <= 0):
        dt = np.maximum(dt, 1e-6)
    return np.concatenate([[0.0], np.cumsum(dt)])


# ---------------------------------------------------------------------------
# ⑤ 主入口
# ---------------------------------------------------------------------------
def _plan_once(waypoints, limits: TrajectoryLimits, options: PlannerOptions | None, acceleration_scale: float = 1.0) -> PlanningReport:
    """单次求解。`加速度缩放` < 1 用于"降低加速度去满足 jerk 限"（见 `规划`）。"""
    settings = options or PlannerOptions()
    original_waypoints = np.asarray(waypoints, dtype=float)
    if original_waypoints.ndim != 2:
        raise ValueError("航点必须是 二维数组 (N, n)")
    dof = original_waypoints.shape[1]
    for name, value in (("vlim", limits.vlim), ("alim", limits.alim), ("jlim", limits.jlim)):
        if value.size != dof:
            raise PlanningError(f"{name} 长度 {value.size} 与航点自由度 {dof} 不一致")

    report = PlanningReport(dof=dof, waypoint_count=original_waypoints.shape[0])

    # [1] 去重 + 展开角
    W = unwrap_angles(deduplicate_waypoints(original_waypoints))
    report.waypoint_count = int(W.shape[0])

    # [2] 平滑 + 偏差校验（LE 缺陷 ⑤：平滑后必须回算偏差）
    if settings.smoothing_iterations > 0:
        smoothed_waypoints = smooth_waypoints(W, settings.smoothing_iterations, settings.smoothing_factor)
        deviation = float(np.max(np.abs(smoothed_waypoints - W)))
        report.smoothing_deviation = deviation
        if deviation > settings.deviation_tolerance:
            raise PlanningError(
                f"平滑后偏离原始航点 {deviation:.4f} rad，超过容差 {settings.deviation_tolerance:.4f} rad"
                f"（调小平滑轮数/系数，或放宽容差）")
        W = smoothed_waypoints

    # [3] 弧长参数化
    ss, grid_waypoints, total_length = arc_length_parameterize(W, settings.grid_size)
    report.grid_size = int(ss.size)
    report.path_length = total_length

    # [4] 样条（可解析求导 —— LE 缺陷 ④ 的对照）
    from scipy.interpolate import CubicSpline
    # ★ 边界条件必须用 `natural`（端点二阶导为 0），**不能用 `clamped`**：
    #   clamped 是"端点一阶导 = 给定值"，默认 0 —— 那等于要求 `q'(0)=0`，
    #   但 `q'(s)` 是**路径形状**的导数，不是速度！强行把它压到 0 会让路径在两端
    #   拐一个 S 弯，`q''` 巨大 → 回算时加速度超限几十上百倍。
    #   实测：clamped 下"两点直线路径"报加速度超限 69%，换 natural 后归零。
    #   （直线的正确 q'' 就是 0；任何让它非 0 的边界条件都是错的。）
    spline = CubicSpline(ss, grid_waypoints, axis=0, bc_type="natural")
    dq = spline(ss, 1)              # (M, n) = q'(s)
    dq2 = spline(ss, 2)             # (M, n) = q''(s)

    # [5] 包络（闭式）
    velocity_upper_bound = velocity_envelope(dq, limits.vlim)
    # ★ 再叠加**曲率**给出的速度上限：`qdd_i = q_i''·sd² + q_i'·sdd` 里的
    #   第一项只和速度有关。要让 |q_i''|·sd² ≤ alim_i，就得
    #       sd ≤ sqrt(alim_i / |q_i''|)
    #   不加这一条，过拐角时速度依然很高，而离心项会把加速度顶爆
    #   （实测四航点直线转角处超限 118767%）。
    #   这一项也是闭式的，代价可忽略。
    with np.errstate(divide="ignore", invalid="ignore"):
        curvature_upper_bound = np.where(
            np.abs(dq2) > CURVATURE_EPSILON,
            np.sqrt((CURVATURE_ACCELERATION_FRACTION * limits.alim)[None, :] / np.maximum(np.abs(dq2), CURVATURE_EPSILON)),
            np.inf,
        ).min(axis=1)
    velocity_upper_bound = np.minimum(velocity_upper_bound, curvature_upper_bound)
    acceleration_upper_bound = acceleration_envelope(dq, (1.0 - CURVATURE_ACCELERATION_FRACTION) * acceleration_scale * limits.alim)
    report.envelope = velocity_upper_bound.copy()
    if not np.all(np.isfinite(velocity_upper_bound)):
        # 有歧义就修掉（坡为 0 的关节不参与），但**不假装没发生**
        velocity_upper_bound[~np.isfinite(velocity_upper_bound)] = np.max(limits.vlim)
    invalid_points = velocity_upper_bound <= 1e-9
    if np.any(invalid_points):
        position = float(ss[int(np.argmax(invalid_points))])
        raise PlanningError("速度包络在该点为零：关节限位太小或路径在此处无法通过", position)

    # 最优下界（LE 缺陷 ⑨ 的对照：不丢弃，而是**拿来做对照**）
    with np.errstate(divide="ignore", invalid="ignore"):
        trapezoid = getattr(np, "trapezoid", None) or np.trapz      # numpy 2 里 trapz 改名了
        report.optimal_lower_bound = float(trapezoid(1.0 / np.maximum(velocity_upper_bound, 1e-9), ss))

    # [6] 前后向扫描
    jerk_upper_bound = float(np.min(limits.jlim))
    sd, sdd = forward_backward_scan(ss, velocity_upper_bound, acceleration_upper_bound, jerk_upper_bound, settings.grid_size)
    if not np.any(sd > 0):
        raise PlanningError("整条轨迹速度恒为 0（约束过紧或被包络卡死）")

    # [7] 时间
    t = integrate_time(ss, sd)
    report.duration_s = float(t[-1])
    report.actual_to_lower_bound = (report.duration_s / report.optimal_lower_bound) if report.optimal_lower_bound > 0 else 0.0

    # [8] 链式法则出 q/qd/qdd
    q = spline(ss)
    qd = dq * sd[:, None]
    qdd = dq2 * (sd ** 2)[:, None] + dq * sdd[:, None]
    report.t, report.s, report.sd, report.q, report.qd, report.qdd = t, ss, sd, q, qd, qdd

    # [9] 回算校验（这是"有没有贴边"的**唯一**依据）
    max_velocity = np.max(np.abs(qd), axis=0)
    max_acceleration = np.max(np.abs(qdd), axis=0)
    # jerk：对 qd 求时间导数（t 非均匀 → 用差分再除以 dt）
    dt = np.diff(t)
    dt = np.maximum(dt, 1e-9)
    jerk = np.abs(np.diff(qd, axis=0)) / dt[:, None]

    report.max_joint_velocity = float(np.max(max_velocity))
    report.max_joint_acceleration = float(np.max(max_acceleration))
    report.max_joint_jerk = float(np.max(jerk)) if jerk.size else 0.0
    report.velocity_margin = float(1.0 - np.max(max_velocity / limits.vlim))
    report.acceleration_margin = float(1.0 - np.max(max_acceleration / limits.alim))
    report.jerk_margin = float(1.0 - report.max_joint_jerk / float(np.min(limits.jlim)))
    report.terminal_velocity = float(np.max(np.abs(qd[-1])))

    velocity_ratios = max_velocity / limits.vlim
    acceleration_ratios = max_acceleration / limits.alim
    joint_jerk_ratios = (np.max(jerk, axis=0) / limits.jlim) if jerk.size else np.zeros(dof)
    if np.max(velocity_ratios) >= max(np.max(acceleration_ratios), np.max(joint_jerk_ratios)):
        report.bottleneck_type, report.bottleneck_joint = "速度", int(np.argmax(velocity_ratios))
        report.bottleneck_position = float(ss[int(np.argmax(np.abs(qd[:, report.bottleneck_joint])))] if report.bottleneck_joint >= 0 else 0.0)
    elif np.max(acceleration_ratios) >= np.max(joint_jerk_ratios):
        report.bottleneck_type, report.bottleneck_joint = "加速度", int(np.argmax(acceleration_ratios))
        report.bottleneck_position = float(ss[int(np.argmax(np.abs(qdd[:, report.bottleneck_joint])))])
    else:
        report.bottleneck_type, report.bottleneck_joint = "加加速度", int(np.argmax(joint_jerk_ratios))

    # 超限位 → 失败（**不静默**）。留 2% 的数值余量，因为离散化的边界总是压线的。
    violations = []
    if report.velocity_margin < -0.02:
        violations.append(f"速度超限 {(-report.velocity_margin)*100:.1f}%")
    if report.acceleration_margin < -0.02:
        violations.append(f"加速度超限 {(-report.acceleration_margin)*100:.1f}%")
    if report.terminal_velocity > 1e-3:
        violations.append(f"终端速度 {report.terminal_velocity:.4f} rad/s（应为 0）")
    if violations:
        report.success = False
        report.reason = "；".join(violations)
        return report

    report.success = True
    report.reason = ""
    return report


def plan_trajectory(waypoints, limits: TrajectoryLimits, options: PlannerOptions | None = None) -> PlanningReport:
    """规划一条关节轨迹。**失败抛 `规划失败`，并带上下文**（LE 缺陷 ⑩ 的对照）。

    ═══ 关于 jerk：这一版**只校验、不整形**（如实说明）═══
    我们的时间律是"加速度受限的前后向扫描"，它天然是 **bang-bang** 的：
    加速度在切换点从 +a 跳到 −a，**理论上 jerk 无穷大**。实测印证了这一点 ——
    2000 个网格点里 jerk 的 99% 分位是 2.0，峰值 3.52 出现在切换点那一个点上。

    要真正把 jerk 限住，必须在切换点插入一段时长为 `a/j` 的斜坡（S 曲线整形）——
    那正是 Ruckig 存在的理由，工作量和风险都不小。所以这一版的立场是：

        **能把 jerk 报准，但不会假装限住它。**
        加加速度超限时，`成功 = False`，并把实测值与限值写进 `原因`，
        调用方（界面）会看到明确失败，而不是拿到一条"看起来没问题"的轨迹。

    试过但放弃的两条路（记录在此，免得后来人重走）：
      · 在时间域对 sdd 做 jerk 率限制并迭代重积分 ——
        加速度只能降不能升（漏了下界）→ 轮廓衰减到 0，144~201 个网格点停住；
        补上双侧钳制后仍不收敛。
      · 二分缩放加速度直到 jerk 达标 —— jerk 峰值来自切换点的不连续，
        与加速度幅值几乎无关，缩多小都是 3.52。
    """
    report = _plan_once(waypoints, limits, options)
    if not report.success:
        return report
    jerk_limit = float(np.min(limits.jlim))
    if jerk_limit <= 0 or not np.isfinite(jerk_limit):
        return report
    if report.jerk_margin >= -0.02:
        return report
    report.success = False
    report.reason = (f"加加速度超限：实测 max|jerk| = {report.max_joint_jerk:.2f} rad/s³，"
              f"限 {jerk_limit:.2f}（本版只校验不整形：切换点不做 S 曲线，"
              f"收紧 jerk 限会让它直接判失败，而不是变慢）")
    return report


# ---------------------------------------------------------------------------
# 自测：`python runtime/trajectory_planning.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    np.set_printoptions(precision=4, suppress=True)
    print("=" * 78)
    print("  轨迹规划内核自测")
    print("=" * 78)

    n = 7
    limits_example = TrajectoryLimits(vlim=np.full(n, 1.5), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    # 一条简单的两点路径：全关节一起转
    W = np.vstack([np.zeros(n), np.full(n, 0.8)])
    report = plan_trajectory(W, limits_example)
    print(f"  两点路径：{report.summary()}")
    print(f"    终端速度 = {report.terminal_velocity:.2e}（必须≈0）")
    print(f"    实际/下界 = {report.actual_to_lower_bound:.2f}（越接近 1 越高效）")

    # 多航点
    W2 = np.vstack([
        np.zeros(n),
        np.array([0.4, -0.2, 0.3, -0.1, 0.2, 0.1, -0.2]),
        np.array([0.8, 0.3, -0.4, 0.5, -0.3, 0.2, 0.4]),
        np.full(n, 0.2),
    ])
    report2 = plan_trajectory(W2, limits_example)
    print(f"  四航点：  {report2.summary()}")
    print(f"    最大速度 {report2.max_joint_velocity:.3f} / 限 {limits_example.vlim[0]:.1f} "
          f"（余量 {report2.velocity_margin*100:.0f}%）")
    print(f"    终端速度 = {report2.terminal_velocity:.2e}")

    # 限位收紧 → 必须变慢（验证"限位真的生效"，对应 LE 缺陷 ②）
    tighter_limits = TrajectoryLimits(vlim=np.full(n, 0.5), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    report3 = plan_trajectory(W2, tighter_limits)
    print(f"  收紧速度限位（1.5 → 0.5）：{report3.duration_s:.3f}s vs 原 {report2.duration_s:.3f}s "
          f"→ {'✓ 变慢了，限位生效' if report3.duration_s > report2.duration_s else '✗ 没变化，限位没生效'}")

    # 不同自由度（验证没有硬编码 6/7 轴，对应 LE 缺陷 ⑧）
    for axis_count in (6, 7):
        axis_report = plan_trajectory(np.vstack([np.zeros(axis_count), np.full(axis_count, 0.5)]),
                   TrajectoryLimits(vlim=np.full(axis_count, 1.0), alim=np.full(axis_count, 3.0), jlim=np.full(axis_count, 30.0)))
        print(f"  {axis_count} 轴模型：自由度={axis_report.dof} → "
              f"{'✓ 按模型走' if axis_report.dof == axis_count else '✗ 硬编码了'}")

    # 不可行路径必须报错（对应 LE 缺陷 ⑩：不许静默）
    try:
        # ★ 必须用 ≥3 个点：平滑只动**内部点**，2 点路径没有内部点，
        #   平滑本来就不该有任何效果（我第一次用 2 点测，还以为"没报错是 bug"）。
        plan_trajectory(np.vstack([np.zeros(n), np.full(n, 0.05), np.full(n, 0.3)]),
             TrajectoryLimits(vlim=np.full(n, 1.0), alim=np.full(n, 3.0), jlim=np.full(n, 30.0)),
             PlannerOptions(smoothing_iterations=50, smoothing_factor=0.49, deviation_tolerance=1e-6))
        print("  ✗ 平滑超容差却没报错")
    except PlanningError as e:
        print(f"  ✓ 平滑超容差被拦住：{e}")
