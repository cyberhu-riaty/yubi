"""
逆解.py —— 笛卡尔航点 → 关节航点（阻尼最小二乘 IK）

═══ 这个模块的位置 ════════════════════════════════════════════════════════
    规划内核（`轨迹规划.py`）是**纯函数**，只认关节航点。
    笛卡尔航点必须在**进内核之前**变成关节航点 —— 那一步就是这里。

═══ 末端执行器怎么认（不硬编码）════════════════════════════════════════════
    ① 优先找 site：`attachment_site` / `end_effector` / `ee` / `tcp` / `tool`
    ② 退而求其次找 body：`attachment` / `tool0` / `link7` / `wrist_3_link` …
    ③ 都找不到就用**运动链最深的那条 body**
    ★ 五个模型实测都有 `attachment_site`，但**不写死它** ——
      用户导入一个新模型时可能叫别的名字，写死就会"能用/不能用"取决于命名习惯。
    实际用了哪个会写进结果，界面上能看到（不猜、也不瞒）。

═══ 为什么用阻尼最小二乘（DLS）而不是伪逆 ══════════════════════════════════
    伪逆在奇异位形附近会让关节速度炸掉（数学上是真的无穷大）。
    DLS 在奇异处退化成"沿梯度小步走"，慢但不会跳；代价是末端到不了时残差收敛变慢，
    所以我们**把残差报出来**，而不是假装解出来了。

═══ 迭代为什么要"接着上一个点"当种子 ══════════════════════════════════════
    每个笛卡尔航点单独从当前姿态起解，很容易在相邻两点解出**差 360° 的两个解**，
    轨迹就会甩一圈。用上一个解当种子，解自然落在最近的分支上。
"""
from __future__ import annotations

import numpy as np

# 候选名（小写比较）
站点候选 = ("attachment_site", "end_effector", "ee_site", "tcp", "tool", "ee")
刚体候选 = ("attachment", "tool0", "hand", "ee_link", "link7", "wrist_3_link", "tool_link")

# 收敛判据与上限
收敛毫米 = 0.5           # 残差小于 0.5 mm 就算到位（比大多数机器人重复精度还松，够用）
最大迭代 = 200
阻尼 = 1e-2


class 逆解失败(Exception):
    def __init__(self, 原因: str, 残差: float | None = None):
        self.原因 = 原因
        self.残差 = 残差
        super().__init__(原因 + (f"（残差 {残差 * 1000:.1f} mm）" if 残差 is not None else ""))


def 找末端(模型, mujoco_mod) -> tuple[int, str, str]:
    """返回 (id, 类型, 名字)，类型是 "site" 或 "body"。"""
    for 名 in 站点候选:
        i = mujoco_mod.mj_name2id(模型, mujoco_mod.mjtObj.mjOBJ_SITE, 名)
        if i >= 0:
            return i, "site", 名
    for 名 in 刚体候选:
        i = mujoco_mod.mj_name2id(模型, mujoco_mod.mjtObj.mjOBJ_BODY, 名)
        if i >= 0:
            return i, "body", 名
    # 兜底：取 body 树里层级最深的那个（通常是末端连杆）
    最深, 最深层 = -1, -1
    for i in range(1, int(模型.nbody)):
        层, j = 0, i
        while j > 0 and 层 < 64:
            j = int(模型.body_parentid[j])
            层 += 1
        if 层 > 最深层:
            最深, 最深层 = i, 层
    if 最深 > 0:
        名字 = mujoco_mod.mj_id2name(模型, mujoco_mod.mjtObj.mjOBJ_BODY, 最深) or f"body{最深}"
        return 最深, "body", 名字
    raise 逆解失败("模型里找不到任何可作末端的 site / body")


def _末端位置(数据, 编号: int, 类型: str) -> np.ndarray:
    return (np.asarray(数据.site_xpos[编号], dtype=float) if 类型 == "site"
            else np.asarray(数据.xpos[编号], dtype=float))


def _关节范围(模型) -> tuple[np.ndarray, np.ndarray]:
    """返回 (低, 高)；无限位的位置给 ±inf（不夹）。"""
    低 = np.full(int(模型.nq), -np.inf)
    高 = np.full(int(模型.nq), np.inf)
    受限 = np.asarray(getattr(模型, "jnt_limited", np.zeros(int(模型.njnt), bool))).ravel()
    范围 = np.asarray(getattr(模型, "jnt_range", np.zeros((int(模型.njnt), 2))), dtype=float)
    for j in range(int(模型.njnt)):
        if 受限.size > j and bool(受限[j]):
            低[j], 高[j] = 范围[j]
    return 低, 高


def 逆解(模型, 数据, 目标: np.ndarray, 种子: np.ndarray | None, mujoco_mod,
        末端: tuple[int, str, str] | None = None) -> tuple[np.ndarray, float]:
    """解一个笛卡尔点。返回 (关节角, 残差米)。**失败抛 `逆解失败`，带残差。**"""
    编号, 类型, 名字 = 末端 or 找末端(模型, mujoco_mod)
    q = (np.array(种子, dtype=float) if 种子 is not None
         else np.array(数据.qpos, dtype=float))
    if q.size != int(模型.nq):
        raise 逆解失败(f"种子维度 {q.size} 与模型 nq={模型.nq} 不一致")
    目标 = np.asarray(目标, dtype=float).ravel()
    if 目标.size != 3:
        raise 逆解失败(f"笛卡尔航点要 3 个数（xyz），收到 {目标.size} 个")

    低, 高 = _关节范围(模型)
    jacp = np.zeros((3, int(模型.nv)))
    I3 = np.eye(3)
    残差 = float("inf")

    for _ in range(最大迭代):
        数据.qpos[:] = q
        mujoco_mod.mj_forward(模型, 数据)
        误差 = 目标 - _末端位置(数据, 编号, 类型)
        残差 = float(np.linalg.norm(误差))
        if 残差 * 1000.0 <= 收敛毫米:
            return q, 残差
        jacp[:] = 0.0
        if 类型 == "site":
            mujoco_mod.mj_jacSite(模型, 数据, jacp, None, 编号)
        else:
            mujoco_mod.mj_jacBody(模型, 数据, jacp, None, 编号)
        # DLS：dq = Jᵀ (J Jᵀ + λ²I)⁻¹ e
        A = jacp @ jacp.T + (阻尼 ** 2) * I3
        try:
            dq = jacp.T @ np.linalg.solve(A, 误差)
        except np.linalg.LinAlgError:
            raise 逆解失败("雅可比求解失败（数值奇异）", 残差) from None
        # 单步限幅：一步跳太大容易越过限位后再也回不来
        步长 = float(np.max(np.abs(dq))) if dq.size else 0.0
        if 步长 > 0.5:
            dq *= 0.5 / 步长
        q = np.clip(q + dq, 低, 高)

    raise 逆解失败("迭代到上限仍未收敛（这个点可能超出工作空间）", 残差)


def 笛卡尔转关节(模型, 数据, 笛卡尔点们, mujoco_mod,
                末端: tuple[int, str, str] | None = None) -> tuple[np.ndarray, float, str]:
    """把一串笛卡尔点转成关节航点。

    返回 (关节航点 (N,nq), 最大残差米, 说明)。
    **每个点用上一个解当种子**（见模块头部的说明）。
    """
    点们 = [np.asarray(p, dtype=float).ravel() for p in (笛卡尔点们 or [])]
    if len(点们) < 2:
        raise 逆解失败("笛卡尔航点至少 2 个")
    编号, 类型, 名字 = 末端 or 找末端(模型, mujoco_mod)
    种子 = np.array(数据.qpos, dtype=float)
    出 = []
    最大残差 = 0.0
    for 序号, 点 in enumerate(点们):
        try:
            解, 残 = 逆解(模型, 数据, 点, 种子, mujoco_mod, (编号, 类型, 名字))
        except 逆解失败 as e:
            raise 逆解失败(f"第 {序号 + 1} 个笛卡尔点解不出来：{e.原因}", e.残差) from None
        出.append(解)
        最大残差 = max(最大残差, 残)
        种子 = 解
    说明 = f"末端={名字}（{类型}），{len(点们)} 个点，最大残差 {最大残差 * 1000:.2f} mm"
    return np.asarray(出, dtype=float), 最大残差, 说明
