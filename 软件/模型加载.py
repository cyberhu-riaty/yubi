"""Legacy compatibility shim for :mod:`model_loader`."""
from __future__ import annotations

import model_loader as _loader


包根 = _loader.PACKAGE_ROOT
公共场景路径 = _loader.COMMON_SCENE_PATH
加载模型 = _loader.load_model
加载规格 = _loader.load_spec


def __getattr__(name: str):
    return getattr(_loader, name)


__all__ = ["包根", "公共场景路径", "加载模型", "加载规格"]
