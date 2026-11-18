/**
 * 本模块自带的 zh / en 文案。
 *
 * 实时跟踪面板不修改中央文案表（`views/i18n.ts`）；文案以 `locale` 选择，
 * 数字格式化留在面板/图表内部，这里只收已经格式化好的字符串。
 */
import type { LiveTrackingStatus } from "./types";

export type LiveTrackingLocale = "zh" | "en";

export interface LiveTrackingLabels {
  panelTitle: string;
  panelAria: string;
  simulation: string;
  simulationNote: string;
  realRobot: string;
  status: Record<LiveTrackingStatus, string>;

  experiment: string;
  model: string;
  noExperiment: string;
  noModel: string;
  runTime: string;
  durationUnknown: string;
  progress: string;

  dataUpdate: string;
  dataAgeUnknown: string;
  dataAgeSeconds: (seconds: string) => string;
  neverUpdated: string;

  compensation: string;
  compensationUnavailable: string;
  compensationDisabled: string;
  compensationEnabled: string;

  jointSelection: string;
  jointsUnavailable: string;
  window: string;
  windowOption: (seconds: number) => string;
  unit: string;
  deg: string;
  rad: string;
  displayOptions: string;

  chartPositionTitle: string;
  chartErrorTitle: string;
  chartTorqueTitle: string;
  chartVelocityTitle: string;
  unitTorque: string;
  unitDegPerSecond: string;
  unitRadPerSecond: string;

  legend: string;
  legendReference: string;
  legendActual: string;
  legendError: string;
  legendTorque: string;
  legendVelocity: string;
  legendCompensation: string;
  missing: string;

  noSamples: string;
  noSamplesHint: string;
  noSeriesData: string;
  noSeriesDataHint: string;
  noJoints: string;
  noJointsHint: string;

  readoutNone: string;
  readoutLatest: (time: string) => string;
  readoutHover: (time: string) => string;
  readoutCursor: (time: string) => string;
  chartAria: (title: string, unit: string) => string;

  hoverHint: string;
  run: string;
  noRun: string;
  timeAxisNote: string;

  velocityOptional: string;
  velocityShow: string;
  velocityHide: string;

  compensationUnavailableNote: string;
  compensationDisabledNote: string;
  compensationNoDataNote: string;

  disconnected: string;
  staleUpdates: (age: string) => string;
  runningNoSamples: string;
  idleHint: string;
  loadingHint: string;
  readyHint: string;
  pausedHint: string;
  completedHint: string;
  errorHint: string;
}

const zh: LiveTrackingLabels = {
  panelTitle: "实时跟踪",
  panelAria: "UR10 实时跟踪曲线面板",
  simulation: "仿真",
  simulationNote: "MuJoCo 仿真数据，非真机实测",
  realRobot: "真机 未接入",
  status: {
    idle: "空闲",
    loading: "加载中",
    ready: "就绪",
    running: "运行中",
    paused: "已暂停",
    completed: "已完成",
    error: "异常",
  },

  experiment: "实验",
  model: "模型",
  noExperiment: "未加载实验",
  noModel: "未加载模型",
  runTime: "运行时间",
  durationUnknown: "总时长未知",
  progress: "运行进度",

  dataUpdate: "数据更新",
  dataAgeUnknown: "未知",
  dataAgeSeconds: (seconds) => `${seconds} s 前`,
  neverUpdated: "尚无采样",

  compensation: "摩擦补偿",
  compensationUnavailable: "未接入",
  compensationDisabled: "已关闭",
  compensationEnabled: "已启用",

  jointSelection: "关节选择",
  jointsUnavailable: "关节信息未接入",
  window: "时间窗",
  windowOption: (seconds) => `${seconds} 秒`,
  unit: "角度单位",
  deg: "deg",
  rad: "rad",
  displayOptions: "显示选项",

  chartPositionTitle: "目标 / 实际位置",
  chartErrorTitle: "跟踪误差（目标 − 实际）",
  chartTorqueTitle: "执行器关节力矩",
  chartVelocityTitle: "关节速度",
  unitTorque: "N·m",
  unitDegPerSecond: "deg/s",
  unitRadPerSecond: "rad/s",

  legend: "图例",
  legendReference: "目标",
  legendActual: "实际",
  legendError: "误差",
  legendTorque: "执行器力矩",
  legendVelocity: "速度",
  legendCompensation: "摩擦补偿",
  missing: "缺失",

  noSamples: "尚无采样数据",
  noSamplesHint: "开始运行后才会出现真实曲线",
  noSeriesData: "当前窗口没有该关节数据",
  noSeriesDataHint: "缺失值留空，不补零",
  noJoints: "关节信息未接入",
  noJointsHint: "无法定位 J1–J6，等待后端关节映射",

  readoutNone: "无采样",
  readoutLatest: (time) => `最新 t = ${time} s`,
  readoutHover: (time) => `悬停 t = ${time} s`,
  readoutCursor: (time) => `播放 t = ${time} s`,
  chartAria: (title, unit) => `${title}，单位 ${unit}`,

  hoverHint: "悬停查看附近真实采样点，不停止运行",
  run: "运行段",
  noRun: "无运行段",
  timeAxisNote: "三图共用本运行段仿真时间横轴（s）",

  velocityOptional: "关节速度（可选）",
  velocityShow: "展开关节速度",
  velocityHide: "收起关节速度",

  compensationUnavailableNote: "补偿力矩未接入",
  compensationDisabledNote: "补偿已关闭，无补偿力矩",
  compensationNoDataNote: "尚无实际补偿数据",

  disconnected: "后端已断开：保留最后一段真实数据，不再更新",
  staleUpdates: (age) => `数据更新延迟 ${age}，曲线不插值`,
  runningNoSamples: "运行中，尚未收到真实采样",
  idleHint: "空闲：开始运行后接收本运行段的真实仿真采样",
  loadingHint: "正在加载运行段…",
  readyHint: "已就绪，等待开始运行",
  pausedHint: "已暂停：仿真时间与曲线同时停止",
  completedHint: "本次运行已结束，曲线保留",
  errorHint: "后端报告错误，等待新的运行段",
};

const en: LiveTrackingLabels = {
  panelTitle: "Live tracking",
  panelAria: "UR10 live tracking chart panel",
  simulation: "Simulation",
  simulationNote: "MuJoCo simulation data — not a real robot",
  realRobot: "Real robot not connected",
  status: {
    idle: "Idle",
    loading: "Loading",
    ready: "Ready",
    running: "Running",
    paused: "Paused",
    completed: "Completed",
    error: "Error",
  },

  experiment: "Experiment",
  model: "Model",
  noExperiment: "No experiment loaded",
  noModel: "No model loaded",
  runTime: "Run time",
  durationUnknown: "Duration unknown",
  progress: "Run progress",

  dataUpdate: "Data update",
  dataAgeUnknown: "unknown",
  dataAgeSeconds: (seconds) => `${seconds} s ago`,
  neverUpdated: "No samples yet",

  compensation: "Friction comp.",
  compensationUnavailable: "Not connected",
  compensationDisabled: "Disabled",
  compensationEnabled: "Enabled",

  jointSelection: "Joint selection",
  jointsUnavailable: "Joint metadata unavailable",
  window: "Window",
  windowOption: (seconds) => `${seconds} s`,
  unit: "Angle unit",
  deg: "deg",
  rad: "rad",
  displayOptions: "Display options",

  chartPositionTitle: "Target / actual position",
  chartErrorTitle: "Tracking error (target − actual)",
  chartTorqueTitle: "Actuator joint torque",
  chartVelocityTitle: "Joint velocity",
  unitTorque: "N·m",
  unitDegPerSecond: "deg/s",
  unitRadPerSecond: "rad/s",

  legend: "Legend",
  legendReference: "Target",
  legendActual: "Actual",
  legendError: "Error",
  legendTorque: "Actuator torque",
  legendVelocity: "Velocity",
  legendCompensation: "Friction comp.",
  missing: "missing",

  noSamples: "No samples yet",
  noSamplesHint: "Real curves appear after a run starts",
  noSeriesData: "No data for this joint in the window",
  noSeriesDataHint: "Missing values stay blank — no zeros invented",
  noJoints: "Joint metadata unavailable",
  noJointsHint: "Cannot identify J1–J6 until the backend supplies the joint mapping",

  readoutNone: "No samples",
  readoutLatest: (time) => `Latest t = ${time} s`,
  readoutHover: (time) => `Hover t = ${time} s`,
  readoutCursor: (time) => `Play t = ${time} s`,
  chartAria: (title, unit) => `${title}, unit ${unit}`,

  hoverHint: "Hover to read the nearest real sample; the run keeps going",
  run: "Run",
  noRun: "No run",
  timeAxisNote: "All charts share this run's simulation-time x-axis (s)",

  velocityOptional: "Joint velocity (optional)",
  velocityShow: "Show joint velocity",
  velocityHide: "Hide joint velocity",

  compensationUnavailableNote: "Compensation torque not connected",
  compensationDisabledNote: "Compensation disabled — no compensation torque",
  compensationNoDataNote: "No actual compensation data yet",

  disconnected: "Backend disconnected — showing the last real data, no longer updating",
  staleUpdates: (age) => `Data update delayed by ${age}; curves are not interpolated`,
  runningNoSamples: "Running — no real samples received yet",
  idleHint: "Idle: start a run to receive real simulation samples for this run segment",
  loadingHint: "Loading run segment…",
  readyHint: "Ready, waiting for the run to start",
  pausedHint: "Paused: simulation time and curves are both frozen",
  completedHint: "This run has finished; its curves are retained",
  errorHint: "The backend reported an error; waiting for a new run segment",
};

export const liveTrackingLabels: Record<LiveTrackingLocale, LiveTrackingLabels> = { zh, en };
