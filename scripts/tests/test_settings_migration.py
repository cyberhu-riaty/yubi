"""Persisted settings keys migrate without losing existing user values."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

SOFTWARE = Path(__file__).resolve().parents[2] / "软件"
if str(SOFTWARE) not in sys.path:
    sys.path.insert(0, str(SOFTWARE))

import model_bridge  # noqa: E402


class SettingsMigrationTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self._old_path = model_bridge.SETTINGS_PATH
        model_bridge.SETTINGS_PATH = str(Path(self._directory.name) / "设置.json")
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        model_bridge.SETTINGS_PATH = self._old_path
        self._directory.cleanup()

    def _write(self, data):
        Path(model_bridge.SETTINGS_PATH).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_legacy_keys_are_read(self):
        self._write({"上次模型": "/tmp/model.xml", "上次项目": "demo", "语言": "en"})
        self.assertEqual(model_bridge.read_setting("last_model"), "/tmp/model.xml")
        self.assertEqual(model_bridge.read_setting("last_project"), "demo")
        self.assertEqual(model_bridge.read_setting("language"), "en")

    def test_remember_model_writes_ascii_key_and_drops_legacy(self):
        self._write({"上次模型": "/tmp/old.xml", "custom": 1})
        model_bridge.remember_model("/tmp/old.xml")
        data = json.loads(Path(model_bridge.SETTINGS_PATH).read_text(encoding="utf-8"))
        self.assertEqual(data["last_model"], "/tmp/old.xml")
        self.assertNotIn("上次模型", data)
        self.assertEqual(data["custom"], 1)

    def test_windows_layout_aliases(self):
        self._write({"Windows主分栏V2": [1, 2], "Windows右列分栏": [3, 4]})
        self.assertEqual(model_bridge.read_setting("windows_split_v2"), [1, 2])
        self.assertEqual(model_bridge.read_setting("windows_right_split"), [3, 4])


if __name__ == "__main__":
    unittest.main()
