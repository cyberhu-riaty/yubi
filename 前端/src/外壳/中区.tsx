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
 *   放在这一格**右侧**（同级视图）。所以这一格仍然什么都不画，只是说明改成了实话。
 *
 * ❌ 它不做的事（每一件都是验收项里的"假实现"）：
 *   · 不摆一个假的 3D 场景（网格、机械臂模型、坐标轴都不画）—— 真画面在右侧那一格
 *   · 不按 URDF 自己算正运动学 —— 会与物理漂移，加载带自由关节的模型立刻露馅
 *   · 不把"关节状态"编出来：没有关节角数据源，浮层里就写"还没有指标序列"，
 *     而不是画一排看起来像关节角的数字
 */
import { useEffect, useMemo, useState } from "react";
import { Tag } from "../组件/标签";
import { Button } from "../组件/按钮";
import { ValueTable, NumericText, type ValueRow } from "../组件/数值表";
import { 命令, 用仓库 } from "../数据/仓库";
import { 命令收尾, 记命令发出 } from "../数据/日志";
import type { SamplePoint } from "../数据/connection";
import { 契约版本, 协议版本 } from "@生成/契约";
import { 用风格 } from "../生成/外观";
import { connectionTranslationKeys, useTranslation } from "../视图/文案";

export interface 中区参数 {
  /** 迷你走势条最多显示多少条（再多就只报总数） */
  条数上限?: number;
}

export function 中区({ 条数上限 = 12 }: 中区参数) {
  const t = useTranslation();
  const 模型 = 用仓库((s) => s.模型.数据);
  const 连接 = 用仓库((s) => s.连接);
  const 曲线数 = 用仓库((s) => s.曲线);
  const 皮肤 = 用风格();

  const 名们 = useMemo(() => Object.keys(曲线数).sort(), [曲线数]);
  const 显示条 = 名们.slice(0, 条数上限);

  const 模型行: ValueRow[] = 模型
    ? [
        { key: t("定义.模型显示名"), value: 模型.current_display_name || t("通用.无") },
        { key: t("定义.自由度"), value: <span className="等宽">{模型.dof ?? "--"}</span> },
        { key: t("定义.执行器数"), value: <span className="等宽">{模型.actuator_count ?? "--"}</span> },
        { key: t("定义.模型状态"), value: 模型.status || "--" },
        {
          key: t("定义.加载耗时"),
          value: <span className="等宽">{模型.duration_s === undefined ? "--" : `${模型.duration_s.toFixed(3)} s`}</span>,
        },
      ]
    : [];

  const 引擎行: ValueRow[] = [
    { key: t("状态栏.连接"), value: <span className="等宽">{t(connectionTranslationKeys[连接])}</span> },
    { key: t("状态栏.皮肤"), value: <span className="等宽">{皮肤}</span> },
    { key: t("关于.契约版本"), value: <span className="等宽">{`${契约版本} / ${协议版本}`}</span> },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 视口本体：只画"这是占位"的说明，不画任何几何 */}
      <div
        className="relative min-h-0 flex-1 overflow-hidden"
        style={{ background: "var(--plot-bg)" }}
        aria-label={t("中区.标题")}
      >
        {/* ★ 这里原来是一整屏居中说明文字 —— 窗口 46% 的高度只放了一段话，
             是"界面很丑"最主要的原因。现在改成：
               · 一行**极简提示**（3D 在右侧，看得到就够，不需要解释一屏）
               · 其余空间留给**真实数据卡片**（模型 / 指标），让这块有信息量
             说明文字没有删掉，收进了右上角浮层与「关于」页 —— 需要看的人依然找得到。*/}
        <div className="flex h-full flex-col gap-2 p-3">
          <div
            className="面板 flex flex-none flex-wrap items-center gap-2 px-3 py-2"
            style={{ background: "var(--bg-panel)" }}
          >
            <span className="min-w-0 truncate text-[0.82em] text-dim">{t("中区.未接入")}</span>
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-2 gap-2 overflow-y-auto">
            <div className="面板 min-w-0 overflow-y-auto p-2">
              <div className="mb-1 flex items-baseline gap-1.5">
                <span style={{ fontWeight: 600 }}>{t("中区.浮层")}</span>
                <span className="flex-1" />
                {模型 ? <Tag>{模型.current_display_name || "…"}</Tag> : <Tag tone="notice">{t("通用.未接入")}</Tag>}
              </div>
              {模型 ? <ValueTable rows={模型行} /> : <div className="text-dim">{t("定义.没模型")}</div>}
              <div className="my-2" style={{ borderTop: "1px solid var(--border-light)" }} />
              <ValueTable rows={引擎行} />
            </div>

            <div className="面板 min-w-0 overflow-y-auto p-2">
              <div className="mb-1 flex items-baseline gap-1.5">
                <span style={{ fontWeight: 600 }}>{t("验证.曲线")}</span>
                <span className="flex-1" />
                <span className="text-[0.82em] text-dim 等宽">{名们.length || ""}</span>
              </div>
              {显示条.length ? (
                <ul className="space-y-1">
                  {显示条.map((名) => (
                    <li key={名} className="flex items-center gap-1.5">
                      <span className="min-w-0 flex-1 truncate text-[0.85em] 等宽" title={名}>
                        {名}
                      </span>
                      <迷你走势 点={曲线数[名] ?? []} />
                      <span className="w-[68px] flex-none text-right text-[0.85em] 等宽">
                        <NumericText value={曲线数[名]?.[曲线数[名].length - 1]?.v} digits={3} />
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="未接入 text-[0.9em]">
                  <div>{t("验证.没有指标")}</div>
                </div>
              )}
            </div>
          </div>
        </div>

      </div>

      {/* 底部一行：只留一个真字段；"未接入/3D 在右侧"上面已经说过一次，不再重复 */}
      <div
        className="flex flex-none items-center gap-2 px-2 py-1 text-[0.8em] text-dim"
        style={{ borderTop: "1px solid var(--border)", background: "var(--bg-title)" }}
      >
        <span className="等宽">{`${t("定义.自由度")}: ${模型?.dof ?? "--"}`}</span>
        <span className="flex-1" />
      </div>
    </div>
  );
}

/** 常驻全局控制：按钮发命令，状态只认后端返回的 `simulation.state`。 */
export function 仿真工具栏() {
  const t = useTranslation();
  const 状态 = 用仓库((s) => s.仿真.数据);
  const experiment = 用仓库((s) => s.experiment.数据);
  const 连接 = 用仓库((s) => s.连接);
  const 模型 = 用仓库((s) => s.模型.数据);
  const [忙, 设忙] = useState<"run" | "pause" | "reset" | null>(null);
  const [重力忙, 设重力忙] = useState(false);
  const [速度忙, 设速度忙] = useState(false);
  const [experimentBusy, setExperimentBusy] = useState(false);
  const [selectedExperiment, setSelectedExperiment] = useState("");
  const experimentOptionsSignature = (experiment?.available ?? [])
    .map((item) => item.key ?? "").join("|");

  useEffect(() => {
    const next = experiment?.current || experiment?.available?.[0]?.key || "";
    if (next) setSelectedExperiment(next);
  }, [experiment?.current, experimentOptionsSignature]);

  const 已运行 = 状态?.state === "running";
  const 已暂停 = 状态?.state === "paused";
  const 重力开 = 状态?.gravity_enabled ?? true;
  const 可发 = 连接 === "已连接" && !!模型 && !!状态;
  const experimentCompleted = !!experiment?.current && experiment?.status === "completed";
  const experimentStatusText = ({
    not_selected: t("simulation.experiment.status.not_selected"),
    loaded: t("simulation.experiment.status.loaded"),
    load_failed: t("simulation.experiment.status.load_failed"),
    running: t("simulation.experiment.status.running"),
    paused: t("simulation.experiment.status.paused"),
    completed: t("simulation.experiment.status.completed"),
    export_failed: t("simulation.experiment.status.export_failed"),
  } as Record<string, string>)[experiment?.status ?? ""]
    ?? experiment?.status
    ?? t("仿真控制.未选择实验");

  const loadExperiment = async () => {
    if (!selectedExperiment) return;
    setExperimentBusy(true);
    try {
      const 起于 = 记命令发出();
      命令收尾("command.experiment", await 命令.loadExperiment(selectedExperiment), 起于,
        { 模块: "仿真·实验" });
    } finally {
      setExperimentBusy(false);
    }
  };

  const 执行 = async (action: "run" | "pause" | "reset") => {
    设忙(action);
    try {
      const 起于 = 记命令发出();
      命令收尾("command.simulation", await 命令.controlSimulation(action), 起于,
        { 模块: `仿真·${action}` });
    } finally {
      设忙(null);
    }
  };

  const 切重力 = async () => {
    设重力忙(true);
    try {
      const 起于 = 记命令发出();
      命令收尾("command.gravity", await 命令.setGravity(!重力开), 起于,
        { 模块: "仿真·重力" });
    } finally {
      设重力忙(false);
    }
  };

  const 改速度 = async (倍率: number) => {
    设速度忙(true);
    try {
      const 起于 = 记命令发出();
      命令收尾("command.simulation", await 命令.setSimulationSpeed(倍率), 起于,
        { 模块: "仿真·速度" });
    } finally {
      设速度忙(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t("仿真控制.标题")}>
      <span className="font-semibold">{t("仿真控制.实验")}</span>
      <select
        className="控件 max-w-[190px] px-1.5 py-1 text-[0.82em]"
        value={selectedExperiment}
        disabled={experimentBusy || 已运行 || !(experiment?.available?.length)}
        title={experiment?.description || t("仿真控制.实验说明")}
        onChange={(e) => setSelectedExperiment(e.target.value)}
      >
        {!experiment?.available?.length ? <option value="">{t("仿真控制.无实验")}</option> : null}
        {(experiment?.available ?? []).map((item) => (
          <option key={item.key} value={item.key} disabled={!!item.error}>
            {item.name || item.key}
          </option>
        ))}
      </select>
      <Button
        variant="secondary"
        size="small"
        disabled={!可发 || experimentBusy || 已运行 || !selectedExperiment
          || selectedExperiment === experiment?.current}
        title={t("仿真控制.加载实验说明")}
        onPress={() => void loadExperiment()}
      >
        {experimentBusy ? "…" : t("仿真控制.加载实验")}
      </Button>
      <Tag tone={experiment?.status === "completed" ? "success"
        : experiment?.status === "running" ? "emphasis" : "neutral"}>
        {experimentStatusText}
      </Tag>
      {experiment?.current ? (
        <span className="等宽 text-[0.78em] text-dim"
          title={experiment.result_directory || experiment.description}>
          {`${(experiment.elapsed_s ?? 0).toFixed(2)}/${(experiment.duration_s ?? 0).toFixed(2)} s`}
        </span>
      ) : null}
      <span className="mx-0.5 h-4 w-px" style={{ background: "var(--border)" }} aria-hidden="true" />
      <span className="mr-0.5 font-semibold">{t("仿真控制.标题")}</span>
      <Tag tone={已运行 ? "success" : 已暂停 ? "emphasis" : "notice"}>
        {状态 ? t(已运行 ? "仿真控制.运行中" : "仿真控制.已暂停") : t("仿真控制.等待")}
      </Tag>
      <Button
        variant="primary"
        size="small"
        disabled={!可发 || !!忙 || 已运行 || experimentCompleted}
        title={experimentCompleted ? t("仿真控制.实验完成说明") : t("仿真控制.运行说明")}
        onPress={() => void 执行("run")}
      >
        {忙 === "run" ? "…" : t("仿真控制.运行")}
      </Button>
      <Button
        variant="secondary"
        size="small"
        disabled={!可发 || !!忙 || 已暂停}
        title={t("仿真控制.暂停说明")}
        onPress={() => void 执行("pause")}
      >
        {忙 === "pause" ? "…" : t("仿真控制.暂停")}
      </Button>
      <Button
        variant="secondary"
        size="small"
        disabled={!可发 || !!忙}
        title={t("仿真控制.复位说明")}
        onPress={() => void 执行("reset")}
      >
        {忙 === "reset" ? "…" : t("仿真控制.复位")}
      </Button>
      <span className="mx-0.5 h-4 w-px" style={{ background: "var(--border)" }} aria-hidden="true" />
      <Button
        variant="secondary"
        size="small"
        pressed={重力开}
        disabled={!可发 || 重力忙}
        title={t("仿真控制.重力说明")}
        onPress={() => void 切重力()}
      >
        {重力忙 ? "…" : t(重力开 ? "仿真控制.重力开" : "仿真控制.重力关")}
      </Button>
      <label className="flex items-center gap-1 text-[0.82em] text-dim">
        <span>{t("仿真控制.速度")}</span>
        <select
          className="控件 px-1.5 py-1 等宽"
          value={状态?.speed_multiplier ?? 1}
          disabled={!可发 || 速度忙}
          title={t("仿真控制.速度说明")}
          onChange={(e) => void 改速度(Number(e.target.value))}
        >
          {[0.25, 0.5, 1, 2, 4].map((倍率) => (
            <option key={倍率} value={倍率}>{`${倍率}×`}</option>
          ))}
        </select>
      </label>
      <span className="等宽 text-[0.8em] text-dim" title={状态?.description}>
        {`t=${状态?.simulation_time?.toFixed(2) ?? "--"} s`}
      </span>
    </div>
  );
}

/**
 * 迷你走势 —— 用真数据画的小折线（按窗口缩放）。
 * 少于两个点就画一个空槽，**不画一条平线**：平线会被读成"值恒定"。
 */
function 迷你走势({ 点 }: { 点: SamplePoint[] }) {
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
