"""Panda_官方MPC移植.py —— 把 MJPC 的 Panda 任务"抄"成 Python 插件（第一版）。

来源与边界
----------------------------------------------------------------------------
算法思想来自 `google-deepmind/mujoco_mpc` 的 Panda 任务（Apache-2.0）：
    · 残差：hand-box、box1-target1、box2-target2（见 `mjpc/tasks/panda/panda.cc`）；
    · 动作：6 个末端力/力矩 + 1 个夹爪，共 7 维（MJPC 的 task.xml）；
    · 规划：随机采样 + `mujoco.rollout` 批量推演，选 cost 最小的一条。
这里**不是**官方 C++ 代码的绑定，而是按同一套残差/动作语义重写的 Python 版；
先保证能跑、能看、能调，再谈 CEM/spline/iLQG。

为什么要有规划线程
----------------------------------------------------------------------------
`每步控制()` 在 500 Hz 的仿真线程里，一次规划约 5–15 ms；直接在里面算会卡住
物理循环。所以这里：
    · 规划线程（默认 20 Hz）读状态快照 → 采样 → 选动作；
    · 仿真线程只读"最新动作"，超过 `超时秒` 没更新就回退到 0 力矩；
    · 两个线程不共享 `MjData`，只共享状态数组和动作（都加锁/拷贝）。

这个模型不是关节力矩模型
----------------------------------------------------------------------------
`模型/panda_mjpc/task.xml` 的 `nu=7` 是 6 个末端 wrench + 1 个夹爪，
`nq=16 / nv=15`（含方块自由度和手指）。所以：
    · 不能挂 `关节pd控制`；
    · 本插件只接受带 `hand/box/box1/box2/target1/target2` 传感器的 MJPC 任务模型；
    · 动作直接写 `data.ctrl[:]`，不做 Jacobian 映射。
"""
from __future__ import annotations

import threading
import time

import numpy as np
import mujoco
import mujoco.rollout as mjroll

import plugin_system as plugin
from plugin_system import ControlPlugin, step_handler

# MJPC Panda 任务里残差/动作依赖的传感器；少一个就没法算 cost
需要的传感器 = ("hand", "box", "box1", "box2", "target1", "target2")
状态规格 = int(mujoco.mjtState.mjSTATE_FULLPHYSICS)


def _传感器切片(模型: mujoco.MjModel) -> dict[str, tuple[int, int]]:
    切片 = {}
    for 名 in 需要的传感器:
        号 = mujoco.mj_name2id(模型, mujoco.mjtObj.mjOBJ_SENSOR, 名)
        if 号 < 0:
            raise ValueError(f"缺少传感器 {名}")
        起 = int(模型.sensor_adr[号])
        切片[名] = (起, 起 + int(模型.sensor_dim[号]))
    return 切片


def _残差(切片: dict[str, tuple[int, int]], 传感器数据: np.ndarray) -> np.ndarray:
    """(…, nsensordata) -> (…, 9)，对应 panda.cc 的三组残差。"""
    取 = lambda 名: 传感器数据[..., 切片[名][0]:切片[名][1]]
    return np.concatenate([
        取("hand") - 取("box"),
        取("box1") - 取("target1"),
        取("box2") - 取("target2"),
    ], axis=-1)


class _规划器:
    """独立线程里的随机采样 MPC；只碰自己的 MjData。"""

    def __init__(self, 模型: mujoco.MjModel, 参数: dict) -> None:
        self.模型 = 模型
        self.数据 = mujoco.MjData(模型)
        self.状态规格 = 状态规格
        self.状态尺寸 = int(mujoco.mj_stateSize(模型, self.状态规格))
        self.切片 = _传感器切片(模型)

        self._锁 = threading.Lock()
        self._状态: np.ndarray | None = None
        self._mocap_pos: np.ndarray | None = None
        self._mocap_quat: np.ndarray | None = None
        self._新状态 = threading.Event()
        self._停止 = threading.Event()

        self._动作 = np.zeros(int(模型.nu), dtype=float)
        self._动作时刻 = 0.0
        self._统计 = {
            "规划次数": 0.0,
            "规划耗时ms": 0.0,
            "cost": 0.0,
            "hand-box(mm)": 0.0,
            "box-target(mm)": 0.0,
            "cost_手": 0.0,
            "cost_目标": 0.0,
            "cost_动作": 0.0,
            "动作范数": 0.0,
            "动作峰值": 0.0,
            "夹爪": 0.0,
            "动作年龄ms": 0.0,
            "错误次数": 0.0,
        }
        self._错误 = ""
        self._参数 = dict(参数)
        # CEM 的均值/标准差跨规划保留（暖启动）；换模型/改 horizon 时形状不符就重置
        self._均值: np.ndarray | None = None
        self._标准差: np.ndarray | None = None
        self._rollout = mjroll.Rollout(nthread=0)
        self._线程 = threading.Thread(target=self._循环, daemon=True,
                                       name="Panda-MPC规划")
        self._线程.start()

    # ---------- 仿真线程调用 ----------
    def 更新状态(self, 状态: np.ndarray, mocap_pos, mocap_quat) -> None:
        with self._锁:
            self._状态 = np.array(状态, dtype=float, copy=True)
            self._mocap_pos = None if mocap_pos is None else np.array(mocap_pos, copy=True)
            self._mocap_quat = None if mocap_quat is None else np.array(mocap_quat, copy=True)
        self._新状态.set()

    def 取动作(self) -> tuple[np.ndarray, float, dict]:
        with self._锁:
            动作 = self._动作.copy()
            年龄 = (time.monotonic() - self._动作时刻) * 1000.0 if self._动作时刻 else 1e9
            统计 = dict(self._统计)
            统计["错误信息"] = self._错误
            return 动作, 年龄, 统计

    def 设参数(self, 名: str, 值: float) -> None:
        with self._锁:
            self._参数[名] = 值

    def 停止(self) -> None:
        self._停止.set()
        self._新状态.set()
        if self._线程.is_alive():
            self._线程.join(timeout=2.0)

    # ---------- 规划线程 ----------
    def _循环(self) -> None:
        序 = 0
        while not self._停止.is_set():
            if not self._新状态.wait(0.2):
                continue
            self._新状态.clear()
            with self._锁:
                状态 = None if self._状态 is None else self._状态.copy()
                mocap_pos = None if self._mocap_pos is None else self._mocap_pos.copy()
                mocap_quat = None if self._mocap_quat is None else self._mocap_quat.copy()
                参数 = dict(self._参数)
            if 状态 is None:
                continue
            开始 = time.perf_counter()
            try:
                mujoco.mj_setState(self.模型, self.数据, 状态, self.状态规格)
                if mocap_pos is not None and self.数据.mocap_pos.size:
                    self.数据.mocap_pos[:] = mocap_pos
                if mocap_quat is not None and self.数据.mocap_quat.size:
                    self.数据.mocap_quat[:] = mocap_quat
                mujoco.mj_forward(self.模型, self.数据)

                采样数 = max(2, int(参数.get("采样数", 48)))
                步数 = max(1, int(参数.get("规划步数", 20)))
                迭代数 = max(1, int(参数.get("CEM迭代", 2)))
                精英比例 = min(0.9, max(0.05, float(参数.get("精英比例", 0.2))))
                初始标准差 = max(0.01, float(参数.get("采样标准差", 0.35)))
                手权重 = float(参数.get("手方块权重", 5.0))
                目标权重 = float(参数.get("方块目标权重", 1.0))
                控制权重 = float(参数.get("控制权重", 0.001))
                权重 = np.array([手权重] * 3 + [目标权重] * 6, dtype=float)

                下界 = np.asarray(self.模型.actuator_ctrlrange[:, 0], dtype=float)
                上界 = np.asarray(self.模型.actuator_ctrlrange[:, 1], dtype=float)
                幅度 = np.maximum(上界 - 下界, 1e-9)
                nu = int(self.模型.nu)

                # 暖启动：上一次的最优序列往前挪一步；形状变了（改 horizon/换模型）就重置
                if self._均值 is None or self._均值.shape != (步数, nu):
                    self._均值 = np.zeros((步数, nu), dtype=float)
                    self._标准差 = 幅度[None, :] * 初始标准差
                else:
                    self._均值 = np.vstack([self._均值[1:], self._均值[-1:]])

                rng = np.random.default_rng(序)
                序 += 1
                输出状态 = np.empty((采样数, 步数, self.状态尺寸), dtype=float)
                输出传感器 = np.empty((采样数, 步数, int(self.模型.nsensordata)), dtype=float)
                最优代价 = float("inf")
                最优动作 = None
                最优传感器 = None

                # CEM：采样 → 选精英 → 更新均值/标准差；每次规划迭代几次
                for 迭代 in range(迭代数):
                    噪声 = rng.standard_normal((采样数, 步数, nu))
                    动作们 = np.clip(
                        self._均值[None, :, :] + 噪声 * self._标准差[None, :, :],
                        下界, 上界)
                    if 迭代 == 0:
                        动作们[0] = 0.0          # 保一条"不动"的基线
                    self._rollout.rollout(
                        self.模型, self.数据, np.tile(状态, (采样数, 1)),
                        control=动作们, nstep=步数,
                        state=输出状态, sensordata=输出传感器,
                    )
                    残差 = _残差(self.切片, 输出传感器)              # (N,H,9)
                    代价 = (np.sum(权重 * 残差 * 残差, axis=(1, 2))
                            + 控制权重 * np.sum(动作们 * 动作们, axis=(1, 2)))
                    本次最优 = int(np.argmin(代价))
                    if float(代价[本次最优]) < 最优代价:
                        最优代价 = float(代价[本次最优])
                        最优动作 = np.array(动作们[本次最优], dtype=float, copy=True)
                        最优传感器 = np.array(输出传感器[本次最优], dtype=float, copy=True)

                    精英数 = max(1, int(采样数 * 精英比例))
                    精英 = 动作们[np.argsort(代价)[:精英数]]
                    self._均值 = np.clip(精英.mean(axis=0), 下界, 上界)
                    self._标准差 = np.clip(
                        精英.std(axis=0) + 0.02 * 幅度[None, :],
                        0.05 * 幅度[None, :], 0.75 * 幅度[None, :])

                if 最优动作 is None or 最优传感器 is None:
                    raise RuntimeError("CEM 没有产出可用动作")
                # 下一次从这个最优序列暖启动（上面会再往前挪一步）
                self._均值 = np.array(最优动作, dtype=float, copy=True)
                手到方块 = float(np.linalg.norm(
                    最优传感器[-1, self.切片["hand"][0]:self.切片["hand"][1]]
                    - 最优传感器[-1, self.切片["box"][0]:self.切片["box"][1]]))
                # 把总 cost 拆开，界面才能回答"为什么"：
                #   cost_手   = 手到方块残差（3 维）
                #   cost_目标 = 方块两侧到目标（6 维）
                #   cost_动作 = 动作大小正则
                最优残差 = _残差(self.切片, 最优传感器)              # (H,9)
                手代价 = float(np.sum(最优残差[:, :3] ** 2)) * 手权重
                目标代价 = float(np.sum(最优残差[:, 3:] ** 2)) * 目标权重
                动作代价 = float(np.sum(最优动作 ** 2)) * 控制权重
                方块到目标 = float(
                    (np.linalg.norm(最优残差[-1, 3:6])
                     + np.linalg.norm(最优残差[-1, 6:9])) / 2.0)
                动作范数 = float(np.linalg.norm(最优动作[0, :6]))
                夹爪 = float(最优动作[0, 6])
            except Exception as 异常:                                  # noqa: BLE001
                with self._锁:
                    self._统计["错误次数"] += 1
                    self._错误 = f"{type(异常).__name__}: {异常}"
                self._停止.wait(0.05)
                continue

            with self._锁:
                self._动作 = np.array(最优动作[0], dtype=float, copy=True)
                self._动作时刻 = time.monotonic()
                self._统计["规划次数"] += 1
                self._统计["规划耗时ms"] = (time.perf_counter() - 开始) * 1000.0
                self._统计["cost"] = float(最优代价)
                self._统计["hand-box(mm)"] = 手到方块 * 1000.0
                self._统计["box-target(mm)"] = 方块到目标 * 1000.0
                self._统计["cost_手"] = 手代价
                self._统计["cost_目标"] = 目标代价
                self._统计["cost_动作"] = 动作代价
                self._统计["动作范数"] = 动作范数
                self._统计["动作峰值"] = max(
                    float(self._统计.get("动作峰值", 0.0)), 动作范数)
                self._统计["夹爪"] = 夹爪
                self._统计["动作年龄ms"] = 0.0
                self._错误 = ""

            # 限频：规划频率默认 20 Hz；算得快也不要空转烧 CPU
            周期 = 1.0 / max(1.0, float(参数.get("规划频率", 20.0)))
            剩余 = 周期 - (time.perf_counter() - 开始)
            if 剩余 > 0:
                self._停止.wait(剩余)


class Panda官方MPC插件(ControlPlugin):
    name = "Panda 官方 MPC（移植）"
    version = "0.2"
    english_name = "Panda MJPC port (CEM)"
    description = "移植 MJPC 的 Panda 任务：9 维残差 + CEM 采样 + mujoco.rollout；7 维末端力/力矩动作。"
    author = "数字样机（算法来源：google-deepmind/mujoco_mpc，Apache-2.0）"
    takes_control = True

    # ---- 可调参数（界面滑杆直接改；规划线程每次规划读一次）----
    采样数 = 48
    规划步数 = 20
    CEM迭代 = 2
    精英比例 = 0.2
    采样标准差 = 0.35
    手方块权重 = 5.0
    方块目标权重 = 1.0
    控制权重 = 0.001
    规划频率 = 20.0
    超时秒 = 0.25

    def __init__(self) -> None:
        self._规划器: _规划器 | None = None
        self._模型 = None
        self._启动失败 = ""
        self._回退次数 = 0
        self._步数 = 0
        self._状态缓冲: np.ndarray | None = None

    # ------------------------------------------------------------------
    def check_model_compatibility(self, 模型) -> str:
        if int(getattr(模型, "nu", 0)) != 7:
            return f"需要 MJPC Panda 的 7 维动作（本模型 nu={getattr(模型, 'nu', 0)}）"
        for 名 in 需要的传感器:
            if mujoco.mj_name2id(模型, mujoco.mjtObj.mjOBJ_SENSOR, 名) < 0:
                return f"缺少传感器「{名}」——这不是 MJPC 的 Panda 任务模型"
        return ""

    def _启动(self, 模型) -> bool:
        try:
            self._规划器 = _规划器(模型, self._参数快照())
            self._状态缓冲 = np.empty(
                int(mujoco.mj_stateSize(模型, 状态规格)), dtype=float)
            return True
        except Exception as 异常:                                      # noqa: BLE001
            self._启动失败 = f"{type(异常).__name__}: {异常}"
            print(f"⚠ 【{self.name}】启动失败：{self._启动失败}", flush=True)
            return False

    def _参数快照(self) -> dict:
        return {
            "采样数": self.采样数,
            "规划步数": self.规划步数,
            "CEM迭代": self.CEM迭代,
            "精英比例": self.精英比例,
            "采样标准差": self.采样标准差,
            "手方块权重": self.手方块权重,
            "方块目标权重": self.方块目标权重,
            "控制权重": self.控制权重,
            "规划频率": self.规划频率,
        }

    def set_parameter(self, 名: str, 值: float) -> str:
        原因 = super().set_parameter(名, 值)
        if not 原因 and self._规划器 is not None:
            self._规划器.设参数(名, getattr(self, 名))
        return 原因

    # ------------------------------------------------------------------
    @step_handler
    def step(self, event: plugin.messages.StepEvent) -> bool:
        模型, 数据 = event.model, event.data
        if self._规划器 is None and not self._启动失败:
            self._启动(模型)
        if self._规划器 is None:
            return False

        self._步数 += 1
        try:
            mujoco.mj_getState(模型, 数据, self._状态缓冲, 状态规格)
            self._规划器.更新状态(
                self._状态缓冲,
                None if 数据.mocap_pos.size == 0 else 数据.mocap_pos,
                None if 数据.mocap_quat.size == 0 else 数据.mocap_quat,
            )
        except Exception as 异常:                                      # noqa: BLE001
            if self._步数 % 500 == 1:
                print(f"⚠ 【{self.name}】同步状态失败：{type(异常).__name__}: {异常}", flush=True)
            return False

        动作, 年龄毫秒, _统计 = self._规划器.取动作()
        if 年龄毫秒 <= max(0.0, self.超时秒) * 1000.0 and np.all(np.isfinite(动作)):
            数据.ctrl[:] = 动作
        else:
            # 规划没跟上：退回 0 力矩（模型有 gravcomp，不会砸下来），并计数
            数据.ctrl[:] = 0.0
            self._回退次数 += 1
        return False

    # ------------------------------------------------------------------
    def adjustable_parameters(self) -> dict:
        return {
            "采样数": {"value": self.采样数, "range": (2.0, 200.0), "step": 1.0},
            "规划步数": {"value": self.规划步数, "range": (1.0, 60.0), "step": 1.0},
            "CEM迭代": {"value": self.CEM迭代, "range": (1.0, 6.0), "step": 1.0},
            "精英比例": {"value": self.精英比例, "range": (0.05, 0.9)},
            "采样标准差": {"value": self.采样标准差, "range": (0.05, 1.0)},
            "手方块权重": {"value": self.手方块权重, "range": (0.0, 100.0)},
            "方块目标权重": {"value": self.方块目标权重, "range": (0.0, 100.0)},
            "控制权重": {"value": self.控制权重, "range": (0.0, 1.0)},
            "规划频率": {"value": self.规划频率, "range": (1.0, 100.0), "unit": "Hz"},
            "超时秒": {"value": self.超时秒, "range": (0.05, 2.0), "unit": "s"},
        }

    def metrics(self) -> dict:
        if self._规划器 is None:
            return {"规划次数": 0.0, "回退次数": float(self._回退次数)}
        动作, 年龄毫秒, 统计 = self._规划器.取动作()
        return {
            "规划次数": 统计.get("规划次数", 0.0),
            "规划耗时(ms)": 统计.get("规划耗时ms", 0.0),
            "cost": 统计.get("cost", 0.0),
            "hand-box(mm)": 统计.get("hand-box(mm)", 0.0),
            "box-target(mm)": 统计.get("box-target(mm)", 0.0),
            "cost_手": 统计.get("cost_手", 0.0),
            "cost_目标": 统计.get("cost_目标", 0.0),
            "cost_动作": 统计.get("cost_动作", 0.0),
            "动作范数": 统计.get("动作范数", 0.0),
            "动作峰值": 统计.get("动作峰值", 0.0),
            "夹爪": 统计.get("夹爪", 0.0),
            "动作年龄(ms)": 年龄毫秒,
            "回退次数": float(self._回退次数),
            "错误次数": 统计.get("错误次数", 0.0),
        }

    def status(self) -> dict:
        if self._启动失败:
            return {"状态": f"启动失败：{self._启动失败}"}
        if self._规划器 is None:
            return {"状态": "等待第一步"}
        动作, 年龄毫秒, 统计 = self._规划器.取动作()
        return {
            "步数": self._步数,
            "规划次数": int(统计.get("规划次数", 0)),
            "hand-box": f"{统计.get('hand-box(mm)', 0.0):.0f} mm",
            "box-target": f"{统计.get('box-target(mm)', 0.0):.0f} mm",
            "动作年龄": f"{年龄毫秒:.0f} ms",
            "回退": self._回退次数,
        }

    # ------------------------------------------------------------------
    def close(self) -> None:
        规划器, self._规划器 = self._规划器, None
        if 规划器 is not None:
            try:
                规划器.停止()
            except Exception:                                         # noqa: BLE001
                pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:                                             # noqa: BLE001
            pass
