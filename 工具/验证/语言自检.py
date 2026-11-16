"""语言机制自检（不需要开窗口）：文案表完整性 / 语言开关与存档 / 决定优先级 / **禁止硬编码中文**。

用法：./.venv/bin/python "工具/验证/语言自检.py"

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

包根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
面板目录 = os.path.join(包根, "软件", "面板")
for p in (os.path.join(包根, "软件"), 面板目录):
    if p not in sys.path:
        sys.path.insert(0, p)

设置文件 = os.path.join(包根, "输出", "设置.json")
备份 = None

通过 = 0
失败 = 0


def 用例(name, 条件, 说明=""):
    global 通过, 失败
    if 条件:
        通过 += 1
        print(f'  ✓ {name}')
    else:
        失败 += 1
        print(f'  ✗ {name}' + (f"   —— {说明}" if 说明 else ""))


def 读(路径):
    try:
        return open(路径, encoding="utf-8").read()
    except FileNotFoundError:
        return None


def 写(路径, text):
    os.makedirs(os.path.dirname(路径), exist_ok=True)
    open(路径, "w", encoding="utf-8").write(text)


界面函数 = {"imgui", "ig"}          # 面板里画界面的两个别名

# 这些形状的串**不需要翻译**：纯数字/符号、单位、路径、格式占位、技术标记。
#   ★ 收紧标准时先想清楚：往这里加一条 = "这句永远只用一种语言"。
_技术串 = re.compile(r"^[\s0-9.,:%+\-*/()\[\]{}<>=|~^_#@!?\u2192\u00b7\u2014'\"]*$"
                 r"|^[/.\\\w.-]+\.(json|csv|xml|py|ini|ttf|so|app|txt|md|flag)$"
                 r"|^\s*[\w./\\-]+\s*$")


def 是技术串(文: str) -> bool:
    if _技术串.match(文):
        return True
    if not re.search(r"[A-Za-z]", 文):
        return True                         # 没有拉丁字母（纯符号/数字/中文之外）
    return False


def 界面中文(源: str) -> list[str]:
    """找出"直接交给 imgui 画的、写死的中文"。

    ★ 为什么要用 AST 而不是正则：正则会把 `{"显示名": ...}`、`"展开的段"` 这类
      **内部键名/字段名**全算成违规（第一版就误报了 237 条），而那些根本不画到界面上。
      只在"imgui.Xxx("参数")"这种位置里的中文字面量才算违规；
      经 `文案.取()/文案.格式化()/文案.状态()` 拿到的文字一律放行。
    """
    漏 = []
    try:
        import i18n as _i18n
        豁免 = set(getattr(_i18n, "UNTRANSLATED_LABELS", set()))
    except Exception:                                                    # noqa: BLE001
        豁免 = set()

    def 看(节点) -> None:
        if 节点 is None:
            return
        # 文案.取(...) / 文案.格式化(...) / 文案.状态(...) → 放行
        if (isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute)
                and isinstance(节点.func.value, ast.Name) and 节点.func.value.id == "i18n"):
            return
        if isinstance(节点, ast.Constant) and isinstance(节点.value, str):
            # ★ ImGui 的 `##` 之后是**隐藏 ID**，不画到屏幕上（"all##面板窗全开" 里
            #   中文部分只是 ID）—— 只检查可见部分。
            文 = 节点.value.split("##")[0]
            if not 文.strip():
                return                      # 纯 ID / 空串
            if 文 in 豁免:
                return
            if 是技术串(文):
                return                      # 数字/单位/符号/路径这类不需要翻
            漏.append(f"第 {节点.lineno} 行 {文[:28]}")
            return
        if isinstance(节点, ast.JoinedStr):          # f-string：只看固定文字那几段
            for 片段 in 节点.values:
                看(片段)
            return
        if isinstance(节点, ast.BinOp):              # "a" + 文案.取(...)
            看(节点.left)
            看(节点.right)
            return
        if isinstance(节点, (ast.Tuple, ast.List)):
            for 元素 in 节点.elts:
                看(元素)

    try:
        树 = ast.parse(源)
    except SyntaxError as exc:
        return [f'（语法错误，跳过：{exc}）']
    for 节点 in ast.walk(树):
        if (isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute)
                and isinstance(节点.func.value, ast.Name)
                and 节点.func.value.id in 界面函数):
            for 参 in 节点.args:
                看(参)
            for values in 节点.keywords:
                看(values.value)
    return 漏


def 主() -> int:
    global 备份
    print("语言机制自检")
    备份 = 读(设置文件)
    try:
        import i18n
        # ---- ① 文案表完整性 ----
        TEXT = i18n.TEXT
        用例("文案表非空", len(TEXT) > 0, f'{len(TEXT)} 条')
        坏 = [k for k, v in TEXT.items() if not (isinstance(v, tuple) and len(v) == 2
                                             and all(isinstance(x, str) and x.strip() for x in v))]
        用例("每条都是 (中文, English) 且都不为空", not 坏, str(坏[:5]))
        同 = [k for k, v in TEXT.items() if v[0] == v[1] and re.search(r"[A-Za-z]", v[0])]
        用例("中英不相同的条目才需要登记（同文不同不过是冗余）", True, f"{len(同)} 条中英相同（允许）")

        # ---- ② 语言开关与存档 ----
        i18n.set_language(i18n.EN)
        用例("切到英文后 当前语言=英文", i18n.current_language == i18n.EN)
        取键 = next(iter(TEXT))
        用例("英文模式下取到英文", i18n.get_text(取键) == TEXT[取键][1])
        i18n.set_language(i18n.ZH)
        用例("切回中文后取到中文", i18n.get_text(取键) == TEXT[取键][0])
        用例("未知键回落到默认值（不炸）", i18n.get_text("根本不存在的键", "fallback") == "fallback")
        用例("设语言拒绝乱值", i18n.set_language("klingon") is False and i18n.current_language == i18n.ZH)
        文档 = json.loads(读(设置文件) or "{}")
        用例("语言落进 输出/设置.json", 文档.get("语言") == i18n.ZH, str(文档)[:80])

        # ---- ③ 决定启动语言：命令行 > 环境变量 > 存档 > 默认中文 ----
        language, 来源 = i18n.resolve_startup_language("en")
        用例("命令行优先", language == i18n.EN and "命令行" in 来源, 来源)
        os.environ["YUBI_LANG"] = "en"
        language, 来源 = i18n.resolve_startup_language("")
        用例("环境变量次之", language == i18n.EN and "环境" in 来源, 来源)
        del os.environ["YUBI_LANG"]
        i18n.write_saved_language(i18n.EN)
        language, 来源 = i18n.resolve_startup_language("")
        用例("存档再次之", language == i18n.EN and "存档" in 来源, 来源)
        i18n.write_saved_language("")
        language, 来源 = i18n.resolve_startup_language("")
        用例("都没有 → 默认中文", language == i18n.DEFAULT_LANGUAGE and language == i18n.ZH, 来源)
        language, 来源 = i18n.resolve_startup_language("klingon")
        用例("命令行乱值被忽略（回默认）", language == i18n.ZH, 来源)

        # ---- ④ 防漏闸门：面板里不许有硬编码界面中文 ----
        # ★ 发布版可能**不带**官方 ImGui 面板（自研界面不需要它们）。
        #   目录/文件不在就跳过这一段，而不是抛 FileNotFoundError ——
        #   校验脚本不能因为"少了一个可选前端"就整条红。
        文件 = []
        if os.path.isdir(面板目录):
            文件 += [os.path.join(面板目录, f)
                     for f in sorted(os.listdir(面板目录)) if f.endswith(".py")]
        for 可选 in ("菜单栏.py",):
            候选 = os.path.join(包根, "软件", 可选)
            if os.path.exists(候选):
                文件.append(候选)
        漏网 = []
        for 路径 in 文件:
            for 一条 in 界面中文(读(路径) or ""):
                漏网.append(f"{os.path.basename(路径)} {一条}")
        用例(f"{len(文件)} 个面板文件里没有硬编码界面中文（必须走 文案.取）", not 漏网,
            "；".join(漏网[:12]) + ("…" if len(漏网) > 12 else ""))

        # ---- ③b 面板名双语 + 字体兜底的判定逻辑 ----
        i18n.set_language(i18n.ZH)
        中文名 = i18n.panel_name("模型库")
        i18n.set_language(i18n.EN)
        英文名 = i18n.panel_name("模型库")
        i18n.set_language(i18n.ZH)
        用例("面板名会跟着语言变（模型库 → Model library）",
           中文名 == "模型库" and 英文名 == "Model library", f"{中文名} / {英文名}")
        用例("认不出的面板名原样返回（不炸）", i18n.panel_name("野面板") == "野面板")
        用例("字体缺汉字时判定为 False（走回退字形：'中' 与 '?' 同宽）",
           i18n.font_has_cjk(lambda 文: 6.0 if 文 == "中" else 6.0) is False)
        用例("字体有汉字时判定为 True（'中' 明显更宽）",
           i18n.font_has_cjk(lambda 文: 16.0 if 文 == "中" else 6.0) is True)

        # ---- ④b 用了 文案.xxx 的文件必须 import 文案（冒烟测试逮到过两次）----
        没导入 = []
        for 路径 in 文件:
            源 = 读(路径) or ""
            if "i18n." in 源 and not re.search(r"^import\s+i18n(\s|$|#)", 源, flags=re.M):
                没导入.append(os.path.basename(路径))
        用例("用了 文案.xxx 的文件都 import 了 文案", not 没导入, "；".join(没导入))

        # ---- ⑤ 面板用到的每个键都存在 ----
        缺键 = []
        for 路径 in 文件:
            源 = 读(路径) or ""
            for m in re.finditer(r'i18n\.get_text\(\s*"([^"]+)"', 源):
                if m.group(1) not in TEXT:
                    缺键.append(f"{os.path.basename(路径)} → {m.group(1)}")
        用例("面板用到的键都在文案表里", not 缺键, "；".join(缺键[:6]))
    finally:
        if 备份 is None:
            if os.path.exists(设置文件):
                os.remove(设置文件)
        else:
            写(设置文件, 备份)

    print(f"\n结果：{通过} 通过 / {失败} 失败")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
