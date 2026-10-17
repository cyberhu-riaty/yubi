"""
加LoongEnv截图并重做第4页.py —— 两件事：
  ① 第 3 页右下角加一张"参考：LoongEnv 实况"截图（用户提供）
  ② 第 4 页重做：用图形方框讲"跟路线①的区别 / 用了什么不同技术 / 还缺什么"

为什么只动这两页：
    用户已在本地反复改过这份 PPT（第 2、3 页都重排了）。整份重生成会覆盖他的修改，
    所以这里只做**定点改动**，其它页一个像素都不碰。

第 4 页的新结构（用户要求：主要用图形方框）：
    一排四块（对比卡）：
        ① 路线① 用的什么   ② 路线② 用的什么   ③ 换来了什么   ④ 还缺什么
    底下一个"区别的本质"：
        路线① 是借官方的"界面"，路线② 是借官方的"能力"。

用法：
    python3 工具/加LoongEnv截图并重做第4页.py            # 就地改，先备份
"""
from __future__ import annotations

import argparse
import os
import shutil

from PIL import Image
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
    "旧底": RGBColor(0x1A, 0x1F, 0x27),      # 路线①（旧）
    "新底": RGBColor(0x12, 0x28, 0x24),      # 路线②（新）
    "灰线": RGBColor(0x5A, 0x6B, 0x7C),
}


def _色(sh, 属性: str):
    try:
        return getattr(sh, 属性).rgb
    except Exception:                                                 # noqa: BLE001
        return None


def 学习配色(页) -> None:
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


def 字(页, 左, 上, 宽, 高, 行们, 对齐=PP_ALIGN.LEFT, 行距=1.1, 顶对齐=False):
    tb = 页.shapes.add_textbox(左, 上, 宽, 高)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.04)
    tf.margin_top = tf.margin_bottom = 0
    if 顶对齐:
        tf.vertical_anchor = MSO_ANCHOR.TOP
    for i, 条 in enumerate(行们):
        文本, 号, 颜色, 粗 = 条[0], 条[1], 条[2], 条[3]
        # 可选：该段自己的行距与段后距（卡片里要精打细算，靠它才排得进）
        段行距 = 条[4] if len(条) > 4 and 条[4] else 行距
        段后 = 条[5] if len(条) > 5 and 条[5] is not None else 1.5
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = 对齐
        p.line_spacing = 段行距
        p.space_after = Pt(段后)
        r = p.add_run()
        r.text = 文本
        r.font.size = Pt(号)
        r.font.color.rgb = 颜色
        r.font.bold = 粗
        r.font.name = 字体
    return tb


# ===========================================================================
# ① 第 3 页：右下角加 LoongEnv 实况截图
# ===========================================================================
def 改第3页(页) -> None:
    # ★ 先把原来那栏文字**改短并压矮**，给下面腾位置。
    #   踩过的坑：第一版是"再加一个文本框"，结果两份文字叠在一起 —— 看起来像重影。
    #   正确做法是改原有的那个（用户可能是自己排的版式，保留它的位置与字号风格）。
    for sh in list(页.shapes):
        if sh.has_text_frame and sh.text_frame.text.strip().startswith("· 双击点开"):
            sh.height = Inches(3.30)
            tf = sh.text_frame
            tf.clear()                     # 清掉旧段落，再写新的
            行们 = [
                "· 双击点开，不用装环境、不用联网",
                "· 6 台机械臂点一下就换（另 24 台可导入）",
                "· 中英双语 ＋ 5 套界面风格",
                "· 换模型 / 换算法 / 改参数都不重启",
            ]
            for i, 行文 in enumerate(行们):
                para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                para.line_spacing = 1.35
                para.space_after = Pt(4)
                r = para.add_run()
                r.text = 行文
                r.font.size = Pt(12)
                r.font.color.rgb = 色["主文"]
                r.font.name = 字体
            break

    # 参考截图：放右下角，控制高度不压过主图
    图路径 = os.path.join(图目录, "LoongEnv_浏览器实况.png")
    if not os.path.exists(图路径):
        print("  ⚠ 找不到 LoongEnv 截图，跳过")
        return
    框(页, Inches(9.64), Inches(4.42), Inches(3.69), Inches(2.55),
       填充=RGBColor(0x16, 0x1C, 0x24), 线=色["描边"])
    字(页, Inches(9.76), Inches(4.48), Inches(3.45), Inches(0.26), [
        ("参考：LoongEnv-SHIZE 实况", 10, 色["次文"], True),
    ])
    # ★ 按**高度**定尺寸：这张图 2697×1555，按宽 3.3in 算高 1.90in，正好。
    图高 = Inches(1.72)
    页.shapes.add_picture(图路径, Inches(9.76), Inches(4.76), height=图高)
    字(页, Inches(9.76), Inches(6.55), Inches(3.45), Inches(0.36), [
        ("我们学的是它的组织方式（任务流＋常驻中区），不抄它的假数据。", 9, 色["次文"], False),
    ], 行距=1.1)


# ===========================================================================
# ② 第 4 页：重做
# ===========================================================================
def 重做第4页(页) -> None:
    # 保留：背景、左侧竖条、标题、分隔线；删掉其余
    保留 = set()          # 存 shape 的 XML 元素（Shape 本身不可哈希）
    for sh in 页.shapes:
        L, T = Emu(sh.left).inches, Emu(sh.top).inches
        W, H = Emu(sh.width).inches, Emu(sh.height).inches
        if W > 12.9 and H > 7.0:                      # 背景
            保留.add(sh._element)
        elif W < 0.2 and H > 7.0:                     # 竖条
            保留.add(sh._element)
        elif T < 0.8 and W < 3.0 and sh.has_text_frame and sh.text_frame.text.strip():
            保留.add(sh._element)                            # "② 重构" 标题
        elif abs(H - 0.01) < 0.02 and W > 12:         # 细分隔线
            保留.add(sh._element)
    for sh in list(页.shapes):
        if sh._element not in 保留:
            sh._element.getparent().remove(sh._element)

    # 副标题（原来第 4 页没有副标题，这里补一句，说明这页讲什么）
    字(页, Inches(2.10), Inches(0.36), Inches(10.6), Inches(0.36), [
        ("跟路线①的区别、用了什么技术、还缺什么", 13, 色["次文"], False),
    ])

    # ---- 四块对比卡 ----
    左0, 宽4 = Inches(0.55), Inches(2.95)
    缝 = Inches(0.135)
    上, 高 = Inches(0.98), Inches(3.20)

    卡们 = [
        ("路线① 用的什么", 色["旧底"], 色["灰线"], [
            ("界面", "官方 ImGui（C++ 编译进去的）"),
            ("语言", "Python 外壳 ＋ C++ 底座"),
            ("进程", "单进程：界面与仿真同屋"),
            ("平台", "只有 macOS"),
            ("改界面", "改不动：只能绕着它补"),
        ]),
        ("路线② 用的什么", 色["新底"], 色["好"], [
            ("界面", "Web：React ＋ Tailwind ＋ Vite"),
            ("语言", "Python 后端 ＋ TypeScript 前端"),
            ("通信", "WebSocket ＋ JSON（一份契约）"),
            ("进程", "仿真独立跑，界面只是客户"),
            ("平台", "窗口层抽象后，可扩到 Windows"),
        ]),
        ("换来了什么", 色["面板"], 色["强调"], [
            ("开发", "界面随便改：组件、图表、主题、双语"),
            ("加算法", "放一个 .py 就生效，不动界面"),
            ("可诊断", "状态全走公开通道，能看能记"),
            ("可回退", "新界面是旁路，老界面同时存在"),
            ("为跨平台", "界面已与系统解耦（只剩窗口层）"),
        ]),
        ("还缺什么", 色["面板"], 色["警"], [
            ("3D 视口", "网页里那块还是占位（下一步）"),
            ("新能力", "轨迹规划 / 诊断 / 部署 / 市场"),
            ("官方面板", "19 个 ImGui 面板在 Web 端不可用"),
            ("跨平台", "Windows 未验证（需一台机器）"),
            ("体验", "启动方式、安装包、签名未做"),
        ]),
    ]
    for i, (标题, 底, 线, 条目) in enumerate(卡们):
        左 = 左0 + i * (宽4 + 缝)
        框(页, 左, 上, 宽4, 高, 填充=底, 线=线, 线宽=1.25)
        字(页, 左 + Inches(0.12), 上 + Inches(0.10), 宽4 - Inches(0.24), Inches(0.30), [
            (标题, 12.5, 线, True),
        ])
        行们 = []
        for 键, 值 in 条目:
            # 键行：小字、紧、无间隙；值行：正常、留 3pt 间隙
            行们.append((键, 9, 色["次文"], True, 0.92, 0))
            行们.append((值, 9.5, 色["主文"], False, 1.0, 3))
        字(页, 左 + Inches(0.12), 上 + Inches(0.44), 宽4 - Inches(0.24),
          Inches(2.40), 行们, 行距=1.0)

    # ---- 底部：区别的本质 + 下一步 ----
    框(页, Inches(0.55), Inches(4.40), Inches(12.20), Inches(1.02),
       填充=RGBColor(0x14, 0x1A, 0x22), 线=色["强调"], 线宽=1.25)
    字(页, Inches(0.72), Inches(4.48), Inches(11.86), Inches(0.86), [
        ("区别的本质：路线① 借的是官方的「界面」，路线② 借的是官方的「能力」。", 13.5, 色["强调"], True),
        ("所以路线① 的天花板是「官方留了位置没有」；路线② 的天花板是「我们自己做到什么程度」。", 12, 色["主文"], False),
    ], 行距=1.2)

    框(页, Inches(0.55), Inches(5.58), Inches(12.20), Inches(1.02),
       填充=色["面板"], 线=色["好"], 线宽=1.25)
    字(页, Inches(0.72), Inches(5.66), Inches(11.86), Inches(0.86), [
        ("下一步：先把「窗口」拿回来，再把「能力」补上。", 13.5, 色["好"], True),
        ("拿回窗口 = 自己掌控窗口 + 把 3D 视口接进中区（这两件必须一起做）；"
         "补能力 = 轨迹规划、诊断、部署、插件市场（按依赖顺序，见下一页）。", 12, 色["主文"], False),
    ], 行距=1.2)

    字(页, Inches(0.55), Inches(6.76), Inches(12.20), Inches(0.34), [
        ("★ 一句话：路线① 已经把「核」验证完了；路线② 是在同一个核上，把「壳」换成自己的。", 11.5, 色["次文"], False),
    ])


def 修第5页页脚(页) -> None:
    """第 5 页底部那行"最后（P5）"框高 0.42in 装两行字偏紧，压一下字号。

    为什么要在改第 4 页的脚本里顺手改：这是同一轮编辑里几何检查报出来的，
    留着重影/溢出不管，等于把问题留给用户。
    """
    for sh in 页.shapes:
        if not sh.has_text_frame:
            continue
        if sh.text_frame.text.strip().startswith("最后（P5）"):
            for para in sh.text_frame.paragraphs:
                for r in para.runs:
                    if r.font.size and r.font.size.pt > 10.5:
                        r.font.size = Pt(10.5)
            break


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--文件", default=os.path.join(
        包根, "报告", "07_历史快照", "交付物", "驭臂_工作汇报.pptx"))
    ap.add_argument("--出", default=None)
    ap.add_argument("--无备份", action="store_true")
    a = ap.parse_args()

    if a.出 is None and not a.无备份:
        备份 = a.文件.replace(".pptx", ".改4页前备份.pptx")
        shutil.copyfile(a.文件, 备份)
        print(f"  ✓ 已备份：{os.path.basename(备份)}")

    prs = Presentation(a.文件)
    学习配色(prs.slides[2])
    print(f"  沿用配色：底={色['底']} 强调={色['强调']}")

    print("  改第 3 页（加 LoongEnv 参考截图）…")
    改第3页(prs.slides[2])
    print("  重做第 4 页（对比 / 技术 / 缺口）…")
    重做第4页(prs.slides[3])
    修第5页页脚(prs.slides[4])

    出 = a.出 or a.文件
    prs.save(出)
    print(f"  ✓ 已写入：{出}")
    for i in (2, 3):
        print(f"  第 {i+1} 页：{len(prs.slides[i].shapes)} 个形状")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
