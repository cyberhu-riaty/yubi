/**
 * 辨识视图.tsx —— 任务流第 4 步：参数辨识。
 *
 * 全部字段来自下行主题「辨识状态」（`s.辨识`，5 Hz）：状态 / 进度 / 采样步数 /
 * 耗时 / 结果 / 拟合 / 日志。前端**只显示**，不做任何推断：不猜"还差多久"，
 * 不给结果打分，不把残差下降说成"模型更准了"。
 *
 * 唯一算出来的数字是"残差变化百分比" —— 那是两个真值之间的算术，
 * 而且下面紧接着就写明它**不能**证明什么（`软件/文案.py` 里同一句话的 Web 版）。
 *
 * 两个动作按钮走真命令（`命令.开始辨识` / `命令.停止辨识`），等回执、写控制台 + 提示。
 */
import { useState } from "react";
import { CollapsibleSection } from "../组件/可折叠区块";
import { Button } from "../组件/按钮";
import { Tag } from "../组件/标签";
import { DataTable, ValueTable, NumericText, formatValue, type TableColumn, type ValueRow } from "../组件/数值表";
import { 命令, 用仓库 } from "../数据/仓库";
import { 命令收尾, 记命令发出 } from "../数据/日志";
import { useTranslation } from "./文案";

/** 结果行里"名称/标称/辨识值/变化"这四个字段名跟后端一致；缺哪个就显示 `--` */
const 结果字段 = ["名称", "标称", "辨识值", "变化"] as const;

export function 辨识视图() {
  const t = useTranslation();
  const 辨识 = 用仓库((s) => s.辨识.数据);
  const 帧号 = 用仓库((s) => s.辨识.帧号);
  const 连接 = 用仓库((s) => s.连接);
  const 状态 = 辨识?.状态 ?? "";
  const 运行中 = 状态.includes("采样中") || 状态.includes("辨识中");
  const 完成 = 状态.includes("完成");
  const 出错 = 状态.includes("失败") || 状态.includes("错误");
  const 可发 = 连接 === "已连接";

  const 导出结果 = () => {
    if (!辨识) return;
    const 体 = JSON.stringify(辨识, null, 2);
    const 地址 = URL.createObjectURL(new Blob([体], { type: "application/json;charset=utf-8" }));
    const 链 = document.createElement("a");
    链.href = 地址;
    链.download = "驭臂辨识结果.json";
    document.body.appendChild(链);
    链.click();
    document.body.removeChild(链);
    window.setTimeout(() => URL.revokeObjectURL(地址), 1000);
  };

  const [时长, 设时长] = useState("10");
  const [忙, 设忙] = useState<"开始" | "停止" | null>(null);
  const [最近回执, 设最近回执] = useState<{ 通过: boolean; 文本: string } | null>(null);

  const 发命令 = async (动作: "开始" | "停止") => {
    设忙(动作);
    const 秒 = Number.parseFloat(时长);
    const 主题 = "命令.辨识";
    const 起于 = 记命令发出();
    const 回执 =
      动作 === "开始"
        ? await 命令.开始辨识(Number.isFinite(秒) ? 秒 : 10)
        : await 命令.停止辨识();
    const r = 命令收尾(主题, 回执, 起于, { 模块: "辨识" });
    设最近回执({ 通过: r.通过, 文本: `${r.主题}：${r.说明 || t("日志.无说明")}` });
    设忙(null);
  };

  const 概览: ValueRow[] = [
    { key: t("辨识.状态"), value: 辨识?.状态 || "--", muted: !辨识?.状态 },
    { key: t("辨识.进度"), value: 辨识?.进度 || "--", muted: !辨识?.进度 },
    {
      key: t("辨识.采样步数"),
      value: <span className="等宽">{辨识?.采样步数 ?? "--"}</span>,
    },
    {
      key: t("辨识.耗时"),
      value: <span className="等宽">{辨识?.耗时 === undefined ? "--" : `${辨识.耗时.toFixed(3)} s`}</span>,
    },
    {
      key: t("关于.帧号"),
      value: <span className="等宽">{辨识 ? `#${帧号}` : "--"}</span>,
      muted: !辨识,
    },
  ];

  const 结果行 = 辨识?.结果 ?? [];
  const 结果列: TableColumn[] = 结果字段.map((字段) => ({
    title: 字段,
    numeric: 字段 !== "名称",
    render: (行: Record<string, unknown>) =>
      字段 === "名称" ? (
        <span className="break-all">{formatValue(行[字段])}</span>
      ) : (
        <NumericText value={行[字段] as number | undefined} digits={6} />
      ),
  }));

  const 拟合 = 辨识?.拟合;
  const 拟合行: ValueRow[] = 拟合
    ? Object.keys(拟合).map((k) => ({
        key: k,
        value: <NumericText value={拟合[k] as number | undefined} digits={6} />,
      }))
    : [];

  // 残差变化：只在"前/后"都是真数字时才算 —— 缺一个就什么都不显示
  const 前 = typeof 拟合?.前 === "number" ? 拟合.前 : undefined;
  const 后 = typeof 拟合?.后 === "number" ? 拟合.后 : undefined;
  const 变化 = 前 !== undefined && 后 !== undefined && 前 !== 0 ? ((后 - 前) / Math.abs(前)) * 100 : undefined;

  return (
    <div>
      <CollapsibleSection
        title={t("辨识.标题")}
        badge={
          辨识?.状态 ? (
            <Tag tone={运行中 ? "emphasis" : 完成 ? "success" : 出错 ? "error" : "neutral"}>{辨识.状态}</Tag>
          ) : (
            <Tag>{t("辨识.尚无状态")}</Tag>
          )
        }
      >
        {辨识 ? (
          <ValueTable rows={概览} />
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
              className="输入 mt-0.5 等宽"
              value={时长}
              inputMode="decimal"
              onChange={(e) => 设时长(e.target.value)}
            />
          </label>
          <Button
            variant="primary"
            disabled={忙 !== null || !可发 || 运行中}
            onPress={() => void 发命令("开始")}
          >
            {忙 === "开始" ? "…" : t("辨识.开始")}
          </Button>
          <Button
            variant="secondary"
            disabled={忙 !== null || !运行中}
            title={!运行中 ? t("辨识.停止条件") : undefined}
            onPress={() => void 发命令("停止")}
          >
            {忙 === "停止" ? "…" : t("辨识.停止")}
          </Button>
          {辨识 ? (
            <Button variant="ghost" size="small" onPress={导出结果}>
              {t("辨识.导出")}
            </Button>
          ) : null}
        </div>
        <p className="mt-1 text-[0.85em] text-dim">{t("辨识.时长说明")}</p>
        {最近回执 ? (
          <div
            className="mt-1 等宽 text-[0.9em]"
            style={{ color: 最近回执.通过 ? "var(--ok)" : "var(--danger)" }}
          >
            {最近回执.通过 ? "ok" : "fail"} —— {最近回执.文本}
          </div>
        ) : null}
      </CollapsibleSection>

      <CollapsibleSection title={t("辨识.结果")} badge={<span className="等宽">{结果行.length || ""}</span>}>
        {结果行.length ? (
          <DataTable columns={结果列} rows={结果行} rowKey={(_r, i) => String(i)} />
        ) : (
          <div className="text-dim">{t("辨识.没结果")}</div>
        )}
      </CollapsibleSection>

      <CollapsibleSection title={t("辨识.拟合")} badge={<span className="等宽">{拟合 ? Object.keys(拟合).length : ""}</span>}>
        {拟合 ? (
          <>
            <ValueTable rows={拟合行} />
            {变化 !== undefined ? (
              <div className="mt-1 等宽">
                Δ = {变化 >= 0 ? "+" : ""}
                {变化.toFixed(2)} %
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
        badge={<span className="等宽">{辨识?.日志?.length ?? ""}</span>}
        defaultOpen={false}
      >
        {辨识?.日志?.length ? (
          <ol className="等宽 space-y-0.5 text-[0.9em]">
            {辨识.日志.map((行, i) => (
              <li key={i} className="break-all">
                <span className="text-dim">{String(i + 1).padStart(3, "0")} </span>
                {行}
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
