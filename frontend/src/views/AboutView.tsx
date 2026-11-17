/**
 * AboutView.tsx —— 软件信息、许可证与开发诊断。
 *
 * 这一格的事实分两层：
 *   · 普通用户先看到：软件名、版本、构建方式、许可证、第三方组件、后端连接。
 *   · 契约/协议/主题数/帧序号/握手/上下行清单收进「开发信息」，默认收起；
 *     它们可核对，但不该占据普通用户的第一屏。
 *
 * 版本号来自 `frontend/package.json`（Vite 会把它打进包），不在组件里手写。
 */
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Tag } from "../components/Badge";
import { ValueTable, type ValueRow } from "../components/DataTable";
import { CONTRACT_VERSION, PROTOCOL_VERSION, serverTopics, clientTopics } from "@generated/contract";
import { useStore } from "../data/store";
import { connectionTranslationKeys, useTranslation } from "./i18n";
import packageInfo from "../../package.json";

export function AboutView() {
  const t = useTranslation();
  const handshake = useStore((s) => s.handshake);
  const frameId = useStore((s) => s.project.frameId);
  const modelFrameId = useStore((s) => s.model.frameId);

  const softwareFacts: ValueRow[] = [
    { key: t("关于.软件"), value: `${t("应用.名称")} · ${t("应用.副标题")}` },
    { key: t("关于.版本"), value: <span className="monospace">v{packageInfo.version}</span> },
    { key: t("关于.构建"), value: t("关于.构建值") },
    { key: t("关于.许可证"), value: "MIT" },
    { key: t("关于.第三方"), value: t("关于.第三方值") },
    { key: t("状态栏.连接"), value: <ConnectionText /> },
  ];

  const developmentFacts: ValueRow[] = [
    {
      key: t("关于.契约版本"),
      value: <span className="monospace">{CONTRACT_VERSION} / {PROTOCOL_VERSION}</span>,
    },
    {
      key: t("关于.主题数"),
      value: <span className="monospace">{serverTopics.length} ↓ / {clientTopics.length} ↑</span>,
    },
    {
      key: t("关于.帧号"),
      value: (
        <span className="monospace">
          {modelFrameId || frameId ? `#${Math.max(modelFrameId, frameId)}` : t("关于.帧号.无")}
        </span>
      ),
      muted: !modelFrameId && !frameId,
    },
  ];

  return (
    <div>
      <CollapsibleSection title={t("关于.标题")}>
        <ValueTable rows={softwareFacts} />
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
          <ValueTable rows={developmentFacts} />
        </div>
        <div className="mt-2 text-[0.85em] text-dim">
          <span className="font-medium">{t("关于.握手")}：</span>
          {handshake ? (
            <span>
              {t("关于.握手.有", {
                可用: handshake.可用主题?.length ?? 0,
                间隔: handshake.广播间隔,
                版本: handshake.契约?.版本 ?? "--",
              })}
            </span>
          ) : (
            <span>{t("关于.握手.无")}</span>
          )}
        </div>

        <details className="assembly-details mt-2">
          <summary>{t("关于.下行")}（{serverTopics.length}）</summary>
          <ul className="mt-1 space-y-1">
            {serverTopics.map((m) => (
              <li key={m.name}>
                <div className="flex items-center gap-1.5">
                  <span className="break-all">{m.name}</span>
                  <Tag>{m.kind}</Tag>
                  <span className="monospace text-dim">{m.className}</span>
                </div>
                <div className="text-[0.85em] text-dim">{m.summary}</div>
              </li>
            ))}
          </ul>
        </details>

        <details className="assembly-details mt-1">
          <summary>{t("关于.上行")}（{clientTopics.length}）</summary>
          <ul className="mt-1 space-y-1">
            {clientTopics.map((m) => (
              <li key={m.name}>
                <div className="flex items-center gap-1.5">
                  <span className="break-all">{m.name}</span>
                  <Tag>{m.kind}</Tag>
                  <span className="monospace text-dim">{m.className}</span>
                </div>
                <div className="text-[0.85em] text-dim">{m.summary}</div>
              </li>
            ))}
          </ul>
        </details>
      </CollapsibleSection>
    </div>
  );
}

/** 后端连接状态文本（从仓库订阅） */
function ConnectionText() {
  const t = useTranslation();
  const connection = useStore((s) => s.connection);
  return <span className="monospace">{t(connectionTranslationKeys[connection])}</span>;
}
