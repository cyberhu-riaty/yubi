"""
contract.py —— 界面与仿真之间**唯一**的通信契约（L0）

它解决什么问题：
    在 P0 之前，"界面看到什么"这件事散落在 7 个桥接层里：`指标桥.py` 定义 `指标消息`、
    `参数桥.py` 定义 `参数表消息`……每个桥自己知道字段，别人只能去读源码。
    一旦界面换成 Web（另一门语言、另一套类型），这种"契约散落"就会立刻变成
    **前后端字段对不上、而且要靠人肉核对**的经典事故。

    本模块把契约**收敛成一份**：谁要发消息、谁要收命令，都得先在这里登记。
    于是三方（Python 发出方 / Python 命令处理方 / 前端生成的类型）都从这一份派生。

设计约束：
    ① **单一事实来源，但要可自证**。字段是手写的，手写就会漂移 —— 所以
       `工具/验证/契约自检.py` 会拿**真实 dataclass 的字段**与本表逐项比对，
       不一致就报错。契约不是文档，是**可机检的不变量**（沿用本项目既有的工程纪律）。
    ② **Python 侧不引入新依赖**。只用标准库（dataclasses / typing），
       不引 pydantic 之类 —— 这个软件要能离线重建 `.venv`。
    ③ **前端可以零依赖地拿到契约**。通过 `/api/contract` 与 WebSocket 握手消息下发，
       前端不靠"抄一遍字段名"，而是靠生成/校验。

字段类型用这几个记号（前端据此生成 TS 类型）：
    "number" | "string" | "boolean" | "any"
    "number[]" / "string[]" / "object[]"
    "record<number>"  = {[键: string]: number}   （指标表、参数值表）
    "record<any>"     = {[键: string]: any}
"""
from __future__ import annotations

import dataclasses
from typing import Any

# 契约版本：**字段有增删改就必须递增**（前端据此判断要不要提示刷新）
#   2（2026-10-16）：补 `命令.改参数`；并把「参数表」里 `参数` 项的真实形状写进说明
#                    （原来写成 {值,最小,最大} 是按想象写的，与实现不符）。
#   3（2026-10-17）：P4 起步，补「资产库」（可选模型清单）。
#   4（2026-10-17）：补「系统」（RTF/步频/内存，监控视图的数据源）。
#   5（2026-10-17）：补「诊断」+「命令.诊断」（把 10 套断言搬进界面）。
#   6（2026-10-17）：补「插件目录」（本机算法库清单 + 元信息）。
#   7（2026-10-17）：补「部署」+「命令.部署」（导出可带走的部署包）。
#   8（2026-10-17）：补「规划结果」+「命令.规划」（关节航点轨迹规划）。
#   9（2026-10-17）：补「参数事务」+「命令.参数事务」（全成功或全回滚）。
#  10（2026-10-18）：补「命令.高亮」——日志/诊断里的关节警告在 3D 中定位（不动物理）。
#  11（2026-10-19）：补「告警」——病态检出（振荡/发散/跟踪超差/饱和）。
#  12（2026-10-20）：补「设备连接」+「命令.设备」——模拟后端/安全状态/遥测/审计。
#  13（2026-10-26）：补「仿真状态」+「命令.仿真」—— Run/Pause/Reset 分离。
#  14（2026-10-29）：运行/重力彻底分离；补关节控制目标与实时控制状态。
#  15（2026-10-29）：补「实验状态」+「命令.实验」—— GUI 可选择并完整运行注册实验。
#  16（2026-10-30）：补仿真速度倍率；只调整墙钟节拍，不修改 MuJoCo timestep。
#  17（2026-11-02）：实验消息主题、类名和字段迁移为英文；删除中文实验桥兼容层。
#  18（2026-11-02）：规划消息主题、类名和字段迁移为英文；删除中文规划桥模块。
#  19（2026-11-02）：模型/项目状态及模型/算法命令迁移为英文；删除中文模型桥模块。
#  20（2026-11-02）：仿真运行/重力消息迁移为英文；删除中文重力桥模块。
#  21（2026-11-02）：参数表、参数修改与参数事务迁移为英文；删除中文参数桥模块。
VERSION = 21


@dataclasses.dataclass(frozen=True)
class Field:
    name: str
    type: str                 # 见文件头记号表
    description: str = ""


@dataclasses.dataclass(frozen=True)
class Topic:
    name: str                   # 线上主题名（前端按它分发）
    class_name: str                 # 对应的 Python dataclass 名（用于自证比对）
    direction: str                 # "下行" = 仿真→界面；"上行" = 界面→仿真
    kind: str                 # "快照" = latest-wins；"命令" = 必须送达处理
    summary: str
    fields: tuple[Field, ...]


# ---------------------------------------------------------------------------
# 下行：仿真 → 界面（现状即 P0 已通的 4 条 + 另外 2 条桥已有的）
# ---------------------------------------------------------------------------
_OUTBOUND = (
    Topic(
        name="指标", class_name="MetricsSnapshot", direction="下行", kind="快照",
        summary="插件 指标() 报上来的实时数值，曲线的数据源（30 Hz 限频）",
        fields=(
            Field("时间", "number", "仿真时间（秒）"),
            Field("墙钟", "number", "真实时间（秒），画曲线用它做横轴更平稳"),
            Field("数值", "record<number>", "{指标名: 数值}，指标名形如「插件名·键名」"),
        ),
    ),
    Topic(
        name="parameter.table", class_name="ParameterTable", direction="下行", kind="快照",
        summary="当前已装算法声明的可调参数（10 Hz 限频）",
        fields=(
            Field("parameters", "record<any>",
                 "{全名: 参数项}，全名 = 「插件名·参数名」。参数项的形状见下：\n"
                 "  {plugin, plugin_english, plugin_version, parameter, value, range, step, unit}\n"
                 "★ 这份形状是从 `parameter_bridge.collect_parameters()` 的真实产物核对的：\n"
                 "  早期契约里写成 {值,最小,最大} —— 那是**按想象写的**，与实现不符，\n"
                 "  后果是前端把 `范围` 数组当成对象逐字符渲染，表格里出现一堆 0=N 1=· 的乱码。\n"
                 "  这正是「契约必须对着实现自证」的理由：`工具/验证/契约自检.py` 现在会\n"
                 "  用真实插件的 `adjustable_parameters()` 产出核对本字段的形状。"),
        ),
    ),
    Topic(
        name="parameter.updated", class_name="ParameterUpdate", direction="下行", kind="快照",
        summary="参数被改动后的回执（界面照它更新控件）",
        fields=(Field("updates", "record<any>", "{full parameter name: new value}"),),
    ),
    Topic(
        name="辨识状态", class_name="辨识状态", direction="下行", kind="快照",
        summary="参数辨识的进度与结果（5 Hz 限频）",
        fields=(
            Field("状态", "string", "空闲 / 采样中 / 辨识中 / 完成 / 出错"),
            Field("进度", "string", "给人看的进度描述"),
            Field("采样步数", "number", "已采样步数"),
            Field("结果", "object[]", "辨识出的参数列表"),
            Field("拟合", "record<any>", "拟合改善情况"),
            Field("耗时", "number", "耗时（秒）"),
            Field("日志", "string[]", "过程日志"),
        ),
    ),
    Topic(
        name="model.state", class_name="ModelState", direction="下行", kind="快照",
        summary="当前加载的模型（2 Hz 限频）",
        fields=(
            Field("current_path", "string", "相对包根或绝对路径"),
            Field("current_display_name", "string", "给人看的型号名"),
            Field("dof", "number", "nq"),
            Field("actuator_count", "number", "nu"),
            Field("status", "string", "就绪 / ✓ … / ✗ …"),
            Field("duration_s", "number", "上次加载耗时（秒）"),
        ),
    ),
    Topic(
        name="设备连接", class_name="连接状态", direction="下行", kind="快照",
        summary="设备链路的状态机/劣化参数/实测遥测/审计（当前只有模拟后端，不是真机）",
        fields=(
            Field("后端", "string", "后端名字。**永远显示它**，避免把模拟当成真机"),
            Field("已连接", "boolean", ""),
            Field("安全状态", "string", "未连接/已连接（未使能）/使能中/运行/停止/故障/急停"),
            Field("模式", "string", "空闲/位置/速度/力矩/阻尼/急停"),
            Field("自由度", "number", ""),
            Field("延迟毫秒", "number", "注入值"),
            Field("抖动毫秒", "number", "注入值"),
            Field("丢包率", "number", "注入值 0..1"),
            Field("编码器分辨率", "number", "量化步长，0=不量化"),
            Field("实测平均延迟", "number", "毫秒，来自真实帧时间戳差"),
            Field("实测最大延迟", "number", "毫秒"),
            Field("丢包数", "number", "后端统计"),
            Field("错序数", "number", ""),
            Field("拒绝数", "number", "安全层拒绝的命令数"),
            Field("最近位置", "number[]", "空 = 还没有状态帧（不是 0）"),
            Field("审计", "object[]", "最近 30 条：{时刻, 类别, 内容, 错误码}"),
            Field("说明", "string", ""),
        ),
    ),
    Topic(
        name="告警", class_name="告警消息", direction="下行", kind="快照",
        summary="当前**活动**的病态告警（含量化证据与经验建议）",
        fields=(
            Field("活动", "object[]",
                 "每项：{类型, 严重度, 信号, 开始秒, 结束秒, 证据, 建议, 曲线[], 曲线t[]}"),
            Field("已检出", "number", "本次会话累计检出过多少条"),
        ),
    ),
    Topic(
        name="parameter.transaction", class_name="ParameterTransactionResult", direction="下行", kind="快照",
        summary="批量改参数的结果：要么全提交，要么全回滚（不会有「改了一半」）",
        fields=(
            Field("state", "string", "idle / committed / rolled_back"),
            Field("success_count", "number", ""),
            Field("failure_count", "number", ""),
            Field("timestamp", "string", ""),
            Field("changes", "object[]", "每项：{full_name, old_value, new_value}"),
            Field("failures", "string[]", "逐条失败原因"),
            Field("description", "string", "给人看的一句话"),
        ),
    ),
    Topic(
        name="planning.result", class_name="PlanningResult", direction="下行", kind="快照",
        summary="关节航点轨迹规划的结果与校验（终端速度/余量/瓶颈/包络）",
        fields=(
            Field("status", "string", "idle / planning / completed / failed"),
            Field("waypoint_count", "number", "参与规划的航点数"),
            Field("dof", "number", "n"),
            Field("duration_s", "number", "秒"),
            Field("path_length", "number", "关节空间弧长 rad"),
            Field("max_joint_velocity", "number", "rad/s"),
            Field("max_joint_acceleration", "number", "rad/s²"),
            Field("max_joint_jerk", "number", "rad/s³（只校验不整形）"),
            Field("velocity_margin", "number", "1 - max(|qd|/vlim)，负数=超限"),
            Field("acceleration_margin", "number", "同上"),
            Field("jerk_margin", "number", "同上"),
            Field("terminal_velocity", "number", "必须≈0"),
            Field("smoothing_deviation", "number", "rad"),
            Field("bottleneck_joint", "number", "-1 = 无"),
            Field("bottleneck_type", "string", "速度 / 加速度 / 加加速度"),
            Field("bottleneck_position", "number", "s ∈ [0,1]"),
            Field("optimal_lower_bound", "number", "∫ds/v_max，纯理论下界"),
            Field("actual_to_lower_bound", "number", "实际时长 / 下界"),
            Field("limit_source", "string", "显式 / 估算（估算会写明）"),
            Field("timestamp", "string", ""),
            Field("reason", "string", "失败原因（空 = 正常）"),
            Field("comparison", "object", "同一路径换约束重规划后的对比"),
            Field("inverse_kinematics", "string", "笛卡尔输入的逆解说明；空 = 关节输入"),
            Field("output_path", "string", "离线产物目录（输出/05_轨迹/…，空 = 没存）"),
            Field("execution_status", "string", "idle / running / completed / interrupted"),
            Field("execution_progress", "number", "0..1"),
            Field("envelope", "number[]", "v_s_max(s) 采样（≤200 点）"),
            Field("path_axis", "number[]", "对应的 s"),
            Field("speed_axis", "number[]", "实际 sd(s)"),
        ),
    ),
    Topic(
        name="部署", class_name="部署状态", direction="下行", kind="快照",
        summary="部署包导出状态（导出的是文件，**不是**真机连接）",
        fields=(
            Field("状态", "string", "空闲 / 导出中 / ✓ 完成 / ✗ 失败"),
            Field("目录", "string", "导出到哪"),
            Field("文件数", "number", "几个文件"),
            Field("字节", "number", "总字节"),
            Field("时间", "string", "几点导出的"),
            Field("清单", "object[]", "每项：{文件, 说明, 字节}"),
            Field("说明", "string", "给人看的一句话"),
            Field("出错", "string", "失败原因（空 = 正常）"),
        ),
    ),
    Topic(
        name="插件目录", class_name="PluginCatalog", direction="下行", kind="快照",
        summary="本机算法库里的插件清单（含版本/说明/作者/被哪些项目用到）",
        fields=(
            Field("数量", "number", "共几个"),
            Field("插件", "object[]",
                 "每项：{插件, 分组, 名称, 版本, 说明, 作者, 文件, 被项目使用[], 当前启用}"),
            Field("说明", "string", "扫描失败时的说明（空 = 正常）"),
        ),
    ),
    Topic(
        name="诊断", class_name="诊断报告", direction="下行", kind="快照",
        summary="自检结果：10 套断言逐条报（真跑 工具/验证 下的脚本）",
        fields=(
            Field("运行中", "boolean", "正在检查（界面据此把按钮变成检查中）"),
            Field("通过", "number", "通过了多少套"),
            Field("总数", "number", "一共跑了多少套"),
            Field("耗时秒", "number", "总耗时"),
            Field("时间", "string", "哪天几点跑的"),
            Field("项", "object[]", "每项：{名, 通过, 说明, 秒}"),
            Field("出错", "string", "跑不起来时的说明（空 = 正常）"),
        ),
    ),
    Topic(
        name="系统", class_name="SystemState", direction="下行", kind="快照",
        summary="运行期系统指标（1 Hz）：实时率、步频、内存 —— 监控视图的数据源",
        fields=(
            Field("仿真时间", "number", "累计仿真时间（秒）"),
            Field("墙钟", "number", "累计墙钟（秒，从开始跑算）"),
            Field("RTF", "number", "实时率 = 仿真时间增量/墙钟增量（1.0 = 实速）"),
            Field("步频", "number", "物理步/秒"),
            Field("仿真步长", "number", "模型的 timestep（秒）"),
            Field("内存MB", "number", "本进程常驻内存"),
            Field("插件数", "number", "当前装了几个插件"),
            Field("出错", "string", "采样失败时的说明（空 = 正常）"),
        ),
    ),
    Topic(
        name="simulation.state", class_name="SimulationState", direction="下行", kind="快照",
        summary="全局仿真运行状态：运行/暂停、data.time、复位次数与目标速度",
        fields=(
            Field("state", "string", "running / paused"),
            Field("gravity_enabled", "boolean", "是否使用模型 XML 中的重力；与运行/暂停相互独立"),
            Field("simulation_time", "number", "MuJoCo data.time（秒）"),
            Field("reset_count", "number", "本次会话执行 Reset 的累计次数"),
            Field("speed_multiplier", "number", "目标墙钟速度；实际达到值以系统.RTF为准"),
            Field("description", "string", "最近一次运行控制动作"),
        ),
    ),
    Topic(
        name="experiment.state", class_name="ExperimentState", direction="下行", kind="快照",
        summary="当前实验、可选实验、运行进度与自动导出结果",
        fields=(
            Field("current", "string", "当前实验注册名；空表示未选择"),
            Field("name", "string", "当前实验显示名"),
            Field("status", "string", "not_selected / loaded / running / paused / completed / failed"),
            Field("available", "object[]", "每项：{key,name,model,project,controllers[],duration_s,description}"),
            Field("model", "string", "实验声明的模型路径"),
            Field("project", "string", "实验声明的项目"),
            Field("controllers", "string[]", "实验声明的控制器注册名"),
            Field("duration_s", "number", "本次实验的仿真时长"),
            Field("elapsed_s", "number", "从本次点击开始累计的仿真时间"),
            Field("result_directory", "string", "自动导出完成后的目录"),
            Field("description", "string", "最近一次实验操作说明"),
        ),
    ),
    Topic(
        name="控制状态", class_name="ControlState", direction="下行", kind="快照",
        summary="关节目标输入区的数据源：当前位置、速度、控制量与已接受目标",
        fields=(
            Field("关节名", "string[]", "与 qpos 顺序对应的关节/坐标名称"),
            Field("当前位置", "number[]", "data.qpos"),
            Field("当前速度", "number[]", "data.qvel"),
            Field("当前控制", "number[]", "data.ctrl"),
            Field("目标", "number[]", "当前已接受的关节目标"),
            Field("目标来源", "string", "当前位置 / 手动输入"),
            Field("说明", "string", "最近一次目标处理结果"),
        ),
    ),
    Topic(
        name="model.library", class_name="AssetLibrary", direction="下行", kind="快照",
        summary="可选模型清单（资产库视图）—— 与「模型状态」区分：那是当前装的哪台",
        fields=(
            Field("count", "number", "共几台"),
            Field("models", "object[]",
                 "每项：{id, display_name, category, dof, actuator_count, license, controllable, path}；"
                 "路径是可直接加载的那个文件"),
        ),
    ),
    Topic(
        name="project.state", class_name="ProjectState", direction="下行", kind="快照",
        summary="当前项目 + 挂了哪些算法 + 重力设置（方案 C 的核心状态）",
        fields=(
            Field("project", "string", "项目名（空 = 没有对应项目）"),
            Field("model_path", "string", ""),
            Field("model_display_name", "string", ""),
            Field("algorithms", "object[]", "已装配算法元信息"),
            Field("report", "string[]", "上次装配的逐行说明"),
            Field("algorithm_library", "string[]", "算法库里可选的算法名"),
            Field("saved", "boolean", "当前算法组是否已写回项目文件"),
            Field("active_controller", "string", "谁在写 ctrl[:]（抢方向盘提示）"),
            Field("overridden_controllers", "string[]", "输出被覆盖的算法名"),
            Field("gravity_enabled", "boolean", "是否启用模型重力；不代表仿真是否运行"),
        ),
    ),
)

# ---------------------------------------------------------------------------
# 上行：界面 → 仿真（命令）
#
# ★ 安全纪律（为什么命令要单独登记、单独白名单）：
#   下行数据错了最多是"显示不对"；上行命令错了是"让机器人做别的事"。
#   所以命令**逐条登记**：没登记的类型一律拒收；每条都要写明是否危险、
#   是否需要限频。`Web桥` 只放行本表里的类型。
# ---------------------------------------------------------------------------
_INBOUND = (
    Topic(
        name="command.parameter_transaction", class_name="ParameterTransactionCommand", direction="上行", kind="快照",
        summary="一次性应用一组参数（预检不过就一个都不改）",
        fields=(
            Field("action", "string", "apply"),
            Field("parameters", "object[]", "每项 {full_name, value}"),
        ),
    ),
    Topic(
        name="command.planning", class_name="PlanningCommand", direction="上行", kind="快照",
        summary="对已记录的关节航点跑一次规划",
        fields=(
            Field("action", "string", "plan / record_waypoint / clear_waypoints / load_waypoints"),
            Field("waypoints", "object[]",
                 "直接给航点（每项是一组关节角）。给了就用它，不给就用已记录的"),
            Field("cartesian_waypoints", "object[]",
                 "每项 {xyz: [x,y,z]}，单位米。给了就先做逆解；**只支持位置，姿态未实现**"),
            Field("velocity_limits", "number[]", "rad/s（不给则从模型估算）"),
            Field("acceleration_limits", "number[]", "rad/s²（不给则 4×速度）"),
            Field("jerk_limits", "number[]", "rad/s³（不给则 20×加速度）"),
            Field("grid_size", "number", "s 上离散点数，默认 2000"),
            Field("smoothing_iterations", "number", "0 = 不平滑"),
            Field("smoothing_factor", "number", "≤0.49"),
            Field("deviation_tolerance", "number", "rad"),
        ),
    ),
    Topic(
        name="命令.部署", class_name="部署命令", direction="上行", kind="快照",
        summary="导出一个部署包（只拷源码与配置，不含模型本体）",
        fields=(Field("动作", "string", "导出（目前只认这个）"),),
    ),
    Topic(
        name="命令.诊断", class_name="诊断命令", direction="上行", kind="快照",
        summary="跑一遍自检（10 套断言真跑）",
        fields=(Field("动作", "string", "运行 / 空闲（目前只认运行）"),),
    ),
    Topic(
        name="命令.设备", class_name="连接命令", direction="上行", kind="快照",
        summary="设备链路控制：打开/使能/进运行/停止/急停/设劣化/演练断线/导出审计",
        fields=(
            Field("动作", "string",
                 "打开 / 使能 / 进运行 / 停止 / 急停 / 设劣化 / 演练断线 / 导出审计"),
            Field("延迟毫秒", "number", "<0 = 不改"),
            Field("抖动毫秒", "number", "<0 = 不改"),
            Field("丢包率", "number", "0..1，<0 = 不改"),
            Field("编码器分辨率", "number", "<0 = 不改"),
        ),
    ),
    Topic(
        name="命令.高亮", class_name="高亮命令", direction="上行", kind="快照",
        summary="在 3D 视口高亮一个关节（视觉诊断；不改变物理/模型）",
        fields=(
            Field("关节", "number", "关节索引；-1 = 清除高亮"),
            Field("秒", "number", "持续时间（秒），后端夹到 0..60"),
        ),
    ),
    Topic(
        name="command.gravity", class_name="GravityState", direction="上行", kind="快照",
        summary="物理总闸：True = 推进物理（重力生效），False = 冻结在默认位置",
        fields=(Field("gravity_enabled", "boolean", ""),),
    ),
    Topic(
        name="command.simulation", class_name="SimulationControlCommand", direction="上行", kind="命令",
        summary="全局仿真控制：运行、暂停、复位或设置墙钟速度倍率",
        fields=(
            Field("action", "string", "run / pause / reset / speed"),
            Field("speed_multiplier", "number", "0.25..4；只调整墙钟节拍，不修改 timestep"),
        ),
    ),
    Topic(
        name="command.experiment", class_name="ExperimentCommand", direction="上行", kind="命令",
        summary="按注册名加载实验；Run/Pause/Reset 继续复用全局仿真控制",
        fields=(
            Field("action", "string", "load"),
            Field("experiment", "string", "ExperimentRegistry 中的注册名"),
        ),
    ),
    Topic(
        name="命令.控制目标", class_name="ControlTargetCommand", direction="上行", kind="命令",
        summary="设置一组关节位置目标；由当前控制算法决定如何跟踪，不直接写 data.ctrl",
        fields=(Field("target", "number[]", "按 qpos 顺序，转动关节单位 rad"),),
    ),
    Topic(
        name="command.model", class_name="SwitchModelCommand", direction="上行", kind="命令",
        summary="切换机械臂（会连带按项目重新装配算法）",
        fields=(
            Field("path", "string", "模型路径（相对包根或绝对）"),
            Field("display_name", "string", "可留空"),
        ),
    ),
    Topic(
        name="command.algorithms", class_name="ApplyAlgorithmsCommand", direction="上行", kind="命令",
        summary="换一组控制算法（等价于点【Algorithms】面板的 Apply）",
        fields=(
            Field("algorithms", "object[]", "[{plugin: 名字}]"),
            Field("persist", "boolean", "是否写回项目文件"),
            Field("reset_pose", "boolean", ""),
        ),
    ),
    Topic(
        name="命令.辨识", class_name="辨识命令", direction="上行", kind="命令",
        summary="开始/停止参数辨识",
        fields=(
            Field("动作", "string", "开始 / 停止"),
            Field("时长", "number", "采样时长（秒）"),
        ),
    ),
    Topic(
        name="command.parameters", class_name="ParameterUpdate", direction="上行", kind="快照",
        summary="改一个或多个算法参数（等价于在【Controller params】面板拖滑杆）",
        fields=(
            Field("updates", "record<number>",
                 "{全名: 新值}，全名必须是参数表里的键（形如「插件名·参数名」）。"
                 "★ 为什么它不是普通命令而是快照语义：官方那条通道本来就是 latest-wins，"
                 "拖滑杆会连发很多条，照旧沿用才不会出现「排队抖动」。"),
        ),
    ),
    Topic(
        name="命令.录制", class_name="录制命令", direction="上行", kind="命令",
        summary="数据录制的开始/停止/回放",
        fields=(
            Field("动作", "string", "开始 / 停止 / 回放"),
            Field("频率", "number", "采样频率（Hz）"),
            Field("备注", "string", ""),
        ),
    ),
)

ALL_TOPICS: tuple[Topic, ...] = _OUTBOUND + _INBOUND
OUTBOUND_TOPICS = tuple(t for t in ALL_TOPICS if t.direction == "下行")
INBOUND_TOPICS = tuple(t for t in ALL_TOPICS if t.direction == "上行")
BY_NAME = {t.name: t for t in ALL_TOPICS}
BY_CLASS_NAME = {t.class_name: t for t in ALL_TOPICS}


def get_topic(name: str) -> Topic | None:
    return BY_NAME.get(name)


def type_markers() -> tuple[str, ...]:
    """本契约用到的基本类型记号（前端据此决定 TS 映射）。"""
    return ("number", "string", "boolean", "any", "number[]", "string[]",
            "object[]", "record<number>", "record<any>")


def to_dict() -> dict:
    """给前端/接口用的纯字典形态（含版本，便于前端判断是否要刷新）。"""
    return {
        "版本": VERSION,
        "类型记号": list(type_markers()),
        "下行": [
            {"名": t.name, "类名": t.class_name, "种类": t.kind, "摘要": t.summary,
             "字段": [{"名": f.name, "类型": f.type, "说明": f.description} for f in t.fields]}
            for t in OUTBOUND_TOPICS
        ],
        "上行": [
            {"名": t.name, "类名": t.class_name, "种类": t.kind, "摘要": t.summary,
             "字段": [{"名": f.name, "类型": f.type, "说明": f.description} for f in t.fields]}
            for t in INBOUND_TOPICS
        ],
    }


# ---------------------------------------------------------------------------
# 校验：命令进来先过这一关（类型 + 必填 + 取值范围）
# ---------------------------------------------------------------------------
def _matches_type(value: Any, type_marker: str) -> bool:
    """宽松但足够拦住"发错东西"的类型检查。"""
    if type_marker == "any":
        return True
    if type_marker == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_marker == "string":
        return isinstance(value, str)
    if type_marker == "boolean":
        return isinstance(value, bool)
    if type_marker == "number[]":
        return isinstance(value, (list, tuple)) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
    if type_marker == "string[]":
        return isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value)
    if type_marker == "object[]":
        return isinstance(value, (list, tuple)) and all(isinstance(v, dict) for v in value)
    if type_marker == "record<number>":
        return isinstance(value, dict) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value.values())
    if type_marker == "record<any":
        return isinstance(value, dict)
    if type_marker == "record<any>":
        return isinstance(value, dict)
    return False


# 每条命令字段的额外约束（不做的话，"动作" 写成任意字符串都能过）
_ENUM_VALUES: dict[tuple[str, str], tuple[str, ...]] = {
    ("command.parameter_transaction", "action"): ("apply",),
    ("command.simulation", "action"): ("run", "pause", "reset", "speed"),
    ("command.experiment", "action"): ("load",),
    ("command.planning", "action"): (
        "plan", "record_waypoint", "clear_waypoints", "load_waypoints",
        "execute", "stop_execution",
    ),
    ("命令.辨识", "动作"): ("开始", "停止", "start", "stop"),
    ("命令.录制", "动作"): ("开始", "停止", "回放", "start", "stop", "replay"),
}
_VALUE_RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("command.simulation", "speed_multiplier"): (0.25, 4.0),
    ("命令.辨识", "时长"): (0.1, 3600.0),
    ("命令.录制", "频率"): (1.0, 10000.0),
}


def class_name_to_topic() -> dict[str, str]:
    """{"指标消息": "指标", …} —— 给"通道水龙头"用。

    ★ 为什么要这个函数、而不是让 `Web桥` 自己写一份白名单：
      写两份就一定会漂移（P1 开发时实测：`Web桥` 的白名单里曾有一条 `录制状态`，
      而 `录制桥` 从来没定义过这个 dataclass —— 幽灵条目，放行它等于没有校验）。
      所以白名单**从契约派生**，契约又由 `工具/验证/契约自检.py` 对着真实 dataclass 自证。
    """
    return {t.class_name: t.name for t in OUTBOUND_TOPICS}


def validate(topic_name: str, payload: Any) -> tuple[bool, str]:
    """校验一条上行命令。返回 (是否通过, 给人看的说明)。"""
    t = BY_NAME.get(topic_name)
    if t is None:
        return False, f'未登记的主题「{topic_name}」'
    if t.direction != "上行":
        return False, f'「{topic_name}」是下行主题，不能当命令发'
    if not isinstance(payload, dict):
        return False, "负载必须是对象"
    known_fields = {f.name for f in t.fields}
    unknown_fields = set(payload) - known_fields
    if unknown_fields:
        return False, f"有未登记字段：{'、'.join(sorted(unknown_fields))}"
    for f in t.fields:
        if f.name not in payload:
            continue                      # 缺省字段交给 Python dataclass 的默认值
        value = payload[f.name]
        if not _matches_type(value, f.type):
            return False, f'字段「{f.name}」类型不符（要 {f.type}）'
        allowed_values = _ENUM_VALUES.get((topic_name, f.name))
        if allowed_values and value not in allowed_values:
            return False, f"字段「{f.name}」取值必须是 {'/'.join(allowed_values)}"
        value_range = _VALUE_RANGES.get((topic_name, f.name))
        if value_range and not (value_range[0] <= float(value) <= value_range[1]):
            return False, f'字段「{f.name}」超出范围 [{value_range[0]}, {value_range[1]}]'
    return True, "ok"


def find_drift() -> list[str]:
    """把本契约与**真实 dataclass** 逐项比对，返回不一致清单（空 = 一致）。

    ★ 为什么要有它：契约是手写的，手写就会漂移。这个函数让"契约与代码不一致"
      从"人肉核对"变成"跑一次脚本就知道"。
    """
    import importlib
    import sys
    import os

    runtime_directory = os.path.dirname(os.path.abspath(__file__))
    if runtime_directory not in sys.path:
        sys.path.insert(0, runtime_directory)

    source_modules = {
        "连接状态": "devices.connection_bridge", "连接命令": "devices.connection_bridge",
        "告警消息": "observation_core", "诊断报告": "diagnostics_bridge",
        "诊断命令": "diagnostics_bridge", "高亮命令": "highlight_bridge",
        "部署命令": "deployment_bridge", "部署状态": "deployment_bridge",
        "SystemState": "system_bridge", "MetricsSnapshot": "metrics_bridge", "PluginCatalog": "plugin_bridge",
        "ParameterTable": "parameter_bridge",
        "ParameterUpdate": "parameter_bridge",
        "ParameterTransactionResult": "parameter_bridge",
        "辨识状态": "identification_bridge", "ModelState": "model_bridge",
        "AssetLibrary": "model_bridge", "ProjectState": "model_bridge",
        "GravityState": "simulation_control", "SimulationState": "simulation_control",
        "SimulationControlCommand": "simulation_control",
        "ExperimentState": "experiment_bridge", "ExperimentCommand": "experiment_bridge",
        "PlanningResult": "planning_bridge", "PlanningCommand": "planning_bridge",
        "ControlState": "control_bridge", "ControlTargetCommand": "control_bridge",
        "SwitchModelCommand": "model_bridge", "ApplyAlgorithmsCommand": "model_bridge",
        "ParameterTransactionCommand": "parameter_bridge",
        "辨识命令": "identification_bridge", "录制命令": "recording_bridge",
    }
    issues: list[str] = []
    for t in ALL_TOPICS:
        module_name = source_modules.get(t.class_name)
        if module_name is None:
            continue
        try:
            from wire_compatibility import resolve_wire_class
            message_class = resolve_wire_class(importlib.import_module(module_name), t.class_name)
        except Exception as exc:                                     # noqa: BLE001
            issues.append(f'{t.name}：拿不到 {module_name}.{t.class_name}（{type(exc).__name__}: {exc}）')
            continue
        from wire_compatibility import wire_field_name
        actual_fields = [wire_field_name(message_class, f.name) for f in dataclasses.fields(message_class)]
        contract_fields = [f.name for f in t.fields]
        if actual_fields != contract_fields:
            missing_fields = [x for x in actual_fields if x not in contract_fields]
            extra_fields = [x for x in contract_fields if x not in actual_fields]
            reordered = (not missing_fields and not extra_fields)
            issues.append(
                f'{t.name}（{module_name}.{t.class_name}）字段不一致'
                + (f'：缺少 {missing_fields}' if missing_fields else "")
                + (f'：多出 {extra_fields}' if extra_fields else "")
                + ("：顺序不同（会影响位置参数，请对齐）" if reordered else ""))
    return issues


__all__ = [
    "VERSION", "Field", "Topic", "ALL_TOPICS", "OUTBOUND_TOPICS",
    "INBOUND_TOPICS", "BY_NAME", "BY_CLASS_NAME", "get_topic", "type_markers",
    "to_dict", "class_name_to_topic", "validate", "find_drift",
]


if __name__ == "__main__":
    import json as _json
    issues = find_drift()
    print("=" * 72)
    print(f'  契约自检（版本 {VERSION}）')
    print("=" * 72)
    print(f'  主题数：下行 {len(OUTBOUND_TOPICS)} / 上行 {len(INBOUND_TOPICS)}')
    if issues:
        print(f'\n  ✗ 发现 {len(issues)} 处与代码不一致：')
        for p in issues:
            print(f'    · {p}')
        raise SystemExit(1)
    print("\n  ✓ 契约与真实 dataclass 完全一致")
    print("\n  " + _json.dumps(to_dict(), ensure_ascii=False)[:200] + " …")
