"""Legacy compatibility shim for :mod:`model_bridge`."""
from __future__ import annotations

import model_bridge as _models


包根 = _models.PACKAGE_ROOT
模型目录 = _models.MODEL_DIRECTORY
空场景路径 = _models.EMPTY_SCENE_PATH
读取模型库 = _models.read_model_library
绝对路径 = _models.absolute_path
显示名 = _models.display_name
读取设置 = _models.read_setting
写入设置 = _models.write_setting
读取上次模型 = _models.read_last_model
记住模型 = _models.remember_model
取资产清单 = _models.asset_manifest
选择本地模型文件 = _models.select_local_model_file

换模型命令 = _models.SwitchModelCommand
模型状态 = _models.ModelState
资产库 = _models.AssetLibrary
模型应用器 = _models.ModelApplier
发布器 = _models.ModelPublisher
资产库发布器 = _models.AssetLibraryPublisher
项目状态 = _models.ProjectState
应用算法命令 = _models.ApplyAlgorithmsCommand
算法选择器 = _models.AlgorithmSelector
项目状态发布器 = _models.ProjectStatePublisher
后台选择器 = _models.BackgroundSelector


def __getattr__(name: str):
    return getattr(_models, name)


__all__ = [
    "包根", "模型目录", "空场景路径", "读取模型库", "绝对路径", "显示名",
    "读取设置", "写入设置", "读取上次模型", "记住模型", "取资产清单",
    "选择本地模型文件", "换模型命令", "模型状态", "资产库", "模型应用器",
    "发布器", "资产库发布器", "项目状态", "应用算法命令", "算法选择器",
    "项目状态发布器", "后台选择器",
]
