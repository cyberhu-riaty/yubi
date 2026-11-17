import type { WireHandshake } from "../data/connection";
/**
 * Console.tsx —— 底部三页签：输出 / 事件 / 问题。
 *
 * 数据只有两个来源，都是真的：
 *   ① `数据/logs.ts` —— 连接状态、握手、回执、后端错误、前端异常（逐条留痕）
 *   ② `数据/store.ts` —— 主题计数与速率（每秒实测差值）
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
  clearLogs as clearLogs,
  getLogs as getLogs,
  useLogs as useLogs,
  sendNativeState as sendNativeState,
  recordCommandStart,
  finishCommand,
  type LogLevel as LogLevel,
  type LogRow as LogRow,
  type TopicRateRow as TopicRateRow,
} from "../data/logs";
import { Tag } from "../components/Badge";
import { commands, useStore, type ProjectState, type DiagnosticReport as DiagnosticReport } from "../data/store";
import { requestStepNavigation } from "./step_navigation";
import { useClock } from "../data/clock";
import { connectionTranslationKeys, useTranslation, formatTime } from "../views/i18n";

export type ConsoleTab = "输出" | "事件" | "问题" | "诊断";

export interface ConsoleProps {
  tab: ConsoleTab;
  onTabChange: (page: ConsoleTab) => void;
  /** 收起抽屉（App 传；不传就不显示收起按钮） */
  onCollapse?: () => void;
}

/** 等级 → 颜色。颜色只来自主题语义色；文字里同时有符号和等级名。 */
const LEVEL_COLORS: Record<LogLevel, string> = {
  信息: "var(--info)",
  注意: "var(--warn)",
  错误: "var(--danger)",
};

const LEVEL_SYMBOLS: Record<LogLevel, string> = { 信息: "●", 注意: "!", 错误: "✗" };
const levelKey: Record<LogLevel, "控制台.等级.信息" | "控制台.等级.注意" | "控制台.等级.错误"> = {
  信息: "控制台.等级.信息",
  注意: "控制台.等级.注意",
  错误: "控制台.等级.错误",
};

const sourceKey: Record<string, "控制台.来源.连接" | "控制台.来源.握手" | "控制台.来源.回执" | "控制台.来源.错误" | "控制台.来源.前端" | "控制台.来源.控制台" | "控制台.来源.规划" | "控制台.来源.诊断"> = {
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
type LevelFilter = LogLevel | "全部";
/** 时间筛选：全部 / 最近 N 分钟 */
type TimeFilter = "全部" | 1 | 5 | 15;
const timeMs: Record<Exclude<TimeFilter, "全部">, number> = { 1: 60_000, 5: 300_000, 15: 900_000 };

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 降级 */
  }
  try {
    const section = document.createElement("textarea");
    section.value = text;
    section.setAttribute("readonly", "");
    section.style.position = "fixed";
    section.style.opacity = "0";
    document.body.appendChild(section);
    section.select();
    const success = document.execCommand("copy");
    document.body.removeChild(section);
    return success;
  } catch {
    return false;
  }
}

function rowText(l: LogRow): string {
  const context = [
    l.module ? `模块=${l.module}` : "",
    l.plugins ? `插件=${l.plugins}` : "",
    l.joint !== undefined ? `J${l.joint}` : "",
  ].filter(Boolean).join(" ");
  const header = `${formatTime(l.timestamp)}\t${l.level}\t${l.source}${l.topic ? `\t${l.topic}` : ""}${context ? `\t${context}` : ""}`;
  return `${header}\n${l.text}${l.details ? `\n${l.details}` : ""}`;
}

export function Console({ tab: tab, onTabChange: onTabChange, onCollapse: onCollapse }: ConsoleProps) {
  const t = useTranslation();
  const snapshot = useLogs();
  const connection = useStore((s) => s.connection);
  const error = useStore((s) => s.error);
  const handshake = useStore((s) => s.handshake);
  const project = useStore((s) => s.project.data);
  const diagnosticReport = useStore((s) => s.diagnostics.data);
  const tick = useClock();

  const [levelFilter, setLevelFilter] = useState<LevelFilter>("全部");
  const [sourceFilter, setSourceFilter] = useState<string>("全部");
  const [pluginFilter, setPluginFilter] = useState<string>("全部");
  const [topicFilter, setTopicFilter] = useState<string>("全部");
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("全部");
  const [rateVisible, setRateVisible] = useState(false);
  const [follow, setFollow] = useState(true);
  const scrollArea = useRef<HTMLDivElement | null>(null);
  const [operation, setOperation] = useState<{ text: string; valid: boolean } | null>(null);
  const hintTimer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (hintTimer.current !== null) window.clearTimeout(hintTimer.current);
    };
  }, []);

  // 原生右列面板的筛选/清空操作回到同一个 Web 控制台 store，
  // 不是再维护一份独立日志。面板收起后，这里的筛选状态仍然保留。
  useEffect(() => {
    const listener = (e: Event) => {
      const d = (e as CustomEvent<{ type?: string; value?: string }>).detail;
      if (d?.type === "筛选") {
        const value = d.value;
        if (value === "全部" || value === "信息" || value === "注意" || value === "错误") {
          setLevelFilter(value);
        }
      } else if (d?.type === "清空") {
        clearLogs();
      }
    };
    window.addEventListener("驭臂.日志操作", listener);
    return () => window.removeEventListener("驭臂.日志操作", listener);
  }, []);

  const displayAction = (text: string, valid: boolean) => {
    setOperation({ text: text, valid: valid });
    if (hintTimer.current !== null) window.clearTimeout(hintTimer.current);
    hintTimer.current = window.setTimeout(() => setOperation(null), 2000);
  };

  const sources = useMemo(() => {
    const collection = new Set<string>();
    for (const l of snapshot.row) collection.add(l.source);
    return [...collection].sort();
  }, [snapshot.row]);

  const pluginList = useMemo(() => {
    const collection = new Set<string>();
    for (const l of snapshot.row) {
      if (l.plugins) collection.add(l.plugins);
    }
    return [...collection].sort();
  }, [snapshot.row]);

  const topics = useMemo(() => {
    const collection = new Set<string>();
    for (const l of snapshot.row) {
      if (l.topic) collection.add(l.topic);
    }
    return [...collection].sort();
  }, [snapshot.row]);

  const rows = useMemo(() => {
    const timeBounds = timeFilter === "全部" ? Number.POSITIVE_INFINITY : timeMs[timeFilter];
    return snapshot.row.filter(
      (l) =>
        (levelFilter === "全部" || l.level === levelFilter) &&
        (sourceFilter === "全部" || l.source === sourceFilter) &&
        (pluginFilter === "全部" || l.plugins === pluginFilter) &&
        (topicFilter === "全部" || l.topic === topicFilter) &&
        (timeBounds === Number.POSITIVE_INFINITY || tick - l.timestamp <= timeBounds),
    );
  }, [snapshot.row, levelFilter, sourceFilter, pluginFilter, topicFilter, timeFilter, tick]);

  const eventRow = useMemo(
    () => rows.filter((l) => l.source === "连接" || l.source === "握手" || l.source === "回执"),
    [rows],
  );

  // 原生面板是主日志的镜像：把同一份筛选结果、总数和筛选摘要推过去。
  // 原生面板上的筛选/清空再通过上面的 `驭臂.日志操作` 回到这里。
  useEffect(() => {
    const summary = [
      levelFilter !== "全部" ? `等级 ${levelFilter}` : "",
      sourceFilter !== "全部" ? `来源 ${sourceFilter}` : "",
      pluginFilter !== "全部" ? `插件 ${pluginFilter}` : "",
      topicFilter !== "全部" ? `主题 ${topicFilter}` : "",
      timeFilter !== "全部" ? `时间 ${timeFilter}` : "",
    ]
      .filter(Boolean)
      .join(" · ") || "无筛选";
    sendNativeState(rows, snapshot.row.length, summary, levelFilter);
  }, [rows, snapshot.row.length, levelFilter, sourceFilter, pluginFilter, topicFilter, timeFilter]);

  const problems = useProblems(connection, error, handshake, snapshot.row, project);
  const tabs: ConsoleTab[] = ["输出", "事件", "问题", "诊断"];
  const currentRow = tab === "事件" ? eventRow : tab === "诊断" ? [] : rows;
  const hasErrors = problems.some((p) => p.level === "错误");
  const diagnosticError =
    !!diagnosticReport &&
    !diagnosticReport.运行中 &&
    (!!diagnosticReport.出错 ||
      ((diagnosticReport.总数 ?? 0) > 0 && (diagnosticReport.通过 ?? 0) < (diagnosticReport.总数 ?? 0)));
  const filterEmpty = tab === "输出" && rows.length === 0 && snapshot.row.length > 0;

  // 新日志到达时跟随到底部；用户向上滚动后暂停，避免抢滚动条。
  useEffect(() => {
    if (!follow || tab === "诊断") return;
    const section = scrollArea.current;
    if (section) section.scrollTop = section.scrollHeight;
  }, [rows.length, eventRow.length, tab, follow]);

  const onScroll = () => {
    const section = scrollArea.current;
    if (!section) return;
    const scrollToBottom = section.scrollHeight - section.scrollTop - section.clientHeight < 24;
    if (scrollToBottom !== follow) setFollow(scrollToBottom);
  };

  const resumeFollowing = () => {
    setFollow(true);
    const section = scrollArea.current;
    if (section) section.scrollTop = section.scrollHeight;
  };

  const copyVisible = async () => {
    if (!currentRow.length) {
      displayAction(t("控制台.复制失败"), false);
      return;
    }
    const success = await copyText(currentRow.map(rowText).join("\n\n"));
    displayAction(
      success ? t("控制台.复制成功", { 数量: currentRow.length }) : t("控制台.复制失败"),
      success,
    );
  };

  const exportData = () => {
    if (!currentRow.length) {
      displayAction(t("控制台.复制失败"), false);
      return;
    }
    try {
      const body = new Blob([currentRow.map(rowText).join("\n\n")], {
        type: "text/plain;charset=utf-8",
      });
      const address = URL.createObjectURL(body);
      const chain = document.createElement("a");
      const time = new Date();
      const supplement = (n: number) => String(n).padStart(2, "0");
      chain.href = address;
      chain.download = `驭臂日志-${time.getFullYear()}${supplement(time.getMonth() + 1)}${supplement(time.getDate())}-${supplement(time.getHours())}${supplement(time.getMinutes())}${supplement(time.getSeconds())}.txt`;
      document.body.appendChild(chain);
      chain.click();
      document.body.removeChild(chain);
      window.setTimeout(() => URL.revokeObjectURL(address), 1000);
      displayAction(t("控制台.导出成功", { 数量: currentRow.length }), true);
    } catch {
      displayAction(t("控制台.复制失败"), false);
    }
  };

  return (
    <section
      aria-label={t("控制台.标题")}
      className="控制台 flex h-full min-h-0 flex-col"
      style={{ background: "var(--bg-menu)" }}
    >
      <div
        className="console-header flex flex-none items-center gap-1 px-1.5 py-1"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div role="tablist" aria-label={t("控制台.标题")} className="flex items-center gap-0.5">
          {tabs.map((p) => {
            const selected = p === tab;
            const badge =
              p === "问题"
                ? problems.length
                : p === "事件"
                  ? eventRow.length
                  : p === "诊断"
                    ? diagnosticReport?.运行中
                      ? "…"
                      : diagnosticReport
                        ? `${diagnosticReport.通过 ?? 0}/${diagnosticReport.总数 ?? 0}`
                        : ""
                    : rows.length;
            return (
              <button
                key={p}
                role="tab"
                type="button"
                aria-selected={selected}
                onClick={() => onTabChange(p)}
                className="console-tab flex items-center gap-1 px-2 py-1"
                style={{
                  background: selected ? "var(--bg-tab-on)" : "transparent",
                  color: selected
                    ? "var(--fg)"
                    : (p === "问题" && hasErrors) || (p === "诊断" && diagnosticError)
                      ? "var(--danger)"
                      : "var(--fg-dim)",
                  borderBottom: `2px solid ${selected ? "var(--grab)" : "transparent"}`,
                }}
              >
                <span>{t(`控制台.页签.${p}` as const)}</span>
                <span
                  className="monospace text-[0.8em]"
                  style={{
                    color:
                      (p === "问题" && hasErrors) || (p === "诊断" && diagnosticError)
                        ? "var(--danger)"
                        : undefined,
                  }}
                >
                  {badge || ""}
                </span>
              </button>
            );
          })}
        </div>

        <span className="flex-1" />

        {tab !== "诊断" ? (
          <>
            <button type="button" className="console-actions" onClick={() => void copyVisible()} title={t("控制台.复制")}>
              {t("控制台.复制")}
            </button>
            <button type="button" className="console-actions" onClick={exportData} title={t("控制台.导出")}>
              {t("控制台.导出")}
            </button>
          </>
        ) : null}
        {tab !== "诊断" ? (
          <button type="button" className="console-actions" onClick={clearLogs} title={t("控制台.清空不了")}>
            {t("控制台.清空")}
          </button>
        ) : null}
        {onCollapse ? (
          <button type="button" className="console-actions" onClick={onCollapse} title={t("控制台.收起")}>
            ⌄
          </button>
        ) : null}
      </div>

      <div
        className="console-filter flex flex-none items-center gap-1.5 px-1.5 pb-1"
        style={{ display: tab === "诊断" ? "none" : undefined }}
      >
        <label className="filter">
          <span className="sr-only">{t("控制台.筛选.等级")}</span>
          <select
            aria-label={t("控制台.筛选.等级")}
            value={levelFilter}
            onChange={(e) => setLevelFilter(e.target.value as LevelFilter)}
          >
            <option value="全部">{t("控制台.筛选.全部等级")}</option>
            <option value="信息">{t("控制台.等级.信息")}</option>
            <option value="注意">{t("控制台.等级.注意")}</option>
            <option value="错误">{t("控制台.等级.错误")}</option>
          </select>
        </label>
        <label className="filter">
          <span className="sr-only">{t("控制台.筛选.来源")}</span>
          <select
            aria-label={t("控制台.筛选.来源")}
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
          >
            <option value="全部">{t("控制台.筛选.全部")}</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {sourceKey[s] ? t(sourceKey[s]) : s}
              </option>
            ))}
          </select>
        </label>
        <label className="filter" title={t("控制台.筛选.插件")}>
          <span className="sr-only">{t("控制台.筛选.插件")}</span>
          <select
            aria-label={t("控制台.筛选.插件")}
            value={pluginFilter}
            onChange={(e) => setPluginFilter(e.target.value)}
          >
            <option value="全部">{t("控制台.筛选.全部插件")}</option>
            {pluginList.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="filter" title={t("控制台.筛选.主题")}>
          <span className="sr-only">{t("控制台.筛选.主题")}</span>
          <select
            aria-label={t("控制台.筛选.主题")}
            value={topicFilter}
            onChange={(e) => setTopicFilter(e.target.value)}
          >
            <option value="全部">{t("控制台.筛选.全部主题")}</option>
            {topics.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="filter" title={t("控制台.筛选.时间")}>
          <span className="sr-only">{t("控制台.筛选.时间")}</span>
          <select
            aria-label={t("控制台.筛选.时间")}
            value={String(timeFilter)}
            onChange={(e) => setTimeFilter(e.target.value === "全部" ? "全部" : (Number(e.target.value) as 1 | 5 | 15))}
          >
            <option value="全部">{t("控制台.筛选.全部时间")}</option>
            <option value="1">{t("控制台.时间.1")}</option>
            <option value="5">{t("控制台.时间.5")}</option>
            <option value="15">{t("控制台.时间.15")}</option>
          </select>
        </label>
        <button
          type="button"
          className="console-actions"
          aria-pressed={rateVisible}
          onClick={() => setRateVisible((previous) => !previous)}
          title={rateVisible ? t("控制台.速率.收起") : t("控制台.速率.开关")}
        >
          {t("控制台.速率.开关")} {rateVisible ? "▴" : "▾"}
        </button>
        <button
          type="button"
          className="console-actions"
          aria-pressed={follow}
          onClick={() => (follow ? setFollow(false) : resumeFollowing())}
          title={t("控制台.跟随.提示")}
        >
          {follow ? t("控制台.跟随.开") : t("控制台.跟随.关")}
        </button>
        <span className="flex-1" />
        {operation ? (
          <span
            className="action-feedback"
            role="status"
            aria-live="polite"
            style={{ color: operation.valid ? "var(--ok)" : "var(--danger)" }}
          >
            {operation.valid ? "✓ " : "! "}
            {operation.text}
          </span>
        ) : null}
      </div>

      <div ref={scrollArea} className="min-h-0 flex-1 overflow-y-auto" onScroll={onScroll}>
        {tab === "输出" ? (
          <>
            <LogList row={rows} filterEmpty={filterEmpty} />
            {rateVisible ? (
              <div className="rate-area">
                <div className="flex flex-wrap items-baseline gap-1.5">
                  <span className="text-dim">{t("控制台.速率.标题")}</span>
                  <Tag>{t("控制台.速率.说明")}</Tag>
                </div>
                {snapshot.rate.length ? (
                  <TopicRateTable row={snapshot.rate} />
                ) : (
                  <div className="mt-1 text-dim">{t("控制台.速率.空")}</div>
                )}
              </div>
            ) : null}
          </>
        ) : tab === "事件" ? (
          <LogList row={eventRow} />
        ) : tab === "诊断" ? (
          <DiagnosticsPanel report={diagnosticReport} />
        ) : (
          <ProblemsPanel problems={problems} />
        )}
      </div>
    </section>
  );
}

function TopicRateTable({ row: row }: { row: TopicRateRow[] }) {
  const t = useTranslation();
  const tick = useClock();
  void tick; // 每秒重画一次：年龄列要跟着走
  return (
    <div className="monospace mt-1 text-[0.82em]">
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
          {row.map((r, i) => (
            <tr key={r.topic} style={{ background: i % 2 ? "var(--bg-row-alt)" : undefined }}>
              <td className="border-b px-1.5 py-0.5 break-all">{r.topic}</td>
              <td className="border-b px-1.5 py-0.5 text-right">{r.count}</td>
              <td className="border-b px-1.5 py-0.5 text-right">{r.rate}</td>
              <td className="border-b px-1.5 py-0.5 text-right text-dim">
                {Number.isFinite(r.age) ? `${(r.age / 1000).toFixed(0)} s` : "--"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LogList({ row: row, filterEmpty: filterEmpty = false }: { row: LogRow[]; filterEmpty?: boolean }) {
  const t = useTranslation();
  const [expanded, setExpanded] = useState<number | null>(null);

  const highlighted = async (joint: number) => {
    const startedAt = recordCommandStart();
    finishCommand("命令.高亮", await commands.highlightJoint(joint, 8), startedAt, { module: "控制台", joint: joint });
  };

  if (!row.length) {
    return (
      <div className="p-3 text-dim">
        <div>{filterEmpty ? t("控制台.筛选.空") : t("控制台.空")}</div>
        {filterEmpty ? null : <div className="mt-1">{t("控制台.空提示")}</div>}
      </div>
    );
  }

  return (
    <ol className="log-list">
      {row.map((l) => {
        const hasDetails = Boolean(l.details);
        return (
          <li key={l.id} className="log-item">
            <button
              type="button"
              className="log-row"
              aria-expanded={hasDetails ? expanded === l.id : undefined}
              onClick={hasDetails ? () => setExpanded(expanded === l.id ? null : l.id) : undefined}
            >
              <span className="log-row-header">
                <span className="log-time monospace">{formatTime(l.timestamp)}</span>
                <span className="log-level" style={{ color: LEVEL_COLORS[l.level] }}>
                  <span aria-hidden="true">{LEVEL_SYMBOLS[l.level]}</span> {t(levelKey[l.level])}
                </span>
                <span className="log-source">{sourceKey[l.source] ? t(sourceKey[l.source]) : l.source}</span>
                {l.topic ? (
                  <span className="log-topic monospace" title={l.topic}>
                    {l.topic}
                  </span>
                ) : null}
                {l.plugins ? (
                  <span className="log-plugin" title={t("控制台.日志.插件", { 名: l.plugins })}>
                    {l.plugins}
                  </span>
                ) : null}
                {l.joint !== undefined ? (
                  <span
                    role="button"
                    tabIndex={0}
                    className="log-joint"
                    title={t("控制台.日志.高亮关节", { 关节: l.joint })}
                    onClick={(e) => {
                      e.stopPropagation();
                      void highlighted(l.joint as number);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        e.stopPropagation();
                        void highlighted(l.joint as number);
                      }
                    }}
                  >
                    J{l.joint}
                  </span>
                ) : null}
              </span>
              <span className="log-text">{l.text}</span>
            </button>
            {expanded === l.id && l.details ? (
              <pre className="log-details">{l.details}</pre>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

interface ProblemItem {
  key: string;
  level: LogLevel;
  description: string;
  evidence: ReactNode;
}

/** 问题 = 按真实连接状态 + 项目装配报告推导的校验；每条都带依据 */
function useProblems(
  connection: string,
  error: string | null,
  handshake: WireHandshake | null,
  row: LogRow[],
  project: ProjectState | null,
): ProblemItem[] {
  const t = useTranslation();
  const output: ProblemItem[] = [];

  if (connection !== "已连接") {
    output.push({
      key: "连接",
      level: "注意",
      description: t("问题.未连接"),
      evidence: (
        <span>
          {t("问题.未连接.说明", {
            状态: t(connectionTranslationKeys[connection as keyof typeof connectionTranslationKeys] ?? "连接.连接中"),
          })}
        </span>
      ),
    });
  }

  if (error && error.includes("协议版本")) {
    output.push({
      key: "协议",
      level: "错误",
      description: t("问题.协议不符"),
      evidence: <span className="break-all">{error}</span>,
    });
  }

  if (error && error.includes("非 JSON")) {
    output.push({
      key: "非JSON",
      level: "注意",
      description: t("问题.非JSON"),
      evidence: <span>{t("问题.非JSON.说明")}</span>,
    });
  }

  // 握手承诺过、但**一帧都没到过**的广播主题（命令回执 / 问候帧不算广播）
  if (handshake?.可用主题?.length) {
    const reached = new Set(getLogs().rate.map((r) => r.topic));
    const missing = handshake.可用主题.filter(
      (Main) => !Main.startsWith("__") && !Main.startsWith("命令.") && !reached.has(Main),
    );
    if (missing.length) {
      output.push({
        key: "主题",
        level: "注意",
        description: t("问题.契约缺主题"),
        evidence: <div className="break-all">{t("问题.契约缺主题.说明", { 主题: missing.join(" · ") })}</div>,
      });
    }
  }

  const incompatible = (project?.report ?? []).filter((row) => row.includes("不兼容"));
  if (incompatible.length) {
    output.push({
      key: "兼容性",
      level: "错误",
      description: t("问题.兼容性"),
      evidence: (
        <ul className="space-y-0.5">
          {incompatible.map((row) => (
            <li key={row} className="break-all">
              {row.replace(/^[-·]\s*/, "")}
            </li>
          ))}
        </ul>
      ),
    });
  }

  const failed = row.filter((l) => l.source === "回执" && l.level === "错误");
  if (failed.length) {
    output.push({
      key: "命令",
      level: "错误",
      description: t("问题.命令失败"),
      evidence: (
        <ul className="space-y-0.5">
          {failed.slice(-5).map((l) => (
            <li key={l.id} className="break-all">
              {formatTime(l.timestamp)} {l.text}
            </li>
          ))}
        </ul>
      ),
    });
  }

  const frontendError = row.filter((l) => l.source === "前端" && l.level === "错误");
  if (frontendError.length) {
    output.push({
      key: "前端",
      level: "错误",
      description: t("问题.前端异常"),
      evidence: (
        <ul className="space-y-0.5">
          {frontendError.slice(-3).map((l) => (
            <li key={l.id} className="break-all">
              {formatTime(l.timestamp)} {l.text}
            </li>
          ))}
        </ul>
      ),
    });
  }

  return output;
}

function ProblemsPanel({ problems: problems }: { problems: ProblemItem[] }) {
  const t = useTranslation();
  if (!problems.length) {
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
        {problems.map((p) => {
          const tone = p.level === "错误" ? "error" : p.level === "注意" ? "warning" : "neutral";
          const symbol = p.level === "错误" ? "✗" : p.level === "注意" ? "!" : "·";
          return (
            <li key={p.key} className="problem-item">
              <div className="flex items-start gap-1.5">
                <Tag tone={tone}>
                  <span aria-hidden="true">{symbol}</span> {t(levelKey[p.level])}
                </Tag>
                <span>{p.description}</span>
              </div>
              <div className="mt-1 text-[0.85em] text-dim">{p.evidence}</div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** 诊断页签：底部工程面板里的"轻量诊断"，完整视图仍走侧栏「诊断」。 */
function DiagnosticsPanel({ report: report }: { report: DiagnosticReport | null }) {
  const t = useTranslation();
  const connection = useStore((s) => s.connection);
  const [busy, setBusy] = useState(false);
  const running = !!report?.运行中;
  const canSend = connection === "已连接";
  const passed = report?.通过 ?? 0;
  const totalCount = report?.总数 ?? 0;
  const allPassed = !!report && !running && totalCount > 0 && passed === totalCount;

  const run = async () => {
    setBusy(true);
    try {
      const startedAt = recordCommandStart();
      finishCommand("命令.诊断", await commands.runDiagnostics(), startedAt);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {report ? (
          <>
            <Tag tone={running ? "emphasis" : allPassed ? "success" : "error"}>
              {running ? t("控制台.诊断.运行中") : t("控制台.诊断.通过", { 通过: passed, 总数: totalCount })}
            </Tag>
            <span className="monospace text-[0.78em] text-dim">
              {`${report.时间 ?? ""} · ${report.耗时秒 ?? "--"}s`}
            </span>
          </>
        ) : (
          <Tag>{t("控制台.诊断.未运行")}</Tag>
        )}
        <span className="flex-1" />
        <button
          type="button"
          className="console-actions"
          disabled={busy || running || !canSend}
          onClick={() => void run()}
          title={t("控制台.诊断.说明")}
        >
          {running ? t("控制台.诊断.运行中") : t("控制台.诊断.运行")}
        </button>
        <button type="button" className="console-actions" onClick={() => requestStepNavigation("诊断")}>
          {t("控制台.诊断.完整")}
        </button>
      </div>
      <p className="mt-1 text-[0.78em] text-dim">{t("控制台.诊断.说明")}</p>
      {report?.出错 ? (
        <div className="mt-1 text-[0.82em]" style={{ color: "var(--danger)" }}>
          {report.出错}
        </div>
      ) : null}
      {report?.项?.length ? (
        <ul className="mt-1.5 space-y-0.5">
          {report.项.map((x, i) => (
            <li key={`${x.名 ?? "项"}-${i}`} className="flex items-baseline gap-1.5 text-[0.82em]">
              <span style={{ flex: "none", color: x.通过 ? "var(--ok)" : "var(--danger)" }}>
                {x.通过 ? "✓" : "✗"}
              </span>
              <span className="w-[5.6em] flex-none">{x.名}</span>
              <span className="min-w-0 flex-1 truncate text-dim monospace" title={x.说明}>
                {x.说明}
              </span>
              <span className="w-[3.2em] flex-none text-right text-dim monospace">
                {x.秒 === undefined ? "" : `${x.秒.toFixed(2)}s`}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-2 text-dim">{running ? t("控制台.诊断.运行中") : t("控制台.诊断.空")}</div>
      )}
    </div>
  );
}

/**
 * 控制台收起后露出的召回条：显示真实的问题计数（含连接/兼容性/命令失败），
 * 有错误变红、只有警告变黄；点一下重新展开。收起不能变成"找不到"。
 */
export function ConsoleRecall({ onExpand: onExpand }: { onExpand: () => void }) {
  const t = useTranslation();
  const snapshot = useLogs();
  const connection = useStore((s) => s.connection);
  const error = useStore((s) => s.error);
  const handshake = useStore((s) => s.handshake);
  const project = useStore((s) => s.project.data);
  const diagnosticReport = useStore((s) => s.diagnostics.data);
  const problems = useProblems(connection, error, handshake, snapshot.row, project);
  const errorCount = problems.filter((p) => p.level === "错误").length;
  const warningCount = problems.filter((p) => p.level === "注意").length;
  const diagnosticError =
    !!diagnosticReport &&
    !diagnosticReport.运行中 &&
    (!!diagnosticReport.出错 ||
      ((diagnosticReport.总数 ?? 0) > 0 && (diagnosticReport.通过 ?? 0) < (diagnosticReport.总数 ?? 0)));

  return (
    <button
      type="button"
      onClick={onExpand}
      className="console-recall"
      title={t("控制台.召回.提示")}
      aria-expanded={false}
    >
      <span className="flex-none">▴ {t("控制台.标题")}</span>
      {errorCount ? (
        <span className="console-recall-badge" style={{ color: "var(--danger)" }}>
          ✗ {t("控制台.召回.错误", { 数量: errorCount })}
        </span>
      ) : null}
      {warningCount ? (
        <span className="console-recall-badge" style={{ color: "var(--warn)" }}>
          ! {t("控制台.召回.注意", { 数量: warningCount })}
        </span>
      ) : null}
      {diagnosticError ? (
        <span className="console-recall-badge" style={{ color: "var(--danger)" }}>
          ✗ {`诊断 ${diagnosticReport?.通过 ?? 0}/${diagnosticReport?.总数 ?? 0}`}
        </span>
      ) : null}
      {!errorCount && !warningCount && !diagnosticError ? (
        <span className="text-dim">{t("控制台.召回.无问题")}</span>
      ) : null}
      <span className="flex-1" />
      <span className="text-dim text-[0.8em]">{t("控制台.展开")} (;)</span>
    </button>
  );
}
