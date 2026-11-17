"""Project document versioning and controller parameter identifier checks."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
SOFTWARE = ROOT / "软件"
if str(SOFTWARE) not in sys.path:
    sys.path.insert(0, str(SOFTWARE))

import project_registry  # noqa: E402
import project_schema  # noqa: E402


LEGACY_PROJECT = {
    "_说明": "旧项目说明",
    "项目": "UR5e_基础PD",
    "模型": "模型/universal_robots_ur5e/ur5e_torque.xml",
    "实验专用": True,
    "算法": [
        {"插件": "joint_pid_control"},
        {"插件": "data_recorder", "类": "DataRecorderPlugin"},
    ],
    "参数": {
        "关节 PID 位置控制": {"KP": 86.0, "积分上限": 0.6},
        "Panda 抓取演示（脚本化）": {"位置增益": 1000.0},
    },
    "外观": {"风格": "现代深色", "主题": "dark"},
    "备注": "旧备注",
    "_顺序说明": "旧顺序说明",
    "_默认说明": "旧默认说明",
}


def _non_ascii_keys(value, prefix=""):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            pointer = f"{prefix}/{key}"
            if isinstance(key, str) and not key.isascii():
                found.append(pointer)
            found.extend(_non_ascii_keys(child, pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_non_ascii_keys(child, f"{prefix}/[{index}]"))
    return found


class ProjectSchemaTests(unittest.TestCase):
    def setUp(self):
        self.index, self.aliases = project_schema.plugin_identifier_index(
            [project_registry.ALGORITHM_DIRECTORY])

    def test_plugin_identifier_index_resolves_display_names(self):
        self.assertEqual(self.index.get("关节 PID 位置控制"), "joint_pid_control")
        self.assertEqual(self.index.get("Panda 抓取演示（脚本化）"), "panda_pick_place")
        self.assertEqual(self.aliases["joint_pid_control"]["积分上限"], "integral_limit")
        self.assertEqual(self.aliases["panda_pick_place"]["位置增益"], "position_gain")

    def test_legacy_document_is_normalized_to_english_machine_keys(self):
        data = project_schema.normalize_project(LEGACY_PROJECT, self.index, self.aliases)
        self.assertEqual(data["project"], "UR5e_基础PD")
        self.assertEqual(data["model"], "模型/universal_robots_ur5e/ur5e_torque.xml")
        self.assertTrue(data["experiment_only"])
        self.assertEqual(data["comment"], "旧项目说明")
        self.assertEqual(data["notes"], "旧备注")
        self.assertEqual(data["order_note"], "旧顺序说明")
        self.assertEqual(data["default_note"], "旧默认说明")
        self.assertEqual(data["algorithms"], [
            {"plugin": "joint_pid_control"},
            {"plugin": "data_recorder", "class": "DataRecorderPlugin"},
        ])
        self.assertEqual(data["parameters"]["joint_pid_control"],
                         {"KP": 86.0, "integral_limit": 0.6})
        self.assertEqual(data["parameters"]["panda_pick_place"], {"position_gain": 1000.0})
        self.assertEqual(data["appearance"], {"style": "现代深色", "theme": "dark"})
        self.assertNotIn("legacy_parameters", data)

    def test_unresolved_parameter_names_are_isolated_as_values(self):
        legacy = {
            "项目": "x", "模型": "m",
            "参数": {"未知插件": {"未知参数": 1.0}, "joint_pd_control": {"未知参数": 2.0}},
        }
        data = project_schema.normalize_project(legacy, self.index, self.aliases)
        buckets = {item["plugin_name"]: item for item in data["legacy_parameters"]}
        self.assertEqual(buckets["未知插件"]["parameters"],
                         [{"name": "未知参数", "value": 1.0}])
        self.assertEqual(buckets["joint_pd_control"]["parameters"],
                         [{"name": "未知参数", "value": 2.0}])

    def test_serialized_document_has_no_non_ascii_keys(self):
        data = project_schema.normalize_project(LEGACY_PROJECT, self.index, self.aliases)
        document = project_schema.serialize_project(data)
        self.assertEqual(_non_ascii_keys(document), [])
        self.assertEqual(document["schema_version"], project_schema.SCHEMA_VERSION)
        self.assertEqual(document["project"], "UR5e_基础PD")
        self.assertEqual(document["parameters"]["joint_pid_control"]["integral_limit"], 0.6)

    def test_version_two_document_round_trips(self):
        first = project_schema.normalize_project(LEGACY_PROJECT, self.index, self.aliases)
        document = project_schema.serialize_project(first)
        second = project_schema.normalize_project(document, self.index, self.aliases)
        self.assertEqual(project_schema.serialize_project(second), document)

    def test_unknown_fields_are_preserved(self):
        legacy = dict(LEGACY_PROJECT)
        legacy["自定义字段"] = {"任意": 1}
        legacy["custom_field"] = 2
        data = project_schema.normalize_project(legacy, self.index, self.aliases)
        document = project_schema.serialize_project(data)
        self.assertEqual(document["custom_field"], 2)
        self.assertEqual(document["legacy_fields"], {"自定义字段": {"任意": 1}})

    def test_every_tracked_project_loads_with_english_keys(self):
        for name in project_registry.list_projects():
            data = project_registry.load_project(name)
            self.assertIsNotNone(data, name)
            document = project_schema.serialize_project(data)
            self.assertEqual(_non_ascii_keys(document), [], name)
            self.assertTrue(document["project"], name)
            self.assertTrue(document["model"], name)


class ProjectPersistenceTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self._old_directory = project_registry.PROJECT_DIRECTORY
        project_registry.PROJECT_DIRECTORY = self._directory.name
        self.addCleanup(self._restore)

    def _restore(self):
        project_registry.PROJECT_DIRECTORY = self._old_directory
        self._directory.cleanup()

    def _write_legacy(self, name: str) -> Path:
        path = Path(self._directory.name) / name
        path.write_text(json.dumps(LEGACY_PROJECT, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_legacy_file_loads_saves_and_restores_parameters(self):
        self._write_legacy("UR5e_基础PD.json")
        loaded = project_registry.load_project("UR5e_基础PD")
        self.assertEqual(loaded["parameters"]["joint_pid_control"]["integral_limit"], 0.6)

        self.assertTrue(project_registry.save_parameters(
            "UR5e_基础PD", "joint_pid_control", {"KP": 200.0}))
        document = json.loads(
            (Path(self._directory.name) / "UR5e_基础PD.json").read_text(encoding="utf-8"))
        self.assertEqual(_non_ascii_keys(document), [])
        self.assertEqual(document["parameters"]["joint_pid_control"],
                         {"KP": 200.0, "integral_limit": 0.6})

        restored = project_registry.load_parameters("UR5e_基础PD")
        self.assertEqual(restored["joint_pid_control"]["KP"], 200.0)

    def test_case_insensitive_file_systems_do_not_create_duplicate_names(self):
        index, aliases = project_schema.plugin_identifier_index(
            [project_registry.ALGORITHM_DIRECTORY])
        document = project_schema.serialize_project(
            project_schema.normalize_project(LEGACY_PROJECT, index, aliases))
        document["project"] = "Panda_MJPC"
        path = Path(self._directory.name) / "panda_mjpc.json"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(Path(project_registry.project_file_path("Panda_MJPC")).name,
                         "panda_mjpc.json")
        self.assertTrue(project_registry.save_project(document))
        self.assertEqual(sorted(p.name for p in Path(self._directory.name).glob("*.json")),
                         ["panda_mjpc.json"])

    def test_saved_document_reloads_with_the_same_values(self):
        self._write_legacy("UR5e_基础PD.json")
        loaded = project_registry.load_project("UR5e_基础PD")
        self.assertTrue(project_registry.save_project(loaded))
        again = project_registry.load_project("UR5e_基础PD")
        self.assertEqual(again["parameters"], loaded["parameters"])
        self.assertEqual(again["algorithms"], loaded["algorithms"])


if __name__ == "__main__":
    unittest.main()
