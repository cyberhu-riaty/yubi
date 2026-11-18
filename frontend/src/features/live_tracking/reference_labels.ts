/** Local zh/en copy for the offline reference comparison panel. */
import type { LiveTrackingLocale } from "./labels";

export interface ReferenceComparisonLabels {
  title: string;
  panelAria: string;
  archived: string;
  offline: string;
  notLive: string;
  trajectory: string;
  joint: string;
  torque: string;
  current: string;
  torqueUnit: string;
  currentUnit: string;
  sourceArchive: string;
  sourceRecompute: string;
  sourceArchiveNote: string;
  sourceRecomputeNote: string;
  exportCsv: string;
  exportHint: string;
  hoverHint: string;
  loading: string;
  loadFailed: string;
  noData: string;
  noDataHint: string;
  rawRtdeMissing: string;
  preprocessingNote: string;
  recomputeMatch: string;
  recomputeContact: string;
  recomputeUnavailable: string;
  recomputeSummary: (bad: string, total: string, max: string, time: string, joint: string) => string;
  contactPairs: (pairs: string) => string;
  badIntervals: (count: string) => string;
  playback: (time: string, duration: string) => string;
  sample: (index: string, total: string) => string;
  selectorBusy: string;
  selectorLocked: string;
  switchFailed: string;
  legendMeasured: string;
  legendModelOff: string;
  legendModelOn: string;
  legendTarget: string;
  legendRecomputeOff: string;
  legendRecomputeOn: string;
  exportFileName: (index: number, kind: string) => string;
  sourceFile: (file: string) => string;
  currentMode: string;
}

const zh: ReferenceComparisonLabels = {
  title: "参考实验对比",
  panelAria: "UR10 参考实验离线回放对比",
  archived: "实机存档",
  offline: "离线回放",
  notLive: "非实时",
  trajectory: "参考轨迹",
  joint: "关节",
  torque: "力矩",
  current: "电流",
  torqueUnit: "N·m",
  currentUnit: "A",
  sourceArchive: "存档参考",
  sourceRecompute: "当前模型重算",
  sourceArchiveNote: "曲线来自原始脚本处理后的实机参考结果；这是存档回放，不是实时采集。",
  sourceRecomputeNote: "曲线是当前模型/MuJoCo 对同一组 q/dq/ddq 的独立重算；轨迹 1、7 的接触帧可能不同。",
  exportCsv: "导出 CSV",
  exportHint: "导出当前轨迹、当前物理量的逐点数值，便于离线复核。",
  hoverHint: "悬停查看读数；播放游标在六张图上同步移动。",
  loading: "正在读取参考数据…",
  loadFailed: "参考数据读取失败",
  noData: "还没有参考数据",
  noDataHint: "请先在顶部实验下拉框加载「UR10 参考实验回放对比」。",
  rawRtdeMissing: "原始 RTDE 记录不在当前工作区；无法从原始数据重新核对滤波、求导与裁剪。",
  preprocessingNote: "处理流程：10 Hz 零相位滤波 + 0.25 s Savitzky–Golay 求导 + 首尾 0.5 s 裁剪。",
  recomputeMatch: "独立重算通过（力矩 ≤ 1e-5 N·m）",
  recomputeContact: "独立重算有接触相关差异；存档回放不受影响",
  recomputeUnavailable: "独立重算暂不可用",
  recomputeSummary: (bad, total, max, time, joint) =>
    `${bad}/${total} 个采样点超过 1e-5 N·m；最大 ${max} N·m（t=${time} s，J${joint}）`,
  contactPairs: (pairs) => `接触对：${pairs}`,
  badIntervals: (count) => `差异区间 ${count} 段`,
  playback: (time, duration) => `t = ${time} / ${duration} s`,
  sample: (index, total) => `采样 ${index} / ${total}`,
  selectorBusy: "切换中…",
  selectorLocked: "运行中不能切换轨迹，请先暂停或复位",
  switchFailed: "切换参考轨迹失败",
  legendMeasured: "实测",
  legendModelOff: "模型（无摩擦）",
  legendModelOn: "模型＋摩擦",
  legendTarget: "UR 目标力矩",
  legendRecomputeOff: "重算（无摩擦）",
  legendRecomputeOn: "重算＋摩擦",
  exportFileName: (index, kind) => `ur10_reference_trajectory_${index}_${kind}.csv`,
  sourceFile: (file) => `来源：${file}`,
  currentMode: "当前模式：离线回放",
};

const en: ReferenceComparisonLabels = {
  title: "Reference experiment",
  panelAria: "UR10 reference experiment offline playback comparison",
  archived: "Archived real data",
  offline: "Offline replay",
  notLive: "Not live",
  trajectory: "Trajectory",
  joint: "Joint",
  torque: "Torque",
  current: "Current",
  torqueUnit: "N·m",
  currentUnit: "A",
  sourceArchive: "Archived reference",
  sourceRecompute: "Current model recompute",
  sourceArchiveNote: "Curves come from the processed real-machine reference results; this is archived replay, not live acquisition.",
  sourceRecomputeNote: "Curves are an independent recompute from the same q/dq/ddq. Contact frames in trajectories 1 and 7 may differ.",
  exportCsv: "Export CSV",
  exportHint: "Export the current trajectory and quantity as point values for offline checks.",
  hoverHint: "Hover for readouts; the playback cursor moves across all six charts.",
  loading: "Loading reference data…",
  loadFailed: "Could not load the reference data",
  noData: "No reference data yet",
  noDataHint: "Load “UR10 reference experiment replay” from the experiment selector first.",
  rawRtdeMissing: "Raw RTDE recordings are not in this workspace; filtering, differentiation and trimming cannot be re-checked from raw data.",
  preprocessingNote: "Processing: 10 Hz zero-phase filter + 0.25 s Savitzky–Golay derivative + 0.5 s trim on both ends.",
  recomputeMatch: "Independent recompute passes (torque ≤ 1e-5 N·m)",
  recomputeContact: "Independent recompute has contact-related differences; archived replay is unaffected",
  recomputeUnavailable: "Independent recompute unavailable",
  recomputeSummary: (bad, total, max, time, joint) =>
    `${bad}/${total} samples exceed 1e-5 N·m; worst ${max} N·m (t=${time} s, J${joint})`,
  contactPairs: (pairs) => `Contact pairs: ${pairs}`,
  badIntervals: (count) => `${count} difference interval(s)`,
  playback: (time, duration) => `t = ${time} / ${duration} s`,
  sample: (index, total) => `sample ${index} / ${total}`,
  selectorBusy: "Switching…",
  selectorLocked: "Cannot switch while running; pause or reset first",
  switchFailed: "Could not switch the reference trajectory",
  legendMeasured: "Measured",
  legendModelOff: "Model (friction off)",
  legendModelOn: "Model + friction",
  legendTarget: "UR target moment",
  legendRecomputeOff: "Recompute (friction off)",
  legendRecomputeOn: "Recompute + friction",
  exportFileName: (index, kind) => `ur10_reference_trajectory_${index}_${kind}.csv`,
  sourceFile: (file) => `Source: ${file}`,
  currentMode: "Mode: offline replay",
};

export const referenceComparisonLabels: Record<LiveTrackingLocale, ReferenceComparisonLabels> = {
  zh,
  en,
};
