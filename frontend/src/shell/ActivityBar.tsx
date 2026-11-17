/**
 * ActivityBar.tsx —— 最左边那条窄图标列（VS Code 的位置）。
 *
 * 十一项按三组排：**流程**（定义→规划→验证→辨识→部署）、**运行**（监控/诊断/插件）、
 * **信息**（外观/帮助/关于）。图标全是**内联 SVG**（没有图标库依赖）：
 *   · 描边用 `currentColor`，所以按钮本身的 `color` 决定图标颜色 —— 换肤自动跟随
 *   · 每个按钮都是真 `<button>`，Tab 能到、有 `title`（含快捷键提示）
 *   · 当前步骤用 `aria-current="step"` + 左侧色条 + 底色三重表示（不靠颜色一种手段）
 *
 * ★ 编号只保留在 title 里（1..5 仍可跳步骤），**不再画在图标角上**：
 *   原来只有前 5 项带编号，看起来像"后 3 项不属于任务流"；统一去掉编号，
 *   组标题说明它们各自属于哪一组。
 */
import type { ReactNode } from "react";
import { FOOTER_STEPS, TASK_STEPS, RUN_STEPS, type StepId } from "./task_flow";
import { useTranslation } from "../views/i18n";

export interface ActivityBarProps {
  current: StepId;
  sidebarOpen: boolean;
  onStepSelect: (id: StepId) => void;
}

/** 16×16 视图框，1.5 描边；只画轮廓，不填色（跟随 currentColor） */
function Icon({ name: name }: { name: StepId }) {
  const common = {
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
  switch (name) {
    case "定义": // 机械臂：基座 + 两节连杆 + 末端
      return (
        <svg {...common}>
          <path d="M2 14h4" />
          <path d="M4 14V7l4-3 4 3" />
          <path d="M8 4V1" />
          <circle cx="8" cy="4" r="1" />
          <path d="M12 7v4" />
        </svg>
      );
    case "规划": // 路径：起点 → 路点 → 终点
      return (
        <svg {...common}>
          <circle cx="3" cy="12.5" r="1.4" />
          <circle cx="8" cy="4" r="1.4" />
          <circle cx="13" cy="11" r="1.4" />
          <path d="M3.8 11.4C5 8 6 5.4 7.5 4.8" />
          <path d="M9 4.6c1.6.3 2.6 3.4 3.3 5.2" />
        </svg>
      );
    case "验证": // 曲线
      return (
        <svg {...common}>
          <path d="M1.5 13.5h13" />
          <path d="M1.5 13.5V2" />
          <path d="M2.5 11l3-4 3 2.5 4.5-6" />
        </svg>
      );
    case "辨识": // 靶心 + 十字
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="5.5" />
          <circle cx="8" cy="8" r="1.8" />
          <path d="M8 0.8v2M8 13.2v2M0.8 8h2M13.2 8h2" />
        </svg>
      );
    case "部署": // 插头/端口
      return (
        <svg {...common}>
          <path d="M5 2v4M11 2v4" />
          <path d="M3 6h10v2.5a5 5 0 0 1-5 5 5 5 0 0 1-5-5V6z" />
          <path d="M8 13.5V15" />
        </svg>
      );
    case "监控": // 仪表盘：底槽 + 指针
      return (
        <svg {...common}>
          <path d="M2.4 11.2a5.8 5.8 0 0 1 11.2 0" />
          <path d="M8 11.2 10.6 7.4" />
          <circle cx="8" cy="11.2" r="0.9" fill="currentColor" stroke="none" />
          <path d="M2.2 13.4h11.6" />
        </svg>
      );
    case "诊断": // 听诊器/放大镜 + 勾
      return (
        <svg {...common}>
          <circle cx="7" cy="7" r="4.6" />
          <path d="M10.4 10.4 14 14" />
          <path d="M5.2 7l1.3 1.3L9 5.8" />
        </svg>
      );
    case "插件": // 拼图块
      return (
        <svg {...common}>
          <path d="M3 6.5h2.2a1.8 1.8 0 1 1 3.6 0H11v2.2a1.8 1.8 0 1 0 0 3.6V14.5H3z" />
          <path d="M11 8.7h2v2.2a1.8 1.8 0 1 0 0 3.6v.5" />
        </svg>
      );
    case "外观": // 调色盘
      return (
        <svg {...common}>
          <path d="M8 1.8a6.2 6.2 0 0 0 0 12.4c1 0 1.6-.7 1.6-1.5 0-.5-.2-.8-.5-1.1-.3-.3-.5-.6-.5-1 0-.8.6-1.4 1.5-1.4h1A2.9 2.9 0 0 0 14 6.3C14 3.8 11.3 1.8 8 1.8z" />
          <circle cx="5.2" cy="6.4" r="0.9" fill="currentColor" stroke="none" />
          <circle cx="8.4" cy="4.8" r="0.9" fill="currentColor" stroke="none" />
          <circle cx="11" cy="7.6" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      );
    case "帮助": // 问号
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6.2" />
          <path d="M5.9 6.1A2.2 2.2 0 0 1 8.2 4c1.5 0 2.5.8 2.5 2.1 0 1.1-.6 1.6-1.5 2.2-.8.5-1.2 1-1.2 2" />
          <circle cx="8" cy="12.5" r="0.7" fill="currentColor" stroke="none" />
        </svg>
      );
    case "关于": // i
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6.2" />
          <path d="M8 7.2v5" />
          <circle cx="8" cy="4.6" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      );
    default:
      return null;
  }
}

function Grid({
  name: name,
  shortName: shortName,
  description: description,
  current: current,
  onPress: onPress,
  shortcut: shortcut,
}: {
  name: StepId;
  shortName: string;
  description: string;
  current: boolean;
  onPress: () => void;
  shortcut?: number;
}) {
  return (
    <button
      type="button"
      onClick={onPress}
      aria-current={current ? "step" : undefined}
      aria-label={`${shortName} —— ${description}`}
      title={shortcut ? `${description} (${shortcut})` : description}
      className="activity-cell relative flex h-[46px] w-full flex-col items-center justify-center gap-0.5"
      style={{
        color: current ? "var(--fg)" : "var(--fg-dim)",
        background: current ? "var(--bg-frame-on)" : "transparent",
        borderLeft: `2px solid ${current ? "var(--grab)" : "transparent"}`,
      }}
    >
      <Icon name={name} />
      {/*
        ★ 图标下面要有**可见的短名**：只有图标 + `title` 的话，
          ① 要悬停才知道是什么；② 页面上根本找不到"部署"这两个字
          （`CONVENTIONS.md` 要求诚实标注未接入，标注得先能被看到）。
          短名走 `取(步骤.名键)`，所以它跟着语言切。
      */}
      <span className="text-[9px] leading-none" aria-hidden="true">
        {shortName}
      </span>
    </button>
  );
}

function GroupTitle({ label: label }: { label: string }) {
  return (
    <div className="activity-group" aria-hidden="true">
      {label}
    </div>
  );
}

export function ActivityBar({ current: current, sidebarOpen: sidebarOpen, onStepSelect: onStepSelect }: ActivityBarProps) {
  const t = useTranslation();

  const renderGroup = (group: typeof TASK_STEPS, shortcutStart?: number): ReactNode =>
    group.map((s, i) => (
      <Grid
        key={s.id}
        name={s.id}
        shortName={t(s.nameKey)}
        description={t(s.descriptionKey)}
        current={current === s.id && sidebarOpen}
        onPress={() => onStepSelect(s.id)}
        shortcut={shortcutStart === undefined ? undefined : shortcutStart + i}
      />
    ));

  return (
    <nav
      aria-label={t("活动栏.标题")}
      aria-orientation="vertical"
      className="flex h-full w-12 flex-none flex-col justify-between overflow-hidden"
      style={{ background: "var(--bg-menu)", borderRight: "1px solid var(--border)" }}
    >
      <div role="toolbar" aria-label={t("活动栏.步骤编组")} aria-orientation="vertical">
        <GroupTitle label={t("活动栏.流程组")} />
        {renderGroup(TASK_STEPS, 1)}
        <div className="activity-divider" />
        <GroupTitle label={t("活动栏.运行组")} />
        {renderGroup(RUN_STEPS)}
      </div>
      <div role="toolbar" aria-label={t("活动栏.底部编组")} aria-orientation="vertical">
        <div className="activity-divider" />
        <GroupTitle label={t("活动栏.信息组")} />
        {renderGroup(FOOTER_STEPS)}
      </div>
    </nav>
  );
}
