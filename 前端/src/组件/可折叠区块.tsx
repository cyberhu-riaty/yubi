/**
 * 可折叠区块.tsx —— 本层唯一真正被复用的模式。
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
import { use取 } from "../视图/文案";

export interface 可折叠区块参数 {
  /** 标题是**纯文本**（它同时进 `title` 属性与读屏），要放复杂内容用 `右侧` */
  标题: string;
  /** 折叠时也可见的计数/状态徽标 */
  徽标?: ReactNode;
  /** 段头右侧的动作区（按钮等）—— 点它不会连带开合 */
  右侧?: ReactNode;
  默认开?: boolean;
  /** 受控开合（不给就用内部状态） */
 开?: boolean;
  on开合?: (开: boolean) => void;
  children: ReactNode;
}

export function 可折叠区块({
  标题,
  徽标,
  右侧,
  默认开 = true,
  开,
  on开合,
  children,
}: 可折叠区块参数) {
  const t = use取();
  const 内部 = useState(默认开);
  const 是受控 = 开 !== undefined;
  const 当前开 = 是受控 ? 开 : 内部[0];
  const 设开 = (值: boolean) => {
    if (!是受控) 内部[1](值);
    on开合?.(值);
  };
  const 内容id = useId();

  return (
    <section className={`段 ${当前开 ? "段-展开" : ""}`}>
      <div className="flex items-stretch">
        <button
          type="button"
          className="段头 flex-1"
          aria-expanded={当前开}
          aria-controls={内容id}
          onClick={() => 设开(!当前开)}
          title={当前开 ? t("区块.收起名", { 名: 标题 }) : t("区块.展开名", { 名: 标题 })}
        >
          <span aria-hidden="true" className="等宽 text-dim">
            {当前开 ? "▾" : "▸"}
          </span>
          <span className="min-w-0 flex-1 truncate">{标题}</span>
          {徽标 ? <span className="flex-none text-dim">{徽标}</span> : null}
          <span className="sr-only">{当前开 ? t("区块.收起") : t("区块.展开")}</span>
        </button>
        {右侧 ? <div className="flex items-center gap-1 px-1">{右侧}</div> : null}
      </div>
      {当前开 ? (
        <div id={内容id} className="段内容 px-3 py-2">
          {children}
        </div>
      ) : null}
    </section>
  );
}
