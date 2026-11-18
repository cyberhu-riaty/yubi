/** Read-only client for the processed UR10 reference experiment.
 *
 * The data is served by the Python side (`/api/reference/...`) from the
 * already processed MAT files.  This module does not read files or infer
 * physical values in the browser; it only decodes/validates the transport and
 * caches the large comparison payload for the lifetime of the page.
 */

export interface ReferenceRecomputeInterval {
  start_s: number;
  end_s: number;
  samples: number;
}

export interface ReferenceRecompute {
  status: "match" | "contact_sensitive" | "unavailable" | string;
  tolerance_nm?: number;
  mujoco_version?: string;
  model?: string;
  sample_count?: number;
  contact_sample_count?: number;
  bad_sample_count?: number;
  max_abs_diff_nm?: number;
  worst?: {
    time_s: number;
    joint: number;
    max_abs_diff_nm: number;
    contact_count: number;
  };
  bad_intervals?: ReferenceRecomputeInterval[];
  contact_pairs?: string[];
}

export interface ReferenceDataset {
  index: number;
  label: string;
  source: {
    kind: string;
    file: string;
    description: string;
    raw_rtde_available: boolean;
  };
  joint_names: string[];
  time_s: number[];
  sample_count: number;
  duration_s: number;
  torque_constant_Nm_per_A: number[];
  series: Record<string, number[][]>;
  recompute: ReferenceRecompute | null;
}

export interface ReferenceTrajectoryInfo {
  index: number;
  label: string;
  file: string;
  available: boolean;
}

export interface ReferenceSummary {
  directory: string;
  model: string;
  raw_rtde_available: boolean;
  preprocessing_note: string;
  trajectories: ReferenceTrajectoryInfo[];
}

const datasetCache = new Map<number, ReferenceDataset>();

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { cache: "no-store", signal });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { error?: unknown };
      if (typeof payload.error === "string") detail = payload.error;
    } catch {
      // Keep the HTTP status if the body is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function fetchReferenceSummary(signal?: AbortSignal): Promise<ReferenceSummary> {
  return fetchJson<ReferenceSummary>("/api/reference/summary", signal);
}

export async function fetchReferenceDataset(
  index: number,
  signal?: AbortSignal,
): Promise<ReferenceDataset> {
  const normalized = Math.max(0, Math.round(index));
  const cached = datasetCache.get(normalized);
  if (cached) return cached;
  const dataset = await fetchJson<ReferenceDataset>(
    `/api/reference/trajectory/${normalized}?recompute=1`,
    signal,
  );
  datasetCache.set(normalized, dataset);
  return dataset;
}

/** Test/reset hook: keep the cache from leaking between dev harnesses. */
export function clearReferenceDatasetCache(): void {
  datasetCache.clear();
}
