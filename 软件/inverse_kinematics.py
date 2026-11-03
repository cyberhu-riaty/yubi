"""Damped-least-squares inverse kinematics for Cartesian waypoints.

规划内核只接受关节航点，因此笛卡尔航点必须先在这里转换成关节角。
求解时以上一个航点的解作为下一个航点的初值，避免相邻点落入相差整圈的解支。
"""
from __future__ import annotations

import numpy as np


SITE_CANDIDATES = (
    "attachment_site", "end_effector", "ee_site", "tcp", "tool", "ee",
)
BODY_CANDIDATES = (
    "attachment", "tool0", "hand", "ee_link", "link7",
    "wrist_3_link", "tool_link",
)

CONVERGENCE_MM = 0.5
MAX_ITERATIONS = 200
DAMPING = 1e-2


class IKError(Exception):
    """Inverse-kinematics failure with an optional residual in metres."""

    def __init__(self, reason: str, residual: float | None = None):
        self.reason = reason
        self.residual = residual
        detail = f"（残差 {residual * 1000:.1f} mm）" if residual is not None else ""
        super().__init__(reason + detail)


def find_end_effector(model, mujoco_module) -> tuple[int, str, str]:
    """Return ``(object_id, object_type, name)`` for the end effector."""
    for name in SITE_CANDIDATES:
        object_id = mujoco_module.mj_name2id(
            model, mujoco_module.mjtObj.mjOBJ_SITE, name)
        if object_id >= 0:
            return object_id, "site", name

    for name in BODY_CANDIDATES:
        object_id = mujoco_module.mj_name2id(
            model, mujoco_module.mjtObj.mjOBJ_BODY, name)
        if object_id >= 0:
            return object_id, "body", name

    # 没有常见名称时，使用运动树中层级最深的刚体作为末端。
    deepest_id = -1
    deepest_level = -1
    for body_id in range(1, int(model.nbody)):
        level = 0
        parent_id = body_id
        while parent_id > 0 and level < 64:
            parent_id = int(model.body_parentid[parent_id])
            level += 1
        if level > deepest_level:
            deepest_id = body_id
            deepest_level = level

    if deepest_id > 0:
        name = (
            mujoco_module.mj_id2name(
                model, mujoco_module.mjtObj.mjOBJ_BODY, deepest_id)
            or f"body{deepest_id}"
        )
        return deepest_id, "body", name
    raise IKError("模型里找不到任何可作末端的 site / body")


def _end_effector_position(data, object_id: int, object_type: str) -> np.ndarray:
    if object_type == "site":
        return np.asarray(data.site_xpos[object_id], dtype=float)
    return np.asarray(data.xpos[object_id], dtype=float)


def _joint_limits(model) -> tuple[np.ndarray, np.ndarray]:
    """Return lower and upper qpos limits; unlimited coordinates use infinity."""
    lower = np.full(int(model.nq), -np.inf)
    upper = np.full(int(model.nq), np.inf)
    limited = np.asarray(
        getattr(model, "jnt_limited", np.zeros(int(model.njnt), bool))
    ).ravel()
    ranges = np.asarray(
        getattr(model, "jnt_range", np.zeros((int(model.njnt), 2))),
        dtype=float,
    )
    for joint_id in range(int(model.njnt)):
        if limited.size > joint_id and bool(limited[joint_id]):
            lower[joint_id], upper[joint_id] = ranges[joint_id]
    return lower, upper


def solve_ik(
    model,
    data,
    target: np.ndarray,
    seed: np.ndarray | None,
    mujoco_module,
    end_effector: tuple[int, str, str] | None = None,
) -> tuple[np.ndarray, float]:
    """Solve one Cartesian point and return ``(qpos, residual_metres)``."""
    object_id, object_type, _name = (
        end_effector or find_end_effector(model, mujoco_module)
    )
    qpos = (
        np.array(seed, dtype=float)
        if seed is not None
        else np.array(data.qpos, dtype=float)
    )
    if qpos.size != int(model.nq):
        raise IKError(f"种子维度 {qpos.size} 与模型 nq={model.nq} 不一致")

    target = np.asarray(target, dtype=float).ravel()
    if target.size != 3:
        raise IKError(f"笛卡尔航点要 3 个数（xyz），收到 {target.size} 个")

    lower, upper = _joint_limits(model)
    position_jacobian = np.zeros((3, int(model.nv)))
    identity = np.eye(3)
    residual = float("inf")

    for _ in range(MAX_ITERATIONS):
        data.qpos[:] = qpos
        mujoco_module.mj_forward(model, data)
        error = target - _end_effector_position(data, object_id, object_type)
        residual = float(np.linalg.norm(error))
        if residual * 1000.0 <= CONVERGENCE_MM:
            return qpos, residual

        position_jacobian[:] = 0.0
        if object_type == "site":
            mujoco_module.mj_jacSite(
                model, data, position_jacobian, None, object_id)
        else:
            mujoco_module.mj_jacBody(
                model, data, position_jacobian, None, object_id)

        # Damped least squares: dq = J.T @ inv(J @ J.T + lambda^2 I) @ error.
        system = (
            position_jacobian @ position_jacobian.T
            + (DAMPING ** 2) * identity
        )
        try:
            delta_q = position_jacobian.T @ np.linalg.solve(system, error)
        except np.linalg.LinAlgError:
            raise IKError("雅可比求解失败（数值奇异）", residual) from None

        # 限制单次迭代步长，避免一次跨过关节限位。
        step_size = float(np.max(np.abs(delta_q))) if delta_q.size else 0.0
        if step_size > 0.5:
            delta_q *= 0.5 / step_size
        qpos = np.clip(qpos + delta_q, lower, upper)

    raise IKError("迭代到上限仍未收敛（这个点可能超出工作空间）", residual)


def cartesian_to_joint(
    model,
    data,
    cartesian_points,
    mujoco_module,
    end_effector: tuple[int, str, str] | None = None,
) -> tuple[np.ndarray, float, str]:
    """Convert Cartesian points to joint waypoints.

    Returns ``(joint_waypoints, maximum_residual_metres, description)``.
    Each point uses the preceding solution as its seed.
    """
    points = [
        np.asarray(point, dtype=float).ravel()
        for point in (cartesian_points or [])
    ]
    if len(points) < 2:
        raise IKError("笛卡尔航点至少 2 个")

    object_id, object_type, name = (
        end_effector or find_end_effector(model, mujoco_module)
    )
    seed = np.array(data.qpos, dtype=float)
    solutions: list[np.ndarray] = []
    maximum_residual = 0.0

    for index, point in enumerate(points):
        try:
            solution, residual = solve_ik(
                model,
                data,
                point,
                seed,
                mujoco_module,
                (object_id, object_type, name),
            )
        except IKError as exc:
            raise IKError(
                f"第 {index + 1} 个笛卡尔点解不出来：{exc.reason}",
                exc.residual,
            ) from None
        solutions.append(solution)
        maximum_residual = max(maximum_residual, residual)
        seed = solution

    description = (
        f"末端={name}（{object_type}），{len(points)} 个点，"
        f"最大残差 {maximum_residual * 1000:.2f} mm"
    )
    return np.asarray(solutions, dtype=float), maximum_residual, description


__all__ = ["IKError", "find_end_effector", "solve_ik", "cartesian_to_joint"]
