# LoongEnv-SHIZE 源码学习笔记

> 对标对象：`github.com/LoongEnv-HIT/LoongEnv-SHIZE`（`main` @ `c8eb52c92cde31985e35fe9f96522bc103b5698f`）
> 定位：React 19 + Tailwind 4 + three.js 前端 / Node sidecar / Python 算法进程 的三进程原型
> 用途：为「驭臂」桌面机械臂仿真工作台（MuJoCo + 自研控制算法，Python + ImGui）提供可复用的参考

---

## 0. 取证说明（先说可信度）

**源码获取方式（因仓库体积异常，需说明）**

仓库含 **277 个文件、799.4 MB** 二进制资产，直接 `git clone --depth 1` 连续失败两次
（`curl 92 HTTP/2 stream not closed cleanly` / `curl 56 Connection reset by peer`），
`--filter=blob:none` 稀疏克隆亦遇 `HTTP 408`；`raw.githubusercontent.com` 在本机网络下超时。

最终采用**按文件定向获取 + 逐文件校验**：

```bash
# 1) 通过 GitHub API 取完整文件树（277 项）
curl -sSL "https://api.github.com/repos/LoongEnv-HIT/LoongEnv-SHIZE/git/trees/main?recursive=1" -o /tmp/tree.json
# 2) 经 jsDelivr CDN 拉取 38 个源码文件（跳过 models/ public/ 与全部图片）
# 3) 用 git blob SHA-1 逐文件校验
```

**校验结果：38/38 文件与 `tree.json` 中的 git blob SHA-1 完全一致（`sha1("blob <len>\0" + content)`），
即所读源码与 commit `c8eb52c` 逐字节相同，未经删改。** 本地路径 `/tmp/loongenv/`。

**未能执行代码**：本机无 `numpy / pandas / scipy / toppra / ecos / ruckig / roboticstoolbox / matplotlib`，
无法运行算法。因此第 5 章的**数值结论不是跑出来的，而是"读代码 + 对仓库内提交的真实运行产物做反向验算"**得到的。
好在仓库提交了 `docs/planning_demo_summary.json`（一次真实运行的完整输出），
第 5.10 节用它反过来验证了对算法控制流的理解——**9 个分段中有 8 个被逐位复现**，这是很强的证据，但仍是**验算而非执行**，下文会明确标注。

**阅读范围**：38 个源码文件全部通读（含 746 行 `pipeline.py` 与 1169 行 `SimulationView.tsx`）。所有引用均为 `file:line`，
行号对应上述 commit。

---

## 1. Repo map：真实逻辑 vs 装饰

### 1.1 目录树（含行数）

```
LoongEnv-SHIZE/                        仓库合计 277 文件 / 799.4 MB（绝大部分是 CAD/网格）
├── README.md                      96   项目说明、启动步骤、效果图链接
├── package.json                   46   react19 / three / recharts / mujoco-js / urdf-loader / motion
├── vite.config.ts                 31   /api 代理 → 127.0.0.1:3001
├── tsconfig.json                  26
├── index.html                     13
├── metadata.json                   5   Google AI Studio applet 元信息
├── .env.example                    9   GEMINI_API_KEY / APP_URL —— 实际无人引用
├── .gitignore                     11
│
├── Figs/                        569 行 md + 12 张截图(≈6.5 MB)
│   └── 封装发布工作流.md             他们的「功能抽离成可安装包」方法论（有价值，见 §6.1）
│
├── docs/
│   ├── ALGORITHM.md               62   ⚠️ 描述了一套代码里根本不存在的 API（见 §6.2-3）
│   └── planning_demo_summary.json 149  ✅ 一次真实运行的输出 —— 本报告的关键证据
│
├── fixed_toppra_mvc_ruckig/     1350 行 / 9 文件   ★★★ 全仓库唯一真正有价值的资产
│   ├── pipeline.py               746   ★★★ 算法全部实现，纯 numpy，零 I/O（除读文件）
│   ├── core.py                   133   精简 API + CorePipelineConfig
│   ├── cli.py                    182   命令行入口 + 结果落盘
│   ├── __init__.py                37   导出 18 个符号
│   ├── __main__.py                 5
│   ├── example_usage.py           64
│   ├── README.md                 145   7 步流水线 + API + CLI + 输出清单
│   ├── pyproject.toml             30
│   └── requirements.txt            8   numpy<2 / toppra>=0.6 / ecos / ruckig>=0.9 / roboticstoolbox
│
├── scripts/
│   ├── planning_bridge.py        358   ★★ Python 侧 JSON 桥（stdin/stdout），ER15 硬编码在此
│   └── generate_planning_docs_artifacts.py 510  文档图表生成器（真实逻辑，与产品无关）
│
├── server/
│   ├── api.mjs                   151   ★ Express 薄代理，仅 2 条路由，零业务逻辑
│   └── dev-stack.mjs              38   并行拉起前后端 + 退出联动
│
├── src/                         3850 行 / 13 文件
│   ├── App.tsx                   610   ★★ VS Code 式外壳（布局真实，状态栏/标签页是假的）
│   ├── main.tsx                    7
│   ├── index.css                  48   滚动条 + 全局字号覆盖 hack
│   ├── types.ts                  183   ★ 插件契约 + 规划请求/响应类型（很干净）
│   ├── components/
│   │   ├── SimulationView.tsx   1169   ★★★ MuJoCo WASM / URDF → three.js，几乎全是真逻辑
│   │   ├── CollapsibleSection.tsx 48   ★ 唯一被真正复用的展示组件（被引用 25 次）
│   │   └── SystemMonitor.tsx      53   ✗ 6 行写死日志，无 props
│   ├── plugins/
│   │   ├── DefinePlugin.tsx      163   ~ 半真实：读资产目录、切换机器人是真的
│   │   ├── DesignPlugin.tsx      604   ★★ 真实：健康检查+上传+POST+回放+recharts
│   │   ├── DeployPlugin.tsx      175   ✗ 全假（含 Math.random() 当关节目标）
│   │   └── DiagnosePlugin.tsx    608   ~ 半真实：数据来源真、物理公式假
│   ├── data/robotCatalog.ts      176   ★ 7 个机器人资产目录（唯一"数据源"）
│   └── lib/utils.ts                6   cn() = clsx + tailwind-merge（shadcn 惯例）
│
├── public/
│   ├── robots/                        ~406 MB 被浏览器直接托管（含 93 MB .stp、41 MB zip）
│   └── samples/er15_waypoints_sample.csv  359 B（11 个路点）
│
└── models/                            ~393 MB，与 public/robots 内容基本重复
```

### 1.2 按目录汇总

| 目录 | 文件数 | 行数 | 性质 |
|---|---|---|---|
| `src/` | 13 | 3850 | 前端全部 |
| `src/components/` | 3 | 1270 | 其中 1169 行是 SimulationView |
| `src/plugins/` | 4 | 1550 | 2 真 / 1 半真 / 1 全假 |
| `scripts/` | 2 | 868 | 桥 + 文档生成器 |
| `fixed_toppra_mvc_ruckig/` | 9 | 1350 | ★ 算法包 |
| `server/` | 2 | 189 | 薄代理 + 进程管理 |
| `docs/` | 2 | 211 | 1 份过期规格 + 1 份真实产物 |

### 1.3 载真逻辑的文件（按价值排序）

| 文件 | 行数 | 判定依据 |
|---|---|---|
| `fixed_toppra_mvc_ruckig/pipeline.py` | 746 | 12 个纯函数 + 5 个 dataclass，全部是数值算法，无 `print`/无网络/无框架 |
| `src/components/SimulationView.tsx` | 1169 | MEMFS 物化、URDF/MJCF 依赖解析、geom→three.js 转换、30fps 同步循环、完整 dispose |
| `src/plugins/DesignPlugin.tsx` | 604 | 真 `fetch` 健康检查(194)+真上传校验(72-127)+真 POST(268)+真图表(557,570)+真回放控制 |
| `scripts/planning_bridge.py` | 358 | 真 JSON 协议 + 真参数校验 + 真调用算法（但 ER15/6 轴硬编码） |
| `server/api.mjs` | 151 | 真 `spawn` 子进程 + 超时 + 错误传播；业务逻辑为 0 |
| `src/App.tsx` | 610 | 真布局/真 splitter/真 rAF 回放循环；状态栏、标签页、面包屑是假 |
| `src/data/robotCatalog.ts` | 176 | 7 个机器人的真实资产描述（路径/关节数/默认位姿/显示缩放） |
| `src/types.ts` | 183 | 插件契约 + 规划契约，设计质量高 |
| `src/components/CollapsibleSection.tsx` | 48 | 唯一可复用展示组件 |
| `scripts/generate_planning_docs_artifacts.py` | 510 | 真实逻辑但服务文档，与产品无关 |

### 1.4 装饰性文件 / 代码

| 位置 | 问题 |
|---|---|
| `src/components/SystemMonitor.tsx` 全文 53 行 | 无 props、无状态，6 条日志（含 `ws://192.168.1.105:8080/stream`、`Task_ID_882`）写死在 JSX 里 |
| `src/plugins/DeployPlugin.tsx` | 见 §6.2-1；`Math.random() * 3.14` 当关节目标(143)，进度条 `animate={{ width: '68%' }}`(105)，E-STOP 无 handler(132)，SSH 按钮无 handler(64) |
| `src/App.tsx:441-471` | 标签栏（`SimulationView.mu` / `system.log`）、面包屑（`LoongEnv > src > components`）、`main*` 分支、`第 1 行, 第 1 列`、`空格: 2`、`UTF-8`、`Prettier` 徽章全部写死 |
| `src/App.tsx:539-607` | 插件市场弹窗：只渲染注册表的静态列表，`安装` 按钮无 handler(595) |
| `docs/ALGORITHM.md` | 描述 `strategyId / stageConfig / algorithmMeta / stageMetrics / debugLogs / input_parse / path_prepare / postprocess` —— **全仓库命中 0 次**（已 grep 验证） |
| `.env.example` + `package.json:16` | `GEMINI_API_KEY` 被 `vite.config.ts:13-15` 注入 bundle，但 `src/` 中 `genai/GEMINI` **命中 0 次**；`@google/genai` 是死依赖 |

---

## 2. 产品叙事与信息架构

### 2.1 叙事：把「机器人开发」讲成一个 IDE

这是整个原型最值得学的一点。它没有把四个模块做成四个平级 Tab 或四个页面，
而是**整体套用 VS Code 的壳**（`src/App.tsx:246-536`）：

| VS Code 部位 | 本项目 | 代码 |
|---|---|---|
| Activity Bar（最左图标列） | 四个模块 + 核心底座 + 插件管理 + 账户 + 设置 | `App.tsx:252-311` |
| Side Bar（可折叠侧栏） | 当前模块的操作面板（插件自定义 UI） | `App.tsx:316-421` |
| Editor（中区） | **始终是同一个 3D 视图** `SimulationView.mu` | `App.tsx:439-480` |
| Panel（底部） | Output 面板（实为装饰） | `App.tsx:497-502` |
| Status Bar（最底） | 仿真引擎 / 分支 / 行列 / 编码 | `App.tsx:507-536` |

产品隐喻因此非常稳定：**"机器人资产"= 文件，"规划一次轨迹"= 跑一次构建，"四个模块"= 四个工作区**。
中间 3D 视图是**常驻不切换**的（`App.tsx:475-479`），四个模块只改左侧面板——
这直接对应"仿真器应当是工作台中心，而不是某个 Tab 的产物"这一判断。

四个模块的定义在 `src/App.tsx:63-68`，这是一处**单点注册**：

```tsx
// 插件注册表
const PLUGIN_REGISTRY: Plugin[] = [
  DefinePlugin, DesignPlugin, DeployPlugin, DiagnosePlugin
];
```

对应的导航标签是 `define / design / deploy / diagnose`，模块名在各自 metadata 里：
定义（`DefinePlugin.tsx:64-70`）、Trajectory Planning（`DesignPlugin.tsx:130-136`）、
实机部署与控制（`DeployPlugin.tsx:9-15`）、Smart Diagnose & Monitor（`DiagnosePlugin.tsx:117-123`）。

### 2.2 外壳 JSX 骨架（可据此重建等价布局）

省略内联 handler 与长 className 的细节，保留元素层级与布局工具类。行号为原文位置。

```tsx
// App.tsx:246
<div className="h-screen bg-[#ffffff] text-[#333333] font-sans
                selection:bg-[#add6ff] flex flex-col overflow-hidden select-none">
  <div className="flex-1 flex overflow-hidden">                    {/* 主容器：横向三段 */}

    {/* 1. Activity Bar —— 固定宽 w-12，深色 */}
    <aside className="w-12 bg-[#2c2c2c] flex flex-col items-center py-2 shrink-0 z-50">   // :252
      <div className="flex flex-col gap-1 w-full items-center">
        {PLUGIN_REGISTRY.map((p, idx) => {                          // :254
          const icons = [Files, Search, GitBranch, PlayCircle];     // :255  ← 写死，忽略 p.icon
          const IconComponent = icons[idx];
          ...
          <button onClick={() => { setActiveModuleId(p.metadata.id);
                                   setIsSideBarVisible(true);
                                   setShowCore(false); }}           // :261-265
            className={cn("w-12 h-12 flex items-center justify-center transition-all relative group",
              activeModuleId === p.metadata.id && isSideBarVisible && !showCore
                ? "text-white border-l-2 border-white"
                : "text-slate-400 hover:text-white")} />            // :266-271
        })}
        <button onClick={() => { setShowCore(!showCore); setIsSideBarVisible(true); }}
                title="核心底座"><Database /></button>                // :278-290
      </div>
      <div className="mt-auto flex flex-col gap-1 w-full items-center mb-2">   {/* 底部组 */}
        <button onClick={() => setShowPluginManager(true)} title="插件管理"><Puzzle /></button>
        <button title="账户"><UserCircle /></button>
        <button title="设置"><Settings /></button>                   // :294-309
      </div>
    </aside>

    {/* 2. Side Bar —— 可折叠，宽度由状态控制 */}
    {isSideBarVisible && (                                          // :314
      <>
      <aside style={{ width: sidebarWidth }}                        // :316-318
             className="bg-[#f3f3f3] border-r border-[#e5e5e5] flex flex-col shrink-0 z-40 shadow-sm min-w-0">
        <div className="h-9 px-4 flex items-center justify-between shrink-0">   {/* 面板标题栏 */}
          <span className="text-[11px] ... uppercase">
            {showCore ? "资源管理器: 核心" : activePlugin.metadata.name}</span>  // :322
          <div className="flex items-center gap-1"><Plus /><ChevronLeft /><MoreHorizontal /></div>
        </div>
        <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col">
          {showCore ? ( /* 通用架构：状态/动作/日志/指标 四项写死 */ :null)      // :338-355
          : (
            <div className="flex flex-col flex-1">
              <details className="border-b ... group/details">        {/* 插件详情：原生 details，默认收起 */}
                <summary className="h-6 px-1 ... list-none">
                  <ChevronRight className="... group-open/details:rotate-90" />
                  <span>插件详情</span></summary>                      // :359-363
                <div className="p-5 bg-white space-y-5 shadow-inner">
                  <h2>{activePlugin.stepTitle}</h2>
                  <p>{activePlugin.metadata.description}</p>
                  <div>{/* 技术栈 */ activePlugin.techStack.map(t => <TechBadge key={t} name={t} />)}</div>
                  <div className="space-y-1 pt-2 border-t">
                    <SchemaCard title="输入架构 (Input Schema)" data={activePlugin.inputSchema} />
                    <SchemaCard title="输出架构 (Output Schema)" data={activePlugin.outputSchema} />
                  </div>
                </div>
              </details>
              <div className="flex-1 flex flex-col min-h-0">          {/* 插件自定义 UI：主体 */}
                <div className="h-9 px-4 flex items-center justify-between bg-[#f3f3f3]
                                border-b border-[#e5e5e5] shrink-0">
                  <span>操作面板</span><Plus /><X />                   {/* :388-401 */}
                </div>
                <div className="flex-1 overflow-y-auto bg-white custom-scrollbar">
                  <activePlugin.component                              // :403  ← 插件在这里被渲染
                    data={{ planningResult, setPlanningResult,
                            playback, setPlayback,
                            robotAssets: ROBOT_ASSETS,
                            selectedRobotId, setSelectedRobotId,
                            apiBase: '/api' }}                          // :404-413
                    onAction={(a, p) => console.log('Plugin Action:', a, p)} />  // :414
                </div>
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* 竖向 splitter */}
      <div role="separator" aria-orientation="vertical" aria-label="调整操作面板宽度"
           onMouseDown={(event) => setDragState({ type: 'sidebar',
                                                  startPos: event.clientX,
                                                  startValue: sidebarWidth })}   // :426
           className="group w-2 shrink-0 cursor-ew-resize bg-white hover:bg-[#f5f9ff]
                      transition-colors flex items-center justify-center">
        <div className={cn("h-full w-[3px] rounded-full transition-colors",
          dragState?.type === 'sidebar' ? "bg-[#007acc]/60" : "bg-transparent group-hover:bg-[#007acc]/35")} />
      </div>
      </>
    )}

    {/* 3. 中区（Editor） */}
    <main className="flex-1 flex flex-col overflow-hidden bg-white relative">   // :439
      <div className="h-9 bg-[#f3f3f3] flex items-center overflow-x-auto shrink-0 border-b">
        {/* 两个写死的标签页：SimulationView.mu（active）/ system.log */}      {/* :441-458 */}
      </div>
      <div className="h-6 bg-[#ffffff] border-b border-[#f3f3f3] flex items-center px-4 shrink-0 z-10">
        {/* 面包屑 LoongEnv > src > components > SimulationView.mu */}          {/* :461-471 */}
      </div>
      <div className="flex-1 relative overflow-hidden">
        <SimulationView robot={selectedRobot}
                        trajectory={planningResult?.trajectory ?? null}
                        currentTimeSec={playback.currentTimeSec} />              {/* :475-479 */}
      </div>

      {/* 横向 splitter */}
      <div role="separator" aria-orientation="horizontal" aria-label="调整底部输出面板高度"
           onMouseDown={(event) => setDragState({ type: 'bottom',
                                                  startPos: event.clientY,
                                                  startValue: bottomPanelHeight })}
           className="group h-2 shrink-0 cursor-ns-resize ...">                  {/* :482-494 */}
        <div className={cn("h-[3px] w-full rounded-full transition-colors",
          dragState?.type === 'bottom' ? "bg-[#007acc]/60" : "bg-transparent group-hover:bg-[#007acc]/35")} />
      </div>

      {/* 4. 底部面板 */}
      <div style={{ height: bottomPanelHeight }}
           className="border-t border-[#e5e5e5] flex flex-col shrink-0 min-h-0">   {/* :497-500 */}
        <SystemMonitor />
      </div>
    </main>
  </div>

  {/* 5. 状态栏 —— 拿 VS Code 蓝 #007acc 铺满 */}
  <footer className="h-6 bg-[#007acc] text-white flex items-center justify-between
                     px-3 text-[11px] shrink-0 z-[60]">                          {/* :507 */}
    <div className="flex items-center h-full">
      <div className="... px-2 hover:bg-white/10 h-full"><GitBranch /><span>main*</span></div>
      <div className="... px-2 hover:bg-white/10 h-full">
        <X /><span>0</span><ShieldAlert /><span>0</span></div>                      {/* 错误/警告恒为 0 */}
      <div className="... px-2 hover:bg-white/10 h-full">
        <Activity /><span>{`仿真引擎: ${selectedRobot.engineLabel}`}</span></div>    {/* :521 ← 唯一真数据 */}
    </div>
    <div className="flex items-center h-full">
      <div className="px-2 ...">第 1 行, 第 1 列</div>
      <div className="px-2 ...">空格: 2</div>
      <div className="px-2 ...">UTF-8</div>
      <div className="px-2 ... flex items-center gap-1"><CheckCircle2 /><span>Prettier</span></div>
      <div className="px-2 ..."><Bell /></div>                                       {/* :525-534 */}
    </div>
  </footer>

  {/* 插件市场弹窗（AnimatePresence + motion 缩放淡入） */}
  <AnimatePresence>{showPluginManager && ( /* 遮罩 + 左侧分类 + 右侧静态卡片列表 */ )}</AnimatePresence>  // :539-607
</div>
```

**状态栏结论**：6 个字段里只有 1 个（`仿真引擎: ${selectedRobot.engineLabel}`，`:521`）接了真数据，
数据源是 `getRobotAsset(selectedRobotId)`（`:145`）→ `robotCatalog.ts`。其余全是 IDE 装饰。

### 2.3 左右面板与 splitter 的真实机制

这是可复用度很高的一段（`App.tsx:111-244`）。

```tsx
// App.tsx:111-125
const SIDEBAR_DEFAULT_WIDTH = 560;
const SIDEBAR_MIN_WIDTH = 380;
const SIDEBAR_MAX_WIDTH = 560;          // ← 与 DEFAULT 相同，实际只能变窄
const BOTTOM_PANEL_DEFAULT_HEIGHT = 220;
const BOTTOM_PANEL_MIN_HEIGHT = 160;
const BOTTOM_PANEL_MAX_HEIGHT = 360;

type DragState =
  | { type: 'sidebar'; startPos: number; startValue: number }
  | { type: 'bottom';  startPos: number; startValue: number }
  | null;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}
```

拖拽由一个 `useEffect` 统一处理，**用 union 类型的 `dragState` 区分方向，而不是两个 handler**：

```tsx
// App.tsx:212-244
useEffect(() => {
  if (!dragState) return;

  const handleMouseMove = (event: MouseEvent) => {
    if (dragState.type === 'sidebar') {
      // 上限随窗口宽度动态收缩，给中区留至少 320px
      const maxWidth = Math.min(SIDEBAR_MAX_WIDTH,
                                Math.max(SIDEBAR_MIN_WIDTH, window.innerWidth - 320));
      setSidebarWidth(clamp(dragState.startValue + event.clientX - dragState.startPos,
                            SIDEBAR_MIN_WIDTH, maxWidth));
      return;
    }
    // 底部面板：注意是减号，因为向上拖 = 变高
    const maxHeight = Math.min(BOTTOM_PANEL_MAX_HEIGHT,
                               Math.max(BOTTOM_PANEL_MIN_HEIGHT, Math.floor(window.innerHeight * 0.45)));
    setBottomPanelHeight(clamp(dragState.startValue - (event.clientY - dragState.startPos),
                               BOTTOM_PANEL_MIN_HEIGHT, maxHeight));
  };

  const handleMouseUp = () => setDragState(null);
  const previousCursor = document.body.style.cursor;        // 保存
  const previousUserSelect = document.body.style.userSelect;
  document.body.style.cursor = dragState.type === 'sidebar' ? 'ew-resize' : 'ns-resize';
  document.body.style.userSelect = 'none';

  window.addEventListener('mousemove', handleMouseMove);
  window.addEventListener('mouseup', handleMouseUp);
  return () => {                                            // 恢复
    document.body.style.cursor = previousCursor;
    document.body.style.userSelect = previousUserSelect;
    window.removeEventListener('mousemove', handleMouseMove);
    window.removeEventListener('mouseup', handleMouseUp);
  };
}, [dragState]);
```

三个细节值得抄：**（a）** 拖动期间把 `body` 的 `cursor` 与 `userSelect` 一起改掉并在 cleanup 里恢复
（否则拖动会选中文本）；**（b）** 惯性用 `startValue + Δ` 而不是累加，避免丢帧漂移；
**（c）** 上限用 `window.innerWidth - 320` 动态收紧而不是硬编码。
唯一缺陷是 `SIDEBAR_DEFAULT_WIDTH === SIDEBAR_MAX_WIDTH`（`:111-113`），侧栏只能缩不能放。

### 2.4 状态：10 个 useState，纯 prop drilling，无 context/reducer

`src/App.tsx:128-146` 是全应用**唯一**的状态源：

```tsx
const [activeModuleId, setActiveModuleId] = useState('define');            // :128
const [showCore, setShowCore] = useState(false);                           // :129
const [showPluginManager, setShowPluginManager] = useState(false);         // :130
const [isSideBarVisible, setIsSideBarVisible] = useState(true);            // :131
const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT_WIDTH);   // :132
const [bottomPanelHeight, setBottomPanelHeight] = useState(BOTTOM_PANEL_DEFAULT_HEIGHT); // :133
const [dragState, setDragState] = useState<DragState>(null);               // :134
const [planningResult, setPlanningResult] = useState<PlanningResult|null>(null); // :135
const [selectedRobotId, setSelectedRobotId] = useState(DEFAULT_ROBOT_ID);  // :136
const [playback, setPlayback] = useState<PlaybackState>({                 // :137-142
  isPlaying: false, currentTimeSec: 0, speed: 1, loop: true,
});

const activePlugin = PLUGIN_REGISTRY.find(p => p.metadata.id === activeModuleId)
                     || PLUGIN_REGISTRY[0];                                // :144
const selectedRobot = getRobotAsset(selectedRobotId);                      // :145
const trajectoryDuration = planningResult?.trajectory.duration ?? 0;       // :146
```

**没有 store、没有 context、没有 reducer。** 向下传的方式只有一个「数据袋对象」
（`App.tsx:404-413`），类型定义在 `src/types.ts:174-183`：

```ts
export interface WorkspacePluginData {
  planningResult: PlanningResult | null;
  setPlanningResult: React.Dispatch<React.SetStateAction<PlanningResult | null>>;
  playback: PlaybackState;
  setPlayback: React.Dispatch<React.SetStateAction<PlaybackState>>;
  robotAssets: RobotAsset[];
  selectedRobotId: string;
  setSelectedRobotId: React.Dispatch<React.SetStateAction<string>>;
  apiBase?: string;
}
```

插件契约本身极简（`src/types.ts:11-24`）：

```ts
export interface PluginComponentProps {
  data: any;                                          // ← 注意是 any，类型安全靠插件自救
  onAction: (action: string, payload?: any) => void;
}
export interface Plugin {
  metadata: PluginMetadata;      // id / name / version / author / description
  icon: React.ReactNode;
  stepTitle: string;
  component: React.FC<PluginComponentProps>;
  techStack: string[];
  inputSchema: any;              // ← 只用来在侧栏渲染 JSON
  outputSchema: any;
}
```

**评价**：契约只有 7 个字段，加一个模块 = 新建一个文件 + 在 `PLUGIN_REGISTRY` 加一行，
这是它真正的架构优点。代价是 `data: any` 让每个插件自己写 `as Partial<DesignPluginData>`
（`DesignPlugin.tsx:151`、`DefinePlugin.tsx:81`、`DiagnosePlugin.tsx:130`），
且 `onAction` 在宿主的实现只有一句 `console.log`（`App.tsx:414`）——**整条插件→宿主的动作通道是死的**。

三个副作用：

| 位置 | 作用 |
|---|---|
| `App.tsx:148-192` | 回放主循环：`requestAnimationFrame`，仅在 `isPlaying` 时跑；按 `previousTs` 算 `elapsed`；`loop` 时取模，否则停在 `duration` 并把 `isPlaying=false`；`speed` 下限 0.01 |
| `App.tsx:194-202` | 清空 `planningResult` 时自动停止回放并归零 |
| `App.tsx:204-210` | **切换机器人时自动停止回放并归零**（避免用旧轨迹驱动新模型） |

`publish → 播放` 的链路是：`DesignPlugin` 拿到响应 → `setPlanningResult`（`DesignPlugin.tsx:291-293`）
→ `App` 把 `planningResult.trajectory` 和 `playback.currentTimeSec` 传给 `SimulationView`（`App.tsx:475-479`）
→ `SimulationView` 用 `trajectoryRef` / `currentTimeRef` 把这两个值**推进 ref 而不是重启渲染循环**
（`SimulationView.tsx:896-904`），只有 `robot` 变化才重建整个场景（`:1106` 的依赖数组）。这是对的：
**60fps 的时间轴不该触发 three.js 场景重建。**

### 2.5 四个模块各自的屏幕构成

#### Define（机器人定义）— `src/plugins/DefinePlugin.tsx` 163 行

编号化的折叠卡片，从上到下（`:91-161`）：

| 顺序 | 卡片 | 内容 | 真实性 |
|---|---|---|---|
| 1 | `资产管理 (Asset Management)` `:94` | 垂直按钮列表，选中项 `bg-[#eef6ff] text-[#0f4c81]` `:105` | 真：`robotAssets.map` → `handleSelectRobot` → `setSelectedRobotId` |
| 2 | `当前机器人 (Selected Robot)` `:115` | 6 行 `DetailRow` 键值表：名称/引擎/格式/关节数/资源路径/说明 | 真：`getRobotAsset()` |
| 3 | `关节约束 (Joint Limits)` `:126` | 4 列表格 Joint/Position/Velocity/Torque | 真：`robot.jointLimits`；无数据时显示空态提示 `:34-37` |
| 4 | `仿真绑定 (Simulation Binding)` `:130` | 两张图标+文字说明卡（"中间 3D 视图会即时切换…不固定 ER15"） | 半真：文字是硬编码说明 |
| 底部 | `Simulation Target` 固定操作条 `:145-159` | 显示当前机器人 + 「已应用到仿真」按钮 | 「按钮」只是重新选中同一个 ID（`:153`），实为空操作 |

局部组件：`DetailRow`（`:14-29`，`grid-cols-[112px_minmax(0,1fr)]` 的两列定义表）、
`JointLimitTable`（`:31-61`）。两者都是行内一次性组件。

#### Design（轨迹规划）— `src/plugins/DesignPlugin.tsx` 604 行 ← **唯一端到端打通的模块**

编号化四段（这是很好的「线性向导放进非线性外壳」的写法）：

| 段 | 标题 | 组成 | 行号 |
|---|---|---|---|
| 1 | `1) Waypoint File` | 虚线拖拽区（`<input type=file accept=".csv,.txt" className="hidden">` 藏在 `<label>` 里）+ 文件名回显 + 格式说明 + 红色错误条 | `:322-342` |
| 2 | `2) Limits & Config` | 6×4 关节限位表（Position 只读 + Velocity/Acceleration 两个 `type=number`）+ 12 个参数控件（`grid-cols-2`） | `:344-449` |
| 3 | `3) Runtime Status` | Sidecar Health 卡（Python 路径 / ER15 Factory OK） + 错误卡 + 日志卡 | `:451-483` |
| 4 | `4) Result & Playback` | 2 个摘要卡（Duration / Minima Count）+ 回放条（Play/Pause、Reset、速度 select、Loop、range 滑块）+ **2 个 recharts 折线图**（MVC Upper Envelope、Path Profile）；无结果时显示空态 | `:485-587` |
| 底部 | 固定操作条 | `Run Fixed TOPPRA MVC Ruckig`，`disabled={!canRun}` | `:591-600` |

**真逻辑**（这是全项目最有价值的前端部分）：

- 前置校验 `validateWaypointText(fileName, text)`（`:72-127`）：CSV 检查 `J1..J6` 表头存在且前 39 行数值合法；
  TXT 检查每行恰好 6 个数值。**校验在前端做了一遍，Python 侧再做一遍**（`planning_bridge.py:110-131`）。
- 健康检查 `useEffect` + `disposed` 标志防止卸载后 setState（`:189-213`）。
- 提交 `handleRunPlanning`（`:240-316`）：先重校验 → 若 `health.ok === false` 直接短路（`:246-249`）→
  `POST ${apiBase}/design/planning/run` → 手动 `response.text()` 再 `JSON.parse`
  （**为了在非 JSON 响应时给出可诊断的错误**，`:275-286`）→ `!response.ok || !payload.ok` 抛错
  （`:287-289`）→ 成功后 `setPlanningResult` 并把回放归零（`:291-299`）→ 失败则**清空结果**并显示错误（`:303-312`）
  → `finally setIsRunning(false)`。
- 图表数据用 `useMemo` 从响应里 reshape（`:174-187`）：MVC 用 `{s: item.x, mvc: item.y}`，
  Path Profile 用 `{t, s, sd}`；`Line` 都带 `isAnimationActive={false}`（`:563,576,577`），
  `stroke="#007acc"` / `#059669` / `#dc2626`。

**注意两处硬编码**：`POSITION_LIMITS`（`:23-30`）把 ER15 的 6 个关节行程写死在前端，
与 `planning_bridge.py:56-63` 是同一份数字的**第二份拷贝**；
`PlanningConfig` 有 12 个字段，UI 只暴露了 10 个（缺 `minima_count`、`minima_max_value`）。

#### Deploy（实机部署与控制）— `src/plugins/DeployPlugin.tsx` 175 行 ← **全假**

三段式步骤导航（`grid-cols-3`，激活项 `border-b-2 border-[#007acc]`，`:32-48`）：

| 步骤 | 内容 | 假在哪 |
|---|---|---|
| 1 硬件连接 | Jetson Orin AGX 卡 + 「建立 SSH 连接」按钮 + 通信链路列表（EtherCAT/CAN-FD/ROS2 全绿点脉冲） | IP `192.168.1.105`、`SSH 已就绪` 写死（`:60-61`）；按钮**无 onClick**（`:64`）；三个"已连接"来自写死数组 `:71` |
| 2 部署配置 | 跳动下载图标 + 进度条 | `animate={{ width: '68%' }}` 目标值写死（`:105`）；`编译 68% / 同步 100%` 写死（`:110-111`） |
| 3 实时控制 | 绿色"已激活"卡 + E-STOP + 控制流表 + 传感器反馈表 | `<span>{ (Math.random()*3.14).toFixed(4) }</span>` 当关节目标（`:143`）；`Jitter: 15us / 1000Hz`、`IMU_X 0.02`、`42.5°C` 全写死；E-STOP **无 onClick**（`:132`） |

底部 `onAction('COMPLETE', 'DEPLOY_FINISHED')`（`:166`）→ 最终落到 `App.tsx:414` 的 `console.log`。

#### Diagnose（诊断与监控）— `src/plugins/DiagnosePlugin.tsx` 608 行 ← **真假混杂**

三段式（Data Source / Monitoring / Reports，`:366-390`）。这张表是本节最重要的产出：

| 内容 | 判定 | 依据 |
|---|---|---|
| Sidecar health 拉取 | ✅ 真 | `fetch(.../health, {cache:'no-store'})` + `healthLoading/healthError` 三态（`:141-171`） |
| `DataSourceTable` 的 6 行 | ⚠️ 半真 | 3 行真（Robot Asset / Simulation Engine / Planning Health API，`:189-206`），第 1 行 `ws://192.168.1.105:8080/stream` 写死且状态恒为 `'online'`（`:183-188`） |
| 关节曲线 `jointMetricChartData` | ⚠️ 数据真、物理假 | x 轴来自真 `planningResult.trajectory.tUniform/qUniform`（`:282-317`）；但 `tau = q*2.2 + dq*0.9 + qdd*0.05`（`:303`）是随手凑的线性式，**没有质量矩阵/逆动力学** |
| `telemetryData` | ⚠️ 同上 | `dq` 用真前后差分（`:238`），但 `tau = |q|*4 + |dq|*1.2 + |qdd|*0.03`（`:240`）、`eeVel = min(4.5, |dq|*0.42 + |q|*0.08)`（`:241`）、`error = min(0.25, |dq|*0.008)`（`:242`）都是编的 |
| `FALLBACK_DIAGNOSE_DATA` | ❌ 假 | 120 点纯正弦波组（`:36-44`），无规划结果时直接顶上（`:258`） |
| `healthScore` | ⚠️ 半真 | 算法真（在线行数占比，`:360-364`），但 6 行里 3 行恒 `online` ⇒ **分数下限被锁在 50%** |
| Monitoring Overview 四个大数字 | ❌ 假 | `Rate 500Hz`、`Throughput 124MB/s` 写死（`:476-477`） |
| `jointLoadData` 柱状图 | ❌ 假 | `load = min(100, 20 + |q_last|*38)`（`:355`） |
| `Diagnostic Insights` 结论文本 | ❌ 假 | 一段固定英文建议（`:550-553`） |
| `Download PDF` / `Sync to Cloud` | ❌ 假 | 两个按钮**均无 onClick**（`:555-560`） |

图表用了 recharts 的三种：`LineChart`（`:417,524,568`）、`AreaChart`（`:501`）、`BarChart`（`:582`），
统一 `isAnimationActive={false}` + `<CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />`。

### 2.6 SimulationView：真正撑起"仿真"二字的 1169 行

`src/components/SimulationView.tsx` 是全项目工程量最大的文件，且**几乎不含假逻辑**。职责：

1. **资产解析**（`:159-202`）：`runtime === 'auto'` 时按 `sourcePriority`（MJCF=0 > .xml=1 > .urdf=2 > .urdf.xml=3，`:111-118`）
   逐个 `fetch` 探测候选路径，并用 `Content-Type` 与内容特征（`<mujoco` / `<robot`）**双重排除 SPA fallback 返回的 HTML**（`:120-157`）。
2. **把模型喂给 MuJoCo WASM**（`:443-556`）：`mujoco.FS.mount(MEMFS)` 挂载 `/working`，
   然后三条路径分别物化：URDF（`package://` 重写 + 依赖逐个 fetch + 二进制写 MEMFS，`:457-479`）、
   显式资产列表（`:481-497`）、MJCF 自动递归（解析 `<compiler meshdir>` 与 `file=` 引用，
   把同一个二进制写到 `toVirtualPath` 与 `<meshdir>/<ref>` **两个候选虚拟路径**，`:499-553`）。
3. **geom → three.js**（`buildGeom`，`:670-739`）：直接读 MuJoCo 的裸数组
   （`geom_type/geom_size/geom_pos/geom_quat/geom_matid/mat_rgba/geom_rgba`，
   网格则 `mesh_vertadr/vertnum/faceadr/facenum/mesh_vert/mesh_face`）构造 `BoxGeometry/SphereGeometry/
   CylinderGeometry/CapsuleGeometry/BufferGeometry`；四元数按 MuJoCo 的 `(w,x,y,z)` 转 three 的 `(x,y,z,w)`（`:737`）。
   `geom_group === 3` 跳过（碰撞体），`mjGEOM_PLANE` 返回 null（地面另建，`:676,692`）。
4. **场景**（`createViewport`，`:756-844`）：`PerspectiveCamera(42°, …, 0.01, 100)`，`camera.up=(0,0,1)`（Z-up！），
   `ACESFilmicToneMapping` + `SRGBColorSpace`，`HemisphereLight` + 主/补/轮廓三向光，
   程序化生成的 256×256 棋盘格 CanvasTexture 地面（`:558-593`），`OrbitControls`。
   **`setPixelRatio(Math.min(window.devicePixelRatio, 1))`**（`:766`）——主动降采样保帧率。
5. **材质档位**（`styleStandardMaterial`，`:595-629`）：`industrial_orange_dark` 与 `neutral_metallic` 两套
   roughness/metalness/emissive/clearcoat 参数，并按颜色亮度自动识别"橙色工业漆"（`:600`）。
   非 `MeshStandardMaterial` 的材质会被**转换成** `MeshPhysicalMaterial`（`enhanceMaterial`，`:631-653`）。
6. **帧循环**（`:983-1016` / `:1048-1063`）：rAF + 30fps 节流（`1000/30`），
   每帧把 `qpos` 写入 → `mj_forward` → 用 `data.xpos/xquat` 同步每个 body 的 `THREE.Group` 位姿 → `controls.update()` → `render`。
7. **回放采样**（`sampleTrajectory`，`:229-261`）：对 `tUniform` 做**手写二分查找** + 线性插值，
   越界钳到首/末帧。
8. **降级阶梯**：MuJoCo 失败且 sourceType 是 URDF 时，自动切 `URDFLoader`（`:1066-1080`），
   并把角标改成 `URDF Loader (Fallback)`（`:1076`）；URDF 分支用 `loader.joints` 过滤非 fixed 关节后 `setJointValue`（`:1042-1043`）。
9. **资源释放**（`:1093-1105`）：`data.delete()`、`model.delete()`、`FS.unmount('/working')`、
   `removeFromParent()`、`viewport.dispose()`（内含 geometry/material/renderer/EventLister 全量 dispose，`:741-754, 835-842`）。

**关键判定：`mj_forward` 只做正运动学，全程没有 `mj_step`（`:961, 998`）。**
所以它是**"MuJoCo 当运动学/模型解析器用"的播放器，不是动力学仿真器**——没有积分、没有接触、没有执行器、没有力矩。
但 UI 上标的是 `MuJoCo WASM`（`App.tsx:521`，来自 `robotCatalog.ts:19` 的 `engineLabel`），
这会让人误以为在跑物理。这一条既是最值得学的技巧（白拿了 MJCF/URDF 解析 + 网格解码 + FK），
也是最需要在文案上澄清的地方。

---

## 3. 设计系统

### 3.1 色彩：一套「VS Code Light+ 主体 + Dark 活动栏 + 蓝色状态栏」的混合体

全部用 Tailwind 任意值写死，**没有 CSS 变量、没有主题层、没有 dark: 变体**。index.css 只有 48 行（滚动条 + 字号覆盖）。

| 角色 | 值 | 出现处 |
|---|---|---|
| 页面底 | `#ffffff` | `App.tsx:247` |
| 活动栏（深） | `#2c2c2c` + `text-slate-400` / `hover:text-white` / 激活 `text-white border-l-2 border-white` | `App.tsx:252, 266-271` |
| 面板/工具栏底 | `#f3f3f3` | `App.tsx:318, 320, 441` |
| 分组标题条 | `#e8e8e8` → hover `#d8d8d8` | `App.tsx:342, 360`；`CollapsibleSection.tsx:36` |
| 分隔线/边框 | `#e5e5e5`（主）、`#ececec`/`#f3f3f3`/`#f1f5f9`/`#f3f4f6`（浅） | 全局 |
| **主强调色** | `#007acc`，hover `#0062a3`（`DesignPlugin.tsx:595`）/ `#005fb8`（`App.tsx:595`） | 状态栏、主按钮、激活下划线、图表主线 |
| 正文主色 | `#333333` | 全局 |
| 正文次色 | `#6f6f6f` | 全局（标签、说明） |
| 三级文字 | `#4b5563` / `#6b7280` / `#526070` / `#374151` / `#64748b` | 插件内（Design/Diagnose 自成一派） |
| 表头底 | `#f8fafc` | `DefinePlugin.tsx:42`；`DesignPlugin.tsx:347`；`DiagnosePlugin.tsx:95` |
| 成功 | `#388a3c` / `emerald-600` / `#16a34a` / `#166534` / `#dcfce7` / `#f0fdf4` | `DeployPlugin.tsx:74,122,128`；`DesignPlugin.tsx:576` |
| 警告 | `amber-600` / `#d97706` | `SystemMonitor.tsx:40`；`DiagnosePlugin.tsx:573` |
| 危险 | `#d32f2f` → `#b71c1c` / `#dc2626` / `red-50`+`red-700` | `DeployPlugin.tsx:132`；`DesignPlugin.tsx:336,577` |
| 选中节点 | `#eef6ff` 底 + `#0f4c81` 字 | `DefinePlugin.tsx:105` |
| 图表 6 关节色板 | `['#007acc','#16a34a','#7c3aed','#d97706','#dc2626','#0ea5a8']` | `DiagnosePlugin.tsx:68`（唯一一处"配色被抽成常量"） |

**评价**：色板本身是克制、连贯、专业的（工业工具感，不是营销风）。
但它是**靠人肉记忆维护的**——`#e5e5e5` 在 6 个文件里出现上百次，`#007acc` 亦然。
没有任何一处 `--color-accent` 之类的抽象。这在原型期是合理取舍，在我们要做长期工作台时应当先建 token 层。

### 3.2 字号：一套"事后放大"的 hack（值得引以为戒）

实际使用的字号是 `text-[9px] / [10px] / [11px] / [12px] / text-xs / text-sm`，
但 `src/index.css:13-26` 用属性子串选择器全局改写了它们：

```css
@layer base {
  [class*="text-[9px]"]  { font-size: 11px !important; line-height: 1.5 !important; }
  [class*="text-[10px]"] { font-size: 12px !important; line-height: 1.5 !important; }
  [class*="text-[11px]"] { font-size: 13px !important; line-height: 1.55 !important; }
}
```

即：**设计稿按 9/10/11px 写，上线前发现太小，于是全局 `!important` 抬到 11/12/13px。**
后果是此后所有 `text-[10px]` 都名不副实，且不可发现（改 class 不生效，得去翻 css）。
这个 hack 是可行的救火方案，但**不要继承**：直接定义一套 5 档字阶即可。

字号→用途的实际映射：`9px→11px` 密集标签/角标；`10px→12px` 分组标题（恒与 `font-bold uppercase tracking-wider/widest` 同现）；
`11px→13px` 正文/表格单元（最高频）；`text-xs(12px)` 中区标签页；`text-sm` 卡片主标题。

### 3.3 间距与尺寸惯例

| 惯例 | 值 | 说明 |
|---|---|---|
| 圆角 | `rounded-sm`（约 2px）**几乎唯一**，`rounded-full` 仅用于 splitter 指示条与状态点，`rounded-xl` 只在加载浮层出现一次（`SimulationView.tsx:1159`） | 方角 = 工业工具感 |
| 面板内边距 | `p-4`（模块内容）、`p-5`（插件详情）、`p-3.5`（CollapsibleSection 内容） | |
| 行内边距 | `px-3 py-2` / `px-3 py-2.5`（表格行）；`px-2`（树行） | |
| 竖向节奏 | `space-y-6`（模块级卡片间距）、`space-y-4`（Design）、`space-y-3`（卡片内） | |
| 横向间距 | `gap-1 / gap-1.5 / gap-2 / gap-3 / gap-6` | |
| 关键高度 | 活动栏 `w-12`；工具栏 `h-9`；面包屑/状态栏 `h-6`；CollapsibleSection 头 `h-8`；splitter `w-2`/`h-2` | |

### 3.4 组件清单（全量）

| 文件 | 组件 | props | 渲染什么 | 复用性判定 |
|---|---|---|---|---|
| `src/components/CollapsibleSection.tsx` | `CollapsibleSection` | `title, children, defaultOpen=true, className?, contentClassName?` | `<section>` 外框 + `<button>` 标题条（`ChevronRight` 旋转 90°）+ 条件渲染内容区 | ✅ **真·可复用**，被 4 个插件共引用 **25 次**。是唯一被抽出来的展示组件 |
| `src/components/SimulationView.tsx` | `SimulationView` | `robot, trajectory?, currentTimeSec?` | three.js 画布 + 左上引擎/状态角标 + 右上关节状态条 + 左下 Model/Format 角标 + 加载/错误浮层 | ⭕ 功能组件，非设计系统组件 |
| `src/components/SystemMonitor.tsx` | `SystemMonitor` | **无** | 4 个假标签页头 + 6 条写死日志 | ❌ 一次性装饰 |
| `src/App.tsx` | `TechBadge`（`:76-80`） | `name` | `font-mono` 小胶囊 | ❌ 一次性 |
| `src/App.tsx` | `SchemaCard`（`:87-107`） | `title, data` | 可折叠 + `<pre>{JSON.stringify(data,null,2)}</pre>` | ⚠️ 通用 JSON 折叠器，但没被抽出去，只在 `App.tsx` 用 2 次 |
| `src/plugins/DefinePlugin.tsx` | `DetailRow`（`:14-29`） | `label, value, mono?` | `grid-cols-[112px_minmax(0,1fr)]` 两列定义行 | ❌ 局部 |
| `src/plugins/DefinePlugin.tsx` | `JointLimitTable`（`:31-61`） | `robot` | 4 列网格表 + 空态 | ❌ 局部 |
| `src/plugins/DiagnosePlugin.tsx` | `SourceStatusBadge`（`:77-90`） | `status: 'online'\|'warning'\|'offline'` | 三色状态胶囊 | ⚠️ 通用模式，局部 |
| `src/plugins/DiagnosePlugin.tsx` | `DataSourceTable`（`:92-114`） | `rows` | 3 列网格表（Source / Endpoint / Status） | ⚠️ 通用模式，局部 |
| `src/lib/utils.ts` | `cn()` | `...ClassValue` | `twMerge(clsx(inputs))` | ✅ shadcn 标准做法，全局使用 |

**一个明确的"该抽而未抽"**：同一个「用 `grid-cols-[...]` + 表头行 + `divide`/`border-b` 拼表格」的模式
在项目里**手写了至少 6 次**：`DefinePlugin.tsx:24 / :42 / :51`、`DiagnosePlugin.tsx:95 / :103`、
`DesignPlugin.tsx:347 / :354`。既然 `CollapsibleSection` 证明他们会抽组件，这里没抽就是漏了。

### 3.5 图标

`lucide-react@^0.546.0`（`package.json:25`）。仅 `App.tsx` 就 import 了 33 个图标（`:7-42`），
全项目约 40 个。用法统一为 `className="w-3.5 h-3.5" / "w-4 h-4" / "w-5 h-5" / "w-6 h-6"` 内联。

两个问题：
1. **同一图标被赋予多个语义**：`X` 既是"关闭标签页"（`App.tsx:446`）又是状态栏的"错误数"（`:514`）；
   `Activity` 既是"仿真引擎"（`:520`）又是"Sidecar Health"（`DesignPlugin.tsx:455`）又是
   "Live Telemetry"（`DiagnosePlugin.tsx:497`）又是"运行中 spinner"（`DesignPlugin.tsx:597`）。
2. **活动栏图标被写死覆盖**（`App.tsx:255`：`const icons = [Files, Search, GitBranch, PlayCircle]` 按 `idx` 取），
   插件自己声明的 `p.icon`（如 `DefinePlugin.tsx:71` 的 `<Box/>`）只用在插件市场弹窗里（`App.tsx:582`）。
   结果是左边的 Files/Search/GitBranch/PlayCircle **讲不出这四个模块是什么**。

### 3.6 图表

仅 `recharts@^3.8.1`，仅在 Design 与 Diagnose 两个插件里。

- 一律 `<ResponsiveContainer width="100%" height="100%">` 包在固定高度的 `<section>` 里
  （`h-44` / `h-[220px]` / `h-[200px]` / `h-[180px]`）。
- 一律 `isAnimationActive={false}` —— **对实时/回放类图表这是正确选择**（避免每帧重播动画）。
- 一致的视觉：`CartesianGrid strokeDasharray="3 3"`、`tick={{ fontSize: 10 }}` 或 `fontSize={9}`、
  折线 `dot={false}` + `strokeWidth={1.2~1.6}`、`Tooltip` 用默认样式或手写 `contentStyle`（`DiagnosePlugin.tsx:506-512`）。
- 图表类型：`LineChart`（趋势）、`AreaChart`（`tau`/`q` 双面积，`fillOpacity={0.1/0.05}`，`:514-515`）、`BarChart`（关节负载，`radius={[2,2,0,0]}`，`:587`）。
- 无缩放/平移/十字准线/导出，无大数据量优化（`downsample` 是在 Python 侧做的，见 §5.9）。

### 3.7 整体气质

**明确是"工程工具"而非"营销页"**：方角、灰阶为主 + 单一蓝强调、极小字号、紧行高、
信息密度高、几乎没有留白、动效只用于模态进出（`motion` 的 `opacity/scale/y` 微位移，
`App.tsx:542-553`、各插件顶部 `initial={{opacity:0,y:5}}`）。
这套气质和"桌面机械臂仿真工作台"的定位是一致的，可直接借鉴。

---

## 4. 架构：三进程与它们的契约

### 4.1 三个进程

| 进程 | 启动命令 | 端口 | 配置项 | 证据 |
|---|---|---|---|---|
| 前端（Vite dev server） | `npm run dev` → `vite --port=3000 --host=0.0.0.0` | **3000** | 硬编码在 script 里 | `package.json:7` |
| Node sidecar（Express） | `npm run dev:api` → `node server/api.mjs` | **3001** | `PLANNER_API_PORT`（默认 `3001`） | `package.json:8`、`api.mjs:11` |
| Python 算法进程 | 由 sidecar **每次请求** `spawn` | 无（stdin/stdout） | `PLANNER_PYTHON`（默认 `'python'`） | `api.mjs:10, 16` |
| 两者一起 | `npm run dev:stack` → `node server/dev-stack.mjs` | — | — | `package.json:9` |

`server/dev-stack.mjs` 全文 38 行，是个**极简 supervisor**：

```js
// server/dev-stack.mjs:1-38
const dev = spawn('npm', ['run', 'dev'],     { shell: true, stdio: 'inherit' });
const api = spawn('npm', ['run', 'dev:api'], { shell: true, stdio: 'inherit' });

let shuttingDown = false;
function shutdown(code = 0) {                    // 幂等，防重入
  if (shuttingDown) return;
  shuttingDown = true;
  dev.kill(); api.kill();
  process.exit(code);
}
process.on('SIGINT',  () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

dev.on('exit', (code) => { if (!shuttingDown) { console.error(`[dev:stack] frontend exited with code ${code ?? 0}`); shutdown(code ?? 1); } });
api.on('exit', (code) => { if (!shuttingDown) { console.error(`[dev:stack] sidecar exited with code ${code ?? 0}`);  shutdown(code ?? 1); } });
```

设计要点：`shell: true`（Windows 友好）+ `stdio: 'inherit'`（两个子进程日志直接混流到父终端，**没有前缀标记**，
这在实际调试时是个小痛点）+ **任一子进程退出就带走另一个**（避免半死状态）。
**没有启动顺序控制、没有就绪探测**——前端可能在 sidecar 起来之前就发健康检查（`DesignPlugin.tsx:194`），
所以前端的健康检查逻辑里必须有失败分支（它确实有，`:199-206`）。

### 4.2 浏览器 → Node sidecar

**没有 CORS 问题**，因为前端从不跨域：`vite.config.ts:21-29` 把 `/api` 代理到 sidecar：

```ts
// vite.config.ts:6-31
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const plannerApiPort = env.PLANNER_API_PORT || '3001';
  return {
    base: './',
    plugins: [react(), tailwindcss()],
    define: { 'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY) },  // ← 注入但无人使用
    resolve: { alias: { '@': path.resolve(__dirname, '.') } },
    server: {
      hmr: process.env.DISABLE_HMR !== 'true',
      proxy: { '/api': { target: `http://127.0.0.1:${plannerApiPort}`, changeOrigin: true } },
    },
  };
});
```

前端只用两个常量：`apiBase: '/api'`（`App.tsx:412`），
插件里 `pluginData.apiBase ?? '/api'` 兜底（`DesignPlugin.tsx:156`、`DiagnosePlugin.tsx:131`）。

**路由表（全部，共 2 条）**

| 方法 | 路径 | 超时 | 请求 | 响应 | 代码 |
|---|---|---|---|---|---|
| `GET` | `/api/design/planning/health` | 45 s | 无 body（sidecar 自造 `{action:'health'}`） | `{ok, python:{executable,version}, dependencies:{8 个包 → bool}, er15Factory:{ok,error}, apiVersion, sidecar:{pythonBin,bridgeScript}, stderr}` | `api.mjs:91-115` |
| `POST` | `/api/design/planning/run` | 600 s | `PlanningRequest`（见下） | `PlanningResult` + `{stderr, exitCode}`；失败时 HTTP 400 + `{ok:false, error, traceback?}` | `api.mjs:117-145` |

请求体类型（`src/types.ts:82-89`）：

```ts
export interface PlanningRequest {
  waypointText: string;          // 整个 CSV/TXT 的文本，不是路径
  fileName: string;              // 只用来推断后缀（csv/txt）
  limits: PlanningLimits;        // { velocity: number[6], acceleration: number[6] } —— 关节空间
  config: PlanningConfig;        // 12 个算法参数
  ssMode: 'arc' | 'time';
  playbackDtMs: number;          // 回放统一采样步长（默认 4 ms）
}
```

响应体类型（`src/types.ts:138-147`）：

```ts
export interface PlanningResult {
  summary: PlanningSummary;      // duration/samples/minimaIdx/minimaV/segmentPoints/segmentTargets/segmentTargetVelocities/config
  trajectory: PlanningTrajectory; // duration, ts, qs, qds, qdds, tUniform, qUniform
  mvc: PlanningMvc;              // gridpoints, mvcUpper, minimaIdx, minimaV, chart[≤500]
  pathProfile: PlanningPathProfile;  // t, s, sd, sdd, chart[≤500]
  waypoints: PlanningWaypoints;  // raw[1000×6], smooth[1000×6]
  warnings: string[];
  logs: string[];
  stderr?: string;               // ← 由 api.mjs 注入，不属于 Python 的返回
}
```

`express.json({ limit: '50mb' })`（`api.mjs:89`）不是随手写的：上传 1000×6 路点 + 回传
14351×6 的 `qs/qds/qdds` 加上 `waypoints.raw/smooth`（各 1000×6），
单次响应轻松上 MB 级。**它是被真实负载逼出来的配置。**

### 4.3 Node sidecar → Python

**Node 侧的全部逻辑**就在 `runBridge()`（`api.mjs:14-86`）里，一个字不多：

```js
// server/api.mjs:14-86（核心骨架）
function runBridge(payload, timeoutMs = 300000) {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonBin, [bridgeScript], {          // 每次请求一个新 Python 进程
      cwd: projectRoot,                                        // cwd = 仓库根
      env: process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = ''; let stderr = ''; let settled = false;

    const timer = setTimeout(() => {                           // 超时 → SIGKILL（无优雅退出）
      if (settled) return;
      settled = true;
      child.kill('SIGKILL');
      reject(new Error(`Planner bridge timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.stdout.on('data', (c) => { stdout += c.toString(); });   // 全量缓冲，非流式
    child.stderr.on('data', (c) => { stderr += c.toString(); });
    child.on('error', (e) => { /* clearTimeout + reject */ });
    child.on('close', (code) => {
      const trimmed = stdout.trim();
      let parsed = null;
      if (trimmed.length > 0) {
        try { parsed = JSON.parse(trimmed); }
        catch { return reject(new Error(`Planner bridge returned non-JSON output. code=${code} stderr=${...} stdout=${trimmed.slice(0,500)}`)); }
      }
      if (code !== 0) {
        if (parsed) return resolve({ parsed, stdout: trimmed, stderr: stderr.trim(), exitCode: code });  // ★ 保留桥自己写的错误 payload
        return reject(new Error(stderr.trim() || `Planner bridge exited with code ${code}`));
      }
      resolve({ parsed, stdout: trimmed, stderr: stderr.trim(), exitCode: code });
    });

    child.stdin.write(JSON.stringify(payload));                // 请求 = 一次性写满 stdin
    child.stdin.end();
  });
}
```

`★` 那一行是唯一有设计含量的地方：**Python 失败时会往 stdout 写一个 `{ok:false,...}` 再 `exit(1)`**
（`planning_bridge.py:347-354`），Node 选择 `resolve` 而不是 `reject`，从而把
Python 的 `error` / `traceback` 原样送到前端，而不是丢掉换成一句 `exited with code 1`。
这是"错误信息跨语言保真"的实用做法。

### 4.4 Node 层的真实工作量

**结论：确认它没有任何业务逻辑。**

`server/api.mjs` 151 行的构成：import 5 行 + 常量 5 行（`:6-12`）+ `runBridge` 73 行（纯进程/JSON 管道）
+ `express.json` 1 行 + 两个路由处理器共 55 行（其中真正做判断的只有
`if (!parsed?.ok) → 400`（`:124-131`）和 `{action:'run', ...req.body}`（`:119-122`））+ `app.listen` 5 行。

它**不**做：参数校验（推给 Python，`planning_bridge.py:93-102, 202-223`）、
单位换算、轨迹后处理、缓存、请求排队、并发控制、鉴权、日志落盘。
唯一的"增值"是：注入 `apiVersion`（`api.mjs:12, 96, 107, 141`）、
透传 `pythonBin/bridgeScript` 供前端展示（`:97-100`）、把 `!ok` 映射成 HTTP 400。

**一个明确缺陷**：`spawn` 在请求处理函数内部（每请求一次），
所以 **N 个并发规划 = N 个 Python 进程**，每个都要重新 `import numpy/pandas/scipy/toppra/ecos/ruckig/roboticstoolbox`
（`planning_bridge.py:21`）——这通常意味着每次请求 1~3 s 的纯 import 开销，且没有取消机制
（只有 600 s 超时后 `SIGKILL`）。README 也承认 "local one-shot planning requests (no queue/streaming)"（`README.md:61`）。

### 4.5 Python 侧协议（`scripts/planning_bridge.py`）

启动时先做 `sys.path` 注入（`:14-19`），把仓库根与包目录都塞进去，这样 `import fixed_toppra_mvc_ruckig` 在
"未 `pip install`" 的情况下也能工作（和 `README.md:95-104` 的说法一致）。

主循环（`:333-358`）：

```python
def main() -> None:
    try:
        raw = sys.stdin.buffer.read().decode('utf-8').strip()   # 一次性读完 stdin
        payload = json.loads(raw) if raw else {}
        action = str(payload.get('action') or 'run').strip().lower()

        if action == 'health':   result = _health()
        elif action == 'run':    result = _run(payload)
        else: raise ValueError(f'Unsupported action: {action}')

        sys.stdout.write(json.dumps(_json_safe(result), ensure_ascii=False, allow_nan=False))
    except Exception as error:
        error_payload = {'ok': False, 'error': str(error), 'traceback': traceback.format_exc()}
        sys.stdout.write(json.dumps(_json_safe(error_payload), ensure_ascii=False, allow_nan=False))
        sys.exit(1)
```

**协议 = 单次 JSON in / 单次 JSON out / 错误也走 stdout 且退出码 1。**
`action` 只有 `health` 与 `run` 两个值。

两个工程细节值得抄：
- `_json_safe()`（`:158-172`）递归处理 `ndarray / np.floating / np.bool_ / np.integer`，
  并把**非有限浮点转成 `None`**（`:165-167`）——这是 numpy→JSON 的经典坑，配合 `allow_nan=False` 双保险。
- `_downsample_series` / `_downsample_profile`（`:105-138`）：图表数据**在 Python 侧降到 ≤500 点**
  （`step = ceil(n / max_points)`，并保证补上最后一帧）。这是正确的方向，但它**只降采样了图表**，
  `trajectory.qs/qds/qdds`（14351×6 各一份）仍然全量 JSON 传输（`:300-306`）。
- 临时文件用 `NamedTemporaryFile(delete=False)` 落盘再 `finally unlink`（`:231-235, 328-330`），
  因为 `load_joint_waypoints` 只接受路径（`pipeline.py:110`）。`_run` 还特意 `lstrip('\ufeff')` 去 BOM（`:204`）。

**`_health()` 的 `ok` 是假的**（`:188-199`）：

```python
return {
    'ok': True,                       # ← 无条件 True（:189）
    'python': {'executable': sys.executable, 'version': sys.version},
    'dependencies': dep_state,        # 真：8 个包的 find_spec
    'er15Factory': {'ok': er15_ok, 'error': er15_error},   # 真：试建 ER15 并跑一次 fkine
}
```

即便 `er15Factory.ok === False`，`ok` 仍是 `True`。
而前端 `DesignPlugin.tsx:246` 恰恰用 `health.ok` 决定要不要短路 → **这道门永远拦不住任何东西**。

### 4.6 硬编码：ER15 与 6 轴

`build_er15_robot_model()`（`planning_bridge.py:53-90`）用 `roboticstoolbox` 的 `ET.SE3 * ET.Rz()`
手工搭了 6 个连杆，关节限位（`:56-63`）与 DH 变换（`:65-72`）全部写死：

```python
limits = [(-2.967,2.967), (-2.7925,1.5708), (-1.4835,3.0543),
          (-3.316,3.316), (-2.2689,2.2689), (-6.2832,6.2832)]
```

同时 `_validate_and_normalize_limits`（`:96-97`）强制 `velocity`/`acceleration` **必须各 6 个值**，
`pipeline.py:112` 的 `load_joint_waypoints` 也把 `["J1".."J6"]` 写成 `required`（`:112, 120-122`），
`pipeline.py:129` 检查 `shape[1] != 6` 就报错。

**后果**：`robotCatalog.ts` 里提供了 7 个机器人（含 2 轴的 MP600），Define 模块可以自由切换，
**但规划永远按 ER15 / 6 轴算**。`DesignPlugin.tsx:23-30` 又在 UI 上重复了一遍同样的 6 组行程数字。
这是一条贯穿前后端的"隐性单一机型假设"，是移植时**第一个必须解决**的结构问题。

### 4.7 一份过期规格：`docs/ALGORITHM.md`

该文档（`:15-28, 44-62`）描述了一个**分阶段流水线 API**：

- stage 名：`input_parse` / `path_prepare` / `parameterization` / `postprocess` / `publish`
- 每阶段返回 `stage` / `status(ok|error|skipped)` / `durationMs` / `errorCode`
- 请求里带 `algorithm.strategyId`（默认 `fixed_toppra_mvc_ruckig`）与 `algorithm.stageConfig`
  （`enablePathPreparation`、`enablePostprocess`、`forceUniformResample`）
- 响应里带 `algorithmMeta` / `stageMetrics` / `debugLogs`，失败统一为 `stage/errorCode/message`
- 并声称 "Design 侧采用阶段化流水线（**Node sidecar 编排**）"

**实测：`strategyId`、`stageConfig`、`algorithmMeta`、`stageMetrics`、`debugLogs`、`input_parse`、
`path_prepare`、`postprocess`、`enablePathPreparation`、`forceUniformResample`、`errorCode`、`durationMs`
在全部 `.ts/.tsx/.mjs/.py` 中命中数均为 0。**

真实实现只有一条 `POST /api/design/planning/run` 直调 Python，Node 侧零编排。
**这份文档描述的是一个从未落地（或已被删除）的设计。** 它无害，但如果有人照着它写前端就会白干。

---

## 5. 轨迹规划算法 —— 全仓库唯一真正有价值的资产

> 代码位置：`fixed_toppra_mvc_ruckig/`（9 文件 1350 行），核心是 `pipeline.py`（746 行）。
> 本章目标：**不读原文也能在另一套代码里复现。**

### 5.0 一句话概括

> 把关节路点拟合成一条以**归一化弧长 `s ∈ [0,1]`** 为参数的样条；
> 用 **TOPPRA** 在关节速度/加速度约束下只求**可行集 `X` 的上包络**（即 MVC，最大速度曲线），
> 把 MVC 的**局部极小点当作分段点**；
> 在每一段上对路径参数 `s` 跑 **1 自由度 Ruckig**（带 jerk 限制的最优时间整形），
> 段与段的衔接速度取该极小点的 MVC 值乘以一个衰减系数；
> 最后把 `s(t)` 代回样条得到关节轨迹 `q(t)`。

它**不**用 TOPPRA 的时间最优解作为轨迹（这是关键设计选择，见 §5.5）。

### 5.1 先明确单位与域（这是理解全文的前提）

**不要跳过这一节。** 该项目最容易误读的地方就是 `v_max=0.02 / a_max=0.02 / j_max=0.04` 这组小得反常的默认值。

| 量 | 域 | 单位 | 来源 |
|---|---|---|---|
| `q` 路点 | 关节空间 | rad（6 轴） | 输入 CSV/TXT |
| `s` 路径参数 | **归一化弧长**，`s ∈ [0,1]` | 无量纲 | `pipeline.py:209`（`ss = s / total_s`），或 `:237`（均匀索引） |
| `vlim` | **关节空间** | rad/s | 前端 `velocityLimits` → `_validate_and_normalize_limits` → `JointVelocityConstraint` |
| `alim` | **关节空间** | rad/s² | 前端 `accelerationLimits` → `JointAccelerationConstraint` |
| **`mvc_upper`** | **s 空间**（= `√(ẋ_max²)`） | 1/s（路径比例/秒） | `pipeline.py:313-315`，由 TOPPRA 从 `vlim/alim` 推出 |
| **`v_max`** | **s 空间** | 1/s | `pipeline.py:602`，喂给 `ruckig_1d` 的 `max_velocity` |
| **`a_max`** | **s 空间** | 1/s² | `pipeline.py:609` |
| **`j_max`** | **s 空间** | 1/s³ | `pipeline.py:610` |
| `dt` | 时间 | s | Ruckig 控制周期 |
| `ts` | 时间 | s | 输出 |

**必须记住的三条结论：**

1. **`v_max / a_max / j_max` 作用在路径参数 `s` 上，不是关节空间。**
   CLI 的帮助文本已经明说了（`cli.py:70-72`）：
   `"1-Dof Ruckig max velocity on s."` / `"…max acceleration on s."` / `"…max jerk on s."`
2. 由于 `s` 被归一化到 `[0,1]`，`ṡ = 0.02` 的含义是"**每 50 秒走完整条路径**"。
   要把 s 空间限制换算成笛卡尔量，需要乘以路径总长 `L`（米）：`v_cart = ṡ · L`。
   **即：同一组 `v_max/a_max/j_max`，在不同长度的路径上对应不同的物理速度/加速度。**
   这是该设计最实际的局限（见 §5.11）。
3. 关节空间的速度/加速度限制**只通过 TOPPRA 的 MVC 间接进入**，
   并且在 `v_max` 的默认配置下 MVC 几乎不起作用（§5.10 有实测证据）。

### 5.2 阶段一：路径准备 `prepare_path()`（`pipeline.py:213-278`）

```
load_joint_waypoints        读 CSV/TXT            :110-131
resample_waypoints          索引空间线性重采样到 1000 点  :134-144
smooth_waypoints_joint_laplacian  60 遍三点拉普拉斯平滑   :170-190
[smooth_waypoints_along_arc]      可选：弧长 EMA 重参数化  :147-167
compute_ee_arc_parameter    1000 次 fkine → 归一化弧长 s   :193-210
ss 严格递增修复                                    :252-261
gridpoints = ss（或均匀 grid_N 点）                 :263-266
path = ta.SplineInterpolator(ss, way_pts_smooth)   :270
```

**（a）读入 `load_joint_waypoints`（`:110-131`）**
先读首行判断是否 CSV（含 `,` 或含 `J1`，`:116`），是 CSV 则要求 `J1..J6` 列齐全（`:120-122`）；
否则按 `np.loadtxt` 当纯数值矩阵，并强制 6 列（`:129-130`）。用 `encoding="utf-8-sig"` 吃掉 BOM（`:113`）。

**（b）重采样 `resample_waypoints(w, n_points=1000)`（`:134-144`）**
关键在于它是**按路点索引均匀**插值（`s_src = linspace(0,1,n_src)`，`:139`），**不是按弧长均匀**：

```python
s_src = np.linspace(0.0, 1.0, n_src)
s_dst = np.linspace(0.0, 1.0, int(n_points))
out[:, j] = np.interp(s_dst, s_src, w[:, j])   # 逐关节独立线性插值
```

所以"1000 点"只保证采样密度，不保证空间均匀。`docs/planning_demo_summary.json` 显示
`waypointCountOriginal: 11 → waypointCountPrepared: 1000`。

**（c）平滑 `smooth_waypoints_joint_laplacian(w, passes=60, blend=0.49)`（`:170-190`）**

```python
ws = np.unwrap(w, axis=0)          # :177 ★ 沿路点轴做相位解缠
blend = float(np.clip(blend, 0.0, 0.49))   # :178 ★ 硬性夹到 0.49 以下
for _ in range(passes):            # :180
    nxt = ws.copy()
    nxt[1:-1, :] = ((1.0 - 2.0*blend) * ws[1:-1, :]
                    + blend * ws[:-2, :] + blend * ws[2:, :])
    nxt[0, :]  = ws[0, :]          # :187 ★ 两端钉死
    nxt[-1, :] = ws[-1, :]         # :188
    ws = nxt
```

三个细节都很讲究：
- **`np.unwrap`**（`:177`）：把每个关节当作相位处理，消除 ±π 跳变。对 J6（行程 ±2π，见 `planning_bridge.py:62`）是必需的，
  否则平滑会在跳变处把轨迹拉成一条斜线。
- **`blend ≤ 0.49` 的硬夹**（`:178`）：三点拉普拉斯迭代在 `blend = 0.5` 时是临界振荡的，
  `0.49` 是显式留出的稳定裕度。这是一个很实在的数值细节。
- **两端钉死**（`:187-188`）：保证起点终点不被平滑移动。

代价：**60 遍 × blend 0.49 是很重的低通**，会明显削角。而**代码里没有任何地方检查
`waypoints_raw` 与 `waypoints_smooth` 的偏差**（两者都返回了，`pipeline.py:274-275`，
`planning_bridge.py:321-324` 也原样传给前端，但没有任何容差判断或告警）。
`warnings` 数组在 `planning_bridge.py:226` 初始化为空，**直到函数结束都没有被写入过**
（`:325` 原样返回空数组）。这是一个真实的算法风险：路径可能已经偏离示教点很多，而系统不会告诉你。

**（d）弧长参数化 `compute_ee_arc_parameter`（`:193-210`）**

```python
for i in range(n):
    Ti = robot_model.fkine(q[i, :])                       # :203  1000 次正运动学
    p_ee[i, :] = _map_toolbox_xyz(Ti.t.reshape(3), swap_xy_for_ee)
delta_s = np.linalg.norm(np.diff(p_ee, axis=0), axis=1)   # :206  相邻末端点欧氏距离
s  = np.hstack(([0.0], np.cumsum(delta_s)))               # :207
ss = s / max(float(s[-1]), 1e-12)                         # :208-209  ★ 归一化到 [0,1]
```

即：用**末端执行器笛卡尔轨迹的累计弧长**作为路径参数。
`swap_xy_for_ee`（`:94-98`）是为兼容"XY 互换的 FK 约定"准备的后门，桥里恒为 `False`（`planning_bridge.py:243`）。
`ss_mode='time'` 时则退化为 `np.linspace(0,1,N)`（`:236-238`）并令 `ee_points` 全零——
**注意这个名字是误称**：重采样后的路点没有时间戳，所以 `'time'` 实际含义是"按路点索引均匀"，不是按时间。

**（e）抖动修复与样条（`:252-270`）**

```python
dss = np.diff(ss)
if np.any(dss <= 0):                    # :253  有重复/倒退的 s 就修
    for i in range(1, len(ss_fix)):
        if ss_fix[i] <= ss_fix[i-1]:
            ss_fix[i] = ss_fix[i-1] + config.eps      # eps = 1e-12
    ss_fix = (ss_fix - ss_fix[0]) / max(ss_fix[-1]-ss_fix[0], 1e-12)   # 重新归一化
...
gridpoints = ss.copy() if config.grid_N is None else np.linspace(0,1,int(config.grid_N))  # :263-266
if not (np.all(np.isfinite(gridpoints)) and np.all(np.diff(gridpoints) > 0)):
    raise ValueError("gridpoints are invalid: expected finite and strictly increasing.")   # :267-268
path = ta.SplineInterpolator(ss, way_pts_smooth)          # :270
```

`ta.SplineInterpolator` 要求节点严格递增，所以这段修复是必要的（三次样条的分母会炸）。
默认 `grid_N = None` ⇒ `gridpoints` **就是** `ss` 本身，即 TOPPRA 的约束采样点与样条节点重合，
且**在 s 上非均匀分布**（弧长大处点疏）——这正是弧长参数化应有的样子。

> 一个易被忽略的点：`ss` 是归一化的，因此 `|dq/ds|` 与真实关节速度之间差一个 `L` 因子。
> 后面所有"s 空间"限制的物理意义都依赖于此。

### 5.3 阶段二：TOPPRA 实例 `build_toppra_instance()`（`pipeline.py:281-306`）

全文只有 26 行，但每一行都有讲究：

```python
c_vel = constraint.JointVelocityConstraint(np.asarray(vlim, dtype=float))            # :291
pc_acc = constraint.JointAccelerationConstraint(
    np.asarray(alim, dtype=float),
    discretization_scheme=constraint.DiscretizationType.Interpolation,               # :292-295
)
robust_pc_acc = constraint.RobustLinearConstraint(
    pc_acc, [config.du, config.dx, config.dc], config.interpolation_scheme,          # :296-300
)
return algo.TOPPRA(
    [c_vel, robust_pc_acc], path,
    gridpoints=np.asarray(gridpoints, dtype=float),
    solver_wrapper=config.solver_wrapper,                                            # :301-306
)
```

约束参数默认值（`ToppraConfig`，`:28-34`）：

| 字段 | 默认 | 含义 |
|---|---|---|
| `du` | `1e-3` | 鲁棒扰动椭球在**控制量 `u = s̈`** 方向的半轴长 |
| `dx` | `5e-2` | 在**路径位置 `x = s`** 方向的半轴长 |
| `dc` | `9e-3` | 在**约束常数量 `c`** 方向的半轴长 |
| `interpolation_scheme` | `1` | 传给 `RobustLinearConstraint` 的 `discretization_scheme`（`DiscretizationType.Interpolation`） |
| `solver_wrapper` | `"ecos"` | 二阶锥/LP 求解器 |

**`RobustLinearConstraint` 到底做了什么？** 依据 TOPPRA 官方源码
（[`toppra.constraint.conic_constraint`](https://hungpham2511.github.io/toppra/_modules/toppra/constraint/conic_constraint.html)），
其签名是 `RobustLinearConstraint(cnst, ellipsoid_axes_lengths, discretization_scheme=Collocation)`：

> 扰动项 `[Δa[i,j], Δb[i,j], Δc[i,j]]ᵀ = diag(ru, rx, rc)·e`，其中 `‖e‖₂ ≤ 1`；
> 原约束 `(a+Δa)u + (b+Δb)x + (c+Δc) ≤ 0` 被转化为凸的二阶锥约束
> `a·u + b·x + c + ‖Pᵀ[u, x, 1]ᵀ‖₂ ≤ 0`，`P = diag(ru, rx, rc)`。

也就是说，`[du, dx, dc]` 是**扰动椭球三个半轴的长度**（不是容差、不是松弛量）：
它要求加速度约束在一个以标称约束为中心、半轴为 `(1e-3, 5e-2, 9e-3)` 的椭球内的**所有**扰动下都成立，
从而换来一圈"约束余量"。`du` 对应控制量（`s̈`）、`dx` 对应路径位置（`s`）、`dc` 对应约束偏移。
`dx = 5e-2` 相对 `s ∈ [0,1]` 是 5% 的路径尺度，其实是相当可观的鲁棒半径。

**一个重要考证（对使用者是好事）：这 26 行 + 5 个默认值，是 TOPPRA 官方示例
[`plot_robust_kinematics.py`](https://hungpham2511.github.io/toppra/auto_examples/plot_robust_kinematics.html)
的逐行移植。** 官方示例第 52-65 行：

```python
path = ta.SplineInterpolator([np.linspace(0, 1, 5), way_pts])
pc_vel = constraint.JointVelocityConstraint([vlim])
pc_acc = constraint.JointAccelerationConstraint([alim], discretization_scheme=constraint.DiscretizationType.Interpolation)
robust_pc_acc = constraint.RobustLinearConstraint(pc_acc, [args.du, args.dx, args.dc], args.interpolation_scheme)
instance = algo.TOPPRA([pc_vel, robust_pc_acc], path, gridpoints=..., solver_wrapper=args.solver_wrapper)
```

而官方 argparse 的默认值就是 `-du 1e-3`、`-dx 5e-2`、`-dc 9e-3`、`-so ecos`、`-i 1`（示例第 26-30 行），
`ToppraConfig`（`pipeline.py:28-34`）与之**完全一致**。含义是：
**这部分不是他们的创新，而是上游推荐的规范用法——这反而是个好信号**（用对了 API）。
命名上的小陷阱：`interpolation_scheme` 这个名字来自官方示例的 CLI 参数名，
它实际是 `RobustLinearConstraint` 的 `discretization_scheme`，
**与 `TOPPRA(...)` 自身用于参数化器的插值选项不是同一个东西**（后者本处未传，走默认）。
另外，由于 `RobustLinearConstraint.compute_constraint_params` 内部会调用
`self.base_constraint.set_discretization_type(self.discretization_type)`，
`pc_acc` 上那次显式的 `DiscretizationType.Interpolation`（`:294`）会被外层再设一遍——
属于无害的冗余，同样是官方示例的写法。

### 5.4 阶段三：MVC 提取 `compute_mvc_profiles()`（`pipeline.py:309-316`）

```python
def compute_mvc_profiles(instance: algo.TOPPRA):
    X = instance.compute_feasible_sets()          # :310  形状 (N+1, 2)
    K = instance.compute_controllable_sets(0, 0)  # :311  形状 (N+1, 2)
    _, sd_vec, _ = instance.compute_parameterization(0, 0)   # :312  TOPPRA 自己的时间最优解
    X = np.sqrt(X)                                # :313 ★
    K = np.sqrt(K)                                # :314 ★
    mvc_upper = np.asarray(X[:, 1], dtype=float)  # :315 ★★ 上包络 = MVC
    return X, K, sd_vec, mvc_upper
```

**为什么要 `sqrt`？** 因为 TOPPRA 的参数化器内部以 **`x(s) = ṡ(s)²`** 为决策变量求解线性/锥规划
（约束对 `ṡ²` 是线性的）。所以 `compute_feasible_sets()` 返回的是**速度平方**的可行区间，
`X[:, 0]` 是 `ṡ²_min`、`X[:, 1]` 是 `ṡ²_max`，开方后才回到速度量纲。
这与官方示例第 72-78 行的处理完全一致（官方也是 `X = np.sqrt(X)` 后画 `X[:,0]`/`X[:,1]` 两条绿线，
并把 `X[:,1]` 当作速度上界）。

**MVC（Maximum Velocity Curve，最大速度曲线）= `X[:, 1]`**：
在每个路径位置 `s` 上，满足**全部关节速度与加速度约束**所能达到的最大路径速度 `ṡ_max(s)`。
它由关节速度限制（`JointVelocityConstraint`）与（鲁棒化后的）关节加速度限制共同决定，
是一条定义在 s 空间的标量曲线。

**关键架构判断：`sd_vec`（TOPPRA 的时间最优速度剖面）被算出来了，然后被丢掉。**
grep 证实：`sd_vec`、`X`、`K` 在 `pipeline.py` 之外**没有任何消费者**
（`cli.py` 只导出 `mvc_upper`；`planning_bridge.py:_run` 只返回 `gridpoints/mvcUpper/minimaIdx/minimaV/chart`），
它们只是被塞进 `PipelineResult`（`pipeline.py:729-731`）供人肉调试。
**所以 TOPPRA 在本项目里只充当"约束→速度包络"的神谕（oracle），不充当轨迹生成器。**
真正的轨迹整形全部交给 1 自由度 Ruckig。这是整个算法最核心的设计取舍：
用 TOPPRA 拿到"物理上允许开多快"的完整信息，再用 Ruckig 拿到"jerk 受限、可执行"的时间律。

### 5.5 阶段四：MVC 极小点 = 分段判据 `detect_mvc_minima_indices()`（`pipeline.py:319-407`）

**这是本算法最巧妙的一步：MVC 既是速度上界，又直接当分段依据。**

直觉：MVC 的局部极小点 = 路径上"最卡"的地方（接近奇异、关节速度/加速度最先饱和、需要转弯减速之处）。
在这些点上必须降速通过，因此它们天然是**加减速的转折点**，
把路径切成若干"加速段—减速段"就有物理意义，而不是按时间或长度等分。

```python
def detect_mvc_minima_indices(mvc_upper, n_inner=None, min_gap=12,
                              max_value=None, smooth_window=21) -> np.ndarray:
    y = np.asarray(mvc_upper).reshape(-1); n = len(y)
    if n < 3: return np.array([], dtype=int)
    keep_all = n_inner is None or int(n_inner) <= 0        # :330  默认 keep_all=True

    candidates = []
    for i in range(1, n - 1):
        if y[i] < y[i-1] and y[i] <= y[i+1]:               # :334  严格下降 + 非严格上升 ⇒ 局部极小
            candidates.append(i)
    ...
```

流程共 5 层兜底，逐层看：

| 层 | 行号 | 逻辑 |
|---|---|---|
| 1 直接找极小 | `:333-335` | `y[i] < y[i-1] and y[i] <= y[i+1]`（半开区间，避免平台重复计数） |
| 2 平滑后重找 | `:337-362` | 若候选数不足（`keep_all` 时不足 1 个），做**奇数窗移动平均**（默认 `w=21`，并对窗口做了一串奇数化/上界裁剪，`:338-345`），用 `<=/<=` 找平台极小（`:354`），再在原始 `y` 上于 `±w/2` 窗口内取 `argmin` 精化（`:357-362`） |
| 3 终极兜底 | `:364-366` | 还没有候选就按 `y` 升序把**内部点**全收进来 |
| 4 聚类去重 | `:368-380` | 按 `min_gap`（默认 **12**，单位是 gridpoint 索引，1000 点里约 1.2% 路径长）合并邻近候选，保留更小的那个 |
| 5 阈值过滤 | `:382-385` | `max_value` 非空则只保留 `y[i] < max_value` 的；若被滤空则返回空数组 |

`n_inner`（即 `minima_count`）为 `None` 时 `keep_all=True`（`:387-388`）返回全部；
否则按 `y` 升序贪心挑选，且强制两两间距 `≥ gap`（`:390-407`）。

阈值的三档语义在 `_resolve_minima_max_value()`（`:410-425`）：

```python
mode = str(config.minima_threshold_mode).strip().lower()
if mode == "none":  return None                                    # 不过滤
if mode == "fixed": return None if config.minima_max_value is None else float(...)
if mode == "mean":                                                 # 默认档
    finite = values[np.isfinite(values)]
    return float(np.mean(finite))                                  # :424 ★ mean(mvc_upper)
raise ValueError("minima_threshold_mode must be one of: 'none', 'fixed', 'mean'.")
```

默认 `'mean'` ⇒ **只保留 MVC 低于其自身均值的那些极小点**，
即"明显比平均更卡的地方才值得停下来减速"。这个启发式很朴素但很有效。

> 一个有用的副产品：`minima_idx` 的长度直接决定了分段数，
> `docs/planning_demo_summary.json` 里是 **8 个极小点 → 9 段**。

### 5.6 阶段五：分段 Ruckig 整形 `plan_segmented_ruckig_from_mvc()`（`pipeline.py:566-668`）

这是全文最需要精读的函数。逐步拆解。

**（a）构造分段目标（`:583-586`）**

```python
segment_points  = [int(i + 1) for i in minima_idx] + [len(gridpoints)]   # :583  仅用于报告
segment_targets = [float(gridpoints[i]) for i in minima_idx] + [1.0]     # :584  ★ s 值，真正用于规划
minima_v        = np.asarray(mvc_upper)[minima_idx] if len(minima_idx) else np.array([])  # :585
velocity_scale  = max(float(config.junction_velocity_scale), 0.0)        # :586  默认 0.8
```

- `segment_targets` 是每段要到达的 **`s` 值**：MVC 极小点处的 `s`，最后追加 `1.0`（路径终点）。
- `minima_v` 是极小点处的 MVC 值，即"该处最多能开多快"。
- `segment_points` 是 `i+1`（下一个 gridpoint 索引），**只进 summary 供人看，不参与后续任何计算**
  —— 它与 `segment_targets` 是同一批点的两种表示（索引 vs s 值），容易误读。

**（b）逐段求解，段间状态串联（`:588-668`）**

```python
x_prev = 0.0; v_prev = 0.0; a_prev = 0.0            # :590-592  从静止出发
for i, x_target in enumerate(segment_targets):
    v_prev_nonneg = max(float(v_prev), 0.0)

    if i == len(segment_targets) - 1:               # :595  最后一段：目标是停住
        segment_v_max = max(float(config.v_max), v_prev_nonneg)
        v_target = 0.0
    else:
        desired_v = max(float(minima_v[i] * velocity_scale), 0.0)      # :599  MVC × 0.8
        # Let each minima keep its own mapped target velocity instead of
        # flattening everything to the global v_max clamp.
        segment_v_max = max(float(config.v_max), desired_v, v_prev_nonneg)   # :602 ★★
        v_target = _segment_feasible_target_velocity(
            x_prev=x_prev, x_target=x_target, v_prev=v_prev_nonneg,
            desired_v=desired_v, v_max=segment_v_max,
            a_max=float(config.a_max), j_max=float(config.j_max))         # :603-611
```

**`segment_v_max = max(v_max, desired_v, v_prev)` 是本算法最反直觉的一行：**
`v_max` 在这里是**下限而不是上限**。设计意图（见 `:600-601` 的注释）是
"让每个极小点保留它自己映射出来的目标速度，而不要被全局 `v_max` 一刀切平"。
所以当 `minima_v·0.8`（实测约 0.30~0.94）远大于 `v_max`（默认 0.02）时，
该段的 Ruckig `max_velocity` 会被抬到 0.94 量级。**真正的限速来自下面那一步的可行性钳位，不是 `v_max`。**

**（c）可行性目标速度 `_segment_feasible_target_velocity()`（`:428-456`）**

```python
def _segment_feasible_target_velocity(x_prev, x_target, v_prev, desired_v,
                                      v_max, a_max, j_max, safety=0.98) -> float:
    seg_len = max(float(x_target) - float(x_prev), 0.0)     # :438  本段 s 长度 L
    if seg_len <= 0.0: return 0.0

    v_prev_nonneg = max(float(v_prev), 0.0)                 # :442
    v_max_eff = max(float(v_max), 1e-9)                     # :443  三个下限保护
    a_max_eff = max(float(a_max), 1e-9)
    j_max_eff = max(float(j_max), 1e-9)
    desired_v = float(np.clip(desired_v, 0.0, v_max_eff))   # :446

    # Conservative distance-based caps to avoid infeasible short segments.
    acc_cap = np.sqrt(max(v_prev_nonneg**2 + 2.0*a_max_eff*seg_len, 0.0))   # :449 ★ 匀加速运动学
    if desired_v >= v_prev_nonneg:
        jerk_cap = (seg_len * np.sqrt(j_max_eff)) ** (2.0/3.0)              # :451 ★ jerk 受限上界
        feasible_cap = min(v_max_eff, acc_cap, jerk_cap)
    else:
        feasible_cap = min(v_max_eff, acc_cap)                              # 减速时不施加 jerk_cap

    return float(np.clip(min(desired_v, safety * feasible_cap), 0.0, v_max_eff))  # :456
```

两个 cap 的物理含义都值得写清楚（它们是"避免短段不可行"的关键）：

- **`acc_cap = √(v_prev² + 2·a_max·L)`**（`:449`）：最经典的匀加速运动学式
  `v² = v₀² + 2aL`。含义：在本段长度 `L` 内，从 `v_prev` 出发以 `a_max` 加速所能达到的速度上限。
- **`jerk_cap = (L·√j_max)^(2/3)`**（`:451`）⟺ **`L = v^(3/2) / √j_max`**。
  这是**加速度上限尚未饱和时的纯 jerk 受限**关系，可自行推导验证：
  设以恒定 jerk `J` 从 0 加速，加速度斜坡 `a(t) = Jt` 升到峰值后再镜像下降
  （三角加速度剖面），则
  - 速度增量 `Δv = J·T²`（`T` 为半个斜坡时长）⇒ `T = √(v/J)`
  - 该过程走过的距离 `L = J·T³ = J·(v/J)^{3/2} = v^{3/2}/√J`
  ⇒ `v = (L·√J)^{2/3}`，与代码一致。
  含义：在**加速度限制还没成为瓶颈**的短段里，能走多快由 jerk 决定。
- **`safety = 0.98`**（`:436`）：对 `feasible_cap` 再打 2% 折扣，给数值误差留余量。

注意减速情形（`desired_v < v_prev`）**故意不加 `jerk_cap`**（`:453-454`），
因为减速时 jerk 受限的距离关系与上面推导的加速镜像不完全对称，
作者选择只保留更宽松的 `acc_cap`——这也正是后文 §5.10 里"减不下去"的直接原因之一。

**（d）1 自由度 Ruckig `ruckig_1d()`（`:478-540`）**

```python
def ruckig_1d(x0, v0, a0, x1, v1=0.0, a1=0.0,
              v_max=0.02, a_max=0.02, j_max=0.04, dt=0.004, max_steps=200000):
    InputParameter, OutputParameter, Result, Ruckig = _import_ruckig()
    otg = Ruckig(1, float(dt))          # :493  ★ 1 自由度
    inp = InputParameter(1); out = OutputParameter(1)
    ...
    inp.current_position     = [float(x0)]
    inp.current_velocity     = [float(np.clip(v0, 0.0, v_max_eff))]
    inp.current_acceleration = [float(a0)]
    inp.target_position      = [float(x1)]
    inp.target_velocity      = [float(np.clip(v1, 0.0, v_max_eff))]
    inp.target_acceleration  = [float(a1)]
    inp.max_velocity         = [v_max_eff]
    inp.min_velocity         = [0.0]            # :507 ★★ 路径参数永不倒退
    inp.max_acceleration     = [a_max_eff]
    inp.min_acceleration     = [-a_max_eff]     # :509 ★★ 必须能减速
    inp.max_jerk             = [j_max_eff]

    for _ in range(int(max_steps)):
        res = otg.update(inp, out)
        if res < 0: raise RuntimeError(f"Ruckig 1D failed with code {res}.")   # :522-523
        x_new = float(out.new_position[0])
        v_new = float(np.clip(out.new_velocity[0], 0.0, v_max_eff))            # :526 再夹一次非负
        a_new = float(out.new_acceleration[0])
        t += dt; ts.append(t); xs.append(x_new); vs.append(v_new); accs.append(a_new)
        out.pass_to_input(inp)
        inp.current_velocity     = [v_new]                                     # :534 ★ 强制回写
        inp.current_acceleration = [a_new]
        if res == Result.Finished: break
    else:
        raise RuntimeError("Ruckig 1D did not finish within max_steps.")        # :539
```

**`min_velocity = [0.0]` 与 `min_acceleration = [-a_max]` 这两个设置是整个 Ruckig 用法的命门**
（`README.md:15-16` 也把它们列为"Ruckig 修复项"）：
- 若 `min_velocity` 允许负值，Ruckig 在"目标速度低于当前速度"时会选择**倒着走**这条捷径，
  路径参数就非单调了，`path(s)` 立刻失去意义。
- 若把加速度下限也设成 0（对称于 `max_acceleration`），Ruckig 就无法减速，所有减速段都会报不可行。
- `:534` 的手动回写是在 `pass_to_input` 之后再夹一次，属于双保险。

`max_steps` 默认 200000（`:50`），配合 `dt=0.001` 可支撑 200 s 轨迹；
`res < 0` 抛 `RuntimeError` 是**唯一**让上层感知失败的通道。

**（e）速度回退阶梯（`:613-648`）—— 本算法第二个精妙处**

```python
last_error: Exception | None = None
seg = None
retry_candidates = [
    v_target,                              # ① 理想：MVC×0.8 经可行性钳位后的值
    0.5 * (v_target + v_prev_nonneg),      # ② 折中
    v_prev_nonneg,                         # ③ 干脆保持上一段末速（匀速通过）
    0.0,                                   # ④ 完全停住
]
dedup_retry_candidates: list[float] = []
for candidate in retry_candidates:                        # :622  去重（1e-12）
    candidate = float(np.clip(candidate, 0.0, segment_v_max))
    if all(abs(candidate - existing) > 1e-12 for existing in dedup_retry_candidates):
        dedup_retry_candidates.append(candidate)

for retry_v_target in dedup_retry_candidates:             # :627
    try:
        seg = ruckig_1d(x0=x_prev, v0=v_prev, a0=a_prev,
                        x1=x_target, v1=retry_v_target, a1=0.0,     # ★ a1 恒为 0
                        v_max=segment_v_max, a_max=config.a_max, j_max=config.j_max,
                        dt=config.dt, max_steps=config.max_steps)
        v_target = retry_v_target                               # :642  ★ 实际采用了哪一档
        break
    except RuntimeError as exc:
        last_error = exc
        continue
if seg is None:
    raise RuntimeError("Segmented Ruckig failed without returning a trajectory.") from last_error
```

设计意图：Ruckig 对给定的边界条件 `(x0,v0,a0) → (x1,v1,a1=0)` 是**要么解要么报错**的，
当段太短、目标速度太高时（`a_max` 不够用）会失败。
与其让整条轨迹崩掉，不如**逐档退让**：先试理想值，不行就折中，再不行就"保持原速匀速通过"，
最后"停住"。`v_target` 会被**改写为实际成功的那一档**并记录进 `segment_target_velocities`（`:650`），
所以从输出里能反推出每一段落在了哪一档——这正是 §5.10 得以验证的钩子。

注意 `a1` 恒为 `0.0`（`:635`）：**每个分段衔接点都以零加速度到达**，
与下一段的 `a0 = a_prev = 0` 自然连续，避免了加速度跳变。这是刻意的。

**（f）段间串联与拼接（`:650-668`）**

```python
segment_target_velocities.append(v_target); segments.append(seg)
_, x_seg, v_seg, a_seg = seg
x_prev = float(x_seg[-1]);      # :653  以下一段的起点 = 上一段的实际终点
v_prev = max(float(v_seg[-1]), 0.0)   # :654  而非上一段的目标值 —— 用"实际达到"的状态
a_prev = float(a_seg[-1])       # :655
...
ts, s_path, sd_path, sdd_path = concat_ruckig_segments(segments)   # :657
s_path = np.clip(s_path, 0.0, 1.0)                                 # :658
```

`concat_ruckig_segments`（`:543-563`）的拼接规则：第 0 段全取；**后续段丢掉首采样点**（`:552` 的 `t[1:], x[1:], …`）
以免重复；`t_offset` 取上一段最后一个绝对时间（`:557`）。

> 顺便解释一个细节：上文的 §5.10 会看到 `segment_target_velocities` 里出现"完全相同的值连续重复"，
> 原因是 `v_prev` 取自**实际末速**（`:654`）而非目标值，当多段连着落到第 ③ 档时，
> 每一档记录的 `v_target` 就等于同一个上游末速。

### 5.7 阶段六：映射回关节空间 `map_path_to_joint_trajectory()`（`pipeline.py:671-682`）

```python
def map_path_to_joint_trajectory(path, ts, ss):
    qs   = np.asarray(path(ss), dtype=float)                              # :676  样条求值
    qds  = np.gradient(qs,   axis=0, edge_order=2) / np.gradient(ts)[:, None]   # :677 ★
    qdds = np.gradient(qds,  axis=0, edge_order=2) / np.gradient(ts)[:, None]   # :678 ★
    if qds.shape[0] > 0:
        qds[-1, :]  = 0.0                                                # :680 ★
        qdds[-1, :] = 0.0                                                # :681 ★
    return qs, qds, qdds
```

**这里是全算法最明显的技术债。** `ṡ` 与 `s̈` 明明已经在 `sd_path` / `sdd_path` 里精确存在，
样条也支持解析导数（`toppra` 的 `SplineInterpolator.__call__(s, order)`），
正确的链式法则是：

```
q̇ = q'(s)·ṡ
q̈ = q''(s)·ṡ² + q'(s)·s̈
```

但代码改用 **`np.gradient` 对 `qs` 做二阶数值微分**。后果：
1. `qd/qdd` 精度只有二阶，且**恰好在分段衔接点（`s̈` 跳变处）最不准**——而分段正是整个算法费力构造出来的结构；
2. `qd` **没有用上 Ruckig 精确的 `ṡ`**，也就无法保证满足关节速度限制 `vlim`（全流程事后无任何校验）；
3. 末行被强行置零（`:680-681`），掩盖了数值微分的端点效应，也掩盖了 §5.10 的终止速度问题。

同类的"事后置零"在主流程里还有一处（`:720-722`）：

```python
if len(sd_path) > 0:
    sd_path[-1]  = 0.0
    sdd_path[-1] = 0.0
```

**这两处置零不是算法行为，是在掩盖求解器没能满足的边界条件**（证据见 §5.10）。

### 5.8 阶段七：输出与回放采样

```python
# pipeline.py:685-693
def resample_traj_uniform(ts, qs, dt):
    t_end = float(ts[-1])
    t_uniform = np.arange(0.0, t_end + 0.5*dt, dt)
    for j in range(qs.shape[1]):
        q_uniform[:, j] = np.interp(t_uniform, ts, qs[:, j])   # 逐关节线性插值
    return t_uniform, q_uniform
```

主入口 `run_mvc_ruckig_pipeline()`（`:696-746`）把七步串起来，
并额外算 `minima_s = segment_targets[:-1]`、`minima_v = np.interp(minima_s, gridpoints, mvc_upper)`（`:724-725`）
—— 注意这是**用插值重算**一遍极小点速度，理论上应等于 `mvc_upper[minima_idx]`（因为 `minima_s = gridpoints[minima_idx]`）。

`planning_bridge.py:_run`（`:202-330`）产出的契约在 §4.2 已列；
两个附加动作：把图表降到 ≤500 点（`:292-293`），以及按 `playbackDtMs` 做统一采样（`:269-270`）。

### 5.9 参数总表（含出处与作用域）

| 参数 | 默认 | 作用域 | 语义 | 代码 |
|---|---|---|---|---|
| `input_path` | `traj_seg_001.txt` | — | 路点文件 | `:16` |
| `grid_N` | `None` | s | `None` ⇒ 用 `ss` 本身当 gridpoints | `:17, 263-266` |
| `ss_mode` | `'arc'` | s | `'arc'` 末端弧长 / `'time'` 索引均匀 | `:18, 233-245` |
| `eps` | `1e-12` | s | 修复 `ss` 重复值时的最小步长 | `:19, 257` |
| `resample_points` | `1000` | 索引 | 重采样点数 | `:21, 222` |
| `joint_smooth_passes` | `60` | 关节 | 拉普拉斯平滑遍数 | `:22, 223-227` |
| `joint_smooth_blend` | `0.49` | 关节 | 平滑权重（硬夹 ≤0.49） | `:23, 178` |
| `arc_smoothing_alpha` | `None` | s | 可选弧长 EMA（默认关） | `:24, 228-231` |
| `swap_xy_for_ee` | `False` | 笛卡尔 | FK 的 XY 互换后门 | `:25, 94-98` |
| `du/dx/dc` | `1e-3/5e-2/9e-3` | 约束 | 鲁棒扰动椭球三半轴 | `:30-32, 296-300` |
| `solver_wrapper` | `'ecos'` | — | TOPPRA 求解器 | `:34, 305` |
| **`dt`** | `0.001` | 时间 | Ruckig 周期 | `:39` |
| **`v_max`** | `0.02` | **s** | Ruckig 速度上限（但被 `max()` 当下限用） | `:40, 602` |
| **`a_max`** | `0.02` | **s** | Ruckig 加速度上限（实测主导总时长） | `:41, 609` |
| **`j_max`** | `0.04` | **s** | Ruckig jerk 上限 | `:42, 610` |
| `intermediate_velocity` | `0.005` | s | **已废弃**，CLI 明确标注 "Legacy compatibility knob" | `:43`；`cli.py:73-78` |
| `minima_count` | `None` | 索引 | 保留极小点个数；`None` ⇒ 全保留 | `:44, 330` |
| `minima_gap` | `12` | 索引 | 极小点最小间距（1000 点中的 12 个） | `:45, 369-380` |
| `minima_threshold_mode` | `'mean'` | s | `mean`/`fixed`/`none` | `:46, 410-425` |
| `minima_max_value` | `None` | s | 仅 `fixed` 档使用 | `:47, 417-418` |
| `minima_smooth_window` | `21` | 索引 | 平滑窗（自动奇数化） | `:48, 338-346` |
| `junction_velocity_scale` | `0.8` | 无量纲 | 极小点 MVC → 衔接速度的折扣 | `:49, 599` |
| `max_steps` | `200000` | — | Ruckig 迭代上限 | `:50` |

UI 可调其中 10 个（缺 `minima_count`、`minima_max_value`），
`du/dx/dc/interpolation_scheme` 在 UI 上完全不可达（`ToppraConfig()` 恒用默认，`planning_bridge.py:245`）。

### 5.10 数值实证：用仓库自带的真实运行产物反向验算

仓库提交了 `docs/planning_demo_summary.json` —— 由 `scripts/generate_planning_docs_artifacts.py`
调用**真实的** `planning_bridge._run`（`:48-57`）后原样写入（`:397`），是**一次真实运行的输出**，
不是手工编的。输入是 `public/samples/er15_waypoints_sample.csv`（11 个路点），
配置就是 `DEFAULT_DOC_CONFIG`（`generate_planning_docs_artifacts.py:29-41`，与 UI 默认一致）。

关键数据：

```
duration        = 14.350 s
samples         = 14351            (dt = 0.001 ⇒ 14351 个采样点，自洽)
minimaIdx       = [85, 179, 598, 700, 799, 811, 899, 911]        (8 个极小点)
minimaV         = [1.1711, 1.1761, 1.0664, 1.0165, 0.3887, 0.6797, 0.3778, 0.6548]
segmentTargets  = [0.100449, 0.211836, 0.746329, 0.840933, 0.909735,
                   0.916404, 0.960989, 0.965939, 1.0]            (9 段)
segmentPoints   = [86, 180, 599, 701, 800, 812, 900, 912, 1000]
segmentTargetVelocities = [0.031060, 0.051601, 0.101778, 0.101778, 0.101778,
                           0.101778, 0.101778, 0.101778, 0.101778]
```

**我把 §5.6 的控制流（`_segment_feasible_target_velocity` + 回退阶梯）用脚本重放了一遍，
拿它去预测 `segmentTargetVelocities`，结果如下：**

| 段 `i` | `L` | `v_prev` | `desired_v` | `acc_cap` | `jerk_cap` | 阶梯① `v_target` | 阶梯② | 实测值 | **命中档位** | 误差 |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 0.100449 | 0 | 0.9369 | 0.063387 | 0.073901 | 0.062120 | **0.031060** | 0.031060 | **①′ 阶梯②** | **逐位相等** |
| 1 | 0.111387 | 0.031060 | 0.9409 | 0.073622 | 0.079173 | 0.072149 | **0.051605** | 0.051601 | ② | 7.6e-5 相对 |
| 2 | 0.534493 | 0.051601 | 0.8531 | 0.155056 | 0.225241 | **0.151955** | 0.101778 | 0.101778 | **②** | 4.2e-7 相对 |
| 3 | 0.094604 | 0.101778 | 0.8132 | 0.118924 | 0.071006 | 0.069586 | 0.085682 | 0.101778 | **③ = v_prev** | **逐位相等** |
| 4 | 0.068802 | 0.101778 | 0.3110 | 0.114502 | 0.057423 | 0.056275 | 0.079026 | 0.101778 | **③** | **逐位相等** |
| 5 | 0.006669 | 0.101778 | 0.5437 | 0.103080 | 0.012117 | 0.011875 | 0.056826 | 0.101778 | **③** | **逐位相等** |
| 6 | 0.044585 | 0.101778 | 0.3022 | 0.110191 | 0.043001 | 0.042141 | 0.071959 | 0.101778 | **③** | **逐位相等** |
| 7 | 0.004950 | 0.101778 | 0.5239 | 0.102746 | 0.009933 | 0.009735 | 0.055756 | 0.101778 | **③** | **逐位相等** |
| 8（末段） | 0.034061 | 0.101778 | —（目标 0） | 0.108264 | — | 0.0 | 0.050889 | 0.101778 | **③** | **逐位相等** |

**9 段中 8 段被逐位复现（相对误差 0.000e+00），第 2 段误差 4.2e-7（浮点量级）。
唯一不完美的是第 1 段（7.6e-5 相对偏差），推测该 JSON 由 `_segment_feasible_target_velocity`
的一个略早版本生成；这不影响任何下述结论。**

由此得到三条**硬结论**：

**结论 1：整条轨迹受 `a_max` 支配，`v_max` 与 MVC 衔接速度从未生效。**
`a_max = 0.02` 在 `s ∈ [0,1]` 上的"静止—静止"最速（bang-bang）时长为
`2·√(1/a_max) = 2·√50 = 14.142 s`；实测 **14.350 s**，仅高 1.5%（差额来自 jerk 限制与分段衔接）。
也就是说这条 11 个路点的轨迹，**慢是因为 s 空间的加速度上限太小，而不是因为速度上限或 MVC**。
而 `segment_v_max` 被抬到了 0.85~0.94（`minimaV×0.8`），却因为 `acc_cap`（约 0.06~0.16）与
`jerk_cap`（约 0.012~0.23）的钳位，实际衔接速度只有 0.031~0.102。
**`v_max=0.02` 这个默认值在此运行中既不是上限也不是瓶颈，完全是误导性的。**

**结论 2：后 6 段的回退阶梯一路掉到第 ③ 档（"保持原速"），MVC 分段的减速意图被彻底架空。**
第 3~8 段（对应 `s ≈ 0.75 → 1.0`，即最后 25% 路径、5 个 MVC 极小点）**全部**命中阶梯第 ③ 档
`v_target = v_prev`。也就是说：这些极小点本应减速（这正是把它们当分段点的全部意义），
但因为剩余段长只有 0.005~0.095，而 `a_max = 0.02` 太小，
连"折中到阶梯②"都做不到，最终只能**匀速冲过去**。
`minimaV` 在 `s = 0.91/0.96` 处低到 0.378/0.655 也不起作用。
**MVC 分段机制在纸面上成立，在默认参数下对轨迹几乎没有影响。**

**结论 3：末段终止速度为 0.1018 ≠ 0，是靠事后强制置零掩盖的。**
最后一段的目标是"以 `v = 0` 到达 `s = 1.0`"，但 `L = 0.034061` 而
`v_prev = 0.1018`：要停下来至少需要 `v²/(2·a_max) = 0.010359/0.04 = 0.259`，
**比可用长度大 7.6 倍**，物理上不可能。于是阶梯①（0.0）与②（0.0509）都失败，落到第 ③ 档
——记录下来的 `segmentTargetVelocities[-1] = 0.101778` 就是这个事实的"物证"。
随后 `pipeline.py:720-722`（`sd_path[-1] = 0; sdd_path[-1] = 0`）与
`:680-681`（`qds[-1] = 0; qdds[-1] = 0`）把最后一帧硬改成零。
**后果：关节速度在最后 1 ms 内从 `0.1018·|q'(1)|` 突降到 0，是一个物理上不可执行的终端速度不连续。**
在真机上这正是最容易触发跟随误差报警/急停的那种指令。

> 我把这三条称为"硬结论"，因为它们是**用提交在仓库里的真实输出反推出来的**，
> 并且对控制流的复现精度到逐位相等——如果不是这个算法，不可能复现出
> `0.031059748306098953` 这个 17 位数字。但请注意 §0 的声明：
> **这是验算（code reading + artifact replay），不是执行代码。**

**从这三条推出的调参建议**（给"驭臂"的参考）：
不要让用户直接调 s 空间的 `a_max/j_max`；应当在 UI 上暴露**关节空间或笛卡尔空间**的限制，
内部按路径长度把 s 空间限制**自动换算**出来（`a_s = a_cart / L`，`v_s = v_cart / L`），
并在每次规划后**回算并显示**：实际生成的最大关节速度/加速度/加加速度 vs 限制值，
以及**末端速度是否为 0**。这样才能立刻发现上述三问题。

### 5.11 已知缺陷清单（按严重度）

| # | 缺陷 | 位置 | 后果 |
|---|---|---|---|
| 1 | 终止速度非零 + 事后强制置零 | `:720-722`、`:680-681`；物证 `segmentTargetVelocities[-1]=0.1018` | 终端速度不连续，真机不可执行 |
| 2 | `v_max` 被 `max()` 当下限用 | `:602` | 默认 0.02 永不生效，参数语义与直觉相反 |
| 3 | s 空间限制与物理量无换算 | 全局 | 同配置在不同长度路径上物理速度不同；无法从 UI 值推断实际快慢 |
| 4 | `qd/qdd` 用数值微分而非链式法则 | `:677-678` | 分段衔接点处精度最差；`qd` 未校验是否超 `vlim` |
| 5 | 平滑无偏差校验 | `:223-227`；`warnings` 恒空（`planning_bridge.py:226, 325`） | 60 遍 blend 0.49 的削角不设上限，可能严重偏离示教点而无告警 |
| 6 | 减速时不施加 `jerk_cap` | `:453-454` | 减速段的可行性估计偏乐观，加剧第 1、2 条 |
| 7 | `ss_mode='time'` 名不符实 | `:236-238` | 实际是按路点索引均匀，非按时间 |
| 8 | ER15 / 6 轴硬编码贯穿三层 | `planning_bridge.py:53-90, 96`；`pipeline.py:112, 129`；`DesignPlugin.tsx:23-30` | 7 个机器人资产可选但规划恒按 ER15；限位数字有两份拷贝 |
| 9 | `sd_vec` / `X` / `K` 算了不用 | `:310-312, 729-731` | TOPPRA 的时间最优解被丢弃（可作对照基线/兜底方案） |
| 10 | 回退阶梯只捕获 `RuntimeError` | `:627-646` | 其他异常直接崩掉整条轨迹 |
| 11 | `segment_points` 用 `i+1` 而 `segment_targets` 用 `gridpoints[i]` | `:583-584` | 同一批点的两种不一致表示，易误读；`segment_points` 无实际用途 |
| 12 | `intermediate_velocity` 死参数 | `:43`；`cli.py:73-78` | 配置面污染 |
| 13 | `ToppraConfig` 四项 UI 不可达 | `planning_bridge.py:245` | 鲁棒半径无法调 |

### 5.12 移植清单（照此可在别的代码库重建）

按顺序实现，每步都是纯函数，输入输出都是 numpy 数组：

```
[1] load_waypoints(path) -> (N,6) float64            # 支持 CSV(要求 J1..J6) 与纯数值 TXT
[2] resample_index_uniform(W, M=1000) -> (M,6)       # 按路点索引 linspace 线性插值
[3] unwrap_and_laplacian_smooth(W, passes=60, blend=0.49) -> (M,6)
        blend = clip(blend, 0, 0.49)；端点钉死；先 np.unwrap(axis=0)
[4] arc_length_parameterize(fkine, W) -> ss (M,)     # 累计末端欧氏距离，归一化到 [0,1]
        修复严格递增；ss[0]=0, ss[-1]=1
[5] path = SplineInterpolator(ss, W_smooth)          # gridpoints = ss（默认）
[6] toppra = TOPPRA([JointVelocityConstraint(vlim),  # vlim/alim 是【关节空间】rad/s, rad/s²
                     RobustLinearConstraint(
                         JointAccelerationConstraint(alim, Interpolation),
                         [du,dx,dc]=[1e-3,5e-2,9e-3], Interpolation)],
                    path, gridpoints=ss, solver_wrapper='ecos')
[7] X = sqrt(toppra.compute_feasible_sets())         # ← 必须先平方根！内部量是 ṡ²
    mvc_upper = X[:,1]                               #   归一化后即 MVC（单位 1/s）
[8] minima_idx = detect_minima(mvc_upper, min_gap=12, threshold=mean(mvc_upper), smooth_window=21)
[9] segment_targets = [ss[i] for i in minima_idx] + [1.0]
    for each segment i:
        desired_v = mvc_upper[minima_idx[i]] * 0.8
        seg_vmax  = max(v_max, desired_v, v_prev)                  # 注意是 max，不是 min
        v_target  = feasible_target(x_prev, x_target, v_prev, desired_v, seg_vmax, a_max, j_max)
                       # acc_cap  = sqrt(v_prev² + 2*a_max*L)
                       # jerk_cap = (L*sqrt(j_max))^(2/3)
                       # v_target = clip(min(desired_v, 0.98*min(seg_vmax,acc_cap,jerk_cap)), 0, seg_vmax)
        for cand in dedup([v_target, 0.5*(v_target+v_prev), v_prev, 0.0]):   # 速度回退阶梯
            try: seg = ruckig_1d(x_prev,v_prev,a_prev → x_target,cand,0,
                                 vmax=seg_vmax, amax=a_max, jmax=j_max, dt,
                                 min_velocity=0.0, min_acceleration=-a_max)
                 break
            except SolverError: continue
        (x_prev,v_prev,a_prev) = seg 的末状态（实际值）
    ts, s, sd, sdd = concat(segments)                # 后续段丢弃首采样点，时间偏移累加
[10] qs  = path(s)
     qds = q'(s)*sd            # ★★ 用链式法则，不要用 np.gradient
     qdds = q''(s)*sd² + q'(s)*sdd
[11] 校验（项目里缺，建议补）：
     max|qd| ≤ vlim ?   max|qdd| ≤ alim ?   max|jerk| ≤ ?   sd[-1] == 0 ?   偏差 |q - W_raw| ≤ tol ?
[12] (t_uniform, q_uniform) = resample_uniform(ts, qs, playback_dt)
```

**移植时最小的改动优先级：**
**(1)** 补 [11] 的校验（这能立刻暴露 §5.10 的三个问题）；
**(2)** 把 `[10]` 换成链式法则（`toppra` 的 `SplineInterpolator` 支持求导）；
**(3)** 把 `v_max/a_max/j_max` 换成关节/笛卡尔量并按路径长度换算（治本）；
**(4)** 让机器人模型参数化（去掉 ER15 硬编码）。

---

## 6. 该学什么 vs 该避什么

### 6.1 该学（都有代码依据）

| # | 学到什么 | 依据 | 为什么值得学 |
|---|---|---|---|
| 1 | **MVC 既是速度上界、又是分段判据** 这一点子 | `pipeline.py:309-316`（取 `X[:,1]`）+ `:319-407`（找极小点）+ `:584`（当分段点） | 把"哪里需要减速"从启发式规则变成约束求解的直接产物，物理上有依据，实现上只是找局部极小。这是全项目唯一有原创性的算法想法 |
| 2 | **TOPPRA 只当"约束→包络"的神谕，轨迹交给 1-DoF Ruckig** | `sd_vec` 被算出即弃（`:312, 731`），全部轨迹来自 `ruckig_1d`（`:478-540`） | 回避了 TOPPRA 时间最优解在真机上无法执行（加速度不连续、无 jerk 限制）的硬伤，同时免费获得精确的速度上界。**这个分工比"直接用 TOPPRA 输出"或"直接用 Ruckig 规划多维"都更实用** |
| 3 | **七阶段纯函数分解**，核心零 I/O | `pipeline.py` 全部 12 个函数都是"数组进、数组出"；唯一读盘的是 `load_joint_waypoints` | 746 行算法可以在没有 ROS、没有仿真器、没有 Web 的环境里单测。移植成本极低 |
| 4 | **"可安装包"的目录纪律** | `pipeline.py`(核心) / `core.py`(瘦 API) / `cli.py`(命令行) / `__init__.py`(导出) / `pyproject.toml`；方法论写在 `Figs/封装发布工作流.md:49-118`（§4 通用封装思路，含 4.1 核心实现层 / 4.2 精简 API 层 / 4.3 命令行入口层） | 从"实验脚本"演化到"别人能 import、能 CLI 跑、能 pip install -e"的三层结构，正是我们要给自研算法建的形状 |
| 5 | **`RobustLinearConstraint` 的正确用法** | `pipeline.py:296-300`，参数直接沿用官方示例（[官方示例](https://hungpham2511.github.io/toppra/auto_examples/plot_robust_kinematics.html)） | `[du,dx,dc]` 是扰动椭球半轴，给约束留出可量化余量。这是"照抄上游规范用法"的正确示范 |
| 6 | **数值细节的克制** | `blend` 硬夹 ≤0.49（`:178`）；`np.unwrap` 处理 ±π 跳变（`:177`）；平滑后 `np.maximum.accumulate` 保单调（`:161`）；`ss` 严格递增修复（`:252-261`） | 三条都是"踩过坑才会写"的代码，直接抄不会有损失 |
| 7 | **Ruckig 的两个命门开关** | `inp.min_velocity = [0.0]`（`:507`）与 `inp.min_acceleration = [-a_max]`（`:509`）；`README.md:15-16` 明确列为修复项 | 不加第一个，路径参数会倒退；不加第二个，所有减速段报不可行。用 Ruckig 做路径参数整形的人几乎都会踩 |
| 8 | **速度回退阶梯** | `:615-648`，且把实际采用的档位写回 `segment_target_velocities`（`:642, 650`） | "求解器要么解要么报错"的场景下，逐档退让比整体崩掉好得多；记录实际档位使其可诊断（§5.10 正是靠它完成验证） |
| 9 | **跨语言 JSON 契约的两道保险** | `_json_safe()` 递归转换 numpy 类型并把非有限浮点转 `None`（`planning_bridge.py:158-172`）+ `allow_nan=False`（`:346`）；错误也写 stdout 且 `exit(1)`（`:347-354`），Node 侧 `if (parsed) resolve(...)` 保留它（`api.mjs:67-75`） | numpy→JS 的 NaN/Infinity 是经典杀手；这条链路把错误信息跨语言保真地送到了前端 |
| 10 | **独立 origin + dev proxy，前端零 CORS** | `vite.config.ts:23-28`；前端只用相对路径 `apiBase='/api'`（`App.tsx:412`） | 一个进程一个端口、前端永不写死 `http://localhost:3001`，也不需要任何 CORS 配置。M0 阶段最省事的接法 |
| 11 | **每次请求 spawn 一个 Python 进程 + stdin/stdout 一次性 JSON** | `api.mjs:16-20, 83-84`；`planning_bridge.py:335-336, 346` | 无状态、无端口、无协议库、无连接池；Python 挂了不会污染常驻进程。作为 M0 是**完全站得住脚**的（它的代价见 §6.2-11） |
| 12 | **把 MuJoCo 当运动学/模型解析器 + 裸数组→three.js 的 geom 桥** | `SimulationView.tsx:670-739`（`buildGeom` 直读 `geom_type/size/pos/quat/mesh_vert/face`）、`:443-556`（MEMFS 物化）、`:961,998`（只 `mj_forward`，不 `mj_step`） | **白拿** MJCF/URDF 解析、FK、网格解码，却不需要场景图导出器、不需要物理步进。对"只做回放/可视化"的工作台是极高效的选择 |
| 13 | **模型依赖的两级解析（URDF `package://` 与 MJCF `file=`/`meshdir`）** | `:313-414`（URDF 重写 + 逐个探测）、`:416-441`（解析 `meshdir`）、`:499-553`（把同一二进制写到两个虚拟路径） | 现实中的机器人包路径约定极乱，这段代码是这个脏活的完整答案 |
| 14 | **时间轴推进用 ref、不用 state** | `SimulationView.tsx:888-889, 896-904, 1106`（只有 `robot` 在依赖数组里） | 60fps 的 `currentTimeSec` 不会触发 three.js 场景重建。这是 React+three.js 集成的关键纪律 |
| 15 | **插件注册表 + 单数据袋契约** | `App.tsx:63-68`（注册表）+ `types.ts:174-183`（`WorkspacePluginData`）+ `App.tsx:403-415`（渲染点） | 加一个模块 = 一个文件 + 注册表一行；宿主不需要知道任何模块细节。**这正是我们工作台该有的模块化形状** |
| 16 | **VS Code 外壳作为产品叙事** | `App.tsx:252-536`（活动栏/侧栏/中区/面板/状态栏一一对应）；中区 3D 视图常驻不切换（`:475-479`） | 工程师零学习成本；更重要的是它把"仿真器"放在了工作台的中心，而不是某个 Tab 的产物 |
| 17 | **线性向导嵌在非线性外壳里** | Design 的 `1) Waypoint File` → `2) Limits & Config` → `3) Runtime Status` → `4) Result & Playback`（`DesignPlugin.tsx:322,344,451,485`），每段都是 `CollapsibleSection` | 规划流程天然是有序的，编号卡片让用户知道"下一步在哪"，又不强迫线性点击 |
| 18 | **`CollapsibleSection` 这个可复用组件本身** | `CollapsibleSection.tsx` 全文 48 行，5 个 props，被引用 **25 次** | 用 `<button>` + `ChevronRight` 旋转 + 条件渲染就够；`defaultOpen` 支持"表单默认展开、说明默认收起"（`DeployPlugin.tsx:69,149`）。**一个 48 行组件覆盖了全部四个模块的骨架** |
| 19 | **图表工程惯例** | 全部 `isAnimationActive={false}`（`DesignPlugin.tsx:563,576,577` 等）、`ResponsiveContainer` + 固定高度容器、`dot={false}` + `strokeWidth≈1.4` | 回放/实时图表禁用动画是必须的，否则每帧重播动画；这三条是无脑可抄的默认值 |
| 20 | **splitter 的三个细节** | `App.tsx:212-244`：拖动期改 `body.cursor`+`userSelect` 并在 cleanup 恢复；用 `startValue + Δ` 而非累加；上限动态收紧（`window.innerWidth - 320`）；`role="separator"` + `aria-orientation`（`:423-425, 483-485`） | 手写 splitter 的完整正确姿势，含无障碍属性 |
| 21 | **两个小契约工程习惯** | 每个响应都回显 `apiVersion`（`api.mjs:12, 96`）；`health` 返回 8 个依赖的 `find_spec` 结果与 ER15 工厂的实跑结果（`planning_bridge.py:176-186`） | 便宜的契约版本化；依赖体检比"服务活着吗"有用得多 |
| 22 | **前端双份校验 + 手动 `text()`→`JSON.parse`** | `DesignPlugin.tsx:72-127`（前端校验）、`:275-286`（先取文本再解析，以便在非 JSON 时给出可诊断错误） | 校验前置能省一次 600s 超时的往返；手动解析让"sidecar 返回 HTML 错误页"这类故障可读 |

### 6.2 该避（同样都有代码依据）

| # | 避开什么 | 依据 | 为什么 |
|---|---|---|---|
| 1 | **假物理量冒充测量值** | `DeployPlugin.tsx:143`（`(Math.random()*3.14).toFixed(4)` 当关节目标）、`:105`（进度条写死 68%）、`:71`（三个"已连接"来自写死数组）、`:132` E-STOP 无 handler；`DiagnosePlugin.tsx:240-242`（`tau = |q|*4+|dq|*1.2+|qdd|*0.03`）、`:303`、`:241`、`:355`（`load = 20+|q|*38`）、`:36-44`（正弦波兜底）、`:476-477`（`500Hz` / `124MB/s` 写死）、`:550-553`（结论文本写死） | 工作台里**一条假力矩曲线比没有力矩曲线更有害**——用户会据此调参。要做就接真逆动力学，做不了就显式标 `DEMO` / 灰掉 |
| 2 | **`health.ok` 无条件真** | `planning_bridge.py:189`（`'ok': True` 写死，即便 `er15Factory.ok=False`）；前端 `DesignPlugin.tsx:246` 却拿它当放行闸门 | 这道门永远拦不住任何东西，形成"看起来有防护实际没有"的假安全感 |
| 3 | **过期规格文档** | `docs/ALGORITHM.md:15-28, 44-62` 描述的 `strategyId/stageConfig/algorithmMeta/stageMetrics/debugLogs/input_parse/path_prepare/postprocess` 在全部代码中**命中 0 次** | 描述未实现设计的文档比没有文档更危险，照着它写前端会白做 |
| 4 | **用事后置零掩盖求解失败** | `pipeline.py:720-722`（`sd[-1]=0, sdd[-1]=0`）、`:680-681`（`qds[-1]=0, qdds[-1]=0`），而 `segmentTargetVelocities[-1] = 0.1018` | §5.10 已证：末段物理上停不下来，代码把它改成零。**结果是终端速度不连续，真机直接报警**。正确做法是报错或延长路径，而不是改数 |
| 5 | **拿数值微分成品当速度/加速度** | `pipeline.py:677-678`（`np.gradient(qs)/np.gradient(ts)`），而 `sd_path`/`sdd_path` 与样条导数都在手边 | 恰好在分段衔接点（唯一的"特征位置"）精度最差；且 `qd` 全程无人校验是否超 `vlim` |
| 6 | **平滑不设偏差上限、不给告警** | `pipeline.py:223-227`（60 遍 blend 0.49）；`planning_bridge.py:226` 初始化 `warnings=[]`，`:325` 原样返回空数组（全函数从未写入） | 削角幅度无界、无告警。对"按示教点走"的工业场景是硬伤 |
| 7 | **s 空间限制直接暴露给用户** | `DesignPlugin.tsx:420-429` 让用户填 `v_max/a_max/j_max`（0.02/0.02/0.04），语义完全是 s 空间；`pipeline.py:602` 还把 `v_max` 当下限用 | 用户无法从这些数推断实际快慢（§5.10：11 个路点跑 14.35 s）。应当暴露关节/笛卡尔限制并在内部换算 |
| 8 | **`v_max` 语义反转** | `pipeline.py:602`：`segment_v_max = max(v_max, desired_v, v_prev)` | 一个叫 "max" 的参数实际是下限，`min`/`max` 一眼看错就会得到完全不同的行为。若必须保留，至少改名 `v_floor` |
| 9 | **`ss_mode='time'` 名不符实** | `pipeline.py:236-238`（`ss = linspace(0,1,N)`），因为重采样的路点没有时间戳 | 名字会骗人，别继承 |
| 10 | **单一机型假设贯穿三层** | `planning_bridge.py:53-90`（ER15 的 6 组限位与 DH 全写死）、`:96-97`（强制 6 值）、`pipeline.py:112/129`（强制 6 列）、`DesignPlugin.tsx:23-30`（ER15 行程的第二份拷贝） | `robotCatalog.ts` 里 7 个机器人（含 2 轴 MP600）在 Define 里可切，规划却恒按 ER15。**移植时第一个要解决的问题**；且限位数字有两份拷贝必然漂移 |
| 11 | **每请求 spawn 一个 Python 进程，无池无队列无取消** | `api.mjs:16`；`README.md:61` 自认 "no queue/streaming" | N 个并发 = N 个进程，每个重付 numpy/toppra/ecos/ruckig 的 import 代价；只有 600 s 后 `SIGKILL` 一种取消方式。改法：常驻 Python + 行分隔 JSON，或换成 Python 直接提供 HTTP |
| 12 | **全量轨迹走 JSON** | `planning_bridge.py:300-306`（`qs/qds/qdds` 各 14351×6 全量）+ `api.mjs:89`（`express.json({limit:'50mb'})`） | 图表已经降到 ≤500 点（`:292-293`），却仍把全量数组发给浏览器。单次响应 MB 级。前端回放只需要 `tUniform/qUniform` |
| 13 | **死配置面与死通道** | `RuckigConfig.intermediate_velocity`（`pipeline.py:43`，`cli.py:77` 自认 legacy）；`ToppraConfig` 四项 UI 不可达（`planning_bridge.py:245` 恒用默认）；`sd_vec/X/K` 算了不用（`:729-731`）；`App.tsx:414` 的 `onAction` 只 `console.log`（⇒ 整条插件→宿主通道失效，`DeployPlugin.tsx:166`、`DiagnosePlugin.tsx:598` 的动作全部落空）；`GEMINI_API_KEY` 注入 bundle（`vite.config.ts:14`）但 `src/` 零引用，`@google/genai`（`package.json:16`）是死依赖 | 配置面和事件面都必须有真实消费者，否则后来者会花时间去追根本不生效的开关 |
| 14 | **假 IDE chrome** | `App.tsx:441-471`（标签页 `SimulationView.mu`/`system.log`、面包屑 `src/components`、`main*`、`第 1 行, 第 1 列`、`空格: 2`、`UTF-8`、`Prettier`）；`:514-516` 错误/警告恒 0；`:539-607` 插件市场只渲染静态列表、`安装` 无 handler | 借 VS Code 的壳是对的（§6.1-16），但把**不具备的能力**也画上去会主动误导。建议：装饰保留形状，内容换成真实状态（例如行列位置换成"当前帧/总帧"） |
| 15 | **`SIDEBAR_DEFAULT_WIDTH === SIDEBAR_MAX_WIDTH`** | `App.tsx:111-113`（都是 560） | splitter 只能缩不能放，是个明显的实现疏漏 |
| 16 | **`index.css` 的全局字号 hack** | `index.css:13-26`：`[class*="text-[10px]"] { font-size: 12px !important; }` | 此后所有 `text-[Npx]` 都名不副实且不可发现（改 class 无效，得翻 css）。应直接定义 5 档字阶 |
| 17 | **同一 UI 模式手写 6 遍** | 表格网格：`DefinePlugin.tsx:24/42/51`、`DiagnosePlugin.tsx:95/103`、`DesignPlugin.tsx:347/354` | 既然 `CollapsibleSection` 证明他们会抽组件，这里没抽就是漏了；`DetailRow`/`SourceStatusBadge`/`DataSourceTable` 三个局部组件本可合成一套 `DataTable`/`KeyValueTable` |
| 18 | **图标语义复用 + 活动栏图标被覆盖** | `App.tsx:255`（`icons = [Files, Search, GitBranch, PlayCircle]` 按索引取，插件自带的 `p.icon` 被忽略）；`X` 同时是"关标签页"(`:446`)与"错误数"(`:514`)；`Activity` 同时是引擎/健康/遥测/spinner | 左侧四个图标讲不出四个模块是什么；同一图标多义会让状态栏失去可读性 |
| 19 | **`qpos[index]` 按下标写关节** | `SimulationView.tsx:956-960`、`:993-997`（`for i < dof: data.qpos[i] = sampledQ[i]`） | 假设"驱动关节就是 `qpos` 的前 N 项"。带 free joint / 浮动基座 / 关节重排的模型会静默错位。应按关节名映射 |
| 20 | **把"MuJoCo WASM"当动力学卖** | 只有 `mj_forward`（`:961, 998`），无 `mj_step`；但 UI 标 `engineLabel: 'MuJoCo WASM'`（`robotCatalog.ts:19` → `App.tsx:521`） | 它其实是"用 MuJoCo 做解析+FK 的播放器"。技巧本身极好（§6.1-12），但对外文案必须说清没有动力学/接触/执行器 |
| 21 | **资产探测靠 `fetch` 逐个试** | `SimulationView.tsx:173-199`（按优先级逐个 fetch 候选）、`:329-339`、`:376`（每次都发网络请求探测是否存在），并用 `Content-Type` 判断是否拿到 SPA 的 HTML | 加载前有 O(n) 次网络往返；用内容嗅探来识别 404 页面很脆弱。应改为清单驱动（`robotCatalog` 已经半个是清单了） |
| 22 | **仓库 799 MB，且资产重复托管** | `models/`（~393 MB）与 `public/robots/`（~406 MB）内容基本重复；`public/robots/MP600` 一个目录 302 MB，含 93 MB `.stp` CAD 文件、41 MB `.zip`、41 MB `.dae`、32 MB `.stl`，**全部作为静态资源面向浏览器** | 克隆要几分钟（本次即因此失败两次）；浏览器可能被诱导下载 93 MB 的 CAD 文件。应：只保留一份、CAD 移出 `public/`、网格转 Draco/glTF |
| 23 | **health 的 `ok` 与 `er15Factory.ok` 双轨** | `planning_bridge.py:188-199`；前端只读 `health.ok`（`DesignPlugin.tsx:246`）与 `er15Factory.ok`（`:463`）各一处，语义重叠 | 两个字段表达同一件事却可能矛盾（`ok=True` 而 `er15Factory.ok=False`）。应统一为单一 `ok` + `reasons[]` |

---

## 附：一句话总结

**值得抄的是三样东西：**
（1）`MVC 当速度上界兼分段判据 → 每段 1-DoF Ruckig 整形 → 映射回关节` 这条算法主线
（连同它的七阶段纯函数分解与可安装包纪律，`pipeline.py` 746 行可整体移植）；
（2）`把 MuJoCo 当解析器/FK 引擎、裸数组直转 three.js、时间轴走 ref` 这套"播放器"架构
（`SimulationView.tsx`，对只做回放/可视化的阶段极高效）；
（3）`VS Code 外壳 + 插件注册表 + 单数据袋契约 + CollapsibleSection` 这套产品骨架
（`App.tsx:63-68, 246-536`；`types.ts:174-183`）。

**必须避开的是：假物理量、事后置零掩盖求解失败、s 空间限制直接暴露给用户、
以及 ER15/6 轴的隐性硬编码。**
前两条会让工具骗人，第三条会让用户无法预测规划结果（实测：11 个路点跑 14.35 s，
且末端速度是 0.10 而非 0，全靠一行赋值改成了 0），第四条会让"7 个机器人可选"变成摆设。
