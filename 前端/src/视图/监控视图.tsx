/**
 * 监控视图.tsx —— 任务流「监控」：跑得动跑不动，看这一格。
 *
 * 诚实边界（先写清楚，免得以后有人往这里塞假数据）：
 *   · RTF / 步频 / 内存 **只有仿真侧能量到**，所以全部来自后端「系统」主题。
 *     界面**不自己估**：拿不到就写"还没收到"，绝不按帧间隔反推一个看起来合理的数。
 *   · 「3D 渲染帧率」**没有做**：那是窗口层的事（3D 视口自己的统计），
 *     仿真侧看不到，所以它不在「系统」消息里。我一开始画了这一格，
 *     结果只能填一个固定的 `--` —— 那正是"看起来像监控、其实是摆设"，
 *     所以整格删掉了。要做它，得先把视口统计算进契约（另开一步）。
 *   · 连接断开时明确写"连接已断开"，而不是让数字停在最后一个值上装作还在跑。
 */
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { 数值表, 数值文本, type 数值行 } from "../组件/数值表";
import { 用仓库 } from "../数据/仓库";
import { use取 } from "./文案";

export function 监控视图() {
  const t = use取();
  const 系统 = 用仓库((s) => s.系统.数据);
  const 连接 = 用仓库((s) => s.连接);

  /** RTF 的语气：1 附近算正常；掉到 0.8 以下就该提示了 */
  const RTF语气 = (() => {
    if (!系统?.RTF) return "警示" as const;
    if (系统.RTF >= 0.95) return "强调" as const;   // 跑得动 = 好
    return "警示" as const;                          // 掉到 0.95 以下就该看
  })();

  const 行: 数值行[] = 系统
    ? [
        {
          键: t("监控.实时率"),
          值: (
            <span className="等宽">
              <数值文本 值={系统.RTF} 位={2} />
              <span className="ml-1 text-dim">×</span>
            </span>
          ),
        },
        {
          键: t("监控.步频"),
          值: <span className="等宽">{系统.步频 === undefined ? "--" : `${系统.步频.toFixed(0)} Hz`}</span>,
        },
        { 键: t("监控.步长"), 值: <span className="等宽">{系统.仿真步长?.toFixed(4) ?? "--"} s</span> },
        {
          键: t("监控.内存"),
          值: <span className="等宽">{系统.内存MB === undefined ? "--" : `${系统.内存MB.toFixed(0)} MB`}</span>,
        },
        { 键: t("监控.仿真时间"), 值: <span className="等宽">{系统.仿真时间?.toFixed(2) ?? "--"} s</span> },
        { 键: t("监控.墙钟"), 值: <span className="等宽">{系统.墙钟?.toFixed(1) ?? "--"} s</span> },
        { 键: t("监控.插件数"), 值: <span className="等宽">{系统.插件数 ?? "--"}</span> },
      ]
    : [];

  return (
    <div className="space-y-2">
      <可折叠区块
        标题={t("步骤.监控")}
        徽标={
          系统 ? (
            <标签 语气={RTF语气}>{`RTF ${系统.RTF?.toFixed(2) ?? "--"}`}</标签>
          ) : (
            <标签 语气="警示">{t("通用.待接入")}</标签>
          )
        }
      >
        <p className="text-dim">{t("监控.说明")}</p>
        {系统 ? (
          <div className="mt-2">
            <数值表 行={行} />
          </div>
        ) : (
          <div className="mt-2 text-dim">
            {连接 === "已连接" ? t("监控.没数据") : t("连接.已断开")}
          </div>
        )}
        {系统?.出错 ? (
          <div className="mt-2" style={{ color: "var(--warning)" }}>
            {系统.出错}
          </div>
        ) : null}
      </可折叠区块>
    </div>
  );
}
