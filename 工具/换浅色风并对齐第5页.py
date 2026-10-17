"""
换浅色风并对齐第5页.py —— 两件事：

① 全篇换「浅色极简风」配色
   深底 → 白底；深面板 → 浅灰面板；亮色强调 → 深色强调（对比度反过来）。
   ★ 只换颜色，不动任何文字、位置、字号 —— 版式是用户排过好几轮的，别碰。

② 第 5 页修两处"让人莫名其妙"的地方
   · P3 / P4 / P5 这三个标签前面从没出现过 → 换成说人话的阶段名
   · 底部那个蓝色解释框，讲的内容第 4 页已经说过 → 删掉

用法：
    python3 工具/换浅色风并对齐第5页.py            # 就地改，先备份
"""
from __future__ import annotations

import argparse
import os
import shutil

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

这里 = os.path.dirname(os.path.abspath(__file__))
包根 = os.path.dirname(这里)
字体 = "PingFang SC"

# ---------------------------------------------------------------------------
# 深 → 浅 的映射表
# ---------------------------------------------------------------------------
# 语义             深版        浅版（新）      说明
映射 = {
    # 底色与面板
    "0D141C": "FFFFFF",     # 页面底：近黑 → 纯白
    "121A23": "F7F8FA",     # 卡片/面板：深蓝灰 → 极浅灰
    "141A22": "F2F5F9",     # 强调面板
    "1E3350": "DDE3EA",     # 细分隔线/描边
    "1A1F27": "F5F6F8",     # 旧路线卡底
    "122824": "EEF9F4",     # 新路线卡底（偏绿）
    "241E10": "FFF7E8",     # 官方 Python 层卡底（偏琥珀）
    "070A0E": "F0F2F5",     # 官方 C++ 层卡底（最深 → 浅灰，视觉仍"最重")
    # 文字与强调
    "DBE6F0": "1A1D23",     # 主文：浅蓝白 → 近黑
    "7B8FA3": "6B7480",     # 次文：蓝灰 → 中性灰
    "4CC2FF": "1668C4",     # 强调蓝：亮蓝 → 深蓝（白底上够对比）
    "3DDC97": "0E8A5F",     # 好/绿：荧光绿 → 深绿
    "FFB454": "B26A00",     # 警/琥珀：亮橙 → 深琥珀
    "5A6B7C": "8A94A0",     # 灰线
    "2A3A4A": "C9D2DB",
}


def 转色(c) -> RGBColor:
    """把一个颜色按映射表换成浅色版；不在表里就原样返回。"""
    if c is None:
        return None
    try:
        键 = str(c)
    except Exception:                                                 # noqa: BLE001
        return c
    return RGBColor.from_string(映射.get(键.upper(), 键))


def 换皮下(prs) -> tuple[int, int, int]:
    """把整份 PPT 的填充/描边/文字色都换成浅色版。返回 (填充数, 描边数, 文字数)。"""
    改填 = 改线 = 改字 = 0
    for s in prs.slides:
        for sh in s.shapes:
            f, l, z = _换一个(sh)
            改填 += f
            改线 += l
            改字 += z
    return 改填, 改线, 改字


def _换一个(sh) -> tuple[int, int, int]:
    """递归：组合形状要钻进去换（★ 踩过的坑：只换顶层，组合里那三块深色卡片
    在白底上就成了黑块 —— 第 2 页的三层图正好是组合的）。"""
    改填 = 改线 = 改字 = 0
    if sh.shape_type == 6:                                       # GROUP
        for sub in sh.shapes:
            f, l, z = _换一个(sub)
            改填 += f
            改线 += l
            改字 += z
    else:
        if str(sh.shape_type).startswith("AUTO"):
            try:
                if sh.fill.type is not None and sh.fill.fore_color.rgb is not None:
                    新 = 转色(sh.fill.fore_color.rgb)
                    if str(新) != str(sh.fill.fore_color.rgb):
                        sh.fill.fore_color.rgb = 新
                        改填 += 1
            except Exception:                                     # noqa: BLE001
                pass
            try:
                if sh.line.color and sh.line.color.rgb is not None:
                    新 = 转色(sh.line.color.rgb)
                    if str(新) != str(sh.line.color.rgb):
                        sh.line.color.rgb = 新
                        改线 += 1
            except Exception:                                     # noqa: BLE001
                pass
        if sh.has_text_frame:
            for para in sh.text_frame.paragraphs:
                for r in para.runs:
                    if _换文字色(r):
                        r.font.color.rgb = _换文字色(r)
                        改字 += 1
    return 改填, 改线, 改字


def _换形状(sh) -> int:
    """递归换文字颜色（组合形状里的子形状也要管）。"""
    改 = 0
    if sh.shape_type == 6:                       # GROUP
        for sub in sh.shapes:
            改 += _换形状(sub)
        return 改
    if sh.has_text_frame:
        for para in sh.text_frame.paragraphs:
            for r in para.runs:
                换 = _换文字色(r)
                if 换:
                    改 += 1
                    r.font.color.rgb = 换
    return 改


def _换文字色(run):
    try:
        if run.font.color and run.font.color.rgb is not None:
            新 = 转色(run.font.color.rgb)
            if str(新) != str(run.font.color.rgb):
                return 新
    except Exception:                                                 # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# 第 5 页：改阶段名、删蓝框、收掉重复的时间线
# ---------------------------------------------------------------------------
def 修第5页(页) -> None:
    # ---- ① P3/P4/P5 → 说人话的阶段名 ----
    #   原来这三个编号从没在别处出现过，读者不知道指什么。
    #   改成"三步"的说法，并把时间口径并进标题，一眼能看懂先后。
    改名 = {
        "P3　拿回窗口": "第一步　拿回窗口",
        "P4　补能力": "第二步　补上能力",
        "P5　打包发布": "第三步　打包发布",
        "P3": "第一步",
        "P4": "第二步",
        "P5": "第三步",
    }
    for sh in 页.shapes:
        if not sh.has_text_frame:
            continue
        原 = sh.text_frame.text.strip()
        if 原 in 改名:
            for para in sh.text_frame.paragraphs:
                for r in para.runs:
                    r.text = 改名[原]
            # 只改第一个 run，其余清掉，避免残留
            for para in sh.text_frame.paragraphs:
                for i, r in enumerate(para.runs):
                    if i > 0:
                        r.text = ""

    # ---- ② 删掉底部那个蓝色解释框（第 4 页已经说过，重复）----
    删 = []
    for sh in 页.shapes:
        W, H = Emu(sh.width).inches, Emu(sh.height).inches
        T = Emu(sh.top).inches
        if str(sh.shape_type).startswith("AUTO") and W > 10 and H > 1.0 and T > 5.0:
            删.append(sh)
        elif sh.has_text_frame and T > 5.5 and sh.text_frame.text.strip().startswith("为什么 3D"):
            删.append(sh)
    for sh in 删:
        sh._element.getparent().remove(sh._element)
    print(f"    删掉底部蓝框 {len(删)} 个形状")

    # ---- ③ 时间线区：原来"现在/接下来/最后"重复了两遍（卡片里一次、线上又一次）----
    #   卡片里已经有时间标签了，所以把下方那条线保留（它是"进度感"），但去掉重复的文字。
    for sh in list(页.shapes):
        if not sh.has_text_frame:
            continue
        T = Emu(sh.top).inches
        if T > 4.8 and sh.text_frame.text.strip() in ("现在", "接下来", "最后"):
            sh._element.getparent().remove(sh._element)

    # ---- ④ 卡片略加高（删了蓝框，下方有余量）----
    #   ★ 踩过的坑：第一版把卡片拉到 5.30in（y 到 6.32），把下方时间线
    #     （圆点在 y=4.96）**整个盖住**了 —— 看起来像时间线"不见了"。
    #     卡片只能长到时间线上方，4.10in 刚好（y 到 5.12 … 仍然压到圆点，
    #     所以真实上限是 3.85in）。
    for sh in 页.shapes:
        W, H = Emu(sh.width).inches, Emu(sh.height).inches
        T = Emu(sh.top).inches
        if str(sh.shape_type).startswith("AUTO") and 2.5 < W < 4.5 and H > 3.0 and T < 1.5:
            sh.height = Inches(3.85)          # y 1.02 → 4.87，时间线圆点 4.96 在其下
    for sh in 页.shapes:
        if sh.has_text_frame:
            T = Emu(sh.top).inches
            W = Emu(sh.width).inches
            if 1.8 < T < 2.0 and 3.0 < W < 4.0:
                sh.height = Inches(2.80)

    # ---- ④b 时间线下移，与卡片底留出呼吸（原来只差 0.09in，挤在一起）----
    for sh in 页.shapes:
        T = Emu(sh.top).inches
        W, H = Emu(sh.width).inches, Emu(sh.height).inches
        if abs(T - 4.96) < 0.05 and abs(W - 0.20) < 0.02:          # 三个圆点
            sh.top = Inches(5.42)
        elif abs(T - 5.04) < 0.05 and W > 10:                        # 横线
            sh.top = Inches(5.50)

    # ---- ⑤ 底部一句"收口"（一句话，不是解释框）----
    字(页, Inches(0.55), Inches(6.62), Inches(12.20), Inches(0.42), [
        ("顺序不能反：3D 视口要靠「自己的窗口」才有地方放，所以这两件必须一起做。",
         12.5, RGBColor(0x6B, 0x74, 0x80), False),
    ], 居中=True)


def 字(页, 左, 上, 宽, 高, 行们, 对齐=None, 行距=1.15, 居中=False):
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    tb = 页.shapes.add_textbox(左, 上, 宽, 高)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.04)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE if 居中 else MSO_ANCHOR.TOP
    for i, (文本, 号, 颜色, 粗) in enumerate(行们):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = 对齐 or (PP_ALIGN.CENTER if 居中 else PP_ALIGN.LEFT)
        p.line_spacing = 行距
        p.space_after = Pt(2)
        r = p.add_run()
        r.text = 文本
        r.font.size = Pt(号)
        r.font.color.rgb = 颜色
        r.font.bold = 粗
        r.font.name = 字体
    return tb


def 做极简(prs) -> None:
    """极简风的三条减法：

    ① 去掉每页左侧那条彩色竖条 —— 深色版它是"品牌色点缀"，浅色版它变成
       一道突兀的深蓝边，反而不极简。
    ② 卡片描边收细（1.2~1.5pt → 0.75pt）：浅色下粗边显"重"。
    ③ 第 5 页删掉时间线的三个圆点 —— "第一步/第二步/第三步"已经表达了顺序，
       圆点是纯装饰。
    """
    去 = 0
    for s in prs.slides:
        for sh in list(s.shapes):
            W, H = Emu(sh.width).inches, Emu(sh.height).inches
            if str(sh.shape_type).startswith("AUTO") and W < 0.2 and H > 7.0:
                sh._element.getparent().remove(sh._element)      # 左侧竖条
                去 += 1
    print(f"    去掉左侧竖条 {去} 条")

    细 = 0
    for s in prs.slides:
        for sh in s.shapes:
            if not str(sh.shape_type).startswith("AUTO"):
                continue
            try:
                if sh.line.width and sh.line.width.pt > 0.8:
                    sh.line.width = Pt(0.75)
                    细 += 1
            except Exception:                                        # noqa: BLE001
                pass
    print(f"    描边收细 {细} 处")

    # 第 5 页的时间线圆点与横线：圆点删、横线留（一条细线是"极简"里可以接受的引导线）
    点 = 0
    for sh in list(prs.slides[4].shapes):
        W, H = Emu(sh.width).inches, Emu(sh.height).inches
        T = Emu(sh.top).inches
        if str(sh.shape_type).startswith("AUTO") and abs(W - 0.20) < 0.03 and abs(H - 0.20) < 0.03 and T > 4.5:
            sh._element.getparent().remove(sh._element)
            点 += 1
    print(f"    删掉时间线圆点 {点} 个")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--文件", default=os.path.join(
        包根, "报告", "07_历史快照", "交付物", "驭臂_工作汇报.pptx"))
    ap.add_argument("--出", default=None)
    ap.add_argument("--无备份", action="store_true")
    a = ap.parse_args()

    if a.出 is None and not a.无备份:
        备份 = a.文件.replace(".pptx", ".换浅色前备份.pptx")
        shutil.copyfile(a.文件, 备份)
        print(f"  ✓ 已备份：{os.path.basename(备份)}")

    prs = Presentation(a.文件)

    print("  ① 换浅色配色（只改颜色，不动位置字号）…")
    填, 线, 字n = 换皮下(prs)
    print(f"    填充 {填} 处、边框 {线} 处、文字 {字n} 处")

    print("  ② 做极简（去竖条 / 收细描边）…")
    做极简(prs)

    print("  ③ 修第 5 页…")
    修第5页(prs.slides[4])

    出 = a.出 or a.文件
    prs.save(出)
    print(f"  ✓ 已写入：{出}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
