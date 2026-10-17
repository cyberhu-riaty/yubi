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
export interface 帧 {
  协议: number;
  主题: string;
  序号?: number;
  墙钟?: number;
  数据: Record<string, unknown>;
}

export interface 握手 {
  可用主题: string[];
  广播间隔: number;
  契约?: {
    版本: number;
    下行: { 名: string; 类名: string; 种类: string; 摘要: string }[];
    上行: { 名: string; 类名: string; 种类: string; 摘要: string }[];
  };
}

export interface 回执 {
  主题: string;
  通过: boolean;
  说明: string;
}

export type 连接状态 = "连接中" | "已连接" | "已断开";

export interface 连接事件 {
  状态?: 连接状态;
  帧?: 帧;
  握手?: 握手;
  回执?: 回执;
  错误?: string;
}

/** 一条曲线的采样点 */
export interface 采样点 {
  t: number;
  v: number;
}

const 重连延迟 = [300, 600, 1200, 2400, 4000, 5000];

export class 连接 {
  private 套接字: WebSocket | null = null;
  private 序号 = -1;
  private 重试 = 0;
  private 关掉了 = false;
  private 定时器: number | null = null;
  private 待回执 = new Map<string, (r: 回执) => void>();
  private 监听 = new Set<(e: 连接事件) => void>();
  /** 每个主题收了多少帧 —— 界面上直接显示，一眼看出哪条链路没通 */
  readonly 计数: Record<string, number> = {};
  readonly 速率: Record<string, number> = {};
  private 上秒计数: Record<string, number> = {};
  private 速率定时器: number | null = null;

  private readonly 地址: string;

  constructor(地址: string) {
    this.地址 = 地址;
  }

  订阅(回调: (e: 连接事件) => void): () => void {
    this.监听.add(回调);
    return () => this.监听.delete(回调);
  }

  private 广播(e: 连接事件): void {
    for (const f of this.监听) {
      try {
        f(e);
      } catch (异常) {
        // 一个订阅者出错不能拖垮整条连接
        console.error("[连接] 订阅者出错", 异常);
      }
    }
  }

  连(): void {
    this.关掉了 = false;
    this.广播({ 状态: "连接中" });
    let 套: WebSocket;
    try {
      套 = new WebSocket(this.地址);
    } catch (异常) {
      this.广播({ 错误: `建立连接失败：${String(异常)}` });
      this.排重连();
      return;
    }
    this.套接字 = 套;

    套.onopen = () => {
      this.重试 = 0;
      this.广播({ 状态: "已连接" });
    };

    套.onmessage = (事件) => {
      let 帧: 帧;
      try {
        帧 = JSON.parse(事件.data as string) as 帧;
      } catch {
        this.广播({ 错误: "收到非 JSON 消息（已忽略）" });
        return;
      }
      if (typeof 帧.协议 === "number" && 帧.协议 !== 协议版本) {
        this.广播({
          错误: `协议版本不一致：后端 ${帧.协议} / 前端 ${协议版本} —— 请刷新页面`,
        });
        return;
      }
      if (帧.主题 === "__问候__") {
        const d = 帧.数据 as unknown as 握手;
        this.广播({ 握手: d });
        return;
      }
      if (帧.主题 === "__回执__") {
        const r = 帧.数据 as unknown as 回执;
        const 等 = this.待回执.get(r.主题);
        if (等) {
          this.待回执.delete(r.主题);
          等(r);
        }
        this.广播({ 回执: r });
        return;
      }
      this.计数[帧.主题] = (this.计数[帧.主题] ?? 0) + 1;
      this.序号 = 帧.序号 ?? this.序号;
      this.广播({ 帧 });
    };

    套.onclose = () => {
      this.套接字 = null;
      if (!this.关掉了) {
        this.广播({ 状态: "已断开" });
        this.排重连();
      }
    };

    套.onerror = () => {
      // 具体信息浏览器不给，交给 onclose 处理重连
      try {
        套.close();
      } catch {
        /* 忽略 */
      }
    };

    if (this.速率定时器 === null) {
      this.速率定时器 = window.setInterval(() => {
        for (const k of Object.keys(this.计数)) {
          this.速率[k] = (this.计数[k] ?? 0) - (this.上秒计数[k] ?? 0);
        }
        this.上秒计数 = { ...this.计数 };
      }, 1000);
    }
  }

  private 排重连(): void {
    if (this.关掉了 || this.定时器 !== null) return;
    const 延迟 = 重连延迟[Math.min(this.重试, 重连延迟.length - 1)];
    this.重试 += 1;
    this.定时器 = window.setTimeout(() => {
      this.定时器 = null;
      this.连();
    }, 延迟);
  }

  /** 发一条命令，等回执（超时算失败 —— 不能无限等） */
  发命令(主题: 下行主题名 | string, 数据: Record<string, unknown>, 超时毫秒 = 4000): Promise<回执> {
    return new Promise((兑现) => {
      const 套 = this.套接字;
      if (!套 || 套.readyState !== WebSocket.OPEN) {
        兑现({ 主题, 通过: false, 说明: "还没连上后端" });
        return;
      }
      const 兜底 = window.setTimeout(() => {
        if (this.待回执.delete(主题)) {
          兑现({ 主题, 通过: false, 说明: "等回执超时（后端可能没在转发命令）" });
        }
      }, 超时毫秒);
      this.待回执.set(主题, (r) => {
        window.clearTimeout(兜底);
        兑现(r);
      });
      try {
        套.send(JSON.stringify({ 主题, 数据 }));
      } catch (异常) {
        window.clearTimeout(兜底);
        this.待回执.delete(主题);
        兑现({ 主题, 通过: false, 说明: `发送失败：${String(异常)}` });
      }
    });
  }

  get 最新序号(): number {
    return this.序号;
  }

  get 已连接(): boolean {
    return this.套接字?.readyState === WebSocket.OPEN;
  }

  关(): void {
    this.关掉了 = true;
    if (this.速率定时器 !== null) window.clearInterval(this.速率定时器);
    this.速率定时器 = null;
    try {
      this.套接字?.close();
    } catch {
      /* 忽略 */
    }
  }
}

/** 按当前页面位置推出后端地址（同源，所以不需要配置项） */
export function 猜地址(): string {
  const 协议 = location.protocol === "https:" ? "wss:" : "ws:";
  return `${协议}//${location.host}/`;
}
