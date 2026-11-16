/**
 * 路径值.tsx —— 长路径的紧凑显示 + 复制完整路径。
 *
 * 为什么单独做一个组件：
 *   模型路径经常很长（/Users/…/模型/xxx/scene.xml），直接塞进两列表格会把
 *   数值列撑爆、把同一行的 DoF/nu 挤到换行。这里默认只显示**文件名 + 上级目录**，
 *   完整路径放 title；需要完整路径时点一下复制。显示的是真的后端路径，不做截断造假。
 */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../视图/文案";

export interface PathValueProps {
  /** 后端给的绝对/相对路径；空值显示 `--` */
  path?: string;
}

function splitPath(path: string): { filename: string; parent: string } {
  const segments = path.split(/[\\/]+/).filter(Boolean);
  const filename = segments.at(-1) ?? path;
  const parent = segments.length > 1 ? segments.at(-2) ?? "" : "";
  return { filename: filename, parent: parent };
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* 降级到下面的 execCommand */
  }
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const success = document.execCommand("copy");
    document.body.removeChild(textarea);
    return success;
  } catch {
    return false;
  }
}

export function PathValue({ path: path }: PathValueProps) {
  const t = useTranslation();
  const [copyState, setCopyState] = useState<"空闲" | "成功" | "失败">("空闲");
  const resetTimer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (resetTimer.current !== null) window.clearTimeout(resetTimer.current);
    };
  }, []);

  if (!path) return <span className="text-dim">--</span>;

  const { filename: filename, parent: parent } = splitPath(path);

  const handleClick = async () => {
    const success = await copyText(path);
    setCopyState(success ? "成功" : "失败");
    if (resetTimer.current !== null) window.clearTimeout(resetTimer.current);
    resetTimer.current = window.setTimeout(() => setCopyState("空闲"), 1400);
  };

  return (
    <span className="路径值 flex min-w-0 items-center justify-end gap-1" title={path}>
      <span className="min-w-0 truncate text-right">
        <span className="路径文件名">{filename}</span>
        {parent ? <span className="text-dim"> · {parent}</span> : null}
      </span>
      <button
        type="button"
        className="复制键"
        onClick={() => void handleClick()}
        title={t("定义.复制路径")}
        aria-label={t("定义.复制路径")}
      >
        {copyState === "成功" ? t("定义.复制成功") : copyState === "失败" ? t("定义.复制失败") : t("通用.复制")}
      </button>
    </span>
  );
}
