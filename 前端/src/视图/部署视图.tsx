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
import { 数值表, type 数值行 } from "../组件/数值表";
import { 连接键, use取 } from "./文案";

export function 部署视图() {
  const t = use取();
  const 状态 = 用仓库((s) => s.部署.数据);
  const 项目 = 用仓库((s) => s.项目.数据);
  const 连接 = 用仓库((s) => s.连接);
  const [忙, 设忙] = useState(false);
  const 可发 = 连接 === "已连接";
  const 算法们 = (项目?.算法 ?? []).map((a) => {
    const 名 = String(a.名称 ?? a.插件 ?? "");
    const 版 = a.版本 === undefined ? "" : ` v${String(a.版本)}`;
    return `${名}${版}`;
  });

  const 导出中 = 状态?.状态 === "导出中";
  const 成功 = 状态?.状态 === "✓ 完成";
  const 失败 = 状态?.状态 === "✗ 失败";

  const 导出 = async () => {
    设忙(true);
    try {
      const 起于 = 记命令发出();
      命令收尾("命令.部署", await 命令.导出部署包(), 起于, { 模块: "部署" });
    } finally {
      设忙(false);
    }
  };

  return (
    <div className="space-y-2">
      <设备控制台 />

      <可折叠区块
        标题={t("部署.标题")}
        徽标={
          成功 ? <标签 语气="强调">{`${状态?.文件数 ?? 0} 文件`}</标签>
          : 失败 ? <标签 语气="警示">{t("部署.失败")}</标签>
          : 导出中 ? <标签 语气="强调">{t("部署.导出中")}</标签>
          : <标签>{t("部署.未导出")}</标签>
        }
      >
        {/* 第一屏分清"后端已连接"与"真机未接入"：两个"已连接"不是一回事 */}
        <div className="部署状态" role="status">
          <span className="部署状态项">
            <span className="text-dim">{t("部署.后端连接")}</span>
            <标签 语气={可发 ? "成功" : "错误"}>{t(连接键[连接])}</标签>
          </span>
          <span className="部署状态项">
            <span className="text-dim">{t("部署.真机状态")}</span>
            <标签 语气="警告">{t("部署.真机未接入")}</标签>
          </span>
        </div>
        <p className="mt-1 text-[0.85em]" style={{ color: "var(--warn)" }}>
          {t("部署.没有连接")}
        </p>

        <div className="mt-2 flex items-center gap-2">
          <按钮 种类="主" disabled={忙 || 导出中 || !可发} title={t("部署.说明")} on按下={() => void 导出()}>
            {导出中 ? t("部署.导出中") : t("部署.导出")}
          </按钮>
          <span className="text-[0.85em] text-dim">
            {`${t("部署.项目")}: ${项目?.项目 || t("通用.无")}`}
          </span>
        </div>

        {状态?.出错 ? (
          <div className="mt-2 text-[0.85em]" style={{ color: "var(--warn)" }}>
            {状态.出错}
          </div>
        ) : null}

        {成功 && 状态?.清单?.length ? (
          <div className="mt-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[0.82em] text-dim">
              <span>{`${t("部署.项目")}: ${项目?.项目 || t("通用.无")}`}</span>
              <span>{`${t("状态栏.模型")}: ${项目?.模型显示名 || t("通用.无")}`}</span>
              <span>{`${t("定义.算法数")}: ${项目?.算法?.length ?? 0}`}</span>
              <span>{`${t("部署.总大小")}: ${((状态.字节 ?? 0) / 1024).toFixed(1)} KB`}</span>
            </div>
            <div className="mt-0.5 break-words text-[0.82em] text-dim">
              {`${t("定义.算法组")}: ${算法们.length ? 算法们.join(" · ") : t("通用.无")}`}
            </div>
            <p className="mt-1 text-[0.8em] text-dim">{t("部署.模型清单说明")}</p>
            <div className="mt-2 text-[0.85em] text-dim">{t("部署.目录")}</div>
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

/**
 * 设备控制台 —— 部署页真正的"连接"部分。
 *
 * ★ 这一格最重要的不是按钮，是**它诚实**：
 *   · 永远显示 `后端` 名字（现在是"模拟后端"）——不让人误以为是真机
 *   · 遥测数字全部来自真实帧时间戳与后端统计，没有就显示"还没收到"
 *   · 状态机画出来，"在哪一格"一眼可见；进「运行」必须人点，没有任何自动流程
 */
function 设备控制台() {
  const t = use取();
  const 设备 = 用仓库((s) => s.设备.数据);
  const 连接 = 用仓库((s) => s.连接);
  const [忙, 设忙] = useState(false);
  const 可发 = 连接 === "已连接";

  const 动 = async (动作: string, 参数?: Record<string, number>) => {
    设忙(true);
    try {
      const 起于 = 记命令发出();
      命令收尾("命令.设备", await 命令.设备动作(动作, 参数), 起于, { 模块: "部署" });
    } finally {
      设忙(false);
    }
  };

  const 态 = 设备?.安全状态 ?? "未连接";
  /** 状态名 → 显示文案。★ 用显式映射而不是模板字符串：
   *  模板 key（`部署.态.${态}`）在类型上是不安全的，新增状态时编译器帮不上忙。 */
  const 态名 = (s: string) =>
    ({
      未连接: t("部署.态.未连接"),
      "已连接（未使能）": t("部署.态.已连接（未使能）"),
      使能中: t("部署.态.使能中"),
      运行: t("部署.态.运行"),
      停止: t("部署.态.停止"),
      故障: t("部署.态.故障"),
      急停: t("部署.态.急停"),
    })[s] ?? s;
  const 阶 = ["未连接", "已连接（未使能）", "使能中", "运行"];
  const 已连接 = !!设备?.已连接;
  const 是运行 = 态 === "运行";
  const 异常 = 态 === "故障" || 态 === "急停";

  const 遥测: 数值行[] = 设备
    ? [
        { 键: t("部署.后端"), 值: <span className="等宽">{设备.后端 || "--"}</span> },
        { 键: t("部署.模式"), 值: <span className="等宽">{设备.模式 || "--"}</span> },
        { 键: t("部署.实测平均延迟"), 值: <span className="等宽">{设备.实测平均延迟 ? `${设备.实测平均延迟.toFixed(1)} ms` : t("部署.还没收到")}</span> },
        { 键: t("部署.实测最大延迟"), 值: <span className="等宽">{设备.实测最大延迟 ? `${设备.实测最大延迟.toFixed(1)} ms` : "--"}</span> },
        { 键: t("部署.丢包错序"), 值: <span className="等宽">{`${设备.丢包数 ?? 0} / ${设备.错序数 ?? 0}`}</span> },
        { 键: t("部署.拒绝数"), 值: <span className="等宽">{设备.拒绝数 ?? 0}</span> },
        {
          键: t("部署.最近位置"),
          值: (
            <span className="等宽">
              {设备.最近位置?.length
                ? `${设备.最近位置.slice(0, 3).map((x) => x.toFixed(3)).join(", ")}…`
                : t("部署.还没收到")}
            </span>
          ),
        },
      ]
    : [];

  return (
    <可折叠区块
      标题={t("部署.设备")}
      徽标={
        <标签 语气={异常 ? "警示" : 是运行 ? "强调" : 已连接 ? "成功" : "警示"}>
          {态名(态)}
        </标签>
      }
    >
      <p className="mt-1 text-[0.85em]" style={{ color: "var(--warn)" }}>
        {t("部署.模拟后端")}
      </p>

      {/* 状态机：把"在哪一格"画出来，比一个词更清楚 */}
      <ol className="mt-2 flex flex-wrap items-center gap-1 text-[0.78em]">
        {阶.map((格, i) => {
          const 到达 = 阶.indexOf(态) >= i && 阶.includes(态);
          return (
            <li key={格} className="flex items-center gap-1">
              {i ? <span className="text-dim">→</span> : null}
              <span
                className="rounded px-1.5 py-0.5 等宽"
                style={{
                  background: 到达 ? "var(--accent)" : "var(--bg-frame)",
                  color: 到达 ? "var(--fg-on-accent)" : "var(--fg-dim)",
                }}
              >
                {态名(格)}
              </span>
            </li>
          );
        })}
        {异常 ? (
          <li className="flex items-center gap-1">
            <span className="text-dim">→</span>
            <span className="rounded px-1.5 py-0.5 等宽"
                  style={{ background: "var(--danger)", color: "#fff" }}>
              {态名(态)}
            </span>
          </li>
        ) : null}
      </ol>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <按钮 种类="次" 尺寸="小" disabled={忙 || !可发} on按下={() => void 动("打开")}>
          {t("部署.打开")}
        </按钮>
        <按钮 种类="主" 尺寸="小" disabled={忙 || !可发 || 态 !== "已连接（未使能）"}
              on按下={() => void 动("使能")}>
          {t("部署.使能")}
        </按钮>
        <按钮 种类="主" 尺寸="小" disabled={忙 || !可发 || 态 !== "使能中"}
              on按下={() => void 动("进运行")}>
          {t("部署.进运行")}
        </按钮>
        <按钮 种类="次" 尺寸="小" disabled={忙 || !可发 || !已连接}
              on按下={() => void 动("停止")}>
          {t("部署.停止")}
        </按钮>
        <按钮 种类="次" 尺寸="小" disabled={忙 || !可发 || !已连接}
              on按下={() => void 动("急停")}>
          {t("部署.急停")}
        </按钮>
        <按钮 种类="次" 尺寸="小" disabled={忙 || !可发 || !已连接}
              on按下={() => void 动("演练断线")}>
          {t("部署.演练")}
        </按钮>
        <按钮 种类="次" 尺寸="小" disabled={忙 || !可发}
              on按下={() => void 动("导出审计")}>
          {t("部署.导出审计")}
        </按钮>
      </div>

      {设备 && 遥测.length ? (
        <div className="mt-2">
          <数值表 行={遥测} />
        </div>
      ) : null}

      <div className="mt-2 grid grid-cols-2 gap-2">
        <劣化滑块 名={t("部署.延迟")} 值={设备?.延迟毫秒 ?? 0} 上限={60} 步={1}
                  单位="ms" 禁用={!已连接 || 忙}
                  on改={(v) => void 动("设劣化", { 延迟毫秒: v })} />
        <劣化滑块 名={t("部署.丢包")} 值={(设备?.丢包率 ?? 0) * 100} 上限={50} 步={1}
                  单位="%" 禁用={!已连接 || 忙}
                  on改={(v) => void 动("设劣化", { 丢包率: v / 100 })} />
        <劣化滑块 名={t("部署.抖动")} 值={设备?.抖动毫秒 ?? 0} 上限={20} 步={0.5}
                  单位="ms" 禁用={!已连接 || 忙}
                  on改={(v) => void 动("设劣化", { 抖动毫秒: v })} />
        <劣化滑块 名={t("部署.量化")} 值={设备?.编码器分辨率 ?? 0} 上限={0.02} 步={0.001}
                  单位="rad" 禁用={!已连接 || 忙}
                  on改={(v) => void 动("设劣化", { 编码器分辨率: v })} />
      </div>

      {设备?.审计?.length ? (
        <div className="mt-2">
          <div className="text-[0.85em] text-dim">{t("部署.审计")}</div>
          <ul className="mt-1 max-h-[132px] space-y-0.5 overflow-y-auto">
            {设备.审计.slice().reverse().map((条, i) => (
              <li key={`${条.时刻}-${i}`} className="flex items-baseline gap-1.5 text-[0.78em]">
                <span className="flex-none text-dim 等宽">{条.类别}</span>
                <span className="min-w-0 flex-1 truncate" title={条.内容}>{条.内容}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </可折叠区块>
  );
}

/** 劣化参数滑块：改完立刻生效（不需要"应用"按钮，便于现场演示） */
function 劣化滑块({
  名, 值, 上限, 步, 单位, 禁用, on改,
}: {
  名: string; 值: number; 上限: number; 步: number; 单位: string;
  禁用: boolean; on改: (v: number) => void;
}) {
  return (
    <label className="block text-[0.8em]">
      <span className="flex items-baseline gap-1">
        <span className="text-dim">{名}</span>
        <span className="flex-1" />
        <span className="等宽">{`${值.toFixed(步 < 1 ? 2 : 0)} ${单位}`}</span>
      </span>
      <input
        type="range"
        className="mt-0.5 w-full"
        min={0}
        max={上限}
        step={步}
        value={值}
        disabled={禁用}
        onChange={(e) => on改(Number(e.target.value))}
        aria-label={名}
      />
    </label>
  );
}
