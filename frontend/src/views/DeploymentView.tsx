/**
 * DeploymentView.tsx —— 任务流第 5 步：导出部署包。
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
import { CollapsibleSection } from "../components/CollapsibleSection";
import { Tag } from "../components/Badge";
import { Button } from "../components/Button";
import { commands, useStore } from "../data/store";
import { finishCommand, recordCommandStart } from "../data/logs";
import { ValueTable, type ValueRow } from "../components/DataTable";
import { connectionTranslationKeys, useTranslation } from "./i18n";

export function DeploymentView() {
  const t = useTranslation();
  const state = useStore((s) => s.deployment.data);
  const project = useStore((s) => s.project.data);
  const connection = useStore((s) => s.connection);
  const [busy, setBusy] = useState(false);
  const canSend = connection === "已连接";
  const algorithms = (project?.algorithms ?? []).map((a) => {
    const name = String(a["名称"] ?? a["插件"] ?? "");
    const version = a["版本"] === undefined ? "" : ` v${String(a["版本"])}`;
    return `${name}${version}`;
  });

  const exporting = state?.状态 === "导出中";
  const succeeded = state?.状态 === "✓ 完成";
  const failed = state?.状态 === "✗ 失败";

  const exportData = async () => {
    setBusy(true);
    try {
      const startedAt = recordCommandStart();
      finishCommand("命令.部署", await commands.exportDeployment(), startedAt, { module: "部署" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <DeviceConsole />

      <CollapsibleSection
        title={t("部署.标题")}
        badge={
          succeeded ? <Tag tone="emphasis">{`${state?.文件数 ?? 0} 文件`}</Tag>
          : failed ? <Tag tone="notice">{t("部署.失败")}</Tag>
          : exporting ? <Tag tone="emphasis">{t("部署.导出中")}</Tag>
          : <Tag>{t("部署.未导出")}</Tag>
        }
      >
        {/* 第一屏分清"后端已连接"与"真机未接入"：两个"已连接"不是一回事 */}
        <div className="deployment-status" role="status">
          <span className="deployment-status-item">
            <span className="text-dim">{t("部署.后端连接")}</span>
            <Tag tone={canSend ? "success" : "error"}>{t(connectionTranslationKeys[connection])}</Tag>
          </span>
          <span className="deployment-status-item">
            <span className="text-dim">{t("部署.真机状态")}</span>
            <Tag tone="warning">{t("部署.真机未接入")}</Tag>
          </span>
        </div>
        <p className="mt-1 text-[0.85em]" style={{ color: "var(--warn)" }}>
          {t("部署.没有连接")}
        </p>

        <div className="mt-2 flex items-center gap-2">
          <Button variant="primary" disabled={busy || exporting || !canSend} title={t("部署.说明")} onPress={() => void exportData()}>
            {exporting ? t("部署.导出中") : t("部署.导出")}
          </Button>
          <span className="text-[0.85em] text-dim">
            {`${t("部署.项目")}: ${project?.project || t("通用.无")}`}
          </span>
        </div>

        {state?.出错 ? (
          <div className="mt-2 text-[0.85em]" style={{ color: "var(--warn)" }}>
            {state.出错}
          </div>
        ) : null}

        {succeeded && state?.清单?.length ? (
          <div className="mt-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[0.82em] text-dim">
              <span>{`${t("部署.项目")}: ${project?.project || t("通用.无")}`}</span>
              <span>{`${t("状态栏.模型")}: ${project?.model_display_name || t("通用.无")}`}</span>
              <span>{`${t("定义.算法数")}: ${project?.algorithms?.length ?? 0}`}</span>
              <span>{`${t("部署.总大小")}: ${((state.字节 ?? 0) / 1024).toFixed(1)} KB`}</span>
            </div>
            <div className="mt-0.5 break-words text-[0.82em] text-dim">
              {`${t("定义.算法组")}: ${algorithms.length ? algorithms.join(" · ") : t("通用.无")}`}
            </div>
            <p className="mt-1 text-[0.8em] text-dim">{t("部署.模型清单说明")}</p>
            <div className="mt-2 text-[0.85em] text-dim">{t("部署.目录")}</div>
            <div className="monospace break-all text-[0.85em]">{state.目录}</div>
            <ul className="mt-1 space-y-0.5">
              {state.清单.map((x) => (
                <li key={x.文件} className="flex items-baseline gap-1.5 text-[0.85em]">
                  <span className="min-w-0 flex-1 truncate monospace">{x.文件}</span>
                  <span className="flex-none text-dim">{x.说明}</span>
                  <span className="w-[62px] flex-none text-right text-dim monospace">
                    {x.字节 === undefined ? "--" : `${(x.字节 / 1024).toFixed(1)} KB`}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CollapsibleSection>
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
function DeviceConsole() {
  const t = useTranslation();
  const device = useStore((s) => s.device.data);
  const connection = useStore((s) => s.connection);
  const [busy, setBusy] = useState(false);
  const canSend = connection === "已连接";

  const actionState = async (action: string, parameters?: Record<string, number>) => {
    setBusy(true);
    try {
      const startedAt = recordCommandStart();
      finishCommand("命令.设备", await commands.deviceAction(action, parameters), startedAt, { module: "部署" });
    } finally {
      setBusy(false);
    }
  };

  const status = device?.安全状态 ?? "未连接";
  /** 状态名 → 显示文案。★ 用显式映射而不是模板字符串：
   *  模板 key（`部署.态.${态}`）在类型上是不安全的，新增状态时编译器帮不上忙。 */
  const statusName = (s: string) =>
    ({
      未连接: t("部署.态.未连接"),
      "已连接（未使能）": t("部署.态.已连接（未使能）"),
      使能中: t("部署.态.使能中"),
      运行: t("部署.态.运行"),
      停止: t("部署.态.停止"),
      故障: t("部署.态.故障"),
      急停: t("部署.态.急停"),
    })[s] ?? s;
  const stage = ["未连接", "已连接（未使能）", "使能中", "运行"];
  const connected = !!device?.已连接;
  const isRunning = status === "运行";
  const error = status === "故障" || status === "急停";

  const telemetry: ValueRow[] = device
    ? [
        { key: t("部署.后端"), value: <span className="monospace">{device.后端 || "--"}</span> },
        { key: t("部署.模式"), value: <span className="monospace">{device.模式 || "--"}</span> },
        { key: t("部署.实测平均延迟"), value: <span className="monospace">{device.实测平均延迟 ? `${device.实测平均延迟.toFixed(1)} ms` : t("部署.还没收到")}</span> },
        { key: t("部署.实测最大延迟"), value: <span className="monospace">{device.实测最大延迟 ? `${device.实测最大延迟.toFixed(1)} ms` : "--"}</span> },
        { key: t("部署.丢包错序"), value: <span className="monospace">{`${device.丢包数 ?? 0} / ${device.错序数 ?? 0}`}</span> },
        { key: t("部署.拒绝数"), value: <span className="monospace">{device.拒绝数 ?? 0}</span> },
        {
          key: t("部署.最近位置"),
          value: (
            <span className="monospace">
              {device.最近位置?.length
                ? `${device.最近位置.slice(0, 3).map((x) => x.toFixed(3)).join(", ")}…`
                : t("部署.还没收到")}
            </span>
          ),
        },
      ]
    : [];

  return (
    <CollapsibleSection
      title={t("部署.设备")}
      badge={
        <Tag tone={error ? "notice" : isRunning ? "emphasis" : connected ? "success" : "notice"}>
          {statusName(status)}
        </Tag>
      }
    >
      <p className="mt-1 text-[0.85em]" style={{ color: "var(--warn)" }}>
        {t("部署.模拟后端")}
      </p>

      {/* 状态机：把"在哪一格"画出来，比一个词更清楚 */}
      <ol className="mt-2 flex flex-wrap items-center gap-1 text-[0.78em]">
        {stage.map((cell, i) => {
          const arrived = stage.indexOf(status) >= i && stage.includes(status);
          return (
            <li key={cell} className="flex items-center gap-1">
              {i ? <span className="text-dim">→</span> : null}
              <span
                className="rounded px-1.5 py-0.5 monospace"
                style={{
                  background: arrived ? "var(--accent)" : "var(--bg-frame)",
                  color: arrived ? "var(--fg-on-accent)" : "var(--fg-dim)",
                }}
              >
                {statusName(cell)}
              </span>
            </li>
          );
        })}
        {error ? (
          <li className="flex items-center gap-1">
            <span className="text-dim">→</span>
            <span className="rounded px-1.5 py-0.5 monospace"
                  style={{ background: "var(--danger)", color: "#fff" }}>
              {statusName(status)}
            </span>
          </li>
        ) : null}
      </ol>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Button variant="secondary" size="small" disabled={busy || !canSend} onPress={() => void actionState("打开")}>
          {t("部署.打开")}
        </Button>
        <Button variant="primary" size="small" disabled={busy || !canSend || status !== "已连接（未使能）"}
              onPress={() => void actionState("使能")}>
          {t("部署.使能")}
        </Button>
        <Button variant="primary" size="small" disabled={busy || !canSend || status !== "使能中"}
              onPress={() => void actionState("进运行")}>
          {t("部署.进运行")}
        </Button>
        <Button variant="secondary" size="small" disabled={busy || !canSend || !connected}
              onPress={() => void actionState("停止")}>
          {t("部署.停止")}
        </Button>
        <Button variant="secondary" size="small" disabled={busy || !canSend || !connected}
              onPress={() => void actionState("急停")}>
          {t("部署.急停")}
        </Button>
        <Button variant="secondary" size="small" disabled={busy || !canSend || !connected}
              onPress={() => void actionState("演练断线")}>
          {t("部署.演练")}
        </Button>
        <Button variant="secondary" size="small" disabled={busy || !canSend}
              onPress={() => void actionState("导出审计")}>
          {t("部署.导出审计")}
        </Button>
      </div>

      {device && telemetry.length ? (
        <div className="mt-2">
          <ValueTable rows={telemetry} />
        </div>
      ) : null}

      <div className="mt-2 grid grid-cols-2 gap-2">
        <DegradationSlider name={t("部署.延迟")} value={device?.延迟毫秒 ?? 0} upperLimit={60} step={1}
                  unit="ms" disabled={!connected || busy}
                  onChange={(v) => void actionState("设劣化", { 延迟毫秒: v })} />
        <DegradationSlider name={t("部署.丢包")} value={(device?.丢包率 ?? 0) * 100} upperLimit={50} step={1}
                  unit="%" disabled={!connected || busy}
                  onChange={(v) => void actionState("设劣化", { 丢包率: v / 100 })} />
        <DegradationSlider name={t("部署.抖动")} value={device?.抖动毫秒 ?? 0} upperLimit={20} step={0.5}
                  unit="ms" disabled={!connected || busy}
                  onChange={(v) => void actionState("设劣化", { 抖动毫秒: v })} />
        <DegradationSlider name={t("部署.量化")} value={device?.编码器分辨率 ?? 0} upperLimit={0.02} step={0.001}
                  unit="rad" disabled={!connected || busy}
                  onChange={(v) => void actionState("设劣化", { 编码器分辨率: v })} />
      </div>

      {device?.审计?.length ? (
        <div className="mt-2">
          <div className="text-[0.85em] text-dim">{t("部署.审计")}</div>
          <ul className="mt-1 max-h-[132px] space-y-0.5 overflow-y-auto">
            {device.审计.slice().reverse().map((item, i) => (
              <li key={`${item.时刻}-${i}`} className="flex items-baseline gap-1.5 text-[0.78em]">
                <span className="flex-none text-dim monospace">{item.类别}</span>
                <span className="min-w-0 flex-1 truncate" title={item.内容}>{item.内容}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </CollapsibleSection>
  );
}

/** 劣化参数滑块：改完立刻生效（不需要"应用"按钮，便于现场演示） */
function DegradationSlider({
  name: name, value: value, upperLimit: upperLimit, step: step, unit: unit, disabled: disabled, onChange: onChange,
}: {
  name: string; value: number; upperLimit: number; step: number; unit: string;
  disabled: boolean; onChange: (v: number) => void;
}) {
  return (
    <label className="block text-[0.8em]">
      <span className="flex items-baseline gap-1">
        <span className="text-dim">{name}</span>
        <span className="flex-1" />
        <span className="monospace">{`${value.toFixed(step < 1 ? 2 : 0)} ${unit}`}</span>
      </span>
      <input
        type="range"
        className="mt-0.5 w-full"
        min={0}
        max={upperLimit}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={name}
      />
    </label>
  );
}
