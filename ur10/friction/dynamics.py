"""Use the identified friction in offline inverse and online forward dynamics."""

from __future__ import annotations

import mujoco
import numpy as np

from .model import UR10Friction
from .files import FileFriction


def inverse_dynamics(
    model: mujoco.MjModel,
    q: np.ndarray,
    dq: np.ndarray,
    ddq: np.ndarray,
    friction: UR10Friction | FileFriction | None = None,
) -> np.ndarray:
    """Return required joint torque for one state or a batch of states."""
    law = friction or UR10Friction()  # 摩擦
    indices = law.validate_model(model)
    q, dq, ddq = (np.asarray(x, dtype=float) for x in (q, dq, ddq))
    if q.shape != dq.shape or q.shape != ddq.shape or q.shape[-1:] != (6,) or q.ndim not in (1, 2):
        raise ValueError("q, dq and ddq must share shape (6,) or (samples, 6)")
    if model.nq != 6 or model.nv != 6:
        raise ValueError("This inverse-dynamics interface requires the six-DOF UR10 model")
    if not all(np.all(np.isfinite(x)) for x in (q, dq, ddq)):
        raise ValueError("state must contain only finite values")
    single = q.ndim == 1
    qs, dqs, ddqs = (x[None, :] if single else x for x in (q, dq, ddq))
    data = mujoco.MjData(model)
    result = np.empty_like(dqs)
    for i in range(len(qs)):
        data.qpos[:] = qs[i]
        data.qvel[:] = dqs[i]
        data.qacc[:] = ddqs[i]
        mujoco.mj_inverse(model, data)
        result[i] = data.qfrc_inverse[indices] + law.torque(dqs[i])  # 这里叠加摩擦
    return result[0] if single else result


def step_with_friction(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    friction: UR10Friction | FileFriction | None = None,
) -> np.ndarray:
    """Apply resisting joint torque for one mj_step; preserve other applied forces.

    Use this function for every step that needs friction. Direct mj_step calls
    bypass this external law. Returns the compensation torque, not the applied
    force; the applied force is its negative.
    """
    law = friction or UR10Friction()
    indices = law.validate_model(model)
    torque = law.torque(data.qvel[indices])
    original = data.qfrc_applied[indices].copy()
    try:
        data.qfrc_applied[indices] = original - torque
        mujoco.mj_step(model, data)
    finally:
        data.qfrc_applied[indices] = original
    return torque
