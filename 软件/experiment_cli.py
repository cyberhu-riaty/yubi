"""GUI 与浏览器入口共用的实验参数解析接缝。"""
from __future__ import annotations

import os

from experiment_registry import Experiment, experiment_registry


def add_experiment_argument(parser) -> None:
    parser.add_argument(
        "--实验", "--experiment", dest="实验", default=None,
        help="按注册名加载完整实验（例如 ur5e_pd_tracking）",
    )


def apply_experiment(args) -> Experiment | None:
    name = str(getattr(args, "实验", "") or "").strip()
    if not name:
        return None
    if getattr(args, "模型", None) or getattr(args, "项目", None):
        raise ValueError("--实验 已经包含模型和项目，不能同时再给 --模型/--项目")
    experiment = experiment_registry.create(name)
    args.模型 = str(experiment.model_path)
    args.项目 = experiment.project
    os.environ["驭臂_模型"] = str(experiment.model_path)
    os.environ["驭臂_当前实验"] = experiment.key
    return experiment


def enqueue_initial_commands(experiment: Experiment | None, queue) -> None:
    """把实验目标送进现有命令通道；不直接碰 MjData，也不自动按 Run。"""
    for message in initial_messages(experiment):
        put = getattr(queue, "put_nowait", None)
        if callable(put):
            put(message)
        else:
            queue.append(message)


def initial_messages(experiment: Experiment | None) -> list[object]:
    """把实验初值转换为已校验的通用消息，供同步和后台入口共用。"""
    if experiment is None:
        return []
    target = experiment.trajectory.get("target_qpos")
    if target is None:
        return []
    import 命令桥
    message, reason = 命令桥.造消息(
        "命令.控制目标", {"目标": [float(x) for x in target]})
    if message is None:
        raise RuntimeError(f"实验初始控制目标构造失败：{reason}")
    return [message]
