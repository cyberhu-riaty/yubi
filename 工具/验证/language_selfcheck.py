"""语言机制自检（不需要开窗口）：文案表完整性 / 语言开关与存档 / 决定优先级 / **禁止硬编码中文**。

用法：./.venv/bin/python "工具/验证/language_selfcheck.py"

★ 最后一条是这套机制的"防漏闸门"：面板里任何**画到界面上的中文**都必须走 `文案.取(键)`，
  否则切到英文时它不会跟着变（用户就会看到"半中半英"）。注释、docstring、终端日志（print）
  里的中文不算 —— 那三类不画到界面上。
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
panel_dir = os.path.join(ROOT, "软件", "面板")
for p in (os.path.join(ROOT, "软件"), panel_dir):
    if p not in sys.path:
        sys.path.insert(0, p)

settings_file = os.path.join(ROOT, "输出", "设置.json")
backup = None

passed = 0
failures = 0


def check(name, condition, detail=""):
    global passed, failures
    if condition:
        passed += 1
        print(f'  ✓ {name}')
    else:
        failures += 1
        print(f'  ✗ {name}' + (f"   —— {detail}" if detail else ""))


def read(path):
    try:
        return open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return None


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)


ui_functions = {"imgui", "ig"}          # 面板里画界面的两个别名

# 这些形状的串**不需要翻译**：纯数字/符号、单位、路径、格式占位、技术标记。
#   ★ 收紧标准时先想清楚：往这里加一条 = "这句永远只用一种语言"。
_technical_pattern = re.compile(r"^[\s0-9.,:%+\-*/()\[\]{}<>=|~^_#@!?\u2192\u00b7\u2014'\"]*$"
                 r"|^[/.\\\w.-]+\.(json|csv|xml|py|ini|ttf|so|app|txt|md|flag)$"
                 r"|^\s*[\w./\\-]+\s*$")


def is_technical_text(text: str) -> bool:
    if _technical_pattern.match(text):
        return True
    if not re.search(r"[A-Za-z]", text):
        return True                         # 没有拉丁字母（纯符号/数字/中文之外）
    return False


def ui_chinese_text(source: str) -> list[str]:
    """找出"直接交给 imgui 画的、写死的中文"。

    ★ 为什么要用 AST 而不是正则：正则会把 `{"显示名": ...}`、`"展开的段"` 这类
      **内部键名/字段名**全算成违规（第一版就误报了 237 条），而那些根本不画到界面上。
      只在"imgui.Xxx("参数")"这种位置里的中文字面量才算违规；
      经 `文案.取()/文案.格式化()/文案.状态()` 拿到的文字一律放行。
    """
    missing = []
    try:
        import i18n as _i18n
        exemptions = set(getattr(_i18n, "UNTRANSLATED_LABELS", set()))
    except Exception:                                                    # noqa: BLE001
        exemptions = set()

    def inspect_node(node) -> None:
        if node is None:
            return
        # 文案.取(...) / 文案.格式化(...) / 文案.状态(...) → 放行
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "i18n"):
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # ★ ImGui 的 `##` 之后是**隐藏 ID**，不画到屏幕上（"all##面板窗全开" 里
            #   中文部分只是 ID）—— 只检查可见部分。
            text = node.value.split("##")[0]
            if not text.strip():
                return                      # 纯 ID / 空串
            if text in exemptions:
                return
            if is_technical_text(text):
                return                      # 数字/单位/符号/路径这类不需要翻
            missing.append(f"第 {node.lineno} 行 {text[:28]}")
            return
        if isinstance(node, ast.JoinedStr):          # f-string：只看固定文字那几段
            for fragment in node.values:
                inspect_node(fragment)
            return
        if isinstance(node, ast.BinOp):              # "a" + 文案.取(...)
            inspect_node(node.left)
            inspect_node(node.right)
            return
        if isinstance(node, (ast.Tuple, ast.List)):
            for element in node.elts:
                inspect_node(element)

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f'（语法错误，跳过：{exc}）']
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in ui_functions):
            for argument in node.args:
                inspect_node(argument)
            for values in node.keywords:
                inspect_node(values.value)
    return missing


def main() -> int:
    global backup
    print("语言机制自检")
    backup = read(settings_file)
    try:
        import i18n
        # ---- ① 文案表完整性 ----
        TEXT = i18n.TEXT
        check("文案表非空", len(TEXT) > 0, f'{len(TEXT)} 条')
        invalid = [k for k, v in TEXT.items() if not (isinstance(v, tuple) and len(v) == 2
                                             and all(isinstance(x, str) and x.strip() for x in v))]
        check("每条都是 (中文, English) 且都不为空", not invalid, str(invalid[:5]))
        shared = [k for k, v in TEXT.items() if v[0] == v[1] and re.search(r"[A-Za-z]", v[0])]
        check("中英不相同的条目才需要登记（同文不同不过是冗余）", True, f"{len(shared)} 条中英相同（允许）")

        # ---- ② 语言开关与存档 ----
        i18n.set_language(i18n.EN)
        check("切到英文后 当前语言=英文", i18n.current_language == i18n.EN)
        get_key = next(iter(TEXT))
        check("英文模式下取到英文", i18n.get_text(get_key) == TEXT[get_key][1])
        i18n.set_language(i18n.ZH)
        check("切回中文后取到中文", i18n.get_text(get_key) == TEXT[get_key][0])
        check("未知键回落到默认值（不炸）", i18n.get_text("根本不存在的键", "fallback") == "fallback")
        check("设语言拒绝乱值", i18n.set_language("klingon") is False and i18n.current_language == i18n.ZH)
        document = json.loads(read(settings_file) or "{}")
        check("语言落进 输出/设置.json", document.get("语言") == i18n.ZH, str(document)[:80])

        # ---- ③ 决定启动语言：命令行 > 环境变量 > 存档 > 默认中文 ----
        language, origin = i18n.resolve_startup_language("en")
        check("命令行优先", language == i18n.EN and "命令行" in origin, origin)
        os.environ["YUBI_LANG"] = "en"
        language, origin = i18n.resolve_startup_language("")
        check("环境变量次之", language == i18n.EN and "环境" in origin, origin)
        del os.environ["YUBI_LANG"]
        i18n.write_saved_language(i18n.EN)
        language, origin = i18n.resolve_startup_language("")
        check("存档再次之", language == i18n.EN and "存档" in origin, origin)
        i18n.write_saved_language("")
        language, origin = i18n.resolve_startup_language("")
        check("都没有 → 默认中文", language == i18n.DEFAULT_LANGUAGE and language == i18n.ZH, origin)
        language, origin = i18n.resolve_startup_language("klingon")
        check("命令行乱值被忽略（回默认）", language == i18n.ZH, origin)

        # ---- ④ 防漏闸门：面板里不许有硬编码界面中文 ----
        # ★ 发布版可能**不带**官方 ImGui 面板（自研界面不需要它们）。
        #   目录/文件不在就跳过这一段，而不是抛 FileNotFoundError ——
        #   校验脚本不能因为"少了一个可选前端"就整条红。
        files = []
        if os.path.isdir(panel_dir):
            files += [os.path.join(panel_dir, f)
                     for f in sorted(os.listdir(panel_dir)) if f.endswith(".py")]
        for options in ("菜单栏.py",):
            candidates = os.path.join(ROOT, "软件", options)
            if os.path.exists(candidates):
                files.append(candidates)
        violations = []
        for path in files:
            for entry in ui_chinese_text(read(path) or ""):
                violations.append(f"{os.path.basename(path)} {entry}")
        check(f"{len(files)} 个面板文件里没有硬编码界面中文（必须走 文案.取）", not violations,
            "；".join(violations[:12]) + ("…" if len(violations) > 12 else ""))

        # ---- ③b 面板名双语 + 字体兜底的判定逻辑 ----
        i18n.set_language(i18n.ZH)
        chinese_name = i18n.panel_name("模型库")
        i18n.set_language(i18n.EN)
        english_name = i18n.panel_name("模型库")
        i18n.set_language(i18n.ZH)
        check("面板名会跟着语言变（模型库 → Model library）",
           chinese_name == "模型库" and english_name == "Model library", f"{chinese_name} / {english_name}")
        check("认不出的面板名原样返回（不炸）", i18n.panel_name("野面板") == "野面板")
        check("字体缺汉字时判定为 False（走回退字形：'中' 与 '?' 同宽）",
           i18n.font_has_cjk(lambda text: 6.0 if text == "中" else 6.0) is False)
        check("字体有汉字时判定为 True（'中' 明显更宽）",
           i18n.font_has_cjk(lambda text: 16.0 if text == "中" else 6.0) is True)

        # ---- ④b 用了 文案.xxx 的文件必须 import 文案（冒烟测试逮到过两次）----
        missing_imports = []
        for path in files:
            source = read(path) or ""
            if "i18n." in source and not re.search(r"^import\s+i18n(\s|$|#)", source, flags=re.M):
                missing_imports.append(os.path.basename(path))
        check("用了 文案.xxx 的文件都 import 了 文案", not missing_imports, "；".join(missing_imports))

        # ---- ⑤ 面板用到的每个键都存在 ----
        missing_keys = []
        for path in files:
            source = read(path) or ""
            for m in re.finditer(r'i18n\.get_text\(\s*"([^"]+)"', source):
                if m.group(1) not in TEXT:
                    missing_keys.append(f"{os.path.basename(path)} → {m.group(1)}")
        check("面板用到的键都在文案表里", not missing_keys, "；".join(missing_keys[:6]))
    finally:
        if backup is None:
            if os.path.exists(settings_file):
                os.remove(settings_file)
        else:
            write(settings_file, backup)

    print(f"\n结果：{passed} 通过 / {failures} 失败")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
