"""
主程序Web.py —— **浏览器入口**：起 Web 服务，用外部浏览器打开同一套界面

它和主入口的关系（一句话）：
    **同一个数据层，两种前端。**
    `主程序窗口.py` → 自研 NSWindow，React 界面 + 原生 OpenGL 3D 视口
    `主程序Web.py`  → 外部浏览器，React 界面，无原生 3D（仿真直接在主线程里跑）

为什么不是"复制一份主程序"：
    模型装载、项目装配、各桥、参数/辨识这些**一模一样**。复制等于把每一处修复
    都维护两遍，必然分叉。所以 `启动.启动外壳()` 多了个 `无窗` 参数：
    窗口与 3D 那两段变成可跳过的，其余原样复用。

现在能用什么 / 还不能用什么（诚实清单）：
    ✅ 真物理、控制算法、参数可改、辨识、项目/模型切换、6 套皮肤、中英双语
    ⚠️ **没有原生 3D 视口** —— 这是浏览器入口的设计取舍，不是遗漏；
       要看 3D 请用 `软件/主程序窗口.py`。
    ⚠️ 官方 Studio 的 19 个 ImGui 面板不在这里，能力由 Web 界面覆盖。

用法：
    .venv/bin/python 软件/主程序Web.py              # 起服务 + 自动开浏览器
    .venv/bin/python 软件/主程序Web.py --不开浏览器   # 只起服务（远程/排查用）
    .venv/bin/python 软件/主程序Web.py --web口 8899
    .venv/bin/python 软件/主程序Web.py --检查         # 不开服务，只做环境与前端产物自检
"""
from __future__ import annotations

import argparse
import os
import sys

本目录 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 本目录)

import 控制台                          # noqa: E402
控制台.准备输出()

import 插件系统 as 插件框架            # noqa: E402
import 启动                            # noqa: E402
import 文案                          # noqa: E402
import Web桥                          # noqa: E402
import 重力桥                          # noqa: E402
import 项目 as 项目清单                  # noqa: E402
import 装配器                          # noqa: E402
import experiment_cli                  # noqa: E402

软件名 = "小软件"
软件名英文 = "XiaoRuanJian Studio"


def _找模型() -> tuple[str, str]:
    """决定这次加载哪个模型。返回 (路径, 一句说明)。

    顺序（与 `主程序窗口.py` 一致，免得两个入口行为不一样）：
      ① 命令行 --模型
      ② 空场景（地面、灯光、背景；机器人由用户在模型库中主动选择）
      ③ 空场景文件缺失时，才回退到上次模型或项目模型
    """
    if 模型 := os.environ.get("驭臂_模型", "").strip():
        return 模型, "命令行/环境变量指定"
    空场景 = os.path.join(os.path.dirname(本目录), "模型", "空场景.xml")
    if os.path.exists(空场景):
        return 空场景, "启动默认空场景（请在模型库中选择机器人）"
    # 空场景文件意外缺失时才回退到已有模型，避免整个程序无法启动。
    try:
        import 模型桥
        上次 = 模型桥.读取上次模型()
        if 上次 and os.path.exists(上次):
            return 上次, "上次用过的模型"
    except Exception:                                                 # noqa: BLE001
        pass
    try:
        for 名字 in sorted(项目清单.列出项目() or []):
            项目 = 项目清单.读取项目(名字)
            路径 = (项目 or {}).get("模型") or ""
            绝对 = 项目清单.绝对路径(路径) if 路径 else ""
            if 绝对 and os.path.exists(绝对):
                return 绝对, f"项目「{名字}」声明的模型"
    except Exception:                                                 # noqa: BLE001
        pass
    return "", "一个模型都没找到"


def _选项目(模型路径: str, 指名: str | None) -> str:
    """决定这次挂哪个项目的算法组。"""
    try:
        if 指名:
            return str(指名)
        if os.path.basename(模型路径) == "空场景.xml":
            return ""
        import 模型桥
        上次 = 模型桥.读取设置("上次项目", "")
        if 上次:
            return str(上次)
        return 项目清单.按模型找项目(模型路径) if 模型路径 else ""
    except Exception:                                                 # noqa: BLE001
        return ""


def 检查() -> int:
    """不开服务，只把"这台机器上能不能跑起来"逐条说清楚。"""
    print("=" * 74)
    print(f"  {软件名} · 无窗宿主自检")
    print("=" * 74)
    坏 = 0

    # ① 前端产物在不在（决定浏览器里看到的是新界面还是 P0 回落页）
    产物 = os.path.join(本目录, "web", "index.html")
    if os.path.exists(产物):
        print(f"  ✓ 前端产物：{os.path.relpath(产物, os.path.dirname(本目录))}")
    else:
        坏 += 1
        print("  ✗ 前端产物不在（会回落到 P0 的单页仪表盘）")
        print("      构建：cd 前端 && node <pnpm.mjs> run build")
        print("      （或用系统 node；DSH 那份 node 有 hardened runtime 限制）")

    # ② 契约与生成物
    try:
        import 契约
        print(f"  ✓ 契约：版本 {契约.版本}，"
              f"下行 {len(契约.下行主题)} / 上行 {len(契约.上行主题)} 个主题")
    except Exception as 异常:                                         # noqa: BLE001
        坏 += 1
        print(f"  ✗ 契约不可用：{异常}")

    # ③ 模型
    模型路径, 说明 = _找模型()
    if 模型路径:
        print(f"  ✓ 模型：{os.path.basename(模型路径)}（{说明}）")
    else:
        坏 += 1
        print("  ✗ 一个模型都没找到")

    # ④ 项目
    项目名 = _选项目(模型路径, None)
    print(f"  · 项目：{项目名 or '（无，进去是静止的）'}")

    # ⑤ 端口占用
    import socket
    口 = int(os.environ.get("驭臂_Web端口", "") or Web桥.默认端口)
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", 口)) == 0:
            print(f"  ⚠ 端口 {口} 已被占用（可能已经有一个在跑；换端口用 --web口）")
        else:
            print(f"  ✓ 端口 {口} 可用")

    print()
    print("=" * 74)
    print(f"  {'✓ 可以启动' if 坏 == 0 else f'✗ {坏} 项要处理'}")
    print("=" * 74)
    return 1 if 坏 else 0


def _已在跑(主机: str, 端口: int) -> bool:
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
        with urllib.request.urlopen(f"http://{主机}:{端口}/api/status", timeout=1.5) as r:
            数据 = json.loads(r.read())
            return isinstance(数据, dict) and "启用" in 数据
    except Exception:                                                 # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{软件名} · 无窗宿主（浏览器界面）")
    ap.add_argument("--web口", "--web-port", dest="web口", type=int, default=None,
                    help=f"Web 端口（默认 {Web桥.默认端口}）")
    ap.add_argument("--不开浏览器", "--no-browser", dest="不开浏览器", action="store_true",
                    help="只起服务，不自动打开浏览器")
    ap.add_argument("--项目", default=None, help="挂哪个项目的算法组")
    ap.add_argument("--模型", default=None, help="加载哪个模型（.xml）")
    experiment_cli.add_experiment_argument(ap)
    ap.add_argument("--开重力", "--gravity", dest="开重力", action="store_true",
                    help="启动时就推进物理（默认冻结在默认位置，与原生界面一致）")
    ap.add_argument("--检查", action="store_true", help="不开服务，只做自检")
    ap.add_argument("--标题", default=f"{软件名} · 机器人仿真（基于 MuJoCo）")
    args = ap.parse_args(argv)

    try:
        当前实验 = experiment_cli.apply_experiment(args)
    except Exception as 异常:                                         # noqa: BLE001
        print(f"✗ 实验加载失败：{异常}", flush=True)
        return 2

    if args.模型:
        os.environ["驭臂_模型"] = args.模型
    if args.web口:
        os.environ["驭臂_Web端口"] = str(args.web口)

    if args.检查:
        return 检查()

    口 = int(os.environ.get("驭臂_Web端口", "") or Web桥.默认端口)
    地址 = f"http://127.0.0.1:{口}/"

    # ---- 0. 已经有一个在跑？那就别再起一个，直接把浏览器指过去 ----
    #   ★ 双击 .app 的真实场景：用户上次没关、或者连点了两下。
    #     这时正确行为是"把界面送到他面前"，而不是报"端口被占"。
    if _已在跑("127.0.0.1", 口):
        print("=" * 74)
        print(f"  已经有一个「{软件名}」在运行了 —— 直接打开它。")
        print(f"  界面地址： {地址}")
        print("=" * 74, flush=True)
        if not args.不开浏览器:
            try:
                import webbrowser
                webbrowser.open(地址)
            except Exception:                                         # noqa: BLE001
                pass
        return 0

    # ---- 1. 先把 Web 服务起起来（这样打印出来的地址立刻可用）----
    桥 = Web桥.启动(端口=口)
    if not 桥.启用:
        print(f"✗ Web 服务起不来：{桥.出错}", flush=True)
        print("  端口可能被别的程序占着。换个端口试试：--web口 8899", flush=True)
        return 1
    地址 = Web桥.健康()["地址"]
    有前端 = os.path.exists(os.path.join(本目录, "web", "index.html"))

    print("=" * 74)
    print(f"  {软件名} · 机器人仿真工作台")
    print("=" * 74)
    print(f"  界面地址： {地址}")
    if not 有前端:
        print("  ⚠ 前端还没构建，浏览器里看到的是简版数据页（不是完整界面）")
        print("      构建：cd 前端 && node <pnpm.mjs> run build")
    print("  关掉：在这个终端按 Ctrl+C")
    print("=" * 74, flush=True)

    # ---- 2. 自动开浏览器（默认行为：双击就该看到界面）----
    if not args.不开浏览器:
        try:
            import webbrowser
            webbrowser.open(地址)
        except Exception as 异常:                                     # noqa: BLE001
            print(f"  ℹ 自动开浏览器失败（手动打开上面的地址即可）：{异常}", flush=True)

    # ---- 3. 决定模型与项目 ----
    模型路径, 说明 = _找模型()
    if not 模型路径:
        print("✗ 一个模型都没找到：用 --模型 指定一个，或先跑 工具/导入模型.py", flush=True)
        return 1
    项目名 = _选项目(模型路径, args.项目)
    if args.开重力:
        重力桥.设界面重力(True)

    print(f"  【模型】{os.path.basename(模型路径)}（{说明}）", flush=True)
    print(f"  【项目】{项目名 or '（无）'}", flush=True)
    if 当前实验 is not None:
        print(f"  【实验】{当前实验.key}（{当前实验.name}）", flush=True)

    # ---- 4. 装配并开跑（无窗模式：仿真在主线程）----
    #   装配方式与 `主程序窗口.py` **完全一致** —— 同一个 `装配器.按项目装配`、
    #   同一个 `安全注册表`。这就是 `启动外壳(无窗=True)` 的价值：
    #   换前端不换装配，算法作者那边一行都不用改。
    插件清单: list = []
    报告: list[str] = []
    if 项目名:
        try:
            插件清单, 报告 = 装配器.按项目装配(
                项目清单.读项目(项目名) if 项目名 else None, 项目名)
        except Exception as 异常:                                     # noqa: BLE001
            print(f"⚠ 项目装配失败（将不挂任何算法）：{type(异常).__name__}: {异常}",
                  flush=True)
            print("  （算法由 项目/*.json 声明：加算法 = 把 .py 放进 算法库/ 并写进项目文件）",
                  flush=True)
            print("   （注意：兼容性预检需要模型对象，装配时会给到；"
                  "换模型时会按项目重新装配）", flush=True)
    for 行 in 报告:
        print(f"  {行}", flush=True)
    print(f"【算法】{len(插件清单)} 个", flush=True)

    # 浏览器工作台也是无窗仿真宿主：使用明确的实时单步节拍，
    # 不依赖官方 Viewer 是否在发布刷新快照。
    注册表 = 插件框架.安全注册表(
        插件清单, 步进插件=插件框架.实时固定步进())
    配置 = 插件框架.viewer_protocol.ViewerConfig(
        title=args.标题, width=1200, height=800, gfx=os.environ.get("驭臂_gfx", ""))

    # 同步浏览器入口会在启动函数开头清理旧队列，因此把已校验的实验消息显式
    # 交给启动函数，让它在清理之后再预置；桌面入口则在“已就绪”后直接入队。
    预置消息 = experiment_cli.initial_messages(当前实验)
    return 启动.启动外壳(配置, 模型路径, None, 插件清单, 注册表,
                        插件框架.通知模型加载, 项目名=项目名, 无窗=True,
                        预置消息=预置消息,
                        实验名=(当前实验.key if 当前实验 is not None else ""))


if __name__ == "__main__":
    raise SystemExit(main())
