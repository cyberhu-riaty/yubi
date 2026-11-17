import { encodeNativeLog, encodeNativeLogState, postNativeLog } from "./wire_compatibility";
/**
 * logs.ts —— 控制台**真实**数据的唯一来源。
 *
 * 这个文件的存在理由很直白：控制台里不许有一行硬编码的假日志。
 * 所以每一行都必须由某个**真的发生过**的事件产生，来源只有六个：
 *   ① 连接状态变化（连接中 / 已连接 / 已断开）
 *   ② 握手（可用主题、广播间隔、契约版本）—— 数据链路打通的第一手证据
 *   ③ 回执（`回执`）—— 命令是与否，逐条留痕
 *   ④ 后端错误（协议版本不一致、非 JSON 消息…）
 *   ⑤ 前端自身异常（window.onerror / unhandledrejection）
 *   ⑥ 界面自己记的一条（比如"按了换模型但路径是空的"）—— 也算真事
 * 另外挂一张**主题速率表**（每秒实测计数差值 + 最近一帧多大年纪），
 * 它是"哪条链路没通"的直接答案。
 *
 * ⚠️ 这里绝不"造"日志：没有事件就没有行；控制台空着本身就是一条信息。
 *
 * 文案走 `视图/i18n.ts` 的 `取()`（`CONVENTIONS.md` §三：组件与日志都不硬编码中文）。
 */
import { useSyncExternalStore } from "react";
import { backend, getState } from "./store";
import type { CommandReceipt } from "./connection";
import { showError } from "./toasts";
import { translate } from "../views/i18n";

export type LogLevel = "info" | "warning" | "error";
export type LogSource = "connection" | "handshake" | "receipt" | "error" | "frontend" | "console" | "planning" | "diagnostics";

export interface LogRow {
  id: number;
  timestamp: number;
  level: LogLevel;
  source: LogSource;
  /** 主题名（有则显示，便于对账） */
  topic?: string;
  text: string;
  /** 附加说明（多行/长文），展开时看 */
  details?: string;
  /** 结构化字段：只在来源**真的知道**时填，不靠字符串猜 */
  module?: string;
  plugins?: string;
  joint?: number;
}

/** 结构化事件上下文：能填才填，不是每条日志都有 */
export interface LogContext {
  module?: string;
  plugins?: string;
  joint?: number;
}

/** 速率表的一行（每个主题一行，每秒刷新） */
export interface TopicRateRow {
  topic: string;
  /** 累计帧数（连接层数的） */
  count: number;
  /** 最近一秒收到几帧（计数差值，**实测**不是估算） */
  rate: number;
  /** 最近一帧是多少毫秒之前；`Infinity` = 从来没收到过 */
  age: number;
}

export interface LogSnapshot {
  row: LogRow[];
  /** 每秒刷新的主题速率表；**只列真实出现过的主题**，不预先摊开契约名单 */
  rate: TopicRateRow[];
  /** 已连接那一刻的墙钟（毫秒）；没连过是 0 → 状态栏显示 "--" 而不是编个数 */
  connectionStart: number;
  /** 发出去的命令条数（含回执失败的） */
  commandCount: number;
}

const CAPACITY = 1000;

let row: LogRow[] = [];
let rate: TopicRateRow[] = [];
let connectionStart = 0;
let commandCount = 0;
let nextId = 1;
let version = 0;
/** 每个主题最近一帧的墙钟（毫秒）—— 用来算"多少秒前有帧" */
const latestFrames = new Map<string, number>();

const subscribers = new Set<() => void>();

/**
 * 合并同一轮事件循环里的多次写入：高频日志/连续回执只触发一次 React 外订阅回调，
 * 避免每条日志都让控制台整页重渲染。版本号仍逐条递增，快照不会丢行。
 */
let notificationPending = false;
function notify(): void {
  version += 1;
  if (notificationPending) return;
  notificationPending = true;
  queueMicrotask(() => {
    notificationPending = false;
    for (const f of subscribers) f();
  });
}

let cache: LogSnapshot = { row: [], rate: [], connectionStart: 0, commandCount: 0 };

export function getLogs(): LogSnapshot {
  if (cache.row !== row || cache.rate !== rate || cache.connectionStart !== connectionStart || cache.commandCount !== commandCount) {
    cache = { row: row, rate: rate, connectionStart: connectionStart, commandCount: commandCount };
  }
  return cache;
}

/** 订阅日志（快照按引用比较，没变就不会白重画） */
/** 把一行日志转成原生面板能直接渲染的字段。 */
function sendNative(entry: LogRow): void {
  postNativeLog(encodeNativeLog(entry));
}

export function sendNativeState(entries: LogRow[], total: number, filter: string, level: LogLevel | "全部"): void {
  postNativeLog(encodeNativeLogState(entries, total, filter, level));
}

export function useLogs(): LogSnapshot {
  return useSyncExternalStore(
    (callback) => {
      subscribers.add(callback);
      return () => subscribers.delete(callback);
    },
    getLogs,
    getLogs,
  );
}

function appendLog(level: LogLevel, source: LogSource, text: string, topic?: string, details?: string,
           context?: LogContext): void {
  const updated: LogRow = {
    id: nextId++,
    timestamp: Date.now(),
    level: level,
    source: source,
    topic: topic,
    text: text,
    details: details,
    module: context?.module,
    plugins: context?.plugins,
    joint: context?.joint,
  };
  row = row.length >= CAPACITY ? [...row.slice(row.length - CAPACITY + 1), updated] : [...row, updated];
  sendNative(updated);
  notify();
}

/** 给界面用的三个便捷入口 */
export function logInfo(source: LogSource, text: string, topic?: string): void {
  appendLog("info", source, text, topic);
}

export function logWarning(source: LogSource, text: string, topic?: string, details?: string): void {
  appendLog("warning", source, text, topic, details);
}

export function logError(source: LogSource, text: string, topic?: string, details?: string): void {
  appendLog("error", source, text, topic, details);
}

/** 带结构化字段的事件（插件/关节/模块）；没有字段时退化为普通日志 */
export function logStructured(
  level: LogLevel,
  source: LogSource,
  text: string,
  context: LogContext,
  topic?: string,
  details?: string,
): void {
  appendLog(level, source, text, topic, details, context);
}

/**
 * 记录一次命令发出的时刻；`命令收尾` 用返回值算出耗时（毫秒）。
 * 命令的成败**只以回执为准**，这里只负责计时。
 */
export function recordCommandStart(): number {
  commandCount += 1;
  notify();
  return Date.now();
}

/**
 * 命令回执的统一落点：写日志 + （失败时）弹提示。
 * 所有视图里的 `await 命令.xxx()` 都必须过这一道 —— 见 `CONVENTIONS.md` §二。
 */
export function finishCommand(
  topic: string,
  receipt: CommandReceipt,
  startedAt: number,
  context?: LogContext,
): CommandReceipt {
  const elapsedMs = Date.now() - startedAt;
  if (receipt.passed) {
    appendLog("info", "receipt", translate("日志.回执通过", { topic: topic, elapsed: elapsedMs }), topic, receipt.description || undefined, context);
  } else {
    // 失败必须"两个出口都亮"：控制台留痕 + 右下角顶一条提示。
    const description = receipt.description || translate("日志.无说明");
    appendLog("error", "receipt", translate("日志.回执失败", { topic: topic, description: description }), topic, translate("日志.耗时", { value: elapsedMs }), context);
    showError(translate("提示.命令失败", { topic: topic }), description);
  }
  return receipt;
}

/** 只订阅"连接起始时刻"（状态栏用；别让它因为日志行每秒变化而重画） */
export function useConnectionStart(): number {
  return useSyncExternalStore(
    (callback) => {
      subscribers.add(callback);
      return () => subscribers.delete(callback);
    },
    () => connectionStart,
    () => connectionStart,
  );
}

/** 清空显示（**只清界面**：连接与命令的历史仍在后端，这一点在界面上也写明） */
export function clearLogs(): void {
  if (!row.length) return;
  row = [];
  notify();
}

/** 供 `问题` 页签用：把一行日志当成一条问题（只有 注意/错误 才算问题） */
export function isProblem(row: LogRow): boolean {
  return row.level === "error" || row.level === "warning";
}

let started = false;
let cleanup: (() => void) | null = null;

/**
 * 起日志 —— 在 App 的 `useEffect` 里调一次。
 * 返回的清理函数会摘掉所有监听（含全局 onerror），不留悬挂引用。
 */
export function startLogging(): () => void {
  if (started) return cleanup ?? (() => {});
  started = true;

  appendLog("info", "console", translate("日志.启动"));

  let lastPlanningEvent = "";
  let lastDiagnosticEvent = "";

  const unsubscribe = backend.subscribe((e) => {
    if (e.state) {
      if (e.state === "connected") {
        connectionStart = Date.now();
        appendLog("info", "connection", translate("日志.已连接"));
      } else if (e.state === "disconnected") {
        appendLog("warning", "connection", translate("日志.已断开"));
      } else {
        appendLog("info", "connection", translate("日志.连接中"));
      }
    }
    if (e.handshake) {
      const topicCount = e.handshake.available_topics?.length ?? 0;
      const contractVersion = e.handshake.contract?.version;
      appendLog(
        "info",
        "handshake",
        translate("日志.握手", {
          topicCount: topicCount,
          interval: e.handshake.broadcast_interval,
          contract: contractVersion === undefined ? "" : translate("日志.握手契约", { version: contractVersion }),
        }),
        "__问候__",
        e.handshake.available_topics?.join(" · "),
      );
    }
    if (e.receipt) {
      appendLog(
        e.receipt.passed ? "info" : "error",
        "receipt",
        e.receipt.passed
          ? translate("日志.回执简单通过", { topic: e.receipt.topic })
          : translate("日志.回执失败", { topic: e.receipt.topic, description: e.receipt.description || translate("日志.无说明") }),
        e.receipt.topic,
        e.receipt.description || undefined,
      );
    }
    if (e.error) {
      appendLog("error", "error", e.error, undefined, translate("日志.后端错误细节"));
    }
    if (e.frame?.topic) {
      latestFrames.set(e.frame.topic, Date.now());
      const data = (e.frame.data ?? {}) as Record<string, unknown>;
      const asString = (v: unknown) => (typeof v === "string" ? v : "");
      const asNumber = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

      // 规划结果里的真实关节信息：失败 / 估算限位时产生一条结构化事件。
      // 这不是"解析日志猜关节"，而是直接读后端规划结果的 `瓶颈关节`。
      if (e.frame.topic === "planning.result") {
        const state = asString(data.status);
        const reason = asString(data.reason);
        const limit = asString(data.limit_source);
        const joint = asNumber(data.bottleneck_joint);
        const failed = state === "failed";
        const estimated = limit.includes("估算");
        if (failed || estimated) {
          const signature = [state, data.timestamp, reason, joint, limit].join("|");
          if (signature !== lastPlanningEvent) {
            lastPlanningEvent = signature;
            const jointLabel = joint !== undefined && joint >= 0 ? `J${joint}` : translate("通用.无");
            const text = failed
              ? translate("日志.规划失败", { reason: reason || translate("日志.无说明") })
              : translate("日志.规划估算", { source: limit, joint: jointLabel });
            logStructured(
              failed ? "error" : "warning",
              "planning",
              text,
              { module: "规划", joint: joint !== undefined && joint >= 0 ? joint : undefined },
              "planning.result",
              failed ? reason || undefined : limit || undefined,
            );
          }
        } else {
          lastPlanningEvent = "";
        }
      }

      // 诊断报告里的失败项：同样来自真实报告，不解析自由文本。
      if (e.frame.topic === "诊断") {
        const items = Array.isArray(data.items) ? (data.items as Record<string, unknown>[]) : [];
        const failures = items.filter((x) => x && x.passed === false);
        const error = asString(data.errors);
        if (failures.length || error) {
          const signature = [data.time, data.passed, data.total, failures.map((x) => asString(x.name)).join(","), error].join("|");
          if (signature !== lastDiagnosticEvent) {
            lastDiagnosticEvent = signature;
            const text = error
              ? translate("日志.诊断出错", { description: error })
              : translate("日志.诊断未通过", { passed: asNumber(data.passed) ?? 0, total: asNumber(data.total) ?? 0 });
            logStructured(
              "error",
              "diagnostics",
              text,
              { module: "诊断" },
              "诊断",
              failures.length ? failures.map((x) => asString(x.name)).filter(Boolean).join(" · ") || undefined : undefined,
            );
          }
        }
      }
    }
  });

  // 每秒把连接层的计数/速率搬进来（**只有真的收过帧的主题才在表里**）
  const heartbeat = window.setInterval(() => {
    const s = getState();
    const name = Object.keys(s.topicCounts).sort();
    const now = Date.now();
    rate = name.map((topic): TopicRateRow => {
      const last = latestFrames.get(topic);
      return {
        topic: topic,
        count: s.topicCounts[topic] ?? 0,
        rate: s.topicRates[topic] ?? 0,
        age: last === undefined ? Number.POSITIVE_INFINITY : now - last,
      };
    });
    notify();
  }, 1000);

  // 前端自己的异常也要进控制台，否则"界面白屏"在日志里查不到
  const handleError = (event: ErrorEvent) => {
    appendLog(
      "error",
      "frontend",
      translate("日志.未捕获", { message: event.message || translate("日志.无信息") }),
      undefined,
      [event.filename, event.lineno ? translate("日志.行号", { value: event.lineno }) : ""].filter(Boolean).join(" ") ||
        undefined,
    );
  };
  const handleRejection = (event: PromiseRejectionEvent) => {
    appendLog("error", "frontend", translate("日志.未处理拒绝", { reason: String(event.reason) }));
  };
  window.addEventListener("error", handleError);
  window.addEventListener("unhandledrejection", handleRejection);

  cleanup = () => {
    unsubscribe();
    window.clearInterval(heartbeat);
    window.removeEventListener("error", handleError);
    window.removeEventListener("unhandledrejection", handleRejection);
    started = false;
    cleanup = null;
  };
  return cleanup;
}
