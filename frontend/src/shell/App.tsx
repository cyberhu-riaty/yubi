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
 * 布局（与 `CONVENTIONS.md` 的图一致）：
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
import { startConnection as startConnection } from "../data/store";
import { startLogging as startLogging } from "../data/logs";
import { ActivityBar as ActivityBar } from "./ActivityBar";
import { Sidebar as Sidebar } from "./Sidebar";
import { MainArea as MainArea, SimulationToolbar as SimulationToolbar } from "./MainArea";
import { Console as Console, ConsoleRecall as ConsoleRecall, type ConsoleTab as ConsoleTab } from "./Console";
import { StatusBar as StatusBar } from "./StatusBar";
import { ToastArea as ToastArea } from "./ToastArea";
import { TASK_STEPS as TASK_STEPS, type StepId } from "./task_flow";
import { STEP_NAVIGATION_EVENT } from "./step_navigation";


const STORAGE_KEY = "驭臂.外壳";

interface ShellPreferences {
  sidebarWidth: number;
  consoleHeight: number;
  sidebarOpen: boolean;
}

// 左 Web / 右 3D 之后，网页面板是 576×920 左右的一块窄面板：侧栏 330 是
// 「模型 + 项目 + 兼容性」三块内容都还能读的宽度；控制台 190 能放约 4 条
// 两行日志。两个值都可拖，双击分隔条回到这里。
const DEFAULT_PREFERENCES: ShellPreferences = { sidebarWidth: 330, consoleHeight: 150, sidebarOpen: true };

const SIDEBAR_LIMITS = { min: 180, max: 640 };
const CONSOLE_LIMITS = { min: 90, max: 620 };
const CONSOLE_TABS: ConsoleTab[] = ["输出", "事件", "问题", "诊断"];

/**
 * 窗口很窄时，硬撑两个可拖动格会出现"负宽"和重叠。
 * 这不是猜的：侧栏最小 180 + 活动栏 48 已经占掉 228，再多就挤没中区了。
 */
const available = () => ({
  width: typeof window === "undefined" ? Number.POSITIVE_INFINITY : window.innerWidth,
  height: typeof window === "undefined" ? Number.POSITIVE_INFINITY : window.innerHeight,
});

function readPreferences(): ShellPreferences {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_PREFERENCES;
    const decoded = JSON.parse(raw) as Record<string, unknown>;
    const parsedValue: Partial<ShellPreferences> = {
      sidebarWidth: (decoded.sidebarWidth ?? decoded["侧栏宽"]) as number | undefined,
      consoleHeight: (decoded.consoleHeight ?? decoded["控制台高"]) as number | undefined,
      sidebarOpen: (decoded.sidebarOpen ?? decoded["侧栏开"]) as boolean | undefined,
    };
    return {
      sidebarWidth: clamp(parsedValue.sidebarWidth ?? DEFAULT_PREFERENCES.sidebarWidth, SIDEBAR_LIMITS.min, SIDEBAR_LIMITS.max),
      consoleHeight: clamp(parsedValue.consoleHeight ?? DEFAULT_PREFERENCES.consoleHeight, CONSOLE_LIMITS.min, CONSOLE_LIMITS.max),
      sidebarOpen: parsedValue.sidebarOpen ?? DEFAULT_PREFERENCES.sidebarOpen,
    };
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}

/** 写偏好（写不进去也不影响使用） */
function savePreferences(preference: ShellPreferences): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preference));
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
function Splitter({
  direction: direction,
  value: value,
  bounds: bounds,
  step: step = 8,
  largeStep: largeStep = 32,
  title: title,
  onChange: onChange,
  onDoubleClick: onDoubleClick,
  reversed: reversed = false,
}: {
  direction: "横" | "纵";
  value: number;
  bounds: { min: number; max: number };
  step?: number;
  largeStep?: number;
  title: string;
  onChange: (nextValue: number) => void;
  onDoubleClick?: () => void;
  /** 值锚在"末端"时置 true（例如底部控制台的高度）：鼠标向下 = 高度变小 */
  reversed?: boolean;
}) {
  const [dragging, setDragging] = useState(false);
  const origin = useRef({ coordinate: 0, value: 0 });

  useEffect(() => {
    if (!dragging) return;
    const stop = () => setDragging(false);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
  }, [dragging]);

  const handleKeyboard = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const horizontal = direction === "横";
    const decreaseKey = horizontal ? "ArrowLeft" : "ArrowUp";
    const increaseKey = horizontal ? "ArrowRight" : "ArrowDown";
    if (e.key === decreaseKey || e.key === increaseKey) {
      e.preventDefault();
      const increment = e.shiftKey ? largeStep : step;
      // 反向的“纵”值锚在底部：方向键也要按视觉方向走。
      // 正常：右/下 = +值；反向：下 = -值、上 = +值。
      const valueDelta = e.key === increaseKey ? (reversed ? -increment : increment) : (reversed ? increment : -increment);
      onChange(clamp(value + valueDelta, bounds.min, bounds.max));
      return;
    }
    if (e.key === "Home") {
      e.preventDefault();
      onChange(bounds.min);
      return;
    }
    if (e.key === "End") {
      e.preventDefault();
      onChange(bounds.max);
    }
  };

  const style = direction === "横" ? { width: 5, cursor: "col-resize" } : { height: 5, cursor: "row-resize" };

  return (
    <div
      role="separator"
      aria-orientation={direction === "横" ? "vertical" : "horizontal"}
      aria-label={title}
      aria-valuenow={Math.round(value)}
      aria-valuemin={bounds.min}
      aria-valuemax={bounds.max}
      tabIndex={0}
      title={title}
      data-dragging={dragging ? "1" : "0"}
      className="splitter"
      style={style}
      onDoubleClick={onDoubleClick}
      onKeyDown={handleKeyboard}
      onPointerDown={(e) => {
        e.preventDefault();
        e.currentTarget.setPointerCapture?.(e.pointerId);
        origin.current = { coordinate: direction === "横" ? e.clientX : e.clientY, value: value };
        setDragging(true);
      }}
      onPointerMove={(e) => {
        if (!dragging) return;
        const currentValue = direction === "横" ? e.clientX : e.clientY;
        const delta = (currentValue - origin.current.coordinate) * (reversed ? -1 : 1);
        onChange(clamp(origin.current.value + delta, bounds.min, bounds.max));
      }}
      onPointerUp={(e) => {
        e.currentTarget.releasePointerCapture?.(e.pointerId);
        setDragging(false);
      }}
    />
  );
}

export function App() {
  const [step, setStep] = useState<StepId>("定义");
  // Windows/macOS 宿主的右下区域承担常看信息；完整 Web 控制台仍可随时展开。
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [tab, setTab] = useState<ConsoleTab>("输出");
  const [viewportWidth, setViewportWidth] = useState(() => (typeof window === "undefined" ? 1440 : window.innerWidth));

  useEffect(() => {
    const measure = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  // 原生工程面板打开时不卸载 Web 控制台，只由 CSS 隐藏；
  // 这样主日志的筛选/清空状态和原生日志面板始终是同一份。
  const [preferences, setPreferences] = useState<ShellPreferences>(() => {
    const initial = readPreferences();
    const { width: width, height: height } = available();
    return {
      ...initial,
      sidebarWidth: clamp(initial.sidebarWidth, SIDEBAR_LIMITS.min, Math.min(SIDEBAR_LIMITS.max, Math.max(SIDEBAR_LIMITS.min, width - 260))),
      consoleHeight: clamp(initial.consoleHeight, CONSOLE_LIMITS.min, Math.min(CONSOLE_LIMITS.max, Math.max(CONSOLE_LIMITS.min, height - 220))),
    };
  });

  // 偏好变化就落盘（一次拖动只写一次：拖动结束前 state 也在变，但写 localStorage 很便宜）
  useEffect(() => {
    savePreferences(preferences);
  }, [preferences]);

  // ① 数据入口与日志入口。清理按反序：先摘日志（它握着后端订阅），再关连接。
  useEffect(() => {
    const stopConnection = startConnection();
    const stopLogging = startLogging();
    return () => {
      stopLogging();
      stopConnection();
    };
  }, []);

  const selectStep = useCallback((id: StepId) => {
    setStep(id);
    setPreferences((previous) => (previous.sidebarOpen ? previous : { ...previous, sidebarOpen: true }));
  }, []);

  const toggleSidebar = useCallback(() => {
    setPreferences((previous) => ({ ...previous, sidebarOpen: !previous.sidebarOpen }));
  }, []);

  // 中区（模型/曲线仪表）只在"侧栏之外还剩足够空间"时显示。
  // 不能只看 window.innerWidth：用户可能把侧栏拖得很宽，1100px 的面板减去
  // 48 活动栏和 780 侧栏只剩 272px，再塞两列就会逐字换行（实测截图）。
  const availableMainWidth = viewportWidth - 48 - (preferences.sidebarOpen ? preferences.sidebarWidth : 0);
  const showMainArea = availableMainWidth >= 620;

  // 视图内部请求切步（例如验证页的"去插件配指标"）。只做导航，不碰数据。
  useEffect(() => {
    const listener = (event: Event) => {
      const target = (event as CustomEvent<StepId>).detail;
      if (typeof target === "string") selectStep(target as StepId);
    };
    window.addEventListener(STEP_NAVIGATION_EVENT, listener);
    return () => window.removeEventListener(STEP_NAVIGATION_EVENT, listener);
  }, [selectStep]);

  // ④ 快捷键（输入框里不抢键）
  useEffect(() => {
    const keypress = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const label = target?.tagName?.toLowerCase();
      if (label === "input" || label === "textarea" || target?.isContentEditable) return;
      // Alt 组合留给"切控制台页签"（Alt+[ / Alt+]），普通组合键不抢
    if (e.metaKey || e.ctrlKey) return;
    if (e.altKey) {
      if (e.key === "[" || e.key === "]") {
        e.preventDefault();
        setConsoleOpen(true);
        setTab((previous) => {
          const step = CONSOLE_TABS.indexOf(previous);
          const nextState = (step + (e.key === "]" ? 1 : -1) + CONSOLE_TABS.length) % CONSOLE_TABS.length;
          return CONSOLE_TABS[nextState];
        });
      }
      return;
    }

      const digit = Number.parseInt(e.key, 10);
      if (!Number.isNaN(digit) && digit >= 1 && digit <= TASK_STEPS.length) {
        e.preventDefault();
        selectStep(TASK_STEPS[digit - 1].id);
        return;
      }
      // ` = 侧栏开合；- / = = 侧栏调宽（键盘等价于拖分隔条）
      if (e.key === "`" || e.key === "Backquote") {
        e.preventDefault();
        toggleSidebar();
        return;
      }
      if (e.key === "-" || e.key === "=") {
        e.preventDefault();
        const increment = e.shiftKey ? 32 : 8;
        setPreferences((previous) => ({
          ...previous,
          sidebarOpen: true,
          sidebarWidth: clamp(previous.sidebarWidth + (e.key === "=" ? increment : -increment), SIDEBAR_LIMITS.min, SIDEBAR_LIMITS.max),
        }));
        return;
      }
      // [ / ] = 控制台调高（键盘等价于拖分隔条）；; = 控制台开合
      if (e.key === "[" || e.key === "]") {
        e.preventDefault();
        const increment = e.shiftKey ? 32 : 8;
        setConsoleOpen(true);
        setPreferences((previous) => ({
          ...previous,
          consoleHeight: clamp(previous.consoleHeight + (e.key === "]" ? increment : -increment), CONSOLE_LIMITS.min, CONSOLE_LIMITS.max),
        }));
        return;
      }
      if (e.key === ";") {
        e.preventDefault();
        setConsoleOpen((previous) => !previous);
      }
    };
    window.addEventListener("keydown", keypress);
    return () => window.removeEventListener("keydown", keypress);
  }, [selectStep, toggleSidebar]);

  // overflow-hidden：整页**不许**滚。实测页面 scrollHeight 会比视口高 200+ px，
  // 一旦整页可滚，页脚就会被挤出可视区（表现是状态栏被切掉半行）。
  return (
    <div
      className="flex h-full min-h-0 flex-col overflow-hidden"
      style={{ background: "var(--bg)" }}
    >
      {/* 全局运行控制不能放在会随可用宽度隐藏的“中区”里。
          固定顶栏始终可见，状态仍只认后端返回的 `simulation.state`。 */}
      <div
        className="flex flex-none items-center px-2.5 py-1.5"
        style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-title)" }}
      >
        <SimulationToolbar />
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
        <ActivityBar current={step} sidebarOpen={preferences.sidebarOpen} onStepSelect={selectStep} />

        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1">
            {preferences.sidebarOpen ? (
              <>
                <div
                  className={`sidebar-panel flex min-h-0 flex-none flex-col overflow-hidden ${showMainArea ? "" : "sidebar-panel-full"}`}
                  style={{ width: preferences.sidebarWidth, borderRight: "1px solid var(--border)" }}
                >
                  <Sidebar step={step} open onCollapse={toggleSidebar} />
                </div>
                {showMainArea ? (
                  <Splitter
                    direction="横"
                    value={preferences.sidebarWidth}
                    bounds={SIDEBAR_LIMITS}
                    title={"侧栏宽度（拖动 / 方向键 / - = 键；双击恢复 330）"}
                    onChange={(value) => setPreferences((previous) => ({ ...previous, sidebarWidth: value }))}
                    onDoubleClick={() => setPreferences((previous) => ({ ...previous, sidebarWidth: DEFAULT_PREFERENCES.sidebarWidth }))}
                  />
                ) : null}
              </>
            ) : null}

            {showMainArea ? (
              <div className="main-area min-h-0 min-w-0 flex-1">
                <MainArea />
              </div>
            ) : null}
          </div>

          {/* 控制台（横跨整个左面板下方） */}
          {consoleOpen ? (
            <>
              <Splitter
                direction="纵"
                value={preferences.consoleHeight}
                bounds={CONSOLE_LIMITS}
                title={"控制台高度（拖动 / 方向键 / [ ] 键；双击恢复 150）"}
                reversed
                onChange={(value) => setPreferences((previous) => ({ ...previous, consoleHeight: value }))}
                onDoubleClick={() => setPreferences((previous) => ({ ...previous, consoleHeight: DEFAULT_PREFERENCES.consoleHeight }))}
              />
              <div
                className="console-panel min-h-0 flex-none overflow-hidden"
                style={{ height: preferences.consoleHeight, borderTop: "1px solid var(--border)" }}
              >
                <Console tab={tab} onTabChange={setTab} onCollapse={() => setConsoleOpen(false)} />
              </div>
            </>
          ) : (
            /* 控制台被收起时留一条可点的"叫回来"的边 —— 收起不能变成"找不回来" */
            <ConsoleRecall onExpand={() => setConsoleOpen(true)} />
          )}
        </div>
      </div>

      <StatusBar />
      <ToastArea />
    </div>
  );
}
