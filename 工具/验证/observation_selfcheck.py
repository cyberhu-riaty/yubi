#!/usr/bin/env python3
"""
observation_selfcheck.py —— 观测核心的**性质测试**（含反例）

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

details: list[str] = []
passed = 0
failures = 0


def check(ok: bool, description: str) -> None:
    global passed, failures
    if ok:
        passed += 1
        details.append(f'  ✓ {description}')
    else:
        failures += 1
        details.append(f'  ✗ {description}')


def make_series(detector, duration=4.0, frequency=20.0):
    n = int(duration * frequency)
    ts = [i / frequency for i in range(n)]
    return ts, [detector(t) for t in ts]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", "--简", action="store_true")
    args = ap.parse_args()

    import observation_core as O

    max_error_signal = "关节 PD 位置控制·最大误差(deg)"
    signed_error_signal = "关节 PD 位置控制·关节2有符号误差(deg)"
    max_error_threshold = O.get_threshold(max_error_signal)
    threshold = O.get_threshold(signed_error_signal)
    check(threshold is not None and max_error_threshold is not None, "① 两类误差信号都有明确阈值")
    check(max_error_threshold.detectors == ("跟踪超差",),
       "① 最大绝对误差只做跟踪超差，不猜振荡/发散")
    check(O.get_threshold("关节 PD 位置控制·力矩峰值(Nm)") is None,
       "① 聚合力矩峰值不再被误判成振荡/发散")

    # ① 振荡
    ts, vs = make_series(lambda t: 10.0 + 6.0 * math.sin(2 * math.pi * 5.0 * t))
    result = O.detect_oscillation(ts, vs, threshold)
    check(result is not None and 4.0 <= result["频率"] <= 6.0,
       f"① 5 Hz 等幅振荡被检出（{(result['证据'] if result else '没报')}）")

    ts, vs = make_series(lambda t: 10.0 + 6.0 * math.exp(-2.0 * t) * math.sin(2 * math.pi * 5.0 * t))
    check(O.detect_oscillation(ts, vs, threshold) is None, "① 衰减的振荡**不报**（那是正常调节过程）")

    # ② 发散
    ts, vs = make_series(lambda t: 1.0 * math.exp(1.6 * t), duration=3.0)
    check(O.detect_divergence(ts, vs, threshold) is not None, "② 指数放大被检出为发散")
    ts, vs = make_series(lambda t: 5.0 + 0.2 * math.sin(2 * math.pi * 3.0 * t))
    check(O.detect_divergence(ts, vs, threshold) is None, "② 稳定平台**不报**发散")

    # ③ 跟踪超差
    ts, vs = make_series(lambda t: 12.0 + 0.3 * math.sin(2 * math.pi * 2.0 * t))
    check(O.detect_tracking_error(ts, vs, max_error_threshold) is not None, "③ 持续大误差被检出为超差")
    ts, vs = make_series(lambda t: 12.0 if 0.4 < t < 0.5 else 0.5, duration=4.0)
    check(O.detect_tracking_error(ts, vs, max_error_threshold) is None, "③ 只闪了一下的超限**不报**")

    # ④ 饱和
    saturation_threshold = O.get_threshold("关节 PD 位置控制·饱和关节数")
    ts, vs = make_series(lambda t: 2.0 if t > 0.5 else 0.0)
    check(O.detect_saturation(ts, vs, saturation_threshold) is not None, "④ 长期 2 个关节饱和被检出")
    ts, vs = make_series(lambda t: 2.0 if 0.4 < t < 0.45 else 0.0)
    check(O.detect_saturation(ts, vs, saturation_threshold) is None, "④ 偶发一次饱和**不报**")

    # ④b **反例（这条是测试逼出来的真 bug）**：
    #     「饱和」判定不能落到「误差」信号上 —— 误差天然 ≥1，
    #     第一版就因此报出"100% 的采样里至少 1 个关节饱和（最多 16 个）"。
    ts, vs = make_series(lambda t: 10.0)
    check(O.detect_saturation(ts, vs, threshold) is not None, "④b 单测函数本身会报（说明这条测试有效）")
    initial_messages = []
    initial_observer = O.ObservationCore(initial_messages.append)
    for i in range(120):
        initial_observer.record(i / 20.0, {max_error_signal: 10.0})
    initial_observer.evaluate(6.0, wall_clock=0.0)
    check(all(a.kind != "饱和" for a in initial_observer.active_alerts()),
       f'④b 端到端：误差信号**不会**被判成饱和（当前 {[a.kind for a in initial_observer.active_alerts()]}）')

    # ⑤ 数据不够
    short_times = [i / 20 for i in range(5)]
    short_values = [10.0, -10.0, 10.0, -10.0, 10.0]
    check(all(f(short_times, short_values, threshold) is None for _, f, _, _ in O.DETECTORS),
       "⑤ 只有 5 个点时任何判定器都**不下结论**")

    # ⑥ NaN/Inf 不进缓冲
    buffer = O.SignalBuffer(retention_seconds=10)
    buffer.record(0.0, 1.0); buffer.record(0.1, float("nan")); buffer.record(0.2, float("inf")); buffer.record(0.3, 2.0)
    _, value = buffer.get_values()
    check(value == [1.0, 2.0], f"⑥ NaN/Inf 被挡在缓冲外（留下的值 {value}）")

    # ⑦ 没标定的信号不判定
    messages = []
    observer = O.ObservationCore(messages.append)
    for i in range(120):
        observer.record(i / 20.0, {"RTF": 1.0 + 0.9 * math.sin(i / 3.0)})
    observer.evaluate(6.0, wall_clock=100.0)
    check(not observer.active_alerts(), "⑦ 没标定的信号（RTF）不产生告警")

    # ⑧ 端到端：喂一段真振荡 → 有告警；再喂一段平稳 → 自动过期
    messages.clear()
    observer = O.ObservationCore(messages.append)
    for i in range(240):
        t = i / 20.0
        observer.record(t, {signed_error_signal: 10 + 6 * math.sin(2 * math.pi * 5 * t)})
    observer.evaluate(12.0, wall_clock=0.0)
    check(len(observer.active_alerts()) >= 1, f'⑧ 端到端检出 {len(observer.active_alerts())} 条告警')
    # 恢复：喂平稳信号，把墙钟推过留存期
    for i in range(240, 480):
        t = i / 20.0
        observer.record(t, {signed_error_signal: 0.2})
    for k in range(30):
        observer.evaluate(24.0 + k, wall_clock=1.0 + k * 1.0)
    check(len(observer.active_alerts()) == 0, "⑧ 恢复后告警自动过期（不留着吓人）")

    # ⑨ 新实验边界：清空不仅清后端缓冲，也要立刻给界面发空列表。
    observer.clear()
    check(not observer.active_alerts() and bool(messages) and not getattr(messages[-1], "active", ()),
       "⑨ 复位/换实验会立即清空历史告警并通知界面")

    if not args.brief:
        print("=" * 78)
        print("  病态检出自检（正例 + 反例 + 边界）")
        print("=" * 78)
        print("\n".join(details))
        print()
    print("=" * 74)
    print(f"  结果：{passed} 通过 / {failures} 失败")
    print("=" * 74)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
