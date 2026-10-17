"""
重做第2页_分层图.py —— 只替换汇报 PPT 的第 2 页，其余页原样保留

为什么是"就地改"而不是重生成整份：
    用户已经在本地手动改过第 1 页（以及可能的其它页）。整份重生成会把他的修改
    覆盖掉 —— 那是最糟的意外。所以这里只动第 2 页的形状，别的页一个像素都不碰。

第 2 页要讲的事（用户要求：用**图**讲清"我们做的工作"与"官方"的关系）：
    我们不是在官方上面"打补丁"，而是**在官方层之上长了一层自己的东西**：
        ┌ 我们做的：自研面板 / 7 个数据通道 / 6 个算法 / 辨识 / 录制 ┐
        ├ 接缝：一个扩展点 + 我们自己的外壳                          ┤
        └ 官方底座：窗口 + 3D 渲染 + 物理引擎（C++，改不动也不该改） ┘
    图要能一眼看出：**官方的东西我们一行没改**，我们改的只有"怎么用它"。

用法：
    python3 工具/重做第2页_分层图.py                      # 就地改（先备份）
    python3 工具/重做第2页_分层图.py --文件 某.pptx --出 新.pptx
"""
from __future__ import annotations

import argparse
import os
import shutil

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

这里 = os.path.dirname(os.path.abspath(__file__))
包根 = os.path.dirname(这里)
字体 = "PingFang SC"

# 默认配色（与汇报 PPT 同一套）；运行时会先从现有页里**读出来**再覆盖，
# 这样用户如果改过主题色，新页也会跟着走。
默认 = {
    "底": RGBColor(0x0D, 0x14, 0x1C),
    "面板": RGBColor(0x12, 0x1A, 0x23),
    "描边": RGBColor(0x1E, 0x33, 0x50),
    "主文": RGBColor(0xDB, 0xE6, 0xF0),
    "次文": RGBColor(0x7B, 0x8F, 0xA3),
    "强调": RGBColor(0x4C, 0xC2, 0xFF),
    "好": RGBColor(0x3D, 0xDC, 0x97),
    "警": RGBColor(0xFF, 0xB4, 0x54),
    # 三层各用不同明度的底，让人一眼看出"上下两摞不同的东西"
    "我们底": RGBColor(0x14, 0x2A, 0x26),   # 偏绿：我们做的
    "接缝底": RGBColor(0x2A, 0x22, 0x12),   # 偏琥珀：接缝
    "官方底": RGBColor(0x0A, 0x0E, 0x13),   # 接近纯黑：官方（视觉上更"重"）
}
色 = dict(默认)


def _取色(sh, 属性: str):
    try:
        return getattr(sh, 属性).rgb
    except Exception:                                                 # noqa: BLE001
        return None


def 学习配色(页) -> None:
    """从现有页里反推配色，避免新页与旧页风格不一致。"""
    for sh in 页.shapes:
        if not str(sh.shape_type).startswith("AUTO"):
            continue
        填 = _取色(sh, "fill")
        if 填 is not None and sh.width > Inches(10) and sh.height > Inches(6):
            色["底"] = 填
        if 填 is not None and sh.width < Inches(0.2) and sh.height > Inches(6):
            色["强调"] = 填
    for sh in 页.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip():
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    try:
                        if r.font.color and r.font.color.rgb is not None:
                            色["主文"] = r.font.color.rgb
                            raise StopIteration
                    except StopIteration:
                        return
                    except Exception:                                 # noqa: BLE001
                        pass


def 框(页, 左, 上, 宽, 高, 填充=None, 线=None, 线宽=0.75, 圆角=0.05):
    sh = 页.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, 左, 上, 宽, 高)
    sh.fill.solid()
    sh.fill.fore_color.rgb = 填充 if 填充 is not None else 色["面板"]
    if 线 is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = 线
        sh.line.width = Pt(线宽)
    sh.shadow.inherit = False
    try:
        sh.adjustments[0] = 圆角
    except Exception:                                                 # noqa: BLE001
        pass
    return sh


def 字(页, 左, 上, 宽, 高, 行们, 对齐=PP_ALIGN.LEFT, 行距=1.05, 内边=0.03):
    tb = 页.shapes.add_textbox(左, 上, 宽, 高)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(内边)
    tf.margin_top = tf.margin_bottom = 0
    for i, (文本, 号, 颜色, 粗) in enumerate(行们):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = 对齐
        p.line_spacing = 行距
        p.space_after = Pt(2)
        r = p.add_run()
        r.text = 文本
        r.font.size = Pt(号)
        r.font.color.rgb = 颜色
        r.font.bold = 粗
        r.font.name = 字体
    return tb


def 箭头(页, 形状, 左, 上, 宽, 高, 填充=None):
    sh = 页.shapes.add_shape(形状, 左, 上, 宽, 高)
    sh.fill.solid()
    sh.fill.fore_color.rgb = 填充 if 填充 is not None else 色["次文"]
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def 造第2页(页, 页宽: Emu, 页高: Emu) -> None:
    # ---------- 标题区（与其他页同一版式）----------
    字(页, Inches(0.55), Inches(0.28), Inches(12.2), Inches(0.62), [
        ("① 原生界面的思路：站在官方肩膀上，只做它没有的", 25, 色["主文"], True),
    ])
    字(页, Inches(0.58), Inches(0.90), Inches(12.2), Inches(0.36), [
        ("我们不改官方的一行代码 —— 而是把它的能力当成底座，在上面长自己的一层。",
         12.5, 色["次文"], False),
    ])
    线 = 页.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(1.24),
                           Inches(12.20), Emu(9525))
    线.fill.solid()
    线.fill.fore_color.rgb = 色["描边"]
    线.line.fill.background()
    线.shadow.inherit = False

    # 说明：所有横向区块基准：左 0.55，宽 12.20
    左, 宽 = Inches(0.55), Inches(12.20)

    # =================================================================
    # ① 我们做的（顶层）
    # =================================================================
    字(页, 左, Inches(1.34), 宽, Inches(0.28), [
        ("我们做的这一层（全部由本项目编写，与官方解耦）", 11.5, 色["好"], True),
    ])
    顶列 = [
        ("9 个自研面板", "模型库 / 算法 / 参数 / 辨识 / 录制 / 监控…", "好"),
        ("6 个控制算法", "关节PD / 正弦 / 末端两点… 加算法 = 放一个 .py", "好"),
        ("7 个数据通道", "把状态、参数、辨识、录制整理成普通数据结构", "好"),
        ("参数辨识 + 录制", "从实测反推真参数；100 Hz 记录与回放", "好"),
    ]
    列宽 = Inches(2.95)
    for i, (名, 述, _) in enumerate(顶列):
        上 = Inches(1.66)
        框(页, 左 + i * (列宽 + Inches(0.13)), 上, 列宽, Inches(0.92),
           填充=色["我们底"], 线=色["好"], 线宽=1.0)
        字(页, 左 + i * (列宽 + Inches(0.13)) + Inches(0.10), 上 + Inches(0.07),
          列宽 - Inches(0.20), Inches(0.80), [
            (名, 11.5, 色["好"], True),
            (述, 9, 色["主文"], False),
        ], 行距=1.0)

    # =================================================================
    # ② 接缝（中间）：两个"接口"，这是唯一与官方打交道的地方
    # =================================================================
    字(页, 左, Inches(2.72), 宽, Inches(0.26), [
        ("接缝层：我们与官方只在这两处打交道", 11.5, 色["警"], True),
    ])
    接缝 = [
        ("一个扩展点（全项目只有 1 个文件直接调官方界面接口）",
         "所以将来要脱钩，改动范围就是那一个文件，不是整个项目。"),
        ("自己的外壳：算法、参数、数据都在我们这边；窗口与渲染借官方的",
         "省下最贵的两块（渲染器与窗口层），把力气花在官方没做的部分。"),
    ]
    for i, (主, 副) in enumerate(接缝):
        上 = Inches(3.02)
        框(页, 左 + i * Inches(6.13), 上, Inches(6.07), Inches(0.92),
           填充=色["接缝底"], 线=色["警"], 线宽=1.0)
        字(页, 左 + i * Inches(6.13) + Inches(0.12), 上 + Inches(0.08),
          Inches(5.83), Inches(0.78), [
            ("● " + 主, 10.5, 色["警"], True),
            (副, 9.5, 色["主文"], False),
        ], 行距=1.0)

    # ★ 原来在接缝层与官方层之间放了一个左右箭头，但那两层的上下关系是"叠放"不是"并列"，
    #   一个横向箭头反而误导（看着像并列的两块）。改成留白 + 下方那句"一行没改"来说明关系。

    # =================================================================
    # ③ 官方底座（底层）：视觉上要"重"、要"稳"
    # =================================================================
    底上 = Inches(4.36)
    框(页, 左, 底上, 宽, Inches(1.22), 填充=色["官方底"],
       线=色["次文"], 线宽=1.25, 圆角=0.04)
    字(页, 左 + Inches(0.16), 底上 + Inches(0.08), Inches(5.0), Inches(0.30), [
        ("官方底座：MuJoCo Studio（C++，编译进 .so）", 12, 色["次文"], True),
    ])
    官方 = [("窗口与面板宿主", "官方把窗口、停靠、19 个面板都做好了"),
            ("3D 渲染（Filament）", "真材质、真阴影，比网页里画的强"),
            ("物理引擎（MuJoCo 核心）", "动力学解算的真正发动机")]
    列宽2 = Inches(3.86)
    for i, (名, 述) in enumerate(官方):
        字(页, 左 + Inches(0.18) + i * (列宽2 + Inches(0.10)), 底上 + Inches(0.42),
          列宽2, Inches(0.72), [
            ("· " + 名, 10.5, 色["主文"], True),
            (述, 9, 色["次文"], False),
        ], 行距=1.0)

    # 明确写"没改"
    字(页, 左 + 宽 - Inches(2.9), 底上 + Inches(0.06), Inches(2.72), Inches(0.30), [
        ("这一层：一行没改 ✕", 10, 色["警"], True),
    ], 对齐=PP_ALIGN.RIGHT)

    # =================================================================
    # ④ 右侧注记：为什么选这条路（三个被否掉的选项，压成一行小卡）
    # =================================================================
    上 = Inches(5.74)
    字(页, 左, 上, 宽, Inches(0.28), [
        ("为什么是这条路（另外两条都否掉了）", 11.5, 色["强调"], True),
    ])
    否 = [
        ("✕ 直接用官方软件", "省事，但加自己的算法要改它的 C++ —— 做不到「后续能自己改」。"),
        ("✕ fork 官方源码", "改得动，但上游约三十天一个版本，每次升级都要重新合并。"),
        ("✔ 自己的外壳 + 官方底座", "算法与数据全在我们这边；窗口与渲染借官方的。"),
    ]
    for i, (名, 述) in enumerate(否):
        成功 = 名.startswith("✔")
        框(页, 左 + i * Inches(4.11), 上 + Inches(0.30), Inches(3.95), Inches(0.74),
           填充=RGBColor(0x14, 0x24, 0x2C) if 成功 else 色["面板"],
           线=色["好"] if 成功 else 色["描边"])
        字(页, 左 + i * Inches(4.11) + Inches(0.10), 上 + Inches(0.34),
          Inches(3.75), Inches(0.66), [
            (名, 10.5, 色["好"] if 成功 else 色["主文"], True),
            (述, 9, 色["主文"], False),
        ], 行距=1.0)

    # 页脚一句话（钉住这张图要传达的核心）
    字(页, 左, Inches(6.92), 宽, Inches(0.30), [
        ("一句话：图里最下面那块最深的是官方做的，上面绿色的是我们做的；"
         "我们改的只有「怎么用它」，不是「它本身」。", 10.5, 色["次文"], False),
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description="就地替换汇报 PPT 的第 2 页为分层图")
    ap.add_argument("--文件", default=os.path.join(
        包根, "报告", "07_历史快照", "交付物", "驭臂_工作汇报.pptx"))
    ap.add_argument("--出", default=None, help="输出路径（默认就地覆盖，先备份）")
    ap.add_argument("--页号", type=int, default=2)
    ap.add_argument("--无备份", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.文件):
        print(f"✗ 找不到：{a.文件}")
        return 1
    if a.出 is None and not a.无备份:
        备份 = a.文件.replace(".pptx", ".替换前备份.pptx")
        shutil.copyfile(a.文件, 备份)
        print(f"  ✓ 已备份：{os.path.basename(备份)}")

    prs = Presentation(a.文件)
    页 = prs.slides[a.页号 - 1]
    学习配色(页)
    print(f"  沿用配色：底={色['底']} 主文={色['主文']} 强调={色['强调']}")

    # 删掉这一页**除背景之外**的所有形状
    保留 = []
    for sh in list(页.shapes):
        是背景 = (str(sh.shape_type).startswith("AUTO")
                and sh.width > prs.slide_width * 0.9 and sh.height > prs.slide_height * 0.9)
        if 是背景:
            保留.append(sh)
            continue
        sh._element.getparent().remove(sh._element)
    print(f"  清掉旧形状 {len(保留) and ''}{a.页号} 页原有形状，保留背景 {len(保留)} 个")

    # 左侧品牌竖条（其它页都有，重建一个）
    条 = 页.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.07), prs.slide_height)
    条.fill.solid()
    条.fill.fore_color.rgb = 色["强调"]
    条.line.fill.background()
    条.shadow.inherit = False

    造第2页(页, prs.slide_width, prs.slide_height)

    出 = a.出 or a.文件
    prs.save(出)
    print(f"  ✓ 已写入：{出}")
    print(f"  第 {a.页号} 页现在有 {len(prs.slides[a.页号-1].shapes)} 个形状")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
