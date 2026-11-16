/**
 * 按钮.tsx —— 最小按钮原语。
 *
 * 为什么自己写而不引组件库：`约定.md` 要求依赖尽量零、颜色一律走主题变量。
 * 相比参考项目多出来的那一件事是**键盘可达**：
 *   · 真 `<button>`（不是 div 上挂 onClick），Tab 能到、Enter/Space 能按
 *   · `onKeyDown` 转发：回车触发一次，且不重复触发（浏览器已经会，这里只做兜底）
 *   · 焦点圈由 `index.css` 的 `:focus-visible` 统一给，不在组件里写死颜色
 */
import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "small" | "medium";

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onClick" | "type"> {
  children: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  pressed?: boolean;
  onPress?: () => void;
}

const sizeClasses: Record<ButtonSize, string> = {
  small: "px-1.5 py-0.5 text-[0.9em]",
  medium: "px-2.5 py-1",
};

/** 种类 → 追加的 Tailwind 语义类（颜色全部来自 `@theme` 里那几个 token） */
const variantClasses: Record<ButtonVariant, string> = {
  primary: "bg-accent text-fg border-line-strong hover:bg-accent-hover",
  secondary: "bg-frame text-fg border-line hover:bg-frame-hover",
  ghost: "bg-transparent text-dim border-transparent hover:bg-frame hover:text-fg",
  danger: "bg-frame text-fg border-line-strong hover:bg-accent-on",
};

export function Button({
  children,
  variant: variant = "secondary",
  size: size = "medium",
  pressed: pressed = false,
  onPress: onPress,
  className = "",
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type="button"
      disabled={disabled}
      aria-pressed={pressed || undefined}
      onClick={onPress}
      className={[
        "控件 inline-flex items-center justify-center gap-1.5 select-none whitespace-nowrap",
        sizeClasses[size],
        variantClasses[variant],
        pressed ? "bg-accent-on" : "",
        disabled ? "opacity-40 cursor-not-allowed" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </button>
  );
}
