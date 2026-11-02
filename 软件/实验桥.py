"""Legacy compatibility shim for :mod:`experiment_bridge`."""
from __future__ import annotations

import experiment_bridge as _bridge


实验命令 = _bridge.ExperimentCommand
实验状态 = _bridge.ExperimentState


class 实验应用器(_bridge.ExperimentRunner):
    """Compatibility adapter for older callers using Chinese method names."""

    def 收到模型(self, event) -> None:
        self.receive_model(event)

    def 发布(self, 强制: bool = False) -> None:
        self.publish(force=强制)


def __getattr__(name: str):
    return getattr(_bridge, name)


__all__ = ["实验命令", "实验状态", "实验应用器"]

