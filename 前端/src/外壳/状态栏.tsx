/**
 * 状态栏.tsx —— 底部一条，**只放约定里那六项**：
 *
 *   项目 · 模型 · 物理开关 · 仿真时间 · 曲线帧率 · 连接状态
 *
 * 不放行号/编码/缩进/Prettier 这类"仿编辑器"的装饰 —— 参考项目那条假状态栏
 * 就是这么来的（`约定.md` §三 点名过）。所以这里每一个数字都必须能追到一个真字段：
 *
 *   项目     ← `项目状态.项目`
 *   模型     ← `模型状态.当前显示名`
 *   物理     ← `项目状态.重力开`；点它是**发真命令**（`命令.重力`）并等回执
 *   仿真时间 ← 连接建立后经过的墙钟时间。⚠️ 仿真侧自己的仿真时间**不在契约里**，
 *              所以悬停提示里写明这一条，不把它装成 sim time
 *   曲线帧率 ← `指标` 主题最近一秒**实测**收到的帧数（没有就是 0，不编）
 *   连接     ← WebSocket 连接状态
 *
 * 最右边是语言切换（"右上角"的语言开关在这个单窗口布局里落到状态栏右侧，
 * 不为它多开一条顶栏 —— 那条顶栏只会是装饰）。
 */
import { 命令, 用仓库 } from "../数据/仓库";
import { 命令收尾, 记命令发出, 用连接起始 } from "../数据/日志";
import { 用节拍 } from "../数据/时钟";
import { 按钮 } from "../组件/按钮";
import { 另一种语言, 语言名, 取语言, 设语言, 连接键, use取, 时长 } from "../视图/文案";

export function 状态栏() {
  const t = use取();
  const 节拍 = 用节拍();
  const 连接 = 用仓库((s) => s.连接);
  const 项目 = 用仓库((s) => s.项目.数据);
  const 模型 = 用仓库((s) => s.模型.数据);
  const 指标速率 = 用仓库((s) => s.主题速率["指标"] ?? 0);
  const 连接起始 = 用连接起始();
  const 语 = 取语言();

  // "仿真时间" = 连接建立之后经过的墙钟秒数；没连过就是 undefined → 显示 "--"
  const 仿真秒 = 连接起始 ? (节拍 - 连接起始) / 1000 : undefined;
  const 物理 = 项目?.重力开;

  const 切物理 = async () => {
    if (typeof 物理 !== "boolean") return;
    const 主题 = "命令.重力";
    const 起于 = 记命令发出();
    命令收尾(主题, await 命令.开物理(!物理), 起于);
  };

  return (
    <footer
      className="flex flex-none flex-wrap items-center gap-x-3 gap-y-0.5 px-2 py-0.5 text-[0.9em]"
      style={{ background: "var(--bg-title)", borderTop: "1px solid var(--border)" }}
      aria-label={t("状态栏.连接")}
    >
      <格 标签={t("状态栏.项目")} 提示={t("状态栏.提示.项目")} 值={项目?.项目 || "--"} />
      <格
        标签={t("状态栏.模型")}
        提示={t("状态栏.提示.模型")}
        值={模型?.当前显示名 || 模型?.当前路径 || "--"}
      />

      <span className="flex items-center gap-1" title={t("状态栏.提示.物理")}>
        <span className="flex-none text-dim">{t("状态栏.物理")}</span>
        <button
          type="button"
          role="switch"
          aria-checked={typeof 物理 === "boolean" ? 物理 : "mixed"}
          disabled={typeof 物理 !== "boolean"}
          onClick={() => void 切物理()}
          className="控件 等宽"
          style={{ padding: "0 6px" }}
        >
          {typeof 物理 === "boolean"
            ? 物理
              ? t("状态栏.物理.开")
              : t("状态栏.物理.关")
            : t("状态栏.物理.未知")}
        </button>
      </span>

      <格
        标签={t("状态栏.仿真时间")}
        提示={t("状态栏.提示.仿真时间")}
        值={仿真秒 === undefined ? "--" : 时长(仿真秒)}
      />
      <格 标签={t("状态栏.曲线帧率")} 提示={t("状态栏.提示.曲线帧率")} 值={`${指标速率} Hz`} />
      <格 标签={t("状态栏.连接")} 提示={t("状态栏.提示.连接")} 值={t(连接键[连接])} />

      <span className="flex-1" />

      <按钮
        尺寸="小"
        种类="幽灵"
        on按下={() => 设语言(另一种语言[语])}
        title={t("状态栏.切到", { 语: 语言名[另一种语言[语]] })}
      >
        {t("状态栏.语言")}: {语言名[语]}
      </按钮>
    </footer>
  );
}

/** 一格：标签 + 值（值等宽；悬停给出这个字段的**真实来源**） */
function 格({ 标签, 值, 提示 }: { 标签: string; 值: string; 提示: string }) {
  return (
    <span className="flex min-w-0 items-center gap-1" title={提示}>
      <span className="flex-none text-dim">{标签}</span>
      <span className="等宽 truncate" style={{ maxWidth: "22ch" }}>
        {值}
      </span>
    </span>
  );
}
