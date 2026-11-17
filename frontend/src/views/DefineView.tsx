/**
 * DefineView.tsx —— 任务流第 1 步：模型 / 项目 / 资产库。
 *
 * 诚实边界（这一格最容易造假，所以先写清楚）：
 *   · 资产库**已是真清单**：数据来自契约里的「资产库」主题（后端读 `model_manifest.json` 生成的模型库索引），
 *     点一台就发 `command.model`。
 *   · **路径不手写**：路径由后端给，界面不拼、不猜；长路径只显示文件名 + 上级目录，
 *     完整路径放 title，并提供复制。
 *   · 兼容性提示**只从 `项目状态.报告` 推**，报告里没有「不兼容」就不画警告；
 *     不猜"应该兼容"，也不把报告里的长文原样铺满整屏。
 *   · 换模型走"发出 → 等回执 → 写控制台 + 提示"，不搞"点了就算成功"。
 *
 * 布局取舍（响应工程师的"左栏太挤"）：
 *   · 模型、项目两块默认展开；资产库/算法库/换模型默认收起。
 *   · 装配报告是 `<details>`，默认收起；顶部兼容性提示只显示结论与下一步。
 *   · 模型/项目字段用两列表格；长路径、长状态截断并提供完整内容。
 */
import { useEffect, useState } from "react";
import { ValueTable, formatValue, type ValueRow } from "../components/DataTable";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Button } from "../components/Button";
import { Tag } from "../components/Badge";
import { PathValue } from "../components/PathValue";
import { commands, useStore } from "../data/store";
import { finishCommand, recordCommandStart, logWarning } from "../data/logs";
import type { CommandReceipt } from "../data/connection";
import { useTranslation } from "./i18n";

/** 从 `算法` 那一列里取一个字段（后端给的是 `Record<string, unknown>[]`，形状由插件定） */
function getField(item: Record<string, unknown>, name: string): unknown {
  return item[name];
}

/** 模型状态：好/坏/未知都用「符号 + 文字」表达，颜色只是辅助 */
function ModelState({ state: state }: { state?: string }) {
  if (!state) return <span className="text-dim">--</span>;
  const invalid = /^✗|失败|错误|不可用/.test(state);
  const valid = /^✓|就绪|已切换|已加载/.test(state);
  const tone = invalid ? "var(--danger)" : valid ? "var(--ok)" : "var(--fg)";
  const symbol = invalid ? "✗" : valid ? "✓" : "•";
  // 后端的状态串自己可能已经带 ✓/✗；先剥掉再统一加一次，避免出现「✓ ✓ 就绪」。
  const bodyText = state.replace(/^\s*[✓✗•]\s*/, "");
  return (
    <span className="状态文本 flex min-w-0 items-center justify-end gap-1" style={{ color: tone }} title={state}>
      <span aria-hidden="true" className="flex-none">{symbol}</span>
      <span className="min-w-0 whitespace-normal break-all">{bodyText}</span>
    </span>
  );
}

/** 顶部的兼容性提示：只显示报告里真的写了「不兼容」的行 */
function CompatibilityHint({ rows: rows, onInspect: onInspect }: { rows: string[]; onInspect: () => void }) {
  const t = useTranslation();
  return (
    <div className="compatibility-bar" role="alert">
      <div className="flex flex-wrap items-center gap-1.5">
        <Tag tone="warning">! {t("定义.兼容性")}</Tag>
        <span className="compatibility-title">{t("定义.兼容性.标题")}</span>
      </div>
      <ul className="mt-1.5 space-y-0.5 text-[0.82em]">
        {rows.map((row) => (
          <li key={row} className="break-all">
            {row.replace(/^[-·]\s*/, "")}
          </li>
        ))}
      </ul>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.8em] text-dim">
        <span>{t("定义.兼容性.影响")}</span>
        <span aria-hidden="true">·</span>
        <span>{t("定义.兼容性.下一步")}</span>
      </div>
      <div className="mt-1.5">
        <Button size="small" variant="ghost" onPress={onInspect}>
          {t("定义.兼容性.查看")}
        </Button>
      </div>
    </div>
  );
}

export function DefineView() {
  const t = useTranslation();
  const model = useStore((s) => s.model.data);
  const modelFrameId = useStore((s) => s.model.frameId);
  const assets = useStore((s) => s.assets.data);
  const project = useStore((s) => s.project.data);
  const pluginCatalog = useStore((s) => s.plugins.data);
  const pluginFrameId = useStore((s) => s.plugins.frameId);
  const control = useStore((s) => s.control.data);
  const connectionState = useStore((s) => s.connection);

  const [path, setPath] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [algorithmsBusy, setAlgorithmsBusy] = useState<"应用" | "保存" | null>(null);
  const [ReceiptBar, setReceipt] = useState<CommandReceipt | null>(null);
  const [algorithmReceipt, setAlgorithmReceipt] = useState<CommandReceipt | null>(null);
  const [targetReceipt, setTargetReceipt] = useState<CommandReceipt | null>(null);
  const [targetBusy, setTargetBusy] = useState(false);
  const [targetDraft, setTargetDraft] = useState<string[]>([]);
  const [reportOpen, setReportOpen] = useState(false);
  // 定义页采用固定式手风琴：区块标题始终可见，一次只展开一个内容区。
  // 内容较长时只在展开区内部滚动，避免整个“定义”页面上下移动。
  type DefinitionSection = "模型" | "项目" | "控制" | "资产" | "算法" | "换模型";
  const [currentSection, setCurrentSection] = useState<DefinitionSection | null>("模型");
  const controlSection = (section: DefinitionSection) => ({
    open: currentSection === section,
    onOpenChange: (open: boolean) => {
      setCurrentSection(open ? section : null);
    },
  });

  const backendTargetKey = (control?.target ?? []).join("|");
  useEffect(() => {
    setTargetDraft((control?.target ?? []).map((value) => Number(value).toFixed(4)));
  }, [backendTargetKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const useCurrentPosition = () => {
    setTargetDraft((control?.current_position ?? []).map((value) => Number(value).toFixed(4)));
  };

  const submitControlTarget = async () => {
    const values = targetDraft.map((value) => Number(value));
    if (!values.length || values.some((value) => !Number.isFinite(value))) {
      logWarning("console", t("定义.控制目标.数值错误"));
      return;
    }
    setTargetBusy(true);
    try {
      const startedAt = recordCommandStart();
      const r = finishCommand("命令.控制目标", await commands.setControlTarget(values), startedAt,
        { module: "定义·关节目标" });
      setTargetReceipt(r);
    } finally {
      setTargetBusy(false);
    }
  };

  // ★ GUI → MuJoCo 的算法配置先放在本地「待选集」里；只有点应用/保存才发给后端。
  //   这里以插件模块名为准，显示名只用于给人看，避免把显示名误当成文件名。
  const pluginItems = pluginCatalog?.plugins ?? [];
  const activeOrder = pluginItems.filter((item) => item.enabled && item.plugin).map((item) => item.plugin as string);
  const [pendingSelection, setPendingSelection] = useState<Set<string>>(() => new Set());

  // ★ MuJoCo → GUI：后端完成装配后会重发插件目录；这时才同步真实生效结果。
  //   必须依赖帧号而不只比较名称：不兼容算法被跳过时，名称集合可能没变，
  //   但这份新帧仍代表后端已经给出了权威结果，应撤掉未成功的勾选。
  useEffect(() => {
    setPendingSelection(new Set(activeOrder));
  }, [pluginFrameId]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeSet = new Set(activeOrder);
  const pendingOrder = pluginItems.flatMap((item) => item.plugin && pendingSelection.has(item.plugin) ? [item.plugin] : []);
  const algorithmsChanged = pluginItems.some((item) => {
    const name = item.plugin ?? "";
    return !!name && pendingSelection.has(name) !== activeSet.has(name);
  });

  const updateSelection = (name: string, selected: boolean) => {
    setPendingSelection((previous) => {
      const updated = new Set(previous);
      if (selected) updated.add(name);
      else updated.delete(name);
      return updated;
    });
  };

  const submitAlgorithms = async (saved: boolean) => {
    const action = saved ? "保存" : "应用";
    setAlgorithmsBusy(action);
    try {
      const startedAt = recordCommandStart();
      // 没有选择变化、只是把已经临时应用的结果存盘时，不重置机器人姿态。
      const r = finishCommand(
        "command.algorithms",
        await commands.applyAlgorithms(pendingOrder, saved, algorithmsChanged),
        startedAt,
        { module: `定义·${action}` },
      );
      setAlgorithmReceipt(r);
    } finally {
      setAlgorithmsBusy(null);
    }
  };

  /**
   * 发一次换模型。
   * ★ 抽成带参数的函数，让"手填路径"和"点资产库"走**同一条路** ——
   *   否则两条路迟早一条有回执、一条没有。
   */
  const requestModelChange = async (targetPath: string, targetDisplayName = "") => {
    setBusy(true);
    try {
      const startedAt = recordCommandStart();
      const r = finishCommand("command.model", await commands.switchModel(targetPath, targetDisplayName), startedAt);
      setReceipt(r);
    } finally {
      setBusy(false);
    }
  };

  const submitModelChange = async () => {
    const clean = path.trim();
    if (!clean) {
      logWarning("console", t("定义.换模型.要路径"));
      return;
    }
    await requestModelChange(clean, displayName.trim());
  };

  // 资产库列表：后端没报就空数组（不画假条目）
  const manifest = assets?.models ?? [];

  // 兼容性只从装配报告里取，报告没写就不画警告
  const incompatibilityRow = (project?.report ?? []).filter((row) => row.includes("不兼容"));
  const openReport = () => {
    setCurrentSection("项目");
    setReportOpen(true);
    window.setTimeout(() => {
      document.getElementById("装配报告")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, 0);
  };

  const modelRow: ValueRow[] = model
    ? [
        { key: t("定义.模型显示名"), value: model.current_display_name || t("通用.无"), plainText: model.current_display_name },
        {
          key: t("定义.模型路径"),
          value: <PathValue path={model.current_path} />,
          plainText: model.current_path,
        },
        {
          key: t("定义.自由度"),
          value: <span className="monospace">{model.dof ?? "--"}</span>,
          hint: t("定义.自由度.提示"),
        },
        {
          key: t("定义.执行器数"),
          value: <span className="monospace">{model.actuator_count ?? "--"}</span>,
          hint: t("定义.执行器数.提示"),
        },
        {
          key: t("定义.模型状态"),
          value: <ModelState state={model.status} />,
          plainText: model.status,
        },
        {
          key: t("定义.加载耗时"),
          value: <span className="monospace">{model.duration_s === undefined ? "--" : `${model.duration_s.toFixed(3)} s`}</span>,
        },
      ]
    : [];

  const projectRow: ValueRow[] = project
    ? [
        { key: t("定义.项目名"), value: project.project || t("通用.无"), plainText: project.project },
        { key: t("定义.算法数"), value: <span className="monospace">{project.algorithms?.length ?? 0}</span> },
        { key: t("定义.控盘"), value: project.active_controller || t("通用.无"), plainText: project.active_controller },
        {
          key: t("定义.被覆盖"),
          value: project.overridden_controllers?.length ? project.overridden_controllers.join(" / ") : t("通用.无"),
          plainText: project.overridden_controllers?.join(" / "),
        },
        {
          key: t("定义.已存盘"),
          value: project.saved === undefined ? "--" : project.saved ? t("通用.是") : t("通用.否"),
        },
      ]
    : [];

  const noAlgorithms = (project?.algorithms?.length ?? 0) === 0;

  return (
    <div className="define-page-fixed">
      {incompatibilityRow.length ? <CompatibilityHint rows={incompatibilityRow} onInspect={openReport} /> : null}

      <CollapsibleSection
        title={t("定义.当前模型")}
        {...controlSection("模型")}
        badge={
          model ? (
            <span className="flex items-center gap-1.5">
              {model.dof !== undefined && model.actuator_count !== undefined && model.dof !== model.actuator_count ? (
                <Tag tone="warning" title={t("定义.nqnu.说明")}>! nq≠nu</Tag>
              ) : null}
              <span className="monospace">{model.dof === undefined ? "" : `${model.dof} DoF`}</span>
            </span>
          ) : (
            <Tag tone="notice">{t("通用.未接入")}</Tag>
          )
        }
      >
        {model ? (
          <>
            <ValueTable rows={modelRow} />
            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.78em] text-dim">
              <span>{t("定义.nqnu.说明")}</span>
              <span className="monospace">#{modelFrameId}</span>
            </div>
            <div className="mt-0.5 text-[0.78em] text-dim">{t("定义.单位.说明")}</div>
          </>
        ) : (
          <div className="text-dim">{t("定义.没模型")}</div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={t("定义.当前项目")}
        {...controlSection("项目")}
        badge={
          <span className="flex items-center gap-1.5">
            {incompatibilityRow.length ? (
              <Tag tone="warning">! {t("定义.兼容性")}</Tag>
            ) : noAlgorithms ? (
              <Tag tone="neutral">{t("定义.兼容性.未评估")}</Tag>
            ) : project?.report?.length ? (
              <Tag tone="success">✓ {t("定义.兼容性.通过")}</Tag>
            ) : null}
            <span className="monospace text-[0.78em] text-dim" title={t("定义.算法数")}>
              {project ? t("定义.算法数.短", { count: project.algorithms?.length ?? 0 }) : ""}
            </span>
          </span>
        }
      >
        {project ? (
          <>
            <ValueTable rows={projectRow} />

            {noAlgorithms ? (
              <div className="mt-2 rounded border border-dashed px-2 py-1.5 text-[0.8em] text-dim" style={{ borderColor: "var(--border-strong)" }}>
                <div>{t("定义.算法.未添加说明")}</div>
              </div>
            ) : null}

            {project.algorithms?.length ? (
              <ul className="mt-2 space-y-1">
                {project.algorithms.map((a, i) => {
                  const name = formatValue(getField(a, "名称") ?? getField(a, "插件"));
                  const version = formatValue(getField(a, "版本"));
                  const incompatible = incompatibilityRow.some((row) => name && row.includes(name));
                  return (
                    <li key={i} className="algorithm-item">
                      <span className="algorithm-name">{name}</span>
                      {version !== "--" ? <span className="algorithm-version monospace text-dim">v{version}</span> : null}
                      {getField(a, "接管控制") ? <Tag tone="emphasis">{t("定义.控盘")}</Tag> : null}
                      {incompatible ? <Tag tone="warning">! {t("定义.算法状态.不兼容")}</Tag> : null}
                    </li>
                  );
                })}
              </ul>
            ) : null}

            <details
              id="装配报告"
              className="assembly-details mt-2"
              open={reportOpen}
              onToggle={(e) => setReportOpen(e.currentTarget.open)}
            >
              <summary>{t("定义.装配报告")}（{project.report?.length ?? 0}）</summary>
              {project.report?.length ? (
                <ul className="mt-1 space-y-0.5 monospace text-[0.82em]">
                  {project.report.map((row, i) => (
                    <li key={i} className="break-all">
                      {row}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="mt-1 text-dim">{t("定义.装配报告.空")}</div>
              )}
            </details>
          </>
        ) : (
          <div className="text-dim">{t("定义.没项目")}</div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={t("定义.控制目标")}
        {...controlSection("控制")}
        badge={
          <span className="flex items-center gap-1.5">
            <span className="monospace text-[0.78em]">{control?.joint_names?.length ?? 0} DoF</span>
            {project?.active_controller ? <Tag tone="success">{project.active_controller}</Tag> : <Tag tone="warning">{t("定义.控制目标.无算法")}</Tag>}
          </span>
        }
      >
        {control?.joint_names?.length ? (
          <>
            <div className="mb-2 text-[0.8em] text-dim">
              {t("定义.控制目标.说明")} · {t("定义.控制目标.来源", { source: control.target_source ?? "--" })}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[0.82em]">
                <thead>
                  <tr>
                    <th className="border-b px-1 py-1 text-left font-normal text-dim">{t("定义.控制目标.关节")}</th>
                    <th className="border-b px-1 py-1 text-right font-normal text-dim">{t("定义.控制目标.当前位置")}</th>
                    <th className="border-b px-1 py-1 text-right font-normal text-dim">{t("定义.控制目标.目标")}</th>
                  </tr>
                </thead>
                <tbody>
                  {control.joint_names.map((name, i) => (
                    <tr key={`${name}-${i}`}>
                      <td className="border-b px-1 py-1 truncate" title={name}>{name}</td>
                      <td className="border-b px-1 py-1 text-right monospace">{control.current_position?.[i]?.toFixed(4) ?? "--"}</td>
                      <td className="border-b px-1 py-1 text-right">
                        <input
                          className="input monospace w-[7.5em] text-right"
                          type="number"
                          step="0.01"
                          value={targetDraft[i] ?? ""}
                          aria-label={`${name} ${t("定义.控制目标.目标")}`}
                          onChange={(e) => setTargetDraft((previous) => {
                            const updated = [...previous];
                            updated[i] = e.target.value;
                            return updated;
                          })}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Button size="small" variant="secondary" onPress={useCurrentPosition}>{t("定义.控制目标.取当前")}</Button>
              <Button
                size="small"
                variant="primary"
                disabled={targetBusy || connectionState !== "connected" || targetDraft.length !== control.joint_names.length}
                onPress={() => void submitControlTarget()}
              >
                {targetBusy ? "…" : t("定义.控制目标.应用")}
              </Button>
              <span className="text-[0.78em] text-dim">{control.description}</span>
            </div>
            {targetReceipt ? (
              <div className="mt-1 text-[0.8em] monospace" style={{ color: targetReceipt.passed ? "var(--ok)" : "var(--danger)" }}>
                {targetReceipt.passed ? "✓" : "✗"} {targetReceipt.description || t("日志.无说明")}
              </div>
            ) : null}
          </>
        ) : (
          <div className="text-dim">{t("定义.控制目标.无关节")}</div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={t("定义.资产库")}
        {...controlSection("资产")}
        badge={
          assets?.count ? (
            <Tag>{assets.count}</Tag>
          ) : (
            <Tag tone="notice">{t("通用.待接入")}</Tag>
          )
        }
      >
        {manifest.length ? (
          <ul className="space-y-1">
            {manifest.map((item) => {
              const isCurrent = !!item.path && item.path === model?.current_path;
              return (
                <li key={item.id ?? item.path}>
                  <Button
                    variant="secondary"
                    size="small"
                    className="w-full"
                    disabled={busy || isCurrent}
                    title={isCurrent ? t("定义.资产库.带星") : t("定义.资产库.点选", { name: item.display_name ?? "?" })}
                    onPress={() => {
                      if (!item.path) return;
                      void requestModelChange(item.path, item.display_name ?? "");
                    }}
                  >
                    <span className="flex w-full items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-left">
                        {item.display_name || item.id || "?"}
                      </span>
                      <span className="flex-none text-[0.85em] text-dim monospace">
                        {`${item.dof ?? "--"} DoF`}
                      </span>
                      <span className="hidden w-[86px] flex-none truncate text-right text-[0.8em] text-dim sm:inline">
                        {item.license ?? ""}
                      </span>
                      {isCurrent ? <Tag>{t("定义.资产库.带星")}</Tag> : null}
                    </span>
                  </Button>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="mt-2 text-dim">{t("定义.资产库.空")}</div>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={t("定义.算法库")}
        {...controlSection("算法")}
        badge={
          <span className="flex items-center gap-1.5">
            {algorithmsChanged ? <Tag tone="warning">{t("定义.算法库.待应用")}</Tag> : null}
            {project?.saved === false ? <Tag tone="emphasis">{t("定义.算法库.未保存")}</Tag> : null}
            <span className="monospace">{pluginItems.length || ""}</span>
          </span>
        }
      >
        <div className="text-[0.82em] text-dim">{t("定义.算法库.说明")}</div>
        {pluginItems.length ? (
          <>
            <ul className="mt-2 space-y-1">
              {pluginItems.map((item) => {
                const name = item.plugin ?? "";
                const applied = activeSet.has(name);
                const selected = pendingSelection.has(name);
                const pendingEnable = selected && !applied;
                const pendingDisable = !selected && applied;
                const displayName = item.name || name;
                const incompatible = incompatibilityRow.some((row) => row.includes(displayName) || (!!name && row.includes(name)));
                return (
                  <li key={name} className="panel p-2">
                    <label className="flex cursor-pointer items-start gap-2">
                      <input
                        type="checkbox"
                        className="mt-0.5 flex-none accent-[var(--accent)]"
                        checked={selected}
                        disabled={!!algorithmsBusy || connectionState !== "connected"}
                        onChange={(e) => updateSelection(name, e.target.checked)}
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-1.5">
                          <span className="break-all font-semibold">{displayName}</span>
                          {item.version ? <span className="monospace text-[0.8em] text-dim">v{item.version}</span> : null}
                          {applied ? <Tag tone="success">{t("定义.算法库.已生效")}</Tag> : null}
                          {pendingEnable ? <Tag tone="warning">{t("定义.算法库.待启用")}</Tag> : null}
                          {pendingDisable ? <Tag tone="warning">{t("定义.算法库.待停用")}</Tag> : null}
                          {incompatible ? <Tag tone="error">! {t("定义.算法状态.不兼容")}</Tag> : null}
                        </span>
                        <span className="mt-0.5 block break-all text-[0.8em] text-dim">
                          {[item.group, name && name !== displayName ? name : ""].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>

            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Button
                variant="primary"
                size="small"
                disabled={!!algorithmsBusy || connectionState !== "connected" || !algorithmsChanged}
                title={t("定义.算法库.临时应用说明")}
                onPress={() => void submitAlgorithms(false)}
              >
                {algorithmsBusy === "应用" ? "…" : t("定义.算法库.临时应用")}
              </Button>
              <Button
                variant="secondary"
                size="small"
                disabled={
                  !!algorithmsBusy
                  || connectionState !== "connected"
                  || !project?.project
                  || (!algorithmsChanged && project.saved !== false)
                }
                title={!project?.project ? t("定义.算法库.无项目不能保存") : t("定义.算法库.保存说明")}
                onPress={() => void submitAlgorithms(true)}
              >
                {algorithmsBusy === "保存"
                  ? "…"
                  : algorithmsChanged
                    ? t("定义.算法库.保存并应用")
                    : t("定义.算法库.保存")}
              </Button>
              {algorithmsChanged ? (
                <Button size="small" variant="ghost" disabled={!!algorithmsBusy} onPress={() => setPendingSelection(new Set(activeOrder))}>
                  {t("定义.算法库.恢复")}
                </Button>
              ) : null}
            </div>

            <div className="mt-1.5 text-[0.8em] text-dim">
              {algorithmsChanged
                ? t("定义.算法库.待应用说明")
                : project?.saved === false
                  ? t("定义.算法库.未保存说明")
                  : t("定义.算法库.已同步说明")}
            </div>
            {algorithmReceipt ? (
              <div className="mt-1 text-[0.82em]" style={{ color: algorithmReceipt.passed ? "var(--ok)" : "var(--danger)" }}>
                <span className="monospace">
                  {algorithmReceipt.passed ? "✓" : "✗"} {algorithmReceipt.description || t("日志.无说明")}
                </span>
              </div>
            ) : null}
          </>
        ) : (
          <div className="text-dim">{t("定义.算法库.空")}</div>
        )}
      </CollapsibleSection>

      <CollapsibleSection title={t("定义.换模型")} {...controlSection("换模型")}>
        <div className="space-y-2">
          <label className="block">
            <span className="text-dim">{t("定义.换模型.路径")}</span>
            <input
              className="input mt-0.5 monospace"
              value={path}
              spellCheck={false}
              placeholder={t("定义.换模型.例子")}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitModelChange();
              }}
            />
          </label>
          <label className="block">
            <span className="text-dim">{t("定义.换模型.显示名")}</span>
            <input
              className="input mt-0.5"
              value={displayName}
              spellCheck={false}
              onChange={(e) => setDisplayName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitModelChange();
              }}
            />
          </label>
          <Button variant="primary" size="medium" disabled={busy || !path.trim()} title={t("定义.换模型.说明")} onPress={() => void submitModelChange()}>
            {busy ? "…" : t("定义.换模型.提交")}
          </Button>
          {ReceiptBar ? (
            <div className="text-[0.9em]" style={{ color: ReceiptBar.passed ? "var(--ok)" : "var(--danger)" }}>
              <span className="monospace">
                {ReceiptBar.topic}：{ReceiptBar.passed ? "ok" : "fail"} —— {ReceiptBar.description || t("日志.无说明")}
              </span>
            </div>
          ) : null}
        </div>
      </CollapsibleSection>
    </div>
  );
}
