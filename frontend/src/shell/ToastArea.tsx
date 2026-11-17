/**
 * ToastArea.tsx —— 右下角的 toast 容器。
 *
 * 只有命令失败这类事会出现在这里（成功不弹：那是噪音）。
 * 每条都能用键盘关掉（真 `<button>`），并且带 `role="status"`，
 * 读屏能念出来。容器本身 `pointer-events: none`，不挡住下面的界面。
 */
import { dismissToast, useToasts } from "../data/toasts";
import { useTranslation } from "../views/i18n";

export function ToastArea() {
  const t = useTranslation();
  const snapshot = useToasts();

  if (!snapshot.items.length) return null;

  return (
    <div
      className="pointer-events-none fixed bottom-3 right-3 z-50 flex w-[320px] max-w-[calc(100%-1.5rem)] flex-col gap-1.5"
      role="status"
      aria-live="polite"
      aria-label={t("控制台.标题")}
    >
      {snapshot.items.map((item) => (
        <div
          key={item.id}
          className="panel pointer-events-auto flex items-start gap-2 p-2"
          style={{
            background: "var(--bg-popup)",
            borderColor: item.kind === "错误" ? "var(--border-strong)" : "var(--border)",
            boxShadow: "0 4px 14px var(--shadow)",
          }}
        >
          <span aria-hidden="true" className="monospace" style={{ color: "var(--fg-dim)" }}>
            {item.kind === "错误" ? "✕" : item.kind === "注意" ? "!" : "·"}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block break-all">{item.text}</span>
            {item.details ? <span className="block break-all text-[0.85em] text-dim">{item.details}</span> : null}
          </span>
          <button
            type="button"
            className="control flex-none px-1 py-0 text-[0.85em]"
            onClick={() => dismissToast(item.id)}
            aria-label={t("通用.关闭")}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
