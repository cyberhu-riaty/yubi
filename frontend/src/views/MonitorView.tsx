/**
 * MonitorView.tsx —— 任务流「监控」：跑得动跑不动，看这一格。
 *
 * 诚实边界（先写清楚，免得以后有人往这里塞假数据）：
 *   · RTF / 步频 / 内存 **只有仿真侧能量到**，所以全部来自后端「系统」主题。
 *     界面**不自己估**：拿不到就写"还没收到"，绝不按帧间隔反推一个看起来合理的数。
 *   · 「3D 渲染帧率」**没有做**：那是窗口层的事（3D 视口自己的统计），
 *     仿真侧看不到，所以它不在「系统」消息里。我一开始画了这一格，
 *     结果只能填一个固定的 `--` —— 那正是"看起来像监控、其实是摆设"，
 *     所以整格删掉了。要做它，得先把视口统计算进契约（另开一步）。
 *   · 连接断开时明确写"连接已断开"，而不是让数字停在最后一个值上装作还在跑。
 */
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Tag } from "../components/Badge";
import { ValueTable, NumericText, type ValueRow } from "../components/DataTable";
import { useStore } from "../data/store";
import { useTranslation } from "./i18n";

export function MonitorView() {
  const t = useTranslation();
  const system = useStore((s) => s.system.data);
  const simulation = useStore((s) => s.simulation.data);
  const connection = useStore((s) => s.connection);
  const alerts = useStore((s) => s.alerts.data);
  const activeAlerts = alerts?.active ?? [];
  const errorCount = activeAlerts.filter((a) => a.severity === "严重").length;
  const frozen = simulation?.state === "paused";
  const canRun = system?.RTF !== undefined && system.RTF >= 0.95;

  /** 冻结时 RTF=0 不是告警；只有推进中掉速才告警 */
  const rtfTone = !system ? "notice" as const : frozen ? "neutral" as const : canRun ? "success" as const : "warning" as const;

  const row: ValueRow[] = system
    ? [
        {
          key: t("监控.实时率"),
          value: (
            <span className="monospace">
              <NumericText value={system.RTF} digits={2} />
              <span className="ml-1 text-dim">×</span>
            </span>
          ),
        },
        {
          key: t("监控.步频"),
          value: <span className="monospace">{system.step_rate === undefined ? "--" : `${system.step_rate.toFixed(0)} Hz`}</span>,
        },
        { key: t("监控.步长"), value: <span className="monospace">{system.timestep?.toFixed(4) ?? "--"} s</span> },
        {
          key: t("监控.内存"),
          value: <span className="monospace">{system.memory_mb === undefined ? "--" : `${system.memory_mb.toFixed(0)} MB`}</span>,
        },
        { key: t("监控.仿真时间"), value: <span className="monospace">{system.simulation_time?.toFixed(2) ?? "--"} s</span> },
        { key: t("监控.墙钟"), value: <span className="monospace">{system.wall_clock?.toFixed(1) ?? "--"} s</span> },
        { key: t("监控.插件数"), value: <span className="monospace">{system.plugin_count ?? "--"}</span> },
      ]
    : [];

  return (
    <div className="space-y-2">
      {/* 病态告警：放在最前面 —— 它是"结论"，比后面的数更有用 */}
      {activeAlerts.length ? (
        <CollapsibleSection
          title={t("监控.告警")}
          badge={
            <Tag tone={errorCount ? "notice" : "emphasis"}>
              {t("监控.告警.计数", { active: activeAlerts.length, severe: errorCount })}
            </Tag>
          }
        >
          <p className="text-dim">{t("监控.告警.说明")}</p>
          <ul className="mt-2 space-y-1.5">
            {activeAlerts.map((a, i) => (
              <li
                key={`${a.kind}-${a.signal}-${i}`}
                className="panel p-2"
                style={{
                  borderLeft: `3px solid ${a.severity === "严重" ? "var(--danger)" : "var(--warn)"}`,
                }}
              >
                <div className="flex flex-wrap items-baseline gap-1.5">
                  <Tag tone={a.severity === "严重" ? "notice" : "emphasis"}>{a.kind}</Tag>
                  <span className="min-w-0 flex-1 break-words text-[0.85em] monospace" title={a.signal}>
                    {String(a.signal ?? "")}
                  </span>
                  <span className="flex-none text-[0.78em] text-dim monospace">
                    {`${(a.start_seconds ?? 0).toFixed(1)}–${(a.end_seconds ?? 0).toFixed(1)}s`}
                  </span>
                </div>
                <div className="mt-1 text-[0.82em]">{a.evidence}</div>
                {a.curve?.length ? (
                  <>
                    <AlertTrend charts={a.curve} />
                    <div className="text-[0.74em] text-dim">
                      {`${t("监控.告警.走势")} ${(a.curve_times?.[a.curve_times.length - 1] ?? 0).toFixed(1)} s`}
                    </div>
                  </>
                ) : null}
                <div className="mt-1 text-[0.8em] text-dim">{a.recommendation}</div>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[0.78em]" style={{ color: "var(--warn)" }}>
            {t("监控.告警.经验")}
          </p>
        </CollapsibleSection>
      ) : null}

      <CollapsibleSection
        title={t("步骤.监控")}
        badge={
          system ? (
            <Tag tone={rtfTone}>{frozen ? "已冻结" : `RTF ${system.RTF?.toFixed(2) ?? "--"}`}</Tag>
          ) : (
            <Tag tone="notice">{t("监控.等待")}</Tag>
          )
        }
      >
        {frozen ? (
          <p className="mt-1 text-[0.85em]" style={{ color: "var(--warn)" }}>{t("监控.冻结")}</p>
        ) : null}
        {system ? (
          <div className="mt-2">
            <ValueTable rows={row} />
          </div>
        ) : (
          <div className="mt-2 text-dim">
            {connection === "connected" ? t("监控.没数据") : t("连接.已断开")}
          </div>
        )}
        {system?.errors ? (
          <div className="mt-2" style={{ color: "var(--warn)" }}>
            {system.errors}
          </div>
        ) : null}
      </CollapsibleSection>
    </div>
  );
}

/**
 * 告警走势 —— 把该时段的抽样曲线画出来。
 *
 * ★ 为什么要在告警里画图，而不是只给一句话：
 *   "5.0 Hz、振幅 22°" 对熟手够用，对新手不如一眼看到"这条曲线在来回抖"。
 *   数据来自后端随告警一起发来的抽样点（12 个），不是前端自己编的形状。
 */
function AlertTrend({ charts: charts }: { charts: number[] }) {
  const width = 100;
  const height = 22;
  const maximum = Math.max(...charts, 1e-9);
  const minimum = Math.min(...charts, -1e-9);
  const increment = maximum - minimum || 1;
  const route = charts
    .map((v, i) => {
      const x = (i / Math.max(charts.length - 1, 1)) * width;
      const y = height - ((v - minimum) / increment) * height;
      return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="mt-1 w-full" style={{ height: 34 }} aria-hidden="true">
      <path d={route} fill="none" stroke="var(--warn)" strokeWidth="1" />
    </svg>
  );
}
