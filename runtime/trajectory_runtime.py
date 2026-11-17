"""与 GUI 无关的关节参考轨迹采样和当前参考值共享。

轨迹使用 MuJoCo 的 ``data.time``，因此暂停、仿真倍率和无界面快速运行都不会
改变实验定义。控制器只接收当前目标，不需要知道目标来自输入框还是轨迹文件。
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class TrajectorySample:
    qpos: np.ndarray
    qvel: np.ndarray


@dataclass(frozen=True)
class TrajectoryVisualization:
    """供 3D 视口读取的末端轨迹快照；数组都是副本，不共享 ``MjData``。"""

    experiment_key: str
    endpoint_name: str
    planned: np.ndarray
    actual: np.ndarray


class JointTrajectory:
    """由实验 JSON 创建的固定目标或平滑多航点关节轨迹。"""

    def __init__(self, specification: Mapping[str, Any]) -> None:
        self.kind = str(specification.get("type") or "joint_target")
        self.interpolation = str(
            specification.get("interpolation") or "quintic_smoothstep")
        self._second_derivatives: np.ndarray | None = None
        if self.kind == "joint_target":
            target = np.asarray(specification.get("target_qpos", []), dtype=float).reshape(-1)
            if target.size == 0:
                raise ValueError("joint_target 缺少 target_qpos")
            self.times = np.asarray([0.0], dtype=float)
            self.waypoints = target.reshape(1, -1)
        elif self.kind == "joint_waypoints":
            self.times = np.asarray(specification.get("times", []), dtype=float).reshape(-1)
            self.waypoints = np.asarray(specification.get("waypoints", []), dtype=float)
            if self.times.size < 2:
                raise ValueError("joint_waypoints 至少需要两个时间点")
            if self.waypoints.ndim != 2 or self.waypoints.shape[0] != self.times.size:
                raise ValueError("waypoints 行数必须与 times 数量相同")
            if self.waypoints.shape[1] == 0:
                raise ValueError("waypoints 不能是空关节向量")
            if abs(float(self.times[0])) > 1e-12:
                raise ValueError("轨迹第一个时间必须是 0")
            if np.any(np.diff(self.times) <= 0.0):
                raise ValueError("轨迹 times 必须严格递增")
            if self.interpolation == "clamped_cubic_spline":
                self._second_derivatives = self._build_clamped_cubic_spline()
            elif self.interpolation != "quintic_smoothstep":
                raise ValueError(f"暂不支持插值方法：{self.interpolation}")
        else:
            raise ValueError(f"暂不支持轨迹类型：{self.kind}")

    def _build_clamped_cubic_spline(self) -> np.ndarray:
        """求各航点二阶导数；首末速度固定为零，中间保持 C2 连续。"""
        count, dof = self.waypoints.shape
        intervals = np.diff(self.times)
        matrix = np.zeros((count, count), dtype=float)
        rhs = np.zeros((count, dof), dtype=float)

        first = float(intervals[0])
        matrix[0, 0] = 2.0 * first
        matrix[0, 1] = first
        rhs[0] = 6.0 * ((self.waypoints[1] - self.waypoints[0]) / first)

        for index in range(1, count - 1):
            previous = float(intervals[index - 1])
            following = float(intervals[index])
            matrix[index, index - 1] = previous
            matrix[index, index] = 2.0 * (previous + following)
            matrix[index, index + 1] = following
            rhs[index] = 6.0 * (
                (self.waypoints[index + 1] - self.waypoints[index]) / following
                - (self.waypoints[index] - self.waypoints[index - 1]) / previous)

        last = float(intervals[-1])
        matrix[-1, -2] = last
        matrix[-1, -1] = 2.0 * last
        rhs[-1] = -6.0 * ((self.waypoints[-1] - self.waypoints[-2]) / last)
        return np.linalg.solve(matrix, rhs)

    @property
    def dof(self) -> int:
        return int(self.waypoints.shape[1])

    @property
    def duration(self) -> float:
        return float(self.times[-1])

    def sample(self, elapsed: float) -> TrajectorySample:
        """按实验指定方式采样关节位置和目标速度。"""
        t = max(0.0, float(elapsed))
        if self.kind == "joint_target" or t <= 0.0:
            return TrajectorySample(self.waypoints[0].copy(), np.zeros(self.dof))
        if t >= self.duration:
            return TrajectorySample(self.waypoints[-1].copy(), np.zeros(self.dof))

        index = int(np.searchsorted(self.times, t, side="right") - 1)
        index = min(max(index, 0), self.times.size - 2)
        t0, t1 = float(self.times[index]), float(self.times[index + 1])
        segment = max(t1 - t0, 1e-12)
        x = np.clip((t - t0) / segment, 0.0, 1.0)
        if self.interpolation == "clamped_cubic_spline":
            assert self._second_derivatives is not None
            left, right = 1.0 - x, x
            m0 = self._second_derivatives[index]
            m1 = self._second_derivatives[index + 1]
            position = (
                left * self.waypoints[index] + right * self.waypoints[index + 1]
                + ((left**3 - left) * m0 + (right**3 - right) * m1)
                * segment**2 / 6.0
            )
            velocity = (
                (self.waypoints[index + 1] - self.waypoints[index]) / segment
                + segment / 6.0
                * ((1.0 - 3.0 * left**2) * m0
                   + (3.0 * right**2 - 1.0) * m1)
            )
            return TrajectorySample(position, velocity)

        blend = 10.0 * x**3 - 15.0 * x**4 + 6.0 * x**5
        blend_rate = (30.0 * x**2 - 60.0 * x**3 + 30.0 * x**4) / segment
        delta = self.waypoints[index + 1] - self.waypoints[index]
        return TrajectorySample(
            self.waypoints[index] + blend * delta,
            blend_rate * delta,
        )


_lock = threading.Lock()
_references: dict[int, tuple[np.ndarray, np.ndarray]] = {}
_visualization_key = ""
_visualization_endpoint = ""
_visualization_planned = np.empty((0, 3), dtype=float)
_visualization_actual: list[np.ndarray] = []


def publish_reference(data, sample: TrajectorySample) -> None:
    """保存当前 data 对应的参考值，供记录器读取；始终复制，避免 NumPy 视图失效。"""
    with _lock:
        _references[id(data)] = (sample.qpos.copy(), sample.qvel.copy())


def current_reference(data) -> tuple[np.ndarray | None, np.ndarray | None]:
    with _lock:
        value = _references.get(id(data))
        if value is None:
            return None, None
        return value[0].copy(), value[1].copy()


def matching_reference_velocity(data, target) -> np.ndarray:
    """目标来自当前轨迹时返回 ``qvel_ref``，手动/定点目标则返回零速度。

    这样控制器不需要认识实验或 GUI；它只判断当前位置目标是否与轨迹发布器的
    参考值一致，也避免切换到手动目标后误用残留的轨迹速度。
    """
    target_array = np.asarray(target, dtype=float).reshape(-1)
    zero = np.zeros_like(np.asarray(data.qvel, dtype=float))
    qpos_ref, qvel_ref = current_reference(data)
    if qpos_ref is None or qvel_ref is None:
        return zero
    qpos_array = np.asarray(qpos_ref, dtype=float).reshape(-1)
    qvel_array = np.asarray(qvel_ref, dtype=float).reshape(-1)
    if (qpos_array.shape != target_array.shape or qvel_array.shape != zero.shape
            or not np.allclose(qpos_array, target_array, rtol=0.0, atol=1e-9)):
        return zero
    return qvel_array.copy()


def clear_reference(data=None) -> None:
    with _lock:
        if data is None:
            _references.clear()
        else:
            _references.pop(id(data), None)


def cartesian_path(model, trajectory: JointTrajectory, mujoco_mod,
                   samples: int = 181) -> tuple[np.ndarray, tuple[int, str, str]]:
    """把关节参考轨迹转换成末端世界坐标，不修改正在运行的仿真数据。"""
    from inverse_kinematics import find_end_effector

    if int(model.nq) != trajectory.dof:
        raise ValueError(f"轨迹是 {trajectory.dof} 轴，模型 nq={model.nq}")
    endpoint = find_end_effector(model, mujoco_mod)
    endpoint_id, endpoint_type, _ = endpoint
    scratch = mujoco_mod.MjData(model)
    count = max(2, int(samples))
    times = np.linspace(0.0, trajectory.duration, count)
    points = np.empty((count, 3), dtype=float)
    for index, elapsed in enumerate(times):
        scratch.qpos[:] = trajectory.sample(float(elapsed)).qpos
        scratch.qvel[:] = 0.0
        mujoco_mod.mj_forward(model, scratch)
        source = (scratch.site_xpos[endpoint_id]
                  if endpoint_type == "site" else scratch.xpos[endpoint_id])
        points[index] = np.asarray(source, dtype=float)
    return points, endpoint


def begin_trajectory_visualization(experiment_key: str, endpoint_name: str,
                                   planned: np.ndarray) -> None:
    """发布既定末端轨迹，并清空上一轮实际轨迹。"""
    global _visualization_key, _visualization_endpoint
    global _visualization_planned, _visualization_actual
    path = np.asarray(planned, dtype=float).reshape(-1, 3).copy()
    with _lock:
        _visualization_key = str(experiment_key or "")
        _visualization_endpoint = str(endpoint_name or "末端")
        _visualization_planned = path
        _visualization_actual = []


def prepare_trajectory_visualization(model, experiment_key: str,
                                     specification: Mapping[str, Any], mujoco_mod
                                     ) -> tuple[JointTrajectory, tuple[int, str, str]]:
    """从实验定义生成 3D 目标线；加载实验时即可调用，不必先推进物理。"""
    trajectory = JointTrajectory(specification)
    count = max(81, min(241, int(trajectory.duration * 12.0) + 1))
    planned, endpoint = cartesian_path(model, trajectory, mujoco_mod, count)
    begin_trajectory_visualization(experiment_key, endpoint[2], planned)
    return trajectory, endpoint


def append_actual_trajectory_point(experiment_key: str, point) -> None:
    """追加一个实际末端点；调用方负责按仿真时间降采样。"""
    value = np.asarray(point, dtype=float).reshape(3).copy()
    with _lock:
        if str(experiment_key or "") != _visualization_key:
            return
        _visualization_actual.append(value)


def current_trajectory_visualization() -> TrajectoryVisualization:
    """渲染线程取得一致快照；不把内部可变列表暴露出去。"""
    with _lock:
        actual = (np.asarray(_visualization_actual, dtype=float).reshape(-1, 3)
                  if _visualization_actual else np.empty((0, 3), dtype=float))
        return TrajectoryVisualization(
            experiment_key=_visualization_key,
            endpoint_name=_visualization_endpoint,
            planned=_visualization_planned.copy(),
            actual=actual.copy(),
        )


def clear_trajectory_visualization() -> None:
    """模型/实验切换时移除旧轨迹，避免把上一台机器的曲线画到新场景。"""
    global _visualization_key, _visualization_endpoint
    global _visualization_planned, _visualization_actual
    with _lock:
        _visualization_key = ""
        _visualization_endpoint = ""
        _visualization_planned = np.empty((0, 3), dtype=float)
        _visualization_actual = []
