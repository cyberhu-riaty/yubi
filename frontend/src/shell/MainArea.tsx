/**
 * MainArea.tsx —— 常驻的 3D 视口占位 + 右上角浮层。
 *
 * ★ 这一格**不随任务流切换**（`CONVENTIONS.md` §三：视图不换、只换上下文）。
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
import { Tag } from "../components/Badge";
import { Button } from "../components/Button";
import { ValueTable, NumericText, type ValueRow } from "../components/DataTable";
import { commands as commands, useStore } from "../data/store";
import { finishCommand as finishCommand, recordCommandStart as recordCommandStart } from "../data/logs";
import type { SamplePoint } from "../data/connection";
import { CONTRACT_VERSION, PROTOCOL_VERSION } from "@generated/contract";
import { useTheme } from "../generated/appearance";
import { connectionTranslationKeys, useTranslation } from "../views/i18n";

export interface MainAreaProps {
  /** 迷你走势条最多显示多少条（再多就只报总数） */
  ROW_LIMIT?: number;
}

export function MainArea({ ROW_LIMIT: ROW_LIMIT = 12 }: MainAreaProps) {
  const t = useTranslation();
  const model = useStore((s) => s.model.data);
  const connection = useStore((s) => s.connection);
  const chartCount = useStore((s) => s.charts);
  const theme = useTheme();

  const names = useMemo(() => Object.keys(chartCount).sort(), [chartCount]);
  const displayBar = names.slice(0, ROW_LIMIT);

  const modelRow: ValueRow[] = model
    ? [
        { key: t("定义.模型显示名"), value: model.current_display_name || t("通用.无") },
        { key: t("定义.自由度"), value: <span className="monospace">{model.dof ?? "--"}</span> },
        { key: t("定义.执行器数"), value: <span className="monospace">{model.actuator_count ?? "--"}</span> },
        { key: t("定义.模型状态"), value: model.status || "--" },
        {
          key: t("定义.加载耗时"),
          value: <span className="monospace">{model.duration_s === undefined ? "--" : `${model.duration_s.toFixed(3)} s`}</span>,
        },
      ]
    : [];

  const engineRow: ValueRow[] = [
    { key: t("状态栏.连接"), value: <span className="monospace">{t(connectionTranslationKeys[connection])}</span> },
    { key: t("状态栏.皮肤"), value: <span className="monospace">{theme}</span> },
    { key: t("关于.契约版本"), value: <span className="monospace">{`${CONTRACT_VERSION} / ${PROTOCOL_VERSION}`}</span> },
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
            className="panel flex flex-none flex-wrap items-center gap-2 px-3 py-2"
            style={{ background: "var(--bg-panel)" }}
          >
            <span className="min-w-0 truncate text-[0.82em] text-dim">{t("中区.未接入")}</span>
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-2 gap-2 overflow-y-auto">
            <div className="panel min-w-0 overflow-y-auto p-2">
              <div className="mb-1 flex items-baseline gap-1.5">
                <span style={{ fontWeight: 600 }}>{t("中区.浮层")}</span>
                <span className="flex-1" />
                {model ? <Tag>{model.current_display_name || "…"}</Tag> : <Tag tone="notice">{t("通用.未接入")}</Tag>}
              </div>
              {model ? <ValueTable rows={modelRow} /> : <div className="text-dim">{t("定义.没模型")}</div>}
              <div className="my-2" style={{ borderTop: "1px solid var(--border-light)" }} />
              <ValueTable rows={engineRow} />
            </div>

            <div className="panel min-w-0 overflow-y-auto p-2">
              <div className="mb-1 flex items-baseline gap-1.5">
                <span style={{ fontWeight: 600 }}>{t("验证.曲线")}</span>
                <span className="flex-1" />
                <span className="text-[0.82em] text-dim monospace">{names.length || ""}</span>
              </div>
              {displayBar.length ? (
                <ul className="space-y-1">
                  {displayBar.map((name) => (
                    <li key={name} className="flex items-center gap-1.5">
                      <span className="min-w-0 flex-1 truncate text-[0.85em] monospace" title={name}>
                        {name}
                      </span>
                      <MiniTrend point={chartCount[name] ?? []} />
                      <span className="w-[68px] flex-none text-right text-[0.85em] monospace">
                        <NumericText value={chartCount[name]?.[chartCount[name].length - 1]?.v} digits={3} />
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="unavailable text-[0.9em]">
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
        <span className="monospace">{`${t("定义.自由度")}: ${model?.dof ?? "--"}`}</span>
        <span className="flex-1" />
      </div>
    </div>
  );
}

/** 常驻全局控制：按钮发命令，状态只认后端返回的 `simulation.state`。 */
export function SimulationToolbar() {
  const t = useTranslation();
  const state = useStore((s) => s.simulation.data);
  const experiment = useStore((s) => s.experiment.data);
  const connection = useStore((s) => s.connection);
  const model = useStore((s) => s.model.data);
  const [busy, setBusy] = useState<"run" | "pause" | "reset" | null>(null);
  const [gravityBusy, setGravityBusy] = useState(false);
  const [speedBusy, setSpeedBusy] = useState(false);
  const [experimentBusy, setExperimentBusy] = useState(false);
  const [selectedExperiment, setSelectedExperiment] = useState("");
  const experimentOptionsSignature = (experiment?.available ?? [])
    .map((item) => item.key ?? "").join("|");

  useEffect(() => {
    const next = experiment?.current || experiment?.available?.[0]?.key || "";
    if (next) setSelectedExperiment(next);
  }, [experiment?.current, experimentOptionsSignature]);

  const ran = state?.state === "running";
  const paused = state?.state === "paused";
  const gravityEnabled = state?.gravity_enabled ?? true;
  const canSend = connection === "已连接" && !!model && !!state;
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
      const startedAt = recordCommandStart();
      finishCommand("command.experiment", await commands.loadExperiment(selectedExperiment), startedAt,
        { module: "仿真·实验" });
    } finally {
      setExperimentBusy(false);
    }
  };

  const execute = async (action: "run" | "pause" | "reset") => {
    setBusy(action);
    try {
      const startedAt = recordCommandStart();
      finishCommand("command.simulation", await commands.controlSimulation(action), startedAt,
        { module: `仿真·${action}` });
    } finally {
      setBusy(null);
    }
  };

  const toggleGravity = async () => {
    setGravityBusy(true);
    try {
      const startedAt = recordCommandStart();
      finishCommand("command.gravity", await commands.setGravity(!gravityEnabled), startedAt,
        { module: "仿真·重力" });
    } finally {
      setGravityBusy(false);
    }
  };

  const updateSpeed = async (multiplier: number) => {
    setSpeedBusy(true);
    try {
      const startedAt = recordCommandStart();
      finishCommand("command.simulation", await commands.setSimulationSpeed(multiplier), startedAt,
        { module: "仿真·速度" });
    } finally {
      setSpeedBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t("仿真控制.标题")}>
      <span className="font-semibold">{t("仿真控制.实验")}</span>
      <select
        className="control max-w-[190px] px-1.5 py-1 text-[0.82em]"
        value={selectedExperiment}
        disabled={experimentBusy || ran || !(experiment?.available?.length)}
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
        disabled={!canSend || experimentBusy || ran || !selectedExperiment
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
        <span className="monospace text-[0.78em] text-dim"
          title={experiment.result_directory || experiment.description}>
          {`${(experiment.elapsed_s ?? 0).toFixed(2)}/${(experiment.duration_s ?? 0).toFixed(2)} s`}
        </span>
      ) : null}
      <span className="mx-0.5 h-4 w-px" style={{ background: "var(--border)" }} aria-hidden="true" />
      <span className="mr-0.5 font-semibold">{t("仿真控制.标题")}</span>
      <Tag tone={ran ? "success" : paused ? "emphasis" : "notice"}>
        {state ? t(ran ? "仿真控制.运行中" : "仿真控制.已暂停") : t("仿真控制.等待")}
      </Tag>
      <Button
        variant="primary"
        size="small"
        disabled={!canSend || !!busy || ran || experimentCompleted}
        title={experimentCompleted ? t("仿真控制.实验完成说明") : t("仿真控制.运行说明")}
        onPress={() => void execute("run")}
      >
        {busy === "run" ? "…" : t("仿真控制.运行")}
      </Button>
      <Button
        variant="secondary"
        size="small"
        disabled={!canSend || !!busy || paused}
        title={t("仿真控制.暂停说明")}
        onPress={() => void execute("pause")}
      >
        {busy === "pause" ? "…" : t("仿真控制.暂停")}
      </Button>
      <Button
        variant="secondary"
        size="small"
        disabled={!canSend || !!busy}
        title={t("仿真控制.复位说明")}
        onPress={() => void execute("reset")}
      >
        {busy === "reset" ? "…" : t("仿真控制.复位")}
      </Button>
      <span className="mx-0.5 h-4 w-px" style={{ background: "var(--border)" }} aria-hidden="true" />
      <Button
        variant="secondary"
        size="small"
        pressed={gravityEnabled}
        disabled={!canSend || gravityBusy}
        title={t("仿真控制.重力说明")}
        onPress={() => void toggleGravity()}
      >
        {gravityBusy ? "…" : t(gravityEnabled ? "仿真控制.重力开" : "仿真控制.重力关")}
      </Button>
      <label className="flex items-center gap-1 text-[0.82em] text-dim">
        <span>{t("仿真控制.速度")}</span>
        <select
          className="control px-1.5 py-1 monospace"
          value={state?.speed_multiplier ?? 1}
          disabled={!canSend || speedBusy}
          title={t("仿真控制.速度说明")}
          onChange={(e) => void updateSpeed(Number(e.target.value))}
        >
          {[0.25, 0.5, 1, 2, 4].map((multiplier) => (
            <option key={multiplier} value={multiplier}>{`${multiplier}×`}</option>
          ))}
        </select>
      </label>
      <span className="monospace text-[0.8em] text-dim" title={state?.description}>
        {`t=${state?.simulation_time?.toFixed(2) ?? "--"} s`}
      </span>
    </div>
  );
}

/**
 * 迷你走势 —— 用真数据画的小折线（按窗口缩放）。
 * 少于两个点就画一个空槽，**不画一条平线**：平线会被读成"值恒定"。
 */
function MiniTrend({ point: point }: { point: SamplePoint[] }) {
  const width = 46;
  const height = 14;
  if (point.length < 2) {
    return (
      <svg width={width} height={height} aria-hidden="true" className="flex-none">
        <rect x="0.5" y="0.5" width={width - 1} height={height - 1} fill="none" stroke="var(--border)" />
      </svg>
    );
  }
  let maximum = -Infinity;
  let minimum = Infinity;
  for (const p of point) {
    if (p.v > maximum) maximum = p.v;
    if (p.v < minimum) minimum = p.v;
  }
  const increment = maximum - minimum || 1;
  const path = point
    .map((p, i) => {
      const x = (i / (point.length - 1)) * width;
      const y = height - ((p.v - minimum) / increment) * height;
      return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} aria-hidden="true" className="flex-none">
      <path d={path} fill="none" stroke="var(--palette-1)" strokeWidth="1" />
    </svg>
  );
}
