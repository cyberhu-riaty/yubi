/**
 * 外观视图.tsx —— 皮肤与语言。
 *
 * 皮肤不是"另写一套颜色"：列表直接来自 `生成/风格.ts`（← `软件/风格表.json`），
 * 点一下就把 `data-风格` 写到 `<html>` 上并记住（`生成/外观.ts`）。
 * 所以这里**没有**第二份风格名单 —— 风格表再加一套，这一格自动多一行。
 */
import { CollapsibleSection } from "../组件/可折叠区块";
import { Tag } from "../组件/标签";
import { Button } from "../组件/按钮";
import { 风格表 } from "@生成/风格";
import { 设风格, 用风格 } from "../生成/外观";
import { getLanguage, setLanguage, languageNames, useTranslation } from "./文案";

export function 外观视图() {
  const t = useTranslation();
  const 当前 = 用风格();
  const 语 = getLanguage();

  return (
    <div>
      <CollapsibleSection title={t("外观.皮肤")} badge={<span className="等宽">{风格表.length}</span>}>
        <ul className="space-y-1">
          {风格表.map((s) => {
            const 选中 = s.名 === 当前;
            return (
              <li key={s.名}>
                <Button
                  variant="secondary"
                  pressed={选中}
                  onPress={() => 设风格(s.名)}
                  className="w-full justify-start"
                  style={选中 ? { background: "var(--bg-frame-on)", borderColor: "var(--grab)", color: "var(--fg)" } : undefined}
                >
                  <span className="flex w-full min-w-0 items-start gap-2 whitespace-normal text-left">
                    <span className="flex min-w-0 flex-1 flex-col items-start">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="break-all">{s.名}</span>
                        <span className="text-[0.85em] text-dim break-all">{s.英文名}</span>
                        {选中 ? <Tag tone="success">✓ {t("外观.当前")}</Tag> : null}
                      </span>
                      <span className="text-[0.85em] text-dim">{s.一句话}</span>
                    </span>
                    <span className="皮肤预览" data-风格={s.名} aria-hidden="true">
                      <span className="皮肤预览-条" />
                      <span className="皮肤预览-字">Aa</span>
                      <span className="皮肤预览-钮" />
                    </span>
                  </span>
                </Button>
              </li>
            );
          })}
        </ul>
        <details className="装配详情 mt-2">
          <summary>{t("外观.高级")}</summary>
          <p className="mt-1 text-[0.8em] text-dim">{t("外观.高级说明")}</p>
        </details>
      </CollapsibleSection>

      <CollapsibleSection title={t("外观.语言")} badge={<Tag>{languageNames[语]}</Tag>}>
        <div className="flex gap-1.5" title={t("外观.语言说明")}>
          <Button variant={语 === "zh" ? "primary" : "secondary"} pressed={语 === "zh"} onPress={() => setLanguage("zh")}>
            中文
          </Button>
          <Button variant={语 === "en" ? "primary" : "secondary"} pressed={语 === "en"} onPress={() => setLanguage("en")}>
            English
          </Button>
        </div>
      </CollapsibleSection>
    </div>
  );
}
