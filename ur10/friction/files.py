"""Load velocity-based friction laws and identified dynamics from local files."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import hashlib

import mujoco
import numpy as np

from .model import JOINT_NAMES


def read_json(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


class FileFriction:
    """Adapter for six named hinge joints; supports single states and batches."""

    def __init__(self, declaration: dict, parameters: dict, function=None):
        self.joint_names = tuple(declaration.get("joint_names", JOINT_NAMES))
        if len(self.joint_names) != 6 or len(set(self.joint_names)) != 6:
            raise ValueError("joint_names must contain six distinct joint names")
        self.label = declaration.get("label", "自定义摩擦")
        self.kind = declaration.get("type", "python")
        self.parameters = parameters
        self.function = function
        if function is None:
            required = {"power": ("fc", "fv", "b", "alpha"),
                        "coulomb_viscous": ("fc", "fv", "b")}
            if self.kind not in required:
                raise ValueError(f"Unknown friction type: {self.kind}")
            for key in required[self.kind]:
                value = np.asarray(parameters[key], dtype=float)
                if value.shape != (6,) or not np.all(np.isfinite(value)):
                    raise ValueError(f"{key} must contain six finite coefficients")
                self.parameters[key] = value
            if self.kind == "power" and np.any(self.parameters["alpha"] <= 0):
                raise ValueError("alpha must be positive")

    def torque(self, velocity: np.ndarray) -> np.ndarray:
        v = np.asarray(velocity, dtype=float)
        if v.ndim == 0 or v.shape[-1] != 6 or not np.all(np.isfinite(v)):
            raise ValueError("velocity must have shape (..., 6) with finite values")
        if self.function is not None:
            result = self.function(v.copy(), self.parameters)
        else:
            p = self.parameters
            exponent = p["alpha"] if self.kind == "power" else 1.0
            result = (p["fc"] + p["fv"] * np.abs(v) ** exponent) * np.sign(v) + p["b"]
        result = np.asarray(result, dtype=float)
        if result.shape != v.shape or not np.all(np.isfinite(result)):
            raise ValueError("Friction torque must have the input shape and finite values")
        return result

    def dof_indices(self, model: mujoco.MjModel) -> np.ndarray:
        indices = []
        for name in self.joint_names:
            jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            if jid < 0 or model.jnt_type[jid] != mujoco.mjtJoint.mjJNT_HINGE:
                raise ValueError(f"Missing hinge joint: {name}")
            indices.append(int(model.jnt_dofadr[jid]))
        return np.asarray(indices)

    def validate_model(self, model: mujoco.MjModel) -> np.ndarray:
        indices = self.dof_indices(model)
        if np.any(model.dof_damping[indices] != 0) or np.any(model.dof_frictionloss[indices] != 0):
            raise ValueError("External friction requires zero joint damping/frictionloss")
        return indices


def load_friction(model_file: Path, parameters_file: Path) -> FileFriction:
    """JSON declares a built-in law; Python exports torque(velocity, parameters)."""
    model_file = Path(model_file)
    parameters = read_json(parameters_file)
    if model_file.suffix.lower() == ".json":
        return FileFriction(read_json(model_file), parameters)
    if model_file.suffix.lower() != ".py":
        raise ValueError("Friction model must be a .json declaration or .py module")
    module_name = "ur10_local_friction_" + hashlib.sha256(str(model_file.resolve()).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(module_name, model_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    function = getattr(module, "torque", None)
    if not callable(function):
        raise ValueError("Python friction file must export torque(velocity, parameters)")
    declaration = {"joint_names": getattr(module, "JOINT_NAMES", JOINT_NAMES),
                   "label": getattr(module, "LABEL", model_file.stem)}
    return FileFriction(declaration, parameters, function)


def load_robot(xml_file: Path, dynamics_file: Path | None = None) -> mujoco.MjModel:
    """Optional overrides use MuJoCo inertial-frame quantities in SI units."""
    model = mujoco.MjModel.from_xml_path(str(Path(xml_file).resolve()))
    if dynamics_file is None:
        return model
    params = read_json(dynamics_file)
    if set(params) - {"bodies", "joints"}:
        raise ValueError("Dynamics JSON supports only 'bodies' and 'joints'")
    for name, values in params.get("bodies", {}).items():
        bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)
        if bid <= 0:
            raise ValueError(f"Unknown or world body: {name}")
        fields = {"mass": (model.body_mass, (), True), "ipos": (model.body_ipos, (3,), False),
                  "inertia": (model.body_inertia, (3,), True), "iquat": (model.body_iquat, (4,), False)}
        for key, value in values.items():
            if key not in fields:
                raise ValueError(f"Unsupported body parameter: {key}")
            array, shape, positive = fields[key]
            value = np.asarray(value, dtype=float)
            if value.shape != shape or not np.all(np.isfinite(value)) or (positive and np.any(value <= 0)):
                raise ValueError(f"Invalid {name}.{key}")
            if key == "iquat":
                if np.linalg.norm(value) == 0:
                    raise ValueError("iquat must be nonzero")
                value = value / np.linalg.norm(value)
            if key == "inertia" and 2 * np.max(value) > np.sum(value) + 1e-12:
                raise ValueError("Principal inertia must satisfy the triangle inequality")
            array[bid] = value
    for name, values in params.get("joints", {}).items():
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        if jid < 0 or model.jnt_type[jid] != mujoco.mjtJoint.mjJNT_HINGE:
            raise ValueError(f"Missing hinge joint: {name}")
        if set(values) != {"armature"}:
            raise ValueError("Joint dynamics overrides support only 'armature'")
        value = values["armature"]
        if not np.isscalar(value) or not np.isfinite(value) or value < 0:
            raise ValueError("armature must be a finite nonnegative scalar")
        model.dof_armature[model.jnt_dofadr[jid]] = value
    mujoco.mj_setConst(model, mujoco.MjData(model))
    return model
