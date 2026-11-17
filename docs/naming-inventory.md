# 内部命名迁移清单

由 `scripts/audit_naming.py` 从当前工作区生成。

扫描 224 个源码与配置文件；非 ASCII 名称出现位置共 4862 处。次数表示位置数量，不是迁移完成百分比。

中文界面、普通字符串值、注释和文档不计为标识符。字符串键是人工确认项，可能是机器字段，也可能是显示标签；JSON 键列入迁移范围。

TypeScript/TSX 使用编译器语法树；Python 使用语法树与 token。CSS/Shell 使用静态词法扫描，动态拼接的协议和路径需要迁移时另行核对。

## 分类统计

| 类别 | 出现位置 |
| --- | ---: |
| `string_key` | 4862 |

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
| `runtime/ascii_text.py` | 0 | 0 | 0 | 48 |
| `runtime/command_bridge.py` | 0 | 0 | 0 | 6 |
| `runtime/contract.py` | 0 | 0 | 0 | 31 |
| `runtime/deployment_bridge.py` | 0 | 0 | 0 | 13 |
| `runtime/devices/connection_bridge.py` | 0 | 0 | 0 | 4 |
| `runtime/diagnostics_bridge.py` | 0 | 0 | 0 | 5 |
| `runtime/i18n.py` | 0 | 0 | 0 | 207 |
| `runtime/legacy/ascii_text.py` | 0 | 0 | 0 | 46 |
| `runtime/legacy/command_bridge.py` | 0 | 0 | 0 | 17 |
| `runtime/legacy/console_support.py` | 0 | 0 | 0 | 1 |
| `runtime/legacy/contract.py` | 0 | 0 | 0 | 36 |
| `runtime/legacy/deployment_bridge.py` | 0 | 0 | 0 | 88 |
| `runtime/legacy/devices/connection_bridge.py` | 0 | 0 | 0 | 388 |
| `runtime/legacy/devices/contract.py` | 0 | 0 | 0 | 388 |
| `runtime/legacy/devices/safety.py` | 0 | 0 | 0 | 388 |
| `runtime/legacy/devices/simulated_backend.py` | 0 | 0 | 0 | 388 |
| `runtime/legacy/devices/tracking_loop.py` | 0 | 0 | 0 | 388 |
| `runtime/legacy/diagnostics_bridge.py` | 0 | 0 | 0 | 84 |
| `runtime/legacy/highlight_bridge.py` | 0 | 0 | 0 | 64 |
| `runtime/legacy/i18n.py` | 0 | 0 | 0 | 88 |
| `runtime/legacy/identification_bridge.py` | 0 | 0 | 0 | 48 |
| `runtime/legacy/observation_core.py` | 0 | 0 | 0 | 226 |
| `runtime/legacy/official_api.py` | 0 | 0 | 0 | 10 |
| `runtime/legacy/parameter_identification.py` | 0 | 0 | 0 | 79 |
| `runtime/legacy/plugin_bridge.py` | 0 | 0 | 0 | 74 |
| `runtime/legacy/recording_bridge.py` | 0 | 0 | 0 | 8 |
| `runtime/legacy/skeleton/official_interface_inventory.py` | 0 | 0 | 0 | 96 |
| `runtime/legacy/ui_bridge.py` | 0 | 0 | 0 | 4 |
| `runtime/legacy/web_bridge.py` | 0 | 0 | 0 | 130 |
| `runtime/legacy_imports.py` | 0 | 0 | 0 | 25 |
| `runtime/observation_core.py` | 0 | 0 | 0 | 19 |
| `runtime/official_interface_inventory.py` | 0 | 0 | 0 | 1 |
| `runtime/plugin_bridge.py` | 0 | 0 | 0 | 21 |
| `runtime/project_registry.py` | 0 | 0 | 0 | 9 |
| `runtime/project_schema.py` | 0 | 0 | 0 | 15 |
| `runtime/run_experiment.py` | 0 | 0 | 0 | 4 |
| `runtime/runtime_engine.py` | 0 | 0 | 0 | 2 |
| `runtime/simulation_control.py` | 0 | 0 | 0 | 3 |
| `runtime/ui_bridge.py` | 0 | 0 | 0 | 3 |
| `runtime/web_bridge.py` | 0 | 0 | 0 | 27 |
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

## 下一步

实施批次和验收标准见 [迁移计划](naming-migration-plan.md)。
字符串键的逐类说明见 [字符串键分类](string-key-classification.md)，
保留的中文路径/模块见 [兼容入口登记](legacy-compatibility-registry.md)。
完整名称与行号可用 `--json-report /tmp/yubi-naming-audit.json` 导出。
