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
import { 协议版本, type 下行主题名 } from "@生成/契约";

/** 后端下发的一帧 */
export interface WireFrame {
  协议: number;
  主题: string;
  序号?: number;
  墙钟?: number;
  数据: Record<string, unknown>;
}

export interface WireHandshake {
  可用主题: string[];
  广播间隔: number;
  契约?: {
    版本: number;
    下行: { 名: string; 类名: string; 种类: string; 摘要: string }[];
    上行: { 名: string; 类名: string; 种类: string; 摘要: string }[];
  };
}

export interface CommandReceipt {
  /** 与发出命令一一对应；旧后端可能没有，所以保持可选。 */
  请求?: string;
  主题: string;
  通过: boolean;
  说明: string;
}

interface PendingCommand {
  topic: string;
  resolve: (r: CommandReceipt) => void;
}

export type ConnectionState = "连接中" | "已连接" | "已断开";

export interface ConnectionEvent {
  state?: ConnectionState;
  frame?: WireFrame;
  handshake?: WireHandshake;
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
      item.resolve({ 请求: requestId, 主题: item.topic, 通过: false, 说明: description });
    }
  }

  connect(): void {
    this.closed = false;
    this.publish({ state: "连接中" });
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
      this.publish({ state: "已连接" });
    };

    ws.onmessage = (event) => {
      let frame: WireFrame;
      try {
        frame = JSON.parse(event.data as string) as WireFrame;
      } catch {
        this.publish({ error: "收到非 JSON 消息（已忽略）" });
        return;
      }
      if (typeof frame.协议 === "number" && frame.协议 !== 协议版本) {
        this.publish({
          error: `协议版本不一致：后端 ${frame.协议} / 前端 ${协议版本} —— 请刷新页面`,
        });
        return;
      }
      if (frame.主题 === "__问候__") {
        const d = frame.数据 as unknown as WireHandshake;
        this.publish({ handshake: d });
        return;
      }
      if (frame.主题 === "__回执__") {
        const r = frame.数据 as unknown as CommandReceipt;
        let key = typeof r.请求 === "string" && r.请求 ? r.请求 : "";
        // 兼容旧后端：没有请求号时，只能按发送顺序找同主题的第一条。
        if (!key) {
          key = Array.from(this.pendingCommands.entries()).find(([, item]) => item.topic === r.主题)?.[0] ?? "";
        }
        const pending = key ? this.pendingCommands.get(key) : undefined;
        if (pending) {
          this.pendingCommands.delete(key);
          pending.resolve(r);
        }
        this.publish({ receipt: r });
        return;
      }
      this.counts[frame.主题] = (this.counts[frame.主题] ?? 0) + 1;
      this.sequence = frame.序号 ?? this.sequence;
      this.publish({ frame: frame });
    };

    ws.onclose = () => {
      this.socket = null;
      // 旧连接上的命令不可能再收到回执；立即失败比让每条命令各等 4 秒更诚实。
      this.failPendingCommands("连接已断开，命令没有收到回执");
      if (!this.closed) {
        this.publish({ state: "已断开" });
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
  sendCommand(topic: 下行主题名 | string, data: Record<string, unknown>, timeoutMs = 4000): Promise<CommandReceipt> {
    return new Promise((resolve) => {
      this.requestSequence += 1;
      const requestId = `${Date.now().toString(36)}-${this.requestSequence.toString(36)}`;
      const ws = this.socket;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        resolve({ 请求: requestId, 主题: topic, 通过: false, 说明: "还没连上后端" });
        return;
      }
      const timeout = window.setTimeout(() => {
        if (this.pendingCommands.delete(requestId)) {
          resolve({ 请求: requestId, 主题: topic, 通过: false, 说明: "等回执超时（后端可能没在转发命令）" });
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
        ws.send(JSON.stringify({ 请求: requestId, 主题: topic, 数据: data }));
      } catch (error) {
        window.clearTimeout(timeout);
        this.pendingCommands.delete(requestId);
        resolve({ 请求: requestId, 主题: topic, 通过: false, 说明: `发送失败：${String(error)}` });
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
