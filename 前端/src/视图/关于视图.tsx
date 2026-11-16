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
import { CollapsibleSection } from "../组件/可折叠区块";
import { Tag } from "../组件/标签";
import { ValueTable, type ValueRow } from "../组件/数值表";
import { 契约版本, 协议版本, 下行元, 上行元 } from "@生成/契约";
import { 用仓库 } from "../数据/仓库";
import { connectionTranslationKeys, useTranslation } from "./文案";
import 包信息 from "../../package.json";

export function 关于视图() {
  const t = useTranslation();
  const 握手 = 用仓库((s) => s.握手);
  const 帧号 = 用仓库((s) => s.项目.帧号);
  const 模型帧号 = 用仓库((s) => s.模型.帧号);

  const 软件事实: ValueRow[] = [
    { key: t("关于.软件"), value: `${t("应用.名称")} · ${t("应用.副标题")}` },
    { key: t("关于.版本"), value: <span className="等宽">v{包信息.version}</span> },
    { key: t("关于.构建"), value: t("关于.构建值") },
    { key: t("关于.许可证"), value: "MIT" },
    { key: t("关于.第三方"), value: t("关于.第三方值") },
    { key: t("状态栏.连接"), value: <连接文本 /> },
  ];

  const 开发事实: ValueRow[] = [
    {
      key: t("关于.契约版本"),
      value: <span className="等宽">{契约版本} / {协议版本}</span>,
    },
    {
      key: t("关于.主题数"),
      value: <span className="等宽">{下行元.length} ↓ / {上行元.length} ↑</span>,
    },
    {
      key: t("关于.帧号"),
      value: (
        <span className="等宽">
          {模型帧号 || 帧号 ? `#${Math.max(模型帧号, 帧号)}` : t("关于.帧号.无")}
        </span>
      ),
      muted: !模型帧号 && !帧号,
    },
  ];

  return (
    <div>
      <CollapsibleSection title={t("关于.标题")}>
        <ValueTable rows={软件事实} />
      </CollapsibleSection>

      <CollapsibleSection title={t("关于.许可证与第三方")}>
        <ul className="space-y-1 text-dim">
          <li>{t("关于.声明一")}</li>
          <li>{t("关于.声明二")}</li>
          <li>{t("关于.声明三")}</li>
          <li>{t("关于.声明四")}</li>
        </ul>
      </CollapsibleSection>

      <CollapsibleSection
        title={t("关于.开发信息")}
        defaultOpen={false}
      >
        <p className="text-[0.85em] text-dim">{t("关于.开发说明")}</p>
        <div className="mt-2">
          <ValueTable rows={开发事实} />
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
                  <Tag>{m.种类}</Tag>
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
                  <Tag>{m.种类}</Tag>
                  <span className="等宽 text-dim">{m.类名}</span>
                </div>
                <div className="text-[0.85em] text-dim">{m.摘要}</div>
              </li>
            ))}
          </ul>
        </details>
      </CollapsibleSection>
    </div>
  );
}

/** 后端连接状态文本（从仓库订阅） */
function 连接文本() {
  const t = useTranslation();
  const 连接 = 用仓库((s) => s.连接);
  return <span className="等宽">{t(connectionTranslationKeys[连接])}</span>;
}
