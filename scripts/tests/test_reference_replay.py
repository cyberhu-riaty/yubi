"""Checks for the processed UR10 reference dataset used by the replay panel."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

from reference_replay import (  # noqa: E402
    JOINT_NAMES,
    list_trajectories,
    load_trajectory,
    reference_directory,
)


class ReferenceReplayTests(unittest.TestCase):
    def test_all_ten_processed_trajectories_are_discoverable(self):
        items = list_trajectories()
        self.assertEqual([item["index"] for item in items], list(range(10)))
        self.assertTrue(all(item["available"] for item in items))
        self.assertTrue((reference_directory() / "trajectory_1_identified_results.mat").is_file())

    def test_trajectory_shapes_and_payload(self):
        item = load_trajectory(0, include_recompute=True)
        self.assertEqual(item.sample_count, 1129)
        self.assertEqual(item.q_actual_rad.shape, (1129, 6))
        self.assertEqual(item.actual_current_A.shape, (1129, 6))
        payload = item.payload(include_recompute=True)
        self.assertEqual(payload["joint_names"], list(JOINT_NAMES))
        self.assertEqual(len(payload["time_s"]), 1129)
        for key in (
            "measured_current_A",
            "measured_torque_Nm",
            "model_torque_friction_off_Nm",
            "model_torque_nonlinear_friction_Nm",
            "target_moment_Nm",
            "recompute_torque_friction_off_Nm",
        ):
            self.assertIn(key, payload["series"])
        self.assertEqual(payload["recompute"]["status"], "match")
        self.assertEqual(payload["source"]["raw_rtde_available"], False)

    def test_interpolation_hits_archived_first_and_last_samples(self):
        item = load_trajectory(7, include_recompute=False)
        q0, dq0 = item.interpolate_state(0.0)
        qn, dqn = item.interpolate_state(1e9)
        self.assertTrue((q0 == item.q_actual_rad[0]).all())
        self.assertTrue((dq0 == item.dq_actual_rad_s[0]).all())
        self.assertTrue((qn == item.q_actual_rad[-1]).all())
        self.assertTrue((dqn == item.dq_actual_rad_s[-1]).all())

    def test_contact_sensitive_trajectories_are_explicit(self):
        one = load_trajectory(1, include_recompute=True)
        seven = load_trajectory(7, include_recompute=True)
        self.assertEqual(one.recompute["status"], "contact_sensitive")
        self.assertEqual(seven.recompute["status"], "contact_sensitive")
        self.assertGreater(one.recompute["max_abs_diff_nm"], 1.0)
        self.assertGreater(seven.recompute["max_abs_diff_nm"], 1.0)
        self.assertIn("forearm", " ".join(one.recompute["contact_pairs"]))
        self.assertGreater(one.recompute["contact_sample_count"], 0)
        self.assertGreater(seven.recompute["contact_sample_count"], 0)

    def test_noncontact_trajectories_recompute_within_tolerance(self):
        for index in (0, 2, 3, 4, 5, 6, 8, 9):
            item = load_trajectory(index, include_recompute=True)
            self.assertEqual(item.recompute["status"], "match", index)
            self.assertLessEqual(item.recompute["max_abs_diff_nm"], 1e-5)


if __name__ == "__main__":
    unittest.main()
