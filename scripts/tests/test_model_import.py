from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("model_import_test_target", ROOT / "工具/import_model.py")
assert SPEC is not None and SPEC.loader is not None
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)


class ModelImportTests(unittest.TestCase):
    def test_english_and_legacy_list_options_produce_the_same_result(self):
        manifest = {"asset_base_url": "https://example.invalid/", "source": "test", "models": {}}
        legacy_manifest = {"资产基地址": "https://example.invalid/", "来源": "test", "模型": {}}
        self.assertEqual(IMPORTER.normalize_manifest(legacy_manifest), manifest)
        outputs = []
        for option in ("--list", "--列表"):
            output = io.StringIO()
            with patch.object(IMPORTER, "read_manifest", return_value=manifest):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(IMPORTER.main([option]), 0)
            outputs.append(output.getvalue())
        self.assertEqual(*outputs)

    @unittest.skipUnless(importlib.util.find_spec("mujoco"), "MuJoCo is required for XML conversion")
    def test_torque_variant_preserves_limits_and_rewrites_keyframe_controls(self):
        xml = '''<mujoco><worldbody><body><joint name="joint" type="hinge"/>
        <geom type="sphere" size="0.1" mass="1"/></body></worldbody>
        <actuator><position name="servo" joint="joint" kp="10" forcerange="-7 7"/></actuator>
        <keyframe><key name="home" qpos="0" ctrl="0.4"/></keyframe></mujoco>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "test.xml").write_text(xml, encoding="utf-8")
            result, stats = IMPORTER.generate_torque_variant(
                "test", directory, {"default_model": "test", "display_name": "Test"}, None,
            )
            root = ET.parse(result).getroot()
            motor = root.find("actuator/motor")
            self.assertIsNotNone(motor)
            self.assertEqual(motor.get("joint"), "joint")
            self.assertEqual(motor.get("ctrlrange"), "-7 7")
            self.assertEqual(root.find("keyframe/key").get("ctrl"), "0")
            self.assertEqual(stats["torque_limits"], [7.0])
            self.assertEqual(stats["armature_joints"], ["joint"])


if __name__ == "__main__":
    unittest.main()
