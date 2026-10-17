/**
 * 定义视图.tsx —— 任务流第 1 步：资产库 / 模型。
 *
 * 诚实边界（这一格最容易造假，所以先写清楚）：
 *   · 资产库**已是真清单**：数据来自契约里的「资产库」主题（后端读 `模型清单.json`），
 *     点一台就发 `命令.换模型`。★ 早先这一格标着"待接入"，是因为当时契约里只有
 *     「模型状态 = 当前模型」，没有"能选哪些"。契约补上之后这里才敢画列表。
 *   · **路径不手写**：列表项里的 `路径` 由后端给（= 清单里的「扭矩模型」），
 *     界面不拼路径、不猜文件在哪 —— 猜出来的路径点下去只会 404。
 *   · 换模型走"发出 → 等回执 → 写控制台 + 提示"，不搞"点了就算成功"。
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
  const 资产 = 用仓库((s) => s.资产.数据);
  const 项目 = 用仓库((s) => s.项目.数据);

  const [路径, 设路径] = useState("");
  const [显示名, 设显示名] = useState("");
  const [忙, 设忙] = useState(false);
  const [回执条, 设回执条] = useState<回执 | null>(null);

  /**
   * 发一次换模型。
   * ★ 抽成带参数的函数，让"手填路径"和"点资产库"走**同一条路** ——
   *   否则两条路迟早一条有回执、一条没有（那种差别排查起来极费劲）。
   */
  const 发换模型 = async (目标路径: string, 目标显示名 = "") => {
    设忙(true);
    try {
      const 起于 = 记命令发出();
      const r = 命令收尾("命令.换模型", await 命令.换模型(目标路径, 目标显示名), 起于);
      设回执条(r);
    } finally {
      设忙(false);
    }
  };

  const 提交换模型 = async () => {
    const 干净 = 路径.trim();
    if (!干净) {
      记注意("控制台", t("定义.换模型.要路径"));
      return;
    }
    await 发换模型(干净, 显示名.trim());
  };

  // 资产库列表：后端没报就空数组（不画假条目）
  const 清单 = 资产?.模型 ?? [];

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
        徽标={
          资产?.数量
            ? <标签>{资产.数量}</标签>
            : <标签 语气="警示">{t("通用.待接入")}</标签>
        }
      >
        <p className="text-dim">{t("定义.资产库.说明")}</p>
        {清单.length ? (
          <ul className="mt-2 space-y-1">
            {清单.map((项) => {
              const 是当前 = !!项.路径 && 项.路径 === 模型?.当前路径;
              return (
                <li key={项.标识 ?? 项.路径}>
                  <按钮
                    种类="次"
                    className="w-full"
                    disabled={忙 || 是当前}
                    title={是当前 ? t("定义.资产库.带星") : t("定义.资产库.点选", { 名: 项.显示名 ?? "?" })}
                    on按下={() => {
                       if (!项.路径) return;
                       void 发换模型(项.路径, 项.显示名 ?? "");
                    }}
                  >
                    <span className="flex w-full items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-left">
                        {项.显示名 || 项.标识 || "?"}
                      </span>
                      <span className="flex-none text-[0.85em] text-dim 等宽">
                        {`${项.自由度 ?? "--"} DoF`}
                      </span>
                      <span className="w-[86px] flex-none truncate text-right text-[0.8em] text-dim">
                        {项.许可 ?? ""}
                      </span>
                      {是当前 ? <标签>{t("定义.资产库.带星")}</标签> : null}
                    </span>
                  </按钮>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="mt-2 text-dim">{t("定义.资产库.空")}</div>
        )}
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
