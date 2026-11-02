"""Legacy compatibility shim for :mod:`plugin_system`.

New controllers should import ``plugin_system``. Historical Chinese names are
kept here for old projects and external scripts during the migration.
"""
from __future__ import annotations

import plugin_system as _plugins


mujoco = _plugins.mujoco
messages = _plugins.messages
viewer_protocol = _plugins.viewer_protocol

控制插件 = _plugins.ControlPlugin
每步 = _plugins.step_handler
优先级 = _plugins.Priority
固定一步 = _plugins.FixedStep
实时固定步进 = _plugins.RealtimeFixedStep
安全注册表 = _plugins.SafeRegistry

取注册表 = _plugins.get_registry
版本自检 = _plugins.check_version
打印插件清单 = _plugins.print_plugin_list
通知模型加载 = _plugins.notify_model_loaded
收集算法信息 = _plugins.collect_algorithm_info
滑块目标 = _plugins.slider_target
打印插件状态 = _plugins.print_plugin_status


def __getattr__(name: str):
    return getattr(_plugins, name)


__all__ = [
    "mujoco", "messages", "viewer_protocol", "控制插件", "每步", "优先级",
    "固定一步", "实时固定步进", "安全注册表", "取注册表", "版本自检",
    "打印插件清单", "通知模型加载", "收集算法信息", "滑块目标", "打印插件状态",
]
