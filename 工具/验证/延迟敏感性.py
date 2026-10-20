#!/usr/bin/env python3
"""
延迟敏感性.py —— L2 要回答的那个问题：**延迟到多少会出问题**

这不是"通过/失败"的测试，是一张**测量表**：同一组增益下，延迟从 0 增到 60 ms，
超调怎么变、稳态误差怎么变、什么时候发散。

为什么值得单独一个工具：
    真机上"这个参数对延迟敏不敏感"是试出来的，而试出来的代价是撞机。
    在这里试的代价是跑 3 秒仿真。

⚠️ 诚实边界（写在输出里，不藏着）：
    本层的闭环是"位置指令 + 后端伺服"，安全层还有单周期增量限幅。
    这种结构对延迟是**退化**而不是**崩溃** —— 超调变大但不会发散。
    要复现真机那种"高增益 + 纯力矩 + 大延迟 → 振荡发散"，
    需要一个**力矩级**的控制器（本层没实现）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

包根 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(包根 / "软件"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--简", action="store_true")
    args = ap.parse_args()

    from 设备.跟踪回路 import 阶跃响应

    print("=" * 78)
    print("  延迟敏感性：位置阶跃 0 → 1，看超调与稳态误差怎么随延迟变化")
    print("=" * 78)
    for 增益 in ((60.0, 8.0, "温和 kp=60  kd=8"),
                 (400.0, 6.0, "激进 kp=400 kd=6")):
        kp, kd, 名 = 增益
        print(f"\n  {名}")
        print("    延迟(ms)   峰值     超调%     稳态误差    实测延迟   发散")
        行们 = []
        for d in (0, 5, 10, 20, 40, 60):
            r = 阶跃响应(d, kp=kp, kd=kd, 时长秒=2.5)
            if not r.get("可达"):
                print(f"    {d:>7}   预热超时（延迟大于预热窗口）")
                continue
            行们.append(r)
            print(f"    {d:>7}   {r['峰值']:6.3f}  {r['超调%']:7.1f}%  "
                  f"{r['稳态误差']:9.5f}  {r['平均延迟毫秒']:7.1f}ms   "
                  f"{'是' if r['发散'] else '否'}")
        if len(行们) >= 2:
            差 = 行们[-1]["超调%"] - 行们[0]["超调%"]
            print(f"    → 延迟 0→60 ms，超调增加 {差:+.1f} 个百分点；"
                  f"{'出现过发散' if any(x['发散'] for x in 行们) else '未发散'}")

    print("\n  ⚠️ 本层闭环是「位置指令 + 后端伺服 + 单周期增量限幅」，")
    print("     这种结构对延迟是**退化**（超调变大）而不是**崩溃**（发散）。")
    print("     要复现真机那种「高增益 + 纯力矩 + 大延迟 → 振荡」，需要一个力矩级控制器。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
