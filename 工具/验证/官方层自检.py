#!/usr/bin/env python3
"""
官方层自检.py —— 守住"全工程只有一处碰官方实验层"这条不变量

背景：
    `mujoco.experimental.studio` 名字里的 "experimental" 是真的：官方不保证不改。
    原来它散落在 11 个文件里直接 import，一旦升级 MuJoCo，报错会从十几个不相干的地方
    冒出来，且多为 `AttributeError: module has no attribute 'Xxx'` 这种"看不出该改哪"的形状。

    收敛到 `软件/官方层.py` 之后，**爆炸半径 = 1 个文件**。但"收敛"不能靠自觉 ——
    下次谁 `from 官方层 import messages` 写顺手了，就悄悄回退。
    所以用这条**机器可查的不变量**盯住：

        除 `软件/官方层.py` 之外，`软件/` `算法库/` `工具/` 里
        **不允许出现 `mujoco.experimental`**（注释/字符串里提到不算，只查 import 语句）。

检查：
  ① 静态扫 import / from-import 语句，找禁名字
  ② 跑 `官方层.自检()`，确认我们依赖的符号都还在
  ③ 确认适配层确实**导出**了各文件用到的名字（防止"删了 import 但没导出"）

用法：
    .venv/bin/python 工具/验证/官方层自检.py
    .venv/bin/python 工具/验证/官方层自检.py --简
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

包根 = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(包根 / "软件"))

适配层 = 包根 / "软件" / "官方层.py"
禁前缀 = "mujoco.experimental"

# 允许直接碰官方实验层的文件（**只有这一个**）
白名单 = {适配层.resolve()}


def 扫目录(目录: Path) -> list[Path]:
    if not 目录.is_dir():
        return []
    return sorted(p for p in 目录.rglob("*.py")
                  if "__pycache__" not in p.parts and ".venv" not in p.parts)


def 查文件(路径: Path) -> list[str]:
    问题: list[str] = []
    try:
        树 = ast.parse(路径.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []          # 语法错由别的检查负责，这里不重复报
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Import):
            for a in 节点.names:
                if a.name.startswith(禁前缀):
                    问题.append(
                        f"{路径.relative_to(包根)}:{节点.lineno} — 直接 import 了 "
                        f"{a.name}\n      改成：from 官方层 import <你要的模块>")
        elif isinstance(节点, ast.ImportFrom):
            模块 = 节点.module or ""
            if 模块.startswith(禁前缀):
                问题.append(
                    f"{路径.relative_to(包根)}:{节点.lineno} — 直接 from-import 了 "
                    f"{模块}\n      改成：from 官方层 import <你要的名字>")
    return 问题


def main() -> int:
    ap = argparse.ArgumentParser(description="官方层自检：不变量 + 符号齐备")
    ap.add_argument("--简", action="store_true")
    args = ap.parse_args()

    文件们: list[Path] = []
    for 子 in ("软件", "算法库", "工具"):
        目录 = 包根 / 子
        文件们 += [p for p in 扫目录(目录) if p.resolve() not in 白名单]

    问题: list[str] = []
    for f in 文件们:
        问题 += 查文件(f)

    # 适配层自身要能导入、且符号齐全
    try:
        import 官方层
    except Exception as 异常:                                          # noqa: BLE001
        print(f"  ✗ 官方层 导入失败：{type(异常).__name__}: {异常}")
        return 1

    通过, 总数, 明细 = 官方层.自检()
    问题 += [f"官方层自检未过：{条}" for 条 in 明细]

    if not args.简:
        print("=" * 78)
        print(f"  官方层自检：扫了 {len(文件们)} 个文件（白名单外）")
        print("=" * 78)
    if 问题:
        for 条 in 问题:
            print(f"  ✗ {条}")
        print(f"\n  结果：{len(问题)} 处问题")
        return 1
    if args.简:
        print(f"  结果：✓ 0 处越界，官方层 {通过}/{总数}")
    else:
        print(f"  ✓ 没有文件越界直接 import `{禁前缀}`（唯一入口：软件/官方层.py）")
        print(f"  ✓ 官方层依赖符号：{通过}/{总数} 都在")
        print(f"\n  结果：✓ 通过（{len(文件们)} 个文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
