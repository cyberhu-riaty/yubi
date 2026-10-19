/**
 * 插件视图.tsx —— 「插件」：本机算法库里有什么，各自什么版本，被谁用到。
 *
 * ★ **先说清楚这一格不是什么**（这是全项目最容易变成骗人的一格）：
 *   它**不是插件市场**。没有远端仓库、没有下载、没有签名校验、没有版本服务器。
 *   所以这里不画搜索框、不画"安装"按钮、不画价格/评分 ——
 *   一个点了会转圈但什么也装不上的市场，比没有市场更糟：用户会以为装上了。
 *
 * 它真做的事：
 *   · 列出 `算法库/` 下的插件，元信息（版本/说明/作者）来自**真文件**（后端 AST 读取）
 *   · 标出"当前项目是否启用"，点一下就在当前项目里启用/停用（走 `命令.应用算法`，有回执）
 *   · 标出"被哪些项目用到"（反查 项目/*.json）
 *
 * 想做真正的市场，至少得先有：远端清单 + 校验和 + 安装到本地 + 版本冲突处理。
 * 那是另一件事，界面上已如实写明"未实现"。
 */
import { useState } from "react";
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { 按钮 } from "../组件/按钮";
import { 命令, 用仓库 } from "../数据/仓库";
import { 命令收尾, 记命令发出 } from "../数据/日志";
import { use取 } from "./文案";

export function 插件视图() {
  const t = use取();
  const 目录 = 用仓库((s) => s.插件.数据);
  const 项目 = 用仓库((s) => s.项目.数据);
  const [忙, 设忙] = useState(false);
  const 不兼容报告 = (项目?.报告 ?? []).filter((行) => 行.includes("不兼容"));

  const 项们 = 目录?.插件 ?? [];
  // ★ 启用序必须用**模块名**（`关节pd控制`），不能用界面上的显示名
  //   （`关节 PD 位置控制`）—— 后端装配认的是模块名，传显示名会"装不上且不报错"。
  //   顺序取「已完成装配的那份清单」：目录里标了 当前启用 的，按目录顺序。
  const 启用序 = 项们.filter((x) => x.当前启用 && x.插件).map((x) => x.插件 as string);

  const 切换 = async (插件名: string, 已启用: boolean) => {
    设忙(true);
    try {
      const 目标 = 已启用
        ? 启用序.filter((n) => n !== 插件名)
        : [...启用序, 插件名];            // 新加的排最后（= 最后写 ctrl，最容易看到效果）
      const 起于 = 记命令发出();
      命令收尾("命令.应用算法", await 命令.应用算法(目标), 起于, {
        模块: "插件",
        插件: 插件名,
      });
    } finally {
      设忙(false);
    }
  };

  return (
    <div className="space-y-2">
      <可折叠区块
        标题={t("步骤.插件")}
        徽标={项们.length ? <标签>{项们.length}</标签> : <标签 语气="警示">{t("通用.待接入")}</标签>}
      >
        <p className="text-dim">{t("插件.说明")}</p>
        <p className="mt-1 text-[0.85em]" style={{ color: "var(--warn)" }}>
          {t("插件.没有远端")}
        </p>
        <p className="mt-1 text-[0.8em] text-dim">{t("插件.兼容性未判定")}</p>

        {项们.length ? (
          <ul className="mt-2 space-y-1">
            {项们.map((x) => {
              const 名 = x.插件 ?? "";
              const 显示名 = x.名称 || 名;
              const 已启用 = !!x.当前启用;
              const 不兼容 = 不兼容报告.some((行) => 行.includes(显示名) || (名 && 行.includes(名)));
              return (
                <li key={名} className="面板 p-2">
                  <div className="flex items-baseline gap-1.5">
                    <span className="min-w-0 flex-1 truncate" style={{ fontWeight: 600 }} title={x.文件 ? `${t("插件.文件")}: ${x.文件}` : undefined}>
                      {显示名}
                    </span>
                    <span className="flex-none text-[0.8em] text-dim 等宽">
                      {x.版本 ? `v${x.版本}` : t("插件.未标注")}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <标签>{t("插件.状态.已安装")}</标签>
                    <标签 语气={已启用 ? "成功" : "中性"}>{已启用 ? t("插件.状态.当前项目已启用") : t("插件.状态.当前项目未启用")}</标签>
                    {不兼容 ? <标签 语气="错误">! {t("定义.算法状态.不兼容")}</标签> : null}
                  </div>
                  <div className="mt-1 text-[0.85em] text-dim">
                    {x.说明 || t("插件.无说明")}
                  </div>
                  {x.被项目使用?.length ? (
                    <div className="mt-1 text-[0.8em] text-dim">
                      {`${t("插件.被使用")}: ${x.被项目使用.join(" / ")}`}
                    </div>
                  ) : (
                    <div className="mt-1 text-[0.8em] text-dim">{t("插件.未被任何项目使用")}</div>
                  )}
                  {不兼容 ? (
                    <div className="mt-1 text-[0.8em]" style={{ color: "var(--danger)" }}>{t("插件.不兼容说明")}</div>
                  ) : null}
                  <div className="mt-1 flex items-center gap-2">
                    <按钮
                      种类={已启用 ? "次" : "主"}
                      尺寸="小"
                      disabled={忙 || (不兼容 && !已启用)}
                      title={不兼容 && !已启用 ? t("插件.不兼容说明") : undefined}
                      on按下={() => void 切换(名, 已启用)}
                    >
                      {已启用 ? t("插件.停用") : t("插件.启用")}
                    </按钮>
                    {x.作者 ? <span className="text-[0.8em] text-dim">{`${t("插件.作者")}: ${x.作者}`}</span> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="mt-2 text-dim">{目录?.说明 || t("插件.空")}</div>
        )}
      </可折叠区块>
    </div>
  );
}
