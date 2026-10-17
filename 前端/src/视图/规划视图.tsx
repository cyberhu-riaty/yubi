/**
 * 规划视图.tsx —— 任务流第 2 步：轨迹规划。
 *
 * 这一格是**故意空着的**，而且要把"为什么空着"写在脸上：
 *   · 契约（`生成/契约.ts`）里没有任何规划主题 —— 上行没有规划请求，
 *     下行没有规划结果。没有数据源，画出来的路点 / 曲线 / 包络必然是编的。
 *   · 规格里判定"真规划器 vs 原型"的判据是**能不能回答约束满足率与贴合误差**。
 *     答不出来的原型画得再漂亮也是假的 —— 所以这里不画。
 *
 * 于是这一格的唯一内容就是：未实现 + 将来会包含什么 + 要什么才能做。
 * 唯一的"数字"是 `上行元.length`（现在真有几条上行命令），它是从生成的契约里数出来的。
 */
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { 数值表, type 数值行 } from "../组件/数值表";
import { 上行元 } from "@生成/契约";
import { use取 } from "./文案";

const 将包含键 = [
  "规划.路点",
  "规划.关节约束",
  "规划.MVC",
  "规划.剖面",
  "规划.约束满足率",
] as const;

export function 规划视图() {
  const t = use取();

  const 现况行: 数值行[] = [
    {
      键: t("规划.上行现有"),
      值: <span className="等宽">{上行元.length}</span>,
      纯文本: 上行元.map((m) => m.名).join("  "),
    },
    {
      键: t("关于.下行"),
      值: <span className="等宽">{t("规划.结果主题")}</span>,
      弱: true,
    },
  ];

  return (
    <div>
      <可折叠区块 标题={t("规划.未实现标题")} 徽标={<标签 语气="警示">{t("通用.未实现")}</标签>}>
        <div className="未接入">
          <p>{t("规划.未实现说明")}</p>
          <div className="mt-2">
            <数值表 行={现况行} />
          </div>
          <p className="mt-2 text-[0.9em]">{t("规划.要什么")}</p>
        </div>
      </可折叠区块>

      <可折叠区块 标题={t("规划.将包含")} 徽标={<span className="等宽">{将包含键.length}</span>}>
        <ul className="space-y-1">
          {将包含键.map((k) => (
            <li key={k} className="flex gap-1.5">
              <span aria-hidden="true" className="等宽 text-dim">
                ·
              </span>
              <span>{t(k)}</span>
            </li>
          ))}
        </ul>
      </可折叠区块>

      <可折叠区块 标题={t("规划.为什么空着")} 默认开={false}>
        <p className="text-dim">{t("规划.为什么这样")}</p>
      </可折叠区块>
    </div>
  );
}
