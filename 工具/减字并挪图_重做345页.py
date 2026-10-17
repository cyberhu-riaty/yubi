"""
减字并挪图_重做345页.py —— 第 3/4/5 页大幅减字；LoongEnv 截图从第 3 页挪到第 4 页（路线②）

用户的三条要求：
    ① LoongEnv 截图放错页了 —— 原意是放在"路线②"那页（第 4 页）
    ② 第 3、4、5 页字还是太多
    ③ 尽量用图形方框

减字的做法（不是删信息，是**换表达**）：
    第 3 页：图占主体，右侧只留 4 个短词（8 字以内）
    第 4 页：一圈"区别"（左旧右新，各 4 行短词）＋ 截图 ＋ 两句话
    第 5 页：三张阶段卡（各 3 行短词）＋ 一条时间线

用法：
    python3 工具/减字并挪图_重做345页.py            # 就地改，先备份
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
图目录 = os.path.join(包根, "报告", "07_历史快照", "交付物", "图")
字体 = "PingFang SC"

色 = {
    "底": RGBColor(0x0D, 0x14, 0x1C),
    "面板": RGBColor(0x12, 0x1A, 0x23),
    "描边": RGBColor(0x1E, 0x33, 0x50),
    "主文": RGBColor(0xDB, 0xE6, 0xF0),
    "次文": RGBColor(0x7B, 0x8F, 0xA3),
    "强调": RGBColor(0x4C, 0xC2, 0xFF),
    "好": RGBColor(0x3D, 0xDC, 0x97),
    "警": RGBColor(0xFF, 0xB4, 0x54),
    "旧": RGBColor(0x1A, 0x1F, 0x27),
    "旧线": RGBColor(0x5A, 0x6B, 0x7C),
    "新": RGBColor(0x12, 0x28, 0x24),
    "深": RGBColor(0x14, 0x1A, 0x22),
}


def _色(sh, 属性):
    try:
        return getattr(sh, 属性).rgb
    except Exception:                                                 # noqa: BLE001
        return None


def 学习配色(页):
    for sh in 页.shapes:
        if not str(sh.shape_type).startswith("AUTO"):
            continue
        填 = _色(sh, "fill")
        if 填 is not None and sh.width > Inches(10) and sh.height > Inches(6):
            色["底"] = 填
        if 填 is not None and sh.width < Inches(0.2) and sh.height > Inches(6):
            色["强调"] = 填


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


def 字(页, 左, 上, 宽, 高, 行们, 对齐=PP_ALIGN.LEFT, 行距=1.15,
      居中=False):
    tb = 页.shapes.add_textbox(左, 上, 宽, 高)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.04)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE if 居中 else MSO_ANCHOR.TOP
    for i, 条 in enumerate(行们):
        文本, 号, 颜色, 粗 = 条[0], 条[1], 条[2], 条[3]
        段后 = 条[4] if len(条) > 4 else 4
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


def 清掉(页, 保留XML: set) -> None:
    for sh in list(页.shapes):
        if sh._element not in 保留XML:
            sh._element.getparent().remove(sh._element)


def 保留要用的(页, 留图=False, 留标题=False, 留右栏=False):
    """留下：背景、左竖条、细分隔线、（可选）图片、（可选）标题、（可选）右栏色块。"""
    留 = set()
    for sh in 页.shapes:
        W, H = Emu(sh.width).inches, Emu(sh.height).inches
        T = Emu(sh.top).inches
        if W > 12.9 and H > 7.0:
            留.add(sh._element); continue                    # 背景
        if W < 0.2 and H > 7.0:
            留.add(sh._element); continue                    # 左竖条
        if abs(H - 0.01) < 0.02 and W > 12:
            留.add(sh._element); continue                    # 细分隔线
        if 留图 and sh.shape_type == 13:
            留.add(sh._element); continue
        if 留标题 and T < 0.80 and sh.has_text_frame and sh.text_frame.text.strip():
            留.add(sh._element); continue
        if 留右栏 and str(sh.shape_type).startswith("AUTO") and W > 3 and 0.5 < T < 1.2:
            留.add(sh._element); continue
    return 留


# ===========================================================================
# 第 3 页：图为主 + 右侧 4 个短词
# ===========================================================================
def 重做第3页(页) -> None:
    留 = 保留要用的(页, 留图=True, 留右栏=True)
    清掉(页, 留)

    # 右侧栏：四个**方框**（不是一行行字）—— 用户要"图形方框"
    项 = [("双击即开", "不用装环境、不联网", 色["好"]),
          ("6 台模型", "点一下就换", 色["强调"]),
          ("双语 + 5 皮肤", "中英文随意切", 色["强调"]),
          ("改参不重启", "换模型/算法/参数", 色["强调"])]
    for i, (大, 小, 线色) in enumerate(项):
        上 = Inches(1.06) + i * Inches(1.16)
        框(页, Inches(9.72), 上, Inches(3.52), Inches(1.02),
           填充=色["深"], 线=线色, 线宽=1.2)
        字(页, Inches(9.86), 上 + Inches(0.10), Inches(3.24), Inches(0.82), [
            (大, 16, 线色, True, 2),
            (小, 10.5, 色["主文"], False, 0),
        ], 行距=1.1)

    # 底部一句定位
    字(页, Inches(9.72), Inches(5.86), Inches(3.52), Inches(0.60), [
        ("这就是已经交付的那台工具", 11.5, 色["次文"], False),
    ], 居中=True, 行距=1.15)


# ===========================================================================
# 第 4 页：路线②（区别 + 技术 + 缺口）＋ LoongEnv 截图
# ===========================================================================
def 重做第4页(页) -> None:
    留 = 保留要用的(页, 留标题=True)
    清掉(页, 留)

    字(页, Inches(2.10), Inches(0.36), Inches(10.60), Inches(0.34), [
        ("跟路线①的区别、用了什么技术、还缺什么", 13, 色["次文"], False),
    ])

    # ---- 左栏：一圈"区别"（旧 → 新），每行只有短词 ----
    左边框 = Inches(0.55)
    宽框 = Inches(6.05)

    框(页, 左边框, Inches(0.96), 宽框, Inches(2.60), 填充=色["旧"], 线=色["旧线"], 线宽=1.2)
    字(页, 左边框 + Inches(0.14), Inches(1.04), 宽框 - Inches(0.28), Inches(0.30), [
        ("路线①（旧）", 12.5, 色["旧线"], True),
    ])
    字(页, 左边框 + Inches(0.14), Inches(1.38), 宽框 - Inches(0.28), Inches(2.10), [
        ("界面　官方 ImGui（C++）", 13, 色["主文"], False, 6),
        ("语言　Python + C++", 13, 色["主文"], False, 6),
        ("进程　单进程，界面与仿真同屋", 13, 色["主文"], False, 6),
        ("平台　只有 macOS", 13, 色["主文"], False, 6),
        ("短板　界面改不动，只能绕", 13, 色["警"], False, 6),
    ], 行距=1.15)

    框(页, 左边框, Inches(3.66), 宽框, Inches(2.60), 填充=色["新"], 线=色["好"], 线宽=1.4)
    字(页, 左边框 + Inches(0.14), Inches(3.74), 宽框 - Inches(0.28), Inches(0.30), [
        ("路线②（新）", 12.5, 色["好"], True),
    ])
    字(页, 左边框 + Inches(0.14), Inches(4.08), 宽框 - Inches(0.28), Inches(2.10), [
        ("界面　Web（React + Tailwind）", 13, 色["主文"], False, 6),
        ("语言　Python + TypeScript", 13, 色["主文"], False, 6),
        ("通信　WebSocket + JSON 契约", 13, 色["主文"], False, 6),
        ("进程　仿真独立跑，界面是客户", 13, 色["主文"], False, 6),
        ("优势　界面随便改，可扩 Windows", 13, 色["好"], False, 6),
    ], 行距=1.15)

    # ---- 右栏：LoongEnv 截图（路线② 的参照）＋ 缺口 ----
    右左 = Inches(6.85)
    右宽 = Inches(5.93)

    框(页, 右左, Inches(0.96), 右宽, Inches(2.60), 填充=色["深"], 线=色["强调"], 线宽=1.2)
    字(页, 右左 + Inches(0.14), Inches(1.02), 右宽 - Inches(0.28), Inches(0.28), [
        ("参照：LoongEnv-SHIZE（我们学它的组织方式）", 11, 色["强调"], True),
    ])
    图路径 = os.path.join(图目录, "LoongEnv_浏览器实况.png")
    # ★ 这图是 2697×1555（宽高比 1.735）。按高度给尺寸时宽度会被反算出来 ——
    #   第一次给 height=2.06in → 宽 3.57in，把右侧说明挤成 1.86in 窄条。
    #   现在给 height=1.62in（宽≈2.81in），说明文字就放得下了。
    if os.path.exists(图路径):
        页.shapes.add_picture(图路径, 右左 + Inches(0.14), Inches(1.34), height=Inches(1.62))
    字(页, 右左 + Inches(3.10), Inches(1.32), Inches(2.72), Inches(2.10), [
        ("学它什么", 11, 色["强调"], True, 3),
        ("任务流式布局", 10.5, 色["主文"], False, 2),
        ("常驻中区 3D", 10.5, 色["主文"], False, 2),
        ("右侧参数随手改", 10.5, 色["主文"], False, 6),
        ("不抄它的假数据", 10.5, 色["警"], False, 2),
    ], 行距=1.12)

    框(页, 右左, Inches(3.66), 右宽, Inches(2.60), 填充=色["面板"], 线=色["警"], 线宽=1.2)
    字(页, 右左 + Inches(0.14), Inches(3.74), 右宽 - Inches(0.28), Inches(0.28), [
        ("还缺什么", 12.5, 色["警"], True),
    ])
    字(页, 右左 + Inches(0.14), Inches(4.08), 右宽 - Inches(0.28), Inches(2.10), [
        ("3D 视口　网页里还是占位", 13, 色["主文"], False, 6),
        ("四项能力　规划 / 诊断 / 部署 / 市场", 13, 色["主文"], False, 6),
        ("官方面板　19 个在 Web 端不可用", 13, 色["主文"], False, 6),
        ("跨平台　Windows 未验证", 13, 色["主文"], False, 6),
        ("交付　安装包 / 签名未做", 13, 色["主文"], False, 6),
    ], 行距=1.15)

    # ---- 底部一句：区别的本质 ----
    框(页, Inches(0.55), Inches(6.44), Inches(12.20), Inches(0.72),
       填充=色["深"], 线=色["强调"], 线宽=1.2)
    字(页, Inches(0.72), Inches(6.50), Inches(11.86), Inches(0.60), [
        ("区别的本质：① 借的是官方的「界面」，② 借的是官方的「能力」—— "
         "所以 ① 的天花板是官方留没留位置，② 的天花板是我们自己做到什么程度。",
         13, 色["强调"], True),
    ], 居中=True, 行距=1.1)


# ===========================================================================
# 第 5 页：三张阶段卡 + 时间线
# ===========================================================================
def 重做第5页(页) -> None:
    留 = 保留要用的(页, 留标题=True)
    清掉(页, 留)

    # ★ 不再是"标题 + 副标题说同一句话"：标题已是"先拿回窗口，再补能力"，
    #   副标题改成补一个**时间口径**（让人知道这三段各有多远）。
    字(页, Inches(2.10), Inches(0.36), Inches(10.60), Inches(0.34), [
        ("三段：现在 → 接下来 → 最后　（每段都能停，停了软件照样可用）", 12, 色["次文"], False),
    ])

    卡们 = [
        ("P3　拿回窗口", 色["强调"], "现在",
         ["自建宿主窗口", "把 3D 接进中区", "顺带铺跨平台路"]),
        ("P4　补能力", 色["好"], "接下来",
         ["轨迹规划（能比出好坏）", "诊断（从猜变成查）", "部署 / 插件市场（最后）"]),
        ("P5　打包发布", 色["次文"], "最后",
         ["macOS 已有", "Windows 安装包", "签名与更新"]),
    ]
    宽卡, 缝 = Inches(3.92), Inches(0.22)
    for i, (标题, 线, 时机, 条目) in enumerate(卡们):
        左 = Inches(0.55) + i * (宽卡 + 缝)
        框(页, 左, Inches(1.02), 宽卡, Inches(3.30), 填充=色["面板"], 线=线, 线宽=1.4)
        字(页, 左 + Inches(0.16), Inches(1.12), 宽卡 - Inches(0.32), Inches(0.34), [
            (标题, 15, 线, True),
        ])
        字(页, 左 + Inches(0.16), Inches(1.48), 宽卡 - Inches(0.32), Inches(0.26), [
            (时机, 10.5, 色["次文"], False),
        ])
        行们 = [("· " + t, 14, 色["主文"], False, 14) for t in 条目]
        字(页, 左 + Inches(0.16), Inches(1.86), 宽卡 - Inches(0.32), Inches(2.30),
          行们, 行距=1.25)

    # 时间线（一条横线 + 三个阶段圆点）
    线y = Inches(4.72)
    条 = 页.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1.2), 线y,
                           Inches(10.9), Emu(19050))
    条.fill.solid(); 条.fill.fore_color.rgb = 色["描边"]
    条.line.fill.background(); 条.shadow.inherit = False
    for i, (标题, 线色, _, _) in enumerate(卡们):
        x = Inches(2.4) + i * Inches(4.24)
        点 = 页.shapes.add_shape(MSO_SHAPE.OVAL, x, 线y - Inches(0.09),
                               Inches(0.20), Inches(0.20))
        点.fill.solid(); 点.fill.fore_color.rgb = 线色
        点.line.fill.background(); 点.shadow.inherit = False
        字(页, x - Inches(0.85), 线y + Inches(0.20), Inches(1.90), Inches(0.30), [
            (["现在", "接下来", "最后"][i], 11, 线色, True),
        ], 对齐=PP_ALIGN.CENTER)

    # 底部一句：为什么 3D 必须跟窗口一起做
    框(页, Inches(0.55), Inches(5.72), Inches(12.20), Inches(1.44),
       填充=色["深"], 线=色["强调"], 线宽=1.2)
    字(页, Inches(0.72), Inches(5.82), Inches(11.86), Inches(1.24), [
        ("为什么 3D 必须跟「拿回窗口」一起做", 14, 色["强调"], True, 8),
        ("3D 画面需要一个「能放原生视图的窗口」，而这个窗口正是 P3 的产物；",
         12.5, 色["主文"], False, 4),
        ("分开做等于先按想象写接口、再回头改。", 12.5, 色["主文"], False, 4),
    ], 行距=1.2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--文件", default=os.path.join(
        包根, "报告", "07_历史快照", "交付物", "驭臂_工作汇报.pptx"))
    ap.add_argument("--出", default=None)
    ap.add_argument("--无备份", action="store_true")
    a = ap.parse_args()

    if a.出 is None and not a.无备份:
        备份 = a.文件.replace(".pptx", ".减字前备份.pptx")
        shutil.copyfile(a.文件, 备份)
        print(f"  ✓ 已备份：{os.path.basename(备份)}")

    prs = Presentation(a.文件)
    学习配色(prs.slides[2])
    print(f"  沿用配色：底={色['底']} 强调={色['强调']}")

    print("  第 3 页：图为主 + 4 个短词…")
    重做第3页(prs.slides[2])
    print("  第 4 页：区别 + 技术 + 缺口 + LoongEnv 截图…")
    重做第4页(prs.slides[3])
    print("  第 5 页：三张阶段卡 + 时间线…")
    重做第5页(prs.slides[4])

    出 = a.出 or a.文件
    prs.save(出)
    print(f"  ✓ 已写入：{出}")
    for i in (2, 3, 4):
        print(f"  第 {i+1} 页：{len(prs.slides[i].shapes)} 个形状")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
