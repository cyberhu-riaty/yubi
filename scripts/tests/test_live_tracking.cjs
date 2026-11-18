const assert = require("node:assert/strict");
const { loadFrontendModule } = require("./frontend_test_loader.cjs");
const { emptyTrackingHistory, receiveTracking } = loadFrontendModule("data/live_tracking.ts");
const point = (index, time, q = .1) => ({ sample_index: index, elapsed_s: time,
  position_rad: [q], reference_rad: [.2], error_rad: [.2 - q],
  velocity_rad_s: [.5], actuator_torque_nm: [2], compensation_torque_nm: null });
const frame = (points, extra = {}) => ({ run_id: "first", joint_names: ["hinge"],
  experiment_name: "experiment", model_name: "model", status: "running",
  elapsed_s: points.at(-1)?.elapsed_s ?? 0, duration_s: 14,
  compensation_state: "unavailable", samples: points, ...extra });
let history = receiveTracking(emptyTrackingHistory(), frame([point(1, 0)]), 100);
assert.equal(history.samples.length, 1, "t=0 must be retained");
history = receiveTracking(history, frame([point(1, 0), point(2, .05)]), 150);
assert.equal(history.samples.length, 2);
const samples = history.samples;
history = receiveTracking(history, frame([point(1, 0), point(2, .05)], { status: "paused" }), 200);
assert.equal(history.samples, samples, "heartbeat must not copy or append history");
assert.equal(history.receivedAtMs, 150, "paused heartbeat is not a new reading");
history = receiveTracking(history, frame([point(5, .2)]), 300);
assert.equal(history.samples.length, 4);
assert.equal(history.samples[2].positionRad[0], null, "dropped points produce an explicit gap");
assert.equal(history.samples[3].elapsedS, .2);
const oldHistory = history;
assert.equal(receiveTracking(history, frame([], { run_id: null }), 400), history);
assert.equal(receiveTracking(history, frame([point(6, .1)]), 400), history, "time reversal in one run rejected");
history = receiveTracking(history, frame([point(1, 0, null)], { run_id: "reset" }), 500);
assert.equal(history.samples.length, 1);
assert.equal(history.samples[0].positionRad[0], null, "missing stays missing");
assert.equal(oldHistory.samples.length, 4, "published history is immutable");
history = receiveTracking(history, frame([point(2, 121)], { run_id: "reset" }), 600);
assert.equal(history.samples.length, 1, "history is bounded by simulation time");
console.log("Live tracking stream passed: t=0, overlap, pause, reset, gaps, null, immutability, retention.");
