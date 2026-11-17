// Generated from Python legacy_wire declarations. Do not edit.

export const serverFieldAliases: Record<string, Record<string, string>> = {
  "指标": {
    "时间": "simulation_time",
    "墙钟": "wall_clock",
    "数值": "values"
  },
  "parameter.table": {},
  "parameter.updated": {},
  "辨识状态": {
    "状态": "state",
    "进度": "progress",
    "采样步数": "sample_count",
    "结果": "results",
    "拟合": "fit",
    "耗时": "elapsed_time",
    "日志": "log"
  },
  "model.state": {},
  "设备连接": {
    "后端": "backend",
    "已连接": "connected",
    "安全状态": "safety_state",
    "模式": "mode",
    "自由度": "dof",
    "延迟毫秒": "latency_ms",
    "抖动毫秒": "jitter_ms",
    "丢包率": "packet_loss_rate",
    "编码器分辨率": "encoder_resolution",
    "实测平均延迟": "measured_mean_latency",
    "实测最大延迟": "measured_max_latency",
    "丢包数": "dropped_packets",
    "错序数": "out_of_order_packets",
    "拒绝数": "rejected_count",
    "最近位置": "latest_position",
    "审计": "audit",
    "说明": "description"
  },
  "告警": {
    "活动": "active",
    "已检出": "detected_count"
  },
  "parameter.transaction": {},
  "planning.result": {},
  "部署": {
    "状态": "state",
    "目录": "directory",
    "文件数": "file_count",
    "字节": "bytes",
    "时间": "time",
    "清单": "manifest",
    "说明": "description",
    "出错": "errors"
  },
  "插件目录": {
    "数量": "count",
    "插件": "plugins",
    "说明": "description"
  },
  "诊断": {
    "运行中": "running",
    "通过": "passed",
    "总数": "total",
    "耗时秒": "elapsed_seconds",
    "时间": "time",
    "项": "items",
    "出错": "errors"
  },
  "系统": {
    "仿真时间": "simulation_time",
    "墙钟": "wall_clock",
    "步频": "step_rate",
    "仿真步长": "timestep",
    "内存MB": "memory_mb",
    "插件数": "plugin_count",
    "出错": "errors"
  },
  "simulation.state": {},
  "experiment.state": {},
  "控制状态": {
    "关节名": "joint_names",
    "当前位置": "current_position",
    "当前速度": "current_velocity",
    "当前控制": "current_control",
    "目标": "target",
    "目标来源": "target_source",
    "说明": "description"
  },
  "model.library": {},
  "project.state": {}
};

export const clientFieldAliases: Record<string, Record<string, string>> = {
  "command.parameter_transaction": {},
  "command.planning": {},
  "命令.部署": {
    "动作": "action"
  },
  "命令.诊断": {
    "动作": "action"
  },
  "命令.设备": {
    "动作": "action",
    "延迟毫秒": "latency_ms",
    "抖动毫秒": "jitter_ms",
    "丢包率": "packet_loss_rate",
    "编码器分辨率": "encoder_resolution"
  },
  "命令.高亮": {
    "关节": "joint",
    "秒": "seconds"
  },
  "command.gravity": {},
  "command.simulation": {},
  "command.experiment": {},
  "命令.控制目标": {},
  "command.model": {},
  "command.algorithms": {},
  "命令.辨识": {
    "动作": "action",
    "时长": "duration"
  },
  "command.parameters": {},
  "命令.录制": {
    "动作": "action",
    "频率": "frequency",
    "备注": "note"
  }
};
