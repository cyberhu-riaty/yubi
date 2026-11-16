"""English message APIs must retain protocol names and dispatcher identity."""
from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


RUNTIME = Path(__file__).resolve().parents[2] / "软件"


class WireCompatibilityTests(unittest.TestCase):
    def load_source(self, filename, name):
        spec = importlib.util.spec_from_file_location(name, RUNTIME / filename)
        module = importlib.util.module_from_spec(spec)
        installed = patch.dict(sys.modules, {name: module})
        installed.start()
        self.addCleanup(installed.stop)
        spec.loader.exec_module(module)
        return module

    def setUp(self):
        self.wire = self.load_source("wire_compatibility.py", "wire_compatibility")

    def test_aliases_preserve_frozen_class_identity_and_english_metadata(self):
        @dataclasses.dataclass(frozen=True)
        class Command:
            action: str = "idle"

        original_class = Command
        Command = self.wire.legacy_wire("旧命令", {"action": "动作"})(Command)
        self.assertIs(Command, original_class)
        message = Command(**{"动作": "start"})
        self.assertEqual(message.action, "start")
        self.assertEqual(getattr(message, "动作"), "start")
        self.assertEqual([field.name for field in dataclasses.fields(message)], ["action"])
        self.assertEqual(self.wire.wire_class_name(message), "旧命令")
        self.assertEqual(self.wire.wire_field_name(Command, "action"), "动作")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            message.action = "stop"
        with self.assertRaises(TypeError):
            Command(action="start", **{"动作": "stop"})

    def test_mutable_alias_writes_update_the_same_english_field(self):
        @self.wire.legacy_wire("旧状态", {"state": "状态"})
        @dataclasses.dataclass
        class State:
            state: str = "idle"

        value = State()
        setattr(value, "状态", "running")
        self.assertEqual(dataclasses.asdict(value), {"state": "running"})

    def test_unconverted_official_messages_keep_their_names(self):
        @dataclasses.dataclass
        class StateSnapshot:
            state: tuple = ()

        self.assertEqual(self.wire.wire_class_name(StateSnapshot()), "StateSnapshot")
        self.assertEqual(self.wire.wire_field_name(StateSnapshot, "state"), "state")

    def test_recording_command_uses_one_class_for_both_constructor_formats(self):
        official = SimpleNamespace(messages=SimpleNamespace(Snapshot=object))
        with patch.dict(sys.modules, {"official_api": official}):
            module = self.load_source("recording_bridge.py", "recording_bridge_under_test")
        canonical = module.RecordingCommand(action="开始", frequency=500, note="test")
        legacy = module.RecordingCommand(**{"动作": "开始", "频率": 500, "备注": "test"})
        self.assertEqual(canonical, legacy)
        self.assertEqual([field.name for field in dataclasses.fields(canonical)],
                         ["action", "frequency", "note"])
        self.assertIs(self.wire.resolve_wire_class(module, "录制命令"),
                      module.RecordingCommand)


if __name__ == "__main__":
    unittest.main()
