/**
 * IdentificationView.tsx —— 任务流第 4 步：参数辨识。
 *
 * 全部字段来自下行主题「辨识状态」（`s.辨识`，5 Hz）：状态 / 进度 / 采样步数 /
 * 耗时 / 结果 / 拟合 / 日志。前端**只显示**，不做任何推断：不猜"还差多久"，
 * 不给结果打分，不把残差下降说成"模型更准了"。
 *
 * 唯一算出来的数字是"残差变化百分比" —— 那是两个真值之间的算术，
 * 而且下面紧接着就写明它**不能**证明什么（`runtime/文案.py` 里同一句话的 Web 版）。
 *
 * 两个动作按钮走真命令（`命令.开始辨识` / `命令.停止辨识`），等回执、写控制台 + 提示。
 */
import { useState } from "react";
import { encodeServerPayload } from "../data/wire_compatibility";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Button } from "../components/Button";
import { Tag } from "../components/Badge";
import { DataTable, ValueTable, NumericText, formatValue, type TableColumn, type ValueRow } from "../components/DataTable";
import { commands, useStore } from "../data/store";
import { finishCommand, recordCommandStart } from "../data/logs";
import { useTranslation } from "./i18n";

/** 结果行里"名称/标称/辨识值/变化"这四个字段名跟后端一致；缺哪个就显示 `--` */
const resultField = [{ key: "name", label: "名称" }, { key: "nominal", label: "标称" }, { key: "identified", label: "辨识值" }, { key: "change", label: "变化" }] as const;

export function IdentificationView() {
  const t = useTranslation();
  const identification = useStore((s) => s.identification.data);
  const frameId = useStore((s) => s.identification.frameId);
  const connection = useStore((s) => s.connection);
  const state = identification?.state ?? "";
  const running = state.includes("采样中") || state.includes("辨识中");
  const complete = state.includes("完成");
  const error = state.includes("失败") || state.includes("错误");
  const canSend = connection === "connected";

  const exportResults = () => {
    if (!identification) return;
    const body = JSON.stringify(encodeServerPayload("辨识状态", identification), null, 2);
    const address = URL.createObjectURL(new Blob([body], { type: "application/json;charset=utf-8" }));
    const chain = document.createElement("a");
    chain.href = address;
    chain.download = "驭臂辨识结果.json";
    document.body.appendChild(chain);
    chain.click();
    document.body.removeChild(chain);
    window.setTimeout(() => URL.revokeObjectURL(address), 1000);
  };

  const [duration, setDuration] = useState("10");
  const [busy, setBusy] = useState<"开始" | "停止" | null>(null);
  const [latestReceipt, setLatestReceipt] = useState<{ passed: boolean; text: string } | null>(null);

  const sendCommand = async (action: "开始" | "停止") => {
    setBusy(action);
    const seconds = Number.parseFloat(duration);
    const topic = "命令.辨识";
    const startedAt = recordCommandStart();
    const receipt =
      action === "开始"
        ? await commands.startIdentification(Number.isFinite(seconds) ? seconds : 10)
        : await commands.stopIdentification();
    const r = finishCommand(topic, receipt, startedAt, { module: "辨识" });
    setLatestReceipt({ passed: r.passed, text: `${r.topic}：${r.description || t("日志.无说明")}` });
    setBusy(null);
  };

  const overview: ValueRow[] = [
    { key: t("辨识.状态"), value: identification?.state || "--", muted: !identification?.state },
    { key: t("辨识.进度"), value: identification?.progress || "--", muted: !identification?.progress },
    {
      key: t("辨识.采样步数"),
      value: <span className="monospace">{identification?.sample_count ?? "--"}</span>,
    },
    {
      key: t("辨识.耗时"),
      value: <span className="monospace">{identification?.elapsed_time === undefined ? "--" : `${identification.elapsed_time.toFixed(3)} s`}</span>,
    },
    {
      key: t("关于.帧号"),
      value: <span className="monospace">{identification ? `#${frameId}` : "--"}</span>,
      muted: !identification,
    },
  ];

  const resultRow = identification?.results ?? [];
  const RESULT_COLUMNS: TableColumn[] = resultField.map((field) => ({
    title: field.label,
    numeric: field.key !== "name",
    render: (row: Record<string, unknown>) =>
      field.key === "name" ? (
        <span className="break-all">{formatValue(row[field.key])}</span>
      ) : (
        <NumericText value={row[field.key] as number | undefined} digits={6} />
      ),
  }));

  const fitting = identification?.fit;
  const fittingRow: ValueRow[] = fitting
    ? Object.keys(fitting).map((k) => ({
        key: ({ before: "前", after: "后", nominal: "标称", identified: "辨识后" } as Record<string, string>)[k] ?? k,
        value: <NumericText value={fitting[k] as number | undefined} digits={6} />,
      }))
    : [];

  // 残差变化：只在"前/后"都是真数字时才算 —— 缺一个就什么都不显示
  const initialResidual = fitting?.before ?? fitting?.nominal;
  const identifiedResidual = fitting?.after ?? fitting?.identified;
  const before = typeof initialResidual === "number" ? initialResidual : undefined;
  const after = typeof identifiedResidual === "number" ? identifiedResidual : undefined;
  const change = before !== undefined && after !== undefined && before !== 0 ? ((after - before) / Math.abs(before)) * 100 : undefined;

  return (
    <div>
      <CollapsibleSection
        title={t("辨识.标题")}
        badge={
          identification?.state ? (
            <Tag tone={running ? "emphasis" : complete ? "success" : error ? "error" : "neutral"}>{identification.state}</Tag>
          ) : (
            <Tag>{t("辨识.尚无状态")}</Tag>
          )
        }
      >
        {identification ? (
          <ValueTable rows={overview} />
        ) : (
          <div className="mt-1 text-[0.85em] text-dim">
            <div>{t("辨识.没状态")}</div>
            <div className="mt-0.5">{t("辨识.等待开始")}</div>
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="block" style={{ width: 120 }}>
            <span className="text-dim">{t("辨识.时长")}</span>
            <input
              className="input mt-0.5 monospace"
              value={duration}
              inputMode="decimal"
              onChange={(e) => setDuration(e.target.value)}
            />
          </label>
          <Button
            variant="primary"
            disabled={busy !== null || !canSend || running}
            onPress={() => void sendCommand("开始")}
          >
            {busy === "开始" ? "…" : t("辨识.开始")}
          </Button>
          <Button
            variant="secondary"
            disabled={busy !== null || !running}
            title={!running ? t("辨识.停止条件") : undefined}
            onPress={() => void sendCommand("停止")}
          >
            {busy === "停止" ? "…" : t("辨识.停止")}
          </Button>
          {identification ? (
            <Button variant="ghost" size="small" onPress={exportResults}>
              {t("辨识.导出")}
            </Button>
          ) : null}
        </div>
        <p className="mt-1 text-[0.85em] text-dim">{t("辨识.时长说明")}</p>
        {latestReceipt ? (
          <div
            className="mt-1 monospace text-[0.9em]"
            style={{ color: latestReceipt.passed ? "var(--ok)" : "var(--danger)" }}
          >
            {latestReceipt.passed ? "ok" : "fail"} —— {latestReceipt.text}
          </div>
        ) : null}
      </CollapsibleSection>

      <CollapsibleSection title={t("辨识.结果")} badge={<span className="monospace">{resultRow.length || ""}</span>}>
        {resultRow.length ? (
          <DataTable columns={RESULT_COLUMNS} rows={resultRow} rowKey={(_r, i) => String(i)} />
        ) : (
          <div className="text-dim">{t("辨识.没结果")}</div>
        )}
      </CollapsibleSection>

      <CollapsibleSection title={t("辨识.拟合")} badge={<span className="monospace">{fitting ? Object.keys(fitting).length : ""}</span>}>
        {fitting ? (
          <>
            <ValueTable rows={fittingRow} />
            {change !== undefined ? (
              <div className="mt-1 monospace">
                Δ = {change >= 0 ? "+" : ""}
                {change.toFixed(2)} %
              </div>
            ) : null}
            <p className="mt-1 text-[0.85em] text-dim">{t("辨识.残差诚实")}</p>
          </>
        ) : (
          <div className="text-dim">{t("辨识.没拟合")}</div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={t("辨识.日志")}
        badge={<span className="monospace">{identification?.log?.length ?? ""}</span>}
        defaultOpen={false}
      >
        {identification?.log?.length ? (
          <ol className="monospace space-y-0.5 text-[0.9em]">
            {identification.log.map((row, i) => (
              <li key={i} className="break-all">
                <span className="text-dim">{String(i + 1).padStart(3, "0")} </span>
                {row}
              </li>
            ))}
          </ol>
        ) : (
          <div className="text-dim">{t("通用.无数据")}</div>
        )}
      </CollapsibleSection>
    </div>
  );
}
