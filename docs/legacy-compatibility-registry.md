# 历史名称与兼容入口登记

2026-11-17：自有源码目录与模块文件均已采用英文 ASCII。旧名字保留为显式数据映射，不再依赖中文文件名。

## 已完成的路径迁移

| 原位置 | 正式位置 | 兼容方式 |
| --- | --- | --- |
| `软件/` | `runtime/` | 根目录三个 ASCII 启动器统一配置运行目录；现有 `.app` 仍调用稳定的根目录入口 |
| `软件/设备/` | `runtime/legacy/devices/` | 旧设备模块经导入适配转到同一英文实现 |
| `软件/骨架/` | `runtime/legacy/skeleton/` | 旧模块名经导入适配；命令行改用正式英文入口 |
| `工具/验证/` | `tools/selfchecks/` | 诊断命令与文档已同步 |
| `工具/` | `tools/` | 工具和打包入口已同步 |
| `项目/`、`实验/`、`算法库/通用/` | `projects/`、`experiments/`、`controllers/common/` | 旧用户数据目录仍只读兼容 |

## 保留的旧导入名称

应用启动器与插件装配器调用 `legacy_imports.install()`。适配器只按下表接受明确旧名，延迟加载 `runtime/legacy/` 中的英文文件，消息类和类型仍属于同一正式实现。独立扩展脚本先把 `runtime/` 加入 `sys.path`，再显式调用 `install()`。

| 旧导入 | 适配模块 |
| --- | --- | --- |
| `Web桥` | `legacy.web_bridge` |
| `参数辨识` | `legacy.parameter_identification` |
| `命令桥` | `legacy.command_bridge` |
| `契约` | `legacy.contract` |
| `官方层` | `legacy.official_api` |
| `录制桥` | `legacy.recording_bridge` |
| `控制台` | `legacy.console_support` |
| `插件桥` | `legacy.plugin_bridge` |
| `文案` | `legacy.i18n` |
| `界面文字` | `legacy.ascii_text` |
| `界面桥` | `legacy.ui_bridge` |
| `观测核心` | `legacy.observation_core` |
| `设备.契约` | `legacy.devices.contract` |
| `设备.安全层` | `legacy.devices.safety` |
| `设备.模拟后端` | `legacy.devices.simulated_backend` |
| `设备.跟踪回路` | `legacy.devices.tracking_loop` |
| `设备.连接桥` | `legacy.devices.connection_bridge` |
| `诊断桥` | `legacy.diagnostics_bridge` |
| `辨识桥` | `legacy.identification_bridge` |
| `部署桥` | `legacy.deployment_bridge` |
| `验证参数辨识` | `legacy.validate_identification` |
| `骨架.官方接口清单` | `legacy.skeleton.official_interface_inventory` |
| `高亮桥` | `legacy.highlight_bridge` |
| `设备` | `legacy.devices` |
| `骨架` | `legacy.skeleton` |

退役条件：发布弃用说明并确认外部插件完成迁移后，删除对应映射及适配模块。新应用代码只导入正式英文模块。

## 旧命令行路径

原 `软件/验证参数辨识.py` 改用 `python runtime/validate_identification.py`；原 `软件/骨架/官方接口清单.py` 改用 `python runtime/official_interface_inventory.py`。旧的物理脚本路径已退役；应用进程中的旧模块导入仍兼容。

## 其他兼容数据

- 旧项目、设置、参数与环境变量的读取转换继续保留。
- v21 线上主题/字段和原生日志桥由明确的编解码边界保留。
- 中文界面、本地化资源、中文参数标签和用户数据属于显示内容。
- 新生成 macOS 启动器使用 `launch.sh`、`package_path.txt`、`icon.icns` 和 `launcher.c`；原有 `.app` 仍通过根目录入口运行。
