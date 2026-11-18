"""Exercise tracking against real MuJoCo forces, addresses and run transitions."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))
from live_tracking_bridge import LiveTrackingPublisher  # noqa: E402
from trajectory_runtime import TrajectorySample, publish_reference, clear_reference  # noqa: E402


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.model = mujoco.MjModel.from_xml_string('''<mujoco model="servo_fixture">
        <worldbody><body><freejoint/><geom size=".1" mass="1"/>
        <body><joint name="hinge"/><geom size=".1" mass="1" pos=".3 0 0"/></body>
        </body></worldbody><actuator><position joint="hinge" kp="10"/></actuator></mujoco>''')
        self.data = mujoco.MjData(self.model)
        self.data.qpos[7] = .1
        self.data.ctrl[0] = .3
        reference = self.data.qpos.copy()
        reference[7] = .4
        publish_reference(self.data, TrajectorySample(reference, np.zeros(self.model.nv)))
        self.addCleanup(clear_reference, self.data)
        self.frames = []
        self.publisher = LiveTrackingPublisher(self.frames.append)
        self.simulation = SimpleNamespace(reset_count=0, running=True)
        self.context = [SimpleNamespace(name="fixture", duration=4), 0, 0.0, "running"]
        self.runner = SimpleNamespace(tracking_context=lambda: self.context)

    def emit(self, now):
        self.publisher.maybe_publish(self.model, self.data, self.runner, self.simulation, now)
        return self.frames[-1]

    def test_zero_time_address_mapping_force_and_nonmutation(self):
        signature = mujoco.mjtState.mjSTATE_INTEGRATION
        before = np.zeros(mujoco.mj_stateSize(self.model, signature))
        after = np.zeros_like(before)
        mujoco.mj_getState(self.model, self.data, before, signature)
        frame = self.emit(0)
        mujoco.mj_getState(self.model, self.data, after, signature)
        np.testing.assert_array_equal(before, after)
        self.assertEqual(frame.joint_names, ["hinge"])
        point = frame.samples[0]
        self.assertEqual(point["elapsed_s"], 0)
        self.assertEqual(point["position_rad"], [.1])
        self.assertAlmostEqual(point["error_rad"][0], .3)
        self.assertAlmostEqual(point["actuator_torque_nm"][0], 2.0)
        self.assertNotEqual(point["actuator_torque_nm"][0], self.data.ctrl[0])
        self.assertIsNone(point["compensation_torque_nm"])

    def test_pause_tail_dedup_resume_and_reset_run_id(self):
        first = self.emit(0)
        self.data.time = .2
        second = self.emit(.05)
        self.assertEqual(len(second.samples), 2)
        self.context[3] = "paused"
        self.simulation.running = False
        paused = self.emit(.06)
        again = self.emit(.3)
        self.assertEqual(paused.samples, again.samples)
        self.assertEqual(again.elapsed_s, .2)
        self.context[3] = "running"
        self.simulation.running = True
        self.data.time = .4
        resumed = self.emit(.4)
        self.assertEqual(resumed.run_id, first.run_id)
        self.assertEqual(resumed.samples[-1]["sample_index"], 3)
        self.simulation.reset_count = 1
        self.data.time = 0
        reset = self.emit(.5)
        self.assertNotEqual(reset.run_id, first.run_id)
        self.assertEqual(len(reset.samples), 1)
        self.assertEqual(reset.samples[0]["sample_index"], 1)

    def test_reload_at_same_time_starts_new_run_and_tail_is_bounded(self):
        first = self.emit(0)
        self.context[1] += 1
        changed = self.emit(.05)
        self.assertNotEqual(changed.run_id, first.run_id)
        for i in range(1, 150):
            self.data.time = i * .05
            last = self.emit(i * .05 + .1)
        self.assertEqual(len(last.samples), 100)
        self.assertGreater(last.samples[0]["sample_index"], 1)


if __name__ == "__main__":
    unittest.main()
