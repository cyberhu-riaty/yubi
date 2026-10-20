"""
设备/模拟后端.py —— 在仿真里"当硬件用"的后端

═══ 它为什么重要 ═══════════════════════════════════════════════════════════
    没有真机的时候，唯一能验证整条链路（连接→使能→运行→超时→安全动作）的办法，
    就是有一个**行为像硬件**的后端。它不是"假数据生成器"，
    而是"一个可以被劣化的、可复现的假硬件"。

═══ 劣化注入不是加 sleep（规格明确要求）═══════════════════════════════════
    · **延迟**：状态帧不是立刻可见，而是排队到 deadline 之后才被 `读状态()` 取走。
      这是接口级的（`采集时刻` 与 `接收时刻` 真的不同），不是 `time.sleep` 拖慢整个进程。
    · **抖动**：每帧延迟加随机偏移（固定种子 → 可复现）。
    · **丢包**：按概率直接丢弃状态帧（于是序号会跳，`错序数` 能统计到）。
    · **量化**：位置按编码器分辨率取整（真机就是这样，控制器的抖动可能来自这里）。
    · **单步保持**：硬件按固定周期出状态，不是每次调用都出新帧 ——
      所以连续调用 `读状态()` 可能拿到同一帧（真实链路就是这样）。

═══ 物理模型 ═══════════════════════════════════════════════════════════════
    默认是一个**每关节独立的二阶系统**（惯量 + 阻尼 + 位置 PD），
    足够验证延迟对稳定性的影响，又完全不依赖 mujoco —— 这一层不该被仿真器绑架。
    需要更高保真时，构造时传 `物理=`（任何有 `步进(位置, 速度, 力矩, dt)` 的对象）。
"""
from __future__ import annotations

import random
import time
from typing import Any

import numpy as np

from .契约 import (
    控制模式, 写结果, 状态帧, 命令帧, 健康报告, 设备能力, 错误码,
)


class 简单物理:
    """每关节独立的二阶系统：`m·q̈ = τ - b·q̇ - k·(q - q_ref)`。

    ★ 为什么用这么简单的东西：这一层要验证的是**链路与安全**，不是动力学保真度。
      把 MuJoCo 拖进设备层会让"设备抽象"变成"MuJoCo 的包装"，那是倒退。
    """

    def __init__(self, 自由度: int, 惯量: float = 0.05, 阻尼: float = 0.6,
                 刚度: float = 8.0):
        self.n = int(自由度)
        self.q = np.zeros(self.n)
        self.qd = np.zeros(self.n)
        self.τ = np.zeros(self.n)
        self.参考 = np.zeros(self.n)
        self.m, self.b, self.k = 惯量, 阻尼, 刚度

    def 设参考(self, 位置: np.ndarray | None) -> None:
        if 位置 is not None and np.size(位置) == self.n:
            self.参考 = np.asarray(位置, dtype=float).copy()

    def 步进(self, dt: float, 力矩: np.ndarray | None = None) -> None:
        dt = max(1e-6, min(float(dt), 0.05))
        外 = np.zeros(self.n) if 力矩 is None else np.asarray(力矩, dtype=float)
        # 半隐式欧拉：先加速度、再速度、再位置（比显式稳，够用）
        加速度 = (外 - self.b * self.qd - self.k * (self.q - self.参考)) / self.m
        self.qd = self.qd + 加速度 * dt
        self.q = self.q + self.qd * dt


class 模拟后端:
    """满足 `设备后端` 协议的仿真后端。"""

    名称 = "模拟后端"
    版本 = "1.0"

    def __init__(self, 自由度: int = 6, *,
                 延迟毫秒: float = 0.0, 抖动毫秒: float = 0.0,
                 丢包率: float = 0.0, 编码器分辨率: float = 0.0,
                 出帧周期毫秒: float = 2.0, 随机种子: int = 20261020,
                 物理: Any = None):
        self.自由度 = int(自由度)
        self.能力 = 设备能力(
            可读位置=True, 可读速度=True, 可读力矩=False, 可读温度=False,
            支持位置模式=True, 支持速度模式=False, 支持力矩模式=True,
            编码器分辨率=float(编码器分辨率),
            最大命令频率=500.0,
        )
        # 劣化参数（公开可变：界面上的滑块直接改它们，便于现场演示）
        self.延迟毫秒 = float(延迟毫秒)
        self.抖动毫秒 = float(抖动毫秒)
        self.丢包率 = float(丢包率)
        self.出帧周期毫秒 = float(出帧周期毫秒)
        self._随机 = random.Random(int(随机种子))

        self._物理 = 物理 if 物理 is not None else 简单物理(self.自由度)
        self._已连接 = False
        self._模式 = 控制模式.空闲
        self._序号 = 0
        self._命令序号 = 0
        self._最后出帧 = 0.0
        self._待发: list[tuple[float, 状态帧]] = []     # (可见时刻, 帧)
        self._最新: 状态帧 | None = None
        self._丢包 = 0
        self._错序 = 0
        self._延迟们: list[float] = []
        self._错误 = 错误码.正常

    # ---- 生命周期 ----
    def 打开(self, 配置: dict | None = None) -> None:
        配置 = 配置 or {}
        # 允许从外部覆盖劣化参数（部署界面用）
        for 键, 属性 in (("延迟毫秒", "延迟毫秒"), ("抖动毫秒", "抖动毫秒"),
                         ("丢包率", "丢包率"), ("编码器分辨率", "编码器分辨率")):
            if 键 in 配置:
                if 键 == "编码器分辨率":
                    self.能力 = 设备能力(**{**self.能力.__dict__, 键: float(配置[键])})
                else:
                    setattr(self, 属性, float(配置[键]))
        self._已连接 = True
        self._模式 = 控制模式.空闲
        self._序号 = 0
        self._丢包 = 0
        self._错序 = 0
        self._延迟们.clear()
        self._待发.clear()
        self._最新 = None
        self._最后出帧 = 0.0

    def 关闭(self) -> None:
        self._已连接 = False
        self._模式 = 控制模式.急停

    # ---- 模式 ----
    def 设模式(self, 模式: 控制模式) -> 写结果:
        if not self._已连接:
            return 写结果(成功=False, 错误码=错误码.未连接, 说明="还没打开")
        if not self.能力.支持(模式):
            self._错误 = 错误码.能力不支持
            return 写结果(成功=False, 错误码=错误码.能力不支持,
                          说明=f"这个后端不支持「{模式.value}」")
        self._模式 = 模式
        return 写结果()

    # ---- 写 ----
    def 写命令(self, 命令: 命令帧) -> 写结果:
        if not self._已连接:
            return 写结果(成功=False, 错误码=错误码.未连接)
        if self._模式 == 控制模式.急停:
            return 写结果(成功=False, 错误码=错误码.未使能, 说明="急停中，拒绝所有命令")
        self._命令序号 = int(命令.序号)
        期望 = 命令.期望位置
        if 期望 and self._模式 == 控制模式.位置:
            self._物理.设参考(np.asarray(期望, dtype=float))
        力矩 = 命令.期望力矩
        self._物理.τ = (np.zeros(self.自由度) if not 力矩
                        else np.asarray(力矩, dtype=float))
        return 写结果()

    # ---- 读（非阻塞，可能返回同一帧或 None）----
    def 读状态(self) -> 状态帧 | None:
        if not self._已连接:
            return None
        现在 = time.perf_counter()
        # 出帧：硬件按固定周期产生状态，不是每次调用都出新帧（单步保持）
        if (现在 - self._最后出帧) * 1000.0 >= self.出帧周期毫秒:
            self._最后出帧 = 现在
            self._物理.步进(self.出帧周期毫秒 / 1000.0, self._物理.τ)
            self._产生一帧(现在)
        # 把到期的帧放出来（延迟在这里体现，而不是 sleep）
        while self._待发 and self._待发[0][0] <= 现在:
            _, 帧 = self._待发.pop(0)
            帧 = 状态帧(**{**帧.__dict__, "接收时刻": 现在})
            延迟 = 帧.延迟毫秒()
            if np.isfinite(延迟):
                self._延迟们.append(延迟)
                del self._延迟们[:-200]
            if self._最新 is not None and 帧.序号 < self._最新.序号:
                self._错序 += 1
            self._最新 = 帧
        return self._最新

    def _产生一帧(self, 现在: float) -> None:
        self._序号 += 1
        if self._随机.random() < self.丢包率:
            self._丢包 += 1
            return                  # 丢包：序号会跳，调用方能看到
        位置 = np.array(self._物理.q, dtype=float)
        if self.能力.编码器分辨率 > 0:
            位置 = np.round(位置 / self.能力.编码器分辨率) * self.能力.编码器分辨率
        帧 = 状态帧(
            序号=self._序号,
            位置=tuple(float(x) for x in 位置),
            速度=tuple(float(x) for x in self._物理.qd),
            力矩=(),                       # 能力表里说读不到力矩 → 就是空，不是 0
            温度=(),                       # 没有传感器 → 空
            采集时刻=现在,
            接收时刻=0.0,
            模式=self._模式,
        )
        延迟 = self.延迟毫秒 + (self._随机.uniform(0.0, self.抖动毫秒) if self.抖动毫秒 else 0.0)
        self._待发.append((现在 + 延迟 / 1000.0, 帧))

    # ---- 健康 ----
    def 健康(self) -> 健康报告:
        延迟 = self._延迟们
        return 健康报告(
            已连接=self._已连接,
            模式=self._模式,
            丢包数=self._丢包,
            错序数=self._错序,
            平均延迟毫秒=float(np.mean(延迟)) if 延迟 else float("nan"),
            最大延迟毫秒=float(np.max(延迟)) if 延迟 else float("nan"),
            错误码=self._错误,
            说明="模拟后端（劣化注入见 延迟/抖动/丢包/量化）",
        )
