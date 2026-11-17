/**
 * Sidebar.tsx —— 上下文侧栏：画**当前步骤**的内容。
 *
 * 这就是"任务流只换左侧上下文"的落点：这里换成哪一步的内容，中区 3D 视口都不动。
 * 每一步的内容在 `视图/` 里，侧栏只负责：
 *   · 顶部一行"当前步骤"（否则用户不知道自己在第几步）
 *   · 把步骤映射到视图组件
 *
 * 注意**没有**任何数据逻辑：视图自己去 `数据/store.ts` 订阅自己关心的那一小块
 * （`CONVENTIONS.md` §二：不把整个 state 往下传）。
 */
import type { StepId } from "./task_flow";
import { getStep } from "./task_flow";
import { ContextBar } from "./ContextBar";
import { useTranslation } from "../views/i18n";
import { Button } from "../components/Button";
import { Tag } from "../components/Badge";
import { DefineView as DefineView } from "../views/DefineView";
import { PlanningView as PlanningView } from "../views/PlanningView";
import { ValidateView as ValidateView } from "../views/ValidateView";
import { IdentificationView as IdentificationView } from "../views/IdentificationView";
import { DeploymentView as DeploymentView } from "../views/DeploymentView";
import { MonitorView as MonitorView } from "../views/MonitorView";
import { DiagnosticsView as DiagnosticsView } from "../views/DiagnosticsView";
import { PluginView as PluginView } from "../views/PluginView";
import { AppearanceView as AppearanceView } from "../views/AppearanceView";
import { HelpView as HelpView } from "../views/HelpView";
import { AboutView as AboutView } from "../views/AboutView";

export interface SidebarProps {
  step: StepId;
  open: boolean;
  onCollapse: () => void;
}

function renderView(step: StepId) {
  switch (step) {
    case "定义":
      return <DefineView />;
    case "规划":
      return <PlanningView />;
    case "验证":
      return <ValidateView />;
    case "辨识":
      return <IdentificationView />;
    case "部署":
      return <DeploymentView />;
    case "监控":
      return <MonitorView />;
    case "诊断":
      return <DiagnosticsView />;
    case "插件":
      return <PluginView />;
    case "外观":
      return <AppearanceView />;
    case "帮助":
      return <HelpView />;
    case "关于":
      return <AboutView />;
    default:
      return null;
  }
}

/** 哪些步骤是"还没接上"的 —— 标题旁边挂一个诚实的徽标 */
/**
 * 哪些步骤还「没接上」—— 标题旁边挂一个诚实的徽标。
 *
 * ★ 「部署」已经从这张表里拿掉了：它现在**能真导出**一个部署包
 *   （项目配置 + 算法源码 + 模型清单，后端真写文件）。
 *   但「没有真机连接」这件事仍然写在视图第一屏 —— 两件事别混：
 *   **能导出** ≠ **能连真机**。
 *
 * ★ 只剩「规划」（轨迹规划）还没做。
 */
const incomplete: Record<string, "待接入" | "未实现" | "未接入"> = {
  // ★ 九项已全部接上。这里留空是**有意的**：一张空的"未完成表"比删掉它更能说明状态。
  //   （「规划」已能真规划；「部署」能真导出包；它们各自的限制写在视图里，不靠这张表表达。）
};

export function Sidebar({ step: step, open: open, onCollapse: onCollapse }: SidebarProps) {
  const t = useTranslation();
  const currentStep = getStep(step);

  if (!open) {
    return (
      <aside
        aria-label={t("侧栏.上下文")}
        className="flex h-full items-start justify-center overflow-hidden"
        style={{ background: "var(--bg-menu)" }}
      >
        <span className="sr-only">{t("侧栏.收起说明")}</span>
      </aside>
    );
  }

  return (
    <aside
      aria-label={t("侧栏.上下文")}
      className="flex h-full min-w-0 flex-col overflow-hidden"
      style={{ background: "var(--bg-menu)" }}
    >
      <header
        className="flex flex-none items-center gap-1.5 px-2.5 py-1.5"
        style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-title)" }}
      >
        {/* 应用名：整个单窗口里它只在这里出现一次（`<title>` 在窗口里看不见） */}
        <span className="flex-none text-dim" title={t("应用.副标题")} style={{ fontWeight: 600 }}>
          {t("应用.名称")}
        </span>
        <span aria-hidden="true" className="flex-none text-dim">
          ·
        </span>
        <span className="truncate">{t(currentStep.nameKey)}</span>
        {incomplete[step] ? <Tag tone="notice">{t(`通用.${incomplete[step]}` as const)}</Tag> : null}
        <span className="flex-1" />
        <Button size="small" variant="ghost" onPress={onCollapse} title={t("侧栏.收起")}>
          ‹
        </Button>
      </header>
      <ContextBar />
      {/* ★ 卡片化之后这里必须有间距：段与段紧贴时，圆角边框会互相"咬"在一起，
             看起来比不分卡片还乱。8px + 左右内边距 = 图二那种"卡片浮在桌面上的"感觉。 */}
      <div
        className={`sidebar-scroll flex min-h-0 flex-1 flex-col gap-2 p-2 ${
          step === "定义" ? "overflow-hidden" : "overflow-y-auto"
        }`}
      >
        {renderView(step)}
      </div>
    </aside>
  );
}
