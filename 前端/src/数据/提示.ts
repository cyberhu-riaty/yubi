/**
 * 提示.ts —— 右下角的短提示（toast）。
 *
 * 只干一件事：把"命令失败"这类**必须让用户立刻看到**的事顶到脸上。
 * 成功不弹（那是噪音），失败弹 —— 与 `约定.md` §二 的"不要发了就算成功"配套。
 *
 * 不依赖任何 UI 库；自动消失的定时器在移除时清掉，不留悬挂。
 */
import { useSyncExternalStore } from "react";

export type 提示种类 = "信息" | "注意" | "错误";

export interface 提示条 {
  序号: number;
  种类: 提示种类;
  文本: string;
  细节?: string;
}

export interface 提示快照 {
  条: 提示条[];
  /** 最后一条被顶掉的提示的序号 —— 供外部做"轻提示"去重时参考 */
  末条: number;
}

/** 每条提示自动消失的时间（毫秒） */
const 寿命 = 6000;
/** 同时最多显示几条 */
const 上限 = 4;

let 条: 提示条[] = [];
let 版本 = 0;
let 下一个序号 = 1;

const 订阅者 = new Set<() => void>();
const 定时器 = new Map<number, number>();

function 通知(): void {
  版本 += 1;
  通知缓存();
  for (const f of 订阅者) f();
}

/**
 * 快照必须**按引用稳定**：`useSyncExternalStore` 每次渲染都会调 `取提示()`，
 * 如果每次都返回新对象，React 会判定"store 一直在变" → 无限重画
 * （实测报错：`The result of getSnapshot should be cached` +
 *  `Maximum update depth exceeded`，整个界面白屏）。
 * 所以这里把快照缓存在模块级，只在真的变了的时候换一个新对象。
 */
let 缓存: 提示快照 = { 条: [], 末条: 0 };

function 通知缓存(): void {
  缓存 = { 条, 末条: 下一个序号 - 1 };
}

export function 取提示(): 提示快照 {
  return 缓存;
}

export function 用提示(): 提示快照 {
  return useSyncExternalStore(
    (回调) => {
      订阅者.add(回调);
      return () => 订阅者.delete(回调);
    },
    () => 取提示(),
    () => 取提示(),
  );
}

function 加(种类: 提示种类, 文本: string, 细节?: string): void {
  const 序号 = 下一个序号++;
  const 新: 提示条 = { 序号, 种类, 文本, 细节 };
  const 排 = [...条, 新];
  条 = 排.length > 上限 ? 排.slice(排.length - 上限) : 排;
  定时器.set(
    序号,
    window.setTimeout(() => 移除(序号), 寿命),
  );
  通知();
}

export function 移除(序号: number): void {
  const t = 定时器.get(序号);
  if (t !== undefined) {
    window.clearTimeout(t);
    定时器.delete(序号);
  }
  const 新 = 条.filter((x) => x.序号 !== 序号);
  if (新.length === 条.length) return;
  条 = 新;
  通知();
}

export function 提示成功(文本: string, 细节?: string): void {
  加("信息", 文本, 细节);
}

export function 提示注意(文本: string, 细节?: string): void {
  加("注意", 文本, 细节);
}

/** 命令失败走这条 —— 与日志里的"错误"行是同一次事实的两个出口 */
export function 提示错误(文本: string, 细节?: string): void {
  加("错误", 文本, 细节);
}
