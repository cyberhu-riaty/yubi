"""GUI 与浏览器入口共用的实验参数解析接缝。"""
from __future__ import annotations

import os
import env_config

from experiment_registry import Experiment, experiment_registry


def add_experiment_argument(parser) -> None:
    parser.add_argument(
        "--experiment", dest="experiment", default=None,
        help="按注册名加载完整实验（例如 ur5e_pd_tracking）",
    )


def apply_experiment(args) -> Experiment | None:
    name = str(getattr(args, "experiment", "") or "").strip()
    if not name:
        return None
    if getattr(args, "model", None) or getattr(args, "project", None):
        raise ValueError("--experiment 已经包含模型和项目，不能同时再给 --模型/--项目")
    experiment = experiment_registry.create(name)
    args.model = str(experiment.model_path)
    args.project = experiment.project
    env_config.write("YUBI_MODEL", str(experiment.model_path))
    os.environ["YUBI_CURRENT_EXPERIMENT"] = experiment.key
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
    import command_bridge
    message, reason = command_bridge.create_message(
        "命令.控制目标", {"target": [float(x) for x in target]})
    if message is None:
        raise RuntimeError(f"实验初始控制目标构造失败：{reason}")
    return [message]
