/**
 * 控制台.tsx —— 底部三页签：输出 / 事件 / 问题。
 *
 * 数据只有两个来源，都是真的：
 *   ① `数据/日志.ts` —— 连接状态、握手、回执、后端错误、前端异常（逐条留痕）
 *   ② `数据/仓库.ts` —— 主题计数与速率（每秒实测差值）
 *
 * 「问题」页签不是装饰：它是**按真实连接状态推导出来的校验**，
 * 每一条都给出依据（哪几行日志）。没问题时它说"没有发现问题"，
 * 并且补一句"这不代表软件没缺陷"—— 一个永远全绿的检查器本身就是假实现。
 */
import { useMemo, useState } from "react";
import { 清日志, 取日志, 用日志, type 日志等级, type 日志行, type 速率行 } from "../数据/日志";
import { 按钮 } from "../组件/按钮";
import { 标签 } from "../组件/标签";
import { 用仓库 } from "../数据/仓库";
import { 用节拍 } from "../数据/时钟";
import { 连接键, use取, 时刻 } from "../视图/文案";

export type 控制台页签 = "输出" | "事件" | "问题";

export interface 控制台参数 {
  页签: 控制台页签;
  on换页签: (页: 控制台页签) => void;
}

/** 等级 → 文字色。只有两种色（正文 / 次要）加链接色，全靠主题变量。 */
const 等级色: Record<日志等级, string> = {
  信息: "var(--fg)",
  注意: "var(--fg-dim)",
  错误: "var(--fg-link)",
};

export function 控制台({ 页签, on换页签 }: 控制台参数) {
  const t = use取();
  const 快照 = 用日志();
  const 连接 = 用仓库((s) => s.连接);
  const 错误 = 用仓库((s) => s.错误);
  const 握手 = 用仓库((s) => s.握手);

  const [只看来源, 设只看来源] = useState<Set<string>>(new Set());

  const 行们 = useMemo(
    () => (只看来源.size ? 快照.行.filter((l) => 只看来源.has(l.来源)) : 快照.行),
    [快照.行, 只看来源],
  );

  const 事件行 = useMemo(
    () => 行们.filter((l) => l.来源 === "连接" || l.来源 === "握手" || l.来源 === "回执"),
    [行们],
  );

  const 来源们 = useMemo(() => {
    const 集 = new Set<string>();
    for (const l of 快照.行) 集.add(l.来源);
    return [...集].sort();
  }, [快照.行]);

  const 问题 = 用问题(连接, 错误, 握手, 快照.行);
  const 页签们: 控制台页签[] = ["输出", "事件", "问题"];

  return (
    <section
      aria-label={t("控制台.标题")}
      className="flex h-full min-h-0 flex-col"
      style={{ background: "var(--bg-menu)" }}
    >
      <div
        className="flex flex-none flex-wrap items-center gap-1 px-1 py-0.5"
        style={{ borderBottom: "1px solid var(--border)" }}
        role="tablist"
        aria-label={t("控制台.标题")}
      >
        {页签们.map((p) => {
          const 选中 = p === 页签;
          const 徽标 = p === "问题" ? 问题.length : p === "事件" ? 事件行.length : 行们.length;
          return (
            <button
              key={p}
              role="tab"
              type="button"
              aria-selected={选中}
              onClick={() => on换页签(p)}
              className="flex items-center gap-1.5 px-2 py-1"
              style={{
                background: 选中 ? "var(--bg-tab-on)" : "transparent",
                color: 选中 ? "var(--fg)" : "var(--fg-dim)",
                borderBottom: `2px solid ${选中 ? "var(--grab)" : "transparent"}`,
              }}
            >
              <span>{t(`控制台.页签.${p}` as const)}</span>
              <span className="等宽 text-[0.85em]">{徽标 || ""}</span>
            </button>
          );
        })}

        <span className="flex-1" />

        {来源们.length > 1 ? (
          <div className="flex flex-wrap items-center gap-1" title={t("控制台.筛选.说明")}>
            {来源们.map((s) => (
              <按钮
                key={s}
                尺寸="小"
                种类={只看来源.has(s) ? "主" : "幽灵"}
                已按下={只看来源.has(s)}
                on按下={() =>
                  设只看来源((旧) => {
                    const 新 = new Set(旧);
                    if (新.has(s)) 新.delete(s);
                    else 新.add(s);
                    return 新;
                  })
                }
              >
                {s}
              </按钮>
            ))}
            {只看来源.size ? (
              <按钮 尺寸="小" 种类="幽灵" on按下={() => 设只看来源(new Set())}>
                {t("控制台.筛选.全部")}
              </按钮>
            ) : null}
          </div>
        ) : null}

        <按钮 尺寸="小" 种类="幽灵" on按下={清日志} title={t("控制台.清空不了")}>
          {t("控制台.清空")}
        </按钮>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {页签 === "输出" ? (
          <>
            <日志列表 行={行们} />
            <div className="px-2 py-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-dim">{t("控制台.速率.标题")}</span>
                <标签>{t("控制台.速率.说明")}</标签>
              </div>
              {快照.速率.length ? (
                <速率表 行={快照.速率} />
              ) : (
                <div className="mt-1 text-dim">{t("控制台.速率.空")}</div>
              )}
            </div>
          </>
        ) : 页签 === "事件" ? (
          <日志列表 行={事件行} />
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
    <div className="等宽 mt-1 text-[0.9em]">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="border-b px-1.5 py-0.5 text-left font-normal text-dim">
              {t("控制台.列.主题")}
            </th>
            <th className="border-b px-1.5 py-0.5 text-right font-normal text-dim">
              {"Σ"}
            </th>
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

function 日志列表({ 行 }: { 行: 日志行[] }) {
  const t = use取();
  const [展开, 设展开] = useState<number | null>(null);

  if (!行.length) {
    return (
      <div className="p-3 text-dim">
        <div>{t("控制台.空")}</div>
        <div className="mt-1">{t("控制台.空提示")}</div>
      </div>
    );
  }

  return (
    <ol className="等宽 text-[0.9em]">
      {行.map((l) => (
        <li key={l.序号} style={{ borderBottom: "1px solid var(--border-light)" }}>
          <button
            type="button"
            className="flex w-full items-start gap-2 px-2 py-0.5 text-left"
            aria-expanded={展开 === l.序号}
            onClick={() => 设展开(展开 === l.序号 ? null : l.序号)}
          >
            <span className="flex-none text-dim">{时刻(l.墙钟)}</span>
            <span className="w-[3em] flex-none" style={{ color: 等级色[l.等级] }}>
              {l.等级}
            </span>
            <span className="w-[3em] flex-none text-dim">{l.来源}</span>
            <span className="hidden w-[8em] flex-none truncate text-dim sm:inline" title={l.主题}>
              {l.主题 ?? ""}
            </span>
            <span className="min-w-0 flex-1 break-all">{l.文本}</span>
          </button>
          {展开 === l.序号 && l.细节 ? (
            <pre className="whitespace-pre-wrap break-all px-2 pb-1 text-dim">{l.细节}</pre>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

interface 问题项 {
  键: string;
  等级: 日志等级;
  说明: string;
  依据: React.ReactNode;
}

/** 问题 = 按真实连接状态推导的校验；每条都带依据 */
function 用问题(
  连接: string,
  错误: string | null,
  握手: { 可用主题: string[] } | null,
  行: 日志行[],
): 问题项[] {
  const t = use取();
  const 出: 问题项[] = [];

  if (连接 !== "已连接") {
    出.push({
      键: "连接",
      等级: "注意",
      说明: t("问题.未连接"),
      依据: <span>{t("问题.未连接.说明", { 状态: t(连接键[连接 as keyof typeof 连接键] ?? "连接.连接中") })}</span>,
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
        {问题.map((p) => (
          <li key={p.键} className="面板 p-2">
            <div className="flex items-center gap-1.5">
              <标签 语气={p.等级 === "错误" ? "警示" : "中性"}>{p.等级}</标签>
              <span>{p.说明}</span>
            </div>
            <div className="mt-1 text-[0.9em] text-dim">{p.依据}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
