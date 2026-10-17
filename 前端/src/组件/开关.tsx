/**
 * 开关.tsx —— 一个真正用键盘能开的开关。
 *
 * 用 `role="switch"` + `aria-checked` 而不是 `<input type=checkbox>`：
 * 外观是三套皮肤、五种控件里"开关"长得最不像原生复选框的那个，
 * 但我们仍然要拿到原生复选框的键盘行为（Tab 可达、Space 切换）。
 * 所以：button + role=switch + 自己处理 Space/Enter。
 *
 * `忙` 用于"命令已发出、等回执"这段：这时要禁用，避免连点出两条命令。
 */
import type { KeyboardEvent, ReactNode } from "react";
import { use取 } from "../视图/文案";

export interface 开关参数 {
  /** 当前值；`undefined` = 还不知道（未连接/后端没报）—— 这时显示"未知"而不是猜一个 false */
  开?: boolean;
  标签: ReactNode;
  说明?: ReactNode;
  禁用?: boolean;
  忙?: boolean;
  on切换?: (下一个: boolean) => void;
}

export function 开关({ 开, 标签, 说明, 禁用, 忙, on切换 }: 开关参数) {
  const t = use取();
  const 已知 = typeof 开 === "boolean";
  const 不能点 = 禁用 || 忙 || !已知;
  const 切 = () => {
    if (不能点) return;
    on切换?.(!开);
  };
  const 按键 = (e: KeyboardEvent<HTMLButtonElement>) => {
    // `<button>` 自己会把 Space/Enter 变成 click；这两行只是显式声明这个契约，
    // 顺手挡掉空格滚动页面。
    if (e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      切();
    }
  };

  return (
    <button
      type="button"
      role="switch"
      aria-checked={已知 ? 开 : "mixed"}
      aria-busy={忙 || undefined}
      disabled={不能点}
      onClick={切}
      onKeyDown={按键}
      className="控件 flex w-full items-start gap-2 text-left"
      style={{ cursor: 不能点 ? "not-allowed" : "pointer" }}
    >
      <span
        aria-hidden="true"
        className="mt-[2px] inline-flex h-[14px] w-[26px] flex-none items-center border"
        style={{
          background: 开 ? "var(--grab)" : "var(--bg-frame-on)",
          borderColor: "var(--border)",
          borderRadius: "999px",
          opacity: 不能点 ? 0.6 : 1,
        }}
      >
        <span
          className="block h-[10px] w-[10px] transition-transform"
          style={{
            background: "var(--bg)",
            borderRadius: "999px",
            transform: 开 ? "translateX(14px)" : "translateX(2px)",
          }}
        />
      </span>
      <span className="min-w-0">
        <span className="block truncate">{标签}</span>
        {说明 ? <span className="block text-[0.85em] text-dim">{说明}</span> : null}
        {!已知 ? (
          <span className="block text-[0.85em] text-dim">{忙 ? t("通用.等待") : "--"}</span>
        ) : null}
      </span>
    </button>
  );
}
