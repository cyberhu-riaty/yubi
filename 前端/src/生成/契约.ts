// ⚠️ 本文件由 `工具/生成前端资产.py` 生成，**不要手改**。
// 来源：`软件/契约.py`（后端与前端之间唯一的通信契约）。
// 改了契约就跑一次生成；`工具/验证/契约自检.py` 会检查它有没有过期。

export const 契约版本 = 21;
export const 协议版本 = 21;

// ---------------- 下行：仿真 → 界面 ----------------
export type 下行主题名 =
    "指标"
  | "parameter.table"
  | "parameter.updated"
  | "辨识状态"
  | "model.state"
  | "设备连接"
  | "告警"
  | "parameter.transaction"
  | "planning.result"
  | "部署"
  | "插件目录"
  | "诊断"
  | "系统"
  | "simulation.state"
  | "experiment.state"
  | "控制状态"
  | "model.library"
  | "project.state"
  ;

/** 插件 指标() 报上来的实时数值，曲线的数据源（30 Hz 限频） */
export interface 下行_指标 {
  /** 仿真时间（秒） */
  时间: number;
  /** 真实时间（秒），画曲线用它做横轴更平稳 */
  墙钟: number;
  /** {指标名: 数值}，指标名形如「插件名·键名」 */
  数值: Record<string, number>;
}

/** 当前已装算法声明的可调参数（10 Hz 限频） */
export interface 下行_parameter_table {
  /** {全名: 参数项}，全名 = 「插件名·参数名」。参数项的形状见下：
  {plugin, plugin_english, plugin_version, parameter, value, range, step, unit}
★ 这份形状是从 `parameter_bridge.collect_parameters()` 的真实产物核对的：
  早期契约里写成 {值,最小,最大} —— 那是**按想象写的**，与实现不符，
  后果是前端把 `范围` 数组当成对象逐字符渲染，表格里出现一堆 0=N 1=· 的乱码。
  这正是「契约必须对着实现自证」的理由：`工具/验证/契约自检.py` 现在会
  用真实插件的 `adjustable_parameters()` 产出核对本字段的形状。 */
  parameters: Record<string, unknown>;
}

/** 参数被改动后的回执（界面照它更新控件） */
export interface 下行_parameter_updated {
  /** {full parameter name: new value} */
  updates: Record<string, unknown>;
}

/** 参数辨识的进度与结果（5 Hz 限频） */
export interface 下行_辨识状态 {
  /** 空闲 / 采样中 / 辨识中 / 完成 / 出错 */
  状态: string;
  /** 给人看的进度描述 */
  进度: string;
  /** 已采样步数 */
  采样步数: number;
  /** 辨识出的参数列表 */
  结果: Record<string, unknown>[];
  /** 拟合改善情况 */
  拟合: Record<string, unknown>;
  /** 耗时（秒） */
  耗时: number;
  /** 过程日志 */
  日志: string[];
}

/** 当前加载的模型（2 Hz 限频） */
export interface 下行_model_state {
  /** 相对包根或绝对路径 */
  current_path: string;
  /** 给人看的型号名 */
  current_display_name: string;
  /** nq */
  dof: number;
  /** nu */
  actuator_count: number;
  /** 就绪 / ✓ … / ✗ … */
  status: string;
  /** 上次加载耗时（秒） */
  duration_s: number;
}

/** 设备链路的状态机/劣化参数/实测遥测/审计（当前只有模拟后端，不是真机） */
export interface 下行_设备连接 {
  /** 后端名字。**永远显示它**，避免把模拟当成真机 */
  后端: string;
  已连接: boolean;
  /** 未连接/已连接（未使能）/使能中/运行/停止/故障/急停 */
  安全状态: string;
  /** 空闲/位置/速度/力矩/阻尼/急停 */
  模式: string;
  自由度: number;
  /** 注入值 */
  延迟毫秒: number;
  /** 注入值 */
  抖动毫秒: number;
  /** 注入值 0..1 */
  丢包率: number;
  /** 量化步长，0=不量化 */
  编码器分辨率: number;
  /** 毫秒，来自真实帧时间戳差 */
  实测平均延迟: number;
  /** 毫秒 */
  实测最大延迟: number;
  /** 后端统计 */
  丢包数: number;
  错序数: number;
  /** 安全层拒绝的命令数 */
  拒绝数: number;
  /** 空 = 还没有状态帧（不是 0） */
  最近位置: number[];
  /** 最近 30 条：{时刻, 类别, 内容, 错误码} */
  审计: Record<string, unknown>[];
  说明: string;
}

/** 当前**活动**的病态告警（含量化证据与经验建议） */
export interface 下行_告警 {
  /** 每项：{类型, 严重度, 信号, 开始秒, 结束秒, 证据, 建议, 曲线[], 曲线t[]} */
  活动: Record<string, unknown>[];
  /** 本次会话累计检出过多少条 */
  已检出: number;
}

/** 批量改参数的结果：要么全提交，要么全回滚（不会有「改了一半」） */
export interface 下行_parameter_transaction {
  /** idle / committed / rolled_back */
  state: string;
  success_count: number;
  failure_count: number;
  timestamp: string;
  /** 每项：{full_name, old_value, new_value} */
  changes: Record<string, unknown>[];
  /** 逐条失败原因 */
  failures: string[];
  /** 给人看的一句话 */
  description: string;
}

/** 关节航点轨迹规划的结果与校验（终端速度/余量/瓶颈/包络） */
export interface 下行_planning_result {
  /** idle / planning / completed / failed */
  status: string;
  /** 参与规划的航点数 */
  waypoint_count: number;
  /** n */
  dof: number;
  /** 秒 */
  duration_s: number;
  /** 关节空间弧长 rad */
  path_length: number;
  /** rad/s */
  max_joint_velocity: number;
  /** rad/s² */
  max_joint_acceleration: number;
  /** rad/s³（只校验不整形） */
  max_joint_jerk: number;
  /** 1 - max(|qd|/vlim)，负数=超限 */
  velocity_margin: number;
  /** 同上 */
  acceleration_margin: number;
  /** 同上 */
  jerk_margin: number;
  /** 必须≈0 */
  terminal_velocity: number;
  /** rad */
  smoothing_deviation: number;
  /** -1 = 无 */
  bottleneck_joint: number;
  /** 速度 / 加速度 / 加加速度 */
  bottleneck_type: string;
  /** s ∈ [0,1] */
  bottleneck_position: number;
  /** ∫ds/v_max，纯理论下界 */
  optimal_lower_bound: number;
  /** 实际时长 / 下界 */
  actual_to_lower_bound: number;
  /** 显式 / 估算（估算会写明） */
  limit_source: string;
  timestamp: string;
  /** 失败原因（空 = 正常） */
  reason: string;
  /** 同一路径换约束重规划后的对比 */
  comparison: unknown;
  /** 笛卡尔输入的逆解说明；空 = 关节输入 */
  inverse_kinematics: string;
  /** 离线产物目录（输出/05_轨迹/…，空 = 没存） */
  output_path: string;
  /** idle / running / completed / interrupted */
  execution_status: string;
  /** 0..1 */
  execution_progress: number;
  /** v_s_max(s) 采样（≤200 点） */
  envelope: number[];
  /** 对应的 s */
  path_axis: number[];
  /** 实际 sd(s) */
  speed_axis: number[];
}

/** 部署包导出状态（导出的是文件，**不是**真机连接） */
export interface 下行_部署 {
  /** 空闲 / 导出中 / ✓ 完成 / ✗ 失败 */
  状态: string;
  /** 导出到哪 */
  目录: string;
  /** 几个文件 */
  文件数: number;
  /** 总字节 */
  字节: number;
  /** 几点导出的 */
  时间: string;
  /** 每项：{文件, 说明, 字节} */
  清单: Record<string, unknown>[];
  /** 给人看的一句话 */
  说明: string;
  /** 失败原因（空 = 正常） */
  出错: string;
}

/** 本机算法库里的插件清单（含版本/说明/作者/被哪些项目用到） */
export interface 下行_插件目录 {
  /** 共几个 */
  数量: number;
  /** 每项：{插件, 分组, 名称, 版本, 说明, 作者, 文件, 被项目使用[], 当前启用} */
  插件: Record<string, unknown>[];
  /** 扫描失败时的说明（空 = 正常） */
  说明: string;
}

/** 自检结果：10 套断言逐条报（真跑 工具/验证 下的脚本） */
export interface 下行_诊断 {
  /** 正在检查（界面据此把按钮变成检查中） */
  运行中: boolean;
  /** 通过了多少套 */
  通过: number;
  /** 一共跑了多少套 */
  总数: number;
  /** 总耗时 */
  耗时秒: number;
  /** 哪天几点跑的 */
  时间: string;
  /** 每项：{名, 通过, 说明, 秒} */
  项: Record<string, unknown>[];
  /** 跑不起来时的说明（空 = 正常） */
  出错: string;
}

/** 运行期系统指标（1 Hz）：实时率、步频、内存 —— 监控视图的数据源 */
export interface 下行_系统 {
  /** 累计仿真时间（秒） */
  仿真时间: number;
  /** 累计墙钟（秒，从开始跑算） */
  墙钟: number;
  /** 实时率 = 仿真时间增量/墙钟增量（1.0 = 实速） */
  RTF: number;
  /** 物理步/秒 */
  步频: number;
  /** 模型的 timestep（秒） */
  仿真步长: number;
  /** 本进程常驻内存 */
  内存MB: number;
  /** 当前装了几个插件 */
  插件数: number;
  /** 采样失败时的说明（空 = 正常） */
  出错: string;
}

/** 全局仿真运行状态：运行/暂停、data.time、复位次数与目标速度 */
export interface 下行_simulation_state {
  /** running / paused */
  state: string;
  /** 是否使用模型 XML 中的重力；与运行/暂停相互独立 */
  gravity_enabled: boolean;
  /** MuJoCo data.time（秒） */
  simulation_time: number;
  /** 本次会话执行 Reset 的累计次数 */
  reset_count: number;
  /** 目标墙钟速度；实际达到值以系统.RTF为准 */
  speed_multiplier: number;
  /** 最近一次运行控制动作 */
  description: string;
}

/** 当前实验、可选实验、运行进度与自动导出结果 */
export interface 下行_experiment_state {
  /** 当前实验注册名；空表示未选择 */
  current: string;
  /** 当前实验显示名 */
  name: string;
  /** not_selected / loaded / running / paused / completed / failed */
  status: string;
  /** 每项：{key,name,model,project,controllers[],duration_s,description} */
  available: Record<string, unknown>[];
  /** 实验声明的模型路径 */
  model: string;
  /** 实验声明的项目 */
  project: string;
  /** 实验声明的控制器注册名 */
  controllers: string[];
  /** 本次实验的仿真时长 */
  duration_s: number;
  /** 从本次点击开始累计的仿真时间 */
  elapsed_s: number;
  /** 自动导出完成后的目录 */
  result_directory: string;
  /** 最近一次实验操作说明 */
  description: string;
}

/** 关节目标输入区的数据源：当前位置、速度、控制量与已接受目标 */
export interface 下行_控制状态 {
  /** 与 qpos 顺序对应的关节/坐标名称 */
  关节名: string[];
  /** data.qpos */
  当前位置: number[];
  /** data.qvel */
  当前速度: number[];
  /** data.ctrl */
  当前控制: number[];
  /** 当前已接受的关节目标 */
  目标: number[];
  /** 当前位置 / 手动输入 */
  目标来源: string;
  /** 最近一次目标处理结果 */
  说明: string;
}

/** 可选模型清单（资产库视图）—— 与「模型状态」区分：那是当前装的哪台 */
export interface 下行_model_library {
  /** 共几台 */
  count: number;
  /** 每项：{id, display_name, category, dof, actuator_count, license, controllable, path}；路径是可直接加载的那个文件 */
  models: Record<string, unknown>[];
}

/** 当前项目 + 挂了哪些算法 + 重力设置（方案 C 的核心状态） */
export interface 下行_project_state {
  /** 项目名（空 = 没有对应项目） */
  project: string;
  model_path: string;
  model_display_name: string;
  /** 已装配算法元信息 */
  algorithms: Record<string, unknown>[];
  /** 上次装配的逐行说明 */
  report: string[];
  /** 算法库里可选的算法名 */
  algorithm_library: string[];
  /** 当前算法组是否已写回项目文件 */
  saved: boolean;
  /** 谁在写 ctrl[:]（抢方向盘提示） */
  active_controller: string;
  /** 输出被覆盖的算法名 */
  overridden_controllers: string[];
  /** 是否启用模型重力；不代表仿真是否运行 */
  gravity_enabled: boolean;
}

export interface 下行负载表 {
  "指标": 下行_指标;
  "parameter.table": 下行_parameter_table;
  "parameter.updated": 下行_parameter_updated;
  "辨识状态": 下行_辨识状态;
  "model.state": 下行_model_state;
  "设备连接": 下行_设备连接;
  "告警": 下行_告警;
  "parameter.transaction": 下行_parameter_transaction;
  "planning.result": 下行_planning_result;
  "部署": 下行_部署;
  "插件目录": 下行_插件目录;
  "诊断": 下行_诊断;
  "系统": 下行_系统;
  "simulation.state": 下行_simulation_state;
  "experiment.state": 下行_experiment_state;
  "控制状态": 下行_控制状态;
  "model.library": 下行_model_library;
  "project.state": 下行_project_state;
}

// ---------------- 上行：界面 → 仿真（命令） ----------------
export type 上行主题名 =
    "command.parameter_transaction"
  | "command.planning"
  | "命令.部署"
  | "命令.诊断"
  | "命令.设备"
  | "命令.高亮"
  | "command.gravity"
  | "command.simulation"
  | "command.experiment"
  | "命令.控制目标"
  | "command.model"
  | "command.algorithms"
  | "命令.辨识"
  | "command.parameters"
  | "命令.录制"
  ;

/** 一次性应用一组参数（预检不过就一个都不改） */
export interface 上行_command_parameter_transaction {
  /** apply */
  action: string;
  /** 每项 {full_name, value} */
  parameters: Record<string, unknown>[];
}

/** 对已记录的关节航点跑一次规划 */
export interface 上行_command_planning {
  /** plan / record_waypoint / clear_waypoints / load_waypoints */
  action: string;
  /** 直接给航点（每项是一组关节角）。给了就用它，不给就用已记录的 */
  waypoints: Record<string, unknown>[];
  /** 每项 {xyz: [x,y,z]}，单位米。给了就先做逆解；**只支持位置，姿态未实现** */
  cartesian_waypoints: Record<string, unknown>[];
  /** rad/s（不给则从模型估算） */
  velocity_limits: number[];
  /** rad/s²（不给则 4×速度） */
  acceleration_limits: number[];
  /** rad/s³（不给则 20×加速度） */
  jerk_limits: number[];
  /** s 上离散点数，默认 2000 */
  grid_size: number;
  /** 0 = 不平滑 */
  smoothing_iterations: number;
  /** ≤0.49 */
  smoothing_factor: number;
  /** rad */
  deviation_tolerance: number;
}

/** 导出一个部署包（只拷源码与配置，不含模型本体） */
export interface 上行_命令_部署 {
  /** 导出（目前只认这个） */
  动作: string;
}

/** 跑一遍自检（10 套断言真跑） */
export interface 上行_命令_诊断 {
  /** 运行 / 空闲（目前只认运行） */
  动作: string;
}

/** 设备链路控制：打开/使能/进运行/停止/急停/设劣化/演练断线/导出审计 */
export interface 上行_命令_设备 {
  /** 打开 / 使能 / 进运行 / 停止 / 急停 / 设劣化 / 演练断线 / 导出审计 */
  动作: string;
  /** <0 = 不改 */
  延迟毫秒: number;
  /** <0 = 不改 */
  抖动毫秒: number;
  /** 0..1，<0 = 不改 */
  丢包率: number;
  /** <0 = 不改 */
  编码器分辨率: number;
}

/** 在 3D 视口高亮一个关节（视觉诊断；不改变物理/模型） */
export interface 上行_命令_高亮 {
  /** 关节索引；-1 = 清除高亮 */
  关节: number;
  /** 持续时间（秒），后端夹到 0..60 */
  秒: number;
}

/** 物理总闸：True = 推进物理（重力生效），False = 冻结在默认位置 */
export interface 上行_command_gravity {
  gravity_enabled: boolean;
}

/** 全局仿真控制：运行、暂停、复位或设置墙钟速度倍率 */
export interface 上行_command_simulation {
  /** run / pause / reset / speed */
  action: string;
  /** 0.25..4；只调整墙钟节拍，不修改 timestep */
  speed_multiplier: number;
}

/** 按注册名加载实验；Run/Pause/Reset 继续复用全局仿真控制 */
export interface 上行_command_experiment {
  /** load */
  action: string;
  /** ExperimentRegistry 中的注册名 */
  experiment: string;
}

/** 设置一组关节位置目标；由当前控制算法决定如何跟踪，不直接写 data.ctrl */
export interface 上行_命令_控制目标 {
  /** 按 qpos 顺序，转动关节单位 rad */
  目标: number[];
}

/** 切换机械臂（会连带按项目重新装配算法） */
export interface 上行_command_model {
  /** 模型路径（相对包根或绝对） */
  path: string;
  /** 可留空 */
  display_name: string;
}

/** 换一组控制算法（等价于点【Algorithms】面板的 Apply） */
export interface 上行_command_algorithms {
  /** [{plugin: 名字}] */
  algorithms: Record<string, unknown>[];
  /** 是否写回项目文件 */
  persist: boolean;
  reset_pose: boolean;
}

/** 开始/停止参数辨识 */
export interface 上行_命令_辨识 {
  /** 开始 / 停止 */
  动作: string;
  /** 采样时长（秒） */
  时长: number;
}

/** 改一个或多个算法参数（等价于在【Controller params】面板拖滑杆） */
export interface 上行_command_parameters {
  /** {全名: 新值}，全名必须是参数表里的键（形如「插件名·参数名」）。★ 为什么它不是普通命令而是快照语义：官方那条通道本来就是 latest-wins，拖滑杆会连发很多条，照旧沿用才不会出现「排队抖动」。 */
  updates: Record<string, number>;
}

/** 数据录制的开始/停止/回放 */
export interface 上行_命令_录制 {
  /** 开始 / 停止 / 回放 */
  动作: string;
  /** 采样频率（Hz） */
  频率: number;
  备注: string;
}

export interface 上行负载表 {
  "command.parameter_transaction": 上行_command_parameter_transaction;
  "command.planning": 上行_command_planning;
  "命令.部署": 上行_命令_部署;
  "命令.诊断": 上行_命令_诊断;
  "命令.设备": 上行_命令_设备;
  "命令.高亮": 上行_命令_高亮;
  "command.gravity": 上行_command_gravity;
  "command.simulation": 上行_command_simulation;
  "command.experiment": 上行_command_experiment;
  "命令.控制目标": 上行_命令_控制目标;
  "command.model": 上行_command_model;
  "command.algorithms": 上行_command_algorithms;
  "命令.辨识": 上行_命令_辨识;
  "command.parameters": 上行_command_parameters;
  "命令.录制": 上行_命令_录制;
}

// ---------------- 元信息 ----------------
export interface 主题元 {
  名: string;
  类名: string;
  种类: string;
  摘要: string;
}

export const 下行元: 主题元[] = [
  { 名: "指标", 类名: "指标消息", 种类: "快照", 摘要: "插件 指标() 报上来的实时数值，曲线的数据源（30 Hz 限频）" },
  { 名: "parameter.table", 类名: "ParameterTable", 种类: "快照", 摘要: "当前已装算法声明的可调参数（10 Hz 限频）" },
  { 名: "parameter.updated", 类名: "ParameterUpdate", 种类: "快照", 摘要: "参数被改动后的回执（界面照它更新控件）" },
  { 名: "辨识状态", 类名: "辨识状态", 种类: "快照", 摘要: "参数辨识的进度与结果（5 Hz 限频）" },
  { 名: "model.state", 类名: "ModelState", 种类: "快照", 摘要: "当前加载的模型（2 Hz 限频）" },
  { 名: "设备连接", 类名: "连接状态", 种类: "快照", 摘要: "设备链路的状态机/劣化参数/实测遥测/审计（当前只有模拟后端，不是真机）" },
  { 名: "告警", 类名: "告警消息", 种类: "快照", 摘要: "当前**活动**的病态告警（含量化证据与经验建议）" },
  { 名: "parameter.transaction", 类名: "ParameterTransactionResult", 种类: "快照", 摘要: "批量改参数的结果：要么全提交，要么全回滚（不会有「改了一半」）" },
  { 名: "planning.result", 类名: "PlanningResult", 种类: "快照", 摘要: "关节航点轨迹规划的结果与校验（终端速度/余量/瓶颈/包络）" },
  { 名: "部署", 类名: "部署状态", 种类: "快照", 摘要: "部署包导出状态（导出的是文件，**不是**真机连接）" },
  { 名: "插件目录", 类名: "插件目录", 种类: "快照", 摘要: "本机算法库里的插件清单（含版本/说明/作者/被哪些项目用到）" },
  { 名: "诊断", 类名: "诊断报告", 种类: "快照", 摘要: "自检结果：10 套断言逐条报（真跑 工具/验证 下的脚本）" },
  { 名: "系统", 类名: "系统状态", 种类: "快照", 摘要: "运行期系统指标（1 Hz）：实时率、步频、内存 —— 监控视图的数据源" },
  { 名: "simulation.state", 类名: "SimulationState", 种类: "快照", 摘要: "全局仿真运行状态：运行/暂停、data.time、复位次数与目标速度" },
  { 名: "experiment.state", 类名: "ExperimentState", 种类: "快照", 摘要: "当前实验、可选实验、运行进度与自动导出结果" },
  { 名: "控制状态", 类名: "控制状态", 种类: "快照", 摘要: "关节目标输入区的数据源：当前位置、速度、控制量与已接受目标" },
  { 名: "model.library", 类名: "AssetLibrary", 种类: "快照", 摘要: "可选模型清单（资产库视图）—— 与「模型状态」区分：那是当前装的哪台" },
  { 名: "project.state", 类名: "ProjectState", 种类: "快照", 摘要: "当前项目 + 挂了哪些算法 + 重力设置（方案 C 的核心状态）" },
];

export const 上行元: 主题元[] = [
  { 名: "command.parameter_transaction", 类名: "ParameterTransactionCommand", 种类: "快照", 摘要: "一次性应用一组参数（预检不过就一个都不改）" },
  { 名: "command.planning", 类名: "PlanningCommand", 种类: "快照", 摘要: "对已记录的关节航点跑一次规划" },
  { 名: "命令.部署", 类名: "部署命令", 种类: "快照", 摘要: "导出一个部署包（只拷源码与配置，不含模型本体）" },
  { 名: "命令.诊断", 类名: "诊断命令", 种类: "快照", 摘要: "跑一遍自检（10 套断言真跑）" },
  { 名: "命令.设备", 类名: "连接命令", 种类: "快照", 摘要: "设备链路控制：打开/使能/进运行/停止/急停/设劣化/演练断线/导出审计" },
  { 名: "命令.高亮", 类名: "高亮命令", 种类: "快照", 摘要: "在 3D 视口高亮一个关节（视觉诊断；不改变物理/模型）" },
  { 名: "command.gravity", 类名: "GravityState", 种类: "快照", 摘要: "物理总闸：True = 推进物理（重力生效），False = 冻结在默认位置" },
  { 名: "command.simulation", 类名: "SimulationControlCommand", 种类: "命令", 摘要: "全局仿真控制：运行、暂停、复位或设置墙钟速度倍率" },
  { 名: "command.experiment", 类名: "ExperimentCommand", 种类: "命令", 摘要: "按注册名加载实验；Run/Pause/Reset 继续复用全局仿真控制" },
  { 名: "命令.控制目标", 类名: "控制目标命令", 种类: "命令", 摘要: "设置一组关节位置目标；由当前控制算法决定如何跟踪，不直接写 data.ctrl" },
  { 名: "command.model", 类名: "SwitchModelCommand", 种类: "命令", 摘要: "切换机械臂（会连带按项目重新装配算法）" },
  { 名: "command.algorithms", 类名: "ApplyAlgorithmsCommand", 种类: "命令", 摘要: "换一组控制算法（等价于点【Algorithms】面板的 Apply）" },
  { 名: "命令.辨识", 类名: "辨识命令", 种类: "命令", 摘要: "开始/停止参数辨识" },
  { 名: "command.parameters", 类名: "ParameterUpdate", 种类: "快照", 摘要: "改一个或多个算法参数（等价于在【Controller params】面板拖滑杆）" },
  { 名: "命令.录制", 类名: "录制命令", 种类: "命令", 摘要: "数据录制的开始/停止/回放" },
];
