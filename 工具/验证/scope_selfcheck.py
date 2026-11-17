#!/usr/bin/env python3
"""
scope_selfcheck.py —— 扫"函数里先引用、后局部导入"这类**只在一部分运行路径下才炸**的坑

为什么要有它：
    旧运行入口里曾经这样写：
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
    .venv/bin/python 工具/验证/scope_selfcheck.py
    .venv/bin/python 工具/验证/scope_selfcheck.py --全（连算法库/工具一起扫）
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

default_targets = [
    ROOT / "软件",
]


def _module_aliases(tree: ast.Module) -> set[str]:
    """模块顶层 import 引入的名字（只算顶层，不含函数里的）。"""
    name = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                name.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                name.add(a.asname or a.name)
    return name


def check_file(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [f"{path}: 解析失败（{type(exc).__name__}）"]
    lines = source.splitlines()
    module_level = _module_aliases(tree)

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # 函数内所有 import 别名 → 行号
        local_imports: dict[str, int] = {}
        local_assignments: dict[str, int] = {}
        # ★ 取**最小行号**，不能用 setdefault：
        #   `ast.walk` 是广度优先、**不按行号顺序**，同一个名字 import 两次时
        #   setdefault 可能记下后面那次 → "首次绑定"被算晚 → 报假错（实测踩过）。
        def record_binding(bindings: dict[str, int], name: str, line: int) -> None:
            bindings[name] = min(bindings.get(name, line), line)

        for child in ast.walk(function):
            if isinstance(child, ast.Import):
                for a in child.names:
                    record_binding(local_imports, a.asname or a.name.split(".")[0], child.lineno)
            elif isinstance(child, ast.ImportFrom):
                for a in child.names:
                    record_binding(local_imports, a.asname or a.name, child.lineno)
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                record_binding(local_assignments, child.id, child.lineno)

        for name, import_line in local_imports.items():
            # ① 模块级同名 + 函数里更早引用 → UnboundLocalError
            first_use = None
            for child in ast.walk(function):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id == name:
                    if first_use is None or child.lineno < first_use:
                        first_use = child.lineno
            if name in module_level and first_use is not None and first_use < import_line:
                issues.append(
                    f"{path.relative_to(ROOT)}:{import_line} — 函数「{function.name}」内重新 import "
                    f"「{name}」，而第 {first_use} 行就引用了它 → 会 UnboundLocalError\n"
                    f"      {lines[import_line - 1].strip()[:90]}\n"
                    f"      修法：删掉函数内的 import，用模块级那份（或改用别的别名）")
            # ② **精确判据**：名字在"第一次被绑定"之前就被**引用**了 → 必然 UnboundLocalError
            #
            #    ★ 原来这条写的是"既 import 又赋值就报"，太粗 ——
            #      `try: import X as Y` / `except: Y = None` 这种**兜底赋值**是正当写法，
            #      却被误报（实测：插件桥那次）。误报多了，人就会开始无视这个检查。
            #
            #    真正会炸的情况只有一种：**先用、后绑**。所以只比这两个行号。
            first_binding = min(import_line, local_assignments.get(name, import_line))
            first_reference = None
            for child in ast.walk(function):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id == name:
                    if first_reference is None or child.lineno < first_reference:
                        first_reference = child.lineno
            if first_reference is not None and first_reference < first_binding:
                issues.append(
                    f"{path.relative_to(ROOT)}:{first_reference} — 函数「{function.name}」里「{name}」"
                    f"在第 {first_reference} 行就用了，但到第 {first_binding} 行才绑定 → "
                    f"会 UnboundLocalError\n"
                    f"      {source.splitlines()[first_reference - 1].strip()[:90]}\n"
                    f"      修法：把这个名字的 import/赋值挪到**使用之前**（被嵌套函数用到的更要靠前）")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="作用域自检：函数内别名导入陷阱")
    ap.add_argument("--all-files", "--全", action="store_true", help="连 算法库/工具 一起扫")
    ap.add_argument("--brief", "--简", action="store_true", help="只打一行结论")
    args = ap.parse_args()

    targets = list(default_targets)
    if args.all_files:
        targets += [ROOT / "controllers", ROOT / "工具", ROOT / "frontend" / "tests"]

    files: list[Path] = []
    for directory in targets:
        if directory.is_dir():
            files += sorted(p for p in directory.rglob("*.py")
                            if "__pycache__" not in p.parts and ".venv" not in p.parts
                            and "spike" not in p.parts)

    issues: list[str] = []
    for f in files:
        issues += check_file(f)

    if not args.brief:
        print("=" * 78)
        print(f"  作用域自检：扫了 {len(files)} 个文件")
        print("=" * 78)
    if issues:
        for issue in issues:
            print(f"  ✗ {issue}")
        print(f"\n  结果：{len(issues)} 处问题")
        return 1
    if not args.brief:
        print("  ✓ 没有'函数内先引用、后局部导入'的别名")
        print(f"\n  结果：0 处问题（{len(files)} 个文件）")
    else:
        print(f"  结果：0 / {len(files)} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
