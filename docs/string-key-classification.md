# 字符串键分类（2026-11-17）

扫描器把字典/对象字面量的键单独列为 `string_key` 人工确认项。本表对当前工作区的 4,895 处字符串键分类；它是**分类记录**，不是“全部需要删除”的清单，也不把出现次数当完成百分比。

- 扫描总数：4,895 处字符串键；另有 23 个文件名、5 个目录名（见 [兼容入口登记](legacy-compatibility-registry.md)）。
- 机器键、JSON 键、自有源码标识符的自动门禁仍以 `python scripts/check_naming.py` 为准；`string_key` 是 advisory，新增内部机器键仍需人工审查。

## 分类统计

| 类别 | 位置数 | 处理 |
| --- | ---: | --- |
| 兼容转发层别名表 | 3,039 | 允许：`软件/设备/*`、各中文 `*桥` 模块的旧名 → 英文名映射；只做导入/关键字转发，不复制实现。退役条件见兼容入口登记。 |
| 界面本地化资源 | 890 | 允许：`frontend/src/views/i18n.ts`、`软件/i18n.py`、`软件/ascii_text.py` 及少量外壳显示键；界面文案继续支持中文。 |
| v21 线上形态/生成物/测试固定件 | 698 | 允许：`contract.py`、`legacy_wire` 声明、`generated/contract.ts`、`generated/wire_fields.ts`、`wire_compatibility.ts`、测试对端与契约测试。协议字段冻结，改协议需单独做版本升级。 |
| 插件显示标签与旧参数别名 | 100 | 允许：参数中文 `label`、指标/状态显示名、`parameter_aliases` 旧键；参数机器标识已是英文。 |
| 原生宿主诊断键 | 61 | 待办：`native_host.py`、`platform_adapters/windows*.py` 的视口统计/状态字典键仍为中文，只在宿主进程内传递；需与 Windows 宿主一起在 Windows 环境复核后迁移。 |
| 其他（逐项核对） | 107 | 见下表，均为显示文案、v21 边界、测试固定件或已登记兼容项。 |
| **合计** | **4,895** | |

## “其他”逐项

| 文件 | 位置数 | 性质 |
| --- | ---: | --- |
| `软件/web_bridge.py` | 27 | v21 帧/握手/回执键（`主题、协议、数据、请求、通过…`）；前端适配器负责转换，保持线上格式 |
| `tools/selfchecks/command_receipt_selfcheck.py` | 13 | 旧回执/命令固定件 |
| `tools/selfchecks/contract_selfcheck.py` | 11 | v21 契约固定件与显示文案 |
| `tools/selfchecks/theme_selfcheck.py` | 7 | 旧主题名/显示键检查样例 |
| `scripts/tests/test_settings_migration.py` | 6 | 旧设置键迁移固定件 |
| `软件/command_bridge.py` | 6 | `SOURCE_MODULES` 里的旧消息类名（线上类名） |
| `软件/diagnostics_bridge.py` | 5 | 诊断项显示名与命令路径 |
| `tools/selfchecks/parameter_transaction_selfcheck.py` | 4 | 参数事务测试夹具 |
| `软件/devices/connection_bridge.py` | 4 | `legacy_wire` 审计条目键（类型/内容/错误码） |
| `软件/run_experiment.py` | 4 | v21 录制命令 `动作/频率/备注` |
| `scripts/tests/test_env_config.py` | 3 | 旧环境变量别名固定件 |
| `scripts/tests/test_model_import.py` | 3 | 旧清单键固定件 |
| `scripts/tests/test_official_api.py` | 3 | 旧入口导入固定件 |
| `软件/simulation_control.py` | 3 | 插件状态显示名（运行/重力/复位） |
| `tools/selfchecks/observation_selfcheck.py` | 2 | 信号与检测器测试固定件 |
| `tools/selfchecks/project_selfcheck.py` | 2 | 显示文案/测试标签 |
| `软件/runtime_engine.py` | 2 | 插件目录 v21 负载键（数量/插件） |
| `controllers/common/controller_template.py` | 1 | 示例状态显示名 |
| `软件/official_interface_inventory.py` | 1 | 旧 `核心` 模块键别名（显式兼容） |

## 已迁移的持久化/内部机器键

- 项目文档：`project / model / algorithms / parameters / appearance / notes / experiment_only`（版本 2，旧中文键读取转换）。
- 控制器参数：`integral_limit / position_gain / target_offset_x / monitored_joint / sample_count ...`；中文只作为 `label` 与旧名别名。
- 录制元信息：`recording_file / recording_time / frequency_hz / sample_rows / software_versions / project / model / algorithms`。
- 模型清单：`source / asset_base_url / models / identifier / torque_model ...`。
- 外观表：`themes / theme_order / default_theme / web_semantic_colors / colors / styles / plots`；主题 id 为 ASCII。
- 设置：`last_model / last_project / language / windows_split_v2 / windows_right_split`，读取兼容旧中文键。
- 环境变量：`YUBI_*` 写入；旧中文名为只读兼容。
- 告警枚举：`oscillation / divergence / tracking_error / saturation`；严重度 `critical / warning`；界面显示仍为中文。

## 维护规则

1. 新增自有源码标识符、JSON 键或机器字段必须使用英文 ASCII；界面文案和显示标签可以保留中文。
2. 旧协议/旧数据字段只能存在于明确的兼容边界（`legacy_wire`、`*桥` 转发层、`wire_compatibility`、迁移器），不得在内部实现里扩散。
3. 任何为“让扫描归零”而删除兼容字段、隐藏键或改写线上协议的做法都不接受；改协议必须版本化并同时更新前端、测试与文档。
