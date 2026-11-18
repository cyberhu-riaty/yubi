/**
 * LiveTrackingPanel.tsx —— 左栏独立的实时跟踪曲线面板。
 *
 * 数据只从 props 来（A 的适配层负责真实仿真数据与入口接入）：
 *   · 不订阅全局状态仓库、不建 WebSocket、不读文件/平台 API；
 *   · 不发运行/暂停/复位等任何物理命令；
 *   · 不启动定时器生成曲线，横轴只跟随样本时间与后端确认的 elapsedS；
 *   · 缺失值（null）留空断线，不补 0、不画演示波形。
 *
 * 展示状态（所选关节、时间窗、角度单位、悬停位置、速度图展开）留在组件内部。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { LiveTrackingChart, type LiveTrackingSeries } from "./LiveTrackingChart";
import { liveTrackingLabels, type LiveTrackingLabels } from "./labels";
import {
  clamp,
  computeTimeRange,
  extractJointSeries,
  formatSeconds,
  lastFiniteSampleTime,
  nearestIndex,
} from "./live_tracking_math";
import type { LiveTrackingPanelProps } from "./types";
import "./live_tracking.css";

const WINDOW_OPTIONS = [10, 30, 60] as const;
const DEGREES_PER_RADIAN = 180 / Math.PI;

type AngleUnit = "deg" | "rad";

interface Notice {
  tone: "danger" | "warn" | "info" | "ok";
  text: string;
}

function shortenRunId(runId: string): string {
  if (runId.length <= 22) return runId;
  return `${runId.slice(0, 12)}…${runId.slice(-6)}`;
}

function finiteOrNull(value: number | null): number | null {
  return value !== null && Number.isFinite(value) && value >= 0 ? value : null;
}

export function LiveTrackingPanel({
  runId,
  experimentName,
  modelName,
  status,
  connected,
  locale,
  jointNames,
  samples,
  elapsedS,
  durationS,
  dataAgeS,
  compensationState,
}: LiveTrackingPanelProps) {
  const labels: LiveTrackingLabels = liveTrackingLabels[locale];

  const [jointIndex, setJointIndex] = useState(0);
  const [windowSeconds, setWindowSeconds] = useState<number>(WINDOW_OPTIONS[0]);
  const [angleUnit, setAngleUnit] = useState<AngleUnit>("deg");
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const [showVelocity, setShowVelocity] = useState(false);

  const jointCount = jointNames.length;
  // 关节数量变化时，失效的选中项立即回落到 J1；渲染数据也不访问越界下标。
  const activeJointIndex = jointCount > 0 ? (jointIndex < jointCount ? jointIndex : 0) : -1;
  const activeJointName = activeJointIndex >= 0 ? jointNames[activeJointIndex] : "";

  useEffect(() => {
    setJointIndex((current) =>
      jointCount === 0 || current < 0 || current >= jointCount ? 0 : current,
    );
  }, [jointCount]);

  const safeElapsedS = Number.isFinite(elapsedS) && elapsedS >= 0 ? elapsedS : 0;
  const lastSampleS = useMemo(() => lastFiniteSampleTime(samples), [samples]);
  const range = useMemo(
    () => computeTimeRange(lastSampleS, safeElapsedS, windowSeconds),
    [lastSampleS, safeElapsedS, windowSeconds],
  );
  const jointData = useMemo(
    () => extractJointSeries(samples, activeJointIndex, range.startS),
    [samples, activeJointIndex, range.startS],
  );

  // runId 改变 = 新运行段：旧悬停不能带过去。
  useEffect(() => {
    setHoverTime(null);
  }, [runId]);

  // 窗口滑动后，旧的悬停时刻可能已经不在轴内；清掉，避免读数与十字线错位。
  useEffect(() => {
    setHoverTime((current) => {
      if (current === null) return null;
      return current < range.startS || current > range.endS ? null : current;
    });
  }, [range.startS, range.endS]);

  const handleHover = useCallback(
    (targetTime: number) => {
      const times = jointData.times;
      if (times.length === 0) return;
      const index = nearestIndex(times, targetTime);
      if (index < 0) return;
      setHoverTime(times[index]);
    },
    [jointData.times],
  );

  const angleScale = angleUnit === "deg" ? DEGREES_PER_RADIAN : 1;
  const angleUnitLabel = angleUnit === "deg" ? labels.deg : labels.rad;
  const angleDigits = angleUnit === "deg" ? 2 : 3;
  const angleMinSpan = angleUnit === "deg" ? 1e-4 : 1e-6;
  const velocityUnit = angleUnit === "deg" ? labels.unitDegPerSecond : labels.unitRadPerSecond;

  const positionSeries = useMemo<LiveTrackingSeries[]>(
    () => [
      {
        key: "reference",
        label: labels.legendReference,
        values: jointData.reference,
        colorVariable: "--palette-2",
        dash: [6, 4],
        marker: "square",
        lineWidth: 1.5,
        drawOnTop: true,
      },
      {
        key: "position",
        label: labels.legendActual,
        values: jointData.position,
        colorVariable: "--palette-1",
        dash: [],
        marker: "circle",
        lineWidth: 1.8,
      },
    ],
    [labels, jointData.reference, jointData.position],
  );

  const errorSeries = useMemo<LiveTrackingSeries[]>(
    () => [
      {
        key: "error",
        label: labels.legendError,
        values: jointData.error,
        colorVariable: "--palette-4",
        dash: [],
        marker: "diamond",
        lineWidth: 1.8,
      },
    ],
    [labels, jointData.error],
  );

  const torqueSeries = useMemo<LiveTrackingSeries[]>(() => {
    const list: LiveTrackingSeries[] = [
      {
        key: "torque",
        label: labels.legendTorque,
        values: jointData.torque,
        colorVariable: "--palette-5",
        dash: [],
        marker: "circle",
        lineWidth: 1.8,
      },
    ];
    // 只有真实出现过补偿力矩才叠加；整项 null / 全缺失时显示“未接入”而不是画 0。
    if (jointData.hasCompensation) {
      list.push({
        key: "compensation",
        label: labels.legendCompensation,
        values: jointData.compensation,
        colorVariable: "--palette-6",
        dash: [4, 3],
        marker: "triangle",
        lineWidth: 1.5,
        drawOnTop: true,
      });
    }
    return list;
  }, [labels, jointData.torque, jointData.compensation, jointData.hasCompensation]);

  const velocitySeries = useMemo<LiveTrackingSeries[]>(
    () => [
      {
        key: "velocity",
        label: labels.legendVelocity,
        values: jointData.velocity,
        colorVariable: "--palette-3",
        dash: [],
        marker: "circle",
        lineWidth: 1.6,
      },
    ],
    [labels, jointData.velocity],
  );

  const compensationNote = jointData.hasCompensation
    ? undefined
    : compensationState === "unavailable"
      ? labels.compensationUnavailableNote
      : compensationState === "disabled"
        ? labels.compensationDisabledNote
        : labels.compensationNoDataNote;

  const experimentText = experimentName.trim() || labels.noExperiment;
  const modelText = modelName.trim() || labels.noModel;
  const durationValue = finiteOrNull(durationS);
  const dataAge = finiteOrNull(dataAgeS);
  const stale = status === "running" && dataAge !== null && dataAge > 0.5;
  const dataAgeText =
    samples.length === 0
      ? labels.neverUpdated
      : dataAge === null
        ? labels.dataAgeUnknown
        : labels.dataAgeSeconds(formatSeconds(dataAge));
  const progress =
    durationValue !== null && durationValue > 0
      ? clamp((safeElapsedS / durationValue) * 100, 0, 100)
      : null;
  const compensationText =
    compensationState === "enabled"
      ? labels.compensationEnabled
      : compensationState === "disabled"
        ? labels.compensationDisabled
        : labels.compensationUnavailable;

  const notices: Notice[] = [];
  if (!connected) notices.push({ tone: "danger", text: labels.disconnected });
  if (stale && dataAge !== null) {
    notices.push({ tone: "warn", text: labels.staleUpdates(`${formatSeconds(dataAge)} s`) });
  }
  switch (status) {
    case "idle":
      notices.push({ tone: "info", text: labels.idleHint });
      break;
    case "loading":
      notices.push({ tone: "info", text: labels.loadingHint });
      break;
    case "ready":
      notices.push({ tone: "info", text: labels.readyHint });
      break;
    case "running":
      if (connected && samples.length === 0) {
        notices.push({ tone: "info", text: labels.runningNoSamples });
      }
      break;
    case "paused":
      notices.push({ tone: "info", text: labels.pausedHint });
      break;
    case "completed":
      notices.push({ tone: "ok", text: labels.completedHint });
      break;
    case "error":
      notices.push({ tone: "danger", text: labels.errorHint });
      break;
    default:
      break;
  }

  const emptyTitle = jointCount === 0 ? labels.noJoints : undefined;
  const emptyHint = jointCount === 0 ? labels.noJointsHint : undefined;

  return (
    <section
      className="live-tracking"
      aria-label={labels.panelAria}
      data-status={status}
      data-locale={locale}
      onPointerLeave={() => setHoverTime(null)}
    >
      <header className="live-tracking__header">
        <div className="live-tracking__title-line">
          <h2 className="live-tracking__title">{labels.panelTitle}</h2>
          <span className="live-tracking__mode">{labels.simulation}</span>
          <span className="live-tracking__status" data-status={status} role="status">
            <span className="live-tracking__status-dot" aria-hidden="true" />
            {labels.status[status]}
          </span>
        </div>
        <div className="live-tracking__subtitle">
          <span className="live-tracking__simulation-note">{labels.simulationNote}</span>
          <span className="live-tracking__compensation" data-compensation={compensationState}>
            {labels.compensation}: {compensationText}
          </span>
          <span className="live-tracking__real-robot">{labels.realRobot}</span>
        </div>

        <dl className="live-tracking__facts">
          <div className="live-tracking__fact">
            <dt>{labels.experiment}</dt>
            <dd title={experimentText}>{experimentText}</dd>
          </div>
          <div className="live-tracking__fact">
            <dt>{labels.model}</dt>
            <dd title={modelText}>{modelText}</dd>
          </div>
          <div className="live-tracking__fact">
            <dt>{labels.runTime}</dt>
            <dd>
              <span>{formatSeconds(safeElapsedS)} s</span>
              <span className="live-tracking__muted">
                {durationValue !== null
                  ? `/ ${formatSeconds(durationValue)} s`
                  : `/ ${labels.durationUnknown}`}
              </span>
            </dd>
          </div>
          <div className="live-tracking__fact">
            <dt>{labels.dataUpdate}</dt>
            <dd data-stale={stale} title={dataAgeText}>
              {dataAgeText}
            </dd>
          </div>
        </dl>

        {progress !== null ? (
          <div
            className="live-tracking__progress"
            role="progressbar"
            aria-label={labels.progress}
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

        {notices.length > 0 ? (
          <div className="live-tracking__notices">
            {notices.map((notice, index) => (
              <p
                className="live-tracking__notice"
                data-tone={notice.tone}
                key={`${notice.tone}-${index}`}
              >
                {notice.text}
              </p>
            ))}
          </div>
        ) : null}
      </header>

      <div className="live-tracking__toolbar">
        <div className="live-tracking__joint-block">
          <div className="live-tracking__joints" role="group" aria-label={labels.jointSelection}>
            {jointNames.map((name, index) => (
              <button
                type="button"
                key={`${index}-${name}`}
                className="live-tracking__chip live-tracking__joint-button"
                aria-pressed={index === activeJointIndex}
                aria-label={`J${index + 1} · ${name}`}
                title={name}
                onClick={() => setJointIndex(index)}
              >
                J{index + 1}
              </button>
            ))}
            {jointCount === 0 ? (
              <span className="live-tracking__toolbar-empty">{labels.jointsUnavailable}</span>
            ) : null}
          </div>
        </div>

        <div className="live-tracking__display-options" role="group" aria-label={labels.displayOptions}>
          <div className="live-tracking__segmented" role="group" aria-label={labels.window}>
            {WINDOW_OPTIONS.map((seconds) => (
              <button
                type="button"
                key={seconds}
                className="live-tracking__chip live-tracking__window-button"
                aria-pressed={windowSeconds === seconds}
                onClick={() => setWindowSeconds(seconds)}
              >
                {labels.windowOption(seconds)}
              </button>
            ))}
          </div>
          <div className="live-tracking__segmented" role="group" aria-label={labels.unit}>
            {(["deg", "rad"] as const).map((unit) => (
              <button
                type="button"
                key={unit}
                className="live-tracking__chip live-tracking__unit-button"
                aria-pressed={angleUnit === unit}
                onClick={() => setAngleUnit(unit)}
              >
                {labels[unit]}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="live-tracking__chart-context">
        {activeJointIndex >= 0 ? (
          <span className="live-tracking__chart-context-joint" title={activeJointName}>
            J{activeJointIndex + 1} · {activeJointName}
          </span>
        ) : null}
        <span className="live-tracking__chart-context-axis">{labels.timeAxisNote}</span>
      </div>

      <div className="live-tracking__charts">
        <LiveTrackingChart
          title={labels.chartPositionTitle}
          unit={angleUnitLabel}
          series={positionSeries}
          times={jointData.times}
          range={range}
          scale={angleScale}
          digits={angleDigits}
          includeZero={false}
          minSpan={angleMinSpan}
          labels={labels}
          hoverTime={hoverTime}
          onHover={handleHover}
          hasAnySamples={samples.length > 0}
          emptyTitle={emptyTitle}
          emptyHint={emptyHint}
        />
        <LiveTrackingChart
          title={labels.chartErrorTitle}
          unit={angleUnitLabel}
          series={errorSeries}
          times={jointData.times}
          range={range}
          scale={angleScale}
          digits={angleDigits}
          includeZero
          minSpan={angleMinSpan}
          labels={labels}
          hoverTime={hoverTime}
          onHover={handleHover}
          hasAnySamples={samples.length > 0}
          emptyTitle={emptyTitle}
          emptyHint={emptyHint}
        />
        <LiveTrackingChart
          title={labels.chartTorqueTitle}
          unit={labels.unitTorque}
          series={torqueSeries}
          times={jointData.times}
          range={range}
          scale={1}
          digits={2}
          includeZero
          minSpan={1e-4}
          labels={labels}
          hoverTime={hoverTime}
          onHover={handleHover}
          hasAnySamples={samples.length > 0}
          emptyTitle={emptyTitle}
          emptyHint={emptyHint}
          note={compensationNote}
        />

        <div className="live-tracking__optional">
          <button
            type="button"
            className="live-tracking__optional-toggle"
            aria-expanded={showVelocity}
            aria-label={showVelocity ? labels.velocityHide : labels.velocityShow}
            title={showVelocity ? labels.velocityHide : labels.velocityShow}
            onClick={() => setShowVelocity((current) => !current)}
          >
            <span className="live-tracking__optional-arrow" aria-hidden="true">
              {showVelocity ? "▾" : "▸"}
            </span>
            {labels.velocityOptional}
          </button>
          {showVelocity ? (
            <LiveTrackingChart
              title={labels.chartVelocityTitle}
              unit={velocityUnit}
              series={velocitySeries}
              times={jointData.times}
              range={range}
              scale={angleScale}
              digits={angleDigits}
              includeZero
              minSpan={angleMinSpan}
              labels={labels}
              hoverTime={hoverTime}
              onHover={handleHover}
              hasAnySamples={samples.length > 0}
              emptyTitle={emptyTitle}
              emptyHint={emptyHint}
            />
          ) : null}
        </div>
      </div>

      <footer className="live-tracking__footer">
        <span className="live-tracking__hover-hint" data-active={hoverTime !== null}>
          {hoverTime !== null
            ? labels.readoutHover(formatSeconds(hoverTime))
            : labels.hoverHint}
        </span>
        <span
          className="live-tracking__run-id"
          title={runId || labels.noRun}
        >
          {runId ? `${labels.run} ${shortenRunId(runId)}` : labels.noRun}
        </span>
      </footer>
    </section>
  );
}
