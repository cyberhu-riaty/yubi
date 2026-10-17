/**
 * 曲线.tsx —— 手绘 canvas 折线图（**不引图表库**）。
 *
 * 数据源：`s.曲线` —— `{曲线名: 采样点[]}`，点是 `{t: 墙钟秒, v: 数值}`，
 * 由后端下行主题「指标」产生（`数据/仓库.ts` 的环形缓冲，最近 120 秒）。
 *
 * 这个组件只做四件事，多一件都不做：
 *   ① 多序列同图，每条一个颜色（颜色取自皮肤的 `--palette-N`，换肤自动变）
 *   ② Y 轴**按当前窗口内的真实数据自动缩放**（不写死 0..1，也不外推）
 *   ③ X 轴固定 120 秒墙钟窗口（仓库的淘汰窗口就是 120 秒，两边对齐）
 *   ④ 鼠标悬停暂停刷新并画十字线，读数取**最近的真实采样点**（不插值编数）
 *
 * ⚠️ 这里**不做**平滑、不做外推、不做滤波：图上的每一个像素都必须能追到一个真实采样点。
 */
import { useEffect, useMemo, useRef, useState, type PointerEvent as 指针事件 } from "react";
import type { 采样点 } from "../数据/连接";
import { 数, use取 } from "../视图/文案";

export interface 曲线参数 {
  /** `{名称: 点[]}`；空对象 = 还没收到任何指标帧 */
  数据: Record<string, 采样点[]>;
  /** 只画这些（未给出 = 全画） */
  显示?: Set<string>;
  /** 时间窗（秒） */
  窗口?: number;
  高?: number;
  /** 悬停暂停状态变化时通知外面（图例上要写"暂停中"） */
  on暂停?: (暂停: boolean) => void;
}

/** 从皮肤变量里算配色（**不缓存** CSS 变量值：换肤时必须跟着变） */
export function 取配色(名序: number): string {
  return `var(--palette-${(名序 % 8) + 1})`;
}

interface 悬停 {
  x: number;
  y: number;
  时间: number;
}

export function 曲线({ 数据, 显示, 窗口 = 120, 高 = 200, on暂停 }: 曲线参数) {
  const t = use取();
  const 画布 = useRef<HTMLCanvasElement | null>(null);
  const 盒 = useRef<HTMLDivElement | null>(null);
  const [宽, 设宽] = useState(600);
  const [悬, 设悬] = useState<悬停 | null>(null);
  // 每帧最多重画一次（30 Hz 数据 + 悬停事件都会来敲门）
  const 排队 = useRef(false);

  const 名们 = useMemo(() => Object.keys(数据), [数据]);
  const 要画的 = useMemo(() => {
    const 集 = 名们.filter((n) => (显示 ? 显示.has(n) : true));
    // 有真实点的排前面，全空的排在后面（不让空曲线挤掉有数据的）
    return 集.sort((a, b) => (数据[b]?.length ?? 0) - (数据[a]?.length ?? 0));
  }, [名们, 显示, 数据]);

  // 容器宽度跟随（ResizeObserver：拖分隔条时图要跟着变宽，不能留白边）
  useEffect(() => {
    const 元素 = 盒.current;
    if (!元素) return;
    const 观 = new ResizeObserver(() => 设宽(Math.max(160, 元素.clientWidth)));
    观.observe(元素);
    设宽(Math.max(160, 元素.clientWidth));
    return () => 观.disconnect();
  }, []);

  // 悬停状态要通知外面（图例上写"暂停中"）
  useEffect(() => {
    on暂停?.(悬 !== null);
  }, [悬, on暂停]);

  useEffect(() => {
    if (排队.current) return;
    排队.current = true;
    const 句柄 = requestAnimationFrame(() => {
      排队.current = false;
      画();
    });
    return () => {
      cancelAnimationFrame(句柄);
      排队.current = false;
    };

    function 画() {
      const 元素 = 画布.current;
      if (!元素) return;
      const 比 = window.devicePixelRatio || 1;
      const 图高 = 高;
      if (元素.width !== Math.round(宽 * 比) || 元素.height !== Math.round(图高 * 比)) {
        元素.width = Math.round(宽 * 比);
        元素.height = Math.round(图高 * 比);
      }
      const 笔 = 元素.getContext("2d");
      if (!笔) return;
      const 样 = getComputedStyle(document.documentElement);
      const 取v = (名: string, 兜底: string) => 样.getPropertyValue(名).trim() || 兜底;

      笔.setTransform(比, 0, 0, 比, 0, 0);
      笔.clearRect(0, 0, 宽, 图高);

      const 左 = 52;
      const 右 = 8;
      const 上 = 8;
      const 下 = 20;
      const 图宽 = Math.max(10, 宽 - 左 - 右);
      const 图高2 = Math.max(10, 图高 - 上 - 下);

      笔.fillStyle = 取v("--plot-bg", "#000");
      笔.fillRect(0, 0, 宽, 图高);

      // ---- 时间范围：窗口右端 = 所有序列里最新的那个点 ----
      let 最晚 = 0;
      for (const n of 要画的) {
        const 点 = 数据[n];
        if (点 && 点.length) 最晚 = Math.max(最晚, 点[点.length - 1].t);
      }
      if (!最晚) {
        // 一个点都没有：不画坐标轴（避免看起来"有坐标系只是没数据"的暗示）
        笔.fillStyle = 取v("--plot-text", "#888");
        笔.font = "12px " + 取v("--font-mono", "monospace");
        笔.fillText(t("曲线.空"), 左, 图高 / 2);
        return;
      }
      /*
       * X 轴窗口：**不超过**数据真实跨度。
       * 只跑了 20 秒的时候画满 120 秒，右边那一小撮挤成一根柱子 ——
       * 看着像"信号是脉冲"，其实是"窗口开太大"。所以取 min(窗口, 真实跨度)，
       * 但留一个 10 秒下限，免得刚收到两个点就横轴抖成一条线。
       */
      let 跨度 = 窗口;
      for (const n of 要画的) {
        const 点 = 数据[n];
        if (点 && 点.length) 跨度 = Math.min(跨度, Math.max(10, 最晚 - 点[0].t));
      }
      const 最早 = 最晚 - 跨度;

      // ---- Y 范围：只看窗口内的真实点 ----
      let 大 = -Infinity;
      let 小 = Infinity;
      for (const n of 要画的) {
        const 点 = 数据[n];
        if (!点) continue;
        for (let i = 点.length - 1; i >= 0; i -= 1) {
          const p = 点[i];
          if (p.t < 最早) break;
          if (p.v > 大) 大 = p.v;
          if (p.v < 小) 小 = p.v;
        }
      }
      const 有范围 = Number.isFinite(大) && Number.isFinite(小);
      if (!有范围) {
        大 = 1;
        小 = -1;
      } else if (大 - 小 < 1e-12) {
        // 全平的一条线：给它一点可视厚度，但**不改数据**
        const 中 = (大 + 小) / 2;
        const 幅 = Math.max(Math.abs(中) * 0.05, 0.5);
        大 = 中 + 幅;
        小 = 中 - 幅;
      } else {
        const 边 = (大 - 小) * 0.08;
        大 += 边;
        小 -= 边;
      }

      const X = (时间: number) => 左 + ((时间 - 最早) / (最晚 - 最早)) * 图宽;
      const Y = (值: number) => 上 + (1 - (值 - 小) / (大 - 小)) * 图高2;

      // ---- 网格 + 刻度 ----
      笔.strokeStyle = 取v("--plot-grid", "#333");
      笔.lineWidth = 1;
      笔.fillStyle = 取v("--plot-tick", "#888");
      笔.font = "10px " + 取v("--font-mono", "monospace");
      笔.textAlign = "right";
      笔.textBaseline = "middle";
      for (let i = 0; i <= 4; i += 1) {
        const 值 = 小 + ((大 - 小) * i) / 4;
        const y = Y(值);
        笔.beginPath();
        笔.moveTo(左, y);
        笔.lineTo(左 + 图宽, y);
        笔.stroke();
        笔.fillText(数(值, 3), 左 - 4, y);
      }
      笔.textAlign = "center";
      笔.textBaseline = "top";
      const 档 = 跨度 <= 30 ? 5 : 15;
      for (let 秒 = 0; 秒 <= 跨度 + 0.001; 秒 += 档) {
        const 时间 = 最晚 - 秒;
        if (时间 < 最早) break;
        const x = X(时间);
        笔.beginPath();
        笔.moveTo(x, 上);
        笔.lineTo(x, 上 + 图高2);
        笔.stroke();
        笔.fillText(秒 === 0 ? "0" : `-${秒}s`, x, 上 + 图高2 + 3);
      }
      笔.strokeStyle = 取v("--plot-border", "#444");
      笔.strokeRect(左, 上, 图宽, 图高2);

      // ---- 折线（每条曲线一段路径；分段的断点由"时间跳变"决定，不外推） ----
      let 序 = 0;
      for (const n of 名们) {
        const 画不画 = 要画的.includes(n);
        const 颜色序 = 序;
        序 += 1;
        if (!画不画) continue;
        const 点 = 数据[n];
        if (!点 || 点.length < 1) continue;
        笔.strokeStyle = 取v(`--palette-${(颜色序 % 8) + 1}`, "#888");
        笔.lineWidth = 1.5;
        笔.beginPath();
        let 起 = false;
        for (let i = 点.length - 1; i >= 0; i -= 1) {
          const p = 点[i];
          if (p.t < 最早) break;
          const x = X(p.t);
          const y = Y(p.v);
          if (!起) {
            笔.moveTo(x, y);
            起 = true;
          } else {
            笔.lineTo(x, y);
          }
        }
        笔.stroke();
      }

      // ---- 十字线 + 最近真实点 ----
      if (悬) {
        笔.strokeStyle = 取v("--plot-cross", "#888");
        笔.setLineDash([3, 3]);
        笔.beginPath();
        笔.moveTo(悬.x, 上);
        笔.lineTo(悬.x, 上 + 图高2);
        笔.stroke();
        笔.setLineDash([]);
        笔.font = "10px " + 取v("--font-mono", "monospace");
        笔.textAlign = "left";
        笔.textBaseline = "top";
        let 行 = 0;
        let 序2 = 0;
        for (const n of 名们) {
          const 颜色序 = 序2;
          序2 += 1;
          if (!要画的.includes(n)) continue;
          const 点 = 数据[n];
          if (!点 || !点.length) continue;
          // 找离 悬.时间 最近的**真实**点（不插值：图上读到的每个数都是后端报来的）
          let 最 = 点[点.length - 1];
          let 距 = Infinity;
          for (let i = 点.length - 1; i >= 0; i -= 1) {
            const d = Math.abs(点[i].t - 悬.时间);
            if (d < 距) {
              距 = d;
              最 = 点[i];
            } else if (d > 距) {
              // 越过最近点后距离只会变大（点按时间递增）
              break;
            }
          }
          const y = Y(最.v);
          笔.fillStyle = 取v(`--palette-${(颜色序 % 8) + 1}`, "#888");
          笔.beginPath();
          笔.arc(X(最.t), y, 2.5, 0, Math.PI * 2);
          笔.fill();
          笔.fillRect(左 + 6, 上 + 6 + 行 * 12, 8, 2);
          笔.fillStyle = 取v("--plot-text", "#ccc");
          笔.fillText(`${n} = ${数(最.v, 4)}`, 左 + 18, 上 + 2 + 行 * 12);
          行 += 1;
        }
      }
    }
  }, [数据, 要画的, 名们, 宽, 高, 窗口, 悬, t]);

  const 动 = (e: 指针事件<HTMLCanvasElement>) => {
    const 元素 = 画布.current;
    if (!元素) return;
    const r = 元素.getBoundingClientRect();
    const x = e.clientX - r.left;
    const 左 = 52;
    const 图宽 = Math.max(10, r.width - 左 - 8);
    const 比例 = Math.min(1, Math.max(0, (x - 左) / 图宽));
    let 最晚 = 0;
    for (const n of 名们) {
      const 点 = 数据[n];
      if (点 && 点.length) 最晚 = Math.max(最晚, 点[点.length - 1].t);
    }
    if (!最晚) return;
    设悬({ x, y: e.clientY - r.top, 时间: 最晚 - (1 - 比例) * 窗口 });
  };

  return (
    <div ref={盒} className="w-full">
      <canvas
        ref={画布}
        style={{ width: "100%", height: 高, display: "block", cursor: "crosshair" }}
        onPointerMove={动}
        onPointerLeave={() => 设悬(null)}
        role="img"
        aria-label={t("验证.曲线")}
      />
    </div>
  );
}
