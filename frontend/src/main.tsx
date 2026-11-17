/**
 * main.tsx —— 挂载点。
 *
 * 顺序很要紧（换肤会闪、语言会跳，都是这里的顺序错了造成的）：
 *   ① 先按 localStorage 把 `data-theme` / `lang` 写到 `<html>` —— 在第一次绘制**之前**，
 *      否则会先闪一下默认皮肤。
 *   ② 再挂 React。
 *
 * `生成/theme.css` 由这里引入（而不是 index.css）：
 * 它是**产物**，与 `生成/` 下别的文件同源同命，集中在一个地方引，
 * 重建生成物时不用去翻别的文件。
 *
 * 默认皮肤用 `themes.ts` 的 `默认风格`（那份是生成的，与后端风格表同源）。
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./generated/theme.css";
import "./index.css";
import { App } from "./shell/App";
import { getTheme, applyThemeToDocument } from "./generated/appearance";
import { getLanguage } from "./views/i18n";

// ① 首帧之前定皮肤与语言（localStorage 里没有就用默认值）
applyThemeToDocument(getTheme());
document.documentElement.setAttribute("lang", getLanguage() === "zh" ? "zh-CN" : "en");

// ② 挂载
const root = document.getElementById("root");
if (!root) {
  throw new Error("index.html 里没有 #root —— 挂载点丢了");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
