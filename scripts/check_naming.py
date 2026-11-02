"""Check the incremental ASCII/English module migration boundary.

Legacy modules remain supported, but files already migrated in a completed batch
must not start importing their Chinese module names again.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_MODULES = {
    "插件系统", "界面桥", "模型加载", "逆解", "项目",
    "装配器", "命令桥", "控制台", "启动", "官方层", "Web桥",
    "重力桥", "模型桥", "契约", "平台适配层", "主程序窗口", "主程序Web",
    "参数辨识", "辨识桥", "录制桥",
}
PUBLIC_MODULES = (
    "plugin_system.py",
    "ui_bridge.py",
    "model_loader.py",
    "inverse_kinematics.py",
    "project_registry.py",
    "plugin_assembler.py",
    "command_bridge.py",
    "console_support.py",
    "runtime_engine.py",
    "official_api.py",
    "web_bridge.py",
    "simulation_control.py",
    "model_bridge.py",
    "contract.py",
    "platform_adapters/__init__.py",
    "desktop_app.py",
    "web_app.py",
    "parameter_identification.py",
    "identification_bridge.py",
    "recording_bridge.py",
    "experiment_bridge.py",
)
MIGRATED_FILES = (
    "run_yubi.py",
    "run_yubi_web.py",
    "软件/主程序窗口.py",
    "软件/主程序Web.py",
    "软件/controller_registry.py",
    "软件/experiment_registry.py",
    "软件/experiment_cli.py",
    "软件/trajectory_runtime.py",
    "软件/run_experiment.py",
    "算法库/通用/joint_pd_plain.py",
    "算法库/通用/joint_pid_plain.py",
    "算法库/通用/joint_pd_gravity_ff.py",
    "算法库/通用/trajectory_target_player.py",
    "算法库/通用/joint_pd_control.py",
    "算法库/通用/joint_pid_control.py",
    "算法库/通用/parameter_identification_plugin.py",
    "算法库/通用/data_recorder.py",
    "算法库/通用/two_point_task_space.py",
    "算法库/通用/sinusoidal_joint_motion.py",
    "算法库/通用/controller_template.py",
    "工具/验证/实验注册自检.py",
    "工具/验证/校验项目.py",
    "工具/验证/运行内核自检.py",
    "工具/验证/实验GUI闭环自检.py",
)
LEGACY_ALGORITHM_IDS = {
    "关节pd控制", "关节pid控制", "参数辨识插件", "数据录制",
    "末端两点运动", "正弦摆动", "轨迹目标执行",
}


def imported_modules(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, item.name.split(".")[0]) for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


def main() -> int:
    errors: list[str] = []
    for name in PUBLIC_MODULES:
        path = ROOT / "软件" / name
        if not path.is_file():
            errors.append(f"missing English public module: {path.relative_to(ROOT)}")
    for relative in MIGRATED_FILES:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing migrated file: {relative}")
            continue
        for line, module in imported_modules(path):
            if module in LEGACY_MODULES:
                errors.append(f"{relative}:{line} imports legacy module {module}")

    algorithm_directory = ROOT / "算法库" / "通用"
    for path in algorithm_directory.glob("*.py"):
        if not path.name.isascii():
            errors.append(f"non-ASCII algorithm filename: {path.relative_to(ROOT)}")

    for directory, fields in (
        (ROOT / "项目", ("算法",)),
        (ROOT / "实验", ("controllers", "preprocessors", "plugins")),
    ):
        for path in directory.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            names: list[str] = []
            for field in fields:
                value = data.get(field, [])
                if not isinstance(value, list):
                    continue
                for item in value:
                    names.append(str(item.get("插件") or "") if isinstance(item, dict)
                                 else str(item))
            for name in names:
                if name in LEGACY_ALGORITHM_IDS:
                    errors.append(
                        f"{path.relative_to(ROOT)} uses legacy algorithm id {name}")
    if errors:
        print("Naming migration check failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(
        f"Naming migration check passed: {len(PUBLIC_MODULES)} public modules, "
        f"{len(MIGRATED_FILES)} migrated callers."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
