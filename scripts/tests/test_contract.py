"""Preserve the v21 wire format and validation behavior through naming changes."""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


RUNTIME = Path(__file__).resolve().parents[2] / "runtime"
# Captured before renaming from the v21 implementation, not regenerated from it.
WIRE_V21_SHA256 = "61b15d41655ad3317790fb682112b8a7e0036f4947d93238785eda831b465024"
VALIDATION_V21_SHA256 = "707fe6c82c4f99f6c8e0f00fe6ec50baa081d2f13a8cfd5352e445d66fb3501b"
VALUES = [None, True, False, 0, 1, -1, 0.1, 0.25, 4.0, 4.01, 3600.0, 3600.1,
          10000.0, 10000.1, "", "run", "pause", "reset", "speed", "load", "apply",
          "record_waypoint", "invalid", [], [0.0], [True], ["x"], (), (1,), {},
          {"x": 0.0}, {"x": True}]


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validation_rows(contract):
    wire = contract.to_dict()
    rows = []
    for topic in wire["下行"] + wire["上行"]:
        name = topic["名"]
        payloads = [None, [], "invalid", 12, True, {}, {"not_a_field": 0}]
        payloads.extend({field["名"]: value} for field in topic["字段"] for value in VALUES)
        for payload in payloads:
            try:
                result = contract.validate(name, payload)
            except Exception as exc:
                result = (type(exc).__name__, str(exc))
            rows.append([name, payload, result])
    return rows


class ContractTests(unittest.TestCase):
    def load_source(self, filename, module_name):
        spec = importlib.util.spec_from_file_location(module_name, RUNTIME / filename)
        module = importlib.util.module_from_spec(spec)
        installed = patch.dict(sys.modules, {module_name: module})
        installed.start()
        self.addCleanup(installed.stop)
        spec.loader.exec_module(module)
        return module

    def setUp(self):
        self.contract = self.load_source("contract.py", "contract_under_test")

    def load_legacy(self):
        canonical = patch.dict(sys.modules, {"contract": self.contract})
        canonical.start()
        self.addCleanup(canonical.stop)
        return self.load_source("legacy/contract.py", "legacy_contract_under_test")

    def test_v22_adds_tracking_and_preserves_existing_v21_payloads(self):
        wire = self.contract.to_dict()
        self.assertEqual(self.contract.VERSION, 22)
        self.assertEqual(len(self.contract.ALL_TOPICS), 34)
        self.assertEqual(list(wire), ["版本", "类型记号", "下行", "上行"])
        self.assertEqual(self.contract.get_topic("tracking.state").class_name, "LiveTrackingState")
        previous = dict(wire, 版本=21)
        previous["下行"] = [topic for topic in wire["下行"] if topic["名"] != "tracking.state"]
        self.assertEqual(digest(previous), WIRE_V21_SHA256)

    def test_validation_results_match_pre_migration_snapshot(self):
        rows = [row for row in validation_rows(self.contract) if row[0] != "tracking.state"]
        self.assertEqual(len(rows), 5767)
        self.assertEqual(digest(rows), VALIDATION_V21_SHA256)

    def test_indexes_preserve_topic_and_field_order(self):
        contract = self.contract
        self.assertEqual(contract.ALL_TOPICS, contract.OUTBOUND_TOPICS + contract.INBOUND_TOPICS)
        for topic in contract.ALL_TOPICS:
            self.assertIs(contract.get_topic(topic.name), topic)
        # A message class may have both inbound and outbound topics. Keep the
        # existing dictionary behavior, which selects the last registered one.
        for name, topic in {item.class_name: item for item in contract.ALL_TOPICS}.items():
            self.assertIs(contract.BY_CLASS_NAME[name], topic)
        self.assertIs(contract.BY_CLASS_NAME["ParameterUpdate"],
                      contract.get_topic("command.parameters"))
        self.assertEqual(contract.class_name_to_topic(),
                         {topic.class_name: topic.name for topic in contract.OUTBOUND_TOPICS})

    def test_metadata_uses_english_fields_and_remains_frozen(self):
        contract = self.contract
        self.assertEqual([field.name for field in dataclasses.fields(contract.Field)],
                         ["name", "type", "description"])
        self.assertEqual([field.name for field in dataclasses.fields(contract.Topic)],
                         ["name", "class_name", "direction", "kind", "summary", "fields"])
        field = contract.Field("speed", "number")
        self.assertEqual(field.description, "")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            field.name = "changed"

    def test_legacy_symbols_and_read_access_remain_available(self):
        legacy = self.load_legacy()
        self.assertIs(getattr(legacy, "字段"), self.contract.Field)
        self.assertIs(getattr(legacy, "主题"), self.contract.Topic)
        self.assertIs(getattr(legacy, "所有主题"), self.contract.ALL_TOPICS)
        for topic in getattr(legacy, "所有主题"):
            self.assertEqual(getattr(topic, "名"), topic.name)
            self.assertEqual(getattr(topic, "类名"), topic.class_name)
            self.assertIs(getattr(topic, "字段"), topic.fields)
            for field in topic.fields:
                self.assertEqual(getattr(field, "名"), field.name)
                self.assertEqual(getattr(field, "类型"), field.type)
        self.assertEqual(getattr(legacy, "转字典")(), self.contract.to_dict())

    def test_legacy_constructor_keywords_and_isinstance_are_supported(self):
        legacy = self.load_legacy()
        field = getattr(legacy, "字段")(**{"名": "target", "类型": "number[]", "说明": "目标"})
        topic = getattr(legacy, "主题")(**{
            "名": "test", "类名": "TestMessage", "方向": "上行", "种类": "命令",
            "摘要": "测试", "字段": (field,),
        })
        self.assertIsInstance(field, self.contract.Field)
        self.assertIsInstance(topic, getattr(legacy, "主题"))
        self.assertEqual(topic.fields, (field,))
        self.assertEqual(field.type, "number[]")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(field, "名", "changed")

    def test_english_construction_and_dataclass_replace_still_work_after_legacy_import(self):
        self.load_legacy()
        field = self.contract.Field(name="speed", type="number", description="速度")
        changed = dataclasses.replace(field, name="speed_multiplier")
        self.assertEqual(changed.name, "speed_multiplier")
        self.assertEqual(field.name, "speed")

    def test_duplicate_constructor_aliases_do_not_silently_overwrite_values(self):
        legacy = self.load_legacy()
        with self.assertRaises(TypeError):
            getattr(legacy, "字段")(name="x", **{"名": "y", "类型": "number"})
        with self.assertRaises(TypeError):
            getattr(legacy, "字段")("x", "number", unsupported=True)

    def test_legacy_function_keywords_keep_existing_results(self):
        legacy = self.load_legacy()
        self.assertIs(getattr(legacy, "取")(**{"名": "command.simulation"}),
                      self.contract.get_topic("command.simulation"))
        self.assertEqual(getattr(legacy, "校验")(**{
            "主题名": "command.simulation", "负载": {"action": "run"},
        }), (True, "ok"))
        self.assertFalse(getattr(legacy, "_符合")(**{"值": True, "类型": "number"}))


if __name__ == "__main__":
    unittest.main()
