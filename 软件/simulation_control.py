"""仿真运行与重力设置的内置通道。

两个概念刻意分开：
  * 运行 / 暂停决定是否派发物理步进，暂停保持当前状态；
  * 重力开 / 关只在 ``model.opt.gravity`` 与零向量之间切换。

因此关闭重力不会自动暂停或复位，按 Run 也不会偷偷打开重力。Reset 才会恢复
默认姿态、清理状态并保持暂停。该模块是外壳内置件，不属于控制算法，也不写 data.ctrl。
"""
from __future__ import annotations

import dataclasses
from typing import Callable

from official_api import messages, sim


# ---------------------------------------------------------------------------
# 界面侧的共享状态（★ 单一真相源 —— 这里踩过一个真坑）
# ---------------------------------------------------------------------------
# 「加载重力」这个开关现在有**两个**界面入口：
#     ① 左上角【Display】的勾选框
#     ② 【Algorithms】算法面板上的 `run physics / freeze` 按钮
#        （加它的原因：用户挂好算法后发现机械臂不动，得能就地开物理，
#          而不是被指去左上角找开关）
#
# ★ 坑：两个入口各发各的 `重力状态` 消息 → **互相顶掉**。
#   【Display】面板每 10 Hz 持续发布它自己的勾选状态（这是刻意的设计：
#   让界面成为真相源、能纠正外部改动），于是算法面板发的 `True` 下一拍就被
#   `False` 覆盖 —— 表现为"点了按钮，物理打开了，但模型还是不动"。
#
# 解决办法：界面侧只保留**一份**状态，两个面板都读写它。
#   谁改都先改它、再发消息；发布器永远读它 → 不可能互相打架。
UI_GRAVITY_ENABLED = True


def set_ui_gravity(enabled: bool) -> None:
    """改界面侧那份共享状态（两个面板都调这个，不要各自存一份）。"""
    global UI_GRAVITY_ENABLED
    UI_GRAVITY_ENABLED = bool(enabled)


# ---------------------------------------------------------------------------
# 界面 → 仿真侧的消息
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class GravityState(messages.Snapshot):
    """是否施用模型 XML 声明的重力；不表达运行/暂停。"""

    gravity_enabled: bool = True


@dataclasses.dataclass(frozen=True)
class SimulationControlCommand(messages.Snapshot):
    """自研工作台的全局运行命令；与控制算法本身无关。"""

    action: str = "pause"          # run / pause / reset / speed
    speed_multiplier: float = 1.0            # 只在“设置速度”时使用；不修改 model.opt.timestep


@dataclasses.dataclass(frozen=True)
class SimulationState(messages.Snapshot):
    """仿真侧确认过的真实运行状态，供工具栏和状态栏显示。"""

    state: str = "paused"          # running / paused
    gravity_enabled: bool = True          # 与运行状态独立：暂停时也可以保持重力开启
    simulation_time: float = 0.0        # MuJoCo data.time
    reset_count: int = 0
    speed_multiplier: float = 1.0        # 目标墙钟速度；实际达到多少仍看系统.RTF
    description: str = ""


# ---------------------------------------------------------------------------
# 仿真侧：内置的"重力/冻结"应用器（常驻，不随算法加载与否变化）
# ---------------------------------------------------------------------------
class GravityApplier:
    """管理独立的步进闸门与重力参数；不写 ``data.ctrl``。"""

    name = "重力开关"          # 有名字 → 会出现在状态行，便于排查
    version = "2.0"
    english_name = "Gravity switch"
    takes_control = False           # 不写 ctrl[:]，不参与"抢方向盘"
    description = "重力开关只改模型重力；Run/Pause/Reset 另由仿真控制命令管理。"

    def __init__(self, reset_callback: Callable | None = None,
                 simulation_reset: Callable | None = None,
                 state_callback: Callable | None = None) -> None:
        self._reset_callback = reset_callback        # 外壳注入：把模型摆回默认姿态（复用 _重置姿态）
        # 显式 Reset 要连当前算法实例一起重新初始化；这个动作只有外壳能完成。
        self._simulation_reset = simulation_reset
        self._state_callback = state_callback
        self._model = None
        self._data = None
        self._model_path = ""
        self._running = False             # 步进闸门：默认暂停
        self._gravity_enabled = True              # 物理参数：默认使用模型 XML 里的重力
        self._original_gravity = None
        self._user_paused = False           # 用户自己在官方 Simulation 面板上的暂停意图
        self._reset_count = 0
        self._freeze_count = 0
        self._speed_multiplier = 1.0
        self._last_action = "模型加载后暂停"
        self._snapshot_parameters = {"speed": 1.0, "noise_scale": 0.0, "noise_rate": 0.0}
        self._remembered_qpos = None          # 没有 home 关键帧时的兜底姿态
        # ★ 重入保护（这里是踩过的真坑）：
        #   冻结时要"补发一条 PAUSED 快照"给官方 StepControl，而补发走的是
        #   `注册表.处理消息()` —— 那会**再次派发到本插件自己**，于是又改写、又补发……
        #   实测：`RecursionError: maximum recursion depth exceeded`，
        #   结果**冻结从来没生效过**（报错只在第一次打印，很容易被忽略）。
        #   所以补发之前先立这个旗，看到旗就原样放行、不再改写。
        self._redispatching = False
        self._freeze_predicate_registered = False
        self._registry = None

    # ------------------------------------------------------------------
    # 外壳挂钩
    # ------------------------------------------------------------------
    def receive_model(self, event) -> None:
        """模型加载 / 切换时调（外壳的 `通知模型加载` 会走到这里）。

        ★ 每次换模型都回到"冻结 + 默认位置"：需求是"**所有模型**进去都静止"，
          所以这里必须重置开关状态，不能沿用上一个模型的。
        """
        new_path = str(getattr(event, "path", "") or "")
        new_model = getattr(event, "model", None)
        model_changed = (new_path != self._model_path) or (self._model is not new_model)

        self._model = new_model
        self._data = getattr(event, "data", None)
        if new_path:
            self._model_path = new_path
        # ★ 只有"真的换了模型"才重置重力状态（这是踩过的坑）：
        #   外壳在**换一组算法**时也会发这条通知（复用同一个机制）。当时没区分，
        #   结果是"我勾了加载重力，一点 Apply 算法，重力又没了" —— 用户莫名其妙。
        #   换算法不该动重力开关；"换算法前把姿态复位"由外壳的 `_装配项目` 负责。
        if not model_changed:
            return
        self._running = False             # 换模型先暂停，避免加载瞬间运动
        self._gravity_enabled = True              # 新模型默认采用 XML 中声明的重力
        self._user_paused = False
        self._remembered_qpos = None
        try:
            self._original_gravity = self._model.opt.gravity.copy()
        except Exception:                                        # noqa: BLE001
            self._original_gravity = None
        self._apply_gravity()
        if self._data is not None:
            try:
                self._remembered_qpos = self._data.qpos.copy()
            except Exception:                                        # noqa: BLE001
                pass
        # 立刻冻结（不等界面下发，避免"进模型瞬间掉一下"）
        self._freeze_at_default(reason="模型已加载")

    def plugin_status(self) -> dict:
        return {"运行": "运行" if self._running else "暂停",
                "重力": "开" if self._gravity_enabled else "关",
                "复位": self._reset_count}

    @property
    def gravity_enabled(self) -> bool:
        """当前模型是否使用 XML 中的重力向量。"""
        return bool(self._gravity_enabled)

    @property
    def running(self) -> bool:
        return bool(self._running)

    @property
    def reset_count(self) -> int:
        return int(self._reset_count)

    @property
    def speed_multiplier(self) -> float:
        return float(self._speed_multiplier)

    @property
    def last_action(self) -> str:
        return str(self._last_action)

    def set_gravity_enabled(self, enabled: bool) -> None:
        """供外壳/面板直接设置重力；运行状态保持不变。"""
        enabled = bool(enabled)
        if enabled == self._gravity_enabled:
            return
        self._gravity_enabled = enabled
        set_ui_gravity(enabled)
        self._apply_gravity()
        print(f"【重力】已{'开启' if enabled else '关闭'}；仿真运行状态不变", flush=True)
        self._report_state()

    # ------------------------------------------------------------------
    # 向注册表登记"冻结判据"（这就是冻结生效的唯一机制）
    # ------------------------------------------------------------------
    def register_with_registry(self, registry) -> None:
        """把 `_该冻结()` 登记给注册表。外壳在注册本插件后调一次。

        ★ 为什么需要显式登记：冻结不能用"改暂停快照"实现（官方不发快照，
          实测 6 秒 0 条），必须在**派发入口**上拦。详见本文件开头的说明。
        """
        self._registry = registry
        try:
            registry.add_freeze_predicate(self._should_freeze)
            self._freeze_predicate_registered = True
        except Exception as exc:                                        # noqa: BLE001
            print(f"⚠ 重力应用器无法登记冻结判据（冻结会失效）："
                  f"{type(exc).__name__}: {exc}")

    def _should_freeze(self) -> bool:
        """注册表问的就是这一句：现在要不要冻结物理？"""
        return not self._running

    # ------------------------------------------------------------------
    # 界面来的开关
    # ------------------------------------------------------------------
    @messages.handler
    def on_gravity_state(self, message: GravityState) -> bool:
        gravity_enabled = bool(getattr(message, "gravity_enabled", False))
        if gravity_enabled == self._gravity_enabled:
            return False                 # 没变化 → 早退（这条消息每帧都到）
        self._gravity_enabled = gravity_enabled
        set_ui_gravity(gravity_enabled)
        self._apply_gravity()
        print(f"【重力】已{'开启' if gravity_enabled else '关闭'}；仿真运行状态不变", flush=True)
        self._report_state()
        return False

    @messages.handler
    def on_simulation_command(self, command: SimulationControlCommand) -> bool:
        """Run / Pause / Reset 的唯一落点。

        Pause 只关掉步进闸门，保持 qpos、qvel、ctrl 和 data.time；Reset 才调用
        外壳重新装配当前算法并清理 MuJoCo 状态。两者分开后，GUI 不再用一个
        “加载重力”开关同时表达三个动作。
        """
        action = str(getattr(command, "action", "pause") or "pause")
        if action in ("运行", "run"):
            self._running = True
            self._user_paused = False
            self._send_official_pause(False)
            self._last_action = "继续运行"
            print("【仿真】运行：从当前状态继续推进", flush=True)
        elif action in ("暂停", "pause"):
            self._running = False
            self._user_paused = True
            self._send_official_pause(True)
            self._last_action = "暂停在当前状态"
            print("【仿真】暂停：保持当前姿态与仿真时间", flush=True)
        elif action in ("复位", "reset"):
            self._running = False
            self._user_paused = True
            self._send_official_pause(True)
            description = ""
            if self._simulation_reset is not None:
                try:
                    description = str(self._simulation_reset() or "")
                except Exception as exc:                              # noqa: BLE001
                    print(f"⚠ 仿真复位回调失败（改用物理状态复位）："
                          f"{type(exc).__name__}: {exc}", flush=True)
            if description:
                self._reset_count += 1
                self._freeze_count += 1
            else:
                self._freeze_at_default(reason="GUI Reset")
            self._last_action = "已复位并暂停"
            print(f"【仿真】复位完成，保持暂停{f'：{description}' if description else ''}", flush=True)
        elif action in ("设置速度", "speed"):
            # 这里只保存并回传权威状态；真正的等待节拍由“实时固定步进”处理。
            # 改倍率不会改 timestep，因此控制器看到的 dt 与物理精度保持不变。
            self._speed_multiplier = max(
                0.25, min(4.0, float(getattr(command, "speed_multiplier", 1.0)))
            )
            self._last_action = f"仿真速度已设为 {self._speed_multiplier:g}×"
            print(f"【仿真】目标速度：{self._speed_multiplier:g}×（物理步长不变）", flush=True)
        self._report_state()
        return False

    def _send_official_pause(self, paused: bool) -> None:
        """同步官方 StepControl，避免外壳闸门打开后它仍停在旧暂停状态。"""
        try:
            self._redispatch(messages.StepControlSnapshot(
                pause_state=(sim.PauseState.NORMAL_PAUSED if paused else sim.PauseState.UNPAUSED),
                **self._snapshot_parameters))
        except Exception as exc:                                      # noqa: BLE001
            print(f"⚠ 同步官方暂停状态失败：{type(exc).__name__}: {exc}", flush=True)

    def _report_state(self) -> None:
        if self._state_callback is None:
            return
        try:
            self._state_callback()
        except Exception:                                             # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 官方每帧发的暂停快照：冻结时把它改写成"暂停"再放行
    #   ★ 这是本模块最关键的一处。为什么不能"直接调 set_pause_state"：
    #     官方 ViewerApp **每帧**都会发一条 StepControlSnapshot（带着它自己那份 pause_state），
    #     官方 StepControl 收到就 apply —— 我们直接设的状态下一帧就被顶掉。
    #     所以只能在消息流上动手：**在官方 StepControl 之前**改写 pause_state。
    #     外壳仿真循环的顺序是 ① 处理快照 ② 派发 StepEvent，而安全注册表**按插件列表顺序**
    #     逐个派发（官方 StepControl 固定排在第 0 个），所以本插件能拦在它前面。
    #     ⚠️ 这里不是靠 priority（跨插件排序不看 priority，见 插件系统.py 的说明）。
    #   ★ 额外好处：官方【Simulation】面板的暂停按钮会**同步显示为已暂停**，两处状态不打架。
    # ------------------------------------------------------------------
    @messages.handler
    def on_step_control_snapshot(self, event: messages.StepControlSnapshot) -> bool:
        # ★ 重入保护：这条快照如果是我们自己补发的，就原样放行 —— 否则会无限递归
        #   （见 __init__ 里 `_正在补发` 的说明；这个坑实测踩过，导致冻结完全失效）。
        if self._redispatching:
            return False
        try:
            self._user_paused = (event.pause_state != sim.PauseState.UNPAUSED)
            self._snapshot_parameters = dict(speed=event.speed, noise_scale=event.noise_scale,
                                  noise_rate=event.noise_rate)
        except Exception:                                                # noqa: BLE001
            pass
        if self._running:
            return False                 # 运行中：原样放行
        # 冻结：发一条"暂停"的快照覆盖它
        #   （dataclass 是 frozen，不能原地改，只能照原值重建一条）
        try:
            parameters = dict(speed=event.speed, noise_scale=event.noise_scale,
                        noise_rate=event.noise_rate)
        except Exception:                                                # noqa: BLE001
            parameters = {}
        try:
            self._redispatch(messages.StepControlSnapshot(
                pause_state=sim.PauseState.NORMAL_PAUSED, **parameters))
        except Exception as exc:                                        # noqa: BLE001
            if self._freeze_count == 0:        # 只在第一次报，避免刷屏
                print(f"⚠ 改写暂停状态失败（模型可能不会冻结）："
                      f"{type(exc).__name__}: {exc}")
        return False

    def _redispatch(self, snapshot) -> None:
        """把改写后的快照送进内部消息通道，让官方 StepControl 收到。

        通道 = `安全注册表.处理消息`（外壳唯一的派发入口）。插件拿不到注册表引用，
        所以用 `插件系统.取注册表()` 这个公开访问器（见 插件系统.py 的契约例外 ①）。

        ★ `_正在补发` 必须在 finally 里复位：万一官方 StepControl 那边抛异常，
          旗子留在 True 上就再也改不动暂停状态了（冻结会静默失效）。
        """
        from plugin_system import get_registry
        registry = get_registry()
        if registry is None:
            return
        self._redispatching = True
        try:
            registry.process_message(snapshot)
        finally:
            self._redispatching = False

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _has_home(self) -> bool:
        if self._model is None:
            return False
        try:
            import mujoco
            return mujoco.mj_name2id(
                self._model, mujoco.mjtObj.mjOBJ_KEY, "home"
            ) >= 0
        except Exception:                                             # noqa: BLE001
            return False

    def _apply_gravity(self) -> None:
        """只修改重力参数，不启动、暂停或复位仿真。"""
        if self._model is None or self._original_gravity is None:
            return
        try:
            self._model.opt.gravity[:] = self._original_gravity if self._gravity_enabled else 0.0
            if self._data is not None:
                import mujoco
                mujoco.mj_forward(self._model, self._data)
        except Exception as exc:                                      # noqa: BLE001
            print(f"⚠ 应用重力参数失败：{type(exc).__name__}: {exc}", flush=True)

    def _freeze_at_default(self, reason: str = "") -> None:
        """把模型摆回默认姿态并冻结。优先用外壳注入的回调（保证与"换算法时重置"同一套行为）。"""
        self._running = False
        reset_description = ""
        if self._reset_callback is not None:
            try:
                reset_description = str(self._reset_callback() or "")
            except Exception as exc:                                    # noqa: BLE001
                print(f"⚠ 复位回调失败（改用本模块自带的复位）："
                      f"{type(exc).__name__}: {exc}")
        if not reset_description:
            reset_description = self._reset_locally()
        self._reset_count += 1
        self._freeze_count += 1
        prefix = f"（{reason}）" if reason else ""
        suffix = f"：{reset_description}" if reset_description else ""
        print(f"【重力】{prefix}已回到默认位置并冻结，物理暂停{suffix}", flush=True)

    def _reset_locally(self) -> str:
        """自带的兜底复位（外壳回调不可用时用）。与 `启动._重置姿态()` 同一套做法。"""
        if self._model is None or self._data is None:
            return ""
        try:
            import mujoco
            if self._has_home():
                key = mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_KEY, "home")
                mujoco.mj_resetDataKeyframe(self._model, self._data, key)
                reference = "home 关键帧"
            else:
                mujoco.mj_resetData(self._model, self._data)
                if self._remembered_qpos is not None:
                    n = min(len(self._remembered_qpos), self._model.nq)
                    self._data.qpos[:n] = self._remembered_qpos[:n]
                reference = "模型初始 qpos"
            self._data.qvel[:] = 0.0        # 关键帧不一定清速度；不清就会"带着旧速度出发"
            self._data.ctrl[:] = 0.0        # 上一组算法写下的力矩也清掉
            mujoco.mj_forward(self._model, self._data)
            return reference
        except Exception as exc:                                        # noqa: BLE001
            print(f"⚠ 重置姿态失败：{type(exc).__name__}: {exc}")
            return ""


# ---------------------------------------------------------------------------
# 发布器：界面把开关状态发给仿真侧（只在变化 / 到时限时才真发）
# ---------------------------------------------------------------------------
class GravityPublisher:
    """把【Display】的开关状态发给仿真侧。

    ★ 用 `Snapshot`（最新覆盖）语义 —— 界面每帧覆盖一次，所以**万一两边状态不同步
      （比如用户又去点了官方 Simulation 面板的暂停），下一帧就会被勾选框纠正回来**。
    """

    def __init__(self, send, frequency: float = 10.0):
        self._send = send
        self._interval = 1.0 / max(frequency, 1e-6)
        self._last_time = 0.0
        self._last_value = None

    def maybe_publish(self, gravity_enabled: bool, wall_time: float) -> None:
        if gravity_enabled == self._last_value and (wall_time - self._last_time) < self._interval:
            return
        self._last_time, self._last_value = wall_time, gravity_enabled
        try:
            self._send(GravityState(gravity_enabled=gravity_enabled))
        except Exception:                                                # noqa: BLE001
            pass                     # 这条通道坏了绝不能影响窗口绘制

    def maybe_publish_shared(self, wall_time: float) -> None:
        """按**界面侧共享状态**发布（【Display】面板每帧调这个）。

        与 `也许发布(值, 墙钟)` 的区别：这里不接收调用方自己的那份状态，
        而是统一读 `simulation_control.UI_GRAVITY_ENABLED` —— 所以另一个面板改了它，下一拍就会发出去，
        两个入口永远不会互相覆盖。
        """
        self.maybe_publish(UI_GRAVITY_ENABLED, wall_time)


class SimulationStatePublisher:
    """把运行/暂停与 data.time 作为独立状态发给自研 GUI（默认 5 Hz）。"""

    def __init__(self, send, frequency: float = 5.0) -> None:
        self._send = send
        self._interval = 1.0 / max(frequency, 1e-6)
        self._next_publish = 0.0
        self._last: tuple | None = None

    def publish(self, applier: GravityApplier, simulation_time: float, force: bool = False) -> bool:
        content = (bool(applier.running), bool(applier.gravity_enabled), float(simulation_time),
              int(applier.reset_count), float(applier.speed_multiplier), applier.last_action)
        if not force and content == self._last:
            return False
        self._last = content
        self._send(SimulationState(
            state="running" if applier.running else "paused",
            gravity_enabled=bool(applier.gravity_enabled),
            simulation_time=float(simulation_time),
            reset_count=int(applier.reset_count),
            speed_multiplier=float(applier.speed_multiplier),
            description=applier.last_action,
        ))
        return True

    def maybe_publish(self, applier: GravityApplier, simulation_time: float, wall_time: float) -> bool:
        if wall_time < self._next_publish:
            return False
        self._next_publish = wall_time + self._interval
        return self.publish(applier, simulation_time)


__all__ = [
    "UI_GRAVITY_ENABLED",
    "set_ui_gravity",
    "GravityState",
    "SimulationControlCommand",
    "SimulationState",
    "GravityApplier",
    "GravityPublisher",
    "SimulationStatePublisher",
]
