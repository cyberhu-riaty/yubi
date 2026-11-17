"""ASCII environment names must keep reading the legacy Chinese aliases."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

SOFTWARE = Path(__file__).resolve().parents[2] / "runtime"
if str(SOFTWARE) not in sys.path:
    sys.path.insert(0, str(SOFTWARE))

import env_config  # noqa: E402


class EnvironmentConfigTests(unittest.TestCase):
    def setUp(self):
        self._saved = {name: os.environ.get(name) for name in (
            "YUBI_MODEL", "驭臂_模型", "YUBI_LANG", "驭臂_语言")}
        for name in self._saved:
            os.environ.pop(name, None)
        self.addCleanup(self._restore)

    def _restore(self):
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_ascii_name_is_read_first(self):
        os.environ["YUBI_MODEL"] = "model-a.xml"
        os.environ["驭臂_模型"] = "model-b.xml"
        self.assertEqual(env_config.read("YUBI_MODEL"), "model-a.xml")
        self.assertEqual(env_config.source("YUBI_MODEL"), "YUBI_MODEL")

    def test_legacy_name_is_a_read_only_fallback(self):
        os.environ["驭臂_模型"] = "legacy.xml"
        self.assertEqual(env_config.read("YUBI_MODEL"), "legacy.xml")
        self.assertEqual(env_config.source("YUBI_MODEL"), "驭臂_模型")
        env_config.write("YUBI_MODEL", "new.xml")
        self.assertEqual(os.environ["YUBI_MODEL"], "new.xml")
        self.assertEqual(env_config.read("YUBI_MODEL"), "new.xml")

    def test_language_legacy_alias(self):
        os.environ["驭臂_语言"] = "en"
        self.assertEqual(env_config.read("YUBI_LANG"), "en")

    def test_every_alias_is_ascii_and_has_a_legacy_value(self):
        for name, legacy in env_config.LEGACY_NAMES.items():
            self.assertTrue(name.isascii(), name)
            self.assertTrue(legacy)


if __name__ == "__main__":
    unittest.main()
