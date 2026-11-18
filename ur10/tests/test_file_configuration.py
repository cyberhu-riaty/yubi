"""Check file-driven formula selection, coefficient replacement and dynamics."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from friction import UR10Friction, inverse_dynamics
from friction.files import load_friction, load_robot


class FileConfigurationTests(unittest.TestCase):
    def test_default_and_python_plugin_preserve_original_formula(self):
        params = ROOT / "configs/ur10_identified_friction.json"
        v = np.array([[0, 0.2, -0.3, 0.4, -0.5, 0.6], [1, -1, 0, 0, 0, 0]])
        for model in (ROOT / "configs/power_friction.json", ROOT / "examples/custom_friction.py"):
            np.testing.assert_allclose(load_friction(model, params).torque(v), UR10Friction().torque(v), atol=1e-12)

    def test_linear_model_and_replacement_coefficients(self):
        with tempfile.TemporaryDirectory() as directory:
            params = Path(directory) / "params.json"
            params.write_text(json.dumps({"fc": [2] * 6, "fv": [3] * 6, "b": [0] * 6}))
            law = load_friction(ROOT / "configs/coulomb_viscous.json", params)
            np.testing.assert_allclose(law.torque(np.array([0, 1, -1, 2, -2, 0])), [0, 5, -5, 8, -8, 0])

    def test_dynamics_file_changes_inverse_torque(self):
        xml = ROOT / "models/ur10_extfric.xml"
        baseline = load_robot(xml)
        with tempfile.TemporaryDirectory() as directory:
            params = Path(directory) / "dynamics.json"
            params.write_text(json.dumps({"joints": {"shoulder_pan_joint": {"armature": 1.0628}}}))
            changed = load_robot(xml, params)
            q = baseline.key_qpos[0].copy()
            delta = inverse_dynamics(changed, q, np.zeros(6), np.ones(6)) - inverse_dynamics(baseline, q, np.zeros(6), np.ones(6))
            np.testing.assert_allclose(delta, [1, 0, 0, 0, 0, 0], atol=1e-9)


if __name__ == "__main__":
    unittest.main()
