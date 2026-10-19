/**
 * 路径值.tsx —— 长路径的紧凑显示 + 复制完整路径。
 *
 * 为什么单独做一个组件：
 *   模型路径经常很长（/Users/…/模型/xxx/scene.xml），直接塞进两列表格会把
 *   数值列撑爆、把同一行的 DoF/nu 挤到换行。这里默认只显示**文件名 + 上级目录**，
 *   完整路径放 title；需要完整路径时点一下复制。显示的是真的后端路径，不做截断造假。
 */
import { useEffect, useRef, useState } from "react";
import { use取 } from "../视图/文案";

export interface 路径值参数 {
  /** 后端给的绝对/相对路径；空值显示 `--` */
  路径?: string;
}

function 拆路径(路径: string): { 文件: string; 上级: string } {
  const 段 = 路径.split(/[\\/]+/).filter(Boolean);
  const 文件 = 段.at(-1) ?? 路径;
  const 上级 = 段.length > 1 ? 段.at(-2) ?? "" : "";
  return { 文件, 上级 };
}

async function 复制(文本: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(文本);
      return true;
    }
  } catch {
    /* 降级到下面的 execCommand */
  }
  try {
    const 区 = document.createElement("textarea");
    区.value = 文本;
    区.setAttribute("readonly", "");
    区.style.position = "fixed";
    区.style.opacity = "0";
    document.body.appendChild(区);
    区.select();
    const 成 = document.execCommand("copy");
    document.body.removeChild(区);
    return 成;
  } catch {
    return false;
  }
}

export function 路径值({ 路径 }: 路径值参数) {
  const t = use取();
  const [状态, 设状态] = useState<"空闲" | "成功" | "失败">("空闲");
  const 定时 = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (定时.current !== null) window.clearTimeout(定时.current);
    };
  }, []);

  if (!路径) return <span className="text-dim">--</span>;

  const { 文件, 上级 } = 拆路径(路径);

  const 点击 = async () => {
    const 成 = await 复制(路径);
    设状态(成 ? "成功" : "失败");
    if (定时.current !== null) window.clearTimeout(定时.current);
    定时.current = window.setTimeout(() => 设状态("空闲"), 1400);
  };

  return (
    <span className="路径值 flex min-w-0 items-center justify-end gap-1" title={路径}>
      <span className="min-w-0 truncate text-right">
        <span className="路径文件名">{文件}</span>
        {上级 ? <span className="text-dim"> · {上级}</span> : null}
      </span>
      <button
        type="button"
        className="复制键"
        onClick={() => void 点击()}
        title={t("定义.复制路径")}
        aria-label={t("定义.复制路径")}
      >
        {状态 === "成功" ? t("定义.复制成功") : 状态 === "失败" ? t("定义.复制失败") : t("通用.复制")}
      </button>
    </span>
  );
}
