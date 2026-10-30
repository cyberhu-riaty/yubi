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

from 官方层 import messages, sim     # 全部走适配层，见 软件/官方层.py


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
界面重力开 = True


def 设界面重力(开: bool) -> None:
    """改界面侧那份共享状态（两个面板都调这个，不要各自存一份）。"""
    global 界面重力开
    界面重力开 = bool(开)


# ---------------------------------------------------------------------------
# 界面 → 仿真侧的消息
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 重力状态(messages.Snapshot):
    """是否施用模型 XML 声明的重力；不表达运行/暂停。"""

    重力开: bool = True


@dataclasses.dataclass(frozen=True)
class 仿真控制命令(messages.Snapshot):
    """自研工作台的全局运行命令；与控制算法本身无关。"""

    动作: str = "暂停"          # 运行 / 暂停 / 复位 / 设置速度
    倍率: float = 1.0            # 只在“设置速度”时使用；不修改 model.opt.timestep


@dataclasses.dataclass(frozen=True)
class 仿真状态(messages.Snapshot):
    """仿真侧确认过的真实运行状态，供工具栏和状态栏显示。"""

    状态: str = "暂停"          # 运行 / 暂停
    重力开: bool = True          # 与运行状态独立：暂停时也可以保持重力开启
    仿真时间: float = 0.0        # MuJoCo data.time
    复位次数: int = 0
    速度倍率: float = 1.0        # 目标墙钟速度；实际达到多少仍看系统.RTF
    说明: str = ""


# ---------------------------------------------------------------------------
# 仿真侧：内置的"重力/冻结"应用器（常驻，不随算法加载与否变化）
# ---------------------------------------------------------------------------
class 重力应用器:
    """管理独立的步进闸门与重力参数；不写 ``data.ctrl``。"""

    名称 = "重力开关"          # 有名字 → 会出现在状态行，便于排查
    版本 = "2.0"
    英文名 = "Gravity switch"
    接管控制 = False           # 不写 ctrl[:]，不参与"抢方向盘"
    说明 = "重力开关只改模型重力；Run/Pause/Reset 另由仿真控制命令管理。"

    def __init__(self, 复位回调: Callable | None = None,
                 仿真复位回调: Callable | None = None,
                 状态回调: Callable | None = None) -> None:
        self._复位回调 = 复位回调        # 外壳注入：把模型摆回默认姿态（复用 _重置姿态）
        # 显式 Reset 要连当前算法实例一起重新初始化；这个动作只有外壳能完成。
        self._仿真复位回调 = 仿真复位回调
        self._状态回调 = 状态回调
        self._模型 = None
        self._数据 = None
        self._模型路径 = ""
        self._运行中 = False             # 步进闸门：默认暂停
        self._重力开 = True              # 物理参数：默认使用模型 XML 里的重力
        self._原始重力 = None
        self._用户暂停 = False           # 用户自己在官方 Simulation 面板上的暂停意图
        self._已复位 = 0
        self._已冻结 = 0
        self._速度倍率 = 1.0
        self._最近动作 = "模型加载后暂停"
        self._快照参数 = {"speed": 1.0, "noise_scale": 0.0, "noise_rate": 0.0}
        self._记住的姿态 = None          # 没有 home 关键帧时的兜底姿态
        # ★ 重入保护（这里是踩过的真坑）：
        #   冻结时要"补发一条 PAUSED 快照"给官方 StepControl，而补发走的是
        #   `注册表.处理消息()` —— 那会**再次派发到本插件自己**，于是又改写、又补发……
        #   实测：`RecursionError: maximum recursion depth exceeded`，
        #   结果**冻结从来没生效过**（报错只在第一次打印，很容易被忽略）。
        #   所以补发之前先立这个旗，看到旗就原样放行、不再改写。
        self._正在补发 = False
        self._已登记判据 = False
        self._注册表 = None

    # ------------------------------------------------------------------
    # 外壳挂钩
    # ------------------------------------------------------------------
    def 收到模型(self, event) -> None:
        """模型加载 / 切换时调（外壳的 `通知模型加载` 会走到这里）。

        ★ 每次换模型都回到"冻结 + 默认位置"：需求是"**所有模型**进去都静止"，
          所以这里必须重置开关状态，不能沿用上一个模型的。
        """
        新路径 = str(getattr(event, "path", "") or "")
        新模型 = getattr(event, "model", None)
        换了模型 = (新路径 != self._模型路径) or (self._模型 is not 新模型)

        self._模型 = 新模型
        self._数据 = getattr(event, "data", None)
        if 新路径:
            self._模型路径 = 新路径
        # ★ 只有"真的换了模型"才重置重力状态（这是踩过的坑）：
        #   外壳在**换一组算法**时也会发这条通知（复用同一个机制）。当时没区分，
        #   结果是"我勾了加载重力，一点 Apply 算法，重力又没了" —— 用户莫名其妙。
        #   换算法不该动重力开关；"换算法前把姿态复位"由外壳的 `_装配项目` 负责。
        if not 换了模型:
            return
        self._运行中 = False             # 换模型先暂停，避免加载瞬间运动
        self._重力开 = True              # 新模型默认采用 XML 中声明的重力
        self._用户暂停 = False
        self._记住的姿态 = None
        try:
            self._原始重力 = self._模型.opt.gravity.copy()
        except Exception:                                        # noqa: BLE001
            self._原始重力 = None
        self._应用重力()
        if self._数据 is not None:
            try:
                self._记住的姿态 = self._数据.qpos.copy()
            except Exception:                                        # noqa: BLE001
                pass
        # 立刻冻结（不等界面下发，避免"进模型瞬间掉一下"）
        self._冻结到默认位置(原因="模型已加载")

    def 插件状态(self) -> dict:
        return {"运行": "运行" if self._运行中 else "暂停",
                "重力": "开" if self._重力开 else "关",
                "复位": self._已复位}

    @property
    def 重力开(self) -> bool:
        """当前模型是否使用 XML 中的重力向量。"""
        return bool(self._重力开)

    @property
    def 运行中(self) -> bool:
        return bool(self._运行中)

    @property
    def 复位次数(self) -> int:
        return int(self._已复位)

    @property
    def 速度倍率(self) -> float:
        return float(self._速度倍率)

    @property
    def 最近动作(self) -> str:
        return str(self._最近动作)

    def 设重力开(self, 开: bool) -> None:
        """供外壳/面板直接设置重力；运行状态保持不变。"""
        开 = bool(开)
        if 开 == self._重力开:
            return
        self._重力开 = 开
        设界面重力(开)
        self._应用重力()
        print(f"【重力】已{'开启' if 开 else '关闭'}；仿真运行状态不变", flush=True)
        self._报状态()

    # ------------------------------------------------------------------
    # 向注册表登记"冻结判据"（这就是冻结生效的唯一机制）
    # ------------------------------------------------------------------
    def 登记到注册表(self, 注册表) -> None:
        """把 `_该冻结()` 登记给注册表。外壳在注册本插件后调一次。

        ★ 为什么需要显式登记：冻结不能用"改暂停快照"实现（官方不发快照，
          实测 6 秒 0 条），必须在**派发入口**上拦。详见本文件开头的说明。
        """
        self._注册表 = 注册表
        try:
            注册表.加冻结判据(self._该冻结)
            self._已登记判据 = True
        except Exception as 异常:                                        # noqa: BLE001
            print(f"⚠ 重力应用器无法登记冻结判据（冻结会失效）："
                  f"{type(异常).__name__}: {异常}")

    def _该冻结(self) -> bool:
        """注册表问的就是这一句：现在要不要冻结物理？"""
        return not self._运行中

    # ------------------------------------------------------------------
    # 界面来的开关
    # ------------------------------------------------------------------
    @messages.handler
    def 收状态(self, 消息: 重力状态) -> bool:
        重力开 = bool(getattr(消息, "重力开", False))
        if 重力开 == self._重力开:
            return False                 # 没变化 → 早退（这条消息每帧都到）
        self._重力开 = 重力开
        设界面重力(重力开)
        self._应用重力()
        print(f"【重力】已{'开启' if 重力开 else '关闭'}；仿真运行状态不变", flush=True)
        self._报状态()
        return False

    @messages.handler
    def 收仿真控制(self, 命令: 仿真控制命令) -> bool:
        """Run / Pause / Reset 的唯一落点。

        Pause 只关掉步进闸门，保持 qpos、qvel、ctrl 和 data.time；Reset 才调用
        外壳重新装配当前算法并清理 MuJoCo 状态。两者分开后，GUI 不再用一个
        “加载重力”开关同时表达三个动作。
        """
        动作 = str(getattr(命令, "动作", "暂停") or "暂停")
        if 动作 in ("运行", "run"):
            self._运行中 = True
            self._用户暂停 = False
            self._发官方暂停(False)
            self._最近动作 = "继续运行"
            print("【仿真】运行：从当前状态继续推进", flush=True)
        elif 动作 in ("暂停", "pause"):
            self._运行中 = False
            self._用户暂停 = True
            self._发官方暂停(True)
            self._最近动作 = "暂停在当前状态"
            print("【仿真】暂停：保持当前姿态与仿真时间", flush=True)
        elif 动作 in ("复位", "reset"):
            self._运行中 = False
            self._用户暂停 = True
            self._发官方暂停(True)
            说明 = ""
            if self._仿真复位回调 is not None:
                try:
                    说明 = str(self._仿真复位回调() or "")
                except Exception as 异常:                              # noqa: BLE001
                    print(f"⚠ 仿真复位回调失败（改用物理状态复位）："
                          f"{type(异常).__name__}: {异常}", flush=True)
            if 说明:
                self._已复位 += 1
                self._已冻结 += 1
            else:
                self._冻结到默认位置(原因="GUI Reset")
            self._最近动作 = "已复位并暂停"
            print(f"【仿真】复位完成，保持暂停{f'：{说明}' if 说明 else ''}", flush=True)
        elif 动作 in ("设置速度", "speed"):
            # 这里只保存并回传权威状态；真正的等待节拍由“实时固定步进”处理。
            # 改倍率不会改 timestep，因此控制器看到的 dt 与物理精度保持不变。
            self._速度倍率 = max(0.25, min(4.0, float(getattr(命令, "倍率", 1.0))))
            self._最近动作 = f"仿真速度已设为 {self._速度倍率:g}×"
            print(f"【仿真】目标速度：{self._速度倍率:g}×（物理步长不变）", flush=True)
        self._报状态()
        return False

    def _发官方暂停(self, 暂停: bool) -> None:
        """同步官方 StepControl，避免外壳闸门打开后它仍停在旧暂停状态。"""
        try:
            self._补发(messages.StepControlSnapshot(
                pause_state=(sim.PauseState.NORMAL_PAUSED if 暂停 else sim.PauseState.UNPAUSED),
                **self._快照参数))
        except Exception as 异常:                                      # noqa: BLE001
            print(f"⚠ 同步官方暂停状态失败：{type(异常).__name__}: {异常}", flush=True)

    def _报状态(self) -> None:
        if self._状态回调 is None:
            return
        try:
            self._状态回调()
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
    def 改暂停状态(self, 事件: messages.StepControlSnapshot) -> bool:
        # ★ 重入保护：这条快照如果是我们自己补发的，就原样放行 —— 否则会无限递归
        #   （见 __init__ 里 `_正在补发` 的说明；这个坑实测踩过，导致冻结完全失效）。
        if self._正在补发:
            return False
        try:
            self._用户暂停 = (事件.pause_state != sim.PauseState.UNPAUSED)
            self._快照参数 = dict(speed=事件.speed, noise_scale=事件.noise_scale,
                                  noise_rate=事件.noise_rate)
        except Exception:                                                # noqa: BLE001
            pass
        if self._运行中:
            return False                 # 运行中：原样放行
        # 冻结：发一条"暂停"的快照覆盖它
        #   （dataclass 是 frozen，不能原地改，只能照原值重建一条）
        try:
            参数 = dict(speed=事件.speed, noise_scale=事件.noise_scale,
                        noise_rate=事件.noise_rate)
        except Exception:                                                # noqa: BLE001
            参数 = {}
        try:
            self._补发(messages.StepControlSnapshot(
                pause_state=sim.PauseState.NORMAL_PAUSED, **参数))
        except Exception as 异常:                                        # noqa: BLE001
            if self._已冻结 == 0:        # 只在第一次报，避免刷屏
                print(f"⚠ 改写暂停状态失败（模型可能不会冻结）："
                      f"{type(异常).__name__}: {异常}")
        return False

    def _补发(self, 快照) -> None:
        """把改写后的快照送进内部消息通道，让官方 StepControl 收到。

        通道 = `安全注册表.处理消息`（外壳唯一的派发入口）。插件拿不到注册表引用，
        所以用 `插件系统.取注册表()` 这个公开访问器（见 插件系统.py 的契约例外 ①）。

        ★ `_正在补发` 必须在 finally 里复位：万一官方 StepControl 那边抛异常，
          旗子留在 True 上就再也改不动暂停状态了（冻结会静默失效）。
        """
        from 插件系统 import 取注册表
        注册表 = 取注册表()
        if 注册表 is None:
            return
        self._正在补发 = True
        try:
            注册表.处理消息(快照)
        finally:
            self._正在补发 = False

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _有home(self) -> bool:
        if self._模型 is None:
            return False

    def _应用重力(self) -> None:
        """只修改重力参数，不启动、暂停或复位仿真。"""
        if self._模型 is None or self._原始重力 is None:
            return
        try:
            self._模型.opt.gravity[:] = self._原始重力 if self._重力开 else 0.0
            if self._数据 is not None:
                import mujoco
                mujoco.mj_forward(self._模型, self._数据)
        except Exception as 异常:                                      # noqa: BLE001
            print(f"⚠ 应用重力参数失败：{type(异常).__name__}: {异常}", flush=True)
        try:
            import mujoco
            return mujoco.mj_name2id(self._模型, mujoco.mjtObj.mjOBJ_KEY, "home") >= 0
        except Exception:                                                # noqa: BLE001
            return False

    def _冻结到默认位置(self, 原因: str = "") -> None:
        """把模型摆回默认姿态并冻结。优先用外壳注入的回调（保证与"换算法时重置"同一套行为）。"""
        self._运行中 = False
        怎么做的 = ""
        if self._复位回调 is not None:
            try:
                怎么做的 = str(self._复位回调() or "")
            except Exception as 异常:                                    # noqa: BLE001
                print(f"⚠ 复位回调失败（改用本模块自带的复位）："
                      f"{type(异常).__name__}: {异常}")
        if not 怎么做的:
            怎么做的 = self._自己复位()
        self._已复位 += 1
        self._已冻结 += 1
        前缀 = f"（{原因}）" if 原因 else ""
        后缀 = f"：{怎么做的}" if 怎么做的 else ""
        print(f"【重力】{前缀}已回到默认位置并冻结，物理暂停{后缀}", flush=True)

    def _自己复位(self) -> str:
        """自带的兜底复位（外壳回调不可用时用）。与 `启动._重置姿态()` 同一套做法。"""
        if self._模型 is None or self._数据 is None:
            return ""
        try:
            import mujoco
            if self._有home():
                键 = mujoco.mj_name2id(self._模型, mujoco.mjtObj.mjOBJ_KEY, "home")
                mujoco.mj_resetDataKeyframe(self._模型, self._数据, 键)
                参考 = "home 关键帧"
            else:
                mujoco.mj_resetData(self._模型, self._数据)
                if self._记住的姿态 is not None:
                    n = min(len(self._记住的姿态), self._模型.nq)
                    self._数据.qpos[:n] = self._记住的姿态[:n]
                参考 = "模型初始 qpos"
            self._数据.qvel[:] = 0.0        # 关键帧不一定清速度；不清就会"带着旧速度出发"
            self._数据.ctrl[:] = 0.0        # 上一组算法写下的力矩也清掉
            mujoco.mj_forward(self._模型, self._数据)
            return 参考
        except Exception as 异常:                                        # noqa: BLE001
            print(f"⚠ 重置姿态失败：{type(异常).__name__}: {异常}")
            return ""


# ---------------------------------------------------------------------------
# 发布器：界面把开关状态发给仿真侧（只在变化 / 到时限时才真发）
# ---------------------------------------------------------------------------
class 发布器:
    """把【Display】的开关状态发给仿真侧。

    ★ 用 `Snapshot`（最新覆盖）语义 —— 界面每帧覆盖一次，所以**万一两边状态不同步
      （比如用户又去点了官方 Simulation 面板的暂停），下一帧就会被勾选框纠正回来**。
    """

    def __init__(self, 发送函数, 频率: float = 10.0):
        self._发 = 发送函数
        self._间隔 = 1.0 / max(频率, 1e-6)
        self._上次时间 = 0.0
        self._上次值 = None

    def 也许发布(self, 重力开: bool, 墙钟: float) -> None:
        if 重力开 == self._上次值 and (墙钟 - self._上次时间) < self._间隔:
            return
        self._上次时间, self._上次值 = 墙钟, 重力开
        try:
            self._发(重力状态(重力开=重力开))
        except Exception:                                                # noqa: BLE001
            pass                     # 这条通道坏了绝不能影响窗口绘制

    def 也许发布共享(self, 墙钟: float) -> None:
        """按**界面侧共享状态**发布（【Display】面板每帧调这个）。

        与 `也许发布(值, 墙钟)` 的区别：这里不接收调用方自己的那份状态，
        而是统一读 `重力桥.界面重力开` —— 所以另一个面板改了它，下一拍就会发出去，
        两个入口永远不会互相覆盖。
        """
        self.也许发布(界面重力开, 墙钟)


class 仿真状态发布器:
    """把运行/暂停与 data.time 作为独立状态发给自研 GUI（默认 5 Hz）。"""

    def __init__(self, 发送函数, 频率: float = 5.0) -> None:
        self._发 = 发送函数
        self._间隔 = 1.0 / max(频率, 1e-6)
        self._下次 = 0.0
        self._上次: tuple | None = None

    def 发布(self, 应用器: 重力应用器, 仿真时间: float, 强制: bool = False) -> bool:
        内容 = (bool(应用器.运行中), bool(应用器.重力开), float(仿真时间),
              int(应用器.复位次数), float(应用器.速度倍率), 应用器.最近动作)
        if not 强制 and 内容 == self._上次:
            return False
        self._上次 = 内容
        self._发(仿真状态(
            状态="运行" if 应用器.运行中 else "暂停",
            重力开=bool(应用器.重力开),
            仿真时间=float(仿真时间),
            复位次数=int(应用器.复位次数),
            速度倍率=float(应用器.速度倍率),
            说明=应用器.最近动作,
        ))
        return True

    def 也许发布(self, 应用器: 重力应用器, 仿真时间: float, 墙钟: float) -> bool:
        if 墙钟 < self._下次:
            return False
        self._下次 = 墙钟 + self._间隔
        return self.发布(应用器, 仿真时间)
