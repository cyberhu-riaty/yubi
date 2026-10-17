/**
 * 提示区.tsx —— 右下角的 toast 容器。
 *
 * 只有命令失败这类事会出现在这里（成功不弹：那是噪音）。
 * 每条都能用键盘关掉（真 `<button>`），并且带 `role="status"`，
 * 读屏能念出来。容器本身 `pointer-events: none`，不挡住下面的界面。
 */
import { 移除, 用提示 } from "../数据/提示";
import { use取 } from "../视图/文案";

export function 提示区() {
  const t = use取();
  const 快照 = 用提示();

  if (!快照.条.length) return null;

  return (
    <div
      className="pointer-events-none fixed bottom-3 right-3 z-50 flex w-[320px] max-w-[calc(100%-1.5rem)] flex-col gap-1.5"
      role="status"
      aria-live="polite"
      aria-label={t("控制台.标题")}
    >
      {快照.条.map((条) => (
        <div
          key={条.序号}
          className="面板 pointer-events-auto flex items-start gap-2 p-2"
          style={{
            background: "var(--bg-popup)",
            borderColor: 条.种类 === "错误" ? "var(--border-strong)" : "var(--border)",
            boxShadow: "0 4px 14px var(--shadow)",
          }}
        >
          <span aria-hidden="true" className="等宽" style={{ color: "var(--fg-dim)" }}>
            {条.种类 === "错误" ? "✕" : 条.种类 === "注意" ? "!" : "·"}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block break-all">{条.文本}</span>
            {条.细节 ? <span className="block break-all text-[0.85em] text-dim">{条.细节}</span> : null}
          </span>
          <button
            type="button"
            className="控件 flex-none px-1 py-0 text-[0.85em]"
            onClick={() => 移除(条.序号)}
            aria-label={t("通用.关闭")}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
