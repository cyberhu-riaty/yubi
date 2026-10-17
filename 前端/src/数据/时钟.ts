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

const 订阅者 = new Set<() => void>();
let 定时器: number | null = null;
let 最近 = Date.now();

function 起步(): void {
  if (定时器 !== null) return;
  定时器 = window.setInterval(() => {
    最近 = Date.now();
    for (const f of 订阅者) f();
  }, 1000);
}

function 停步(): void {
  if (定时器 === null) return;
  window.clearInterval(定时器);
  定时器 = null;
}

/** 订阅 1 Hz 节拍，返回当前毫秒时间戳（每秒变一次，可直接进依赖） */
export function 用节拍(): number {
  return useSyncExternalStore(
    (回调) => {
      订阅者.add(回调);
      起步();
      return () => {
        订阅者.delete(回调);
        if (!订阅者.size) 停步();
      };
    },
    () => 最近,
    () => 最近,
  );
}
