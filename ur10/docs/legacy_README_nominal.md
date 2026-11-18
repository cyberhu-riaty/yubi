# 未辨识 UR10 模型对比实验

该副本程序使用：

`C:\Users\asteroid\Desktop\xml-models\ur10\ur10\ur10.xml`

它不会修改原有辨识模型程序，也不会修改该 XML 文件。

为保证与辨识模型实验公平，程序加载未辨识 XML 后，仅在运行内存中将其经验 `damping` 和 `frictionloss` 清零，保留原始质量、质心、惯量和 `armature=0.1`，然后分别计算：

1. 未辨识模型，不加摩擦；
2. 未辨识模型，加入与辨识模型实验相同的论文非线性摩擦。

运行全部轨迹：

```powershell
python .\ur10_experiment\ur10_nominal_inverse_dynamics_experiment.py
```

结果默认保存到：

`ur10_experiment/results_nominal/`

其中 `model_comparison.csv` 会将当前未辨识模型结果与 `results/metrics_summary.csv` 中的辨识模型结果进行并列比较。
