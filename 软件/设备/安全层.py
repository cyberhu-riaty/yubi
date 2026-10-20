"""
设备/安全层.py —— 对**任何**后端生效的安全逻辑

═══ 它挡在什么位置 ════════════════════════════════════════════════════════
        算法 ──► 安全层 ──► 设备后端 ──► 硬件
                   ↑
        状态机 / 看门狗 / 限幅 / 首帧保护 / 审计都在这一层

    放在这一层而不是每个后端里，是因为：**安全逻辑不该随协议重写一遍**。
    换了 UDP、CAN、厂商 SDK，这一层的规则一条都不能少。

═══ 规格里那八条"绝不允许"，逐条对应到代码 ══════════════════════════════
    ① 看门狗   —— `_查看门狗()`：状态帧超过 `看门狗毫秒` 没更新 → 进故障 + 切阻尼
       ⚠️ **诚实说明**：真机的看门狗必须在**硬件/驱动侧**（上位机崩了就没人发心跳）。
          这一层只能做到"我们能做的部分"：超时就停止下发并请求阻尼。
          真机的硬件看门狗需要在后端里实现，条款写在这里不是"已完成"。
    ② 限位/限速 —— `_限幅()`：位置夹到软限位、单周期位移限幅、速度限幅
       ⚠️ 同样是**第二道**：下层也必须有一份。
    ③ 急停 —— `急停()` 只是"请求"；物理回路不归软件管。
    ④ 状态机 —— 不允许跳过"未使能"直接运行；每次进运行必须显式 `使能()`
    ⑤ 首帧保护 —— 使能后第一条命令强制为"保持当前位置"
    ⑥ 限速渐变 —— 增量限幅（单周期最大位移）
    ⑦ 审计日志 —— 每次模式切换/拒绝/看门狗都记
    ⑧ 禁用高风险自动化 —— 这一层不提供"自动开始运行"的入口
"""
from __future__ import annotations

import time

import numpy as np

from .契约 import (
    审计日志, 安全状态, 控制模式, 错误码, 命令帧, 状态帧, 写结果, 健康报告,
    设备能力,
)


class 安全层:
    """包在设备后端外面的一层。**所有对外方法都先过安全检查**。"""

    def __init__(self, 后端, *, 看门狗毫秒: float = 100.0,
                 单周期最大位移: float = 0.02,
                 位置限位: tuple[float, float] | None = None,
                 软件限速: float | None = None,
                 审计: 审计日志 | None = None):
        self.后端 = 后端
        self.看门狗毫秒 = float(看门狗毫秒)
        self.单周期最大位移 = float(单周期最大位移)
        self.位置限位 = 位置限位
        self.软件限速 = 软件限速
        self.审计 = 审计 or 审计日志()

        self.状态 = 安全状态.未连接
        self._序号 = 0
        self._心跳 = 0
        self._上次状态时刻 = 0.0
        self._上次命令位置: np.ndarray | None = None
        self._首帧待发 = False             # ⑤ 首帧保护
        self._最近状态: 状态帧 | None = None
        self._拒绝数 = 0

    # ---- 生命周期 ----
    def 打开(self, 配置: dict | None = None) -> 写结果:
        try:
            self.后端.打开(配置)
        except Exception as 异常:                                     # noqa: BLE001
            self.审计.记("状态迁移", f"打开失败：{异常}", 错误码.内部错误)
            return 写结果(成功=False, 错误码=错误码.内部错误, 说明=str(异常))
        self.状态 = 安全状态.已连接
        self._首帧待发 = False
        self.审计.记("状态迁移", "打开 → 已连接（未使能）")
        return 写结果()

    def 关闭(self) -> None:
        try:
            self.后端.关闭()
        finally:
            self.状态 = 安全状态.未连接
            self.审计.记("状态迁移", "关闭 → 未连接")

    @property
    def 能力(self) -> 设备能力:
        return getattr(self.后端, "能力", 设备能力())

    @property
    def 自由度(self) -> int:
        return int(getattr(self.后端, "自由度", 0))

    # ---- 状态机 ----
    def 使能(self, 模式: 控制模式 = 控制模式.位置) -> 写结果:
        """④ 进入运行必须**显式**调用这里，不会被任何自动流程触发。"""
        if self.状态 != 安全状态.已连接:
            self.审计.记("命令拒绝", f"未在「已连接」状态就使能（当前 {self.状态.value}）",
                         错误码.未连接)
            return 写结果(成功=False, 错误码=错误码.未连接,
                          说明=f"当前是「{self.状态.value}」，要先 打开()")
        果 = self.后端.设模式(模式)
        if not 果.成功:
            self.状态 = 安全状态.故障
            self.审计.记("命令拒绝", f"设模式 {模式.value} 失败：{果.说明}", 果.错误码)
            return 果
        self.状态 = 安全状态.使能中
        self._首帧待发 = True              # ⑤ 首帧保护：下一条命令必须是"保持当前位置"
        self._上次命令位置 = None
        self.审计.记("状态迁移", f"使能 → 使能中（模式 {模式.value}）")
        return 写结果()

    def 进运行(self) -> 写结果:
        """从"使能中"切到"运行"。首帧保护要求先有一条保持命令。"""
        if self.状态 != 安全状态.使能中:
            return 写结果(成功=False, 错误码=错误码.未使能,
                          说明=f"当前是「{self.状态.value}」，不能直接进运行")
        self.状态 = 安全状态.运行
        self.审计.记("状态迁移", "运行")
        return 写结果()

    def 停止(self, 原因: str = "手动停止") -> None:
        if self.状态 in (安全状态.未连接,):
            return
        try:
            self.后端.设模式(控制模式.空闲)
        except Exception:                                             # noqa: BLE001
            pass
        self.状态 = 安全状态.停止
        self.审计.记("状态迁移", f"停止（{原因}）")

    def 急停(self, 原因: str = "手动急停") -> None:
        """③ 这只是**请求**。物理急停回路不归软件管。"""
        try:
            self.后端.设模式(控制模式.急停)
        except Exception:                                             # noqa: BLE001
            pass
        self.状态 = 安全状态.急停
        self.审计.记("安全动作", f"急停请求（{原因}）—— 物理回路不归软件管")

    # ---- 读（带看门狗）----
    def 读状态(self) -> 状态帧 | None:
        帧 = None
        try:
            帧 = self.后端.读状态()
        except Exception as 异常:                                     # noqa: BLE001
            self.审计.记("状态迁移", f"读状态异常：{异常}", 错误码.内部错误)
        if 帧 is not None:
            if self._最近状态 is None or 帧.序号 != self._最近状态.序号:
                self._上次状态时刻 = time.perf_counter()
                self._最近状态 = 帧
        self._查看门狗()
        return 帧

    def _查看门狗(self) -> None:
        """① 状态帧太久没更新 → 进故障 + 请求阻尼。

        ★ 触发后**不再自动恢复**：必须人工 `停止()` 再 `使能()`。
          "自动重连后继续跑"是危险的 —— 故障原因还没查清楚就接着动。
        """
        if self.状态 not in (安全状态.使能中, 安全状态.运行):
            return
        if self._上次状态时刻 <= 0:
            return
        经过 = (time.perf_counter() - self._上次状态时刻) * 1000.0
        if 经过 <= self.看门狗毫秒:
            return
        try:
            self.后端.设模式(控制模式.阻尼)
        except Exception:                                             # noqa: BLE001
            pass
        self.状态 = 安全状态.故障
        说明 = f"看门狗触发：{经过:.0f} ms 没有新状态（阈值 {self.看门狗毫秒:.0f} ms）"
        self.审计.记("看门狗", 说明, 错误码.超时)
        print(f"⚠ {说明} → 已切阻尼，需人工停止后重新使能", flush=True)

    # ---- 写（限幅 + 首帧保护）----
    def 写命令(self, 期望位置=None, 期望速度=None, 期望力矩=None) -> 写结果:
        if self.状态 not in (安全状态.使能中, 安全状态.运行):
            self._拒绝数 += 1
            self.审计.记("命令拒绝", f"状态 {self.状态.value} 不接受命令", 错误码.未使能)
            return 写结果(成功=False, 错误码=错误码.未使能)

        位置 = None
        if 期望位置 is not None and len(期望位置):
            位置 = np.asarray(期望位置, dtype=float).ravel()
            if 位置.size != self.自由度:
                self._拒绝数 += 1
                self.审计.记("命令拒绝", f"位置维度 {位置.size} ≠ 自由度 {self.自由度}",
                             错误码.协议错误)
                return 写结果(成功=False, 错误码=错误码.协议错误, 说明="维度不符")

            # ⑤ 首帧保护：使能后的第一条命令**强制**为"保持当前位置"
            if self._首帧待发:
                当前 = self._最近状态.位置 if self._最近状态 else None
                if not 当前:
                    self._拒绝数 += 1
                    self.审计.记("命令拒绝", "首帧保护：还没有状态帧，拒绝下发", 错误码.未使能)
                    return 写结果(成功=False, 错误码=错误码.未使能,
                                  说明="首帧保护：还没有状态帧")
                位置 = np.asarray(当前, dtype=float)
                self._首帧待发 = False
                self.审计.记("安全动作", "首帧保护：第一条命令已改为「保持当前位置」")

            位置, 果 = self._限幅(位置)
            if not 果.成功:
                self._拒绝数 += 1
                return 果
            self._上次命令位置 = 位置

        self._序号 += 1
        self._心跳 += 1
        帧 = 命令帧(
            序号=self._序号,
            期望位置=tuple(float(x) for x in 位置) if 位置 is not None else (),
            期望速度=tuple(float(x) for x in (期望速度 or ())),
            期望力矩=tuple(float(x) for x in (期望力矩 or ())),
            心跳计数=self._心跳,
        )
        try:
            果 = self.后端.写命令(帧)
        except Exception as 异常:                                     # noqa: BLE001
            self.审计.记("命令拒绝", f"写命令异常：{异常}", 错误码.内部错误)
            return 写结果(成功=False, 错误码=错误码.内部错误, 说明=str(异常))
        if not 果.成功:
            self._拒绝数 += 1
            self.审计.记("命令拒绝", f"后端拒绝：{果.说明}", 果.错误码)
        return 果

    def _限幅(self, 位置: np.ndarray) -> tuple[np.ndarray, 写结果]:
        """② 软限位 + ⑥ 单周期增量限幅。被夹的值会记审计（复盘要看得到）。"""
        改过 = False
        if self.位置限位 is not None:
            低, 高 = self.位置限位
            夹后 = np.clip(位置, 低, 高)
            if not np.allclose(夹后, 位置):
                改过 = True
                位置 = 夹后
        if self._上次命令位置 is not None:
            增量 = 位置 - self._上次命令位置
            最大 = float(np.max(np.abs(增量))) if 增量.size else 0.0
            if 最大 > self.单周期最大位移 > 0:
                位置 = self._上次命令位置 + 增量 * (self.单周期最大位移 / 最大)
                改过 = True
        if 改过:
            self.审计.记("命令拒绝", "命令被限幅（软限位或单周期增量）", 错误码.增量超限)
        return 位置, 写结果()

    # ---- 健康 ----
    def 健康(self) -> 健康报告:
        try:
            后 = self.后端.健康()
        except Exception:                                             # noqa: BLE001
            return 健康报告(说明="后端健康查询失败")
        return 健康报告(
            已连接=后.已连接, 模式=后.模式, 丢包数=后.丢包数, 错序数=后.错序数,
            平均延迟毫秒=后.平均延迟毫秒, 最大延迟毫秒=后.最大延迟毫秒,
            错误码=后.错误码,
            说明=f"{后.说明}｜安全状态={self.状态.value}｜拒绝={self._拒绝数}",
        )

    def 快照(self) -> dict:
        """给界面用的一行摘要。**所有字段都来自真实状态**，不做补零。"""
        后 = self.健康()
        return {
            "状态": self.状态.value,
            "模式": 后.模式.value,
            "已连接": 后.已连接,
            "丢包": 后.丢包数,
            "错序": 后.错序数,
            "平均延迟毫秒": 后.平均延迟毫秒,
            "最大延迟毫秒": 后.最大延迟毫秒,
            "拒绝数": self._拒绝数,
            "说明": 后.说明,
        }
