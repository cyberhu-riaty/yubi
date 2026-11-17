/**
 * AppearanceView.tsx —— 皮肤与语言。
 *
 * 皮肤不是"另写一套颜色"：列表直接来自 `生成/themes.ts`（← `runtime/theme_table.json`），
 * 点一下就把 `data-theme` 写到 `<html>` 上并记住（`生成/appearance.ts`）。
 * 所以这里**没有**第二份风格名单 —— 风格表再加一套，这一格自动多一行。
 */
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Tag } from "../components/Badge";
import { Button } from "../components/Button";
import { themes } from "@generated/themes";
import { setTheme, useTheme } from "../generated/appearance";
import { getLanguage, setLanguage, languageNames, useTranslation } from "./i18n";

export function AppearanceView() {
  const t = useTranslation();
  const current = useTheme();
  const localized = getLanguage();

  return (
    <div>
      <CollapsibleSection title={t("外观.皮肤")} badge={<span className="monospace">{themes.length}</span>}>
        <ul className="space-y-1">
          {themes.map((s) => {
            const selected = s.id === current;
            return (
              <li key={s.id}>
                <Button
                  variant="secondary"
                  pressed={selected}
                  onPress={() => setTheme(s.id)}
                  className="w-full justify-start"
                  style={selected ? { background: "var(--bg-frame-on)", borderColor: "var(--grab)", color: "var(--fg)" } : undefined}
                >
                  <span className="flex w-full min-w-0 items-start gap-2 whitespace-normal text-left">
                    <span className="flex min-w-0 flex-1 flex-col items-start">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="break-all">{s.name}</span>
                        <span className="text-[0.85em] text-dim break-all">{s.englishName}</span>
                        {selected ? <Tag tone="success">✓ {t("外观.当前")}</Tag> : null}
                      </span>
                      <span className="text-[0.85em] text-dim">{s.description}</span>
                    </span>
                    <span className="theme-preview" data-theme={s.id} aria-hidden="true">
                      <span className="theme-preview-bar" />
                      <span className="theme-preview-text">Aa</span>
                      <span className="theme-preview-button" />
                    </span>
                  </span>
                </Button>
              </li>
            );
          })}
        </ul>
        <details className="assembly-details mt-2">
          <summary>{t("外观.高级")}</summary>
          <p className="mt-1 text-[0.8em] text-dim">{t("外观.高级说明")}</p>
        </details>
      </CollapsibleSection>

      <CollapsibleSection title={t("外观.语言")} badge={<Tag>{languageNames[localized]}</Tag>}>
        <div className="flex gap-1.5" title={t("外观.语言说明")}>
          <Button variant={localized === "zh" ? "primary" : "secondary"} pressed={localized === "zh"} onPress={() => setLanguage("zh")}>
            中文
          </Button>
          <Button variant={localized === "en" ? "primary" : "secondary"} pressed={localized === "en"} onPress={() => setLanguage("en")}>
            English
          </Button>
        </div>
      </CollapsibleSection>
    </div>
  );
}
