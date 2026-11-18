"""Check numerical parity with archived results and the forward step hook."""

import sys
import unittest
from pathlib import Path

import mujoco
import numpy as np
from scipy.io import loadmat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from friction import UR10Friction, inverse_dynamics, step_with_friction  # noqa: E402


class FrictionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = mujoco.MjModel.from_xml_path(str(ROOT / "models" / "ur10_extfric.xml"))
        cls.law = UR10Friction()

    def test_archived_trajectory(self):
        archive = ROOT / "experiments" / "legacy" / "outputs" / "results" / "trajectory_0_identified_results.mat"
        result = loadmat(archive)
        q = result["q_actual_rad"]
        dq = result["dq_actual_rad_s"]
        ddq = result["ddq_actual_rad_s2"]
        np.testing.assert_allclose(self.law.torque(dq), result["friction_torque_Nm"], rtol=0, atol=1e-12)
        sample = np.array([0, len(q) // 2, len(q) - 1])
        actual = inverse_dynamics(self.model, q[sample], dq[sample], ddq[sample], self.law)
        # Archived MuJoCo output can differ slightly across runtime versions.
        np.testing.assert_allclose(actual, result["identified_torque_nonlinear_friction_Nm"][sample], rtol=0, atol=3e-6)

    def test_forward_step_matches_manual_force_and_preserves_other_force(self):
        model = self.model
        indices = self.law.validate_model(model)
        initial = mujoco.MjData(model)
        mujoco.mj_resetDataKeyframe(model, initial, 0)
        initial.qvel[:] = [0.2, -0.3, 0.1, -0.4, 0.5, -0.2]
        initial.ctrl[:] = initial.qpos
        initial.qfrc_applied[:] = [1.0, 0.0, -2.0, 0.0, 0.0, 0.5]
        wrapped = mujoco.MjData(model)
        manual = mujoco.MjData(model)
        for data in (wrapped, manual):
            data.qpos[:] = initial.qpos
            data.qvel[:] = initial.qvel
            data.ctrl[:] = initial.ctrl
            data.qfrc_applied[:] = initial.qfrc_applied
        returned = step_with_friction(model, wrapped, self.law)
        np.testing.assert_array_equal(wrapped.qfrc_applied, initial.qfrc_applied)
        np.testing.assert_allclose(returned, self.law.torque(initial.qvel[indices]))
        manual.qfrc_applied[indices] -= returned
        mujoco.mj_step(model, manual)
        np.testing.assert_allclose(wrapped.qpos, manual.qpos, rtol=0, atol=1e-12)
        np.testing.assert_allclose(wrapped.qvel, manual.qvel, rtol=0, atol=1e-12)

    def test_zero_speed_preserves_identified_bias(self):
        np.testing.assert_array_equal(self.law.torque(np.zeros(6)), self.law.b)

    def test_rejects_xml_with_built_in_friction(self):
        model = mujoco.MjModel.from_xml_path(str(ROOT / "models" / "ur10.xml"))
        with self.assertRaisesRegex(ValueError, "damping and frictionloss must be zero"):
            self.law.validate_model(model)


if __name__ == "__main__":
    unittest.main()
