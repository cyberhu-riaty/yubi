"""
spike_验收.py —— P2 的**自动验收**：把"同级视图成立"从"截图看着行"变成"逐条可判定"

为什么还要这一步（前两个 spike 不够）：
    `spike_同级视图.py` / `spike_GL同级.py` 给的是一次**静态截图级**证据 ——
    能证明"两块都在、各自出帧"，但撑不起"冻结架构"这个结论。缺的四样：
      ① **活体 resize**：改尺寸时两块是否各自跟随（不是只看初始布局）
      ② **持续帧率与稳定性**：不是"累计出帧数"，而是**帧间隔分布**
         （人眼对 p99 敏感；只看均值会把周期性卡顿藏起来）
      ③ **无泄漏**：长时间跑会不会攒 GL 纹理
      ④ **WebView 真的在合成**：在 WebKit 进程里查 DOM，不是"我们调了 loadHTMLString_"

本版是从能跑的 `spike_GL同级.py` **增量**长出来的，不是另起一套。三条硬教训写在下面。

─── 三条硬教训（都是本次踩出来的，别再犯）─────────────────────────────
① **不要在 AppKit 回调里建第二套 GL 上下文。**
   `mujoco.Renderer` 自建 CGL 上下文。而 `prepareOpenGL` / 定时器回调 / `drawRect_`
   都跑在 `CATransaction … WithDisplayLink` 的刷帧事务里 —— 在事务中间建第二套上下文，
   进程**直接 SIGTRAP**，Python 侧连 traceback 都没有（`faulthandler` 抓不到、
   `objc.setObjCExceptionHandler` 也不触发）。
   → 修法：MuJoCo 的渲染器**只在独立线程里建**，GPU 资源（纹理）只在绘制路径里建。

② **`NSOpenGLView` 没有有意义的 `layer.drawableSize`。**
   那是 `CAMetalLayer` 的属性。对 GL 视图，"对齐"该看
   `convertRectToBacking_(bounds)` 算出的**像素尺寸**（= 我们传给 glViewport 的那个）。
   照 CAMetalLayer 的写法去设 `drawableSize_` 是在测一个不存在的东西（本次先写错、已改）。

③ **不要给窗口装 delegate 来收 resize。**
   实测：只要 `窗口.setDelegate_(任意对象)` 就会 SIGTRAP（与那个对象是否实现
   `windowDidResize_` 无关）。改用**通知**收 resize：
   `NSNotificationCenter` 观察 `NSWindowDidResizeNotification` —— 语义更明确，
   也避开这条路。

用法：
    .venv/bin/python 工具/spike/spike_验收.py --截图 /tmp/验收截图
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time

import objc
from AppKit import (NSApplication, NSApplicationActivationPolicyRegular, NSBackingStoreBuffered,
                    NSColor, NSMakeRect, NSOpenGLPFAAccelerated, NSOpenGLPFAColorSize,
                    NSOpenGLPFADepthSize, NSOpenGLPFADoubleBuffer, NSOpenGLPFAOpenGLProfile,
                    NSOpenGLPixelFormat, NSOpenGLProfileVersionLegacy, NSOpenGLView, NSWindow,
                    NSWindowDidResizeNotification, NSWindowStyleMaskClosable,
                    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
                    NSWindowStyleMaskTitled)
from Foundation import NSNotificationCenter, NSObject, NSTimer
from WebKit import WKWebView, WKWebViewConfiguration

参数 = None
结果: list[tuple[str, bool, str]] = []


def 判(名: str, 好: bool, 说明: str) -> bool:
    结果.append((名, bool(好), 说明))
    print(f"  {'✓' if 好 else '✗'} {名:16} {说明}", flush=True)
    return bool(好)


def _内存MB() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)


class GLView(NSOpenGLView):
    """兼容 profile 的 GL 视图：把 MuJoCo 离屏帧当纹理铺满，并记录帧间隔。"""

    def initWithFrame_(self, frame):
        属性 = [NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersionLegacy,
               NSOpenGLPFAColorSize, 24, NSOpenGLPFADepthSize, 24,
               NSOpenGLPFADoubleBuffer, NSOpenGLPFAAccelerated, 0]
        格式 = NSOpenGLPixelFormat.alloc().initWithAttributes_(属性)
        self = objc.super(GLView, self).initWithFrame_pixelFormat_(frame, 格式)
        if self is None:
            return None
        self.帧数 = 0
        self.帧间隔: list[float] = []
        self.上帧 = 0.0
        self.纹理 = 0
        self.图 = None
        self.错误 = ""
        self.视口像素 = (0, 0)
        return self

    def prepareOpenGL(self):
        """只做上下文自己的事。**绝不在这里建 MuJoCo 渲染器**（见文件头教训 ①）。"""
        objc.super(GLView, self).prepareOpenGL()
        self.openGLContext().makeCurrentContext()

    def 后台载MuJoCo(self):
        def 干活():
            try:
                import mujoco
                import numpy as np
                包根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                模型 = mujoco.MjModel.from_xml_path(
                    os.path.join(包根, "模型", "kuka_iiwa_14", "iiwa14_torque.xml"))
                数据 = mujoco.MjData(模型)
                mujoco.mj_forward(模型, 数据)
                # ★ 离屏帧缓冲默认只有 640×480：渲染更大的尺寸会直接
                #   `ValueError: Image width 760 > framebuffer width 640`。
                #   必须在建 Renderer **之前**把 offwidth/offheight 调大。
                #   （这条在 spike_同级视图.py 里踩过一次，重写时又丢了一次 —— 所以写进注释。）
                模型.vis.global_.offwidth = 1280
                模型.vis.global_.offheight = 720
                渲染 = mujoco.Renderer(模型, height=420, width=760)
                相机 = mujoco.MjvCamera()
                mujoco.mjv_defaultFreeCamera(模型, 相机)
                相机.distance, 相机.azimuth, 相机.elevation = 3.4, 135.0, -16.0
                相机.lookat[:] = (0.0, 0.0, 0.45)
                选项 = mujoco.MjvOption()
                mujoco.mjv_defaultOption(选项)
                渲染.update_scene(数据, camera=相机, scene_option=选项)
                图 = 渲染.render()
                self.图 = np.ascontiguousarray(图[::-1])       # 赋值原子；绘制侧只读
                print("  ✓ MuJoCo 后台载入成功（独立线程，未撞 AppKit 事务）", flush=True)
            except Exception as 异常:                                 # noqa: BLE001
                self.错误 = f"{type(异常).__name__}: {异常}"
                print(f"  ✗ MuJoCo 载入失败：{self.错误}", flush=True)

        import threading
        threading.Thread(target=干活, daemon=True, name="MuJoCo载入").start()

    def drawRect_(self, _脏区):
        from OpenGL import GL
        try:
            上下文 = self.openGLContext()
            上下文.makeCurrentContext()
            尺寸 = self.convertRectToBacking_(self.bounds()).size
            宽, 高 = max(1, int(尺寸.width)), max(1, int(尺寸.height))
            self.视口像素 = (宽, 高)
            GL.glViewport(0, 0, 宽, 高)
            GL.glClearColor(0.02, 0.05, 0.09, 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            if self.图 is not None:
                if self.纹理 == 0:              # 只建一次（同时是"无泄漏"的前提）
                    贴图 = GL.glGenTextures(1)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, 贴图)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
                    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
                    高图, 宽图, _ = self.图.shape
                    GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, 宽图, 高图, 0,
                                    GL.GL_RGB, GL.GL_UNSIGNED_BYTE, self.图.tobytes())
                    self.纹理 = 贴图
                GL.glMatrixMode(GL.GL_PROJECTION); GL.glLoadIdentity()
                GL.glOrtho(0, 1, 0, 1, -1, 1)
                GL.glMatrixMode(GL.GL_MODELVIEW); GL.glLoadIdentity()
                GL.glEnable(GL.GL_TEXTURE_2D)
                GL.glBindTexture(GL.GL_TEXTURE_2D, self.纹理)
                GL.glColor3f(1, 1, 1)
                GL.glBegin(GL.GL_QUADS)
                GL.glTexCoord2f(0, 1); GL.glVertex2f(0, 0)
                GL.glTexCoord2f(1, 1); GL.glVertex2f(1, 0)
                GL.glTexCoord2f(1, 0); GL.glVertex2f(1, 1)
                GL.glTexCoord2f(0, 0); GL.glVertex2f(0, 1)
                GL.glEnd()
                GL.glDisable(GL.GL_TEXTURE_2D)
            上下文.flushBuffer()
            现在 = time.perf_counter()
            if self.上帧 > 0:
                self.帧间隔.append(现在 - self.上帧)
                del self.帧间隔[:-5000]
            self.上帧 = 现在
            self.帧数 += 1
        except Exception as 异常:                                         # noqa: BLE001
            if self.帧数 == 0:
                self.错误 = f"drawRect_: {type(异常).__name__}: {异常}"

    def 期望像素(self) -> tuple[int, int]:
        """按 backingScale 算出的**应有像素尺寸** —— GL 视图的对齐该看这个（教训 ②）。"""
        尺寸 = self.convertRectToBacking_(self.bounds()).size
        return (int(尺寸.width), int(尺寸.height))

    def reshape(self):
        objc.super(GLView, self).reshape()
        self.openGLContext().update()


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, _通知):
        global 参数
        self.宽, self.高 = 1100.0, 760.0
        self.网页区比 = 0.42

        窗口 = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(140, 140, self.宽, self.高),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered, False)
        窗口.setTitle_("P2 验收 · 同级视图（自动判定）")
        窗口.setBackgroundColor_(NSColor.blackColor())
        # ★ 不设窗口 delegate（教训 ③），改用通知收 resize
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "窗口改尺寸:", NSWindowDidResizeNotification, 窗口)

        内容 = 窗口.contentView()
        网页高 = self.高 * self.网页区比
        gl高 = self.高 - 网页高

        self.gl = GLView.alloc().initWithFrame_(NSMakeRect(0, 0, self.宽, gl高))
        内容.addSubview_(self.gl)

        配置 = WKWebViewConfiguration.alloc().init()
        self.网页 = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, gl高, self.宽, 网页高), 配置)
        内容.addSubview_(self.网页)
        self.网页.loadHTMLString_baseURL_(HTML, None)

        窗口.makeKeyAndOrderFront_(None)
        self.窗口 = 窗口

        print("=" * 80, flush=True)
        print("  P2 验收：同级视图（自动判定）", flush=True)
        print("=" * 80, flush=True)
        self.起始内存 = _内存MB()
        self.尺寸表 = [(1280.0, 820.0), (900.0, 640.0), (1200.0, 700.0)]
        self.截图目录 = 参数.截图 or "/tmp/验收截图"
        os.makedirs(self.截图目录, exist_ok=True)
        self.组 = 0
        # ★ `NSOpenGLView` 是**被动绘制**的：没人要求重绘，`drawRect_` 就一次都不会被调
        #   （实测踩过：帧率采到 0 帧，而画面还是上一帧的内容，看起来"像是好的"）。
        #   所以必须有一个驱动源每帧 setNeedsDisplay_。
        self.渲染驱动 = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 60.0, self, "请求重绘:", None, True)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "第一步:", None, False)

    def 请求重绘_(self, _定时器):
        self.gl.setNeedsDisplay_(True)

    def 窗口改尺寸_(self, _通知):
        self._重排()

    def _重排(self):
        内容 = self.窗口.contentView()
        宽 = 内容.bounds().size.width
        高 = 内容.bounds().size.height
        网页高 = 高 * self.网页区比
        gl高 = 高 - 网页高
        self.gl.setFrame_(NSMakeRect(0, 0, 宽, gl高))
        self.网页.setFrame_(NSMakeRect(0, gl高, 宽, 网页高))

    def 第一步_(self, _定时器):
        print("\n【① 结构与合成前提】", flush=True)
        self.gl.后台载MuJoCo()
        子 = self.窗口.contentView().subviews()
        判("真同级", len(子) == 2, f"contentView 子视图数 = {len(子)}（应为 2）")
        判("非嵌套", self.网页 not in list(self.gl.subviews()),
          "原生视图不是 webview 的子视图（并列，不是嵌进去）")
        层 = self.gl.layer()
        判("原生layer", 层 is not None,
          f"原生视图 layer = {type(层).__name__ if 层 else '无'}"
          f"（wantsLayer={self.gl.wantsLayer()}，AppKit 自动提升）")
        判("网页layer", self.网页.layer() is not None,
          f"webview layer = {type(self.网页.layer()).__name__}")
        应 = self.gl.期望像素()
        判("初始像素尺寸", 应[0] > 0 and 应[1] > 0,
          f"GL 视口应有像素 = {应[0]}×{应[1]}"
          f"（backingScale={self.窗口.backingScaleFactor()}）")
        def _收到DOM(值, 错):
            # ★ PyObjC 的 completion handler **必须返回 None**：
            #   直接写 `lambda v, e: 判(...)` 会把 bool 返回给 ObjC，
            #   于是抛 `OC_PythonException: did not return None, expecting void return value`
            #   → **整个进程被 abort**（本次为此找了很久，因为异常文本被压在栈前面）。
            判("WebView渲染",
              '"ready":"complete"' in (值 or "") and '"文案":true' in (值 or ""),
              f"在 WebKit 进程内查 DOM：{值}")

        self.网页.evaluateJavaScript_completionHandler_(
            "JSON.stringify({ready:document.readyState,"
            " 文案:document.body.innerText.includes('同级并列')})", _收到DOM)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            3.0, self, "第二步:", None, False)

    def 第二步_(self, _定时器):
        print("\n【② 帧率与稳定性（采样 4 秒）】", flush=True)
        self.gl.帧间隔 = []
        self.gl.帧数 = 0
        self.采样起 = time.perf_counter()
        # ★ 内存要**分两段**量：MuJoCo 载入（模型 + 渲染器 + 帧缓冲）本身就会占一大块，
        #   把它算进"泄漏"会得出错误的结论。真正的泄漏看"载入完成之后"的增长。
        self.载入后内存 = _内存MB()
        print(f"  （MuJoCo 载入后 RSS = {self.载入后内存:.0f} MB）", flush=True)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            4.0, self, "算帧率:", None, False)

    def 算帧率_(self, _定时器):
        间 = sorted(self.gl.帧间隔)
        秒 = time.perf_counter() - self.采样起
        帧率 = len(间) / 秒 if 秒 > 0 else 0
        if len(间) < 10:
            判("帧率", False, f"只采到 {len(间)} 帧")
        else:
            中位 = 间[len(间) // 2]
            p99 = 间[min(len(间) - 1, int(len(间) * 0.99))]
            判("帧率", 帧率 >= 30,
              f"{帧率:.1f} fps（中位帧间隔 {中位*1000:.2f} ms，p99 {p99*1000:.2f} ms）")
            判("稳定性", p99 < 中位 * 3,
              f"p99/中位 = {p99/中位:.2f}×（<3× 视为无周期性卡顿）")
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.4, self, "开始resize:", None, False)

    def 开始resize_(self, _定时器):
        print("\n【③ 活体 resize（动画改尺寸，逐组校验）】", flush=True)
        self._下一组()

    def _下一组(self):
        if self.组 >= len(self.尺寸表):
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                0.4, self, "收工:", None, False)
            return
        宽, 高 = self.尺寸表[self.组]
        self.窗口.setFrame_display_animate_(NSMakeRect(140, 140, 宽, 高), True, True)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.6, self, "校验组:", None, False)

    def 校验组_(self, _定时器):
        宽, 高 = self.尺寸表[self.组]
        内容 = self.窗口.contentView().bounds().size
        应 = self.gl.期望像素()
        视口 = self.gl.视口像素
        # GL 视图的对齐看"GL 视口像素"而不是 layer.drawableSize（教训 ②）
        对 = (视口[0] > 0 and 视口[1] > 0
              and abs(视口[0] - 应[0]) <= 2 and abs(视口[1] - 应[1]) <= 2)
        比例 = (abs(self.网页.frame().size.height / 内容.height - self.网页区比) < 0.02
               and abs(self.gl.frame().size.height / 内容.height - (1 - self.网页区比)) < 0.02)
        子 = self.窗口.contentView().subviews()
        判(f"resize#{self.组+1}", 对 and 比例 and len(子) == 2,
          f"窗口 {宽:.0f}×{高:.0f} → 内容 {内容.width:.0f}×{内容.height:.0f}；"
          f"GL 视口 {视口[0]}×{视口[1]}（应 {应[0]}×{应[1]}）；"
          f"比例 webview={self.网页.frame().size.height/内容.height:.2f}"
          f"/gl={self.gl.frame().size.height/内容.height:.2f}"
          f"（应 {self.网页区比:.2f}/{1-self.网页区比:.2f}）；子视图 {len(子)}")
        截图 = os.path.join(self.截图目录, f"resize_{self.组+1}_{int(宽)}x{int(高)}.png")
        subprocess.run(["screencapture", "-x", "-o", "-l",
                        str(self.窗口.windowNumber()), 截图],
                       capture_output=True, text=True)
        self.组 += 1
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.4, self, "下一组:", None, False)

    def 下一组_(self, _定时器):
        self._下一组()

    def 收工_(self, _定时器):
        print("\n【④ 内存与汇总】", flush=True)
        末 = _内存MB()
        判("无泄漏", 末 - self.载入后内存 < 30,
          f"运行期 RSS：载入后 {self.载入后内存:.0f} → 结束 {末:.0f} MB"
          f"（增长 {末-self.载入后内存:+.0f} MB；另：起步 {self.起始内存:.0f} MB，"
          f"其中 MuJoCo 载入一次性占 {self.载入后内存-self.起始内存:+.0f} MB）")
        判("纹理只建一次", self.gl.图 is None or self.gl.纹理 != 0,
          f"GL 纹理号 = {self.gl.纹理}（非 0 = 建好并复用，不是每帧新建）")
        判("MuJoCo画面", self.gl.图 is not None, self.gl.错误 or "已载入并贴进 GL 视口")
        if self.gl.错误:
            判("GL无错误", False, self.gl.错误)

        print("\n" + "=" * 80, flush=True)
        通过 = sum(1 for _, 好, _ in 结果 if 好)
        失败 = [r for r in 结果 if not r[1]]
        print(f"  结果：{通过} 通过 / {len(失败)} 失败", flush=True)
        for 名, _, 说明 in 失败:
            print(f"    ✗ {名}：{说明}", flush=True)
        print("=" * 80, flush=True)
        try:
            with open(os.path.join(self.截图目录, "验收结果.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"通过": 通过, "失败": len(失败),
                          "明细": [{"项": n, "通过": bool(o), "说明": s}
                                 for n, o, s in 结果]}, f, ensure_ascii=False, indent=2)
        except Exception:                                             # noqa: BLE001
            pass
        NSApplication.sharedApplication().terminate_(None)


HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>
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
<div class="条"><span class="点"></span>上：真 WKWebView &nbsp;·&nbsp; 下：NSOpenGLView + 真 MuJoCo 场景
  &nbsp;·&nbsp; 这个页面会被自动 resize 三次</div>
<div class="体">
  <h1>P2 验收：同级并列（自动判定）</h1>
  <div>跑完打印 PASS/FAIL 表。下面的原生区在 resize 过程中应始终跟随、不变形。</div>
  <div class="网格">
    <div class="卡"><b>上</b><span>WKWebView</span></div>
    <div class="卡"><b>下</b><span>NSOpenGLView</span></div>
    <div class="卡"><b>画面</b><span>MuJoCo</span></div>
  </div>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="P2 自动验收：同级视图")
    ap.add_argument("--秒", type=float, default=30.0)
    ap.add_argument("--截图", default=None, help="截图与结果 JSON 的输出目录")
    args = ap.parse_args()
    global 参数
    参数 = args

    应用 = NSApplication.sharedApplication()
    应用.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    委托 = AppDelegate.alloc().init()
    应用.setDelegate_(委托)
    应用.activateIgnoringOtherApps_(True)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        args.秒 + 20, 委托, "收工:", None, False)
    应用.run()
    return 0 if all(好 for _, 好, _ in 结果) else 1


if __name__ == "__main__":
    raise SystemExit(main())
