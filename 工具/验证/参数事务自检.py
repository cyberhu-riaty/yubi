#!/usr/bin/env python3
"""
参数事务自检.py —— "全成功，或一个都不动"这条语义的**性质测试**

为什么单列一套：事务这种东西，"跑通了"和"语义对"完全是两回事。
一次成功提交什么都证明不了 —— 真正要证明的是**失败时没有留下半套改动**。

测的性质：
  ① 全部合法 → 全部生效，差异表正确
  ② 有越界 → **一个都不生效**（预检拦截）
  ③ 有未知插件/未知参数 → 同样一个都不生效
  ④ 失败后原值必须与提交前**逐项相等**
  ⑤ 提交才存盘；回滚不存盘（不能把半套写进项目文件）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

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

    import 参数桥
    import 插件系统 as 框架
    import 装配器

    插件, _ = 装配器.按项目装配({"算法": [{"插件": "关节pd控制"}], "参数": {}}, "事务自检")
    reg = 框架.安全注册表(插件)
    发出: list = []
    存盘: list = []
    ap_ = 参数桥.参数应用器(参数存盘=lambda 名, 表: 存盘.append((名, 表))).重绑(reg).绑定发布(发出.append)
    实例 = list(ap_._插件名到实例.values())[0]                       # noqa: SLF001
    全名 = f"{实例.名称}·KP"
    KD名 = f"{实例.名称}·KD"

    def 提交(项: dict) -> object:
        发出.clear()
        存盘.clear()
        ap_.收批量(参数桥.批量参数命令(
            动作="应用", 参数=tuple({"全名": k, "值": v} for k, v in 项.items())))
        return 发出[-1] if 发出 else None

    # ① 全部合法
    原KP, 原KD = float(实例.KP), float(实例.KD)
    r = 提交({全名: 原KP + 50.0, KD名: 原KD + 5.0})
    判(r is not None and r.状态 == "✓ 已提交", f"① 合法提交 → {getattr(r, '状态', '无')}")
    判(abs(float(实例.KP) - (原KP + 50.0)) < 1e-9 and abs(float(实例.KD) - (原KD + 5.0)) < 1e-9,
       f"① 两个参数都真的生效（KP={实例.KP}、KD={实例.KD}）")
    判(len(getattr(r, "差异", ())) == 2, f"① 差异表 {len(getattr(r, '差异', ()))} 条（应为 2）")
    判(len(存盘) == 1, "① 提交时写了存盘（1 次）")

    # ② 越界 → 一个都不生效
    before = (float(实例.KP), float(实例.KD))
    r = 提交({全名: before[0] + 100.0, KD名: 99999.0})
    判(r is not None and r.状态 == "✗ 已回滚", f"② 越界提交 → {getattr(r, '状态', '无')}")
    判((float(实例.KP), float(实例.KD)) == before,
       f"② 失败后原值逐项相等（{实例.KP}、{实例.KD}）")
    判(len(存盘) == 0, "② 回滚时**没有**存盘（不能把半套写进项目文件）")

    # ③ 未知插件
    r = 提交({"不存在的插件·KP": 1.0})
    判(r is not None and r.状态 == "✗ 已回滚", "③ 未知插件 → 回滚")
    判(len(getattr(r, "失败", ())) >= 1, "③ 给出了失败原因")

    # ④ 未知参数
    r = 提交({f"{实例.名称}·没有这个参数": 1.0})
    判(r is not None and r.状态 == "✗ 已回滚", "④ 未知参数 → 回滚")

    # ⑤ 空改动
    r = 提交({})
    判(r is not None and r.状态 == "✗ 已回滚", "⑤ 空改动 → 明确回执，不静默")

    if not args.简:
        print("=" * 78)
        print("  参数事务自检（全成功 或 一个都不动）")
        print("=" * 78)
        print("\n".join(明细))
        print()
    print("=" * 74)
    print(f"  结果：{通过} 通过 / {失败} 失败")
    print("=" * 74)
    return 0 if 失败 == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
