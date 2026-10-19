/**
 * 控制台.tsx —— 底部三页签：输出 / 事件 / 问题。
 *
 * 数据只有两个来源，都是真的：
 *   ① `数据/日志.ts` —— 连接状态、握手、回执、后端错误、前端异常（逐条留痕）
 *   ② `数据/仓库.ts` —— 主题计数与速率（每秒实测差值）
 *
 * 这次针对"日志挤在左栏、横向滚动、找不到重点"的改造：
 *   · 两行一条：第一行时刻/等级/来源/主题，第二行正文；窄面板里不再横向挤。
 *   · 等级/来源下拉筛选 + 复制/导出；问题页签带明确的等级图标和颜色。
 *   · 主题速率默认收起，不再每时每刻占掉日志的高度。
 *   · 「问题」仍按真实连接状态推导；另外把项目装配报告里的「不兼容」也列出来。
 *
 * 「问题」不是装饰：每一条都给出依据。没问题时说"没有发现问题"，
 * 并补一句"这不代表软件没缺陷"—— 一个永远全绿的检查器本身就是假实现。
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  清日志,
  取日志,
  用日志,
  送原生状态,
  记命令发出,
  命令收尾,
  type 日志等级,
  type 日志行,
  type 速率行,
} from "../数据/日志";
import { 标签 } from "../组件/标签";
import { 命令, 用仓库, type 项目状态, type 诊断报告 } from "../数据/仓库";
import { 请求跳步 } from "./跳步";
import { 用节拍 } from "../数据/时钟";
import { 连接键, use取, 时刻 } from "../视图/文案";

export type 控制台页签 = "输出" | "事件" | "问题" | "诊断";

export interface 控制台参数 {
  页签: 控制台页签;
  on换页签: (页: 控制台页签) => void;
  /** 收起抽屉（App 传；不传就不显示收起按钮） */
  on收起?: () => void;
}

/** 等级 → 颜色。颜色只来自主题语义色；文字里同时有符号和等级名。 */
const 等级色: Record<日志等级, string> = {
  信息: "var(--info)",
  注意: "var(--warn)",
  错误: "var(--danger)",
};

const 等级符号: Record<日志等级, string> = { 信息: "●", 注意: "!", 错误: "✗" };
const 等级键: Record<日志等级, "控制台.等级.信息" | "控制台.等级.注意" | "控制台.等级.错误"> = {
  信息: "控制台.等级.信息",
  注意: "控制台.等级.注意",
  错误: "控制台.等级.错误",
};

const 来源键: Record<string, "控制台.来源.连接" | "控制台.来源.握手" | "控制台.来源.回执" | "控制台.来源.错误" | "控制台.来源.前端" | "控制台.来源.控制台" | "控制台.来源.规划" | "控制台.来源.诊断"> = {
  连接: "控制台.来源.连接",
  握手: "控制台.来源.握手",
  回执: "控制台.来源.回执",
  错误: "控制台.来源.错误",
  前端: "控制台.来源.前端",
  控制台: "控制台.来源.控制台",
  规划: "控制台.来源.规划",
  诊断: "控制台.来源.诊断",
};

/** 等级筛选："全部" 或某个等级 */
type 等级筛 = 日志等级 | "全部";
/** 时间筛选：全部 / 最近 N 分钟 */
type 时间筛 = "全部" | 1 | 5 | 15;
const 时间毫秒: Record<Exclude<时间筛, "全部">, number> = { 1: 60_000, 5: 300_000, 15: 900_000 };

async function 复制文本(文本: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(文本);
      return true;
    }
  } catch {
    /* 降级 */
  }
  try {
    const 区 = document.createElement("textarea");
    区.value = 文本;
    区.setAttribute("readonly", "");
    区.style.position = "fixed";
    区.style.opacity = "0";
    document.body.appendChild(区);
    区.select();
    const 成 = document.execCommand("copy");
    document.body.removeChild(区);
    return 成;
  } catch {
    return false;
  }
}

function 行文本(l: 日志行): string {
  const 结构 = [
    l.模块 ? `模块=${l.模块}` : "",
    l.插件 ? `插件=${l.插件}` : "",
    l.关节 !== undefined ? `J${l.关节}` : "",
  ].filter(Boolean).join(" ");
  const 头 = `${时刻(l.墙钟)}\t${l.等级}\t${l.来源}${l.主题 ? `\t${l.主题}` : ""}${结构 ? `\t${结构}` : ""}`;
  return `${头}\n${l.文本}${l.细节 ? `\n${l.细节}` : ""}`;
}

export function 控制台({ 页签, on换页签, on收起 }: 控制台参数) {
  const t = use取();
  const 快照 = 用日志();
  const 连接 = 用仓库((s) => s.连接);
  const 错误 = 用仓库((s) => s.错误);
  const 握手 = 用仓库((s) => s.握手);
  const 项目 = 用仓库((s) => s.项目.数据);
  const 诊断报告 = 用仓库((s) => s.诊断.数据);
  const 节拍 = 用节拍();

  const [等级筛, 设等级筛] = useState<等级筛>("全部");
  const [来源筛, 设来源筛] = useState<string>("全部");
  const [插件筛, 设插件筛] = useState<string>("全部");
  const [主题筛, 设主题筛] = useState<string>("全部");
  const [时间筛, 设时间筛] = useState<时间筛>("全部");
  const [速率开, 设速率开] = useState(false);
  const [跟随, 设跟随] = useState(true);
  const 滚动区 = useRef<HTMLDivElement | null>(null);
  const [操作, 设操作] = useState<{ 文本: string; 好: boolean } | null>(null);
  const 提示定时 = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (提示定时.current !== null) window.clearTimeout(提示定时.current);
    };
  }, []);

  // 原生右列面板的筛选/清空操作回到同一个 Web 控制台 store，
  // 不是再维护一份独立日志。面板收起后，这里的筛选状态仍然保留。
  useEffect(() => {
    const 听 = (e: Event) => {
      const d = (e as CustomEvent<{ 类型?: string; 值?: string }>).detail;
      if (d?.类型 === "筛选") {
        const 值 = d.值;
        if (值 === "全部" || 值 === "信息" || 值 === "注意" || 值 === "错误") {
          设等级筛(值);
        }
      } else if (d?.类型 === "清空") {
        清日志();
      }
    };
    window.addEventListener("驭臂.日志操作", 听);
    return () => window.removeEventListener("驭臂.日志操作", 听);
  }, []);

  const 显示操作 = (文本: string, 好: boolean) => {
    设操作({ 文本, 好 });
    if (提示定时.current !== null) window.clearTimeout(提示定时.current);
    提示定时.current = window.setTimeout(() => 设操作(null), 2000);
  };

  const 来源们 = useMemo(() => {
    const 集 = new Set<string>();
    for (const l of 快照.行) 集.add(l.来源);
    return [...集].sort();
  }, [快照.行]);

  const 插件们 = useMemo(() => {
    const 集 = new Set<string>();
    for (const l of 快照.行) {
      if (l.插件) 集.add(l.插件);
    }
    return [...集].sort();
  }, [快照.行]);

  const 主题们 = useMemo(() => {
    const 集 = new Set<string>();
    for (const l of 快照.行) {
      if (l.主题) 集.add(l.主题);
    }
    return [...集].sort();
  }, [快照.行]);

  const 行们 = useMemo(() => {
    const 时间界 = 时间筛 === "全部" ? Number.POSITIVE_INFINITY : 时间毫秒[时间筛];
    return 快照.行.filter(
      (l) =>
        (等级筛 === "全部" || l.等级 === 等级筛) &&
        (来源筛 === "全部" || l.来源 === 来源筛) &&
        (插件筛 === "全部" || l.插件 === 插件筛) &&
        (主题筛 === "全部" || l.主题 === 主题筛) &&
        (时间界 === Number.POSITIVE_INFINITY || 节拍 - l.墙钟 <= 时间界),
    );
  }, [快照.行, 等级筛, 来源筛, 插件筛, 主题筛, 时间筛, 节拍]);

  const 事件行 = useMemo(
    () => 行们.filter((l) => l.来源 === "连接" || l.来源 === "握手" || l.来源 === "回执"),
    [行们],
  );

  // 原生面板是主日志的镜像：把同一份筛选结果、总数和筛选摘要推过去。
  // 原生面板上的筛选/清空再通过上面的 `驭臂.日志操作` 回到这里。
  useEffect(() => {
    const 摘要 = [
      等级筛 !== "全部" ? `等级 ${等级筛}` : "",
      来源筛 !== "全部" ? `来源 ${来源筛}` : "",
      插件筛 !== "全部" ? `插件 ${插件筛}` : "",
      主题筛 !== "全部" ? `主题 ${主题筛}` : "",
      时间筛 !== "全部" ? `时间 ${时间筛}` : "",
    ]
      .filter(Boolean)
      .join(" · ") || "无筛选";
    送原生状态(行们, 快照.行.length, 摘要, 等级筛);
  }, [行们, 快照.行.length, 等级筛, 来源筛, 插件筛, 主题筛, 时间筛]);

  const 问题 = 用问题(连接, 错误, 握手, 快照.行, 项目);
  const 页签们: 控制台页签[] = ["输出", "事件", "问题", "诊断"];
  const 当前行 = 页签 === "事件" ? 事件行 : 页签 === "诊断" ? [] : 行们;
  const 问题有错误 = 问题.some((p) => p.等级 === "错误");
  const 诊断异常 =
    !!诊断报告 &&
    !诊断报告.运行中 &&
    (!!诊断报告.出错 ||
      ((诊断报告.总数 ?? 0) > 0 && (诊断报告.通过 ?? 0) < (诊断报告.总数 ?? 0)));
  const 筛选空 = 页签 === "输出" && 行们.length === 0 && 快照.行.length > 0;

  // 新日志到达时跟随到底部；用户向上滚动后暂停，避免抢滚动条。
  useEffect(() => {
    if (!跟随 || 页签 === "诊断") return;
    const 区 = 滚动区.current;
    if (区) 区.scrollTop = 区.scrollHeight;
  }, [行们.length, 事件行.length, 页签, 跟随]);

  const 滚动时 = () => {
    const 区 = 滚动区.current;
    if (!区) return;
    const 贴底 = 区.scrollHeight - 区.scrollTop - 区.clientHeight < 24;
    if (贴底 !== 跟随) 设跟随(贴底);
  };

  const 恢复跟随 = () => {
    设跟随(true);
    const 区 = 滚动区.current;
    if (区) 区.scrollTop = 区.scrollHeight;
  };

  const 复制可见 = async () => {
    if (!当前行.length) {
      显示操作(t("控制台.复制失败"), false);
      return;
    }
    const 成 = await 复制文本(当前行.map(行文本).join("\n\n"));
    显示操作(
      成 ? t("控制台.复制成功", { 数量: 当前行.length }) : t("控制台.复制失败"),
      成,
    );
  };

  const 导出 = () => {
    if (!当前行.length) {
      显示操作(t("控制台.复制失败"), false);
      return;
    }
    try {
      const 体 = new Blob([当前行.map(行文本).join("\n\n")], {
        type: "text/plain;charset=utf-8",
      });
      const 地址 = URL.createObjectURL(体);
      const 链 = document.createElement("a");
      const 时 = new Date();
      const 补 = (n: number) => String(n).padStart(2, "0");
      链.href = 地址;
      链.download = `驭臂日志-${时.getFullYear()}${补(时.getMonth() + 1)}${补(时.getDate())}-${补(时.getHours())}${补(时.getMinutes())}${补(时.getSeconds())}.txt`;
      document.body.appendChild(链);
      链.click();
      document.body.removeChild(链);
      window.setTimeout(() => URL.revokeObjectURL(地址), 1000);
      显示操作(t("控制台.导出成功", { 数量: 当前行.length }), true);
    } catch {
      显示操作(t("控制台.复制失败"), false);
    }
  };

  return (
    <section
      aria-label={t("控制台.标题")}
      className="控制台 flex h-full min-h-0 flex-col"
      style={{ background: "var(--bg-menu)" }}
    >
      <div
        className="控制台头 flex flex-none items-center gap-1 px-1.5 py-1"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div role="tablist" aria-label={t("控制台.标题")} className="flex items-center gap-0.5">
          {页签们.map((p) => {
            const 选中 = p === 页签;
            const 徽标 =
              p === "问题"
                ? 问题.length
                : p === "事件"
                  ? 事件行.length
                  : p === "诊断"
                    ? 诊断报告?.运行中
                      ? "…"
                      : 诊断报告
                        ? `${诊断报告.通过 ?? 0}/${诊断报告.总数 ?? 0}`
                        : ""
                    : 行们.length;
            return (
              <button
                key={p}
                role="tab"
                type="button"
                aria-selected={选中}
                onClick={() => on换页签(p)}
                className="控制台页签 flex items-center gap-1 px-2 py-1"
                style={{
                  background: 选中 ? "var(--bg-tab-on)" : "transparent",
                  color: 选中
                    ? "var(--fg)"
                    : (p === "问题" && 问题有错误) || (p === "诊断" && 诊断异常)
                      ? "var(--danger)"
                      : "var(--fg-dim)",
                  borderBottom: `2px solid ${选中 ? "var(--grab)" : "transparent"}`,
                }}
              >
                <span>{t(`控制台.页签.${p}` as const)}</span>
                <span
                  className="等宽 text-[0.8em]"
                  style={{
                    color:
                      (p === "问题" && 问题有错误) || (p === "诊断" && 诊断异常)
                        ? "var(--danger)"
                        : undefined,
                  }}
                >
                  {徽标 || ""}
                </span>
              </button>
            );
          })}
        </div>

        <span className="flex-1" />

        {页签 !== "诊断" ? (
          <>
            <button type="button" className="控制台动作" onClick={() => void 复制可见()} title={t("控制台.复制")}>
              {t("控制台.复制")}
            </button>
            <button type="button" className="控制台动作" onClick={导出} title={t("控制台.导出")}>
              {t("控制台.导出")}
            </button>
          </>
        ) : null}
        {页签 !== "诊断" ? (
          <button type="button" className="控制台动作" onClick={清日志} title={t("控制台.清空不了")}>
            {t("控制台.清空")}
          </button>
        ) : null}
        {on收起 ? (
          <button type="button" className="控制台动作" onClick={on收起} title={t("控制台.收起")}>
            ⌄
          </button>
        ) : null}
      </div>

      <div
        className="控制台筛选 flex flex-none items-center gap-1.5 px-1.5 pb-1"
        style={{ display: 页签 === "诊断" ? "none" : undefined }}
      >
        <label className="筛选器">
          <span className="sr-only">{t("控制台.筛选.等级")}</span>
          <select
            aria-label={t("控制台.筛选.等级")}
            value={等级筛}
            onChange={(e) => 设等级筛(e.target.value as 等级筛)}
          >
            <option value="全部">{t("控制台.筛选.全部等级")}</option>
            <option value="信息">{t("控制台.等级.信息")}</option>
            <option value="注意">{t("控制台.等级.注意")}</option>
            <option value="错误">{t("控制台.等级.错误")}</option>
          </select>
        </label>
        <label className="筛选器">
          <span className="sr-only">{t("控制台.筛选.来源")}</span>
          <select
            aria-label={t("控制台.筛选.来源")}
            value={来源筛}
            onChange={(e) => 设来源筛(e.target.value)}
          >
            <option value="全部">{t("控制台.筛选.全部")}</option>
            {来源们.map((s) => (
              <option key={s} value={s}>
                {来源键[s] ? t(来源键[s]) : s}
              </option>
            ))}
          </select>
        </label>
        <label className="筛选器" title={t("控制台.筛选.插件")}>
          <span className="sr-only">{t("控制台.筛选.插件")}</span>
          <select
            aria-label={t("控制台.筛选.插件")}
            value={插件筛}
            onChange={(e) => 设插件筛(e.target.value)}
          >
            <option value="全部">{t("控制台.筛选.全部插件")}</option>
            {插件们.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="筛选器" title={t("控制台.筛选.主题")}>
          <span className="sr-only">{t("控制台.筛选.主题")}</span>
          <select
            aria-label={t("控制台.筛选.主题")}
            value={主题筛}
            onChange={(e) => 设主题筛(e.target.value)}
          >
            <option value="全部">{t("控制台.筛选.全部主题")}</option>
            {主题们.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="筛选器" title={t("控制台.筛选.时间")}>
          <span className="sr-only">{t("控制台.筛选.时间")}</span>
          <select
            aria-label={t("控制台.筛选.时间")}
            value={String(时间筛)}
            onChange={(e) => 设时间筛(e.target.value === "全部" ? "全部" : (Number(e.target.value) as 1 | 5 | 15))}
          >
            <option value="全部">{t("控制台.筛选.全部时间")}</option>
            <option value="1">{t("控制台.时间.1")}</option>
            <option value="5">{t("控制台.时间.5")}</option>
            <option value="15">{t("控制台.时间.15")}</option>
          </select>
        </label>
        <button
          type="button"
          className="控制台动作"
          aria-pressed={速率开}
          onClick={() => 设速率开((旧) => !旧)}
          title={速率开 ? t("控制台.速率.收起") : t("控制台.速率.开关")}
        >
          {t("控制台.速率.开关")} {速率开 ? "▴" : "▾"}
        </button>
        <button
          type="button"
          className="控制台动作"
          aria-pressed={跟随}
          onClick={() => (跟随 ? 设跟随(false) : 恢复跟随())}
          title={t("控制台.跟随.提示")}
        >
          {跟随 ? t("控制台.跟随.开") : t("控制台.跟随.关")}
        </button>
        <span className="flex-1" />
        {操作 ? (
          <span
            className="操作反馈"
            role="status"
            aria-live="polite"
            style={{ color: 操作.好 ? "var(--ok)" : "var(--danger)" }}
          >
            {操作.好 ? "✓ " : "! "}
            {操作.文本}
          </span>
        ) : null}
      </div>

      <div ref={滚动区} className="min-h-0 flex-1 overflow-y-auto" onScroll={滚动时}>
        {页签 === "输出" ? (
          <>
            <日志列表 行={行们} 筛选空={筛选空} />
            {速率开 ? (
              <div className="速率区">
                <div className="flex flex-wrap items-baseline gap-1.5">
                  <span className="text-dim">{t("控制台.速率.标题")}</span>
                  <标签>{t("控制台.速率.说明")}</标签>
                </div>
                {快照.速率.length ? (
                  <速率表 行={快照.速率} />
                ) : (
                  <div className="mt-1 text-dim">{t("控制台.速率.空")}</div>
                )}
              </div>
            ) : null}
          </>
        ) : 页签 === "事件" ? (
          <日志列表 行={事件行} />
        ) : 页签 === "诊断" ? (
          <诊断页 报告={诊断报告} />
        ) : (
          <问题页 问题={问题} />
        )}
      </div>
    </section>
  );
}

function 速率表({ 行 }: { 行: 速率行[] }) {
  const t = use取();
  const 节拍 = 用节拍();
  void 节拍; // 每秒重画一次：年龄列要跟着走
  return (
    <div className="等宽 mt-1 text-[0.82em]">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="border-b px-1.5 py-0.5 text-left font-normal text-dim">
              {t("控制台.列.主题")}
            </th>
            <th className="border-b px-1.5 py-0.5 text-right font-normal text-dim">{"Σ"}</th>
            <th className="border-b px-1.5 py-0.5 text-right font-normal text-dim">{"Δ/1s"}</th>
            <th className="border-b px-1.5 py-0.5 text-right font-normal text-dim">
              {t("控制台.列.时刻")}
            </th>
          </tr>
        </thead>
        <tbody>
          {行.map((r, i) => (
            <tr key={r.主题} style={{ background: i % 2 ? "var(--bg-row-alt)" : undefined }}>
              <td className="border-b px-1.5 py-0.5 break-all">{r.主题}</td>
              <td className="border-b px-1.5 py-0.5 text-right">{r.计数}</td>
              <td className="border-b px-1.5 py-0.5 text-right">{r.速率}</td>
              <td className="border-b px-1.5 py-0.5 text-right text-dim">
                {Number.isFinite(r.年龄) ? `${(r.年龄 / 1000).toFixed(0)} s` : "--"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function 日志列表({ 行, 筛选空 = false }: { 行: 日志行[]; 筛选空?: boolean }) {
  const t = use取();
  const [展开, 设展开] = useState<number | null>(null);

  const 高亮 = async (关节: number) => {
    const 起于 = 记命令发出();
    命令收尾("命令.高亮", await 命令.高亮关节(关节, 8), 起于, { 模块: "控制台", 关节 });
  };

  if (!行.length) {
    return (
      <div className="p-3 text-dim">
        <div>{筛选空 ? t("控制台.筛选.空") : t("控制台.空")}</div>
        {筛选空 ? null : <div className="mt-1">{t("控制台.空提示")}</div>}
      </div>
    );
  }

  return (
    <ol className="日志列表">
      {行.map((l) => {
        const 有细节 = Boolean(l.细节);
        return (
          <li key={l.序号} className="日志项">
            <button
              type="button"
              className="日志行"
              aria-expanded={有细节 ? 展开 === l.序号 : undefined}
              onClick={有细节 ? () => 设展开(展开 === l.序号 ? null : l.序号) : undefined}
            >
              <span className="日志行首">
                <span className="日志时间 等宽">{时刻(l.墙钟)}</span>
                <span className="日志等级" style={{ color: 等级色[l.等级] }}>
                  <span aria-hidden="true">{等级符号[l.等级]}</span> {t(等级键[l.等级])}
                </span>
                <span className="日志来源">{来源键[l.来源] ? t(来源键[l.来源]) : l.来源}</span>
                {l.主题 ? (
                  <span className="日志主题 等宽" title={l.主题}>
                    {l.主题}
                  </span>
                ) : null}
                {l.插件 ? (
                  <span className="日志插件" title={t("控制台.日志.插件", { 名: l.插件 })}>
                    {l.插件}
                  </span>
                ) : null}
                {l.关节 !== undefined ? (
                  <span
                    role="button"
                    tabIndex={0}
                    className="日志关节"
                    title={t("控制台.日志.高亮关节", { 关节: l.关节 })}
                    onClick={(e) => {
                      e.stopPropagation();
                      void 高亮(l.关节 as number);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        e.stopPropagation();
                        void 高亮(l.关节 as number);
                      }
                    }}
                  >
                    J{l.关节}
                  </span>
                ) : null}
              </span>
              <span className="日志文本">{l.文本}</span>
            </button>
            {展开 === l.序号 && l.细节 ? (
              <pre className="日志细节">{l.细节}</pre>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

interface 问题项 {
  键: string;
  等级: 日志等级;
  说明: string;
  依据: ReactNode;
}

/** 问题 = 按真实连接状态 + 项目装配报告推导的校验；每条都带依据 */
function 用问题(
  连接: string,
  错误: string | null,
  握手: { 可用主题: string[] } | null,
  行: 日志行[],
  项目: 项目状态 | null,
): 问题项[] {
  const t = use取();
  const 出: 问题项[] = [];

  if (连接 !== "已连接") {
    出.push({
      键: "连接",
      等级: "注意",
      说明: t("问题.未连接"),
      依据: (
        <span>
          {t("问题.未连接.说明", {
            状态: t(连接键[连接 as keyof typeof 连接键] ?? "连接.连接中"),
          })}
        </span>
      ),
    });
  }

  if (错误 && 错误.includes("协议版本")) {
    出.push({
      键: "协议",
      等级: "错误",
      说明: t("问题.协议不符"),
      依据: <span className="break-all">{错误}</span>,
    });
  }

  if (错误 && 错误.includes("非 JSON")) {
    出.push({
      键: "非JSON",
      等级: "注意",
      说明: t("问题.非JSON"),
      依据: <span>{t("问题.非JSON.说明")}</span>,
    });
  }

  // 握手承诺过、但**一帧都没到过**的广播主题（命令回执 / 问候帧不算广播）
  if (握手?.可用主题?.length) {
    const 到过 = new Set(取日志().速率.map((r) => r.主题));
    const 缺 = 握手.可用主题.filter(
      (主) => !主.startsWith("__") && !主.startsWith("命令.") && !到过.has(主),
    );
    if (缺.length) {
      出.push({
        键: "主题",
        等级: "注意",
        说明: t("问题.契约缺主题"),
        依据: <div className="break-all">{t("问题.契约缺主题.说明", { 主题: 缺.join(" · ") })}</div>,
      });
    }
  }

  const 不兼容 = (项目?.报告 ?? []).filter((行) => 行.includes("不兼容"));
  if (不兼容.length) {
    出.push({
      键: "兼容性",
      等级: "错误",
      说明: t("问题.兼容性"),
      依据: (
        <ul className="space-y-0.5">
          {不兼容.map((行) => (
            <li key={行} className="break-all">
              {行.replace(/^[-·]\s*/, "")}
            </li>
          ))}
        </ul>
      ),
    });
  }

  const 失败 = 行.filter((l) => l.来源 === "回执" && l.等级 === "错误");
  if (失败.length) {
    出.push({
      键: "命令",
      等级: "错误",
      说明: t("问题.命令失败"),
      依据: (
        <ul className="space-y-0.5">
          {失败.slice(-5).map((l) => (
            <li key={l.序号} className="break-all">
              {时刻(l.墙钟)} {l.文本}
            </li>
          ))}
        </ul>
      ),
    });
  }

  const 前端错 = 行.filter((l) => l.来源 === "前端" && l.等级 === "错误");
  if (前端错.length) {
    出.push({
      键: "前端",
      等级: "错误",
      说明: t("问题.前端异常"),
      依据: (
        <ul className="space-y-0.5">
          {前端错.slice(-3).map((l) => (
            <li key={l.序号} className="break-all">
              {时刻(l.墙钟)} {l.文本}
            </li>
          ))}
        </ul>
      ),
    });
  }

  return 出;
}

function 问题页({ 问题 }: { 问题: 问题项[] }) {
  const t = use取();
  if (!问题.length) {
    return (
      <div className="p-3 text-dim">
        <div>{t("控制台.问题.无")}</div>
        <div className="mt-1">{t("控制台.问题.无说明")}</div>
      </div>
    );
  }
  return (
    <div className="p-2">
      <div className="mb-1 text-dim">{t("控制台.问题.标题")}</div>
      <ul className="space-y-2">
        {问题.map((p) => {
          const 语气 = p.等级 === "错误" ? "错误" : p.等级 === "注意" ? "警告" : "中性";
          const 符号 = p.等级 === "错误" ? "✗" : p.等级 === "注意" ? "!" : "·";
          return (
            <li key={p.键} className="问题项">
              <div className="flex items-start gap-1.5">
                <标签 语气={语气}>
                  <span aria-hidden="true">{符号}</span> {t(等级键[p.等级])}
                </标签>
                <span>{p.说明}</span>
              </div>
              <div className="mt-1 text-[0.85em] text-dim">{p.依据}</div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** 诊断页签：底部工程面板里的"轻量诊断"，完整视图仍走侧栏「诊断」。 */
function 诊断页({ 报告 }: { 报告: 诊断报告 | null }) {
  const t = use取();
  const 连接 = 用仓库((s) => s.连接);
  const [忙, 设忙] = useState(false);
  const 运行中 = !!报告?.运行中;
  const 可发 = 连接 === "已连接";
  const 通过 = 报告?.通过 ?? 0;
  const 总数 = 报告?.总数 ?? 0;
  const 全过 = !!报告 && !运行中 && 总数 > 0 && 通过 === 总数;

  const 跑 = async () => {
    设忙(true);
    try {
      const 起于 = 记命令发出();
      命令收尾("命令.诊断", await 命令.跑诊断(), 起于);
    } finally {
      设忙(false);
    }
  };

  return (
    <div className="p-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {报告 ? (
          <>
            <标签 语气={运行中 ? "强调" : 全过 ? "成功" : "错误"}>
              {运行中 ? t("控制台.诊断.运行中") : t("控制台.诊断.通过", { 通过, 总数 })}
            </标签>
            <span className="等宽 text-[0.78em] text-dim">
              {`${报告.时间 ?? ""} · ${报告.耗时秒 ?? "--"}s`}
            </span>
          </>
        ) : (
          <标签>{t("控制台.诊断.未运行")}</标签>
        )}
        <span className="flex-1" />
        <button
          type="button"
          className="控制台动作"
          disabled={忙 || 运行中 || !可发}
          onClick={() => void 跑()}
          title={t("控制台.诊断.说明")}
        >
          {运行中 ? t("控制台.诊断.运行中") : t("控制台.诊断.运行")}
        </button>
        <button type="button" className="控制台动作" onClick={() => 请求跳步("诊断")}>
          {t("控制台.诊断.完整")}
        </button>
      </div>
      <p className="mt-1 text-[0.78em] text-dim">{t("控制台.诊断.说明")}</p>
      {报告?.出错 ? (
        <div className="mt-1 text-[0.82em]" style={{ color: "var(--danger)" }}>
          {报告.出错}
        </div>
      ) : null}
      {报告?.项?.length ? (
        <ul className="mt-1.5 space-y-0.5">
          {报告.项.map((x, i) => (
            <li key={`${x.名 ?? "项"}-${i}`} className="flex items-baseline gap-1.5 text-[0.82em]">
              <span style={{ flex: "none", color: x.通过 ? "var(--ok)" : "var(--danger)" }}>
                {x.通过 ? "✓" : "✗"}
              </span>
              <span className="w-[5.6em] flex-none">{x.名}</span>
              <span className="min-w-0 flex-1 truncate text-dim 等宽" title={x.说明}>
                {x.说明}
              </span>
              <span className="w-[3.2em] flex-none text-right text-dim 等宽">
                {x.秒 === undefined ? "" : `${x.秒.toFixed(2)}s`}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-2 text-dim">{运行中 ? t("控制台.诊断.运行中") : t("控制台.诊断.空")}</div>
      )}
    </div>
  );
}

/**
 * 控制台收起后露出的召回条：显示真实的问题计数（含连接/兼容性/命令失败），
 * 有错误变红、只有警告变黄；点一下重新展开。收起不能变成"找不到"。
 */
export function 控制台召回({ on展开 }: { on展开: () => void }) {
  const t = use取();
  const 快照 = 用日志();
  const 连接 = 用仓库((s) => s.连接);
  const 错误 = 用仓库((s) => s.错误);
  const 握手 = 用仓库((s) => s.握手);
  const 项目 = 用仓库((s) => s.项目.数据);
  const 诊断报告 = 用仓库((s) => s.诊断.数据);
  const 问题 = 用问题(连接, 错误, 握手, 快照.行, 项目);
  const 错误数 = 问题.filter((p) => p.等级 === "错误").length;
  const 注意数 = 问题.filter((p) => p.等级 === "注意").length;
  const 诊断异常 =
    !!诊断报告 &&
    !诊断报告.运行中 &&
    (!!诊断报告.出错 ||
      ((诊断报告.总数 ?? 0) > 0 && (诊断报告.通过 ?? 0) < (诊断报告.总数 ?? 0)));

  return (
    <button
      type="button"
      onClick={on展开}
      className="控制台召回"
      title={t("控制台.召回.提示")}
      aria-expanded={false}
    >
      <span className="flex-none">▴ {t("控制台.标题")}</span>
      {错误数 ? (
        <span className="控制台召回-徽标" style={{ color: "var(--danger)" }}>
          ✗ {t("控制台.召回.错误", { 数量: 错误数 })}
        </span>
      ) : null}
      {注意数 ? (
        <span className="控制台召回-徽标" style={{ color: "var(--warn)" }}>
          ! {t("控制台.召回.注意", { 数量: 注意数 })}
        </span>
      ) : null}
      {诊断异常 ? (
        <span className="控制台召回-徽标" style={{ color: "var(--danger)" }}>
          ✗ {`诊断 ${诊断报告?.通过 ?? 0}/${诊断报告?.总数 ?? 0}`}
        </span>
      ) : null}
      {!错误数 && !注意数 && !诊断异常 ? (
        <span className="text-dim">{t("控制台.召回.无问题")}</span>
      ) : null}
      <span className="flex-1" />
      <span className="text-dim text-[0.8em]">{t("控制台.展开")} (;)</span>
    </button>
  );
}
