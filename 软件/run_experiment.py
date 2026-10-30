"""按注册名运行一次无界面实验，并导出统一结果。"""
from __future__ import annotations

import argparse
import os
import time

os.environ.setdefault("驭臂_关Web", "1")

import experiment_registry as _experiments
import experiment_cli
from experiment_results import ExperimentResultRecorder
import 控制台
import 命令桥
import 启动
import 插件系统
import 装配器
import 项目


控制台.准备输出()


def run(name: str, duration_override: float | None = None) -> str:
    experiment = _experiments.experiment_registry.create(name)
    project_data = 项目.读项目(experiment.project)
    plugins, report = 装配器.按项目装配(project_data, experiment.project)
    for line in report:
        print(f"  {line}", flush=True)

    recorder = ExperimentResultRecorder(
        experiment, float(experiment.recording.get("frequency_hz", 100.0)))
    启动.请求停止(1.0)
    启动._排空本地队列()                                      # noqa: SLF001
    启动.设状态观察者(recorder.observe)
    # 离线实验按“一个循环 = 一个物理步”尽快计算，不等待真实墙钟；GUI 入口仍使用
    # 官方 StepControl 的实时节拍，两者控制/插件/结果接口完全相同。
    registry = 插件系统.安全注册表(plugins, 步进插件=插件系统.固定一步())
    config = 插件系统.viewer_protocol.ViewerConfig(
        title=experiment.name, width=1200, height=800, gfx="")
    try:
        code = 启动.启动外壳(
            config, str(experiment.model_path), None, plugins, registry,
            插件系统.通知模型加载, 项目名=experiment.project,
            无窗=True, 后台线程=True)
        if code != 0:
            raise RuntimeError(f"仿真引擎启动失败，返回码 {code}")
        ready, reason = 启动.等待就绪(20.0)
        if not ready:
            raise RuntimeError(reason)

        if bool(experiment.recording.get("enabled", True)):
            命令桥.命令入队(启动.取命令队列(), "命令.录制", {
                "动作": "开始",
                "频率": float(experiment.recording.get("frequency_hz", 100.0)),
                "备注": f"experiment={experiment.key}",
            }, 打印=False)
        experiment_cli.enqueue_initial_commands(experiment, 启动.取命令队列())
        命令桥.命令入队(
            启动.取命令队列(), "命令.仿真", {"动作": "运行"}, 打印=False)

        duration = float(duration_override) if duration_override is not None else experiment.duration
        deadline = time.monotonic() + max(20.0, duration * 10.0)
        while recorder.latest_time < duration and time.monotonic() < deadline:
            time.sleep(0.01)
        if recorder.latest_time < duration:
            raise TimeoutError(
                f"实验没有在期限内到达 {duration:g}s（当前 {recorder.latest_time:g}s）")

        命令桥.命令入队(
            启动.取命令队列(), "命令.仿真", {"动作": "暂停"}, 打印=False)
        if bool(experiment.recording.get("enabled", True)):
            命令桥.命令入队(
                启动.取命令队列(), "命令.录制", {"动作": "停止"}, 打印=False)
        time.sleep(0.3)  # 给仿真线程一小段时间处理暂停与录制收尾命令。
        output = recorder.export()
        print(f"✓ 实验完成：{experiment.key}\n  结果目录：{output}", flush=True)
        return str(output)
    finally:
        启动.请求停止(5.0)
        启动.设状态观察者(None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按注册名运行 yubi 无界面实验")
    parser.add_argument("experiment", nargs="?", default="ur5e_pd_tracking")
    parser.add_argument("--时长", "--duration", dest="duration", type=float, default=None,
                        help="仅用于调试/冒烟测试；正常运行使用实验定义的停止条件")
    parser.add_argument("--列出", "--list", dest="list_only", action="store_true")
    args = parser.parse_args(argv)
    if args.list_only:
        for key in _experiments.experiment_registry.keys():
            item = _experiments.experiment_registry.create(key)
            print(f"{key:24} {item.name}")
        return 0
    run(args.experiment, args.duration)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
