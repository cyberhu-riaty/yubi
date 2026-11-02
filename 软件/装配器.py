"""Legacy compatibility shim for :mod:`plugin_assembler`."""
from __future__ import annotations

import plugin_assembler as _assembler


导入算法文件 = _assembler.import_algorithm_file
找插件类 = _assembler.find_plugin_class
读元信息 = _assembler.read_metadata
检查兼容性 = _assembler.check_compatibility
创建插件 = _assembler.create_plugin
按项目装配 = _assembler.assemble_project
从模型建项目 = _assembler.project_from_model


def __getattr__(name: str):
    return getattr(_assembler, name)


__all__ = [
    "导入算法文件", "找插件类", "读元信息", "检查兼容性",
    "创建插件", "按项目装配", "从模型建项目",
]
