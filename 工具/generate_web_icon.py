"""
generate_web_icon.py —— 画「小软件 · 工作台（Web 界面）」的图标

与 `generate_app_icon.py` 的区别，以及为什么要有两个图标：
    两个 .app 指向**同一个软件的不同前端**（原生 ImGui 界面 / 浏览器界面）。
    如果图标一样，桌面和 Dock 上根本分不出点哪个 —— 实测那种"点错了还以为是 bug"
    的体验很差。所以：
      · 原生界面：机械臂为主（`generate_app_icon.py`，一眼是"机器人"）
      · 本图标  ：**窗口 + 机械臂**（一眼是"界面/工作台"）
    配色沿用同一套品牌色（深蓝底 + 亮蓝强调），所以两个图标看着是一家的。

用法：
    .venv/bin/python 工具/generate_web_icon.py                    # 输出 工具/图标_Web.icns
    .venv/bin/python 工具/generate_web_icon.py --输出 某处/x.icns
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
sizes = [(16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")]


def _rounded_rectangle(draw: ImageDraw.ImageDraw, bounds, radius: float, fill: str, outline: str | None = None,
         line_width: int = 0) -> None:
    draw.rounded_rectangle(bounds, radius=radius, fill=fill,
                       outline=outline, width=line_width)


def draw_icon(size: int, background: str, window_background: str, title_bar: str, foreground: str,
         accent: str) -> Image.Image:
    """一个窗口：标题条 + 三颗圆点 + 里面一台机械臂。"""
    S = size
    image = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # ---- 底板（macOS 图标要留安全边距，否则在 Dock 里显得比别人大）----
    margin = S * 0.085
    outer = [margin, margin, S - margin, S - margin]
    _rounded_rectangle(draw, outer, S * 0.205, background)

    # ---- 窗口 ----
    padding = S * 0.155
    window = [padding, S * 0.215, S - padding, S - S * 0.205]
    _rounded_rectangle(draw, window, S * 0.055, window_background)

    # ---- 标题条 ----
    bar_height = (window[3] - window[1]) * 0.185
    draw.rounded_rectangle([window[0], window[1], window[2], window[1] + bar_height * 1.6],
                       radius=S * 0.055, fill=title_bar)
    # 把标题条下缘切成直角（只保留上圆角）
    draw.rectangle([window[0], window[1] + bar_height * 0.9, window[2], window[1] + bar_height], fill=title_bar)

    # ---- 三颗圆点（红黄绿的精神，但用主题色，避免照抄系统 UI）----
    dot_radius = S * 0.0165
    dot_y = window[1] + bar_height * 0.5
    for i, color in enumerate((accent, foreground, "#5b6b7c")):
        dot_x = window[0] + S * 0.052 + i * S * 0.052
        draw.ellipse([dot_x - dot_radius, dot_y - dot_radius, dot_x + dot_radius, dot_y + dot_radius], fill=color)

    # ---- 窗口里的机械臂（基座在左下，向右上伸出去）----
    content_top = window[1] + bar_height * 1.25
    content_bottom = window[3] - S * 0.03
    content_left = window[0] + S * 0.06
    content_right = window[2] - S * 0.06
    H = content_bottom - content_top

    base = (content_left + (content_right - content_left) * 0.18, content_bottom - H * 0.04)
    shoulder = (base[0] + (content_right - content_left) * 0.06, content_top + H * 0.52)
    elbow = (shoulder[0] + (content_right - content_left) * 0.40, content_top + H * 0.20)
    wrist = (elbow[0] + (content_right - content_left) * 0.30, content_top + H * 0.56)
    stroke_width = int(S * 0.055)

    # 底座
    draw.rounded_rectangle([base[0] - stroke_width * 0.95, base[1] - stroke_width * 0.55,
                        base[0] + stroke_width * 0.95, content_bottom],
                        radius=stroke_width * 0.25, fill=foreground)
    for first, second, width in ((base, shoulder, stroke_width), (shoulder, elbow, stroke_width * 0.88),
                      (elbow, wrist, stroke_width * 0.74)):
        draw.line([first, second], fill=foreground, width=int(width))
    for point, r in ((shoulder, stroke_width * 0.62), (elbow, stroke_width * 0.55), (wrist, stroke_width * 0.46)):
        draw.ellipse([point[0] - r, point[1] - r, point[0] + r, point[1] + r], fill=accent)
    # 末端夹爪（两片）
    tip = (wrist[0] + (content_right - content_left) * 0.10, wrist[1] - H * 0.16)
    draw.line([wrist, tip], fill=accent, width=int(stroke_width * 0.34))
    cross = stroke_width * 0.42
    draw.line([(tip[0], tip[1]), (tip[0] + cross, tip[1] - cross)], fill=foreground, width=int(stroke_width * 0.3))
    draw.line([(tip[0], tip[1]), (tip[0] + cross, tip[1] + cross * 0.7)], fill=foreground,
            width=int(stroke_width * 0.3))
    return image


def generate_icns(output_path: str, colors: dict) -> bool:
    if shutil.which("iconutil") is None:
        print("  ✗ 找不到 iconutil（只能在 macOS 上用）")
        return False
    with tempfile.TemporaryDirectory() as temp_dir:
        iconset = os.path.join(temp_dir, "图标.iconset")
        os.makedirs(iconset, exist_ok=True)
        for pixels, name in sizes:
            draw_icon(pixels, **colors).save(os.path.join(iconset, name), "PNG")
        result = subprocess.run(["iconutil", "-c", "icns", iconset, "-o", output_path],
                            capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ✗ iconutil 失败：{result.stderr.strip()[:200]}")
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="画「小软件 · Web 工作台」图标")
    ap.add_argument("--output", "--输出", default=None, help="输出的 .icns 路径")
    ap.add_argument("--background", "--底色", default="#101b2d", help="底板底色")
    ap.add_argument("--window-background", "--窗口底", default="#16233a", help="窗口内容底色")
    ap.add_argument("--title-bar", "--标题条", default="#1e3350", help="窗口标题条色")
    ap.add_argument("--foreground", "--主色", default="#c9d6e6", help="机械臂主体色")
    ap.add_argument("--accent", "--强调色", default="#4cc2ff", help="关节/高亮色")
    args = ap.parse_args(argv)

    directory = os.path.dirname(os.path.abspath(__file__))
    output = args.output or os.path.join(directory, "图标_Web.icns")
    colors = {
        "background": args.background,
        "window_background": args.window_background,
        "title_bar": args.title_bar,
        "foreground": args.foreground,
        "accent": args.accent,
    }

    print("=" * 66)
    print("生成图标（Web 工作台）")
    print("=" * 66)
    print(f"  输出 {output}")
    print(f"  配色 {args.background} / 窗口 {args.window_background} / 主色 {args.foreground} / 强调 {args.accent}")
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    if not generate_icns(output, colors):
        return 1
    print(f"  ✓ 完成（{os.path.getsize(output) / 1024:.0f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
