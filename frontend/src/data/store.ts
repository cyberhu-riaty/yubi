/**
 * store.ts —— 界面状态的唯一来源（P1 的 L0 那一半）
 *
 * 为什么不用 useState 到处传（这是 SPEC 里明确点名不要抄 LE 的地方）：
 *   LE 是"App 一层 10 个 useState + 一个 data prop drilling 下发全部"，
 *   而且那个 data 里混装了三类关注点（规划结果 / 播放时钟 / 机器人资产）。
 *   我们要长到九项功能，那样必然失控。
 *
 * 所以这里按**域**拆开，每个域是一份 latest-wins 快照 + 一段曲线历史：
 *   项目 / 模型 / 参数 / 指标 / 辨识 / 连接
 * 组件用 `用仓库(选择器)` 只订阅自己关心的那一小块，避免"一个字节变了整页重画"。
 *
 * 曲线历史（环形缓冲）单独说明：
 *   指标是 30 Hz 的，一分钟就是 1800 帧 × N 条曲线。全留会吃内存，
 *   所以每条曲线只留最近 `曲线容量` 个点，且**按墙钟时间**淘汰
 *   （用墙钟而不是仿真时间：物理暂停时仿真时间不动，曲线会挤成一坨）。
 */
import { useSyncExternalStore } from "react";
import { BackendConnection, guessBackendUrl, type CommandReceipt, type WireFrame, type WireHandshake, type ConnectionState, type SamplePoint } from "./connection";

export interface ProjectState {
  project?: string;
  model_path?: string;
  model_display_name?: string;
  algorithms?: Record<string, unknown>[];
  report?: string[];
  algorithm_library?: string[];
  saved?: boolean;
  active_controller?: string;
  overridden_controllers?: string[];
  gravity_enabled?: boolean;
}

/** 资产库里的一台机器人（来自后端 `model_bridge.asset_manifest()` 的真实产物） */
export interface AssetItem {
  id?: string;
  display_name?: string;
  category?: string;
  dof?: number;
  actuator_count?: number;
  license?: string;
  controllable?: boolean;
  /** 可直接加载的那个文件（= 清单里的「扭矩模型」绝对路径） */
  path?: string;
}

/** 运行期系统指标（来自 `系统桥`，1 Hz 一条） */
export interface SystemState {
  仿真时间?: number;
  墙钟?: number;
  RTF?: number;
  步频?: number;
  仿真步长?: number;
  内存MB?: number;
  插件数?: number;
  出错?: string;
}

/** Run / Pause / Reset 后由仿真侧确认的状态；不根据按钮点击自行猜。 */
export interface SimulationState {
  state?: "running" | "paused" | string;
  gravity_enabled?: boolean;
  simulation_time?: number;
  reset_count?: number;
  speed_multiplier?: number;
  description?: string;
}

export interface ExperimentItem {
  key?: string;
  name?: string;
  model?: string;
  project?: string;
  controllers?: string[];
  duration_s?: number;
  description?: string;
  error?: string;
}

/** 注册实验的选择、进度和自动导出结果。 */
export interface ExperimentState {
  current?: string;
  name?: string;
  status?: string;
  available?: ExperimentItem[];
  model?: string;
  project?: string;
  controllers?: string[];
  duration_s?: number;
  elapsed_s?: number;
  result_directory?: string;
  description?: string;
}

/** 关节目标输入区的权威状态：当前位置来自 MjData，目标来自后端确认。 */
export interface ControlState {
  关节名?: string[];
  当前位置?: number[];
  当前速度?: number[];
  当前控制?: number[];
  目标?: number[];
  目标来源?: string;
  说明?: string;
}

/** 自检里的一项 */
export interface DiagnosticItem {
  名?: string;
  通过?: boolean;
  说明?: string;
  秒?: number;
}

/** 自检报告（来自 `诊断桥`，真跑 工具/验证 下的脚本） */
export interface DiagnosticReport {
  运行中?: boolean;
  通过?: number;
  总数?: number;
  耗时秒?: number;
  时间?: string;
  项?: DiagnosticItem[];
  出错?: string;
}

/** 算法库里的一个插件（来自 `插件桥.取插件目录()`） */
export interface PluginItem {
  插件?: string;
  分组?: string;
  名称?: string;
  版本?: string;
  说明?: string;
  作者?: string;
  文件?: string;
  被项目使用?: string[];
  当前启用?: boolean;
  /** 当前控制链里的执行序号；顺序会影响后写入 data.ctrl 的算法 */
  当前顺序?: number | null;
}

export interface PluginCatalog {
  数量?: number;
  插件?: PluginItem[];
  说明?: string;
}

/** 设备链路状态（来自 `设备/连接桥`） */
export interface DeviceConnection {
  后端?: string;
  已连接?: boolean;
  安全状态?: string;
  模式?: string;
  自由度?: number;
  延迟毫秒?: number;
  抖动毫秒?: number;
  丢包率?: number;
  编码器分辨率?: number;
  实测平均延迟?: number;
  实测最大延迟?: number;
  丢包数?: number;
  错序数?: number;
  拒绝数?: number;
  最近位置?: number[];
  审计?: { 时刻?: number; 类别?: string; 内容?: string; 错误码?: string }[];
  说明?: string;
}

/** 一条病态告警（来自 `观测核心`） */
export interface AlertItem {
  类型?: string;
  严重度?: string;
  信号?: string;
  开始秒?: number;
  结束秒?: number;
  证据?: string;
  建议?: string;
  曲线?: number[];
  曲线t?: number[];
}

export interface AlertTable {
  活动?: AlertItem[];
  已检出?: number;
}

/** Trajectory planning result published by ``planning_bridge``. */
export interface PlanningResult {
  status?: string;
  waypoint_count?: number;
  dof?: number;
  duration_s?: number;
  path_length?: number;
  max_joint_velocity?: number;
  max_joint_acceleration?: number;
  max_joint_jerk?: number;
  velocity_margin?: number;
  acceleration_margin?: number;
  jerk_margin?: number;
  terminal_velocity?: number;
  smoothing_deviation?: number;
  bottleneck_joint?: number;
  bottleneck_type?: string;
  bottleneck_position?: number;
  optimal_lower_bound?: number;
  actual_to_lower_bound?: number;
  limit_source?: string;
  timestamp?: string;
  reason?: string;
  comparison?: {
    previous_duration?: number;
    current_duration?: number;
    duration_change_percent?: number;
    previous_max_velocity?: number;
    current_max_velocity?: number;
    previous_constraint?: string;
    current_constraint?: string;
    previous_speed_axis?: number[];
    current_speed_axis?: number[];
  };
  inverse_kinematics?: string;
  output_path?: string;
  execution_status?: string;
  execution_progress?: number;
  envelope?: number[];
  path_axis?: number[];
  speed_axis?: number[];
}

export interface DeploymentItem {
  文件?: string;
  说明?: string;
  字节?: number;
}

export interface DeploymentState {
  状态?: string;
  目录?: string;
  文件数?: number;
  字节?: number;
  时间?: string;
  清单?: DeploymentItem[];
  说明?: string;
  出错?: string;
}

export interface AssetLibrary {
  count?: number;
  models?: AssetItem[];
}

export interface ModelState {
  current_path?: string;
  current_display_name?: string;
  dof?: number;
  actuator_count?: number;
  status?: string;
  duration_s?: number;
}

/**
 * 一个可调参数。
 * ★ 形状来自后端 `parameter_bridge.collect_parameters()` 的真实产物。
 *   （早先这里写的是 `{值, 最小, 最大}`，与实现不符，导致 `范围` 数组被当对象渲染成乱码。）
 */
export interface ParameterItem {
  plugin?: string;
  plugin_english?: string;
  plugin_version?: string;
  parameter?: string;
  value?: number;
  /** [最小, 最大] —— 注意是**数组**，不是两个字段 */
  range?: number[];
  step?: number;
  unit?: string;
  [key: string]: unknown;
}

export interface IdentificationState {
  状态?: string;
  进度?: string;
  采样步数?: number;
  结果?: Record<string, unknown>[];
  拟合?: Record<string, unknown>;
  耗时?: number;
  日志?: string[];
}

export interface SnapshotDomain<T> {
  data: T | null;
  frameId: number;
  timestamp: number;
}

export interface UIState {
  connection: ConnectionState;
  error: string | null;
  handshake: WireHandshake | null;
  topicCounts: Record<string, number>;
  topicRates: Record<string, number>;
  project: SnapshotDomain<ProjectState>;
  model: SnapshotDomain<ModelState>;
  /** 可选模型清单。★ 与 `模型` 区分：那是"当前装的哪台"，这是"能选哪些" */
  assets: SnapshotDomain<AssetLibrary>;
  /** 运行期系统指标（RTF/步频/内存）。只在仿真侧能量到的量在这里 */
  system: SnapshotDomain<SystemState>;
  /** 全局仿真运行状态（Run / Pause / Reset） */
  simulation: SnapshotDomain<SimulationState>;
  /** 当前注册实验及自动运行结果 */
  experiment: SnapshotDomain<ExperimentState>;
  /** 简单关节控制目标与当前状态 */
  control: SnapshotDomain<ControlState>;
  /** 自检报告 */
  diagnostics: SnapshotDomain<DiagnosticReport>;
  /** 本机算法库插件清单 */
  plugins: SnapshotDomain<PluginCatalog>;
  /** 部署包导出状态 */
  deployment: SnapshotDomain<DeploymentState>;
  /** 轨迹规划结果 */
  planning: SnapshotDomain<PlanningResult>;
  /** 病态告警 */
  alerts: SnapshotDomain<AlertTable>;
  /** 设备链路 */
  device: SnapshotDomain<DeviceConnection>;
  /**
   * 参数表。负载形状是 `{parameters: {full_name: ParameterItem}}`。
   * 这里如实声明，别在类型上"美化"成扁平结构：类型与实现对不上时，
   * 错的是类型（实测踩过：少剥一层导致表格渲染出一堆 `--` 行）。
   */
  parameters: SnapshotDomain<{ parameters?: Record<string, ParameterItem> }>;
  identification: SnapshotDomain<IdentificationState>;
  /** {曲线名: 采样点[]} —— 只留最近 N 个点 */
  charts: Record<string, SamplePoint[]>;
  chartFrameCount: number;
  receipt: CommandReceipt | null;
}

/** 每条曲线保留的最大点数（30 Hz × 120 秒 = 3600；曲线一多就很占内存） */
const CHART_CAPACITY = 3600;
/** 曲线保留的墙钟窗口（秒） */
const CHART_WINDOW_SECONDS = 120;

const emptySnapshot: SnapshotDomain<never> = { data: null, frameId: 0, timestamp: 0 };

let state: UIState = {
  connection: "连接中",
  error: null,
  handshake: null,
  topicCounts: {},
  topicRates: {},
  project: { ...emptySnapshot },
  model: { ...emptySnapshot },
  assets: { ...emptySnapshot },
  system: { ...emptySnapshot },
  simulation: { ...emptySnapshot },
  experiment: { ...emptySnapshot },
  control: { ...emptySnapshot },
  diagnostics: { ...emptySnapshot },
  plugins: { ...emptySnapshot },
  deployment: { ...emptySnapshot },
  planning: { ...emptySnapshot },
  alerts: { ...emptySnapshot },
  device: { ...emptySnapshot },
  parameters: { ...emptySnapshot },
  identification: { ...emptySnapshot },
  charts: {},
  chartFrameCount: 0,
  receipt: null,
};

const subscribers = new Set<() => void>();
let versionNumber = 0;
let notificationQueued = false;

function updateState(update: (draft: UIState) => UIState): void {
  state = update(state);
  versionNumber += 1;
  // 合帧：一秒钟可能有上百条消息，不能让每条都触发一次 React 渲染
  if (notificationQueued) return;
  notificationQueued = true;
  requestAnimationFrame(() => {
    notificationQueued = false;
    for (const f of subscribers) f();
  });
}

export function getState(): UIState {
  return state;
}

export function useStore<T>(selector: (s: UIState) => T): T {
  return useSyncExternalStore(
    (callback) => {
      subscribers.add(callback);
      return () => subscribers.delete(callback);
    },
    () => selector(getState()),
    () => selector(getState()),
  );
}

// ---------------------------------------------------------------------------
// 连接实例
// ---------------------------------------------------------------------------
export const backend = new BackendConnection(guessBackendUrl());

export function startConnection(): () => void {
  const cancel = backend.subscribe((e) => {
    if (e.state) updateState((s) => ({ ...s, connection: e.state! }));
    if (e.error) updateState((s) => ({ ...s, error: e.error! }));
    if (e.handshake) updateState((s) => ({ ...s, handshake: e.handshake!, error: null }));
    if (e.receipt) updateState((s) => ({ ...s, receipt: e.receipt! }));
    if (e.frame) receiveFrame(e.frame);
  });
  backend.connect();

  const heartbeat = window.setInterval(() => {
    updateState((s) => ({ ...s, topicCounts: { ...backend.counts }, topicRates: { ...backend.rates } }));
  }, 1000);

  return () => {
    cancel();
    window.clearInterval(heartbeat);
    backend.close();
  };
}

function receiveFrame(frame: WireFrame): void {
  const timestamp = (frame.墙钟 ?? Date.now() / 1000) as number;
  switch (frame.主题) {
    case "model.library":
      updateState((s) => ({ ...s, assets: { data: frame.数据 as AssetLibrary, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "设备连接":
      updateState((s) => ({ ...s, device: { data: frame.数据 as DeviceConnection, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "告警":
      updateState((s) => ({ ...s, alerts: { data: frame.数据 as AlertTable, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "planning.result":
      updateState((s) => ({
        ...s,
        planning: { data: frame.数据 as PlanningResult, frameId: frame.序号 ?? 0, timestamp: timestamp },
      }));
      return;
    case "部署":
      updateState((s) => ({ ...s, deployment: { data: frame.数据 as DeploymentState, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "插件目录":
      updateState((s) => ({ ...s, plugins: { data: frame.数据 as PluginCatalog, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "诊断":
      updateState((s) => ({ ...s, diagnostics: { data: frame.数据 as DiagnosticReport, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "系统":
      updateState((s) => ({ ...s, system: { data: frame.数据 as SystemState, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "simulation.state": {
      const nextState = frame.数据 as SimulationState;
      updateState((s) => {
        const previousState = s.simulation.data;
        const resetOccurred = typeof previousState?.reset_count === "number"
          && typeof nextState.reset_count === "number"
          && nextState.reset_count > previousState.reset_count;
        const timeReversed = typeof previousState?.simulation_time === "number"
          && typeof nextState.simulation_time === "number"
          && nextState.simulation_time + 1e-9 < previousState.simulation_time;
        const resetCharts = resetOccurred || timeReversed;
        return {
          ...s,
          simulation: { data: nextState, frameId: frame.序号 ?? 0, timestamp: timestamp },
          // Reset 是新的实验段：不把复位前后两个不连续状态连成假的竖线。
          charts: resetCharts ? {} : s.charts,
          chartFrameCount: resetCharts ? 0 : s.chartFrameCount,
        };
      });
      return;
    }
    case "experiment.state":
      updateState((s) => ({
        ...s,
        experiment: { data: frame.数据 as ExperimentState, frameId: frame.序号 ?? 0, timestamp: timestamp },
      }));
      return;
    case "控制状态":
      updateState((s) => ({ ...s, control: { data: frame.数据 as ControlState, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "project.state":
      updateState((s) => ({ ...s, project: { data: frame.数据 as ProjectState, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "model.state":
      updateState((s) => ({ ...s, model: { data: frame.数据 as ModelState, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "parameter.table":
      updateState((s) => ({
        ...s,
        parameters: {
          data: frame.数据 as { parameters?: Record<string, ParameterItem> },
          frameId: frame.序号 ?? 0,
          timestamp: timestamp,
        },
      }));
      return;
    case "辨识状态":
      updateState((s) => ({ ...s, identification: { data: frame.数据 as IdentificationState, frameId: frame.序号 ?? 0, timestamp: timestamp } }));
      return;
    case "指标": {
      const values = (frame.数据.数值 ?? {}) as Record<string, number>;
      const t = (frame.数据.墙钟 as number) ?? timestamp;
      if (!Object.keys(values).length) return;
      updateState((s) => {
        const charts = { ...s.charts };
        for (const [name, v] of Object.entries(values)) {
          if (typeof v !== "number" || !Number.isFinite(v)) continue;
          const previous = charts[name] ?? [];
          // 只在"确实新增了一个点"时复制数组，避免每条曲线每帧都重建
          let updated = previous.length && previous[previous.length - 1].t === t
            ? [...previous.slice(0, -1), { t, v }]
            : [...previous, { t, v }];
          updated = prune(updated, t);
          charts[name] = updated;
        }
        return { ...s, charts: charts, chartFrameCount: s.chartFrameCount + 1 };
      });
      return;
    }
    default:
      return;
  }
}

function prune(point: SamplePoint[], now: number): SamplePoint[] {
  let output = point;
  if (output.length > CHART_CAPACITY) output = output.slice(output.length - CHART_CAPACITY);
  const earliest = now - CHART_WINDOW_SECONDS;
  let startIndex = 0;
  while (startIndex < output.length && output[startIndex].t < earliest) startIndex += 1;
  if (startIndex > 0) output = output.slice(startIndex);
  return output;
}

// ---------------------------------------------------------------------------
// 命令（都走"校验 + 回执"，见 连接.ts）
// ---------------------------------------------------------------------------
export const commands = {
  loadExperiment(experiment: string) {
    return backend.sendCommand("command.experiment", { action: "load", experiment });
  },
  controlSimulation(action: "run" | "pause" | "reset") {
    return backend.sendCommand("command.simulation", { action });
  },
  setSimulationSpeed(speedMultiplier: number) {
    return backend.sendCommand("command.simulation", {
      action: "speed", speed_multiplier: speedMultiplier,
    });
  },
  setGravity(enabled: boolean) {
    return backend.sendCommand("command.gravity", { gravity_enabled: enabled });
  },
  setControlTarget(target: number[]) {
    return backend.sendCommand("命令.控制目标", { target: target });
  },
  recordWaypoint() {
    return backend.sendCommand("command.planning", { action: "record_waypoint" });
  },
  clearWaypoints() {
    return backend.sendCommand("command.planning", { action: "clear_waypoints" });
  },
  executeTrajectory() {
    return backend.sendCommand("command.planning", { action: "execute" });
  },
  stopTrajectory() {
    return backend.sendCommand("command.planning", { action: "stop_execution" });
  },
  planCartesian(points: { xyz: number[] }[], limits?: {
    velocity_limits?: number[]; acceleration_limits?: number[];
  }) {
    return backend.sendCommand("command.planning", {
      action: "plan",
      cartesian_waypoints: points,
      ...(limits?.velocity_limits ? { velocity_limits: limits.velocity_limits } : {}),
      ...(limits?.acceleration_limits
        ? { acceleration_limits: limits.acceleration_limits } : {}),
    });
  },
  planTrajectory(
    waypoints?: { q: number[] }[],
    limits?: {
      velocity_limits?: number[];
      acceleration_limits?: number[];
      jerk_limits?: number[];
    },
  ) {
    return backend.sendCommand("command.planning", {
      action: "plan",
      ...(waypoints?.length ? { waypoints } : {}),
      ...(limits?.velocity_limits ? { velocity_limits: limits.velocity_limits } : {}),
      ...(limits?.acceleration_limits
        ? { acceleration_limits: limits.acceleration_limits } : {}),
      ...(limits?.jerk_limits ? { jerk_limits: limits.jerk_limits } : {}),
    });
  },
  deviceAction(action: string, parameters?: Record<string, number>) {
    return backend.sendCommand("命令.设备", { 动作: action, ...(parameters ?? {}) });
  },
  exportDeployment() {
    return backend.sendCommand("命令.部署", { 动作: "导出" });
  },
  runDiagnostics() {
    return backend.sendCommand("命令.诊断", { 动作: "运行" });
  },
  /** 在原生 3D 里高亮一个关节（视觉诊断；后端夹到 0..60s） */
  highlightJoint(joint: number, seconds = 8) {
    return backend.sendCommand("命令.高亮", { 关节: joint, 秒: seconds });
  },
  switchModel(path: string, displayName = "") {
    return backend.sendCommand("command.model", { path, display_name: displayName });
  },
  /** 改参数：键必须是参数表里的全名（形如「插件名·参数名」） */
  updateParameters(updates: Record<string, number>) {
    return backend.sendCommand("command.parameters", { updates });
  },
  applyAlgorithms(algorithms: string[], persist = false, resetPose = true) {
    return backend.sendCommand("command.algorithms", {
      algorithms: algorithms.map((name) => ({ plugin: name })),
      persist,
      reset_pose: resetPose,
    });
  },
  startIdentification(durationSeconds = 10) {
    return backend.sendCommand("命令.辨识", { 动作: "开始", 时长: durationSeconds });
  },
  stopIdentification() {
    return backend.sendCommand("命令.辨识", { 动作: "停止", 时长: 0 });
  },
  startRecording(frequency = 100, note = "") {
    return backend.sendCommand("命令.录制", { 动作: "开始", 频率: frequency, 备注: note });
  },
  stopRecording() {
    return backend.sendCommand("命令.录制", { 动作: "停止", 频率: 100, 备注: "" });
  },
};

/* ---------------------------------------------------------------------------
 * 调试钩子：把仓库暴露到 window，供自动化测试读取真实内部状态。
 *
 * 为什么必须有它：端到端测试若靠"正则去匹配页面上的数字"，会随排版微调而失效
 * （实测踩过：换成"点数在长大"的判定后仍然取到了无关的数字）。
 * 把状态直接暴露出来，测试问的就是"界面真的收到了多少帧曲线数据"，
 * 而不是"我猜页面上哪个数字是点数"。
 *
 * 只在浏览器环境挂载，不加任何运行时开销；生产打包同样保留（无副作用）。
 * ------------------------------------------------------------------------- */
declare global {
  interface Window {
    yubi?: {
      getState: typeof getState;
      chartPointCount: () => number;
      chartNames: () => string[];
    };
  }
}

if (typeof window !== "undefined") {
  window.yubi = {
    getState: getState,
    chartPointCount: () =>
      Object.values(getState().charts).reduce((total, points) => total + points.length, 0),
    chartNames: () => Object.keys(getState().charts).sort(),
  };
}
