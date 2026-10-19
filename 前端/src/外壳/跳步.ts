/**
 * 跳步.ts —— 视图内部请求"切到另一个任务流步骤"的最小通道。
 *
 * 为什么不用 prop 层层传 `on选步`：视图只关心"让用户去插件页配指标"，
 * 不该为了一个导航动作为每个视图改 props。这里用一次 CustomEvent，
 * App 是唯一监听者；仍然是纯 UI 动作，不碰仓库数据。
 */
import type { 步骤id } from "./任务流";

export const 跳步事件 = "驭臂.跳步";

export function 请求跳步(id: 步骤id): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<步骤id>(跳步事件, { detail: id }));
}
