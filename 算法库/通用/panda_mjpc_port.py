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
REQUIRED_SENSORS = ("hand", "box", "box1", "box2", "target1", "target2")
STATE_SPEC = int(mujoco.mjtState.mjSTATE_FULLPHYSICS)


def _sensor_slices(model: mujoco.MjModel) -> dict[str, tuple[int, int]]:
    slices = {}
    for name in REQUIRED_SENSORS:
        index = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, name)
        if index < 0:
            raise ValueError(f'缺少传感器 {name}')
        start = int(model.sensor_adr[index])
        slices[name] = (start, start + int(model.sensor_dim[index]))
    return slices


def _residuals(slices: dict[str, tuple[int, int]], sensor_data: np.ndarray) -> np.ndarray:
    """(…, nsensordata) -> (…, 9)，对应 panda.cc 的三组残差。"""
    get = lambda name: sensor_data[..., slices[name][0]:slices[name][1]]
    return np.concatenate([
        get("hand") - get("box"),
        get("box1") - get("target1"),
        get("box2") - get("target2"),
    ], axis=-1)


class _Planner:
    """独立线程里的随机采样 MPC；只碰自己的 MjData。"""

    def __init__(self, model: mujoco.MjModel, parameters: dict) -> None:
        self.model = model
        self.data = mujoco.MjData(model)
        self.STATE_SPEC = STATE_SPEC
        self.state_size = int(mujoco.mj_stateSize(model, self.STATE_SPEC))
        self.slices = _sensor_slices(model)

        self._lock = threading.Lock()
        self._state: np.ndarray | None = None
        self._mocap_pos: np.ndarray | None = None
        self._mocap_quat: np.ndarray | None = None
        self._new_state = threading.Event()
        self._stop = threading.Event()

        self._action = np.zeros(int(model.nu), dtype=float)
        self._action_time = 0.0
        self._statistics = {
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
        self._error = ""
        self._parameters = dict(parameters)
        # CEM 的均值/标准差跨规划保留（暖启动）；换模型/改 horizon 时形状不符就重置
        self._mean: np.ndarray | None = None
        self._standard_deviation: np.ndarray | None = None
        self._rollout = mjroll.Rollout(nthread=0)
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                       name="Panda-MPC规划")
        self._thread.start()

    # ---------- 仿真线程调用 ----------
    def update_state(self, state: np.ndarray, mocap_pos, mocap_quat) -> None:
        with self._lock:
            self._state = np.array(state, dtype=float, copy=True)
            self._mocap_pos = None if mocap_pos is None else np.array(mocap_pos, copy=True)
            self._mocap_quat = None if mocap_quat is None else np.array(mocap_quat, copy=True)
        self._new_state.set()

    def get_action(self) -> tuple[np.ndarray, float, dict]:
        with self._lock:
            action = self._action.copy()
            age = (time.monotonic() - self._action_time) * 1000.0 if self._action_time else 1e9
            statistics = dict(self._statistics)
            statistics["错误信息"] = self._error
            return action, age, statistics

    def set_parameter(self, name: str, value: float) -> None:
        with self._lock:
            self._parameters[name] = value

    def stop(self) -> None:
        self._stop.set()
        self._new_state.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ---------- 规划线程 ----------
    def _loop(self) -> None:
        sequence = 0
        while not self._stop.is_set():
            if not self._new_state.wait(0.2):
                continue
            self._new_state.clear()
            with self._lock:
                state = None if self._state is None else self._state.copy()
                mocap_pos = None if self._mocap_pos is None else self._mocap_pos.copy()
                mocap_quat = None if self._mocap_quat is None else self._mocap_quat.copy()
                parameters = dict(self._parameters)
            if state is None:
                continue
            started = time.perf_counter()
            try:
                mujoco.mj_setState(self.model, self.data, state, self.STATE_SPEC)
                if mocap_pos is not None and self.data.mocap_pos.size:
                    self.data.mocap_pos[:] = mocap_pos
                if mocap_quat is not None and self.data.mocap_quat.size:
                    self.data.mocap_quat[:] = mocap_quat
                mujoco.mj_forward(self.model, self.data)

                sample_count = max(2, int(parameters.get("采样数", 48)))
                step_count = max(1, int(parameters.get("规划步数", 20)))
                iteration_count = max(1, int(parameters.get("CEM迭代", 2)))
                elite_fraction = min(0.9, max(0.05, float(parameters.get("精英比例", 0.2))))
                initial_stddev = max(0.01, float(parameters.get("采样标准差", 0.35)))
                hand_weight = float(parameters.get("手方块权重", 5.0))
                target_weight = float(parameters.get("方块目标权重", 1.0))
                control_weight = float(parameters.get("控制权重", 0.001))
                weights = np.array([hand_weight] * 3 + [target_weight] * 6, dtype=float)

                lower = np.asarray(self.model.actuator_ctrlrange[:, 0], dtype=float)
                upper = np.asarray(self.model.actuator_ctrlrange[:, 1], dtype=float)
                amplitude = np.maximum(upper - lower, 1e-9)
                nu = int(self.model.nu)

                # 暖启动：上一次的最优序列往前挪一步；形状变了（改 horizon/换模型）就重置
                if self._mean is None or self._mean.shape != (step_count, nu):
                    self._mean = np.zeros((step_count, nu), dtype=float)
                    self._standard_deviation = amplitude[None, :] * initial_stddev
                else:
                    self._mean = np.vstack([self._mean[1:], self._mean[-1:]])

                rng = np.random.default_rng(sequence)
                sequence += 1
                output_states = np.empty((sample_count, step_count, self.state_size), dtype=float)
                output_sensors = np.empty((sample_count, step_count, int(self.model.nsensordata)), dtype=float)
                best_cost = float("inf")
                best_action = None
                best_sensors = None

                # CEM：采样 → 选精英 → 更新均值/标准差；每次规划迭代几次
                for iteration in range(iteration_count):
                    noise = rng.standard_normal((sample_count, step_count, nu))
                    actions = np.clip(
                        self._mean[None, :, :] + noise * self._standard_deviation[None, :, :],
                        lower, upper)
                    if iteration == 0:
                        actions[0] = 0.0          # 保一条"不动"的基线
                    self._rollout.rollout(
                        self.model, self.data, np.tile(state, (sample_count, 1)),
                        control=actions, nstep=step_count,
                        state=output_states, sensordata=output_sensors,
                    )
                    residuals = _residuals(self.slices, output_sensors)              # (N,H,9)
                    costs = (np.sum(weights * residuals * residuals, axis=(1, 2))
                            + control_weight * np.sum(actions * actions, axis=(1, 2)))
                    best_index = int(np.argmin(costs))
                    if float(costs[best_index]) < best_cost:
                        best_cost = float(costs[best_index])
                        best_action = np.array(actions[best_index], dtype=float, copy=True)
                        best_sensors = np.array(output_sensors[best_index], dtype=float, copy=True)

                    elite_count = max(1, int(sample_count * elite_fraction))
                    elites = actions[np.argsort(costs)[:elite_count]]
                    self._mean = np.clip(elites.mean(axis=0), lower, upper)
                    self._standard_deviation = np.clip(
                        elites.std(axis=0) + 0.02 * amplitude[None, :],
                        0.05 * amplitude[None, :], 0.75 * amplitude[None, :])

                if best_action is None or best_sensors is None:
                    raise RuntimeError("CEM 没有产出可用动作")
                # 下一次从这个最优序列暖启动（上面会再往前挪一步）
                self._mean = np.array(best_action, dtype=float, copy=True)
                hand_to_box = float(np.linalg.norm(
                    best_sensors[-1, self.slices["hand"][0]:self.slices["hand"][1]]
                    - best_sensors[-1, self.slices["box"][0]:self.slices["box"][1]]))
                # 把总 cost 拆开，界面才能回答"为什么"：
                #   cost_手   = 手到方块残差（3 维）
                #   cost_目标 = 方块两侧到目标（6 维）
                #   cost_动作 = 动作大小正则
                best_residuals = _residuals(self.slices, best_sensors)              # (H,9)
                hand_cost = float(np.sum(best_residuals[:, :3] ** 2)) * hand_weight
                target_cost = float(np.sum(best_residuals[:, 3:] ** 2)) * target_weight
                action_cost = float(np.sum(best_action ** 2)) * control_weight
                box_to_target = float(
                    (np.linalg.norm(best_residuals[-1, 3:6])
                     + np.linalg.norm(best_residuals[-1, 6:9])) / 2.0)
                action_norm = float(np.linalg.norm(best_action[0, :6]))
                gripper = float(best_action[0, 6])
            except Exception as exc:                                  # noqa: BLE001
                with self._lock:
                    self._statistics["错误次数"] += 1
                    self._error = f'{type(exc).__name__}: {exc}'
                self._stop.wait(0.05)
                continue

            with self._lock:
                self._action = np.array(best_action[0], dtype=float, copy=True)
                self._action_time = time.monotonic()
                self._statistics["规划次数"] += 1
                self._statistics["规划耗时ms"] = (time.perf_counter() - started) * 1000.0
                self._statistics["cost"] = float(best_cost)
                self._statistics["hand-box(mm)"] = hand_to_box * 1000.0
                self._statistics["box-target(mm)"] = box_to_target * 1000.0
                self._statistics["cost_手"] = hand_cost
                self._statistics["cost_目标"] = target_cost
                self._statistics["cost_动作"] = action_cost
                self._statistics["动作范数"] = action_norm
                self._statistics["动作峰值"] = max(
                    float(self._statistics.get("动作峰值", 0.0)), action_norm)
                self._statistics["夹爪"] = gripper
                self._statistics["动作年龄ms"] = 0.0
                self._error = ""

            # 限频：规划频率默认 20 Hz；算得快也不要空转烧 CPU
            period = 1.0 / max(1.0, float(parameters.get("规划频率", 20.0)))
            remaining = period - (time.perf_counter() - started)
            if remaining > 0:
                self._stop.wait(remaining)


class PandaMPCController(ControlPlugin):
    parameter_aliases = {'CEM迭代': 'cem_iterations', '规划频率': 'planning_frequency', '超时秒': 'timeout_seconds', '控制权重': 'control_weight', '规划步数': 'horizon_steps', '精英比例': 'elite_fraction', '方块目标权重': 'box_target_weight', '采样标准差': 'sampling_stddev', '手方块权重': 'hand_box_weight', '采样数': 'sample_count'}
    name = "Panda 官方 MPC（移植）"
    version = "0.2"
    english_name = "Panda MJPC port (CEM)"
    description = "移植 MJPC 的 Panda 任务：9 维残差 + CEM 采样 + mujoco.rollout；7 维末端力/力矩动作。"
    author = "数字样机（算法来源：google-deepmind/mujoco_mpc，Apache-2.0）"
    takes_control = True

    # ---- 可调参数（界面滑杆直接改；规划线程每次规划读一次）----
    sample_count = 48
    horizon_steps = 20
    cem_iterations = 2
    elite_fraction = 0.2
    sampling_stddev = 0.35
    hand_box_weight = 5.0
    box_target_weight = 1.0
    control_weight = 0.001
    planning_frequency = 20.0
    timeout_seconds = 0.25

    def __init__(self) -> None:
        self._Planner: _Planner | None = None
        self._model = None
        self._startup_error = ""
        self._fallback_count = 0
        self._step_count = 0
        self._state_buffer: np.ndarray | None = None

    # ------------------------------------------------------------------
    def check_model_compatibility(self, model) -> str:
        if int(getattr(model, "nu", 0)) != 7:
            return f"需要 MJPC Panda 的 7 维动作（本模型 nu={getattr(model, 'nu', 0)}）"
        for name in REQUIRED_SENSORS:
            if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, name) < 0:
                return f'缺少传感器「{name}」——这不是 MJPC 的 Panda 任务模型'
        return ""

    def _start(self, model) -> bool:
        try:
            self._Planner = _Planner(model, self._parameter_snapshot())
            self._state_buffer = np.empty(
                int(mujoco.mj_stateSize(model, STATE_SPEC)), dtype=float)
            return True
        except Exception as exc:                                      # noqa: BLE001
            self._startup_error = f'{type(exc).__name__}: {exc}'
            print(f'⚠ 【{self.name}】启动失败：{self._startup_error}', flush=True)
            return False

    def _parameter_snapshot(self) -> dict:
        return {
            "采样数": self.sample_count,
            "规划步数": self.horizon_steps,
            "CEM迭代": self.cem_iterations,
            "精英比例": self.elite_fraction,
            "采样标准差": self.sampling_stddev,
            "手方块权重": self.hand_box_weight,
            "方块目标权重": self.box_target_weight,
            "控制权重": self.control_weight,
            "规划频率": self.planning_frequency,
        }

    def set_parameter(self, name: str, value: float) -> str:
        reason = super().set_parameter(name, value)
        if not reason and self._Planner is not None:
            self._Planner.set_parameter(name, getattr(self, self.parameter_aliases.get(name, name)))
        return reason

    # ------------------------------------------------------------------
    @step_handler
    def step(self, event: plugin.messages.StepEvent) -> bool:
        model, data = event.model, event.data
        if self._Planner is None and not self._startup_error:
            self._start(model)
        if self._Planner is None:
            return False

        self._step_count += 1
        try:
            mujoco.mj_getState(model, data, self._state_buffer, STATE_SPEC)
            self._Planner.update_state(
                self._state_buffer,
                None if data.mocap_pos.size == 0 else data.mocap_pos,
                None if data.mocap_quat.size == 0 else data.mocap_quat,
            )
        except Exception as exc:                                      # noqa: BLE001
            if self._step_count % 500 == 1:
                print(f'⚠ 【{self.name}】同步状态失败：{type(exc).__name__}: {exc}', flush=True)
            return False

        action, age_ms, _statistics = self._Planner.get_action()
        if age_ms <= max(0.0, self.timeout_seconds) * 1000.0 and np.all(np.isfinite(action)):
            data.ctrl[:] = action
        else:
            # 规划没跟上：退回 0 力矩（模型有 gravcomp，不会砸下来），并计数
            data.ctrl[:] = 0.0
            self._fallback_count += 1
        return False

    # ------------------------------------------------------------------
    def adjustable_parameters(self) -> dict:
        return {
            "采样数": {"value": self.sample_count, "range": (2.0, 200.0), "step": 1.0},
            "规划步数": {"value": self.horizon_steps, "range": (1.0, 60.0), "step": 1.0},
            "CEM迭代": {"value": self.cem_iterations, "range": (1.0, 6.0), "step": 1.0},
            "精英比例": {"value": self.elite_fraction, "range": (0.05, 0.9)},
            "采样标准差": {"value": self.sampling_stddev, "range": (0.05, 1.0)},
            "手方块权重": {"value": self.hand_box_weight, "range": (0.0, 100.0)},
            "方块目标权重": {"value": self.box_target_weight, "range": (0.0, 100.0)},
            "控制权重": {"value": self.control_weight, "range": (0.0, 1.0)},
            "规划频率": {"value": self.planning_frequency, "range": (1.0, 100.0), "unit": "Hz"},
            "超时秒": {"value": self.timeout_seconds, "range": (0.05, 2.0), "unit": "s"},
        }

    def metrics(self) -> dict:
        if self._Planner is None:
            return {"规划次数": 0.0, "回退次数": float(self._fallback_count)}
        action, age_ms, statistics = self._Planner.get_action()
        return {
            "规划次数": statistics.get("规划次数", 0.0),
            "规划耗时(ms)": statistics.get("规划耗时ms", 0.0),
            "cost": statistics.get("cost", 0.0),
            "hand-box(mm)": statistics.get("hand-box(mm)", 0.0),
            "box-target(mm)": statistics.get("box-target(mm)", 0.0),
            "cost_手": statistics.get("cost_手", 0.0),
            "cost_目标": statistics.get("cost_目标", 0.0),
            "cost_动作": statistics.get("cost_动作", 0.0),
            "动作范数": statistics.get("动作范数", 0.0),
            "动作峰值": statistics.get("动作峰值", 0.0),
            "夹爪": statistics.get("夹爪", 0.0),
            "动作年龄(ms)": age_ms,
            "回退次数": float(self._fallback_count),
            "错误次数": statistics.get("错误次数", 0.0),
        }

    def status(self) -> dict:
        if self._startup_error:
            return {"状态": f'启动失败：{self._startup_error}'}
        if self._Planner is None:
            return {"状态": "等待第一步"}
        action, age_ms, statistics = self._Planner.get_action()
        return {
            "步数": self._step_count,
            "规划次数": int(statistics.get("规划次数", 0)),
            "hand-box": f"{statistics.get('hand-box(mm)', 0.0):.0f} mm",
            "box-target": f"{statistics.get('box-target(mm)', 0.0):.0f} mm",
            "动作年龄": f'{age_ms:.0f} ms',
            "回退": self._fallback_count,
        }

    # ------------------------------------------------------------------
    def close(self) -> None:
        planner, self._Planner = self._Planner, None
        if planner is not None:
            try:
                planner.stop()
            except Exception:                                         # noqa: BLE001
                pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:                                             # noqa: BLE001
            pass
