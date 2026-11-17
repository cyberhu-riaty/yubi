/**
 * appearance.ts —— 皮肤（`data-theme`）的读写与订阅。
 *
 * 为什么单独一个文件而不是塞进 `数据/store.ts`：
 *   仓库那份是**后端状态**（项目/模型/参数/辨识/曲线/连接），皮肤是**纯本地偏好**，
 *   两者生命周期完全不同（换肤不该惊动任何数据订阅者）。
 *
 * 数据源只有一个：`生成/themes.ts` 的 `风格表`（← `软件/风格表.json`）。
 * 这里**不维护第二份风格名单**，否则加了第 6 套皮肤前端就漏了。
 */
import { useSyncExternalStore } from "react";
import { DEFAULT_THEME, themes } from "@generated/themes";

const STORAGE_KEY = "驭臂.风格";

/** 当前合法风格 id 集合（校验用）。`data-theme` 与本地存储都使用 ASCII id。 */
const validThemeIds = new Set(themes.map((s) => s.id));
/** 旧版本把中文短名存进 localStorage；读取时迁移到 id。 */
const legacyThemeIds = new Map(themes.flatMap((s) => [
  [s.legacyName, s.id], [s.name, s.id],
]));

function readSavedTheme(): string {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && validThemeIds.has(stored)) return stored;
    const legacy = stored ? legacyThemeIds.get(stored) : undefined;
    if (legacy) {
      window.localStorage.setItem(STORAGE_KEY, legacy);
      return legacy;
    }
  } catch {
    /* 隐私模式 / 存储被禁用：用默认值，不报错 */
  }
  return DEFAULT_THEME;
}

let currentTheme = readSavedTheme();

const subscribers = new Set<() => void>();

function publish(): void {
  for (const f of subscribers) f();
}

/** 把风格写到 `<html data-theme>`（整站换肤就靠这一个属性） */
export function applyThemeToDocument(name: string): void {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("data-theme", name);
  }
}

export function getTheme(): string {
  return currentTheme;
}

export function setTheme(name: string): void {
  if (!validThemeIds.has(name) || name === currentTheme) return;
  currentTheme = name;
  try {
    window.localStorage.setItem(STORAGE_KEY, name);
  } catch {
    /* 存不下也能用，只是下次启动回到默认 */
  }
  applyThemeToDocument(name);
  publish();
}

/** 订阅当前风格（换肤时只有用到它的组件重画） */
export function useTheme(): string {
  return useSyncExternalStore(
    (callback) => {
      subscribers.add(callback);
      return () => subscribers.delete(callback);
    },
    getTheme,
    getTheme,
  );
}
