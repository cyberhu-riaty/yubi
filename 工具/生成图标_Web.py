"""
生成图标_Web.py —— 画「小软件 · 工作台（Web 界面）」的图标

与 `生成图标.py` 的区别，以及为什么要有两个图标：
    两个 .app 指向**同一个软件的不同前端**（原生 ImGui 界面 / 浏览器界面）。
    如果图标一样，桌面和 Dock 上根本分不出点哪个 —— 实测那种"点错了还以为是 bug"
    的体验很差。所以：
      · 原生界面：机械臂为主（`生成图标.py`，一眼是"机器人"）
      · 本图标  ：**窗口 + 机械臂**（一眼是"界面/工作台"）
    配色沿用同一套品牌色（深蓝底 + 亮蓝强调），所以两个图标看着是一家的。

用法：
    .venv/bin/python 工具/生成图标_Web.py                    # 输出 工具/图标_Web.icns
    .venv/bin/python 工具/生成图标_Web.py --输出 某处/x.icns
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

# 尺寸表：macOS 图标规范（iconutil 要求这几个名字）
尺寸表 = [(16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")]


def _圆角(笔: ImageDraw.ImageDraw, 框, 半径: float, 填充: str, 描边: str | None = None,
         宽度: int = 0) -> None:
    笔.rounded_rectangle(框, radius=半径, fill=填充,
                       outline=描边, width=宽度)


def 画图标(尺寸: int, 底色: str, 窗口底: str, 标题条: str, 主色: str,
         强调色: str) -> Image.Image:
    """一个窗口：标题条 + 三颗圆点 + 里面一台机械臂。"""
    S = 尺寸
    图 = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    笔 = ImageDraw.Draw(图)

    # ---- 底板（macOS 图标要留安全边距，否则在 Dock 里显得比别人大）----
    边距 = S * 0.085
    外 = [边距, 边距, S - 边距, S - 边距]
    _圆角(笔, 外, S * 0.205, 底色)

    # ---- 窗口 ----
    内边距 = S * 0.155
    窗 = [内边距, S * 0.215, S - 内边距, S - S * 0.205]
    _圆角(笔, 窗, S * 0.055, 窗口底)

    # ---- 标题条 ----
    条高 = (窗[3] - 窗[1]) * 0.185
    笔.rounded_rectangle([窗[0], 窗[1], 窗[2], 窗[1] + 条高 * 1.6],
                       radius=S * 0.055, fill=标题条)
    # 把标题条下缘切成直角（只保留上圆角）
    笔.rectangle([窗[0], 窗[1] + 条高 * 0.9, 窗[2], 窗[1] + 条高], fill=标题条)

    # ---- 三颗圆点（红黄绿的精神，但用主题色，避免照抄系统 UI）----
    点r = S * 0.0165
    点y = 窗[1] + 条高 * 0.5
    for i, 色 in enumerate((强调色, 主色, "#5b6b7c")):
        点x = 窗[0] + S * 0.052 + i * S * 0.052
        笔.ellipse([点x - 点r, 点y - 点r, 点x + 点r, 点y + 点r], fill=色)

    # ---- 窗口里的机械臂（基座在左下，向右上伸出去）----
    内容上 = 窗[1] + 条高 * 1.25
    内容下 = 窗[3] - S * 0.03
    内容左 = 窗[0] + S * 0.06
    内容右 = 窗[2] - S * 0.06
    H = 内容下 - 内容上

    基座 = (内容左 + (内容右 - 内容左) * 0.18, 内容下 - H * 0.04)
    肩 = (基座[0] + (内容右 - 内容左) * 0.06, 内容上 + H * 0.52)
    肘 = (肩[0] + (内容右 - 内容左) * 0.40, 内容上 + H * 0.20)
    腕 = (肘[0] + (内容右 - 内容左) * 0.30, 内容上 + H * 0.56)
    粗 = int(S * 0.055)

    # 底座
    笔.rounded_rectangle([基座[0] - 粗 * 0.95, 基座[1] - 粗 * 0.55,
                        基座[0] + 粗 * 0.95, 内容下],
                        radius=粗 * 0.25, fill=主色)
    for 甲, 乙, 宽 in ((基座, 肩, 粗), (肩, 肘, 粗 * 0.88),
                      (肘, 腕, 粗 * 0.74)):
        笔.line([甲, 乙], fill=主色, width=int(宽))
    for 点, r in ((肩, 粗 * 0.62), (肘, 粗 * 0.55), (腕, 粗 * 0.46)):
        笔.ellipse([点[0] - r, 点[1] - r, 点[0] + r, 点[1] + r], fill=强调色)
    # 末端夹爪（两片）
    尖 = (腕[0] + (内容右 - 内容左) * 0.10, 腕[1] - H * 0.16)
    笔.line([腕, 尖], fill=强调色, width=int(粗 * 0.34))
    叉 = 粗 * 0.42
    笔.line([(尖[0], 尖[1]), (尖[0] + 叉, 尖[1] - 叉)], fill=主色, width=int(粗 * 0.3))
    笔.line([(尖[0], 尖[1]), (尖[0] + 叉, 尖[1] + 叉 * 0.7)], fill=主色,
            width=int(粗 * 0.3))
    return 图


def 生成_icns(输出路径: str, 配色: dict) -> bool:
    if shutil.which("iconutil") is None:
        print("  ✗ 找不到 iconutil（只能在 macOS 上用）")
        return False
    with tempfile.TemporaryDirectory() as 临时:
        图标集 = os.path.join(临时, "图标.iconset")
        os.makedirs(图标集, exist_ok=True)
        for 像素, 名 in 尺寸表:
            画图标(像素, **配色).save(os.path.join(图标集, 名), "PNG")
        结果 = subprocess.run(["iconutil", "-c", "icns", 图标集, "-o", 输出路径],
                            capture_output=True, text=True)
        if 结果.returncode != 0:
            print(f"  ✗ iconutil 失败：{结果.stderr.strip()[:200]}")
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="画「小软件 · Web 工作台」图标")
    ap.add_argument("--输出", default=None, help="输出的 .icns 路径")
    ap.add_argument("--底色", default="#101b2d", help="底板底色")
    ap.add_argument("--窗口底", default="#16233a", help="窗口内容底色")
    ap.add_argument("--标题条", default="#1e3350", help="窗口标题条色")
    ap.add_argument("--主色", default="#c9d6e6", help="机械臂主体色")
    ap.add_argument("--强调色", default="#4cc2ff", help="关节/高亮色")
    args = ap.parse_args(argv)

    这里 = os.path.dirname(os.path.abspath(__file__))
    输出 = args.输出 or os.path.join(这里, "图标_Web.icns")
    配色 = {"底色": args.底色, "窗口底": args.窗口底, "标题条": args.标题条,
           "主色": args.主色, "强调色": args.强调色}

    print("=" * 66)
    print("生成图标（Web 工作台）")
    print("=" * 66)
    print(f"  输出 {输出}")
    print(f"  配色 {args.底色} / 窗口 {args.窗口底} / 主色 {args.主色} / 强调 {args.强调色}")
    os.makedirs(os.path.dirname(os.path.abspath(输出)), exist_ok=True)
    if not 生成_icns(输出, 配色):
        return 1
    print(f"  ✓ 完成（{os.path.getsize(输出) / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
