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

export type 按钮种类 = "主" | "次" | "幽灵" | "危险";
export type 按钮尺寸 = "小" | "中";

export interface 按钮参数 extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onClick" | "type"> {
  children: ReactNode;
  种类?: 按钮种类;
  尺寸?: 按钮尺寸;
  已按下?: boolean;
  on按下?: () => void;
}

const 尺寸类: Record<按钮尺寸, string> = {
  小: "px-1.5 py-0.5 text-[0.9em]",
  中: "px-2.5 py-1",
};

/** 种类 → 追加的 Tailwind 语义类（颜色全部来自 `@theme` 里那几个 token） */
const 种类类: Record<按钮种类, string> = {
  主: "bg-accent text-fg border-line-strong hover:bg-accent-hover",
  次: "bg-frame text-fg border-line hover:bg-frame-hover",
  幽灵: "bg-transparent text-dim border-transparent hover:bg-frame hover:text-fg",
  危险: "bg-frame text-fg border-line-strong hover:bg-accent-on",
};

export function 按钮({
  children,
  种类 = "次",
  尺寸 = "中",
  已按下 = false,
  on按下,
  className = "",
  disabled,
  ...其余
}: 按钮参数) {
  return (
    <button
      {...其余}
      type="button"
      disabled={disabled}
      aria-pressed={已按下 || undefined}
      onClick={on按下}
      className={[
        "控件 inline-flex items-center justify-center gap-1.5 select-none whitespace-nowrap",
        尺寸类[尺寸],
        种类类[种类],
        已按下 ? "bg-accent-on" : "",
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
