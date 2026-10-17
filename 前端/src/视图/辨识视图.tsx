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
import { 可折叠区块 } from "../组件/可折叠区块";
import { 按钮 } from "../组件/按钮";
import { 标签 } from "../组件/标签";
import { 小表格, 数值表, 数值文本, 文本, type 列, type 数值行 } from "../组件/数值表";
import { 命令, 用仓库 } from "../数据/仓库";
import { 命令收尾, 记命令发出 } from "../数据/日志";
import { use取 } from "./文案";

/** 结果行里"名称/标称/辨识值/变化"这四个字段名跟后端一致；缺哪个就显示 `--` */
const 结果字段 = ["名称", "标称", "辨识值", "变化"] as const;

export function 辨识视图() {
  const t = use取();
  const 辨识 = 用仓库((s) => s.辨识.数据);
  const 帧号 = 用仓库((s) => s.辨识.帧号);

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
    const r = 命令收尾(主题, 回执, 起于);
    设最近回执({ 通过: r.通过, 文本: `${r.主题}：${r.说明 || t("日志.无说明")}` });
    设忙(null);
  };

  const 概览: 数值行[] = [
    { 键: t("辨识.状态"), 值: 辨识?.状态 || "--", 弱: !辨识?.状态 },
    { 键: t("辨识.进度"), 值: 辨识?.进度 || "--", 弱: !辨识?.进度 },
    {
      键: t("辨识.采样步数"),
      值: <span className="等宽">{辨识?.采样步数 ?? "--"}</span>,
    },
    {
      键: t("辨识.耗时"),
      值: <span className="等宽">{辨识?.耗时 === undefined ? "--" : `${辨识.耗时.toFixed(3)} s`}</span>,
    },
    {
      键: t("关于.帧号"),
      值: <span className="等宽">{辨识 ? `#${帧号}` : "--"}</span>,
      弱: !辨识,
    },
  ];

  const 结果行 = 辨识?.结果 ?? [];
  const 结果列: 列[] = 结果字段.map((字段) => ({
    标题: 字段,
    数字: 字段 !== "名称",
    格: (行: Record<string, unknown>) =>
      字段 === "名称" ? (
        <span className="break-all">{文本(行[字段])}</span>
      ) : (
        <数值文本 值={行[字段] as number | undefined} 位={6} />
      ),
  }));

  const 拟合 = 辨识?.拟合;
  const 拟合行: 数值行[] = 拟合
    ? Object.keys(拟合).map((k) => ({
        键: k,
        值: <数值文本 值={拟合[k] as number | undefined} 位={6} />,
      }))
    : [];

  // 残差变化：只在"前/后"都是真数字时才算 —— 缺一个就什么都不显示
  const 前 = typeof 拟合?.前 === "number" ? 拟合.前 : undefined;
  const 后 = typeof 拟合?.后 === "number" ? 拟合.后 : undefined;
  const 变化 = 前 !== undefined && 后 !== undefined && 前 !== 0 ? ((后 - 前) / Math.abs(前)) * 100 : undefined;

  return (
    <div>
      <可折叠区块
        标题={t("辨识.标题")}
        徽标={
          <>
            {辨识?.状态 ? <标签 语气="强调">{辨识.状态}</标签> : <标签 语气="警示">{t("通用.未接入")}</标签>}
          </>
        }
      >
        {辨识 ? <数值表 行={概览} /> : <div className="text-dim">{t("辨识.没状态")}</div>}

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
          <按钮 种类="主" disabled={忙 !== null} on按下={() => void 发命令("开始")}>
            {忙 === "开始" ? "…" : t("辨识.开始")}
          </按钮>
          <按钮 种类="次" disabled={忙 !== null} on按下={() => void 发命令("停止")}>
            {忙 === "停止" ? "…" : t("辨识.停止")}
          </按钮>
        </div>
        <p className="mt-1 text-[0.85em] text-dim">{t("辨识.时长说明")}</p>
        {最近回执 ? (
          <div
            className="mt-1 等宽 text-[0.9em]"
            style={{ color: 最近回执.通过 ? "var(--fg)" : "var(--fg-dim)" }}
          >
            {最近回执.通过 ? "ok" : "fail"} —— {最近回执.文本}
          </div>
        ) : null}
      </可折叠区块>

      <可折叠区块 标题={t("辨识.结果")} 徽标={<span className="等宽">{结果行.length || ""}</span>}>
        {结果行.length ? (
          <小表格 列={结果列} 行={结果行} 行键={(_r, i) => String(i)} />
        ) : (
          <div className="text-dim">{t("辨识.没结果")}</div>
        )}
      </可折叠区块>

      <可折叠区块 标题={t("辨识.拟合")} 徽标={<span className="等宽">{拟合 ? Object.keys(拟合).length : ""}</span>}>
        {拟合 ? (
          <>
            <数值表 行={拟合行} />
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
      </可折叠区块>

      <可折叠区块
        标题={t("辨识.日志")}
        徽标={<span className="等宽">{辨识?.日志?.length ?? ""}</span>}
        默认开={false}
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
      </可折叠区块>
    </div>
  );
}
