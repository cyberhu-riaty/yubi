/**
 * 文案.ts —— 界面文字的中英两套 + 语言开关。
 *
 * 纪律（`约定.md` §三）：**组件里不硬编码中文**，任何画到屏幕上的字都走 `取(键)`。
 *
 * 与后端 `软件/文案.py` 的关系：**术语照抄，键名各自独立**。
 *   后端那份管 ImGui 面板（受"字体画不出汉字"限制，键名与字符串都是它自己的）；
 *   这份管浏览器（字体齐全，中文随便画）。两边共享的只有"叫法"：
 *   模型库、算法库、参数辨识、物理总闸… 这些词两边必须一样，否则同一个人看到两套名词。
 *
 * 模板写法：`{名}`。`取("键", { 名: 值 })` 做替换；缺参数时原样保留 `{名}`，
 * 一眼能看出是漏了参数，而不是悄悄画出一个空字符串。
 */
import { useSyncExternalStore } from "react";

export type 语言 = "zh" | "en";

export const 语言名: Record<语言, string> = { zh: "中文", en: "English" };
/** 状态栏那个切换按钮上显示的字（显示"另一种语言"） */
export const 另一种语言: Record<语言, 语言> = { zh: "en", en: "zh" };

const 存储键 = "驭臂.语言";

function 读存档(): 语言 {
  try {
    const 存 = window.localStorage.getItem(存储键);
    if (存 === "zh" || 存 === "en") return 存;
  } catch {
    /* 存储不可用就用系统语言 */
  }
  try {
    return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
  } catch {
    return "zh";
  }
}

let 当前语言: 语言 = 读存档();

const 订阅者 = new Set<() => void>();

export function 取语言(): 语言 {
  return 当前语言;
}

export function 设语言(语: 语言): void {
  if (语 === 当前语言) return;
  当前语言 = 语;
  try {
    window.localStorage.setItem(存储键, 语);
  } catch {
    /* 存不下也能用，只是下次回到系统语言 */
  }
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("lang", 语 === "zh" ? "zh-CN" : "en");
  }
  广播();
}

function 广播(): void {
  for (const f of 订阅者) f();
}

export function 用语言(): 语言 {
  return useSyncExternalStore(
    (回调) => {
      订阅者.add(回调);
      return () => 订阅者.delete(回调);
    },
    取语言,
    取语言,
  );
}

// ---------------------------------------------------------------------------
// 文案表：键 → [中文, English]
//   ★ 加文案就在这里加一行，不许在组件里写字符串。
// ---------------------------------------------------------------------------
const 表 = {
  // ---- 通用 ----
  "通用.待接入": ["待接入", "not wired yet"],
  "通用.未实现": ["未实现", "not implemented"],
  "通用.未接入": ["未接入", "not connected"],
  "通用.是": ["是", "yes"],
  "通用.否": ["否", "no"],
  "通用.个": [" 个", ""],
  "通用.秒": ["{值} 秒", "{值} s"],
  "通用.毫秒": ["{值} ms", "{值} ms"],
  "通用.无": ["（无）", "(none)"],
  "通用.无数据": ["暂无数据", "no data yet"],
  "通用.计数": ["{值} 帧", "{值} frames"],
  "通用.每格": ["每格", "each"],
  "通用.复制": ["复制", "Copy"],
  "通用.关闭": ["关闭", "Close"],
  "通用.等待": ["等待中", "waiting"],
  "通用.中": ["中", "mid"],
  "通用.最大": ["最大", "max"],
  "通用.最小": ["最小", "min"],
  "通用.单位": ["单位", "unit"],

  // ---- 应用 / 活动栏 ----
  "应用.名称": ["驭臂", "Yubi"],
  "应用.副标题": ["机器人仿真工作台", "Robot simulation workbench"],

  // ---- 活动栏 ----
  "活动栏.标题": ["活动栏", "Activity bar"],
  "活动栏.步骤编组": ["任务流", "Task flow"],
  "活动栏.底部编组": ["设置与信息", "Settings and info"],

  // ---- 任务流 ----
  "任务流.提示": ["任务流只换左侧上下文，中区 3D 视口常驻不切换。", "The task flow only swaps the left context; the centre 3D viewport stays put."],
  "步骤.定义": ["定义", "Define"],
  "步骤.定义.一句话": ["选机械臂、看当前项目", "Pick the arm, inspect the current project"],
  "步骤.规划": ["规划", "Plan"],
  "步骤.规划.一句话": ["轨迹规划（尚未实现）", "Trajectory planning (not implemented)"],
  "步骤.验证": ["验证", "Verify"],
  "步骤.验证.一句话": ["实时曲线与参数表", "Live curves and parameter table"],
  "步骤.辨识": ["辨识", "Identify"],
  "步骤.辨识.一句话": ["参数辨识进度与结果", "System identification progress and results"],
  "步骤.监控": ["监控", "Monitor"],
  "步骤.监控.一句话": [
    "实时率、步频、内存 —— 跑得动跑不动，看这里",
    "Real-time factor, step rate, memory — whether it keeps up",
  ],
  "监控.实时率": ["实时率 RTF", "Real-time factor"],
  "监控.步频": ["物理步频", "Physics step rate"],
  "监控.内存": ["进程内存", "Process memory"],
  "监控.仿真时间": ["仿真时间", "Sim time"],
  "监控.墙钟": ["已运行", "Elapsed"],
  "监控.步长": ["物理步长", "Timestep"],
  "监控.插件数": ["已装插件", "Plugins"],
  "监控.说明": [
    "RTF = 仿真时间推进 ÷ 真实耗时。1.00 表示实速；明显小于 1 说明算不过来（算法太重或模型太复杂）。这些数只能由仿真侧算，界面不自己估。",
    "RTF = sim time advanced ÷ wall clock. 1.00 means real time; well below 1 means it cannot keep up. These can only be measured on the sim side; the UI never estimates them.",
  ],
  "监控.没数据": [
    "还没收到系统指标（1 Hz 发一次，稍等）",
    "No system metrics yet (sent once a second)",
  ],
  "监控.渲染帧率": ["3D 渲染帧率", "3D render rate"],
  "监控.渲染帧率.说明": [
    "这一项来自窗口层（3D 视口自己的统计），不是仿真侧算的。",
    "This one comes from the window layer (the 3D viewport's own stats), not the sim side.",
  ],
  "步骤.部署": ["部署", "Deploy"],
  "步骤.部署.一句话": ["真机部署（未接入）", "Real-hardware deploy (not connected)"],
  "步骤.外观": ["外观", "Appearance"],
  "步骤.外观.一句话": ["皮肤与语言", "Skin and language"],
  "步骤.关于": ["关于", "About"],
  "步骤.关于.一句话": ["版本、运行环境、声明", "Version, runtime, notices"],

  // ---- 侧栏 ----
  "侧栏.当前步骤": ["当前步骤", "Current step"],
  "侧栏.上下文": ["上下文侧栏", "Context sidebar"],
  "侧栏.收起": ["收起侧栏", "Collapse sidebar"],
  "侧栏.展开": ["展开侧栏", "Expand sidebar"],
  "侧栏.收起说明": [
    "侧栏已收起 —— 点最左侧图标列的任一图标可以再叫出来。",
    "Sidebar collapsed — click any icon in the activity bar to bring it back.",
  ],

  // ---- 可折叠区块 ----
  "区块.展开": ["展开", "Expand"],
  "区块.收起": ["收起", "Collapse"],
  "区块.展开名": ["展开「{名}」", "Expand “{名}”"],
  "区块.收起名": ["收起「{名}」", "Collapse “{名}”"],

  // ---- 中区（3D 视口占位） ----
  "中区.标题": ["三维视口", "3D viewport"],
  "中区.未接入": ["原生 3D 就在窗口下方", "The native 3D view is the pane below"],
  "中区.未接入说明": [
    "三维视图是**真 MuJoCo 原生渲染**，由宿主窗口直接放在这一格的下方（同级视图，不是网页里画的）。所以这里不重复画几何 —— 重复画会和真画面打架，而且网页侧重算正运动学会与物理漂移。",
    "The 3D view is **real native MuJoCo rendering**, placed by the host window directly below this pane (a sibling view, not drawn in the page). So no geometry is drawn here — duplicating it would fight the real render, and recomputing kinematics in the page would drift from the physics.",
  ],
  "中区.操作提示": [
    "在下方的 3D 区里：拖拽=转视角 ／ 滚轮=缩放 ／ Shift+拖拽=平移 ／ R=复位",
    "In the 3D pane below: drag to orbit · scroll to zoom · Shift+drag to pan · R to reset",
  ],
  "中区.不重算": [
    "前端不会按 URDF 自己重算正运动学 —— 那会与物理漂移，加载带自由关节的模型立刻露馅。",
    "The frontend does not recompute forward kinematics from the URDF — that drifts from the physics and falls apart the moment a model has free joints.",
  ],
  "中区.浮层": ["模型与关节状态", "Model and joint state"],
  "中区.接口就绪": ["视口接口已就位：{值}", "Viewport hook ready: {值}"],
  "中区.视口接口未就绪": ["视口接口尚未出现", "No viewport hook in the contract yet"],

  // ---- 控制台 ----
  "控制台.标题": ["控制台", "Console"],
  "控制台.页签.输出": ["输出", "Output"],
  "控制台.页签.事件": ["事件", "Events"],
  "控制台.页签.问题": ["问题", "Problems"],
  "控制台.清空": ["清空", "Clear"],
  "控制台.清空不了": [
    "清空只影响显示；连接与命令的历史仍然留在后端。",
    "Clearing only affects this view; connection and command history stays in the backend.",
  ],
  "控制台.自动滚动": ["自动滚动", "Auto scroll"],
  "控制台.筛选.全部": ["全部来源", "All sources"],
  "控制台.筛选.说明": ["只留下选中的来源", "Show only the selected sources"],
  "控制台.空": ["这里还什么都没有 —— 没有事件就不编事件。", "Nothing here yet — no events, no invented lines."],
  "控制台.空提示": ["连上后端、或发一条命令之后就会有真实的行。", "Real lines appear once the backend connects or a command is sent."],
  "控制台.列.时刻": ["时刻", "Time"],
  "控制台.列.等级": ["等级", "Level"],
  "控制台.列.来源": ["来源", "Source"],
  "控制台.列.主题": ["主题", "Topic"],
  "控制台.列.文本": ["内容", "Message"],
  "控制台.速率.标题": ["主题速率（每秒，来自连接层实测）", "Topic rates (per second, measured at the transport)"],
  "控制台.速率.说明": [
    "只列**真的收到过**的主题；契约里登记但从未到达的主题不在这里，它们会出现在「问题」页签。",
    "Only topics that **actually arrived** are listed; contracted topics that never arrive show up under “Problems”.",
  ],
  "控制台.速率.空": ["还没有收到任何帧。", "No frames received yet."],
  "控制台.速率.归零": ["{值}（{时长} 秒前有帧）", "{值} (last frame {时长}s ago)"],
  "控制台.问题.等级": ["等级", "Level"],
  "控制台.问题.项": ["检查项", "Check"],
  "控制台.问题.证据": ["证据（真实的那些行）", "Evidence (the real lines)"],
  "控制台.问题.标题": ["自动校验（按真实连接状态推导）", "Automatic checks (derived from the real connection state)"],
  "控制台.问题.无": ["没有发现问题。", "No problems found."],
  "控制台.问题.无说明": [
    "这是真的「没有」：连接正常、契约主题都在收、没有失败的回执。它不代表软件没缺陷。",
    "This is a real “none”: the link is up, contracted topics are arriving, no receipt failed. It does not mean the software is bug-free.",
  ],

  // ---- 问题检查项 ----
  "问题.未连接": ["与后端未连接", "Not connected to the backend"],
  "问题.未连接.说明": [
    "当前状态：{状态}。没有连接就没有任何真实数据，所有视图都会是空的。",
    "Current state: {状态}. Without a link there is no real data; every view stays empty.",
  ],
  "问题.协议不符": ["协议版本不一致", "Protocol version mismatch"],
  "问题.契约缺主题": ["契约登记的主题从未到达", "Contracted topics that never arrived"],
  "问题.契约缺主题.说明": [
    "握手承诺了这些主题，但一帧都没收到：{主题}。可能是后端还没开始广播，也可能是链路被挡。",
    "The handshake promised these topics but not a single frame arrived: {主题}. The backend may not be broadcasting yet, or the link is blocked.",
  ],
  "问题.命令失败": ["有命令被拒 / 失败", "A command was rejected / failed"],
  "问题.命令失败.说明": [
    "最近 {数量} 条失败回执，见「输出」页签（等级 = 错误）。失败的命令**没有生效**。",
    "The latest {数量} failed receipt(s) are in the Output tab (level = error). A failed command **did not take effect**.",
  ],
  "问题.前端异常": ["前端自身报过错", "The frontend itself reported an error"],
  "问题.前端异常.说明": [
    "来源标注为「前端」的错误行不是后端的问题，是这一层自己的异常。",
    "Error lines tagged “frontend” did not come from the backend — they are exceptions in this layer.",
  ],
  "问题.非JSON": ["收到过非 JSON 消息", "A non-JSON message arrived"],
  "问题.非JSON.说明": [
    "这条已经写在「输出」里，通常是端口上有别的东西在说话。",
    "Also logged under Output — usually something else is talking on the port.",
  ],

  // ---- 状态栏 ----
  "状态栏.项目": ["项目", "Project"],
  "状态栏.模型": ["模型", "Model"],
  "状态栏.物理": ["物理", "Physics"],
  "状态栏.仿真时间": ["仿真时间", "Sim time"],
  "状态栏.曲线帧率": ["曲线帧率", "Curve rate"],
  "状态栏.连接": ["连接", "Link"],
  "状态栏.物理.开": ["推进中", "running"],
  "状态栏.物理.关": ["冻结", "frozen"],
  "状态栏.物理.未知": ["--", "--"],
  "状态栏.语言": ["语言", "Language"],
  "状态栏.切到": ["切到 {语}", "Switch to {语}"],
  "状态栏.皮肤": ["皮肤", "Skin"],
  "状态栏.提示.项目": ["当前项目名（来自 项目状态）", "Current project name (from project state)"],
  "状态栏.提示.模型": ["当前模型（来自 模型状态）", "Current model (from model state)"],
  "状态栏.提示.物理": ["物理总闸：推进物理 / 冻结在默认位置", "Physics master switch: stepping / frozen at the default pose"],
  "状态栏.提示.仿真时间": ["连接建立后经过的墙钟时间（仿真侧的仿真时间不在契约里）", "Wall-clock time since the link came up (the simulation's own sim time is not in the contract)"],
  "状态栏.提示.曲线帧率": ["指标帧的实测到达速率（最近一秒）", "Measured arrival rate of metric frames (last second)"],
  "状态栏.提示.连接": ["WebSocket 连接状态", "WebSocket link state"],

  // ---- 连接状态 ----
  "连接.连接中": ["连接中", "connecting"],
  "连接.已连接": ["已连接", "connected"],
  "连接.已断开": ["已断开", "disconnected"],

  // ---- 定义（资产库 / 模型） ----
  "定义.当前模型": ["当前模型", "Current model"],
  "定义.模型路径": ["路径", "Path"],
  "定义.模型显示名": ["显示名", "Display name"],
  "定义.自由度": ["自由度 nq", "DoF nq"],
  "定义.执行器数": ["执行器数 nu", "Actuators nu"],
  "定义.模型状态": ["状态", "State"],
  "定义.加载耗时": ["上次加载耗时", "Last load"],
  "定义.没模型": ["后端还没有报模型 —— 可能在启动，也可能没加载任何模型。", "The backend has not reported a model yet — it may still be starting, or none is loaded."],
  "定义.当前项目": ["当前项目", "Current project"],
  "定义.项目名": ["项目", "Project"],
  "定义.算法组": ["挂载的算法", "Mounted algorithms"],
  "定义.算法数": ["算法数量", "Algorithm count"],
  "定义.控盘": ["在写 ctrl 的算法", "Writing ctrl"],
  "定义.被覆盖": ["输出被覆盖", "Outputs masked"],
  "定义.已存盘": ["算法组已写回项目文件", "Algorithm set saved to the project file"],
  "定义.装配报告": ["上次装配报告", "Last assembly report"],
  "定义.没项目": ["后端没有报项目。", "The backend reports no project."],
  "定义.资产库": ["资产库（模型库）", "Asset library (model library)"],
  "定义.资产库.说明": [
    "点一台即可直接加载（走 `命令.换模型`，不搞「点了就算成功」—— 每条命令都有回执）。",
    "Click a robot to load it right away (via `命令.换模型`; every command gets an ack).",
  ],
  "定义.资产库.空": [
    "后端没有报上来任何资产。可能模型清单还没读出来，或一个模型都没导入。",
    "The backend reported no assets — the model inventory may not be loaded, or no models are imported.",
  ],
  "定义.资产库.带星": ["当前加载", "loaded"],
  "定义.资产库.点选": ["加载这台：{名}", "Load {名}"],
  "定义.资产库.待接入": [
    "模型库列表**还没进契约**：`软件/契约.py` 里只有「当前模型」，没有可浏览的模型清单。",
    "The model library is **not in the contract yet**: the contract carries only the current model, not a browsable list.",
  ],
  "定义.资产库.后补": [
    "要真做这一格，需要后端新增一条下行主题（形如 资产.模型清单）并重新生成契约；在那之前这里只列出「当前模型」，不编一份假的目录树。",
    "Doing this properly needs a new downlink topic (e.g. assets.model-list) plus a contract regeneration; until then this pane lists only the current model instead of inventing a fake catalogue.",
  ],
  "定义.算法库": ["算法库", "Algorithm library"],
  "定义.算法库.说明": [
    "下面这些名字来自 `项目状态.算法库`（后端在算法库目录里真的扫到的），已经挂到本项目上的会打勾。",
    "These names come from the project state's algorithm library — scanned from the real algorithms directory. Those already mounted on this project are ticked.",
  ],
  "定义.算法库.空": ["算法库里没有算法。", "The algorithm library is empty."],
  "定义.算法库.已挂": ["已挂", "mounted"],
  "定义.换模型": ["换模型（按路径）", "Switch model (by path)"],
  "定义.换模型.路径": ["模型路径（相对包根或绝对路径）", "Model path (relative to the package root, or absolute)"],
  "定义.换模型.显示名": ["显示名（可留空）", "Display name (optional)"],
  "定义.换模型.提交": ["加载这个路径", "Load this path"],
  "定义.换模型.说明": [
    "这条路等价于后端的换模型命令：会连带按项目重新装配算法。命令要等回执，失败会写到「输出」并弹出提示。",
    "This maps to the backend's switch-model command and re-assembles algorithms for the project. It awaits a receipt; failures land in Output and raise a toast.",
  ],
  "定义.换模型.要路径": ["先填一个模型路径。", "Type a model path first."],
  "定义.换模型.例子": ["模型/<型号>/scene.xml", "models/<name>/scene.xml"],

  // ---- 规划 ----
  "规划.未实现标题": ["轨迹规划尚未实现", "Trajectory planning is not implemented"],
  "规划.未实现说明": [
    "契约里没有任何与规划有关的主题 —— 没有规划请求，也没有规划结果。所以这一格**不能**画曲线、不能画路点，画了就是假的。",
    "The contract has no planning topic at all — no request, no result. So this pane **cannot** show curves or waypoints; showing any would be fake.",
  ],
  "规划.将包含": ["这一格将来会包含", "This pane will contain"],
  "规划.路点": ["路点表（关节/末端位姿、时间戳、来源）", "Waypoint table (joint/Cartesian pose, timestamp, source)"],
  "规划.关节约束": ["关节空间约束：位置/速度/加速度上下限", "Joint-space constraints: position/velocity/acceleration limits"],
  "规划.MVC": ["MVC 包络（速度-力矩可行域）与实际轨迹是否越界", "MVC envelope (velocity–torque feasible set) and whether the trajectory leaves it"],
  "规划.剖面": ["路径剖面：s(t)、s'(t)、s''(t) 与时间最优换挡点", "Path profile: s(t), s'(t), s''(t) and the time-optimal switching points"],
  "规划.约束满足率": ["约束满足率与**约束回代校验**（把结果代回约束里逐点验）", "Constraint satisfaction rate and **re-substitution check** (feed the result back through the constraints, point by point)"],
  "规划.为什么空着": ["为什么这一格是空的", "Why this pane is empty"],
  "规划.为什么这样": [
    "规格里对规划器的判据是「能不能回答约束满足率与贴合误差」—— 答不出来的就是原型。这一格在这里的意义就是**明确地空着**。",
    "The spec's test for a real planner is whether it can answer constraint-satisfaction and tracking error. One that cannot is a prototype. This pane's job right now is to stay honestly empty.",
  ],
  "规划.要什么": ["要真做，需要：上行规划请求主题 + 下行规划结果主题 + 观测核心（时间戳/seq/错误码）。", "Doing it for real needs an uplink planning request, a downlink planning result, and the observation core (timestamps/seq/error codes)."],
  "规划.结果主题": ["0 条规划结果主题", "0 planning-result topics"],
  "规划.上行现有": ["契约里现有的上行命令（全是别的事，没有一条与规划有关）", "Uplink commands in the contract today (none of them about planning)"],

  // ---- 验证：曲线 ----
  "验证.曲线": ["曲线（实时）", "Curves (live)"],
  "验证.曲线.说明": [
    "数据来自下行主题「指标」的 `数值`：键名形如「插件名·键名」，值是后端算出来的数。前端不加工、不外推。",
    "Data comes from the metric topic's values map: keys look like “plugin·key”, values are computed by the backend. The frontend neither post-processes nor extrapolates.",
  ],
  "验证.窗口": ["时间窗", "Window"],
  "验证.窗口.标签": ["时间窗", "Window"],
  "验证.窗口.值": ["{值} 秒（跟随仓库的环形缓冲上限）", "{值} s (matches the store's ring buffer)"],
  "验证.选中": ["显示", "Show"],
  "验证.全选": ["全选", "All"],
  "验证.全不选": ["全不选", "None"],
  "验证.没有指标": [
    "还没有收到任何指标帧。要么后端没在广播「指标」，要么没有算法在报数。",
    "No metric frame received yet. Either the backend is not broadcasting metrics, or no algorithm reports any.",
  ],
  "验证.曲线名": ["曲线", "Series"],
  "验证.当前值": ["当前值", "Current"],
  "验证.点数": ["点数", "Points"],
  "验证.峰": ["峰值", "Peak"],
  "验证.暂停中": ["暂停中（鼠标在图上）", "paused (pointer over the plot)"],
  "验证.取消选中": ["这条没在显示", "hidden"],
  "验证.超出窗口": [
    "{条} 条曲线的数据点早于当前时间窗（后端没再发新帧）。",
    "{条} series have points older than the current window (the backend stopped sending frames).",
  ],
  "曲线.空": ["没有可画的点。", "No points to draw."],
  "曲线.轴时间": ["墙钟（秒，0 = 最新一点）", "wall clock (s, 0 = newest point)"],
  "曲线.放大提示": ["滚轮缩放时间窗（{值} 秒）", "wheel zooms the window ({值} s)"],
  "曲线.说明": ["横轴用**墙钟**而不是仿真时间：物理暂停时仿真时间不动，曲线会挤成一坨。", "The x axis uses **wall clock**, not sim time: when physics is paused sim time freezes and the curve collapses into a spike."],

  // ---- 验证：参数表 ----
  "验证.参数": ["参数表（可编辑）", "Parameter table (editable)"],
  "验证.参数.说明": [
    "数据来自下行主题「参数表」，是各算法自己声明的可调参数。",
    "Data comes from the parameter-table topic — tunables declared by each algorithm.",
  ],
  "验证.参数.可编辑": [
    "直接改上面的数值即可（走 `命令.改参数`，等后端回执；改完 `参数表` 会回灌最新值）。范围与步长来自后端声明，越界由算法自己拒绝。改动会写回当前项目文件——这是「这一组参数」成为实验记录一部分的方式。",
    "Edit a value directly (sent as the `命令.改参数` command and confirmed by a receipt; the parameter table then reports the new value). Bounds and step come from the backend, and out-of-range values are rejected by the algorithm itself. Changes are saved back into the current project file.",
  ],
  "验证.参数.空": ["后端还没有报参数表（可能没有算法声明可调参数）。", "The backend has not reported a parameter table (perhaps no algorithm declares tunables)."],
  "验证.参数.插件": ["插件", "Plugin"],
  "验证.参数.名": ["参数", "Parameter"],
  "验证.参数.值": ["值", "Value"],
  "验证.参数.最小": ["最小", "Min"],
  "验证.参数.最大": ["最大", "Max"],
  "验证.参数.单位": ["单位", "Unit"],
  "验证.参数.说明列": ["说明", "Note"],
  "验证.参数.值缺": ["（没报值）", "(no value)"],
  "验证.参数.取值表头": ["这一项后端没按标准形状报，原样列出：", "This entry does not follow the standard shape; listed verbatim:"],
  "验证.参数.范围条": ["{值} ∈ [{最小}, {最大}]", "{值} ∈ [{最小}, {最大}]"],

  // ---- 辨识 ----
  "辨识.标题": ["参数辨识", "System identification"],
  "辨识.状态": ["状态", "State"],
  "辨识.进度": ["进度", "Progress"],
  "辨识.采样步数": ["采样步数", "Sampled steps"],
  "辨识.耗时": ["耗时", "Elapsed"],
  "辨识.结果": ["辨识结果", "Results"],
  "辨识.拟合": ["拟合", "Fit"],
  "辨识.日志": ["日志（最新在下）", "Log (newest last)"],
  "辨识.开始": ["开始辨识", "Start identification"],
  "辨识.停止": ["停止辨识", "Stop identification"],
  "辨识.时长": ["采样时长（秒）", "Sample duration (s)"],
  "辨识.时长说明": [
    "时长会作为 `命令.辨识` 的 `时长` 字段发给后端；后端说不行就以回执为准。",
    "The duration is sent as the identify command's duration field; if the backend disagrees, its receipt wins.",
  ],
  "辨识.没状态": ["后端还没有报辨识状态。", "The backend has not reported identification state yet."],
  "辨识.没结果": ["还没有结果。", "No results yet."],
  "辨识.没拟合": ["还没有拟合数据。", "No fit data yet."],
  "辨识.残差诚实": [
    "残差下降只说明这组参数更贴合**这批数据**；它**不能**证明这组参数等于真实机器人。",
    "A lower residual means the parameters fit **this batch of data** better; it does **not** prove they equal the real robot.",
  ],
  "辨识.停不了": ["当前状态不是「采样中/辨识中」；停止命令仍会发给后端（由它判定）。", "The current state is not “sampling/identifying”; the stop command is still sent to the backend, which judges it."],

  // ---- 部署 ----
  "部署.未接入标题": ["真机部署：未接入", "Real-hardware deploy: not connected"],
  "部署.未接入说明": [
    "**没有任何硬件协议后端存在**。契约里没有设备抽象、没有传输层、没有时间戳/序号/错误码，也没有安全状态机。",
    "**No hardware protocol backend exists.** The contract has no device abstraction, no transport layer, no timestamps/sequence numbers/error codes, and no safety state machine.",
  ],
  "部署.诚实要求": [
    "验收项明确写着：「Deploy 页面没有未接入状态 = 假实现」。所以这一格的第一状态**必须**是未接入，而不是一个绿灯。",
    "The acceptance criterion is explicit: “a Deploy page without a not-connected state is a fake”. So the first state of this pane **must** be not-connected, not a green light.",
  ],
  "部署.连接设置": ["连接设置（不生效）", "Connection settings (inactive)"],
  "部署.连接设置.说明": [
    "下面这些框不连任何东西：填了也不会发出去，因为**没有可发的目标**。它们在这里是为了说明将来要有哪些字段。",
    "These fields connect to nothing: filling them sends nothing, because there is no target to send to. They exist to show which fields will be needed.",
  ],
  "部署.协议": ["协议", "Protocol"],
  "部署.有绿灯": ["有一个「已连接」的绿灯", "Has a “connected” green light"],
  "部署.地址": ["地址", "Host"],
  "部署.端口": ["端口", "Port"],
  "部署.波特率": ["波特率", "Baud"],
  "部署.安全": ["安全边界", "Safety boundary"],
  "部署.安全说明": [
    "规格要求：本软件不承担人身安全职责，必须另有硬件安全回路；每次真机连接都要用户确认这一条。在产品里这句话要显式出现，不能藏在文档里。",
    "The spec requires stating that this software carries no personal-safety responsibility, that a separate hardware safety loop is mandatory, and that the user confirms this on every real connection. That sentence must appear in the product, not only in documents.",
  ],
  "部署.要什么": ["要真做，最少需要这些（与协议无关的那部分返工风险接近 0）", "Doing it for real needs at least these (the protocol-independent part has near-zero rework risk)"],
  "部署.要什么.设备抽象": ["设备抽象 + 契约测试套件", "Device abstraction + contract test suite"],
  "部署.要什么.仿真后端": ["SimBackend + 劣化注入（延迟/丢包/量化，固定种子）", "SimBackend + degradation injection (latency/loss/quantisation, fixed seed)"],
  "部署.要什么.安全层": ["安全层：看门狗、状态机、限幅、限速、首帧、审计", "Safety layer: watchdog, state machine, clamping, rate limiting, first frame, audit"],
  "部署.要什么.传输": ["UDP / 串口传输（任何协议都要用的底座）", "UDP / serial transport (the base every protocol needs)"],
  "部署.要什么.真机": ["真机首跑 +15~25 人日；CAN +20~40；EtherCAT +65~130（很可能要换 Linux）", "First real-hardware run +15~25 person-days; CAN +20~40; EtherCAT +65~130 (likely requires Linux)"],
  "部署.绿灯是假的": [
    "识别方法：假部署永远显示「已连接」。这里没有绿灯，因为**没有任何东西可连**。",
    "How to spot a fake: it always shows “connected”. There is no green light here because there is **nothing to connect to**.",
  ],

  // ---- 外观视图 ----
  "外观.皮肤": ["皮肤", "Skin"],
  "外观.皮肤说明": [
    "5 套皮肤与 `软件/风格表.json` 同源（`生成/主题.css` 是它的产物）。点一下即应用，写到 localStorage，下次打开还是这套。",
    "The 5 skins come from the same source as the style table (`生成/主题.css` is generated from it). One click applies, persists to localStorage, and survives the next launch.",
  ],
  "外观.当前": ["当前", "current"],
  "外观.语言": ["语言", "Language"],
  "外观.语言说明": [
    "语言写 localStorage；界面文字走 `视图/文案.ts`，键表里中英都在。",
    "The language persists to localStorage; all UI text comes from the i18n table, which carries both languages.",
  ],
  "外观.快捷键": [
    "皮肤随数据属性切换：`<html data-风格=…>`，颜色全部来自 `var(--…)`。",
    "Skins switch via a data attribute on `<html>`; every colour comes from `var(--…)`.",
  ],

  // ---- 关于视图 ----
  "关于.标题": ["关于", "About"],
  "关于.名称": ["名称", "Name"],
  "关于.版本": ["契约版本 / 协议版本", "Contract / protocol version"],
  "关于.主题数": ["契约主题数", "Contract topics"],
  "关于.下行": ["下行主题", "Downlink topics"],
  "关于.上行": ["上行命令", "Uplink commands"],
  "关于.握手": ["握手", "Handshake"],
  "关于.握手.有": [
    "已握手：后端承诺 {可用} 条主题，广播间隔 {间隔} 秒，契约版本 {版本}。",
    "Handshaken: the backend promises {可用} topics, a {间隔} s broadcast interval, contract version {版本}.",
  ],
  "关于.握手.无": ["尚未握手。（握手消息不在契约里 —— 它是连接层的问候帧。）", "No handshake yet. (The handshake is not in the contract — it is the transport's greeting frame.)"],
  "关于.帧号": ["最新帧序号", "Newest frame seq"],
  "关于.帧号.无": ["还没有收到帧", "no frame received yet"],
  "关于.声明": ["声明", "Notices"],
  "关于.声明一": [
    "本软件是独立项目，与 Google DeepMind 无隶属、无背书、无赞助关系。",
    "This software is an independent project, not affiliated with, endorsed by, or sponsored by Google DeepMind.",
  ],
  "关于.声明二": [
    "基于 MuJoCo（Apache-2.0）。MuJoCo 是其所有者的商标；本项目不把它当作自己名字的一部分。",
    "Built on MuJoCo (Apache-2.0). MuJoCo is a trademark of its owner; this project does not use it as part of its own name.",
  ],
  "关于.声明三": ["这一层只做界面：不读文件、不读进程、不调平台 API，一切经 `数据/仓库.ts`。", "This layer is UI only: it reads no files, no processes and no platform APIs — everything goes through the store module."],

  // ---- 日志文案 ----
  "日志.启动": ["前端已启动，开始连接后端", "Frontend started, connecting to the backend"],
  "日志.连接中": ["正在连接后端…", "Connecting to the backend…"],
  "日志.已连接": ["已连接到后端", "Connected to the backend"],
  "日志.已断开": ["与后端断开，正在按退避重连", "Disconnected from the backend, retrying with backoff"],
  "日志.握手": [
    "握手成功：{主题数} 条下行主题，广播间隔 {间隔} s{契约}",
    "Handshake ok: {主题数} downlink topics, {间隔} s broadcast interval{契约}",
  ],
  "日志.握手契约": ["，契约版本 {版本}", ", contract version {版本}"],
  "日志.回执简单通过": ["{主题}：回执通过", "{主题}: receipt ok"],
  "日志.回执通过": ["{主题} 已受理（{耗时} ms）", "{主题} accepted ({耗时} ms)"],
  "日志.回执失败": ["{主题} 被拒 / 失败：{说明}", "{主题} rejected / failed: {说明}"],
  "日志.无说明": ["（无说明）", "(no reason given)"],
  "日志.耗时": ["耗时 {值} ms", "took {值} ms"],
  "日志.后端错误细节": ["后端报错 —— 数据可能已经不是最新的", "Backend error — the data may no longer be current"],
  "日志.未捕获": ["未捕获异常：{信息}", "Uncaught exception: {信息}"],
  "日志.无信息": ["（无信息）", "(no message)"],
  "日志.未处理拒绝": ["未处理的 Promise 拒绝：{原因}", "Unhandled promise rejection: {原因}"],
  "日志.行号": ["行 {值}", "line {值}"],

  // ---- 命令失败提示 ----
  "提示.命令失败": ["{主题} 失败", "{主题} failed"],
  "提示.没有说明": ["后端没有给出说明", "the backend gave no reason"],
  "提示.换模型受理": ["换模型命令已受理", "Switch-model command accepted"],
  "提示.辨识受理": ["辨识命令已受理", "Identification command accepted"],
  "提示.物理受理": ["物理总闸命令已受理", "Physics switch command accepted"],
  "提示.缺路径": ["先填一个模型路径", "Type a model path first"],

  // ---- 分隔条 ----
  "分隔条.侧栏": ["拖动调整侧栏宽度；方向键微调，Home/End 到两端", "Drag to resize the sidebar; arrow keys nudge, Home/End jump to the ends"],
  "分隔条.控制台": ["拖动调整控制台高度；方向键微调，Home/End 到两端", "Drag to resize the console; arrow keys nudge, Home/End jump to the ends"],
} as const satisfies Record<string, readonly [string, string]>;

export type 文案键 = keyof typeof 表;

/**
 * 连接状态 → 文案键。
 * 为什么要这么一层：`取()` 的键是**字面量联合**（写错键名 `tsc` 就报错），
 * 而模板字符串拼出来的 `` `连接.${状态}` `` 推不出字面量。
 * 与其到处 `as const` 硬转（那等于把类型检查关掉），不如把映射写在这里一次说清。
 */
export const 连接键 = {
  连接中: "连接.连接中",
  已连接: "连接.已连接",
  已断开: "连接.已断开",
} as const satisfies Record<string, 文案键>;

/**
 * 取文案。
 * @param 键 文案键（由 `表` 约束，写错键名 `tsc` 直接报错）
 * @param 参 模板参数：`{名}` → 值
 */
export function 取(键: 文案键, 参?: Record<string, string | number>): string {
  const 条 = 表[键][当前语言 === "zh" ? 0 : 1];
  if (!参) return 条;
  return 条.replace(/\{([^}]+)\}/g, (整, 名: string) => {
    const 值 = 参[名];
    return 值 === undefined ? 整 : String(值);
  });
}

/** 组件里用的版本：语言一变，用到它的组件自动重画 */
export function use取(): (键: 文案键, 参?: Record<string, string | number>) => string {
  用语言(); // 订阅语言变化
  return 取;
}

/** 数字格式化：固定小数位 + 等宽显示（不做任何"美化"，就是格式化） */
export function 数(值: number | undefined | null, 位 = 3): string {
  if (值 === undefined || 值 === null || !Number.isFinite(值)) return "--";
  return 值.toFixed(位);
}

/** 时间戳 → HH:MM:SS（本地时区） */
export function 时刻(毫秒: number): string {
  const d = new Date(毫秒);
  const p = (n: number, 宽 = 2) => String(n).padStart(宽, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 秒数 → 人类可读时长（用于耗时/仿真时间） */
export function 时长(秒: number | undefined | null): string {
  if (秒 === undefined || 秒 === null || !Number.isFinite(秒)) return "--";
  if (秒 < 60) return `${秒.toFixed(秒 < 10 ? 2 : 1)} s`;
  const 分 = Math.floor(秒 / 60);
  const 余 = Math.floor(秒 % 60);
  if (分 < 60) return `${分}m ${String(余).padStart(2, "0")}s`;
  const 时 = Math.floor(分 / 60);
  return `${时}h ${String(分 % 60).padStart(2, "0")}m`;
}
