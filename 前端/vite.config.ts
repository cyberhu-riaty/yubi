import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/*
 * `@生成/*` → `src/生成/*`：契约.ts / 风格.ts / 主题.css 由 Python 侧生成，
 * 前端不抄第二份。`tsconfig.json` 里有同一条 —— **两处都要写**：
 * tsc 与 vite 各认各的路径表，少写一处就会"tsc 过了、构建却找不到模块"（真踩过）。
 *
 * 这里特意**不引 node 内置模块**（不写 `fileURLToPath(import.meta.url)`）：
 * 那需要 `@types/node`，而本项目的 `tsconfig.types` 只有 `vite/client`。
 * `import.meta.dirname` 是 Node ≥20.11 原生支持的（构建期不会进浏览器产物），
 * 声明成字符串联合类型是为了绕开"没有 node 类型"这一条，不是在做运行时判断。
 */
const 前端根 = (import.meta as unknown as { dirname: string }).dirname;

// 构建产物直接落到 软件/web/ —— 由 Python 的 Web桥 在同一个端口提供，
// 所以"前端产物"和"后端服务"是同源的：不需要 CORS，不需要第二个进程。
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./",
  resolve: {
    alias: {
      "@生成": `${前端根}/src/生成`,
    },
  },
  build: {
    // ★ 产物目录 = `软件/web/`，`emptyOutDir` 会**递归清空**它。
    //   所以这里只放构建产物，**不放任何需要长期存在的文件** —— 生成物
    //   （契约.ts / 风格.ts / 主题.css）一律落在 `src/生成/`，靠 import 打进包。
    //   踩过的坑：生成物曾同时放这里，于是每次构建都删掉它，且顺序一变就时好时坏。
    //   （`emptyOutDir` 只有 boolean，没有"排除目录"，查过类型定义；所以正解是
    //    别把东西放进来，而不是想办法排除。）
    outDir: "../软件/web",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    port: 5273,
    proxy: {
      // 开发时把接口转给 Python 侧的 Web桥
      "/api": "http://127.0.0.1:8712",
      "/ws": { target: "ws://127.0.0.1:8712", ws: true },
    },
  },
});
