# Universal Robots UR10（MJCF）

驭臂模型库里的 **UR10（CB3 世代）** 模型，与 `universal_robots_ur10e` 并列。
运动学、惯量、限位和外观都取 UR10 的官方值，不是 UR10e。

## 来源

- 上游仓库：[ros-industrial/universal_robot](https://github.com/ros-industrial/universal_robot) → `ur_description` 1.5.0
- 许可证：BSD-3-Clause（见 `LICENSE`）
- commit：`39ad110d8f2e8f66856a201cca88aa7a7025e3eb`（2026-07-20）
- 参数文件：`config/ur10/` 下的 `default_kinematics.yaml`、`joint_limits.yaml`、`physical_parameters.yaml`、`visual_parameters.yaml`
- 网格：`meshes/ur10/visual/*.dae`（视觉）与 `meshes/ur10/collision/*.stl`（碰撞）

## 转换步骤（可复现）

1. `xacro urdf/ur10.xacro` → `ur10.urdf`（全部用默认参数，不做标定覆盖）
2. 视觉 DAE 按材质拆成多个 OBJ（trimesh），保留官方配色；碰撞用官方 STL
3. MuJoCo `MjSpec` 读入 URDF（`discardvisual="false"`）并写出 MJCF
4. 手工补齐 URDF 表达不了的东西：
   - `base_link_inertia` 的 **4.0 kg** 根杆惯量（MuJoCo 的 URDF 读入器会丢掉无质量根杆上的惯量）
   - 关节 `armature=0.1`、阻尼（肩 10 / 肘 5 / 腕 2）
   - 6 个位置伺服执行器（`kp=5000, kv=500`）与力矩上限 330/330/150/56/56/56 N·m
   - `home` 关键帧、末端站点 `attachment_site`（法兰外 0.1 m 的 TCP）
5. `工具/import_model.py` 生成 `ur10_torque.xml`：执行器换成 `<motor>`，`ctrl` 直接是关节力矩（N·m）
6. 用与 `算法库/通用/关节pd控制.py` 相同的 PD 算式做闭环验证：**残差 0.018°**（判定阈值 0.5°）

## 文件

| 文件 | 用途 |
|---|---|
| `ur10.xml` | 位置伺服基模型（`ctrl` = 目标关节角，单位 rad） |
| `ur10_torque.xml` | 力矩模型（**推荐加载**，`ctrl` = 关节力矩，单位 N·m） |
| `scene.xml` | 独立场景（自带地面 / 灯光 / 天空盒），用于单独打开模型 |
| `assets/` | 视觉 OBJ 与碰撞 STL |
| `模型信息.json` | 模型库索引用的显示名 / 许可 / 说明（`工具/import_model.py --索引` 会读它） |

在驭臂里加载纯机械臂 XML 时，`软件/模型加载.py` 会自动把 `模型/公共场景.xml`
（地面、灯光、棋盘格材质）挂上，所以一般不需要 `scene.xml`。

## 与 menagerie `ur10e` 模型的差别

- 尺寸和惯量是 UR10 官方值（`d1=127.3 mm`、`a2=612 mm`、`a3=572.3 mm`、`d4=163.941 mm`……），
  不是 UR10e 的 181 mm 基座 / 更长的腕部
- 碰撞体用官方 STL 的凸包，并**关闭了机械臂自碰撞**：STL 凸包在关节处互相重叠，
  保留自碰撞会让位置伺服在折弯姿态被假接触推飞（实测漂移 3.8 rad）。
  与地面、外部物体的碰撞仍然有效（碰撞体 `contype=2, conaffinity=1`）
- 颜色直接取官方 DAE 材质（CB3 的深灰 + 蓝），没有重新调色

## 注意

- `qpos=0` 是 URDF 的零位（手臂几乎贴地）；正常使用请走 `home` 关键帧，
  外壳加载模型时会自动重置到 `home`
- elbow 限位沿用上游 MoveIt 的安全限位 ±180°，其余关节 ±360°
- 模型没有夹爪；末端执行器请挂在 `attachment_site`（wrist_3 坐标系 +z 方向 0.1 m）

## 许可

本模型沿用上游 BSD-3-Clause 许可，见同目录 `LICENSE`。
