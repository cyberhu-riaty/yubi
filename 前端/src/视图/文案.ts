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
  "活动栏.流程组": ["流程", "Flow"],
  "活动栏.运行组": ["运行", "Run"],
  "活动栏.信息组": ["信息", "Info"],

  // ---- 任务流 ----
  "任务流.提示": ["任务流只换左侧上下文，右侧原生 3D 视口常驻不切换。", "The task flow only swaps the left context; the native 3D viewport on the right stays put."],
  "步骤.定义": ["定义", "Define"],
  "步骤.定义.一句话": ["选机械臂、看当前项目", "Pick the arm, inspect the current project"],
  "步骤.规划": ["规划", "Plan"],
  "步骤.规划.一句话": ["关节航点 → 时间参数化轨迹", "Joint waypoints → time-parameterized trajectory"],
  "步骤.验证": ["验证", "Verify"],
  "步骤.验证.一句话": ["实时曲线与参数表", "Live curves and parameter table"],
  "步骤.辨识": ["辨识", "Identify"],
  "步骤.辨识.一句话": ["参数辨识进度与结果", "System identification progress and results"],
  "规划.说明": [
    "先记录几个关节航点，再点「规划」。后端会用真实关节限位算出一条时间参数化轨迹，并回算校验；下面的数字都来自回算，不是估的。",
    "Record a few joint waypoints, then press Plan. The backend plans a time-parameterized trajectory under the real joint limits and re-checks it; every number below comes from that check, not estimation.",
  ],
  "规划.记录": ["记录当前姿态", "Record pose"],
  "规划.规划": ["规划", "Plan"],
  "规划.规划中": ["规划中…", "Planning…"],
  "规划.清空": ["清空航点", "Clear"],
  "规划.已记录": ["已记录航点", "waypoints"],
  "规划.航点计数": ["{数量} 航点", "{数量} wp"],
  "规划.尚无航点": ["尚无航点", "no waypoints"],
  "规划.高亮瓶颈": ["在 3D 中高亮 J{关节}", "Highlight J{关节} in 3D"],
  "规划.需要航点": [
    "先记录至少 2 个航点，才能规划；「记录当前姿态」每点一次记一条。",
    "Record at least 2 waypoints before planning; “Record pose” adds one per click.",
  ],
  "规划.失败": ["规划失败", "failed"],
  "规划.航点数": ["航点数", "Waypoints"],
  "规划.自由度": ["自由度", "DoF"],
  "规划.总时长": ["总时长", "Duration"],
  "规划.路径长度": ["路径长度", "Path length"],
  "规划.终端速度": ["终端速度", "Terminal speed"],
  "规划.最大速度": ["最大关节速度 rad/s", "Max joint speed"],
  "规划.最大加速度": ["最大关节加速度 rad/s²", "Max joint accel"],
  "规划.最大加加速度": ["最大关节加加速度 rad/s³", "Max joint jerk"],
  "规划.瓶颈": ["瓶颈", "Bottleneck"],
  "规划.实际比下界": ["实际/理论下界", "actual / lower bound"],
  "规划.余量": ["余量", "margin"],
  "规划.限位来源": ["限位来源", "limits from"],
  "规划.对比": ["与上次对比", "vs previous"],
  "规划.对比.说明": [
    "灰线=上次，蓝线=本次；横轴是路径参数 s。只有航点相同才出对比——路径不同时比快慢没有意义。",
    "Grey = previous, blue = current; x-axis is path parameter s. Compared only when the waypoints are identical.",
  ],
  "规划.笛卡尔": ["笛卡尔航点（逆解）", "Cartesian waypoints (IK)"],
  "规划.笛卡尔.说明": [
    "每行 `x y z`（米，末端执行器的世界坐标）。后端用阻尼最小二乘解成关节航点再规划；**只支持位置，姿态约束未实现**。解不出来会报第几个点。",
    "One `x y z` per line (metres, world frame of the end effector). The backend solves it into joint waypoints with damped least squares, then plans. Position only — orientation constraints are not implemented. Failures report which point.",
  ],
  "规划.笛卡尔.算": ["逆解并规划", "Solve & plan"],
  "规划.逆解": ["逆解", "IK"],
  "规划.速度上限": ["速度上限", "Speed cap"],
  "规划.加速度上限": ["加速度上限", "Accel cap"],
  "规划.自动": ["自动", "auto"],
  "规划.导入": ["导入 CSV", "Import CSV"],
  "规划.导入成功": ["已导入", "Imported"],
  "规划.导入失败": ["导入失败", "Import failed"],
  "规划.文件说明": [
    "CSV/纯文本：每行一组关节角（逗号或空格分隔）；`#` 开头的行与首行表头会自动跳过。列数必须等于当前机器人关节数。",
    "CSV/plain text: one set of joint angles per line (comma or space separated). Lines starting with # and a first header row are skipped. The column count must equal the robot's joint count.",
  ],
  "规划.执行": ["执行轨迹", "Execute"],
  "规划.停止": ["停止执行", "Stop"],
  "规划.存盘": ["离线产物", "Saved to"],
  "规划.执行进度": ["执行进度", "Progress"],
  "规划.包络": ["速度包络（灰=上界，蓝=实际）", "Speed envelope (grey = cap, blue = actual)"],
  "部署.标题": ["部署包（导出）", "Deployment package (export)"],
  "部署.总大小": ["总大小", "Total size"],
  "部署.模型清单说明": [
    "模型文件的 sha256 写在导出包的 模型清单.md 里；界面只列出文件，不读取包内文件。",
    "Model-file sha256 values are in 模型清单.md inside the exported package; the UI lists files but does not read package contents.",
  ],
  "部署.设备": ["设备连接", "Device link"],
  "部署.设备说明": [
    "这一格控制的是**设备链路**：状态机、看门狗、劣化注入、审计。所有遥测数字都来自真实帧的时间戳与后端统计。",
    "This panel drives the device link: state machine, watchdog, degradation injection, audit. Every telemetry number comes from real frame timestamps and backend counters.",
  ],
  "部署.模拟后端": [
    "⚠ 当前后端是「模拟后端」——它不是真机。真机还需要协议后端（UDP/串口/CAN）与独立的物理急停回路。",
    "⚠ The current backend is a simulator — not real hardware. Real hardware still needs a protocol backend (UDP/serial/CAN) and an independent physical e-stop circuit.",
  ],
  "部署.后端": ["后端", "Backend"],
  "部署.模式": ["控制模式", "Mode"],
  "部署.实测平均延迟": ["实测平均延迟", "Measured mean latency"],
  "部署.实测最大延迟": ["实测最大延迟", "Measured max latency"],
  "部署.丢包错序": ["丢包 / 错序", "Dropped / reordered"],
  "部署.拒绝数": ["被拒绝的命令", "Rejected commands"],
  "部署.最近位置": ["最近位置", "Latest position"],
  "部署.还没收到": ["还没收到", "nothing yet"],
  "部署.打开": ["打开", "Open"],
  "部署.使能": ["使能", "Enable"],
  "部署.进运行": ["进入运行", "Run"],
  "部署.停止": ["停止", "Stop"],
  "部署.急停": ["急停（请求）", "E-stop (request)"],
  "部署.演练": ["演练断线", "Drill: link loss"],
  "部署.导出审计": ["导出审计", "Export audit"],
  "部署.延迟": ["注入延迟", "Injected latency"],
  "部署.抖动": ["注入抖动", "Injected jitter"],
  "部署.丢包": ["注入丢包", "Injected loss"],
  "部署.量化": ["编码器量化", "Encoder quantization"],
  "部署.审计": ["审计（最近 30 条）", "Audit (last 30)"],
  "部署.态.未连接": ["未连接", "Disconnected"],
  "部署.态.已连接（未使能）": ["已连接（未使能）", "Connected (disabled)"],
  "部署.态.使能中": ["使能中", "Enabling"],
  "部署.态.运行": ["运行", "Running"],
  "部署.态.停止": ["停止", "Stopped"],
  "部署.态.故障": ["故障", "Fault"],
  "部署.态.急停": ["急停", "E-stop"],
  "部署.说明": [
    "把当前项目导出成一个可带走的部署包：项目配置、算法源码、模型清单（含校验和）。包里的都是真文件，导出后可以直接打开查看。",
    "Export the current project as a portable deployment package: project config, algorithm sources, and a model manifest with checksums. Everything in it is a real file you can open.",
  ],
  "部署.没有连接": [
    "真机连接不在本软件范围内：没有传输层、设备抽象和安全状态机。这里只导出部署包，不会连接或控制真机。",
    "Hardware connection is out of scope: there is no transport, device abstraction, or safety state machine. This page only exports a package; it does not connect to or control hardware.",
  ],
  "部署.状态": ["连接状态", "Connection state"],
  "部署.后端连接": ["后端（界面数据）", "Backend (UI data)"],
  "部署.后端已连接": ["已连接", "connected"],
  "部署.真机状态": ["真机", "Hardware"],
  "部署.真机未接入": ["未接入（没有设备层）", "not connected (no device layer)"],
  "部署.包内容": ["部署包内容", "Package contents"],
  "部署.包说明": ["导出后列出真实文件与字节数；SHA-256 由后端在导出时计算。", "After export, real files and sizes are listed; SHA-256 is computed by the backend during export."],
  "部署.导出": ["导出部署包", "Export package"],
  "部署.导出中": ["导出中…", "Exporting…"],
  "部署.未导出": ["还没导出", "not exported"],
  "部署.失败": ["导出失败", "failed"],
  "部署.目录": ["导出到", "Exported to"],
  "部署.项目": ["项目", "Project"],
  "步骤.插件": ["插件", "Plugins"],
  "步骤.插件.一句话": [
    "本机算法库里有什么插件、什么版本、被谁用到 —— 不是商店",
    "What plugins exist in the local library, their versions, and who uses them — not a store",
  ],
  "插件.说明": [
    "这里列出本机算法库里的插件及其信息；当前项目的算法选择统一在「定义」页完成。",
    "This lists local plugins and their details; configure the current project's algorithms under Define.",
  ],
  "插件.只读说明": ["本页只查看算法信息；选择、应用和保存集中在「定义」页。", "This page is informational; selection, apply, and save live under Define."],
  "插件.去定义": ["去「定义」配置", "Configure under Define"],
  "插件.状态.已安装": ["本机已安装", "installed locally"],
  "插件.文件": ["文件", "File"],
  "插件.未被任何项目使用": ["未被任何项目使用", "not used by any project"],
  "插件.不兼容说明": ["当前模型与这个插件不兼容；启用会被装配跳过。", "This plugin is incompatible with the current model; enabling would be skipped during assembly."],
  "插件.兼容性在装配时判定": ["兼容性在启用/装配时判定；当前项目报告里没有它的不兼容记录。", "Compatibility is decided on enable/assembly; the current project report has no incompatibility for it."],
  "插件.状态.当前项目已启用": ["当前项目已启用", "enabled in this project"],
  "插件.状态.当前项目未启用": ["当前项目未启用", "not enabled in this project"],
  "插件.兼容性未判定": ["兼容性：由当前项目的装配报告判定", "Compatibility: decided by the current project assembly report"],
  "插件.启用会判定": ["启用后会按当前模型装配；不兼容时报告会写明原因。", "On enable it is assembled against the current model; if incompatible, the report states why."],
  "插件.没有远端": [
    "注意：这里没有远端市场 —— 不能下载、不能装新插件。当前只列出本机已有的。",
    "Note: there is no remote marketplace here — nothing can be downloaded or installed. Only local plugins are listed.",
  ],
  "插件.已启用": ["已启用", "enabled"],
  "插件.启用": ["启用", "Enable"],
  "插件.停用": ["停用", "Disable"],
  "插件.作者": ["作者", "Author"],
  "插件.被使用": ["被这些项目用到", "Used by"],
  "插件.没人用": ["还没有项目用到它", "No project uses it yet"],
  "插件.未标注": ["版本未标注", "version not declared"],
  "插件.无说明": ["（这个插件没写说明）", "(no description in the plugin)"],
  "插件.空": ["算法库里没有插件", "No plugins in the library"],
  "步骤.诊断": ["诊断", "Diagnose"],
  "步骤.诊断.一句话": [
    "把终端里那些断言搬进界面：点一下真跑一遍，逐条报过没过",
    "The terminal checks, in the UI: click to actually run them, one result per suite",
  ],
  "诊断.说明": [
    "点「开始检查」会真的重跑本机检查脚本，没有“上次全绿”的缓存。结果逐项列出，失败项给出原因。",
    "Run checks actually re-runs the local check scripts; there is no cached all-green. Results are listed per item, with a reason for failures.",
  ],
  "诊断.高级": ["高级信息（命令 / 子进程）", "Advanced (commands / subprocesses)"],
  "诊断.高级说明": [
    "检查脚本位于本机 工具/验证/ 目录，由后端用子进程执行；命令与进程细节属于开发诊断信息。",
    "The checks live in 工具/验证/ and are executed by the backend as subprocesses; command and process details are developer diagnostics.",
  ],
  "诊断.未运行": ["未运行", "not run"],
  "诊断.已用时": ["已用时 {秒} s", "elapsed {秒} s"],
  "诊断.导出": ["导出报告", "Export report"],
  "诊断.开始": ["开始检查", "Run checks"],
  "诊断.运行中": ["检查中…", "Running…"],
  "诊断.没跑过": ["还没跑过 —— 点上面的按钮开始", "Not run yet — use the button above"],
  "步骤.监控": ["监控", "Monitor"],
  "步骤.监控.一句话": [
    "实时率、步频、内存 —— 跑得动跑不动，看这里",
    "Real-time factor, step rate, memory — whether it keeps up",
  ],
  "监控.告警": ["病态告警", "Fault alerts"],
  "监控.告警.说明": [
    "这些是软件从时序数据里**判定**出的结论，不是原始数字：每条都带量化证据（频率/振幅/斜率/时段）。没检出不等于没问题，只等于没命中已知的四类。",
    "These are conclusions the software reached from the time series, not raw numbers: each carries quantitative evidence (frequency, amplitude, slope, interval). No alert only means none of the four known patterns matched.",
  ],
  "监控.告警.走势": ["走势（最近）", "Trend (last)"],
  "监控.告警.经验": [
    "建议是按经验规则给的，不是自动整定；改完请再看一段曲线确认。",
    "Suggestions are rule-of-thumb, not auto-tuning; re-check the curves after changing.",
  ],
  "监控.实时率": ["实时率 RTF", "Real-time factor"],
  "监控.步频": ["物理步频", "Physics step rate"],
  "监控.内存": ["进程内存", "Process memory"],
  "监控.仿真时间": ["仿真时间", "Sim time"],
  "监控.墙钟": ["采样墙钟（仿真进程）", "Sampler wall clock (sim process)"],
  "监控.墙钟.提示": ["仿真进程启动后经过的墙钟时间，不是仿真时间；仿真时间见上一行。", "Wall-clock time since the simulation process started, not simulation time (see the row above)."],
  "监控.步长": ["物理步长", "Timestep"],
  "监控.插件数": ["已装插件", "Plugins"],
  "监控.说明": [
    "RTF = 仿真时间推进 ÷ 真实耗时，1.00 为实速；明显小于 1 说明算不过来。这些数由仿真进程采集，界面不自己估。",
    "RTF = sim time advanced ÷ wall clock; 1.00 is real time, well below 1 means it cannot keep up. These numbers are measured by the simulation process; the UI never estimates them.",
  ],
  "监控.冻结": ["仿真已暂停：RTF 与步频为 0 是预期值，点击“运行”后才有意义。", "Simulation is paused: an RTF and step rate of 0 is expected; click Run to make them meaningful."],
  "监控.无趋势": ["仿真进程每次只发瞬时值；历史趋势需要额外采样，当前不画假曲线。", "The simulation process sends instantaneous values only; historical trends would need extra sampling and are not faked here."],
  "监控.等待": ["等待数据", "waiting for data"],
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
  "步骤.帮助": ["帮助", "Help"],
  "步骤.帮助.一句话": ["快速上手、操作说明与注意事项", "Quick start, controls, and cautions"],
  "步骤.关于": ["关于", "About"],
  "步骤.关于.一句话": ["版本、运行环境、声明", "Version, runtime, notices"],

  // ---- 帮助 ----
  "帮助.快速标题": ["快速开始", "Quick start"],
  "帮助.新手": ["首次使用", "First run"],
  "帮助.快速.一": ["在“定义”页选择模型，并确认自由度和执行器数量。", "Select a model on Define and check its DoF and actuator count."],
  "帮助.快速.二": ["在“插件”页启用与模型兼容的控制算法。", "Enable a controller compatible with the model on Plugins."],
  "帮助.快速.三": ["用工作台顶部固定的“运行 / 暂停 / 复位”控制仿真。", "Use the persistent Run / Pause / Reset bar at the top of the workbench."],
  "帮助.快速.四": ["在“验证”和“监控”页检查曲线、参数、实时率与告警。", "Inspect curves, parameters, real-time factor, and warnings on Verify and Monitor."],
  "帮助.三维标题": ["3D 视口操作", "3D viewport controls"],
  "帮助.三维.旋转": ["左键拖动：旋转视角。", "Left-drag: orbit the camera."],
  "帮助.三维.平移": ["Shift + 左键拖动：平移视角。", "Shift + left-drag: pan the camera."],
  "帮助.三维.缩放": ["滚轮：缩放。", "Mouse wheel: zoom."],
  "帮助.三维.适配": ["双击或按 F / R：重新适配模型。", "Double-click or press F / R: fit the model in view."],
  "帮助.说明书标题": ["完整使用说明", "Full user guide"],
  "帮助.说明书说明": ["按钮说明、参数含义、典型流程和故障排查统一放在仓库说明书中。", "Button reference, parameter meanings, workflows, and troubleshooting are maintained in the repository guide."],
  "帮助.悬浮提示": ["日常使用时，把鼠标停在按钮、状态项或被截断的文字上，可查看一句话提示或完整内容。", "Hover over buttons, status fields, or truncated text for a one-line hint or the full value."],
  "帮助.注意标题": ["重要注意事项", "Important cautions"],
  "帮助.注意.暂停": ["程序默认暂停物理推进；模型不动不代表启动失败。", "Physics is paused by default; a stationary model does not mean startup failed."],
  "帮助.注意.模拟": ["部署页当前使用模拟设备后端，不代表已经连接真机。", "The Deploy page currently uses a simulated device backend; no real robot is connected."],
  "帮助.注意.急停": ["界面中的急停是软件请求，不能替代真机的物理急停回路。", "The on-screen E-stop is a software request and cannot replace a hardware E-stop circuit."],

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
  "中区.未接入": ["原生 3D 在宿主窗口右侧", "The native 3D view is the pane on the right"],
  "中区.未接入说明": [
    "三维视图是**真 MuJoCo 原生渲染**，由宿主窗口直接放在这一格的右侧（同级视图，不是网页里画的）。所以这里不重复画几何 —— 重复画会和真画面打架，而且网页侧重算正运动学会与物理漂移。",
    "The 3D view is **real native MuJoCo rendering**, placed by the host window directly to the right of this pane (a sibling view, not drawn in the page). So no geometry is drawn here — duplicating it would fight the real render, and recomputing kinematics in the page would drift from the physics.",
  ],
  "中区.操作提示": [
    "右侧 3D 区：拖拽=转视角 ／ 滚轮=缩放 ／ Shift+拖拽=平移 ／ R=复位 ／ F=适配",
    "In the 3D pane on the right: drag to orbit · scroll to zoom · Shift+drag to pan · R reset · F fit",
  ],
  "中区.不重算": [
    "前端不会按 URDF 自己重算正运动学 —— 那会与物理漂移，加载带自由关节的模型立刻露馅。",
    "The frontend does not recompute forward kinematics from the URDF — that drifts from the physics and falls apart the moment a model has free joints.",
  ],
  "中区.浮层": ["模型与关节状态", "Model and joint state"],
  "中区.接口就绪": ["视口接口已就位：{值}", "Viewport hook ready: {值}"],
  "中区.视口接口未就绪": ["视口接口尚未出现", "No viewport hook in the contract yet"],
  "仿真控制.标题": ["仿真控制", "Simulation controls"],
  "仿真控制.实验": ["实验", "Experiment"],
  "仿真控制.实验说明": ["选择已注册的完整实验", "Select a registered experiment"],
  "仿真控制.无实验": ["没有可用实验", "No experiments"],
  "仿真控制.未选择实验": ["未选择", "not selected"],
  "仿真控制.加载实验": ["加载", "Load"],
  "仿真控制.加载实验说明": ["加载实验声明的模型、项目、控制器和目标", "Load the experiment model, project, controller, and target"],
  "仿真控制.实验完成说明": ["实验已完成；复位或重新加载后才能再次开始", "Experiment completed; reset or reload before running again"],
  "仿真控制.等待": ["等待状态", "waiting"],
  "仿真控制.运行中": ["运行中", "running"],
  "仿真控制.已暂停": ["已暂停", "paused"],
  "仿真控制.运行": ["运行", "Run"],
  "仿真控制.暂停": ["暂停", "Pause"],
  "仿真控制.复位": ["复位", "Reset"],
  "仿真控制.运行说明": ["从当前状态继续推进 MuJoCo 仿真。", "Continue MuJoCo simulation from the current state."],
  "仿真控制.暂停说明": ["停在当前姿态；不改变 qpos，也不清零 data.time。", "Hold the current pose without changing qpos or clearing data.time."],
  "仿真控制.复位说明": ["恢复默认姿态，清零速度、控制量和 data.time，并重新初始化当前算法。", "Restore the default pose, clear velocity, controls and data.time, and reinitialize the current algorithms."],
  "仿真控制.重力开": ["重力：开", "Gravity: on"],
  "仿真控制.重力关": ["重力：关", "Gravity: off"],
  "仿真控制.重力说明": ["只切换模型重力，不启动、暂停或复位仿真。", "Toggle model gravity only; this does not run, pause, or reset the simulation."],
  "仿真控制.速度": ["速度", "Speed"],
  "仿真控制.速度说明": ["调整仿真相对真实时间的目标速度；不修改 MuJoCo 物理步长。实际速度请看底部实时倍率。", "Set the target simulation speed relative to wall time without changing the MuJoCo timestep. See RTF below for the achieved speed."],

  // ---- 控制台 ----
  "控制台.标题": ["控制台", "Console"],
  "控制台.页签.输出": ["输出", "Output"],
  "控制台.页签.事件": ["事件", "Events"],
  "控制台.页签.问题": ["问题", "Problems"],
  "控制台.页签.诊断": ["诊断", "Diagnostics"],
  "控制台.清空": ["清空", "Clear"],
  "控制台.清空不了": [
    "清空只影响显示；连接与命令的历史仍然留在后端。",
    "Clearing only affects this view; connection and command history stays in the backend.",
  ],
  "控制台.自动滚动": ["自动滚动", "Auto scroll"],
  "控制台.跟随.开": ["跟随最新", "Follow latest"],
  "控制台.跟随.关": ["已暂停跟随", "Follow paused"],
  "控制台.跟随.提示": [
    "新日志到达时自动滚到底部；向上滚动会暂停，点按钮恢复。",
    "Auto-scroll on new lines; scrolling up pauses it, click to resume.",
  ],
  "控制台.召回.提示": ["展开控制台（快捷键 ;）；徽标来自真实问题计数", "Expand console (shortcut ;); badges come from real problem counts"],
  "控制台.日志.插件": ["插件 {名}", "plugin {名}"],
  "控制台.日志.高亮关节": ["在 3D 中高亮 J{关节}", "Highlight J{关节} in 3D"],
  "控制台.日志.高亮失败": ["高亮命令失败：{说明}", "Highlight command failed: {说明}"],
  "控制台.召回.错误": ["错误 {数量}", "{数量} errors"],
  "控制台.召回.注意": ["注意 {数量}", "{数量} warnings"],
  "控制台.召回.无问题": ["无问题", "no problems"],
  "控制台.诊断.未运行": ["未运行", "not run"],
  "控制台.诊断.说明": ["真跑本机检查脚本，结果来自后端。", "Runs local checks; results come from the backend."],
  "控制台.诊断.运行": ["运行检查", "Run checks"],
  "控制台.诊断.运行中": ["检查中…", "running…"],
  "控制台.诊断.完整": ["打开完整诊断", "Open full diagnostics"],
  "控制台.诊断.空": ["还没有跑过诊断。", "No diagnostics run yet."],
  "控制台.诊断.通过": ["{通过}/{总数} 项通过", "{通过}/{总数} passed"],
  "控制台.筛选.全部": ["全部来源", "All sources"],
  "控制台.筛选.说明": ["只留下选中的来源", "Show only the selected sources"],
  "控制台.筛选.等级": ["等级", "Level"],
  "控制台.筛选.全部等级": ["全部等级", "All levels"],
  "控制台.筛选.来源": ["来源", "Source"],
  "控制台.筛选.插件": ["插件", "Plugin"],
  "控制台.筛选.全部插件": ["全部插件", "All plugins"],
  "控制台.筛选.主题": ["主题", "Topic"],
  "控制台.筛选.全部主题": ["全部主题", "All topics"],
  "控制台.筛选.时间": ["时间", "Time"],
  "控制台.筛选.空": ["当前筛选没有匹配的日志。", "No log lines match the current filters."],
  "控制台.筛选.全部时间": ["全部时间", "All time"],
  "控制台.时间.1": ["最近 1 分钟", "Last 1 min"],
  "控制台.时间.5": ["最近 5 分钟", "Last 5 min"],
  "控制台.时间.15": ["最近 15 分钟", "Last 15 min"],
  "控制台.复制": ["复制可见", "Copy"],
  "控制台.导出": ["导出", "Export"],
  "控制台.复制成功": ["已复制 {数量} 行日志", "Copied {数量} log lines"],
  "控制台.复制失败": ["复制失败：浏览器不允许访问剪贴板", "Copy failed: clipboard access was blocked"],
  "控制台.导出成功": ["已导出 {数量} 行日志", "Exported {数量} log lines"],
  "控制台.收起": ["收起控制台", "Collapse console"],
  "控制台.展开": ["展开控制台", "Expand console"],
  "控制台.速率.开关": ["主题速率", "Topic rates"],
  "控制台.速率.收起": ["收起主题速率", "Hide topic rates"],
  "控制台.等级.信息": ["信息", "info"],
  "控制台.等级.注意": ["注意", "warn"],
  "控制台.等级.错误": ["错误", "error"],
  "控制台.来源.连接": ["连接", "link"],
  "控制台.来源.握手": ["握手", "handshake"],
  "控制台.来源.回执": ["回执", "receipt"],
  "控制台.来源.错误": ["错误", "error"],
  "控制台.来源.前端": ["前端", "frontend"],
  "控制台.来源.控制台": ["控制台", "console"],
  "控制台.来源.规划": ["规划", "planning"],
  "控制台.来源.诊断": ["诊断", "diagnostics"],
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
  "问题.兼容性": ["有算法与当前模型不兼容", "An algorithm is incompatible with the current model"],
  "问题.兼容性.说明": [
    "装配报告里明确写了「不兼容」，本次没有启用该算法。原因、影响和下一步见「定义」页顶部的兼容性提示。",
    "The assembly report explicitly says “incompatible”, so that algorithm was not enabled. See the compatibility banner at the top of Define for cause, impact and next steps.",
  ],

  // ---- 状态栏 ----
  "状态栏.标题": ["状态栏", "Status bar"],
  "状态栏.实验": ["实验", "Experiment"],
  "状态栏.项目": ["项目", "Project"],
  "状态栏.模型": ["模型", "Model"],
  "状态栏.物理": ["仿真", "Sim"],
  "状态栏.仿真时间": ["仿真时间", "Sim time"],
  "状态栏.实时率": ["实时倍率", "RTF"],
  "状态栏.帧率": ["指标帧率", "Metric rate"],
  "状态栏.连接": ["后端", "Backend"],
  "状态栏.真机": ["真机", "Hardware"],
  "状态栏.真机.未接入": ["未接入", "not connected"],
  "状态栏.物理.开": ["运行中", "running"],
  "状态栏.物理.关": ["已暂停", "paused"],
  "状态栏.物理.未知": ["--", "--"],
  "状态栏.语言": ["语言", "Language"],
  "状态栏.切到": ["切到 {语}", "Switch to {语}"],
  "状态栏.皮肤": ["皮肤", "Skin"],
  "状态栏.提示.项目": ["当前项目名（来自 项目状态）", "Current project name (from project state)"],
  "状态栏.提示.模型": ["当前模型（来自 模型状态）", "Current model (from model state)"],
  "状态栏.提示.物理": [
    "仿真运行状态；请使用工作台顶部的 Run / Pause / Reset 控制，它不是真机急停",
    "Simulation run state; use Run / Pause / Reset at the top of the workbench. This is not a hardware e-stop.",
  ],
  "状态栏.提示.仿真时间": [
    "真实的 MuJoCo data.time（来自 仿真状态），不是连接后的墙钟时间",
    "The real MuJoCo data.time (from Simulation state), not wall-clock since the link came up",
  ],
  "状态栏.提示.实时率": [
    "系统.RTF = 仿真时间增量 ÷ 墙钟增量；1.00 为实速，明显小于 1 说明算不过来",
    "System.RTF = sim-time delta ÷ wall-clock delta; 1.00 is real time, well below 1 means it cannot keep up",
  ],
  "状态栏.提示.帧率": [
    "「指标」帧的实测到达速率（约等于曲线采样率）；不是 3D 渲染帧率（在 3D 工具栏上），也不是物理步频（见「监控」）",
    "Measured arrival rate of metric frames (≈ curve sampling rate); not the 3D render rate (shown on the 3D toolbar), nor the physics step rate (see Monitor)",
  ],
  "状态栏.提示.连接": [
    "与后端进程的 WebSocket 连接状态；它不代表真机已连接",
    "WebSocket link to the backend process; it does not mean hardware is connected",
  ],
  "状态栏.提示.真机": [
    "本软件没有真机传输层/设备抽象；这里始终是「未接入」，详见「部署」",
    "This software has no hardware transport or device abstraction; this is always “not connected” — see Deploy",
  ],

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
  "定义.自由度.提示": [
    "nq = 广义坐标数，也是关节自由度数；它回答「这台臂有几个可以动的关节」",
    "nq = number of generalized coordinates (joint DoF): how many joints can move",
  ],
  "定义.执行器数.提示": [
    "nu = 执行器数；扭矩模型通常 nq = nu，位置伺服或带夹爪的模型可能不等",
    "nu = actuator count; torque models usually have nq = nu, position-servo or gripper models may differ",
  ],
  "定义.nqnu.说明": [
    "nq 是关节自由度，nu 是执行器数；两者不等时，先确认算法是否要求 nq = nu。",
    "nq is joint DoF, nu is actuator count; when they differ, check whether the algorithm requires nq = nu.",
  ],
  "定义.模型状态": ["状态", "State"],
  "定义.加载耗时": ["上次加载耗时", "Last load"],
  "定义.模型文件": ["文件", "File"],
  "定义.复制路径": ["复制完整路径", "Copy full path"],
  "定义.复制成功": ["已复制", "Copied"],
  "定义.复制失败": ["复制失败", "Copy failed"],
  "定义.没模型": ["后端还没有报模型 —— 可能在启动，也可能没加载任何模型。", "The backend has not reported a model yet — it may still be starting, or none is loaded."],
  "定义.当前项目": ["当前项目", "Current project"],
  "定义.控制目标": ["关节控制目标", "Joint control target"],
  "定义.控制目标.说明": ["输入期望关节位置（转动关节单位 rad），再点击应用；目标由当前控制算法跟踪，界面不会直接写控制力。", "Enter desired joint positions (rad for revolute joints), then apply. The active controller tracks the target; the UI does not write actuator forces directly."],
  "定义.控制目标.来源": ["目标来源：{来源}", "Target source: {来源}"],
  "定义.控制目标.关节": ["关节 / 坐标", "Joint / coordinate"],
  "定义.控制目标.当前位置": ["当前位置", "Current"],
  "定义.控制目标.目标": ["目标（rad）", "Target (rad)"],
  "定义.控制目标.取当前": ["取当前位置", "Use current pose"],
  "定义.控制目标.应用": ["应用目标", "Apply target"],
  "定义.控制目标.无算法": ["无控制算法", "no controller"],
  "定义.控制目标.无关节": ["当前场景没有可输入目标的关节。请先加载机械臂模型。", "The current scene has no joints with editable targets. Load a robot model first."],
  "定义.控制目标.数值错误": ["关节目标必须全部是有效数值。", "All joint targets must be valid numbers."],
  "定义.项目名": ["项目", "Project"],
  "定义.算法组": ["挂载的算法", "Mounted algorithms"],
  "定义.算法数": ["算法数量", "Algorithm count"],
  "定义.算法数.短": ["{数量} 个算法", "{数量} algos"],
  "定义.控盘": ["在写 ctrl 的算法", "Writing ctrl"],
  "定义.被覆盖": ["输出被覆盖", "Outputs masked"],
  "定义.已存盘": ["算法组已写回项目文件", "Algorithm set saved to the project file"],
  "定义.装配报告": ["上次装配报告", "Last assembly report"],
  "定义.装配报告.空": ["没有装配报告。", "No assembly report."],
  "定义.装配报告.展开": ["查看装配报告", "View assembly report"],
  "定义.装配报告.收起": ["收起装配报告", "Hide assembly report"],
  "定义.算法状态.不兼容": ["与当前模型不兼容", "incompatible with this model"],
  "定义.算法状态.已挂": ["已挂载", "mounted"],
  "定义.兼容性": ["兼容性", "Compatibility"],
  "定义.兼容性.通过": ["未发现不兼容", "No incompatibility found"],
  "定义.兼容性.未评估": ["兼容性未评估", "compatibility not evaluated"],
  "定义.算法.未添加": ["尚未添加算法", "No algorithms added"],
  "定义.单位.说明": [
    "关节量单位（rad / m）由模型与算法定义；界面只显示数值，不擅自换算。",
    "Joint units (rad / m) are defined by the model and algorithm; the UI shows values without converting them.",
  ],
  "定义.算法.去插件": ["去「插件」启用算法", "Open Plugins"],
  "定义.算法.未添加说明": [
    "当前项目还没有挂载算法。可在下方「算法库」勾选，先临时应用验证，再保存到项目。",
    "No algorithm is mounted. Select one in the Algorithm library below, apply it temporarily, then save it to the project.",
  ],
  "定义.兼容性.标题": ["有算法与当前模型不兼容", "An algorithm is incompatible with the current model"],
  "定义.兼容性.影响": ["本次不启用该算法；其余算法照常装配。", "That algorithm is skipped; the rest are assembled normally."],
  "定义.兼容性.下一步": ["换用匹配的模型，或调整/停用该算法。", "Use a matching model, or adjust/disable that algorithm."],
  "定义.兼容性.查看": ["查看装配报告", "View assembly report"],
  "定义.兼容性.无": ["没有发现兼容性问题。", "No compatibility problems found."],
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
    "勾选只是在界面中准备修改；点击「临时应用」后才送到仿真，验证合适后再保存到项目。",
    "Checking only stages a change in the UI; Apply temporarily sends it to the simulation, and Save persists it after verification.",
  ],
  "定义.算法库.空": ["算法库里没有算法。", "The algorithm library is empty."],
  "定义.算法库.已挂": ["已挂", "mounted"],
  "定义.算法库.已生效": ["当前生效", "active"],
  "定义.算法库.待应用": ["有待应用修改", "changes staged"],
  "定义.算法库.未保存": ["未保存", "not saved"],
  "定义.算法库.待启用": ["待启用", "will enable"],
  "定义.算法库.待停用": ["待停用", "will disable"],
  "定义.算法库.临时应用": ["临时应用", "Apply temporarily"],
  "定义.算法库.保存": ["保存到项目", "Save to project"],
  "定义.算法库.保存并应用": ["应用并保存", "Apply and save"],
  "定义.算法库.恢复": ["撤销选择", "Discard changes"],
  "定义.算法库.临时应用说明": ["让所选算法立即参与当前仿真，但不修改项目文件。", "Use the selected algorithms now without changing the project file."],
  "定义.算法库.保存说明": ["将所选算法应用到当前仿真，并写入当前项目文件。", "Apply the selection and write it to the current project file."],
  "定义.算法库.无项目不能保存": ["当前没有项目，只能临时应用，不能保存。", "There is no current project; the selection can only be applied temporarily."],
  "定义.算法库.待应用说明": ["这些勾选尚未送入仿真；当前运行的仍是带“当前生效”标记的算法。", "These choices have not reached the simulation; algorithms marked active are still running."],
  "定义.算法库.未保存说明": ["当前算法已经在仿真中生效，但还没有写回项目文件。", "The algorithms are active in the simulation but have not been written to the project file."],
  "定义.算法库.已同步说明": ["界面选择、当前仿真和项目文件一致。", "The UI selection, running simulation, and project file are in sync."],
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
    "曲线由后端推送的指标生成；每条曲线的名字由算法声明（格式：算法名·指标名）。前端不加工、不外推。",
    "Curves come from metrics pushed by the backend; each name is declared by the algorithm (format: algorithm·metric). The frontend neither post-processes nor extrapolates.",
  ],
  "验证.最近更新": [
    "最近收到指标：{秒} 秒前",
    "Last metric: {秒} s ago",
  ],
  "验证.采集已暂停": ["仿真已暂停：曲线保留，不再增加点", "Simulation paused: curve retained; no new points"],
  "验证.从未收到": ["还没有收到任何指标帧", "No metric frame received yet"],
  "验证.单位说明": ["单位由算法在指标名里声明；没有声明就不显示。", "Units are declared by the algorithm in the metric name; if absent, none is shown."],
  "验证.去插件": ["去「插件」检查算法指标", "Check algorithm metrics under Plugins"],
  "验证.空原因": [
    "可能当前项目没有挂载算法，或算法没有提供指标。",
    "Maybe the current project has no algorithm mounted, or the algorithm does not provide metrics.",
  ],
  "验证.窗口": ["时间窗", "Window"],
  "验证.窗口.标签": ["时间窗", "Window"],
  "验证.窗口.值": ["当前保留最近 {值} 秒", "showing the last {值} s"],
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
  "曲线.空": ["尚无指标帧", "No metric frames yet"],
  "曲线.空提示": ["等待后端推送指标；或到「插件」检查算法是否实现指标。", "Waiting for metrics; or check under Plugins whether the algorithm implements metrics."],
  "曲线.轴值": ["指标值（单位由算法声明）", "value (unit declared by algorithm)"],
  "曲线.轴时间": ["墙钟（秒，0 = 最新一点）", "wall clock (s, 0 = newest point)"],
  "曲线.放大提示": ["滚轮缩放时间窗（{值} 秒）", "wheel zooms the window ({值} s)"],
  "曲线.说明": ["横轴用**墙钟**而不是仿真时间：物理暂停时仿真时间不动，曲线会挤成一坨。", "The x axis uses **wall clock**, not sim time: when physics is paused sim time freezes and the curve collapses into a spike."],

  // ---- 验证：参数表 ----
  "验证.参数": ["参数表（可编辑）", "Parameter table (editable)"],
  "验证.参数.说明": [
    "参数由当前挂载的算法声明；没有挂载算法就没有可调参数。",
    "Parameters are declared by the mounted algorithms; no algorithms means no tunables.",
  ],
  "验证.参数.可编辑": [
    "单击数值后输入；按 Enter 或点击别处应用，按 Esc 取消。范围与步长由算法声明，改动会写回当前项目。",
    "Click a value to edit; press Enter or click elsewhere to apply, and Escape to cancel. Bounds and step are declared by the algorithm; changes are saved to the current project.",
  ],
  "验证.参数.输入提示": ["编辑后按 Enter 或点击别处应用；Esc 取消", "Press Enter or click elsewhere to apply; Escape cancels"],
  "验证.参数.数值错误": ["请输入有效数字；本次修改没有提交。", "Enter a valid number; the change was not submitted."],
  "验证.参数.空": ["当前没有可调参数：可能没有挂载算法，或算法没有声明参数。", "No tunables right now: perhaps no algorithm is mounted, or none declares parameters."],
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
    "采样时长会发给后端；以后端回执为准。",
    "The sample duration is sent to the backend; its receipt is authoritative.",
  ],
  "辨识.尚无状态": ["尚无状态", "no state yet"],
  "辨识.等待开始": [
    "还没有开始辨识。点「开始辨识」后，这里会显示采样进度、结果和拟合。",
    "Identification has not started. After you press Start, sampling progress, results and fit will appear here.",
  ],
  "辨识.没结果": ["还没有结果。完成一次辨识后，这里会列出参数与变化。", "No results yet. After one run, parameters and changes appear here."],
  "辨识.没拟合": ["还没有拟合数据。完成一次辨识后，这里会显示残差对比。", "No fit data yet. After one run, the residual comparison appears here."],
  "辨识.停止条件": ["只有正在采样/辨识时才能停止", "Stop is available only while sampling/identifying"],
  "辨识.导出": ["导出结果（JSON）", "Export result (JSON)"],
  "辨识.没状态": ["后端还没有报辨识状态。", "The backend has not reported identification state yet."],
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
    "{数量} 套界面皮肤。点一下立即应用，下次打开仍会保留。",
    "{数量} interface skins. One click applies immediately and the choice is remembered next time.",
  ],
  "外观.高级": ["高级信息（开发者）", "Advanced (developer)"],
  "外观.高级说明": [
    "皮肤定义来自 软件/风格表.json，生成前端主题；选择写在浏览器本地存储里。普通使用不需要看这些。",
    "Skin definitions live in 软件/风格表.json and are generated into the frontend theme; the choice is stored in browser local storage. Normal use does not need this.",
  ],
  "外观.语言当前": ["当前界面语言：{语}", "Current UI language: {语}"],
  "外观.当前": ["当前", "current"],
  "外观.语言": ["语言", "Language"],
  "外观.语言说明": [
    "语言切换后立即生效，并会记住。",
    "The language applies immediately and is remembered.",
  ],
  "外观.快捷键": [
    "皮肤切换是纯前端偏好，不会改变仿真或项目数据。",
    "Switching skins is a frontend preference; it does not change the simulation or project data.",
  ],

  // ---- 关于视图 ----
  "关于.标题": ["关于", "About"],
  "关于.名称": ["名称", "Name"],
  "关于.版本": ["软件版本", "Software version"],
  "关于.契约版本": ["契约版本 / 协议版本", "Contract / protocol version"],
  "关于.软件": ["软件", "Software"],
  "关于.构建": ["构建", "Build"],
  "关于.构建值": ["本地源码运行（无打包版本号）", "local source (no packaged build number)"],
  "关于.许可证与第三方": ["许可证与第三方", "License & third-party"],
  "关于.许可证": ["许可证", "License"],
  "关于.第三方": ["第三方组件", "Third-party components"],
  "关于.第三方值": ["MuJoCo（Apache-2.0）· React（MIT）· Vite（MIT）· Tailwind CSS（MIT）", "MuJoCo (Apache-2.0) · React (MIT) · Vite (MIT) · Tailwind CSS (MIT)"],
  "关于.开发信息": ["开发信息（契约 / 握手 / 帧序号）", "Developer info (contract / handshake / frame seq)"],
  "关于.开发说明": ["以下字段面向开发与排障，普通使用不需要展开。", "The fields below are for development and troubleshooting; normal use does not need them."],
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
  "关于.声明三": ["界面只显示后端推送的状态；不直接读文件、不直接调用平台 API。", "The UI only displays state pushed by the backend; it does not read files or call platform APIs directly."],
  "关于.声明四": ["模型资产各自保留原许可，详见 模型/ 下各目录的 LICENSE。", "Bundled model assets keep their upstream licenses; see the LICENSE files under 模型/."],

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
  "日志.规划失败": ["规划失败：{原因}", "Planning failed: {原因}"],
  "日志.规划估算": ["规划使用估算限位（{来源}）；瓶颈关节 {关节}", "Planning used estimated limits ({来源}); bottleneck joint {关节}"],
  "日志.诊断未通过": ["诊断 {通过}/{总数} 未通过", "Diagnostics {通过}/{总数} failed"],
  "日志.诊断出错": ["诊断出错：{说明}", "Diagnostics error: {说明}"],

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
  const 替换后 = !参
    ? 条
    : 条.replace(/\{([^}]+)\}/g, (整, 名: string) => {
        const 值 = 参[名];
        return 值 === undefined ? 整 : String(值);
      });
  // 文案表是从报告/文档里长出来的，里面夹着 Markdown 的 **粗体** 和 `代码` 标记。
  // 网页层没有 Markdown 渲染器，直接显示这些标记会让普通用户看到 `**` 和反引号
  // （工程师截图里点名的就是这类"排版符号泄漏"）。在**唯一出口**把它们去掉，
  // 保证所有页面、title、日志都不会再漏出原始标记；强调靠字号/颜色/层级表达。
  return 替换后.replace(/\*\*/g, "").replace(/`/g, "");
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
