"""
web_app.py —— **浏览器入口**：起 Web 服务，用外部浏览器打开同一套界面

它和主入口的关系（一句话）：
    **同一个数据层，两种前端。**
    `run_yubi.py` → 平台原生窗口，React 界面 + 原生 MuJoCo 3D 视口
    `run_yubi_web.py` → 外部浏览器，React 界面，无原生 3D（仿真直接在主线程里跑）

为什么不是"复制一份主程序"：
    模型装载、项目装配、各桥、参数/辨识这些**一模一样**。复制等于把每一处修复
    都维护两遍，必然分叉。所以 `runtime_engine.start()` 提供了无窗口模式：
    窗口与 3D 那两段变成可跳过的，其余原样复用。

现在能用什么 / 还不能用什么（诚实清单）：
    ✅ 真物理、控制算法、参数可改、辨识、项目/模型切换、6 套皮肤、中英双语
    ⚠️ **没有原生 3D 视口** —— 这是浏览器入口的设计取舍，不是遗漏；
       要看 3D 请用 `run_yubi.py`。
    ⚠️ 官方 Studio 的 19 个 ImGui 面板不在这里，能力由 Web 界面覆盖。

用法：
    .venv/bin/python run_yubi_web.py                  # 起服务 + 自动开浏览器
    .venv/bin/python run_yubi_web.py --no-browser     # 只起服务（远程/排查用）
    .venv/bin/python run_yubi_web.py --web-port 8899
    .venv/bin/python run_yubi_web.py --check          # 不开服务，只做环境与前端产物自检
"""
from __future__ import annotations

import argparse
import os
import env_config
import sys

SOFTWARE_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SOFTWARE_DIRECTORY)

import console_support                 # noqa: E402

console_support.prepare_output()

import contract                        # noqa: E402
import experiment_cli                  # noqa: E402
import model_bridge                    # noqa: E402
import plugin_assembler                # noqa: E402
import plugin_system                   # noqa: E402
import project_registry                # noqa: E402
import runtime_engine                  # noqa: E402
import simulation_control              # noqa: E402
import web_bridge                      # noqa: E402

APP_NAME = "小软件"
APP_NAME_ENGLISH = "XiaoRuanJian Studio"


def find_model() -> tuple[str, str]:
    """决定这次加载哪个模型。返回 (路径, 一句说明)。

    顺序（与 `desktop_app.py` 一致，免得两个入口行为不一样）：
      ① 命令行 --模型
      ② 空场景（地面、灯光、背景；机器人由用户在模型库中主动选择）
      ③ 空场景文件缺失时，才回退到上次模型或项目模型
    """
    if model := env_config.read("YUBI_MODEL").strip():
        return model, "命令行/环境变量指定"
    empty_scene = os.path.join(os.path.dirname(SOFTWARE_DIRECTORY), "模型", "空场景.xml")
    if os.path.exists(empty_scene):
        return empty_scene, "启动默认空场景（请在模型库中选择机器人）"
    # 空场景文件意外缺失时才回退到已有模型，避免整个程序无法启动。
    try:
        last_model = model_bridge.read_last_model()
        if last_model and os.path.exists(last_model):
            return last_model, "上次用过的模型"
    except Exception:                                                 # noqa: BLE001
        pass
    try:
        for name in sorted(project_registry.list_projects() or []):
            project = project_registry.load_project(name)
            path = (project or {}).get("model") or ""
            absolute_path = project_registry.absolute_path(path) if path else ""
            if absolute_path and os.path.exists(absolute_path):
                return absolute_path, f"项目「{name}」声明的模型"
    except Exception:                                                 # noqa: BLE001
        pass
    return "", "一个模型都没找到"


def select_project(model_path: str, requested_project: str | None) -> str:
    """决定这次挂哪个项目的算法组。"""
    try:
        if requested_project:
            return str(requested_project)
        if os.path.basename(model_path) == "空场景.xml":
            return ""
        last_model = model_bridge.read_setting("last_project", "")
        if last_model:
            return str(last_model)
        return project_registry.find_project_for_model(model_path) if model_path else ""
    except Exception:                                                 # noqa: BLE001
        return ""


def check_environment() -> int:
    """不开服务，只把"这台机器上能不能跑起来"逐条说清楚。"""
    print("=" * 74)
    print(f"  {APP_NAME} · 无窗宿主自检")
    print("=" * 74)
    failures = 0

    # ① 前端产物在不在（决定浏览器里看到的是新界面还是 P0 回落页）
    frontend_path = os.path.join(SOFTWARE_DIRECTORY, "web", "index.html")
    if os.path.exists(frontend_path):
        print(f"  ✓ 前端产物：{os.path.relpath(frontend_path, os.path.dirname(SOFTWARE_DIRECTORY))}")
    else:
        failures += 1
        print("  ✗ 前端产物不在（会回落到 P0 的单页仪表盘）")
        print("      构建：cd frontend && node <pnpm.mjs> run build")
        print("      （或用系统 node；DSH 那份 node 有 hardened runtime 限制）")

    # ② 契约与生成物
    try:
        print(f"  ✓ 契约：版本 {contract.VERSION}，"
              f"下行 {len(contract.OUTBOUND_TOPICS)} / "
              f"上行 {len(contract.INBOUND_TOPICS)} 个主题")
    except Exception as exc:                                         # noqa: BLE001
        failures += 1
        print(f"  ✗ 契约不可用：{exc}")

    # ③ 模型
    model_path, description = find_model()
    if model_path:
        print(f"  ✓ 模型：{os.path.basename(model_path)}（{description}）")
    else:
        failures += 1
        print("  ✗ 一个模型都没找到")

    # ④ 项目
    project_name = select_project(model_path, None)
    print(f"  · 项目：{project_name or '（无，进去是静止的）'}")

    # ⑤ 端口占用
    import socket
    port = int(env_config.read("YUBI_WEB_PORT") or web_bridge.DEFAULT_PORT)
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            print(f"  ⚠ 端口 {port} 已被占用（可能已经有一个在跑；换端口用 --web口）")
        else:
            print(f"  ✓ 端口 {port} 可用")

    print()
    print("=" * 74)
    print(f"  {'✓ 可以启动' if failures == 0 else f'✗ {failures} 项要处理'}")
    print("=" * 74)
    return 1 if failures else 0


def is_running(host: str, port: int) -> bool:
    """那个端口上是不是**我们自己的**实例（而不是别的程序占着）。

    ★ 为什么必须区分这两种情况：双击 .app 时若端口被占，
      · 如果是"上一次没关干净的我方实例" → 正确反应是**直接把浏览器指过去**，
        而不是弹一句"起不来"。用户要的是界面，不是一句报错。
      · 如果是别的程序占着 → 得说清楚并建议换端口。
      区分办法：探 `/api/status`，能解析出我们的字段就是自己人。
    """
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/status", timeout=1.5) as r:
            data = json.loads(r.read())
            return isinstance(data, dict) and "enabled" in data
    except Exception:                                                 # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} · 无窗宿主（浏览器界面）")
    ap.add_argument("--web口", "--web-port", dest="web_port", type=int, default=None,
                    help=f"Web 端口（默认 {web_bridge.DEFAULT_PORT}）")
    ap.add_argument("--不开浏览器", "--no-browser", dest="no_browser", action="store_true",
                    help="只起服务，不自动打开浏览器")
    ap.add_argument("--项目", "--project", dest="project", default=None,
                    help="挂哪个项目的算法组")
    ap.add_argument("--模型", "--model", dest="model", default=None,
                    help="加载哪个模型（.xml）")
    experiment_cli.add_experiment_argument(ap)
    ap.add_argument("--开重力", "--gravity", "--enable-gravity", dest="enable_gravity",
                    action="store_true",
                    help="启动时就推进物理（默认冻结在默认位置，与原生界面一致）")
    ap.add_argument("--检查", "--check", dest="check_environment", action="store_true",
                    help="不开服务，只做自检")
    ap.add_argument("--标题", "--title", dest="title",
                    default=f"{APP_NAME} · 机器人仿真（基于 MuJoCo）")
    args = ap.parse_args(argv)

    try:
        current_experiment = experiment_cli.apply_experiment(args)
    except Exception as exc:                                         # noqa: BLE001
        print(f"✗ 实验加载失败：{exc}", flush=True)
        return 2

    if args.model:
        env_config.write("YUBI_MODEL", args.model)
    if args.web_port:
        env_config.write("YUBI_WEB_PORT", str(args.web_port))

    if args.check_environment:
        return check_environment()

    port = int(env_config.read("YUBI_WEB_PORT") or web_bridge.DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}/"

    # ---- 0. 已经有一个在跑？那就别再起一个，直接把浏览器指过去 ----
    #   ★ 双击 .app 的真实场景：用户上次没关、或者连点了两下。
    #     这时正确行为是"把界面送到他面前"，而不是报"端口被占"。
    if is_running("127.0.0.1", port):
        print("=" * 74)
        print(f"  已经有一个「{APP_NAME}」在运行了 —— 直接打开它。")
        print(f"  界面地址： {url}")
        print("=" * 74, flush=True)
        if not args.no_browser:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:                                         # noqa: BLE001
                pass
        return 0

    # ---- 1. 先把 Web 服务起起来（这样打印出来的地址立刻可用）----
    server = web_bridge.start(port=port)
    if not web_bridge.server_enabled(server):
        print(f"✗ Web 服务起不来：{web_bridge.server_error(server)}", flush=True)
        print("  端口可能被别的程序占着。换个端口试试：--web口 8899", flush=True)
        return 1
    url = web_bridge.health()["address"]
    has_frontend = os.path.exists(os.path.join(SOFTWARE_DIRECTORY, "web", "index.html"))

    print("=" * 74)
    print(f"  {APP_NAME} · 机器人仿真工作台")
    print("=" * 74)
    print(f"  界面地址： {url}")
    if not has_frontend:
        print("  ⚠ 前端还没构建，浏览器里看到的是简版数据页（不是完整界面）")
        print("      构建：cd frontend && node <pnpm.mjs> run build")
    print("  关掉：在这个终端按 Ctrl+C")
    print("=" * 74, flush=True)

    # ---- 2. 自动开浏览器（默认行为：双击就该看到界面）----
    if not args.no_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as exc:                                     # noqa: BLE001
            print(f"  ℹ 自动开浏览器失败（手动打开上面的地址即可）：{exc}", flush=True)

    # ---- 3. 决定模型与项目 ----
    model_path, description = find_model()
    if not model_path:
        print("✗ 一个模型都没找到：用 --模型 指定一个，或先跑 tools/import_model.py", flush=True)
        return 1
    project_name = select_project(model_path, args.project)
    if args.enable_gravity:
        simulation_control.set_ui_gravity(True)

    print(f"  【模型】{os.path.basename(model_path)}（{description}）", flush=True)
    print(f"  【项目】{project_name or '（无）'}", flush=True)
    if current_experiment is not None:
        print(f"  【实验】{current_experiment.key}（{current_experiment.name}）", flush=True)

    # ---- 4. 装配并开跑（无窗模式：仿真在主线程）----
    #   装配方式与桌面入口完全一致：同一个 `plugin_assembler.assemble_project`，
    #   同一个 `plugin_system.SafeRegistry`。换前端不换算法运行方式。
    #   换前端不换装配，算法作者那边一行都不用改。
    plugins: list = []
    report: list[str] = []
    if project_name:
        try:
            plugins, report = plugin_assembler.assemble_project(
                project_registry.load_project(project_name) if project_name else None, project_name)
        except Exception as exc:                                     # noqa: BLE001
            print(f"⚠ 项目装配失败（将不挂任何算法）：{type(exc).__name__}: {exc}",
                  flush=True)
            print("  （算法由 projects/*.json 声明：加算法 = 把 .py 放进 controllers/common/ 并写进项目文件）",
                  flush=True)
            print("   （注意：兼容性预检需要模型对象，装配时会给到；"
                  "换模型时会按项目重新装配）", flush=True)
    for line in report:
        print(f"  {line}", flush=True)
    print(f"【算法】{len(plugins)} 个", flush=True)

    # 浏览器工作台也是无窗仿真宿主：使用明确的实时单步节拍，
    # 不依赖官方 Viewer 是否在发布刷新快照。
    registry = plugin_system.SafeRegistry(
        plugins, step_plugin=plugin_system.RealtimeFixedStep())
    config = plugin_system.viewer_protocol.ViewerConfig(
        title=args.title, width=1200, height=800, gfx=env_config.read("YUBI_GFX"))

    # 同步浏览器入口会在启动函数开头清理旧队列，因此把已校验的实验消息显式
    # 交给启动函数，让它在清理之后再预置；桌面入口则在“已就绪”后直接入队。
    initial_messages = experiment_cli.initial_messages(current_experiment)
    return runtime_engine.start(
        config, model_path, None, plugins, registry,
        plugin_system.notify_model_loaded,
        project_name=project_name,
        headless=True,
        initial_messages=initial_messages,
        experiment_name=(current_experiment.key if current_experiment is not None else ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
