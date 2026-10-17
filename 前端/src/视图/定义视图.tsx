/**
 * 定义视图.tsx —— 任务流第 1 步：资产库 / 模型。
 *
 * 诚实边界（这一格最容易造假，所以先写清楚）：
 *   · **可浏览的模型库还没进契约**。`软件/契约.py` 的下行主题里只有「模型状态 = 当前模型」，
 *     没有"模型清单"这种东西。所以这里只列**当前模型**，模型库一栏显式标 `待接入`，
 *     而不是画一棵看起来很像的假目录树。
 *   · 真正有契约支撑的是**换模型命令**（`命令.换模型`），所以它是这一格唯一的真交互：
 *     走"发出 → 等回执 → 写控制台 + 提示"，不搞"点了就算成功"。
 */
import { useState } from "react";
import { 数值表, 文本, type 数值行 } from "../组件/数值表";
import { 可折叠区块 } from "../组件/可折叠区块";
import { 按钮 } from "../组件/按钮";
import { 标签 } from "../组件/标签";
import { 命令, 用仓库 } from "../数据/仓库";
import { 命令收尾, 记命令发出, 记注意 } from "../数据/日志";
import type { 回执 } from "../数据/连接";
import { use取 } from "./文案";

/** 从 `算法` 那一列里取一个字段（后端给的是 `Record<string, unknown>[]`，形状由插件定） */
function 取字段(项: Record<string, unknown>, 名: string): unknown {
  return 项[名];
}

export function 定义视图() {
  const t = use取();
  const 模型 = 用仓库((s) => s.模型.数据);
  const 模型帧号 = 用仓库((s) => s.模型.帧号);
  const 项目 = 用仓库((s) => s.项目.数据);

  const [路径, 设路径] = useState("");
  const [显示名, 设显示名] = useState("");
  const [忙, 设忙] = useState(false);
  const [回执条, 设回执条] = useState<回执 | null>(null);

  const 提交换模型 = async () => {
    const 干净 = 路径.trim();
    if (!干净) {
      记注意("控制台", t("定义.换模型.要路径"));
      return;
    }
    设忙(true);
    const 起于 = 记命令发出();
    const r = 命令收尾("命令.换模型", await 命令.换模型(干净, 显示名.trim()), 起于);
    设回执条(r);
    设忙(false);
  };

  const 模型行: 数值行[] = 模型
    ? [
        { 键: t("定义.模型显示名"), 值: 模型.当前显示名 || t("通用.无") },
        { 键: t("定义.模型路径"), 值: 模型.当前路径 || "--", 纯文本: 模型.当前路径 },
        { 键: t("定义.自由度"), 值: <span className="等宽">{模型.自由度 ?? "--"}</span> },
        { 键: t("定义.执行器数"), 值: <span className="等宽">{模型.执行器数 ?? "--"}</span> },
        { 键: t("定义.模型状态"), 值: 模型.状态 || "--" },
        {
          键: t("定义.加载耗时"),
          值: <span className="等宽">{模型.耗时 === undefined ? "--" : `${模型.耗时.toFixed(3)} s`}</span>,
        },
      ]
    : [];

  const 项目行: 数值行[] = 项目
    ? [
        { 键: t("定义.项目名"), 值: 项目.项目 || t("通用.无") },
        { 键: t("定义.算法数"), 值: <span className="等宽">{项目.算法?.length ?? 0}</span> },
        { 键: t("定义.控盘"), 值: 项目.控盘 || t("通用.无") },
        {
          键: t("定义.被覆盖"),
          值: 项目.被覆盖?.length ? 项目.被覆盖.join(" / ") : t("通用.无"),
        },
        {
          键: t("定义.已存盘"),
          值: 项目.已存盘 === undefined ? "--" : 项目.已存盘 ? t("通用.是") : t("通用.否"),
        },
      ]
    : [];

  const 已挂 = new Set(
    (项目?.算法 ?? []).map((a) => String(取字段(a, "名称") ?? 取字段(a, "插件") ?? "")),
  );

  return (
    <div>
      <可折叠区块
        标题={t("定义.当前模型")}
        徽标={
          模型 ? (
            <span className="等宽">{模型.自由度 === undefined ? "" : `${模型.自由度} DoF`}</span>
          ) : (
            <标签 语气="警示">{t("通用.未接入")}</标签>
          )
        }
      >
        {模型 ? (
          <>
            <数值表 行={模型行} />
            <div className="mt-2 text-[0.85em] text-dim 等宽">#{模型帧号}</div>
          </>
        ) : (
          <div className="text-dim">{t("定义.没模型")}</div>
        )}
      </可折叠区块>

      <可折叠区块
        标题={t("定义.当前项目")}
        徽标={
          <span className="等宽">
            {项目 ? `${项目.算法?.length ?? 0}` : ""}
          </span>
        }
      >
        {项目 ? (
          <>
            <数值表 行={项目行} />
            {项目.算法?.length ? (
              <ul className="mt-2 space-y-0.5">
                {项目.算法.map((a, i) => (
                  <li key={i} className="flex items-baseline gap-1.5">
                    <span className="等宽 text-dim">·</span>
                    <span className="break-all">{文本(取字段(a, "名称") ?? 取字段(a, "插件"))}</span>
                    {取字段(a, "接管控制") ? <标签 语气="强调">{t("定义.控盘")}</标签> : null}                  </li>
                ))}
              </ul>
            ) : null}
            {项目.报告?.length ? (
              <div className="mt-2">
                <div className="text-dim">{t("定义.装配报告")}</div>
                <ul className="等宽 space-y-0.5">
                  {项目.报告.map((行, i) => (
                    <li key={i} className="break-all">
                      {行}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : (
          <div className="text-dim">{t("定义.没项目")}</div>
        )}
      </可折叠区块>

      <可折叠区块
        标题={t("定义.资产库")}
        徽标={<标签 语气="警示">{t("通用.待接入")}</标签>}
        默认开={false}
      >
        <p className="text-dim">{t("定义.资产库.待接入")}</p>
        <p className="mt-1 text-dim">{t("定义.资产库.后补")}</p>
        {模型 ? (
          <div className="mt-2 面板 p-2">
            <div className="mb-1 text-dim">{t("定义.当前模型")}</div>
            <div className="break-all">{模型.当前显示名 || t("通用.无")}</div>
            <div className="等宽 break-all text-dim">{模型.当前路径 || "--"}</div>
          </div>
        ) : null}
      </可折叠区块>

      <可折叠区块
        标题={t("定义.算法库")}
        徽标={<span className="等宽">{项目?.算法库?.length ?? ""}</span>}
        默认开={false}
      >
        <p className="text-dim">{t("定义.算法库.说明")}</p>
        {项目?.算法库?.length ? (
          <ul className="mt-1 space-y-0.5">
            {项目.算法库.map((名) => (
              <li key={名} className="flex items-baseline gap-1.5">
                <span aria-hidden="true" className="等宽 text-dim">
                  {已挂.has(名) ? "☑" : "☐"}
                </span>
                <span className="break-all">{名}</span>
                {已挂.has(名) ? <标签 语气="强调">{t("定义.算法库.已挂")}</标签> : null}
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-dim">{t("定义.算法库.空")}</div>
        )}
      </可折叠区块>

      <可折叠区块 标题={t("定义.换模型")} 默认开={false}>
        <p className="text-dim">{t("定义.换模型.说明")}</p>
        <div className="mt-2 space-y-2">
          <label className="block">
            <span className="text-dim">{t("定义.换模型.路径")}</span>
            <input
              className="输入 mt-0.5 等宽"
              value={路径}
              spellCheck={false}
              placeholder={t("定义.换模型.例子")}
              onChange={(e) => 设路径(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void 提交换模型();
              }}
            />
          </label>
          <label className="block">
            <span className="text-dim">{t("定义.换模型.显示名")}</span>
            <input
              className="输入 mt-0.5"
              value={显示名}
              spellCheck={false}
              onChange={(e) => 设显示名(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void 提交换模型();
              }}
            />
          </label>
          <按钮 种类="主" 尺寸="中" disabled={忙 || !路径.trim()} on按下={() => void 提交换模型()}>
            {忙 ? "…" : t("定义.换模型.提交")}
          </按钮>
          {回执条 ? (
            <div className="text-[0.9em]" style={{ color: 回执条.通过 ? "var(--fg)" : "var(--fg-dim)" }}>
              <span className="等宽">
                {回执条.主题}：{回执条.通过 ? "ok" : "fail"} —— {回执条.说明 || t("日志.无说明")}
              </span>
            </div>
          ) : null}
        </div>
      </可折叠区块>
    </div>
  );
}
