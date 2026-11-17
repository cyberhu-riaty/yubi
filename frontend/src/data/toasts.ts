/**
 * 提示.ts —— 右下角的短提示（toast）。
 *
 * 只干一件事：把"命令失败"这类**必须让用户立刻看到**的事顶到脸上。
 * 成功不弹（那是噪音），失败弹 —— 与 `CONVENTIONS.md` §二 的"不要发了就算成功"配套。
 *
 * 不依赖任何 UI 库；自动消失的定时器在移除时清掉，不留悬挂。
 */
import { useSyncExternalStore } from "react";

export type ToastKind = "信息" | "注意" | "错误";

export interface Toast {
  id: number;
  kind: ToastKind;
  text: string;
  details?: string;
}

export interface ToastSnapshot {
  items: Toast[];
  /** 最后一条被顶掉的提示的序号 —— 供外部做"轻提示"去重时参考 */
  lastId: number;
}

/** 每条提示自动消失的时间（毫秒） */
const TOAST_LIFETIME_MS = 6000;
/** 同时最多显示几条 */
const MAX_TOASTS = 4;

let items: Toast[] = [];
let version = 0;
let nextId = 1;

const subscribers = new Set<() => void>();
const timers = new Map<number, number>();

function notify(): void {
  version += 1;
  updateSnapshot();
  for (const f of subscribers) f();
}

/**
 * 快照必须**按引用稳定**：`useSyncExternalStore` 每次渲染都会调 `取提示()`，
 * 如果每次都返回新对象，React 会判定"store 一直在变" → 无限重画
 * （实测报错：`The result of getSnapshot should be cached` +
 *  `Maximum update depth exceeded`，整个界面白屏）。
 * 所以这里把快照缓存在模块级，只在真的变了的时候换一个新对象。
 */
let snapshot: ToastSnapshot = { items: [], lastId: 0 };

function updateSnapshot(): void {
  snapshot = { items: items, lastId: nextId - 1 };
}

export function getToasts(): ToastSnapshot {
  return snapshot;
}

export function useToasts(): ToastSnapshot {
  return useSyncExternalStore(
    (callback) => {
      subscribers.add(callback);
      return () => subscribers.delete(callback);
    },
    () => getToasts(),
    () => getToasts(),
  );
}

function addToast(kind: ToastKind, text: string, details?: string): void {
  const id = nextId++;
  const next: Toast = { id: id, kind: kind, text: text, details: details };
  const queue = [...items, next];
  items = queue.length > MAX_TOASTS ? queue.slice(queue.length - MAX_TOASTS) : queue;
  timers.set(
    id,
    window.setTimeout(() => dismissToast(id), TOAST_LIFETIME_MS),
  );
  notify();
}

export function dismissToast(id: number): void {
  const t = timers.get(id);
  if (t !== undefined) {
    window.clearTimeout(t);
    timers.delete(id);
  }
  const next = items.filter((x) => x.id !== id);
  if (next.length === items.length) return;
  items = next;
  notify();
}

export function showSuccess(text: string, details?: string): void {
  addToast("信息", text, details);
}

export function showWarning(text: string, details?: string): void {
  addToast("注意", text, details);
}

/** 命令失败走这条 —— 与日志里的"错误"行是同一次事实的两个出口 */
export function showError(text: string, details?: string): void {
  addToast("错误", text, details);
}
