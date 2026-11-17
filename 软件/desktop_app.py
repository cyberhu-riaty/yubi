"""
desktop_app.py —— 主入口：**我们自己的窗口**，Web 界面 + 原生 3D 视口同级并列

它和浏览器入口的关系（一张表说清）：

    | 入口 | 窗口 | 界面 | 3D |
    |---|---|---|---|
    | **`run_yubi.py`** | **平台原生窗口** | **窗口内网页视图里的 React** | **macOS / Windows 均已接入** |
    | `run_yubi_web.py` | 无（外部浏览器打开） | 浏览器里的 React | ❌ 无原生 3D |

为什么要有它：
    界面不再依赖官方 Studio 的窗口，也不再依赖外部浏览器。macOS 的 3D 仍然是
    **MuJoCo 渲染**（不是浏览器里的运动学回放）；Windows 由 Qt 同级放置网页工作台
    与 3D 视口，两边都复用同一个仿真与消息后端。

线程排法（沿用既有约束，没有新花样）：
    平台窗口事件循环占主线程（macOS AppKit / Windows Qt）→ 仿真回后台线程。
    两边通过 Web 桥的消息队列通信，**不共享 MjData**（视口有自己那份）。

当前边界（诚实清单）：
    · 部署页只有模拟后端，没有真机协议后端与物理急停；
    · 笛卡尔规划只支持位置；jerk 只校验不整形；
    · 官方 Studio 的 19 个 ImGui 面板不在这个窗口里，能力由 Web 界面覆盖。

用法：
    .venv/bin/python run_yubi.py                 # 起窗口（推荐）
    .venv/bin/python run_yubi.py --check         # 只自检，不开窗口
    .venv/bin/python run_yubi.py --no-3d         # 只要 Web 界面（排查用）
"""
from __future__ import annotations

import argparse
import os
import sys

SOFTWARE_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SOFTWARE_DIRECTORY)

import console_support

console_support.prepare_output()
import command_bridge
import contract
import experiment_cli
import model_bridge
import platform_adapters
import plugin_assembler
import plugin_system
import project_registry
import runtime_engine
import web_bridge

APP_NAME = "小软件"

# 默认窗口尺寸（旧尺寸下 Web 内容会被裁，别改小）
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1440.0, 920.0


def find_model() -> tuple[str, str]:
    """明确指定时加载指定模型，否则先进入有地面和灯光的空场景。"""
    if model := os.environ.get("驭臂_模型", "").strip():
        return model, "命令行/环境变量指定"
    empty_scene = os.path.join(os.path.dirname(SOFTWARE_DIRECTORY), "模型", "空场景.xml")
    if os.path.exists(empty_scene):
        return empty_scene, "启动默认空场景（请在模型库中选择机器人）"
    # 空场景文件意外缺失时才回退到已有模型，避免整个程序无法启动。
    try:
        last_model = model_bridge.read_last_model()
        if last_model and os.path.exists(last_model):
            return last_model, "上次用过的模型"
    except Exception:  # noqa: BLE001, S110
        pass
    try:
        for name in sorted(project_registry.list_projects() or []):
            project = project_registry.load_project(name) or {}
            path = project.get("模型") or ""
            absolute_path = project_registry.absolute_path(path) if path else ""
            if absolute_path and os.path.exists(absolute_path):
                return absolute_path, f"项目「{name}」声明的模型"
    except Exception:  # noqa: BLE001, S110
        pass
    return "", "一个模型都没找到"


def select_project(model_path: str, requested_project: str | None) -> str:
    try:
        if requested_project:
            return str(requested_project)
        if os.path.basename(model_path) == "空场景.xml":
            return ""
        last_model = model_bridge.read_setting("上次项目", "")
        return str(last_model) if last_model else (
            project_registry.find_project_for_model(model_path) if model_path else "")
    except Exception:                                                 # noqa: BLE001
        return ""


def check_environment() -> int:
    print("=" * 76)
    print(f"  {APP_NAME} · 宿主窗口自检")
    print("=" * 76)
    failures = 0
    # ① 平台层能不能起窗口（由平台实现自己回答，入口不碰平台细节）
    try:
        platform_impl = platform_adapters.get_implementation()
        available, reason = platform_impl.is_available()
        if available:
            print(f"  ✓ 窗口实现：{platform_impl.name}")
        else:
            failures += 1
            print(f"  ✗ 窗口不可用（{platform_impl.name}）：{reason}")
    except Exception as exc:                                         # noqa: BLE001
        failures += 1
        print(f"  ✗ 平台适配层不可用：{type(exc).__name__}: {exc}")
    # ② 前端产物
    frontend_path = os.path.join(SOFTWARE_DIRECTORY, "web", "index.html")
    if os.path.exists(frontend_path):
        print("  ✓ 前端产物：软件/web/index.html")
    else:
        failures += 1
        print("  ✗ 前端产物不在（窗口里会是一片空白）")
        print("      构建：cd frontend && node <pnpm.mjs> run build")
    # ③ 模型
    model_path, description = find_model()
    print(f"  {'✓' if model_path else '✗'} 模型："
          f"{os.path.basename(model_path) if model_path else '没找到'}（{description}）")
    if not model_path:
        failures += 1
    # ④ 契约
    try:
        print(f"  ✓ 契约：版本 {contract.VERSION}（下行 {len(contract.OUTBOUND_TOPICS)} / "
              f"上行 {len(contract.INBOUND_TOPICS)}）")
    except Exception as exc:                                         # noqa: BLE001
        failures += 1
        print(f"  ✗ 契约不可用：{exc}")
    # ⑤ 上行命令名（本入口会直接入队的那几个）
    try:
        for topic_name in ("command.gravity", "command.simulation", "命令.控制目标", "command.experiment"):
            if contract.get_topic(topic_name) is None:
                failures += 1
                print(f"  ✗ 契约里没有上行命令「{topic_name}」（工作台控制通道不完整）")
            else:
                print(f"  ✓ 上行命令「{topic_name}」在契约里")
    except Exception as exc:                                         # noqa: BLE001
        failures += 1
        print(f"  ✗ 上行命令检查失败：{exc}")
    # ⑥ 端口
    import socket
    port = int(os.environ.get("驭臂_Web端口", "") or web_bridge.DEFAULT_PORT)
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print(f"  ⚠ 端口 {port} 已被占用（可能已有一个在跑；换端口用 --web口）")
        else:
            print(f"  ✓ 端口 {port} 可用")
    print()
    print("=" * 76)
    print(f"  {'✓ 可以启动' if failures == 0 else f'✗ {failures} 项要处理'}")
    print("=" * 76)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} · 宿主窗口（Web 界面 + 原生 3D 视口）")
    ap.add_argument("--web口", "--web-port", dest="web_port", type=int, default=None)
    ap.add_argument("--项目", "--project", dest="project", default=None,
                    help="挂哪个项目的算法组")
    ap.add_argument("--模型", "--model", dest="model", default=None,
                    help="加载哪个模型")
    experiment_cli.add_experiment_argument(ap)
    ap.add_argument("--开重力", "--enable-gravity", dest="enable_gravity", action="store_true",
                    help="启动时就推进物理（默认冻结在默认位置）")
    ap.add_argument("--无3D", "--no-3d", dest="no_3d", action="store_true",
                    help="不要 3D 视口（Web 界面铺满窗口；排查用）")
    ap.add_argument("--宽", "--width", dest="width", type=float, default=DEFAULT_WIDTH)
    ap.add_argument("--高", "--height", dest="height", type=float, default=DEFAULT_HEIGHT)
    ap.add_argument("--检查", "--check", dest="check_environment", action="store_true",
                    help="不开窗口，只自检")
    ap.add_argument("--标题", "--title", dest="title", default=f"{APP_NAME} · 机器人仿真工作台")
    args = ap.parse_args(argv)

    try:
        current_experiment = experiment_cli.apply_experiment(args)
    except Exception as exc:                                         # noqa: BLE001
        print(f"✗ 实验加载失败：{exc}", flush=True)
        return 2

    if args.model:
        os.environ["驭臂_模型"] = args.model
    if args.web_port:
        os.environ["驭臂_Web端口"] = str(args.web_port)

    if args.check_environment:
        return check_environment()

    # ---- 0. 先问平台层"能不能起窗口"（不能就给人话，而不是抛栈）----
    #   ★ 入口**不直接** import 任何平台相关模块（宿主窗口/AppKit/…）——
    #     那是平台适配层的职责。换平台时只改 `软件/平台适配层/`，本文件不动。
    try:
        platform_impl = platform_adapters.get_implementation()
    except Exception as exc:                                         # noqa: BLE001
        print(f"✗ 取不到窗口实现：{type(exc).__name__}: {exc}", flush=True)
        print("  （临时替代：run_yubi_web.py —— 用外部浏览器看同一个界面）", flush=True)
        return 1
    available, reason = platform_impl.is_available()
    if not available:
        print(f"✗ 起不了窗口（{platform_impl.name}）：{reason}", flush=True)
        return 1

    port = int(os.environ.get("驭臂_Web端口", "") or web_bridge.DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}/"

    # ---- 1. 模型/项目先定下来（视口要用模型路径）----
    model_path, description = find_model()
    if not model_path:
        print("✗ 一个模型都没找到：用 --模型 指定一个", flush=True)
        return 1
    project_name = select_project(model_path, args.project)
    os.environ["驭臂_当前模型"] = model_path
    os.environ["驭臂_当前项目"] = project_name
    # ★ `--开重力` 记在这里、**装配之后**才施用：装配过程会重置姿态/冻结物理
    #   （那是"刚加载模型别乱动"的默认行为），先设会被它盖掉 ——
    #   表现就是状态栏明明写着"开重力"，物理却还是"冻结"。
    enable_gravity_after_setup = bool(args.enable_gravity)

    # ---- 2. Web 服务 ----
    server = web_bridge.start(port=port)
    if not web_bridge.server_enabled(server):
        print(f"✗ Web 服务起不来：{web_bridge.server_error(server)}", flush=True)
        print("  端口可能被占；换一个：--web口 8899", flush=True)
        return 1

    # ---- 3. 仿真的装配与启动（后台线程：主线程要留给 AppKit）----
    plugins, report = [], []
    if project_name:
        try:
            plugins, report = plugin_assembler.assemble_project(
                project_registry.load_project(project_name) if project_name else None, project_name)
        except Exception as exc:                                     # noqa: BLE001
            print(f"⚠ 项目装配失败（将不挂任何算法）：{type(exc).__name__}: {exc}",
                  flush=True)

    print("=" * 76, flush=True)
    print(f"  {APP_NAME} · 机器人仿真工作台（宿主窗口）", flush=True)
    print("=" * 76, flush=True)
    print(f"  界面地址 : {url}（显示在窗口内的网页视图里）", flush=True)
    print(f"  模型     : {os.path.basename(model_path)}（{description}）", flush=True)
    print(f"  项目     : {project_name or '（无 → 不挂算法，进去是静止的）'}", flush=True)
    if current_experiment is not None:
        print(f"  实验     : {current_experiment.key}（{current_experiment.name}）", flush=True)
    print(f"  算法     : {len(plugins)} 个", flush=True)
    if args.no_3d:
        print("  ⚠ --无3D：本次不建 3D 视口", flush=True)
    print("=" * 76, flush=True)

    # 无窗宿主不能依赖官方 Viewer 的刷新节拍：按模型 timestep
    # 实时推进，保证 GUI 的 Start 按钮能以约 1× 速度跑完实验。
    registry = plugin_system.SafeRegistry(
        plugins, step_plugin=plugin_system.RealtimeFixedStep())
    config = plugin_system.viewer_protocol.ViewerConfig(
        title=args.title, width=int(args.width), height=int(args.height), gfx="")

    # ★ 后台线程：与"有窗模式"同一套排法（窗口在哪，仿真就不在哪）。
    #   命令注入靠 `runtime_engine.command_queue`：主线程放入命令，仿真线程每圈排空。
    # ★ 3D 视口的"状态来源"：放在**仿真线程**里的观察者，只做一次引用替换
    #   （回调里绝不能碰 AppKit —— 那必须在主线程）
    viewport_slot = {"视口": None, "待换模型": None}
    def receive_state(snapshot):
        # ⚠️ 这个函数在**仿真线程**里被调用：只允许做"放好引用"这种事
        viewport = viewport_slot["视口"]
        if viewport is not None:
            viewport.receive_state(snapshot)

    def receive_model_event(event):
        # 模型桥在换模型成功后会广播 ModelEvent；这里只记路径，绝不碰 AppKit。
        # 主线程的 _主线程每帧 会取走它，停旧渲染线程、重装新模型。
        path = str(getattr(event, "path", "") or "")
        if path:
            viewport_slot["待换模型"] = path

    runtime_engine.set_state_observer(receive_state)
    runtime_engine.set_model_observer(receive_model_event)

    # `启动外壳(...后台线程=True)` 自己负责创建仿真线程。这里不再额外包一层
    # “启动线程”，也不猜固定等待时间；模型和插件真正就绪后会发出事件。
    start_code = runtime_engine.start(
        config, model_path, None, plugins, registry,
        plugin_system.notify_model_loaded,
        project_name=project_name,
        headless=True,
        background_thread=True,
        experiment_name=(current_experiment.key if current_experiment is not None else ""),
    )
    if start_code != 0:
        web_bridge.close()
        return int(start_code)
    ready, ready_reason = runtime_engine.wait_until_ready(15.0)
    if not ready:
        print(f"✗ {ready_reason}", flush=True)
        runtime_engine.stop()
        web_bridge.close()
        return 1

    # 实验定义里的初始控制目标统一走现有命令队列。
    # 普通启动时 当前实验 为 None，不改变原来的 GUI 操作流程。
    try:
        experiment_cli.enqueue_initial_commands(current_experiment, runtime_engine.command_queue())
    except Exception as e:
        print(f"✗ 实验初始命令加载失败：{type(e).__name__}: {e}", flush=True)
        runtime_engine.stop()
        web_bridge.close()
        return 1

    if enable_gravity_after_setup:
        # 装配完成后再开（见上面 `要开重力` 的说明）。
        # 走和 Web 命令同一条路：`command_bridge.enqueue_command` → 仿真循环每圈排空。
        # 这样"命令行开的重力"和"界面上点的重力"走的是同一条通道，不会两套逻辑。
        try:
            # ★ 主题名要用**契约里的名字**（`command.gravity`），不是消息类名。
            #   写错的话 `命令入队` 会回一句"不是登记过的上行命令"，然后静默不入队 ——
            #   表现就是"命令行说要开重力，仿真却一直停在 t=0.00s"（本次实测踩到）。
            ok, description = command_bridge.enqueue_command(
                runtime_engine.command_queue(), "command.gravity",
                {"gravity_enabled": True}, print_result=False)
            if not ok:
                print(f"  ⚠ 开重力没能入队：{description}", flush=True)
            print("  ✓ 已请求开重力（装配之后生效）", flush=True)
        except Exception as exc:                                     # noqa: BLE001
            print(f"  ⚠ 开重力失败（不影响起窗口）：{type(exc).__name__}: {exc}",
                  flush=True)

    # ---- 4. 起窗口（这一步必须在主线程）----
    exit_code = 0
    try:
        # 视口槽交给平台层：它建好原生渲染面后回填，状态观察者据此把每步状态喂进去。
        exit_code = platform_impl.run(
            url=url, title=args.title, width=args.width, height=args.height,
            command_queue=runtime_engine.command_queue(), no_3d=args.no_3d,
            viewport_slot=viewport_slot,
        )
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在退出…", flush=True)
        exit_code = 0
    finally:
        # 关闭顺序：先断开观察者，防止再给已销毁的视口送帧；再停仿真；
        # 最后关闭本地 Web 服务，释放端口。重复关闭也是安全的。
        runtime_engine.set_state_observer(None)
        runtime_engine.set_model_observer(None)
        stopped, stop_reason = runtime_engine.stop(3.0)
        if not stopped:
            print(f"⚠ {stop_reason}", flush=True)
            exit_code = 1
        web_bridge.close()
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
