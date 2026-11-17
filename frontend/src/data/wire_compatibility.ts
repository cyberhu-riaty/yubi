/** v21 transport adapter. Keep legacy keys here; application state uses English fields. */
import { clientFieldAliases, serverFieldAliases } from "@generated/wire_fields";

type FieldAliases = Record<string, string>;
type Payload = Record<string, unknown>;

export interface MessageFrame {
  protocol?: number;
  topic: string;
  sequence?: number;
  timestamp?: number;
  data: Payload;
}

export interface TopicMetadata {
  name: string;
  class_name: string;
  kind: string;
  summary: string;
}

export interface Handshake {
  available_topics: string[];
  broadcast_interval: number;
  contract?: { version: number; server_topics: TopicMetadata[]; client_topics: TopicMetadata[] };
}

export interface CommandReceipt {
  request_id?: string;
  topic: string;
  passed: boolean;
  description: string;
}

export const nestedFieldAliases = {
  diagnosticItem: { "名": "name", "通过": "passed", "说明": "description", "秒": "seconds" },
  pluginItem: {
    "插件": "plugin", "分组": "group", "名称": "name", "版本": "version", "说明": "description",
    "作者": "author", "文件": "file", "被项目使用": "used_by_projects", "当前启用": "enabled", "当前顺序": "order",
  },
  projectAlgorithm: { "名称": "name", "版本": "version", "接管控制": "takes_control", "说明": "description" },
  auditEntry: { "时刻": "timestamp", "类别": "category", "内容": "content", "错误码": "error_code" },
  alertItem: {
    "类型": "kind", "严重度": "severity", "信号": "signal", "开始秒": "start_seconds", "结束秒": "end_seconds",
    "证据": "evidence", "建议": "recommendation", "曲线": "curve", "曲线t": "curve_times", "最后见": "last_seen",
  },
  deploymentItem: { "文件": "file", "说明": "description", "字节": "bytes" },
  identificationResult: { "名称": "name", "标称": "nominal", "辨识值": "identified", "变化": "change" },
  identificationFit: { "前": "before", "后": "after", "标称": "nominal", "辨识后": "identified" },
} satisfies Record<string, FieldAliases>;

// The production plugin emits positional rows; older test/extension backends
// may emit objects. Retain tuple provenance so downloading a result is lossless.
const identificationTuples = new WeakMap<object, unknown[]>();
const identificationColumns = ["name", "nominal", "identified", "change"];

function record(value: unknown): Payload {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Payload;
}

function inverse(aliases: FieldAliases): FieldAliases {
  return Object.fromEntries(Object.entries(aliases).map(([wire, english]) => [english, wire]));
}

function remap(value: unknown, aliases: FieldAliases): Payload {
  const seen = new Set<string>();
  const mapped = Object.fromEntries(Object.entries(record(value)).map(([key, item]) => {
    const name = typeof aliases[key] === "string" ? aliases[key] : key;
    if (seen.has(name)) throw new Error(`Duplicate message field: ${name}`);
    seen.add(name);
    return [name, item];
  }));
  const tuple = identificationTuples.get(record(value));
  if (tuple) identificationTuples.set(mapped, tuple);
  return mapped;
}

function nested(topic: string, payload: Payload, encode: boolean): Payload {
  const result = { ...payload };
  const convert = (field: string, aliases: FieldAliases, array = true) => {
    if (!(field in result) || result[field] == null) return;
    const fields = encode ? inverse(aliases) : aliases;
    if (array) {
      if (Array.isArray(result[field])) result[field] = (result[field] as unknown[]).map((item) =>
        item && typeof item === "object" && !Array.isArray(item) ? remap(item, fields) : item);
    } else result[field] = remap(result[field], fields);
  };
  switch (topic) {
    case "诊断": convert("items", nestedFieldAliases.diagnosticItem); break;
    case "插件目录": convert("plugins", nestedFieldAliases.pluginItem); break;
    case "project.state": convert("algorithms", nestedFieldAliases.projectAlgorithm); break;
    case "设备连接": convert("audit", nestedFieldAliases.auditEntry); break;
    case "告警": convert("active", nestedFieldAliases.alertItem); break;
    case "部署": convert("manifest", nestedFieldAliases.deploymentItem); break;
    case "辨识状态":
      if (Array.isArray(result.results)) result.results = result.results.map((item) => {
        if (!encode && Array.isArray(item)) {
          const row = Object.fromEntries(identificationColumns.map((key, index) => [key, item[index]]));
          identificationTuples.set(row, item.slice());
          return row;
        }
        const tuple = identificationTuples.get(record(item));
        if (encode && tuple) return tuple.map((value, index) =>
          index < identificationColumns.length ? record(item)[identificationColumns[index]] : value);
        return item && typeof item === "object" && !Array.isArray(item)
          ? remap(item, encode ? inverse(nestedFieldAliases.identificationResult) : nestedFieldAliases.identificationResult)
          : item;
      });
      convert("fit", nestedFieldAliases.identificationFit, false);
      break;
  }
  return result;
}

export function decodeServerPayload(topic: string, value: unknown): Payload {
  return nested(topic, remap(value, serverFieldAliases[topic] ?? {}), false);
}

/** Preserve the existing downloaded JSON format when exporting normalized snapshots. */
export function encodeServerPayload(topic: string, value: unknown): Payload {
  return remap(nested(topic, record(value), true), inverse(serverFieldAliases[topic] ?? {}));
}

export function decodeFrame(value: unknown): MessageFrame {
  const frame = record(value);
  if (typeof frame["主题"] !== "string") throw new Error("Message topic must be a string");
  return {
    protocol: frame["协议"] as number | undefined,
    topic: frame["主题"], sequence: frame["序号"] as number | undefined,
    timestamp: frame["墙钟"] as number | undefined, data: record(frame["数据"]),
  };
}

export function decodeHandshake(value: unknown): Handshake {
  const raw = remap(value, { "可用主题": "available_topics", "广播间隔": "broadcast_interval", "契约": "contract" });
  if (raw.contract) {
    const contract = remap(raw.contract, { "版本": "version", "下行": "server_topics", "上行": "client_topics" });
    const fields = { "名": "name", "类名": "class_name", "种类": "kind", "摘要": "summary" };
    for (const key of ["server_topics", "client_topics"]) {
      if (Array.isArray(contract[key])) contract[key] = (contract[key] as unknown[]).map((item) => remap(item, fields));
    }
    raw.contract = contract;
  }
  return raw as unknown as Handshake;
}

export function decodeReceipt(value: unknown): CommandReceipt {
  return remap(value, { "请求": "request_id", "主题": "topic", "通过": "passed", "说明": "description" }) as unknown as CommandReceipt;
}

export function encodeCommand(requestId: string, topic: string, data: Payload): string {
  const payload = remap(data, inverse(clientFieldAliases[topic] ?? {}));
  return JSON.stringify({ "请求": requestId, "主题": topic, "数据": payload });
}

interface NativeLogEntry {
  timestamp: number;
  level: string;
  source: string;
  text: string;
  details?: string;
  module?: string;
  plugins?: string;
  joint?: number;
}

const legacyLogLevels: Record<string, string> = { info: "信息", warning: "注意", error: "错误" };
const legacyLogSources: Record<string, string> = {
  connection: "连接", handshake: "握手", receipt: "回执", error: "错误", frontend: "前端",
  console: "控制台", planning: "规划", diagnostics: "诊断",
};

export const legacyLogLevel = (value: string): string => legacyLogLevels[value] ?? value;
export const legacyLogSource = (value: string): string => legacyLogSources[value] ?? value;

export function decodeNativeLogLevel(value: string): string {
  return inverse(legacyLogLevels)[value] ?? value;
}

export function encodeNativeLog(entry: NativeLogEntry): Payload {
  return {
    "墙钟": entry.timestamp, "等级": legacyLogLevel(entry.level), "来源": legacyLogSource(entry.source), "文本": entry.text,
    "细节": entry.details ?? "", "模块": entry.module ?? "", "插件": entry.plugins ?? "", "关节": entry.joint ?? null,
  };
}

export function encodeNativeLogState(entries: NativeLogEntry[], total: number, filter: string, level: string): Payload {
  return { "类型": "日志状态", "行": entries.slice(-500).map(encodeNativeLog), "总数": total, "筛选": filter, "等级": legacyLogLevel(level) };
}

export function postNativeLog(payload: Payload): void {
  try {
    const host = window as unknown as {
      webkit?: { messageHandlers?: Record<string, { postMessage?: (value: unknown) => void }> };
    };
    host.webkit?.messageHandlers?.["驭臂日志"]?.postMessage?.(payload);
  } catch {
    // The browser also runs without a native host.
  }
}
