"""Legacy compatibility shim for :mod:`project_registry`."""
from __future__ import annotations

import project_registry as _projects


软件目录 = _projects.软件目录
包根 = _projects.PACKAGE_ROOT
项目目录 = _projects.PROJECT_DIRECTORY
算法库目录 = _projects.ALGORITHM_DIRECTORY
模型目录 = _projects.MODEL_DIRECTORY
设置路径 = _projects.SETTINGS_PATH
后缀 = _projects.PROJECT_SUFFIX

绝对 = _projects.absolute_path
相对包根 = _projects.relative_to_package
模型库条目 = _projects.model_library_entries
显示模型名 = _projects.display_model_name
列出项目 = _projects.list_projects
项目文件路径 = _projects.project_file_path
读项目 = _projects.load_project
保存项目 = _projects.save_project
按模型找项目 = _projects.find_project_for_model
算法别名 = _projects.ALGORITHM_ALIASES
规范算法名 = _projects.normalize_algorithm_name
算法文件 = _projects.algorithm_file
解析算法 = _projects.parse_algorithms
发现的算法 = _projects.discover_algorithms
读参数 = _projects.load_parameters
保存参数 = _projects.save_parameters
读取上次项目 = _projects.load_last_project
保存上次项目 = _projects.save_last_project


def __getattr__(name: str):
    return getattr(_projects, name)


__all__ = [
    "软件目录", "包根", "项目目录", "算法库目录", "模型目录", "设置路径", "后缀",
    "绝对", "相对包根", "模型库条目", "显示模型名", "列出项目", "项目文件路径",
    "读项目", "保存项目", "按模型找项目", "算法别名", "规范算法名", "算法文件",
    "解析算法", "发现的算法", "读参数", "保存参数", "读取上次项目", "保存上次项目",
]
