# UR10 辨识模型逆动力学验证

该程序完成第一阶段实验：将真机实测轨迹逐采样点写入 MuJoCo，计算辨识模型需要的关节力矩，加入论文式（3-2）的非线性摩擦，再与实测电流换算的关节力矩比较。

## 运行

在本目录的上一级执行：

```powershell
python .\ur10_experiment\ur10_inverse_dynamics_experiment.py
```

默认使用：

- 模型：`C:\Users\asteroid\Desktop\ur10\ur10_extfric.xml`
- 数据：`C:\Users\asteroid\Desktop\ur10数据-2106采集\ur10数据-2106采集`
- 全部10条无负载轨迹

只分析第0条轨迹：

```powershell
python .\ur10_experiment\ur10_inverse_dynamics_experiment.py --trajectory 0
```

## 计算内容

1. 对重复的 RTDE 时间戳保留最后一条记录。
2. 根据时间戳确定采样率，当前数据约为125 Hz。
3. 实测电流采用四阶10 Hz零相位低通滤波。
4. 实测位置先低通，再用 Savitzky-Golay 多项式重构一致的 `q/dq/ddq`。
5. 调用 `mujoco.mj_inverse` 计算不含外挂摩擦的逆动力学力矩。
6. 按论文式（3-2）加入 `Fc/Fv/B/alpha` 非线性摩擦。
7. 使用偏心负载辨识的关节力矩系数 `K` 完成电流与力矩换算。

## 输出

结果写入 `ur10_experiment/results/`：

- `metrics_by_trajectory.csv`：每条轨迹、每个关节的 RMSE、MAE、最大误差和 R²。
- `metrics_summary.csv`：10条轨迹的平均指标。
- `experiment_metadata.json`：模型路径、参数、滤波设置和各数据集采样信息。
- `trajectory_*_torque.png`：实测估算力矩、无摩擦预测、非线性摩擦预测和 UR `target_M`。
- `trajectory_*_current.png`：实测电流与两种模型预测电流。

## 说明

这是逆动力学离线验证，不调用 `mj_step`，也不使用 XML 中的位置伺服控制器。每个采样点独立计算。摩擦在逆动力学中作为电机需要克服的力矩，因此与 `qfrc_inverse` 相加。
