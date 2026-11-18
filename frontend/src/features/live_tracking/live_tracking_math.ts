/**
 * 实时跟踪面板的纯函数辅助层（无 React、无 DOM，可直接单测）。
 *
 * 这里只做四类事：
 *   ① 从 A 的只读历史里取出**当前关节**的列，缺失值保留为 NaN（不填 0）；
 *   ② 统一运行段仿真时间轴 / 当前窗口范围；
 *   ③ 按窗口内的真实点计算纵轴范围（不外推、不插值）；
 *   ④ 二分查找附近的真实采样点与刻度格式。
 *
 * 注意：B 不维护第二份历史；`extractJointSeries` 只是把 props 重新排成画图用的列。
 */
import type { LiveTrackingSample } from "./types";

/** 缺失值。用 NaN 表示“这一列此处没有真实数据”，绘图时据此断线。 */
export const MISSING = Number.NaN;

export interface JointSeriesData {
  /** 与各列等长的仿真时间（秒），严格递增。 */
  times: Float64Array;
  position: Float64Array;
  reference: Float64Array;
  velocity: Float64Array;
  error: Float64Array;
  torque: Float64Array;
  /** `compensationTorqueNm` 为 null 或该关节为空时，整列为 NaN。 */
  compensation: Float64Array;
  /** 本运行段是否出现过至少一个真实补偿力矩值。 */
  hasCompensation: boolean;
}

const EMPTY = new Float64Array(0);

function emptySeriesData(): JointSeriesData {
  return {
    times: EMPTY,
    position: EMPTY,
    reference: EMPTY,
    velocity: EMPTY,
    error: EMPTY,
    torque: EMPTY,
    compensation: EMPTY,
    hasCompensation: false,
  };
}

/** 只接受有限数值；null、undefined、NaN、Infinity 一律视为缺失。 */
function vectorValue(vector: readonly (number | null)[] | null | undefined, index: number): number {
  if (!vector || index < 0 || index >= vector.length) return MISSING;
  const value = vector[index];
  return typeof value === "number" && Number.isFinite(value) ? value : MISSING;
}

/**
 * 取出某个关节在整段历史中的列。
 *
 * `fromS` 只用于裁掉窗口之外的旧点（A 的缓冲最长 120 秒，窗口最长 60 秒），
 * 不是另存历史；返回的每一列与 `times` 严格等长。
 */
export function extractJointSeries(
  samples: readonly LiveTrackingSample[],
  jointIndex: number,
  fromS = 0,
): JointSeriesData {
  if (jointIndex < 0 || samples.length === 0) return emptySeriesData();

  const minimumTime = Number.isFinite(fromS) && fromS > 0 ? fromS : 0;
  // A 的历史按 elapsedS 升序；窗口滑动后只分配窗口内的点，不每帧复制 120 秒全史。
  let startIndex = 0;
  if (minimumTime > 0) {
    let low = 0;
    let high = samples.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (samples[middle].elapsedS < minimumTime) low = middle + 1;
      else high = middle;
    }
    startIndex = low;
  }
  const capacity = samples.length - startIndex;
  if (capacity <= 0) return emptySeriesData();

  const times = new Float64Array(capacity);
  const position = new Float64Array(capacity);
  const reference = new Float64Array(capacity);
  const velocity = new Float64Array(capacity);
  const error = new Float64Array(capacity);
  const torque = new Float64Array(capacity);
  const compensation = new Float64Array(capacity);

  let count = 0;
  let previousTime = Number.NEGATIVE_INFINITY;
  let hasCompensation = false;

  for (let i = startIndex; i < samples.length; i += 1) {
    const sample = samples[i];
    const time = sample.elapsedS;
    // A 保证严格递增；这里对非有限、负数和重复时间做防御，避免画出回折/竖线。
    if (!Number.isFinite(time) || time < 0 || time <= previousTime || time < minimumTime) continue;

    const compensationValue = vectorValue(sample.compensationTorqueNm, jointIndex);
    times[count] = time;
    position[count] = vectorValue(sample.positionRad, jointIndex);
    reference[count] = vectorValue(sample.referenceRad, jointIndex);
    velocity[count] = vectorValue(sample.velocityRadS, jointIndex);
    error[count] = vectorValue(sample.errorRad, jointIndex);
    torque[count] = vectorValue(sample.actuatorTorqueNm, jointIndex);
    compensation[count] = compensationValue;
    if (Number.isFinite(compensationValue)) hasCompensation = true;

    previousTime = time;
    count += 1;
  }

  if (count === 0) return emptySeriesData();
  if (count === capacity) {
    return { times, position, reference, velocity, error, torque, compensation, hasCompensation };
  }
  return {
    times: times.subarray(0, count),
    position: position.subarray(0, count),
    reference: reference.subarray(0, count),
    velocity: velocity.subarray(0, count),
    error: error.subarray(0, count),
    torque: torque.subarray(0, count),
    compensation: compensation.subarray(0, count),
    hasCompensation,
  };
}

/** 最后一个有效采样时间；空历史返回 null。t=0 是有效时间，不能用真值判断。 */
export function lastFiniteSampleTime(samples: readonly LiveTrackingSample[]): number | null {
  for (let i = samples.length - 1; i >= 0; i -= 1) {
    const time = samples[i].elapsedS;
    if (Number.isFinite(time) && time >= 0) return time;
  }
  return null;
}

export interface TimeRange {
  startS: number;
  endS: number;
}

/**
 * 运行段仿真时间横轴。
 *
 * - 右端取 `max(窗口, elapsedS, 最新采样时间)`：窗口未满时固定显示 0..窗口，
 *   起步阶段不因每个新点缩放横轴；窗口满后跟随后端确认的 elapsedS。
 * - 左端 = 右端 − 窗口，且不小于 0。
 * - 不用墙钟推动；暂停时 `elapsedS` 不变，轴自然停住。
 */
export function computeTimeRange(
  lastSampleS: number | null,
  elapsedS: number,
  windowS: number,
): TimeRange {
  const safeWindow = Number.isFinite(windowS) && windowS > 0 ? windowS : 10;
  const safeElapsed = Number.isFinite(elapsedS) && elapsedS > 0 ? elapsedS : 0;
  const safeLast =
    lastSampleS !== null && Number.isFinite(lastSampleS) && lastSampleS > 0 ? lastSampleS : 0;
  const endS = Math.max(safeWindow, safeElapsed, safeLast);
  return { startS: Math.max(0, endS - safeWindow), endS };
}

/** 第一个 time >= value 的下标；都小于 value 时返回 length。 */
export function lowerBound(times: Float64Array, value: number): number {
  let low = 0;
  let high = times.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (times[middle] < value) low = middle + 1;
    else high = middle;
  }
  return low;
}

/** 第一个 time > value 的下标；都小于等于 value 时返回 length。 */
export function upperBound(times: Float64Array, value: number): number {
  let low = 0;
  let high = times.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (times[middle] <= value) low = middle + 1;
    else high = middle;
  }
  return low;
}

/** 离 target 最近的**真实**采样点下标；没有采样时返回 -1。 */
export function nearestIndex(times: Float64Array, target: number): number {
  if (times.length === 0 || !Number.isFinite(target)) return -1;
  const after = lowerBound(times, target);
  if (after <= 0) return 0;
  if (after >= times.length) return times.length - 1;
  const before = after - 1;
  return target - times[before] <= times[after] - target ? before : after;
}

/** 窗口内第一个采样点下标；窗口内没有点时返回 -1。 */
export function firstIndexInRange(times: Float64Array, range: TimeRange): number {
  const index = lowerBound(times, range.startS);
  return index < times.length && times[index] <= range.endS ? index : -1;
}

/** 窗口内最后一个采样点下标；窗口内没有点时返回 -1。 */
export function lastIndexInRange(times: Float64Array, range: TimeRange): number {
  const index = upperBound(times, range.endS) - 1;
  return index >= 0 && times[index] >= range.startS ? index : -1;
}

export interface ValueRange {
  min: number;
  max: number;
}

export interface ValueRangeOptions {
  /** 把 0 纳入纵轴（误差/力矩/速度看符号时需要）。 */
  includeZero?: boolean;
  /** 恒定值/单点时的最小纵轴跨度（显示单位）。 */
  minSpan?: number;
}

/**
 * 纵轴范围只由窗口内的真实有限值决定。
 * 恒定值或单点会围绕该值展开一个最小跨度，否则线会与网格线重合而看不见。
 */
export function computeValueRange(
  seriesColumns: readonly Float64Array[],
  times: Float64Array,
  range: TimeRange,
  scale: number,
  options: ValueRangeOptions = {},
): ValueRange | null {
  const first = lowerBound(times, range.startS);
  const last = upperBound(times, range.endS) - 1;
  if (first > last || times.length === 0) return null;

  const safeScale = Number.isFinite(scale) && scale !== 0 ? scale : 1;
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;
  let count = 0;

  for (const values of seriesColumns) {
    const available = Math.min(last, values.length - 1);
    for (let i = first; i <= available; i += 1) {
      const raw = values[i];
      if (!Number.isFinite(raw)) continue;
      const value = raw * safeScale;
      if (value < minimum) minimum = value;
      if (value > maximum) maximum = value;
      count += 1;
    }
  }
  if (count === 0) return null;

  if (options.includeZero) {
    minimum = Math.min(minimum, 0);
    maximum = Math.max(maximum, 0);
  }

  const minimumSpan =
    typeof options.minSpan === "number" && Number.isFinite(options.minSpan) && options.minSpan > 0
      ? options.minSpan
      : 1e-9;
  if (maximum - minimum < minimumSpan) {
    const middle = (minimum + maximum) / 2;
    minimum = middle - minimumSpan / 2;
    maximum = middle + minimumSpan / 2;
  }

  const padding = (maximum - minimum) * 0.08;
  return { min: minimum - padding, max: maximum + padding };
}

/** 时间刻度步长：按图上大约放 2–6 个标签选一个“好读”的秒数。 */
export function timeTickStep(spanS: number, pixelWidth: number): number {
  if (!Number.isFinite(spanS) || spanS <= 0) return 1;
  const target = Math.max(2, Math.min(6, Math.round(pixelWidth / 40)));
  const raw = spanS / target;
  const steps = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600];
  for (const step of steps) {
    if (step >= raw) return step;
  }
  return 600;
}

function trimTrailingZeros(text: string): string {
  if (!text.includes(".")) return text === "-0" ? "0" : text;
  const trimmed = text.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "" || trimmed === "-0" ? "0" : trimmed;
}

/** 时间刻度文字。 */
export function formatTimeTick(value: number, step: number): string {
  if (!Number.isFinite(value)) return "";
  if (step >= 1) return String(Math.round(value));
  const digits = step >= 0.1 ? 1 : step >= 0.01 ? 2 : 3;
  return trimTrailingZeros(value.toFixed(digits));
}

/** 纵轴刻度文字：按刻度间隔选小数位，恒定值被放大后也不会所有标签都相同。 */
export function formatAxisValue(value: number, span: number): string {
  if (!Number.isFinite(value)) return "";
  const step = Math.abs(span) / 4;
  const digits =
    step > 0 && Number.isFinite(step)
      ? Math.max(0, Math.min(8, Math.ceil(-Math.log10(step)) + 1))
      : 3;
  return trimTrailingZeros(value.toFixed(digits));
}

/** 状态栏 / 悬停时间（秒）。 */
export function formatSeconds(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return Math.abs(value) >= 100 ? value.toFixed(1) : value.toFixed(2);
}

/** 读数保留固定小数位；把 -0.00 归零，但绝不把缺失值变成 0。 */
export function formatFixed(value: number, digits: number): string {
  if (!Number.isFinite(value)) return "";
  const safeDigits = Math.max(0, Math.min(6, Math.round(digits)));
  const threshold = 0.5 * 10 ** -safeDigits;
  const safe = Math.abs(value) < threshold ? 0 : value;
  return safe.toFixed(safeDigits);
}

export function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
