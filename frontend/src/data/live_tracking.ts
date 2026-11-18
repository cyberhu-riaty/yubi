/** Decode the display stream, deduplicate its repeated tail and bound history.
 * Component props are adapted structurally from this data; no transport or
 * simulation state lives in the presentation component.
 */
const statuses = ["idle", "loading", "ready", "running", "paused", "completed", "error"] as const;
const compensationStates = ["unavailable", "disabled", "enabled"] as const;

function vector(value: unknown, size: number): (number | null)[] | null {
  if (!Array.isArray(value) || value.length !== size) return null;
  return value.map((v: unknown) => typeof v === "number" && Number.isFinite(v) ? v : null);
}

function sample(raw: Record<string, unknown>, size: number) {
  if (typeof raw.elapsed_s !== "number" || !Number.isFinite(raw.elapsed_s) || raw.elapsed_s < 0
      || typeof raw.sample_index !== "number" || !Number.isSafeInteger(raw.sample_index) || raw.sample_index < 1) return null;
  const positionRad = vector(raw.position_rad, size);
  const referenceRad = vector(raw.reference_rad, size);
  const velocityRadS = vector(raw.velocity_rad_s, size);
  const errorRad = vector(raw.error_rad, size);
  const actuatorTorqueNm = vector(raw.actuator_torque_nm, size);
  const compensationTorqueNm = raw.compensation_torque_nm === null ? null : vector(raw.compensation_torque_nm, size);
  if (!positionRad || !referenceRad || !velocityRadS || !errorRad || !actuatorTorqueNm) return null;
  return {
    index: raw.sample_index,
    value: { elapsedS: raw.elapsed_s, positionRad, referenceRad, velocityRadS,
      errorRad, actuatorTorqueNm, compensationTorqueNm },
  };
}

type DisplaySample = NonNullable<ReturnType<typeof sample>>["value"];

export interface TrackingHistory {
  runId: string;
  experimentName: string;
  modelName: string;
  status: typeof statuses[number];
  jointNames: readonly string[];
  samples: readonly DisplaySample[];
  elapsedS: number;
  durationS: number | null;
  compensationState: typeof compensationStates[number];
  lastSampleIndex: number;
  receivedAtMs: number | null;
}

export function emptyTrackingHistory(): TrackingHistory {
  return { runId: "", experimentName: "", modelName: "", status: "idle", jointNames: [], samples: [],
    elapsedS: 0, durationS: null, compensationState: "unavailable", lastSampleIndex: 0, receivedAtMs: null };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** Reject malformed metadata as a whole; retain nulls for unavailable readings. */
export function receiveTracking(previous: TrackingHistory, raw: Record<string, unknown>, nowMs: number): TrackingHistory {
  if (typeof raw.run_id !== "string" || !raw.run_id
      || !Array.isArray(raw.joint_names) || !raw.joint_names.every((n: unknown) => typeof n === "string")
      || !statuses.includes(raw.status as typeof statuses[number])
      || !compensationStates.includes(raw.compensation_state as typeof compensationStates[number])
      || typeof raw.elapsed_s !== "number" || !Number.isFinite(raw.elapsed_s) || raw.elapsed_s < 0
      || !Array.isArray(raw.samples)) return previous;
  const names = raw.joint_names as string[];
  const sameRun = previous.runId === raw.run_id;
  if (sameRun && (raw.elapsed_s + 1e-9 < previous.elapsedS
      || names.length !== previous.jointNames.length
      || names.some((name, index) => name !== previous.jointNames[index]))) return previous;
  let lastIndex = sameRun ? previous.lastSampleIndex : 0;
  let samples = sameRun ? previous.samples : [];
  const additions: DisplaySample[] = [];
  let lastTime = samples.length ? samples[samples.length - 1].elapsedS : -1;
  for (const item of raw.samples) {
    if (!isRecord(item)) continue;
    const decoded = sample(item, names.length);
    if (!decoded || decoded.index <= lastIndex || decoded.value.elapsedS <= lastTime
        || decoded.value.elapsedS > raw.elapsed_s + 1e-9) continue;
    if (lastIndex && decoded.index > lastIndex + 1 && lastTime >= 0) {
      // An explicit missing marker prevents connecting across lost samples.
      // This is not an interpolated reading: every quantity is unavailable.
      const missing = Array<number | null>(names.length).fill(null);
      additions.push({ elapsedS: (lastTime + decoded.value.elapsedS) / 2,
        positionRad: missing, referenceRad: missing, velocityRadS: missing,
        errorRad: missing, actuatorTorqueNm: missing, compensationTorqueNm: null });
    }
    additions.push(decoded.value);
    lastIndex = decoded.index;
    lastTime = decoded.value.elapsedS;
  }
  if (additions.length) {
    samples = [...samples, ...additions];
    let first = Math.max(0, samples.length - 12000);
    const cutoff = lastTime - 120;
    while (first < samples.length && samples[first].elapsedS < cutoff) first++;
    if (first) samples = samples.slice(first);
  }
  return {
    runId: raw.run_id,
    experimentName: typeof raw.experiment_name === "string" ? raw.experiment_name : "",
    modelName: typeof raw.model_name === "string" ? raw.model_name : "",
    status: raw.status as typeof statuses[number],
    jointNames: sameRun ? previous.jointNames : [...names],
    samples,
    elapsedS: raw.elapsed_s,
    durationS: typeof raw.duration_s === "number" && Number.isFinite(raw.duration_s) && raw.duration_s > 0 ? raw.duration_s : null,
    compensationState: raw.compensation_state as typeof compensationStates[number],
    lastSampleIndex: lastIndex,
    // Heartbeats in paused/completed states must not make old readings fresh.
    receivedAtMs: additions.length ? nowMs : sameRun ? previous.receivedAtMs : null,
  };
}
