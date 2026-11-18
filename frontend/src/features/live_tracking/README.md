# 实时跟踪曲线面板（B 交付）

> 角色：**B**（约 30%）。目录：`frontend/src/features/live_tracking/`。
> 按《UR10 实时跟踪双 AI 协作方案 v1》第 5 节固定接口实现；**未改接口、未改目录外文件**。
> 当前状态：**B 已停止编辑，目录写权限交给 A**。
> 接口变更：**无**（`types.ts` 按第 5 节原样复制）。

## 1. 导出与调用

唯一产品导出：

```ts
import { LiveTrackingPanel } from "../features/live_tracking/LiveTrackingPanel";
import type { LiveTrackingPanelProps } from "../features/live_tracking/types";
```

`LiveTrackingPanel(props: LiveTrackingPanelProps)` 是纯展示组件；数据只来自 props，不订阅仓库、不建 WebSocket、不发运行/暂停/复位命令、不生成演示曲线。A 的 `frontend/src/views/LiveTrackingView.tsx` 已按固定接口接入（B 未修改该文件）。

调用示例（与 A 现有适配层的结构一致）：

```tsx
import { useClock } from "../data/clock";
import { useStore } from "../data/store";
import { useLanguage } from "./i18n";
import { LiveTrackingPanel } from "../features/live_tracking/LiveTrackingPanel";

export function ExampleTrackingPanel() {
  const tracking = useStore((s) => s.liveTracking);
  const connected = useStore((s) => s.connection === "connected");
  const tick = useClock();
  const locale = useLanguage(); // "zh" | "en"

  return (
    <LiveTrackingPanel
      runId={tracking.runId}
      experimentName={tracking.experimentName}
      modelName={tracking.modelName}
      status={tracking.status}
      connected={connected}
      locale={locale}
      jointNames={tracking.jointNames}
      samples={tracking.samples}
      elapsedS={tracking.elapsedS}
      durationS={tracking.durationS}
      dataAgeS={tracking.receivedAtMs === null ? null : Math.max(0, (tick - tracking.receivedAtMs) / 1000)}
      compensationState={tracking.compensationState}
    />
  );
}
```

样式由 `LiveTrackingPanel.tsx` 内部的 `import "./live_tracking.css"` 自动带入；不需要改 `index.css`，不需要额外全局初始化。

## 2. 文件清单

| 文件 | 作用 |
|---|---|
| `types.ts` | 第 5 节固定展示接口 v1（原样复制，字段/单位/可空性未改） |
| `LiveTrackingPanel.tsx` | 面板：状态栏、关节选择、时间窗/单位、三张默认图 + 可选速度图、统一悬停、提示与页脚 |
| `LiveTrackingChart.tsx` | 本面板专用 Canvas 2D 图表：Retina、ResizeObserver、rAF 合并重绘、断线、共享十字线 |
| `live_tracking_math.ts` | 纯函数：取当前关节列、时间轴、二分查找、纵轴范围、刻度/读数格式化（可单测） |
| `labels.ts` | 本模块 zh / en 文案（不改中央文案表） |
| `live_tracking.css` | 全部以 `.live-tracking` 为作用域；颜色走现有 CSS 变量 |

## 3. 展示行为与关键取舍

### 状态栏

- 明确的“仿真”标识 + “MuJoCo 仿真数据，非真机实测” + “真机 未接入”，不把仿真值写成真机实测。
- 实验名 / 模型名（长名称省略号 + `title` 全文）、运行状态（文字 + 圆点，不只靠颜色）、
  运行时间 / 总时长（未知显示“总时长未知”）、数据更新时间、摩擦补偿状态。
- 运行进度条仅在 `durationS` 已知且 >0 时出现；未知不伪造。
- 断线、运行中数据更新延迟（`dataAgeS > 0.5`，仅 `status === "running"`）、暂停/完成/错误、
  运行中尚无采样等提示分别显示；断线保留最后一段历史。

### 关节 / 时间窗 / 单位

- 按 `jointNames` 渲染 J1–J6；默认第一个有效关节；关节数量减少时失效选择回落到 J1，且绘图不访问越界下标。
- 10 / 30 / 60 秒窗口，默认 10 秒；deg / rad，默认 deg；力矩始终 N·m，时间始终秒。
- 角度切换只改变显示倍率与小数位；`errorRad` 直接展示 A 计算的目标减实际，B **不**从位置重算。
- 速度图作为可选折叠项，默认收起；展开后与三张图共用时间范围和悬停。

### 时间轴（不使用墙钟）

- `end = max(窗口长度, 后端 elapsedS, 最新样本时间)`，`start = max(0, end - 窗口长度)`。
- 因此起步阶段固定显示 `0..窗口`，不会因每个新点反复缩放；窗口满后跟随 A 确认的 `elapsedS`。
- 暂停时 `elapsedS` 不变，时间轴与曲线一起停住；不用 `Date.now()` 推动横轴，不启动数据定时器。

### 缺失值 / 极端数据

- `null` 或非有限数保留为 NaN，画线时断线；不补 0、不跨缺口连线、不插值。
- `t=0` 是有效时间：是否为空只看数组长度，不用首个时间点的真值判断；单点会画出点标记。
- 恒定值会围绕该值展开最小纵轴跨度，避免线与网格重合不可见；刻度小数位随间隔调整，避免标签重复。
- 重复/NaN/负时间做防御性跳过；A 保证严格递增时不会触发。
- 补偿力矩只在选中关节的当前窗口出现真实有限值时叠加；整项 `null` / 未接入时显示“未接入/尚无实际补偿数据”而不画 0。

### 悬停与重绘

- 面板维护唯一的 `hoverTime`；三张图 + 速度图共享十字线与最近真实采样点读数。
- 悬停只改变展示，不发送任何命令，不停止机器人；指针移出面板清除悬停。
- `runId` 改变清除旧悬停；窗口滑动使旧悬停落在轴外时也会清掉。
- Canvas 用 `requestAnimationFrame` 合并重绘；`ResizeObserver` + `window.resize` 处理尺寸；
  `devicePixelRatio` 设置 backing store；`matchMedia("(resolution: …dppx)")` 处理 DPR 变化事件。
- 换肤通过观察 `<html data-theme>` 重绘 Canvas；颜色全部来自现有 `--plot-*` / `--palette-*` / `--fg-*` 变量。
- 每帧只按窗口范围内真实点分配画图列；不是每帧深拷贝全部 120 秒历史。

### 可访问性 / 布局

- 关节、时间窗、单位都是 `<button>` + `aria-pressed`；图表 Canvas 有 `role="img"` 与标题/单位 `aria-label`。
- 状态、图例、缺失读数均同时有文字，不单靠颜色；错误/延迟提示带文字说明。
- 所有 CSS 规则以 `.live-tracking` 开头，未写 `html/body/:root/canvas/button` 全局规则；
  适配约 280–900 px，长名称省略 + `title`，不制造外层横向滚动。

## 4. 已做检查

### 类型检查

`pnpm` 在本机不可用（`pnpm --version` 无输出），改用仓库内 TypeScript 等价命令：

```bash
./frontend/node_modules/.bin/tsc --noEmit -p frontend/tsconfig.json
# exit 0（包含 A 当前并行修改后的工作区）
```

### 纯函数测试（临时文件，不在交付目录内）

`/tmp/live_tracking_math.test.ts` 用 Node 24 type stripping 运行，覆盖：

- `t=0` 保留、重复时间/NaN/负时间跳过、短向量/越界向量按缺失处理；
- `fromS` 窗口裁剪、最后有效样本时间；
- 时间范围：空数据、`t=0`、窗口未满、滑动窗口、elapsed 超前、非法参数；
- 二分查找边界、最近真实点、窗口首末下标；
- 纵轴范围：全缺失返回 null、includeZero、弧度→度缩放、恒定值展开、极小恒定值刻度不重复；
- 时间刻度步长、读数/秒数格式化、`-0` 归零、NaN 不转 0；
- zh/en 文案键结构与空字符串检查。

结果：

```text
live_tracking_math tests: PASS
```

### 可视检查（临时 harness，已删除）

在独立端口 `5279` 启动临时 Vite harness，用无头 Chrome + CDP 截图/测量；演示数据只存在于临时 harness，**未进入面板默认值或产品入口**。检查后 harness 文件已删除，服务已停止。

覆盖：

| 项 | 结果 |
|---|---|
| 宽度 280 / 520 / 900 px | 面板宽度分别 280 / 520 / 900；组件内无横向溢出（`scrollWidth == viewport`，组件内 overflow 元素为 0） |
| 主题 workbench / modern_dark | 颜色随 CSS 变量变化；Canvas 在主题切换后重绘 |
| 语言 zh / en | 标题、状态、图例、空数据提示、页脚、单位全部切换 |
| DPR 2 | 500 CSS px 画布 → 1000 px backing store；262 CSS px 窄栏 → 262 backing store（DPR1） |
| 容器 resize | 520 → 280 px 后 Canvas 重算为 262 × 128，无溢出 |
| 空数据 | 三图显示“尚无采样数据 / 开始运行后才会出现真实曲线”，图例“缺失”，不画假波形 |
| t=0 单点 | 三个系列在时间轴 0 处画出点标记，读数 `最新 t = 0.00 s`，未误判为空 |
| 运行中 + 悬停 | 三图共享十字线，读数取最近真实采样点；悬停不改变状态、不发命令 |
| 暂停 / 完成 / 断线 | 状态与提示正确；断线保留历史并明确提示；运行中 `dataAgeS > 0.5` 显示延迟提示 |
| 恒定值 | 展开纵轴后平线可见；目标虚线覆盖实际线仍可分辨；刻度标签不重复 |
| null 缺失 | 位置/误差/力矩在缺口处断线；悬停缺值显示“缺失”；补偿项单独连续/断开 |
| 60 秒窗口 + rad | 横轴 0–60 s，单位与读数同步切换 |
| 速度图 | 展开后与三图共用时间轴/悬停，单位 deg/s 或 rad/s |
| 无关节信息 / 单关节 | 无关节时明确提示且不访问越界下标；单关节正常 |
| 超长实验/模型/runId | 省略号显示，`title` 保留全文，页脚 runId 截断，不撑破布局 |
| runId 切换 | 旧悬停被清除，页脚显示新 runId；关节数从 6 减到 2 时失效选择回落 J1 |
| 30 Hz 流式更新 | 临时 stream harness 运行约 4.5 s：`elapsedS` 从 5 推进到 9.52，悬停时间保持 5.56 s，无异常 |
| 控制台 | 仅开发服务器 `favicon.ico` 404；无 React/Canvas 运行时错误 |

截图保存在 `/tmp/lt-*.png`（不随交付目录提交）。未宣称真实仿真联调完成。

## 5. 未完成与限制

- **未接真实 UR10 仿真数据**：没有启动真实后端/仿真，未验证 A 实际发布频率、延迟与 20–30 Hz 更新；不能宣称端到端跑通。
- **未在生产桌面窗口检查**：未在 WKWebView + 原生 3D 的实际左栏宽度下验证；只做了独立 Vite harness。
- **未运行生产构建/打包**：按协作方案由 A 独占执行（构建会清空 `runtime/web/`）。
- **未验证跨显示器 DPR 热切换**：headless CDP 只改 `deviceScaleFactor` 不派发 resize/resolution 事件；
  初次加载与容器 resize 已验证，真实桌面切换显示器时依赖浏览器事件或下一帧数据重绘。
- **未做完整读屏/键盘审计**：按钮可聚焦、Canvas 有 aria-label；图表悬停读数以指针操作为主。
- **未验证真实补偿控制器**：补偿曲线叠加逻辑已用 harness 验证；实际 `compensationTorqueNm` 是否来自真实控制项由 A 保证。

## 6. 给 A 的边界外问题与接入注意

B 未修改 `runtime/`、`controllers/`、模型、实验、`frontend/src/data/`、`frontend/src/shell/`、
`ValidateView.tsx`、现有 `Chart.tsx`、`index.css`、中央 i18n、生成目录、`package.json` 或锁文件。
以下为只读观察，交给 A 处理：

1. **dataAge 刷新频率**：A 的 `LiveTrackingView.tsx` 用 1 Hz 的 `useClock()` 计算 `dataAgeS`，
   面板的 0.5 s 延迟提示与“数据更新”读数因此约 1 s 粒度，最长可能晚约 1 s 出现。
   如需更及时，可由 A 提高 `dataAgeS` 更新频率；面板不自行跑墙钟。
2. **samples 引用**：面板按 `samples` 引用做 `useMemo`。A 的 `receiveTracking` 在追加时生成新数组，符合；
   请勿原地 `push` 同一个数组，否则图表不会重算。
3. **补偿状态一致性**：`compensationTorqueNm` 与 `compensationState` 必须一致。若补偿未接入/关闭，
   请勿传非零补偿数组；面板只在存在真实有限值时叠加并显示独立图例。
4. **缺失标记兼容**：A 在丢样处插入全 `null` 的显式缺失点与接口兼容，面板会断线显示；
   请保持 `elapsedS` 严格递增且不要重复时间点。
5. **横轴来源**：面板只用样本 `elapsedS` 与传入 `elapsedS` 推进横轴；暂停时请保持 `elapsedS` 不变。
   运行中数据停滞时面板显示延迟提示，不自行补点。
6. **接入方式**：A 已新建 `frontend/src/views/LiveTrackingView.tsx` 并 import 本面板；CSS 由面板内部 import，
   无需改 `index.css`。A 只需继续按固定接口传值并完成真实仿真联调。
7. **构建**：请 A 在真实数据联调后执行类型、契约与生产构建检查；B 未运行也会清空 `runtime/web/` 的构建。

## 7. 文件写权限

**B 已交付，已停止编辑 `frontend/src/features/live_tracking/`，目录写权限交给 A。**

如果 A 需要调整面板接口，请先协调；B 不会在未协调的情况下修改接口或目录外文件。

## 8. 2026-11-18 扩展：参考实验回放对比

后续集成阶段在本目录新增了**独立于 v1 实时面板**的参考对比 UI；v1 的
`LiveTrackingPanel` / `LiveTrackingPanelProps` 字段保持不变：

- `ReferenceComparisonPanel.tsx`：六关节 3×2（窄栏自动单列）力矩/电流对比，
  存档参考/当前模型重算切换、播放游标、CSV 导出；
- `reference_labels.ts`：本模块参考对比中英文案；
- `LiveTrackingChart.tsx`：增加可选 `cursorTime`（播放游标）和复用现有
  `LiveTrackingLabels`；不影响实时面板的 `hoverTime` 行为。

数据来源、实验入口和验收口径见 `docs/UR10参考图回放界面说明.md` 与
`docs/UR10参考图复现差距分析.md`。参考回放是离线存档回放，不是实时采集，
也不是正向控制复现；轨迹 1/7 的接触差异在面板中明确标注。
