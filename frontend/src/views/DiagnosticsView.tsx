/**
 * DiagnosticsView.tsx —— 「诊断」：把终端里那批断言搬进界面。
 *
 * 诚实边界：
 *   · 这里显示的每一项，都是**真的跑了一遍** `工具/验证/*.py` 的结果
 *     （后端用子进程调用，跟你在终端里敲的是同一批脚本）。
 *   · 没有"历史全绿"缓存：每次点都重跑。缓存住的绿灯会在你真改坏东西时骗你。
 *   · 跑不动/超时就报失败，不写"未知"糊过去。
 */
import { useState } from "react";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { useClock } from "../data/clock";
import { Tag } from "../components/Badge";
import { Button } from "../components/Button";
import { commands, useStore } from "../data/store";
import { finishCommand, recordCommandStart } from "../data/logs";
import { useTranslation } from "./i18n";

export function DiagnosticsView() {
  const t = useTranslation();
  const report = useStore((s) => s.diagnostics.data);
  const connection = useStore((s) => s.connection);
  const tick = useClock();
  const [busy, setBusy] = useState(false);
  const [startTime, setStartTime] = useState<number | null>(null);
  const elapsed = report?.运行中 && startTime ? Math.max(0, Math.round((tick - startTime) / 1000)) : undefined;

  const allPassed = !!report && !report.运行中 && (report.通过 ?? 0) === (report.总数 ?? 0) && (report.总数 ?? 0) > 0;

  const runOnce = async () => {
    setBusy(true);
    setStartTime(Date.now());
    try {
      const startedAt = recordCommandStart();
      finishCommand("命令.诊断", await commands.runDiagnostics(), startedAt, { module: "诊断" });
    } finally {
      setBusy(false);
    }
  };

  const exportReport = () => {
    if (!report) return;
    const body = JSON.stringify(report, null, 2);
    const address = URL.createObjectURL(new Blob([body], { type: "application/json;charset=utf-8" }));
    const chain = document.createElement("a");
    chain.href = address;
    chain.download = `驭臂诊断-${String(report.时间 || "report").replace(/[^0-9A-Za-z_-]+/g, "-")}.json`;
    document.body.appendChild(chain);
    chain.click();
    document.body.removeChild(chain);
    window.setTimeout(() => URL.revokeObjectURL(address), 1000);
  };

  return (
    <div className="space-y-2">
      <CollapsibleSection
        title={t("步骤.诊断")}
        badge={
          report?.运行中 ? (
            <Tag tone="emphasis">{t("诊断.运行中")}</Tag>
          ) : report ? (
            <Tag tone={allPassed ? "success" : "error"}>{`${report.通过 ?? 0}/${report.总数 ?? 0}`}</Tag>
          ) : (
            <Tag>{t("诊断.未运行")}</Tag>
          )
        }
      >
        <div className="flex items-center gap-2">
          <Button variant="primary" title={t("诊断.说明")} onPress={() => void runOnce()} disabled={busy || !!report?.运行中 || connection !== "已连接"}>
            {report?.运行中 ? t("诊断.运行中") : t("诊断.开始")}
          </Button>
          {report?.运行中 && elapsed !== undefined ? (
            <span className="text-[0.85em] text-dim monospace">{t("诊断.已用时", { 秒: elapsed })}</span>
          ) : report && !report.运行中 ? (
            <>
              <span className="text-[0.85em] text-dim monospace">
                {`${report.时间 ?? ""} · ${report.耗时秒 ?? "--"}s`}
              </span>
              <Button size="small" variant="ghost" onPress={exportReport}>
                {t("诊断.导出")}
              </Button>
            </>
          ) : null}
        </div>

        {report?.项?.length ? (
          <ul className="mt-2 space-y-0.5">
            {report.项.map((x) => (
              <li key={x.名} className="flex items-baseline gap-1.5 text-[0.85em]">
                <span style={{ flex: "none", color: x.通过 ? "var(--ok)" : "var(--danger)" }}>
                  {x.通过 ? "✓" : "✗"}
                </span>
                <span className="w-[76px] flex-none">{x.名}</span>
                <span className="min-w-0 flex-1 truncate text-dim monospace" title={x.说明}>
                  {x.说明}
                </span>
                <span className="w-[46px] flex-none text-right text-dim monospace">
                  {x.秒 === undefined ? "" : `${x.秒.toFixed(2)}s`}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-2 text-dim">{report?.运行中 ? t("诊断.运行中") : t("诊断.没跑过")}</div>
        )}

        <details className="assembly-details mt-2">
          <summary>{t("诊断.高级")}</summary>
          <p className="mt-1 text-[0.8em] text-dim">{t("诊断.高级说明")}</p>
        </details>
      </CollapsibleSection>
    </div>
  );
}
