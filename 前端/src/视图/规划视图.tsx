/**
 * 规划视图.tsx —— 「规划」：关节航点 → 时间参数化轨迹。
 *
 * 这一格显示的全是**真数字**，来自后端 `规划桥` 对内核输出的回算：
 *   · 终端速度（必须是 0 —— 不是事后置零，是后向扫描天然收住的）
 *   · 三项余量（1 − max(实际/限位)）：负数 = 超限，后端会直接判失败
 *   · 瓶颈（哪个关节、什么类型、在 s 的哪里）
 *   · 限位来源：**显式**还是**估算** —— 估算时必须让用户看见，否则"规划通过"没有意义
 *
 * ★ 关于 jerk：本版**只校验不整形**。收紧 jerk 限会让它判失败而不是变慢，
 *   界面上这句话必须写出来，不能让用户以为它做了 S 曲线。
 */
import { useState } from "react";
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { 按钮 } from "../组件/按钮";
import { 数值表, type 数值行 } from "../组件/数值表";
import { useRef } from "react";
import { 命令, 用仓库 } from "../数据/仓库";
import { 解析航点文本, type 解析结果 } from "../数据/航点文件";
import { 命令收尾, 记命令发出 } from "../数据/日志";
import { use取 } from "./文案";

export function 规划视图() {
  const t = use取();
  const 规划 = 用仓库((s) => s.规划.数据);
  const 模型 = 用仓库((s) => s.模型.数据);
  const 连接 = 用仓库((s) => s.连接);
  const [忙, 设忙] = useState(false);
  const [导入, 设导入] = useState<解析结果 | null>(null);
  // 约束：空 = 用后端按模型推算的默认值（界面上写明是"估算"）。
  //   ★ 给用户的是关节空间的量（rad/s、rad/s²），不是 s 空间的 ——
  //     s 空间的数与实际快慢差一个路径长度，用户从界面上的数推不出会发生什么。
  const [速度上限, 设速度上限] = useState("");
  const [加速度上限, 设加速度上限] = useState("");
  const 文件框 = useRef<HTMLInputElement | null>(null);
  const 可发 = 连接 === "已连接";

  /** 选文件 → 解析 → 直接把航点送去规划（不落盘、不占权限面） */
  const 读文件 = async (文件: File | undefined) => {
    if (!文件) return;
    设忙(true);
    try {
      const 文本 = await 文件.text();
      const 果 = 解析航点文本(文本, 规划?.自由度 || 模型?.自由度);
      设导入(果);
      if (!果.问题) {
        const 起于 = 记命令发出();
        命令收尾("命令.规划", await 命令.跑规划(果.航点.map((关节) => ({ 关节 }))), 起于);
      }
    } finally {
      设忙(false);
      if (文件框.current) 文件框.current.value = "";
    }
  };

  /** 把输入框里的单一数值铺成"每个关节一个"的上限；空/非法 → undefined（用默认） */
  const 数们 = (文本: string) => {
    const 值 = Number(文本);
    const 自由度 = 规划?.自由度 || 模型?.自由度 || 0;
    return 文本.trim() && Number.isFinite(值) && 值 > 0 && 自由度 > 0
      ? Array.from({ length: 自由度 }, () => 值)
      : undefined;
  };

  const 跑 = async (动作: "记录航点" | "清空航点" | "规划") => {
    设忙(true);
    try {
      const 起于 = 记命令发出();
      const r =
        动作 === "记录航点" ? await 命令.记录航点()
        : 动作 === "清空航点" ? await 命令.清空航点()
        : await 命令.跑规划(undefined, {
            速度上限: 数们(速度上限),
            加速度上限: 数们(加速度上限),
          });
      命令收尾("命令.规划", r, 起于, { 模块: "规划" });
    } finally {
      设忙(false);
    }
  };

  const 成功 = 规划?.状态 === "✓ 完成";
  const 执行中 = 规划?.执行状态 === "执行中";
  const 规划中 = 规划?.状态 === "规划中";
  const 航点数 = 规划?.航点数 ?? 0;

  /** 执行/停止轨迹：走同一条命令通道，因此也有回执 */
  const 执行 = async (开始: boolean) => {
    设忙(true);
    try {
      const 起于 = 记命令发出();
      命令收尾("命令.规划", 开始 ? await 命令.执行轨迹() : await 命令.停止轨迹(), 起于, {
        模块: "规划",
      });
    } finally {
      设忙(false);
    }
  };
  const 失败 = 规划?.状态 === "✗ 失败";

  const 高亮瓶颈 = async () => {
    const 关节 = 规划?.瓶颈关节;
    if (关节 === undefined || 关节 < 0) return;
    const 起于 = 记命令发出();
    命令收尾("命令.高亮", await 命令.高亮关节(关节, 8), 起于, { 模块: "规划", 关节 });
  };

   /** 余量 → 标签语气：负数（超限）就是警示 */
  const 余量语气 = (v?: number) => (v === undefined ? "中性" : v < 0 ? "警示" : v < 0.05 ? "强调" : "中性");

  const 行: 数值行[] = 规划
    ? [
        { 键: t("规划.航点数"), 值: <span className="等宽">{规划.航点数 ?? "--"}</span> },
        { 键: t("规划.自由度"), 值: <span className="等宽">{规划.自由度 ?? "--"}</span> },
        { 键: t("规划.总时长"), 值: <span className="等宽">{规划.总时长 === undefined ? "--" : `${规划.总时长.toFixed(3)} s`}</span> },
        { 键: t("规划.路径长度"), 值: <span className="等宽">{规划.路径长度 === undefined ? "--" : `${规划.路径长度.toFixed(3)} rad`}</span> },
        { 键: t("规划.终端速度"), 值: <span className="等宽">{(规划.终端速度 ?? 0).toExponential(1)}</span> },
        { 键: t("规划.最大速度"), 值: <span className="等宽">{(规划.最大关节速度 ?? 0).toFixed(3)}</span> },
        { 键: t("规划.最大加速度"), 值: <span className="等宽">{(规划.最大关节加速度 ?? 0).toFixed(2)}</span> },
        { 键: t("规划.最大加加速度"), 值: <span className="等宽">{(规划.最大关节加加速度 ?? 0).toFixed(2)}</span> },
        {
          键: t("规划.瓶颈"),
          值: (
            <span className="等宽">
              {规划.瓶颈类型 ? `${规划.瓶颈类型} @ J${规划.瓶颈关节} (s=${(规划.瓶颈位置 ?? 0).toFixed(2)})` : "--"}
            </span>
          ),
        },
        {
          键: t("规划.实际比下界"),
          值: <span className="等宽">{(规划.实际比下界 ?? 0).toFixed(2)}<span className="ml-1 text-dim">×</span></span>,
        },
      ]
    : [];

  return (
    <div className="space-y-2">
      <可折叠区块
        标题={t("步骤.规划")}
        徽标={
          成功 ? <标签 语气="成功">{`${规划?.总时长?.toFixed(2) ?? "?"}s`}</标签>
          : 失败 ? <标签 语气="错误">{t("规划.失败")}</标签>
          : 规划中 ? <标签 语气="强调">{t("规划.规划中")}</标签>
          : 航点数 > 0 ? <标签>{t("规划.航点计数", { 数量: 航点数 })}</标签>
          : <标签>{t("规划.尚无航点")}</标签>
        }
      >
        <p className="text-dim">{t("规划.说明")}</p>
        <p className="mt-1 text-[0.8em] text-dim">{t("规划.文件说明")}</p>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <按钮 种类="次" 尺寸="小" disabled={忙 || !可发} on按下={() => void 跑("记录航点")}>
            {t("规划.记录")}
          </按钮>
          <label className="flex items-center gap-1 text-[0.8em]">
            <span className="text-dim">{t("规划.速度上限")}</span>
            <input
              className="参数输入 w-[62px]"
              value={速度上限}
              onChange={(e) => 设速度上限(e.target.value)}
              placeholder={t("规划.自动")}
              inputMode="decimal"
            />
          </label>
          <label className="flex items-center gap-1 text-[0.8em]">
            <span className="text-dim">{t("规划.加速度上限")}</span>
            <input
              className="参数输入 w-[62px]"
              value={加速度上限}
              onChange={(e) => 设加速度上限(e.target.value)}
              placeholder={t("规划.自动")}
              inputMode="decimal"
            />
          </label>
          <按钮
            种类="主"
            尺寸="小"
            disabled={忙 || !可发 || 规划中 || 航点数 < 2}
            title={航点数 < 2 ? t("规划.需要航点") : undefined}
            on按下={() => void 跑("规划")}
          >
            {规划中 ? t("规划.规划中") : t("规划.规划")}
          </按钮>
          <按钮 种类="次" 尺寸="小" disabled={忙 || !可发 || 航点数 === 0} on按下={() => void 跑("清空航点")}>
            {t("规划.清空")}
          </按钮>
          {成功 ? (
            执行中 ? (
              <按钮 种类="次" 尺寸="小" disabled={忙 || !可发} on按下={() => void 执行(false)}>
                {t("规划.停止")}
              </按钮>
            ) : (
              <按钮 种类="次" 尺寸="小" disabled={忙 || !可发} on按下={() => void 执行(true)}>
                {t("规划.执行")}
              </按钮>
            )
          ) : null}
          <input
            ref={文件框}
            type="file"
            accept=".csv,.txt,text/csv,text/plain"
            className="hidden"
            onChange={(e) => void 读文件(e.target.files?.[0])}
          />
          <按钮 种类="次" 尺寸="小" disabled={忙} on按下={() => 文件框.current?.click()}>
            {t("规划.导入")}
          </按钮>
          {规划?.航点数 ? (
            <span className="text-[0.85em] text-dim">{`${t("规划.已记录")}: ${规划.航点数}`}</span>
          ) : null}
        </div>

        {!成功 && 航点数 < 2 ? (
          <p className="mt-1.5 text-[0.82em] text-dim">{t("规划.需要航点")}</p>
        ) : null}

        {导入 ? (
          <div
            className="mt-2 text-[0.82em]"
            style={{ color: 导入.问题 ? "var(--danger)" : "var(--fg-dim)" }}
          >
            {导入.问题
              ? `${t("规划.导入失败")}：${导入.问题}`
              : `${t("规划.导入成功")}：${导入.行数} 个航点 × ${导入.列数} 列（跳过 ${导入.跳过} 行注释/表头）`}
          </div>
        ) : null}

        {失败 && 规划?.原因 ? (
          <div className="mt-2 text-[0.85em]" style={{ color: "var(--warn)" }}>
            {规划.原因}
          </div>
        ) : null}

        {规划?.瓶颈关节 !== undefined && 规划.瓶颈关节 >= 0 ? (
          <div className="mt-1">
            <按钮 种类="幽灵" 尺寸="小" on按下={() => void 高亮瓶颈()}>
              {t("规划.高亮瓶颈", { 关节: 规划.瓶颈关节 })}
            </按钮>
          </div>
        ) : null}

        {成功 ? (
          <>
            <div className="mt-2">
              <数值表 行={行} />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[0.82em]">
              <span className="text-dim">{t("规划.余量")}</span>
              <标签 语气={余量语气(规划.速度余量)}>{`速度 ${((规划.速度余量 ?? 0) * 100).toFixed(0)}%`}</标签>
              <标签 语气={余量语气(规划.加速度余量)}>{`加速度 ${((规划.加速度余量 ?? 0) * 100).toFixed(0)}%`}</标签>
              <标签 语气={余量语气(规划.加加速度余量)}>{`加加速度 ${((规划.加加速度余量 ?? 0) * 100).toFixed(0)}%`}</标签>
            </div>
            {规划.对比 ? (
              <div className="mt-2">
                <div className="flex items-baseline gap-1.5">
                  <span style={{ fontWeight: 600 }}>{t("规划.对比")}</span>
                  <span className="flex-1" />
                  <标签 语气={(规划.对比["时长变化%"] ?? 0) > 0 ? "警示" : "强调"}>
                    {`${(规划.对比["时长变化%"] ?? 0) >= 0 ? "+" : ""}${(规划.对比["时长变化%"] ?? 0).toFixed(0)}%`}
                  </标签>
                </div>
                <div className="text-[0.82em] text-dim">
                  {`${(规划.对比.上次时长 ?? 0).toFixed(2)} s → ${(规划.对比.本次时长 ?? 0).toFixed(2)} s`}
                </div>
                {规划.对比.上次sd?.length && 规划.对比.本次sd?.length ? (
                  <对比图 上次={规划.对比.上次sd} 本次={规划.对比.本次sd} />
                ) : null}
                <div className="text-[0.78em] text-dim">{t("规划.对比.说明")}</div>
              </div>
            ) : null}

            {规划.存盘路径 ? (
              <div className="mt-1 text-[0.82em]">
                <span className="text-dim">{t("规划.存盘")}：</span>
                <span className="等宽 break-all">{规划.存盘路径}</span>
              </div>
            ) : null}
            {执行中 ? (
              <div className="mt-1 flex items-center gap-2 text-[0.82em]">
                <span className="text-dim">{t("规划.执行进度")}</span>
                <span className="等宽">{`${((规划.执行进度 ?? 0) * 100).toFixed(0)}%`}</span>
              </div>
            ) : null}
            {规划.限位来源 ? (
              <div className="mt-1 text-[0.82em]" style={{ color: "var(--warn)" }}>
                {`${t("规划.限位来源")}: ${规划.限位来源}`}
              </div>
            ) : null}
          </>
        ) : null}

        {规划?.包络?.length ? (
          <div className="mt-2">
            <div className="text-[0.85em] text-dim">{t("规划.包络")}</div>
            <包络图 包络={规划.包络} sd={规划.sd轴 ?? []} />
          </div>
        ) : null}
      </可折叠区块>
    </div>
  );
}

/**
 * 包络图 —— 手写 SVG（项目里没有图表库，也不打算为一张图引一个）。
 * 灰线 = 速度上界 `v_s_max(s)`；蓝线 = 实际 `sd(s)`。
 * 两条线之间的空隙就是"没用满的部分"，比看数字直观。
 */
function 包络图({ 包络, sd }: { 包络: number[]; sd: number[] }) {
  const 宽 = 100;
  const 高 = 42;
  const 全 = [...包络, ...sd].filter((x) => Number.isFinite(x) && x > 0);
  if (!全.length) return null;
  const 顶 = Math.max(...全) || 1;
  const 折 = (组: number[]) =>
    组
      .map((v, i) => {
        const x = (i / Math.max(组.length - 1, 1)) * 宽;
        const y = 高 - (Math.max(0, Math.min(v, 顶)) / 顶) * 高;
        return `${i ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");
  return (
    <svg viewBox={`0 0 ${宽} ${高}`} className="mt-1 w-full" style={{ height: 90 }} aria-hidden="true">
      <path d={折(包络)} fill="none" stroke="var(--border)" strokeWidth="0.6" />
      {sd.length ? <path d={折(sd)} fill="none" stroke="var(--palette-1)" strokeWidth="0.9" /> : null}
    </svg>
  );
}

/**
 * 对比图 —— 灰线 = 上一次的 sd(s)，蓝线 = 本次。
 *
 * 横轴是路径参数 s（不是时间），所以两条线可以直接叠：
 * **同一批航点**下几何路径是一样的，差别只在"走多快"。
 * 这也是为什么只有航点一致时才出对比 —— 路径不同的话叠在一起没有意义。
 */
function 对比图({ 上次, 本次 }: { 上次: number[]; 本次: number[] }) {
  const 宽 = 100;
  const 高 = 30;
  const 顶 = Math.max(...上次, ...本次, 1e-9);
  const 折 = (组: number[]) =>
    组
      .map((v, i) => {
        const x = (i / Math.max(组.length - 1, 1)) * 宽;
        const y = 高 - (Math.max(0, v) / 顶) * 高;
        return `${i ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");
  return (
    <svg viewBox={`0 0 ${宽} ${高}`} className="mt-1 w-full" style={{ height: 56 }} aria-hidden="true">
      <path d={折(上次)} fill="none" stroke="var(--border-strong)" strokeWidth="0.9" />
      <path d={折(本次)} fill="none" stroke="var(--accent)" strokeWidth="1" />
    </svg>
  );
}
