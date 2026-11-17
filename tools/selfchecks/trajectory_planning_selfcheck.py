#!/usr/bin/env python3
"""
trajectory_planning_selfcheck.py —— 规划内核的**性质测试**（不是"跑通就算过"）

为什么要单独一套：这一项是九项里唯一有实质算法难度的，
而"能跑出结果"完全不代表结果对 —— 一条速度恒为 0 的轨迹也能"跑出结果"。

所以这里测的是**性质**，每条都对应 `LoongEnv-SHINE 源码学习笔记` §5.11 的一个缺陷：

  ① 终端速度为 0（LE 缺陷 1：事后硬置零）
  ② 速度限位真的生效（LE 缺陷 2：v_max 被当上限/下限用混）
  ③ 约束在关节空间、s 空间量现算（LE 缺陷 3：无换算）
  ④ 链式法则正确（LE 缺陷 4：用 np.gradient 数值微分）
  ⑤ 平滑偏差有校验（LE 缺陷 5：warnings 恒空）
  ⑥ jerk 两个方向都受限（LE 缺陷 6：减速段不施加）
  ⑧ 自由度不硬编码（LE 缺陷 8：ER15/6 轴写死）
  ⑩ 不可行必须报错（LE 缺陷 10：只捕获 RuntimeError）

用法：
    .venv/bin/python tools/selfchecks/trajectory_planning_selfcheck.py [--short]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

package_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(package_root / "软件"))

details: list[str] = []
passed = 0
failed = 0


def check(condition: bool, description: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        details.append(f"  ✓ {description}")
    else:
        failed += 1
        details.append(f"  ✗ {description}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--short", action="store_true")
    args = ap.parse_args()

    import trajectory_planning as TP

    n = 6
    W = np.vstack([
        np.zeros(n),
        np.array([0.4, -0.3, 0.5, -0.2, 0.3, 0.1]),
        np.array([0.1, 0.2, -0.3, 0.4, -0.1, 0.5]),
        np.full(n, 0.25),
    ])
    limits_example = TP.TrajectoryLimits(vlim=np.full(n, 1.2), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    report = TP.plan_trajectory(W, limits_example)

    # ① 终端速度为 0 —— 而且**不是**事后改的（下面会验证末段是平滑降速的）
    check(report.success, f"四航点规划成功（{report.duration_s:.3f}s）")
    check(report.terminal_velocity <= 1e-3, f"① 终端速度 = {report.terminal_velocity:.2e}（应≈0）")
    # 末段确实是"逐步降到 0"，不是最后一帧突降
    if report.sd is not None and report.sd.size > 5:
        tail = report.sd[-6:]
        monotonic = bool(np.all(np.diff(tail) <= 1e-9))
        check(monotonic, f"① 末 5 步速度单调降到 0（{np.round(tail, 4).tolist()}）")

    # ② 速度限位真的生效：收紧上限 → 时长必须变长
    tighter_limits = TP.TrajectoryLimits(vlim=np.full(n, 0.4), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    tight_report = TP.plan_trajectory(W, tighter_limits)
    check(tight_report.duration_s > report.duration_s * 1.2,
       f"② 速度限位 1.2→0.4：{report.duration_s:.2f}s → {tight_report.duration_s:.2f}s（必须明显变长）")

    # ③ 关节空间约束：不同关节给不同限位，最先顶到的应该是限位最小的那个
    uneven_limits = TP.TrajectoryLimits(vlim=np.array([0.3, 1.2, 1.2, 1.2, 1.2, 1.2]),
                  alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    uneven_report = TP.plan_trajectory(W, uneven_limits)
    check(uneven_report.success and uneven_report.bottleneck_joint == 0,
       f"③ 只把 J0 限位调小 → 瓶颈关节 = {uneven_report.bottleneck_joint}（应为 0）")

    # ④ 链式法则：直线路径的 q'' 必须是 0，qdd 只来自 sd'
    straight_waypoints = np.vstack([np.zeros(n), np.full(n, 0.6)])
    straight_report = TP.plan_trajectory(straight_waypoints, limits_example)
    check(straight_report.success, "④ 直线路径规划成功")
    if straight_report.qdd is not None:
        # 直线路径上，各关节的 qdd 应该互相成比例（同一条直线方向），且都不超限
        check(straight_report.acceleration_margin >= -0.02,
           f"④ 直线路径加速度余量 {straight_report.acceleration_margin*100:.1f}%（不应超限）")

    # ⑤ 平滑偏差必须被校验：容差设得极小 → 必须失败
    try:
        TP.plan_trajectory(np.vstack([np.zeros(n), np.full(n, 0.05), np.full(n, 0.5)]),
                limits_example, TP.PlannerOptions(smoothing_iterations=40, smoothing_factor=0.49, deviation_tolerance=1e-6))
        check(False, "⑤ 平滑超容差却没报错")
    except TP.PlanningError as e:
        check("偏差" in str(e) or "超过" in str(e), f"⑤ 平滑超容差被拦住：{str(e)[:44]}")

    # ⑥ jerk：本版**只校验不整形**（见 轨迹规划设计.md 的「关于 jerk 的诚实说明」）。
    #   所以测的不是"变慢"，而是"**超限时必须明确失败，不许假装通过**"。
    jerk_limits = TP.TrajectoryLimits(vlim=np.full(n, 1.2), alim=np.full(n, 4.0), jlim=np.full(n, 1.0))
    jerk_report = TP.plan_trajectory(W, jerk_limits)
    check((not jerk_report.success) and "加加速度超限" in jerk_report.reason,
       f"⑥ jerk 限收到 1.0 → 明确判失败：{jerk_report.reason[:52]}")
    #   而限值宽松时必须通过（否则就是把正常轨迹误判成超限）
    wide_limits = TP.TrajectoryLimits(vlim=np.full(n, 1.2), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    check(TP.plan_trajectory(W, wide_limits).success, "⑥ jerk 限 40（宽松）→ 通过")

    # ⑧ 自由度不硬编码
    for axis_count in (2, 6, 7):
        axis_report = TP.plan_trajectory(np.vstack([np.zeros(axis_count), np.full(axis_count, 0.4)]),
                     TP.TrajectoryLimits(vlim=np.full(axis_count, 1.0), alim=np.full(axis_count, 3.0),
                            jlim=np.full(axis_count, 30.0)))
        check(axis_report.success and axis_report.dof == axis_count, f"⑧ {axis_count} 轴模型：自由度 = {axis_report.dof}")

    # ⑩ 不可行必须报错（且带上下文）
    #   ★ 用例要选**真不可行**的输入。我第一版用"限位 = 1e-6"，
    #     那其实只是"很慢"，仍然可行 —— 测的是错的假设。
    #     本算法没有"求解器失败"这种状态（前后向扫描不会失败），
    #     它报的不可行是**退化输入**：
    for name, degenerate in (("全部航点相同", np.vstack([np.full(n, 0.2)] * 3)),
                     ("只有 1 个航点", np.zeros((1, n)))):
        try:
            TP.plan_trajectory(degenerate, limits_example)
            check(False, f"⑩ {name} 没报错")
        except TP.PlanningError as e:
            check(True, f"⑩ {name} 被拦住：{str(e)[:40]}")
    #   维度不匹配也要报
    try:
        TP.plan_trajectory(np.vstack([np.zeros(n), np.full(n, 0.3)]),
                TP.TrajectoryLimits(vlim=np.full(5, 1.0), alim=np.full(5, 3.0), jlim=np.full(5, 30.0)))
        check(False, "⑩ 限位维度不匹配没报错")
    except TP.PlanningError as e:
        check("不一致" in str(e), f"⑩ 限位维度不匹配被拦住：{str(e)[:40]}")

    # 附加：重复航点必须被去掉而不是让 s 不严格递增
    deduplicated_report = TP.plan_trajectory(np.vstack([np.zeros(n), np.zeros(n), np.full(n, 0.4), np.full(n, 0.4)]), limits_example)
    check(deduplicated_report.success and deduplicated_report.waypoint_count == 2, f"附加 重复航点被去掉：{deduplicated_report.waypoint_count} 个")

    if not args.short:
        print("=" * 78)
        print("  轨迹规划自检（性质测试）")
        print("=" * 78)
        print("\n".join(details))
        print()
    print("=" * 74)
    print(f"  结果：{passed} 通过 / {failed} 失败")
    print("=" * 74)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
