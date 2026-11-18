/** Bind the processed UR10 reference data and replay experiment to the panel.
 *
 * The data payload is read from the Python side; the panel remains presentation
 * only.  Switching trajectories is done through the plugin's documented
 * adjustable parameter, then a reset so playback and curves start together.
 */
import { useEffect, useRef, useState } from "react";
import { commands, useStore } from "../data/store";
import {
  fetchReferenceDataset,
  fetchReferenceSummary,
  type ReferenceDataset,
  type ReferenceSummary,
} from "../data/reference";
import { ReferenceComparisonPanel } from "../features/live_tracking/ReferenceComparisonPanel";
import { referenceComparisonLabels } from "../features/live_tracking/reference_labels";
import { useLanguage } from "./i18n";

const FALLBACK_PARAMETER = "reference_replay_player·trajectory";

export function ReferenceComparisonView() {
  const tracking = useStore((s) => s.liveTracking);
  const parameters = useStore((s) => s.parameters.data);
  const locale = useLanguage();
  const labels = referenceComparisonLabels[locale];

  const parameterEntry = Object.entries(parameters?.parameters ?? {}).find(
    ([key, item]) => item?.parameter === "trajectory"
      && (item?.plugin_id === "reference_replay_player" || key.includes("reference_replay_player")),
  );
  const parameterKey = parameterEntry?.[0] ?? FALLBACK_PARAMETER;
  const backendTrajectory = Number(parameterEntry?.[1]?.value ?? 0);

  const [selectedIndex, setSelectedIndex] = useState(0);
  const initialisedFromBackend = useRef(false);
  const [dataset, setDataset] = useState<ReferenceDataset | null>(null);
  const [summary, setSummary] = useState<ReferenceSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    // Adopt the persisted trajectory once.  Later parameter-table snapshots
    // belong to the current selection and must not fight the local UI.
    if (initialisedFromBackend.current || busy || !parameterEntry) return;
    if (Number.isFinite(backendTrajectory) && backendTrajectory >= 0) {
      setSelectedIndex(Math.round(backendTrajectory));
      initialisedFromBackend.current = true;
    }
  }, [backendTrajectory, busy, parameterEntry]);

  useEffect(() => {
    const controller = new AbortController();
    fetchReferenceSummary(controller.signal)
      .then((value) => setSummary(value))
      .catch((reason: unknown) => {
        if ((reason as { name?: string })?.name !== "AbortError") {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setDataset(null);
    setFetching(true);
    setError("");
    fetchReferenceDataset(selectedIndex, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setDataset(value);
      })
      .catch((reason: unknown) => {
        if ((reason as { name?: string })?.name !== "AbortError") {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setFetching(false);
      });
    return () => controller.abort();
  }, [selectedIndex]);

  const switchTrajectory = async (index: number) => {
    const next = Math.max(0, Math.round(index));
    if (next === selectedIndex || busy) return;
    if (tracking.status === "running") {
      setError(labels.selectorLocked);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const update = await commands.updateParameters({ [parameterKey]: next });
      if (!update.passed) throw new Error(update.description || labels.switchFailed);
      const reset = await commands.controlSimulation("reset");
      if (!reset.passed) throw new Error(reset.description || labels.switchFailed);
      setSelectedIndex(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ReferenceComparisonPanel
      dataset={dataset && dataset.index === selectedIndex ? dataset : null}
      summary={summary}
      selectedIndex={selectedIndex}
      locale={locale}
      currentTimeS={tracking.elapsedS}
      status={tracking.status}
      canSwitch={tracking.status !== "running" && !busy}
      busy={busy || fetching}
      error={error}
      onSelect={switchTrajectory}
    />
  );
}
