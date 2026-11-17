/**
 * 连接.ts —— 与 Python 侧 `Web桥` 的 WebSocket 连接（P1 的数据入口）
 *
 * 设计要点（都是踩过才知道的）：
 *  ① **latest-wins**：后端发的快照是"最新覆盖"语义，前端也按这个存 ——
 *     不为每条消息建队列，UI 永远只画最新一帧。这与官方 `Snapshot` 语义一致。
 *  ② **重连**：界面的数据源断掉是常态（后端重启、窗口重开），必须自愈，
 *     并且重连成功要**重新同步契约**（后端可能升级了）。
 *  ③ **命令要等回执**：命令是要动设备的，不能"发了就算成功"。
 *     所以 `发命令` 返回一个 Promise，由 `__回执__` 兑现。
 *  ④ 协议版本不一致要**明说**，而不是静默显示错数据。
 */
import { PROTOCOL_VERSION, type ClientTopic } from "@generated/contract";

import {
  decodeFrame, decodeHandshake, decodeReceipt, decodeServerPayload, encodeCommand,
  type MessageFrame, type Handshake, type CommandReceipt,
} from "./wire_compatibility";
export type { MessageFrame, Handshake, CommandReceipt } from "./wire_compatibility";

interface PendingCommand {
  topic: string;
  resolve: (r: CommandReceipt) => void;
}

export type ConnectionState = "connecting" | "connected" | "disconnected";

export interface ConnectionEvent {
  state?: ConnectionState;
  frame?: MessageFrame;
  handshake?: Handshake;
  receipt?: CommandReceipt;
  error?: string;
}

/** 一条曲线的采样点 */
export interface SamplePoint {
  t: number;
  v: number;
}

const RECONNECT_DELAYS = [300, 600, 1200, 2400, 4000, 5000];

export class BackendConnection {
  private socket: WebSocket | null = null;
  private sequence = -1;
  private retryCount = 0;
  private closed = false;
  private reconnectTimer: number | null = null;
  /** 请求号 → 等待项。不能按主题存：同类命令并发时会互相覆盖。 */
  private pendingCommands = new Map<string, PendingCommand>();
  private requestSequence = 0;
  private listeners = new Set<(e: ConnectionEvent) => void>();
  /** 每个主题收了多少帧 —— 界面上直接显示，一眼看出哪条链路没通 */
  readonly counts: Record<string, number> = {};
  readonly rates: Record<string, number> = {};
  private previousCounts: Record<string, number> = {};
  private rateTimer: number | null = null;

  private readonly address: string;

  constructor(address: string) {
    this.address = address;
  }

  subscribe(callback: (e: ConnectionEvent) => void): () => void {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  private publish(e: ConnectionEvent): void {
    for (const f of this.listeners) {
      try {
        f(e);
      } catch (error) {
        // 一个订阅者出错不能拖垮整条连接
        console.error("[连接] 订阅者出错", error);
      }
    }
  }

  private failPendingCommands(description: string): void {
    for (const [requestId, item] of this.pendingCommands) {
      this.pendingCommands.delete(requestId);
      item.resolve({ request_id: requestId, topic: item.topic, passed: false, description: description });
    }
  }

  connect(): void {
    this.closed = false;
    this.publish({ state: "connecting" });
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.address);
    } catch (error) {
      this.publish({ error: `建立连接失败：${String(error)}` });
      this.scheduleReconnect();
      return;
    }
    this.socket = ws;

    ws.onopen = () => {
      this.retryCount = 0;
      this.publish({ state: "connected" });
    };

    ws.onmessage = (event) => {
      let frame: MessageFrame;
      try {
        frame = decodeFrame(JSON.parse(event.data as string));
      } catch {
        this.publish({ error: "收到非 JSON 消息（已忽略）" });
        return;
      }
      if (typeof frame.protocol === "number" && frame.protocol !== PROTOCOL_VERSION) {
        this.publish({
          error: `协议版本不一致：后端 ${frame.protocol} / 前端 ${PROTOCOL_VERSION} —— 请刷新页面`,
        });
        return;
      }
      try {
        if (frame.topic === "__问候__") {
          const d = decodeHandshake(frame.data);
          this.publish({ handshake: d });
          return;
        }
        if (frame.topic === "__回执__") {
          const r = decodeReceipt(frame.data);
          let key = typeof r.request_id === "string" && r.request_id ? r.request_id : "";
          // 兼容旧后端：没有请求号时，只能按发送顺序找同主题的第一条。
          if (!key) {
            key = Array.from(this.pendingCommands.entries()).find(([, item]) => item.topic === r.topic)?.[0] ?? "";
          }
          const pending = key ? this.pendingCommands.get(key) : undefined;
          if (pending) {
            this.pendingCommands.delete(key);
            pending.resolve(r);
          }
          this.publish({ receipt: r });
          return;
        }
        frame.data = decodeServerPayload(frame.topic, frame.data);
      } catch (error) {
        this.publish({ error: `收到无效消息（已忽略）：${String(error)}` });
        return;
      }
      this.counts[frame.topic] = (this.counts[frame.topic] ?? 0) + 1;
      this.sequence = frame.sequence ?? this.sequence;
      this.publish({ frame: frame });
    };

    ws.onclose = () => {
      this.socket = null;
      // 旧连接上的命令不可能再收到回执；立即失败比让每条命令各等 4 秒更诚实。
      this.failPendingCommands("连接已断开，命令没有收到回执");
      if (!this.closed) {
        this.publish({ state: "disconnected" });
        this.scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // 具体信息浏览器不给，交给 onclose 处理重连
      try {
        ws.close();
      } catch {
        /* 忽略 */
      }
    };

    if (this.rateTimer === null) {
      this.rateTimer = window.setInterval(() => {
        for (const k of Object.keys(this.counts)) {
          this.rates[k] = (this.counts[k] ?? 0) - (this.previousCounts[k] ?? 0);
        }
        this.previousCounts = { ...this.counts };
      }, 1000);
    }
  }

  private scheduleReconnect(): void {
    if (this.closed || this.reconnectTimer !== null) return;
    const delay = RECONNECT_DELAYS[Math.min(this.retryCount, RECONNECT_DELAYS.length - 1)];
    this.retryCount += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  /** 发一条命令，等回执（超时算失败 —— 不能无限等） */
  sendCommand(topic: ClientTopic | string, data: Record<string, unknown>, timeoutMs = 4000): Promise<CommandReceipt> {
    return new Promise((resolve) => {
      this.requestSequence += 1;
      const requestId = `${Date.now().toString(36)}-${this.requestSequence.toString(36)}`;
      const ws = this.socket;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        resolve({ request_id: requestId, topic: topic, passed: false, description: "还没连上后端" });
        return;
      }
      const timeout = window.setTimeout(() => {
        if (this.pendingCommands.delete(requestId)) {
          resolve({ request_id: requestId, topic: topic, passed: false, description: "等回执超时（后端可能没在转发命令）" });
        }
      }, timeoutMs);
      this.pendingCommands.set(requestId, {
        topic: topic,
        resolve: (r) => {
          window.clearTimeout(timeout);
          resolve(r);
        },
      });
      try {
        ws.send(encodeCommand(requestId, topic, data));
      } catch (error) {
        window.clearTimeout(timeout);
        this.pendingCommands.delete(requestId);
        resolve({ request_id: requestId, topic: topic, passed: false, description: `发送失败：${String(error)}` });
      }
    });
  }

  get latestSequence(): number {
    return this.sequence;
  }

  get connected(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  close(): void {
    this.closed = true;
    this.failPendingCommands("连接已关闭，命令没有收到回执");
    if (this.rateTimer !== null) window.clearInterval(this.rateTimer);
    this.rateTimer = null;
    try {
      this.socket?.close();
    } catch {
      /* 忽略 */
    }
  }
}

/** 按当前页面位置推出后端地址（同源，所以不需要配置项） */
export function guessBackendUrl(): string {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/`;
}
