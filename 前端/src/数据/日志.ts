/**
 * 日志.ts —— 控制台**真实**数据的唯一来源。
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
 * 文案走 `视图/文案.ts` 的 `取()`（`约定.md` §三：组件与日志都不硬编码中文）。
 */
import { useSyncExternalStore } from "react";
import { 后端, 取状态 } from "./仓库";
import type { 回执 } from "./连接";
import { 提示错误 } from "./提示";
import { 取 } from "../视图/文案";

export type 日志等级 = "信息" | "注意" | "错误";
export type 日志来源 = "连接" | "握手" | "回执" | "错误" | "前端" | "控制台" | "规划" | "诊断";

export interface 日志行 {
  序号: number;
  墙钟: number;
  等级: 日志等级;
  来源: 日志来源;
  /** 主题名（有则显示，便于对账） */
  主题?: string;
  文本: string;
  /** 附加说明（多行/长文），展开时看 */
  细节?: string;
  /** 结构化字段：只在来源**真的知道**时填，不靠字符串猜 */
  模块?: string;
  插件?: string;
  关节?: number;
}

/** 结构化事件上下文：能填才填，不是每条日志都有 */
export interface 结构字段 {
  模块?: string;
  插件?: string;
  关节?: number;
}

/** 速率表的一行（每个主题一行，每秒刷新） */
export interface 速率行 {
  主题: string;
  /** 累计帧数（连接层数的） */
  计数: number;
  /** 最近一秒收到几帧（计数差值，**实测**不是估算） */
  速率: number;
  /** 最近一帧是多少毫秒之前；`Infinity` = 从来没收到过 */
  年龄: number;
}

export interface 日志快照 {
  行: 日志行[];
  /** 每秒刷新的主题速率表；**只列真实出现过的主题**，不预先摊开契约名单 */
  速率: 速率行[];
  /** 已连接那一刻的墙钟（毫秒）；没连过是 0 → 状态栏显示 "--" 而不是编个数 */
  连接起始: number;
  /** 发出去的命令条数（含回执失败的） */
  命令数: number;
}

const 容量 = 1000;

let 行: 日志行[] = [];
let 速率: 速率行[] = [];
let 连接起始 = 0;
let 命令数 = 0;
let 下一个序号 = 1;
let 版本 = 0;
/** 每个主题最近一帧的墙钟（毫秒）—— 用来算"多少秒前有帧" */
const 最近帧 = new Map<string, number>();

const 订阅者 = new Set<() => void>();

/**
 * 合并同一轮事件循环里的多次写入：高频日志/连续回执只触发一次 React 外订阅回调，
 * 避免每条日志都让控制台整页重渲染。版本号仍逐条递增，快照不会丢行。
 */
let 待通知 = false;
function 通知(): void {
  版本 += 1;
  if (待通知) return;
  待通知 = true;
  queueMicrotask(() => {
    待通知 = false;
    for (const f of 订阅者) f();
  });
}

let 缓存: 日志快照 = { 行: [], 速率: [], 连接起始: 0, 命令数: 0 };

export function 取日志(): 日志快照 {
  if (缓存.行 !== 行 || 缓存.速率 !== 速率 || 缓存.连接起始 !== 连接起始 || 缓存.命令数 !== 命令数) {
    缓存 = { 行, 速率, 连接起始, 命令数 };
  }
  return 缓存;
}

/** 订阅日志（快照按引用比较，没变就不会白重画） */
/** 把一行日志转成原生面板能直接渲染的字段。 */
function 原生行(l: 日志行): Record<string, unknown> {
  return {
    墙钟: l.墙钟,
    等级: l.等级,
    来源: l.来源,
    文本: l.文本,
    细节: l.细节 ?? "",
    模块: l.模块 ?? "",
    插件: l.插件 ?? "",
    关节: l.关节 ?? null,
  };
}

function 发原生(内容: Record<string, unknown>): void {
  try {
    const w = window as unknown as {
      webkit?: { messageHandlers?: { 驭臂日志?: { postMessage?: (x: unknown) => void } } };
    };
    w.webkit?.messageHandlers?.驭臂日志?.postMessage?.(内容);
  } catch {
    /* 镜像失败不影响 Web 控制台 */
  }
}

/** 把单行日志镜像给原生宿主（有 WKWebView 的 messageHandler 时才发；浏览器里是 no-op）。 */
function 送原生(l: 日志行): void {
  发原生(原生行(l));
}

/** 把**当前主日志的完整筛选结果**发给原生面板；面板的计数/筛选/清空都以它为准。 */
export function 送原生状态(
  行: 日志行[],
  总数: number,
  筛选: string,
  等级: 日志等级 | "全部",
): void {
  发原生({
    类型: "日志状态",
    行: 行.slice(-500).map(原生行),
    总数,
    筛选,
    等级,
  });
}

export function 用日志(): 日志快照 {
  return useSyncExternalStore(
    (回调) => {
      订阅者.add(回调);
      return () => 订阅者.delete(回调);
    },
    取日志,
    取日志,
  );
}

function 记(等级: 日志等级, 来源: 日志来源, 文本: string, 主题?: string, 细节?: string,
           结构?: 结构字段): void {
  const 新: 日志行 = {
    序号: 下一个序号++,
    墙钟: Date.now(),
    等级,
    来源,
    主题,
    文本,
    细节,
    模块: 结构?.模块,
    插件: 结构?.插件,
    关节: 结构?.关节,
  };
  行 = 行.length >= 容量 ? [...行.slice(行.length - 容量 + 1), 新] : [...行, 新];
  送原生(新);
  通知();
}

/** 给界面用的三个便捷入口 */
export function 记信息(来源: 日志来源, 文本: string, 主题?: string): void {
  记("信息", 来源, 文本, 主题);
}

export function 记注意(来源: 日志来源, 文本: string, 主题?: string, 细节?: string): void {
  记("注意", 来源, 文本, 主题, 细节);
}

export function 记错误(来源: 日志来源, 文本: string, 主题?: string, 细节?: string): void {
  记("错误", 来源, 文本, 主题, 细节);
}

/** 带结构化字段的事件（插件/关节/模块）；没有字段时退化为普通日志 */
export function 记结构化(
  等级: 日志等级,
  来源: 日志来源,
  文本: string,
  结构: 结构字段,
  主题?: string,
  细节?: string,
): void {
  记(等级, 来源, 文本, 主题, 细节, 结构);
}

/**
 * 记录一次命令发出的时刻；`命令收尾` 用返回值算出耗时（毫秒）。
 * 命令的成败**只以回执为准**，这里只负责计时。
 */
export function 记命令发出(): number {
  命令数 += 1;
  通知();
  return Date.now();
}

/**
 * 命令回执的统一落点：写日志 + （失败时）弹提示。
 * 所有视图里的 `await 命令.xxx()` 都必须过这一道 —— 见 `约定.md` §二。
 */
export function 命令收尾(
  主题: string,
  回执: 回执,
  起于: number,
  结构?: 结构字段,
): 回执 {
  const 耗时 = Date.now() - 起于;
  if (回执.通过) {
    记("信息", "回执", 取("日志.回执通过", { 主题, 耗时 }), 主题, 回执.说明 || undefined, 结构);
  } else {
    // 失败必须"两个出口都亮"：控制台留痕 + 右下角顶一条提示。
    const 说明 = 回执.说明 || 取("日志.无说明");
    记("错误", "回执", 取("日志.回执失败", { 主题, 说明 }), 主题, 取("日志.耗时", { 值: 耗时 }), 结构);
    提示错误(取("提示.命令失败", { 主题 }), 说明);
  }
  return 回执;
}

/** 只订阅"连接起始时刻"（状态栏用；别让它因为日志行每秒变化而重画） */
export function 用连接起始(): number {
  return useSyncExternalStore(
    (回调) => {
      订阅者.add(回调);
      return () => 订阅者.delete(回调);
    },
    () => 连接起始,
    () => 连接起始,
  );
}

/** 清空显示（**只清界面**：连接与命令的历史仍在后端，这一点在界面上也写明） */
export function 清日志(): void {
  if (!行.length) return;
  行 = [];
  通知();
}

/** 供 `问题` 页签用：把一行日志当成一条问题（只有 注意/错误 才算问题） */
export function 是问题(行: 日志行): boolean {
  return 行.等级 === "错误" || 行.等级 === "注意";
}

let 起动 = false;
let 卸载: (() => void) | null = null;

/**
 * 起日志 —— 在 App 的 `useEffect` 里调一次。
 * 返回的清理函数会摘掉所有监听（含全局 onerror），不留悬挂引用。
 */
export function 起日志(): () => void {
  if (起动) return 卸载 ?? (() => {});
  起动 = true;

  记("信息", "控制台", 取("日志.启动"));

  let 上次规划事件 = "";
  let 上次诊断事件 = "";

  const 取消订阅 = 后端.订阅((e) => {
    if (e.状态) {
      if (e.状态 === "已连接") {
        连接起始 = Date.now();
        记("信息", "连接", 取("日志.已连接"));
      } else if (e.状态 === "已断开") {
        记("注意", "连接", 取("日志.已断开"));
      } else {
        记("信息", "连接", 取("日志.连接中"));
      }
    }
    if (e.握手) {
      const 主题数 = e.握手.可用主题?.length ?? 0;
      const 契约版本 = e.握手.契约?.版本;
      记(
        "信息",
        "握手",
        取("日志.握手", {
          主题数,
          间隔: e.握手.广播间隔,
          契约: 契约版本 === undefined ? "" : 取("日志.握手契约", { 版本: 契约版本 }),
        }),
        "__问候__",
        e.握手.可用主题?.join(" · "),
      );
    }
    if (e.回执) {
      记(
        e.回执.通过 ? "信息" : "错误",
        "回执",
        e.回执.通过
          ? 取("日志.回执简单通过", { 主题: e.回执.主题 })
          : 取("日志.回执失败", { 主题: e.回执.主题, 说明: e.回执.说明 || 取("日志.无说明") }),
        e.回执.主题,
        e.回执.说明 || undefined,
      );
    }
    if (e.错误) {
      记("错误", "错误", e.错误, undefined, 取("日志.后端错误细节"));
    }
    if (e.帧?.主题) {
      最近帧.set(e.帧.主题, Date.now());
      const 数据 = (e.帧.数据 ?? {}) as Record<string, unknown>;
      const 串 = (v: unknown) => (typeof v === "string" ? v : "");
      const 数 = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

      // 规划结果里的真实关节信息：失败 / 估算限位时产生一条结构化事件。
      // 这不是"解析日志猜关节"，而是直接读后端规划结果的 `瓶颈关节`。
      if (e.帧.主题 === "规划结果") {
        const 状态 = 串(数据.状态);
        const 原因 = 串(数据.原因);
        const 限位 = 串(数据.限位来源);
        const 关节 = 数(数据.瓶颈关节);
        const 失败 = 状态.includes("✗");
        const 估算 = 限位.includes("估算");
        if (失败 || 估算) {
          const 签名 = [状态, 数据.时间, 原因, 关节, 限位].join("|");
          if (签名 !== 上次规划事件) {
            上次规划事件 = 签名;
            const 关节文本 = 关节 !== undefined && 关节 >= 0 ? `J${关节}` : 取("通用.无");
            const 文本 = 失败
              ? 取("日志.规划失败", { 原因: 原因 || 取("日志.无说明") })
              : 取("日志.规划估算", { 来源: 限位, 关节: 关节文本 });
            记结构化(
              失败 ? "错误" : "注意",
              "规划",
              文本,
              { 模块: "规划", 关节: 关节 !== undefined && 关节 >= 0 ? 关节 : undefined },
              "规划结果",
              失败 ? 原因 || undefined : 限位 || undefined,
            );
          }
        } else {
          上次规划事件 = "";
        }
      }

      // 诊断报告里的失败项：同样来自真实报告，不解析自由文本。
      if (e.帧.主题 === "诊断") {
        const 项们 = Array.isArray(数据.项) ? (数据.项 as Record<string, unknown>[]) : [];
        const 失败项 = 项们.filter((x) => x && x.通过 === false);
        const 出错 = 串(数据.出错);
        if (失败项.length || 出错) {
          const 签名 = [数据.时间, 数据.通过, 数据.总数, 失败项.map((x) => 串(x.名)).join(","), 出错].join("|");
          if (签名 !== 上次诊断事件) {
            上次诊断事件 = 签名;
            const 文本 = 出错
              ? 取("日志.诊断出错", { 说明: 出错 })
              : 取("日志.诊断未通过", { 通过: 数(数据.通过) ?? 0, 总数: 数(数据.总数) ?? 0 });
            记结构化(
              "错误",
              "诊断",
              文本,
              { 模块: "诊断" },
              "诊断",
              失败项.length ? 失败项.map((x) => 串(x.名)).filter(Boolean).join(" · ") || undefined : undefined,
            );
          }
        }
      }
    }
  });

  // 每秒把连接层的计数/速率搬进来（**只有真的收过帧的主题才在表里**）
  const 心跳 = window.setInterval(() => {
    const s = 取状态();
    const 名 = Object.keys(s.主题计数).sort();
    const 现在 = Date.now();
    速率 = 名.map((主题) => {
      const 末 = 最近帧.get(主题);
      return {
        主题,
        计数: s.主题计数[主题] ?? 0,
        速率: s.主题速率[主题] ?? 0,
        年龄: 末 === undefined ? Number.POSITIVE_INFINITY : 现在 - 末,
      };
    });
    通知();
  }, 1000);

  // 前端自己的异常也要进控制台，否则"界面白屏"在日志里查不到
  const 捕异常 = (事件: ErrorEvent) => {
    记(
      "错误",
      "前端",
      取("日志.未捕获", { 信息: 事件.message || 取("日志.无信息") }),
      undefined,
      [事件.filename, 事件.lineno ? 取("日志.行号", { 值: 事件.lineno }) : ""].filter(Boolean).join(" ") ||
        undefined,
    );
  };
  const 捕拒绝 = (事件: PromiseRejectionEvent) => {
    记("错误", "前端", 取("日志.未处理拒绝", { 原因: String(事件.reason) }));
  };
  window.addEventListener("error", 捕异常);
  window.addEventListener("unhandledrejection", 捕拒绝);

  卸载 = () => {
    取消订阅();
    window.clearInterval(心跳);
    window.removeEventListener("error", 捕异常);
    window.removeEventListener("unhandledrejection", 捕拒绝);
    起动 = false;
    卸载 = null;
  };
  return 卸载;
}
