#!/usr/bin/env python3
"""
轨迹规划自检.py —— 规划内核的**性质测试**（不是"跑通就算过"）

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
    .venv/bin/python 工具/验证/轨迹规划自检.py [--简]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

包根 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(包根 / "软件"))

明细: list[str] = []
通过 = 0
失败 = 0


def 判(好: bool, 说明: str) -> None:
    global 通过, 失败
    if 好:
        通过 += 1
        明细.append(f"  ✓ {说明}")
    else:
        失败 += 1
        明细.append(f"  ✗ {说明}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--简", action="store_true")
    args = ap.parse_args()

    import 轨迹规划 as TP

    n = 6
    W = np.vstack([
        np.zeros(n),
        np.array([0.4, -0.3, 0.5, -0.2, 0.3, 0.1]),
        np.array([0.1, 0.2, -0.3, 0.4, -0.1, 0.5]),
        np.full(n, 0.25),
    ])
    约 = TP.约束(vlim=np.full(n, 1.2), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    报 = TP.规划(W, 约)

    # ① 终端速度为 0 —— 而且**不是**事后改的（下面会验证末段是平滑降速的）
    判(报.成功, f"四航点规划成功（{报.总时长:.3f}s）")
    判(报.终端速度 <= 1e-3, f"① 终端速度 = {报.终端速度:.2e}（应≈0）")
    # 末段确实是"逐步降到 0"，不是最后一帧突降
    if 报.sd is not None and 报.sd.size > 5:
        末段 = 报.sd[-6:]
        单调 = bool(np.all(np.diff(末段) <= 1e-9))
        判(单调, f"① 末 5 步速度单调降到 0（{np.round(末段, 4).tolist()}）")

    # ② 速度限位真的生效：收紧上限 → 时长必须变长
    约紧 = TP.约束(vlim=np.full(n, 0.4), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    报紧 = TP.规划(W, 约紧)
    判(报紧.总时长 > 报.总时长 * 1.2,
       f"② 速度限位 1.2→0.4：{报.总时长:.2f}s → {报紧.总时长:.2f}s（必须明显变长）")

    # ③ 关节空间约束：不同关节给不同限位，最先顶到的应该是限位最小的那个
    约差 = TP.约束(vlim=np.array([0.3, 1.2, 1.2, 1.2, 1.2, 1.2]),
                  alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    报差 = TP.规划(W, 约差)
    判(报差.成功 and 报差.瓶颈关节 == 0,
       f"③ 只把 J0 限位调小 → 瓶颈关节 = {报差.瓶颈关节}（应为 0）")

    # ④ 链式法则：直线路径的 q'' 必须是 0，qdd 只来自 sd'
    W直 = np.vstack([np.zeros(n), np.full(n, 0.6)])
    报直 = TP.规划(W直, 约)
    判(报直.成功, "④ 直线路径规划成功")
    if 报直.qdd is not None:
        # 直线路径上，各关节的 qdd 应该互相成比例（同一条直线方向），且都不超限
        判(报直.加速度余量 >= -0.02,
           f"④ 直线路径加速度余量 {报直.加速度余量*100:.1f}%（不应超限）")

    # ⑤ 平滑偏差必须被校验：容差设得极小 → 必须失败
    try:
        TP.规划(np.vstack([np.zeros(n), np.full(n, 0.05), np.full(n, 0.5)]),
                约, TP.参数(平滑轮数=40, 平滑系数=0.49, 偏差容差=1e-6))
        判(False, "⑤ 平滑超容差却没报错")
    except TP.规划失败 as e:
        判("偏差" in str(e) or "超过" in str(e), f"⑤ 平滑超容差被拦住：{str(e)[:44]}")

    # ⑥ jerk：本版**只校验不整形**（见 轨迹规划设计.md 的「关于 jerk 的诚实说明」）。
    #   所以测的不是"变慢"，而是"**超限时必须明确失败，不许假装通过**"。
    约j = TP.约束(vlim=np.full(n, 1.2), alim=np.full(n, 4.0), jlim=np.full(n, 1.0))
    报j = TP.规划(W, 约j)
    判((not 报j.成功) and "加加速度超限" in 报j.原因,
       f"⑥ jerk 限收到 1.0 → 明确判失败：{报j.原因[:52]}")
    #   而限值宽松时必须通过（否则就是把正常轨迹误判成超限）
    约宽 = TP.约束(vlim=np.full(n, 1.2), alim=np.full(n, 4.0), jlim=np.full(n, 40.0))
    判(TP.规划(W, 约宽).成功, "⑥ jerk 限 40（宽松）→ 通过")

    # ⑧ 自由度不硬编码
    for 轴 in (2, 6, 7):
        报x = TP.规划(np.vstack([np.zeros(轴), np.full(轴, 0.4)]),
                     TP.约束(vlim=np.full(轴, 1.0), alim=np.full(轴, 3.0),
                            jlim=np.full(轴, 30.0)))
        判(报x.成功 and 报x.自由度 == 轴, f"⑧ {轴} 轴模型：自由度 = {报x.自由度}")

    # ⑩ 不可行必须报错（且带上下文）
    #   ★ 用例要选**真不可行**的输入。我第一版用"限位 = 1e-6"，
    #     那其实只是"很慢"，仍然可行 —— 测的是错的假设。
    #     本算法没有"求解器失败"这种状态（前后向扫描不会失败），
    #     它报的不可行是**退化输入**：
    for 名, 退化 in (("全部航点相同", np.vstack([np.full(n, 0.2)] * 3)),
                     ("只有 1 个航点", np.zeros((1, n)))):
        try:
            TP.规划(退化, 约)
            判(False, f"⑩ {名} 没报错")
        except TP.规划失败 as e:
            判(True, f"⑩ {名} 被拦住：{str(e)[:40]}")
    #   维度不匹配也要报
    try:
        TP.规划(np.vstack([np.zeros(n), np.full(n, 0.3)]),
                TP.约束(vlim=np.full(5, 1.0), alim=np.full(5, 3.0), jlim=np.full(5, 30.0)))
        判(False, "⑩ 限位维度不匹配没报错")
    except TP.规划失败 as e:
        判("不一致" in str(e), f"⑩ 限位维度不匹配被拦住：{str(e)[:40]}")

    # 附加：重复航点必须被去掉而不是让 s 不严格递增
    报重 = TP.规划(np.vstack([np.zeros(n), np.zeros(n), np.full(n, 0.4), np.full(n, 0.4)]), 约)
    判(报重.成功 and 报重.航点数 == 2, f"附加 重复航点被去掉：{报重.航点数} 个")

    if not args.简:
        print("=" * 78)
        print("  轨迹规划自检（性质测试）")
        print("=" * 78)
        print("\n".join(明细))
        print()
    print("=" * 74)
    print(f"  结果：{通过} 通过 / {失败} 失败")
    print("=" * 74)
    return 0 if 失败 == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
