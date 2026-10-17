"""
系统桥.py —— 运行期系统监视（P4 · SystemMonitor）

它解决什么问题：
    界面能显示"物理在跑"，但说不清**跑得怎么样**：
      · 实时率 RTF 是多少？（仿真时间 / 墙钟 —— 小于 1 就是跑不动）
      · 物理步频够不够？（算法写得重，步频会掉下来）
      · 进程占了多大内存？（长时间跑有没有涨）
    这三件事在排查"卡了/漂了/慢了"时是第一手信息，而它们**只能由仿真侧自己算**。

★ 这里只报**真的能量到的量**，量不到的宁可不报：
    · RTF / 步频 / 内存 —— 本进程内可精确测
    · 渲染帧率 —— 在**窗口层**（宿主窗口的 3D 视口统计），仿真侧看不到，
      所以这条**不在本消息里**。界面从视口统计里取（见 `宿主窗口.取统计()`）。
      把量不到的东西塞进契约，早晚会变成"界面显示一个永远 0 的数"。

为什么独立成一个桥、而不是塞进 指标桥：
    `指标` 是**插件**报的业务量（跟踪误差、力矩峰值…），名字由插件定；
    本消息是**外壳**报的系统量，字段固定。两者混在一起会让"指标"这个名字
    既表示业务量又表示系统量，界面没法区分该画曲线还是该显示数字。

数据流：
    仿真侧：启动.py 的热循环里每约 1 秒 → 系统桥.发布器.也许发布(...)
                    ↓ 自定义 Snapshot 消息（最新覆盖，不排队）
    界面侧：前端「监控」视图
"""
from __future__ import annotations

import dataclasses
import time
from typing import Any, Callable

from 官方层 import messages          # 全部走适配层，见 软件/官方层.py


# ---------------------------------------------------------------------------
# 仿真侧 → 界面：运行期系统指标
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 系统状态(messages.Snapshot):
    """运行期系统指标（监控视图的数据源）。

    ★ 字段都是"每秒算一次"的瞬时/累计量，**不是**高频变化的东西 ——
      所以频率 1 Hz 足够，不需要按帧发。
    """
    仿真时间: float = 0.0          # 累计仿真时间（秒）
    墙钟: float = 0.0              # 累计墙钟（秒，从开始跑算）
    RTF: float = 0.0               # 实时率 = 仿真时间增量 / 墙钟增量（1.0 = 实速）
    步频: float = 0.0              # 物理步/秒
    仿真步长: float = 0.0          # 模型的 timestep（秒）
    内存MB: float = 0.0            # 本进程常驻内存
    插件数: int = 0                # 当前装了几个插件
    出错: str = ""                 # 采样失败时的说明（空 = 正常）


def _内存MB() -> float:
    """本进程常驻内存（MB）。用标准库，不引依赖（这软件要能离线重建环境）。"""
    try:
        import resource
        # macOS / Linux 的 ru_maxrss 单位不同：macOS 是字节，Linux 是 KB
        import sys
        值 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return 值 / (1024 * 1024) if sys.platform == "darwin" else 值 / 1024
    except Exception:                                                 # noqa: BLE001
        return 0.0


class 发布器:
    """周期性把系统指标发给界面（默认 1 Hz）。

    ★ 为什么 1 Hz：这些量的意义在"趋势"，不在"每一帧"。发到 10 Hz 只会
      让监控视图的数字跳得看不清，还白占带宽。
    """

    def __init__(self, 发送函数: Callable[[Any], None], 频率: float = 1.0):
        self._发送 = 发送函数
        self._间隔 = 1.0 / max(频率, 1e-6)
        self._下次 = 0.0
        self._上次时刻 = time.perf_counter()
        self._上次仿真时间 = 0.0
        self._上次步数 = 0
        self._起始时刻 = time.perf_counter()
        self.已发布 = 0
        self.最近: 系统状态 | None = None
        # ★ 第一次调用只用来**定基准**，不发消息。
        #   否则 RTF = （首次调用时的仿真增量）/（初始化到现在的极短间隔），
        #   实测会算出 RTF=578 这种离谱数字 —— 界面第一个样本就是错的，
        #   而"监控面板一开始显示一个荒谬值"最容易让人以为整个监控是假的。
        self._已就绪 = False

    def 也许发布(self, 仿真时间: float, 步数: int, 仿真步长: float,
                 插件数: int, 墙钟: float) -> bool:
        """到点就采一次并发出。返回是否真的发了。

        参数
          仿真时间 : 当前的 `data.time`
          步数     : 当前的累计物理步数（用来算步频）
          仿真步长 : 模型的 `timestep`
          插件数   : 当前注册表里有几个插件
          墙钟     : `time.perf_counter()`（调用方传，避免这里再取一次导致抖动）
        """
        if 墙钟 < self._下次:
            return False
        self._下次 = 墙钟 + self._间隔

        现在 = time.perf_counter()
        if not self._已就绪:
            # 只用这一次把基准对齐，不发
            self._已就绪 = True
            self._上次时刻 = 现在
            self._上次仿真时间 = 仿真时间
            self._上次步数 = 步数
            return False
        墙钟增量 = max(1e-9, 现在 - self._上次时刻)
        仿真增量 = 仿真时间 - self._上次仿真时间
        步增量 = max(0, 步数 - self._上次步数)

        RTF = 仿真增量 / 墙钟增量
        步频 = 步增量 / 墙钟增量

        self._上次时刻 = 现在
        self._上次仿真时间 = 仿真时间
        self._上次步数 = 步数

        状态 = 系统状态(
            仿真时间=float(仿真时间),
            墙钟=float(现在 - self._起始时刻),
            RTF=float(RTF),
            步频=float(步频),
            仿真步长=float(仿真步长),
            内存MB=float(_内存MB()),
            插件数=int(插件数),
            出错="",
        )
        self.最近 = 状态
        try:
            self._发送(状态)
            self.已发布 += 1
            return True
        except Exception as 异常:                                         # noqa: BLE001
            # 通道坏了绝不能拖垮仿真
            if self.已发布 == 0:
                print(f"⚠ 系统指标发布失败（不影响控制）：{type(异常).__name__}: {异常}")
            return False
