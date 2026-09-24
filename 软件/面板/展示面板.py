"""
面板/展示面板.py —— 左上角的小方框：**勾选 = 无重力的展示姿态；不勾 = 正常有重力**

它解决什么问题（用户原话）：
    "模型刚加载的时候就受到重力影响往下掉。如果在纯展示的时候（即没有加载控制算法），
     在界面的左上角设计一个小方框，勾选的时候展示模型的默认姿态（即无重力影响），
     没有勾选的时候则有重力影响。"

为什么是**独立的小窗口**，而不是塞进【工作台】的页签：
    用户明确要"界面左上角的一个小方框"，展示场景下要一眼看到、随手指点。
    塞进页签就得先切页签，反而绕。所以本面板是一间独立浮动窗口，
    第一次由我们摆在左上角（`FirstUseEver`，之后 ImGui 记住用户拖到的位置）。

★ 它为什么**关不掉**（`不可关闭 = True`）：
    它是"展示模式"的唯一开关。要是被关掉，用户就再也找不到（这正是
    `面板注册表.py` 文件头记着的那次事故）。所以它和【模型库】一样不可关闭。

它到底做了什么（技术要点，实测过）：
    **光把重力设成 0 是不够的** —— 机械臂会停在"掉到一半"的姿态，而且还会继续动。
    正确做法是 ① 数据复位到默认姿态 ② **暂停物理**。
    这两件事在仿真侧由 `重力桥.重力状态应用器` 做：
        · 默认姿态 = 模型的 `home` 关键帧；没有 keyframe 的模型（如空场景）用"加载时的姿态"
        · 暂停用官方 `sim.StepControl.set_pause_state(NORMAL_PAUSED)`
          —— 实测暂停后连打 500 次 `advance()`，`qpos` 变化 **0.0**（真冻住）
        · 用官方暂停的好处：官方【Simulation】面板的暂停按钮会同步显示"已暂停"

★ 面板上的文字**只能是 ASCII**：官方 UI 字体没有中文字形，中文会画成 `?`
  （中文说明在终端与文档里）。校验：`./.venv/bin/python 优化（软件优化的报告都放这里面来）/验证/字体覆盖.py`
"""
from __future__ import annotations

import os as _os
import sys as _sys
import time as _time

_外壳目录 = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _外壳目录 not in _sys.path:
    _sys.path.insert(0, _外壳目录)

from mujoco.experimental.dear_imgui import dear_imgui as imgui       # noqa: E402
from mujoco.experimental.studio import messages, viewer_protocol      # noqa: E402

import 面板注册表                                                      # noqa: E402
from 重力桥 import 发布器, 关重力状态                                   # noqa: E402

# 第一次出现时放哪（左上角；之后由 ImGui 记住用户拖到的位置）
初始位置 = (12.0, 56.0)
初始大小 = (232.0, 96.0)


class 展示面板:
    """窗口侧插件：左上角的小方框（关重力 / 回默认姿态）。"""

    面板显示名 = "展示"
    页签名 = "Display"

    # ★ 独立窗口：**不参与【工作台】的页签**，永远以自己的小窗口出现。
    #   为什么：用户要的是"界面左上角的一个小方框"——收进页签就得先切页签才看得见，
    #   而展示场景下它必须一眼可见、随手指点（容器会读这个属性并跳过本面板）。
    独立窗口 = True

    # ★ 不可关闭：它是"展示模式"的唯一开关（细节见文件头）
    不可关闭 = True

    def __init__(self):
        self.viewer = None
        self.可见 = True
        self.关闭重力 = False          # 勾选框状态：True = 无重力展示姿态
        self.摆放过 = False
        self.绘制次数 = 0
        self.错误次数 = 0
        self._发布 = 发布器(self._发送, 频率=10.0)
        self._上次勾选 = False

    # ------------------------------------------------------------------
    @messages.handler(priority=messages.Priority.CRITICAL)
    def 记下窗口(self, event: viewer_protocol.ViewerInitEvent) -> bool:
        self.viewer = event.viewer
        return False

    def _发送(self, 消息: 关重力状态) -> None:
        if self.viewer is not None:
            self.viewer.send_to_sim(消息)

    # ------------------------------------------------------------------
    @messages.handler
    def 每帧发布(self, event: messages.UpdateEvent) -> bool:
        """每帧把勾选状态发给仿真侧（内部只在变化/到时限时才真发）。

        ★ 不看 `self.可见`：面板被收进容器或被拖到看不见的地方时，
          这条开关也必须继续生效（否则"物理停着但勾选框已经取消"会打架）。
        """
        self._发布.也许发布(self.关闭重力, _time.perf_counter())
        return False

    # ------------------------------------------------------------------
    @messages.handler
    def 画面板(self, event: messages.BuildGuiEvent) -> bool:
        # ★ 必须在"可见性检查"之前：即使被收进容器/关掉，也要能响应 F9 恢复
        面板注册表.每帧(self)
        if not self.可见:
            return False
        self.绘制次数 += 1
        if not self.摆放过:
            self.摆放过 = True
            # 只用 FirstUseEver：我们只管"第一次"放哪，之后尊重用户拖到的位置
            imgui.SetNextWindowPos(imgui.Vec2(*初始位置), imgui.Cond.FirstUseEver.value)
            imgui.SetNextWindowSize(imgui.Vec2(*初始大小), imgui.Cond.FirstUseEver.value)
        # NoCollapse：这个窗口小，被折叠起来就只剩标题栏（用户会以为坏了）
        # 不传 p_open（第二项 None）→ 没有 ×（刻意的，见类文档）
        展开, _ = imgui.Begin("Display", None, imgui.WindowFlags.NoCollapse)
        面板注册表.记录(self)
        try:
            if not 展开:
                return False
            self._画内容()
        except Exception as 异常:                                          # noqa: BLE001
            self.错误次数 += 1
            if self.错误次数 <= 2:
                print(f"⚠ 展示面板绘制出错：{type(异常).__name__}: {异常}")
        finally:
            imgui.End()
        return False

    # ------------------------------------------------------------------
    def _画内容(self) -> None:
        变了, 新值 = imgui.Checkbox("Gravity off (default pose)", self.关闭重力)
        if 变了:
            self.关闭重力 = bool(新值)
            if self.关闭重力 != self._上次勾选:
                self._上次勾选 = self.关闭重力
                # 立刻发一次，不用等到下一个 10 Hz 节拍（点一下要马上有反应）
                self._发布.也许发布(self.关闭重力, _time.perf_counter() + 1e9)

        if self.关闭重力:
            imgui.TextDisabled("showing the model's default pose")
            imgui.TextDisabled("(physics paused - no gravity drop)")
        else:
            imgui.TextDisabled("gravity on - the model behaves normally")
        imgui.TextDisabled("uncheck to let gravity act again")


# 启动器约定：模块里叫“面板类”的就是要实例化的面板
面板类 = 展示面板
