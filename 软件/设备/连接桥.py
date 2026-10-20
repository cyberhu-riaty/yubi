"""
设备/连接桥.py —— 把设备链路接到界面上的桥（部署页的控制端）

═══ 它连哪几样 ════════════════════════════════════════════════════════════
    界面 ──命令──► 连接桥 ──► 安全层 ──► 模拟后端
                      │
                      └──快照──► 界面（安全状态 / 遥测 / 审计）

═══ 三条必须守住的规矩 ═════════════════════════════════════════════════════
    ① **界面只能"请求"，不能"命令"**。
       进「运行」必须由人显式点按（规格 B3-8：禁用高风险自动化），
       所以这里没有任何"连上就自动跑"的入口。
    ② **来自真实硬件的量，没有硬件就显示"未接入"，不能显示 0**。
       现在只有模拟后端，所以 `后端=模拟` 会一路带到界面上，让人看得见。
    ③ **审计要能导出**。这是事后复盘的唯一依据，不能只留在内存里。

═══ 为什么把安全层建在这里，而不是建在界面里 ══════════════════════════════
    安全逻辑必须与 UI 无关：UI 崩了、关了，安全状态机不该跟着消失。
    所以连接桥持有 `安全层` 实例，UI 只是它的一个观察者。
"""
from __future__ import annotations

import dataclasses
import os
import time
from typing import Any, Callable

from 官方层 import messages

from .契约 import 控制模式, 安全状态
from .安全层 import 安全层
from .模拟后端 import 模拟后端


# ---------------------------------------------------------------------------
# 界面 → 仿真侧
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 连接命令(messages.Snapshot):
    动作: str = "快照"     # 打开 / 使能 / 进运行 / 停止 / 急停 / 设劣化 / 演练断线 / 导出审计
    延迟毫秒: float = -1.0        # <0 = 不改
    抖动毫秒: float = -1.0
    丢包率: float = -1.0
    编码器分辨率: float = -1.0


# ---------------------------------------------------------------------------
# 仿真侧 → 界面
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 连接状态(messages.Snapshot):
    后端: str = ""                  # ★ 永远带上后端名字，界面据此显示"模拟"而不是假装真机
    已连接: bool = False
    安全状态: str = "未连接"
    模式: str = "空闲"
    自由度: int = 0
    # ---- 劣化参数（界面上可调，改完立即生效）----
    延迟毫秒: float = 0.0
    抖动毫秒: float = 0.0
    丢包率: float = 0.0
    编码器分辨率: float = 0.0
    # ---- 实测遥测（全部来自真链路，不补零）----
    实测平均延迟: float = 0.0
    实测最大延迟: float = 0.0
    丢包数: int = 0
    错序数: int = 0
    拒绝数: int = 0
    最近位置: tuple = ()            # 空 = 还没有状态帧
    # ---- 审计（最近若干条，给界面列表用）----
    审计: tuple = ()                # 每项 {时刻, 类别, 内容, 错误码}
    说明: str = ""


class 连接桥:
    名称 = "设备连接"
    版本 = "0.1"

    def __init__(self, 发送函数: Callable[[Any], None], 包根: str = "",
                 自由度: int = 6):
        self._发送 = 发送函数
        self._包根 = 包根 or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._自由度 = int(自由度)
        self.层: 安全层 | None = None
        self.后: 模拟后端 | None = None
        self.打开次数 = 0
        self.最近: 连接状态 | None = None

    # ---- 懒建后端：界面不点"打开"就不占资源 ----
    def _建(self) -> 安全层:
        if self.层 is None:
            self.后 = 模拟后端(self._自由度)
            self.层 = 安全层(self.后, 看门狗毫秒=100.0,
                             单周期最大位移=0.02, 位置限位=(-3.0, 3.0))
        return self.层

    @messages.handler
    def 收命令(self, 命令: 连接命令) -> bool:
        动作 = str(getattr(命令, "动作", ""))
        try:
            if 动作 == "打开":
                self._打开()
            elif 动作 == "使能":
                self._建().使能(控制模式.位置)
            elif 动作 == "进运行":
                self._建().进运行()
            elif 动作 == "停止":
                self._建().停止("界面请求")
            elif 动作 == "急停":
                self._建().急停("界面请求")
            elif 动作 == "设劣化":
                self._设劣化(命令)
            elif 动作 == "演练断线":
                self._演练断线()
            elif 动作 == "导出审计":
                self._导出审计()
        except Exception as 异常:                                         # noqa: BLE001
            print(f"⚠ 设备命令「{动作}」失败：{type(异常).__name__}: {异常}", flush=True)
        self._发布()
        return False

    # ---- 各个动作 ----
    def _打开(self) -> None:
        层 = self._建()
        层.打开()
        self.打开次数 += 1
        print(f"【设备】已打开模拟后端（自由度 {self._自由度}）—— 注意：**不是真机**",
              flush=True)

    def _设劣化(self, 命令: 连接命令) -> None:
        层 = self._建()
        后 = self.后
        if 后 is None:
            return
        for 名 in ("延迟毫秒", "抖动毫秒", "丢包率", "编码器分辨率"):
            值 = float(getattr(命令, 名, -1.0))
            if 值 < 0:
                continue
            if 名 == "编码器分辨率":
                # 能力表是不可变的，改量化要重建一份（如实反映"换了编码器"）
                后.能力 = dataclasses.replace(后.能力, 编码器分辨率=值)
            else:
                setattr(后, 名, 值)
        层.审计.记("模式切换",
                    f"劣化参数：延迟 {后.延迟毫秒:.0f}ms、抖动 {后.抖动毫秒:.0f}ms、"
                    f"丢包 {后.丢包率*100:.0f}%、量化 {后.能力.编码器分辨率:g}")

    def _演练断线(self) -> None:
        """把后端"拔线"：之后不再出状态帧，看门狗应当触发。

        ★ 这是**演练**，不是故障注入接口 —— 它模拟的是"网线掉了"这一类事件。
        """
        层 = self._建()
        if self.后 is not None:
            self.后.关闭()
        层.审计.记("安全动作", "演练：模拟断线（后端关闭，不再出状态帧）")
        print("【设备】演练断线：后端已关闭，等看门狗触发", flush=True)

    def _导出审计(self) -> None:
        层 = self._建()
        目录 = os.path.join(self._包根, "输出", "06_部署审计")
        os.makedirs(目录, exist_ok=True)
        路径 = os.path.join(目录, f"审计_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        条数 = 层.审计.导出csv(路径)
        层.审计.记("安全动作", f"导出审计 {条数} 条 → {os.path.basename(路径)}")
        print(f"【设备】审计已导出 {条数} 条 → {路径}", flush=True)

    # ---- 泵：由仿真循环周期调用 ----
    def 也许泵(self, 墙钟: float, 间隔秒: float = 0.02) -> None:
        """驱动一次链路：读状态（喂看门狗）+ 按 50 Hz 发布。

        ★ 为什么必须有人泵：`读状态()` 是**拉式**接口 ——
          没人调用它，就不会有遥测，**看门狗也不会触发**（它只在读取时检查）。
          这也是真机上"控制循环必须活着"的同一件事：循环停了，安全逻辑就停了。
        """
        if self.层 is None:
            return
        try:
            self.层.读状态()
        except Exception:                                             # noqa: BLE001
            pass
        if 墙钟 >= getattr(self, "_下次发布", 0.0):
            self._下次发布 = 墙钟 + float(间隔秒)
            self._发布()

    # ---- 发布 ----
    def 也许发布(self, 墙钟: float) -> None:
        self._发布()

    def _发布(self) -> None:
        层 = self.层
        后 = self.后
        if 层 is None or 后 is None:
            状态 = 连接状态(后端="（未打开）", 说明="点「打开」才会创建模拟后端")
        else:
            健 = 层.健康()
            最近位置: tuple = ()
            if 层._最近状态 is not None and 层._最近状态.位置:      # noqa: SLF001
                最近位置 = tuple(float(x) for x in 层._最近状态.位置)  # noqa: SLF001
            审计 = tuple({
                "时刻": round(条.时刻, 3), "类别": 条.类别,
                "内容": 条.内容, "错误码": 条.错误码.value,
            } for 条 in 层.审计.最近(30))
            状态 = 连接状态(
                后端=后.名称,
                已连接=bool(健.已连接),
                安全状态=层.状态.value,
                模式=健.模式.value,
                自由度=int(后.自由度),
                延迟毫秒=float(后.延迟毫秒),
                抖动毫秒=float(后.抖动毫秒),
                丢包率=float(后.丢包率),
                编码器分辨率=float(后.能力.编码器分辨率),
                实测平均延迟=float(健.平均延迟毫秒 if 健.平均延迟毫秒 == 健.平均延迟毫秒 else 0.0),
                实测最大延迟=float(健.最大延迟毫秒 if 健.最大延迟毫秒 == 健.最大延迟毫秒 else 0.0),
                丢包数=int(健.丢包数),
                错序数=int(健.错序数),
                拒绝数=int(getattr(层, "_拒绝数", 0)),
                最近位置=最近位置,
                审计=审计,
                说明=健.说明,
            )
        self.最近 = 状态
        try:
            self._发送(状态)
        except Exception:                                             # noqa: BLE001
            pass
