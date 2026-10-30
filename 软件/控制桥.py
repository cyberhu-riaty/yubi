"""控制桥：在工作台与控制算法之间传递关节目标，并回报当前关节状态。"""
from __future__ import annotations

import dataclasses
from typing import Callable

import numpy as np

from 官方层 import messages
from 界面桥 import 面板目标消息


@dataclasses.dataclass(frozen=True)
class 控制目标命令(messages.Snapshot):
    """GUI → 仿真：按 qpos 顺序给出一组关节目标，单位沿用模型（转动关节为 rad）。"""

    目标: object = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class 控制状态(messages.Snapshot):
    """仿真 → GUI：目标输入区需要的最小状态。"""

    关节名: list = dataclasses.field(default_factory=list)
    当前位置: list = dataclasses.field(default_factory=list)
    当前速度: list = dataclasses.field(default_factory=list)
    当前控制: list = dataclasses.field(default_factory=list)
    目标: list = dataclasses.field(default_factory=list)
    目标来源: str = "当前位置"
    说明: str = ""


def _关节标签(model) -> list[str]:
    """把 MuJoCo 的 joint/qpos 地址转换成与 qpos 等长的可读标签。"""
    nq = int(getattr(model, "nq", 0))
    标签 = [f"qpos[{i}]" for i in range(nq)]
    try:
        import mujoco
        地址 = [int(model.jnt_qposadr[j]) for j in range(int(model.njnt))] + [nq]
        for j in range(int(model.njnt)):
            名 = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j) or f"joint[{j}]"
            宽 = max(0, 地址[j + 1] - 地址[j])
            for k in range(宽):
                标签[地址[j] + k] = 名 if 宽 == 1 else f"{名}[{k}]"
    except Exception:                                                # noqa: BLE001
        pass
    return 标签


class 控制目标应用器:
    """校验 GUI 目标，再复用现有 ``面板目标消息`` 交给当前控制算法。"""

    名称 = "控制目标输入"
    版本 = "1.0"
    接管控制 = False

    def __init__(self, 转发: Callable[[object], None]) -> None:
        self._转发 = 转发
        self._模型 = None
        self._数据 = None
        self._目标 = np.zeros(0, dtype=float)
        self._来源 = "当前位置"
        self._说明 = "尚未加载可控制模型"

    def 收到模型(self, event) -> None:
        新模型 = getattr(event, "model", None)
        新数据 = getattr(event, "data", None)
        真换模型 = self._模型 is not 新模型
        self._模型, self._数据 = 新模型, 新数据
        if 新数据 is None:
            self._目标 = np.zeros(0, dtype=float)
            self._说明 = "尚未加载可控制模型"
            return
        nq = int(getattr(新模型, "nq", 0))
        if 真换模型 or self._目标.size != nq:
            self._目标 = np.asarray(新数据.qpos, dtype=float).copy()
            self._来源 = "当前位置"
        self._说明 = "没有关节可控制" if nq == 0 else "目标已就绪"
        if nq:
            self._转发(self._目标.copy())

    @messages.handler
    def 收目标(self, 命令: 控制目标命令) -> bool:
        if self._数据 is None or self._模型 is None:
            self._说明 = "目标未应用：没有模型"
            return False
        try:
            目标 = np.asarray(getattr(命令, "目标", []), dtype=float).reshape(-1)
        except Exception:                                             # noqa: BLE001
            self._说明 = "目标未应用：请输入数值"
            return False
        nq = int(getattr(self._模型, "nq", 0))
        if 目标.size != nq:
            self._说明 = f"目标未应用：需要 {nq} 个值，收到 {目标.size} 个"
            print(f"⚠ 【控制目标】{self._说明}", flush=True)
            return False
        if not np.isfinite(目标).all():
            self._说明 = "目标未应用：包含非有限数值"
            return False
        self._目标 = 目标.copy()
        self._来源 = "手动输入"
        self._说明 = "目标已发送给当前控制算法"
        self._转发(self._目标.copy())
        print(f"【控制目标】已应用 {nq} 个关节目标", flush=True)
        return False

    @property
    def 目标(self) -> np.ndarray:
        return self._目标.copy()

    @property
    def 来源(self) -> str:
        return self._来源

    @property
    def 说明(self) -> str:
        return self._说明

    def 重置为当前位置(self) -> None:
        """Reset 后让目标与复位姿态一致，避免再次 Run 时突然追逐旧目标。"""
        if self._数据 is None:
            return
        self._目标 = np.asarray(self._数据.qpos, dtype=float).copy()
        self._来源 = "当前位置"
        self._说明 = "目标已随 Reset 恢复为当前位置"
        if self._目标.size:
            self._转发(self._目标.copy())


class 控制状态发布器:
    """以较低频率发布 qpos/qvel/ctrl 和已接受的目标。"""

    def __init__(self, 发送函数, 频率: float = 10.0) -> None:
        self._发 = 发送函数
        self._间隔 = 1.0 / max(频率, 1e-6)
        self._下次 = 0.0

    def 也许发布(self, 应用器: 控制目标应用器, model, data, 墙钟: float) -> bool:
        if 墙钟 < self._下次:
            return False
        self._下次 = 墙钟 + self._间隔
        self._发(控制状态(
            关节名=_关节标签(model),
            当前位置=np.asarray(data.qpos, dtype=float).reshape(-1).tolist(),
            当前速度=np.asarray(data.qvel, dtype=float).reshape(-1).tolist(),
            当前控制=np.asarray(data.ctrl, dtype=float).reshape(-1).tolist(),
            目标=应用器.目标.tolist(),
            目标来源=应用器.来源,
            说明=应用器.说明,
        ))
        return True
