"""
theme_selfcheck.py —— 逐键校验 runtime/theme_table.json 是否只用了真实存在的枚举项

为什么必须校验：
    风格表里的键名（Col.Button / StyleVar.WindowRounding / implot.Col.PlotBg …）
    全部要写进 `getattr(imgui.Col, 键名)`。**写错一个字母，换肤那一行就抛
    AttributeError**。所以这里把 5 套风格 × 所有键逐条与绑定里的真实枚举对一遍，
    并且顺便验证颜色字符串能被解析成合法 RGBA。

跑法：
    .venv/bin/python 优化/验证/theme_selfcheck.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

directory = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(directory))
SOFTWARE = os.path.join(ROOT, "runtime")
if SOFTWARE not in sys.path:
    sys.path.insert(0, SOFTWARE)

from official_api import dear_imgui as imgui            # noqa: E402
from official_api import implot                            # noqa: E402

if SOFTWARE not in sys.path:
    sys.path.insert(0, SOFTWARE)
import ascii_text                                                        # noqa: E402


def enum_name(kind) -> set[str]:
    return {v for v in dir(kind) if not v.startswith("_") and v not in ("name", "value")}


imgui_colors = enum_name(imgui.Col)
imgui_styles = enum_name(imgui.StyleVar)
implot_colors = enum_name(implot.Col)
implot_styles = enum_name(implot.StyleVar)

errors: list[str] = []
warnings: list[str] = []
counts = {"颜色": 0, "样式": 0, "曲线颜色": 0}


def check_color(path: str, value) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", value):
        errors.append(f"{path}：颜色格式不对（要 #RRGGBB 或 #RRGGBBAA）：{value!r}")
    counts["颜色"] += 1


def check_number(path: str, value, variable_name: str) -> None:
    if variable_name in ("WindowPadding", "FramePadding", "ItemSpacing", "ItemInnerSpacing",
                  "CellPadding", "WindowTitleAlign", "ButtonTextAlign",
                  "SeparatorTextPadding", "WindowMinSize",
                  "PlotPadding", "LabelPadding", "LegendPadding", "LegendInnerPadding",
                  "AnnotationPadding", "DigitalPadding", "MousePosPadding",
                  "PlotDefaultSize", "PlotMinSize"):
        if not (isinstance(value, list) and len(value) == 2
                and all(isinstance(v, (int, float)) for v in value)):
            errors.append(f"{path}：{variable_name} 需要 [x, y] 两个数：{value!r}")
    elif not isinstance(value, (int, float)):
        errors.append(f"{path}：{variable_name} 需要数字：{value!r}")
    counts["样式"] += 1


def check_undefined_css_variables() -> None:
    """源码里 `var(--x)` 用到的变量，必须在 `theme.css` 里真的定义过。

    ★ 为什么加这条：`var(--warning)` 不存在时，浏览器**不会报错**，
      只会把那条颜色当成"没有值"——表现就是"文字/线没颜色"，
      代码看起来完全正常。实测踩过：告警色的走势曲线一直是空白的。
    """
    import re
    import glob

    definition = set()
    for file in ("frontend/src/generated/theme.css", "frontend/src/index.css"):
        source = (ROOT / file).read_text(encoding="utf-8")
        definition |= set(re.findall(r"(--[a-zA-Z0-9_-]+)\s*:", source))
    # Tailwind 与内联样式里允许的局部变量（不是颜色 token）
    allowed = {"--tw-ring-offset-shadow", "--tw-ring-shadow", "--tw-shadow"}
    missing = []
    used = 0
    for file in glob.glob(str(ROOT / "frontend/src/**/*.tsx"), recursive=True) +\
            glob.glob(str(ROOT / "frontend/src/**/*.ts"), recursive=True) +\
            glob.glob(str(ROOT / "frontend/src/**/*.css"), recursive=True):
        source = open(file, encoding="utf-8").read()
        for name in re.findall(r"var\((--[a-zA-Z0-9_-]+)", source):
            used += 1
            if name not in definition and name not in allowed:
                missing.append(f"{pathlib.Path(file).name}: {name}")
    if missing:
        check(False, "用到未定义的 CSS 变量（不会报错，只会没颜色）：" + "；".join(sorted(set(missing))[:6]))
    else:
        check(True, f"{used} 处 var(--…) 全部有定义")


def main() -> int:
    table_path = os.path.join(ROOT, "runtime", "theme_table.json")  # ★ 唯一权威份（应用读它）
    if not os.path.exists(table_path):
        table_path = os.path.join(ROOT, "runtime", "风格表.json")   # 旧检出回退
    with open(table_path, encoding="utf-8") as f:
        table = json.load(f)

    # 2026-10-16 整理：原先 `优化/风格表.json` 是审查期快照，要求两份逐字节一致。
    # 现在不保留第二份副本（副本漂移过），权威份只剩 runtime/theme_table.json，
    # 所以"两份一致"的检查退役——若将来又出现副本，会出现的那天再加回来。
    print()

    themes = table["themes"]
    print(f"读入风格表：{len(themes)} 套风格 —— {'、'.join(theme.get('display_name', name) for name, theme in themes.items())}")
    print(f"绑定里的可用枚举：imgui.Col {len(imgui_colors)} 项 / imgui.StyleVar {len(imgui_styles)} 项 / "
          f"implot.Col {len(implot_colors)} 项 / implot.StyleVar {len(implot_styles)} 项\n")

    for name, theme in themes.items():
        display = theme.get("display_name", name)
        print(f"── {name}（{display}）")
        # 颜色
        for key, value in theme.get("colors", {}).items():
            if key not in imgui_colors:
                errors.append(f"{name}.colors.{key}：imgui.Col 里没有这个枚举项（最接近的："
                            f"{sorted(x for x in imgui_colors if key[:5].lower() in x.lower())[:3]}）")
            check_color(f"{name}.colors.{key}", value)
        # 样式
        for key, value in theme.get("styles", {}).items():
            if key not in imgui_styles:
                errors.append(f"{name}.styles.{key}：imgui.StyleVar 里没有这个枚举项")
            check_number(f"{name}.styles", value, key)
        # 曲线
        plot = theme.get("plots", {})
        for key, value in plot.get("implot", {}).items():
            if key not in implot_colors:
                errors.append(f"{name}.plots.implot.{key}：implot.Col 里没有这个枚举项")
            check_color(f"{name}.plots.implot.{key}", value)
        for key, value in plot.get("line_styles", {}).items():
            if key not in implot_styles:
                errors.append(f"{name}.plots.line_styles.{key}：implot.StyleVar 里没有这个枚举项")
            check_number(f"{name}.plots.line_styles", value, key)
        palette = plot.get("palette", [])
        for i, value in enumerate(palette):
            check_color(f"{name}.plots.palette[{i}]", value)
        if len(palette) != 8:
            warnings.append(f"{name}.plots.palette 有 {len(palette)} 色（曲线基类默认 8 色，可改但要对齐）")
        print(f"   颜色 {len(theme.get('colors',{}))} 项 / 样式 {len(theme.get('styles',{}))} 项 / "
              f"曲线颜色 {len(plot.get('implot',{}))} 项 / 曲线样式 {len(plot.get('line_styles',{}))} 项 / "
              f"调色板 {len(palette)} 色")

    # ★ 面板上会画的字段必须是纯 ASCII（官方 UI 字体没有中文字形，中文会变成 ?）
    #   中文的 显示名/一句话 只给终端与文档用，面板用 英文名/英文说明。
    for name, theme in themes.items():
        for field in ("english_name", "english_description"):
            value = str(theme.get(field) or "")
            if not value:
                errors.append(f"{name}.{field} 缺失 —— 面板上要显示它（中文会画成 ?）")
            elif not ascii_text.is_supported(value):
                errors.append(f"{name}.{field} 含字体画不出来的字符：{value!r}")
        if not ascii_text.is_supported(str(theme.get("base_theme") or "")):
            errors.append(f"{name}.base_theme 含画不出来的字符")

    # 基底主题必须是官方认得的
    valid_bases = {"dark", "light", "classic"}
    for name, theme in themes.items():
        if theme.get("base_theme") not in valid_bases:
            errors.append(f"{name}.base_theme={theme.get('base_theme')!r}，官方只认 {valid_bases}")

    # ★ 源码里 var(--x) 用到的变量必须在主题里真的定义过：
    #   写错名字时浏览器**不报错**，只是那条颜色"没有值"，表现是文字/曲线没颜色。
    #   实测踩过：告警走势曲线用了不存在的 `--warning`（真名是 `--warn`），一直是空白。
    import glob as _glob
    import re as _re
    _defined = set()
    for _f in ("frontend/src/generated/theme.css", "frontend/src/index.css"):
        _source = pathlib.Path(ROOT, _f).read_text(encoding="utf-8")
        _defined |= set(_re.findall(r"(--[a-zA-Z0-9_-]+)\s*:", _source))
    _allowed = {"--tw-ring-offset-shadow", "--tw-ring-shadow", "--tw-shadow"}
    _missing, _used = [], 0
    for _f in (_glob.glob(os.path.join(ROOT, "frontend/src/**/*.tsx"), recursive=True)
               + _glob.glob(os.path.join(ROOT, "frontend/src/**/*.ts"), recursive=True)
               + _glob.glob(os.path.join(ROOT, "frontend/src/**/*.css"), recursive=True)):
        _text = open(_f, encoding="utf-8").read()
        for _match in _re.finditer(r"var\((--[a-zA-Z0-9_-]+)(\$\{)?", _text):
            # ★ 动态拼接的（`var(--palette-${i})`）跳过：名字要运行期才定，
            #   静态检查无从判断。这里只查**写死**的变量名。
            if _match.group(2):
                continue
            _name = _match.group(1)
            _used += 1
            if _name not in _defined and _name not in _allowed:
                _missing.append(f"{pathlib.Path(_f).name}: {_name}")
    if _missing:
        errors.append("用到未定义的 CSS 变量（不会报错，只会没颜色）："
                    + "；".join(sorted(set(_missing))[:6]))
    else:
        print(f"  CSS 变量：{_used} 处 var(--…) 全部有定义")

    print()
    if warnings:
        print(f"⚠ {len(warnings)} 条提醒：")
        for w in warnings:
            print("   · " + w)
    if errors:
        print(f"\n✗ {len(errors)} 处错误：")
        for e in errors:
            print("   · " + e)
        return 1
    print(f"✓ 全部通过：{counts['颜色']} 个颜色值 + {counts['样式']} 个样式值，"
          f"没有用到不存在的枚举项，颜色格式全部合法")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
