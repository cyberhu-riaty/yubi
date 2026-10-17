#!/usr/bin/env python3
"""
作用域自检.py —— 扫"函数里先引用、后局部导入"这类**只在一部分运行路径下才炸**的坑

为什么要有它：
    `软件/启动.py` 里曾经这样写：
        import Web桥 as _Web桥          # 模块顶部
        ...
        def 启动外壳(...):
            _web口 = int(... or _Web桥.默认端口)     # ← 第 268 行
            ...
            if 无窗:
                import Web桥 as _Web桥              # ← 函数内又 import 一次
    Python 的规则是：**函数体里出现过赋值（import…as 也算），这个名字在整个函数里
    就是局部变量**。于是第 268 行抛 `UnboundLocalError`。

    而这段代码**只在有窗模式（官方 ImGui 界面）执行** —— 那段时间的验证全走无窗模式，
    所以"新窗口一切正常、老的原生界面打不开"，排查方向一度被带偏（以为是 .app 授权）。

    这类 bug 的共同特征：**静态看得见、但只在某条分支上运行时才暴露**。
    所以用静态检查扫，比等它报错强。

检查内容：
  ① 函数内的 `import X as Y` / `from M import X as Y`
  ② 如果同名在**模块级**也有导入，且函数里**更早**的位置就引用了它 → 报错
  ③ 如果同名在函数里既被 import、又被赋值 → 也报（同一个坑）

用法：
    .venv/bin/python 工具/验证/作用域自检.py
    .venv/bin/python 工具/验证/作用域自检.py --全（连算法库/工具一起扫）
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

包根 = Path(__file__).resolve().parents[2]

默认目标 = [
    包根 / "软件",
]


def _模块级别名(树: ast.Module) -> set[str]:
    """模块顶层 import 引入的名字（只算顶层，不含函数里的）。"""
    名 = set()
    for 节点 in 树.body:
        if isinstance(节点, ast.Import):
            for a in 节点.names:
                名.add(a.asname or a.name.split(".")[0])
        elif isinstance(节点, ast.ImportFrom):
            for a in 节点.names:
                名.add(a.asname or a.name)
    return 名


def 查文件(路径: Path) -> list[str]:
    问题: list[str] = []
    try:
        源 = 路径.read_text(encoding="utf-8")
        树 = ast.parse(源)
    except (SyntaxError, UnicodeDecodeError) as 异常:
        return [f"{路径}: 解析失败（{type(异常).__name__}）"]
    行们 = 源.splitlines()
    模块级 = _模块级别名(树)

    for 函数 in ast.walk(树):
        if not isinstance(函数, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # 函数内所有 import 别名 → 行号
        局部导入: dict[str, int] = {}
        局部赋值: dict[str, int] = {}
        for 子 in ast.walk(函数):
            if isinstance(子, ast.Import):
                for a in 子.names:
                    局部导入.setdefault(a.asname or a.name.split(".")[0], 子.lineno)
            elif isinstance(子, ast.ImportFrom):
                for a in 子.names:
                    局部导入.setdefault(a.asname or a.name, 子.lineno)
            elif isinstance(子, ast.Name) and isinstance(子.ctx, ast.Store):
                if 子.id not in 局部赋值:
                    局部赋值[子.id] = 子.lineno

        for 名, 导入行 in 局部导入.items():
            # ① 模块级同名 + 函数里更早引用 → UnboundLocalError
            最早就用 = None
            for 子 in ast.walk(函数):
                if isinstance(子, ast.Name) and isinstance(子.ctx, ast.Load) and 子.id == 名:
                    if 最早就用 is None or 子.lineno < 最早就用:
                        最早就用 = 子.lineno
            if 名 in 模块级 and 最早就用 is not None and 最早就用 < 导入行:
                问题.append(
                    f"{路径.relative_to(包根)}:{导入行} — 函数「{函数.name}」内重新 import "
                    f"「{名}」，而第 {最早就用} 行就引用了它 → 会 UnboundLocalError\n"
                    f"      {行们[导入行 - 1].strip()[:90]}\n"
                    f"      修法：删掉函数内的 import，用模块级那份（或改用别的别名）")
            # ② 同名既 import 又赋值 → 都是局部绑定，极易混
            if 名 in 局部赋值 and 局部赋值[名] != 导入行:
                问题.append(
                    f"{路径.relative_to(包根)}:{导入行} — 函数「{函数.name}」内「{名}」"
                    f"既有 import 又有赋值（第 {局部赋值[名]} 行），容易误读")
    return 问题


def main() -> int:
    ap = argparse.ArgumentParser(description="作用域自检：函数内别名导入陷阱")
    ap.add_argument("--全", action="store_true", help="连 算法库/工具 一起扫")
    ap.add_argument("--简", action="store_true", help="只打一行结论")
    args = ap.parse_args()

    目标 = list(默认目标)
    if args.全:
        目标 += [包根 / "算法库", 包根 / "工具", 包根 / "前端" / "测试"]

    文件们: list[Path] = []
    for 目录 in 目标:
        if 目录.is_dir():
            文件们 += sorted(p for p in 目录.rglob("*.py")
                            if "__pycache__" not in p.parts and ".venv" not in p.parts
                            and "spike" not in p.parts)

    问题: list[str] = []
    for f in 文件们:
        问题 += 查文件(f)

    if not args.简:
        print("=" * 78)
        print(f"  作用域自检：扫了 {len(文件们)} 个文件")
        print("=" * 78)
    if 问题:
        for 条 in 问题:
            print(f"  ✗ {条}")
        print(f"\n  结果：{len(问题)} 处问题")
        return 1
    if not args.简:
        print("  ✓ 没有'函数内先引用、后局部导入'的别名")
        print(f"\n  结果：0 处问题（{len(文件们)} 个文件）")
    else:
        print(f"  结果：0 / {len(文件们)} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
