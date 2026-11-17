/**
 * CollapsibleSection.tsx —— 本层唯一真正被复用的模式。
 *
 * 参考项目里那个 `CollapsibleSection`（48 行）被用了 25 次，说明"标题 + 折叠"
 * 确实是界面的基本单位；这一份照样做，但补上它缺的东西：
 *
 *  ① **键盘可达**：标题是 `<button>`，Tab 能到、Enter/Space 能开合
 *     （参考项目里 0 个 `tabIndex` / `onKeyDown`）。
 *  ② `aria-expanded` + `aria-controls` + 区块 `id`：读屏能说出来。
 *  ③ 计数徽标：折叠状态下也能看到"里面有几条"，不用展开才知道 / 不用展开瞎猜。
 *  ④ 段头右侧插槽（`右侧`）：把"属于这一段的动作"放在段头，而不是混进内容里。
 */
import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "../views/i18n";

export interface CollapsibleSectionProps {
  /** 标题是**纯文本**（它同时进 `title` 属性与读屏），要放复杂内容用 `右侧` */
  title: string;
  /** 折叠时也可见的计数/状态徽标 */
  badge?: ReactNode;
  /** 段头右侧的动作区（按钮等）—— 点它不会连带开合 */
  actions?: ReactNode;
  defaultOpen?: boolean;
  /** 受控开合（不给就用内部状态） */
 open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
}

export function CollapsibleSection({
  title: title,
  badge: badge,
  actions: actions,
  defaultOpen: defaultOpen = true,
  open: open,
  onOpenChange: onOpenChange,
  children,
}: CollapsibleSectionProps) {
  const t = useTranslation();
  const internalState = useState(defaultOpen);
  const isControlled = open !== undefined;
  const isOpen = isControlled ? open : internalState[0];
  const setOpen = (value: boolean) => {
    if (!isControlled) internalState[1](value);
    onOpenChange?.(value);
  };
  const contentId = useId();

  return (
    <section className={`section ${isOpen ? "section-expanded" : ""}`}>
      <div className="flex items-stretch">
        <button
          type="button"
          className="section-header flex-1"
          aria-expanded={isOpen}
          aria-controls={contentId}
          onClick={() => setOpen(!isOpen)}
          title={isOpen ? t("区块.收起名", { 名: title }) : t("区块.展开名", { 名: title })}
        >
          <span aria-hidden="true" className="monospace text-dim">
            {isOpen ? "▾" : "▸"}
          </span>
          <span className="min-w-0 flex-1 truncate">{title}</span>
          {badge ? <span className="flex-none text-dim">{badge}</span> : null}
          <span className="sr-only">{isOpen ? t("区块.收起") : t("区块.展开")}</span>
        </button>
        {actions ? <div className="flex items-center gap-1 px-1">{actions}</div> : null}
      </div>
      {isOpen ? (
        <div id={contentId} className="section-content px-3 py-2">
          {children}
        </div>
      ) : null}
    </section>
  );
}
