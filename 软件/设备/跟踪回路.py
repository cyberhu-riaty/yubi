"""
设备/跟踪回路.py —— 把控制器接到设备链路上，让"延迟"真的咬人

═══ 为什么需要这一层 ═══════════════════════════════════════════════════════
    上一版做完设备抽象后，延迟注入只影响**观测**：模拟后端自带"伺服跟参考"，
    延迟再大动力学也稳。这不是 bug，是**闭环里没有控制器**。

    真机上的失稳链条是这样的：
        控制器用**收到的（旧的）状态**算指令 → 指令迟到 → 实际状态更偏 → 指令更大 …
    要把这条链在仿真里复现，就必须让"用延迟状态算指令"这一步真的存在于回路中。

═══ 两个诚实声明 ═══════════════════════════════════════════════════════════
    ① 这一层是**演示与控制律验证**用的最小闭环（位置 PD + 重力/无重力一视同仁），
       不是"真机控制器"。真机还要考虑摩擦、柔性、电机环、限幅动力学。
    ② 它的价值在于**能定量回答一个问题**：
       "同一个增益，延迟从 0 增到多少毫秒会开始振荡？" —— 这个数在真机上试是撞机，
       在这里试是改一行参数。
"""
from __future__ import annotations

import time

import numpy as np


class 跟踪回路:
    """用**收到的状态**算位置 PD 指令，经安全层下发。

    ★ 关键点：`步进()` 里读到的状态可能是**上一帧甚至更早**的 ——
      这不是缺陷，正是要复现的现实。真机控制器永远拿不到"此刻"的真实状态。
    """

    def __init__(self, 层, *, kp: float = 60.0, kd: float = 8.0, 步长秒: float = 0.002):
        self.层 = 层
        self.kp = float(kp)
        self.kd = float(kd)
        self.步长秒 = float(步长秒)
        self.目标: np.ndarray | None = None
        self.历史: list[tuple[float, float, float]] = []   # (墙钟, 指令, 实际)
        self._上次指令: np.ndarray | None = None

    def 设目标(self, 目标) -> None:
        self.目标 = np.asarray(目标, dtype=float).ravel()

    def 步进(self) -> bool:
        """走一步。返回是否真的下发了指令。

        ★ 只读**一帧**：`读状态()` 是非阻塞的，可能拿到旧帧（单步保持）
          或同一帧（没出新帧）—— 这两种都算"这一刻我只有这些信息"，
          控制器就该基于它做决定。这正是延迟影响的来源。
        """
        状态 = self.层.读状态()
        if 状态 is None or not 状态.位置:
            return False
        实际 = np.asarray(状态.位置, dtype=float)
        速度 = np.asarray(状态.速度, dtype=float) if 状态.速度 else np.zeros_like(实际)
        目标 = self.目标 if self.目标 is not None else 实际
        if 目标.size != 实际.size:
            return False
        # 位置 PD：指令 = 目标 + Kp·误差 - Kd·速度（再用安全层的增量限幅管住突变）
        误差 = 目标 - 实际
        指令 = 目标 + self.kp * 误差 * self.步长秒 - self.kd * 速度 * self.步长秒
        果 = self.层.写命令(期望位置=指令)
        if 果.成功:
            self._上次指令 = 指令
            现在 = time.perf_counter()
            self.历史.append((现在, float(np.max(np.abs(指令))), float(np.max(np.abs(实际)))))
            del self.历史[:-4000]
            return True
        return False


def 阶跃响应(延迟毫秒: float, kp: float = 60.0, kd: float = 8.0,
             时长秒: float = 3.0) -> dict:
    """跑一次"0 → 1"的位置阶跃，返回超调/稳态误差/是否发散等指标。

    这是 L2 最该回答的问题：**同一个增益，延迟到多少会失控**。
    """
    from .契约 import 控制模式
    from .模拟后端 import 模拟后端
    from .安全层 import 安全层

    后 = 模拟后端(1, 延迟毫秒=延迟毫秒, 出帧周期毫秒=2)
    层 = 安全层(后, 看门狗毫秒=1000, 单周期最大位移=1.0, 位置限位=(-10, 10))
    层.打开()
    层.使能(控制模式.位置)

    # 预热：等到真的收到状态帧（不能拍固定毫秒数 —— 延迟大于预热时长就收不到）
    截止 = time.perf_counter() + 2.0
    while 层._最近状态 is None and time.perf_counter() < 截止:
        层.读状态()
        time.sleep(0.001)
    if 层._最近状态 is None:
        return {"可达": False}

    回路 = 跟踪回路(层, kp=kp, kd=kd)
    回路.设目标([1.0])
    回路.步进()                      # 首帧保护会把这条改成"保持"
    层.进运行()

    峰 = 0.0
    末 = None
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 时长秒:
        回路.步进()
        time.sleep(0.001)
        if 后._物理.q.size:
            末 = float(后._物理.q[0])
            峰 = max(峰, 末)
    实际延迟 = 后.健康().平均延迟毫秒
    return {
        "可达": True, "峰值": 峰, "超调%": (峰 - 1.0) * 100.0,
        "稳态误差": abs((末 if 末 is not None else 0.0) - 1.0),
        "平均延迟毫秒": 实际延迟,
        "发散": 峰 > 5.0 or (末 is not None and abs(末) > 5.0),
        "安全状态": 层.状态.value,
    }
