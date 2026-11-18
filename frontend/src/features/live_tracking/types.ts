/**
 * UR10 实时跟踪面板的固定展示接口 v1。
 *
 * 本文件按《UR10 实时跟踪双 AI 协作方案》第 5 节**原样复制**：
 * 这是 A（数据适配层）到 B（面板）的展示接口，不是 WebSocket 消息结构。
 * B 不重新设计字段；字段名、单位、可空性与语义均以协作方案为准。
 */

export type NullableJointVector = readonly (number | null)[];

export interface LiveTrackingSample {
  /** 从本运行段开始计算的仿真时间，单位秒，首个有效点可为 0。 */
  elapsedS: number;
  /** 以下向量与 jointNames 一一对应，长度必须一致。 */
  positionRad: NullableJointVector;
  referenceRad: NullableJointVector;
  velocityRadS: NullableJointVector;
  /** 目标减实际；A 负责计算，B 不从位置重新推导。 */
  errorRad: NullableJointVector;
  /** 执行器实际施加的广义关节力矩，单位 N·m，不是原始 ctrl。 */
  actuatorTorqueNm: NullableJointVector;
  /** 控制器实际施加的摩擦前馈项；未知或未接入时整项为 null。 */
  compensationTorqueNm: NullableJointVector | null;
}

export type LiveTrackingStatus =
  | "idle" | "loading" | "ready" | "running"
  | "paused" | "completed" | "error";

export interface LiveTrackingPanelProps {
  /** 无运行段时为空；复位、重载、换模型、后端重启后改变。 */
  runId: string;
  experimentName: string;
  modelName: string;
  status: LiveTrackingStatus;
  /** 指后端通信连接，不代表真机连接。 */
  connected: boolean;
  locale: "zh" | "en";
  jointNames: readonly string[];
  /** 当前 runId 的有界、只读历史，不是待追加的新样本批次。 */
  samples: readonly LiveTrackingSample[];
  /** 后端确认的运行段时间，暂停时不变。 */
  elapsedS: number;
  /** 实验总时长，未知时为 null。 */
  durationS: number | null;
  /** 最近一次真实数据到达距今的秒数，由 A 更新；未知时为 null。 */
  dataAgeS: number | null;
  compensationState: "unavailable" | "disabled" | "enabled";
}
