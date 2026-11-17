"""Check migrated APIs and the repository-wide internal naming baseline.

Legacy modules remain supported, but files already migrated in a completed batch
must not start importing their Chinese module names again.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_MODULES = {
    "插件系统", "界面桥", "项目",
    "装配器", "命令桥", "控制台", "启动", "官方层", "Web桥",
    "契约", "平台适配层", "主程序窗口", "主程序Web",
    "参数辨识", "辨识桥", "录制桥", "控制桥", "指标桥", "系统桥",
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
    "control_bridge.py",
    "metrics_bridge.py",
    "system_bridge.py",
    "model_bridge.py",
    "contract.py",
    "platform_adapters/__init__.py",
    "desktop_app.py",
    "web_app.py",
    "parameter_identification.py",
    "identification_bridge.py",
    "recording_bridge.py",
    "experiment_bridge.py",
    "planning_bridge.py",
    "trajectory_planning.py",
    "parameter_bridge.py",
)
MIGRATED_FILES = (
    "run_yubi.py",
    "run_yubi_web.py",
    "软件/desktop_app.py",
    "软件/web_app.py",
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
    "工具/验证/experiment_registry_selfcheck.py",
    "工具/验证/project_selfcheck.py",
    "工具/验证/runtime_selfcheck.py",
    "工具/验证/experiment_gui_selfcheck.py",
    "工具/验证/trajectory_planning_selfcheck.py",
    "工具/验证/parameter_transaction_selfcheck.py",
)
LEGACY_ALGORITHM_IDS = {
    "关节pd控制", "关节pid控制", "参数辨识插件", "数据录制",
    "末端两点运动", "正弦摆动", "轨迹目标执行",
}
REMOVED_LEGACY_MODULES = {
    "实验桥", "规划桥", "轨迹规划", "逆解", "模型加载", "模型桥", "重力桥", "参数桥",
    "插件系统", "装配器", "项目", "启动", "主程序窗口", "主程序Web",
    "控制桥", "指标桥", "系统桥",
    "宿主窗口", "定时器", "平台适配层",
}
# These shims remain available to external plugins, but application code must
# depend on the English implementation so the old import cannot grow back.
COMPATIBILITY_ONLY_MODULES = {"官方层", "契约"}
REMOVED_PLUGIN_METHODS = {
    "可调参数", "设置参数", "收到模型", "模型兼容性", "每步控制", "每步目标",
    "每步录制", "指标", "插件状态", "绑定模型路径", "模型已切换",
}
REMOVED_PLUGIN_ATTRIBUTES = {"名称", "英文名", "版本", "作者", "说明", "接管控制"}
ASCII_IDENTIFIER_FILES = (
    "工具/import_model.py",
    "工具/urdf_to_mjcf.py",
    "工具/generate_frontend_assets.py",
    "工具/验证/contract_selfcheck.py",
    "frontend/tests/fake_backend.py",
    "frontend/tests/browser_smoke.py",
    "软件/contract.py",
    "软件/契约.py",
    "软件/official_api.py",
    "软件/官方层.py",
    "工具/验证/official_api_selfcheck.py",
    "工具/验证/platform_selfcheck.py",
    "软件/plugin_system.py",
    "软件/plugin_assembler.py",
    "软件/runtime_engine.py",
    "软件/desktop_app.py",
    "软件/web_app.py",
)
HAN = re.compile(r"[\u4e00-\u9fff]")


def chinese_identifiers(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        values: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            values.append(node.name)
        elif isinstance(node, ast.Name):
            values.append(node.id)
        elif isinstance(node, ast.Attribute):
            values.append(node.attr)
        elif isinstance(node, ast.arg):
            values.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            values.append(node.arg)
        found.extend((getattr(node, "lineno", 0), value) for value in values if HAN.search(value))
    return found


def imported_modules(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, item.name.split(".")[0]) for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            # Device/platform packages also have their own 契约 modules. Relative
            # imports resolve there, not to the root compatibility shim.
            found.append((node.lineno, "." * node.level + node.module.split(".")[0]))
    return found


def check_migration_boundary() -> int:
    errors: list[str] = []
    for module in REMOVED_LEGACY_MODULES:
        removed_path = ROOT / "软件" / f"{module}.py"
        if removed_path.exists():
            errors.append(f"removed legacy module still exists: 软件/{module}.py")
    from audit_naming import SCOPE_FILE, discover_files, read_json
    for path in discover_files(ROOT, read_json(SCOPE_FILE)):
        if path.suffix != ".py":
            continue
        for line, module in imported_modules(path):
            if module in REMOVED_LEGACY_MODULES:
                errors.append(
                    f"{path.relative_to(ROOT)}:{line} imports removed module {module}")
            elif module in COMPATIBILITY_ONLY_MODULES:
                replacement = {"官方层": "official_api", "契约": "contract"}[module]
                errors.append(
                    f"{path.relative_to(ROOT)}:{line} imports compatibility module {module}; "
                    f"use {replacement}")
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

    for relative in ASCII_IDENTIFIER_FILES:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing ASCII-identifier module: {relative}")
            continue
        for line, name in chinese_identifiers(path):
            errors.append(f"{relative}:{line} contains Chinese identifier {name}")

    algorithm_directory = ROOT / "算法库" / "通用"
    for path in algorithm_directory.glob("*.py"):
        if not path.name.isascii():
            errors.append(f"non-ASCII algorithm filename: {path.relative_to(ROOT)}")

    parameter_api_paths = (
        ROOT / "软件" / "plugin_system.py",
        ROOT / "软件" / "parameter_bridge.py",
        ROOT / "软件" / "control_bridge.py",
        ROOT / "软件" / "experiment_bridge.py",
        *algorithm_directory.glob("*.py"),
    )
    for path in parameter_api_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name in REMOVED_PLUGIN_METHODS:
                errors.append(
                    f"{path.relative_to(ROOT)}:{node.lineno} defines removed plugin method {node.name}")
        for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            for member in class_node.body:
                if not isinstance(member, ast.Assign):
                    continue
                for target in member.targets:
                    if isinstance(target, ast.Name) and target.id in REMOVED_PLUGIN_ATTRIBUTES:
                        errors.append(
                            f"{path.relative_to(ROOT)}:{member.lineno} defines removed plugin attribute {target.id}")
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "插件类" for target in targets):
                errors.append(
                    f"{path.relative_to(ROOT)}:{node.lineno} defines removed plugin_class alias 插件类")

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
        f"Migrated API boundary passed: {len(PUBLIC_MODULES)} public modules, "
        f"{len(MIGRATED_FILES)} migrated callers."
    )
    return 0


def main() -> int:
    status = check_migration_boundary()
    if status:
        return status
    from audit_naming import main as audit_main
    return audit_main()


if __name__ == "__main__":
    raise SystemExit(main())
