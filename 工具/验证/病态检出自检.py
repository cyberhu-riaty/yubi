#!/usr/bin/env python3
"""
病态检出自检.py —— 观测核心的**性质测试**（含反例）

这一套的重点不是"能报出来"，而是**不该报的时候绝不报**。
告警系统有一个不对称的性质：
    漏报 → 你还得自己看曲线，回到原状，没有额外损失
    误报 → 人会开始无视所有告警，整套东西的价值变成**负数**
所以每一类判定都要同时验：正例能报、反例不报、数据不够时不下结论。

测的性质：
  ① 振荡：同频正弦 → 报；衰减的正弦 → 不报（那是正常调节过程）
  ② 发散：包络单调放大 → 报；稳定平台 → 不报
  ③ 跟踪超差：持续大均值 → 报；超限但只闪了一下 → 不报
  ④ 饱和：长期顶着上限 → 报；偶发一次 → 不报
  ⑤ 数据不够：只有 5 个点 → 任何判定器都不下结论
  ⑥ NaN/Inf 不进缓冲（否则均值/极值全废）
  ⑦ 没标定的信号（如 RTF）不判定
  ⑧ 告警会自动过期（恢复后不留着吓人）
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

package_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(package_root / "软件"))

明细: list[str] = []
通过 = 0
失败 = 0


def 判(好: bool, description: str) -> None:
    global 通过, 失败
    if 好:
        通过 += 1
        明细.append(f'  ✓ {description}')
    else:
        失败 += 1
        明细.append(f'  ✗ {description}')


def 造序列(detector, 时长=4.0, frequency=20.0):
    n = int(时长 * frequency)
    ts = [i / frequency for i in range(n)]
    return ts, [detector(t) for t in ts]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--简", action="store_true")
    args = ap.parse_args()

    import observation_core as O

    最大误差信号 = "关节 PD 位置控制·最大误差(deg)"
    有符号误差信号 = "关节 PD 位置控制·关节2有符号误差(deg)"
    最大误差阈 = O.get_threshold(最大误差信号)
    threshold = O.get_threshold(有符号误差信号)
    判(threshold is not None and 最大误差阈 is not None, "① 两类误差信号都有明确阈值")
    判(最大误差阈.detectors == ("跟踪超差",),
       "① 最大绝对误差只做跟踪超差，不猜振荡/发散")
    判(O.get_threshold("关节 PD 位置控制·力矩峰值(Nm)") is None,
       "① 聚合力矩峰值不再被误判成振荡/发散")

    # ① 振荡
    ts, vs = 造序列(lambda t: 10.0 + 6.0 * math.sin(2 * math.pi * 5.0 * t))
    result = O.detect_oscillation(ts, vs, threshold)
    判(result is not None and 4.0 <= result["频率"] <= 6.0,
       f"① 5 Hz 等幅振荡被检出（{(result['证据'] if result else '没报')}）")

    ts, vs = 造序列(lambda t: 10.0 + 6.0 * math.exp(-2.0 * t) * math.sin(2 * math.pi * 5.0 * t))
    判(O.detect_oscillation(ts, vs, threshold) is None, "① 衰减的振荡**不报**（那是正常调节过程）")

    # ② 发散
    ts, vs = 造序列(lambda t: 1.0 * math.exp(1.6 * t), 时长=3.0)
    判(O.detect_divergence(ts, vs, threshold) is not None, "② 指数放大被检出为发散")
    ts, vs = 造序列(lambda t: 5.0 + 0.2 * math.sin(2 * math.pi * 3.0 * t))
    判(O.detect_divergence(ts, vs, threshold) is None, "② 稳定平台**不报**发散")

    # ③ 跟踪超差
    ts, vs = 造序列(lambda t: 12.0 + 0.3 * math.sin(2 * math.pi * 2.0 * t))
    判(O.detect_tracking_error(ts, vs, 最大误差阈) is not None, "③ 持续大误差被检出为超差")
    ts, vs = 造序列(lambda t: 12.0 if 0.4 < t < 0.5 else 0.5, 时长=4.0)
    判(O.detect_tracking_error(ts, vs, 最大误差阈) is None, "③ 只闪了一下的超限**不报**")

    # ④ 饱和
    饱阈 = O.get_threshold("关节 PD 位置控制·饱和关节数")
    ts, vs = 造序列(lambda t: 2.0 if t > 0.5 else 0.0)
    判(O.detect_saturation(ts, vs, 饱阈) is not None, "④ 长期 2 个关节饱和被检出")
    ts, vs = 造序列(lambda t: 2.0 if 0.4 < t < 0.45 else 0.0)
    判(O.detect_saturation(ts, vs, 饱阈) is None, "④ 偶发一次饱和**不报**")

    # ④b **反例（这条是测试逼出来的真 bug）**：
    #     「饱和」判定不能落到「误差」信号上 —— 误差天然 ≥1，
    #     第一版就因此报出"100% 的采样里至少 1 个关节饱和（最多 16 个）"。
    ts, vs = 造序列(lambda t: 10.0)
    判(O.detect_saturation(ts, vs, threshold) is not None, "④b 单测函数本身会报（说明这条测试有效）")
    发0 = []
    核0 = O.ObservationCore(发0.append)
    for i in range(120):
        核0.record(i / 20.0, {最大误差信号: 10.0})
    核0.evaluate(6.0, wall_clock=0.0)
    判(all(a.kind != "饱和" for a in 核0.active_alerts()),
       f'④b 端到端：误差信号**不会**被判成饱和（当前 {[a.kind for a in 核0.active_alerts()]}）')

    # ⑤ 数据不够
    少ts = [i / 20 for i in range(5)]
    少vs = [10.0, -10.0, 10.0, -10.0, 10.0]
    判(all(f(少ts, 少vs, threshold) is None for _, f, _, _ in O.DETECTORS),
       "⑤ 只有 5 个点时任何判定器都**不下结论**")

    # ⑥ NaN/Inf 不进缓冲
    缓 = O.SignalBuffer(retention_seconds=10)
    缓.record(0.0, 1.0); 缓.record(0.1, float("nan")); 缓.record(0.2, float("inf")); 缓.record(0.3, 2.0)
    _, 值 = 缓.get_values()
    判(值 == [1.0, 2.0], f"⑥ NaN/Inf 被挡在缓冲外（留下的值 {值}）")

    # ⑦ 没标定的信号不判定
    发 = []
    核 = O.ObservationCore(发.append)
    for i in range(120):
        核.record(i / 20.0, {"RTF": 1.0 + 0.9 * math.sin(i / 3.0)})
    核.evaluate(6.0, wall_clock=100.0)
    判(not 核.active_alerts(), "⑦ 没标定的信号（RTF）不产生告警")

    # ⑧ 端到端：喂一段真振荡 → 有告警；再喂一段平稳 → 自动过期
    发.clear()
    核 = O.ObservationCore(发.append)
    for i in range(240):
        t = i / 20.0
        核.record(t, {有符号误差信号: 10 + 6 * math.sin(2 * math.pi * 5 * t)})
    核.evaluate(12.0, wall_clock=0.0)
    判(len(核.active_alerts()) >= 1, f'⑧ 端到端检出 {len(核.active_alerts())} 条告警')
    # 恢复：喂平稳信号，把墙钟推过留存期
    for i in range(240, 480):
        t = i / 20.0
        核.record(t, {有符号误差信号: 0.2})
    for k in range(30):
        核.evaluate(24.0 + k, wall_clock=1.0 + k * 1.0)
    判(len(核.active_alerts()) == 0, "⑧ 恢复后告警自动过期（不留着吓人）")

    # ⑨ 新实验边界：清空不仅清后端缓冲，也要立刻给界面发空列表。
    核.clear()
    判(not 核.active_alerts() and bool(发) and not getattr(发[-1], "active", ()),
       "⑨ 复位/换实验会立即清空历史告警并通知界面")

    if not args.简:
        print("=" * 78)
        print("  病态检出自检（正例 + 反例 + 边界）")
        print("=" * 78)
        print("\n".join(明细))
        print()
    print("=" * 74)
    print(f"  结果：{通过} 通过 / {失败} 失败")
    print("=" * 74)
    return 0 if 失败 == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
