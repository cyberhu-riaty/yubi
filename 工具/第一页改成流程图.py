"""
第一页改成流程图.py —— 第 1 页从"两张大字卡"改成"四步流程图"

用户的要求：第一页字太多，主要靠图形介绍流程。
现在的第 1 页有 442 字（两张大卡片各写了一大段"思路/代价"），读起来像文档。

改成：一条流程 —— 借官方底座 → 长出核 → 撞墙 → 换壳
     每步一个方框，框里只有标题 + 2~3 个短词，框间用箭头连起来，
     框下用一行状态（✔ 已交付 / ✕ 天花板 / ◐ 进行中）说明这一步的结果。

★ 只改第 1 页，其它页一个像素都不碰（用户已多次在本地调整）。

用法：
    python3 工具/第一页改成流程图.py            # 就地改，先备份
"""
from __future__ import annotations

import argparse
import os
import shutil

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

这里 = os.path.dirname(os.path.abspath(__file__))
包根 = os.path.dirname(这里)
字体 = "PingFang SC"

# 浅色极简风（与全篇一致）
色 = {
    "底": RGBColor(0xFF, 0xFF, 0xFF),
    "主文": RGBColor(0x1A, 0x1D, 0x23),
    "次文": RGBColor(0x6B, 0x74, 0x80),
    "描边": RGBColor(0xDD, 0xE3, 0xEA),
    "强调": RGBColor(0x16, 0x68, 0xC4),      # 进行中
    "好": RGBColor(0x0E, 0x8A, 0x5F),        # 已交付
    "警": RGBColor(0xB2, 0x6A, 0x00),        # 撞墙
    "灰": RGBColor(0x8A, 0x94, 0xA0),        # 起步
    "好底": RGBColor(0xEE, 0xF9, 0xF4),
    "警底": RGBColor(0xFF, 0xF7, 0xE8),
    "蓝底": RGBColor(0xEF, 0xF5, 0xFD),
    "灰底": RGBColor(0xF7, 0xF8, 0xFA),
}


def 框(页, 左, 上, 宽, 高, 填充, 线, 线宽=0.9, 圆角=0.06):
    sh = 页.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, 左, 上, 宽, 高)
    sh.fill.solid()
    sh.fill.fore_color.rgb = 填充
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


def 字(页, 左, 上, 宽, 高, 行们, 对齐=PP_ALIGN.LEFT, 行距=1.15, 居中=False):
    tb = 页.shapes.add_textbox(左, 上, 宽, 高)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE if 居中 else MSO_ANCHOR.TOP
    for i, 条 in enumerate(行们):
        文本, 号, 颜色, 粗 = 条[0], 条[1], 条[2], 条[3]
        段后 = 条[4] if len(条) > 4 else 3
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = 对齐
        p.line_spacing = 行距
        p.space_after = Pt(段后)
        r = p.add_run()
        r.text = 文本
        r.font.size = Pt(号)
        r.font.color.rgb = 颜色
        r.font.bold = 粗
        r.font.name = 字体
    return tb


def 箭头(页, 左, 上, 宽, 高):
    sh = 页.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, 左, 上, 宽, 高)
    sh.fill.solid()
    sh.fill.fore_color.rgb = 色["灰"]
    sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def 重做第1页(页) -> None:
    # 只保留背景
    留 = set()
    for sh in 页.shapes:
        if Emu(sh.width).inches > 12.9 and Emu(sh.height).inches > 7.0:
            留.add(sh._element)
    for sh in list(页.shapes):
        if sh._element not in 留:
            sh._element.getparent().remove(sh._element)

    # ---------------- 标题 ----------------
    字(页, Inches(0.72), Inches(0.46), Inches(11.90), Inches(0.62), [
        ("驭臂 · 机器人仿真与控制工作台", 30, 色["主文"], True),
    ])
    字(页, Inches(0.74), Inches(1.10), Inches(11.90), Inches(0.36), [
        ("让机械臂在电脑里真跑起来的工具 —— 两条路走过来的", 13.5, 色["次文"], False),
    ])

    # ---------------- 四步流程 ----------------
    步们 = [
        ("①", "借官方工作台", "起步", 色["灰"], 色["灰底"], None,
         ["窗口 / 渲染 / 物理", "都用官方的"]),
        ("②", "长出「核」", "已交付", 色["好"], 色["好底"], "✔",
         ["真物理 · 控制算法", "参数辨识 · 数据录制"]),
        ("③", "撞墙", "天花板", 色["警"], 色["警底"], "✕",
         ["界面改不动", "只有 macOS"]),
        ("④", "换壳", "进行中", 色["强调"], 色["蓝底"], "◐",
         ["Web 界面", "核一行不动"]),
    ]

    卡宽 = Inches(2.80)
    卡高 = Inches(3.30)
    起左 = Inches(0.57)
    缝 = Inches(0.33)
    上 = Inches(1.88)

    for i, (号, 名, 状态, 线色, 底, 徽, 条目) in enumerate(步们):
        左 = 起左 + i * (卡宽 + 缝)
        框(页, 左, 上, 卡宽, 卡高, 填充=底, 线=线色, 线宽=1.0)

        # 步骤号（大、淡）
        字(页, 左 + Inches(0.16), 上 + Inches(0.14), Inches(0.60), Inches(0.50), [
            (号, 22, 线色, True),
        ])
        # 步骤名
        字(页, 左 + Inches(0.16), 上 + Inches(0.74), 卡宽 - Inches(0.32), Inches(0.44), [
            (名, 17, 色["主文"], True),
        ])
        # 短条目
        行们 = [("· " + t, 12, 色["次文"], False, 6) for t in 条目]
        字(页, 左 + Inches(0.16), 上 + Inches(1.30), 卡宽 - Inches(0.32), Inches(1.00),
          行们, 行距=1.2)
        # 状态徽（框内底部）
        if 徽:
            字(页, 左 + Inches(0.16), 上 + 卡高 - Inches(0.52), 卡宽 - Inches(0.32), Inches(0.36), [
                (f"{徽} {状态}", 13, 线色, True),
            ])
        else:
            字(页, 左 + Inches(0.16), 上 + 卡高 - Inches(0.52), 卡宽 - Inches(0.32), Inches(0.36), [
                (状态, 12, 色["次文"], False),
            ])

        # 箭头（最后一个不放）
        if i < 3:
            箭头(页, 左 + 卡宽 + Inches(0.06), 上 + 卡高 / 2 - Inches(0.13),
               Inches(0.21), Inches(0.26))

    # ---------------- 底部一行：护城河 ----------------
    字(页, Inches(0.72), Inches(5.62), Inches(11.90), Inches(0.34), [
        ("两条路都保留的东西：", 12, 色["次文"], False),
    ])
    河 = ["真物理（不是回放）", "参数辨识 1.47%", "录制 100 Hz", "算法可插拔"]
    卡2宽 = Inches(2.80)
    for i, 项 in enumerate(河):
        左 = Inches(0.72) + i * (卡2宽 + Inches(0.30))
        框(页, 左, Inches(6.00), 卡2宽, Inches(0.60),
           填充=色["灰底"], 线=色["描边"], 线宽=0.75)
        字(页, 左, Inches(6.00), 卡2宽, Inches(0.60), [
            (项, 12.5, 色["主文"], False),
        ], 居中=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--文件", default=os.path.join(
        包根, "报告", "07_历史快照", "交付物", "驭臂_工作汇报.pptx"))
    ap.add_argument("--出", default=None)
    ap.add_argument("--无备份", action="store_true")
    a = ap.parse_args()

    if a.出 is None and not a.无备份:
        备份 = a.文件.replace(".pptx", ".改首页前备份.pptx")
        shutil.copyfile(a.文件, 备份)
        print(f"  ✓ 已备份：{os.path.basename(备份)}")

    prs = Presentation(a.文件)

    # 先记下其它页的文字，改完对比，确保没碰
    def 快照(s):
        return [sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
    其它页 = {i: 快照(prs.slides[i]) for i in range(1, 5)}

    print("  重做第 1 页（四步流程图）…")
    重做第1页(prs.slides[0])

    出 = a.出 or a.文件
    prs.save(出)

    检查 = Presentation(出)
    for i in range(1, 5):
        if 快照(检查.slides[i]) != 其它页[i]:
            print(f"  ✗ 第 {i+1} 页被意外改动！")
            return 2
    print("  ✓ 第 2~5 页均未改动")

    总 = sum(len(sh.text_frame.text.replace("\n", ""))
             for sh in 检查.slides[0].shapes if sh.has_text_frame)
    print(f"  ✓ 已写入：{出}")
    print(f"  第 1 页现在 {len(检查.slides[0].shapes)} 个形状、{总} 字")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
