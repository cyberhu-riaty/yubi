/**
 * PluginView.tsx —— 「插件」：本机算法库里有什么，各自什么版本，被谁用到。
 *
 * ★ **先说清楚这一格不是什么**（这是全项目最容易变成骗人的一格）：
 *   它**不是插件市场**。没有远端仓库、没有下载、没有签名校验、没有版本服务器。
 *   所以这里不画搜索框、不画"安装"按钮、不画价格/评分 ——
 *   一个点了会转圈但什么也装不上的市场，比没有市场更糟：用户会以为装上了。
 *
 * 它真做的事：
 *   · 列出 `算法库/` 下的插件，元信息（版本/说明/作者）来自**真文件**（后端 AST 读取）
 *   · 标出"当前项目是否启用"；真正的选择、应用与保存统一放在「定义」页
 *   · 标出"被哪些项目用到"（反查 项目/*.json）
 *
 * 想做真正的市场，至少得先有：远端清单 + 校验和 + 安装到本地 + 版本冲突处理。
 * 那是另一件事，界面上已如实写明"未实现"。
 */
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Tag } from "../components/Badge";
import { Button } from "../components/Button";
import { useStore } from "../data/store";
import { requestStepNavigation } from "../shell/step_navigation";
import { useTranslation } from "./i18n";

export function PluginView() {
  const t = useTranslation();
  const directory = useStore((s) => s.plugins.data);
  const project = useStore((s) => s.project.data);
  const incompatibilityReport = (project?.report ?? []).filter((row) => row.includes("不兼容"));

  const items = directory?.插件 ?? [];

  return (
    <div className="space-y-2">
      <CollapsibleSection
        title={t("步骤.插件")}
        badge={items.length ? <Tag>{items.length}</Tag> : <Tag tone="notice">{t("通用.待接入")}</Tag>}
      >
        <p className="text-[0.85em]" style={{ color: "var(--warn)" }}>
          {t("插件.没有远端")}
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[0.82em] text-dim">
          <span>{t("插件.只读说明")}</span>
          <Button size="small" variant="ghost" onPress={() => requestStepNavigation("定义")}>
            {t("插件.去定义")}
          </Button>
        </div>

        {items.length ? (
          <ul className="mt-2 space-y-1">
            {items.map((x) => {
              const name = x.插件 ?? "";
              const displayName = x.名称 || name;
              const enabled = !!x.当前启用;
              const incompatible = incompatibilityReport.some((row) => row.includes(displayName) || (name && row.includes(name)));
              return (
                <li key={name} className="panel p-2">
                  <div className="flex items-baseline gap-1.5">
                    <span className="min-w-0 flex-1 truncate" style={{ fontWeight: 600 }} title={x.文件 ? `${t("插件.文件")}: ${x.文件}` : undefined}>
                      {displayName}
                    </span>
                    <span className="flex-none text-[0.8em] text-dim monospace">
                      {x.版本 ? `v${x.版本}` : t("插件.未标注")}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <Tag>{t("插件.状态.已安装")}</Tag>
                    <Tag tone={enabled ? "success" : "neutral"}>{enabled ? t("插件.状态.当前项目已启用") : t("插件.状态.当前项目未启用")}</Tag>
                    {incompatible ? <Tag tone="error">! {t("定义.算法状态.不兼容")}</Tag> : null}
                  </div>
                  <div className="mt-1 text-[0.85em] text-dim">
                    {x.说明 || t("插件.无说明")}
                  </div>
                  {x.被项目使用?.length ? (
                    <div className="mt-1 text-[0.8em] text-dim">
                      {`${t("插件.被使用")}: ${x.被项目使用.join(" / ")}`}
                    </div>
                  ) : (
                    <div className="mt-1 text-[0.8em] text-dim">{t("插件.未被任何项目使用")}</div>
                  )}
                  {incompatible ? (
                    <div className="mt-1 text-[0.8em]" style={{ color: "var(--danger)" }}>{t("插件.不兼容说明")}</div>
                  ) : null}
                  <div className="mt-1 flex items-center gap-2">
                    {x.作者 ? <span className="text-[0.8em] text-dim">{`${t("插件.作者")}: ${x.作者}`}</span> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="mt-2 text-dim">{directory?.说明 || t("插件.空")}</div>
        )}
      </CollapsibleSection>
    </div>
  );
}
