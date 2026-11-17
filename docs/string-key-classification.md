# 字符串键分类（2026-11-17）

当前扫描包含 4862 处中文字符串键。这些是按名称用途分类的位置，不是剩余变量数量；源码标识符、路径和 JSON 键已通过严格门禁。

| 类别 | 位置数 |
| --- | ---: |
| 插件显示标签与旧参数别名 | 101 |
| v21 生成物、编解码边界与测试固定件 | 604 |
| 界面本地化资源 | 882 |
| 其他兼容/显示键（按文件核对） | 211 |
| 兼容转发层与旧导入映射 | 3064 |

## 其他兼容/显示键的核对

| 文件 | 性质 |
| --- | --- |
| `runtime/web_bridge.py`、`command_bridge.py` | v21 帧、握手、回执与旧消息类名 |
| `runtime/deployment_bridge.py`、`devices/connection_bridge.py`、`diagnostics_bridge.py`、`plugin_bridge.py`、`runtime_engine.py` | `legacy_wire` 声明或显式旧负载编码 |
| `runtime/observation_core.py` | v21 告警字段与面向用户的证据/曲线名称 |
| `runtime/project_registry.py`、`project_schema.py` | 旧算法标识与项目 schema 读取转换 |
| `runtime/simulation_control.py`、`ui_bridge.py` | 旧动作/主题名称兼容 |
| `frontend/src/views/DeploymentView.tsx` | 旧设备安全状态到本地化显示的查找表 |
| `runtime/official_interface_inventory.py` | 明确的旧 API 名称映射 |
| `tools/generate_frontend_assets.py` | 读取冻结 v21 契约并生成兼容映射 |
| `tools/selfchecks/*.py` | 旧数据、旧参数与协议固定样例、显示标签 |
| `scripts/check_naming.py` | 禁止应用新增旧导入的检查表 |

原生宿主的统计、视口槽和相机动作队列已经全部改用英文。原生日志桥中保留的中文字段属于既有宿主消息协议，发送和接收通过固定格式回归检查。

兼容层的退役条件见 [历史名称与兼容入口登记](legacy-compatibility-registry.md)。
