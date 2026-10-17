/**
 * 数值表.tsx —— 带单位的键值表 / 通用小表格。
 *
 * 两个用法，一个实现：
 *   · `数值表`：键 → 值（值可带单位、可选等宽）。侧栏里那些"当前模型 / 当前项目"
 *     全是它的实例。
 *   · `小表格`：真表头 + 多行多列（参数表、曲线图例、主题速率表用）。
 *
 * 三条原则：
 *   ① 值缺失显示 `--`（`数()` 的约定），**不显示 0** —— 0 和"没有"是两件事。
 *   ② 数字用 `tabular-nums` 等宽，刷新时不抖。
 *   ③ 单位单独一列/一段小字，不硬拼进数值里（否则没法对齐、也没法复制纯数字）。
 */
import type { ReactNode } from "react";
import { 数 } from "../视图/文案";

/** 等宽数字：有值就格式化，没值给 `--` */
export function 数值文本({
  值,
  位 = 3,
  单位,
  符号 = false,
}: {
  值?: number | null;
  位?: number;
  单位?: string;
  符号?: boolean;
}) {
  const 文本 = 值 === undefined || 值 === null || !Number.isFinite(值) ? "--" : 数值(值, 位, 符号);
  return (
    <span className="等宽">
      {文本}
      {单位 && 文本 !== "--" ? <span className="text-dim"> {单位}</span> : null}
    </span>
  );
}

function 数值(值: number, 位: number, 符号: boolean): string {
  const 基 = 数(值, 位);
  return 符号 && 值 >= 0 ? `+${基}` : 基;
}

export interface 数值行 {
  键: string;
  值: ReactNode;
  /** 值的单位（会以小字跟在后面，不进 ReactNode 的字符串） */
  单位?: string;
  /** 值的纯文本（给 title 与复制用；有它才做悬停提示） */
  纯文本?: string;
  /** 这一行是"没有值"的诚实说明（如「未接入」），用弱色显示 */
  弱?: boolean;
}

export interface 数值表参数 {
  行: 数值行[];
   /** 没数据时的说明；**空表不编内容** */
  空?: string;
  /** 键列宽（Tailwind 宽度类，默认自适应） */
  键宽?: string;
}

export function 数值表({ 行, 空, 键宽 }: 数值表参数) {
  if (!行.length) {
    return <div className="text-dim">{空 ?? "--"}</div>;
  }
  return (
    <table className="w-full border-collapse">
      <tbody>
        {行.map((r) => (
          <tr key={r.键} className="align-top">
            <th
              scope="row"
              className={`pr-2 text-left font-normal text-dim ${键宽 ?? ""}`}
              style={{ whiteSpace: "nowrap" }}
            >
              {r.键}
            </th>
            <td
              className={`break-all text-right ${r.弱 ? "text-dim" : ""}`}
              title={r.纯文本}
            >
              {r.值}
              {r.单位 ? <span className="text-dim"> {r.单位}</span> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export interface 列 {
  标题: ReactNode;
  /** 单元格渲染 */
  格: (行: Record<string, unknown>, 序: number) => ReactNode;
  /** 用键取值（与 `格` 二选一，`格` 优先） */
  键?: string;
  数字?: boolean;
  宽度?: string;
}

export interface 小表格参数 {
  列: 列[];
  行: Record<string, unknown>[];
  空?: string;
  行键?: (行: Record<string, unknown>, 序: number) => string;
}

export function 小表格({ 列, 行, 空, 行键 }: 小表格参数) {
  if (!行.length) {
    return <div className="text-dim">{空 ?? "--"}</div>;
  }
  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            {列.map((c, i) => (
              <th
                key={i}
                scope="col"
                className={`border-b px-1.5 py-1 text-left font-normal text-dim ${c.宽度 ?? ""}`}
                style={{ background: "var(--bg-table-head)" }}
              >
                {c.标题}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {行.map((r, 序) => (
            <tr key={行键 ? 行键(r, 序) : 序} style={{ background: 序 % 2 ? "var(--bg-row-alt)" : undefined }}>
              {列.map((c, i) => (
                <td
                  key={i}
                  className={`border-b px-1.5 py-1 align-top ${c.数字 ? "等宽 text-right" : ""}`}
                >
                  {c.格 ? c.格(r, 序) : 文本(r[c.键 ?? ""])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 把任意后端值渲染成一行文本（对象/数组退化成 JSON，不猜结构） */
export function 文本(值: unknown): string {
  if (值 === undefined || 值 === null) return "--";
  if (typeof 值 === "number") return 数(值, 4);
  if (typeof 值 === "string") return 值;
  if (typeof 值 === "boolean") return 值 ? "true" : "false";
  try {
    return JSON.stringify(值);
  } catch {
    return String(值);
  }
}
