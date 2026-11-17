/**
 * 曲线.tsx —— 手绘 canvas 折线图（**不引图表库**）。
 *
 * 数据源：`s.曲线` —— `{曲线名: 采样点[]}`，点是 `{t: 墙钟秒, v: 数值}`，
 * 由后端下行主题「指标」产生（`数据/仓库.ts` 的环形缓冲，最近 120 秒）。
 *
 * 这个组件只做四件事，多一件都不做：
 *   ① 多序列同图，每条一个颜色（颜色取自皮肤的 `--palette-N`，换肤自动变）
 *   ② Y 轴**按当前窗口内的真实数据自动缩放**（不写死 0..1，也不外推）
 *   ③ X 轴最多显示 120 秒；起步数据不足时自动收缩，与鼠标查询共用范围
 *   ④ 鼠标悬停暂停刷新并画十字线，读数取**最近的真实采样点**（不插值编数）
 *
 * ⚠️ 这里**不做**平滑、不做外推、不做滤波：图上的每一个像素都必须能追到一个真实采样点。
 */
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { SamplePoint } from "../数据/connection";
import { formatNumber, useTranslation } from "../视图/文案";

export interface LineChartProps {
  /** `{名称: 点[]}`；空对象 = 还没收到任何指标帧 */
  data: Record<string, SamplePoint[]>;
  /** 只画这些（未给出 = 全画） */
  visible?: Set<string>;
  /** 时间窗（秒） */
  windowSeconds?: number;
  height?: number;
  /** 悬停暂停状态变化时通知外面（图例上要写"暂停中"） */
  onPausedChange?: (paused: boolean) => void;
}

/** 从皮肤变量里算配色（**不缓存** CSS 变量值：换肤时必须跟着变） */
export function seriesColor(seriesIndex: number): string {
  return `var(--palette-${(seriesIndex % 8) + 1})`;
}

interface HoverState {
  time: number;
}

interface TimeRange {
  earliest: number;
  latest: number;
  span: number;
}

/**
 * 绘图和鼠标查询必须共用这一份时间范围。
 * 旧实现绘图会把刚起步的 120 s 窗口收缩成 10 s，鼠标却仍按 120 s 换算，
 * 因此十字线在右边、标点却跑到中间。
 */
function getTimeRange(data: Record<string, SamplePoint[]>, seriesNames: string[], windowSeconds: number): TimeRange | null {
  let latest = 0;
  for (const name of seriesNames) {
    const points = data[name];
    if (points?.length) latest = Math.max(latest, points[points.length - 1].t);
  }
  if (!latest) return null;

  let span = windowSeconds;
  for (const name of seriesNames) {
    const points = data[name];
    if (points?.length) span = Math.min(span, Math.max(10, latest - points[0].t));
  }
  return { earliest: latest - span, latest: latest, span: span };
}

/** 二分查找距离指定时刻最近的真实采样点。 */
function nearestSample(points: SamplePoint[], time: number): SamplePoint | null {
  if (!points.length) return null;
  let left = 0;
  let right = points.length - 1;
  while (left < right) {
    const middle = Math.floor((left + right) / 2);
    if (points[middle].t < time) left = middle + 1;
    else right = middle;
  }
  const after = points[left];
  const before = left > 0 ? points[left - 1] : null;
  return before && Math.abs(before.t - time) <= Math.abs(after.t - time) ? before : after;
}

export function LineChart({ data: data, visible: visible, windowSeconds: windowSeconds = 120, height: height = 200, onPausedChange: onPausedChange }: LineChartProps) {
  const t = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState<HoverState | null>(null);
  // 每帧最多重画一次（30 Hz 数据 + 悬停事件都会来敲门）
  const framePending = useRef(false);

  // 颜色必须按“稳定的曲线名称顺序”分配。
  // 验证页下方的勾选列表也是按名称排序；这里如果直接使用后端对象的插入顺序，
  // 同一条曲线在画布和列表里就可能拿到不同颜色，看起来像勾选错了曲线。
  const names = useMemo(() => Object.keys(data).sort(), [data]);
  const visibleNames = useMemo(() => {
    const selected = names.filter((n) => (visible ? visible.has(n) : true));
    // 有真实点的排前面，全空的排在后面（不让空曲线挤掉有数据的）
    return selected.sort((a, b) => (data[b]?.length ?? 0) - (data[a]?.length ?? 0));
  }, [names, visible, data]);

  // 容器宽度跟随（ResizeObserver：拖分隔条时图要跟着变宽，不能留白边）
  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(Math.max(160, element.clientWidth)));
    observer.observe(element);
    setWidth(Math.max(160, element.clientWidth));
    return () => observer.disconnect();
  }, []);

  // 悬停状态要通知外面（图例上写"暂停中"）
  useEffect(() => {
    onPausedChange?.(hover !== null);
  }, [hover, onPausedChange]);

  useEffect(() => {
    if (framePending.current) return;
    framePending.current = true;
    const frameHandle = requestAnimationFrame(() => {
      framePending.current = false;
      draw();
    });
    return () => {
      cancelAnimationFrame(frameHandle);
      framePending.current = false;
    };

    function draw() {
      const element = canvasRef.current;
      if (!element) return;
      const pixelRatio = window.devicePixelRatio || 1;
      const canvasHeight = height;
      if (element.width !== Math.round(width * pixelRatio) || element.height !== Math.round(canvasHeight * pixelRatio)) {
        element.width = Math.round(width * pixelRatio);
        element.height = Math.round(canvasHeight * pixelRatio);
      }
      const context = element.getContext("2d");
      if (!context) return;
      const computedStyle = getComputedStyle(document.documentElement);
      const cssValue = (name: string, fallback: string) => computedStyle.getPropertyValue(name).trim() || fallback;

      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.clearRect(0, 0, width, canvasHeight);

      const left = 52;
      const right = 8;
      const top = 8;
      const bottom = 20;
      const plotWidth = Math.max(10, width - left - right);
      const plotHeight = Math.max(10, canvasHeight - top - bottom);

      context.fillStyle = cssValue("--plot-bg", "#000");
      context.fillRect(0, 0, width, canvasHeight);

      // ---- 时间范围：绘图与鼠标换算共用同一个结果 ----
      const timeRange = getTimeRange(data, visibleNames, windowSeconds);
      if (!timeRange) {
        // 一个点都没有：坐标轴照画，但用文案明确写"尚无指标帧"。
        // 工程师反馈"图表空白，用户只能从旁边文字推断"——坐标系本身是信息，
        // 关键是别让它看起来像"有数据只是没画出来"。
        context.strokeStyle = cssValue("--plot-grid", "#333");
        context.lineWidth = 1;
        context.strokeRect(left, top, plotWidth, plotHeight);
        for (let i = 1; i < 4; i += 1) {
          const y = top + (i / 4) * plotHeight;
          context.beginPath();
          context.moveTo(left, y);
          context.lineTo(left + plotWidth, y);
          context.stroke();
        }
        context.fillStyle = cssValue("--plot-tick", "#888");
        context.font = "10px " + cssValue("--font-mono", "monospace");
        context.textAlign = "center";
        context.fillText(t("曲线.轴时间"), left + plotWidth / 2, canvasHeight - 4);
        context.save();
        context.translate(12, top + plotHeight / 2);
        context.rotate(-Math.PI / 2);
        context.fillText(t("曲线.轴值"), 0, 0);
        context.restore();
        context.fillStyle = cssValue("--plot-text", "#888");
        context.font = "12px " + cssValue("--font-ui", "sans-serif");
        context.fillText(t("曲线.空"), left + plotWidth / 2, top + plotHeight / 2 - 4);
        context.font = "10px " + cssValue("--font-ui", "sans-serif");
        context.fillStyle = cssValue("--plot-tick", "#888");
        context.fillText(t("曲线.空提示"), left + plotWidth / 2, top + plotHeight / 2 + 14);
        return;
      }
      /*
       * X 轴窗口：**不超过**数据真实跨度。
       * 只跑了 20 秒的时候画满 120 秒，右边那一小撮挤成一根柱子 ——
       * 看着像"信号是脉冲"，其实是"窗口开太大"。所以取 min(窗口, 真实跨度)，
       * 但留一个 10 秒下限，免得刚收到两个点就横轴抖成一条线。
       */
      const { earliest: earliest, latest: latest, span: span } = timeRange;

      // ---- Y 范围：只看窗口内的真实点 ----
      let maximum = -Infinity;
      let minimum = Infinity;
      for (const n of visibleNames) {
        const points = data[n];
        if (!points) continue;
        for (let i = points.length - 1; i >= 0; i -= 1) {
          const p = points[i];
          if (p.t < earliest) break;
          if (p.v > maximum) maximum = p.v;
          if (p.v < minimum) minimum = p.v;
        }
      }
      const hasRange = Number.isFinite(maximum) && Number.isFinite(minimum);
      if (!hasRange) {
        maximum = 1;
        minimum = -1;
      } else if (maximum - minimum < 1e-12) {
        // 全平的一条线：给它一点可视厚度，但**不改数据**
        const middle = (maximum + minimum) / 2;
        const amplitude = Math.max(Math.abs(middle) * 0.05, 0.5);
        maximum = middle + amplitude;
        minimum = middle - amplitude;
      } else {
        const padding = (maximum - minimum) * 0.08;
        maximum += padding;
        minimum -= padding;
      }

      const X = (time: number) => left + ((time - earliest) / (latest - earliest)) * plotWidth;
      const Y = (value: number) => top + (1 - (value - minimum) / (maximum - minimum)) * plotHeight;

      // ---- 网格 + 刻度 ----
      context.strokeStyle = cssValue("--plot-grid", "#333");
      context.lineWidth = 1;
      context.fillStyle = cssValue("--plot-tick", "#888");
      context.font = "10px " + cssValue("--font-mono", "monospace");
      context.textAlign = "right";
      context.textBaseline = "middle";
      for (let i = 0; i <= 4; i += 1) {
        const value = minimum + ((maximum - minimum) * i) / 4;
        const y = Y(value);
        context.beginPath();
        context.moveTo(left, y);
        context.lineTo(left + plotWidth, y);
        context.stroke();
        context.fillText(formatNumber(value, 3), left - 4, y);
      }
      context.textAlign = "center";
      context.textBaseline = "top";
      const tickInterval = span <= 30 ? 5 : 15;
      for (let seconds = 0; seconds <= span + 0.001; seconds += tickInterval) {
        const time = latest - seconds;
        if (time < earliest) break;
        const x = X(time);
        context.beginPath();
        context.moveTo(x, top);
        context.lineTo(x, top + plotHeight);
        context.stroke();
        context.fillText(seconds === 0 ? "0" : `-${seconds}s`, x, top + plotHeight + 3);
      }
      context.strokeStyle = cssValue("--plot-border", "#444");
      context.strokeRect(left, top, plotWidth, plotHeight);

      // ---- 折线（每条曲线一段路径；分段的断点由"时间跳变"决定，不外推） ----
      let seriesIndex = 0;
      for (const n of names) {
        const isVisible = visibleNames.includes(n);
        const colorIndex = seriesIndex;
        seriesIndex += 1;
        if (!isVisible) continue;
        const points = data[n];
        if (!points || points.length < 1) continue;
        context.strokeStyle = cssValue(`--palette-${(colorIndex % 8) + 1}`, "#888");
        context.lineWidth = 1.5;
        context.beginPath();
        let pathStarted = false;
        for (let i = points.length - 1; i >= 0; i -= 1) {
          const p = points[i];
          if (p.t < earliest) break;
          const x = X(p.t);
          const y = Y(p.v);
          if (!pathStarted) {
            context.moveTo(x, y);
            pathStarted = true;
          } else {
            context.lineTo(x, y);
          }
        }
        context.stroke();
      }

      // ---- 十字线 + 最近真实点 ----
      if (hover) {
        // 十字线吸附到真实采样时刻，不再画在原始鼠标 x 上却读取另一个时刻。
        const hoverX = X(hover.time);
        context.strokeStyle = cssValue("--plot-cross", "#888");
        context.setLineDash([3, 3]);
        context.beginPath();
        context.moveTo(hoverX, top);
        context.lineTo(hoverX, top + plotHeight);
        context.stroke();
        context.setLineDash([]);
        context.font = "10px " + cssValue("--font-mono", "monospace");
        context.textAlign = "left";
        context.textBaseline = "top";
        let legendRow = 0;
        let legendSeriesIndex = 0;
        for (const n of names) {
          const colorIndex = legendSeriesIndex;
          legendSeriesIndex += 1;
          if (!visibleNames.includes(n)) continue;
          const points = data[n];
          if (!points || !points.length) continue;
          // 找离 悬.时间 最近的**真实**点（不插值）。
          const nearest = nearestSample(points, hover.time);
          if (!nearest) continue;
          const y = Y(nearest.v);
          context.fillStyle = cssValue(`--palette-${(colorIndex % 8) + 1}`, "#888");
          context.beginPath();
          context.arc(X(nearest.t), y, 2.5, 0, Math.PI * 2);
          context.fill();
          context.fillRect(left + 6, top + 6 + legendRow * 12, 8, 2);
          context.fillStyle = cssValue("--plot-text", "#ccc");
          context.fillText(`${n} = ${formatNumber(nearest.v, 4)}`, left + 18, top + 2 + legendRow * 12);
          legendRow += 1;
        }
      }
    }
  }, [data, visibleNames, names, width, height, windowSeconds, hover, t]);

  const handlePointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const element = canvasRef.current;
    if (!element) return;
    const r = element.getBoundingClientRect();
    const x = e.clientX - r.left;
    const left = 52;
    const plotWidth = Math.max(10, r.width - left - 8);
    const ratio = Math.min(1, Math.max(0, (x - left) / plotWidth));
    const timeRange = getTimeRange(data, visibleNames, windowSeconds);
    if (!timeRange) return;
    const targetTime = timeRange.earliest + ratio * timeRange.span;

    // 在所有可见曲线中选距离鼠标最近的真实采样时刻。
    // 当前指标是同一帧同时发布的，因此各曲线标点会与十字线共线。
    let snappedTime = targetTime;
    let nearestDistance = Infinity;
    for (const n of visibleNames) {
      const nearest = nearestSample(data[n] ?? [], targetTime);
      if (!nearest) continue;
      const distance = Math.abs(nearest.t - targetTime);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        snappedTime = nearest.t;
      }
    }
    setHover({ time: snappedTime });
  };

  return (
    <div ref={containerRef} className="w-full">
      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: height, display: "block", cursor: "crosshair" }}
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHover(null)}
        role="img"
        aria-label={t("验证.曲线")}
      />
    </div>
  );
}
