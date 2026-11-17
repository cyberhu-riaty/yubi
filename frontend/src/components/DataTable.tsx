/**
 * DataTable.tsx —— 带单位的键值表 / 通用小表格。
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
import { formatNumber } from "../views/i18n";

/** 等宽数字：有值就格式化，没值给 `--` */
export function NumericText({
  value: value,
  digits: digits = 3,
  unit: unit,
  signed: signed = false,
}: {
  value?: number | null;
  digits?: number;
  unit?: string;
  signed?: boolean;
}) {
  const text = value === undefined || value === null || !Number.isFinite(value) ? "--" : formatNumericValue(value, digits, signed);
  return (
    <span className="monospace">
      {text}
      {unit && text !== "--" ? <span className="text-dim"> {unit}</span> : null}
    </span>
  );
}

function formatNumericValue(value: number, digits: number, signed: boolean): string {
  const formatted = formatNumber(value, digits);
  return signed && value >= 0 ? `+${formatted}` : formatted;
}

export interface ValueRow {
  key: string;
  value: ReactNode;
  /** 值的单位（会以小字跟在后面，不进 ReactNode 的字符串） */
  unit?: string;
  /** 值的纯文本（给 title 与复制用；有它才做悬停提示） */
  plainText?: string;
  /** 这一行是"没有值"的诚实说明（如「未接入」），用弱色显示 */
  muted?: boolean;
  /** 键名/取值的解释（悬停提示；用于 nq、nu 这类缩写） */
  hint?: string;
}

export interface ValueTableProps {
  rows: ValueRow[];
   /** 没数据时的说明；**空表不编内容** */
  emptyText?: string;
  /** 键列宽（Tailwind 宽度类，默认自适应） */
  keyWidth?: string;
}

export function ValueTable({ rows: rows, emptyText: emptyText, keyWidth: keyWidth }: ValueTableProps) {
  if (!rows.length) {
    return <div className="text-dim">{emptyText ?? "--"}</div>;
  }
  return (
    <table className="data-table w-full border-collapse">
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className="align-top">
            <th
              scope="row"
              className={`pr-2 text-left font-normal text-dim ${keyWidth ?? ""}`}
              style={{ whiteSpace: "nowrap" }}
              title={r.hint}
            >
              {r.key}
            </th>
            <td
              className={`break-all text-right ${r.muted ? "text-dim" : ""}`}
              title={r.plainText ?? r.hint}
            >
              {r.value}
              {r.unit ? <span className="text-dim"> {r.unit}</span> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export interface TableColumn {
  title: ReactNode;
  /** 单元格渲染 */
  render: (rows: Record<string, unknown>, index: number) => ReactNode;
  /** 用键取值（与 `格` 二选一，`格` 优先） */
  key?: string;
  numeric?: boolean;
  width?: string;
}

export interface DataTableProps {
  columns: TableColumn[];
  rows: Record<string, unknown>[];
  emptyText?: string;
  rowKey?: (rows: Record<string, unknown>, index: number) => string;
}

export function DataTable({ columns: columns, rows: rows, emptyText: emptyText, rowKey: rowKey }: DataTableProps) {
  if (!rows.length) {
    return <div className="text-dim">{emptyText ?? "--"}</div>;
  }
  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th
                key={i}
                scope="col"
                className={`border-b px-1.5 py-1 text-left font-normal text-dim whitespace-nowrap ${c.width ?? ""}`}
                style={{ background: "var(--bg-table-head)" }}
              >
                {c.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, index) => (
            <tr key={rowKey ? rowKey(r, index) : index} style={{ background: index % 2 ? "var(--bg-row-alt)" : undefined }}>
              {columns.map((c, i) => (
                <td
                  key={i}
                  className={`border-b px-1.5 py-1 align-top ${c.numeric ? "monospace text-right" : ""}`}
                >
                  {c.render ? c.render(r, index) : formatValue(r[c.key ?? ""])}
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
export function formatValue(value: unknown): string {
  if (value === undefined || value === null) return "--";
  if (typeof value === "number") return formatNumber(value, 4);
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
