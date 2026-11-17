"""
generate_frontend_assets.py —— 把 Python 侧的**单一事实来源**生成成前端能直接吃的文件

它解决什么问题：
    P1 开始，界面换成了另一门语言。于是出现两个"必然漂移"的地方：
      ① 消息字段：Python 的 dataclass ↔ TypeScript 的类型定义
      ② 外观风格：`软件/风格表.json`（5 套风格）↔ 前端的 CSS 变量
    靠人抄一定会漂移，而且漂移了**不报错**——只是某个字段永远显示不出来、
    或者某个颜色悄悄不对。所以两边都从 Python 侧生成。

生成物（都带"别手改"的头注释）：
    `软件/web/契约.ts`        —— 后端下发的契约 → TS 类型 + 主题名常量
    `软件/web/主题.css`       —— 风格表 → CSS 变量（每套风格一个类）

用法：
    .venv/bin/python 工具/generate_frontend_assets.py          # 生成
    .venv/bin/python 工具/generate_frontend_assets.py --检查   # 只检查是否与当前生成物一致（给自检用）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(SCRIPT_DIR)
SOFTWARE_DIR = os.path.join(PACKAGE_ROOT, "软件")
if SOFTWARE_DIR not in sys.path:
    sys.path.insert(0, SOFTWARE_DIR)

# ---- 产物放哪儿：只放**构建期**目录，不放运行时的 `软件/web/` ----
#
# ★ 这里有一个踩过的坑，值得写清楚（结论是"别修症状，去删掉冲突的那份东西"）：
#
#   Vite 构建默认 `emptyOutDir`，会**递归清空**输出目录 `软件/web/`。
#   一开始生成物也放在那儿（想给运行时留一份 `主题.css`），于是每次构建都会删掉它。
#   表现很坑：**构建成功，但生成物检查突然失败**，而且顺序一变就时好时坏。
#
#   试过的两条"修症状"的路都不通：
#     · 靠"构建后记得补跑一次生成" —— 靠人记的事迟早会漏；
#     · 想给 `emptyOutDir` 配排除目录 —— Vite 这个选项**只有 boolean**（查过类型定义）。
#
#   真正对的修法是问一句：**那份运行时副本需要吗？** 答案是**不需要**：
#   前端 `main.tsx` 里 `import "./生成/主题.css"`，Vite 会把它打进
#   `软件/web/assets/index-*.css`（实测产物里 5 套风格的颜色变量齐全）。
#   所以运行时那一份是**冗余的**，删掉它，冲突就从根上没有了。
#
#   生成物只落在这里：
TS_OUTPUT_DIR = os.path.join(PACKAGE_ROOT, "前端", "src", "生成")
# 早先误放在 `软件/web/`（含其 `生成/` 子目录）的冗余副本 —— `--检查` 会要求清掉
LEGACY_OUTPUT_PATHS = (
    os.path.join(SOFTWARE_DIR, "web", "契约.ts"),
    os.path.join(SOFTWARE_DIR, "web", "风格.ts"),
    os.path.join(SOFTWARE_DIR, "web", "主题.css"),
    os.path.join(SOFTWARE_DIR, "web", "生成", "主题.css"),
)

# ---------------------------------------------------------------------------
# ① 契约 → TypeScript
# ---------------------------------------------------------------------------
_typescript_type = {
    "number": "number",
    "string": "string",
    "boolean": "boolean",
    "any": "unknown",
    "number[]": "number[]",
    "string[]": "string[]",
    "object[]": "Record<string, unknown>[]",
    "record<number>": "Record<string, number>",
    "record<any>": "Record<string, unknown>",
}


def generate_contract_typescript() -> str:
    import contract

    data = contract.to_dict()
    line: list[str] = [
        "// ⚠️ 本文件由 `工具/generate_frontend_assets.py` 生成，**不要手改**。",
        "// 来源：`软件/contract.py`（后端与前端之间唯一的通信契约）。",
        "// 改了契约就跑一次生成；`工具/验证/contract_selfcheck.py` 会检查它有没有过期。",
        "",
        f"export const 契约版本 = {data['版本']};",
        f'export const 协议版本 = {contract.VERSION};',
        "",
    ]

    def section(title: str, topics: list[dict], prefix: str) -> None:
        line.append(f"// ---------------- {title} ----------------")
        line.append(f"export type {prefix}主题名 =")
        for i, t in enumerate(topics):
            line.append(f'  {"| " if i else "  "}"{t["名"]}"')
        line.append("  ;")
        line.append("")
        for t in topics:
            line.append(f"/** {t['摘要']} */")
            line.append(f"export interface {prefix}_{_safe_identifier(t['名'])} {{")
            if not t["字段"]:
                line.append("  [键: string]: unknown;")
            for f in t["字段"]:
                annotation = _typescript_type.get(f["类型"], "unknown")
                description = f"  /** {f['说明']} */" if f["说明"] else ""
                if description:
                    line.append(description)
                line.append(f"  {_safe_field(f['名'])}: {annotation};")
            line.append("}")
            line.append("")
        # 主题名 → 负载类型的映射，前端分发时用它
        line.append(f"export interface {prefix}负载表 {{")
        for t in topics:
            line.append(f'  "{t["名"]}": {prefix}_{_safe_identifier(t["名"])};')
        line.append("}")
        line.append("")

    section("下行：仿真 → 界面", data["下行"], "下行")
    section("上行：界面 → 仿真（命令）", data["上行"], "上行")

    line.append("// ---------------- 元信息 ----------------")
    line.append("export interface 主题元 {")
    line.append("  名: string;")
    line.append("  类名: string;")
    line.append("  种类: string;")
    line.append("  摘要: string;")
    line.append("}")
    line.append("")
    line.append("export const 下行元: 主题元[] = [")
    for t in data["下行"]:
        line.append(f'  {{ 名: "{t["名"]}", 类名: "{t["类名"]}", 种类: "{t["种类"]}", '
                 f'摘要: {json.dumps(t["摘要"], ensure_ascii=False)} }},')
    line.append("];")
    line.append("")
    line.append("export const 上行元: 主题元[] = [")
    for t in data["上行"]:
        line.append(f'  {{ 名: "{t["名"]}", 类名: "{t["类名"]}", 种类: "{t["种类"]}", '
                 f'摘要: {json.dumps(t["摘要"], ensure_ascii=False)} }},')
    line.append("];")
    line.append("")
    return "\n".join(line)


def _safe_identifier(name: str) -> str:
    """把主题名变成合法的 TS 标识符（中文可以用，去掉点号等）。"""
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in name)


def _safe_field(name: str) -> str:
    """字段名可能是中文（直接可用）；带引号风险的一律加引号。"""
    if name.isidentifier():
        return name
    return json.dumps(name, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ② 风格表 → CSS 变量
# ---------------------------------------------------------------------------
# ImGui 的颜色名 → 网页语义名（按优先级取第一个存在的键）
SEMANTIC_COLORS: dict[str, tuple[str, ...]] = {
    "bg":            ("WindowBg", "ChildBg"),
    "bg-panel":      ("ChildBg", "WindowBg"),
    "bg-popup":      ("PopupBg", "ChildBg"),
    "bg-menu":       ("MenuBarBg", "WindowBg"),
    "bg-title":      ("TitleBg", "MenuBarBg"),
    "bg-title-on":   ("TitleBgActive", "TitleBg"),
    "bg-frame":      ("FrameBg", "ChildBg"),
    "bg-frame-hover": ("FrameBgHovered", "FrameBg"),
    "bg-frame-on":   ("FrameBgActive", "FrameBgHovered"),
    "bg-header":     ("Header", "FrameBg"),
    "bg-header-hover": ("HeaderHovered", "Header"),
    "bg-header-on":  ("HeaderActive", "HeaderHovered"),
    "bg-tab":        ("Tab", "FrameBg"),
    "bg-tab-hover":  ("TabHovered", "Tab"),
    "bg-tab-on":     ("TabSelected", "Tab"),
    "bg-table-head": ("TableHeaderBg", "Header"),
    "bg-row":        ("TableRowBg", "ChildBg"),
    "bg-row-alt":    ("TableRowBgAlt", "TableRowBg"),
    "bg-nav":        ("NavHighlight", "Header"),
    "bg-scroll":     ("ScrollbarBg", "ChildBg"),
    "bg-scroll-grab": ("ScrollbarGrab", "Separator"),
    "fg":            ("Text",),
    "fg-dim":        ("TextDisabled", "Text"),
    "fg-link":       ("TextLink", "Text"),
    "fg-on-accent":  ("CheckMark", "Text"),
    "border":        ("Border", "Separator"),
    "border-strong": ("TableBorderStrong", "Border"),
    "border-light":  ("TableBorderLight", "Border"),
    "separator":     ("Separator", "Border"),
    "accent":        ("Button", "Header"),
    "accent-hover":  ("ButtonHovered", "Button"),
    "accent-on":     ("ButtonActive", "ButtonHovered"),
    "grab":          ("SliderGrab", "Button"),
    "grab-on":       ("SliderGrabActive", "SliderGrab"),
    "sel-bg":        ("TextSelectedBg", "Header"),
    "resize":        ("ResizeGrip", "Separator"),
    "shadow":        ("BorderShadow", "Border"),
}

PLOT_COLORS: dict[str, str] = {
    "plot-bg": "PlotBg",
    "plot-border": "PlotBorder",
    "plot-grid": "AxisGrid",
    "plot-tick": "AxisTick",
    "plot-text": "AxisText",
    "plot-title": "TitleText",
    "plot-legend-bg": "LegendBg",
    "plot-legend-border": "LegendBorder",
    "plot-cross": "Crosshairs",
    "plot-sel": "Selection",
    "plot-lines": "PlotLines",
    "plot-hist": "PlotHistogram",
}


def get_color(colors: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        if k in colors:
            return str(colors[k])
    return None


def generate_theme_css() -> str:
    table = json.load(open(os.path.join(SOFTWARE_DIR, "风格表.json"), encoding="utf-8"))
    themes: dict = table["风格"]
    line: list[str] = [
        "/* ⚠️ 本文件由 `工具/generate_frontend_assets.py` 生成，**不要手改**。",
        " * 来源：`软件/风格表.json`（全部风格，数据驱动换肤的唯一数据源）。",
        " * 用法：把 `data-风格=\"航天测控\"` 放在 <html> 上即可整站换肤。 */",
        "",
        ":root {",
        "  --radius: 6px;",
        "  --font-ui: -apple-system, BlinkMacSystemFont, \"PingFang SC\", \"Microsoft YaHei\",",
        "             \"Segoe UI\", Roboto, sans-serif;",
        "  --font-mono: \"SF Mono\", ui-monospace, Menlo, Consolas, monospace;",
        "}",
        "",
    ]
    # 默认皮肤名：来自 `风格表.json` 的 `默认风格` 字段（取不到就退回排序第一个）
    default_theme = table.get("默认风格") or None
    # ★ 默认皮肤必须**先输出**，其余皮肤后输出。
    #   原因：默认块带 `:root`，而 `:root` 与 `[data-风格=…]` 同特异性；
    #   若默认块排在最后，它会在 `<html data-风格="航天测控">` 时仍然覆盖所有
    #   皮肤变量 —— 换肤看起来"点了没反应"（实测踩到）。
    #   排到最前面后：没设 data-风格 → `:root` 生效；设了 → 后面的属性块覆盖。
    order = list(themes.items())
    if default_theme in themes:
        order = [(default_theme, themes[default_theme])] + [
            (name, theme) for name, theme in order if name != default_theme
        ]
    for i, (name, theme) in enumerate(order):
        color = theme.get("颜色", {})
        style = theme.get("样式", {})
        plot = theme.get("曲线", {})
        imp = plot.get("implot", {}) if isinstance(plot, dict) else {}
        palette = plot.get("调色板", []) if isinstance(plot, dict) else []
        # ★ 选择器不能都挂 `:root`：那样 5 套风格会互相覆盖，只有最后一套生效
        #   （实测踩过）。默认那套挂 `:root`（没设 data-风格 时也能看），
        #   其余只挂属性选择器。
        # ★ 默认皮肤由 `风格表.json` 的 `默认风格` 字段决定，**不再靠列表排序**。
        #   靠排序的话，"想换个默认皮肤"就得去挪数据顺序 —— 那会连带改掉
        #   `风格表.ts` 的顺序，界面上皮肤列表也跟着跳，属于用错了杠杆。
        default = (name == default_theme) or (default_theme is None and i == 0)
        selector = (':root, [data-风格="%s"]' % name) if default else ('[data-风格="%s"]' % name)
        line.append(f"/* {name} · {theme.get('英文名','')} —— {theme.get('一句话','')} */")
        line.append(f"{selector} {{")
        for semantic, keys in SEMANTIC_COLORS.items():
            value = get_color(color, keys)
            if value:
                line.append(f"  --{semantic}: {value};")
        for semantic, key in PLOT_COLORS.items():
            if key in imp:
                line.append(f"  --{semantic}: {imp[key]};")
        if palette:
            line.append("  --palette: " + ", ".join(palette) + ";")
            for i, c in enumerate(palette[:8], 1):
                line.append(f"  --palette-{i}: {c};")
        # 语义状态色：日志等级、兼容性提示、运行状态共用。
        #   ★ 单独放在风格表顶层的 `网页语义色` 里，而不是从调色板里猜索引 ——
        #     调色板的顺序是给曲线用的，拿它当状态色会在换肤后把"错误"画成紫色。
        semantic_colors = table.get("网页语义色", {}).get(name, {})
        for semantic, chinese in (("info", "信息"), ("ok", "成功"),
                          ("warn", "警告"), ("danger", "错误")):
            value = semantic_colors.get(chinese)
            if value:
                line.append(f"  --{semantic}: {value};")
        # 样式：只搬网页有意义的几项
        roundness = style.get("FrameRounding")
        border = style.get("WindowBorderSize")
        inner = style.get("WindowPadding")
        if isinstance(roundness, (int, float)):
            line.append(f"  --radius: {float(roundness):.1f}px;")
        if isinstance(border, (int, float)):
            line.append(f"  --border-w: {float(border):.1f}px;")
        if isinstance(inner, list) and len(inner) == 2:
            line.append(f"  --pad-x: {float(inner[0]):.1f}px;")
            line.append(f"  --pad-y: {float(inner[1]):.1f}px;")
        line.append(f"  --基底: {theme.get('基底主题','dark')};")
        line.append(f"  --字号倍率: {theme.get('自研面板字号', 1.0)};")
        line.append("}")
        # 深浅色提示：给浏览器原生控件（滚动条、输入框）用。
        # ★ 默认那套要连 `:root` 一起写，否则"没设 data-风格"时拿不到 color-scheme。
        palette_name = "light" if theme.get("基底主题") == "light" else "dark"
        line.append((f':root, [data-风格="{name}"]' if default else f'[data-风格="{name}"]')
                 + f" {{ color-scheme: {palette_name}; }}")
        line.append("")
    return "\n".join(line)


# ---------------------------------------------------------------------------
# ③ 主题元信息 → TS（前端风格切换器要用）
# ---------------------------------------------------------------------------
def generate_theme_typescript() -> str:
    table = json.load(open(os.path.join(SOFTWARE_DIR, "风格表.json"), encoding="utf-8"))
    line = [
        "// ⚠️ 本文件由 `工具/generate_frontend_assets.py` 生成，**不要手改**。",
        "// 来源：`软件/风格表.json`。",
        "",
        "export interface 风格元 {",
        "  名: string;",
        "  英文名: string;",
        "  一句话: string;",
        "  基底: string;",
        "}",
        "",
        "export const 风格表: 风格元[] = [",
    ]
    for name, theme in table["风格"].items():
        line.append("  { 名: %s, 英文名: %s, 一句话: %s, 基底: %s },"
                 % (json.dumps(name, ensure_ascii=False),
                    json.dumps(theme.get("英文名", ""), ensure_ascii=False),
                    json.dumps(theme.get("一句话", ""), ensure_ascii=False),
                    json.dumps(theme.get("基底主题", "dark"), ensure_ascii=False)))
    line += ["];", "",
          # ★ 同样认 `默认风格` 字段，不靠 风格列表[0]
          "export const 默认风格 = %s;" % json.dumps(
              table.get("默认风格") or table["风格列表"][0], ensure_ascii=False),
          ""]
    return "\n".join(line)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
# 名 → (内容生成函数, 目标目录)。TS 走构建期目录，CSS 走运行时目录。
OUTPUTS = {
    "契约.ts": (generate_contract_typescript, TS_OUTPUT_DIR),
    "风格.ts": (generate_theme_typescript, TS_OUTPUT_DIR),
    "主题.css": (generate_theme_css, TS_OUTPUT_DIR),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="把契约与风格表生成成前端资产")
    ap.add_argument("--check", "--检查", dest="check", action="store_true",
                    help="只检查产物是否与当前来源一致（不一致退出码 1）")
    args = ap.parse_args()

    os.makedirs(TS_OUTPUT_DIR, exist_ok=True)
    stale: list[str] = []
    for name, (generate, directory) in OUTPUTS.items():
        text = generate()
        path = os.path.join(directory, name)
        previous = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        if previous == text:
            print(f"  ✓ {name} 与来源一致（{len(text)} 字节）")
            continue
        if args.check:
            stale.append(name)
            print(f"  ✗ {name} 与来源不一致（产物 {len(previous)} 字节 / 应为 {len(text)} 字节）"
                  f" → {os.path.relpath(path, PACKAGE_ROOT)}")
        else:
            open(path, "w", encoding="utf-8").write(text)
            print(f"  ✓ 已生成 {name}（{len(text)} 字节）"
                  f" → {os.path.relpath(path, PACKAGE_ROOT)}")

    # 清掉早先放在 `软件/web/` 里的冗余副本（见文件头"踩过的坑"）。
    for legacy_path in LEGACY_OUTPUT_PATHS:
        if os.path.exists(legacy_path):
            if args.check:
                stale.append(os.path.basename(legacy_path) + "（遗留位置）")
                print(f"  ✗ {os.path.relpath(legacy_path, PACKAGE_ROOT)} 是冗余副本，应删除（运行时用打包产物）")
            else:
                os.remove(legacy_path)
                print(f"  ✓ 已清掉冗余副本 {os.path.relpath(legacy_path, PACKAGE_ROOT)}")

    if args.check and stale:
        print(f"\n  结论：{len(stale)} 个产物过期，跑一次 "
              f"`.venv/bin/python 工具/generate_frontend_assets.py` 重新生成")
        return 1
    return 0


if __name__ == "__main__":
    print("=" * 72)
    print("  生成前端资产（契约 → TS，风格表 → CSS）")
    print("=" * 72)
    raise SystemExit(main())
