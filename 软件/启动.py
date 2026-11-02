"""Legacy compatibility shim for :mod:`runtime_engine`.

New code must import ``runtime_engine``. Historical Chinese names remain here
so old tools and external scripts continue to work during the migration.
"""
from __future__ import annotations

import runtime_engine as _runtime


等待就绪 = _runtime.wait_until_ready
请求停止 = _runtime.stop
设状态观察者 = _runtime.set_state_observer
设模型观察者 = _runtime.set_model_observer
取命令队列 = _runtime.command_queue
_排空本地队列 = _runtime.drain_local_queue


def 启动外壳(
    配置,
    模型路径: str,
    窗口类,
    插件列表: list,
    注册表,
    通知模型加载,
    项目名: str = "",
    无窗: bool = False,
    后台线程: bool = False,
    预置消息: list | tuple | None = None,
    实验名: str = "",
):
    return _runtime.start(
        配置,
        模型路径,
        窗口类,
        插件列表,
        注册表,
        通知模型加载,
        project_name=项目名,
        headless=无窗,
        background_thread=后台线程,
        initial_messages=预置消息,
        experiment_name=实验名,
    )


def __getattr__(name: str):
    return getattr(_runtime, name)


__all__ = [
    "等待就绪", "请求停止", "设状态观察者", "设模型观察者",
    "取命令队列", "启动外壳", "_排空本地队列",
]
