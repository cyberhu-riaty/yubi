"""平台宿主接口，约定可用性探测、窗口主循环、视口位置和运行统计。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PlatformCapabilities(ABC):
    """桌面窗口适配器的公共接口。"""

    #: 给人看的平台名（诊断输出用）
    name: str = "未命名"

    # ------------------------------------------------------------------
    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """这个平台现在能不能起窗口。返回 (可用?, 不可用时的原因)。

        ★ 必须是"能查的"，不能靠 try/except 猜：入口要在起窗口**之前**
          就知道该不该回退（比如缺 PyObjC 时应该提示装什么，而不是抛一堆栈）。
        """

    @abstractmethod
    def run(self, *, url: str, title: str, width: float, height: float,
           command_queue: Any = None, no_3d: bool = False,
           viewport_slot: dict | None = None) -> int:
        """起窗口并**阻塞**到用户关窗。返回进程退出码。

        参数
          地址      : WebView 要加载的地址（通常是本机 `http://127.0.0.1:<口>/`）
          标题      : 窗口标题
          宽 / 高   : 初始窗口尺寸（逻辑像素）
          命令队列  : 仿真线程每圈排空的线程安全队列
          无3D      : True 时不要原生渲染面，网页铺满（排查用）
          视口槽    : 可选 dict，平台层**建好原生渲染面后回填**
                      `视口槽["视口"] = <渲染面对象>`。
                      用途：入口把"仿真每步的状态"喂给它（`视口.收_状态`），
                      而不必知道这个渲染面是什么平台的东西 ——
                      **这是平台层与入口之间唯一的状态通道，只有这一个。**

        约定
          · 主线程归平台事件循环；仿真必须在**后台线程**（见 `启动.启动外壳(后台线程=True)`）
          · 不得与仿真共享 `MjData`（跨线程可变对象），只通过状态快照同步
        """

    @abstractmethod
    def viewport_rectangle(self) -> tuple[int, int, int, int] | None:
        """原生渲染面当前占的矩形 (x, y, 宽, 高)，逻辑像素；没有则 None。

        用途：网页侧需要知道"哪一块被原生面占了"，才不会在那里画东西、
        也才能把浮层排到正确的位置。
        """

    @abstractmethod
    def statistics(self) -> dict:
        """运行统计（帧率、帧数、错误…）。用于自检与排查，**不参与业务**。"""
