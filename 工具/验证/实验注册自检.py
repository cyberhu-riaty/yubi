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
from trajectory_runtime import (  # noqa: E402
    JointTrajectory,
    cartesian_path,
    clear_reference,
    matching_reference_velocity,
    publish_reference,
)
from official_api import messages, mujoco  # noqa: E402
from ui_bridge import PanelTargetMessage  # noqa: E402
import model_loader  # noqa: E402
import plugin_assembler  # noqa: E402
import project_registry  # noqa: E402


def main() -> int:
    passed = 0
    pd = controller_registry.create("joint_pd_control")
    assert bool(getattr(pd, "takes_control", False))
    print("[PASS] ControllerRegistry 按名称创建 PD")
    passed += 1

    pid = controller_registry.create("joint_pid_control")
    assert bool(getattr(pid, "takes_control", False))
    print("[PASS] ControllerRegistry 按名称创建 PID")
    passed += 1

    try:
        controller_registry.create("data_recorder")
    except TypeError:
        pass
    else:
        raise AssertionError("辅助插件不能冒充控制器")
    print("[PASS] ControllerRegistry 拒绝非控制型插件")
    passed += 1

    legacy_pd = controller_registry.create("关节pd控制")
    assert type(legacy_pd).__name__ == type(pd).__name__
    assert project_registry.algorithm_file("关节pd控制") == project_registry.algorithm_file(
        "joint_pd_control")
    print("[PASS] 历史中文插件标识自动映射到英文文件")
    passed += 1

    comparison_keys = (
        "ur5e_pd_plain", "ur5e_pid_plain", "ur5e_pd_gravity_ff",
    )
    expected = {"ur5e_pd_tracking", *comparison_keys}
    trajectory_keys = (
        "ur5e_pd_waypoint_tracking",
        "ur5e_pid_waypoint_tracking",
        "ur5e_pd_gravity_ff_waypoint_tracking",
    )
    expected.update(trajectory_keys)
    assert expected.issubset(experiment_registry.keys())
    for key in sorted(expected):
        experiment = experiment_registry.create(key)
        assert experiment.model_path.is_file()
        project = project_registry.load_project(experiment.project)
        instances, report = plugin_assembler.assemble_project(project, experiment.project)
        assert sum(bool(getattr(x, "takes_control", True)) for x in instances) == 1
        assert not any(line.startswith("✗") for line in report), report
    print("[PASS] 全部定点与轨迹实验的模型、控制器、辅助插件与项目装配一致")
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

    trajectory_group = [experiment_registry.create(key) for key in trajectory_keys]
    reference_trajectory = trajectory_group[0]
    for experiment in trajectory_group[1:]:
        assert experiment.model == reference_trajectory.model
        assert experiment.trajectory == reference_trajectory.trajectory
        assert experiment.initial_state == reference_trajectory.initial_state
        assert experiment.stop_condition == reference_trajectory.stop_condition
        assert experiment.recording == reference_trajectory.recording
    trajectory = JointTrajectory(reference_trajectory.trajectory)
    assert trajectory.dof == 6 and trajectory.duration == 16.0
    assert trajectory.interpolation == "clamped_cubic_spline"
    assert not np.allclose(trajectory.sample(0.0).qpos, trajectory.sample(16.0).qpos)
    assert not np.allclose(trajectory.sample(6.0).qpos, trajectory.sample(0.0).qpos)
    assert np.max(np.abs(trajectory.sample(0.0).qvel)) < 1e-12
    assert np.max(np.abs(trajectory.sample(16.0).qvel)) < 1e-12
    for waypoint_index, knot in enumerate(trajectory.times[1:-1], start=1):
        center = trajectory.sample(float(knot))
        assert np.allclose(center.qpos, trajectory.waypoints[waypoint_index], atol=1e-12)
        assert np.linalg.norm(center.qvel) > 1e-3, "中间航点不应再次停住"
        epsilon = 1e-4
        left = trajectory.sample(float(knot) - epsilon)
        right = trajectory.sample(float(knot) + epsilon)
        assert np.max(np.abs(right.qvel - left.qvel)) < 1e-3
        acceleration_left = (center.qvel - left.qvel) / epsilon
        acceleration_right = (right.qvel - center.qvel) / epsilon
        assert np.max(np.abs(acceleration_right - acceleration_left)) < 1e-3
    print("[PASS] 三组实验共享C2连续关节样条；起止静止、中间航点不停顿")
    passed += 1

    model = model_loader.load_model(mujoco, str(reference.model_path))
    cartesian = reference_trajectory.trajectory.get("cartesian_reference", {})
    assert cartesian.get("shape") == "smooth_s_curve" and cartesian.get("plane") == "XZ"
    planned_path, endpoint = cartesian_path(model, trajectory, mujoco, 321)
    x_start = float(cartesian["x_start_m"])
    x_end = float(cartesian["x_end_m"])
    z_center = float(cartesian["z_center_m"])
    amplitude = float(cartesian["amplitude_m"])
    cycles = float(cartesian["cycles"])
    progress = (planned_path[:, 0] - x_start) / (x_end - x_start)
    expected_z = z_center + amplitude * np.sin(2.0 * np.pi * cycles * progress)
    assert np.max(np.abs(planned_path[:, 2] - expected_z)) < 0.002
    assert np.ptp(planned_path[:, 1]) < 0.001
    assert np.max(np.diff(planned_path[:, 0])) < 1e-6
    assert abs(np.ptp(planned_path[:, 0]) - abs(x_end - x_start)) < 0.002
    assert abs(np.ptp(planned_path[:, 2]) - 2.0 * amplitude) < 0.002
    assert np.linalg.norm(planned_path[-1] - planned_path[0]) > 0.15
    assert endpoint[2] == cartesian["end_effector"]
    print("[PASS] 末端目标为平滑XZ S形多航点路径；形状误差<2 mm、平面漂移<1 mm")
    passed += 1

    reference_data = mujoco.MjData(model)
    moving_reference = trajectory.sample(6.0)
    publish_reference(reference_data, moving_reference)
    assert np.allclose(
        matching_reference_velocity(reference_data, moving_reference.qpos),
        moving_reference.qvel,
    )
    manual_target = moving_reference.qpos.copy()
    manual_target[0] += 0.1
    assert np.max(np.abs(matching_reference_velocity(reference_data, manual_target))) < 1e-12
    clear_reference(reference_data)
    print("[PASS] 轨迹目标使用目标速度，手动/不匹配目标自动回到零目标速度")
    passed += 1

    controls = []
    for name in ("joint_pd_plain", "joint_pid_plain", "joint_pd_gravity_ff"):
        controller = controller_registry.create(name)
        data = mujoco.MjData(model)
        home = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
        if home >= 0:
            mujoco.mj_resetDataKeyframe(model, data, home)
        controller.step(messages.StepEvent(model=model, data=data))
        controls.append(np.asarray(data.ctrl, dtype=float).copy())
    assert np.max(np.abs(controls[0])) < 1e-12
    assert np.max(np.abs(controls[1])) < 1e-12
    assert np.max(np.abs(controls[2])) > 1e-3
    print("[PASS] 零误差时纯 PD/PID 不输出补偿，PD＋重力前馈输出模型重力力矩")
    passed += 1

    # 连续轨迹每拍都会给一个略有变化的 q_ref。PID 必须保留积分；只有明显的
    # 目标跳变才重置，避免旧任务的积分带到新任务。
    tracking_pid = controller_registry.create("joint_pid_plain")
    data = mujoco.MjData(model)
    if home >= 0:
        mujoco.mj_resetDataKeyframe(model, data, home)
    base = np.asarray(data.qpos, dtype=float).copy()
    for step in range(1, 31):
        target = base.copy()
        target[1] += step * 0.001
        tracking_pid.on_panel_target(PanelTargetMessage(ctrl_target=target))
        tracking_pid.step(messages.StepEvent(model=model, data=data))
    assert float(tracking_pid.积分[1]) > 1e-5, "连续目标更新不应逐拍清空积分"
    jumped = target.copy()
    jumped[1] += 0.3
    tracking_pid.on_panel_target(PanelTargetMessage(ctrl_target=jumped))
    assert np.max(np.abs(tracking_pid.积分)) < 1e-12, "大幅目标跳变应清空旧积分"
    tracking_pid.KP = 5000.0
    tracking_pid.step(messages.StepEvent(model=model, data=data))
    assert abs(float(tracking_pid.积分[1])) < 1e-12, "力矩饱和且误差同向时不应继续积分"
    print("[PASS] PID 连续轨迹保留积分，大幅跳变清零，饱和时停止同向积分")
    passed += 1

    model_path = str(experiment_registry.create("ur5e_pd_tracking").model_path)
    default_project = project_registry.find_project_for_model(model_path)
    assert default_project not in {"UR5e_PD跟踪实验", "UR5e_PID跟踪实验"}
    print("[PASS] 普通模型选择不会误启动实验专用项目")
    passed += 1

    experiment = experiment_registry.create("ur5e_pd_tracking")
    initial_messages = experiment_cli.initial_messages(experiment)
    assert len(initial_messages) == 1
    assert list(getattr(initial_messages[0], "target", ())) == list(
        experiment.trajectory["target_qpos"])
    print("[PASS] 实验关节目标可转换为通用控制消息")
    passed += 1

    print(f"实验注册自检：{passed} 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
