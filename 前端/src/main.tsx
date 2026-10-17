/**
 * main.tsx —— 挂载点。
 *
 * 顺序很要紧（换肤会闪、语言会跳，都是这里的顺序错了造成的）：
 *   ① 先按 localStorage 把 `data-风格` / `lang` 写到 `<html>` —— 在第一次绘制**之前**，
 *      否则会先闪一下默认皮肤。
 *   ② 再挂 React。
 *
 * `生成/主题.css` 由这里引入（而不是 index.css）：
 * 它是**产物**，与 `生成/` 下别的文件同源同命，集中在一个地方引，
 * 重建生成物时不用去翻别的文件。
 *
 * 默认皮肤用 `风格.ts` 的 `默认风格`（那份是生成的，与后端风格表同源）。
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./生成/主题.css";
import "./index.css";
import { App } from "./外壳/App";
import { 取风格, 应用到文档 } from "./生成/外观";
import { 取语言 } from "./视图/文案";

// ① 首帧之前定皮肤与语言（localStorage 里没有就用默认值）
应用到文档(取风格());
document.documentElement.setAttribute("lang", 取语言() === "zh" ? "zh-CN" : "en");

// ② 挂载
const 根 = document.getElementById("root");
if (!根) {
  throw new Error("index.html 里没有 #root —— 挂载点丢了");
}

createRoot(根).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
