/**
 * 关于视图.tsx —— 软件信息、许可证与开发诊断。
 *
 * 这一格的事实分两层：
 *   · 普通用户先看到：软件名、版本、构建方式、许可证、第三方组件、后端连接。
 *   · 契约/协议/主题数/帧序号/握手/上下行清单收进「开发信息」，默认收起；
 *     它们可核对，但不该占据普通用户的第一屏。
 *
 * 版本号来自 `前端/package.json`（Vite 会把它打进包），不在组件里手写。
 */
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { 数值表, type 数值行 } from "../组件/数值表";
import { 契约版本, 协议版本, 下行元, 上行元 } from "@生成/契约";
import { 用仓库 } from "../数据/仓库";
import { 连接键, use取 } from "./文案";
import 包信息 from "../../package.json";

export function 关于视图() {
  const t = use取();
  const 握手 = 用仓库((s) => s.握手);
  const 帧号 = 用仓库((s) => s.项目.帧号);
  const 模型帧号 = 用仓库((s) => s.模型.帧号);

  const 软件事实: 数值行[] = [
    { 键: t("关于.软件"), 值: `${t("应用.名称")} · ${t("应用.副标题")}` },
    { 键: t("关于.版本"), 值: <span className="等宽">v{包信息.version}</span> },
    { 键: t("关于.构建"), 值: t("关于.构建值") },
    { 键: t("关于.许可证"), 值: "MIT" },
    { 键: t("关于.第三方"), 值: t("关于.第三方值") },
    { 键: t("状态栏.连接"), 值: <连接文本 /> },
  ];

  const 开发事实: 数值行[] = [
    {
      键: t("关于.契约版本"),
      值: <span className="等宽">{契约版本} / {协议版本}</span>,
    },
    {
      键: t("关于.主题数"),
      值: <span className="等宽">{下行元.length} ↓ / {上行元.length} ↑</span>,
    },
    {
      键: t("关于.帧号"),
      值: (
        <span className="等宽">
          {模型帧号 || 帧号 ? `#${Math.max(模型帧号, 帧号)}` : t("关于.帧号.无")}
        </span>
      ),
      弱: !模型帧号 && !帧号,
    },
  ];

  return (
    <div>
      <可折叠区块 标题={t("关于.标题")}>
        <数值表 行={软件事实} />
      </可折叠区块>

      <可折叠区块 标题={t("关于.许可证与第三方")}>
        <ul className="space-y-1 text-dim">
          <li>{t("关于.声明一")}</li>
          <li>{t("关于.声明二")}</li>
          <li>{t("关于.声明三")}</li>
          <li>{t("关于.声明四")}</li>
        </ul>
      </可折叠区块>

      <可折叠区块
        标题={t("关于.开发信息")}
        默认开={false}
      >
        <p className="text-[0.85em] text-dim">{t("关于.开发说明")}</p>
        <div className="mt-2">
          <数值表 行={开发事实} />
        </div>
        <div className="mt-2 text-[0.85em] text-dim">
          <span className="font-medium">{t("关于.握手")}：</span>
          {握手 ? (
            <span>
              {t("关于.握手.有", {
                可用: 握手.可用主题?.length ?? 0,
                间隔: 握手.广播间隔,
                版本: 握手.契约?.版本 ?? "--",
              })}
            </span>
          ) : (
            <span>{t("关于.握手.无")}</span>
          )}
        </div>

        <details className="装配详情 mt-2">
          <summary>{t("关于.下行")}（{下行元.length}）</summary>
          <ul className="mt-1 space-y-1">
            {下行元.map((m) => (
              <li key={m.名}>
                <div className="flex items-center gap-1.5">
                  <span className="break-all">{m.名}</span>
                  <标签>{m.种类}</标签>
                  <span className="等宽 text-dim">{m.类名}</span>
                </div>
                <div className="text-[0.85em] text-dim">{m.摘要}</div>
              </li>
            ))}
          </ul>
        </details>

        <details className="装配详情 mt-1">
          <summary>{t("关于.上行")}（{上行元.length}）</summary>
          <ul className="mt-1 space-y-1">
            {上行元.map((m) => (
              <li key={m.名}>
                <div className="flex items-center gap-1.5">
                  <span className="break-all">{m.名}</span>
                  <标签>{m.种类}</标签>
                  <span className="等宽 text-dim">{m.类名}</span>
                </div>
                <div className="text-[0.85em] text-dim">{m.摘要}</div>
              </li>
            ))}
          </ul>
        </details>
      </可折叠区块>
    </div>
  );
}

/** 后端连接状态文本（从仓库订阅） */
function 连接文本() {
  const t = use取();
  const 连接 = 用仓库((s) => s.连接);
  return <span className="等宽">{t(连接键[连接])}</span>;
}
