"""
generate_app_icon.py —— 给 .app 画一个图标（不依赖设计软件）

它做什么：
    用 Pillow 画一个"抽象机械臂"图标（圆角深色底 + 基座 + 两节臂 + 关节），
    然后生成 macOS 需要的 .iconset 并用系统自带的 `iconutil` 转成 .icns。

为什么自己画：
    项目里没有设计资源，也没有设计软件。图标只要能表达"机械臂仿真软件"即可，
    用代码画的好处是**可重现**：改几行参数就能换配色/换造型，不用找设计师。

用法：
    .venv/bin/python 工具/generate_app_icon.py                      # 默认输出到 工具/图标.icns
    .venv/bin/python 工具/generate_app_icon.py --输出 某处/我的.icns
    .venv/bin/python 工具/generate_app_icon.py --底色 "#1b2a41" --主色 "#4cc2ff"

技术要点（踩过的）：
    · macOS 图标必须留出"安全边距"（内容不能占满整张图），否则在 Dock 里显得比别人大
    · .icns 必须由 `iconutil` 从 .iconset 目录生成，且文件名有固定命名规则
    · 16/32 这种小尺寸下细节会糊，所以画的是"少而粗"的几何形状，不画细节
"""
from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter


def draw_icon(dimensions: int, background: str, foreground: str, accent: str) -> Image.Image:
    """画一张 `尺寸×尺寸` 的图标。所有坐标按比例算，任何尺寸都清晰。"""
    # 超采样 4 倍再缩小 → 边缘平滑（省得手写抗锯齿）
    scale = 4
    S = dimensions * scale
    image = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # ---- 背景：圆角方块（macOS 风格安全边距 = 8%）----
    margin = int(S * 0.08)
    radius = int(S * 0.22)
    draw.rounded_rectangle([margin, margin, S - margin, S - margin], radius=radius, fill=background)

    # 背景上加一点从左上到右下的渐变感（叠一层半透明）
    highlight = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    highlight_pen = ImageDraw.Draw(highlight)
    highlight_pen.rounded_rectangle([margin, margin, S - margin, S - margin], radius=radius,
                           fill=(255, 255, 255, 26))
    highlight = highlight.filter(ImageFilter.GaussianBlur(S * 0.02))
    image = Image.alpha_composite(image, highlight)
    draw = ImageDraw.Draw(image)

    def point(x: float, y: float) -> tuple[float, float]:
        """把 0~1 的相对坐标换算成像素坐标。"""
        return (S * x, S * y)

    # ---- 基座（底部梯形 + 一条底座线）----
    draw.polygon([point(0.28, 0.82), point(0.72, 0.82), point(0.64, 0.70), point(0.36, 0.70)],
               fill=foreground)
    draw.rounded_rectangle([point(0.24, 0.82)[0], point(0.24, 0.82)[1],
                          point(0.76, 0.88)[0], point(0.76, 0.88)[1]],
                         radius=S * 0.015, fill=foreground)

    # ---- 肩关节（基座上方的圆）----
    shoulder = point(0.50, 0.68)
    draw.ellipse([shoulder[0] - S * 0.055, shoulder[1] - S * 0.055,
                shoulder[0] + S * 0.055, shoulder[1] + S * 0.055], fill=accent)

    # ---- 上臂：从肩关节斜向左上 ----
    elbow = point(0.34, 0.44)
    draw.line([shoulder, elbow], fill=foreground, width=int(S * 0.085))
    draw.ellipse([elbow[0] - S * 0.05, elbow[1] - S * 0.05,
                elbow[0] + S * 0.05, elbow[1] + S * 0.05], fill=accent)

    # ---- 前臂：从肘斜向右上 ----
    wrist = point(0.62, 0.28)
    draw.line([elbow, wrist], fill=foreground, width=int(S * 0.07))
    draw.ellipse([wrist[0] - S * 0.042, wrist[1] - S * 0.042,
                wrist[0] + S * 0.042, wrist[1] + S * 0.042], fill=accent)

    # ---- 末端工具：一小段"手指/夹爪"----
    tip = point(0.74, 0.19)
    draw.line([wrist, tip], fill=accent, width=int(S * 0.035))
    draw.ellipse([tip[0] - S * 0.028, tip[1] - S * 0.028,
                tip[0] + S * 0.028, tip[1] + S * 0.028], fill=foreground)

    # ---- 末端画一条淡淡的运动弧线（暗示"在运动"）----
    arc = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    arc_pen = ImageDraw.Draw(arc)
    arc_pen.arc([point(0.30, 0.06)[0], point(0.30, 0.06)[1],
              point(1.04, 0.66)[0], point(1.04, 0.66)[1]],
             start=200, end=300, fill=(255, 255, 255, 110), width=int(S * 0.012))
    image = Image.alpha_composite(image, arc)

    # 缩回目标尺寸
    return image.resize((dimensions, dimensions), Image.LANCZOS)


def generate_icns(output_path: str, background: str, foreground: str, accent: str) -> bool:
    """生成 .icns。需要系统的 iconutil（macOS 自带）。"""
    if shutil.which("iconutil") is None:
        print("✗ 找不到 iconutil（macOS 才能用）")
        return False

    with tempfile.TemporaryDirectory() as temp_dir:
        iconset = os.path.join(temp_dir, "图标.iconset")
        os.makedirs(iconset)
        # macOS 规定的命名与尺寸
        specs = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2),
                (256, 1), (256, 2), (512, 1), (512, 2)]
        for base, scale_factor in specs:
            pixels = base * scale_factor
            name = f"icon_{base}x{base}" + ("@2x" if scale_factor == 2 else "") + ".png"
            draw_icon(pixels, background, foreground, accent).save(os.path.join(iconset, name), "PNG")
        result = subprocess.run(["iconutil", "-c", "icns", iconset, "-o", output_path],
                              capture_output=True, text=True)
        if result.returncode != 0:
            print(f"✗ iconutil 失败：{result.stderr.strip()}")
            return False
    return True


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="生成 .app 图标")
    ap.add_argument("--output", "--输出", default=None, help="输出的 .icns 路径")
    ap.add_argument("--background", "--底色", default="#16233a", help="背景色（默认深蓝）")
    ap.add_argument("--foreground", "--主色", default="#c9d6e6", help="机械臂主体色（默认浅灰蓝）")
    ap.add_argument("--accent", "--强调色", default="#4cc2ff", help="关节高亮色（默认亮蓝）")
    args = ap.parse_args(argv)

    if args.output:
        output = args.output
    else:
        directory = os.path.dirname(os.path.abspath(__file__))
        output = os.path.join(directory, "图标.icns")

    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    print("=" * 66)
    print("生成图标")
    print("=" * 66)
    print(f"  底色 {args.background} / 主色 {args.foreground} / 强调色 {args.accent}")
    if not generate_icns(output, args.background, args.foreground, args.accent):
        return 1
    size = os.path.getsize(output) / 1024
    print(f"  ✓ 已生成 {output}（{size:.0f} KB）")
    # 顺便导出一张预览 PNG（方便在文档/PPT 里用）
    preview = os.path.splitext(output)[0] + "_预览.png"
    draw_icon(512, args.background, args.foreground, args.accent).save(preview, "PNG")
    print(f"  ✓ 预览图 {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
