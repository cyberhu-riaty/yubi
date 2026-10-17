/**
 * 部署视图.tsx —— 任务流第 5 步：真机部署。
 *
 * 这一格**必须**先是"未接入"状态，这是验收项而不是风格选择：
 *   规格的"假实现识别清单"写着 ——「Deploy 页面没有"未接入"状态 → 必是假」，
 *   因为真部署一定有"没连上"这个状态，而假实现永远显示"已连接"。
 *
 * 事实是：契约里没有设备抽象、没有传输层、没有时间戳/序号/错误码、没有安全状态机。
 * 所以这里**没有**连接按钮、没有绿灯、没有遥测曲线、没有"健康检查 ok"。
 *
 * 那几个输入框是**禁用**的：它们不连任何东西。做成可编辑再"看起来能连"，
 * 就是这一格最容易犯的错 —— 填了没反应，比不让填更误导。
 */
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { 数值表, type 数值行 } from "../组件/数值表";
import { use取 } from "./文案";

/** 将来要有的字段 —— 现在是灰色的、禁用的、且写明"不生效"的占位 */
const 设置字段 = [
  { 键: "部署.协议", 例: "UDP / 串口（都还没有实现）" },
  { 键: "部署.地址", 例: "192.168.0.10" },
  { 键: "部署.端口", 例: "9000" },
  { 键: "部署.波特率", 例: "115200" },
] as const;

const 要什么键 = [
  "部署.要什么.设备抽象",
  "部署.要什么.仿真后端",
  "部署.要什么.安全层",
  "部署.要什么.传输",
  "部署.要什么.真机",
] as const;

export function 部署视图() {
  const t = use取();

  const 现状: 数值行[] = [
    { 键: t("状态栏.连接"), 值: t("通用.未接入"), 弱: true },
    { 键: t("部署.协议"), 值: t("通用.无"), 弱: true },
    { 键: t("部署.有绿灯"), 值: t("通用.否"), 弱: true },
  ];

  return (
    <div>
      <可折叠区块
        标题={t("部署.未接入标题")}
        徽标={<标签 语气="警示">{t("通用.未接入")}</标签>}
      >
        <div className="未接入">
          <p>{t("部署.未接入说明")}</p>
          <div className="mt-2">
            <数值表 行={现状} />
          </div>
          <p className="mt-2 text-[0.9em]">{t("部署.诚实要求")}</p>
          <p className="mt-2 text-[0.9em]">{t("部署.绿灯是假的")}</p>
        </div>
      </可折叠区块>

      <可折叠区块 标题={t("部署.连接设置")} 徽标={<标签 语气="警示">{t("通用.未接入")}</标签>}>
        <p className="text-dim">{t("部署.连接设置.说明")}</p>
        <div className="mt-2 space-y-2">
          {设置字段.map((f) => (
            <label key={f.键} className="block">
              <span className="text-dim">{t(f.键)}</span>
              <input
                className="输入 mt-0.5 等宽"
                value=""
                placeholder={f.例}
                disabled
                readOnly
                aria-disabled="true"
              />
            </label>
          ))}
        </div>
      </可折叠区块>

      <可折叠区块 标题={t("部署.安全")} 默认开={false}>
        <p className="text-dim">{t("部署.安全说明")}</p>
      </可折叠区块>

      <可折叠区块 标题={t("部署.要什么")} 徽标={<span className="等宽">{要什么键.length}</span>} 默认开={false}>
        <ul className="space-y-1">
          {要什么键.map((k) => (
            <li key={k} className="flex gap-1.5">
              <span aria-hidden="true" className="等宽 text-dim">
                ·
              </span>
              <span>{t(k)}</span>
            </li>
          ))}
        </ul>
      </可折叠区块>
    </div>
  );
}
