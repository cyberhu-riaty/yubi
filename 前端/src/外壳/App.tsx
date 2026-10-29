/**
 * App.tsx —— 组合根（composition root）。
 *
 * 它只做四件事，一行数据逻辑都不写：
 *   ① 起连接：`起连接()`（数据入口）+ `起日志()`（控制台事件源），都在 `useEffect` 里，
 *      清理函数按注册的反序摘干净 —— 不留悬挂的 WebSocket、定时器、事件监听
 *   ② 三格布局 + **可拖动分隔条**（侧栏宽度 / 控制台高度）
 *   ③ 任务流的当前步骤（只换左侧上下文；中区常驻不切换）
 *   ④ 快捷键：`1..5` 跳步骤、`` ` `` 收起/展开侧栏、`[`/`]` 切控制台页签
 *
 * 布局（与 `约定.md` 的图一致）：
 *
 *   ┌──────────────────────────────────────────────┐
 *   │ 活动栏 │ 侧栏 ║ 中区（3D 占位 + 浮层）        │
 *   │        │      ║───────────────────────────────│
 *   │        │      ║ 控制台 [输出][事件][问题]      │
 *   ├──────────────────────────────────────────────┤
 *   │ 状态栏：物理·仿真时间·实时倍率·帧率·连接     │
 *   └──────────────────────────────────────────────┘
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { 起连接 } from "../数据/仓库";
import { 起日志 } from "../数据/日志";
import { 活动栏 } from "./活动栏";
import { 侧栏 } from "./侧栏";
import { 中区, 仿真工具栏 } from "./中区";
import { 控制台, 控制台召回, type 控制台页签 } from "./控制台";
import { 状态栏 } from "./状态栏";
import { 提示区 } from "./提示区";
import { 任务步骤, type 步骤id } from "./任务流";
import { 跳步事件 } from "./跳步";


const 存储键 = "驭臂.外壳";

interface 外壳偏好 {
  侧栏宽: number;
  控制台高: number;
  侧栏开: boolean;
}

// 左 Web / 右 3D 之后，网页面板是 576×920 左右的一块窄面板：侧栏 330 是
// 「模型 + 项目 + 兼容性」三块内容都还能读的宽度；控制台 190 能放约 4 条
// 两行日志。两个值都可拖，双击分隔条回到这里。
const 默认偏好: 外壳偏好 = { 侧栏宽: 330, 控制台高: 150, 侧栏开: true };

const 侧栏界 = { 最小: 180, 最大: 640 };
const 控制台界 = { 最小: 90, 最大: 620 };
const 控制台页签序: 控制台页签[] = ["输出", "事件", "问题", "诊断"];

/**
 * 窗口很窄时，硬撑两个可拖动格会出现"负宽"和重叠。
 * 这不是猜的：侧栏最小 180 + 活动栏 48 已经占掉 228，再多就挤没中区了。
 */
const 可用 = () => ({
  宽: typeof window === "undefined" ? Number.POSITIVE_INFINITY : window.innerWidth,
  高: typeof window === "undefined" ? Number.POSITIVE_INFINITY : window.innerHeight,
});

function 读偏好(): 外壳偏好 {
  try {
    const 原 = window.localStorage.getItem(存储键);
    if (!原) return 默认偏好;
    const 解 = JSON.parse(原) as Partial<外壳偏好>;
    return {
      侧栏宽: 夹(解.侧栏宽 ?? 默认偏好.侧栏宽, 侧栏界.最小, 侧栏界.最大),
      控制台高: 夹(解.控制台高 ?? 默认偏好.控制台高, 控制台界.最小, 控制台界.最大),
      侧栏开: 解.侧栏开 ?? 默认偏好.侧栏开,
    };
  } catch {
    return 默认偏好;
  }
}

function 夹(值: number, 小: number, 大: number): number {
  return Math.min(大, Math.max(小, Math.round(值)));
}

/** 写偏好（写不进去也不影响使用） */
function 存偏好(偏: 外壳偏好): void {
  try {
    window.localStorage.setItem(存储键, JSON.stringify(偏));
  } catch {
    /* 隐私模式：忽略 */
  }
}

/**
 * 分隔条：鼠标拖 + 键盘调。
 * - 拖动用 `setPointerCapture`，所以指针移出窗口也不会丢事件；
 * - 键盘：方向键挪 8（Shift 挪 32），Home/End 到两端；
 * - 失焦/松开都会清掉拖动状态（不会"粘住"鼠标）。
 */
function 分隔条({
  方向,
  值,
  界,
  步骤 = 8,
  大步 = 32,
  标题,
  on改,
  on双击,
  反向 = false,
}: {
  方向: "横" | "纵";
  值: number;
  界: { 最小: number; 最大: number };
  步骤?: number;
  大步?: number;
  标题: string;
  on改: (下一个: number) => void;
  on双击?: () => void;
  /** 值锚在"末端"时置 true（例如底部控制台的高度）：鼠标向下 = 高度变小 */
  反向?: boolean;
}) {
  const [拖动, 设拖动] = useState(false);
  const 基点 = useRef({ 坐标: 0, 值: 0 });

  useEffect(() => {
    if (!拖动) return;
    const 停 = () => 设拖动(false);
    window.addEventListener("pointerup", 停);
    window.addEventListener("pointercancel", 停);
    return () => {
      window.removeEventListener("pointerup", 停);
      window.removeEventListener("pointercancel", 停);
    };
  }, [拖动]);

  const 键盘 = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const 横 = 方向 === "横";
    const 减 = 横 ? "ArrowLeft" : "ArrowUp";
    const 加 = 横 ? "ArrowRight" : "ArrowDown";
    if (e.key === 减 || e.key === 加) {
      e.preventDefault();
      const 幅 = e.shiftKey ? 大步 : 步骤;
      // 反向的“纵”值锚在底部：方向键也要按视觉方向走。
      // 正常：右/下 = +值；反向：下 = -值、上 = +值。
      const 值增 = e.key === 加 ? (反向 ? -幅 : 幅) : (反向 ? 幅 : -幅);
      on改(夹(值 + 值增, 界.最小, 界.最大));
      return;
    }
    if (e.key === "Home") {
      e.preventDefault();
      on改(界.最小);
      return;
    }
    if (e.key === "End") {
      e.preventDefault();
      on改(界.最大);
    }
  };

  const 样式 = 方向 === "横" ? { width: 5, cursor: "col-resize" } : { height: 5, cursor: "row-resize" };

  return (
    <div
      role="separator"
      aria-orientation={方向 === "横" ? "vertical" : "horizontal"}
      aria-label={标题}
      aria-valuenow={Math.round(值)}
      aria-valuemin={界.最小}
      aria-valuemax={界.最大}
      tabIndex={0}
      title={标题}
      data-拖动={拖动 ? "1" : "0"}
      className="分隔条"
      style={样式}
      onDoubleClick={on双击}
      onKeyDown={键盘}
      onPointerDown={(e) => {
        e.preventDefault();
        e.currentTarget.setPointerCapture?.(e.pointerId);
        基点.current = { 坐标: 方向 === "横" ? e.clientX : e.clientY, 值 };
        设拖动(true);
      }}
      onPointerMove={(e) => {
        if (!拖动) return;
        const 现 = 方向 === "横" ? e.clientX : e.clientY;
        const 增量 = (现 - 基点.current.坐标) * (反向 ? -1 : 1);
        on改(夹(基点.current.值 + 增量, 界.最小, 界.最大));
      }}
      onPointerUp={(e) => {
        e.currentTarget.releasePointerCapture?.(e.pointerId);
        设拖动(false);
      }}
    />
  );
}

export function App() {
  const [步骤, 设步骤] = useState<步骤id>("定义");
  // Windows/macOS 宿主的右下区域承担常看信息；完整 Web 控制台仍可随时展开。
  const [控制台开, 设控制台开] = useState(false);
  const [页签, 设页签] = useState<控制台页签>("输出");
  const [视口宽, 设视口宽] = useState(() => (typeof window === "undefined" ? 1440 : window.innerWidth));

  useEffect(() => {
    const 量 = () => 设视口宽(window.innerWidth);
    window.addEventListener("resize", 量);
    return () => window.removeEventListener("resize", 量);
  }, []);

  // 原生工程面板打开时不卸载 Web 控制台，只由 CSS 隐藏；
  // 这样主日志的筛选/清空状态和原生日志面板始终是同一份。
  const [偏好, 设偏好] = useState<外壳偏好>(() => {
    const 初 = 读偏好();
    const { 宽, 高 } = 可用();
    return {
      ...初,
      侧栏宽: 夹(初.侧栏宽, 侧栏界.最小, Math.min(侧栏界.最大, Math.max(侧栏界.最小, 宽 - 260))),
      控制台高: 夹(初.控制台高, 控制台界.最小, Math.min(控制台界.最大, Math.max(控制台界.最小, 高 - 220))),
    };
  });

  // 偏好变化就落盘（一次拖动只写一次：拖动结束前 state 也在变，但写 localStorage 很便宜）
  useEffect(() => {
    存偏好(偏好);
  }, [偏好]);

  // ① 数据入口与日志入口。清理按反序：先摘日志（它握着后端订阅），再关连接。
  useEffect(() => {
    const 停连接 = 起连接();
    const 停日志 = 起日志();
    return () => {
      停日志();
      停连接();
    };
  }, []);

  const 选步 = useCallback((id: 步骤id) => {
    设步骤(id);
    设偏好((旧) => (旧.侧栏开 ? 旧 : { ...旧, 侧栏开: true }));
  }, []);

  const 切侧栏 = useCallback(() => {
    设偏好((旧) => ({ ...旧, 侧栏开: !旧.侧栏开 }));
  }, []);

  // 中区（模型/曲线仪表）只在"侧栏之外还剩足够空间"时显示。
  // 不能只看 window.innerWidth：用户可能把侧栏拖得很宽，1100px 的面板减去
  // 48 活动栏和 780 侧栏只剩 272px，再塞两列就会逐字换行（实测截图）。
  const 中区可用 = 视口宽 - 48 - (偏好.侧栏开 ? 偏好.侧栏宽 : 0);
  const 显示中区 = 中区可用 >= 620;

  // 视图内部请求切步（例如验证页的"去插件配指标"）。只做导航，不碰数据。
  useEffect(() => {
    const 听 = (事件: Event) => {
      const 目标 = (事件 as CustomEvent<步骤id>).detail;
      if (typeof 目标 === "string") 选步(目标 as 步骤id);
    };
    window.addEventListener(跳步事件, 听);
    return () => window.removeEventListener(跳步事件, 听);
  }, [选步]);

  // ④ 快捷键（输入框里不抢键）
  useEffect(() => {
    const 按键 = (e: KeyboardEvent) => {
      const 目标 = e.target as HTMLElement | null;
      const 标签 = 目标?.tagName?.toLowerCase();
      if (标签 === "input" || 标签 === "textarea" || 目标?.isContentEditable) return;
      // Alt 组合留给"切控制台页签"（Alt+[ / Alt+]），普通组合键不抢
    if (e.metaKey || e.ctrlKey) return;
    if (e.altKey) {
      if (e.key === "[" || e.key === "]") {
        e.preventDefault();
        设控制台开(true);
        设页签((旧) => {
          const 步 = 控制台页签序.indexOf(旧);
          const 下一 = (步 + (e.key === "]" ? 1 : -1) + 控制台页签序.length) % 控制台页签序.length;
          return 控制台页签序[下一];
        });
      }
      return;
    }

      const 数字 = Number.parseInt(e.key, 10);
      if (!Number.isNaN(数字) && 数字 >= 1 && 数字 <= 任务步骤.length) {
        e.preventDefault();
        选步(任务步骤[数字 - 1].id);
        return;
      }
      // ` = 侧栏开合；- / = = 侧栏调宽（键盘等价于拖分隔条）
      if (e.key === "`" || e.key === "Backquote") {
        e.preventDefault();
        切侧栏();
        return;
      }
      if (e.key === "-" || e.key === "=") {
        e.preventDefault();
        const 幅 = e.shiftKey ? 32 : 8;
        设偏好((旧) => ({
          ...旧,
          侧栏开: true,
          侧栏宽: 夹(旧.侧栏宽 + (e.key === "=" ? 幅 : -幅), 侧栏界.最小, 侧栏界.最大),
        }));
        return;
      }
      // [ / ] = 控制台调高（键盘等价于拖分隔条）；; = 控制台开合
      if (e.key === "[" || e.key === "]") {
        e.preventDefault();
        const 幅 = e.shiftKey ? 32 : 8;
        设控制台开(true);
        设偏好((旧) => ({
          ...旧,
          控制台高: 夹(旧.控制台高 + (e.key === "]" ? 幅 : -幅), 控制台界.最小, 控制台界.最大),
        }));
        return;
      }
      if (e.key === ";") {
        e.preventDefault();
        设控制台开((旧) => !旧);
      }
    };
    window.addEventListener("keydown", 按键);
    return () => window.removeEventListener("keydown", 按键);
  }, [选步, 切侧栏]);

  // overflow-hidden：整页**不许**滚。实测页面 scrollHeight 会比视口高 200+ px，
  // 一旦整页可滚，页脚就会被挤出可视区（表现是状态栏被切掉半行）。
  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden"
      style={{ background: "var(--bg)" }}
    >
      {/* 全局运行控制不能放在会随可用宽度隐藏的“中区”里。
          固定顶栏始终可见，状态仍只认后端返回的 `仿真状态`。 */}
      <div
        className="flex flex-none items-center px-2.5 py-1.5"
        style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-title)" }}
      >
        <仿真工具栏 />
      </div>

      {/* ★ 结构说明（为了让"控制台横跨整个左面板下方"这件事成立）：
       *
       *   外壳行：  [活动栏] [ 外壳列 ....................... ]
       *   外壳列：            [ 侧栏 | 中区 ]   ← 上半
       *                       [ 分隔条 ]        ← 可拖
       *                       [ 控制台 ]        ← 下半（横跨整列宽度）
       *
       * 之前控制台被放在"侧栏右边的那一列"里，于是 Web 面板只占窗口 40% 时，
       * 它只能分到 576-48-300 = 228px —— 挤成一团、文字全糊在一起。
       * 现在它横跨整个左面板（528px），宽度够了才有可读性。
       * 宽窗口下（浏览器版）这个结构同样成立，而且比原来更整齐。 */}
      <div className="flex min-h-0 flex-1">
        <活动栏 当前={步骤} 侧栏开={偏好.侧栏开} on选步={选步} />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1">
            {偏好.侧栏开 ? (
              <>
                <div
                  className={`侧栏格 flex min-h-0 flex-none flex-col overflow-hidden ${显示中区 ? "" : "侧栏格-满"}`}
                  style={{ width: 偏好.侧栏宽, borderRight: "1px solid var(--border)" }}
                >
                  <侧栏 步骤={步骤} 开 on收起={切侧栏} />
                </div>
                {显示中区 ? (
                  <分隔条
                    方向="横"
                    值={偏好.侧栏宽}
                    界={侧栏界}
                    标题={"侧栏宽度（拖动 / 方向键 / - = 键；双击恢复 330）"}
                    on改={(值) => 设偏好((旧) => ({ ...旧, 侧栏宽: 值 }))}
                    on双击={() => 设偏好((旧) => ({ ...旧, 侧栏宽: 默认偏好.侧栏宽 }))}
                  />
                ) : null}
              </>
            ) : null}

            {显示中区 ? (
              <div className="中区格 min-h-0 min-w-0 flex-1">
                <中区 />
              </div>
            ) : null}
          </div>

          {/* 控制台（横跨整个左面板下方） */}
          {控制台开 ? (
            <>
              <分隔条
                方向="纵"
                值={偏好.控制台高}
                界={控制台界}
                标题={"控制台高度（拖动 / 方向键 / [ ] 键；双击恢复 150）"}
                反向
                on改={(值) => 设偏好((旧) => ({ ...旧, 控制台高: 值 }))}
                on双击={() => 设偏好((旧) => ({ ...旧, 控制台高: 默认偏好.控制台高 }))}
              />
              <div
                className="控制台格 min-h-0 flex-none overflow-hidden"
                style={{ height: 偏好.控制台高, borderTop: "1px solid var(--border)" }}
              >
                <控制台 页签={页签} on换页签={设页签} on收起={() => 设控制台开(false)} />
              </div>
            </>
          ) : (
            /* 控制台被收起时留一条可点的"叫回来"的边 —— 收起不能变成"找不回来" */
            <控制台召回 on展开={() => 设控制台开(true)} />
          )}
        </div>
      </div>

      <状态栏 />
      <提示区 />
    </div>
  );
}
