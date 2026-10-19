/**
 * 定义视图.tsx —— 任务流第 1 步：模型 / 项目 / 资产库。
 *
 * 诚实边界（这一格最容易造假，所以先写清楚）：
 *   · 资产库**已是真清单**：数据来自契约里的「资产库」主题（后端读 `模型清单.json`），
 *     点一台就发 `命令.换模型`。
 *   · **路径不手写**：路径由后端给，界面不拼、不猜；长路径只显示文件名 + 上级目录，
 *     完整路径放 title，并提供复制。
 *   · 兼容性提示**只从 `项目状态.报告` 推**，报告里没有「不兼容」就不画警告；
 *     不猜"应该兼容"，也不把报告里的长文原样铺满整屏。
 *   · 换模型走"发出 → 等回执 → 写控制台 + 提示"，不搞"点了就算成功"。
 *
 * 布局取舍（响应工程师的"左栏太挤"）：
 *   · 模型、项目两块默认展开；资产库/算法库/换模型默认收起。
 *   · 装配报告是 `<details>`，默认收起；顶部兼容性提示只显示结论与下一步。
 *   · 模型/项目字段用两列表格；长路径、长状态截断并提供完整内容。
 */
import { useState } from "react";
import { 数值表, 文本, type 数值行 } from "../组件/数值表";
import { 可折叠区块 } from "../组件/可折叠区块";
import { 按钮 } from "../组件/按钮";
import { 标签 } from "../组件/标签";
import { 路径值 } from "../组件/路径值";
import { 命令, 用仓库 } from "../数据/仓库";
import { 请求跳步 } from "../外壳/跳步";
import { 命令收尾, 记命令发出, 记注意 } from "../数据/日志";
import type { 回执 } from "../数据/连接";
import { use取 } from "./文案";

/** 从 `算法` 那一列里取一个字段（后端给的是 `Record<string, unknown>[]`，形状由插件定） */
function 取字段(项: Record<string, unknown>, 名: string): unknown {
  return 项[名];
}

/** 模型状态：好/坏/未知都用「符号 + 文字」表达，颜色只是辅助 */
function 模型状态({ 状态 }: { 状态?: string }) {
  if (!状态) return <span className="text-dim">--</span>;
  const 坏 = /^✗|失败|错误|不可用/.test(状态);
  const 好 = /^✓|就绪|已切换|已加载/.test(状态);
  const 语气 = 坏 ? "var(--danger)" : 好 ? "var(--ok)" : "var(--fg)";
  const 符号 = 坏 ? "✗" : 好 ? "✓" : "•";
  // 后端的状态串自己可能已经带 ✓/✗；先剥掉再统一加一次，避免出现「✓ ✓ 就绪」。
  const 正文 = 状态.replace(/^\s*[✓✗•]\s*/, "");
  return (
    <span className="状态文本 flex min-w-0 items-center justify-end gap-1" style={{ color: 语气 }} title={状态}>
      <span aria-hidden="true" className="flex-none">{符号}</span>
      <span className="min-w-0 whitespace-normal break-all">{正文}</span>
    </span>
  );
}

/** 顶部的兼容性提示：只显示报告里真的写了「不兼容」的行 */
function 兼容性提示({ 行们, on查看 }: { 行们: string[]; on查看: () => void }) {
  const t = use取();
  return (
    <div className="兼容条" role="alert">
      <div className="flex flex-wrap items-center gap-1.5">
        <标签 语气="警告">! {t("定义.兼容性")}</标签>
        <span className="兼容标题">{t("定义.兼容性.标题")}</span>
      </div>
      <ul className="mt-1.5 space-y-0.5 text-[0.82em]">
        {行们.map((行) => (
          <li key={行} className="break-all">
            {行.replace(/^[-·]\s*/, "")}
          </li>
        ))}
      </ul>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.8em] text-dim">
        <span>{t("定义.兼容性.影响")}</span>
        <span aria-hidden="true">·</span>
        <span>{t("定义.兼容性.下一步")}</span>
      </div>
      <div className="mt-1.5">
        <按钮 尺寸="小" 种类="幽灵" on按下={on查看}>
          {t("定义.兼容性.查看")}
        </按钮>
      </div>
    </div>
  );
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
  const [报告开, 设报告开] = useState(false);

  /**
   * 发一次换模型。
   * ★ 抽成带参数的函数，让"手填路径"和"点资产库"走**同一条路** ——
   *   否则两条路迟早一条有回执、一条没有。
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

  // 兼容性只从装配报告里取，报告没写就不画警告
  const 不兼容行 = (项目?.报告 ?? []).filter((行) => 行.includes("不兼容"));
  const 打开报告 = () => {
    设报告开(true);
    window.setTimeout(() => {
      document.getElementById("装配报告")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, 0);
  };

  const 模型行: 数值行[] = 模型
    ? [
        { 键: t("定义.模型显示名"), 值: 模型.当前显示名 || t("通用.无"), 纯文本: 模型.当前显示名 },
        {
          键: t("定义.模型路径"),
          值: <路径值 路径={模型.当前路径} />,
          纯文本: 模型.当前路径,
        },
        {
          键: t("定义.自由度"),
          值: <span className="等宽">{模型.自由度 ?? "--"}</span>,
          提示: t("定义.自由度.提示"),
        },
        {
          键: t("定义.执行器数"),
          值: <span className="等宽">{模型.执行器数 ?? "--"}</span>,
          提示: t("定义.执行器数.提示"),
        },
        {
          键: t("定义.模型状态"),
          值: <模型状态 状态={模型.状态} />,
          纯文本: 模型.状态,
        },
        {
          键: t("定义.加载耗时"),
          值: <span className="等宽">{模型.耗时 === undefined ? "--" : `${模型.耗时.toFixed(3)} s`}</span>,
        },
      ]
    : [];

  const 项目行: 数值行[] = 项目
    ? [
        { 键: t("定义.项目名"), 值: 项目.项目 || t("通用.无"), 纯文本: 项目.项目 },
        { 键: t("定义.算法数"), 值: <span className="等宽">{项目.算法?.length ?? 0}</span> },
        { 键: t("定义.控盘"), 值: 项目.控盘 || t("通用.无"), 纯文本: 项目.控盘 },
        {
          键: t("定义.被覆盖"),
          值: 项目.被覆盖?.length ? 项目.被覆盖.join(" / ") : t("通用.无"),
          纯文本: 项目.被覆盖?.join(" / "),
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
  const 无算法 = (项目?.算法?.length ?? 0) === 0;

  return (
    <div className="space-y-2">
      {不兼容行.length ? <兼容性提示 行们={不兼容行} on查看={打开报告} /> : null}

      <可折叠区块
        标题={t("定义.当前模型")}
        徽标={
          模型 ? (
            <span className="flex items-center gap-1.5">
              {模型.自由度 !== undefined && 模型.执行器数 !== undefined && 模型.自由度 !== 模型.执行器数 ? (
                <标签 语气="警告" title={t("定义.nqnu.说明")}>! nq≠nu</标签>
              ) : null}
              <span className="等宽">{模型.自由度 === undefined ? "" : `${模型.自由度} DoF`}</span>
            </span>
          ) : (
            <标签 语气="警示">{t("通用.未接入")}</标签>
          )
        }
      >
        {模型 ? (
          <>
            <数值表 行={模型行} />
            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.78em] text-dim">
              <span>{t("定义.nqnu.说明")}</span>
              <span className="等宽">#{模型帧号}</span>
            </div>
            <div className="mt-0.5 text-[0.78em] text-dim">{t("定义.单位.说明")}</div>
          </>
        ) : (
          <div className="text-dim">{t("定义.没模型")}</div>
        )}
      </可折叠区块>

      <可折叠区块
        标题={t("定义.当前项目")}
        徽标={
          <span className="flex items-center gap-1.5">
            {不兼容行.length ? (
              <标签 语气="警告">! {t("定义.兼容性")}</标签>
            ) : 无算法 ? (
              <标签 语气="中性">{t("定义.兼容性.未评估")}</标签>
            ) : 项目?.报告?.length ? (
              <标签 语气="成功">✓ {t("定义.兼容性.通过")}</标签>
            ) : null}
            <span className="等宽 text-[0.78em] text-dim" title={t("定义.算法数")}>
              {项目 ? t("定义.算法数.短", { 数量: 项目.算法?.length ?? 0 }) : ""}
            </span>
          </span>
        }
      >
        {项目 ? (
          <>
            <数值表 行={项目行} />

            {无算法 ? (
              <div className="mt-2 rounded border border-dashed px-2 py-1.5 text-[0.8em] text-dim" style={{ borderColor: "var(--border-strong)" }}>
                <div>{t("定义.算法.未添加说明")}</div>
                <按钮 尺寸="小" 种类="幽灵" className="mt-1" on按下={() => 请求跳步("插件")}>
                  {t("定义.算法.去插件")}
                </按钮>
              </div>
            ) : null}

            {项目.算法?.length ? (
              <ul className="mt-2 space-y-1">
                {项目.算法.map((a, i) => {
                  const 名 = 文本(取字段(a, "名称") ?? 取字段(a, "插件"));
                  const 版本 = 文本(取字段(a, "版本"));
                  const 不兼容 = 不兼容行.some((行) => 名 && 行.includes(名));
                  return (
                    <li key={i} className="算法项">
                      <span className="算法名">{名}</span>
                      {版本 !== "--" ? <span className="算法版本 等宽 text-dim">v{版本}</span> : null}
                      {取字段(a, "接管控制") ? <标签 语气="强调">{t("定义.控盘")}</标签> : null}
                      {不兼容 ? <标签 语气="警告">! {t("定义.算法状态.不兼容")}</标签> : null}
                    </li>
                  );
                })}
              </ul>
            ) : null}

            <details
              id="装配报告"
              className="装配详情 mt-2"
              open={报告开}
              onToggle={(e) => 设报告开(e.currentTarget.open)}
            >
              <summary>{t("定义.装配报告")}（{项目.报告?.length ?? 0}）</summary>
              {项目.报告?.length ? (
                <ul className="mt-1 space-y-0.5 等宽 text-[0.82em]">
                  {项目.报告.map((行, i) => (
                    <li key={i} className="break-all">
                      {行}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-1 text-dim">{t("定义.装配报告.空")}</div>
              )}
            </details>
          </>
        ) : (
          <div className="text-dim">{t("定义.没项目")}</div>
        )}
      </可折叠区块>

      <可折叠区块
        标题={t("定义.资产库")}
        默认开={false}
        徽标={
          资产?.数量 ? (
            <标签>{资产.数量}</标签>
          ) : (
            <标签 语气="警示">{t("通用.待接入")}</标签>
          )
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
                    尺寸="小"
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
                      <span className="hidden w-[86px] flex-none truncate text-right text-[0.8em] text-dim sm:inline">
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
            <div className="text-[0.9em]" style={{ color: 回执条.通过 ? "var(--ok)" : "var(--danger)" }}>
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
