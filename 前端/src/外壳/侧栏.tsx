/**
 * 侧栏.tsx —— 上下文侧栏：画**当前步骤**的内容。
 *
 * 这就是"任务流只换左侧上下文"的落点：这里换成哪一步的内容，中区 3D 视口都不动。
 * 每一步的内容在 `视图/` 里，侧栏只负责：
 *   · 顶部一行"当前步骤"（否则用户不知道自己在第几步）
 *   · 把步骤映射到视图组件
 *
 * 注意**没有**任何数据逻辑：视图自己去 `数据/仓库.ts` 订阅自己关心的那一小块
 * （`约定.md` §二：不把整个 state 往下传）。
 */
import type { 步骤id } from "./任务流";
import { 取步骤 } from "./任务流";
import { 上下文条 } from "./上下文条";
import { use取 } from "../视图/文案";
import { 按钮 } from "../组件/按钮";
import { 标签 } from "../组件/标签";
import { 定义视图 } from "../视图/定义视图";
import { 规划视图 } from "../视图/规划视图";
import { 验证视图 } from "../视图/验证视图";
import { 辨识视图 } from "../视图/辨识视图";
import { 部署视图 } from "../视图/部署视图";
import { 监控视图 } from "../视图/监控视图";
import { 诊断视图 } from "../视图/诊断视图";
import { 插件视图 } from "../视图/插件视图";
import { 外观视图 } from "../视图/外观视图";
import { 帮助视图 } from "../视图/帮助视图";
import { 关于视图 } from "../视图/关于视图";

export interface 侧栏参数 {
  步骤: 步骤id;
  开: boolean;
  on收起: () => void;
}

function 画视图(步骤: 步骤id) {
  switch (步骤) {
    case "定义":
      return <定义视图 />;
    case "规划":
      return <规划视图 />;
    case "验证":
      return <验证视图 />;
    case "辨识":
      return <辨识视图 />;
    case "部署":
      return <部署视图 />;
    case "监控":
      return <监控视图 />;
    case "诊断":
      return <诊断视图 />;
    case "插件":
      return <插件视图 />;
    case "外观":
      return <外观视图 />;
    case "帮助":
      return <帮助视图 />;
    case "关于":
      return <关于视图 />;
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
const 未完成: Record<string, "待接入" | "未实现" | "未接入"> = {
  // ★ 九项已全部接上。这里留空是**有意的**：一张空的"未完成表"比删掉它更能说明状态。
  //   （「规划」已能真规划；「部署」能真导出包；它们各自的限制写在视图里，不靠这张表表达。）
};

export function 侧栏({ 步骤, 开, on收起 }: 侧栏参数) {
  const t = use取();
  const 当前步骤 = 取步骤(步骤);

  if (!开) {
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
        <span className="truncate">{t(当前步骤.名键)}</span>
        {未完成[步骤] ? <标签 语气="警示">{t(`通用.${未完成[步骤]}` as const)}</标签> : null}
        <span className="flex-1" />
        <按钮 尺寸="小" 种类="幽灵" on按下={on收起} title={t("侧栏.收起")}>
          ‹
        </按钮>
      </header>
      <上下文条 />
      {/* ★ 卡片化之后这里必须有间距：段与段紧贴时，圆角边框会互相"咬"在一起，
             看起来比不分卡片还乱。8px + 左右内边距 = 图二那种"卡片浮在桌面上的"感觉。 */}
      <div
        className={`侧栏内容滚动 flex min-h-0 flex-1 flex-col gap-2 p-2 ${
          步骤 === "定义" ? "overflow-hidden" : "overflow-y-auto"
        }`}
      >
        {画视图(步骤)}
      </div>
    </aside>
  );
}
