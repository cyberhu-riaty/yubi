"""Check the adapter's observable behavior with controlled Studio dependencies."""
from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "软件"


def load_source(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_dependencies(blocked: str | None = None):
    """Emulate import results without requiring MuJoCo or a GUI on CI."""
    modules = {name: ModuleType(name) for name in (
        "messages", "step_control", "viewer_app", "viewer_protocol", "launch_native",
        "launch_thread", "viewer_handle", "endpoints", "plugin_registry", "sim", "ux",
    )}
    for name in ("handler", "Priority", "Message", "Snapshot", "Event", "StepEvent",
                 "ModelEvent", "StateSnapshot", "StepControlSnapshot"):
        setattr(modules["messages"], name, type(name, (), {}))
    modules["step_control"].StepControl = type("StepControl", (), {})
    modules["viewer_protocol"].ViewerConfig = type("ViewerConfig", (), {})
    mujoco = ModuleType("mujoco")
    mujoco.__version__ = "3.13.0"
    experimental = ModuleType("mujoco.experimental")
    experimental.studio = ModuleType("studio")
    implot = ModuleType("mujoco.experimental.implot")
    implot.implot = ModuleType("implot")
    imgui = ModuleType("dear_imgui")
    imported = []
    original_import = builtins.__import__

    def importer(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mujoco" or name.startswith("mujoco.experimental"):
            imported.append(name)
            if name == blocked:
                raise ModuleNotFoundError(f"test missing dependency: {name}")
            if name == "mujoco":
                return mujoco
            if name == "mujoco.experimental":
                return experimental
            if name == "mujoco.experimental.implot":
                return implot
            if name == "mujoco.experimental.dear_imgui.dear_imgui":
                return imgui
            return modules[name.rsplit(".", 1)[1]]
        return original_import(name, globals, locals, fromlist, level)

    return modules, imported, importer


class OfficialApiTests(unittest.TestCase):
    def load_adapter(self, blocked=None):
        modules, imported, importer = fake_dependencies(blocked)
        with patch("builtins.__import__", side_effect=importer):
            adapter = load_source(RUNTIME / "official_api.py", "adapter_under_test")
        return adapter, modules, imported, importer

    def test_required_exports_keep_class_identity_and_self_check_counts(self):
        adapter, modules, _, _ = self.load_adapter()
        self.assertIs(adapter.messages, modules["messages"])
        self.assertIs(adapter.messages.StepEvent, modules["messages"].StepEvent)
        self.assertEqual(adapter.self_check(), (26, 26, []))

    def test_gui_modules_are_lazy_and_cached(self):
        adapter, _, imported, importer = self.load_adapter()
        optional = ("mujoco.experimental.studio.ux", "mujoco.experimental.implot",
                    "mujoco.experimental.dear_imgui.dear_imgui")
        self.assertFalse(set(optional) & set(imported))
        with patch("builtins.__import__", side_effect=importer):
            for name in ("ux", "implot", "dear_imgui"):
                self.assertIs(getattr(adapter, name), getattr(adapter, name))
        for name in optional:
            self.assertEqual(imported.count(name), 1)

    def test_missing_mujoco_does_not_prevent_self_check(self):
        adapter, _, _, _ = self.load_adapter("mujoco")
        passed, total, issues = adapter.self_check()
        self.assertEqual(passed, 0)
        self.assertGreater(total, 0)
        self.assertTrue(any("mujoco" in issue for issue in issues))
        with self.assertRaises(SystemExit) as caught:
            _ = adapter.messages
        self.assertIn("test missing dependency", str(caught.exception))
        self.assertIn("run_yubi.py", str(caught.exception))

    def test_partial_dependency_failure_is_reported_without_replacing_loaded_classes(self):
        adapter, modules, _, _ = self.load_adapter("mujoco.experimental.studio.viewer_handle")
        self.assertIs(adapter.messages.Snapshot, modules["messages"].Snapshot)
        passed, total, issues = adapter.self_check()
        self.assertLess(passed, total)
        self.assertTrue(any("viewer_handle" in issue for issue in issues))

    def test_missing_message_symbol_points_to_english_implementation(self):
        adapter, modules, _, _ = self.load_adapter()
        del modules["messages"].Snapshot
        passed, total, issues = adapter.self_check()
        self.assertLess(passed, total)
        self.assertTrue(any("official_api.py" in issue for issue in issues))

    def test_legacy_entry_exports_the_same_objects_and_does_not_reimport_studio(self):
        adapter, _, imported, importer = self.load_adapter()
        before = list(imported)
        with patch.dict("sys.modules", {"official_api": adapter}):
            legacy = load_source(RUNTIME / "官方层.py", "legacy_adapter_under_test")
            with patch.dict("sys.modules", {"官方层": legacy}):
                namespace = {}
                exec("from 官方层 import messages, 自检, MUJOCO版本要求", namespace)
            self.assertIs(namespace["messages"], adapter.messages)
            self.assertIs(namespace["自检"], adapter.self_check)
            self.assertEqual(namespace["MUJOCO版本要求"], adapter.MUJOCO_VERSION_REQUIREMENT)
            for name, canonical in legacy._LEGACY_EXPORTS.items():
                self.assertIs(getattr(legacy, name), getattr(adapter, canonical))
            with patch("builtins.__import__", side_effect=importer):
                self.assertIs(legacy.ux, adapter.ux)
        self.assertEqual(imported[:len(before)], before)
        self.assertEqual(imported[len(before):], ["mujoco.experimental.studio.ux"])

    def test_optional_import_failure_retains_actionable_diagnostic(self):
        adapter, _, _, _ = self.load_adapter()
        _, _, importer = fake_dependencies("mujoco.experimental.implot")
        with patch("builtins.__import__", side_effect=importer), self.assertRaises(SystemExit) as caught:
            _ = adapter.implot
        self.assertIn("implot", str(caught.exception))
        self.assertIn("official_api", str(caught.exception))

    def test_environment_hint_keeps_platform_specific_python_path(self):
        adapter, _, _, _ = self.load_adapter()
        with patch.object(adapter.sys, "platform", "win32"):
            self.assertEqual(adapter._environment_command("run_yubi.py"),
                             r".\.venv\Scripts\python.exe run_yubi.py")
        with patch.object(adapter.sys, "platform", "darwin"):
            self.assertEqual(adapter._environment_command("run_yubi.py"),
                             ".venv/bin/python run_yubi.py")

    def test_unknown_names_raise_attribute_error(self):
        adapter, _, _, _ = self.load_adapter()
        with self.assertRaises(AttributeError):
            _ = adapter.unknown_dependency


if __name__ == "__main__":
    unittest.main()
