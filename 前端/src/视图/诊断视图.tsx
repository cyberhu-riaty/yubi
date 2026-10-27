/**
 * 诊断视图.tsx —— 「诊断」：把终端里那批断言搬进界面。
 *
 * 诚实边界：
 *   · 这里显示的每一项，都是**真的跑了一遍** `工具/验证/*.py` 的结果
 *     （后端用子进程调用，跟你在终端里敲的是同一批脚本）。
 *   · 没有"历史全绿"缓存：每次点都重跑。缓存住的绿灯会在你真改坏东西时骗你。
 *   · 跑不动/超时就报失败，不写"未知"糊过去。
 */
import { useState } from "react";
import { 可折叠区块 } from "../组件/可折叠区块";
import { 用节拍 } from "../数据/时钟";
import { 标签 } from "../组件/标签";
import { 按钮 } from "../组件/按钮";
import { 命令, 用仓库 } from "../数据/仓库";
import { 命令收尾, 记命令发出 } from "../数据/日志";
import { use取 } from "./文案";

export function 诊断视图() {
  const t = use取();
  const 报告 = 用仓库((s) => s.诊断.数据);
  const 连接 = 用仓库((s) => s.连接);
  const 节拍 = 用节拍();
  const [忙, 设忙] = useState(false);
  const [开始时刻, 设开始时刻] = useState<number | null>(null);
  const 已用时 = 报告?.运行中 && 开始时刻 ? Math.max(0, Math.round((节拍 - 开始时刻) / 1000)) : undefined;

  const 都通过 = !!报告 && !报告.运行中 && (报告.通过 ?? 0) === (报告.总数 ?? 0) && (报告.总数 ?? 0) > 0;

  const 跑一遍 = async () => {
    设忙(true);
    设开始时刻(Date.now());
    try {
      const 起于 = 记命令发出();
      命令收尾("命令.诊断", await 命令.跑诊断(), 起于, { 模块: "诊断" });
    } finally {
      设忙(false);
    }
  };

  const 导出报告 = () => {
    if (!报告) return;
    const 体 = JSON.stringify(报告, null, 2);
    const 地址 = URL.createObjectURL(new Blob([体], { type: "application/json;charset=utf-8" }));
    const 链 = document.createElement("a");
    链.href = 地址;
    链.download = `驭臂诊断-${String(报告.时间 || "report").replace(/[^0-9A-Za-z_-]+/g, "-")}.json`;
    document.body.appendChild(链);
    链.click();
    document.body.removeChild(链);
    window.setTimeout(() => URL.revokeObjectURL(地址), 1000);
  };

  return (
    <div className="space-y-2">
      <可折叠区块
        标题={t("步骤.诊断")}
        徽标={
          报告?.运行中 ? (
            <标签 语气="强调">{t("诊断.运行中")}</标签>
          ) : 报告 ? (
            <标签 语气={都通过 ? "成功" : "错误"}>{`${报告.通过 ?? 0}/${报告.总数 ?? 0}`}</标签>
          ) : (
            <标签>{t("诊断.未运行")}</标签>
          )
        }
      >
        <div className="flex items-center gap-2">
          <按钮 种类="主" title={t("诊断.说明")} on按下={() => void 跑一遍()} disabled={忙 || !!报告?.运行中 || 连接 !== "已连接"}>
            {报告?.运行中 ? t("诊断.运行中") : t("诊断.开始")}
          </按钮>
          {报告?.运行中 && 已用时 !== undefined ? (
            <span className="text-[0.85em] text-dim 等宽">{t("诊断.已用时", { 秒: 已用时 })}</span>
          ) : 报告 && !报告.运行中 ? (
            <>
              <span className="text-[0.85em] text-dim 等宽">
                {`${报告.时间 ?? ""} · ${报告.耗时秒 ?? "--"}s`}
              </span>
              <按钮 尺寸="小" 种类="幽灵" on按下={导出报告}>
                {t("诊断.导出")}
              </按钮>
            </>
          ) : null}
        </div>

        {报告?.项?.length ? (
          <ul className="mt-2 space-y-0.5">
            {报告.项.map((x) => (
              <li key={x.名} className="flex items-baseline gap-1.5 text-[0.85em]">
                <span style={{ flex: "none", color: x.通过 ? "var(--ok)" : "var(--danger)" }}>
                  {x.通过 ? "✓" : "✗"}
                </span>
                <span className="w-[76px] flex-none">{x.名}</span>
                <span className="min-w-0 flex-1 truncate text-dim 等宽" title={x.说明}>
                  {x.说明}
                </span>
                <span className="w-[46px] flex-none text-right text-dim 等宽">
                  {x.秒 === undefined ? "" : `${x.秒.toFixed(2)}s`}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-2 text-dim">{报告?.运行中 ? t("诊断.运行中") : t("诊断.没跑过")}</div>
        )}

        <details className="装配详情 mt-2">
          <summary>{t("诊断.高级")}</summary>
          <p className="mt-1 text-[0.8em] text-dim">{t("诊断.高级说明")}</p>
        </details>
      </可折叠区块>
    </div>
  );
}
