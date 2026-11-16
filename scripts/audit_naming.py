"""Inventory non-ASCII internal names and reject additions beyond a reviewed baseline.

Comments, docstrings, UI text, and configuration values are not identifiers.
Literal object keys are advisory because they can also be user-visible labels.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tokenize


ROOT = Path(__file__).resolve().parents[1]
SCOPE_FILE = Path(__file__).with_name("naming_scope.json")
BASELINE_FILE = Path(__file__).with_name("naming_baseline.json")
TS_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def discover_files(root: Path, scope: dict) -> list[Path]:
    """Walk explicit application roots, pruning dependencies before descending."""
    extensions = set(scope["source_extensions"] + scope["config_extensions"])
    result = []

    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or path.name in scope["exclude_directories"]:
                continue
            if relative in scope["exclude_paths"]:
                continue
            if path.is_dir():
                visit(path)
            elif path.suffix in extensions and path.name not in scope["exclude_files"]:
                result.append(path)

    for name in scope["source_roots"]:
        directory = root / name
        if directory.is_dir():
            visit(directory)
    result.extend(path for path in root.iterdir()
                  if path.is_file() and path.suffix in extensions
                  and path.name not in scope["exclude_files"])
    return sorted(set(result))


def scan(root: Path, scope: dict) -> dict:
    files = discover_files(root, scope)
    findings: list[dict] = []
    errors: list[str] = []
    seen_directories: set[str] = set()
    ts_files = []

    def add(relative: str, line: int, category: str, name: str) -> None:
        if not name.isascii():
            findings.append(dict(path=relative, line=line, category=category, name=name))

    def json_keys(value, relative: str, prefix: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                pointer = f"{prefix}/{key.replace('~', '~0').replace('/', '~1')}"
                if not key.isascii():
                    add(relative, 0, "json_key", pointer)
                json_keys(child, relative, pointer)
        elif isinstance(value, list):
            for child in value:
                json_keys(child, relative, prefix + "/[]")

    for path in files:
        relative = path.relative_to(root).as_posix()
        for parent in path.relative_to(root).parents:
            name = parent.as_posix()
            if name != "." and name not in seen_directories:
                add(name, 0, "directory_name", parent.name)
                seen_directories.add(name)
        add(relative, 0, "file_name", path.name)
        if path.suffix in TS_EXTENSIONS:
            ts_files.append(relative)
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
            if path.suffix == ".py":
                tree = ast.parse(text, filename=relative)
                for token in tokenize.generate_tokens(io.StringIO(text).readline):
                    if token.type == tokenize.NAME:
                        add(relative, token.start[0], "python_identifier", token.string)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Dict):
                        for key in node.keys:
                            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                add(relative, key.lineno, "string_key", key.value)
                    elif isinstance(node, ast.Subscript):
                        key = node.slice
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            add(relative, key.lineno, "string_key", key.value)
            elif path.suffix == ".json":
                try:
                    json_keys(json.loads(text), relative)
                except json.JSONDecodeError:
                    # TypeScript configuration permits comments and trailing commas.
                    ts_files.append(relative)
            elif path.suffix == ".sh":
                for line, source in enumerate(text.splitlines(), 1):
                    if source.lstrip().startswith("#"):
                        continue
                    for match in re.finditer(
                        r"(?<![\w])([\w]+)(?=\s*\(\)\s*\{|=)|\$\{?([\w]+)", source
                    ):
                        add(relative, line, "shell_identifier", match.group(1) or match.group(2))
            elif path.suffix == ".css":
                # Replace comments/strings with spaces while preserving line numbers.
                source = re.sub(
                    r"/\*[\s\S]*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
                    lambda match: re.sub(r"[^\n]", " ", match.group()), text,
                )
                for match in re.finditer(r"(?:\.[\w-]+|--[\w-]+|\[([\w-]+))", source):
                    add(relative, source.count("\n", 0, match.start()) + 1,
                        "css_identifier", match.group(1) or match.group())
        except (ValueError, SyntaxError, tokenize.TokenError, UnicodeError) as exc:
            errors.append(f"{relative}: {exc}")

    if ts_files:
        try:
            result = subprocess.run(
                ["node", str(Path(__file__).with_name("audit_typescript_names.mjs"))],
                input=json.dumps(dict(root=str(root), files=ts_files)),
                capture_output=True, text=True, check=False,
            )
            if result.returncode:
                errors.append(result.stderr.strip() or "TypeScript scanner failed")
            else:
                parsed = json.loads(result.stdout)
                findings.extend(parsed["findings"])
                errors.extend(parsed["errors"])
        except (OSError, ValueError) as exc:
            errors.append(f"TypeScript scanner: {exc}")

    findings = sorted(findings, key=lambda x: (
        x["path"], x["category"], x["name"], x["line"]))
    return dict(version=1, files=[p.relative_to(root).as_posix() for p in files],
                findings=findings, errors=errors)


def finding_counts(report: dict, advisory: set[str]) -> Counter:
    return Counter((item["path"], item["category"], item["name"])
                   for item in report["findings"] if item["category"] not in advisory)


def baseline_for(report: dict, scope: dict) -> dict:
    counts = finding_counts(report, set(scope["advisory_categories"]))
    return dict(version=1, scope=scope, entries=[
        dict(path=path, category=category, name=name, count=count)
        for (path, category, name), count in sorted(counts.items())])


def regressions(report: dict, baseline: dict, scope: dict) -> list[dict]:
    allowed = Counter({(item["path"], item["category"], item["name"]): item["count"]
                       for item in baseline["entries"]})
    current = finding_counts(report, set(scope["advisory_categories"]))
    return [dict(path=path, category=category, name=name,
                 added=count - allowed[(path, category, name)])
            for (path, category, name), count in sorted(current.items())
            if count > allowed[(path, category, name)]]


def markdown_report(report: dict, scope: dict) -> str:
    totals = Counter(item["category"] for item in report["findings"])
    per_file = defaultdict(Counter)
    for item in report["findings"]:
        per_file[item["path"]][item["category"]] += 1
    lines = ["# 内部命名迁移清单", "", "由 `scripts/audit_naming.py` 从当前工作区生成。", "",
             f"扫描 {len(report['files'])} 个源码与配置文件；非 ASCII 名称出现位置共 "
             f"{len(report['findings'])} 处。次数表示位置数量，不是迁移完成百分比。", "",
             "中文界面、普通字符串值、注释和文档不计为标识符。字符串键是人工确认项，"
             "可能是机器字段，也可能是显示标签；JSON 键列入迁移范围。", "",
             "TypeScript/TSX 使用编译器语法树；Python 使用语法树与 token。"
             "CSS/Shell 使用静态词法扫描，动态拼接的协议和路径需要迁移时另行核对。", "",
             "## 分类统计", "", "| 类别 | 出现位置 |", "| --- | ---: |"]
    lines.extend(f"| `{category}` | {count} |" for category, count in sorted(totals.items()))
    lines.extend(["", "## 按文件迁移", "",
                  "目录与文件名是独立项；标识符数不包括注释和显示文案。", "",
                  "| 文件或目录 | 代码标识符 | 路径/导入 | JSON 键 | 字符串键待确认 |",
                  "| --- | ---: | ---: | ---: | ---: |"])
    for path, counts in sorted(per_file.items()):
        identifiers = sum(counts[k] for k in (
            "python_identifier", "typescript_identifier", "shell_identifier", "css_identifier"))
        paths = sum(counts[k] for k in ("directory_name", "file_name", "import_path"))
        lines.append(f"| `{path}` | {identifiers} | {paths} | {counts['json_key']} | {counts['string_key']} |")
    lines.extend(["", "## 下一步", "",
                  "实施批次和验收标准见 [迁移计划](naming-migration-plan.md)。",
                  "完整名称与行号可用 `--json-report /tmp/yubi-naming-audit.json` 导出。", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path, default=BASELINE_FILE)
    parser.add_argument("--write-baseline", type=Path,
                        help="Explicitly capture reviewed debt; never run automatically in CI")
    parser.add_argument("--strict", action="store_true", help="Fail on any remaining internal name")
    parser.add_argument("--report", type=Path, help="Write Markdown inventory")
    parser.add_argument("--json-report", type=Path, help="Write full findings with locations")
    args = parser.parse_args(argv)
    scope = read_json(SCOPE_FILE)
    report = scan(args.root.resolve(), scope)
    if report["errors"]:
        print("Naming audit could not scan all files:", file=sys.stderr)
        for error in report["errors"]:
            print(f"  {error}", file=sys.stderr)
        return 2
    for path, body in ((args.report, markdown_report(report, scope)),
                       (args.json_report, json.dumps(report, ensure_ascii=False, indent=2) + "\n")):
        if path:
            path.write_text(body, encoding="utf-8")
    if args.write_baseline:
        args.write_baseline.write_text(
            json.dumps(baseline_for(report, scope), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"Captured existing naming debt in {args.write_baseline}")
        return 0
    if args.strict:
        added = regressions(report, dict(entries=[]), scope)
    else:
        if not args.baseline.is_file():
            print(f"Missing reviewed baseline: {args.baseline}", file=sys.stderr)
            return 2
        baseline = read_json(args.baseline)
        if baseline.get("version") != 1 or baseline.get("scope") != scope:
            print("Baseline scope differs from scanner scope; review coverage before updating.", file=sys.stderr)
            return 2
        added = regressions(report, baseline, scope)
    if added:
        if args.strict:
            print(f"Strict naming check failed: {len(added)} internal names remain.")
        else:
            print(f"Naming check failed: {len(added)} names exceed the reviewed baseline.")
        for item in added[:30]:
            print(f"  {item['path']}: {item['category']} {item['name']!r} (+{item['added']})")
        if len(added) > 30:
            print("  ... use --json-report for the full inventory")
        return 1
    print(f"Naming gate passed across {len(report['files'])} files; "
          f"{len(report['findings'])} existing positions remain (including advisory keys). "
          "This is an incremental gate, not full migration completion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
