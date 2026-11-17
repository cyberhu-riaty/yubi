/**
 * PlanningView.tsx —— 「规划」：关节航点 → 时间参数化轨迹。
 *
 * 这一格显示的全是**真数字**，来自后端 `规划桥` 对内核输出的回算：
 *   · 终端速度（必须是 0 —— 不是事后置零，是后向扫描天然收住的）
 *   · 三项余量（1 − max(实际/限位)）：负数 = 超限，后端会直接判失败
 *   · 瓶颈（哪个关节、什么类型、在 s 的哪里）
 *   · 限位来源：**显式**还是**估算** —— 估算时必须让用户看见，否则"规划通过"没有意义
 *
 * ★ 关于 jerk：本版**只校验不整形**。收紧 jerk 限会让它判失败而不是变慢，
 *   界面上这句话必须写出来，不能让用户以为它做了 S 曲线。
 */
import { useState } from "react";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Tag } from "../components/Badge";
import { Button } from "../components/Button";
import { ValueTable, type ValueRow } from "../components/DataTable";
import { useRef } from "react";
import { commands, useStore } from "../data/store";
import { parseWaypointText, type WaypointParseResult } from "../data/waypoint_file";
import { finishCommand, recordCommandStart } from "../data/logs";
import { useTranslation } from "./i18n";

export function PlanningView() {
  const t = useTranslation();
  const planning = useStore((s) => s.planning.data);
  const model = useStore((s) => s.model.data);
  const connection = useStore((s) => s.connection);
  const [busy, setBusy] = useState(false);
  const [importData, setImportData] = useState<WaypointParseResult | null>(null);
  // 约束：空 = 用后端按模型推算的默认值（界面上写明是"估算"）。
  //   ★ 给用户的是关节空间的量（rad/s、rad/s²），不是 s 空间的 ——
  //     s 空间的数与实际快慢差一个路径长度，用户从界面上的数推不出会发生什么。
  const [cartesianText, setCartesianText] = useState(
    // 给一行示例，让用户知道格式（空着的话没人知道要填什么）
    "0.30  0.00  0.55\n0.30  0.00  0.65\n0.38 -0.05  0.70",
  );
  const [velocityLimit, setVelocityLimit] = useState("");
  const [accelerationLimit, setAccelerationLimit] = useState("");
  const fileInput = useRef<HTMLInputElement | null>(null);
  const canSend = connection === "connected";

  /** 选文件 → 解析 → 直接把航点送去规划（不落盘、不占权限面） */
  const readFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      const text = await file.text();
      const result = parseWaypointText(text, planning?.dof || model?.dof);
      setImportData(result);
      if (!result.error) {
        const startedAt = recordCommandStart();
        finishCommand("command.planning",
          await commands.planTrajectory(result.waypoints.map((joint) => ({ q: joint }))), startedAt);
      }
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  /** 把输入框里的单一数值铺成"每个关节一个"的上限；空/非法 → undefined（用默认） */
  const numbers = (text: string) => {
    const value = Number(text);
    const dof = planning?.dof || model?.dof || 0;
    return text.trim() && Number.isFinite(value) && value > 0 && dof > 0
      ? Array.from({ length: dof }, () => value)
      : undefined;
  };

  /** 解析「每行 x y z」的笛卡尔航点文本 —— 报错带行号，不静默丢 */
  const parseCartesianText = (text: string): { points: number[][]; problems: string } => {
    const points: number[][] = [];
    const rows = text.split("\n");
    for (let i = 0; i < rows.length; i += 1) {
      const raw = rows[i].trim();
      if (!raw || raw.startsWith("#")) continue;
      const section = raw.split(/[,;\t ]+/).filter(Boolean).map(Number);
      if (section.length !== 3 || section.some((x) => !Number.isFinite(x))) {
        return { points: points, problems: `第 ${i + 1} 行不是 3 个数字（x y z）` };
      }
      points.push(section);
    }
    if (points.length < 2) return { points: points, problems: `只解析出 ${points.length} 个点，至少 2 个` };
    return { points: points, problems: "" };
  };

  const runCartesian = async () => {
    const { points: points, problems: problems } = parseCartesianText(cartesianText);
    if (problems) {
      setImportData({ waypoints: [], rowCount: 0, columnCount: 0, skipped: 0, error: problems });
      return;
    }
    setImportData(null);
    setBusy(true);
    try {
      const startedAt = recordCommandStart();
      finishCommand(
        "command.planning",
        await commands.planCartesian(
          points.map((xyz) => ({ xyz })),
          {
            velocity_limits: numbers(velocityLimit),
            acceleration_limits: numbers(accelerationLimit),
          },
        ),
        startedAt,
      );
    } finally {
      setBusy(false);
    }
  };

  const run = async (action: "记录航点" | "清空航点" | "规划") => {
    setBusy(true);
    try {
      const startedAt = recordCommandStart();
      const r =
        action === "记录航点" ? await commands.recordWaypoint()
        : action === "清空航点" ? await commands.clearWaypoints()
        : await commands.planTrajectory(undefined, {
            velocity_limits: numbers(velocityLimit),
            acceleration_limits: numbers(accelerationLimit),
          });
      finishCommand("command.planning", r, startedAt, { module: "规划" });
    } finally {
      setBusy(false);
    }
  };

  const succeeded = planning?.status === "completed";
  const executing = planning?.execution_status === "running";
  const planningBusy = planning?.status === "planning";
  const waypointCount = planning?.waypoint_count ?? 0;

  /** 执行/停止轨迹：走同一条命令通道，因此也有回执 */
  const execute = async (start: boolean) => {
    setBusy(true);
    try {
      const startedAt = recordCommandStart();
      finishCommand("command.planning",
        start ? await commands.executeTrajectory() : await commands.stopTrajectory(), startedAt, {
        module: "规划",
      });
    } finally {
      setBusy(false);
    }
  };
  const failed = planning?.status === "failed";

  const highlightBottleneck = async () => {
    const joint = planning?.bottleneck_joint;
    if (joint === undefined || joint < 0) return;
    const startedAt = recordCommandStart();
    finishCommand("命令.高亮", await commands.highlightJoint(joint, 8), startedAt, { module: "规划", joint: joint });
  };

   /** 余量 → 标签语气：负数（超限）就是警示 */
  const marginTone = (v?: number) => (v === undefined ? "neutral" : v < 0 ? "notice" : v < 0.05 ? "emphasis" : "neutral");

  const row: ValueRow[] = planning
    ? [
        { key: t("规划.航点数"), value: <span className="monospace">{planning.waypoint_count ?? "--"}</span> },
        { key: t("规划.自由度"), value: <span className="monospace">{planning.dof ?? "--"}</span> },
        { key: t("规划.总时长"), value: <span className="monospace">{planning.duration_s === undefined ? "--" : `${planning.duration_s.toFixed(3)} s`}</span> },
        { key: t("规划.路径长度"), value: <span className="monospace">{planning.path_length === undefined ? "--" : `${planning.path_length.toFixed(3)} rad`}</span> },
        { key: t("规划.终端速度"), value: <span className="monospace">{(planning.terminal_velocity ?? 0).toExponential(1)}</span> },
        { key: t("规划.最大速度"), value: <span className="monospace">{(planning.max_joint_velocity ?? 0).toFixed(3)}</span> },
        { key: t("规划.最大加速度"), value: <span className="monospace">{(planning.max_joint_acceleration ?? 0).toFixed(2)}</span> },
        { key: t("规划.最大加加速度"), value: <span className="monospace">{(planning.max_joint_jerk ?? 0).toFixed(2)}</span> },
        {
          key: t("规划.瓶颈"),
          value: (
            <span className="monospace">
              {planning.bottleneck_type ? `${planning.bottleneck_type} @ J${planning.bottleneck_joint} (s=${(planning.bottleneck_position ?? 0).toFixed(2)})` : "--"}
            </span>
          ),
        },
        {
          key: t("规划.实际比下界"),
          value: <span className="monospace">{(planning.actual_to_lower_bound ?? 0).toFixed(2)}<span className="ml-1 text-dim">×</span></span>,
        },
      ]
    : [];

  return (
    <div className="space-y-2">
      <CollapsibleSection
        title={t("步骤.规划")}
        badge={
          succeeded ? <Tag tone="success">{`${planning?.duration_s?.toFixed(2) ?? "?"}s`}</Tag>
          : failed ? <Tag tone="error">{t("规划.失败")}</Tag>
          : planningBusy ? <Tag tone="emphasis">{t("规划.规划中")}</Tag>
          : waypointCount > 0 ? <Tag>{t("规划.航点计数", { count: waypointCount })}</Tag>
          : <Tag>{t("规划.尚无航点")}</Tag>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="small" disabled={busy || !canSend} title={t("规划.需要航点")} onPress={() => void run("记录航点")}>
            {t("规划.记录")}
          </Button>
          <label className="flex items-center gap-1 text-[0.8em]">
            <span className="text-dim">{t("规划.速度上限")}</span>
            <input
              className="parameter-input w-[62px]"
              value={velocityLimit}
              onChange={(e) => setVelocityLimit(e.target.value)}
              placeholder={t("规划.自动")}
              inputMode="decimal"
            />
          </label>
          <label className="flex items-center gap-1 text-[0.8em]">
            <span className="text-dim">{t("规划.加速度上限")}</span>
            <input
              className="parameter-input w-[62px]"
              value={accelerationLimit}
              onChange={(e) => setAccelerationLimit(e.target.value)}
              placeholder={t("规划.自动")}
              inputMode="decimal"
            />
          </label>
          <Button
            variant="primary"
            size="small"
            disabled={busy || !canSend || planningBusy || waypointCount < 2}
            title={waypointCount < 2 ? t("规划.需要航点") : undefined}
            onPress={() => void run("规划")}
          >
            {planningBusy ? t("规划.规划中") : t("规划.规划")}
          </Button>
          <Button variant="secondary" size="small" disabled={busy || !canSend || waypointCount === 0} onPress={() => void run("清空航点")}>
            {t("规划.清空")}
          </Button>
          {succeeded ? (
            executing ? (
              <Button variant="secondary" size="small" disabled={busy || !canSend} onPress={() => void execute(false)}>
                {t("规划.停止")}
              </Button>
            ) : (
              <Button variant="secondary" size="small" disabled={busy || !canSend} onPress={() => void execute(true)}>
                {t("规划.执行")}
              </Button>
            )
          ) : null}
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.txt,text/csv,text/plain"
            className="hidden"
            onChange={(e) => void readFile(e.target.files?.[0])}
          />
          <Button variant="secondary" size="small" disabled={busy} title={t("规划.文件说明")} onPress={() => fileInput.current?.click()}>
            {t("规划.导入")}
          </Button>
          {planning?.waypoint_count ? (
            <span className="text-[0.85em] text-dim">{`${t("规划.已记录")}: ${planning.waypoint_count}`}</span>
          ) : null}
        </div>

        {!succeeded && waypointCount < 2 ? (
          <p className="mt-1.5 text-[0.82em] text-dim">{t("规划.需要航点")}</p>
        ) : null}

        <details className="mt-2">
          <summary className="cursor-pointer text-[0.85em] text-dim">{t("规划.笛卡尔")}</summary>
          <p className="mt-1 text-[0.8em] text-dim">{t("规划.笛卡尔.说明")}</p>
          <textarea
            className="parameter-input mt-1 w-full font-mono"
            rows={3}
            value={cartesianText}
            onChange={(e) => setCartesianText(e.target.value)}
            spellCheck={false}
            aria-label={t("规划.笛卡尔")}
          />
          <div className="mt-1">
            <Button variant="secondary" size="small" disabled={busy} onPress={() => void runCartesian()}>
              {t("规划.笛卡尔.算")}
            </Button>
          </div>
        </details>

        {planning?.inverse_kinematics ? (
          <div className="mt-2 text-[0.82em]">
            <span className="text-dim">{t("规划.逆解")}：</span>
            <span className="monospace">{planning.inverse_kinematics}</span>
          </div>
        ) : null}

        {importData ? (
          <div
            className="mt-2 text-[0.82em]"
            style={{ color: importData.error ? "var(--danger)" : "var(--fg-dim)" }}
          >
            {importData.error
              ? `${t("规划.导入失败")}：${importData.error}`
              : `${t("规划.导入成功")}：${importData.rowCount} 个航点 × ${importData.columnCount} 列（跳过 ${importData.skipped} 行注释/表头）`}
          </div>
        ) : null}

        {failed && planning?.reason ? (
          <div className="mt-2 text-[0.85em]" style={{ color: "var(--warn)" }}>
            {planning.reason}
          </div>
        ) : null}

        {planning?.bottleneck_joint !== undefined && planning.bottleneck_joint >= 0 ? (
          <div className="mt-1">
            <Button variant="ghost" size="small" onPress={() => void highlightBottleneck()}>
              {t("规划.高亮瓶颈", { joint: planning.bottleneck_joint })}
            </Button>
          </div>
        ) : null}

        {succeeded ? (
          <>
            <div className="mt-2">
              <ValueTable rows={row} />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[0.82em]">
              <span className="text-dim">{t("规划.余量")}</span>
              <Tag tone={marginTone(planning.velocity_margin)}>{`速度 ${((planning.velocity_margin ?? 0) * 100).toFixed(0)}%`}</Tag>
              <Tag tone={marginTone(planning.acceleration_margin)}>{`加速度 ${((planning.acceleration_margin ?? 0) * 100).toFixed(0)}%`}</Tag>
              <Tag tone={marginTone(planning.jerk_margin)}>{`加加速度 ${((planning.jerk_margin ?? 0) * 100).toFixed(0)}%`}</Tag>
            </div>
            {planning.comparison ? (
              <div className="mt-2">
                <div className="flex items-baseline gap-1.5">
                  <span style={{ fontWeight: 600 }}>{t("规划.对比")}</span>
                  <span className="flex-1" />
                  <Tag tone={(planning.comparison.duration_change_percent ?? 0) > 0 ? "notice" : "emphasis"}>
                    {`${(planning.comparison.duration_change_percent ?? 0) >= 0 ? "+" : ""}${(planning.comparison.duration_change_percent ?? 0).toFixed(0)}%`}
                  </Tag>
                </div>
                <div className="text-[0.82em] text-dim">
                  {`${(planning.comparison.previous_duration ?? 0).toFixed(2)} s → ${(planning.comparison.current_duration ?? 0).toFixed(2)} s`}
                </div>
                {planning.comparison.previous_speed_axis?.length && planning.comparison.current_speed_axis?.length ? (
                  <ComparisonChart previous={planning.comparison.previous_speed_axis} currentRun={planning.comparison.current_speed_axis} />
                ) : null}
                <div className="text-[0.78em] text-dim">{t("规划.对比.说明")}</div>
              </div>
            ) : null}

            {planning.output_path ? (
              <div className="mt-1 text-[0.82em]">
                <span className="text-dim">{t("规划.存盘")}：</span>
                <span className="monospace break-all">{planning.output_path}</span>
              </div>
            ) : null}
            {executing ? (
              <div className="mt-1 flex items-center gap-2 text-[0.82em]">
                <span className="text-dim">{t("规划.执行进度")}</span>
                <span className="monospace">{`${((planning.execution_progress ?? 0) * 100).toFixed(0)}%`}</span>
              </div>
            ) : null}
            {planning.limit_source ? (
              <div className="mt-1 text-[0.82em]" style={{ color: "var(--warn)" }}>
                {`${t("规划.限位来源")}: ${planning.limit_source}`}
              </div>
            ) : null}
          </>
        ) : null}

        {planning?.envelope?.length ? (
          <div className="mt-2">
            <div className="text-[0.85em] text-dim">{t("规划.包络")}</div>
            <EnvelopeChart envelope={planning.envelope} sd={planning.speed_axis ?? []} />
          </div>
        ) : null}
      </CollapsibleSection>
    </div>
  );
}

/**
 * 包络图 —— 手写 SVG（项目里没有图表库，也不打算为一张图引一个）。
 * 灰线 = 速度上界 `v_s_max(s)`；蓝线 = 实际 `sd(s)`。
 * 两条线之间的空隙就是"没用满的部分"，比看数字直观。
 */
function EnvelopeChart({ envelope: envelope, sd }: { envelope: number[]; sd: number[] }) {
  const width = 100;
  const height = 42;
  const all = [...envelope, ...sd].filter((x) => Number.isFinite(x) && x > 0);
  if (!all.length) return null;
  const top = Math.max(...all) || 1;
  const fold = (group: number[]) =>
    group
      .map((v, i) => {
        const x = (i / Math.max(group.length - 1, 1)) * width;
        const y = height - (Math.max(0, Math.min(v, top)) / top) * height;
        return `${i ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="mt-1 w-full" style={{ height: 90 }} aria-hidden="true">
      <path d={fold(envelope)} fill="none" stroke="var(--border)" strokeWidth="0.6" />
      {sd.length ? <path d={fold(sd)} fill="none" stroke="var(--palette-1)" strokeWidth="0.9" /> : null}
    </svg>
  );
}

/**
 * 对比图 —— 灰线 = 上一次的 sd(s)，蓝线 = 本次。
 *
 * 横轴是路径参数 s（不是时间），所以两条线可以直接叠：
 * **同一批航点**下几何路径是一样的，差别只在"走多快"。
 * 这也是为什么只有航点一致时才出对比 —— 路径不同的话叠在一起没有意义。
 */
function ComparisonChart({ previous: previous, currentRun: currentRun }: { previous: number[]; currentRun: number[] }) {
  const width = 100;
  const height = 30;
  const top = Math.max(...previous, ...currentRun, 1e-9);
  const fold = (group: number[]) =>
    group
      .map((v, i) => {
        const x = (i / Math.max(group.length - 1, 1)) * width;
        const y = height - (Math.max(0, v) / top) * height;
        return `${i ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="mt-1 w-full" style={{ height: 56 }} aria-hidden="true">
      <path d={fold(previous)} fill="none" stroke="var(--border-strong)" strokeWidth="0.9" />
      <path d={fold(currentRun)} fill="none" stroke="var(--accent)" strokeWidth="1" />
    </svg>
  );
}
