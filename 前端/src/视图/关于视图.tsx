/**
 * 关于视图.tsx —— 版本、运行环境、声明。
 *
 * 这一格全部是**可核对的事实**：
 *   · 契约版本 / 协议版本 / 主题清单 → 来自生成的 `@生成/契约`（不是抄的）
 *   · 握手内容 → 后端在连接建立时真的发过来的（`s.握手`）
 *   · 最新帧序号 → 真的收到了多少帧（`s.项目.帧号` 等）
 * 一条没核对过的话都不写进去。声明那三条是许可与从属关系，必须原文照写。
 */
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { 数值表, type 数值行 } from "../组件/数值表";
import { 契约版本, 协议版本, 下行元, 上行元 } from "@生成/契约";
import { 用仓库 } from "../数据/仓库";
import { 连接键, use取 } from "./文案";

export function 关于视图() {
  const t = use取();
  const 握手 = 用仓库((s) => s.握手);
  const 帧号 = 用仓库((s) => s.项目.帧号);
  const 模型帧号 = 用仓库((s) => s.模型.帧号);

  const 事实: 数值行[] = [
    { 键: t("关于.名称"), 值: `${t("应用.名称")} · ${t("应用.副标题")}` },
    {
      键: t("关于.版本"),
      值: (
        <span className="等宽">
          {契约版本} / {协议版本}
        </span>
      ),
    },
    {
      键: t("关于.主题数"),
      值: (
        <span className="等宽">
          {下行元.length} ↓ / {上行元.length} ↑
        </span>
      ),
    },
    {
      键: t("关于.帧号"),
      值: (
        <span className="等宽">
          {模型帧号 || 帧号 ? `#${Math.max(模型帧号, 帧号)}` : t("关于.帧号.无")}
        </span>
      ),
      弱: !模型帧号 && !帧号,
    },
    { 键: t("状态栏.连接"), 值: <连接文本 /> },
  ];

  return (
    <div>
      <可折叠区块 标题={t("关于.标题")}>
        <数值表 行={事实} />
      </可折叠区块>

      <可折叠区块 标题={t("关于.握手")} 徽标={握手 ? <标签 语气="强调">ok</标签> : <标签 语气="警示">--</标签>}>
        {握手 ? (
          <p className="text-dim">
            {t("关于.握手.有", {
              可用: 握手.可用主题?.length ?? 0,
              间隔: 握手.广播间隔,
              版本: 握手.契约?.版本 ?? "--",
            })}
          </p>
        ) : (
          <p className="text-dim">{t("关于.握手.无")}</p>
        )}
      </可折叠区块>

      <可折叠区块 标题={t("关于.下行")} 徽标={<span className="等宽">{下行元.length}</span>} 默认开={false}>
        <ul className="space-y-1">
          {下行元.map((m) => (
            <li key={m.名}>
              <div className="flex items-center gap-1.5">
                <span className="break-all">{m.名}</span>
                <标签>{m.种类}</标签>
                <span className="等宽 text-dim">{m.类名}</span>
              </div>
              <div className="text-[0.85em] text-dim">{m.摘要}</div>
            </li>
          ))}
        </ul>
      </可折叠区块>

      <可折叠区块 标题={t("关于.上行")} 徽标={<span className="等宽">{上行元.length}</span>} 默认开={false}>
        <ul className="space-y-1">
          {上行元.map((m) => (
            <li key={m.名}>
              <div className="flex items-center gap-1.5">
                <span className="break-all">{m.名}</span>
                <标签>{m.种类}</标签>
                <span className="等宽 text-dim">{m.类名}</span>
              </div>
              <div className="text-[0.85em] text-dim">{m.摘要}</div>
            </li>
          ))}
        </ul>
      </可折叠区块>

      <可折叠区块 标题={t("关于.声明")}>
        <ul className="space-y-1 text-dim">
          <li>{t("关于.声明一")}</li>
          <li>{t("关于.声明二")}</li>
          <li>{t("关于.声明三")}</li>
        </ul>
      </可折叠区块>
    </div>
  );
}

/** 连接状态文本（从仓库订阅） */
function 连接文本() {
  const t = use取();
  const 连接 = 用仓库((s) => s.连接);
  return <span className="等宽">{t(连接键[连接])}</span>;
}
