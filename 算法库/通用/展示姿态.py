"""
展示姿态.py —— 【Display】展示模式（关重力、定在默认姿态）的仿真侧算法

它原来住在 `软件/重力桥.py` 里。方案 C 把"控制算法"统一收进 `算法库/` 之后
（这样它才能被项目文件声明、被界面上的算法列表显示出来），所以搬到这里。
桥那边只留**消息契约**（`关重力状态`）与发布器 —— 理由见下。

★ 为什么消息契约留在 `重力桥.py`、实现搬到这里（这是本项目的一条规定）：
  界面（`软件/面板/展示面板.py`）和仿真侧算法靠消息通信，而**消息能不能送达
  取决于两边引用的消息类是不是同一个对象**（仿真侧派发时会做
  `issubclass(type(消息), info.message_type)`，类型不同就静默跳过）。
  所以消息定义必须放在双方共同的、位置稳定的邻居里（桥），不能跟着实现走 ——
  这个坑本项目已经踩过两次，详见 `软件/录制桥.py` 的文件头。

它**不写 ctrl**，不和控制算法抢方向盘；只在展示模式下碰 qpos（复位那一下）。
"暂停"是怎么做到的：不改外壳，靠在官方 StepControl **之前**改写那条每帧的暂停快照
（细节见下面 `改暂停状态()` 的注释）。
"""
from __future__ import annotations

import os as _os
import sys as _sys

# 本文件在 算法库/通用/ 下，但要 import 外壳侧的 重力桥 / 插件系统 —— 先保证 软件/ 在 sys.path 上
_软件目录 = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                           "..", "..", "软件"))
if _os.path.isdir(_软件目录) and _软件目录 not in _sys.path:
    _sys.path.insert(0, _软件目录)

import mujoco                                                        # noqa: E402
from mujoco.experimental.studio import messages, sim, viewer_protocol  # noqa: E402
#   ★ `sim` = 官方暂停状态枚举（`sim.PauseState`），改写暂停快照时要用。
#     从 重力桥.py 搬过来时**漏过它一次**，代价是这个插件每帧抛 NameError、
#     被"再错一次就停用"的出错隔离永久停用（界面勾选框还在，但没人接）。
#     教训：搬代码时导入清单要和代码一起搬 —— 或者干脆让静态检查先跑一遍。

import 插件系统 as 插件                                                # noqa: E402
from 插件系统 import 取注册表                                          # noqa: E402
from 重力桥 import 关重力状态                                          # noqa: E402


class 展示姿态插件:
    """仿真侧插件：勾"关重力"时把模型定在默认姿态（暂停物理、不落）。

    它**不写 ctrl**，不和控制算法抢方向盘；只在展示模式下碰 qpos（复位那一下）。
    """

    名称 = "展示姿态（关重力）"
    版本 = "1.0"
    英文名 = "Display pose"          # 面板/清单上显示用（官方 UI 字体没有中文字形）
    # 不写 ctrl[:]（不抢方向盘）→ 不会和别的算法互相覆盖
    接管控制 = False
    说明 = "勾选【Display】时把模型定在默认姿态（暂停物理、无重力下落）；取消勾选恢复重力。"
    作者 = "数字样机"

    def __init__(self) -> None:
        self._模型 = None
        self._数据 = None
        self._模型路径 = ""
        self._关闭 = False                 # 展示模式开关（界面说了算）
        self._用户暂停 = False             # 用户自己在官方面板上的暂停意图
        self._记住的姿态 = None            # 没有 home 关键帧时的兜底姿态
        self._已复位 = 0

    # ------------------------------------------------------------------
    # 外壳挂钩（用现成机制，不改外壳）
    # ------------------------------------------------------------------
    def 收到模型(self, event) -> None:
        """模型加载/切换时调（外壳的 `通知模型加载` 会走到这里）。"""
        self._模型 = getattr(event, "model", None)
        self._数据 = getattr(event, "data", None)
        self._模型路径 = str(getattr(event, "path", "") or self._模型路径)
        self._关闭 = False                 # 换模型 → 回到"有重力"的正常状态
        self._用户暂停 = False
        self._记住的姿态 = None
        # ★ 兜底姿态：空场景/自建模型不一定有 `home` 关键帧（实测 `模型/空场景.xml` nkey=0）
        if self._模型 is not None and self._数据 is not None:
            try:
                self._记住的姿态 = self._数据.qpos.copy()
            except Exception:                                        # noqa: BLE001
                pass

    def 插件状态(self) -> dict:
        return {"展示模式": "开（无重力）" if self._关闭 else "关（正常重力）",
                "复位": self._已复位}

    # ------------------------------------------------------------------
    # 界面来的开关
    # ------------------------------------------------------------------
    @messages.handler
    def 收状态(self, 消息: 关重力状态) -> bool:
        关闭 = bool(getattr(消息, "关闭", False))
        if 关闭 == self._关闭:
            return False                   # 没变化 → 早退（这条消息每帧都到）
        self._关闭 = 关闭
        if 关闭:
            self._回到默认姿态()
            print(f"【展示】已关闭重力 → 回到默认姿态并暂停"
                  f"（参考：{'模型的 home 关键帧' if self._有home() else '加载时的姿态'}）", flush=True)
        else:
            print("【展示】已恢复重力 → 物理从默认姿态继续", flush=True)
        return False

    # ------------------------------------------------------------------
    # 官方每帧发的暂停快照：展示模式下把它改写成"暂停"再放行
    #   ★ 这是本模块最关键的一处。为什么不能"直接调 set_pause_state"：
    #     官方 ViewerApp **每帧**都会发一条 StepControlSnapshot（带着它自己那份 pause_state），
    #     官方 StepControl 收到就 apply —— 我们直接设的状态下一帧就被顶掉。
    #     所以只能在消息流上动手：**在官方 StepControl 之前**（快照派发发生得更早）改写 pause_state。
    #     实测依据：外壳仿真循环的顺序是 ① 处理快照 ② 派发 StepEvent，
    #     而安全注册表**按插件列表顺序**逐个派发（官方 StepControl 固定排在第 0 个），
    #     所以本插件能拦在它前面 —— 靠的是"排在第 0 个之后的顺序"，**不是** priority。
    #     ⚠️ 下面 `@messages.handler(priority=LIBRARY)` 的 priority 在本外壳里不起作用
    #        （跨插件排序只看列表顺序；见 插件系统.py 的说明）。
    #   ★ 额外好处：官方【Simulation】面板的暂停按钮会**同步显示为已暂停**，两处状态不打架。
    # ------------------------------------------------------------------
    @messages.handler(priority=messages.Priority.LIBRARY)
    def 改暂停状态(self, 事件: messages.StepControlSnapshot) -> bool:
        self._用户暂停 = (事件.pause_state != sim.PauseState.UNPAUSED)   # 记住用户自己的意图
        if not self._关闭:
            return False                    # 正常模式：原样放行
        # 展示模式：发一条"暂停"的快照覆盖它
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
            if self._已复位 == 0:        # 只在第一次报，避免刷屏
                print(f"⚠ 展示模式下改写暂停状态失败：{type(异常).__name__}: {异常}")
        return False

    def _补发(self, 快照) -> None:
        """把改写后的快照送进内部消息通道，让官方 StepControl 收到。

        ★ 通道从哪来：`主程序.py` 已经把「数据录制插件」挂上去了，它证明"仿真侧能收到
          界面发来的消息"；这里要走的是**反方向**（仿真侧 → 仿真侧的消息总线）。
          做法：外壳的 `注册表.处理消息` 就是我们唯一的派发入口，而插件拿不到注册表引用，
          所以改用 `插件系统.安全注册表` 的公开约定 —— 见 `main()` 里传入的注册表。
          为保持"不动外壳"，这里用一个**延迟绑定**：首次调用时从模块级共享位取。
        """
        取注册表().处理消息(快照)
    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _有home(self) -> bool:
        if self._模型 is None:
            return False
        try:
            return mujoco.mj_name2id(self._模型, mujoco.mjtObj.mjOBJ_KEY, "home") >= 0
        except Exception:                                            # noqa: BLE001
            return False

    def _回到默认姿态(self) -> None:
        if self._模型 is None or self._数据 is None:
            return
        try:
            if self._有home():
                键 = mujoco.mj_name2id(self._模型, mujoco.mjtObj.mjOBJ_KEY, "home")
                mujoco.mj_resetDataKeyframe(self._模型, self._数据, 键)
            else:
                mujoco.mj_resetData(self._模型, self._数据)
                if self._记住的姿态 is not None:
                    n = min(len(self._记住的姿态), self._模型.nq)
                    self._数据.qpos[:n] = self._记住的姿态[:n]
            # ★ 必须补一次 mj_forward：复位只写了 qpos/qvel，派生量（site 位置等）要重算，
            #   否则画面那一帧用的还是旧姿态算出来的东西。
            mujoco.mj_forward(self._模型, self._数据)
            self._已复位 += 1
        except Exception as 异常:                                        # noqa: BLE001
            print(f"⚠ 回到默认姿态失败（不影响使用）：{type(异常).__name__}: {异常}")
