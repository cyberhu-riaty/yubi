"""桌面和浏览器共用的仿真运行核心。

桌面窗口占用主线程，仿真在线程中推进物理并通过消息通道发布状态。
模型切换时按项目配置重新装配插件。
"""
from __future__ import annotations

import os
import env_config
import queue
import sys
import threading
import traceback

# 让本模块无论在哪个目录被导入，都能 import 到同目录的核心模块
_software_dir = os.path.dirname(os.path.abspath(__file__))
if _software_dir not in sys.path:
    sys.path.insert(0, _software_dir)

import plugin_system as plugin_framework                                           # noqa: E402
import project_registry as _project                                           # noqa: E402
import model_loader as _model_loader                                           # noqa: E402

import model_bridge as _model_bridge                                            # noqa: E402
import simulation_control as _simulation_control                              # noqa: E402
import control_bridge as _control_bridge                                         # noqa: E402
from model_bridge import ProjectState                                           # noqa: E402

import web_bridge as _web_bridge                                                 # noqa: E402


class _ViewportStateSnapshot:
    """给原生 3D 与运行信息面板的线程安全数值副本。"""

    __slots__ = ("state", "state_sig", "time", "qpos", "qvel", "ctrl",
                 "target_qpos", "target_qvel", "ctrlrange", "joint_names")

    def __init__(self, snapshot, data, model) -> None:
        self.state = snapshot.state
        self.state_sig = snapshot.state_sig
        self.time = float(data.time)
        self.qpos = data.qpos.copy()
        self.qvel = data.qvel.copy()
        self.ctrl = data.ctrl.copy()
        try:
            from trajectory_runtime import current_reference
            self.target_qpos, self.target_qvel = current_reference(data)
        except Exception:                                             # noqa: BLE001
            self.target_qpos, self.target_qvel = None, None
        self.ctrlrange = model.actuator_ctrlrange.copy()
        self.joint_names = [
            str(plugin_framework.mujoco.mj_id2name(
                model, plugin_framework.mujoco.mjtObj.mjOBJ_JOINT, index) or f"joint_{index}")
            for index in range(int(model.njnt))
        ]


def apply_theme(window_plugins: list) -> None:
    """界面主题不在这里应用 —— 见下方说明。

    ★ 踩过的坑：官方 `ux.setup_theme()` 必须在**窗口和 ImGui 上下文都建好之后**才能调用。
      在窗口创建之前调用会直接 **段错误（segfault）**，整个进程崩掉、连窗口都开不出来。
      所以主题的实际应用放在 `界面桥.py` 的「首帧」处理器里（那时上下文已经就绪）。

    主题值也可以手动改：~/.mujoco.ini 里的 `[Studio][UX] theme=0/1/2`
    （0=浅色 1=深色 2=经典），或者在窗口里打开 Options → Theme 菜单改。
    """
    return None


# ---------------------------------------------------------------------------
# 宿主窗口（P3）用的命令队列
# ---------------------------------------------------------------------------
# 跨线程命令通过 Queue 传递，排空时不会丢掉并发入队的命令。
command_queue_obj: queue.Queue = queue.Queue()


def _enqueue_local(message) -> None:
    command_queue_obj.put_nowait(message)


def _drain_local_queue() -> list:
    result = []
    while True:
        try:
            result.append(command_queue_obj.get_nowait())
        except queue.Empty:
            return result


# ---------------------------------------------------------------------------
# 当前运行会话：让窗口能等待“真的初始化完成”，也能在退出时要求仿真停稳
# ---------------------------------------------------------------------------
class _RuntimeSession:
    def __init__(self, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        self.ready = threading.Event()
        self.thread: threading.Thread | None = None
        self.error: BaseException | None = None


_session_lock = threading.Lock()
_current_session: _RuntimeSession | None = None


def _register_session(session: _RuntimeSession) -> None:
    global _current_session
    with _session_lock:
        _current_session = session


def wait_until_ready(timeout: float = 15.0) -> tuple[bool, str]:
    """等待仿真完成模型和插件初始化；供宿主窗口启动前调用。"""
    with _session_lock:
        session = _current_session
    if session is None:
        return False, "仿真会话还没有创建"
    if not session.ready.wait(max(0.0, float(timeout))):
        return False, f"等待仿真就绪超时（{timeout:g} 秒）"
    if session.error is not None:
        exc = session.error
        return False, f"仿真初始化失败：{type(exc).__name__}: {exc}"
    return True, "ok"


def stop(timeout: float = 3.0) -> tuple[bool, str]:
    """请求当前仿真停止并等待线程退出；重复调用也是安全的。"""
    with _session_lock:
        session = _current_session
    if session is None:
        return True, "没有运行中的仿真"
    session.stop_event.set()
    thread = session.thread
    if thread is not None and thread is not threading.current_thread() and thread.is_alive():
        thread.join(timeout=max(0.0, float(timeout)))
    if thread is not None and thread.is_alive():
        return False, f"仿真线程在 {timeout:g} 秒内没有退出"
    return True, "ok"

# ---------------------------------------------------------------------------
# 状态观察者（P3 的 3D 视口用）
# ---------------------------------------------------------------------------
# ★ 为什么需要：宿主窗口里的 3D 视口要跟着仿真动，但它和仿真在**不同线程**，
#   不能共享 `MjData`。最省事又安全的办法是把每步的集成状态搬过去，
#   视口用它**自己那份** MjData `mj_setState` + `mj_forward`。
#
#   为什么不用 `Web桥.水龙头.最近状态`：那条通道只在**有 web 出口**时才装上，
#   而宿主窗口是 `无窗` 形态，水龙头可能根本没装（实测就是这样，同步次数一直是 0）。
#   回调挂在这里最直接：与"状态是怎么算出来的"在同一处，不依赖任何桥。
#
#   ⚠️ 回调在**仿真线程**里被调用，所以它只能做"拷贝"这种没有竞态的事，
#      绝不能在里头碰 AppKit（那必须在主线程）。
state_observer = None


def set_state_observer(callback) -> None:
    """注册"每步状态"的观察者。传 None 取消。"""
    global state_observer
    state_observer = callback


# 模型事件观察者：同上，但只在**换模型**时被调用。
#   ★ 为什么也要有：`无窗` 形态下没有官方 viewer 端点，`ModelEvent` 原本
#     根本没机会广播出去 —— 表现是**界面一直显示"后端还没有报模型"**，
#     尽管模型早就装好、3D 视口也在正常渲染（很能骗人：画面是对的，状态栏是空的）。
model_observer = None


def set_model_observer(callback) -> None:
    """注册"换模型"的观察者（参数是 ModelEvent 消息）。传 None 取消。"""
    global model_observer
    model_observer = callback


def _broadcast_model_event(event) -> None:
    """把模型事件也送一份给观察者（web 出口用它填界面状态）。

    参数就是官方那条 `messages.ModelEvent` —— 和 `发送出口.发送` 收到的是同一个对象，
    这样"界面看到的东西"与"官方 viewer 看到的东西"永远一致。
    """
    if model_observer is None or event is None:
        return
    try:
        model_observer(event)
    except Exception:                                                 # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 发送出口：**一个可变持有者**，避免"重绑名字"造成的自递归
# ---------------------------------------------------------------------------
# ★ 这里有一个真实事故，写下来免得再犯：
#   原来出口是一个局部函数 `发送`，装 Web 水龙头时写成 `龙头, 发送 = 安装(发送)`
#   想"就地替换"。但有窗分支的函数体本身就是 `仿真端点.send_to_viewer(消息)`，
#   名字一换、又和闭包变量同名，调用链就变成了 发送 → 水龙头 → 发送 → …
#   —— 实测 `RecursionError`，**原生界面启动即崩**（而无窗分支恰好没事，
#   因为它的函数体是"追加到队列"，不回头调自己，所以测试全绿却漏了这条）。
#
#   修法不是"小心点别重绑"，而是**从结构上不让它可能发生**：
#   出口放在一个对象里，装水龙头只改对象内部，外部永远只叫同一个名字。
# ---------------------------------------------------------------------------
class _SendOutlet:
    """所有发布器/桥接层抓住的都是**这一个** `发送`；内部实现可随时替换。"""

    def __init__(self) -> None:
        self._implementation = None
        self.tap_installed = False
        self.call_count = 0

    def install(self, implementation) -> None:
        self._implementation = implementation

    def send(self, message) -> None:
        self.call_count += 1
        self._implementation(message)


send_outlet = _SendOutlet()


def command_queue() -> queue.Queue:
    """给宿主窗口用：拿到仿真循环每圈排空的那个队列。"""
    return command_queue_obj


def _start_impl(config, model_path: str, window_class, plugins: list, registry, on_model_loaded,
            project_name: str = "", headless: bool = False, background_thread: bool = False,
            initial_messages: list | tuple | None = None, experiment_name: str = ""):
    """启动官方 Studio 窗口 + 我们的插件。

    参数
      配置        : 官方 ViewerConfig（标题、宽高、gfx 模式）
      模型路径    : 要加载的 MJCF/XML
      窗口类      : 官方 viewer_app.ViewerApp（19 个现成面板都靠它）。**无窗模式不用**
      插件列表    : 启动时按项目装配出来的控制算法实例
      注册表      : plugin_system.SafeRegistry（带出错隔离）
      通知模型加载: plugin_system.notify_model_loaded（让插件拿到 model/data）
      项目名      : 启动时选中的项目名（换模型后会被换成新项目的名字）
      后台线程    : 仅在 `无窗=True` 时有意义 —— 让仿真跑在**后台线程**，
                    把主线程让给宿主窗口（AppKit）。宿主窗口形态用这个。
      预置消息    : 清理上一次会话残留后，为本次会话预先放入的通用命令消息。
                    同步浏览器入口用它装载实验初值；不包含任何实验或机器人逻辑。
      experiment_name: 可选的 ExperimentRegistry 注册名；只启用通用实验运行器，
                    空字符串表示普通工作台模式。
      无窗        : **不开官方窗口**（P2 的"无窗宿主"）。此时：
                    · 不建线程端点、不建 ViewerHandle、不加载 ImGui 面板；
                    · 仿真循环直接坐在**主线程**上转（原来它在仿真线程里）；
                    · 界面只剩 Web（数据出口照常工作，命令由 `命令桥` 注入本地队列）。
                    ★ 为什么做成参数而不是复制一份启动流程：界面换了，**数据层一模一样**
                      （模型装载、项目装配、7 个桥、参数/辨识/录制全不动）。复制一份
                      等于把 700 行里的每一处修复都要维护两遍 —— 那是必然分叉的写法。

    返回：0 正常 / 1 出错
    """
    import mujoco
    # 全部走适配层（`runtime/official_api.py`），消息类仍使用官方原始对象。
    # 直接 import mujoco.experimental.* 已被断言禁止（见 tools/selfchecks/official_api_selfcheck.py）。
    from official_api import launch_native, launch_thread, messages, viewer_handle

    # 同一进程内再次启动（主要用于自检）时，不能把上一次残留消息带进新模型。
    _drain_local_queue()
    for message in list(initial_messages or ()):
        command_queue_obj.put_nowait(message)

    # 将模型路径提供给持有独立渲染数据的宿主视口。
    env_config.write("YUBI_CURRENT_MODEL", str(model_path or ""))
    env_config.write("YUBI_CURRENT_PROJECT", str(project_name or ""))

    # ---- 1. 消息通道：两种模式共用同一套"发/收"接口 ----
    #   有窗：官方线程端点（viewer 线程 ↔ 仿真线程），窗口侧每帧派发。
    #   无窗：一个**本地队列**，仿真循环自己排空（命令由 `命令桥.命令入队` 塞进来）。
    #   ★ 抽象成一个出口就够（`发送出口.发送`）：所有发布器与桥接层只认它，
    #     于是"界面是 ImGui 还是 Web"对它们完全透明。
    #     为什么是**对象**而不是局部函数：见下面 `_发送出口` 的说明（自递归事故）。
    if headless:
        viewer_endpoint, simulation_endpoint = None, None

        # ★ 无窗形态下，仿真**没有官方 viewer 端点**，界面只能靠 Web 桥。
        #   所以这里要主动把发出的消息送进 Web 的发布表 —— 否则界面会一直停在
        #   "后端还没有报模型 / 还没有收到任何帧"，而 3D 视口明明在正常渲染
        #   （画面是对的、状态栏是空的，非常能骗人）。
        #
        #   ★ 而且必须走**同一套契约转换**（`Web桥.安装水龙头`），不能自己另写一遍
        #     `[type(消息).__name__ → 主题]` 的映射：那样两边迟早不一致，
        #     而且白名单也会分叉。水龙头那套已经处理好了"哪些消息给界面"。
        def _send_to_queue(message) -> None:
            _enqueue_local(message)

        try:
            # ⚠️ 这里**不要再写 `import Web桥 as _Web桥`**！模块顶部已经有
            #    `import Web桥 as _Web桥`（第 48 行）。在函数里再 import 一次，
            #    Python 会把 `_Web桥` 判定为**整个函数的局部变量**，
            #    于是函数前面（第 268 行那段 Web 接口初始化）引用它时直接
            #    `UnboundLocalError: local variable '_Web桥' referenced before assignment`
            #    —— 而且只在**有窗模式**（官方 ImGui 界面）才炸，无窗模式反而正常，
            #    所以回归容易漏掉。已因此把原生界面打不开过一次，别再犯。

            class _local_target:
                """冒充官方端点：只实现水龙头需要的那个方法。

                水龙头会把消息转成 (主题, 负载) 再调 `下一个`，所以这里
                就是"把本地队列当端点"用的 —— 命令依旧进队列，桥接由水龙头做。
                """

                @staticmethod
                def send_to_viewer(message) -> None:                     # noqa: N805
                    _enqueue_local(message)

            _tap, _ = _web_bridge.install_faucet(_local_target())
            send_outlet.install(_tap)
        except Exception as _exc:                                    # noqa: BLE001
            print(f"  ⚠ 无窗形态没能接上 Web 出口（界面会收不到模型/指标）：{_exc}",
                  flush=True)
            send_outlet.install(_send_to_queue)

        def drain_inbox() -> list:
            return _drain_local_queue()

    else:
        viewer_endpoint, simulation_endpoint = launch_thread.make_thread_endpoints()

        def _send_to_window(message) -> None:
            simulation_endpoint.send_to_viewer(message)

        send_outlet.install(_send_to_window)

        def drain_inbox() -> list:
            # 官方的两个通道：事件与快照。拆开自己写是为了插入出错隔离
            # （见下面循环里的说明）。
            return list(simulation_endpoint.get_viewer_events()) + list(simulation_endpoint.get_viewer_snapshots())

    # ---- 1b. Web 接口（方案 B 的 P0）：把消息抄一份给浏览器 ----
    #   ★ 顺序很重要：所有发布器都在构造时抓走 `发送`
    #     这个函数对象，所以水龙头必须**在这里**装（它们构造之前）。
    #     装晚了它们抓到的还是原件，Web 就一条数据都收不到。
    #   ★ 开关：环境变量 驭臂_关Web=1 打开时完全跳过（排查用）。
    _web_tap = None
    if env_config.read("YUBI_DISABLE_WEB") not in ("1", "true", "yes"):
        try:
            _web_port = int(env_config.read("YUBI_WEB_PORT") or _web_bridge.DEFAULT_PORT)
        except ValueError:
            _web_port = _web_bridge.DEFAULT_PORT
        try:
            bridge = _web_bridge.start(port=_web_port)
            if bridge.enabled:
                # 包装当前发送实现，再安装包装后的实现，避免递归。
                # ★ 包的是**出口对象的实现**，不是某个局部名字 ——
                #   这样无论有窗/无窗，调用链永远只有一层，不可能自递归。
                _web_tap, _new_implementation = _web_bridge.install_faucet(send_outlet._implementation)
                if _web_tap is not None:
                    send_outlet.install(_new_implementation)
                    send_outlet.tap_installed = True
                print(f"【Web】数据出口已开： {_web_bridge.health()['address']}"
                      f"（浏览器打开即可看真实指标流；关掉：--无web 或 驭臂_关Web=1）",
                      flush=True)
            else:
                print(f"⚠ Web 桥没起来（不影响使用）：{bridge.errors}", flush=True)
        except Exception as exc:                                     # noqa: BLE001
            print(f"⚠ Web 桥不可用（不影响使用）：{type(exc).__name__}: {exc}", flush=True)

    # ---- 2. 仿真侧句柄：它负责"每转一圈派发 StepEvent"这件事 ----
    #         注意：这里不把插件交给官方句柄，而是交给我们自己的安全注册表，
    #         所以下面循环里调的是 registry.process_message(...) 而不是 handle.sync(...)。
    #   ★ 无窗模式没有官方端点，也就没有句柄 —— 仿真状态直接住在
    #     `当前模型/当前数据` 里（见仿真循环起手）。下面所有 `句柄.` 的用法
    #     都已经分支处理过，这里给个占位对象只为 `finally` 里的 close 能调到。
    if headless:
        class _no_handle:
            model = None
            data = None

            def close(self) -> None:
                pass
        handle = _no_handle()
    else:
        handle = viewer_handle.ViewerHandle(simulation_endpoint)

    stop_event = threading.Event()
    session = _RuntimeSession(stop_event)
    _register_session(session)
    errors = {}

    # ---- 3. 仿真线程 ----
    def simulation_loop():
        session.thread = threading.current_thread()
        try:
            import time as _time
            import numpy as _np

            # 当前项目名（换模型时变）+ 当前算法实例表。
            # ★ 用 nonlocal 让下面的 `_装配项目()` 能改写它们：
            #   仿真循环里的 插件列表 必须**始终是当前这一组**，
            #   否则每步派发用的还是启动时那一批老算法。
            current_project_name = str(project_name or "")

            # 无窗模式：没有 ViewerHandle，仿真状态就住在这两个变量里（有窗时它们是镜像）。
            current_model = None
            current_data = None

            # 这两样在下面创建，但 `_装配项目()` 要用 —— 所以先声明成 None 占位。
            # ★ 为什么允许它们是 None：装配通道和参数/发布通道是**互相独立**的，
            #   任何一条起不来都不应该让另一条失效（各自 try/except 兜底）。
            #   启动时的第一次装配发生在它们就绪之前，所以必须能容忍 None。
            parameter_applier = None
            project_publisher = None
            model_applier = None
            gravity_applier = None            # 内置件，注册在下面；这里先占位给 `_装配项目` 用
            simulation_state_publisher = None
            ControlTargetApplier = None
            control_state_publisher = None
            experiment_runner = None
            current_algorithm_info: list = []
            current_algorithm_config: list[str] = []  # 模块名且保留执行顺序；Reset 用它重建同一组算法
            current_control_disk = ""            # 真正驱动机械臂的那个算法（界面显示用）
            current_overrides: list = []      # 输出被整体盖掉的算法（界面显示用）
            currently_persisted = True            # 当前这组算法是否与项目文件一致（界面 Save 按钮用）
            current_algorithm_library: list = []        # 算法库里全部可选算法（算法变化时才重算，见 装配前刷新）

            model = _model_loader.load_model(mujoco, model_path)
            data = mujoco.MjData(model)
            current_model, current_data = model, data
            keywords = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
            if keywords >= 0:
                mujoco.mj_resetDataKeyframe(model, data, keywords)
            mujoco.mj_forward(model, data)

            def _reset_pose(model, data) -> str:
                """把机器人摆回**默认姿态**（home 关键帧），并清掉速度。返回一句说明。

                ★ 为什么要有它（用户实测报上来的问题）：
                  换算法时物理状态**默认是不动的**，而多数控制算法"拿第一次看到的位置
                  当基准"。于是从算法 1 切到算法 2 时，算法 2 是在**算法 1 留下的姿态**
                  上开始控制的 —— 现象就是"机器人再也回不到默认位置了"。
                  实测：正弦摆动跑 400 步后偏离默认姿态 0.33 rad，切到关节 PD 后
                  它把这个姿态当了基准。

                做法与内置件 `重力应用器._自己复位()` 是同一套（一致很重要，
                否则同一个概念会有两种行为）：
                  ① 有 `home` 关键帧 → 用它（模型自带的"默认姿势"）
                  ② 没有 → `mj_resetData`（回到 XML 里的初始 qpos）
                  ③ 最后必须 `mj_forward`：复位只写了 qpos/qvel，
                     派生量（site 位置、雅可比等）要重算，否则画面和算法读到的还是旧值。
                """
                if model is None or data is None:
                    return ""
                try:
                    has_home = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home") >= 0
                    if has_home:
                        key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
                        mujoco.mj_resetDataKeyframe(model, data, key)
                    else:
                        mujoco.mj_resetData(model, data)
                    data.qvel[:] = 0.0            # 关键帧不一定清速度；不清就会"带着旧速度出发"
                    data.ctrl[:] = 0.0            # 上一组算法写下的力矩也清掉
                    mujoco.mj_forward(model, data)
                    return (f"（已把机器人重置到默认姿态"
                            f"{'（home 关键帧）' if has_home else '（模型初始 qpos）'}）")
                except Exception as exc:                                      # noqa: BLE001
                    return f"⚠ 重置姿态失败（算法照常在当前姿态上接手）：{type(exc).__name__}: {exc}"

            # ---- 项目装配：换模型 → 换一组算法（方案 C 的核心）----
            # ★ `发送` 这个名字只在**有窗**分支里存在（它是那边的局部函数）。
            #   而无窗模式也要用发布器（模型状态/参数表/辨识状态/指标全靠它），
            #   原来直接用 `发送` → `NameError` → **整段装配失败** → 界面永远
            #   显示"后端还没有报模型 / 还没有收到任何帧"，而 3D 视口照常渲染
            #   （画面是对的、状态栏是空的，非常能骗人）。
            #   所以统一走 `发送出口` —— 它结构上就是为"实现可换"而生的
            #   （见 `_发送出口` 的说明）。
            def _publish_outlet(message) -> None:
                send_outlet.send(message)

            # ★ 插件桥必须在 `_装配项目` **之前**备好。
            #   原因：`_装配项目` 里要用 `_插件桥`，它是**闭包自由变量** ——
            #   如果赋值语句写在后面，那么在 `_装配项目` 被调用时它还没绑定，
            #   直接 `NameError: free variable '_插件桥' referenced before assignment`。
            #
            #   这个坑我在本项目栽了**三次**（`发送`、`_Web桥`、`_插件桥`），
            #   共同点都是"赋值/import 写在使用点之后"。所以这里的规矩是：
            #   **凡是被嵌套函数用到的模块级/闭包名，都放到最前面统一备好。**
            try:
                import plugin_bridge as _plugin_bridge
            except Exception as _exc:                                    # noqa: BLE001
                print(f"⚠ 插件目录不可用（插件视图将没有数据）：{_exc}")
                _plugin_bridge = None
            # 轨迹规划器：记录航点 → 调内核 → 发结果
            #   ★ 必须在 `_装配项目` 之前建好（它是闭包变量，见上面的规矩）
            try:
                import planning_bridge as _planning_bridge
                _planner = _planning_bridge.TrajectoryPlanner(
                    _publish_outlet,
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                registry.add_plugin(_planner)
                print("【规划】就绪（记录航点 → 规划 → 看校验数字）", flush=True)
            except Exception as _exc:                                    # noqa: BLE001
                print(f"⚠ 轨迹规划不可用（规划视图将不能规划）：{_exc}")
                _planner = None

            # 病态检出（观测核心）：现有聚合指标可靠检出超差/饱和；
            # 振荡/发散需逐关节有符号信号，不能拿最大绝对值硬猜。
            #   ★ 必须在循环之前建好（循环里每步都要喂它）。
            try:
                import observation_core as _observation_core
                _observation = _observation_core.ObservationCore(_publish_outlet)
                print("【观测】病态检出已就绪（跟踪超差 / 饱和；振荡与发散等待逐关节有符号指标）",
                      flush=True)
            except Exception as _exc:                                    # noqa: BLE001
                print(f"⚠ 病态检出不可用（监控页不会有告警）：{_exc}")
                _observation = None

            # 设备连接桥：部署页的控制端（模拟后端 + 安全层 + 审计）
            #   ★ 界面只"请求"，进「运行」必须由人显式点按（规格 B3-8）。
            try:
                import devices.connection_bridge as _connection_bridge
                _device_bridge = _connection_bridge.DeviceBridge(
                    _publish_outlet,
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    int(getattr(model, "nq", 6) or 6),
                )
                registry.add_plugin(_device_bridge)
                print("【设备】部署页已就绪（模拟后端；**不是真机**）", flush=True)
            except Exception as _exc:                                    # noqa: BLE001
                print(f"⚠ 设备连接不可用（部署页只能导出包）：{_exc}")
                _device_bridge = None

            # 部署器：导出可带走的包（**不连真机** —— 这个软件没有传输层）
            try:
                import deployment_bridge as _deployment_bridge
                _deployer = _deployment_bridge.Deployer(_publish_outlet,
                                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                registry.add_plugin(_deployer)
                print("【部署】就绪（可导出部署包；真机连接未实现）", flush=True)
            except Exception as _exc:                                    # noqa: BLE001
                print(f"⚠ 部署器不可用（部署视图将不能导出）：{_exc}")

            def _assemble_project(new_project_name: str, new_model, new_data, new_model_path: str,
                          algorithm_overrides: list | None = None, persist: bool = False,
                          reset_pose: bool = False,
                          keep_persisted_state: bool | None = None) -> list[str]:
                """按项目清单重新装配算法，装进注册表并通知各插件。

                返回给人看的报告行（会打进终端）。**这个函数必须在仿真线程里调用** ——
                它要换掉正在被仿真的那组插件实例。

                `算法覆盖` / `落盘` / `重置姿态` 给【Algorithms】面板用（界面当场选算法）：
                  · `算法覆盖` 非 None → 用用户选的这一组，**忽略项目文件里的 `算法` 字段**；
                  · `落盘=True` → 同时把这组选择写回项目文件（【Save】按钮）。
                    两者分开是刻意的：Apply 只临时生效（试错不会弄坏预设），Save 才落盘；
                  · `重置姿态=True` → 装配**之前**先把机器人摆回默认姿态（home 关键帧）。
                    ★ 这一条是"换算法后机器人回不到默认位置"的解药，见下面 `_重置姿态()`。
                """
                nonlocal plugins, current_project_name, project_publisher, current_algorithm_info, currently_persisted
                nonlocal current_algorithm_config
                nonlocal current_control_disk, current_overrides, gravity_applier
                import plugin_assembler as _assembler

                # 新模型/新算法不能沿用上一组的时序和告警。否则相邻实验会在监控页
                # 同时出现两张同名卡片，甚至把切换瞬间误判成突变。
                if _observation is not None:
                    _observation.clear()

                data = _project.load_project(new_project_name) if new_project_name else None
                if algorithm_overrides is not None:
                    run_config = [str(x) for x in algorithm_overrides if str(x).strip()]
                else:
                    run_config = [str(x.get("plugin", "")) for x in _project.parse_algorithms(data)
                            if isinstance(x, dict) and str(x.get("plugin", "")).strip()]

                # 先复位姿态，让新控制器以默认位置初始化。
                reset_note = _reset_pose(new_model, new_data) if reset_pose else ""

                new_instance, report = _assembler.assemble_project(
                    data, new_project_name, model=new_model, algorithm_override=algorithm_overrides)
                if reset_note:
                    report.insert(0, reset_note)

                # ① 把项目里存过的参数灌回插件（"上次调好的 KP/KD"要能延续）
                restore = _restore_parameters(new_project_name, new_instance)
                if restore:
                    report.append(restore)

                # ② 换掉注册表里的用户算法（内部插件保持不动，见 SafeRegistry.set_user_plugins）
                from trajectory_runtime import clear_trajectory_visualization
                clear_trajectory_visualization()
                registry.set_user_plugins(new_instance)

                # ③ 让常驻的内部插件重新认识这一组算法。
                #    ★ 这一步不能省：参数应用器原来只在启动时绑定一次，
                #      不重绑的话界面滑杆会"拖了没反应且不报错"（静默失效）。
                #    ★ 用 `is not None` 判断而不是无条件调用：启动时的第一次装配
                #      发生在参数桥建好**之前**（那时它还不存在），这是正常的 ——
                #      装配和参数桥是两条独立的通道，谁先就绪都不该让另一个失败。
                if parameter_applier is not None:
                    parameter_applier.rebind(registry)

                # ④ 通知每个插件"模型 + 这一组算法是什么"
                algorithm_info = plugin_framework.collect_algorithm_info(new_instance)
                #   谁在控盘 / 谁被覆盖 —— 供界面显示（见 装配器._抢方向盘体检 的说明）。
                #   判定依据是算法自己声明的 `接管控制`（默认 True）：
                #   多个都声明接管时，**只有最后一个真正生效**，前面的被整体覆盖。
                _control_disk = [a["name"] for a in algorithm_info if a.get("takes_control", True)]
                control_disk = ""
                overrides: list = []
                if len(_control_disk) == 1:
                    control_disk = _control_disk[0]
                elif len(_control_disk) > 1:
                    control_disk, overrides = _control_disk[-1], _control_disk[:-1]
                current_control_disk, current_overrides = control_disk, overrides
                # ★ 通知"所有插件"，不只是新装配的用户算法 —— 内置件也要收到模型。
                #   这里踩过一个很隐蔽的坑：原来传的是 `新实例`（只含用户算法），
                #   于是 `重力应用器` 这种**内置件永远收不到 `收到模型`**：
                #   它就不复位、不冻结，而物理从第一帧就在跑 —— 现象是
                #   "刚进模型就掉到偏离 home 0.77 rad 的位置，然后被冻在那个歪姿上"。
                #   通知列表改用 `注册表._目标`（= StepControl + 用户算法 + 全部内置件）。
                #   `算法信息` 仍然只含用户算法 —— 它表达的是"这一组装了哪些算法"，
                #   内置件不该出现在算法清单与录制元信息里。
                on_model_loaded(list(getattr(registry, "_targets", new_instance)), new_model, new_data,
                              algorithm_info, new_project_name)
                for _p in new_instance:
                    if hasattr(_p, "bind_model_path"):
                        try:
                            _p.bind_model_path(new_model_path)
                        except Exception as _exc:                         # noqa: BLE001
                            print(f"⚠ 插件【{getattr(_p, 'name', _p)}】的 bind_model_path() 出错：{_exc}")
                    if hasattr(_p, "model_changed"):
                        try:
                            _p.model_changed(new_model_path, new_model, new_data)
                        except Exception as _exc:                         # noqa: BLE001
                            print(f"⚠ 插件【{getattr(_p, 'name', _p)}】的 model_changed() 出错：{_exc}")

                plugins = new_instance
                current_project_name = str(new_project_name or "")
                current_algorithm_info = algorithm_info
                current_algorithm_config = run_config
                _project.save_last_project(current_project_name)

                # ★ "这一组算法和项目文件一致吗" —— 界面上的 Save 按钮靠它决定是否可用
                currently_persisted = (algorithm_overrides is None) if keep_persisted_state is None else bool(keep_persisted_state)
                if persist and algorithm_overrides is not None and data is not None:
                    # 【Save】：把界面上选的那组写回项目文件（只动 `算法` 字段，别的字段原样）
                    write_back = dict(data)
                    write_back.pop("order_note", None)          # 那是给人看的说明，重写一份新的
                    write_back["algorithms"] = [{"plugin": str(x)} for x in algorithm_overrides if str(x).strip()]
                    write_back["order_note"] = (
                        "列表顺序 = 每步的执行顺序：最后一项最后写 ctrl[:]，所以它说了算。"
                        "（本列表由界面【Algorithms】面板的 Save 写回）")
                    if _project.save_project(write_back):
                        currently_persisted = True
                        report.append(f"（已把这组算法写回 projects/{os.path.basename(_project.project_file_path(new_project_name))}）")
                    else:
                        report.append("✗ 写回项目文件失败（选择已在本次运行生效，但没记住）")

                # ★ 模型应用器也要知道"当前是哪个模型/项目"（它 2 Hz 往界面报）：
                #   这两个字段以前在 `切换模型()` 里更新，现在收进这里 ——
                #   `切换模型()` 负责"换物理对象"，`_装配项目()` 负责"换工作环境"，
                #   同一个状态只在**一个地方**写，才不会出现两边不一致。
                if model_applier is not None:
                    model_applier.current_path = str(new_model_path or "")
                    model_applier.current_display_name = (_project.display_model_name(new_model_path)
                                            if new_model_path else "（外来模型）")
                    if new_model_path:
                        try:
                            _model_bridge.remember_model(new_model_path)  # 记录最近选择；普通启动仍进空场景
                        except Exception:                              # noqa: BLE001
                            pass

                # ⑤ 立刻发一条项目状态给界面（点模型 → 界面马上更新算法列表）。
                #    这里**主动发**、不等节拍：节拍是 2 秒一次的兜底，
                #    而"点一下就要看到算法列表变了"是交互体验的硬要求。
                if project_publisher is not None:
                    project_publisher.publish(ProjectState(
                        project=current_project_name,
                        model_path=new_model_path,
                        model_display_name=_project.display_model_name(new_model_path) if new_model_path else "",
                        algorithms=plugin_framework.algorithm_info_wire(algorithm_info),
                        report=report,
                        algorithm_library=current_algorithm_library,
                        saved=currently_persisted,
                        active_controller=control_disk,
                        overridden_controllers=overrides,
                        gravity_enabled=bool(gravity_applier.gravity_enabled) if gravity_applier is not None else False,
                    ))
                    # 同一时刻把插件目录也发一份：「当前启用」是根据这组装好的算法算的，
                    # 所以它必须跟 项目状态 在同一个时机更新，否则界面上的勾会落后一拍。
                    if _plugin_bridge is not None:
                        try:
                            _catalog = _plugin_bridge.get_plugin_catalog(
                                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                [str(getattr(p, "name", "")) for p in new_instance])
                            _publish_outlet(_plugin_bridge.PluginCatalog(
                                _catalog["数量"],
                                tuple(_catalog["插件"]),
                                _catalog.get("说明", ""),
                            ))
                        except Exception as _e:                               # noqa: BLE001
                            print(f"⚠ 插件目录发布失败（不影响控制）："
                                  f"{type(_e).__name__}: {_e}")
                return report

            _model_event = messages.ModelEvent(model=model, path=model_path)
            send_outlet.send(_model_event)
            _broadcast_model_event(_model_event)

            def _restore_parameters(name: str, instances: list) -> str:
                """把项目文件里存过的参数灌回插件。返回一句给人看的说明（空串=没有）。

                ★ 为什么在**装配之后**马上灌一次：参数面板拖出来的值只活在内存里，
                  换项目 / 重启就没了。项目文件里存着上一次调好的值，
                  装配完立刻回填，用户点回来看到的就是上次那组参数。
                """
                if not name:
                    return ""
                stored = _project.load_parameters(name)
                if not stored:
                    return ""
                restored_count = 0
                for _p in instances:
                    plugin_id = str(getattr(_p, "plugin_id", "") or "")
                    plugin = stored.get(plugin_id) or {}
                    if not plugin:
                        # Version-1 projects stored parameters under the display name.
                        plugin = stored.get(str(getattr(_p, "name", ""))) or {}
                    for _parameter_name, _value in plugin.items():
                        item = getattr(_p, "set_parameter", None)
                        if item is None:
                            continue
                        try:
                            if not item(str(_parameter_name), float(_value)):
                                restored_count += 1
                        except Exception:                                  # noqa: BLE001
                            continue
                return f"（已恢复项目里存的 {restored_count} 个参数值）" if restored_count else ""

            # 算法目录仅扫描一次，避免在仿真循环中访问磁盘。
            try:
                current_algorithm_library = [d["plugin"] for d in _project.discover_algorithms()]
                print(f"【算法库】可选算法 {len(current_algorithm_library)} 个：{'、'.join(current_algorithm_library)}", flush=True)
            except Exception as exc:                                      # noqa: BLE001
                print(f"⚠ 算法库扫描失败（界面上的算法列表会是空的）：{type(exc).__name__}: {exc}")

            # ---- 仿真运行 / 重力设置：内置常驻、彼此独立，与算法也相互独立 ----
            #   ★ 必须在**首次装配之前**注册：重力应用器要在第一次 `通知模型加载`
            #     时就收到模型、把机器人复位到默认位置并冻结。注册晚了（原来是放在
            #     模型桥那一段之后）的后果实测过：**首次加载没人复位**，
            #     而物理从屏幕第一帧就开始推进 —— 等应用器上线时模型已经掉到偏离
            #     home 0.74 rad 的位置，然后被冻在**那个歪姿**上，不是默认位置。
            #
            #   ★ 为什么是内置件而不是算法：
            #     需求是"**所有模型进去都静止**"，不能取决于"恰好装了某个算法"。
            #     它曾经是 算法库/通用/展示姿态.py 里的算法插件 —— 一旦用户把算法列表
            #     清空（正是现在要的默认状态），开关就静默失效。所以收进外壳：
            #     注册成内置件，不进 `_用户插件`，换算法时不会被换掉，也不出现在算法列表里。
            def _reset_pose_callback() -> str:
                """给重力应用器的复位回调：无参、返回一句"怎么复位的"说明。

                复用 `_重置姿态()`，这样"换算法时重置"和"Reset 复位"
                走的是**同一套代码** —— 否则同一个概念会长出两种行为。
                """
                new_model, new_data = model, data
                if new_model is None or new_data is None:
                    return ""
                return _reset_pose(new_model, new_data)

            def _simulation_reset_callback() -> str:
                """Reset = 清 MuJoCo 状态 + 用同一配置重建当前算法实例。"""
                original_persisted_state = currently_persisted
                current_path = (model_applier.current_path if model_applier is not None
                         else str(model_path or ""))
                report = _assemble_project(
                    current_project_name, model, data, current_path,
                    algorithm_overrides=list(current_algorithm_config),
                    reset_pose=True,
                    keep_persisted_state=original_persisted_state,
                )
                if ControlTargetApplier is not None:
                    ControlTargetApplier.reset_to_current_position()
                return next((line for line in report if "重置到默认姿态" in line), "已重建当前算法")

            simulation_state_publisher = _simulation_control.SimulationStatePublisher(_publish_outlet)

            def _simulation_state_changed() -> None:
                if simulation_state_publisher is not None and gravity_applier is not None:
                    simulation_state_publisher.publish(
                        gravity_applier, float(getattr(data, "time", 0.0)), force=True)

            gravity_applier = _simulation_control.GravityApplier(
                reset_callback=_reset_pose_callback,
                simulation_reset=_simulation_reset_callback,
                state_callback=_simulation_state_changed,
            )
            registry.add_plugin(gravity_applier)          # 让它收到 重力状态
            gravity_applier.register_with_registry(registry)  # ★ 登记"世界冻结"判据
                                                #   （不能用"改暂停快照"实现：官方不发快照）
            print("【仿真】默认暂停；重力默认按模型 XML 开启，两者已相互独立", flush=True)

            # ---- 简单控制目标：GUI 目标 → 现有面板目标消息 → 当前控制算法 ----
            # 这里只负责数据交换，不在外壳里实现 PID/PD。没有控制算法时目标会被记住，
            # 但不会凭空驱动模型；装配算法后会再次转发当前目标。
            def _forward_control_target(target) -> None:
                import ui_bridge as _ui_bridge
                registry.process_message(_ui_bridge.PanelTargetMessage(ctrl_target=_np.asarray(target, dtype=float)))

            ControlTargetApplier = _control_bridge.ControlTargetApplier(_forward_control_target)
            control_state_publisher = _control_bridge.ControlStatePublisher(_publish_outlet)
            registry.add_plugin(ControlTargetApplier)

            # 启动时也走同一条装配路径（保证"启动"和"点模型"行为完全一致）
            try:
                project_publisher = _model_bridge.ProjectStatePublisher(_publish_outlet)
                report = _assemble_project(current_project_name, model, data, model_path)
                for _line in report:
                    print(f"  {_line}", flush=True)
            except Exception as exc:                                      # noqa: BLE001
                print(f"⚠ 项目装配不可用（本组算法保持 主程序.py 里装好的那一批）："
                      f"{type(exc).__name__}: {exc}")

            # 资产库清单：启动时发一次就够（清单不变；运行期真变了再发）
            try:
                _model_bridge.AssetLibraryPublisher(_publish_outlet).publish()
            except Exception as exc:                                      # noqa: BLE001
                print(f"⚠ 资产库清单发布失败（不影响控制）："
                      f"{type(exc).__name__}: {exc}")

            print("【仿真线程】模型已发送给窗口，开始跑控制回路…", flush=True)
            print("（下面每 2 秒打一行插件状态，可以据此判断算法到底有没有在干活）\n", flush=True)

            last_status = 0.0
            # 无窗工作台暂停后不应继续把相同的 MjData 复制给3D。
            # 记住最后一次真正发过的状态；复位/换模型仍会强制发一帧。
            last_snapshot_model = None
            last_snapshot_time = None
            last_snapshot_reset = -1

            # ------------------------------------------------------------------
            # 模型桥：把"换模型"收敛到这一个函数里（见 模型桥.py 的说明）
            #
            # ★ 为什么必须自己做这件事（踩过的坑）：
            #   官方推荐的循环是 handle.sync(...)，它会把 viewer 事件派发给插件；
            #   而我们为了做出错隔离把 sync() 拆开自己写，viewer 事件进的是
            #   **我们的注册表**，里面没有 ViewerHandle。
            #   于是用户在窗口里拖进一个模型时：窗口侧的画面换了，仿真侧的
            #   model/data 却没人接 —— 画面和物理对不上。这里补上这一环。
            # ------------------------------------------------------------------
            model_applier = None
            try:
                def switch_model_callback(model=None, path: str = "", notify_window: bool = True,
                          project_override: str = ""):
                    """加载并重绑一个新模型。返回 (是否成功, 给人看的一句话)。"""
                    nonlocal current_model, current_data
                    if model is None:
                        if not path or not os.path.exists(path):
                            return False, f"模型文件不存在：{path or '（空路径）'}"
                        started_at = _time.perf_counter()
                        try:
                            model = _model_loader.load_model(mujoco, path)
                        except Exception as exc:                          # noqa: BLE001
                            # ★ 加载失败绝不能影响正在跑的旧模型（用户可能只是选错了文件）
                            return False, f"加载失败（已保留原模型）：{type(exc).__name__}: {exc}"
                        duration_s = _time.perf_counter() - started_at
                    else:
                        duration_s = 0.0

                    new_data = mujoco.MjData(model)
                    key_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
                    if key_id >= 0:
                        mujoco.mj_resetDataKeyframe(model, new_data, key_id)
                    mujoco.mj_forward(model, new_data)

                    # ① 重绑外壳正在用的这一份（循环末尾会从 句柄 读回去）
                    if headless:
                        current_model, current_data = model, new_data
                    else:
                        handle.model, handle.data = model, new_data
                    # ② 告诉窗口侧（拖拽那条路窗口自己已经有了，就不用回发）
                    if notify_window:
                        _model_event = messages.ModelEvent(model=model, path=path)
                        send_outlet.send(_model_event)
                        _broadcast_model_event(_model_event)
                    # ③ ★ 换算法组：按模型反查项目，再按项目重新装配
                    #    - 空场景 / 外来模型 / 没有项目的模型 → 项目名为空 → 空算法集
                    #      （以前这两种情况会留着上一个模型的控制律继续跑，既危险又费解）
                    #
                    # ★★ 这里有两个真 bug，都出在"按模型反查项目"这一步：
                    #
                    #   bug 1：**同一个模型加载两次会清空用户的算法**。
                    #     窗口侧初始化完会再发一次 ModelEvent（同一条路径），
                    #     于是这里又把装配跑一遍 —— 而反查到的项目可能不是用户
                    #     用 `--项目` 指定的那个（多个项目共用同一模型时，反查会
                    #     "随便挑第一个"）。表现出来的现象是：**启动时明明装配了算法，
                    #     一两秒后算法没了、参数面板空了**（正是诊断测出来的那个"参数表缺"）。
                    #
                    #   bug 2：反查在多项目共用同一模型时会**随机挑**一个，
                    #     哪怕用户已经明确指定了项目。
                    #
                    #   修法：① 当前项目自己就声明了这个模型 → 就用它，不去反查；
                    #         ② 模型路径没变 → 根本不重新装配（没变化就没有理由动它）。
                    current_project_uses_model = False
                    if current_project_name and path:
                        current_config = _project.load_project(current_project_name)
                        if current_config:
                            declared_path = str(current_config.get("model") or "")
                            current_project_uses_model = (
                                bool(declared_path)
                                and os.path.normpath(_project.absolute_path(declared_path)) == os.path.normpath(path))
                    model_unchanged = bool(model_applier is not None
                                and getattr(model_applier, "current_path", "")
                                and os.path.normpath(str(model_applier.current_path)) == os.path.normpath(path))
                    if project_override:
                        new_project_name = str(project_override)
                    elif current_project_uses_model:
                        new_project_name = current_project_name
                    elif model_unchanged and current_project_name:
                        # 同一模型重复通知 → 保持现状，别动用户的算法
                        new_project_name = current_project_name
                    else:
                        new_project_name = _project.find_project_for_model(path) if path else ""
                    # 换模型也重置姿态：这是新加载的 MjData，本来就该从默认姿态开始
                    # （否则若模型没换、只是重新加载，同样会把"上一次的姿态"当基准）
                    report = _assemble_project(new_project_name, model, new_data, path, reset_pose=True)
                    for line in report:
                        print(f"  {line}", flush=True)

                    if model_applier is not None:
                        model_applier.dof = int(model.nq)
                        model_applier.actuator_count = int(model.nu)
                        model_applier.duration_s = duration_s
                    display = _model_bridge.display_name(path) if path else "（外来模型）"
                    arm_joints = _model_bridge.arm_joint_count(model)
                    dimensions = f"{arm_joints} 轴"
                    if int(model.nq) != arm_joints:
                        dimensions += f"、nq={int(model.nq)} / nu={int(model.nu)}"
                    return True, (f"已切换到 {display}（{dimensions}、"
                                  f"{len(plugins)} 个算法、耗时 {duration_s*1000:.0f} ms）" if duration_s
                                  else f"已切换到 {display}（{dimensions}、{len(plugins)} 个算法）")

                model_applier = _model_bridge.ModelApplier(switch_model_callback)
                # ★ 路径/显示名**立刻**填上；自由度等模型到位后由主循环补（见下）。
                #   为什么不能等 `句柄.model`：这是**跨线程竞态** —— 实测过，本段执行时
                #   仿真线程往往还没把 model 交给窗口（`句柄.model` 是 None）。
                #   而 `模型路径` 这个入参此刻已经确定，没必要跟着一起等。
                #   （`_装配项目()` 早于本行执行、那时 `模型应用器` 还是 None，
                #     所以它那次"填路径"被跳过了 —— 这正是【模型库】面板一直显示
                #     "当前："为空、`模型状态` 里路径为空的原因。）
                model_applier.current_path = str(model_path or "")
                model_applier.current_display_name = (_project.display_model_name(model_path)
                                        if model_path else "（外来模型）")
                if headless or current_model is not None:
                    # 无窗模式下模型早已装好（本地变量就是权威），直接填；
                    # 有窗模式这里是"恰好已到位就一起填"，没到位就等主循环补。
                    if current_model is not None:
                        model_applier.dof = int(current_model.nq)
                        model_applier.actuator_count = int(current_model.nu)
                registry.add_plugin(model_applier)          # 让它收到 换模型命令 / 拖拽的 ModelEvent
                model_publisher = _model_bridge.ModelPublisher(_publish_outlet, frequency=2.0)

                # ---- 【Algorithms】面板的落地端：界面选了算法 → 在这里重新装配 ----
                #   ★ 为什么要有这个回调：装配必须换掉**正在被仿真的那批插件实例**，
                #     而界面线程不能碰仿真侧的对象（跨线程改状态）。所以界面只"说想要哪几个"，
                #     装配在这里做（`_装配项目()` 的 算法覆盖 参数）。
                def switch_algorithm(algorithm_list: list, persist: bool = False, reset_pose: bool = True):
                    """界面选了一组算法 → 按它重新装配。返回 (是否成功, 给人看的一句话)。"""
                    if not algorithm_list:
                        return False, "一个算法都没选（至少勾一个；只想空跑请用 --无插件）"
                    report = _assemble_project(current_project_name, current_model, current_data, model_applier.current_path,
                                     algorithm_overrides=algorithm_list, persist=persist, reset_pose=reset_pose)
                    failure = [line for line in report if str(line).startswith("✗")]
                    installed = len(plugins)
                    tail = "并已写回项目文件" if persist else "（临时生效，未写回项目文件）"
                    return (not failure), f"已装配 {installed} 个算法{tail}" + (
                        f"；{len(failure)} 个失败（见终端）" if failure else "")

                algorithm_selector = _model_bridge.AlgorithmSelector(switch_algorithm)
                registry.add_plugin(algorithm_selector)          # 让它收到 应用算法命令
                print(f"【模型】模型库已就绪（当前：{model_applier.current_display_name}）"
                      f"—— 界面【模型库】面板可切换，也可以把 .xml 拖进窗口", flush=True)
                print("【算法】算法选择面板已就绪（界面【Algorithms】页签可勾选/调序/应用）",
                      flush=True)
            except Exception as exc:                                     # noqa: BLE001
                print(f"⚠ 模型桥不可用（将无法在界面里切换模型）：{type(exc).__name__}: {exc}")
                model_publisher = None

            # ---- 注册实验：只组合现有模型/项目/控制器/目标，不复制 GUI 或仿真循环 ----
            try:
                import experiment_registry as _experiment_registry
                import experiment_bridge as _experiment_bridge
                import trajectory_runtime as _trajectory_runtime

                initial_experiment = (
                    _experiment_registry.experiment_registry.create(experiment_name)
                    if str(experiment_name or "").strip() else None
                )

                def _apply_experiment_target(experiment) -> None:
                    if ControlTargetApplier is None:
                        return
                    target = experiment.trajectory.get("target_qpos")
                    if target is not None:
                        ControlTargetApplier.receive_target(_control_bridge.ControlTargetCommand(target=list(target)))

                def _prepare_experiment_trajectory_visualization(experiment) -> None:
                    """实验一加载就生成目标末端线；实际线仍由运行中的轨迹插件记录。"""
                    _trajectory_runtime.clear_trajectory_visualization()
                    if str(experiment.trajectory.get("type") or "") != "joint_waypoints":
                        return
                    _trajectory_runtime.prepare_trajectory_visualization(
                        current_model if headless else handle.model,
                        experiment.key, experiment.trajectory, plugin_framework.mujoco)

                def _load_experiment(name: str):
                    try:
                        experiment = _experiment_registry.experiment_registry.create(name)
                    except Exception as error:                           # noqa: BLE001
                        return None, f"实验不可用：{error}"
                    # 换实验前先暂停；指定项目避免“同一模型多个项目”时反查到错误算法。
                    if gravity_applier is not None:
                        gravity_applier.on_simulation_command(
                            _simulation_control.SimulationControlCommand(action="pause"))
                    ok, reason = switch_model_callback(
                        path=str(experiment.model_path), notify_window=True,
                        project_override=experiment.project)
                    if not ok:
                        return None, reason
                    _apply_experiment_target(experiment)
                    os.environ["YUBI_CURRENT_EXPERIMENT"] = experiment.key
                    try:
                        _prepare_experiment_trajectory_visualization(experiment)
                    except Exception as error:                           # noqa: BLE001
                        print(f"⚠ 目标轨迹 3D 预览生成失败：{type(error).__name__}: {error}",
                              flush=True)
                    return experiment, f"已加载 {experiment.name}；点击开始运行"

                def _pause_experiment() -> None:
                    if gravity_applier is not None:
                        gravity_applier.on_simulation_command(
                            _simulation_control.SimulationControlCommand(action="pause"))

                experiment_runner = _experiment_bridge.ExperimentRunner(
                    _publish_outlet, _load_experiment, _pause_experiment,
                    _apply_experiment_target, initial_experiment,
                    clear_observations=(_observation.clear if _observation is not None else None))
                registry.add_plugin(experiment_runner)
                # 它是在首次项目装配之后加入的，所以手动补一次当前模型上下文。
                experiment_runner.receive_model(
                    type("模型事件", (), {"model": model, "data": data})())
                experiment_runner.publish(force=True)
                print(f"【实验】已就绪（当前："
                      f"{initial_experiment.key if initial_experiment else '未选择'}）",
                      flush=True)
            except Exception as exc:                                     # noqa: BLE001
                print(f"⚠ 实验运行器不可用（普通模型/控制功能不受影响）："
                      f"{type(exc).__name__}: {exc}", flush=True)
                experiment_runner = None

            from live_tracking_bridge import LiveTrackingPublisher
            tracking_publisher = LiveTrackingPublisher(_publish_outlet)

            # 参数通道：把"插件声明了哪些可调参数"周期性发给界面（第 4 步 参数面板）
            try:
                import parameter_bridge as _parameter_bridge

                def _persist_parameters(plugin_name: str, values: dict) -> None:
                    """把界面上拖出来的参数写回**当前项目文件**（方案 C：参数可复现）。

                    ★ 为什么由外壳提供这个回调、而不是让参数桥自己读写项目文件：
                      "当前是哪个项目"这本账在外壳手里（换模型时会变），
                      参数桥只管"界面 → 插件"这条线。职责分开，换项目时才不会写错文件。
                    """
                    if not current_project_name:
                        return                     # 没有项目 → 参数无处可存（正常，不是错误）
                    _project.save_parameters(current_project_name, plugin_name, values)

                parameter_publisher = _parameter_bridge.ParameterPublisher(_publish_outlet)
                # 绑定发布：事务式批量应用要把"提交/回滚"的结果发回界面
                applier = (_parameter_bridge.ParameterApplier(
                    persist_parameters=_persist_parameters)
                    .bind(registry)
                    .bind_publisher(_publish_outlet))
                parameter_applier = applier        # `_装配项目()` 每次装配后会重绑
                registry.add_plugin(applier)                          # 让它也收到参数消息
                print("【参数】控制器参数面板已就绪"
                      "（界面里拖滑杆即可实时改参数；改动会写回当前项目文件）", flush=True)
            except Exception as exc:                                     # noqa: BLE001
                print(f"⚠ 参数桥不可用（参数面板将无法改参数）：{type(exc).__name__}: {exc}")
                parameter_publisher, parameter_applier = None, None

            # 辨识通道：把"参数辨识插件"的状态周期性发给界面（第 4 步 D3 界面化）
            try:
                import identification_bridge as _identification_bridge
                identification_publisher = _identification_bridge.Publisher(_publish_outlet)
                # ★ 这里不再逐个插件调 `绑定模型路径`：那件事已经收进 `_装配项目()`
                #   （装配完就通知，换模型时也会重来一遍）。以前在这里做，
                #   等价于"启动时通知一次"，换模型后就不再同步了。
                print("【辨识】参数辨识面板已就绪（激励采样 → 后台辨识 → 看拟合改善）", flush=True)
            except Exception as exc:                                     # noqa: BLE001
                print(f"⚠ 辨识桥不可用（辨识面板将无法工作）：{type(exc).__name__}: {exc}")
                identification_publisher = None
            # 指标发布器：把插件 指标() 报上来的数送给窗口侧面板画曲线（第 4 步 D1）
            # 限频到 ~30 Hz（物理 500 Hz，曲线不需要那么密），失败不影响控制回路
            try:
                import metrics_bridge as _metrics_bridge
                metric_publisher = _metrics_bridge.Publisher(_publish_outlet)
            except Exception as exc:                                     # noqa: BLE001
                print(f"⚠ 指标桥不可用（监控面板将没有数据）：{exc}")
                metric_publisher = None

            # 诊断器：收到「命令.诊断」就在后台线程跑 10 套断言，跑完发「诊断报告」。
            #   ★ 用子进程跑 `tools/selfchecks/*.py`（就是终端里那批脚本），不另写一份检查 ——
            #     两套检查迟早不一致，不一致的那套一定会在关键时刻骗人。
            try:
                import diagnostics_bridge as _diagnostics_bridge
                _diagnostics_runner = _diagnostics_bridge.DiagnosticsRunner(_publish_outlet, os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))))
                registry.add_plugin(_diagnostics_runner)
            except Exception as exc:                                     # noqa: BLE001
                print(f"⚠ 诊断器不可用（诊断视图将没有数据）：{exc}")
                _diagnostics_runner = None

            # 关节高亮应用器：日志里的 J4 点击后，把"亮 J4"写到进程内共享状态。
            #   ★ 纯视觉；宿主主线程读它，不参与物理/控制。
            try:
                import highlight_bridge as _highlight_bridge
                registry.add_plugin(_highlight_bridge.HighlightApplier())
                print("【高亮】关节定位通道已注册", flush=True)
            except Exception as exc:                                     # noqa: BLE001
                print(f"⚠ 高亮应用器不可用（关节定位将无效）：{exc}")

            # 系统监视发布器：RTF / 步频 / 内存（1 Hz 够了，看的是趋势不是每一帧）
            #   ★ 这几项**只能由仿真侧算**：界面拿不到"物理跑了多少步"。
            #     渲染帧率不在这里 —— 那是窗口层的事（见 宿主窗口.取统计）。
            try:
                import system_bridge as _system_bridge
                system_publisher = _system_bridge.Publisher(_publish_outlet)
            except Exception as exc:                                     # noqa: BLE001
                print(f"⚠ 系统桥不可用（监控视图将没有数据）：{exc}")
                system_publisher = None

            # 到这里模型、插件和内置发布器都已完成初始化。宿主窗口等的是这个
            # 明确信号，而不是猜“睡 1.2 秒应该够了”。
            session.ready.set()
            while not stop_event.is_set():
                # 官方 ViewerHandle.sync 做了三件事，我们拆开自己做，好插入出错隔离：
                #   ① 处理 viewer 发来的事件/快照  ② 派发 StepEvent  ③ 回发状态快照
                #   ★ 其中第 ② 步的"推进物理"由官方的 StepControl 插件完成（见 插件系统.py 的说明），
                #     它同时负责暂停/单步/倍速/噪声/发散后自动重置 —— 所以这里不再自己管节拍。
                if headless:
                    # 无窗宿主切换模型时，回调会替换 `当前模型/当前数据`。
                    # 每圈在这里取回权威引用，避免 3D 已换模型、物理循环却仍跑旧模型。
                    model, data = current_model, current_data
                else:
                    handle.model, handle.data = model, data

                # ---- 把 Web 来的命令转进收件队列 ----
                #   ★ 这里**不看 `后台线程`**：宿主窗口形态下仿真也在后台线程，
                #     但命令同样要在这一圈被搬进来 —— 否则 Web 上的按钮"有回执、没反应"。
                #     早先这里写的是 `if 无窗:` 才算，而宿主窗口走的正是 `无窗+后台线程`，
                #     逻辑上没问题；但**同步界面侧共享状态**必须在仿真线程做
                #     （见 `命令桥.排空并注入`），所以这里不能挪到主线程去。
                #   ★ 有窗模式不需要这一步：那边由 viewer 线程的 `界面桥._每帧发目标`
                #     调 `命令桥.转发待发命令(viewer)`，直接 `send_to_sim` 进官方端点。
                #     无窗之后没有那个线程，仿真就在主线程上 —— 于是"每圈顺手把网络收到的
                #     命令搬进本地队列"即可，搬完与"界面自己发的消息"走完全相同的路。
                #   ★ 踩过的坑：忘了这一步的表现是"回执说通过、物理却纹丝不动"，
                #     因为命令被收下了但**没有任何人把它搬进来**。
                if headless:
                    try:
                        import command_bridge as _command_bridge
                        _command_bridge.drain_and_inject(command_queue_obj)
                    except Exception as exc:                             # noqa: BLE001
                        if not errors.get("command_bridge_reported"):
                            errors["command_bridge_reported"] = True
                            print(f"⚠ 命令注入失败（Web 端的按钮会没反应）："
                                  f"{type(exc).__name__}: {exc}", flush=True)

                # 收件：有窗时是官方端点里的 viewer 事件/快照；无窗时是本地队列
                #   ★ 无窗下 `命令桥` 把 Web 命令塞进同一个队列，所以命令与
                #     "界面改参数"走的是**同一条路** —— 不需要为 Web 单独开一条注入通道。
                for event in drain_inbox():
                    registry.process_message(event)

                if not headless and handle.model is None:
                    break
                if headless:
                    # A model-load command can replace both objects while the
                    # inbox is drained. Never sample/step the old pair once more.
                    model, data = current_model, current_data
                    handle.model, handle.data = model, data
                else:
                    model, data = handle.model, handle.data

                # 派发 StepEvent：StepControl（内置）推进物理 + 你的插件写控制量
                registry.process_message(messages.StepEvent(model=model, data=data))

                # The controller and reference have now been evaluated at the
                # current state. Sampling uses a private MjData, never mutating
                # the plant to refresh derived actuator forces.
                if gravity_applier is not None:
                    try:
                        tracking_publisher.maybe_publish(
                            model, data, experiment_runner, gravity_applier,
                            _time.perf_counter())
                    except Exception as exc:                             # noqa: BLE001
                        if not errors.get("tracking_reported"):
                            errors["tracking_reported"] = True
                            print(f"⚠ 实时跟踪采样失败：{type(exc).__name__}: {exc}", flush=True)

                # 「记录航点」需要 `data.qpos`，只有这里拿得到 —— 所以由循环消费。
                #   ★ 插件自己拿不到 data（那是外壳的局部变量），这是刻意的分层：
                #     需要仿真数据的动作都在外壳里做，插件只描述"想做什么"。
                if _planner is not None and getattr(_planner, "待记录", False):
                    _planner.pending_records = False
                    try:
                        # ★ 本文件里 numpy 的别名是 `_np`（不是 `np`）—— 写错会 NameError，
                        #   而它只在使用时才暴露（这里），启动日志里表现为"记录航点失败"。
                        _count = _planner.record_waypoint(
                            _np.asarray(data.qpos, dtype=float).ravel())
                        print(f"【规划】已记录第 {_count} 个航点", flush=True)
                        _planner.publish_waypoint_count()
                    except Exception as _e:                               # noqa: BLE001
                        print(f"⚠ 记录航点失败：{type(_e).__name__}: {_e}", flush=True)

                # 送一帧指标给界面（内部按 30 Hz 限频，不会每圈都发）
                if (metric_publisher is not None and gravity_applier is not None
                        and gravity_applier.running):
                    # ★ 只有**真的发了一帧**才喂观测核心：指标是 30 Hz 限频的，
                    #   而物理是 500 Hz。若每步都喂，缓冲里会塞进 16 倍重复值，
                    #   "过零次数"和"频率"会被严重低估（判定直接失效）。
                    _published = metric_publisher.maybe_publish(registry, float(data.time),
                                                 _time.perf_counter())
                    if _published and _observation is not None:
                        try:
                            _observation.record(float(data.time), metric_publisher.latest)
                        except Exception:                                 # noqa: BLE001
                            pass
                # 判定（内部 1 Hz 节流；它自己不会跑赢仿真）
                if _observation is not None:
                    try:
                        _observation.evaluate(float(data.time), _time.perf_counter())
                    except Exception as _e:                               # noqa: BLE001
                        pass
                # 设备链路泵：没人读状态就没有遥测，看门狗也永远不会触发。
                #   （真机同理：控制循环停了，安全逻辑也就停了。）
                if _device_bridge is not None:
                    try:
                        _device_bridge.maybe_pump(_time.perf_counter())
                    except Exception:                                     # noqa: BLE001
                        pass
                # 系统指标（1 Hz）：RTF / 步频 / 内存。
                #   步数用 `data.time / timestep` 反推不稳，直接用 mujoco 的累计计数；
                #   拿不到就退回 0（宁可步频显示 0，也不编一个数）。
                if system_publisher is not None:
                    _steps = 0
                    try:
                        _steps = int(getattr(data, "time", 0.0) / max(model.opt.timestep, 1e-9))
                    except Exception:                                     # noqa: BLE001
                        _steps = 0
                    system_publisher.maybe_publish(
                        float(data.time), _steps, float(model.opt.timestep),
                        len(getattr(registry, "_targets", [])), _time.perf_counter())
                # 仿真控制状态（5 Hz）：Run/Pause/Reset 工具栏的权威数据源。
                if simulation_state_publisher is not None and gravity_applier is not None:
                    simulation_state_publisher.maybe_publish(
                        gravity_applier, float(data.time), _time.perf_counter())
                # 关节目标输入区（10 Hz）：当前位置来自 MjData，目标来自控制目标应用器。
                if control_state_publisher is not None and ControlTargetApplier is not None:
                    control_state_publisher.maybe_publish(
                        ControlTargetApplier, model, data, _time.perf_counter())
                # 周期性送"可调参数表"给界面（10 Hz 够了，滑杆不需要更密）
                if parameter_publisher is not None:
                    parameter_publisher.maybe_publish(
                        registry, float(data.time), _time.perf_counter())
                # 辨识状态（5 Hz 够了：采样/辨识都是秒级过程）
                if identification_publisher is not None:
                    identification_publisher.maybe_publish(registry, _time.perf_counter())
                # 当前模型状态（2 Hz 够了：只在切换时才会变）
                if model_publisher is not None:
                    # ★ 用**循环里这份 `model`**（每圈都是最新的），不要用 `当前模型` ——
                    #   后者只在"换模型"和"起手"时写，无窗模式下循环不刷新它，
                    #   拿它算自由度会永远停在起手那一刻的值（实测：nq 一直是 0）。
                    #   换模型时 `切换模型()` 已经写过一次，这里是从权威对象兜底且幂等。
                    if model_applier is not None and model is not None:
                        model_applier.dof = int(model.nq)
                        model_applier.actuator_count = int(model.nu)
                    model_publisher.maybe_publish(model_applier, _time.perf_counter())
                # 当前项目状态（哪个项目 / 挂了哪些算法 / 参数多少）。
                # ★ 装配完成时会**主动发**一条（点模型立刻更新），这里只是兜底重发：
                #   内容没变时 `也许发布` 内部会跳过，所以不构成额外负担。
                #   算法信息用装配时算好的快照，**不在这个循环里重算** ——
                #   这里是 ~500 Hz 的热路径，而 `收集算法信息()` 要遍历全部插件、
                #   还会调用它们的 `adjustable_parameters()`，放在循环里是纯浪费。
                if project_publisher is not None:
                    project_publisher.maybe_publish(ProjectState(
                        project=current_project_name,
                        model_path=(model_applier.current_path if model_applier is not None else ""),
                        model_display_name=(model_applier.current_display_name if model_applier is not None else ""),
                        algorithms=plugin_framework.algorithm_info_wire(current_algorithm_info),
                        algorithm_library=current_algorithm_library,
                        saved=currently_persisted,
                        active_controller=current_control_disk,
                        overridden_controllers=current_overrides,
                        gravity_enabled=bool(gravity_applier.gravity_enabled) if gravity_applier is not None else False,
                    ), _time.perf_counter())

                _snapshot_reset = int(gravity_applier.reset_count) if gravity_applier is not None else 0
                _snapshot_time = float(data.time)
                _snapshot_due = (
                    not headless
                    or gravity_applier is None
                    or gravity_applier.running
                    or model is not last_snapshot_model
                    or _snapshot_time != last_snapshot_time
                    or _snapshot_reset != last_snapshot_reset
                )
                if _snapshot_due:
                    integration_signature = int(mujoco.mjtState.mjSTATE_INTEGRATION)
                    integration_state = _np.empty(mujoco.mj_stateSize(model, integration_signature), _np.float64)
                    mujoco.mj_getState(model, data, integration_state, integration_signature)
                    snapshot = messages.StateSnapshot(state=integration_state, state_sig=integration_signature)
                    send_outlet.send(snapshot)
                    # 顺手给 3D 视口（如果有）；失败绝不影响仿真主循环
                    if state_observer is not None:
                        try:
                            state_observer(_ViewportStateSnapshot(snapshot, data, model))
                        except Exception:                             # noqa: BLE001
                            pass
                    last_snapshot_model = model
                    last_snapshot_time = _snapshot_time
                    last_snapshot_reset = _snapshot_reset

                # 官方 StepControl 自己会按刷新预算等待；这里补一点点，避免极端情况下空转
                _time.sleep(0.0002)

                # ---- 每 2 秒在终端打一行插件状态（看得见"算法正在干活"）----
                now = _time.perf_counter()
                if now - last_status >= 2.0:
                    last_status = now
                    line = registry.plugin_snapshot()
                    if line:
                        print(f"  [t={data.time:6.2f}s] {line}", flush=True)
        except KeyboardInterrupt:
            print("\n【仿真线程】收到 Ctrl+C，正在退出…", flush=True)
        except Exception as exc:                             # noqa: BLE001
            errors["error"] = exc
            session.error = exc
            session.ready.set()
            print(f"\n✗ 仿真线程出错：{type(exc).__name__}: {exc}")
            traceback.print_exc(limit=6)
        finally:
            stop_event.set()
            # 初始化阶段出错时也要唤醒等待者，让窗口立即得到失败原因。
            session.ready.set()
            if not headless:
                try:
                    handle.close()
                except Exception:                                 # noqa: BLE001
                    pass

    # ---- 无窗模式：没有 ImGui 窗口，仿真自己转 ----
    #   两种跑法，取决于谁来占主线程：
    #     · 纯无窗（web_app.py）：没人抢主线程 → 仿真**就在主线程上转**，
    #       命令注入与状态读取同线程，没有竞态（P2 的形态）。
    #     · 宿主窗口（desktop_app.py）：平台窗口必须占主线程 → 仿真挪到
    #       **后台线程**，与"有窗模式"同一套排法。这不是倒退，而是同一个约束回来了：
    #       "窗口在哪，仿真就不在哪"。
    if headless:
        if background_thread:
            print("【无窗模式】仿真在后台线程运行（主线程留给宿主窗口）。", flush=True)
            thread = threading.Thread(target=simulation_loop, daemon=True, name="仿真线程")
            session.thread = thread
            thread.start()
            return 0
        print("【无窗模式】仿真在主线程运行；界面请用浏览器打开上面的地址。", flush=True)
        try:
            simulation_loop()
        except KeyboardInterrupt:
            print("\n收到 Ctrl+C，正在退出…", flush=True)
        stop_event.set()
        if "error" in errors:
            return 1
        print("无窗运行结束。")
        return 0

    thread = threading.Thread(target=simulation_loop, daemon=True, name="仿真线程")
    session.thread = thread
    thread.start()

    # ---- 4. 主线程跑窗口（这一步必须在主线程，否则 macOS 直接拒绝）----
    #      窗口侧挂三个插件：
    #        窗口类()   —— 官方 19 个面板（外面包了一层，用于主题与实例传递）
    #        界面桥()   —— 滑杆值送进仿真侧（见 界面桥.py）
    #        监控面板() —— 把我们自己的指标画成实时曲线（见 面板/监控面板.py，第 4 步 D1）
    window_plugins = []
    try:
        import ui_bridge as _ui_bridge
        window_instance = _ui_bridge.make_window_class(window_class)()          # 包一层：主题/实例传递用
        window_plugins = [window_instance, _ui_bridge.UIBridge()]
    except Exception as exc:                                 # noqa: BLE001
        print(f"⚠ 界面桥加载失败（{exc}），只开官方界面")
        window_plugins = [window_class()]

    #   ★ 面板目录里的每个 .py 都会被自动加载（约定：模块里有 `面板类` 这个名字）。
    #     所以"加一个面板"= 往 面板/ 放一个文件，**不用改这个启动文件**。
    panel_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "面板")
    try:
        import sys as _sys
        if panel_dir not in _sys.path:
            _sys.path.insert(0, panel_dir)
        loaded = []
        pending_info = []
        for filename in sorted(os.listdir(panel_dir)):
            if not filename.endswith(".py") or filename.startswith("_") or filename == "曲线基类.py":
                continue
            module_name = filename[:-3]
            try:
                module = __import__(module_name)
                panel_class = getattr(module, "面板类", None)
                if panel_class is None:
                    continue                      # 不是面板文件（比如纯工具模块）
                instance = panel_class()
                window_plugins.append(instance)
                loaded.append(getattr(panel_class, "面板显示名", module_name))
                # 关于面板需要知道"谁在控制、用的什么模型、有哪些面板" → 启动后填进去
                if hasattr(instance, "设置信息"):
                    pending_info.append(instance)
            except Exception as exc:                                 # noqa: BLE001
                print(f"⚠ 面板 {filename} 加载失败（跳过）：{type(exc).__name__}: {exc}")
        for instance in pending_info:
            try:
                instance.set_info(plugins, model_path, loaded)
            except Exception as exc:                                 # noqa: BLE001
                print(f"⚠ 面板信息注入失败：{type(exc).__name__}: {exc}")
        if loaded:
            print(f"【界面】已加载 {len(loaded)} 个自定义面板：{'、'.join(loaded)}", flush=True)
    except Exception as exc:                                 # noqa: BLE001
        print(f"⚠ 面板目录加载失败（不影响使用）：{type(exc).__name__}: {exc}")

    try:
        launch_native.run_native_viewer(config, viewer_endpoint, plugins=window_plugins)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在关闭窗口…", flush=True)

    stop_event.set()
    thread.join(timeout=2.0)
    if "error" in errors:
        print(f"（仿真线程的异常已在上面打印）")
        return 1
    print("窗口已关闭。")
    return 0


# ---------------------------------------------------------------------------
# Stable English public API
# ---------------------------------------------------------------------------
drain_local_queue = _drain_local_queue


def start(
    config,
    model_path: str,
    window_class,
    plugins: list,
    registry,
    on_model_loaded,
    *,
    project_name: str = "",
    headless: bool = False,
    background_thread: bool = False,
    initial_messages: list | tuple | None = None,
    experiment_name: str = "",
):
    """Start the shared simulation runtime using stable English arguments."""
    return _start_impl(
        config,
        model_path,
        window_class,
        plugins,
        registry,
        on_model_loaded,
        project_name=project_name,
        headless=headless,
        background_thread=background_thread,
        initial_messages=initial_messages,
        experiment_name=experiment_name,
    )


__all__ = [
    "wait_until_ready", "stop", "set_state_observer", "set_model_observer",
    "command_queue", "start", "drain_local_queue",
]
