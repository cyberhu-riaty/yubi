/**
 * ValidateView.tsx —— 任务流第 3 步：实时曲线 + 参数表。
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
import { LineChart, seriesColor } from "../components/Chart";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Button } from "../components/Button";
import { Tag } from "../components/Badge";
import { DataTable, NumericText, formatValue, type TableColumn } from "../components/DataTable";
import { commands, useStore } from "../data/store";
import { useClock } from "../data/clock";
import { requestStepNavigation } from "../shell/step_navigation";
import type { ParameterItem } from "../data/store";
import { showError } from "../data/toasts";
import { useTranslation } from "./i18n";
import { LiveTrackingView } from "./LiveTrackingView";
import { ReferenceComparisonView } from "./ReferenceComparisonView";

/** `s.曲线` 的环形缓冲窗口（`数据/store.ts` 里就是 120 秒） */
const windowSeconds = 120;

function formatNumericText(value?: number): string {
  return value === undefined || !Number.isFinite(value) ? "" : String(value);
}

function ParameterValueEditor({
  fullName: fullName, value: value, min: min, max: max, stepSize: stepSize, saving: saving, submit: submit,
}: {
  fullName: string;
  value?: number;
  min?: number;
  max?: number;
  stepSize?: number;
  saving: boolean;
  submit: (fullName: string, newValue: number) => Promise<boolean>;
}) {
  const t = useTranslation();
  const [draft, setDraft] = useState(() => formatNumericText(value));
  const [focus, setFocus] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const pendingConfirmation = useRef<number | null>(null);

  // 后端回灌：只有"没在编辑 + 没有未提交修改"时才覆盖草稿。
  // 提交成功后先等后端真的回灌这个值，避免被旧帧打回原值。
  useEffect(() => {
    if (pendingConfirmation.current !== null) {
      if (value !== undefined && Math.abs(value - pendingConfirmation.current) <= 1e-9) {
        pendingConfirmation.current = null;
        setDirty(false);
        setError("");
        setDraft(formatNumericText(value));
      }
      return;
    }
    if (!focus && !dirty) {
      setDraft(formatNumericText(value));
      setError("");
    }
  }, [value, focus, dirty]);

  const restore = () => {
    pendingConfirmation.current = null;
    setDraft(formatNumericText(value));
    setDirty(false);
    setError("");
  };

  const submitDraft = async () => {
    const text = draft.trim();
    if (!text) {
      restore();
      return;
    }
    const digit = Number(text);
    if (!Number.isFinite(digit)) {
      setError(t("验证.参数.无效"));
      return;
    }
    if ((min !== undefined && digit < min) || (max !== undefined && digit > max)) {
      setError(t("验证.参数.超范围", {
        min: min ?? "−∞",
        max: max ?? "+∞",
      }));
      return;
    }
    if (value !== undefined && digit === value) {
      setDirty(false);
      setError("");
      setDraft(formatNumericText(digit));
      return;
    }
    setError("");
    const passed = await submit(fullName, digit);
    if (passed) {
      pendingConfirmation.current = digit;
      setDraft(formatNumericText(digit));
      setDirty(true);           // 等后端回灌后再变干净
    } else {
      setError(t("验证.参数.未接受"));
    }
  };

  return (
    <span className="parameter-cell">
      <input
        type="text"
        inputMode="decimal"
        autoComplete="off"
        spellCheck={false}
        className="parameter-input"
        aria-label={`${fullName} ${t("验证.参数.值")}`}
        aria-invalid={!!error}
        data-error={error ? "true" : undefined}
        data-dirty={dirty && !error ? "true" : undefined}
        value={draft}
        disabled={saving}
        title={[
          fullName,
          min !== undefined || max !== undefined
            ? t("验证.参数.范围提示", { min: min ?? "−∞", max: max ?? "+∞" })
            : "",
          stepSize ? `步长 ${stepSize}` : "",
          t("验证.参数.编辑提示"),
        ].filter(Boolean).join("\n")}
        onFocus={() => setFocus(true)}
        onBlur={() => {
          setFocus(false);
          if (dirty) void submitDraft();
        }}
        onChange={(e) => {
          setDraft(e.target.value);
          setDirty(true);
          setError("");
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (dirty) void submitDraft();
          } else if (e.key === "Escape") {
            e.preventDefault();
            restore();
          }
        }}
      />
      {error ? <span className="parameter-error" title={error} aria-hidden="true">!</span> : null}
      {saving ? <span className="parameter-save" aria-hidden="true">…</span> : null}
    </span>
  );
}

export function ValidateView() {
  const currentExperiment = useStore((s) => s.experiment.data?.current ?? "");
  const referenceMode = currentExperiment === "ur10_reference_replay";
  const t = useTranslation();
  const chartCount = useStore((s) => s.charts);
  const parameters = useStore((s) => s.parameters.data);
  const parameterFrameId = useStore((s) => s.parameters.frameId);
  const simulationRunning = useStore((s) => s.simulation.data?.state === "running");
  const trackingActive = useStore((s) => !!s.liveTracking.experimentName);
  const tick = useClock();

  const names = useMemo(() => Object.keys(chartCount).sort(), [chartCount]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [paused, setPaused] = useState(false);

  // 曲线停在最后一个真实指标点；“多少秒前”只用本地时钟更新文字，
  // 不会为了让横轴移动而伪造重复数据点。
  const latestTime = useMemo(() => {
    let latest = 0;
    for (const n of names) {
      const point = chartCount[n];
      if (point?.length) latest = Math.max(latest, point[point.length - 1].t);
    }
    return latest;
  }, [names, chartCount]);
  const latestAge = latestTime ? Math.max(0, tick / 1000 - latestTime) : undefined;

  const outsideWindow = latestTime
    ? names.filter((n) => {
        const point = chartCount[n];
        return point?.length ? point[point.length - 1].t < latestTime - 1 : false;
      }).length
    : 0;

  const visible = useMemo(() => new Set(names.filter((n) => !hidden.has(n))), [names, hidden]);

  const toggle = (name: string) => {
    setHidden((previous) => {
      const updated = new Set(previous);
      if (updated.has(name)) updated.delete(name);
      else updated.add(name);
      return updated;
    });
  };

  /** 演示时一键切到同类曲线，避免角度、误差和力矩混在同一纵轴。 */
  const onlyVisible = (verdict: (name: string) => boolean) => {
    setHidden(new Set(names.filter((name) => !verdict(name))));
  };

  const legendRow: Record<string, unknown>[] = names.map((name) => {
    const point = chartCount[name];
    const last = point?.[point.length - 1];
    let peak = -Infinity;
    for (const p of point ?? []) if (p.v > peak) peak = p.v;
    return { name, value: last?.v, peak: Number.isFinite(peak) ? peak : undefined, pointCount: point?.length ?? 0 };
  });

  const legendColumns: TableColumn[] = [
    {
      title: t("验证.选中"),
      width: "w-[3.4em]",
      render: (row) => {
        const name = String(row.name);
        return (
          <input
            type="checkbox"
            checked={!hidden.has(name)}
            onChange={() => toggle(name)}
            aria-label={`${t("验证.选中")} ${name}`}
            // 复选框、图例短线和画布曲线使用同一个稳定颜色，便于快速核对。
            style={{ accentColor: seriesColor(names.indexOf(name)) }}
          />
        );
      },
    },
    {
      title: t("验证.曲线名"),
      // 给足宽度，否则长名字会被压成一竖条；配合下面的 `truncate` 用省略号收尾
      width: "w-[22ch] max-w-[22ch]",
      render: (row) => {
        const name = String(row.name);
        const order = names.indexOf(name);
        return (
          <span className="flex min-w-0 items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-[3px] w-3 flex-none"
              style={{ background: seriesColor(order) }}
            />
            {/* ★ 曲线名要 `whitespace-nowrap`：它是「插件名·指标名」，本来就很长。
                之前用 `break-all` 在窄列里会**逐字换行**成一竖条（一行一个字），
                表格被撑成一条细长竖线 —— 实测截图里就是这样，能读但极难用。
                名称本来就可能超宽，所以让它不折行 + 溢出省略，完整名字放进 title。 */}
            <span className="truncate" title={name}>
              {name}
            </span>
          </span>
        );
      },
    },
    {
      title: t("验证.当前值"),
      numeric: true,
      render: (row) => <NumericText value={row.value as number | undefined} digits={4} />,
    },
    { title: t("验证.峰"), numeric: true, render: (row) => <NumericText value={row.peak as number | undefined} digits={4} /> },
    { title: t("验证.点数"), numeric: true, render: (row) => <span className="monospace">{String(row.pointCount ?? "")}</span> },
  ];

  // ★ `parameter.table` 的负载形状是 `{parameters: {full_name: item}}`。
  //   在**一个地方**解包，别让下面每处都记得多剥一层 ——
  //   实测踩过：少剥这一层会把 `参数` 这个包装键当成插件名，
  //   表格里出现 `值/单位/参数/插件/…` 一堆 `--` 行，看起来像"后端没报数据"。
  const parameterItems: [string, ParameterItem][] = useMemo(() => {
    const raw = (parameters as unknown as { parameters?: Record<string, ParameterItem> } | null)?.parameters;
    if (!raw || typeof raw !== "object") return [];
    return Object.keys(raw).sort().map((fullName) => [fullName, raw[fullName] ?? {}]);
  }, [parameters]);

  // ★ 参数项的真实形状来自 `parameter_bridge.collect_parameters()`：
  //     {plugin, plugin_english, plugin_version, parameter, value, range, step, unit}
  //   早先这里按 `{值, 最小, 最大}` 渲染 —— 那是**按想象写的**，与实现不符，
  //   后果是 `范围`（一个数组）被当成对象逐字符渲染，表格里出现一堆 `0=N 1=·` 的乱码。
  const rangeEdge = (item: ParameterItem, endpoint: 0 | 1): number | undefined => {
    const r = item.range;
    return Array.isArray(r) && typeof r[endpoint] === "number" ? (r[endpoint] as number) : undefined;
  };

  // 改参数：**显式提交**（Enter / 失焦），不再每敲一个字符就发一条命令。
  // 旧实现把后端当前值直接绑在 input.value 上，onChange 立刻发命令并等回执；
  // 结果"1"还没打完就被后端回灌成原值，小数点/负号也经常打不进去。
  const [editing, setEditing] = useState<string | null>(null);
  async function submitParameters(fullName: string, newValue: number): Promise<boolean> {
    if (editing !== null) return false;
    setEditing(fullName);
    try {
      const receipt = await commands.updateParameters({ [fullName]: newValue });
      if (!receipt.passed) {
        showError(receipt.description);
        return false;
      }
      return true;
    } catch (error) {
      showError(`改参数失败：${String(error)}`);
      return false;
    } finally {
      setEditing(null);
    }
  }

  const parameterColumn: TableColumn[] = [
    {
      title: t("验证.参数.名"),
      width: "w-[20ch] max-w-[20ch]",
      render: (row) => {
        // 显示用「插件中文名·参数中文标签」；命令仍用 fullName 里的英文机器键。
        const plugin = String(row.plugin ?? "");
        const label = String((row as unknown as ParameterItem).label || row.name || "");
        return (
          <span className="block truncate" title={String(row.fullName)}>
            {plugin ? `${plugin}·${label}` : label}
          </span>
        );
      },
    },
    {
      title: t("验证.参数.值"),
      numeric: true,
      render: (row) => {
        // ★ 必须用 `行.全名`（「插件名·参数名」），**不是** `行.名`（短名）。
        //   后端 `parameter_bridge` 按完整名称中的分隔符拆出插件名并查找实例：
        //   发短名（KD）会拆不出插件 → 实例找不到 → 命令被静默忽略，
        //   界面看起来就是"改了没用"。实测踩过，而且因为回执是"已接受"，
        //   现象上极像"编辑功能没实现"。
        const fullName = String(row.fullName ?? row.name);
        const value = row.value as number | undefined;
        const min = rangeEdge(row as unknown as ParameterItem, 0);
        const max = rangeEdge(row as unknown as ParameterItem, 1);
        const step = (row as unknown as ParameterItem).step;
        return (
          <ParameterValueEditor
            fullName={fullName}
            value={value}
            min={min}
            max={max}
            stepSize={typeof step === "number" ? step : undefined}
            saving={editing === fullName}
            submit={submitParameters}
          />
        );
      },
    },
    {
      title: t("验证.参数.最小"),
      numeric: true,
      render: (row) => <NumericText value={rangeEdge(row as unknown as ParameterItem, 0)} digits={6} />,
    },
    {
      title: t("验证.参数.最大"),
      numeric: true,
      render: (row) => <NumericText value={rangeEdge(row as unknown as ParameterItem, 1)} digits={6} />,
    },
    {
      title: t("验证.参数.单位"),
      render: (row) => <span className="monospace text-dim">{String(row.unit ?? "") || "—"}</span>,
    },
  ];

  /**
   * 把一个参数项摊成一行。字段名与后端一致，多余键原样附在后面（不丢信息）。
   * `全名` 形如「插件名·参数名」——插件名从它取（后端也单独给了 `插件` 字段，优先用它）。
   */
  function flattened(fullName: string, item: ParameterItem): Record<string, unknown> {
    const plugins = String(item.plugin ?? fullName.split("·")[0] ?? "");
    const name = String(item.parameter ?? fullName.split("·")[1] ?? fullName);
    const known = ["plugin", "plugin_id", "plugin_english", "plugin_version", "parameter", "label",
      "value", "range", "step", "unit"];
    const extra = Object.keys(item).filter((k) => !known.includes(k));
    const range = item.range;
    const min = Array.isArray(range) && typeof range[0] === "number" ? range[0] : undefined;
    const max = Array.isArray(range) && typeof range[1] === "number" ? range[1] : undefined;
    return {
      fullName: fullName,
      plugin: plugins,
      name: name,
      label: item.label,
      value: item.value,
      min: min,
      max: max,
      unit: item.unit,
      step: item.step,
      range: range,
      description: extra.length ? extra.map((k) => `${k}=${formatValue(item[k])}`).join(" ") : undefined,
    };
  }

  return (
    <div>
      {trackingActive ? (referenceMode ? <ReferenceComparisonView /> : <LiveTrackingView />) : null}
      <CollapsibleSection
        key={trackingActive ? "experiment-metrics" : "plugin-metrics"}
        title={t("验证.曲线")}
        defaultOpen={!trackingActive}
        badge={
          <span className="monospace">
            {names.length ? `${names.length} · ${windowSeconds}s` : ""}
          </span>
        }
      >
        <div className="panel" title={t("验证.曲线.说明")} style={{ background: "var(--plot-bg)", borderRadius: "var(--radius)" }}>
          <LineChart data={chartCount} visible={visible} windowSeconds={windowSeconds} height={190} onPausedChange={setPaused} />
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1 text-[0.85em] text-dim">
          <span className="flex-none">{t("验证.窗口.标签")}</span>
          <span className="monospace">{t("验证.窗口.值", { value: windowSeconds })}</span>
          <span aria-hidden="true">·</span>
          <span>{t("曲线.轴时间")}</span>
          <span aria-hidden="true">·</span>
          <span className="monospace">
            {latestAge === undefined
              ? t("验证.从未收到")
              : !simulationRunning
                ? t("验证.采集已暂停")
                : t("验证.最近更新", { seconds: latestAge.toFixed(0) })}
          </span>
          {paused ? <Tag tone="emphasis">{t("验证.暂停中")}</Tag> : null}
          {outsideWindow > 0 ? <Tag tone="notice">{t("验证.超出窗口", { count: outsideWindow })}</Tag> : null}
        </div>

        {names.length ? (
          <>
            <div className="mt-2 flex items-center gap-1.5">
              <Button size="small" variant="ghost" onPress={() => onlyVisible((name) => name.includes("目标位置") || name.includes("实际位置"))}>
                {t("验证.只看轨迹")}
              </Button>
              <Button size="small" variant="ghost" onPress={() => onlyVisible((name) => name.includes("误差"))}>
                {t("验证.只看误差")}
              </Button>
              <Button size="small" variant="ghost" onPress={() => onlyVisible((name) => name.includes("力矩") || name.includes("控制输入"))}>
                {t("验证.只看控制")}
              </Button>
              <Button size="small" variant="ghost" onPress={() => setHidden(new Set())}>
                {t("验证.全选")}
              </Button>
              <Button size="small" variant="ghost" onPress={() => setHidden(new Set(names))}>
                {t("验证.全不选")}
              </Button>
            </div>
            <div className="mt-1">
              <DataTable
                columns={legendColumns}
                rows={legendRow}
                rowKey={(r) => String(r.fullName)}
                emptyText={t("验证.没有指标")}
              />
            </div>
          </>
        ) : (
          <div className="mt-2 unavailable space-y-1">
            <div>{t("验证.没有指标")}</div>
            <div className="text-[0.85em]">{t("验证.空原因")}</div>
            <Button size="small" variant="ghost" onPress={() => requestStepNavigation("插件")}>
              {t("验证.去插件")}
            </Button>
          </div>
        )}

      </CollapsibleSection>

      <CollapsibleSection
        title={t("验证.参数")}
        badge={
          <>
            <span className="monospace"> {parameters ? `#${parameterFrameId}` : ""}</span>
          </>
        }
      >
        <div className="text-dim text-[0.9em]" title={t("验证.参数.说明")}>{t("验证.参数.可编辑")}</div>
        {parameterItems.length ? (
          <>
            <div className="mt-2">
              <DataTable
                columns={parameterColumn}
                rows={parameterItems.map(([fullName, item]) => flattened(fullName, item))}
                rowKey={(r) => String(r.name)}
              />
            </div>
            <div className="mt-1 text-[0.8em] text-dim">{t("验证.参数.编辑说明")}</div>
          </>
        ) : (
          <div className="mt-2 text-dim">{t("验证.参数.空")}</div>
        )}
      </CollapsibleSection>
    </div>
  );
}
