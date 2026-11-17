/**
 * HelpView.tsx —— 主界面只给入口，不把整本说明书重新塞回工作区。
 *
 * 这里保留首次使用真正需要的最短路径；按钮明细、参数含义、故障排查和
 * 能力边界统一维护在 `docs/使用手册.md`，避免界面文案与说明书各写一套。
 */
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Tag } from "../components/Badge";
import { useTranslation, type TranslationKey } from "./i18n";

const QUICK_STEPS = ["帮助.快速.一", "帮助.快速.二", "帮助.快速.三", "帮助.快速.四"] as const satisfies readonly TranslationKey[];
const viewportActions = ["帮助.三维.旋转", "帮助.三维.平移", "帮助.三维.缩放", "帮助.三维.适配"] as const satisfies readonly TranslationKey[];
const warningItem = ["帮助.注意.暂停", "帮助.注意.模拟", "帮助.注意.急停"] as const satisfies readonly TranslationKey[];

export function HelpView() {
  const t = useTranslation();
  return (
    <div className="space-y-2">
      <CollapsibleSection title={t("帮助.快速标题")} badge={<Tag>{t("帮助.新手")}</Tag>}>
        <ol className="list-decimal space-y-1 pl-5">
          {QUICK_STEPS.map((key) => <li key={key}>{t(key)}</li>)}
        </ol>
      </CollapsibleSection>

      <CollapsibleSection title={t("帮助.三维标题")} defaultOpen={false}>
        <ul className="space-y-1">
          {viewportActions.map((key) => <li key={key}>{t(key)}</li>)}
        </ul>
      </CollapsibleSection>

      <CollapsibleSection title={t("帮助.说明书标题")}>
        <p>{t("帮助.说明书说明")}</p>
        <div className="panel mt-2 break-all px-2 py-1.5 monospace">docs/使用手册.md</div>
        <p className="mt-2 text-[0.85em] text-dim">{t("帮助.悬浮提示")}</p>
      </CollapsibleSection>

      <CollapsibleSection title={t("帮助.注意标题")} defaultOpen={false}>
        <ul className="space-y-1" style={{ color: "var(--warn)" }}>
          {warningItem.map((key) => <li key={key}>{t(key)}</li>)}
        </ul>
      </CollapsibleSection>
    </div>
  );
}
