"""Exercise the actual UR10 runtime and tracking transport without opening UI."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))
os.environ["YUBI_DISABLE_WEB"] = "1"

import command_bridge
import plugin_system
import runtime_engine
import web_bridge
from experiment_registry import experiment_registry
from trajectory_runtime import JointTrajectory


def main() -> None:
    latest = {}
    original_publish = web_bridge.publish
    web_bridge.publish = lambda topic, value: latest.__setitem__(topic, value)
    runtime_engine.stop(2)
    runtime_engine.drain_local_queue()
    registry = plugin_system.SafeRegistry([], step_plugin=plugin_system.RealtimeFixedStep())
    config = plugin_system.viewer_protocol.ViewerConfig(title="UR10 tracking check", width=800, height=600, gfx="")

    def wait(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return latest.get("tracking.state", {})
            time.sleep(.01)
        raise AssertionError(f"Timed out; tracking={latest.get('tracking.state')}")

    def send(topic, payload):
        ok, reason = command_bridge.enqueue_command(runtime_engine.command_queue(), topic, payload, print_result=False)
        assert ok, reason

    try:
        runtime_engine.start(config, str(ROOT / "模型/空场景.xml"), None, [], registry,
                             plugin_system.notify_model_loaded, project_name="", headless=True, background_thread=True)
        ready, reason = runtime_engine.wait_until_ready(20)
        assert ready, reason
        send("command.experiment", {"action": "load", "experiment": "ur10_live_tracking"})
        loaded = wait(lambda: latest.get("tracking.state", {}).get("status") == "ready")
        first_id = loaded["run_id"]
        assert loaded["elapsed_s"] == 0 and len(loaded["joint_names"]) == 6
        assert loaded["samples"][0]["elapsed_s"] == 0
        send("command.simulation", {"action": "run"})
        running = wait(lambda: latest.get("tracking.state", {}).get("elapsed_s", 0) > .8)
        assert running["status"] == "running"
        trajectory = JointTrajectory(experiment_registry.create("ur10_live_tracking").trajectory)
        for point in running["samples"]:
            np.testing.assert_allclose(point["reference_rad"], trajectory.sample(point["elapsed_s"]).qpos,
                                       rtol=0, atol=1e-10, err_msg="Reference and display have different time origins")
        send("command.simulation", {"action": "pause"})
        paused = wait(lambda: latest.get("tracking.state", {}).get("status") == "paused")
        paused_time = paused["elapsed_s"]
        time.sleep(.3)
        assert latest["tracking.state"]["elapsed_s"] == paused_time
        assert latest["tracking.state"]["samples"] == paused["samples"]
        send("command.simulation", {"action": "speed", "speed_multiplier": 4})
        send("command.simulation", {"action": "run"})
        resumed = wait(lambda: latest.get("tracking.state", {}).get("elapsed_s", 0) > paused_time + .5)
        assert resumed["run_id"] == first_id
        send("command.simulation", {"action": "reset"})
        reset = wait(lambda: latest.get("tracking.state", {}).get("run_id") != first_id)
        assert reset["status"] == "ready" and reset["elapsed_s"] == 0
        assert len(reset["samples"]) == 1
        send("command.simulation", {"action": "run"})
        completed = wait(lambda: latest.get("tracking.state", {}).get("status") == "completed", 15)
        assert completed["elapsed_s"] >= 14
        points = completed["samples"]
        assert all(a["elapsed_s"] < b["elapsed_s"] for a, b in zip(points, points[1:]))
        positions = np.asarray([p["position_rad"] for p in points])
        assert np.max(np.ptp(positions, axis=0)) > .1, "Robot did not move"
        assert np.isfinite(positions).all()
        assert np.max(np.abs([p["actuator_torque_nm"] for p in points])) > 1
        assert not registry.failed_plugins, registry.failed_plugins
        second_id = completed["run_id"]
        send("command.experiment", {"action": "load", "experiment": "ur10_live_tracking"})
        reloaded = wait(lambda: latest.get("tracking.state", {}).get("run_id") != second_id)
        assert reloaded["elapsed_s"] == 0
        send("command.model", {"path": str(ROOT / "模型/空场景.xml")})
        switched = wait(lambda: latest.get("tracking.state", {}).get("status") == "idle")
        assert not switched["samples"] and not switched["joint_names"]
        print("PASS: actual UR10 load, t=0, motion, pause, resume, 4x speed, reset, completion, reload, model switch")
    finally:
        runtime_engine.stop(5)
        web_bridge.publish = original_publish


if __name__ == "__main__":
    main()
