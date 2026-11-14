/**
 * 验证视图.tsx —— 任务流第 3 步：实时曲线 + 参数表。
 *
 * 两块都是**真数据**：
 *   · 曲线 ← 下行主题「指标」（`s.曲线`，最近 120 秒环形缓冲）
 *   · 参数表 ← 下行主题 `parameter.table`（各算法自己声明的可调参数）
 *
 * 两块都各有一处**不能做**的事，所以就地写明：
 *   · 曲线：横轴用**墙钟**而不是仿真时间（物理暂停时仿真时间不动，曲线会挤成一坨）。
 *   · 参数表：**可编辑** —— 走 `command.parameters`，等回执后参数表回灌最新值。
 *     所以这里是只读的真值，而不是一个按了没反应的滑块。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { 曲线, 取配色 } from "../组件/曲线";
import { 可折叠区块 } from "../组件/可折叠区块";
import { 按钮 } from "../组件/按钮";
import { 标签 } from "../组件/标签";
import { 小表格, 数值文本, 文本, type 列 } from "../组件/数值表";
import { 命令, 用仓库 } from "../数据/仓库";
import { 用节拍 } from "../数据/时钟";
import { 请求跳步 } from "../外壳/跳步";
import type { ParameterItem } from "../数据/仓库";
import { 提示错误 } from "../数据/提示";
import { use取 } from "./文案";

/** `s.曲线` 的环形缓冲窗口（`数据/仓库.ts` 里就是 120 秒） */
const 窗口秒 = 120;

function 数字文本(值?: number): string {
  return 值 === undefined || !Number.isFinite(值) ? "" : String(值);
}

function 参数值编辑({
  全名, 值, 最小, 最大, 步长, 保存中, 提交,
}: {
  全名: string;
  值?: number;
  最小?: number;
  最大?: number;
  步长?: number;
  保存中: boolean;
  提交: (全名: string, 新值: number) => Promise<boolean>;
}) {
  const t = use取();
  const [草稿, 设草稿] = useState(() => 数字文本(值));
  const [焦点, 设焦点] = useState(false);
  const [脏, 设脏] = useState(false);
  const [错误, 设错误] = useState("");
  const 待确认 = useRef<number | null>(null);

  // 后端回灌：只有"没在编辑 + 没有未提交修改"时才覆盖草稿。
  // 提交成功后先等后端真的回灌这个值，避免被旧帧打回原值。
  useEffect(() => {
    if (待确认.current !== null) {
      if (值 !== undefined && Math.abs(值 - 待确认.current) <= 1e-9) {
        待确认.current = null;
        设脏(false);
        设错误("");
        设草稿(数字文本(值));
      }
      return;
    }
    if (!焦点 && !脏) {
      设草稿(数字文本(值));
      设错误("");
    }
  }, [值, 焦点, 脏]);

  const 还原 = () => {
    待确认.current = null;
    设草稿(数字文本(值));
    设脏(false);
    设错误("");
  };

  const 提交草稿 = async () => {
    const 文本 = 草稿.trim();
    if (!文本) {
      还原();
      return;
    }
    const 数字 = Number(文本);
    if (!Number.isFinite(数字)) {
      设错误(t("验证.参数.无效"));
      return;
    }
    if ((最小 !== undefined && 数字 < 最小) || (最大 !== undefined && 数字 > 最大)) {
      设错误(t("验证.参数.超范围", {
        最小: 最小 ?? "−∞",
        最大: 最大 ?? "+∞",
      }));
      return;
    }
    if (值 !== undefined && 数字 === 值) {
      设脏(false);
      设错误("");
      设草稿(数字文本(数字));
      return;
    }
    设错误("");
    const 通过 = await 提交(全名, 数字);
    if (通过) {
      待确认.current = 数字;
      设草稿(数字文本(数字));
      设脏(true);           // 等后端回灌后再变干净
    } else {
      设错误(t("验证.参数.未接受"));
    }
  };

  return (
    <span className="参数单元">
      <input
        type="text"
        inputMode="decimal"
        autoComplete="off"
        spellCheck={false}
        className="参数输入"
        aria-label={`${全名} ${t("验证.参数.值")}`}
        aria-invalid={!!错误}
        data-错误={错误 ? "true" : undefined}
        data-脏={脏 && !错误 ? "true" : undefined}
        value={草稿}
        disabled={保存中}
        title={[
          全名,
          最小 !== undefined || 最大 !== undefined
            ? t("验证.参数.范围提示", { 最小: 最小 ?? "−∞", 最大: 最大 ?? "+∞" })
            : "",
          步长 ? `步长 ${步长}` : "",
          t("验证.参数.编辑提示"),
        ].filter(Boolean).join("\n")}
        onFocus={() => 设焦点(true)}
        onBlur={() => {
          设焦点(false);
          if (脏) void 提交草稿();
        }}
        onChange={(e) => {
          设草稿(e.target.value);
          设脏(true);
          设错误("");
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (脏) void 提交草稿();
          } else if (e.key === "Escape") {
            e.preventDefault();
            还原();
          }
        }}
      />
      {错误 ? <span className="参数错误" title={错误} aria-hidden="true">!</span> : null}
      {保存中 ? <span className="参数保存" aria-hidden="true">…</span> : null}
    </span>
  );
}

export function 验证视图() {
  const t = use取();
  const 曲线数 = 用仓库((s) => s.曲线);
  const 参数 = 用仓库((s) => s.参数.数据);
  const 参数帧号 = 用仓库((s) => s.参数.帧号);
  const 仿真运行 = 用仓库((s) => s.仿真.数据?.state === "running");
  const 节拍 = 用节拍();

  const 名们 = useMemo(() => Object.keys(曲线数).sort(), [曲线数]);
  const [隐藏, 设隐藏] = useState<Set<string>>(new Set());
  const [暂停, 设暂停] = useState(false);

  // 曲线停在最后一个真实指标点；“多少秒前”只用本地时钟更新文字，
  // 不会为了让横轴移动而伪造重复数据点。
  const 最新时刻 = useMemo(() => {
    let 最晚 = 0;
    for (const n of 名们) {
      const 点 = 曲线数[n];
      if (点?.length) 最晚 = Math.max(最晚, 点[点.length - 1].t);
    }
    return 最晚;
  }, [名们, 曲线数]);
  const 最近年龄 = 最新时刻 ? Math.max(0, 节拍 / 1000 - 最新时刻) : undefined;

  const 窗口外 = 最新时刻
    ? 名们.filter((n) => {
        const 点 = 曲线数[n];
        return 点?.length ? 点[点.length - 1].t < 最新时刻 - 1 : false;
      }).length
    : 0;

  const 显示 = useMemo(() => new Set(名们.filter((n) => !隐藏.has(n))), [名们, 隐藏]);

  const 切换 = (名: string) => {
    设隐藏((旧) => {
      const 新 = new Set(旧);
      if (新.has(名)) 新.delete(名);
      else 新.add(名);
      return 新;
    });
  };

  /** 演示时一键切到同类曲线，避免角度、误差和力矩混在同一纵轴。 */
  const 只显示 = (判定: (名: string) => boolean) => {
    设隐藏(new Set(名们.filter((名) => !判定(名))));
  };

  const 图例行: Record<string, unknown>[] = 名们.map((名) => {
    const 点 = 曲线数[名];
    const 末 = 点?.[点.length - 1];
    let 峰 = -Infinity;
    for (const p of 点 ?? []) if (p.v > 峰) 峰 = p.v;
    return { 名, 值: 末?.v, 峰: Number.isFinite(峰) ? 峰 : undefined, 点: 点?.length ?? 0 };
  });

  const 图例列: 列[] = [
    {
      标题: t("验证.选中"),
      宽度: "w-[3.4em]",
      格: (行) => {
        const 名 = String(行.名);
        return (
          <input
            type="checkbox"
            checked={!隐藏.has(名)}
            onChange={() => 切换(名)}
            aria-label={`${t("验证.选中")} ${名}`}
            // 复选框、图例短线和画布曲线使用同一个稳定颜色，便于快速核对。
            style={{ accentColor: 取配色(名们.indexOf(名)) }}
          />
        );
      },
    },
    {
      标题: t("验证.曲线名"),
      // 给足宽度，否则长名字会被压成一竖条；配合下面的 `truncate` 用省略号收尾
      宽度: "w-[22ch] max-w-[22ch]",
      格: (行) => {
        const 名 = String(行.名);
        const 序 = 名们.indexOf(名);
        return (
          <span className="flex min-w-0 items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-[3px] w-3 flex-none"
              style={{ background: 取配色(序) }}
            />
            {/* ★ 曲线名要 `whitespace-nowrap`：它是「插件名·指标名」，本来就很长。
                之前用 `break-all` 在窄列里会**逐字换行**成一竖条（一行一个字），
                表格被撑成一条细长竖线 —— 实测截图里就是这样，能读但极难用。
                名称本来就可能超宽，所以让它不折行 + 溢出省略，完整名字放进 title。 */}
            <span className="truncate" title={名}>
              {名}
            </span>
          </span>
        );
      },
    },
    {
      标题: t("验证.当前值"),
      数字: true,
      格: (行) => <数值文本 值={行.值 as number | undefined} 位={4} />,
    },
    { 标题: t("验证.峰"), 数字: true, 格: (行) => <数值文本 值={行.峰 as number | undefined} 位={4} /> },
    { 标题: t("验证.点数"), 数字: true, 格: (行) => <span className="等宽">{String(行.点 ?? "")}</span> },
  ];

  // ★ `parameter.table` 的负载形状是 `{parameters: {full_name: item}}`。
  //   在**一个地方**解包，别让下面每处都记得多剥一层 ——
  //   实测踩过：少剥这一层会把 `参数` 这个包装键当成插件名，
  //   表格里出现 `值/单位/参数/插件/…` 一堆 `--` 行，看起来像"后端没报数据"。
  const 参数项们: [string, ParameterItem][] = useMemo(() => {
    const 原 = (参数 as unknown as { parameters?: Record<string, ParameterItem> } | null)?.parameters;
    if (!原 || typeof 原 !== "object") return [];
    return Object.keys(原).sort().map((全名) => [全名, 原[全名] ?? {}]);
  }, [参数]);

  // ★ 参数项的真实形状来自 `parameter_bridge.collect_parameters()`：
  //     {plugin, plugin_english, plugin_version, parameter, value, range, step, unit}
  //   早先这里按 `{值, 最小, 最大}` 渲染 —— 那是**按想象写的**，与实现不符，
  //   后果是 `范围`（一个数组）被当成对象逐字符渲染，表格里出现一堆 `0=N 1=·` 的乱码。
  const 范围边 = (项: ParameterItem, 哪端: 0 | 1): number | undefined => {
    const r = 项.range;
    return Array.isArray(r) && typeof r[哪端] === "number" ? (r[哪端] as number) : undefined;
  };

  // 改参数：**显式提交**（Enter / 失焦），不再每敲一个字符就发一条命令。
  // 旧实现把后端当前值直接绑在 input.value 上，onChange 立刻发命令并等回执；
  // 结果"1"还没打完就被后端回灌成原值，小数点/负号也经常打不进去。
  const [改中, 设改中] = useState<string | null>(null);
  async function 提交参数(全名: string, 新值: number): Promise<boolean> {
    if (改中 !== null) return false;
    设改中(全名);
    try {
      const 回执 = await 命令.updateParameters({ [全名]: 新值 });
      if (!回执.通过) {
        提示错误(回执.说明);
        return false;
      }
      return true;
    } catch (异常) {
      提示错误(`改参数失败：${String(异常)}`);
      return false;
    } finally {
      设改中(null);
    }
  }

  const 参数列: 列[] = [
    {
      标题: t("验证.参数.名"),
      宽度: "w-[20ch] max-w-[20ch]",
      格: (行) => (
        <span className="block truncate" title={String(行.全名)}>
          {String(行.全名)}
        </span>
      ),
    },
    {
      标题: t("验证.参数.值"),
      数字: true,
      格: (行) => {
        // ★ 必须用 `行.全名`（「插件名·参数名」），**不是** `行.名`（短名）。
        //   后端 `parameter_bridge` 按完整名称中的分隔符拆出插件名并查找实例：
        //   发短名（KD）会拆不出插件 → 实例找不到 → 命令被静默忽略，
        //   界面看起来就是"改了没用"。实测踩过，而且因为回执是"已接受"，
        //   现象上极像"编辑功能没实现"。
        const 全名 = String(行.全名 ?? 行.名);
        const 值 = 行.值 as number | undefined;
        const 最小 = 范围边(行 as unknown as ParameterItem, 0);
        const 最大 = 范围边(行 as unknown as ParameterItem, 1);
        const 步 = (行 as unknown as ParameterItem).step;
        return (
          <参数值编辑
            全名={全名}
            值={值}
            最小={最小}
            最大={最大}
            步长={typeof 步 === "number" ? 步 : undefined}
            保存中={改中 === 全名}
            提交={提交参数}
          />
        );
      },
    },
    {
      标题: t("验证.参数.最小"),
      数字: true,
      格: (行) => <数值文本 值={范围边(行 as unknown as ParameterItem, 0)} 位={6} />,
    },
    {
      标题: t("验证.参数.最大"),
      数字: true,
      格: (行) => <数值文本 值={范围边(行 as unknown as ParameterItem, 1)} 位={6} />,
    },
    {
      标题: t("验证.参数.单位"),
      格: (行) => <span className="等宽 text-dim">{String(行.单位 ?? "") || "—"}</span>,
    },
  ];

  /**
   * 把一个参数项摊成一行。字段名与后端一致，多余键原样附在后面（不丢信息）。
   * `全名` 形如「插件名·参数名」——插件名从它取（后端也单独给了 `插件` 字段，优先用它）。
   */
  function 摊开(全名: string, 项: ParameterItem): Record<string, unknown> {
    const 插件 = String(项.plugin ?? 全名.split("·")[0] ?? "");
    const 名 = String(项.parameter ?? 全名.split("·")[1] ?? 全名);
    const 已知 = ["plugin", "plugin_english", "plugin_version", "parameter", "value", "range", "step", "unit"];
    const 额外 = Object.keys(项).filter((k) => !已知.includes(k));
    const 范围 = 项.range;
    const 最小 = Array.isArray(范围) && typeof 范围[0] === "number" ? 范围[0] : undefined;
    const 最大 = Array.isArray(范围) && typeof 范围[1] === "number" ? 范围[1] : undefined;
    return {
      全名,
      插件,
      名,
      值: 项.value,
      最小,
      最大,
      单位: 项.unit,
      步长: 项.step,
      范围,
      说明: 额外.length ? 额外.map((k) => `${k}=${文本(项[k])}`).join(" ") : undefined,
    };
  }

  return (
    <div>
      <可折叠区块
        标题={t("验证.曲线")}
        徽标={
          <span className="等宽">
            {名们.length ? `${名们.length} · ${窗口秒}s` : ""}
          </span>
        }
      >
        <div className="面板" title={t("验证.曲线.说明")} style={{ background: "var(--plot-bg)", borderRadius: "var(--radius)" }}>
          <曲线 数据={曲线数} 显示={显示} 窗口={窗口秒} 高={190} on暂停={设暂停} />
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1 text-[0.85em] text-dim">
          <span className="flex-none">{t("验证.窗口.标签")}</span>
          <span className="等宽">{t("验证.窗口.值", { 值: 窗口秒 })}</span>
          <span aria-hidden="true">·</span>
          <span>{t("曲线.轴时间")}</span>
          <span aria-hidden="true">·</span>
          <span className="等宽">
            {最近年龄 === undefined
              ? t("验证.从未收到")
              : !仿真运行
                ? t("验证.采集已暂停")
                : t("验证.最近更新", { 秒: 最近年龄.toFixed(0) })}
          </span>
          {暂停 ? <标签 语气="强调">{t("验证.暂停中")}</标签> : null}
          {窗口外 > 0 ? <标签 语气="警示">{t("验证.超出窗口", { 条: 窗口外 })}</标签> : null}
        </div>

        {名们.length ? (
          <>
            <div className="mt-2 flex items-center gap-1.5">
              <按钮 尺寸="小" 种类="幽灵" on按下={() => 只显示((名) => 名.includes("目标位置") || 名.includes("实际位置"))}>
                {t("验证.只看轨迹")}
              </按钮>
              <按钮 尺寸="小" 种类="幽灵" on按下={() => 只显示((名) => 名.includes("误差"))}>
                {t("验证.只看误差")}
              </按钮>
              <按钮 尺寸="小" 种类="幽灵" on按下={() => 只显示((名) => 名.includes("力矩") || 名.includes("控制输入"))}>
                {t("验证.只看控制")}
              </按钮>
              <按钮 尺寸="小" 种类="幽灵" on按下={() => 设隐藏(new Set())}>
                {t("验证.全选")}
              </按钮>
              <按钮 尺寸="小" 种类="幽灵" on按下={() => 设隐藏(new Set(名们))}>
                {t("验证.全不选")}
              </按钮>
            </div>
            <div className="mt-1">
              <小表格
                列={图例列}
                行={图例行}
                行键={(r) => String(r.全名)}
                空={t("验证.没有指标")}
              />
            </div>
          </>
        ) : (
          <div className="mt-2 未接入 space-y-1">
            <div>{t("验证.没有指标")}</div>
            <div className="text-[0.85em]">{t("验证.空原因")}</div>
            <按钮 尺寸="小" 种类="幽灵" on按下={() => 请求跳步("插件")}>
              {t("验证.去插件")}
            </按钮>
          </div>
        )}

      </可折叠区块>

      <可折叠区块
        标题={t("验证.参数")}
        徽标={
          <>
            <span className="等宽"> {参数 ? `#${参数帧号}` : ""}</span>
          </>
        }
      >
        <div className="text-dim text-[0.9em]" title={t("验证.参数.说明")}>{t("验证.参数.可编辑")}</div>
        {参数项们.length ? (
          <>
            <div className="mt-2">
              <小表格
                列={参数列}
                行={参数项们.map(([全名, 项]) => 摊开(全名, 项))}
                行键={(r) => String(r.名)}
              />
            </div>
            <div className="mt-1 text-[0.8em] text-dim">{t("验证.参数.编辑说明")}</div>
          </>
        ) : (
          <div className="mt-2 text-dim">{t("验证.参数.空")}</div>
        )}
      </可折叠区块>
    </div>
  );
}
