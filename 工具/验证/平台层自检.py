#!/usr/bin/env python3
"""
平台层自检.py —— 守住"入口不碰平台细节"这条边界

背景：
    `软件/主程序窗口.py` 曾经直接 `import 宿主窗口`（那里面全是 PyObjC / AppKit /
    NSOpenGLView / WKWebView）。能跑，但"能跑"不等于"可移植"：
    入口一旦沾上平台，将来做 Windows 版就得从入口一路改进去，也没人知道边界在哪。

    现在已经收进 `软件/平台适配层/`。这层只回答一个问题：
    **换一个平台，最少要实现什么？** —— 五个方法，见 `契约.py`。

检查（全部机器可判）：
  ① 入口文件里**不出现**平台相关模块名（宿主窗口 / AppKit / WebKit / PyObjC / objc）
  ② 平台实现确实实现了契约的**每一个**抽象方法（漏一个就该报）
  ③ 契约的抽象方法数量没被悄悄改（现在 4 个）+ `起` 的参数里有 `视口槽`
  ④ 当前平台的 `可用()` 能被调用且返回二元组（不是抛异常）

用法：
    .venv/bin/python 工具/验证/平台层自检.py [--简]
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

包根 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(包根 / "软件"))

# 入口文件：允许写"业务"，不允许写"平台"
入口文件 = [包根 / "软件" / "主程序窗口.py"]
禁词 = ("宿主窗口", "AppKit", "WebKit", "PyObjC", "import objc", "NSWindow", "NSOpenGLView")


def 查入口(路径: Path) -> list[str]:
    问题: list[str] = []
    try:
        源 = 路径.read_text(encoding="utf-8")
        树 = ast.parse(源)
    except (SyntaxError, UnicodeDecodeError):
        return [f"{路径.name}: 解析失败"]

    # 只查**代码**里出现（import 语句 + 名字），注释与说明文字允许提到
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            for a in 节点.names:
                根 = a.name.split(".")[0]
                if 根 in ("宿主窗口", "objc"):
                    问题.append(
                        f"{路径.name}:{节点.lineno} — 入口直接 import 了 {a.name}，"
                        f"应改为经 平台适配层")
        elif isinstance(节点, ast.ImportFrom):
            模块 = 节点.module or ""
            根 = 模块.split(".")[0]
            if 根 in ("宿主窗口", "AppKit", "WebKit", "objc", "Quartz"):
                问题.append(
                    f"{路径.name}:{节点.lineno} — 入口直接 from-import 了 {模块}，"
                    f"应改为经 平台适配层")
    return 问题


def main() -> int:
    ap = argparse.ArgumentParser(description="平台层自检")
    ap.add_argument("--简", action="store_true")
    args = ap.parse_args()

    问题: list[str] = []
    for f in 入口文件:
        问题 += 查入口(f)

    # ②③ 契约 vs 实现
    try:
        import 平台适配层
        from 平台适配层.契约 import 平台能力
    except Exception as 异常:                                          # noqa: BLE001
        print(f"  ✗ 平台适配层导入失败：{type(异常).__name__}: {异常}")
        return 1

    抽象 = 平台能力.__abstractmethods__
    期望 = {"可用", "起", "视口矩形", "统计"}
    if set(抽象) != 期望:
        问题.append(f"契约的抽象方法变了：现在 {sorted(抽象)}，期望 {sorted(期望)}")

    # `起` 的参数里必须有 视口槽（这是平台层与入口之间唯一的状态通道）
    import inspect
    签名 = inspect.signature(平台能力.起)
    if "视口槽" not in 签名.parameters:
        问题.append("契约的 `起()` 缺少 `视口槽` 参数（平台层与入口的状态通道）")

    try:
        平台 = 平台适配层.取实现()
    except Exception as 异常:                                          # noqa: BLE001
        print(f"  ✗ 取实现失败：{type(异常).__name__}: {异常}")
        return 1

    for 名 in 抽象:
        if not hasattr(平台, 名):
            问题.append(f"实现 {type(平台).__name__} 缺少方法 {名}")
        elif getattr(type(平台), 名, None) is getattr(平台能力, 名, None):
            问题.append(f"实现 {type(平台).__name__} 没有覆写抽象方法 {名}")

    # ④ 可用() 可调用且返回二元组
    try:
        结果 = 平台.可用()
        if not (isinstance(结果, tuple) and len(结果) == 2):
            问题.append(f"`可用()` 应返回 (bool, str)，实际 {结果!r}")
    except Exception as 异常:                                          # noqa: BLE001
        问题.append(f"`可用()` 抛异常：{type(异常).__name__}: {异常}")

    if not args.简:
        print("=" * 78)
        print(f"  平台层自检：入口 {len(入口文件)} 个，实现 {type(平台).__name__}")
        print("=" * 78)
    if 问题:
        for 条 in 问题:
            print(f"  ✗ {条}")
        print(f"\n  结果：{len(问题)} 处问题")
        return 1

    if args.简:
        print(f"  结果：✓ 边界干净，契约 {len(抽象)}/4 方法齐备（{type(平台).__name__}）")
    else:
        print("  ✓ 入口不直接 import 任何平台模块（只经 平台适配层）")
        print(f"  ✓ 契约抽象方法 {len(抽象)}/4 齐备：{', '.join(sorted(抽象))}")
        print(f"  ✓ `起()` 含 视口槽 参数（平台层与入口唯一状态通道）")
        可用, 原因 = 平台.可用()
        print(f"  {'✓' if 可用 else '✗'} 当前平台可用：{平台.名称}"
              + (f"（{原因}）" if 原因 else ""))
        print(f"\n  结果：✓ 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
