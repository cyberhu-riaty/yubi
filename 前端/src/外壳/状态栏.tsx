/**
 * 状态栏.tsx —— 底部一条，只放**运行现场最常扫的几项**：
 *
 *   物理运行状态 · 仿真时间 · 实时倍率 RTF · 指标帧率 · 连接状态
 *
 * 不放行号/编码/缩进/Prettier 这类"仿编辑器"的装饰。每一个数字都必须能追到
 * 一个真字段：
 *
 *   物理     ← `仿真状态.状态`；这里只读显示，控制按钮常驻在 3D 区上方
 *   仿真时间 ← `仿真状态.仿真时间`（仿真侧 data.time），**不是**连接后的墙钟
 *   实时倍率 ← `系统.RTF` = 仿真时间增量 ÷ 墙钟增量
 *   指标帧率 ← `指标` 主题最近一秒**实测**收到的帧数（没有就是 0，不编）
 *   连接     ← WebSocket 连接状态
 *
 * 项目名/模型名/语言不在这里：它们分别属于「定义」「外观」，塞进同一条状态栏
 * 只会把它撑成两行（实测 576px 宽时旧版就换行了）。语言开关放在「外观」页。
 */
import { 用仓库 } from "../数据/仓库";
import { 连接键, use取, 数, 时长 } from "../视图/文案";

export function 状态栏() {
  const t = use取();
  const 连接 = 用仓库((s) => s.连接);
  const 仿真 = 用仓库((s) => s.仿真.数据);
  const 系统 = 用仓库((s) => s.系统.数据);
  const 指标速率 = 用仓库((s) => s.主题速率["指标"] ?? 0);

  const 运行中 = 仿真?.状态 === "运行";
  const 仿真秒 = 仿真?.仿真时间 ?? 系统?.仿真时间;
  const RTF = 系统?.RTF;
  // 冻结时 RTF 天然是 0，不算"跑不动"；只有推进中且明显掉速才提示。
  const RTF警示 = 运行中 && RTF !== undefined && RTF < 0.95;
  const 连接色 =
    连接 === "已连接" ? "var(--ok)" : 连接 === "连接中" ? "var(--warn)" : "var(--danger)";

  return (
    <footer
      className="状态栏 flex flex-none items-center gap-x-2.5 gap-y-0 px-2.5 text-[0.82em]"
      aria-label={t("状态栏.标题")}
    >
      <span className="状态栏项" title={t("状态栏.提示.物理")}>
        <span className="状态栏标签">{t("状态栏.物理")}</span>
        <span className="等宽">
          {仿真 ? t(运行中 ? "状态栏.物理.开" : "状态栏.物理.关") : t("状态栏.物理.未知")}
        </span>
      </span>

      <格
        标签={t("状态栏.仿真时间")}
        提示={t("状态栏.提示.仿真时间")}
        值={仿真秒 === undefined ? "--" : 时长(仿真秒)}
        宽="13ch"
      />
      <格
        标签={t("状态栏.实时率")}
        提示={t("状态栏.提示.实时率")}
        值={RTF === undefined ? "--" : `${数(RTF, 2)}×`}
        宽="9ch"
        警示={RTF警示}
      />
      <格
        标签={t("状态栏.帧率")}
        提示={t("状态栏.提示.帧率")}
        值={`${指标速率} Hz`}
        宽="9ch"
      />

      <span className="flex-1" />

      <span className="状态栏项" role="status" title={t("状态栏.提示.连接")}>
        <span className="状态栏标签">{t("状态栏.连接")}</span>
        <span className="状态点" aria-hidden="true" style={{ background: 连接色 }} />
        <span className="等宽">{t(连接键[连接])}</span>
      </span>
    </footer>
  );
}

/** 一格：标签 + 值（值等宽；悬停给出这个字段的**真实来源**） */
function 格({
  标签,
  值,
  提示,
  宽,
  警示 = false,
}: {
  标签: string;
  值: string;
  提示: string;
  宽?: string;
  警示?: boolean;
}) {
  return (
    <span className="状态栏项 min-w-0" title={提示}>
      <span className="状态栏标签 flex-none">{标签}</span>
      {警示 ? (
        <span
          className="状态点"
          style={{ background: "var(--warn)" }}
          aria-hidden="true"
        />
      ) : null}
      <span className="等宽 truncate" style={{ maxWidth: 宽 ?? "14ch" }}>
        {值}
      </span>
    </span>
  );
}
