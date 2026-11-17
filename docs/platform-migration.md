# 平台英文化交接

本批基于 `8e04296`，涵盖桌面宿主、平台适配及维护工具。仿真项目、模型、控制算法以及前后端消息协议由各自的维护批次处理。

## 配置与兼容边界

| 入口或配置 | 当前处理 |
|---|---|
| `输出/设置.json` 中的 `Windows主分栏V2`、`Windows右列分栏`、`last_project`、`语言` | 布局与语言键保留；上次项目新写入 `last_project`，读取兼容旧的 `上次项目`。 |
| `YUBI_WEB_PORT`、`YUBI_DISABLE_WEB`、`YUBI_MODEL`、`YUBI_LANG` | 新的 ASCII 环境变量；读取兼容旧中文名（见下表），写入只使用新名。命令行可用 `--web-port`、`--model`、`--语言`。 |
| `YUBI_DIAGNOSTIC`、`YUBI_CURRENT_MODEL`、`YUBI_CURRENT_PROJECT`、`YUBI_GFX` | 新的 ASCII 环境变量；设置方与读取方都已改用新名，旧名为只读兼容。 |
| macOS 启动器的 `YUBI_PACKAGE_PATH`、`Resources/包路径.txt` 和 `Resources/启动.sh` | 新生成启动器优先读 `YUBI_PACKAGE_PATH`，仍回退旧的 `小软件_包路径`；包内 `包路径.txt` 优先。 |
| 旧中文环境变量 | `驭臂_模型`、`驭臂_Web端口`、`驭臂_关Web`、`驭臂_语言`、`驭臂_宿主诊断`、`驭臂_当前模型`、`驭臂_当前项目`、`驭臂_gfx`、`小软件_包路径` 仅作为读取兼容，不再写入；迁移表在 `软件/env_config.py`。 |
| 旧中文命令行选项 | 维护脚本以英文选项为主，保留已支持的中文选项作为别名。 |
| v21 消息字段及旧配置、录制数据格式 | 由前后端协议批次统一处理。本批保留现有格式。 |

## 模块入口

- 旧 `宿主窗口.py`、`定时器.py` 已移除，内部实现分别在 `native_host.py`、`runloop_timers.py`。
- 旧 `平台适配层` 的六个转发文件已移除。入口统一用 `platform_adapters`，Windows 视口和运行信息分别在 `windows_viewport.py` 和 `windows_runtime_info.py`。
- 旧 `官方层自检.py` 已移除，诊断页使用 `official_api_selfcheck.py`。仓库外如有调用方，需要改用对应的英文入口。

## 验证记录

- Windows 实际窗口基于现有 KUKA LBR iiwa 14 验证了启动、模型库加载、3D 和运行信息刷新、运行、暂停及复位。复位后时间为 0 秒，保持暂停。
- 运行内核自检 4 项通过，项目一致性检查 74 项通过，Windows 启动预检通过。
- 版本锁检查、两套图标的内存绘制和 Bash 语法检查通过。macOS 实际打包和 GUI 中的具体控制实验未在本批验收。
- 增量命名门禁通过，未发现超出已审查基线的新内部命名。当前扫描仍报告 13,172 个非 ASCII 命名位置（其中 4,827 个是需人工分类的字符串键）；它们是历史存量，不能据此认定全仓英文化已完成。后续应按前端、Python 核心、协议配置、导入工具等范围继续迁移。
