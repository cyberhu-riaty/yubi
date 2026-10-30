"""实验定义与按名称加载接口。

实验只描述“这次要组合什么”，不包含 GUI 代码和 MuJoCo 主循环。当前先支持 JSON
实验清单；以后有复杂初始化逻辑时，也可以用 ``register`` 注册 Python 工厂。
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from controller_registry import ControllerRegistry, controller_registry
import 项目 as _项目


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT_DIRECTORY = PACKAGE_ROOT / "实验"


@dataclass(frozen=True)
class Experiment:
    """一次可复现仿真实验的通用定义。"""

    key: str
    name: str
    model: str
    project: str
    controllers: tuple[str, ...]
    plugins: tuple[str, ...] = ()
    trajectory: Mapping[str, Any] = field(default_factory=dict)
    initial_state: Mapping[str, Any] = field(default_factory=dict)
    stop_condition: Mapping[str, Any] = field(default_factory=dict)
    recording: Mapping[str, Any] = field(default_factory=dict)
    result: Mapping[str, Any] = field(default_factory=dict)
    description: str = ""

    @property
    def model_path(self) -> Path:
        path = Path(self.model)
        return path.resolve() if path.is_absolute() else (PACKAGE_ROOT / path).resolve()

    @property
    def duration(self) -> float:
        if str(self.stop_condition.get("type", "simulation_time")) != "simulation_time":
            raise ValueError(f"实验「{self.key}」暂不支持停止条件：{self.stop_condition}")
        return float(self.stop_condition.get("seconds", 0.0))

    @property
    def algorithm_names(self) -> tuple[str, ...]:
        """控制器在前、辅助插件在后；顺序就是插件执行顺序。"""
        return tuple(dict.fromkeys((*self.controllers, *self.plugins)))

    def should_stop(self, simulation_time: float) -> bool:
        return self.duration > 0 and float(simulation_time) >= self.duration

    def validate(self, controllers: ControllerRegistry = controller_registry) -> list[str]:
        errors: list[str] = []
        if not self.key:
            errors.append("实验注册名为空")
        if not self.model_path.is_file():
            errors.append(f"模型不存在：{self.model_path}")
        project = _项目.读项目(self.project) if self.project else None
        if not project:
            errors.append(f"项目不存在：{self.project or '（空）'}")
        else:
            configured = tuple(
                str(item.get("插件") or "") for item in _项目.解析算法(project)
                if isinstance(item, dict)
            )
            if configured != self.algorithm_names:
                errors.append(
                    f"项目算法与实验定义不一致：项目={configured}，实验={self.algorithm_names}")
        for name in self.controllers:
            try:
                controllers.describe(name)
            except Exception as exc:                                  # noqa: BLE001
                errors.append(f"控制器「{name}」不可用：{exc}")
        if self.duration <= 0:
            errors.append("停止时间必须大于 0 秒")
        return errors


class ExperimentRegistry:
    """通过实验名称注册、列出并创建完整实验。"""

    def __init__(self, directory: str | Path = EXPERIMENT_DIRECTORY) -> None:
        self.directory = Path(directory)
        self._factories: dict[str, Callable[[], Experiment]] = {}

    def register(self, name: str, factory: Callable[[], Experiment]) -> None:
        key = str(name).strip()
        if not key:
            raise ValueError("实验注册名不能为空")
        if key in self._factories or (self.directory / f"{key}.json").exists():
            raise KeyError(f"实验已经注册：{key}")
        self._factories[key] = factory

    def keys(self) -> tuple[str, ...]:
        files = {p.stem for p in self.directory.glob("*.json") if not p.name.startswith("_")}
        return tuple(sorted(files | set(self._factories)))

    def create(self, name: str, validate: bool = True) -> Experiment:
        key = str(name).strip()
        if key in self._factories:
            experiment = self._factories[key]()
        else:
            path = self.directory / f"{key}.json"
            if not path.is_file():
                available = "、".join(self.keys()) or "（无）"
                raise KeyError(f"找不到实验「{key}」；现有：{available}")
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            experiment = self._from_mapping(key, data)
        if validate:
            errors = experiment.validate()
            if errors:
                raise ValueError("；".join(errors))
        return experiment

    @staticmethod
    def _from_mapping(default_key: str, data: Mapping[str, Any]) -> Experiment:
        controllers = tuple(str(x) for x in data.get("controllers", ()) if str(x).strip())
        plugins = tuple(str(x) for x in data.get("plugins", ()) if str(x).strip())
        return Experiment(
            key=str(data.get("key") or default_key),
            name=str(data.get("name") or data.get("key") or default_key),
            model=str(data.get("model") or ""),
            project=str(data.get("project") or ""),
            controllers=controllers,
            plugins=plugins,
            trajectory=dict(data.get("trajectory") or {}),
            initial_state=dict(data.get("initial_state") or {}),
            stop_condition=dict(data.get("stop_condition") or {}),
            recording=dict(data.get("recording") or {}),
            result=dict(data.get("result") or {}),
            description=str(data.get("description") or ""),
        )


experiment_registry = ExperimentRegistry()


def register_experiment(name: str):
    """装饰器形式：``@register_experiment("my_experiment")``。"""
    def decorate(factory: Callable[[], Experiment]):
        experiment_registry.register(name, factory)
        return factory
    return decorate
