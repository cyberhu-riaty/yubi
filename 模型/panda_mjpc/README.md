# Panda（MJPC 任务模型）

来源：[google-deepmind/mujoco_mpc](https://github.com/google-deepmind/mujoco_mpc) 的
`mjpc/tasks/panda`（main 分支）与 `mjpc/tasks/common.xml`。

## 文件

| 文件 | 说明 |
|---|---|
| `task.xml` | MJPC 的 Panda 抓取任务场景：Panda + 夹爪 + 方块 + mocap 目标 + 传感器 |
| `panda_modified.xml` | 由 `panda.xml.patch` 打进 Menagerie 的 `franka_emika_panda/panda.xml` 生成 |
| `common.xml` | MJPC 公共场景设置；`task.xml` 里原来的 `../common.xml` 已改为同目录 `common.xml` |
| `LICENSE` | Apache-2.0（MJPC） |

网格资源**没有复制**：`panda_modified.xml` 的 `meshdir` 指向
`../franka_emika_panda/assets`，复用仓库里已有的 Panda 网格（避免重复 33 MB）。
这份网格来自 Menagerie Panda，Apache-2.0，见 `模型/franka_emika_panda/LICENSE`。

## 怎么生成的（可复现）

```bash
cp 模型/franka_emika_panda/panda.xml /tmp/panda_modified.xml
cd /tmp
curl -sL https://raw.githubusercontent.com/google-deepmind/mujoco_mpc/main/mjpc/tasks/panda/panda.xml.patch \
  | patch -p1
```

然后把生成的 `panda_modified.xml`、MJPC 的 `task.xml` 与 `common.xml` 拷进本目录，
并做两处路径调整：

- `task.xml`：`<include file="../common.xml"/>` → `<include file="common.xml"/>`
- `panda_modified.xml`：`meshdir="assets"` → `meshdir="../franka_emika_panda/assets"`

## 实测

- `nq=16 / nv=15 / nu=7`，`timestep=0.003`，`nsensor=11`，1 个 `home` 关键帧。
- 执行器：6 个末端 site 力/力矩执行器（`site="eeff"`，`ctrlrange=-1..1`）
  + 1 个夹爪 `intvelocity`（`actuator8`）。
- 传感器：`Reach`、`Bring`、`hand`、`box`、`box1`、`box2`、`target`、
  `target1`、`target2`、`trace0`、`trace1`。

## 重要：这不是关节力矩模型

- **不要**用 `算法库/通用/关节pd控制.py`（它要求 `nu==nv==nq`）。
- 这是给 MJPC / 移植版 MPC 用的：动作是末端 6 维力/力矩 + 夹爪，不是 7 个关节力矩。
- 3D 视口可以直接渲染；但它比 `panda_torque.xml` 多了夹爪、方块、目标点。

## 许可

- MJPC 的 `task.xml` / `panda_modified.xml` / `common.xml`：Apache-2.0，见 `LICENSE`。
- 网格与材质：`模型/franka_emika_panda/`（Menagerie Panda），Apache-2.0，见该目录 `LICENSE`。

## 模型库索引

`模型/模型库.json` 里的 `panda_mjpc` 是**手工条目**（类别 `arm_task`，`可控制: false`），
`软件/模型桥.py` 的过滤已放行 `arm_task`，所以它能在资产库显示、点选加载。

⚠️ 重跑 `工具/import_model.py --全部` 会重写 `模型/模型库.json`，这条需要补回。
