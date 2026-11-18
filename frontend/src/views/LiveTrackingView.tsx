/** A-owned binding between the shared store and B's presentation-only panel. */
import { useStore } from "../data/store";
import { useEffect, useState } from "react";
import { LiveTrackingPanel } from "../features/live_tracking/LiveTrackingPanel";
import { useLanguage } from "./i18n";

export function LiveTrackingView() {
  const tracking = useStore((s) => s.liveTracking);
  const connected = useStore((s) => s.connection === "connected");
  const [tick, setTick] = useState(Date.now);
  useEffect(() => {
    // Freshness is wall-clock information, independent of the plot's sim time.
    const timer = window.setInterval(() => setTick(Date.now()), 200);
    return () => window.clearInterval(timer);
  }, []);
  const locale = useLanguage();
  return <LiveTrackingPanel
    runId={tracking.runId}
    experimentName={tracking.experimentName}
    modelName={tracking.modelName}
    status={tracking.status}
    connected={connected}
    locale={locale}
    jointNames={tracking.jointNames}
    samples={tracking.samples}
    elapsedS={tracking.elapsedS}
    durationS={tracking.durationS}
    dataAgeS={tracking.receivedAtMs === null ? null : Math.max(0, (tick - tracking.receivedAtMs) / 1000)}
    compensationState={tracking.compensationState}
  />;
}
