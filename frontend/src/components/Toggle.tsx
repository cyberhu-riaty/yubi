/**
 * Toggle.tsx —— 一个真正用键盘能开的开关。
 *
 * 用 `role="switch"` + `aria-checked` 而不是 `<input type=checkbox>`：
 * 外观是三套皮肤、五种控件里"开关"长得最不像原生复选框的那个，
 * 但我们仍然要拿到原生复选框的键盘行为（Tab 可达、Space 切换）。
 * 所以：button + role=switch + 自己处理 Space/Enter。
 *
 * `忙` 用于"命令已发出、等回执"这段：这时要禁用，避免连点出两条命令。
 */
import type { KeyboardEvent, ReactNode } from "react";
import { useTranslation } from "../views/i18n";

export interface SwitchProps {
  /** 当前值；`undefined` = 还不知道（未连接/后端没报）—— 这时显示"未知"而不是猜一个 false */
  checked?: boolean;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  busy?: boolean;
  onCheckedChange?: (next: boolean) => void;
}

export function Switch({ checked: checked, label: label, description: description, disabled: disabled, busy: busy, onCheckedChange: onCheckedChange }: SwitchProps) {
  const t = useTranslation();
  const isKnown = typeof checked === "boolean";
  const isDisabled = disabled || busy || !isKnown;
  const toggle = () => {
    if (isDisabled) return;
    onCheckedChange?.(!checked);
  };
  const handleKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    // `<button>` 自己会把 Space/Enter 变成 click；这两行只是显式声明这个契约，
    // 顺手挡掉空格滚动页面。
    if (e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      toggle();
    }
  };

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isKnown ? checked : "mixed"}
      aria-busy={busy || undefined}
      disabled={isDisabled}
      onClick={toggle}
      onKeyDown={handleKeyDown}
      className="control flex w-full items-start gap-2 text-left"
      style={{ cursor: isDisabled ? "not-allowed" : "pointer" }}
    >
      <span
        aria-hidden="true"
        className="mt-[2px] inline-flex h-[14px] w-[26px] flex-none items-center border"
        style={{
          background: checked ? "var(--grab)" : "var(--bg-frame-on)",
          borderColor: "var(--border)",
          borderRadius: "999px",
          opacity: isDisabled ? 0.6 : 1,
        }}
      >
        <span
          className="block h-[10px] w-[10px] transition-transform"
          style={{
            background: "var(--bg)",
            borderRadius: "999px",
            transform: checked ? "translateX(14px)" : "translateX(2px)",
          }}
        />
      </span>
      <span className="min-w-0">
        <span className="block truncate">{label}</span>
        {description ? <span className="block text-[0.85em] text-dim">{description}</span> : null}
        {!isKnown ? (
          <span className="block text-[0.85em] text-dim">{busy ? t("通用.等待") : "--"}</span>
        ) : null}
      </span>
    </button>
  );
}
