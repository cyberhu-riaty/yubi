/** Real backend -> WebSocket -> production decoder/store -> panel data.
 * Start an isolated Yubi instance first and set YUBI_TEST_PORT explicitly.
 */
const assert = require("node:assert/strict");
const { loadFrontendModule } = require("./frontend_test_loader.cjs");
const port = Number(process.env.YUBI_TEST_PORT);
assert(Number.isInteger(port) && port > 0, "Set YUBI_TEST_PORT to an isolated test backend");
const { getState, startConnection, commands, backend } = loadFrontendModule("data/store.ts", {
  globals: {
    WebSocket,
    location: { protocol: "http:", host: `127.0.0.1:${port}` },
    window: { setInterval, clearInterval, setTimeout, clearTimeout },
    requestAnimationFrame: (fn) => setTimeout(fn, 0),
  },
  mocks: { react: { useSyncExternalStore: () => undefined } },
});
const wait = async (predicate, timeout = 15000) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (predicate()) return getState().liveTracking;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`Timed out: ${JSON.stringify({ error: getState().error, tracking: getState().liveTracking })}`);
};
const send = async (promise) => { const receipt = await promise; assert(receipt.passed, receipt.description); };
(async () => {
  const close = startConnection();
  try {
    await wait(() => getState().connection === "connected" && !!getState().handshake);
    const oldId = getState().liveTracking.runId;
    await send(commands.loadExperiment("ur10_live_tracking"));
    const loaded = await wait(() => getState().liveTracking.status === "ready"
      && getState().liveTracking.runId !== oldId && getState().liveTracking.jointNames.length === 6);
    assert.equal(loaded.samples[0].elapsedS, 0);
    await send(commands.controlSimulation("run"));
    await wait(() => getState().liveTracking.elapsedS > .25);
    const count = backend.counts["tracking.state"] || 0;
    const wallStart = Date.now();
    await wait(() => getState().liveTracking.elapsedS > 2.3);
    const arrived = (backend.counts["tracking.state"] || 0) - count;
    const hz = arrived / ((Date.now() - wallStart) / 1000);
    const moving = getState().liveTracking;
    assert(moving.samples.length > 25);
    assert(moving.samples.every((p, i, a) => i === 0 || a[i - 1].elapsedS < p.elapsedS));
    assert(moving.samples.some((p) => Math.abs(p.positionRad[0]) > .03));
    assert(moving.samples.some((p) => p.actuatorTorqueNm.some((v) => Math.abs(v ?? 0) > 1)));
    assert(moving.samples.every((p) => p.compensationTorqueNm === null));
    assert(hz >= 15 && hz <= 30, `Unexpected tracking arrival rate ${hz} Hz`);
    await send(commands.controlSimulation("pause"));
    const paused = await wait(() => getState().liveTracking.status === "paused");
    await new Promise((resolve) => setTimeout(resolve, 400));
    assert.equal(getState().liveTracking.elapsedS, paused.elapsedS);
    assert.equal(getState().liveTracking.samples.length, paused.samples.length);
    await send(commands.controlSimulation("reset"));
    const reset = await wait(() => getState().liveTracking.runId !== paused.runId);
    assert.equal(reset.elapsedS, 0);
    assert.equal(reset.samples.length, 1);
    console.log(`PASS real transport/store: ${hz.toFixed(1)} Hz; six joints, coherent forces, pause, reset and bounded monotonic history`);
  } finally { close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
