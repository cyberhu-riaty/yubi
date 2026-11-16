"""Exercise scanner coverage and regression checks without running the application."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit_naming", SCRIPTS / "audit_naming.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class NamingAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scope = audit.read_json(audit.SCOPE_FILE)
        self.previous_typescript = os.environ.get("YUBI_TYPESCRIPT_PATH")
        if not self.previous_typescript:
            os.environ["YUBI_TYPESCRIPT_PATH"] = str(SCRIPTS.parent / "前端/node_modules/typescript")
            self.addCleanup(lambda: os.environ.pop("YUBI_TYPESCRIPT_PATH", None))

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def findings(self):
        report = audit.scan(self.root, self.scope)
        self.assertEqual(report["errors"], [])
        return report

    def test_python_ui_text_is_allowed_but_internal_names_are_found(self):
        self.write("src/controller.py", '''
# 中文注释和文案可以保留。
"""中文文档字符串。"""
import 官方层 as adapter
class 控制器:
    def step(self, 目标):
        self.结果 = 目标
        return "控制完成"
''')
        names = {x["name"] for x in self.findings()["findings"]}
        self.assertEqual(names, {"官方层", "控制器", "目标", "结果"})

    def test_raw_non_ascii_python_identifiers_are_not_hidden_by_normalization(self):
        self.write("src/controller.py", "ｘ = 1\n")
        self.assertIn("ｘ", {x["name"] for x in self.findings()["findings"]})

    def test_typescript_uses_syntax_tree_and_keeps_jsx_text(self):
        self.write("frontend/Panel.tsx", '''
// 中文注释
import { value } from "./数据/store";
const 标题 = "中文界面";
const escaped = {"显示标签": value};
const lookup = escaped["显示标签"];
const \\u53d8\\u91cf = 1;
export function Panel() { return <button data-状态={标题}>开始运行</button>; }
''')
        findings = self.findings()["findings"]
        names = {x["name"] for x in findings}
        self.assertTrue({"标题", "变量", "data-状态", "./数据/store", "显示标签"} <= names)
        self.assertNotIn("中文界面", names)
        self.assertNotIn("开始运行", names)

    def test_json_keys_are_distinct_from_display_values(self):
        self.write("projects/example.json", '{"项目": {"model": "中文模型"}, "name": "中文显示名"}')
        findings = self.findings()["findings"]
        self.assertEqual([(x["category"], x["name"]) for x in findings], [("json_key", "/项目")])

    def test_jsonc_configuration_is_supported(self):
        self.write("frontend/tsconfig.json", '{// comment\n"compilerOptions": {}, "字段": 1,}')
        self.assertIn("/字段", {x["name"] for x in self.findings()["findings"]})

    def test_scope_includes_root_files_but_excludes_assets_and_dependencies(self):
        self.write("run_demo.py", "目标 = 1\n")
        self.write("ur10/example.py", "not valid Python!")
        self.write("软件/web/bundle.js", "not valid JavaScript!")
        self.write("frontend/node_modules/invalid.ts", "not valid TypeScript!")
        self.write("tools/新脚本.py", "print('中文文案')\n")
        report = self.findings()
        self.assertEqual(len(report["files"]), 2)
        self.assertIn("新脚本.py", {x["name"] for x in report["findings"]})

    def test_added_uses_and_new_files_cannot_hide_under_baseline(self):
        self.write("src/old.py", "目标 = 1\n")
        initial = self.findings()
        baseline = audit.baseline_for(initial, self.scope)
        self.assertEqual(audit.regressions(initial, baseline, self.scope), [])
        self.write("src/old.py", "目标 = 1\nprint(目标)\n")
        self.write("src/new.py", "目标 = 2\n")
        added = audit.regressions(self.findings(), baseline, self.scope)
        self.assertEqual({(x["path"], x["added"]) for x in added},
                         {("src/old.py", 1), ("src/new.py", 1)})

    def test_removals_are_allowed_and_comments_do_not_change_baseline_counts(self):
        self.write("src/old.py", "目标 = 1\nprint(目标)\n")
        baseline = audit.baseline_for(self.findings(), self.scope)
        self.write("src/old.py", "# 新增中文注释\n\n目标 = 1\n")
        self.assertEqual(audit.regressions(self.findings(), baseline, self.scope), [])

    def test_literal_ui_keys_are_advisory(self):
        self.write("src/ui.py", 'labels = {"显示名称": "机器人"}\n')
        report = self.findings()
        self.assertEqual(report["findings"][0]["category"], "string_key")
        self.assertEqual(audit.regressions(report, {"entries": []}, self.scope), [])

    def test_import_guard_distinguishes_relative_contract_from_root_shim(self):
        spec = importlib.util.spec_from_file_location("naming_policy", SCRIPTS / "check_naming.py")
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        self.write("src/device.py", "from .契约 import State\nimport 契约 as old\nfrom 契约 import Topic\n")
        imports = policy.imported_modules(self.root / "src/device.py")
        self.assertEqual(imports, [(1, ".契约"), (2, "契约"), (3, "契约")])
        self.assertNotIn(imports[0][1], policy.COMPATIBILITY_ONLY_MODULES)
        self.assertIn(imports[1][1], policy.COMPATIBILITY_ONLY_MODULES)

    def test_invalid_source_fails_instead_of_disappearing_from_inventory(self):
        self.write("src/broken.py", "def broken(:\n")
        self.assertTrue(audit.scan(self.root, self.scope)["errors"])

    def test_parse_failure_does_not_write_an_incomplete_report_or_baseline(self):
        self.write("src/broken.py", "def broken(:\n")
        baseline = self.root / "baseline.json"
        inventory = self.root / "inventory.md"
        with contextlib.redirect_stderr(io.StringIO()):
            status = audit.main(["--root", str(self.root), "--write-baseline", str(baseline),
                                 "--report", str(inventory)])
        self.assertEqual(status, 2)
        self.assertFalse(baseline.exists())
        self.assertFalse(inventory.exists())

    def test_missing_typescript_parser_is_an_error(self):
        self.write("frontend/Panel.tsx", "export const value = 1;")
        configured = os.environ["YUBI_TYPESCRIPT_PATH"]
        try:
            os.environ["YUBI_TYPESCRIPT_PATH"] = str(self.root / "missing-parser")
            self.assertTrue(audit.scan(self.root, self.scope)["errors"])
        finally:
            os.environ["YUBI_TYPESCRIPT_PATH"] = configured

    def test_shell_and_css_internal_names_are_found(self):
        self.write("tools/run.sh", "#!/bin/sh\n# 中文注释\n目标=1\necho '中文文案'\n")
        self.write("frontend/style.css", "/* 中文注释 */\n.按钮 { --宽度: 1px; content: '中文'; }\n")
        names = {x["name"] for x in self.findings()["findings"]}
        self.assertEqual(names, {"目标", ".按钮", "--宽度"})


if __name__ == "__main__":
    unittest.main()
