# 内部命名迁移清单

由 `scripts/audit_naming.py` 从当前工作区生成。

扫描 221 个源码与配置文件；非 ASCII 名称出现位置共 4921 处。次数表示位置数量，不是迁移完成百分比。

中文界面、普通字符串值、注释和文档不计为标识符。字符串键是人工确认项，可能是机器字段，也可能是显示标签；JSON 键列入迁移范围。

TypeScript/TSX 使用编译器语法树；Python 使用语法树与 token。CSS/Shell 使用静态词法扫描，动态拼接的协议和路径需要迁移时另行核对。

## 分类统计

| 类别 | 出现位置 |
| --- | ---: |
| `directory_name` | 3 |
| `file_name` | 23 |
| `string_key` | 4895 |

## 按文件迁移

目录与文件名是独立项；标识符数不包括注释和显示文案。

| 文件或目录 | 代码标识符 | 路径/导入 | JSON 键 | 字符串键待确认 |
| --- | ---: | ---: | ---: | ---: |
| `controllers/common/controller_template.py` | 0 | 0 | 0 | 1 |
| `controllers/common/data_recorder.py` | 0 | 0 | 0 | 4 |
| `controllers/common/joint_pd_control.py` | 0 | 0 | 0 | 8 |
| `controllers/common/joint_pd_gravity_ff.py` | 0 | 0 | 0 | 3 |
| `controllers/common/joint_pd_plain.py` | 0 | 0 | 0 | 2 |
| `controllers/common/joint_pid_control.py` | 0 | 0 | 0 | 9 |
| `controllers/common/joint_pid_plain.py` | 0 | 0 | 0 | 4 |
| `controllers/common/panda_mjpc_port.py` | 0 | 0 | 0 | 29 |
| `controllers/common/panda_pick_place.py` | 0 | 0 | 0 | 13 |
| `controllers/common/parameter_identification_plugin.py` | 0 | 0 | 0 | 13 |
| `controllers/common/sinusoidal_joint_motion.py` | 0 | 0 | 0 | 3 |
| `controllers/common/trajectory_target_player.py` | 0 | 0 | 0 | 8 |
| `controllers/common/two_point_task_space.py` | 0 | 0 | 0 | 4 |
| `frontend/src/data/wire_compatibility.ts` | 0 | 0 | 0 | 80 |
| `frontend/src/generated/contract.ts` | 0 | 0 | 0 | 91 |
| `frontend/src/generated/wire_fields.ts` | 0 | 0 | 0 | 91 |
| `frontend/src/shell/App.tsx` | 0 | 0 | 0 | 3 |
| `frontend/src/shell/StatusBar.tsx` | 0 | 0 | 0 | 1 |
| `frontend/src/views/DeploymentView.tsx` | 0 | 0 | 0 | 8 |
| `frontend/src/views/i18n.ts` | 0 | 0 | 0 | 623 |
| `frontend/tests/fake_backend.py` | 0 | 0 | 0 | 138 |
| `scripts/check_naming.py` | 0 | 0 | 0 | 2 |
| `scripts/tests/test_connection.cjs` | 0 | 0 | 0 | 10 |
| `scripts/tests/test_contract.py` | 0 | 0 | 0 | 21 |
| `scripts/tests/test_env_config.py` | 0 | 0 | 0 | 3 |
| `scripts/tests/test_frontend_state.cjs` | 0 | 0 | 0 | 9 |
| `scripts/tests/test_model_import.py` | 0 | 0 | 0 | 3 |
| `scripts/tests/test_official_api.py` | 0 | 0 | 0 | 3 |
| `scripts/tests/test_project_schema.py` | 0 | 0 | 0 | 32 |
| `scripts/tests/test_settings_migration.py` | 0 | 0 | 0 | 6 |
| `scripts/tests/test_wire_compatibility.cjs` | 0 | 0 | 0 | 81 |
| `scripts/tests/test_wire_compatibility.py` | 0 | 0 | 0 | 5 |
| `tools/generate_frontend_assets.py` | 0 | 0 | 0 | 30 |
| `tools/selfchecks/command_receipt_selfcheck.py` | 0 | 0 | 0 | 13 |
| `tools/selfchecks/contract_selfcheck.py` | 0 | 0 | 0 | 11 |
| `tools/selfchecks/observation_selfcheck.py` | 0 | 0 | 0 | 2 |
| `tools/selfchecks/parameter_transaction_selfcheck.py` | 0 | 0 | 0 | 4 |
| `tools/selfchecks/project_selfcheck.py` | 0 | 0 | 0 | 2 |
| `tools/selfchecks/theme_selfcheck.py` | 0 | 0 | 0 | 7 |
| `软件` | 0 | 1 | 0 | 0 |
| `软件/Web桥.py` | 0 | 1 | 0 | 130 |
| `软件/ascii_text.py` | 0 | 0 | 0 | 48 |
| `软件/command_bridge.py` | 0 | 0 | 0 | 6 |
| `软件/contract.py` | 0 | 0 | 0 | 31 |
| `软件/deployment_bridge.py` | 0 | 0 | 0 | 13 |
| `软件/desktop_app.py` | 0 | 0 | 0 | 4 |
| `软件/devices/connection_bridge.py` | 0 | 0 | 0 | 4 |
| `软件/diagnostics_bridge.py` | 0 | 0 | 0 | 5 |
| `软件/i18n.py` | 0 | 0 | 0 | 207 |
| `软件/native_host.py` | 0 | 0 | 0 | 28 |
| `软件/observation_core.py` | 0 | 0 | 0 | 19 |
| `软件/official_interface_inventory.py` | 0 | 0 | 0 | 1 |
| `软件/platform_adapters/macos.py` | 0 | 0 | 0 | 1 |
| `软件/platform_adapters/windows.py` | 0 | 0 | 0 | 11 |
| `软件/platform_adapters/windows_runtime_info.py` | 0 | 0 | 0 | 1 |
| `软件/platform_adapters/windows_viewport.py` | 0 | 0 | 0 | 13 |
| `软件/plugin_bridge.py` | 0 | 0 | 0 | 21 |
| `软件/project_registry.py` | 0 | 0 | 0 | 9 |
| `软件/project_schema.py` | 0 | 0 | 0 | 15 |
| `软件/run_experiment.py` | 0 | 0 | 0 | 4 |
| `软件/runtime_engine.py` | 0 | 0 | 0 | 2 |
| `软件/simulation_control.py` | 0 | 0 | 0 | 3 |
| `软件/ui_bridge.py` | 0 | 0 | 0 | 3 |
| `软件/web_bridge.py` | 0 | 0 | 0 | 27 |
| `软件/参数辨识.py` | 0 | 1 | 0 | 79 |
| `软件/命令桥.py` | 0 | 1 | 0 | 17 |
| `软件/契约.py` | 0 | 1 | 0 | 36 |
| `软件/官方层.py` | 0 | 1 | 0 | 10 |
| `软件/录制桥.py` | 0 | 1 | 0 | 8 |
| `软件/控制台.py` | 0 | 1 | 0 | 1 |
| `软件/插件桥.py` | 0 | 1 | 0 | 74 |
| `软件/文案.py` | 0 | 1 | 0 | 88 |
| `软件/界面文字.py` | 0 | 1 | 0 | 46 |
| `软件/界面桥.py` | 0 | 1 | 0 | 4 |
| `软件/观测核心.py` | 0 | 1 | 0 | 226 |
| `软件/设备` | 0 | 1 | 0 | 0 |
| `软件/设备/契约.py` | 0 | 1 | 0 | 388 |
| `软件/设备/安全层.py` | 0 | 1 | 0 | 388 |
| `软件/设备/模拟后端.py` | 0 | 1 | 0 | 388 |
| `软件/设备/跟踪回路.py` | 0 | 1 | 0 | 388 |
| `软件/设备/连接桥.py` | 0 | 1 | 0 | 388 |
| `软件/诊断桥.py` | 0 | 1 | 0 | 84 |
| `软件/辨识桥.py` | 0 | 1 | 0 | 48 |
| `软件/部署桥.py` | 0 | 1 | 0 | 88 |
| `软件/验证参数辨识.py` | 0 | 1 | 0 | 0 |
| `软件/骨架` | 0 | 1 | 0 | 0 |
| `软件/骨架/官方接口清单.py` | 0 | 1 | 0 | 96 |
| `软件/高亮桥.py` | 0 | 1 | 0 | 64 |

## 下一步

实施批次和验收标准见 [迁移计划](naming-migration-plan.md)。
字符串键的逐类说明见 [字符串键分类](string-key-classification.md)，
保留的中文路径/模块见 [兼容入口登记](legacy-compatibility-registry.md)。
完整名称与行号可用 `--json-report /tmp/yubi-naming-audit.json` 导出。
