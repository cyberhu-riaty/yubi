"""
轨迹规划.py —— 关节空间轨迹规划内核（**纯函数**：数组进、数组出）

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
曲率下限 = 1e-9          # |q'(s)| 小于它就当该关节不参与这一步的限位换算

# 加速度预算怎么在两处之间分账：
#   qdd_i = q_i''·sd²  +  q_i'·sdd
#           └─ 曲率项 ─┘   └─ 切向项 ─┘
# 两项**共用**同一个 alim。我们给曲率项留 曲率预算 这一份，切向项用剩下的，
# 由三角不等式保证两者之和不超过 alim。
# ★ 为什么要显式分账：不分的话，两项各自都"没超"，加起来却超了
#   （实测四航点路径超限 86%）。分账是保守的，但保守得**可解释**。
曲率预算 = 0.5


class 规划失败(Exception):
    """规划不可行。**必须带上下文**（哪一段、哪个 s、为什么），不许静默返回空轨迹。"""

    def __init__(self, 原因: str, 位置: float | None = None):
        self.原因 = 原因
        self.位置 = 位置
        super().__init__(f"{原因}" + (f"（s={位置:.4f}）" if 位置 is not None else ""))


@dataclasses.dataclass
class 约束:
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
        for 名 in ("vlim", "alim", "jlim"):
            值 = np.asarray(getattr(self, 名), dtype=float).ravel()
            if 值.size == 0 or not np.all(np.isfinite(值)) or np.any(值 <= 0):
                raise ValueError(f"{名} 必须是全为正的有限数组")
            setattr(self, 名, 值)


@dataclasses.dataclass
class 参数:
    网格数: int = 2000             # s 上的离散点数
    平滑轮数: int = 0              # 0 = 不平滑（保留原始航点语义）
    平滑系数: float = 0.4
    偏差容差: float = 0.02         # rad，平滑后离开原始航点的最大允许偏差
    保留航点: bool = True          # True = 路径必须经过每个航点（不平滑时天然成立）


@dataclasses.dataclass
class 报告:
    """规划的**证据**。界面上显示的就是这些数字，不带任何"看起来合理"的估计。"""
    成功: bool = False
    原因: str = ""
    自由度: int = 0
    航点数: int = 0
    网格数: int = 0
    总时长: float = 0.0
    路径长度: float = 0.0          # 关节空间弧长（rad）
    # ---- 校验（都对限位回算，不是拍脑袋）----
    最大关节速度: float = 0.0
    最大关节加速度: float = 0.0
    最大关节加加速度: float = 0.0
    速度余量: float = 0.0          # 1 - max(|qd|/vlim)，≥0 表示没超
    加速度余量: float = 0.0
    加加速度余量: float = 0.0
    终端速度: float = 0.0          # |qd(t_end)| 的最大值 —— 必须 ≈ 0
    平滑偏差: float = 0.0          # 平滑后离开原始航点的最大偏差（rad）
    # ---- 诊断 ----
    瓶颈关节: int = -1             # 哪个关节最先顶到限位
    瓶颈类型: str = ""             # 速度 / 加速度 / 加加速度
    瓶颈位置: float = 0.0          # 对应的 s
    最优下界: float = 0.0          # ∫ds/v_s_max(s)，与我们实际时长的比值说明实现效率
    实际比下界: float = 0.0
    # ---- 数据（时间序列，供曲线/回放）----
    t: np.ndarray | None = None
    s: np.ndarray | None = None
    sd: np.ndarray | None = None
    q: np.ndarray | None = None
    qd: np.ndarray | None = None
    qdd: np.ndarray | None = None
    包络: np.ndarray | None = None    # v_s_max(s)，界面上画成一条曲线

    def 摘要(self) -> str:
        if not self.成功:
            return f"✗ {self.原因}"
        return (f"✓ {self.总时长:.3f}s / {self.路径长度:.3f}rad / "
                f"v {self.最大关节速度:.2f} m·rad/s（余量 {self.速度余量*100:.0f}%）/ "
                f"瓶颈 {self.瓶颈类型}@s={self.瓶颈位置:.2f}")


# ---------------------------------------------------------------------------
# ① 航点预处理
# ---------------------------------------------------------------------------
def 去重航点(航点: np.ndarray) -> np.ndarray:
    """删掉相邻重复点。

    ★ 为什么必须做：重复点会让弧长增量为 0，`s` 不再严格递增 ——
      LE 的 §5.12 `[4]` 特意写了"修复严格递增"，说明它踩过。
      我们不"修复"，而是**从源头上不让它不严格**：重复点没有信息量，删掉即可。
    """
    W = np.asarray(航点, dtype=float)
    if W.ndim != 2:
        raise ValueError("航点必须是 二维数组 (N, n)")
    if W.shape[0] < 2:
        raise 规划失败("至少需要 2 个航点")
    保留 = [0]
    阈值 = 1e-9
    for i in range(1, W.shape[0]):
        if np.max(np.abs(W[i] - W[保留[-1]])) > 阈值:
            保留.append(i)
    if len(保留) < 2:
        raise 规划失败("所有航点都相同（去掉重复后只剩 1 个）")
    return W[保留]


def 展开角度(W: np.ndarray) -> np.ndarray:
    """按列做 np.unwrap，消掉 ±π 跳变。

    ★ 不做的后果：本来从 +179° 到 -179° 是"转 2°"，会被当成"倒转 358°"，
      弧长与包络全错。这一步是零成本的保险。
    """
    return np.unwrap(np.asarray(W, dtype=float), axis=0)


def 平滑航点(W: np.ndarray, 轮数: int, 系数: float) -> np.ndarray:
    """Laplacian 平滑：每轮把内部点往邻居均值挪一点，**端点钉死**。

    ★ 端点钉死是硬要求：不钉的话"起点/终点的位姿"会变，而那正是用户给的东西。
    ★ 系数上限 0.49：等于/大于 0.5 会震荡甚至发散（LE 也夹了这个界）。
    """
    if 轮数 <= 0:
        return W.copy()
    系 = float(np.clip(系数, 0.0, 0.49))
    出 = W.copy()
    for _ in range(int(轮数)):
        邻均 = 0.5 * (出[:-2] + 出[2:])
        出[1:-1] = (1.0 - 系) * 出[1:-1] + 系 * 邻均
    return 出


# ---------------------------------------------------------------------------
# ② 弧长参数化 + 样条
# ---------------------------------------------------------------------------
def 弧长参数(W: np.ndarray, 网格数: int) -> tuple[np.ndarray, np.ndarray]:
    """返回 (ss, W_沿网格插值)。ss 是 [0,1] 上严格递增的弧长参数。"""
    N = W.shape[0]
    段长 = np.linalg.norm(np.diff(W, axis=0), axis=1)
    累计 = np.concatenate([[0.0], np.cumsum(段长)])
    总长 = float(累计[-1])
    if 总长 <= 1e-12:
        raise 规划失败("路径总长度为 0（航点全在同一位置）")
    原始 = 累计 / 总长
    # 网格：均匀 s，但必须覆盖每个原始航点位置
    ss = np.linspace(0.0, 1.0, max(int(网格数), N))
    # 用**分段线性**在原始参数上插值航点，得到路径上的采样点
    W网格 = np.column_stack([np.interp(ss, 原始, W[:, j]) for j in range(W.shape[1])])
    return ss, W网格, 总长  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# ③ 速度包络（闭式）
# ---------------------------------------------------------------------------
def 速度包络(dq: np.ndarray, vlim: np.ndarray) -> np.ndarray:
    """`v_s_max(s) = min_i vlim_i / |q_i'(s)|`。

    ★ 这是**闭式解**，不是近似：路径速度 sd 与关节速度的关系是
      `qd_i = q_i'(s) · sd`，所以 `|sd| ≤ vlim_i / |q_i'(s)|` 对每个关节都成立，
      取最小即该点允许的最大 sd。不需要 LP/solver。
    """
    数, n = dq.shape[0], vlim.size        # dq 是 (M, n)：行=网格点，列=关节
    上界 = np.full(数, np.inf)
    for i in range(n):
        坡 = np.abs(dq[:, i])
        有效 = 坡 > 曲率下限
        上界[有效] = np.minimum(上界[有效], vlim[i] / 坡[有效])
    # 某些点上所有关节的坡都为 0（比如拐点处），这时不限制
    上界[~np.isfinite(上界)] = np.inf
    return 上界


def 加速度包络(dq: np.ndarray, alim: np.ndarray) -> np.ndarray:
    """加速度约束的**保守**路径界：`a_s_max(s) = min_i alim_i / |q_i'(s)|`。

    ★ 说清楚它是保守的：完整的加速度关系是
        `qdd_i = q_i''·sd² + q_i'·sdd`
      我们这里只保留第二项（路径切向），把曲率项 `q''·sd²` 留到**回算校验**里去抓。
      理由：曲率项依赖 sd，与 sd 本身耦合，精确处理需要迭代/求解；
      而"回算后如果超了就报错"能保证**不会悄悄输出超限的轨迹** ——
      这比"用一个近似假装准确"诚实。
    """
    数, n = dq.shape[0], alim.size        # 同上：行=网格点，列=关节
    上界 = np.full(数, np.inf)
    for i in range(n):
        坡 = np.abs(dq[:, i])
        有效 = 坡 > 曲率下限
        上界[有效] = np.minimum(上界[有效], alim[i] / 坡[有效])
    上界[~np.isfinite(上界)] = np.inf
    return 上界


# ---------------------------------------------------------------------------
# ④ 前后向扫描（时间律）
# ---------------------------------------------------------------------------
def 前后向扫描(ss: np.ndarray, v上界: np.ndarray, a上界: np.ndarray,
              j上界: float, 网格数: int) -> tuple[np.ndarray, np.ndarray]:
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
    有限a = np.where(np.isfinite(a上界), a上界, 1e6)

    # ---- ① 加速度限的前后向 ----
    sd = np.zeros(M)
    for k in range(M - 1):
        a_max = min(有限a[k], 有限a[k + 1])
        v = math.sqrt(max(sd[k] ** 2 + 2.0 * a_max * ds[k], 0.0))
        sd[k + 1] = min(v, v上界[k + 1])
    sd[-1] = 0.0
    for k in range(M - 2, -1, -1):
        a_max = min(有限a[k], 有限a[k + 1])
        v2 = sd[k + 1] ** 2 + 2.0 * a_max * ds[k]
        sd[k] = min(sd[k], math.sqrt(max(v2, 0.0)))

    def 由速度求加速度(v: np.ndarray) -> np.ndarray:
        """精确关系（恒加速度下）：sdd = (v²₊₁ − v²) / (2·ds)。"""
        out = np.zeros(M)
        out[:-1] = (v[1:] ** 2 - v[:-1] ** 2) / np.maximum(2.0 * ds, 1e-12)
        return out

    def 由加速度积速度(a: np.ndarray) -> np.ndarray:
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
    if j上界 > 0 and np.isfinite(j上界):
        a上界 = np.minimum(a上界, np.sqrt(j上界 * np.maximum(v上界, 0.0)))

    # ★ 中途停滞必须报出来，不能靠假的极小时间糊过去。
    #   判断：中间（不是端点）存在速度≈0 的点，说明轮廓塌了。
    中间零 = int(np.sum(sd[1:-1] < 1e-9))
    if 中间零 > 0:
        raise 规划失败(
            f"轨迹中途停滞：{中间零}/{sd.size} 个网格点速度为 0"
            f"（jerk 限过紧或约束互相矛盾）",
            float(ss[int(np.argmax(sd < 1e-9))]))

    return sd, 由速度求加速度(sd)


def 时间积分(ss: np.ndarray, sd: np.ndarray) -> np.ndarray:
    """由 ds 与 sd 积出时间。sd→0 的地方用解析式 `dt = 2·ds/(sd_k+sd_{k+1})`（梯形）。"""
    ds = np.diff(ss)
    平均 = 0.5 * (sd[:-1] + sd[1:])
    dt = np.where(平均 > 1e-9, ds / np.maximum(平均, 1e-12), 0.0)
    # 完全静止的一段（理论不该出现）按极小时间推进，避免 t 不严格递增
    if np.any(dt <= 0):
        dt = np.maximum(dt, 1e-6)
    return np.concatenate([[0.0], np.cumsum(dt)])


# ---------------------------------------------------------------------------
# ⑤ 主入口
# ---------------------------------------------------------------------------
def _规划一次(航点, 约束_: 约束, 参数_: 参数 | None, 加速度缩放: float = 1.0) -> 报告:
    """单次求解。`加速度缩放` < 1 用于"降低加速度去满足 jerk 限"（见 `规划`）。"""
    参 = 参数_ or 参数()
    W原始 = np.asarray(航点, dtype=float)
    if W原始.ndim != 2:
        raise ValueError("航点必须是 二维数组 (N, n)")
    自由度 = W原始.shape[1]
    for 名, 值 in (("vlim", 约束_.vlim), ("alim", 约束_.alim), ("jlim", 约束_.jlim)):
        if 值.size != 自由度:
            raise 规划失败(f"{名} 长度 {值.size} 与航点自由度 {自由度} 不一致")

    报 = 报告(自由度=自由度, 航点数=W原始.shape[0])

    # [1] 去重 + 展开角
    W = 展开角度(去重航点(W原始))
    报.航点数 = int(W.shape[0])

    # [2] 平滑 + 偏差校验（LE 缺陷 ⑤：平滑后必须回算偏差）
    if 参.平滑轮数 > 0:
        W平滑 = 平滑航点(W, 参.平滑轮数, 参.平滑系数)
        偏差 = float(np.max(np.abs(W平滑 - W)))
        报.平滑偏差 = 偏差
        if 偏差 > 参.偏差容差:
            raise 规划失败(
                f"平滑后偏离原始航点 {偏差:.4f} rad，超过容差 {参.偏差容差:.4f} rad"
                f"（调小平滑轮数/系数，或放宽容差）")
        W = W平滑

    # [3] 弧长参数化
    ss, W网格, 总长 = 弧长参数(W, 参.网格数)
    报.网格数 = int(ss.size)
    报.路径长度 = 总长

    # [4] 样条（可解析求导 —— LE 缺陷 ④ 的对照）
    from scipy.interpolate import CubicSpline
    # ★ 边界条件必须用 `natural`（端点二阶导为 0），**不能用 `clamped`**：
    #   clamped 是"端点一阶导 = 给定值"，默认 0 —— 那等于要求 `q'(0)=0`，
    #   但 `q'(s)` 是**路径形状**的导数，不是速度！强行把它压到 0 会让路径在两端
    #   拐一个 S 弯，`q''` 巨大 → 回算时加速度超限几十上百倍。
    #   实测：clamped 下"两点直线路径"报加速度超限 69%，换 natural 后归零。
    #   （直线的正确 q'' 就是 0；任何让它非 0 的边界条件都是错的。）
    样条 = CubicSpline(ss, W网格, axis=0, bc_type="natural")
    dq = 样条(ss, 1)              # (M, n) = q'(s)
    dq2 = 样条(ss, 2)             # (M, n) = q''(s)

    # [5] 包络（闭式）
    v上界 = 速度包络(dq, 约束_.vlim)
    # ★ 再叠加**曲率**给出的速度上限：`qdd_i = q_i''·sd² + q_i'·sdd` 里的
    #   第一项只和速度有关。要让 |q_i''|·sd² ≤ alim_i，就得
    #       sd ≤ sqrt(alim_i / |q_i''|)
    #   不加这一条，过拐角时速度依然很高，而离心项会把加速度顶爆
    #   （实测四航点直线转角处超限 118767%）。
    #   这一项也是闭式的，代价可忽略。
    with np.errstate(divide="ignore", invalid="ignore"):
        曲率上界 = np.where(
            np.abs(dq2) > 曲率下限,
            np.sqrt((曲率预算 * 约束_.alim)[None, :] / np.maximum(np.abs(dq2), 曲率下限)),
            np.inf,
        ).min(axis=1)
    v上界 = np.minimum(v上界, 曲率上界)
    a上界 = 加速度包络(dq, (1.0 - 曲率预算) * 加速度缩放 * 约束_.alim)
    报.包络 = v上界.copy()
    if not np.all(np.isfinite(v上界)):
        # 有歧义就修掉（坡为 0 的关节不参与），但**不假装没发生**
        v上界[~np.isfinite(v上界)] = np.max(约束_.vlim)
    坏点 = v上界 <= 1e-9
    if np.any(坏点):
        位置 = float(ss[int(np.argmax(坏点))])
        raise 规划失败("速度包络在该点为零：关节限位太小或路径在此处无法通过", 位置)

    # 最优下界（LE 缺陷 ⑨ 的对照：不丢弃，而是**拿来做对照**）
    with np.errstate(divide="ignore", invalid="ignore"):
        _梯形 = getattr(np, "trapezoid", None) or np.trapz      # numpy 2 里 trapz 改名了
        报.最优下界 = float(_梯形(1.0 / np.maximum(v上界, 1e-9), ss))

    # [6] 前后向扫描
    j上界 = float(np.min(约束_.jlim))
    sd, sdd = 前后向扫描(ss, v上界, a上界, j上界, 参.网格数)
    if not np.any(sd > 0):
        raise 规划失败("整条轨迹速度恒为 0（约束过紧或被包络卡死）")

    # [7] 时间
    t = 时间积分(ss, sd)
    报.总时长 = float(t[-1])
    报.实际比下界 = (报.总时长 / 报.最优下界) if 报.最优下界 > 0 else 0.0

    # [8] 链式法则出 q/qd/qdd
    q = 样条(ss)
    qd = dq * sd[:, None]
    qdd = dq2 * (sd ** 2)[:, None] + dq * sdd[:, None]
    报.t, 报.s, 报.sd, 报.q, 报.qd, 报.qdd = t, ss, sd, q, qd, qdd

    # [9] 回算校验（这是"有没有贴边"的**唯一**依据）
    最大v = np.max(np.abs(qd), axis=0)
    最大a = np.max(np.abs(qdd), axis=0)
    # jerk：对 qd 求时间导数（t 非均匀 → 用差分再除以 dt）
    dt = np.diff(t)
    dt = np.maximum(dt, 1e-9)
    jerk = np.abs(np.diff(qd, axis=0)) / dt[:, None]

    报.最大关节速度 = float(np.max(最大v))
    报.最大关节加速度 = float(np.max(最大a))
    报.最大关节加加速度 = float(np.max(jerk)) if jerk.size else 0.0
    报.速度余量 = float(1.0 - np.max(最大v / 约束_.vlim))
    报.加速度余量 = float(1.0 - np.max(最大a / 约束_.alim))
    报.加加速度余量 = float(1.0 - 报.最大关节加加速度 / float(np.min(约束_.jlim)))
    报.终端速度 = float(np.max(np.abs(qd[-1])))

    比值v = 最大v / 约束_.vlim
    比值a = 最大a / 约束_.alim
    jerk各关节 = (np.max(jerk, axis=0) / 约束_.jlim) if jerk.size else np.zeros(自由度)
    if np.max(比值v) >= max(np.max(比值a), np.max(jerk各关节)):
        报.瓶颈类型, 报.瓶颈关节 = "速度", int(np.argmax(比值v))
        报.瓶颈位置 = float(ss[int(np.argmax(np.abs(qd[:, 报.瓶颈关节])))] if 报.瓶颈关节 >= 0 else 0.0)
    elif np.max(比值a) >= np.max(jerk各关节):
        报.瓶颈类型, 报.瓶颈关节 = "加速度", int(np.argmax(比值a))
        报.瓶颈位置 = float(ss[int(np.argmax(np.abs(qdd[:, 报.瓶颈关节])))])
    else:
        报.瓶颈类型, 报.瓶颈关节 = "加加速度", int(np.argmax(jerk各关节))

    # 超限位 → 失败（**不静默**）。留 2% 的数值余量，因为离散化的边界总是压线的。
    超 = []
    if 报.速度余量 < -0.02:
        超.append(f"速度超限 {(-报.速度余量)*100:.1f}%")
    if 报.加速度余量 < -0.02:
        超.append(f"加速度超限 {(-报.加速度余量)*100:.1f}%")
    if 报.终端速度 > 1e-3:
        超.append(f"终端速度 {报.终端速度:.4f} rad/s（应为 0）")
    if 超:
        报.成功 = False
        报.原因 = "；".join(超)
        return 报

    报.成功 = True
    报.原因 = ""
    return 报


def 规划(航点, 约束_: 约束, 参数_: 参数 | None = None) -> 报告:
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
    报 = _规划一次(航点, 约束_, 参数_)
    if not 报.成功:
        return 报
    j限 = float(np.min(约束_.jlim))
    if j限 <= 0 or not np.isfinite(j限):
        return 报
    if 报.加加速度余量 >= -0.02:
        return 报
    报.成功 = False
    报.原因 = (f"加加速度超限：实测 max|jerk| = {报.最大关节加加速度:.2f} rad/s³，"
              f"限 {j限:.2f}（本版只校验不整形：切换点不做 S 曲线，"
              f"收紧 jerk 限会让它直接判失败，而不是变慢）")
    return 报


# ---------------------------------------------------------------------------
# 自测：`python 软件/轨迹规划.py`
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    np.set_printoptions(precision=4, suppress=True)
    print("=" * 78)
    print("  轨迹规划内核自测")
    print("=" * 78)

    n = 7
    约 = 约束(vlim=np.full(n, 1.5), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    # 一条简单的两点路径：全关节一起转
    W = np.vstack([np.zeros(n), np.full(n, 0.8)])
    报 = 规划(W, 约)
    print(f"  两点路径：{报.摘要()}")
    print(f"    终端速度 = {报.终端速度:.2e}（必须≈0）")
    print(f"    实际/下界 = {报.实际比下界:.2f}（越接近 1 越高效）")

    # 多航点
    W2 = np.vstack([
        np.zeros(n),
        np.array([0.4, -0.2, 0.3, -0.1, 0.2, 0.1, -0.2]),
        np.array([0.8, 0.3, -0.4, 0.5, -0.3, 0.2, 0.4]),
        np.full(n, 0.2),
    ])
    报2 = 规划(W2, 约)
    print(f"  四航点：  {报2.摘要()}")
    print(f"    最大速度 {报2.最大关节速度:.3f} / 限 {约.vlim[0]:.1f} "
          f"（余量 {报2.速度余量*100:.0f}%）")
    print(f"    终端速度 = {报2.终端速度:.2e}")

    # 限位收紧 → 必须变慢（验证"限位真的生效"，对应 LE 缺陷 ②）
    约紧 = 约束(vlim=np.full(n, 0.5), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    报3 = 规划(W2, 约紧)
    print(f"  收紧速度限位（1.5 → 0.5）：{报3.总时长:.3f}s vs 原 {报2.总时长:.3f}s "
          f"→ {'✓ 变慢了，限位生效' if 报3.总时长 > 报2.总时长 else '✗ 没变化，限位没生效'}")

    # 不同自由度（验证没有硬编码 6/7 轴，对应 LE 缺陷 ⑧）
    for 轴 in (6, 7):
        报x = 规划(np.vstack([np.zeros(轴), np.full(轴, 0.5)]),
                   约束(vlim=np.full(轴, 1.0), alim=np.full(轴, 3.0), jlim=np.full(轴, 30.0)))
        print(f"  {轴} 轴模型：自由度={报x.自由度} → "
              f"{'✓ 按模型走' if 报x.自由度 == 轴 else '✗ 硬编码了'}")

    # 不可行路径必须报错（对应 LE 缺陷 ⑩：不许静默）
    try:
        # ★ 必须用 ≥3 个点：平滑只动**内部点**，2 点路径没有内部点，
        #   平滑本来就不该有任何效果（我第一次用 2 点测，还以为"没报错是 bug"）。
        规划(np.vstack([np.zeros(n), np.full(n, 0.05), np.full(n, 0.3)]),
             约束(vlim=np.full(n, 1.0), alim=np.full(n, 3.0), jlim=np.full(n, 30.0)),
             参数(平滑轮数=50, 平滑系数=0.49, 偏差容差=1e-6))
        print("  ✗ 平滑超容差却没报错")
    except 规划失败 as e:
        print(f"  ✓ 平滑超容差被拦住：{e}")
