"""
生成前端资产.py —— 把 Python 侧的**单一事实来源**生成成前端能直接吃的文件

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
    .venv/bin/python 工具/生成前端资产.py          # 生成
    .venv/bin/python 工具/生成前端资产.py --检查   # 只检查是否与当前生成物一致（给自检用）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

这里 = os.path.dirname(os.path.abspath(__file__))
包根 = os.path.dirname(这里)
软件目录 = os.path.join(包根, "软件")
if 软件目录 not in sys.path:
    sys.path.insert(0, 软件目录)

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
TS产物目录 = os.path.join(包根, "前端", "src", "生成")
# 早先误放在 `软件/web/`（含其 `生成/` 子目录）的冗余副本 —— `--检查` 会要求清掉
冗余位置 = (
    os.path.join(软件目录, "web", "契约.ts"),
    os.path.join(软件目录, "web", "风格.ts"),
    os.path.join(软件目录, "web", "主题.css"),
    os.path.join(软件目录, "web", "生成", "主题.css"),
)

# ---------------------------------------------------------------------------
# ① 契约 → TypeScript
# ---------------------------------------------------------------------------
_TS类型 = {
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


def 生成契约ts() -> str:
    import 契约

    数据 = 契约.转字典()
    行: list[str] = [
        "// ⚠️ 本文件由 `工具/生成前端资产.py` 生成，**不要手改**。",
        "// 来源：`软件/契约.py`（后端与前端之间唯一的通信契约）。",
        "// 改了契约就跑一次生成；`工具/验证/契约自检.py` 会检查它有没有过期。",
        "",
        f"export const 契约版本 = {数据['版本']};",
        f"export const 协议版本 = {契约.版本};",
        "",
    ]

    def 一段(标题: str, 主题们: list[dict], 前缀: str) -> None:
        行.append(f"// ---------------- {标题} ----------------")
        行.append(f"export type {前缀}主题名 =")
        for i, t in enumerate(主题们):
            行.append(f'  {"| " if i else "  "}"{t["名"]}"')
        行.append("  ;")
        行.append("")
        for t in 主题们:
            行.append(f"/** {t['摘要']} */")
            行.append(f"export interface {前缀}_{_安全(t['名'])} {{")
            if not t["字段"]:
                行.append("  [键: string]: unknown;")
            for f in t["字段"]:
                注解 = _TS类型.get(f["类型"], "unknown")
                说明 = f"  /** {f['说明']} */" if f["说明"] else ""
                if 说明:
                    行.append(说明)
                行.append(f"  {_安全字段(f['名'])}: {注解};")
            行.append("}")
            行.append("")
        # 主题名 → 负载类型的映射，前端分发时用它
        行.append(f"export interface {前缀}负载表 {{")
        for t in 主题们:
            行.append(f'  "{t["名"]}": {前缀}_{_安全(t["名"])};')
        行.append("}")
        行.append("")

    一段("下行：仿真 → 界面", 数据["下行"], "下行")
    一段("上行：界面 → 仿真（命令）", 数据["上行"], "上行")

    行.append("// ---------------- 元信息 ----------------")
    行.append("export interface 主题元 {")
    行.append("  名: string;")
    行.append("  类名: string;")
    行.append("  种类: string;")
    行.append("  摘要: string;")
    行.append("}")
    行.append("")
    行.append("export const 下行元: 主题元[] = [")
    for t in 数据["下行"]:
        行.append(f'  {{ 名: "{t["名"]}", 类名: "{t["类名"]}", 种类: "{t["种类"]}", '
                 f'摘要: {json.dumps(t["摘要"], ensure_ascii=False)} }},')
    行.append("];")
    行.append("")
    行.append("export const 上行元: 主题元[] = [")
    for t in 数据["上行"]:
        行.append(f'  {{ 名: "{t["名"]}", 类名: "{t["类名"]}", 种类: "{t["种类"]}", '
                 f'摘要: {json.dumps(t["摘要"], ensure_ascii=False)} }},')
    行.append("];")
    行.append("")
    return "\n".join(行)


def _安全(名: str) -> str:
    """把主题名变成合法的 TS 标识符（中文可以用，去掉点号等）。"""
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in 名)


def _安全字段(名: str) -> str:
    """字段名可能是中文（直接可用）；带引号风险的一律加引号。"""
    if 名.isidentifier():
        return 名
    return json.dumps(名, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ② 风格表 → CSS 变量
# ---------------------------------------------------------------------------
# ImGui 的颜色名 → 网页语义名（按优先级取第一个存在的键）
语义映射: dict[str, tuple[str, ...]] = {
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

曲线映射: dict[str, str] = {
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


def 取色(颜色表: dict, 键们: tuple[str, ...]) -> str | None:
    for k in 键们:
        if k in 颜色表:
            return str(颜色表[k])
    return None


def 生成主题css() -> str:
    表 = json.load(open(os.path.join(软件目录, "风格表.json"), encoding="utf-8"))
    风格们: dict = 表["风格"]
    行: list[str] = [
        "/* ⚠️ 本文件由 `工具/生成前端资产.py` 生成，**不要手改**。",
        " * 来源：`软件/风格表.json`（5 套风格，数据驱动换肤的唯一数据源）。",
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
    默认皮肤名 = 表.get("默认风格") or None
    for i, (名, 一套) in enumerate(风格们.items()):
        颜色 = 一套.get("颜色", {})
        样式 = 一套.get("样式", {})
        曲线 = 一套.get("曲线", {})
        imp = 曲线.get("implot", {}) if isinstance(曲线, dict) else {}
        调色板 = 曲线.get("调色板", []) if isinstance(曲线, dict) else []
        # ★ 选择器不能都挂 `:root`：那样 5 套风格会互相覆盖，只有最后一套生效
        #   （实测踩过）。默认那套挂 `:root`（没设 data-风格 时也能看），
        #   其余只挂属性选择器。
        # ★ 默认皮肤由 `风格表.json` 的 `默认风格` 字段决定，**不再靠列表排序**。
        #   靠排序的话，"想换个默认皮肤"就得去挪数据顺序 —— 那会连带改掉
        #   `风格表.ts` 的顺序，界面上皮肤列表也跟着跳，属于用错了杠杆。
        默认 = (名 == 默认皮肤名) or (默认皮肤名 is None and i == 0)
        选择器 = (':root, [data-风格="%s"]' % 名) if 默认 else ('[data-风格="%s"]' % 名)
        行.append(f"/* {名} · {一套.get('英文名','')} —— {一套.get('一句话','')} */")
        行.append(f"{选择器} {{")
        for 语义, 键们 in 语义映射.items():
            值 = 取色(颜色, 键们)
            if 值:
                行.append(f"  --{语义}: {值};")
        for 语义, 键 in 曲线映射.items():
            if 键 in imp:
                行.append(f"  --{语义}: {imp[键]};")
        if 调色板:
            行.append("  --palette: " + ", ".join(调色板) + ";")
            for i, c in enumerate(调色板[:8], 1):
                行.append(f"  --palette-{i}: {c};")
        # 样式：只搬网页有意义的几项
        圆 = 样式.get("FrameRounding")
        边 = 样式.get("WindowBorderSize")
        内 = 样式.get("WindowPadding")
        if isinstance(圆, (int, float)):
            行.append(f"  --radius: {float(圆):.1f}px;")
        if isinstance(边, (int, float)):
            行.append(f"  --border-w: {float(边):.1f}px;")
        if isinstance(内, list) and len(内) == 2:
            行.append(f"  --pad-x: {float(内[0]):.1f}px;")
            行.append(f"  --pad-y: {float(内[1]):.1f}px;")
        行.append(f"  --基底: {一套.get('基底主题','dark')};")
        行.append(f"  --字号倍率: {一套.get('自研面板字号', 1.0)};")
        行.append("}")
        # 深浅色提示：给浏览器原生控件（滚动条、输入框）用。
        # ★ 默认那套要连 `:root` 一起写，否则"没设 data-风格"时拿不到 color-scheme。
        色系 = "light" if 一套.get("基底主题") == "light" else "dark"
        行.append((f':root, [data-风格="{名}"]' if 默认 else f'[data-风格="{名}"]')
                 + f" {{ color-scheme: {色系}; }}")
        行.append("")
    return "\n".join(行)


# ---------------------------------------------------------------------------
# ③ 主题元信息 → TS（前端风格切换器要用）
# ---------------------------------------------------------------------------
def 生成主题ts() -> str:
    表 = json.load(open(os.path.join(软件目录, "风格表.json"), encoding="utf-8"))
    行 = [
        "// ⚠️ 本文件由 `工具/生成前端资产.py` 生成，**不要手改**。",
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
    for 名, 一套 in 表["风格"].items():
        行.append("  { 名: %s, 英文名: %s, 一句话: %s, 基底: %s },"
                 % (json.dumps(名, ensure_ascii=False),
                    json.dumps(一套.get("英文名", ""), ensure_ascii=False),
                    json.dumps(一套.get("一句话", ""), ensure_ascii=False),
                    json.dumps(一套.get("基底主题", "dark"), ensure_ascii=False)))
    行 += ["];", "",
          # ★ 同样认 `默认风格` 字段，不靠 风格列表[0]
          "export const 默认风格 = %s;" % json.dumps(
              表.get("默认风格") or 表["风格列表"][0], ensure_ascii=False),
          ""]
    return "\n".join(行)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
# 名 → (内容生成函数, 目标目录)。TS 走构建期目录，CSS 走运行时目录。
产物 = {
    "契约.ts": (生成契约ts, TS产物目录),
    "风格.ts": (生成主题ts, TS产物目录),
    "主题.css": (生成主题css, TS产物目录),
}


def 主() -> int:
    ap = argparse.ArgumentParser(description="把契约与风格表生成成前端资产")
    ap.add_argument("--检查", action="store_true",
                    help="只检查产物是否与当前来源一致（不一致退出码 1）")
    args = ap.parse_args()

    os.makedirs(TS产物目录, exist_ok=True)
    过期: list[str] = []
    for 名, (生成, 目录) in 产物.items():
        文本 = 生成()
        路径 = os.path.join(目录, 名)
        旧 = open(路径, encoding="utf-8").read() if os.path.exists(路径) else ""
        if 旧 == 文本:
            print(f"  ✓ {名} 与来源一致（{len(文本)} 字节）")
            continue
        if args.检查:
            过期.append(名)
            print(f"  ✗ {名} 与来源不一致（产物 {len(旧)} 字节 / 应为 {len(文本)} 字节）"
                  f" → {os.path.relpath(路径, 包根)}")
        else:
            open(路径, "w", encoding="utf-8").write(文本)
            print(f"  ✓ 已生成 {名}（{len(文本)} 字节）"
                  f" → {os.path.relpath(路径, 包根)}")

    # 清掉早先放在 `软件/web/` 里的冗余副本（见文件头"踩过的坑"）。
    for 旧路径 in 冗余位置:
        if os.path.exists(旧路径):
            if args.检查:
                过期.append(os.path.basename(旧路径) + "（遗留位置）")
                print(f"  ✗ {os.path.relpath(旧路径, 包根)} 是冗余副本，应删除（运行时用打包产物）")
            else:
                os.remove(旧路径)
                print(f"  ✓ 已清掉冗余副本 {os.path.relpath(旧路径, 包根)}")

    if args.检查 and 过期:
        print(f"\n  结论：{len(过期)} 个产物过期，跑一次 "
              f"`.venv/bin/python 工具/生成前端资产.py` 重新生成")
        return 1
    return 0


if __name__ == "__main__":
    print("=" * 72)
    print("  生成前端资产（契约 → TS，风格表 → CSS）")
    print("=" * 72)
    raise SystemExit(主())
