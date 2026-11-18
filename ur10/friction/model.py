"""The six identified friction laws, in joint torque units (N m)."""

from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np

JOINT_NAMES = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)


@dataclass(frozen=True)
class UR10Friction:
    """Compute the identified motor torque needed to overcome joint friction.

    Input is joint velocity in rad/s, with the final axis ordered as JOINT_NAMES.
    The original identified expression is preserved, including its B term at zero.
    """

    fc: tuple[float, ...] = (10.0974, 0.0001, 5.0802, 2.4161, 1.6300, 1.5899)
    fv: tuple[float, ...] = (21.4908, 26.2056, 15.2510, 3.2302, 3.8445, 3.7069)
    b: tuple[float, ...] = (-0.3424, 0.1266, 0.2008, 0.6767, 0.6249, 0.5755)
    alpha: tuple[float, ...] = (0.5779, 0.2727, 0.6048, 0.8441, 0.7126, 0.7176)

    def __post_init__(self) -> None:
        for name in ("fc", "fv", "b", "alpha"):
            values = getattr(self, name)
            if len(values) != len(JOINT_NAMES) or not np.all(np.isfinite(values)):
                raise ValueError(f"{name} must contain six finite values")
        if np.any(np.asarray(self.alpha) <= 0):
            raise ValueError("alpha must be positive")

    def torque(self, velocity: np.ndarray) -> np.ndarray:
        """Return friction compensation torque for shape (6,) or (..., 6)."""
        v = np.asarray(velocity, dtype=float)
        if v.ndim == 0 or v.shape[-1] != len(JOINT_NAMES):
            raise ValueError(f"velocity must have a final dimension of {len(JOINT_NAMES)}")
        if not np.all(np.isfinite(v)):
            raise ValueError("velocity must contain only finite values")
        return (np.asarray(self.fc) + np.asarray(self.fv) * np.abs(v) ** np.asarray(self.alpha)) * np.sign(v) + np.asarray(self.b)

    def dof_indices(self, model: mujoco.MjModel) -> np.ndarray:
        """Map named hinge joints to MuJoCo velocity/force indices."""
        indices = []
        for name in JOINT_NAMES:
            jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            if jid < 0:
                raise ValueError(f"Missing UR10 joint: {name}")
            if model.jnt_type[jid] != mujoco.mjtJoint.mjJNT_HINGE:
                raise ValueError(f"UR10 joint must be a hinge: {name}")
            indices.append(int(model.jnt_dofadr[jid]))
        return np.asarray(indices, dtype=int)

    def validate_model(self, model: mujoco.MjModel) -> np.ndarray:   # 检查这个 MuJoCo 模型是不是已经自带摩擦
        indices = self.dof_indices(model)
        if np.any(model.dof_damping[indices] != 0) or np.any(model.dof_frictionloss[indices] != 0):
            raise ValueError("UR10 joint damping and frictionloss must be zero")
        return indices
