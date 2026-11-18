/**
 * ReferenceComparisonPanel.tsx —— 六关节参考实验离线回放对比。
 *
 * 这是“参考图复现”专用面板，不替换实时仿真面板：
 *   · 数据是处理后的实机参考 MAT（实测电流/估算力矩、模型无摩擦/含摩擦、UR 目标力矩）；
 *   · 3D 机器人由 `reference_replay_player` 按同一组 q/dq 回放；
 *   · 六张图共用同一时间轴与播放游标，支持力矩/电流切换和存档/重算来源切换；
 *   · 轨迹 1、7 的独立重算接触帧差异必须明确标注，不能冒充“完全一致”。
 */
import { useEffect, useMemo, useState } from "react";
import type { ReferenceDataset, ReferenceSummary } from "../../data/reference";
import { LiveTrackingChart, type LiveTrackingSeries } from "./LiveTrackingChart";
import { liveTrackingLabels } from "./labels";
import { upperBound } from "./live_tracking_math";
import { referenceComparisonLabels, type ReferenceComparisonLabels } from "./reference_labels";
import type { LiveTrackingLocale } from "./labels";
import type { LiveTrackingStatus } from "./types";
import "./live_tracking.css";

type Metric = "torque" | "current";
type Source = "archive" | "recompute";

export interface ReferenceComparisonPanelProps {
  dataset: ReferenceDataset | null;
  summary: ReferenceSummary | null;
  selectedIndex: number;
  locale: LiveTrackingLocale;
  currentTimeS: number;
  status: LiveTrackingStatus;
  canSwitch: boolean;
  busy: boolean;
  error: string;
  onSelect: (index: number) => void;
}

function inputColumn(dataset: ReferenceDataset | null, name: string, joint: number): Float64Array {
  const rows = dataset?.series?.[name];
  if (!rows || rows.length === 0) return new Float64Array(0);
  const values = new Float64Array(rows.length);
  for (let index = 0; index < rows.length; index += 1) {
    const value = rows[index]?.[joint];
    values[index] = typeof value === "number" && Number.isFinite(value) ? value : Number.NaN;
  }
  return values;
}

function formatNumber(value: number | undefined | null, digits = 2): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function formatSeconds(value: number | undefined | null): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return "—";
  return Math.abs(value) >= 100 ? value.toFixed(1) : value.toFixed(2);
}

function downloadCsv(dataset: ReferenceDataset, metric: Metric, source: Source,
                     labels: ReferenceComparisonLabels) {
  const effectiveSource = source === "recompute" && dataset.recompute ? "recompute" : "archive";
  const fields = metric === "torque"
    ? [
        ["measured_torque_Nm", labels.legendMeasured],
        [effectiveSource === "recompute" ? "recompute_torque_friction_off_Nm" : "model_torque_friction_off_Nm", labels.legendModelOff],
        [effectiveSource === "recompute" ? "recompute_torque_nonlinear_friction_Nm" : "model_torque_nonlinear_friction_Nm", labels.legendModelOn],
        ["target_moment_Nm", labels.legendTarget],
      ]
    : [
        ["measured_current_A", labels.legendMeasured],
        [effectiveSource === "recompute" ? "recompute_current_friction_off_A" : "model_current_friction_off_A", labels.legendModelOff],
        [effectiveSource === "recompute" ? "recompute_current_nonlinear_friction_A" : "model_current_nonlinear_friction_A", labels.legendModelOn],
      ];
  const header = ["time_s"];
  for (const [key, label] of fields) {
    for (let joint = 0; joint < 6; joint += 1) {
      header.push(`${key}_J${joint + 1}_${label.replace(/,/g, "_")}`);
    }
  }
  const lines = [header.join(",")];
  for (let sample = 0; sample < dataset.sample_count; sample += 1) {
    const row = [String(dataset.time_s[sample])];
    for (const [key] of fields) {
      const values = dataset.series[key];
      for (let joint = 0; joint < 6; joint += 1) {
        const value = values?.[sample]?.[joint];
        row.push(typeof value === "number" && Number.isFinite(value) ? String(value) : "");
      }
    }
    lines.push(row.join(","));
  }
  const blob = new Blob([`\ufeff${lines.join("\n")}\n`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = labels.exportFileName(dataset.index, metric);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function ReferenceComparisonPanel({
  dataset,
  summary,
  selectedIndex,
  locale,
  currentTimeS,
  status,
  canSwitch,
  busy,
  error,
  onSelect,
}: ReferenceComparisonPanelProps) {
  const labels = referenceComparisonLabels[locale];
  const liveLabels = liveTrackingLabels[locale];
  const [metric, setMetric] = useState<Metric>("torque");
  const [source, setSource] = useState<Source>("archive");
  const [hoverTime, setHoverTime] = useState<number | null>(null);

  const hasRecompute = Boolean(
    dataset?.recompute &&
    dataset.series.recompute_torque_friction_off_Nm &&
    dataset.series.recompute_torque_nonlinear_friction_Nm,
  );
  const effectiveSource: Source = source === "recompute" && hasRecompute ? "recompute" : "archive";
  const duration = Math.max(0.001, dataset?.duration_s ?? 0);
  const playbackTime = Math.max(0, Math.min(duration, currentTimeS));
  const times = useMemo(
    () => (dataset ? Float64Array.from(dataset.time_s) : new Float64Array(0)),
    [dataset],
  );
  const range = useMemo(() => ({ startS: 0, endS: duration }), [duration]);

  useEffect(() => {
    setHoverTime(null);
  }, [dataset?.index]);

  const seriesByJoint = useMemo<LiveTrackingSeries[][]>(() => {
    if (!dataset) return [];
    const isTorque = metric === "torque";
    const modelPrefix = effectiveSource === "recompute" ? "recompute" : "model";
    const onSuffix = isTorque
      ? "torque_nonlinear_friction_Nm"
      : "current_nonlinear_friction_A";
    const measuredKey = isTorque ? "measured_torque_Nm" : "measured_current_A";
    const onKey = `${modelPrefix}_${onSuffix}`;
    const onLabel = effectiveSource === "recompute" ? labels.legendRecomputeOn : labels.legendModelOn;
    const dash = effectiveSource === "recompute" ? [5, 3] : [];
    const joints: LiveTrackingSeries[][] = [];
    for (let joint = 0; joint < 6; joint += 1) {
      const measured = inputColumn(dataset, measuredKey, joint);
      const frictionOn = inputColumn(dataset, onKey, joint);
      const series: LiveTrackingSeries[] = [
        {
          key: "measured",
          label: labels.legendMeasured,
          values: measured,
          colorVariable: "--tracking-ref-measured",
          dash: [],
          marker: "circle",
          lineWidth: 1.25,
        },
        {
          key: "model-on",
          label: onLabel,
          values: frictionOn,
          colorVariable: "--tracking-ref-friction",
          dash,
          marker: "diamond",
          lineWidth: 1.05,
        },
      ];
      if (isTorque) {
        series.push({
          key: "target",
          label: labels.legendTarget,
          values: inputColumn(dataset, "target_moment_Nm", joint),
          colorVariable: "--tracking-ref-target",
          dash: [],
          marker: "triangle",
          lineWidth: 0.95,
        });
      }
      joints.push(series);
    }
    return joints;
  }, [dataset, metric, effectiveSource, labels]);

  const sampleCount = status === "running" || status === "paused" || status === "completed"
    ? upperBound(times, playbackTime)
    : 0;
  const visibleSeriesByJoint = useMemo(
    () => seriesByJoint.map((series) => series.map((item) =>
      item.key === "target" ? item : {
        ...item,
        values: item.values.subarray(0, sampleCount),
        scaleValues: item.values,
      },
    )),
    [seriesByJoint, sampleCount],
  );
  const sampleIndex = Math.max(0, sampleCount - 1);
  const cursorTime = times[sampleIndex] ?? null;
  const chartHoverTime = hoverTime === null || sampleCount === 0 || cursorTime === null
    ? hoverTime
    : Math.min(hoverTime, cursorTime);

  const durationText = dataset ? formatSeconds(dataset.duration_s) : "—";
  const progress = dataset ? Math.min(100, Math.max(0, (playbackTime / duration) * 100)) : 0;
  const recompute = dataset?.recompute;
  const recomputeTone =
    recompute?.status === "match"
      ? "ok"
      : recompute?.status === "contact_sensitive"
        ? "warn"
        : "info";
  const recomputeHeadline =
    recompute?.status === "match"
      ? labels.recomputeMatch
      : recompute?.status === "contact_sensitive"
        ? labels.recomputeContact
        : labels.recomputeUnavailable;
  const recomputeDetail = recompute?.status === "contact_sensitive" && recompute.worst
    ? `${labels.recomputeSummary(
        String(recompute.bad_sample_count ?? "—"),
        String(recompute.sample_count ?? "—"),
        formatNumber(recompute.max_abs_diff_nm, 3),
        formatSeconds(recompute.worst.time_s),
        String(recompute.worst.joint),
      )} · ${labels.contactPairs((recompute.contact_pairs ?? []).join(", "))}`
    : "";

  const options = summary?.trajectories ?? [];
  const optionIndices = options.length
    ? options.map((item) => item.index)
    : [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];

  return (
    <section
      className="live-tracking live-tracking--reference"
      aria-label={labels.panelAria}
      onPointerLeave={() => setHoverTime(null)}
    >
      <header className="live-tracking__header live-tracking__reference-header">
        <div className="live-tracking__title-line">
          <h2 className="live-tracking__title">{labels.title}</h2>
          <span className="live-tracking__mode">{labels.archived}</span>
          <span className="live-tracking__mode live-tracking__mode--muted">{labels.offline}</span>
          <span className="live-tracking__mode live-tracking__mode--muted">{labels.notLive}</span>
          <span className="live-tracking__status" data-status={status} role="status">
            <span className="live-tracking__status-dot" aria-hidden="true" />
            {liveLabels.status[status]}
          </span>
        </div>
        <div className="live-tracking__subtitle">
          <span>{labels.currentMode}</span>
          <span className="live-tracking__real-robot">{labels.notLive}</span>
        </div>

        <div className="live-tracking__reference-controls">
          <label className="live-tracking__reference-field">
            <span>{labels.trajectory}</span>
            <select
              className="live-tracking__select"
              value={selectedIndex}
              disabled={!canSwitch || busy}
              title={!canSwitch ? labels.selectorLocked : labels.trajectory}
              onChange={(event) => onSelect(Number(event.target.value))}
            >
              {optionIndices.map((index) => (
                <option value={index} key={index}>
                  {`Trajectory ${index}`}
                </option>
              ))}
            </select>
          </label>
          <div className="live-tracking__segmented" role="group" aria-label={labels.torque}>
            <button
              type="button"
              className="live-tracking__chip"
              aria-pressed={metric === "torque"}
              onClick={() => setMetric("torque")}
            >
              {`${labels.torque} · ${labels.torqueUnit}`}
            </button>
            <button
              type="button"
              className="live-tracking__chip"
              aria-pressed={metric === "current"}
              onClick={() => setMetric("current")}
            >
              {`${labels.current} · ${labels.currentUnit}`}
            </button>
          </div>
          <div className="live-tracking__segmented" role="group" aria-label={labels.sourceArchive}>
            <button
              type="button"
              className="live-tracking__chip"
              aria-pressed={effectiveSource === "archive"}
              onClick={() => setSource("archive")}
            >
              {labels.sourceArchive}
            </button>
            <button
              type="button"
              className="live-tracking__chip"
              aria-pressed={effectiveSource === "recompute"}
              disabled={!hasRecompute}
              title={hasRecompute ? labels.sourceRecomputeNote : labels.recomputeUnavailable}
              onClick={() => setSource("recompute")}
            >
              {labels.sourceRecompute}
            </button>
          </div>
          <button
            type="button"
            className="live-tracking__chip live-tracking__reference-export"
            disabled={!dataset}
            title={labels.exportHint}
            onClick={() => {
              if (dataset) downloadCsv(dataset, metric, effectiveSource, labels);
            }}
          >
            {labels.exportCsv}
          </button>
        </div>

        <div className="live-tracking__reference-playback">
          <span className="live-tracking__reference-time">
            {labels.playback(formatSeconds(playbackTime), durationText)}
          </span>
          <span className="live-tracking__reference-sample">
            {labels.sample(String(sampleIndex + 1), String(dataset?.sample_count ?? 0))}
          </span>
          {busy ? <span className="live-tracking__muted">{labels.selectorBusy}</span> : null}
        </div>
        {dataset ? (
          <div
            className="live-tracking__progress"
            role="progressbar"
            aria-label={`${labels.title} ${durationText}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress)}
          >
            <span
              className="live-tracking__progress-fill"
              style={{ width: `${progress}%` }}
              aria-hidden="true"
            />
          </div>
        ) : null}

        <p className="live-tracking__notice" data-tone={recomputeTone}>
          {recomputeHeadline}
          {recomputeDetail ? (
            <span className="live-tracking__notice-detail">{recomputeDetail}</span>
          ) : null}
        </p>
        {error ? (
          <p className="live-tracking__notice" data-tone="danger">
            {`${labels.loadFailed}: ${error}`}
          </p>
        ) : null}
        {!dataset ? (
          <p className="live-tracking__notice" data-tone="info">
            {busy ? labels.loading : labels.noData}
            {!busy ? ` ${labels.noDataHint}` : ""}
          </p>
        ) : (
          <details className="live-tracking__reference-details">
            <summary>{labels.sourceFile(dataset.source.file)}</summary>
            <p>{labels.preprocessingNote}</p>
            <p>{labels.rawRtdeMissing}</p>
            <p>{labels.currentMode}</p>
          </details>
        )}
      </header>

      {dataset ? (
        <>
          <div className="live-tracking__chart-context">
            <span className="live-tracking__chart-context-joint">
              {`${labels.trajectory} ${dataset.index} · ${dataset.source.file}`}
            </span>
            <span className="live-tracking__chart-context-axis">
              {effectiveSource === "archive" ? labels.sourceArchiveNote : labels.sourceRecomputeNote}
            </span>
          </div>
          <div className="live-tracking__reference-grid">
            {visibleSeriesByJoint.map((series, joint) => (
              <LiveTrackingChart
                key={`${dataset.index}-${joint}-${metric}-${effectiveSource}`}
                title={`${labels.joint} ${joint + 1}`}
                unit={metric === "torque" ? labels.torqueUnit : labels.currentUnit}
                series={series}
                times={times}
                range={range}
                scale={1}
                digits={metric === "torque" ? 2 : 3}
                includeZero
                minSpan={1e-4}
                labels={liveLabels}
                hoverTime={chartHoverTime}
                cursorTime={cursorTime}
                onHover={setHoverTime}
                hasAnySamples
              />
            ))}
          </div>
        </>
      ) : null}

      <footer className="live-tracking__footer">
        <span className="live-tracking__hover-hint" data-active={chartHoverTime !== null}>
          {chartHoverTime !== null
            ? liveLabels.readoutHover(formatSeconds(chartHoverTime))
            : labels.hoverHint}
        </span>
        <span className="live-tracking__reference-source">
          {dataset ? labels.sourceFile(dataset.source.file) : labels.currentMode}
        </span>
      </footer>
    </section>
  );
}
