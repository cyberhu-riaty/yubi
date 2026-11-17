# 内部命名迁移清单

由 `scripts/audit_naming.py` 从当前工作区生成。

扫描 211 个源码与配置文件；非 ASCII 名称出现位置共 11086 处。次数表示位置数量，不是迁移完成百分比。

中文界面、普通字符串值、注释和文档不计为标识符。字符串键是人工确认项，可能是机器字段，也可能是显示标签；JSON 键列入迁移范围。

TypeScript/TSX 使用编译器语法树；Python 使用语法树与 token。CSS/Shell 使用静态词法扫描，动态拼接的协议和路径需要迁移时另行核对。

## 分类统计

| 类别 | 出现位置 |
| --- | ---: |
| `css_identifier` | 146 |
| `directory_name` | 17 |
| `file_name` | 70 |
| `import_path` | 139 |
| `json_key` | 579 |
| `string_key` | 4849 |
| `typescript_identifier` | 5286 |

## 按文件迁移

目录与文件名是独立项；标识符数不包括注释和显示文案。

| 文件或目录 | 代码标识符 | 路径/导入 | JSON 键 | 字符串键待确认 |
| --- | ---: | ---: | ---: | ---: |
| `scripts/check_naming.py` | 0 | 0 | 0 | 2 |
| `scripts/tests/test_connection.cjs` | 0 | 0 | 0 | 15 |
| `scripts/tests/test_contract.py` | 0 | 0 | 0 | 21 |
| `scripts/tests/test_model_import.py` | 0 | 0 | 0 | 7 |
| `scripts/tests/test_official_api.py` | 0 | 0 | 0 | 3 |
| `scripts/tests/test_wire_compatibility.py` | 0 | 0 | 0 | 5 |
| `前端` | 0 | 1 | 0 | 0 |
| `前端/src/index.css` | 122 | 0 | 0 | 0 |
| `前端/src/main.tsx` | 7 | 4 | 0 | 0 |
| `前端/src/外壳` | 0 | 1 | 0 | 0 |
| `前端/src/外壳/App.tsx` | 422 | 9 | 0 | 0 |
| `前端/src/外壳/step_navigation.ts` | 0 | 1 | 0 | 0 |
| `前端/src/外壳/上下文条.tsx` | 21 | 3 | 0 | 0 |
| `前端/src/外壳/中区.tsx` | 198 | 10 | 0 | 0 |
| `前端/src/外壳/任务流.ts` | 54 | 2 | 0 | 0 |
| `前端/src/外壳/侧栏.tsx` | 52 | 18 | 0 | 0 |
| `前端/src/外壳/控制台.tsx` | 785 | 6 | 0 | 0 |
| `前端/src/外壳/提示区.tsx` | 13 | 3 | 0 | 0 |
| `前端/src/外壳/活动栏.tsx` | 91 | 3 | 0 | 0 |
| `前端/src/外壳/状态栏.tsx` | 68 | 3 | 0 | 1 |
| `前端/src/数据` | 0 | 1 | 0 | 0 |
| `前端/src/数据/connection.ts` | 61 | 1 | 0 | 0 |
| `前端/src/数据/仓库.ts` | 558 | 1 | 0 | 0 |
| `前端/src/数据/日志.ts` | 466 | 3 | 0 | 0 |
| `前端/src/生成` | 0 | 1 | 0 | 0 |
| `前端/src/生成/主题.css` | 24 | 1 | 0 | 0 |
| `前端/src/生成/外观.ts` | 45 | 2 | 0 | 0 |
| `前端/src/生成/契约.ts` | 288 | 1 | 0 | 16 |
| `前端/src/生成/风格.ts` | 32 | 1 | 0 | 0 |
| `前端/src/组件` | 0 | 1 | 0 | 0 |
| `前端/src/组件/可折叠区块.tsx` | 2 | 2 | 0 | 0 |
| `前端/src/组件/开关.tsx` | 0 | 2 | 0 | 0 |
| `前端/src/组件/按钮.tsx` | 0 | 1 | 0 | 0 |
| `前端/src/组件/数值表.tsx` | 0 | 2 | 0 | 0 |
| `前端/src/组件/曲线.tsx` | 0 | 3 | 0 | 0 |
| `前端/src/组件/标签.tsx` | 0 | 1 | 0 | 0 |
| `前端/src/组件/路径值.tsx` | 0 | 2 | 0 | 0 |
| `前端/src/视图` | 0 | 1 | 0 | 0 |
| `前端/src/视图/关于视图.tsx` | 64 | 7 | 0 | 0 |
| `前端/src/视图/外观视图.tsx` | 28 | 7 | 0 | 0 |
| `前端/src/视图/定义视图.tsx` | 496 | 10 | 0 | 0 |
| `前端/src/视图/帮助视图.tsx` | 16 | 4 | 0 | 0 |
| `前端/src/视图/插件视图.tsx` | 53 | 7 | 0 | 0 |
| `前端/src/视图/文案.ts` | 10 | 1 | 0 | 618 |
| `前端/src/视图/监控视图.tsx` | 110 | 6 | 0 | 0 |
| `前端/src/视图/规划视图.tsx` | 329 | 9 | 0 | 0 |
| `前端/src/视图/诊断视图.tsx` | 102 | 8 | 0 | 0 |
| `前端/src/视图/辨识视图.tsx` | 186 | 8 | 0 | 0 |
| `前端/src/视图/部署视图.tsx` | 294 | 8 | 0 | 5 |
| `前端/src/视图/验证视图.tsx` | 433 | 12 | 0 | 0 |
| `前端/tsconfig.json` | 0 | 0 | 1 | 0 |
| `前端/vite.config.ts` | 2 | 0 | 0 | 1 |
| `前端/测试` | 0 | 1 | 0 | 0 |
| `前端/测试/fake_backend.py` | 0 | 0 | 0 | 138 |
| `实验` | 0 | 1 | 0 | 0 |
| `工具` | 0 | 1 | 0 | 0 |
| `工具/generate_frontend_assets.py` | 0 | 0 | 0 | 30 |
| `工具/import_model.py` | 0 | 0 | 0 | 79 |
| `工具/urdf_to_mjcf.py` | 0 | 0 | 0 | 25 |
| `工具/模型清单.json` | 0 | 1 | 245 | 0 |
| `工具/示例_urdf转mjcf` | 0 | 1 | 0 | 0 |
| `工具/示例_urdf转mjcf/示例_参数.json` | 0 | 1 | 2 | 0 |
| `工具/示例_urdf转mjcf/示例_参数_六轴.json` | 0 | 1 | 2 | 0 |
| `工具/验证` | 0 | 1 | 0 | 0 |
| `工具/验证/command_receipt_selfcheck.py` | 0 | 0 | 0 | 13 |
| `工具/验证/contract_selfcheck.py` | 0 | 0 | 0 | 11 |
| `工具/验证/experiment_gui_selfcheck.py` | 0 | 0 | 0 | 1 |
| `工具/验证/experiment_registry_selfcheck.py` | 0 | 0 | 0 | 1 |
| `工具/验证/latency_sensitivity.py` | 0 | 0 | 0 | 8 |
| `工具/验证/observation_selfcheck.py` | 0 | 0 | 0 | 2 |
| `工具/验证/parameter_transaction_selfcheck.py` | 0 | 0 | 0 | 4 |
| `工具/验证/project_selfcheck.py` | 0 | 0 | 0 | 7 |
| `工具/验证/runtime_selfcheck.py` | 0 | 0 | 0 | 1 |
| `工具/验证/theme_selfcheck.py` | 0 | 0 | 0 | 8 |
| `算法库` | 0 | 1 | 0 | 0 |
| `算法库/通用` | 0 | 1 | 0 | 0 |
| `算法库/通用/controller_template.py` | 0 | 0 | 0 | 1 |
| `算法库/通用/data_recorder.py` | 0 | 0 | 0 | 26 |
| `算法库/通用/joint_pd_control.py` | 0 | 0 | 0 | 8 |
| `算法库/通用/joint_pd_gravity_ff.py` | 0 | 0 | 0 | 3 |
| `算法库/通用/joint_pd_plain.py` | 0 | 0 | 0 | 2 |
| `算法库/通用/joint_pid_control.py` | 0 | 0 | 0 | 10 |
| `算法库/通用/joint_pid_plain.py` | 0 | 0 | 0 | 5 |
| `算法库/通用/panda_mjpc_port.py` | 0 | 0 | 0 | 69 |
| `算法库/通用/panda_pick_place.py` | 0 | 0 | 0 | 20 |
| `算法库/通用/parameter_identification_plugin.py` | 0 | 0 | 0 | 13 |
| `算法库/通用/sinusoidal_joint_motion.py` | 0 | 0 | 0 | 3 |
| `算法库/通用/trajectory_target_player.py` | 0 | 0 | 0 | 9 |
| `算法库/通用/two_point_task_space.py` | 0 | 0 | 0 | 4 |
| `软件` | 0 | 1 | 0 | 0 |
| `软件/Web桥.py` | 0 | 1 | 0 | 130 |
| `软件/ascii_text.py` | 0 | 0 | 0 | 48 |
| `软件/command_bridge.py` | 0 | 0 | 0 | 8 |
| `软件/contract.py` | 0 | 0 | 0 | 31 |
| `软件/deployment_bridge.py` | 0 | 0 | 0 | 15 |
| `软件/desktop_app.py` | 0 | 0 | 0 | 8 |
| `软件/devices/connection_bridge.py` | 0 | 0 | 0 | 4 |
| `软件/devices/safety.py` | 0 | 0 | 0 | 9 |
| `软件/devices/tracking_loop.py` | 0 | 0 | 0 | 8 |
| `软件/diagnostics_bridge.py` | 0 | 0 | 0 | 5 |
| `软件/experiment_cli.py` | 0 | 0 | 0 | 1 |
| `软件/i18n.py` | 0 | 0 | 0 | 208 |
| `软件/model_bridge.py` | 0 | 0 | 0 | 1 |
| `软件/native_host.py` | 0 | 0 | 0 | 28 |
| `软件/observation_core.py` | 0 | 0 | 0 | 19 |
| `软件/official_interface_inventory.py` | 0 | 0 | 0 | 1 |
| `软件/planning_bridge.py` | 0 | 0 | 0 | 23 |
| `软件/platform_adapters/macos.py` | 0 | 0 | 0 | 1 |
| `软件/platform_adapters/windows.py` | 0 | 0 | 0 | 11 |
| `软件/platform_adapters/windows_runtime_info.py` | 0 | 0 | 0 | 1 |
| `软件/platform_adapters/windows_viewport.py` | 0 | 0 | 0 | 13 |
| `软件/plugin_assembler.py` | 0 | 0 | 0 | 35 |
| `软件/plugin_bridge.py` | 0 | 0 | 0 | 21 |
| `软件/plugin_system.py` | 0 | 0 | 0 | 14 |
| `软件/project_registry.py` | 0 | 0 | 0 | 26 |
| `软件/run_experiment.py` | 0 | 0 | 0 | 4 |
| `软件/runloop_timers.py` | 0 | 0 | 0 | 8 |
| `软件/runtime_engine.py` | 0 | 0 | 0 | 12 |
| `软件/simulation_control.py` | 0 | 0 | 0 | 3 |
| `软件/ui_bridge.py` | 0 | 0 | 0 | 3 |
| `软件/web_app.py` | 0 | 0 | 0 | 3 |
| `软件/web_bridge.py` | 0 | 0 | 0 | 43 |
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
| `软件/风格表.json` | 0 | 1 | 118 | 0 |
| `软件/验证参数辨识.py` | 0 | 1 | 0 | 0 |
| `软件/骨架` | 0 | 1 | 0 | 0 |
| `软件/骨架/官方接口清单.py` | 0 | 1 | 0 | 96 |
| `软件/高亮桥.py` | 0 | 1 | 0 | 64 |
| `项目` | 0 | 1 | 0 | 0 |
| `项目/Panda_MJPC.json` | 0 | 0 | 13 | 0 |
| `项目/Panda_基础PD.json` | 0 | 1 | 11 | 0 |
| `项目/Panda_抓取演示.json` | 0 | 1 | 12 | 0 |
| `项目/UR10_基础PD.json` | 0 | 1 | 10 | 0 |
| `项目/UR10e_基础PD.json` | 0 | 1 | 12 | 0 |
| `项目/UR5e_PD跟踪实验.json` | 0 | 1 | 14 | 0 |
| `项目/UR5e_PID跟踪实验.json` | 0 | 1 | 10 | 0 |
| `项目/UR5e_基础PD.json` | 0 | 1 | 11 | 0 |
| `项目/iiwa14_基础PD.json` | 0 | 1 | 11 | 0 |
| `项目/ur5e_pd_gravity_ff.json` | 0 | 0 | 10 | 0 |
| `项目/ur5e_pd_gravity_ff_waypoint_tracking.json` | 0 | 0 | 13 | 0 |
| `项目/ur5e_pd_plain.json` | 0 | 0 | 10 | 0 |
| `项目/ur5e_pd_waypoint_tracking.json` | 0 | 0 | 13 | 0 |
| `项目/ur5e_pid_plain.json` | 0 | 0 | 11 | 0 |
| `项目/ur5e_pid_waypoint_tracking.json` | 0 | 0 | 12 | 0 |
| `项目/xArm7_基础PD.json` | 0 | 1 | 12 | 0 |
| `项目/索引.json` | 0 | 1 | 26 | 0 |

## 下一步

实施批次和验收标准见 [迁移计划](naming-migration-plan.md)。
完整名称与行号可用 `--json-report /tmp/yubi-naming-audit.json` 导出。
