"""Transfer joint targets and state between the workbench and controllers."""
from __future__ import annotations

import dataclasses
from wire_compatibility import legacy_wire
from typing import Callable

import numpy as np

from official_api import messages
from ui_bridge import PanelTargetMessage


@dataclasses.dataclass(frozen=True)
class ControlTargetCommand(messages.Snapshot):
    """GUI → 仿真：按 qpos 顺序给出一组关节目标，单位沿用模型（转动关节为 rad）。"""

    target: object = dataclasses.field(default_factory=list)


@legacy_wire('ControlState', {'joint_names': '关节名', 'current_position': '当前位置', 'current_velocity': '当前速度', 'current_control': '当前控制', 'target': '目标', 'target_source': '目标来源', 'description': '说明'})
@dataclasses.dataclass(frozen=True)
class ControlState(messages.Snapshot):
    """仿真 → GUI：目标输入区需要的最小状态。"""

    joint_names: list = dataclasses.field(default_factory=list)
    current_position: list = dataclasses.field(default_factory=list)
    current_velocity: list = dataclasses.field(default_factory=list)
    current_control: list = dataclasses.field(default_factory=list)
    target: list = dataclasses.field(default_factory=list)
    target_source: str = "当前位置"
    description: str = ""


def _joint_labels(model) -> list[str]:
    """把 MuJoCo 的 joint/qpos 地址转换成与 qpos 等长的可读标签。"""
    nq = int(getattr(model, "nq", 0))
    labels = [f"qpos[{i}]" for i in range(nq)]
    try:
        import mujoco
        addresses = [int(model.jnt_qposadr[j]) for j in range(int(model.njnt))] + [nq]
        for j in range(int(model.njnt)):
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j) or f"joint[{j}]"
            width = max(0, addresses[j + 1] - addresses[j])
            for k in range(width):
                labels[addresses[j] + k] = name if width == 1 else f"{name}[{k}]"
    except Exception:                                                # noqa: BLE001
        pass
    return labels


class ControlTargetApplier:
    """校验 GUI 目标，再复用现有 ``面板目标消息`` 交给当前控制算法。"""

    name = "控制目标输入"
    version = "1.0"
    takes_control = False

    def __init__(self, forward: Callable[[object], None]) -> None:
        self._forward = forward
        self._model = None
        self._data = None
        self._target = np.zeros(0, dtype=float)
        self._source = "当前位置"
        self._note = "尚未加载可控制模型"

    def receive_model(self, event) -> None:
        new_model = getattr(event, "model", None)
        new_data = getattr(event, "data", None)
        model_changed = self._model is not new_model
        self._model, self._data = new_model, new_data
        if new_data is None:
            self._target = np.zeros(0, dtype=float)
            self._note = "尚未加载可控制模型"
            return
        nq = int(getattr(new_model, "nq", 0))
        if model_changed or self._target.size != nq:
            self._target = np.asarray(new_data.qpos, dtype=float).copy()
            self._source = "当前位置"
        self._note = "没有关节可控制" if nq == 0 else "目标已就绪"
        if nq:
            self._forward(self._target.copy())

    @messages.handler
    def receive_target(self, command: ControlTargetCommand) -> bool:
        if self._data is None or self._model is None:
            self._note = "目标未应用：没有模型"
            return False
        try:
            target = np.asarray(getattr(command, "target", []), dtype=float).reshape(-1)
        except Exception:                                             # noqa: BLE001
            self._note = "目标未应用：请输入数值"
            return False
        nq = int(getattr(self._model, "nq", 0))
        if target.size != nq:
            self._note = f"目标未应用：需要 {nq} 个值，收到 {target.size} 个"
            print(f"⚠ 【控制目标】{self._note}", flush=True)
            return False
        if not np.isfinite(target).all():
            self._note = "目标未应用：包含非有限数值"
            return False
        self._target = target.copy()
        self._source = "手动输入"
        self._note = "目标已发送给当前控制算法"
        self._forward(self._target.copy())
        print(f"【控制目标】已应用 {nq} 个关节目标", flush=True)
        return False

    @property
    def target(self) -> np.ndarray:
        return self._target.copy()

    @property
    def source(self) -> str:
        return self._source

    @property
    def note(self) -> str:
        return self._note

    def reset_to_current_position(self) -> None:
        """Reset 后让目标与复位姿态一致，避免再次 Run 时突然追逐旧目标。"""
        if self._data is None:
            return
        self._target = np.asarray(self._data.qpos, dtype=float).copy()
        self._source = "当前位置"
        self._note = "目标已随 Reset 恢复为当前位置"
        if self._target.size:
            self._forward(self._target.copy())


class ControlStatePublisher:
    """以较低频率发布 qpos/qvel/ctrl 和已接受的目标。"""

    def __init__(self, send, frequency: float = 10.0) -> None:
        self._send = send
        self._interval = 1.0 / max(frequency, 1e-6)
        self._next_publish = 0.0

    def maybe_publish(self, applier: ControlTargetApplier, model, data, wall_clock: float) -> bool:
        if wall_clock < self._next_publish:
            return False
        self._next_publish = wall_clock + self._interval
        self._send(ControlState(
            joint_names=_joint_labels(model),
            current_position=np.asarray(data.qpos, dtype=float).reshape(-1).tolist(),
            current_velocity=np.asarray(data.qvel, dtype=float).reshape(-1).tolist(),
            current_control=np.asarray(data.ctrl, dtype=float).reshape(-1).tolist(),
            target=applier.target.tolist(),
            target_source=applier.source,
            description=applier.note,
        ))
        return True
