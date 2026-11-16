/**
 * 监控视图.tsx —— 任务流「监控」：跑得动跑不动，看这一格。
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
import { CollapsibleSection } from "../组件/可折叠区块";
import { Tag } from "../组件/标签";
import { ValueTable, NumericText, type ValueRow } from "../组件/数值表";
import { 用仓库 } from "../数据/仓库";
import { useTranslation } from "./文案";

export function 监控视图() {
  const t = useTranslation();
  const 系统 = 用仓库((s) => s.系统.数据);
  const 仿真 = 用仓库((s) => s.仿真.数据);
  const 连接 = 用仓库((s) => s.连接);
  const 告警 = 用仓库((s) => s.告警.数据);
  const 活动告警 = 告警?.活动 ?? [];
  const 严重数 = 活动告警.filter((a) => a.严重度 === "严重").length;
  const 已冻结 = 仿真?.state === "paused";
  const 跑得动 = 系统?.RTF !== undefined && 系统.RTF >= 0.95;

  /** 冻结时 RTF=0 不是告警；只有推进中掉速才告警 */
  const RTF语气 = !系统 ? "notice" as const : 已冻结 ? "neutral" as const : 跑得动 ? "success" as const : "warning" as const;

  const 行: ValueRow[] = 系统
    ? [
        {
          key: t("监控.实时率"),
          value: (
            <span className="等宽">
              <NumericText value={系统.RTF} digits={2} />
              <span className="ml-1 text-dim">×</span>
            </span>
          ),
        },
        {
          key: t("监控.步频"),
          value: <span className="等宽">{系统.步频 === undefined ? "--" : `${系统.步频.toFixed(0)} Hz`}</span>,
        },
        { key: t("监控.步长"), value: <span className="等宽">{系统.仿真步长?.toFixed(4) ?? "--"} s</span> },
        {
          key: t("监控.内存"),
          value: <span className="等宽">{系统.内存MB === undefined ? "--" : `${系统.内存MB.toFixed(0)} MB`}</span>,
        },
        { key: t("监控.仿真时间"), value: <span className="等宽">{系统.仿真时间?.toFixed(2) ?? "--"} s</span> },
        { key: t("监控.墙钟"), value: <span className="等宽">{系统.墙钟?.toFixed(1) ?? "--"} s</span> },
        { key: t("监控.插件数"), value: <span className="等宽">{系统.插件数 ?? "--"}</span> },
      ]
    : [];

  return (
    <div className="space-y-2">
      {/* 病态告警：放在最前面 —— 它是"结论"，比后面的数更有用 */}
      {活动告警.length ? (
        <CollapsibleSection
          title={t("监控.告警")}
          badge={
            <Tag tone={严重数 ? "notice" : "emphasis"}>
              {t("监控.告警.计数", { 活动: 活动告警.length, 严重: 严重数 })}
            </Tag>
          }
        >
          <p className="text-dim">{t("监控.告警.说明")}</p>
          <ul className="mt-2 space-y-1.5">
            {活动告警.map((a, i) => (
              <li
                key={`${a.类型}-${a.信号}-${i}`}
                className="面板 p-2"
                style={{
                  borderLeft: `3px solid ${a.严重度 === "严重" ? "var(--danger)" : "var(--warn)"}`,
                }}
              >
                <div className="flex flex-wrap items-baseline gap-1.5">
                  <Tag tone={a.严重度 === "严重" ? "notice" : "emphasis"}>{a.类型}</Tag>
                  <span className="min-w-0 flex-1 break-words text-[0.85em] 等宽" title={a.信号}>
                    {String(a.信号 ?? "")}
                  </span>
                  <span className="flex-none text-[0.78em] text-dim 等宽">
                    {`${(a.开始秒 ?? 0).toFixed(1)}–${(a.结束秒 ?? 0).toFixed(1)}s`}
                  </span>
                </div>
                <div className="mt-1 text-[0.82em]">{a.证据}</div>
                {a.曲线?.length ? (
                  <>
                    <告警走势 曲线={a.曲线} />
                    <div className="text-[0.74em] text-dim">
                      {`${t("监控.告警.走势")} ${(a.曲线t?.[a.曲线t.length - 1] ?? 0).toFixed(1)} s`}
                    </div>
                  </>
                ) : null}
                <div className="mt-1 text-[0.8em] text-dim">{a.建议}</div>
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
          系统 ? (
            <Tag tone={RTF语气}>{已冻结 ? "已冻结" : `RTF ${系统.RTF?.toFixed(2) ?? "--"}`}</Tag>
          ) : (
            <Tag tone="notice">{t("监控.等待")}</Tag>
          )
        }
      >
        {已冻结 ? (
          <p className="mt-1 text-[0.85em]" style={{ color: "var(--warn)" }}>{t("监控.冻结")}</p>
        ) : null}
        {系统 ? (
          <div className="mt-2">
            <ValueTable rows={行} />
          </div>
        ) : (
          <div className="mt-2 text-dim">
            {连接 === "已连接" ? t("监控.没数据") : t("连接.已断开")}
          </div>
        )}
        {系统?.出错 ? (
          <div className="mt-2" style={{ color: "var(--warn)" }}>
            {系统.出错}
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
function 告警走势({ 曲线 }: { 曲线: number[] }) {
  const 宽 = 100;
  const 高 = 22;
  const 大 = Math.max(...曲线, 1e-9);
  const 小 = Math.min(...曲线, -1e-9);
  const 幅 = 大 - 小 || 1;
  const 路 = 曲线
    .map((v, i) => {
      const x = (i / Math.max(曲线.length - 1, 1)) * 宽;
      const y = 高 - ((v - 小) / 幅) * 高;
      return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${宽} ${高}`} className="mt-1 w-full" style={{ height: 34 }} aria-hidden="true">
      <path d={路} fill="none" stroke="var(--warn)" strokeWidth="1" />
    </svg>
  );
}
