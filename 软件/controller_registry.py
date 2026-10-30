"""通用控制器注册表。

它不替代 yubi 已有的插件系统，而是给“按名称选择控制器”提供稳定外观：
算法文件仍放在 ``算法库/``，真正的动态导入仍由 ``装配器.创建插件`` 完成。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import 项目 as _项目
import 装配器 as _装配器


@dataclass(frozen=True)
class ControllerInfo:
    key: str
    name: str
    version: str
    description: str
    author: str
    source: str


class ControllerRegistry:
    """按稳定名称注册、发现并创建控制器。

    ``register`` 用于纯 Python 工厂；``create`` 也能直接创建 ``算法库/`` 中已发现的
    控制插件。非控制型辅助插件（录制、辨识等 ``接管控制=False``）会被明确拒绝。
    """

    def __init__(self) -> None:
        self._factories: dict[str, Callable[..., object]] = {}
        self._metadata: dict[str, dict[str, str]] = {}

    def register(self, name: str, factory: Callable[..., object], **metadata: str) -> None:
        key = str(name).strip()
        if not key:
            raise ValueError("控制器注册名不能为空")
        if key in self._factories:
            raise KeyError(f"控制器已经注册：{key}")
        self._factories[key] = factory
        self._metadata[key] = {k: str(v) for k, v in metadata.items()}

    def unregister(self, name: str) -> None:
        self._factories.pop(str(name), None)
        self._metadata.pop(str(name), None)

    def keys(self) -> tuple[str, ...]:
        discovered = {str(item.get("插件") or "") for item in _项目.发现的算法()}
        return tuple(sorted(({x for x in discovered if x} | set(self._factories))))

    def create(self, name: str, **kwargs: Any) -> object:
        key = str(name).strip()
        if key in self._factories:
            instance = self._factories[key](**kwargs)
        else:
            if kwargs:
                raise TypeError(f"算法库控制器「{key}」不接受构造参数；请通过可调参数接口配置")
            instance, _meta, error = _装配器.创建插件(key)
            if instance is None:
                raise KeyError(f"无法创建控制器「{key}」：{error}")
        if not bool(getattr(instance, "接管控制", True)):
            raise TypeError(f"「{key}」是辅助插件，不是控制器（接管控制=False）")
        return instance

    def describe(self, name: str) -> ControllerInfo:
        key = str(name).strip()
        if key in self._factories:
            instance = self.create(key)
            meta = self._metadata.get(key, {})
            return ControllerInfo(
                key=key,
                name=meta.get("name", str(getattr(instance, "名称", key))),
                version=meta.get("version", str(getattr(instance, "版本", "-"))),
                description=meta.get("description", str(getattr(instance, "说明", ""))),
                author=meta.get("author", str(getattr(instance, "作者", ""))),
                source="registered factory",
            )
        instance, meta, error = _装配器.创建插件(key)
        if instance is None:
            raise KeyError(f"无法读取控制器「{key}」：{error}")
        if not bool(getattr(instance, "接管控制", True)):
            raise TypeError(f"「{key}」不是控制器")
        return ControllerInfo(
            key=key,
            name=str(meta.get("名称") or key),
            version=str(meta.get("版本") or "-"),
            description=str(meta.get("说明") or ""),
            author=str(meta.get("作者") or ""),
            source=str(meta.get("文件") or ""),
        )


controller_registry = ControllerRegistry()


def register_controller(name: str, **metadata: str):
    """装饰器形式：``@register_controller("my_pid")``。"""
    def decorate(factory: Callable[..., object]):
        controller_registry.register(name, factory, **metadata)
        return factory
    return decorate
