#!/usr/bin/env python3
"""Verify that official_api owns Studio imports and exports required symbols.

Use --short for compact output; the previous --简 option remains supported.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PACKAGE_ROOT / "runtime"))

ADAPTER_PATH = PACKAGE_ROOT / "runtime" / "official_api.py"
EXPERIMENTAL_PREFIX = "mujoco.experimental"

# 允许直接碰官方实验层的文件（**只有这一个**）
ALLOWED_IMPORT_FILES = {ADAPTER_PATH.resolve()}


def find_python_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*.py")
                  if "__pycache__" not in p.parts and ".venv" not in p.parts)


def check_file(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []          # 语法错由别的检查负责，这里不重复报
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith(EXPERIMENTAL_PREFIX):
                    issues.append(
                        f'{path.relative_to(PACKAGE_ROOT)}:{node.lineno} — 直接 import 了 '
                        f'{a.name}\n      改成：from official_api import <你要的模块>')
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith(EXPERIMENTAL_PREFIX):
                issues.append(
                    f'{path.relative_to(PACKAGE_ROOT)}:{node.lineno} — 直接 from-import 了 '
                    f'{module}\n      改成：from official_api import <你要的名字>')
    return issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="官方层自检：不变量 + 符号齐备")
    ap.add_argument("--short", "--简", dest="short", action="store_true")
    args = ap.parse_args(argv)

    files: list[Path] = []
    for name in ("runtime", "controllers", "tools"):
        directory = PACKAGE_ROOT / name
        files += [p for p in find_python_files(directory) if p.resolve() not in ALLOWED_IMPORT_FILES]

    issues: list[str] = []
    for f in files:
        issues += check_file(f)

    # 适配层自身要能导入、且符号齐全
    try:
        import official_api
    except Exception as exc:                                          # noqa: BLE001
        print(f'  ✗ 官方层 导入失败：{type(exc).__name__}: {exc}')
        return 1

    passed, total, details = official_api.self_check()
    issues += [f'官方层自检未过：{issue}' for issue in details]

    if not args.short:
        print("=" * 78)
        print(f'  官方层自检：扫了 {len(files)} 个文件（白名单外）')
        print("=" * 78)
    if issues:
        for issue in issues:
            print(f'  ✗ {issue}')
        print(f'\n  结果：{len(issues)} 处问题')
        return 1
    if args.short:
        print(f'  结果：✓ 0 处越界，官方层 {passed}/{total}')
    else:
        print(f'  ✓ 没有文件越界直接 import `{EXPERIMENTAL_PREFIX}`（唯一入口：runtime/official_api.py）')
        print(f'  ✓ 官方层依赖符号：{passed}/{total} 都在')
        print(f'\n  结果：✓ 通过（{len(files)} 个文件）')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
