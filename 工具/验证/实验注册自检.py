"""控制器注册、实验注册和项目装配的快速自检。"""
from __future__ import annotations

from pathlib import Path
import os
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SOFTWARE = ROOT / "软件"
if str(SOFTWARE) not in sys.path:
    sys.path.insert(0, str(SOFTWARE))
os.environ["驭臂_关Web"] = "1"

from controller_registry import controller_registry  # noqa: E402
from experiment_registry import experiment_registry  # noqa: E402
import experiment_cli  # noqa: E402
from 官方层 import messages, mujoco  # noqa: E402
import 模型加载  # noqa: E402
import 装配器  # noqa: E402
import 项目  # noqa: E402


def main() -> int:
    passed = 0
    pd = controller_registry.create("关节pd控制")
    assert bool(getattr(pd, "接管控制", False))
    print("[PASS] ControllerRegistry 按名称创建 PD")
    passed += 1

    pid = controller_registry.create("关节pid控制")
    assert bool(getattr(pid, "接管控制", False))
    print("[PASS] ControllerRegistry 按名称创建 PID")
    passed += 1

    try:
        controller_registry.create("数据录制")
    except TypeError:
        pass
    else:
        raise AssertionError("辅助插件不能冒充控制器")
    print("[PASS] ControllerRegistry 拒绝非控制型插件")
    passed += 1

    comparison_keys = (
        "ur5e_pd_plain", "ur5e_pid_plain", "ur5e_pd_gravity_ff",
    )
    expected = {"ur5e_pd_tracking", *comparison_keys}
    assert expected.issubset(experiment_registry.keys())
    for key in sorted(expected):
        experiment = experiment_registry.create(key)
        assert experiment.model_path.is_file()
        project = 项目.读项目(experiment.project)
        instances, report = 装配器.按项目装配(project, experiment.project)
        assert sum(bool(getattr(x, "接管控制", True)) for x in instances) == 1
        assert not any(line.startswith("✗") for line in report), report
    print("[PASS] 四个实验的模型、控制器、辅助插件与项目装配一致")
    passed += 1

    comparison = [experiment_registry.create(key) for key in comparison_keys]
    reference = comparison[0]
    for experiment in comparison[1:]:
        assert experiment.model == reference.model
        assert experiment.trajectory == reference.trajectory
        assert experiment.initial_state == reference.initial_state
        assert experiment.stop_condition == reference.stop_condition
        assert experiment.recording == reference.recording
    print("[PASS] 三组对比实验使用相同模型、目标、初始状态、时长和记录条件")
    passed += 1

    model = 模型加载.加载模型(mujoco, str(reference.model_path))
    controls = []
    for name in ("joint_pd_plain", "joint_pid_plain", "joint_pd_gravity_ff"):
        controller = controller_registry.create(name)
        data = mujoco.MjData(model)
        home = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
        if home >= 0:
            mujoco.mj_resetDataKeyframe(model, data, home)
        controller.每步控制(messages.StepEvent(model=model, data=data))
        controls.append(np.asarray(data.ctrl, dtype=float).copy())
    assert np.max(np.abs(controls[0])) < 1e-12
    assert np.max(np.abs(controls[1])) < 1e-12
    assert np.max(np.abs(controls[2])) > 1e-3
    print("[PASS] 零误差时纯 PD/PID 不输出补偿，PD＋重力前馈输出模型重力力矩")
    passed += 1

    model_path = str(experiment_registry.create("ur5e_pd_tracking").model_path)
    default_project = 项目.按模型找项目(model_path)
    assert default_project not in {"UR5e_PD跟踪实验", "UR5e_PID跟踪实验"}
    print("[PASS] 普通模型选择不会误启动实验专用项目")
    passed += 1

    experiment = experiment_registry.create("ur5e_pd_tracking")
    initial_messages = experiment_cli.initial_messages(experiment)
    assert len(initial_messages) == 1
    assert list(getattr(initial_messages[0], "目标", ())) == list(
        experiment.trajectory["target_qpos"])
    print("[PASS] 实验关节目标可转换为通用控制消息")
    passed += 1

    print(f"实验注册自检：{passed} 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
