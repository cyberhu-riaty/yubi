# UR10 辨识动力学与非线性摩擦

本目录保留原有模型和离线实验，并提供可复用的非线性摩擦接口。摩擦系数沿用历史实验脚本中的六关节辨识值；没有重新辨识参数。

## 目录

| 路径 | 内容 |
| --- | --- |
| `models/` | URDF、MuJoCo XML 与网格资源；XML 和网格的相对路径保持完整 |
| `friction/` | 摩擦公式、逆动力学和正向仿真逐步接口 |
| `configs/` | 文件化的摩擦模型声明、辨识系数与动力学/测量参数示例 |
| `examples/` | 最小正向仿真示例 |
| `tests/` | 历史结果与正向施力验证 |
| `experiments/legacy/scripts/` | 原有 Python、MATLAB 离线实验脚本 |
| `experiments/legacy/outputs/` | 原有 MAT、CSV、图片结果，按实验类型保留原子目录 |
| `experiments/reproduce_torque_figures.py` | 调用封装摩擦，重画力矩对比图及误差图；也可选重新运行 MuJoCo 刚体逆动力学 |
| `experiments/reproduced/` | 新生成的 MAT 与图，按刚体力矩来源区分，不覆盖历史图片 |
| `docs/` | 原有实验说明（其中旧 Windows 路径是历史记录） |

## 摩擦模型

按 `friction.JOINT_NAMES` 的顺序输入六个关节速度，单位为 rad/s。输出对应关节需要克服摩擦的力矩，单位为 N·m：

```text
tau_f = (Fc + Fv * abs(dq) ** alpha) * sign(dq) + B
```

公式严格沿用原实验，`dq=0` 时输出 `B`。它是辨识公式的偏置项，不等同于完整的静摩擦或粘滑模型。没有对零速做平滑或阈值处理。

`models/ur10_extfric.xml` 的 `damping` 和 `frictionloss` 为零，应与外部摩擦接口搭配使用。`models/ur10.xml` 和 `models/ur10_normal.xml` 自带简化摩擦，接口会拒绝直接用于它们，以免重复计算。`models/scene.xml` 仍包含 `ur10.xml`，用于查看原有场景，不会自动启用非线性摩擦。

## 使用

在本目录下使用工作区现有虚拟环境：

```bash
../.venv/bin/python examples/run_friction.py
../.venv/bin/python -m unittest discover -s tests -v
```

Python 接口示例：

```python
import mujoco
from friction import UR10Friction, inverse_dynamics, step_with_friction

model = mujoco.MjModel.from_xml_path("models/ur10_extfric.xml")
data = mujoco.MjData(model)
law = UR10Friction()

tau_f = law.torque(data.qvel[law.validate_model(model)])
tau_required = inverse_dynamics(model, q, dq, ddq, law)
step_with_friction(model, data, law)
```

`inverse_dynamics` 接受形状为 `(6,)` 或 `(样本数, 6)` 的状态，返回所需电机力矩 `mj_inverse + tau_f`。`step_with_friction` 在每一步把 `-tau_f` 加到关节外力中，执行一次 `mj_step`，随后恢复调用前的 `qfrc_applied`；已有外力不会被覆盖。需要摩擦的每一步都必须调用这个接口；直接调用 `mj_step` 不会施加外部摩擦。

历史脚本的模型和输出默认路径已调整到当前目录结构。原始 RTDE 轨迹数据不在本目录，运行历史离线实验时仍需用 `--data-dir` 指定数据位置。现有 MAT 结果用于数值回归验证。

## 重新计算力矩并生成对比图、误差图

打开 `experiments/reproduce_torque_figures.py`，在末尾 `CONFIG = RunConfig(...)` 中设置输入 MAT 目录、两个机器人 XML、摩擦模型及系数文件、可选动力学参数文件、输出根目录与绘图选项。直接运行即使用这组配置。输出根目录下按 `rigid_source` 建立子目录；命令行只覆盖对应配置项。新格式见 [文件配置接口](docs/文件配置接口.md)。内置幂律/库仑黏性模型用 JSON，自定义无状态速度摩擦模型可通过 Python 文件加载。默认文件复现原参数。

存档的 `results_all_combinations/*.mat` 包含滤波后的 `q/dq/ddq`、刚体力矩和实测电流。以下命令读取存档刚体力矩，再调用配置文件加载的摩擦模型重新计算摩擦并相加，生成五种模型组合的力矩对比图和误差图：

```bash
../.venv/bin/python experiments/reproduce_torque_figures.py --trajectory 0
```

省略 `--trajectory 0` 则处理全部存档轨迹；用 `--mode identified_friction_effect` 等模式名可只画一组比较。输出在 `experiments/reproduced/archived_rigid/`，包括重新计算的 MAT 和与旧 MATLAB 脚本同名的 `*_torque.png`、`*_torque_error.png`。存档刚体力矩加封装摩擦所得曲线与历史结果一致。新脚本使用 Matplotlib 复刻旧 MATLAB 图的六关节布局、曲线、颜色、RMSE/Bias 和命名；不同绘图引擎的字体、图例位置及像素尺寸可能不同。

若需要从存档的 `q/dq/ddq` 重新运行 MuJoCo 刚体逆动力学，可加 `--rigid-source recompute`，结果存入 `experiments/reproduced/recomputed_rigid/`。第 1、7 条轨迹部分采样点的刚体逆动力学重算值与历史存档差异较大，故此模式的图不保证与旧图相同；封装摩擦项本身仍一致。

若要从原始 RTDE 记录重新做时间戳去重、滤波、求导和逆动力学，先取得 `ur_rtde_newtraj_2021_*_data_noload.mat`，再运行 `experiments/legacy/scripts/ur10_all_model_combinations.py --data-dir <数据目录> --output-dir <新输出目录>`。现有 `experiments/legacy/scripts/plot_results_in_matlab.m` 可使用 MATLAB 绘制原样式。
