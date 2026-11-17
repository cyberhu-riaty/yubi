/**
 * 时钟.ts —— 一个全局 1 Hz 节拍（给"墙上时间"这类显示用）。
 *
 * 为什么需要它：状态栏的"仿真时间 = 已经跑了多久"、空曲线图的横轴，
 * 都要在没有新帧的时候照样走字。**不伪造任何数据** —— 它只提供 `Date.now()`，
 * 谁要用谁自己减起点。
 *
 * 全局只开一个定时器（不是每个组件一个），组件用 `用节拍()` 订阅。
 */
import { useSyncExternalStore } from "react";

const subscribers = new Set<() => void>();
let timers: number | null = null;
let latest = Date.now();

function startTicker(): void {
  if (timers !== null) return;
  timers = window.setInterval(() => {
    latest = Date.now();
    for (const f of subscribers) f();
  }, 1000);
}

function stopTicker(): void {
  if (timers === null) return;
  window.clearInterval(timers);
  timers = null;
}

/** 订阅 1 Hz 节拍，返回当前毫秒时间戳（每秒变一次，可直接进依赖） */
export function useClock(): number {
  return useSyncExternalStore(
    (callback) => {
      subscribers.add(callback);
      startTicker();
      return () => {
        subscribers.delete(callback);
        if (!subscribers.size) stopTicker();
      };
    },
    () => latest,
    () => latest,
  );
}
