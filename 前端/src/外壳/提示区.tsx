/**
 * 提示区.tsx —— 右下角的 toast 容器。
 *
 * 只有命令失败这类事会出现在这里（成功不弹：那是噪音）。
 * 每条都能用键盘关掉（真 `<button>`），并且带 `role="status"`，
 * 读屏能念出来。容器本身 `pointer-events: none`，不挡住下面的界面。
 */
import { dismissToast, useToasts } from "../数据/toasts";
import { useTranslation } from "../视图/文案";

export function 提示区() {
  const t = useTranslation();
  const 快照 = useToasts();

  if (!快照.items.length) return null;

  return (
    <div
      className="pointer-events-none fixed bottom-3 right-3 z-50 flex w-[320px] max-w-[calc(100%-1.5rem)] flex-col gap-1.5"
      role="status"
      aria-live="polite"
      aria-label={t("控制台.标题")}
    >
      {快照.items.map((条) => (
        <div
          key={条.id}
          className="面板 pointer-events-auto flex items-start gap-2 p-2"
          style={{
            background: "var(--bg-popup)",
            borderColor: 条.kind === "错误" ? "var(--border-strong)" : "var(--border)",
            boxShadow: "0 4px 14px var(--shadow)",
          }}
        >
          <span aria-hidden="true" className="等宽" style={{ color: "var(--fg-dim)" }}>
            {条.kind === "错误" ? "✕" : 条.kind === "注意" ? "!" : "·"}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block break-all">{条.text}</span>
            {条.details ? <span className="block break-all text-[0.85em] text-dim">{条.details}</span> : null}
          </span>
          <button
            type="button"
            className="控件 flex-none px-1 py-0 text-[0.85em]"
            onClick={() => dismissToast(条.id)}
            aria-label={t("通用.关闭")}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
