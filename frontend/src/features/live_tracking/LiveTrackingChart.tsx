/**
 * LiveTrackingChart.tsx —— 实时跟踪面板专用 Canvas 2D 图表。
 *
 * 和通用 `components/Chart.tsx` 的区别（也是本模块存在的原因）：
 *   · 横轴是**本运行段仿真时间**，由样本时间与后端确认的 elapsedS 决定，不用墙钟；
 *   · 缺失值（null / 非有限数）保留为 NaN，画线时**断线**，绝不补 0、不跨缺口连线；
 *   · 三张图由面板传入同一个 `range` 与同一个 `hoverTime`，悬停读数取最近的真实采样点；
 *   · t=0 是有效数据：是否为空只看数组长度，不用首个时间点的真值判断。
 *
 * 本组件不发任何命令、不订阅仓库、不启动数据定时器；重绘只用 requestAnimationFrame 合并。
 */
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type { LiveTrackingLabels } from "./labels";
import {
  clamp,
  computeValueRange,
  firstIndexInRange,
  formatAxisValue,
  formatFixed,
  formatSeconds,
  formatTimeTick,
  lastIndexInRange,
  lowerBound,
  nearestIndex,
  timeTickStep,
  upperBound,
  type TimeRange,
} from "./live_tracking_math";

export type LiveTrackingMarker = "circle" | "square" | "diamond" | "triangle";

export interface LiveTrackingSeries {
  key: string;
  label: string;
  values: Float64Array;
  /** Full series for a fixed vertical scale during progressive playback. */
  scaleValues?: Float64Array;
  /** CSS 变量名，例如 `--palette-1`；换肤后自动跟随。 */
  colorVariable: string;
  /** 空数组 = 实线；例如 `[5, 4]` = 虚线。 */
  dash: readonly number[];
  marker: LiveTrackingMarker;
  lineWidth?: number;
  /** 后画的系列。目标虚线盖在实际线之上，重合时两种线型都还看得见。 */
  drawOnTop?: boolean;
}

export interface LiveTrackingChartProps {
  title: string;
  /** 纵轴显示单位；力矩始终 N·m。 */
  unit: string;
  series: readonly LiveTrackingSeries[];
  times: Float64Array;
  /** 三图共用的仿真时间范围（秒）。 */
  range: TimeRange;
  /** 弧度 → 显示单位的倍率；力矩为 1。 */
  scale: number;
  /** 读数小数位。 */
  digits: number;
  /** 纵轴是否纳入 0（有符号量看正负）。 */
  includeZero: boolean;
  /** 恒定值/单点时的最小纵轴跨度（显示单位）。 */
  minSpan: number;
  labels: LiveTrackingLabels;
  /** 面板统一维护的悬停仿真时间；null = 没在悬停。 */
  hoverTime: number | null;
  /** 参考回放的播放游标时间；没有指针悬停时用它画竖线/读数。 */
  cursorTime?: number | null;
  /** 把指针位置换算成仿真时间交给面板；面板负责吸附到真实采样点。 */
  onHover: (time: number) => void;
  /** 整个运行段是否有过采样（用于区分“尚无采样”和“本窗口无数据”）。 */
  hasAnySamples?: boolean;
  emptyTitle?: string;
  emptyHint?: string;
  /** 图注说明（例如补偿项未接入）。 */
  note?: string;
}

interface CanvasLayout {
  plotLeft: number;
  plotWidth: number;
}

interface Colors {
  background: string;
  border: string;
  grid: string;
  tick: string;
  text: string;
  cross: string;
  fontUi: string;
  fontMono: string;
}

const NEAREST_EPSILON = 1e-6;

/** 观察 `<html data-theme>` 变化，换肤后强制重绘 Canvas（CSS 变量已变，但 props 没变）。 */
function useThemeStamp(): number {
  const [stamp, setStamp] = useState(0);
  useEffect(() => {
    if (typeof MutationObserver === "undefined") return;
    const observer = new MutationObserver(() => setStamp((value) => value + 1));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class", "style", "lang"],
    });
    return () => observer.disconnect();
  }, []);
  return stamp;
}

function readColors(style: CSSStyleDeclaration): Colors {
  const value = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    background: value("--plot-bg", "#ffffff"),
    border: value("--plot-border", "#cccccc"),
    grid: value("--plot-grid", "#eeeeee"),
    tick: value("--plot-tick", "#888888"),
    text: value("--plot-text", "#333333"),
    cross: value("--plot-cross", "#999999"),
    fontUi: value("--font-ui", "sans-serif"),
    fontMono: value("--font-mono", "monospace"),
  };
}

function fitText(context: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (maxWidth <= 0 || context.measureText(text).width <= maxWidth) return text;
  let low = 0;
  let high = text.length;
  while (low < high) {
    const middle = (low + high + 1) >>> 1;
    const candidate = `${text.slice(0, middle)}…`;
    if (context.measureText(candidate).width <= maxWidth) low = middle;
    else high = middle - 1;
  }
  return low > 0 ? `${text.slice(0, low)}…` : "…";
}

function drawMarker(
  context: CanvasRenderingContext2D,
  marker: LiveTrackingMarker,
  x: number,
  y: number,
  radius: number,
  color: string,
  outline: string,
): void {
  context.save();
  context.fillStyle = color;
  context.strokeStyle = outline;
  context.lineWidth = 1;
  context.beginPath();
  if (marker === "square") {
    context.rect(x - radius, y - radius, radius * 2, radius * 2);
  } else if (marker === "diamond") {
    context.moveTo(x, y - radius * 1.3);
    context.lineTo(x + radius * 1.3, y);
    context.lineTo(x, y + radius * 1.3);
    context.lineTo(x - radius * 1.3, y);
    context.closePath();
  } else if (marker === "triangle") {
    context.moveTo(x, y - radius * 1.35);
    context.lineTo(x + radius * 1.25, y + radius);
    context.lineTo(x - radius * 1.25, y + radius);
    context.closePath();
  } else {
    context.arc(x, y, radius, 0, Math.PI * 2);
  }
  context.fill();
  context.stroke();
  context.restore();
}

interface DrawOptions {
  canvas: HTMLCanvasElement;
  width: number;
  height: number;
  times: Float64Array;
  series: readonly LiveTrackingSeries[];
  range: TimeRange;
  scale: number;
  includeZero: boolean;
  minSpan: number;
  hoverTime: number | null;
  cursorTime?: number | null;
  labels: LiveTrackingLabels;
  hasAnySamples: boolean;
  emptyTitle?: string;
  emptyHint?: string;
}

function drawChart(options: DrawOptions): CanvasLayout {
  const { canvas, width, height, times, series, range, scale, labels } = options;
  const devicePixelRatio = Math.max(1, window.devicePixelRatio || 1);
  const pixelWidth = Math.max(1, Math.round(width * devicePixelRatio));
  const pixelHeight = Math.max(1, Math.round(height * devicePixelRatio));
  if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
  if (canvas.height !== pixelHeight) canvas.height = pixelHeight;

  const context = canvas.getContext("2d");
  if (!context) return { plotLeft: 40, plotWidth: Math.max(10, width - 46) };

  context.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);

  const computedStyle = getComputedStyle(canvas);
  const colors = readColors(computedStyle);
  const colorOf = (variable: string, fallback: string) =>
    computedStyle.getPropertyValue(variable).trim() || fallback;
  const compact = width < 320;
  const fontSize = compact ? 9 : 10;
  context.fillStyle = colors.background;
  context.fillRect(0, 0, width, height);

  const spanS = Math.max(1e-6, range.endS - range.startS);
  const valueRange =
    computeValueRange(
      series.map((item) => item.scaleValues ?? item.values),
      times,
      range,
      scale,
      { includeZero: options.includeZero, minSpan: options.minSpan },
    ) ?? { min: -1, max: 1 };
  const valueSpan = Math.max(1e-12, valueRange.max - valueRange.min);

  // 纵轴刻度文字宽度决定左边距（避免窄栏里标签被裁掉，也避免固定左边距浪费绘图区）。
  const tickCount = 4;
  const tickValues: number[] = [];
  const tickLabels: string[] = [];
  for (let i = 0; i <= tickCount; i += 1) {
    const value = valueRange.min + (valueSpan * i) / tickCount;
    tickValues.push(value);
    tickLabels.push(formatAxisValue(value, valueSpan));
  }
  context.font = `${fontSize}px ${colors.fontMono}`;
  let widestLabel = 0;
  for (const label of tickLabels) {
    widestLabel = Math.max(widestLabel, context.measureText(label).width);
  }
  const padLeft = Math.max(compact ? 30 : 34, Math.ceil(widestLabel) + 9);
  const padRight = 7;
  const padTop = 6;
  const padBottom = 16;
  const plotWidth = Math.max(10, width - padLeft - padRight);
  const plotHeight = Math.max(10, height - padTop - padBottom);

  const X = (time: number) => padLeft + ((time - range.startS) / spanS) * plotWidth;
  const Y = (value: number) => padTop + (1 - (value - valueRange.min) / valueSpan) * plotHeight;

  // ---- 网格与纵轴刻度 ----
  context.lineWidth = 1;
  context.strokeStyle = colors.grid;
  context.fillStyle = colors.tick;
  context.font = `${fontSize}px ${colors.fontMono}`;
  context.textAlign = "right";
  context.textBaseline = "middle";
  for (let i = 0; i <= tickCount; i += 1) {
    const y = Y(tickValues[i]);
    context.beginPath();
    context.moveTo(padLeft, y);
    context.lineTo(padLeft + plotWidth, y);
    context.stroke();
    context.fillText(tickLabels[i], padLeft - 5, y);
  }

  // ---- 横轴刻度：三图共用同一范围 ----
  const timeStep = timeTickStep(spanS, plotWidth);
  const firstTick = Math.ceil((range.startS - NEAREST_EPSILON) / timeStep) * timeStep;
  const tickTotal = Math.floor((range.endS - firstTick) / timeStep + NEAREST_EPSILON);
  context.textBaseline = "top";
  for (let i = 0; i <= tickTotal; i += 1) {
    const time = firstTick + i * timeStep;
    if (time < range.startS - NEAREST_EPSILON) continue;
    if (time > range.endS + NEAREST_EPSILON) break;
    const x = X(time);
    context.strokeStyle = colors.grid;
    context.beginPath();
    context.moveTo(x, padTop);
    context.lineTo(x, padTop + plotHeight);
    context.stroke();
    context.fillStyle = colors.tick;
    context.textAlign = x <= padLeft + 10 ? "left" : x >= width - 14 ? "right" : "center";
    context.fillText(formatTimeTick(time, timeStep), x, padTop + plotHeight + 3);
  }

  // ---- 0 线（有符号量）----
  if (options.includeZero && valueRange.min < 0 && valueRange.max > 0) {
    const zeroY = Y(0);
    context.save();
    context.strokeStyle = colors.border;
    context.setLineDash([2, 3]);
    context.beginPath();
    context.moveTo(padLeft, zeroY);
    context.lineTo(padLeft + plotWidth, zeroY);
    context.stroke();
    context.restore();
  }

  context.strokeStyle = colors.border;
  context.lineWidth = 1;
  context.strokeRect(padLeft, padTop, plotWidth, plotHeight);

  const first = lowerBound(times, range.startS);
  const last = Math.min(upperBound(times, range.endS) - 1, times.length - 1);
  let anyFinite = false;

  if (first <= last) {
    const drawSeries = [...series].sort(
      (left, right) => Number(left.drawOnTop === true) - Number(right.drawOnTop === true),
    );
    for (const item of drawSeries) {
      const values = item.values;
      const available = Math.min(last, values.length - 1);
      if (available < first) continue;
      const color = colorOf(item.colorVariable, colors.text);
      const finiteIndices: number[] = [];
      let finiteCount = 0;
      let lastFiniteIndex = -1;

      context.strokeStyle = color;
      context.lineWidth = item.lineWidth ?? 1.6;
      context.lineJoin = "round";
      context.lineCap = "butt";
      context.setLineDash([...item.dash]);
      context.beginPath();
      let penDown = false;
      for (let i = first; i <= available; i += 1) {
        const raw = values[i];
        if (!Number.isFinite(raw)) {
          // null / 非有限值：留空断线，不能跨缺口连到下一个真实点。
          penDown = false;
          continue;
        }
        anyFinite = true;
        const pointX = X(times[i]);
        const pointY = Y(raw * scale);
        if (penDown) context.lineTo(pointX, pointY);
        else {
          context.moveTo(pointX, pointY);
          penDown = true;
        }
        finiteCount += 1;
        lastFiniteIndex = i;
        if (finiteIndices.length <= 8) finiteIndices.push(i);
      }
      context.stroke();
      context.setLineDash([]);

      // 单点/短轨迹没有可描的线段，用点标出来；长轨迹只标最新端点。
      if (finiteCount === 1 && finiteIndices.length > 0) {
        const index = finiteIndices[0];
        drawMarker(
          context,
          item.marker,
          X(times[index]),
          Y(values[index] * scale),
          2.8,
          color,
          colors.background,
        );
      } else if (finiteCount > 1 && finiteCount <= 8) {
        for (const index of finiteIndices) {
          drawMarker(
            context,
            item.marker,
            X(times[index]),
            Y(values[index] * scale),
            2.2,
            color,
            colors.background,
          );
        }
      } else if (lastFiniteIndex >= 0) {
        drawMarker(
          context,
          item.marker,
          X(times[lastFiniteIndex]),
          Y(values[lastFiniteIndex] * scale),
          2.4,
          color,
          colors.background,
        );
      }
    }
  }

  // ---- 统一悬停/播放游标：十字线 + 最近真实采样点 ----
  const cursorTime = options.hoverTime ?? options.cursorTime ?? null;
  if (cursorTime !== null) {
    const index = nearestIndex(times, cursorTime);
    if (index >= 0) {
      const time = times[index];
      if (time >= range.startS - NEAREST_EPSILON && time <= range.endS + NEAREST_EPSILON) {
        const x = X(time);
        context.save();
        context.strokeStyle = colors.cross;
        context.lineWidth = 1;
        context.setLineDash([3, 3]);
        context.beginPath();
        context.moveTo(x, padTop);
        context.lineTo(x, padTop + plotHeight);
        context.stroke();
        context.restore();
        for (const item of series) {
          const raw = item.values[index];
          if (!Number.isFinite(raw)) continue;
          const color = colorOf(item.colorVariable, colors.text);
          drawMarker(
            context,
            item.marker,
            x,
            Y(raw * scale),
            3.4,
            color,
            colors.background,
          );
        }
      }
    }
  }

  // ---- 空数据提示：坐标系照画，但明确写原因，别让人误以为“有数据没画出来” ----
  if (!anyFinite) {
    const title =
      options.emptyTitle ??
      (!options.hasAnySamples ? labels.noSamples : labels.noSeriesData);
    const hint =
      options.emptyHint ??
      (!options.hasAnySamples ? labels.noSamplesHint : labels.noSeriesDataHint);
    const centerX = padLeft + plotWidth / 2;
    const centerY = padTop + plotHeight / 2;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.font = `${fontSize + 1.5}px ${colors.fontUi}`;
    context.fillStyle = colors.text;
    context.fillText(fitText(context, title, plotWidth - 12), centerX, centerY - 6);
    context.font = `${fontSize}px ${colors.fontUi}`;
    context.fillStyle = colors.tick;
    context.fillText(fitText(context, hint, plotWidth - 12), centerX, centerY + 12);
  }

  return { plotLeft: padLeft, plotWidth };
}

export function LiveTrackingChart({
  title,
  unit,
  series,
  times,
  range,
  scale,
  digits,
  includeZero,
  minSpan,
  labels,
  hoverTime,
  cursorTime = null,
  onHover,
  hasAnySamples = false,
  emptyTitle,
  emptyHint,
  note,
}: LiveTrackingChartProps) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const layoutRef = useRef<CanvasLayout | null>(null);
  const dprRef = useRef(1);
  const [width, setWidth] = useState(320);
  const [dprVersion, setDprVersion] = useState(0);
  const themeStamp = useThemeStamp();
  const height = width < 320 ? 128 : width < 440 ? 144 : 156;

  // 容器宽度跟随（拖左栏分隔条、缩放窗口时 Canvas 要跟着变，不能留白边）。
  // Retina 像素比变化时 CSS 尺寸可能不变，用 resolution 媒体查询补一次重绘。
  useLayoutEffect(() => {
    const element = wrapperRef.current;
    if (!element) return;
    let resolutionQuery: MediaQueryList | null = null;

    function measure() {
      const next = element?.clientWidth ?? 0;
      if (next > 0) {
        setWidth((current) => (Math.abs(current - next) >= 0.5 ? next : current));
      }
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      if (Math.abs(dpr - dprRef.current) > 1e-6) {
        dprRef.current = dpr;
        setDprVersion((value) => value + 1);
      }
    }

    function handleResolutionChange() {
      setDprVersion((value) => value + 1);
      bindResolutionQuery();
    }

    function bindResolutionQuery() {
      resolutionQuery?.removeEventListener("change", handleResolutionChange);
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      resolutionQuery = window.matchMedia(`(resolution: ${dpr}dppx)`);
      resolutionQuery.addEventListener("change", handleResolutionChange);
    }

    dprRef.current = Math.max(1, window.devicePixelRatio || 1);
    measure();
    bindResolutionQuery();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      resolutionQuery?.removeEventListener("change", handleResolutionChange);
    };
  }, []);

  // 每帧最多画一次：数据 20–30 Hz 更新时不会排队堆画布。
  useEffect(() => {
    const handle = requestAnimationFrame(() => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      layoutRef.current = drawChart({
        canvas,
        width,
        height,
        times,
        series,
        range,
        scale,
        includeZero,
        minSpan,
        hoverTime,
        cursorTime,
        labels,
        hasAnySamples,
        emptyTitle,
        emptyHint,
      });
    });
    return () => cancelAnimationFrame(handle);
  }, [
    width,
    height,
    dprVersion,
    times,
    series,
    range,
    scale,
    includeZero,
    minSpan,
    hoverTime,
    cursorTime,
    labels,
    hasAnySamples,
    themeStamp,
    emptyTitle,
    emptyHint,
  ]);

  const handlePointer = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const layout = layoutRef.current;
    if (!layout || layout.plotWidth <= 0) return;
    const rectangle = event.currentTarget.getBoundingClientRect();
    const ratio = clamp(
      (event.clientX - rectangle.left - layout.plotLeft) / layout.plotWidth,
      0,
      1,
    );
    onHover(range.startS + ratio * (range.endS - range.startS));
  };

  const hoverIndex =
    hoverTime !== null && times.length > 0
      ? nearestIndex(times, hoverTime)
      : -1;
  const hoverInRange =
    hoverIndex >= 0 &&
    times[hoverIndex] >= range.startS - NEAREST_EPSILON &&
    times[hoverIndex] <= range.endS + NEAREST_EPSILON;
  const cursorIndex =
    cursorTime !== null && times.length > 0 ? nearestIndex(times, cursorTime) : -1;
  const cursorInRange =
    cursorIndex >= 0 &&
    times[cursorIndex] >= range.startS - NEAREST_EPSILON &&
    times[cursorIndex] <= range.endS + NEAREST_EPSILON;
  const latestIndex = lastIndexInRange(times, range);
  const readoutIndex = hoverInRange ? hoverIndex : cursorInRange ? cursorIndex : latestIndex;
  const readoutLabel =
    hoverInRange && hoverIndex >= 0
      ? labels.readoutHover(formatSeconds(times[hoverIndex]))
      : cursorInRange && cursorIndex >= 0
        ? labels.readoutCursor(formatSeconds(times[cursorIndex]))
        : latestIndex >= 0
          ? labels.readoutLatest(formatSeconds(times[latestIndex]))
          : labels.readoutNone;

  const hasSampleInWindow = firstIndexInRange(times, range) >= 0;

  return (
    <figure className="live-tracking__chart">
      <figcaption className="live-tracking__chart-head">
        <div className="live-tracking__chart-heading">
          <span className="live-tracking__chart-title">{title}</span>
          <span className="live-tracking__chart-unit">{unit}</span>
          <span className="live-tracking__chart-readout" data-empty={!hasSampleInWindow}>
            {readoutLabel}
          </span>
        </div>
        <div className="live-tracking__legend" role="list" aria-label={labels.legend}>
          {series.map((item) => {
            const raw =
              readoutIndex >= 0 && readoutIndex < item.values.length
                ? item.values[readoutIndex]
                : Number.NaN;
            const text = Number.isFinite(raw)
              ? formatFixed(raw * scale, digits)
              : labels.missing;
            return (
              <span
                className="live-tracking__legend-item"
                role="listitem"
                key={item.key}
                title={`${item.label} ${text}${Number.isFinite(raw) ? ` ${unit}` : ""}`}
              >
                <span
                  className="live-tracking__legend-line"
                  aria-hidden="true"
                  style={{
                    borderTopColor: `var(${item.colorVariable})`,
                    borderTopStyle: item.dash.length > 0 ? "dashed" : "solid",
                  }}
                />
                <span
                  className="live-tracking__legend-marker"
                  aria-hidden="true"
                  data-marker={item.marker}
                  style={{ color: `var(${item.colorVariable})` }}
                />
                <span className="live-tracking__legend-label">{item.label}</span>
                <span className="live-tracking__legend-value" data-missing={!Number.isFinite(raw)}>
                  {text}
                </span>
              </span>
            );
          })}
          {note ? <span className="live-tracking__chart-note">{note}</span> : null}
        </div>
      </figcaption>
      <div className="live-tracking__canvas-wrap" ref={wrapperRef}>
        <canvas
          ref={canvasRef}
          className="live-tracking__canvas"
          style={{ height: `${height}px` }}
          role="img"
          aria-label={labels.chartAria(title, unit)}
          onPointerMove={handlePointer}
          onPointerDown={handlePointer}
        />
      </div>
    </figure>
  );
}
