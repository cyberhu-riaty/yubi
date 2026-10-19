"""
校验风格表.py —— 逐键校验 优化/风格表.json 是否只用了真实存在的枚举项

为什么必须校验：
    风格表里的键名（Col.Button / StyleVar.WindowRounding / implot.Col.PlotBg …）
    全部要写进 `getattr(imgui.Col, 键名)`。**写错一个字母，换肤那一行就抛
    AttributeError**。所以这里把 5 套风格 × 所有键逐条与绑定里的真实枚举对一遍，
    并且顺便验证颜色字符串能被解析成合法 RGBA。

跑法：
    .venv/bin/python 优化/验证/校验风格表.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

本目录 = os.path.dirname(os.path.abspath(__file__))
包根 = os.path.dirname(os.path.dirname(本目录))
软件目录 = os.path.join(包根, "软件")
if 软件目录 not in sys.path:
    sys.path.insert(0, 软件目录)

from 官方层 import dear_imgui as imgui            # noqa: E402
from 官方层 import implot                            # noqa: E402

if 软件目录 not in sys.path:
    sys.path.insert(0, 软件目录)
import 界面文字                                                        # noqa: E402


def 枚举名(类) -> set[str]:
    return {v for v in dir(类) if not v.startswith("_") and v not in ("name", "value")}


Imgui颜色 = 枚举名(imgui.Col)
ImGui样式 = 枚举名(imgui.StyleVar)
Implot颜色 = 枚举名(implot.Col)
Implot样式 = 枚举名(implot.StyleVar)

错误: list[str] = []
警告: list[str] = []
统计 = {"颜色": 0, "样式": 0, "曲线颜色": 0}


def 校验颜色(路径: str, 值) -> None:
    if not isinstance(值, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", 值):
        错误.append(f"{路径}：颜色格式不对（要 #RRGGBB 或 #RRGGBBAA）：{值!r}")
    统计["颜色"] += 1


def 校验数值(路径: str, 值, 变量名: str) -> None:
    if 变量名 in ("WindowPadding", "FramePadding", "ItemSpacing", "ItemInnerSpacing",
                  "CellPadding", "WindowTitleAlign", "ButtonTextAlign",
                  "SeparatorTextPadding", "WindowMinSize",
                  "PlotPadding", "LabelPadding", "LegendPadding", "LegendInnerPadding",
                  "AnnotationPadding", "DigitalPadding", "MousePosPadding",
                  "PlotDefaultSize", "PlotMinSize"):
        if not (isinstance(值, list) and len(值) == 2
                and all(isinstance(v, (int, float)) for v in 值)):
            错误.append(f"{路径}：{变量名} 需要 [x, y] 两个数：{值!r}")
    elif not isinstance(值, (int, float)):
        错误.append(f"{路径}：{变量名} 需要数字：{值!r}")
    统计["样式"] += 1


def 检查未定义的css变量() -> None:
    """源码里 `var(--x)` 用到的变量，必须在 `主题.css` 里真的定义过。

    ★ 为什么加这条：`var(--warning)` 不存在时，浏览器**不会报错**，
      只会把那条颜色当成"没有值"——表现就是"文字/线没颜色"，
      代码看起来完全正常。实测踩过：告警色的走势曲线一直是空白的。
    """
    import re
    import glob

    定义处 = set()
    for 文件 in ("前端/src/生成/主题.css", "前端/src/index.css"):
        源 = (包根 / 文件).read_text(encoding="utf-8")
        定义处 |= set(re.findall(r"(--[a-zA-Z0-9_-]+)\s*:", 源))
    # Tailwind 与内联样式里允许的局部变量（不是颜色 token）
    允许 = {"--tw-ring-offset-shadow", "--tw-ring-shadow", "--tw-shadow"}
    漏 = []
    用了 = 0
    for 文件 in glob.glob(str(包根 / "前端/src/**/*.tsx"), recursive=True) + \
            glob.glob(str(包根 / "前端/src/**/*.ts"), recursive=True) + \
            glob.glob(str(包根 / "前端/src/**/*.css"), recursive=True):
        源 = open(文件, encoding="utf-8").read()
        for 名 in re.findall(r"var\((--[a-zA-Z0-9_-]+)", 源):
            用了 += 1
            if 名 not in 定义处 and 名 not in 允许:
                漏.append(f"{pathlib.Path(文件).name}: {名}")
    if 漏:
        判(False, "用到未定义的 CSS 变量（不会报错，只会没颜色）：" + "；".join(sorted(set(漏))[:6]))
    else:
        判(True, f"{用了} 处 var(--…) 全部有定义")


def main() -> int:
    表路径 = os.path.join(包根, "软件", "风格表.json")      # ★ 唯一权威份（应用读它）
    with open(表路径, encoding="utf-8") as f:
        表 = json.load(f)

    # 2026-10-16 整理：原先 `优化/风格表.json` 是审查期快照，要求两份逐字节一致。
    # 报告归入 报告/ 之后不再保留第二份副本（副本漂移过），权威份只剩 软件/ 这一份，
    # 所以"两份一致"的检查退役——若将来又出现副本，会出现的那天再加回来。
    print()

    风格们 = 表["风格"]
    print(f"读入风格表：{len(风格们)} 套风格 —— {'、'.join(风格们)}")
    print(f"绑定里的可用枚举：imgui.Col {len(Imgui颜色)} 项 / imgui.StyleVar {len(ImGui样式)} 项 / "
          f"implot.Col {len(Implot颜色)} 项 / implot.StyleVar {len(Implot样式)} 项\n")

    for 名, 风格 in 风格们.items():
        print(f"── {名}（{风格.get('显示名','?')}）")
        # 颜色
        for 键, 值 in 风格.get("颜色", {}).items():
            if 键 not in Imgui颜色:
                错误.append(f"{名}.颜色.{键}：imgui.Col 里没有这个枚举项（最接近的："
                            f"{sorted(x for x in Imgui颜色 if 键[:5].lower() in x.lower())[:3]}）")
            校验颜色(f"{名}.颜色.{键}", 值)
        # 样式
        for 键, 值 in 风格.get("样式", {}).items():
            if 键 not in ImGui样式:
                错误.append(f"{名}.样式.{键}：imgui.StyleVar 里没有这个枚举项")
            校验数值(f"{名}.样式", 值, 键)
        # 曲线
        曲线 = 风格.get("曲线", {})
        for 键, 值 in 曲线.get("implot", {}).items():
            if 键 not in Implot颜色:
                错误.append(f"{名}.曲线.implot.{键}：implot.Col 里没有这个枚举项")
            校验颜色(f"{名}.曲线.implot.{键}", 值)
        for 键, 值 in 曲线.get("曲线样式", {}).items():
            if 键 not in Implot样式:
                错误.append(f"{名}.曲线.曲线样式.{键}：implot.StyleVar 里没有这个枚举项")
            校验数值(f"{名}.曲线.曲线样式", 值, 键)
        调色板 = 曲线.get("调色板", [])
        for i, 值 in enumerate(调色板):
            校验颜色(f"{名}.曲线.调色板[{i}]", 值)
        if len(调色板) != 8:
            警告.append(f"{名}.曲线.调色板 有 {len(调色板)} 色（曲线基类默认 8 色，可改但要对齐）")
        print(f"   颜色 {len(风格.get('颜色',{}))} 项 / 样式 {len(风格.get('样式',{}))} 项 / "
              f"曲线颜色 {len(曲线.get('implot',{}))} 项 / 曲线样式 {len(曲线.get('曲线样式',{}))} 项 / "
              f"调色板 {len(调色板)} 色")

    # ★ 面板上会画的字段必须是纯 ASCII（官方 UI 字体没有中文字形，中文会变成 ?）
    #   中文的 显示名/一句话 只给终端与文档用，面板用 英文名/英文说明。
    for 名, 风格 in 风格们.items():
        for 字段 in ("英文名", "英文说明"):
            值 = str(风格.get(字段) or "")
            if not 值:
                错误.append(f"{名}.{字段} 缺失 —— 面板上要显示它（中文会画成 ?）")
            elif not 界面文字.可用(值):
                错误.append(f"{名}.{字段} 含字体画不出来的字符：{值!r}")
        if not 界面文字.可用(str(风格.get("基底主题") or "")):
            错误.append(f"{名}.基底主题 含画不出来的字符")

    # 基底主题必须是官方认得的
    合法基底 = {"dark", "light", "classic"}
    for 名, 风格 in 风格们.items():
        if 风格.get("基底主题") not in 合法基底:
            错误.append(f"{名}.基底主题={风格.get('基底主题')!r}，官方只认 {合法基底}")

    # ★ 源码里 var(--x) 用到的变量必须在主题里真的定义过：
    #   写错名字时浏览器**不报错**，只是那条颜色"没有值"，表现是文字/曲线没颜色。
    #   实测踩过：告警走势曲线用了不存在的 `--warning`（真名是 `--warn`），一直是空白。
    import glob as _glob
    import re as _re
    _定义 = set()
    for _f in ("前端/src/生成/主题.css", "前端/src/index.css"):
        _源 = pathlib.Path(包根, _f).read_text(encoding="utf-8")
        _定义 |= set(_re.findall(r"(--[a-zA-Z0-9_-]+)\s*:", _源))
    _允许 = {"--tw-ring-offset-shadow", "--tw-ring-shadow", "--tw-shadow"}
    _漏, _用 = [], 0
    for _f in (_glob.glob(os.path.join(包根, "前端/src/**/*.tsx"), recursive=True)
               + _glob.glob(os.path.join(包根, "前端/src/**/*.ts"), recursive=True)
               + _glob.glob(os.path.join(包根, "前端/src/**/*.css"), recursive=True)):
        _文本 = open(_f, encoding="utf-8").read()
        for _匹配 in _re.finditer(r"var\((--[a-zA-Z0-9_-]+)(\$\{)?", _文本):
            # ★ 动态拼接的（`var(--palette-${i})`）跳过：名字要运行期才定，
            #   静态检查无从判断。这里只查**写死**的变量名。
            if _匹配.group(2):
                continue
            _名 = _匹配.group(1)
            _用 += 1
            if _名 not in _定义 and _名 not in _允许:
                _漏.append(f"{pathlib.Path(_f).name}: {_名}")
    if _漏:
        错误.append("用到未定义的 CSS 变量（不会报错，只会没颜色）："
                    + "；".join(sorted(set(_漏))[:6]))
    else:
        print(f"  CSS 变量：{_用} 处 var(--…) 全部有定义")

    print()
    if 警告:
        print(f"⚠ {len(警告)} 条提醒：")
        for w in 警告:
            print("   · " + w)
    if 错误:
        print(f"\n✗ {len(错误)} 处错误：")
        for e in 错误:
            print("   · " + e)
        return 1
    print(f"✓ 全部通过：{统计['颜色']} 个颜色值 + {统计['样式']} 个样式值，"
          f"没有用到不存在的枚举项，颜色格式全部合法")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
