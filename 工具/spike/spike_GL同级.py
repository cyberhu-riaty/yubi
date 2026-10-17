"""
spike_GL同级.py —— P2 spike 第二步：**OpenGL 视图**能否同样与 WKWebView 并列

为什么还要单独验这一步（Metal 已经成功了）：
    第一版 spike 用的是 CAMetalLayer —— 那证明的是"**一个图层支撑的原生视图**
    可以和 WKWebView 同级并列"。但**真实的 3D 要画 MuJoCo 的场景**，而 MuJoCo 的
    经典渲染器要的是 **OpenGL 1.5 兼容 profile**（官方文档原话；实测 core profile 下
    `MjrContext` 直接 FatalError: ARB_framebuffer_object required）。

    Metal 与 OpenGL 在 macOS 上是**两套完全不同的合成路径**：
      · Metal 走 CAMetalLayer（layer-backed，原生支持）
      · 传统 NSOpenGLView **默认不是 layer-backed** —— 而 WKWebView 是。
        这正是调研里点名的头号风险："layer-backed 的 webview vs 非 layer-backed 的
        GL 视图 → 叠加/合成瑕疵"。

    所以这一步必须单独验，不能拿 Metal 的结果外推。

它验证什么：
    ① `NSOpenGLView`（兼容 profile）与 WKWebView 同级并列，网页不被盖、GL 区不被盖
    ② GL 区**真的在出帧**（画一个随时间变化的颜色；并统计帧数）
    ③ GL 区**真的能画 MuJoCo 场景**：若 `mujoco.Renderer` 可用，就用它离屏渲染
       一帧再上传成 GL 纹理贴上去（这条是"3D 视口"的真身）
    ④ 拖动改变窗口大小时两块各自跟随

⚠️ 第 ③ 步是**加分项**：它成不成立都不影响"同级并列"这个结论，
   只影响"3D 画面怎么进到那块区域"的实现选择（直画 / 离屏+纹理 / 服务端渲染）。

用法：
    .venv/bin/python 工具/spike/spike_GL同级.py --秒 12
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
                    NSColor, NSMakeRect, NSOpenGLPFAAccelerated, NSOpenGLPFAColorSize,
                    NSOpenGLPFADepthSize, NSOpenGLPFADoubleBuffer, NSOpenGLPFAOpenGLProfile,
                    NSOpenGLProfileVersionLegacy, NSOpenGLView, NSWindow,
                    NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
                    NSWindowStyleMaskResizable, NSWindowStyleMaskTitled)
from Foundation import NSObject, NSTimer
from WebKit import WKWebView, WKWebViewConfiguration

参数 = None
窗口宽, 窗口高 = 1100.0, 760.0
网页高比 = 0.44


class GLView(NSOpenGLView):
    """兼容 profile 的 NSOpenGLView：每帧清屏成随时间变化的颜色。

    关键点（踩过才写的）：
      · 必须 `NSOpenGLProfileVersionLegacy` —— MuJoCo 要兼容 profile；
        用 core profile 的话 `MjrContext` 建不起来。
      · 每帧要 `makeCurrentContext()` + `flushBuffer()`（双缓冲）。
    """

    def initWithFrame_(self, frame):
        # ---- 像素格式：兼容 profile + 双缓冲 + 24 位深度（MuJoCo 要深度）----
        属性 = [
            NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersionLegacy,
            NSOpenGLPFAColorSize, 24,
            NSOpenGLPFADepthSize, 24,
            NSOpenGLPFADoubleBuffer,
            NSOpenGLPFAAccelerated,
            0,
        ]
        from AppKit import NSOpenGLPixelFormat
        格式 = NSOpenGLPixelFormat.alloc().initWithAttributes_(属性)
        self = objc.super(GLView, self).initWithFrame_pixelFormat_(frame, 格式)
        if self is None:
            return None
        self.帧数 = 0
        self.上帧 = 0.0
        self.上下文信息 = ""
        self.MuJoCo纹理 = None
        self.MuJoCo错误 = ""
        return self

    def prepareOpenGL(self):
        objc.super(GLView, self).prepareOpenGL()
        self.openGLContext().makeCurrentContext()
        # 关掉垂直同步，让帧数能反映真实出帧能力
        from AppKit import NSOpenGLCPSwapInterval
        值 = objc.pyobjc_unicode if False else None
        try:
            import ctypes
            间隔 = ctypes.c_int(0)
            self.openGLContext().setValues_forParameter_(间隔, NSOpenGLCPSwapInterval)
        except Exception:                                             # noqa: BLE001
            pass
        self._报上下文()

    def _报上下文(self):
        try:
            from OpenGL import GL
            版本 = GL.glGetString(GL.GL_VERSION)
            渲染器 = GL.glGetString(GL.GL_RENDERER)
            glsl = GL.glGetString(GL.GL_SHADING_LANGUAGE_VERSION)
            解 = lambda b: b.decode() if isinstance(b, bytes) else str(b)
            self.上下文信息 = (f"GL_VERSION={解(版本)}  GLSL={解(glsl)}  "
                            f"RENDERER={解(渲染器)}")
            print(f"  OpenGL 上下文：{self.上下文信息}", flush=True)
        except Exception as 异常:                                     # noqa: BLE001
            self.上下文信息 = f"（读不到：{异常}）"

    def 试建MuJoCo纹理(self) -> None:
        """加分项：用 `mujoco.Renderer` 离屏渲一帧，看这条路通不通。

        ★ 为什么值得试：`mujoco.Renderer` **自带自己的 GL 上下文**
          （macOS 上是 cgl），不依赖我们这个视图的上下文 —— 所以"离屏渲染 + 上传纹理"
          是一条**不碰 profile 冲突**的路子。它成不成，决定 3D 的接入方式。
        """
        try:
            import mujoco
            import numpy as np
            包根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            模型路径 = os.path.join(包根, "模型", "kuka_iiwa_14", "iiwa14_torque.xml")
            if not os.path.exists(模型路径):
                self.MuJoCo错误 = f"找不到模型：{模型路径}"
                return
            模型 = mujoco.MjModel.from_xml_path(模型路径)
            数据 = mujoco.MjData(模型)
            mujoco.mj_forward(模型, 数据)
            # ★ offwidth/offheight 默认只有 640×480，渲染更大尺寸会 ValueError
            渲染 = mujoco.Renderer(模型, height=360, width=640)
            # ★ 第一次跑出来**几乎全黑**（均值 1.2）—— 因为没给相机。离屏渲染不会
            #   自动取一个好看的角度，默认视角在模型外面。显式给相机才看得到机器人。
            #   ⚠️ 本机 mujoco 3.13 的签名是
            #      `update_scene(data, camera=-1, scene_option=None)`
            #      —— **没有 `scene=` 参数**（场景由 Renderer 自己持有）。
            #      按老文档写 `scene=` 会 TypeError（实测踩过）。
            相机 = mujoco.MjvCamera()
            mujoco.mjv_defaultFreeCamera(模型, 相机)
            # 相机参数是**试出来的**：iiwa14 立起来约 1.2 m 高，
            #   distance 2.6 太近（机器人顶出画面）、背景默认全黑（均值才 1.2）。
            相机.distance = 5.0
            相机.azimuth = 135.0
            相机.elevation = -14.0
            相机.lookat[:] = (0.0, 0.0, 0.55)
            选项 = mujoco.MjvOption()
            mujoco.mjv_defaultOption(选项)
            # 打开天窗（背景）与雾，否则背板是纯黑、看不出"这是 3D 场景"
            模型.vis.global_.offwidth = 1280
            模型.vis.global_.offheight = 720
            渲染.update_scene(数据, camera=相机, scene_option=选项)
            图 = 渲染.render()
            self.MuJoCo图 = np.ascontiguousarray(图[::-1])      # OpenGL 是下到上
            self.MuJoCo纹理 = 0        # 0 = 还没有纹理，>0 = GL 纹理号
            self.MuJoCo错误 = ""
            print(f"  ✓ MuJoCo 离屏渲染成功：{图.shape}  均值={图.mean():.1f}", flush=True)
        except Exception as 异常:                                     # noqa: BLE001
            self.MuJoCo错误 = f"{type(异常).__name__}: {异常}"
            print(f"  ⚠ MuJoCo 离屏渲染不可用（不影响同级结论）：{self.MuJoCo错误}",
                  flush=True)

    def drawRect_(self, _脏区):
        import ctypes
        上下文 = self.openGLContext()
        上下文.makeCurrentContext()
        from OpenGL import GL
        try:
            像素尺寸 = self.convertRectToBacking_(self.bounds()).size
            视口宽 = max(1, int(像素尺寸.width))
            视口高 = max(1, int(像素尺寸.height))
            GL.glViewport(0, 0, 视口宽, 视口高)
            t = time.perf_counter()
            if getattr(self, "MuJoCo图", None) is not None:
                # ---- 有 MuJoCo 帧：把它当纹理铺满（这条通了，3D 就能进这块区域）----
                if self.MuJoCo纹理 == 0:
                    贴图号 = GL.glGenTextures(1)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, 贴图号)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                    高, 宽, _ = self.MuJoCo图.shape
                    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, 宽, 高, 0,
                                    GL.GL_RGB, GL.GL_UNSIGNED_BYTE, self.MuJoCo图.tobytes())
                    self.MuJoCo纹理 = 贴图号
                GL.glClearColor(0.02, 0.05, 0.09, 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
                GL.glMatrixMode(GL.GL_PROJECTION)
                GL.glLoadIdentity()
                GL.glOrtho(0, 1, 0, 1, -1, 1)
                GL.glMatrixMode(GL.GL_MODELVIEW)
                GL.glLoadIdentity()
                GL.glEnable(GL.GL_TEXTURE_2D)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self.MuJoCo纹理)
                GL.glColor3f(1, 1, 1)
                GL.glBegin(GL.GL_QUADS)
                GL.glTexCoord2f(0, 1); GL.glVertex2f(0, 0)
                GL.glTexCoord2f(1, 1); GL.glVertex2f(1, 0)
                GL.glTexCoord2f(1, 0); GL.glVertex2f(1, 1)
                GL.glTexCoord2f(0, 0); GL.glVertex2f(0, 1)
                GL.glEnd()
                GL.glDisable(GL.GL_TEXTURE_2D)
            else:
                # ---- 没有 MuJoCo：画一个随时间变化的颜色（证明真的在出帧）----
                相位 = (t * 0.4) % 1.0
                GL.glClearColor(0.05 + 0.15 * 相位, 0.30 + 0.30 * 相位,
                                0.50 + 0.30 * (1 - 相位), 1.0)
                GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            上下文.flushBuffer()
            self.帧数 += 1
        except Exception as 异常:                                         # noqa: BLE001
            if self.帧数 == 0:
                print(f"  ✗ GL 出帧失败：{type(异常).__name__}: {异常}", flush=True)

    def reshape(self):
        objc.super(GLView, self).reshape()
        self.openGLContext().update()


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, _通知):
        global 参数
        窗口 = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(120, 120, 窗口宽, 窗口高),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered, False)
        窗口.setTitle_("P2 spike · 第二步：OpenGL 视图 + WKWebView 同级并列")
        窗口.setBackgroundColor_(NSColor.blackColor())
        内容 = 窗口.contentView()

        网页高 = 窗口高 * 网页高比
        gl高 = 窗口高 - 网页高

        自 = GLView.alloc().initWithFrame_(NSMakeRect(0, 0, 窗口宽, gl高))
        内容.addSubview_(自)
        self.gl = 自

        配置 = WKWebViewConfiguration.alloc().init()
        网 = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, gl高, 窗口宽, 网页高), 配置)
        内容.addSubview_(网)
        self.网页 = 网
        网.loadHTMLString_baseURL_(HTML, None)

        窗口.makeKeyAndOrderFront_(None)
        self.窗口 = 窗口

        print("=" * 74)
        print("  P2 spike 第二步：OpenGL 视图 + WKWebView 同级并列")
        print("=" * 74)
        print(f"  窗口   : {窗口宽:.0f}×{窗口高:.0f}（backingScale={窗口.backingScaleFactor()}）")
        print(f"  布局   : 上 WKWebView {网页高:.0f}px ／ 下 NSOpenGLView {gl高:.0f}px")
        for i, v in enumerate(内容.subviews()):
            f = v.frame()
            层 = type(v.layer()).__name__ if v.layer() is not None else "无图层(传统 GL 视图)"
            print(f"    [{i}] {type(v).__name__:26} frame=({f.origin.x:.0f},{f.origin.y:.0f},"
                  f"{f.size.width:.0f},{f.size.height:.0f})  layer={层}")
        print()
        print("  ⚠️ 注意看：GL 视图是不是 layer-backed（关系到合成路径）")
        print("=" * 74, flush=True)

        # 试 MuJoCo 离屏渲染（加分项）
        self.gl.试建MuJoCo纹理()

        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 60.0, self, "画一帧:", None, True)
        if 参数.秒 > 0:
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                参数.秒, self, "收工:", None, False)

    def 画一帧_(self, _定时器):
        self.gl.setNeedsDisplay_(True)

    def 收工_(self, _定时器):
        层 = self.gl.layer()
        print(f"\n  GL 视图 layer-backed: {self.gl.wantsLayer()} / layer={type(层).__name__ if 层 else '无'}")
        print(f"  GL 实际出帧数：{self.gl.帧数}（0 = 没画成）")
        print(f"  MuJoCo 离屏渲染："
              f"{'✓ 成功并已贴进 GL 视口' if self.gl.MuJoCo纹理 else '✗ ' + self.gl.MuJoCo错误}",
              flush=True)
        NSApplication.sharedApplication().terminate_(None)


HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
  html,body{margin:0;height:100%;background:#0d141c;color:#dbe6f0;
    font:14px/1.6 -apple-system,"PingFang SC",sans-serif}
  .条{display:flex;align-items:center;gap:10px;padding:8px 14px;background:#16233a;
    border-bottom:1px solid #1e3350;font-size:13px}
  .点{width:9px;height:9px;border-radius:99px;background:#4cc2ff}
  .体{padding:14px} h1{font-size:15px;margin:0 0 8px}
  .网格{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:10px}
  .卡{background:#121a23;border:1px solid #1e3350;border-radius:8px;padding:10px}
  .卡 b{color:#7b8fa3;font-weight:400;font-size:12px;display:block}
  .卡 span{font:16px/1.4 ui-monospace,Menlo,monospace;color:#4cc2ff}
</style></head><body>
<div class="条"><span class="点"></span>上：真 WKWebView &nbsp;·&nbsp; 下：<b>NSOpenGLView</b>（兼容 profile）
  &nbsp;·&nbsp; 若 MuJoCo 离屏渲染成功，下面显示的是<b>真的 iiwa14 场景</b></div>
<div class="体">
  <h1>第二步：OpenGL 能否同样并列</h1>
  <div>Metal 已经证明"图层支撑的原生视图"可以并列。这一步验的是 OpenGL ——
       它默认<b>不是</b> layer-backed，而 webview 是，这正是调研点名的头号风险。</div>
  <div class="网格">
    <div class="卡"><b>上</b><span>WKWebView</span></div>
    <div class="卡"><b>下</b><span>NSOpenGLView</span></div>
    <div class="卡"><b>画面来源</b><span>MuJoCo</span></div>
  </div>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="P2 spike 第二步：GL + WKWebView 同级并列")
    ap.add_argument("--秒", type=float, default=14.0)
    args = ap.parse_args()
    global 参数
    参数 = args

    应用 = NSApplication.sharedApplication()
    应用.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    委托 = AppDelegate.alloc().init()
    应用.setDelegate_(委托)
    应用.activateIgnoringOtherApps_(True)
    应用.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
