/**
 * 部署视图.tsx —— 任务流第 5 步：导出部署包。
 *
 * ★ 这一格最容易造假，所以边界写在最前面：
 *
 *   **没有真机连接。** 契约里没有设备抽象、没有传输层、没有时间戳/序号/错误码、
 *   没有安全状态机。所以这里**没有**"连接"按钮、没有绿灯、没有遥测曲线、
 *   没有"健康检查 ok" —— 在没有任何传输层的情况下，那些只能是真的假的。
 *   （`目标功能规格.md` 的"假实现识别清单"：Deploy 页面没有"未接入"状态，必是假；
 *     因为真部署一定有"没连上"这个状态，而假实现永远显示"已连接"。）
 *
 *   **做的是导出。** 把当前项目打成可带走的包：项目配置 + 算法**源码** +
 *   模型清单（含 sha256）。这一步是能做实的，而且能验证（后端真写了文件）。
 *   包里**不含模型本体**（单个资产解包可达 30 MB+），只给校验和。
 */
import { useState } from "react";
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { 按钮 } from "../组件/按钮";
import { 命令, 用仓库 } from "../数据/仓库";
import { 命令收尾, 记命令发出 } from "../数据/日志";
import { use取 } from "./文案";

export function 部署视图() {
  const t = use取();
  const 状态 = 用仓库((s) => s.部署.数据);
  const 项目 = 用仓库((s) => s.项目.数据);
  const [忙, 设忙] = useState(false);

  const 导出中 = 状态?.状态 === "导出中";
  const 成功 = 状态?.状态 === "✓ 完成";
  const 失败 = 状态?.状态 === "✗ 失败";

  const 导出 = async () => {
    设忙(true);
    try {
      const 起于 = 记命令发出();
      命令收尾("命令.部署", await 命令.导出部署包(), 起于);
    } finally {
      设忙(false);
    }
  };

  return (
    <div className="space-y-2">
      <可折叠区块
        标题={t("步骤.部署")}
        徽标={
          成功 ? <标签 语气="强调">{`${状态?.文件数 ?? 0} 文件`}</标签>
          : 失败 ? <标签 语气="警示">{t("部署.失败")}</标签>
          : 导出中 ? <标签 语气="强调">{t("部署.导出中")}</标签>
          : <标签>{t("部署.未导出")}</标签>
        }
      >
        {/* 第一屏就说清楚"没有真机连接" */}
        <p className="text-dim">{t("部署.说明")}</p>
        <p className="mt-1 text-[0.85em]" style={{ color: "var(--warning)" }}>
          {t("部署.没有连接")}
        </p>

        <div className="mt-2 flex items-center gap-2">
          <按钮 种类="主" disabled={忙 || 导出中} on按下={() => void 导出()}>
            {导出中 ? t("部署.导出中") : t("部署.导出")}
          </按钮>
          <span className="text-[0.85em] text-dim">
            {`${t("部署.项目")}: ${项目?.项目 || t("通用.无")}`}
          </span>
        </div>

        {状态?.出错 ? (
          <div className="mt-2 text-[0.85em]" style={{ color: "var(--warning)" }}>
            {状态.出错}
          </div>
        ) : null}

        {成功 && 状态?.清单?.length ? (
          <div className="mt-2">
            <div className="text-[0.85em] text-dim">{t("部署.目录")}</div>
            <div className="等宽 break-all text-[0.85em]">{状态.目录}</div>
            <ul className="mt-1 space-y-0.5">
              {状态.清单.map((x) => (
                <li key={x.文件} className="flex items-baseline gap-1.5 text-[0.85em]">
                  <span className="min-w-0 flex-1 truncate 等宽">{x.文件}</span>
                  <span className="flex-none text-dim">{x.说明}</span>
                  <span className="w-[62px] flex-none text-right text-dim 等宽">
                    {x.字节 === undefined ? "--" : `${(x.字节 / 1024).toFixed(1)} KB`}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </可折叠区块>
    </div>
  );
}
