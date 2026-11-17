/**
 * StatusBar.tsx —— 底部一条，只放**运行现场最常扫的几项**：
 *
 *   物理运行状态 · 仿真时间 · 实时倍率 RTF · 指标帧率 · 连接状态
 *
 * 不放行号/编码/缩进/Prettier 这类"仿编辑器"的装饰。每一个数字都必须能追到
 * 一个真字段：
 *
 *   物理     ← `simulation.state.state`；这里只读显示，控制按钮常驻在 3D 区上方
 *   仿真时间 ← `simulation.state.simulation_time`（仿真侧 data.time），**不是**连接后的墙钟
 *   实时倍率 ← `系统.RTF` = 仿真时间增量 ÷ 墙钟增量
 *   指标帧率 ← `指标` 主题最近一秒**实测**收到的帧数（没有就是 0，不编）
 *   连接     ← WebSocket 连接状态
 *
 * 项目名/模型名/语言不在这里：它们分别属于「定义」「外观」，塞进同一条状态栏
 * 只会把它撑成两行（实测 576px 宽时旧版就换行了）。语言开关放在「外观」页。
 */
import { useStore } from "../data/store";
import { connectionTranslationKeys, useTranslation, formatNumber, formatDuration } from "../views/i18n";

export function StatusBar() {
  const t = useTranslation();
  const connection = useStore((s) => s.connection);
  const simulation = useStore((s) => s.simulation.data);
  const system = useStore((s) => s.system.data);
  const metricRate = useStore((s) => s.topicRates["指标"] ?? 0);

  const running = simulation?.state === "running";
  const simulationSeconds = simulation?.simulation_time ?? system?.仿真时间;
  const RTF = system?.RTF;
  // 冻结时 RTF 天然是 0，不算"跑不动"；只有推进中且明显掉速才提示。
  const rtfWarning = running && RTF !== undefined && RTF < 0.95;
  const connectionColor =
    connection === "已连接" ? "var(--ok)" : connection === "连接中" ? "var(--warn)" : "var(--danger)";

  return (
    <footer
      className="status-bar flex flex-none items-center gap-x-2.5 gap-y-0 px-2.5 text-[0.82em]"
      aria-label={t("状态栏.标题")}
    >
      <span className="status-item" title={t("状态栏.提示.物理")}>
        <span className="status-label">{t("状态栏.物理")}</span>
        <span className="monospace">
          {simulation ? t(running ? "状态栏.物理.开" : "状态栏.物理.关") : t("状态栏.物理.未知")}
        </span>
      </span>

      <Cell
        label={t("状态栏.仿真时间")}
        hint={t("状态栏.提示.仿真时间")}
        value={simulationSeconds === undefined ? "--" : formatDuration(simulationSeconds)}
        width="13ch"
      />
      <Cell
        label={t("状态栏.实时率")}
        hint={t("状态栏.提示.实时率")}
        value={RTF === undefined ? "--" : `${formatNumber(RTF, 2)}×`}
        width="9ch"
        warning={rtfWarning}
      />
      <Cell
        label={t("状态栏.帧率")}
        hint={t("状态栏.提示.帧率")}
        value={`${metricRate} Hz`}
        width="9ch"
      />

      <span className="flex-1" />

      <span className="status-item" role="status" title={t("状态栏.提示.连接")}>
        <span className="status-label">{t("状态栏.连接")}</span>
        <span className="status-dot" aria-hidden="true" style={{ background: connectionColor }} />
        <span className="monospace">{t(connectionTranslationKeys[connection])}</span>
      </span>
    </footer>
  );
}

/** 一格：标签 + 值（值等宽；悬停给出这个字段的**真实来源**） */
function Cell({
  label: label,
  value: value,
  hint: hint,
  width: width,
  warning: warning = false,
}: {
  label: string;
  value: string;
  hint: string;
  width?: string;
  warning?: boolean;
}) {
  return (
    <span className="status-item min-w-0" title={hint}>
      <span className="status-label flex-none">{label}</span>
      {warning ? (
        <span
          className="status-dot"
          style={{ background: "var(--warn)" }}
          aria-hidden="true"
        />
      ) : null}
      <span className="monospace truncate" style={{ maxWidth: width ?? "14ch" }}>
        {value}
      </span>
    </span>
  );
}
