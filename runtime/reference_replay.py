"""Load the processed UR10 reference experiment for offline replay/comparison.

The reference data in this repository is the **already processed** result set
produced by the original ``ur10_inverse_dynamics_experiment.py``: measured
current, estimated torque, UR target moment, the two identified model torque
curves and the smoothed q/dq/ddq.  This module does not pretend those files are
raw RTDE logs and does not re-run the zero-phase/Savitzky-Golay preprocessing.

Two consumers share the same cache:

* the web endpoint (``/api/reference/...``) for the comparison charts;
* the reference replay controller, which needs q/dq to move the 3D robot.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REFERENCE_DIRECTORY = ROOT / "ur10/experiments/legacy/outputs/results"
REFERENCE_MODEL = ROOT / "ur10/models/ur10_extfric_new.xml"
TOLERANCE_NM = 1e-5
JOINT_NAMES = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)
# The archived result family is trajectory_0 ... trajectory_9.  Restrict the
# names so a request cannot walk out of the configured directory.
_FILE_PATTERN = "trajectory_*_identified_results.mat"


def reference_directory() -> Path:
    """Return the configured processed-data directory.

    ``YUBI_REFERENCE_DIR`` makes it possible to point the validator at a
    different copy without changing source.  The default points at the data
    bundled in ``ur10/experiments/legacy/outputs/results``.
    """
    override = os.environ.get("YUBI_REFERENCE_DIR", "").strip()
    return Path(override).expanduser().resolve() if override else DEFAULT_REFERENCE_DIRECTORY


def _source_path(index: int) -> Path:
    return reference_directory() / f"trajectory_{int(index)}_identified_results.mat"


def trajectory_indices() -> tuple[int, ...]:
    indices: list[int] = []
    for path in sorted(reference_directory().glob(_FILE_PATTERN)):
        try:
            indices.append(int(path.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return tuple(indices)


def list_trajectories() -> list[dict[str, Any]]:
    items = []
    for index in trajectory_indices():
        path = _source_path(index)
        items.append({
            "index": index,
            "label": f"Trajectory {index}",
            "file": path.name,
            "available": path.is_file(),
        })
    return items


@dataclass(frozen=True)
class ReferenceTrajectory:
    index: int
    path: Path
    time_s: np.ndarray
    q_actual_rad: np.ndarray
    dq_actual_rad_s: np.ndarray
    ddq_actual_rad_s2: np.ndarray
    actual_current_A: np.ndarray
    actual_torque_est_Nm: np.ndarray
    target_moment_Nm: np.ndarray
    friction_torque_Nm: np.ndarray
    identified_torque_friction_off_Nm: np.ndarray
    identified_torque_nonlinear_friction_Nm: np.ndarray
    identified_current_friction_off_A: np.ndarray
    identified_current_nonlinear_friction_A: np.ndarray
    torque_constant_Nm_per_A: np.ndarray
    recompute: dict[str, Any] | None = None

    @property
    def duration_s(self) -> float:
        return float(self.time_s[-1]) if len(self.time_s) else 0.0

    @property
    def sample_count(self) -> int:
        return int(len(self.time_s))

    def sample_index(self, elapsed_s: float) -> int:
        """Nearest archived sample to ``elapsed_s`` (playback/readout helper)."""
        if not len(self.time_s):
            return -1
        after = int(np.searchsorted(self.time_s, float(elapsed_s), side="left"))
        if after <= 0:
            return 0
        if after >= len(self.time_s):
            return len(self.time_s) - 1
        before = after - 1
        return before if abs(self.time_s[before] - elapsed_s) <= abs(self.time_s[after] - elapsed_s) else after

    def interpolate_state(self, elapsed_s: float) -> tuple[np.ndarray, np.ndarray]:
        """Interpolate q/dq for smooth 3D playback between 125 Hz samples.

        The processed samples are the source of truth; interpolation is only a
        display/playback convenience between them.
        """
        if not len(self.time_s):
            return np.zeros(6), np.zeros(6)
        if len(self.time_s) == 1:
            return self.q_actual_rad[0].copy(), self.dq_actual_rad_s[0].copy()
        time = float(np.clip(elapsed_s, self.time_s[0], self.time_s[-1]))
        after = int(np.searchsorted(self.time_s, time, side="right"))
        if after <= 0:
            return self.q_actual_rad[0].copy(), self.dq_actual_rad_s[0].copy()
        if after >= len(self.time_s):
            return self.q_actual_rad[-1].copy(), self.dq_actual_rad_s[-1].copy()
        before = after - 1
        span = float(self.time_s[after] - self.time_s[before])
        alpha = 0.0 if span <= 1e-12 else float((time - self.time_s[before]) / span)
        q = self.q_actual_rad[before] * (1.0 - alpha) + self.q_actual_rad[after] * alpha
        dq = self.dq_actual_rad_s[before] * (1.0 - alpha) + self.dq_actual_rad_s[after] * alpha
        return q, dq

    def payload(self, include_recompute: bool = True) -> dict[str, Any]:
        series = {
            "measured_current_A": self.actual_current_A,
            "measured_torque_Nm": self.actual_torque_est_Nm,
            "model_torque_friction_off_Nm": self.identified_torque_friction_off_Nm,
            "model_torque_nonlinear_friction_Nm": self.identified_torque_nonlinear_friction_Nm,
            "model_current_friction_off_A": self.identified_current_friction_off_A,
            "model_current_nonlinear_friction_A": self.identified_current_nonlinear_friction_A,
            "target_moment_Nm": self.target_moment_Nm,
            "friction_torque_Nm": self.friction_torque_Nm,
        }
        if include_recompute and self.recompute is not None:
            series["recompute_torque_friction_off_Nm"] = self.recompute["rigid_torque_Nm"]
            series["recompute_torque_nonlinear_friction_Nm"] = self.recompute["total_torque_Nm"]
            series["recompute_current_friction_off_A"] = self.recompute["rigid_current_A"]
            series["recompute_current_nonlinear_friction_A"] = self.recompute["total_current_A"]
        return {
            "index": self.index,
            "label": f"Trajectory {self.index}",
            "source": {
                "kind": "processed_reference",
                "file": self.path.name,
                "description": "原始脚本处理后的实机数据（已滤波/求导）；不是原始 RTDE 记录",
                "raw_rtde_available": False,
            },
            "joint_names": list(JOINT_NAMES),
            "time_s": self.time_s.tolist(),
            "sample_count": self.sample_count,
            "duration_s": self.duration_s,
            "torque_constant_Nm_per_A": self.torque_constant_Nm_per_A.tolist(),
            "series": {name: values.tolist() for name, values in series.items()},
            "recompute": _public_recompute(self.recompute),
        }


def _public_recompute(recompute: dict[str, Any] | None) -> dict[str, Any] | None:
    if recompute is None:
        return None
    # Do not duplicate the full recompute arrays in the metadata object; they
    # already live in ``series``.
    return {key: value for key, value in recompute.items()
            if key not in ("rigid_torque_Nm", "total_torque_Nm",
                           "rigid_current_A", "total_current_A")}


def _array(reference: dict[str, Any], name: str, columns: int = 6) -> np.ndarray:
    value = np.asarray(reference.get(name), dtype=float)
    if value.shape != (len(reference["time_s"]), columns):
        raise ValueError(f"{name} has shape {value.shape}, expected (n, {columns})")
    if not np.isfinite(value).all():
        raise ValueError(f"{name} contains non-finite values")
    return value


def _geom_label(model, geom: int) -> str:
    """Readable contact pair label: geom/mesh name, then body name."""
    import mujoco

    name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom)
    if name:
        return str(name)
    if int(model.geom_type[geom]) == int(mujoco.mjtGeom.mjGEOM_MESH):
        mesh = int(model.geom_dataid[geom])
        mesh_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_MESH, mesh)
        if mesh_name:
            return f"mesh:{mesh_name}"
    body = int(model.geom_bodyid[geom])
    body_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body)
    return f"body:{body_name}" if body_name else f"geom_{geom}"


def _recompute(reference: dict[str, Any], q: np.ndarray, dq: np.ndarray,
               ddq: np.ndarray, friction: np.ndarray, kt: np.ndarray) -> dict[str, Any]:
    """Independent ``mj_inverse`` recompute and contact-aware comparison.

    The reference arrays themselves remain the acceptance basis.  This extra
    pass exists to expose whether a current model/MuJoCo build reproduces them;
    trajectories 1 and 7 are known to differ only on contact-active samples.
    """
    import mujoco

    times = np.asarray(reference["time_s"], dtype=float).reshape(-1)
    model = mujoco.MjModel.from_xml_path(str(REFERENCE_MODEL))
    data = mujoco.MjData(model)
    rigid = np.empty_like(q)
    contacts = np.zeros(len(q), dtype=int)
    contact_pairs: set[str] = set()
    for index in range(len(q)):
        data.qpos[:] = q[index]
        data.qvel[:] = dq[index]
        data.qacc[:] = ddq[index]
        mujoco.mj_inverse(model, data)
        rigid[index] = data.qfrc_inverse
        contacts[index] = int(data.ncon)
        for contact in range(int(data.ncon)):
            item = data.contact[contact]
            names = [_geom_label(model, int(item.geom1)), _geom_label(model, int(item.geom2))]
            contact_pairs.add("-".join(sorted(names)))
    total = rigid + friction
    diff = rigid - reference["identified_torque_friction_off_Nm"]
    per_sample = np.max(np.abs(diff), axis=1)
    bad = per_sample > TOLERANCE_NM
    bad_indices = np.flatnonzero(bad)
    intervals: list[dict[str, Any]] = []
    if len(bad_indices):
        start = previous = int(bad_indices[0])
        for value in bad_indices[1:]:
            value = int(value)
            if value == previous + 1:
                previous = value
                continue
            intervals.append(_interval(times, start, previous))
            start = previous = value
        intervals.append(_interval(times, start, previous))
    worst_flat = int(np.argmax(np.abs(diff)))
    worst_sample, worst_joint = np.unravel_index(worst_flat, diff.shape)
    return {
        "status": "match" if not len(bad_indices) else "contact_sensitive",
        "tolerance_nm": TOLERANCE_NM,
        "mujoco_version": mujoco.__version__,
        "model": REFERENCE_MODEL.name,
        "sample_count": int(len(q)),
        "contact_sample_count": int(np.count_nonzero(contacts)),
        "bad_sample_count": int(len(bad_indices)),
        "max_abs_diff_nm": float(np.max(np.abs(diff))),
        "worst": {
            "time_s": float(times[worst_sample]),
            "joint": int(worst_joint) + 1,
            "max_abs_diff_nm": float(np.max(np.abs(diff))),
            "contact_count": int(contacts[worst_sample]),
        },
        "bad_intervals": intervals[:20],
        "contact_pairs": sorted(contact_pairs),
        "rigid_torque_Nm": rigid,
        "total_torque_Nm": total,
        "rigid_current_A": rigid / kt,
        "total_current_A": total / kt,
    }


def _interval(times: np.ndarray, start: int, end: int) -> dict[str, Any]:
    return {
        "start_s": float(times[start]),
        "end_s": float(times[end]),
        "samples": int(end - start + 1),
    }


@lru_cache(maxsize=32)
def _load_file(path_text: str, mtime_ns: int, include_recompute: bool) -> ReferenceTrajectory:
    from scipy.io import loadmat

    path = Path(path_text)
    reference = {key: value for key, value in loadmat(path).items() if not key.startswith("_")}
    times = np.asarray(reference["time_s"], dtype=float).reshape(-1)
    if len(times) < 2 or not np.isfinite(times).all() or not np.all(np.diff(times) > 0):
        raise ValueError(f"Invalid reference time axis in {path}")
    q = _array(reference, "q_actual_rad")
    dq = _array(reference, "dq_actual_rad_s")
    ddq = _array(reference, "ddq_actual_rad_s2")
    friction = _array(reference, "friction_torque_Nm")
    kt = np.asarray(reference["torque_constant_Nm_per_A"], dtype=float).reshape(6)
    if not np.isfinite(kt).all() or np.any(kt <= 0):
        raise ValueError(f"Invalid torque constants in {path}")
    recompute = _recompute(reference, q, dq, ddq, friction, kt) if include_recompute else None
    return ReferenceTrajectory(
        index=int(reference.get("trajectory", np.array([[0]]))[0, 0]),
        path=path,
        time_s=times,
        q_actual_rad=q,
        dq_actual_rad_s=dq,
        ddq_actual_rad_s2=ddq,
        actual_current_A=_array(reference, "actual_current_A"),
        actual_torque_est_Nm=_array(reference, "actual_torque_est_Nm"),
        target_moment_Nm=_array(reference, "target_moment_Nm"),
        friction_torque_Nm=friction,
        identified_torque_friction_off_Nm=_array(reference, "identified_torque_friction_off_Nm"),
        identified_torque_nonlinear_friction_Nm=_array(reference, "identified_torque_nonlinear_friction_Nm"),
        identified_current_friction_off_A=_array(reference, "identified_current_friction_off_A"),
        identified_current_nonlinear_friction_A=_array(reference, "identified_current_nonlinear_friction_A"),
        torque_constant_Nm_per_A=kt,
        recompute=recompute,
    )


def load_trajectory(index: int, include_recompute: bool = False) -> ReferenceTrajectory:
    index = int(index)
    if index not in trajectory_indices():
        raise FileNotFoundError(f"No processed reference trajectory {index} in {reference_directory()}")
    path = _source_path(index)
    return _load_file(str(path), path.stat().st_mtime_ns, bool(include_recompute))


def reference_payload(index: int, include_recompute: bool = True) -> dict[str, Any]:
    return load_trajectory(index, include_recompute=include_recompute).payload(
        include_recompute=include_recompute)


def reference_summary() -> dict[str, Any]:
    """Small metadata block for the panel header (no heavy recompute)."""
    return {
        "directory": str(reference_directory()),
        "model": str(REFERENCE_MODEL),
        "raw_rtde_available": False,
        "preprocessing_note": (
            "参考数据是原始脚本处理后的结果：10 Hz 零相位滤波 + 0.25 s Savitzky-Golay "
            "求导 + 首尾 0.5 s 裁剪。原始 RTDE 49 列记录不在当前工作区，无法从原始数据"
            "重新核对预处理。"
        ),
        "trajectories": list_trajectories(),
    }


if __name__ == "__main__":
    # Small human-readable probe; the HTTP endpoint and tests use the functions.
    print(json.dumps(reference_summary(), ensure_ascii=False, indent=2))
    for index in trajectory_indices():
        item = load_trajectory(index, include_recompute=True)
        status = item.recompute["status"] if item.recompute else "unknown"
        print(f"trajectory {index}: {item.sample_count} samples, {item.duration_s:.3f} s, "
              f"recompute={status}")
