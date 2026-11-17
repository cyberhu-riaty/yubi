# 内部代码命名迁移计划与验收状态

2026-11-17：用户要求的代码英文化范围已完成，跨平台真机验证暂不计入。逐批历史证据见 [执行记录](english-migration-execution.md)。

| 范围 | 状态 |
| --- | --- |
| Python、TypeScript、CSS 内部标识符 | 严格扫描非 ASCII 数量为 0 |
| 自有源码文件与目录 | 严格扫描非 ASCII 数量为 0；运行代码在 `runtime/`，兼容适配文件在 `runtime/legacy/` |
| JSON 机器键 | 非 ASCII 数量为 0；旧项目、设置与参数仍可读取 |
| 原生宿主内部诊断键与动作队列 | 已统一英文，生产方和消费者同步；中文显示文字保留 |
| 旧插件导入与协议 | 显式适配保留；v21 契约和命令 JSON 格式由固定回归检查守护 |
| 命名门禁 | `scripts/check_naming.py` 默认严格模式；历史基线为空 |

## 命名规则

变量、函数、类、属性、文件、源码目录及新机器键使用规范英文 ASCII。中文界面文案、注释、文档、用户数据、显示标签和明确隔离的旧协议/导入别名允许保留中文。字符串键已分类，不能把界面资源或兼容字段当成新变量，也不能用扩大基线隐藏新问题。

运行目录采用 `runtime/`，保留现有扁平 Python 导入与消息类身份。此次只调整命名和路径；进一步把实现改成完整 Python 安装包属于后续架构工作，不是英文化验收的前提。

## 日常验收

```bash
python scripts/check_naming.py
python scripts/audit_naming.py --strict --report docs/naming-inventory.md
python -m unittest discover -s scripts/tests
node --test scripts/tests/test_connection.cjs scripts/tests/test_frontend_state.cjs scripts/tests/test_wire_compatibility.cjs
python tools/selfchecks/contract_selfcheck.py --brief
python run_yubi.py --check
```

前端修改另在 `frontend/` 运行 `npm run typecheck`、`npm run build`；生成源码先改 `tools/generate_frontend_assets.py` 再重新生成。源码和发行包应从只含已提交文件的副本验证。

## 单独登记的后续工作

- Windows 真机启动、窗口与打包验证按用户要求暂缓。
- 真实辨识插件“采样/辨识”与前端“开始/停止”的既有动作漂移属于功能问题，尚未修改，需单独做真实插件端到端核对。
- GitHub Actions 工作流仍为本地草稿，现有凭据缺少 workflow 权限；没有声称自动 CI 已上线。本地严格检查与测试可直接运行。
- 第三方模型、字体、外部 `ur10/` 源码、用户报告、文档和编译产物不属于源码命名扫描范围。模型数据路径保持兼容。
