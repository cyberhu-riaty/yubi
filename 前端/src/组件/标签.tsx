/**
 * 标签.tsx —— 小标签（轴数、单位、未接入、状态）。
 *
 * 三种用法，语义不同所以颜色也不同：
 *   · 中性（默认）：单位、计数这类附注 → 灰底灰字
 *   · 强调：当前生效的东西（"在写 ctrl"）
 *   · 警示：未接入 / 未实现 / 出错 —— 这一种**不加动画、不加绿色**，
 *     诚实标注就该看起来像"缺东西"，而不是像"已就绪"
 */
import type { ReactNode } from "react";

export type 标签语气 = "中性" | "强调" | "警示";

export interface 标签参数 {
  children: ReactNode;
  语气?: 标签语气;
  等宽?: boolean;
  title?: string;
}

const 语气样式: Record<标签语气, React.CSSProperties> = {
  中性: { background: "var(--bg-frame)", color: "var(--fg-dim)", borderColor: "var(--border)" },
  强调: { background: "var(--bg-frame-on)", color: "var(--fg)", borderColor: "var(--border-strong)" },
  警示: {
    background: "transparent",
    color: "var(--fg-dim)",
    borderColor: "var(--border-strong)",
    borderStyle: "dashed",
  },
};

export function 标签({ children, 语气 = "中性", 等宽 = false, title }: 标签参数) {
  return (
    <span
      className={`标签${等宽 ? " 等宽" : ""}`}
      style={语气样式[语气]}
      title={title}
    >
      {children}
    </span>
  );
}
