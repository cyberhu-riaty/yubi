/**
 * task_flow.ts —— 左侧上下文侧栏的"步骤"定义。
 *
 * 这是整个外壳的骨架约定（`CONVENTIONS.md` §三 那一句"任务流只换左侧上下文"的落点）：
 *   · 5 个任务步骤 + 3 个运行条目 + 3 个底部条目（外观/帮助/关于）
 *   · 每一步只是**一个 id + 一句文案键**，具体画什么在 `视图/` 里
 *   · 中区 3D 视口**不属于**任何一步 —— 它常驻（见 `外壳/MainArea.tsx`）
 *
 * 为什么把这里做成数据而不是写死两个数组：
 *   活动栏、侧栏、键盘快捷键（数字键跳步）都要用同一份顺序，
 *   写两份必然漂移（"加了一步忘了改另一处"是这类外壳最常见的 bug）。
 */
import type { TranslationKey } from "../views/i18n";

export type StepId =
  | "定义"
  | "规划"
  | "验证"
  | "辨识"
  | "部署"
  | "监控"
  | "诊断"
  | "插件"
  | "外观"
  | "帮助"
  | "关于";

export interface Step {
  id: StepId;
  /** 活动栏/侧栏的标题文案键 */
  nameKey: TranslationKey;
  /** 悬停说明的文案键 */
  descriptionKey: TranslationKey;
  /**
   * 归在哪一组：
   *   任务 = 按顺序做设计（定义→规划→验证→辨识→部署）
   *   运行 = 跑起来之后才看的东西（监控）—— 插在任务与底部之间，
   *          因为"监控"不属于设计流程，混进上面会让人以为它是第 6 步
   *   底部 = 设置与信息
   */
  group: "任务" | "运行" | "底部";
}

/** 顺序就是活动栏从上到下的顺序（也决定 Ctrl/Cmd+1..5 的编号） */
export const STEP_TABLE: Step[] = [
  { id: "定义", nameKey: "步骤.定义", descriptionKey: "步骤.定义.一句话", group: "任务" },
  { id: "规划", nameKey: "步骤.规划", descriptionKey: "步骤.规划.一句话", group: "任务" },
  { id: "验证", nameKey: "步骤.验证", descriptionKey: "步骤.验证.一句话", group: "任务" },
  { id: "辨识", nameKey: "步骤.辨识", descriptionKey: "步骤.辨识.一句话", group: "任务" },
  { id: "部署", nameKey: "步骤.部署", descriptionKey: "步骤.部署.一句话", group: "任务" },
  { id: "监控", nameKey: "步骤.监控", descriptionKey: "步骤.监控.一句话", group: "运行" },
  { id: "诊断", nameKey: "步骤.诊断", descriptionKey: "步骤.诊断.一句话", group: "运行" },
  { id: "插件", nameKey: "步骤.插件", descriptionKey: "步骤.插件.一句话", group: "运行" },
  { id: "外观", nameKey: "步骤.外观", descriptionKey: "步骤.外观.一句话", group: "底部" },
  { id: "帮助", nameKey: "步骤.帮助", descriptionKey: "步骤.帮助.一句话", group: "底部" },
  { id: "关于", nameKey: "步骤.关于", descriptionKey: "步骤.关于.一句话", group: "底部" },
];

export const TASK_STEPS = STEP_TABLE.filter((s) => s.group === "任务");
export const RUN_STEPS = STEP_TABLE.filter((s) => s.group === "运行");
export const FOOTER_STEPS = STEP_TABLE.filter((s) => s.group === "底部");

export function getStep(id: StepId): Step {
  const find = STEP_TABLE.find((s) => s.id === id);
  if (!find) throw new Error(`任务流里没有这一步：${id}`);
  return find;
}
