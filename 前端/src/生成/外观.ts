/**
 * 外观.ts —— 皮肤（`data-风格`）的读写与订阅。
 *
 * 为什么单独一个文件而不是塞进 `数据/仓库.ts`：
 *   仓库那份是**后端状态**（项目/模型/参数/辨识/曲线/连接），皮肤是**纯本地偏好**，
 *   两者生命周期完全不同（换肤不该惊动任何数据订阅者）。
 *
 * 数据源只有一个：`生成/风格.ts` 的 `风格表`（← `软件/风格表.json`）。
 * 这里**不维护第二份风格名单**，否则加了第 6 套皮肤前端就漏了。
 */
import { useSyncExternalStore } from "react";
import { 默认风格, 风格表 } from "@生成/风格";

const 存储键 = "驭臂.风格";

/** 当前合法风格名集合（校验用） */
const 合法名 = new Set(风格表.map((s) => s.名));

function 读存档(): string {
  try {
    const 存 = window.localStorage.getItem(存储键);
    if (存 && 合法名.has(存)) return 存;
  } catch {
    /* 隐私模式 / 存储被禁用：用默认值，不报错 */
  }
  return 默认风格;
}

let 当前 = 读存档();

const 订阅者 = new Set<() => void>();

function 广播(): void {
  for (const f of 订阅者) f();
}

/** 把风格写到 `<html data-风格>`（整站换肤就靠这一个属性） */
export function 应用到文档(名: string): void {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-风格", 名);
  }
}

export function 取风格(): string {
  return 当前;
}

export function 设风格(名: string): void {
  if (!合法名.has(名) || 名 === 当前) return;
  当前 = 名;
  try {
    window.localStorage.setItem(存储键, 名);
  } catch {
    /* 存不下也能用，只是下次启动回到默认 */
  }
  应用到文档(名);
  广播();
}

/** 订阅当前风格（换肤时只有用到它的组件重画） */
export function 用风格(): string {
  return useSyncExternalStore(
    (回调) => {
      订阅者.add(回调);
      return () => 订阅者.delete(回调);
    },
    取风格,
    取风格,
  );
}
