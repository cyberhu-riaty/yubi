/**
 * 活动栏.tsx —— 最左边那条窄图标列（VS Code 的位置）。
 *
 * 五项是任务流的五个步骤，底部两项是外观/关于。图标全是**内联 SVG**（没有图标库依赖）：
 *   · 描边用 `currentColor`，所以按钮本身的 `color` 决定图标颜色 —— 换肤自动跟随
 *   · 每个按钮都是真 `<button>`，Tab 能到、有 `title`（含快捷键提示）
 *   · 当前步骤用 `aria-current="step"` + 左侧色条 + 底色三重表示（不靠颜色一种手段）
 *
 * 快捷键 1..5 在这里只显示提示，真正绑在 `App.tsx`（避免两处各绑一次）。
 */
import type { ReactNode } from "react";
import { 底部步骤, 任务步骤, type 步骤id } from "./任务流";
import { use取 } from "../视图/文案";

export interface 活动栏参数 {
  当前: 步骤id;
  侧栏开: boolean;
  on选步: (id: 步骤id) => void;
}

/** 16×16 视图框，1.5 描边；只画轮廓，不填色（跟随 currentColor） */
function 图标({ 名 }: { 名: 步骤id }) {
  const 公共 = {
    width: 18,
    height: 18,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.4,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (名) {
    case "定义": // 机械臂：基座 + 两节连杆 + 末端
      return (
        <svg {...公共}>
          <path d="M2 14h4" />
          <path d="M4 14V7l4-3 4 3" />
          <path d="M8 4V1" />
          <circle cx="8" cy="4" r="1" />
          <path d="M12 7v4" />
        </svg>
      );
    case "规划": // 路径：起点 → 路点 → 终点
      return (
        <svg {...公共}>
          <circle cx="3" cy="12.5" r="1.4" />
          <circle cx="8" cy="4" r="1.4" />
          <circle cx="13" cy="11" r="1.4" />
          <path d="M3.8 11.4C5 8 6 5.4 7.5 4.8" />
          <path d="M9 4.6c1.6.3 2.6 3.4 3.3 5.2" />
        </svg>
      );
    case "验证": // 曲线
      return (
        <svg {...公共}>
          <path d="M1.5 13.5h13" />
          <path d="M1.5 13.5V2" />
          <path d="M2.5 11l3-4 3 2.5 4.5-6" />
        </svg>
      );
    case "辨识": // 靶心 + 十字
      return (
        <svg {...公共}>
          <circle cx="8" cy="8" r="5.5" />
          <circle cx="8" cy="8" r="1.8" />
          <path d="M8 0.8v2M8 13.2v2M0.8 8h2M13.2 8h2" />
        </svg>
      );
    case "部署": // 插头/端口
      return (
        <svg {...公共}>
          <path d="M5 2v4M11 2v4" />
          <path d="M3 6h10v2.5a5 5 0 0 1-5 5 5 5 0 0 1-5-5V6z" />
          <path d="M8 13.5V15" />
        </svg>
      );
    case "外观": // 调色盘
      return (
        <svg {...公共}>
          <path d="M8 1.8a6.2 6.2 0 0 0 0 12.4c1 0 1.6-.7 1.6-1.5 0-.5-.2-.8-.5-1.1-.3-.3-.5-.6-.5-1 0-.8.6-1.4 1.5-1.4h1A2.9 2.9 0 0 0 14 6.3C14 3.8 11.3 1.8 8 1.8z" />
          <circle cx="5.2" cy="6.4" r="0.9" fill="currentColor" stroke="none" />
          <circle cx="8.4" cy="4.8" r="0.9" fill="currentColor" stroke="none" />
          <circle cx="11" cy="7.6" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      );
    case "关于": // i
      return (
        <svg {...公共}>
          <circle cx="8" cy="8" r="6.2" />
          <path d="M8 7.2v5" />
          <circle cx="8" cy="4.6" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      );
    default:
      return null;
  }
}

function 格子({
  名,
  短名,
  说明,
  当前,
  on按下,
  快捷键,
}: {
  名: 步骤id;
  短名: string;
  说明: string;
  当前: boolean;
  on按下: () => void;
  快捷键?: number;
}) {
  return (
    <button
      type="button"
      onClick={on按下}
      aria-current={当前 ? "step" : undefined}
      aria-label={`${短名} —— ${说明}`}
      title={快捷键 ? `${说明} (${快捷键})` : 说明}
      className="relative flex h-[52px] w-full flex-col items-center justify-center gap-0.5"
      style={{
        color: 当前 ? "var(--fg)" : "var(--fg-dim)",
        background: 当前 ? "var(--bg-frame-on)" : "transparent",
        borderLeft: `2px solid ${当前 ? "var(--grab)" : "transparent"}`,
      }}
    >
      <图标 名={名} />
      {/*
        ★ 图标下面要有**可见的短名**：只有图标 + `title` 的话，
          ① 要悬停才知道是什么；② 页面上根本找不到"部署"这两个字
          （`约定.md` 要求诚实标注未接入，标注得先能被看到）。
          短名走 `取(步骤.名键)`，所以它跟着语言切。
      */}
      <span className="text-[9px] leading-none" aria-hidden="true">
        {短名}
      </span>
      {快捷键 ? (
        <span
          aria-hidden="true"
          className="等宽 absolute bottom-0.5 right-1 text-[9px] leading-none"
          style={{ color: "var(--fg-dim)" }}
        >
          {快捷键}
        </span>
      ) : null}
    </button>
  );
}

export function 活动栏({ 当前, 侧栏开, on选步 }: 活动栏参数) {
  const t = use取();

  const 画组 = (组: typeof 任务步骤, 快捷键起?: number): ReactNode =>
    组.map((s, i) => (
      <格子
        key={s.id}
        名={s.id}
        短名={t(s.名键)}
        说明={t(s.说明键)}
        当前={当前 === s.id && 侧栏开}
        on按下={() => on选步(s.id)}
        快捷键={快捷键起 === undefined ? undefined : 快捷键起 + i}
      />
    ));

  return (
    <nav
      aria-label={t("活动栏.标题")}
      aria-orientation="vertical"
      className="flex h-full w-12 flex-none flex-col justify-between"
      style={{ background: "var(--bg-menu)", borderRight: "1px solid var(--border)" }}
    >
      <div role="toolbar" aria-label={t("活动栏.步骤编组")} aria-orientation="vertical">
        {画组(任务步骤, 1)}
      </div>
      <div role="toolbar" aria-label={t("活动栏.底部编组")} aria-orientation="vertical">
        {画组(底部步骤)}
      </div>
    </nav>
  );
}
