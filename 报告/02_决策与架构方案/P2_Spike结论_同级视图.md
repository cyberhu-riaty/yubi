# P2 Spike 结论：原生渲染视图 + WKWebView 同窗口并列 —— **成立**

> 执行日期：2026-10-16 ｜ 脚本：`工具/spike/spike_同级视图.py`（Metal）、
> `工具/spike/spike_GL同级.py`（OpenGL）、**`工具/spike/spike_验收.py`（自动验收，14 项）**
> 环境：macOS 26 / Apple M5 / Python 3.10.21 / PyObjC 12.2.2 / mujoco 3.13.0
> 起因：`WebView与原生3D集成调研.md` 把这件事列为**三条外壳路线共同的、必须先验的头号未知**。

---

## 一、结论

**原生渲染视图可以作为 WKWebView 的同级视图放进同一个 NSWindow，没有合成瑕疵。**

而且这条结论对 **Metal 与 OpenGL 两条路径都成立** —— 这一点很重要，因为真实 3D 用的是
OpenGL（MuJoCo 经典渲染器要兼容 profile），不能用 Metal 的结果外推。

| 验证项 | 结果 |
|---|---|
| 子视图数 | **2**（`MetalView` / `NSOpenGLView` + `WKWebView`，同挂 `contentView`） |
| 网页是否被原生视图盖住 | ❌ 没有 —— 网页完整渲染（HTML/CSS 全部生效） |
| 原生视图是否被网页盖住 | ❌ 没有 —— 交界处干净，各自占自己的矩形 |
| 原生视图是否在出帧 | ✅ Metal **543 帧** ／ OpenGL **951~953 帧** |
| **MuJoCo 画面能否进那块区域** | ✅ **能**（下面 §三） |
| 同级布局是否需要"透明" | ❌ **不需要** —— 因此**绕开了 macOS 私有 API**（`drawsBackground`） |
| **自动验收（14 项）** | ✅ **14/14 通过**，见 §一.1 |

### 1.0 自动验收结果（`spike_验收.py`，可重跑）

从"截图看着行"升级成"逐条可判定"。**14 项全过**，关键数字：

| 判定项 | 结果 |
|---|---|
| 真同级 / 非嵌套 | 2 个子视图，原生视图不是 webview 的子视图 |
| layer-backed | 原生 `_NSOpenGLViewBackingLayer` ／ 网页 `NSViewBackingLayer` |
| WebView 真渲染 | 在 **WebKit 进程内**查 DOM：`{"ready":"complete","文案":true}` |
| MuJoCo 画面 | ✅ 后台线程载入并贴进 GL 视口 |
| **持续帧率** | **60.0 fps**（中位帧间隔 16.65 ms） |
| **稳定性** | **p99/中位 = 1.03×**（无周期性卡顿） |
| **活体 resize ×3** | 1280×820 ／ 900×640 ／ 1200×700 —— GL 视口每次都**精确等于**应有像素（2560×918 / 1800×709 / 2400×779），两块比例恒为 0.42/0.58，子视图数恒为 2 |
| **无泄漏** | 运行期 RSS **282 → 282 MB（+0 MB）**；GL 纹理只建 1 个 |
| （参考）启动开销 | 起步 93 MB，MuJoCo 载入一次性 **+189 MB**。拆开量过：**模型约 +90 MB、渲染器约 +60 MB**，其余是首次渲染的驱动侧开销 |
| （参考）离屏缓冲选多大 | **几乎不影响内存**：1280×720 与 640×480 的渲染器开销只差约 8 MB（57 vs 65 MB）。所以 P3 选尺寸时按**画质需要**决定即可，不必为省内存牺牲分辨率 |

> 📌 **"+0 MB" 这个数字比"跑得动"更有价值**：它排除了"每帧新建纹理/drawable"这类
> 会拖垮长时间运行的问题 —— 而那正是 3D 视口最容易犯的错。
>
> 📌 内存要**分两段量**：把 MuJoCo 的一次性载入算进"泄漏"会得出错误结论
> （第一次测就误报 +191 MB）。

### 1.1 为什么"不需要透明"是这条好消息里最重要的一半

调研的结论是：macOS 上让 WKWebView 透明要碰 **私有 KVC key `drawsBackground`**
（`wry` 源码里那句 `// NOTE: Private API` 就是证据），Tauri 与 Wails 都把它藏在构建开关后面。

**同级布局只要"把 webview 摆到 3D 以外的矩形"就行**，根本不需要透明。
所以我们的架构**从第一天起就不在私有 API 上**——不堵死未来上架与系统升级。
**这条要守住**：以后不要为了"3D 从圆角里透出来"之类的效果把透明加回来。

---

## 二、决定性风险自己消失了：`NSOpenGLView` 是 layer-backed 的

调研点名的头号风险原话是：

> "macOS: layer-backed webview vs non-layer-backed GL view. WKWebView is layer-backed;
> classic `NSOpenGLView` is not → overlay/compositing artefacts."

**实测把这条风险直接消掉了。** 传统 `NSOpenGLView` 在现代 macOS 上会被系统**自动提升为
layer-backed**：

```
GL 视图 layer-backed: True / layer=_NSOpenGLViewBackingLayer
```

也就是说，AppKit 自己把"非 layer-backed 的 GL 视图"这件事解决了 ——
两者都是图层支撑的，于是**同一个合成器里并列**，不存在 airspace 冲突。
实测 951 帧无撕裂、无闪烁。

> 📌 这条值得单独记：调研把"未验证"标得很诚实（`[UNVERIFIED: no first-party doc states
> "CAMetalLayer sibling of WKWebView is artefact-free"]`），而实测答案是**比预期更好**——
> 连 OpenGL 这条更老的路径也是干净的。

---

## 三、3D 画面怎么进那块区域：两条都通，推荐"离屏 + 纹理"

| 路线 | 验证情况 | 评价 |
|---|---|---|
| **A. `mujoco.Renderer` 离屏渲染 → 上传成 GL 纹理 → 铺满视口** | ✅ **本次走通**（真 iiwa14 场景显示在视口里） | **推荐**。它自带独立 GL 上下文（macOS 上 cgl），**不与我们视图的上下文争 profile**；且天然支持"渲到任意尺寸" |
| B. 在视图自己的上下文里直接 `mjv_updateScene` + `mjr_render` | 另有一份已验证的参考实现（`输出/render_probe/`，2560×1440 = 11.4 ms/帧） | 质量更高（有真阴影/反射），但要求上下文是**兼容 profile**、且窗口层由一个我们完全掌控的宿主创建 |

**为什么推荐 A 起步**：我们现在是"Python 进程 + 我们自己的 NSWindow"，用 A 不必接管
整个窗口层与 GL 上下文生命周期，风险最小；等 3D 交互（轨道相机、拾取）需求变重、或
性能成为瓶颈时，再评估切到 B。

### 3.1 实测踩到的**七个**坑（都已修，值得记）

| # | 坑 | 症状 | 原因与修法 |
|---|---|---|---|
| 1 | `CAMetalLayer.drawableSize` 默认 **0×0** | **一块纯黑，且不报任何错**，出帧数 0 | 只 `setFrame_` 不够，必须显式 `setDrawableSize_(宽×scale, 高×scale)`（三处：建好后 / 入窗后 / 尺寸变化时） |
| 2 | PyObjC 里 `colorAttachments()[0]` **不可下标** | `TypeError: ... is not subscriptable` | 用显式方法名 `objectAtIndexedSubscript_(0)` |
| 3 | MuJoCo 离屏渲染默认**没相机**、且帧缓冲默认只有 640×480 | 均值 1.2（看着像"渲染失败"，其实**机器人不在画面里**）；渲 760 宽报 `Image width 760 > framebuffer width 640` | 显式给 `MjvCamera`；并在建 Renderer **之前**设 `model.vis.global_.offwidth/offheight`。另：本机签名是 `update_scene(data, camera=…, scene_option=…)` —— **没有 `scene=`**（按老文档写会 TypeError） |
| 4 | **在 AppKit 回调里建第二套 GL 上下文** | 进程**直接 SIGTRAP**，Python 侧无 traceback（`faulthandler` 抓不到、`objc.setObjCExceptionHandler` 也不触发） | `mujoco.Renderer` 自建 CGL 上下文；而 `prepareOpenGL`/定时器/`drawRect_` 都跑在 `CATransaction … WithDisplayLink` 事务里。**必须挪到独立线程**（GPU 资源仍只在绘制路径里建） |
| 5 | **PyObjC completion handler 返回了非 None** | `OC_PythonException: did not return None, expecting void return value` → **整个进程 abort**，而异常文本被压在栈前面、极难看到 | `evaluateJavaScript_completionHandler_` 的回调**必须返回 None**；别写 `lambda v,e: 判(...)`（`判` 返回 bool） |
| 6 | **`NSOpenGLView` 是被动绘制的** | 帧率采到 **0 帧**，而界面上还留着上一帧内容 —— **看起来像好的** | 必须有人每帧 `setNeedsDisplay_(True)`，否则 `drawRect_` 一次都不会被调 |
| 7 | `窗口.setDelegate_(任意对象)` | **直接 SIGTRAP**（与那个对象有没有实现 `windowDidResize_` 无关） | 改用**通知**收 resize：`NSNotificationCenter` 观察 `NSWindowDidResizeNotification` |

> 📌 坑 5、6、7 有一个共同点：**症状都在"别处"**。
> 坑 5 表现为"进程莫名 abort"、坑 6 表现为"界面看起来正常"、
> 坑 7 表现为"设个 delegate 就死"。定位它们靠的是**读系统崩溃报告**
> （`~/Library/Logs/DiagnosticReports/*.ips` 里有 `+[NSApplication _crashOnException:]`
> 与真正的异常文本），而不是靠猜代码。

> 坑 1 与坑 3 的共同教训：**"全黑"不等于"没跑起来"**。
> 坑 1 是真没出帧，坑 3 是出了帧但画面里没东西，坑 6 更阴 —— 出了帧但**再也没出过**，
> 而屏幕上还留着旧内容。三者症状相似，必须分别取证。

---

## 四、对架构的直接影响

按调研给的三种结局对号入座：

| 结局 | 本次实测 | 影响 |
|---|---|---|
| ✅ 无瑕疵 | **命中这一条** | **三条外壳路线全部可选** —— 选型从"能不能做"变成"打包/团队技能"问题 |
| ⚠️ 有瑕疵但可接受 | — | 不适用 |
| ❌ 冲突无法规避 | — | 不适用（不需要退到"独立贴附窗口"或纯自研窗口） |

**具体落到我们的选择：**

1. **pywebview / 自建 PyObjC 宿主这条路可以放心走**（P2 的第一步已经用 PyObjC 直建验证过，
   不依赖 pywebview 也行）。
2. **中区那一格可以从"占位"换成真 3D**：一个 `NSOpenGLView`（或 CAMetalLayer 视图）挂在
   `contentView` 上，Web 界面负责其余部分。
3. **官方 Studio 窗口不再是必需品**：3D 与界面都由我们自己的窗口承载，
   跨平台时"平台适配层"只需抽象四个能力（建窗口 / 挂 WebView / 取 3D 视口矩形 / 同级组合）
   —— 这与总方案 §3 的分层一致。

---

## 五、还没验的（诚实清单）

| 项 | 为什么没验 | 风险 |
|---|---|---|
| **Windows 上同样成立** | 本机没有 Windows | 中。调研指出 Windows 侧是 `add_child`/子 HWND，且有已知的"子 webview 在同步命令里死锁"（wry#583）；需要一台 Windows 机器复验 |
| macOS 上**无显示器**时 | 无法拔掉显示器 | 低（我们的形态是桌面软件，本来就要有屏） |
| ~~拖动改变窗口大小时的**逐帧**表现~~ | ✅ **已验**（动画 resize ×3，每次 GL 视口精确等于应有像素；p99/中位 1.03× 说明过程中没有卡顿） | — |
| 3D 的**交互**（轨道相机、拾取、拖拽） | spike 只验"画面进得来" | 中。这是下一步的工程量，不是未知风险 |
| ~~离屏渲染 → 纹理这条路的**性能上限**~~ | ✅ **已验**：端到端（含纹理上传）**60.0 fps**，p99 17.09 ms —— 即这条路能撑满 60 Hz 视口 | — |

**P2 的边界（避免误解）**：P2 是**冻结原点**，交付的是「架构能不能走」的答案，
**不交付功能**。「能用的 3D 视口」（连续渲染 + 轨道相机 + 与仿真循环对接）不属于 P2 ——
它需要**宿主窗口里的一个视口槽**，而那个宿主是 **P3** 的交付物。

所以正确的顺序是：**P3 建宿主 → 紧接着把视口接进去**（视口是那个接口的第一个真消费者，
接口的设计离不开它）。二者**捆在一起做**，分开做等于先按想象写接口、再回头改。
