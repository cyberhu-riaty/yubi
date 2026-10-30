# 实验注册接口

GUI、3D 渲染和 MuJoCo 主循环是稳定平台；这里的 JSON 只描述一次实验要组合什么。

```text
实验 JSON
├─ model             模型路径
├─ project           项目装配清单
├─ controllers       真正写 data.ctrl 的控制器
├─ plugins           记录、辨识等辅助插件
├─ trajectory        轨迹类型与来源说明
├─ initial_state     初始状态
├─ stop_condition    停止条件
├─ recording         记录策略
└─ result            结果目录与文件
```

## 运行

```powershell
# 可以启动时直接指定实验；进入 GUI 后点击“开始”即可自动记录、停止和导出
& ".venv\Scripts\python.exe" "软件\主程序窗口.py" --实验 ur5e_pd_tracking

# 无界面自动运行并导出 states.csv / metrics.json / curves.html
& ".venv\Scripts\python.exe" "软件\run_experiment.py" ur5e_pd_tracking

# 查看已注册实验
& ".venv\Scripts\python.exe" "软件\run_experiment.py" --列出
```

普通方式打开 GUI 时，也可以在顶部“实验”下拉框中选择并加载。加载只准备模型、
项目、控制器和目标，不会擅自启动；仍由用户点击原来的“开始”按钮。达到实验 JSON
声明的停止时间后，平台会自动暂停，并把结果写入 `输出/实验/`。

GUI 模式使用实时固定步进器，按模型 timestep 节拍显示；无界面实验使用
不等待墙钟的固定一步步进器，按最快速度计算。两者都保证一次控制对应一个物理步。

## UR5e 三组控制对比实验

下面三组使用完全相同的模型、初始状态、固定关节目标、12 秒停止条件和 100 Hz
结果采样。三组共用 ``KP=86``、``KD=70``；PID 组只增加 ``KI=40``，重力
前馈组只增加由 MuJoCo 模型计算的纯重力力矩。

| 注册名 | GUI 显示名 | 控制结构 |
|---|---|---|
| `ur5e_pd_plain` | PD定点控制 | `Kp·e - Kd·qvel` |
| `ur5e_pid_plain` | PID定点控制 | `Kp·e + Ki∫e dt - Kd·qvel` |
| `ur5e_pd_gravity_ff` | PD＋重力前馈定点控制 | `Kp·e - Kd·qvel + τg(q)` |

原来的 `ur5e_pd_tracking` 包含 `qfrc_bias` 补偿，适合作为运行示例，但不应拿来
解释“是否加入重力前馈”的单变量对比。旧的 `ur5e_pid_tracking` 实验入口已移除；
它引用的控制器源码与项目配置仍保留，供以后复用。

## 新增控制算法

1. 在 `算法库/` 新增一个继承 `插件系统.控制插件` 的文件。
2. 在实验专用项目 JSON 的 `算法` 中写入插件文件名。
3. 复制一个实验 JSON，修改 `key/controllers/project`。
4. 运行 `工具/验证/实验注册自检.py`。

不需要修改 GUI、渲染模块、`启动.py` 或命令桥。复杂 Python 实验也可以通过
`ExperimentRegistry.register()` 注册工厂，不必局限于 JSON。
