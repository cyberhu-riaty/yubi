/**
 * 中区.tsx —— 常驻的 3D 视口占位 + 右上角浮层。
 *
 * ★ 这一格**不随任务流切换**（`约定.md` §三：视图不换、只换上下文）。
 *   切换左侧步骤时中区一个像素都不该动，连 canvas 都不重建。
 *
 * ✅ 它做的事：把后端**真报上来**的模型/引擎信息、以及真收到过的指标序列
 *    （每个键一条迷你走势 + 当前值）显示出来。
 *
 * ✅ P3 之后：原生 3D 表面**真的接上了** —— 但不是接在这一格里，而是由宿主窗口
 *   放在这一格**下方**（同级视图）。所以这一格仍然什么都不画，只是说明改成了实话。
 *
 * ❌ 它不做的事（每一件都是验收项里的"假实现"）：
 *   · 不摆一个假的 3D 场景（网格、机械臂模型、坐标轴都不画）—— 真画面在下方那一格
 *   · 不按 URDF 自己算正运动学 —— 会与物理漂移，加载带自由关节的模型立刻露馅
 *   · 不把"关节状态"编出来：没有关节角数据源，浮层里就写"还没有指标序列"，
 *     而不是画一排看起来像关节角的数字
 */
import { useMemo } from "react";
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { 数值表, 数值文本, type 数值行 } from "../组件/数值表";
import { 用仓库 } from "../数据/仓库";
import type { 采样点 } from "../数据/连接";
import { 契约版本, 协议版本 } from "@生成/契约";
import { 用风格 } from "../生成/外观";
import { 连接键, use取 } from "../视图/文案";

export interface 中区参数 {
  /** 迷你走势条最多显示多少条（再多就只报总数） */
  条数上限?: number;
}

export function 中区({ 条数上限 = 12 }: 中区参数) {
  const t = use取();
  const 模型 = 用仓库((s) => s.模型.数据);
  const 连接 = 用仓库((s) => s.连接);
  const 曲线数 = 用仓库((s) => s.曲线);
  const 皮肤 = 用风格();

  const 名们 = useMemo(() => Object.keys(曲线数).sort(), [曲线数]);
  const 显示条 = 名们.slice(0, 条数上限);

  const 模型行: 数值行[] = 模型
    ? [
        { 键: t("定义.模型显示名"), 值: 模型.当前显示名 || t("通用.无") },
        { 键: t("定义.自由度"), 值: <span className="等宽">{模型.自由度 ?? "--"}</span> },
        { 键: t("定义.执行器数"), 值: <span className="等宽">{模型.执行器数 ?? "--"}</span> },
        { 键: t("定义.模型状态"), 值: 模型.状态 || "--" },
        {
          键: t("定义.加载耗时"),
          值: <span className="等宽">{模型.耗时 === undefined ? "--" : `${模型.耗时.toFixed(3)} s`}</span>,
        },
      ]
    : [];

  const 引擎行: 数值行[] = [
    { 键: t("状态栏.连接"), 值: <span className="等宽">{t(连接键[连接])}</span> },
    { 键: t("状态栏.皮肤"), 值: <span className="等宽">{皮肤}</span> },
    { 键: t("关于.版本"), 值: <span className="等宽">{`${契约版本} / ${协议版本}`}</span> },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 视口本体：只画"这是占位"的说明，不画任何几何 */}
      <div
        className="relative min-h-0 flex-1 overflow-hidden"
        style={{ background: "var(--plot-bg)" }}
        aria-label={t("中区.标题")}
      >
        <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
          <div className="max-w-[46ch]">
            <div className="mb-1" style={{ fontWeight: 600 }}>
              {t("中区.未接入")}
            </div>
            <p className="text-dim">{t("中区.未接入说明")}</p>
            <p className="mt-2 text-[0.9em] text-dim">{t("中区.不重算")}</p>
            <p className="mt-2 text-[0.85em] text-dim">{t("中区.操作提示")}</p>
          </div>
        </div>

        {/* 右上角浮层：模型/引擎信息 + 指标走势条 */}
        <div
          className="面板 absolute right-2 top-2 max-h-[calc(100%-1rem)] w-[264px] overflow-y-auto"
          style={{ background: "var(--bg-popup)", boxShadow: "0 2px 10px var(--shadow)" }}
        >
          <可折叠区块
            标题={t("中区.浮层")}
            徽标={模型 ? <标签>{模型.当前显示名 || "…"}</标签> : <标签 语气="警示">{t("通用.未接入")}</标签>}
          >
            {模型 ? <数值表 行={模型行} /> : <div className="text-dim">{t("定义.没模型")}</div>}
            <div className="mt-2" style={{ borderTop: "1px solid var(--border-light)" }} />
            <div className="mt-2">
              <数值表 行={引擎行} />
            </div>
          </可折叠区块>

          <可折叠区块
            标题={t("中区.浮层") + " · " + t("验证.曲线")}
            徽标={<span className="等宽">{名们.length || ""}</span>}
          >
            {显示条.length ? (
              <ul className="space-y-1">
                {显示条.map((名) => (
                  <li key={名} className="flex items-center gap-1.5">
                    <span className="min-w-0 flex-1 truncate text-[0.85em] 等宽" title={名}>
                      {名}
                    </span>
                    <迷你走势 点={曲线数[名] ?? []} />
                    <span className="w-[68px] flex-none text-right text-[0.85em] 等宽">
                      <数值文本 值={曲线数[名]?.[曲线数[名].length - 1]?.v} 位={3} />
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="未接入 text-[0.9em]">
                <div>{t("中区.视口接口未就绪")}</div>
                <div className="mt-1">{t("验证.没有指标")}</div>
              </div>
            )}
            {名们.length > 显示条.length ? (
              <div className="mt-1 text-[0.85em] text-dim 等宽">+{名们.length - 显示条.length}</div>
            ) : null}
          </可折叠区块>
        </div>
      </div>

      {/* 底部一行：浮层收起时也看得到"3D 在下方" */}
      <div
        className="flex flex-none items-center gap-2 px-2 py-1 text-[0.85em] text-dim"
        style={{ borderTop: "1px solid var(--border)", background: "var(--bg-title)" }}
      >
        <标签 语气="警示">{t("通用.未接入")}</标签>
        <span className="truncate">{t("中区.未接入")}</span>
        <span className="flex-1" />
        <span className="等宽">{`${t("定义.自由度")}: ${模型?.自由度 ?? "--"}`}</span>
      </div>
    </div>
  );
}

/**
 * 迷你走势 —— 用真数据画的小折线（按窗口缩放）。
 * 少于两个点就画一个空槽，**不画一条平线**：平线会被读成"值恒定"。
 */
function 迷你走势({ 点 }: { 点: 采样点[] }) {
  const 宽 = 46;
  const 高 = 14;
  if (点.length < 2) {
    return (
      <svg width={宽} height={高} aria-hidden="true" className="flex-none">
        <rect x="0.5" y="0.5" width={宽 - 1} height={高 - 1} fill="none" stroke="var(--border)" />
      </svg>
    );
  }
  let 大 = -Infinity;
  let 小 = Infinity;
  for (const p of 点) {
    if (p.v > 大) 大 = p.v;
    if (p.v < 小) 小 = p.v;
  }
  const 幅 = 大 - 小 || 1;
  const 路径 = 点
    .map((p, i) => {
      const x = (i / (点.length - 1)) * 宽;
      const y = 高 - ((p.v - 小) / 幅) * 高;
      return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={宽} height={高} aria-hidden="true" className="flex-none">
      <path d={路径} fill="none" stroke="var(--palette-1)" strokeWidth="1" />
    </svg>
  );
}
