"""
spike_同级视图.py —— P2 决定性验证：**原生渲染视图能不能和 WKWebView 同窗口并列**

为什么这个 spike 必须先做（而不是先写代码再试）：
    对 Tauri / pywebview / 自建 C++ 宿主三条路的调研**全部收敛到同一个未知**：

        「一个 Metal/GL 原生视图，能不能作为 WKWebView 的**同级视图**
          放进同一个 NSWindow，而不出现合成瑕疵？」

    它**不是框架问题，是 macOS 合成器的问题**。所以先用最小代价问出答案：
      ✅ 行 → 外壳选型变成"打包/团队技能"问题，三条路都活着
      ❌ 不行 → 退到"3D 用独立但始终贴附的窗口"，或直接上自研窗口方案
                （自研窗口那条路已经在 `输出/render_probe/` 验证过能跑）

它做什么：
    一个 NSWindow，**上下两块**：
      · 上：真正的 WKWebView，里面是真实 HTML（带背景色的块 + 文字）
      · 下：CAMetalLayer 支撑的 NSView，Metal 每帧画一个**动画渐变**
    然后：
      ① 打印子视图顺序 / 图层属性 / 各自 frame（证明布局真的是"同级并列"）
      ② 截图（由外部脚本抓窗口），供人眼判断有没有瑕疵
      ③ 自动退出（供脚本化验证）

怎么判定"有瑕疵"（人眼与截图都看这几条）：
      · 金属视图区域有没有**被 webview 的白色底盖住**（airspace 问题）
      · 两者交界处有没有**闪烁 / 撕裂 / 错位**
      · 改变窗口大小时，两块是否**各自正确跟随**
      · Metal 是否真的在动（渐变在变 = 有帧在画）

用法：
    .venv/bin/python 工具/spike/spike_同级视图.py --秒 10
    .venv/bin/python 工具/spike/spike_同级视图.py --截图 /tmp/spike.png --秒 8
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
                    NSColor, NSMakeRect, NSView, NSWindow, NSWindowStyleMaskClosable,
                    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
                    NSWindowStyleMaskTitled)
from Foundation import NSObject, NSRunLoop, NSDate, NSTimer, NSURL, NSURLRequest
from Quartz import (CACurrentMediaTime, CAMetalLayer, CATransaction,
                    kCAGravityResize)
from WebKit import WKWebView, WKWebViewConfiguration

# Metal（pyobjc-framework-Metal 没装时给出可读提示，而不是崩）
try:
    import Metal
    from Quartz import CGColorCreateGenericRGB
    有金属 = True
except Exception as 异常:                                             # noqa: BLE001
    有金属 = False
    金属错误 = f"{type(异常).__name__}: {异常}"

窗口宽, 窗口高 = 1100.0, 760.0
网页高比 = 0.46          # 上 46% 给网页，下 54% 给金属视图


class MetalView(NSView):
    """一个 CAMetalLayer 支撑的视图：每帧清屏成一个随时间变化的颜色。

    为什么用"动画颜色"而不是画个静止方块：**静止图看不出有没有在合成**。
    颜色在变 = 有真的帧在提交，闪烁/撕裂这类问题也才暴露得出来。
    """

    def initWithFrame_(self, frame):
        self = objc.super(MetalView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.设备 = Metal.MTLCreateSystemDefaultDevice()
        self.队列 = self.设备.newCommandQueue() if self.设备 else None
        self.帧数 = 0
        self.上帧时刻 = 0.0
        self._装图层()
        return self

    def _同步尺寸(self):
        """把 layer 的 frame / contentsScale / **drawableSize** 都对齐到视图大小。

        ★ 踩过的坑：只 setFrame_ 是不够的 —— CAMetalLayer 的 `drawableSize`
          默认是 0×0，`nextDrawable()` 就一直返回 nil，表现为**一块纯黑**、
          而且不报任何错（实测：出帧数 0）。必须显式设 drawableSize。
        """
        if getattr(self, "层", None) is None:
            return
        比 = self.window().backingScaleFactor() if self.window() else 2.0
        宽 = self.bounds().size.width
        高 = self.bounds().size.height
        self.层.setFrame_(self.bounds())
        self.层.setContentsScale_(比)
        self.层.setDrawableSize_((宽 * 比, 高 * 比))

    def viewDidMoveToWindow(self):
        objc.super(MetalView, self).viewDidMoveToWindow()
        self._同步尺寸()

    def viewDidChangeBackingProperties(self):
        objc.super(MetalView, self).viewDidChangeBackingProperties()
        self._同步尺寸()

    def layout(self):
        objc.super(MetalView, self).layout()
        self._同步尺寸()

    def _装图层(self):
        层 = CAMetalLayer.layer()
        层.setDevice_(self.设备)
        层.setPixelFormat_(80)                 # MTLPixelFormatBGRA8Unorm
        层.setFramebufferOnly_(True)
        层.setOpaque_(True)
        层.setContentsGravity_(kCAGravityResize)
        比例 = self.window().backingScaleFactor() if self.window() else 2.0
        层.setContentsScale_(比例)
        self.setWantsLayer_(True)
        self.setLayer_(层)
        self.层 = 层

    # ---- 每帧 ----
    def 画一帧(self):
        if not self.队列 or self.层 is None:
            return
        t = CACurrentMediaTime()
        if t - self.上帧时刻 < 1.0 / 60.0:      # 限到 60 fps，别把 CPU 吃满
            return
        self.上帧时刻 = t
        尺寸 = self.层.drawableSize()
        if 尺寸.width < 2 or 尺寸.height < 2:
            return
        try:
            画布 = self.层.nextDrawable()
        except Exception:                                             # noqa: BLE001
            return
        if 画布 is None:
            return
        相位 = (t * 0.35) % 1.0
        缓冲 = self.队列.commandBuffer()
        通过 = Metal.MTLRenderPassDescriptor.renderPassDescriptor()
        # PyObjC 里这个数组**不可下标**（没有 __getitem__），要用显式方法名
        附件 = 通过.colorAttachments().objectAtIndexedSubscript_(0)
        附件.setTexture_(画布.texture())
        附件.setLoadAction_(2)                 # MTLLoadActionClear
        附件.setStoreAction_(1)                # MTLStoreActionStore
        # 渐变色：蓝 → 青，随时间缓慢变化（一眼看出"在动"）
        附件.setClearColor_((0.05 + 0.10 * 相位, 0.25 + 0.35 * 相位,
                           0.45 + 0.35 * (1.0 - 相位), 1.0))
        编码 = 缓冲.renderCommandEncoderWithDescriptor_(通过)
        编码.endEncoding()
        缓冲.presentDrawable_(画布)
        缓冲.commit()
        self.帧数 += 1

    def resizeWithOldSuperviewSize_(self, 旧):
        objc.super(MetalView, self).resizeWithOldSuperviewSize_(旧)
        if getattr(self, "层", None) is not None:
            比例 = self.window().backingScaleFactor() if self.window() else 2.0
            尺寸 = self.convertSizeToBacking_(self.bounds().size)
            self.层.setContentsScale_(比例)
            self.层.setDrawableSize_(尺寸)


# ★ 参数走模块级变量，不走 init：NSObject 没有 `initWithArgs_` 这个初始化器，
#   自己 `objc.super(...).initWithArgs_(...)` 会直接 AttributeError（实测踩过）。
#   一个 spike 不值得为它写一个带参初始化器的子类。
参数 = None


class AppDelegate(NSObject):

    def applicationDidFinishLaunching_(self, _通知):
        global 参数
        窗口 = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(120, 120, 窗口宽, 窗口高),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered, False)
        窗口.setTitle_("P2 spike · 原生渲染视图 + WKWebView 同级并列")
        窗口.setBackgroundColor_(NSColor.blackColor())
        内容 = 窗口.contentView()

        网页高 = 窗口高 * 网页高比
        金属高 = 窗口高 - 网页高

        # ---- ① 先加金属视图（下方）----
        金 = MetalView.alloc().initWithFrame_(NSMakeRect(0, 0, 窗口宽, 金属高))
        if hasattr(金, "层") and 金.层 is not None:
            金.层.setFrame_(NSMakeRect(0, 0, 窗口宽, 金属高))
        内容.addSubview_(金)
        金._同步尺寸()
        self.金属 = 金

        # ---- ② 再加 WKWebView（上方）----
        配置 = WKWebViewConfiguration.alloc().init()
        网 = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 金属高, 窗口宽, 网页高), 配置)
        # ★ 不给它设透明：调研的结论是"同级布局**不需要**透明"，
        #   而透明在 macOS 上要碰私有 API（drawsBackground）。这里正好验证这条。
        网.setValue_forKey_(False, "opaque") if False else None
        内容.addSubview_(网)
        self.网页 = 网

        # ---- ③ 先给网页一个深色底，再灌真实 HTML ----
        #   顺序重要：先设不透明底色，避免加载完成前闪白，掩盖真正的问题
        网.setValue_forKey_(False, "drawsBackground") if 参数.试透明 else None
        网.loadHTMLString_baseURL_(HTML, None)

        窗口.makeKeyAndOrderFront_(None)
        self.窗口 = 窗口
        金._同步尺寸()

        # ---- ④ 打印事实：证明这确实是"同级并列" ----
        print("=" * 74)
        print("  P2 spike：原生渲染视图 + WKWebView 同级并列")
        print("=" * 74)
        print(f"  窗口      : {窗口宽:.0f}×{窗口高:.0f}"
              f"（backingScale={窗口.backingScaleFactor()}）")
        print(f"  布局      : 上 WKWebView {网页高:.0f}px ／ 下 Metal {金属高:.0f}px")
        子视图 = 内容.subviews()
        print(f"  contentView 的子视图数：{len(子视图)}（应为 2 = 真同级）")
        for i, v in enumerate(子视图):
            名 = type(v).__name__
            f = v.frame()
            层类 = type(v.layer()).__name__ if v.layer() is not None else "无图层"
            print(f"    [{i}] {名:12} frame=({f.origin.x:.0f},{f.origin.y:.0f},"
                  f"{f.size.width:.0f},{f.size.height:.0f})  layer={层类}")
        print(f"  Metal 设备: {self.金属.设备.name() if self.金属.设备 else '不可用'}")
        print(f"  drawableSize: {self.金属.层.drawableSize()}")
        print(f"  webview 是否透明(drawsBackground): "
              f"{参数.试透明 if 参数.试透明 else '否（默认不透明）'}")
        print()
        print("  ⚠️ 看这几条判断有没有合成瑕疵：")
        print("     · 下方金属区域有没有被网页的底色盖住")
        print("     · 交界处有没有闪烁 / 撕裂 / 错位")
        print("     · 拖动改变窗口大小时两块是否各自跟随")
        print("     · 金属颜色是否在缓慢变化（在变 = 真的在出帧）")
        print("=" * 74, flush=True)

        # ---- ⑤ 定时器：驱动 Metal + 定时退出 ----
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 60.0, self, "画一帧:", None, True)
        if 参数.秒 > 0:
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                参数.秒, self, "收工:", None, False)

    def 画一帧_(self, _定时器):
        try:
            self.金属.画一帧()
        except Exception as 异常:                                     # noqa: BLE001
            print(f"  ✗ Metal 出帧失败：{type(异常).__name__}: {异常}", flush=True)

    def 收工_(self, _定时器):
        print(f"\n  Metal 实际出帧数：{self.金属.帧数}（0 = 没画成）", flush=True)
        NSApplication.sharedApplication().terminate_(None)


HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
  html,body{margin:0;height:100%;background:#0d141c;color:#dbe6f0;
    font:14px/1.6 -apple-system,"PingFang SC",sans-serif}
  .条{display:flex;align-items:center;gap:10px;padding:8px 14px;background:#16233a;
    border-bottom:1px solid #1e3350;font-size:13px}
  .点{width:9px;height:9px;border-radius:99px;background:#4cc2ff}
  .体{padding:14px}
  h1{font-size:15px;margin:0 0 8px}
  .网格{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}
  .卡{background:#121a23;border:1px solid #1e3350;border-radius:8px;padding:10px}
  .卡 b{color:#7b8fa3;font-weight:400;font-size:12px;display:block}
  .卡 span{font:16px/1.4 ui-monospace,Menlo,monospace;color:#4cc2ff}
  .注{margin-top:12px;color:#7b8fa3;font-size:12px}
</style></head><body>
<div class="条"><span class="点"></span>上面这块是<b>真的 WKWebView</b>（真 HTML/CSS）
  &nbsp;·&nbsp;下面那块是 <b>CAMetalLayer 原生视图</b></div>
<div class="体">
  <h1>P2 决定性验证：同级并列</h1>
  <div>如果下面那块金属区域在缓慢变色、且没有被这块网页的底盖住，
       说明"原生渲染视图 + WebView 同窗口"成立 —— 三条外壳路线都活着。</div>
  <div class="网格">
    <div class="卡"><b>上：网页</b><span>WKWebView</span></div>
    <div class="卡"><b>下：原生</b><span>Metal</span></div>
    <div class="卡"><b>未来 3D</b><span>MuJoCo</span></div>
  </div>
  <div class="注">拖动窗口边缘改变大小，观察两块是否各自正确跟随。</div>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="P2 spike：原生视图 + WKWebView 同级并列")
    ap.add_argument("--秒", type=float, default=12.0, help="跑多少秒后自动退出（0=不自动退）")
    ap.add_argument("--试透明", dest="试透明", action="store_true",
                    help="顺带试一下 webview 透明（用的是私有 KVC key，仅作对照）")
    args = ap.parse_args()

    if not 有金属:
        print(f"✗ Metal 不可用：{金属错误}")
        print("  装一下：.venv/bin/python -m pip install pyobjc-framework-Metal")
        return 1

    应用 = NSApplication.sharedApplication()
    应用.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    global 参数
    参数 = args
    委托 = AppDelegate.alloc().init()
    应用.setDelegate_(委托)
    应用.activateIgnoringOtherApps_(True)
    应用.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
