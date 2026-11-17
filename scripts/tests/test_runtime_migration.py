"""Check legacy imports and diagnostic producers/consumers after path migration."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"


def source_function(relative, name, namespace=None):
    """Execute actual methods without loading AppKit or Qt on the test platform."""
    tree = ast.parse((RUNTIME / relative).read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    function.decorator_list = []
    scope = {"os": os, **(namespace or {})}
    exec(compile(ast.Module(body=[function], type_ignores=[]), relative, "exec"), scope)
    return scope[name]


class RuntimeMigrationTests(unittest.TestCase):
    def test_legacy_imports_remain_lazy_and_share_canonical_types(self):
        code = '''
import importlib, sys
from legacy_imports import install, LegacyImportFinder
before = set(sys.modules)
install()
install()
assert sum(isinstance(finder, LegacyImportFinder) for finder in sys.meta_path) == 1
assert not any(name.startswith(("mujoco", "AppKit", "PySide6")) for name in set(sys.modules) - before)
import contract
legacy = importlib.import_module("契约")
assert legacy.Field is contract.Field
assert getattr(legacy, "字段") is contract.Field
assert getattr(legacy, "转字典")() == contract.to_dict()
devices = importlib.import_module("设备.契约")
from devices.contract import CommandFrame
assert getattr(devices, "命令帧") is CommandFrame
assert devices is importlib.import_module("设备.契约")
assert devices is importlib.import_module("legacy.devices.contract")
assert importlib.util.find_spec("not_a_legacy_module") is None
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                env={**os.environ, "PYTHONPATH": str(RUNTIME)},
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_mac_statistics_keep_values_under_english_keys(self):
        viewport = SimpleNamespace(ready=True, error="", statistics={
            "rendered_frames": 25, "displayed_frames": 23,
            "state_syncs": 17, "fps": 59.94})
        host = SimpleNamespace(viewport=viewport, main_thread_frames=29, web_view=object())
        statistics = source_function("native_host.py", "get_statistics", {
            "_last_host": host, "get_viewport_rectangle": lambda: (0, 0, 640, 480)})()
        self.assertEqual(statistics["viewport_rendered_frames"], 25)
        self.assertEqual(statistics["viewport_displayed_frames"], 23)
        self.assertEqual(statistics["viewport_state_syncs"], 17)
        self.assertEqual(statistics["main_thread_frames"], 29)
        self.assertEqual(statistics["viewport_fps"], 59.9)
        self.assertTrue(all(key.isascii() for key in statistics))
        idle = source_function("native_host.py", "get_statistics", {"_last_host": None})()
        self.assertEqual(idle, {"state": "窗口未启动"})

    def test_windows_info_panel_reads_renamed_diagnostics(self):
        snapshot = SimpleNamespace(time=1.25, qpos=[0.2], qvel=[0.3], ctrl=[0.4])
        viewport = SimpleNamespace(
            _latest_lock=threading.Lock(), latest_state=snapshot,
            _model_path="models/robot.xml", _status_text="就绪", ready=True)
        producer = source_function("platform_adapters/windows_viewport.py", "runtime_info")
        viewport.runtime_info = lambda: producer(viewport)
        viewport.statistics = lambda: {"rendered_frames": 7, "displayed_frames": 6,
                                       "state_syncs": 5, "fps": 60, "error": ""}

        class Text:
            value = ""
            def setText(self, value):
                self.value = value
            setPlainText = setText

        table_calls = []
        panel = SimpleNamespace(
            _viewport=viewport, _time_label=Text(), _model_label=Text(),
            _sync_label=Text(), _fps_label=Text(), _diagnostic=Text(),
            _last_diagnostic="", _numeric_values=list,
            _write_input_table=lambda *args, **kwargs: table_calls.append((args, kwargs)))
        refresh = source_function("platform_adapters/windows_runtime_info.py", "_refresh")
        refresh(panel)
        self.assertEqual(panel._time_label.value, "1.250 s")
        self.assertEqual(panel._model_label.value, "robot.xml")
        self.assertEqual(panel._sync_label.value, "5 次")
        self.assertIn("渲染帧       : 7", panel._diagnostic.value)
        self.assertIn("显示帧       : 6", panel._diagnostic.value)
        self.assertEqual(table_calls[0][0], ([0.2], [0.3], [0.4]))
        self.assertFalse(table_calls[0][1]["waiting_for_state"])


if __name__ == "__main__":
    unittest.main()
