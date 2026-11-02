"""Experiment trajectory target player: publish q_ref(t) to a controller."""
from __future__ import annotations

import os

import numpy as np

import plugin_system as studio
from plugin_system import ControlPlugin, step_handler
from ui_bridge import PanelTargetMessage
from experiment_registry import experiment_registry
from trajectory_runtime import (
    JointTrajectory,
    append_actual_trajectory_point,
    clear_reference,
    clear_trajectory_visualization,
    prepare_trajectory_visualization,
    publish_reference,
)


class ExperimentTrajectoryPlayer(ControlPlugin):
    名称 = "实验轨迹目标执行"
    英文名 = "Experiment trajectory target player"
    版本 = "1.0"
    作者 = "数字样机"
    说明 = "根据 data.time 采样多航点轨迹，只发布关节目标，不直接写 data.ctrl。"
    接管控制 = False
    # 默认监看受重力影响明显的肩关节，验证页能直观看到目标与实际是否重合。
    监看关节 = 1.0

    def __init__(self) -> None:
        self._experiment_key = ""
        self._trajectory: JointTrajectory | None = None
        self._start_time: float | None = None
        self._last_time: float | None = None
        self._data = None
        self._progress = 0.0
        self._last_target = np.zeros(0)
        self._last_actual = np.zeros(0)
        self._joint_names: list[str] = []
        self._model = None
        self._endpoint: tuple[int, str, str] | None = None
        self._visualization_key = ""
        self._last_trace_time: float | None = None

    def 收到模型(self, event) -> None:
        if self._data is not None:
            clear_reference(self._data)
        self._data = getattr(event, "data", None)
        self._model = getattr(event, "model", None)
        self._start_time = None
        self._last_time = None
        self._endpoint = None
        self._visualization_key = ""
        self._last_trace_time = None
        clear_trajectory_visualization()
        model = self._model
        self._joint_names = []
        if model is not None:
            self._joint_names = [
                str(studio.mujoco.mj_id2name(
                    model, studio.mujoco.mjtObj.mjOBJ_JOINT, index) or f"joint_{index}")
                for index in range(int(model.njnt))
            ]

    def _load_selected_experiment(self) -> None:
        key = str(os.environ.get("驭臂_当前实验", "") or "").strip()
        if key == self._experiment_key:
            return
        self._experiment_key = key
        self._trajectory = None
        self._start_time = None
        self._last_time = None
        self._visualization_key = ""
        self._last_trace_time = None
        clear_trajectory_visualization()
        if not key:
            return
        experiment = experiment_registry.create(key)
        if str(experiment.trajectory.get("type") or "") != "joint_waypoints":
            return
        self._trajectory = JointTrajectory(experiment.trajectory)

    def _prepare_visualization(self, event) -> None:
        """计算一次既定末端轨迹；使用临时 MjData，不触碰真实仿真状态。"""
        if self._trajectory is None or self._visualization_key == self._experiment_key:
            return
        model = getattr(event, "model", None) or self._model
        if model is None:
            return
        _, endpoint = prepare_trajectory_visualization(
            model, self._experiment_key,
            {"type": self._trajectory.kind,
             "times": self._trajectory.times,
             "waypoints": self._trajectory.waypoints},
            studio.mujoco,
        )
        self._endpoint = endpoint
        self._visualization_key = self._experiment_key
        self._last_trace_time = None

    def _append_actual_point(self, event, elapsed: float, force: bool = False) -> None:
        if self._endpoint is None:
            return
        if not force and self._last_trace_time is not None and elapsed - self._last_trace_time < 0.05:
            return
        endpoint_id, endpoint_type, _ = self._endpoint
        source = (event.data.site_xpos[endpoint_id]
                  if endpoint_type == "site" else event.data.xpos[endpoint_id])
        append_actual_trajectory_point(self._experiment_key, source)
        self._last_trace_time = elapsed

    @step_handler
    def 每步目标(self, event: studio.messages.StepEvent) -> bool:
        self._load_selected_experiment()
        if self._trajectory is None:
            return False
        data_time = float(event.data.time)
        reset = self._start_time is None or (
                self._last_time is not None and data_time + 1e-12 < self._last_time)
        if reset:
            self._start_time = data_time
        self._last_time = data_time
        if int(event.data.qpos.size) != self._trajectory.dof:
            raise ValueError(
                f"轨迹是 {self._trajectory.dof} 轴，当前模型 qpos 是 {event.data.qpos.size} 轴")

        elapsed = max(0.0, data_time - float(self._start_time))
        if reset:
            self._visualization_key = ""
        self._prepare_visualization(event)
        self._append_actual_point(event, elapsed, force=reset)
        sample = self._trajectory.sample(elapsed)
        publish_reference(event.data, sample)
        self._last_target = sample.qpos.copy()
        self._last_actual = np.asarray(event.data.qpos, dtype=float).copy()
        self._progress = min(elapsed / max(self._trajectory.duration, 1e-12), 1.0)

        registry = studio.get_registry()
        if registry is None:
            raise RuntimeError("找不到当前插件注册表，无法发布轨迹目标")
        registry.处理消息(PanelTargetMessage(ctrl_target=np.asarray(sample.qpos, dtype=float)))
        return False

    def 插件状态(self) -> dict:
        if self._trajectory is None:
            return {"轨迹": "未激活"}
        index = self._watch_index()
        name = self._joint_names[index] if index < len(self._joint_names) else f"joint_{index}"
        return {"轨迹": self._experiment_key, "进度": f"{self._progress * 100:.0f}%",
                "监看关节": name}

    def _watch_index(self) -> int:
        size = int(self._last_target.size or len(self._joint_names) or 1)
        return min(max(int(round(float(self.监看关节))), 0), size - 1)

    def 指标(self) -> dict:
        """目标/实际使用同一单位，适合验证页直接叠加观察。"""
        if self._last_target.size == 0 or self._last_actual.size != self._last_target.size:
            return {}
        index = self._watch_index()
        target = float(np.degrees(self._last_target[index]))
        actual = float(np.degrees(self._last_actual[index]))
        return {
            "监看关节目标位置(deg)": target,
            "监看关节实际位置(deg)": actual,
            "监看关节有符号误差(deg)": target - actual,
        }

    def 可调参数(self) -> dict:
        upper = max(0, int(self._last_target.size or len(self._joint_names) or 1) - 1)
        return {
            "监看关节": {"值": self.监看关节, "范围": (0.0, float(upper)),
                       "步长": 1.0, "单位": "关节索引"},
        }


插件类 = ExperimentTrajectoryPlayer
