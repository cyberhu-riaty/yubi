"""
主程序窗口.py —— 主入口：**我们自己的窗口**，Web 界面 + 原生 3D 视口同级并列

它和浏览器入口的关系（一张表说清）：

    | 入口 | 窗口 | 界面 | 3D |
    |---|---|---|---|
    | **`主程序窗口.py`** | **平台原生窗口** | **窗口内网页视图里的 React** | **macOS / Windows 均已接入** |
    | `主程序Web.py`   | 无（外部浏览器打开） | 浏览器里的 React | ❌ 无原生 3D |

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
    .venv/bin/python 软件/主程序窗口.py                 # 起窗口（推荐）
    .venv/bin/python 软件/主程序窗口.py --检查           # 只自检，不开窗口
    .venv/bin/python 软件/主程序窗口.py --无3D           # 只要 Web 界面（排查用）
"""
from __future__ import annotations

import argparse
import os
import sys

本目录 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 本目录)

import 控制台

控制台.准备输出()

import Web桥
import 启动
import 插件系统 as 插件框架
import 装配器

import 项目 as 项目清单

软件名 = "小软件"

# 默认窗口尺寸（旧尺寸下 Web 内容会被裁，别改小）
默认宽, 默认高 = 1440.0, 920.0


def _找模型() -> tuple[str, str]:
    """与 `主程序Web.py` 同一套顺序（两个入口行为必须一致）。"""
    if 模型 := os.environ.get("驭臂_模型", "").strip():
        return 模型, "命令行/环境变量指定"
    try:
        import 模型桥
        上次 = 模型桥.读取上次模型()
        if 上次 and os.path.exists(上次):
            return 上次, "上次用过的模型"
    except Exception:  # noqa: BLE001, S110
        pass
    try:
        for 名字 in sorted(项目清单.列出项目() or []):
            项目 = 项目清单.读取项目(名字) or {}
            路径 = 项目.get("模型") or ""
            绝对 = 项目清单.绝对路径(路径) if 路径 else ""
            if 绝对 and os.path.exists(绝对):
                return 绝对, f"项目「{名字}」声明的模型"
    except Exception:  # noqa: BLE001, S110
        pass
    空场景 = os.path.join(os.path.dirname(本目录), "模型", "空场景.xml")
    if os.path.exists(空场景):
        return 空场景, "空场景（没有可用模型）"
    return "", "一个模型都没找到"


def _选项目(模型路径: str, 指名: str | None) -> str:
    try:
        if 指名:
            return str(指名)
        import 模型桥
        上次 = 模型桥.读取设置("上次项目", "")
        return str(上次) if 上次 else (项目清单.按模型找项目(模型路径) if 模型路径 else "")
    except Exception:                                                 # noqa: BLE001
        return ""


def 检查() -> int:
    print("=" * 76)
    print(f"  {软件名} · 宿主窗口自检")
    print("=" * 76)
    坏 = 0
    # ① 平台层能不能起窗口（由平台实现自己回答，入口不碰平台细节）
    try:
        import 平台适配层
        平台 = 平台适配层.取实现()
        可用, 原因 = 平台.可用()
        if 可用:
            print(f"  ✓ 窗口实现：{平台.名称}")
        else:
            坏 += 1
            print(f"  ✗ 窗口不可用（{平台.名称}）：{原因}")
    except Exception as 异常:                                         # noqa: BLE001
        坏 += 1
        print(f"  ✗ 平台适配层不可用：{type(异常).__name__}: {异常}")
    # ② 前端产物
    产物 = os.path.join(本目录, "web", "index.html")
    if os.path.exists(产物):
        print("  ✓ 前端产物：软件/web/index.html")
    else:
        坏 += 1
        print("  ✗ 前端产物不在（窗口里会是一片空白）")
        print("      构建：cd 前端 && node <pnpm.mjs> run build")
    # ③ 模型
    模型路径, 说明 = _找模型()
    print(f"  {'✓' if 模型路径 else '✗'} 模型："
          f"{os.path.basename(模型路径) if 模型路径 else '没找到'}（{说明}）")
    if not 模型路径:
        坏 += 1
    # ④ 契约
    try:
        import 契约
        print(f"  ✓ 契约：版本 {契约.版本}（下行 {len(契约.下行主题)} / "
              f"上行 {len(契约.上行主题)}）")
    except Exception as 异常:                                         # noqa: BLE001
        坏 += 1
        print(f"  ✗ 契约不可用：{异常}")
    # ⑤ 上行命令名（本入口会直接入队的那几个）
    try:
        import 契约 as _契约
        for 名 in ("命令.重力",):
            if _契约.取(名) is None:
                坏 += 1
                print(f"  ✗ 契约里没有上行命令「{名}」（本入口会用它开重力）")
            else:
                print(f"  ✓ 上行命令「{名}」在契约里")
    except Exception as 异常:                                         # noqa: BLE001
        坏 += 1
        print(f"  ✗ 上行命令检查失败：{异常}")
    # ⑥ 端口
    import socket
    口 = int(os.environ.get("驭臂_Web端口", "") or Web桥.默认端口)
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", 口)) == 0:
            print(f"  ⚠ 端口 {口} 已被占用（可能已有一个在跑；换端口用 --web口）")
        else:
            print(f"  ✓ 端口 {口} 可用")
    print()
    print("=" * 76)
    print(f"  {'✓ 可以启动' if 坏 == 0 else f'✗ {坏} 项要处理'}")
    print("=" * 76)
    return 1 if 坏 else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{软件名} · 宿主窗口（Web 界面 + 原生 3D 视口）")
    ap.add_argument("--web口", "--web-port", dest="web口", type=int, default=None)
    ap.add_argument("--项目", default=None, help="挂哪个项目的算法组")
    ap.add_argument("--模型", default=None, help="加载哪个模型")
    ap.add_argument("--开重力", dest="开重力", action="store_true",
                    help="启动时就推进物理（默认冻结在默认位置）")
    ap.add_argument("--无3D", dest="无3D", action="store_true",
                    help="不要 3D 视口（Web 界面铺满窗口；排查用）")
    ap.add_argument("--宽", type=float, default=默认宽)
    ap.add_argument("--高", type=float, default=默认高)
    ap.add_argument("--检查", action="store_true", help="不开窗口，只自检")
    ap.add_argument("--标题", default=f"{软件名} · 机器人仿真工作台")
    args = ap.parse_args(argv)

    if args.模型:
        os.environ["驭臂_模型"] = args.模型
    if args.web口:
        os.environ["驭臂_Web端口"] = str(args.web口)

    if args.检查:
        return 检查()

    # ---- 0. 先问平台层"能不能起窗口"（不能就给人话，而不是抛栈）----
    #   ★ 入口**不直接** import 任何平台相关模块（宿主窗口/AppKit/…）——
    #     那是平台适配层的职责。换平台时只改 `软件/平台适配层/`，本文件不动。
    try:
        import 平台适配层
        平台 = 平台适配层.取实现()
    except Exception as 异常:                                         # noqa: BLE001
        print(f"✗ 取不到窗口实现：{type(异常).__name__}: {异常}", flush=True)
        print("  （临时替代：软件/主程序Web.py —— 用外部浏览器看同一个界面）", flush=True)
        return 1
    可用, 原因 = 平台.可用()
    if not 可用:
        print(f"✗ 起不了窗口（{平台.名称}）：{原因}", flush=True)
        return 1

    口 = int(os.environ.get("驭臂_Web端口", "") or Web桥.默认端口)
    地址 = f"http://127.0.0.1:{口}/"

    # ---- 1. 模型/项目先定下来（视口要用模型路径）----
    模型路径, 说明 = _找模型()
    if not 模型路径:
        print("✗ 一个模型都没找到：用 --模型 指定一个", flush=True)
        return 1
    项目名 = _选项目(模型路径, args.项目)
    os.environ["驭臂_当前模型"] = 模型路径
    os.environ["驭臂_当前项目"] = 项目名
    # ★ `--开重力` 记在这里、**装配之后**才施用：装配过程会重置姿态/冻结物理
    #   （那是"刚加载模型别乱动"的默认行为），先设会被它盖掉 ——
    #   表现就是状态栏明明写着"开重力"，物理却还是"冻结"。
    要开重力 = bool(args.开重力)

    # ---- 2. Web 服务 ----
    桥 = Web桥.启动(端口=口)
    if not 桥.启用:
        print(f"✗ Web 服务起不来：{桥.出错}", flush=True)
        print("  端口可能被占；换一个：--web口 8899", flush=True)
        return 1

    # ---- 3. 仿真的装配与启动（后台线程：主线程要留给 AppKit）----
    插件清单, 报告 = [], []
    if 项目名:
        try:
            插件清单, 报告 = 装配器.按项目装配(
                项目清单.读项目(项目名) if 项目名 else None, 项目名)
        except Exception as 异常:                                     # noqa: BLE001
            print(f"⚠ 项目装配失败（将不挂任何算法）：{type(异常).__name__}: {异常}",
                  flush=True)

    print("=" * 76, flush=True)
    print(f"  {软件名} · 机器人仿真工作台（宿主窗口）", flush=True)
    print("=" * 76, flush=True)
    print(f"  界面地址 : {地址}（显示在窗口内的网页视图里）", flush=True)
    print(f"  模型     : {os.path.basename(模型路径)}（{说明}）", flush=True)
    print(f"  项目     : {项目名 or '（无 → 不挂算法，进去是静止的）'}", flush=True)
    print(f"  算法     : {len(插件清单)} 个", flush=True)
    if args.无3D:
        print("  ⚠ --无3D：本次不建 3D 视口", flush=True)
    print("=" * 76, flush=True)

    注册表 = 插件框架.安全注册表(插件清单)
    配置 = 插件框架.viewer_protocol.ViewerConfig(
        title=args.标题, width=int(args.宽), height=int(args.高), gfx="")

    # ★ 后台线程：与"有窗模式"同一套排法（窗口在哪，仿真就不在哪）。
    #   命令注入靠 `启动.命令队列` —— 主线程往里塞，仿真线程每圈排空。
    # ★ 3D 视口的"状态来源"：放在**仿真线程**里的观察者，只做一次引用替换
    #   （回调里绝不能碰 AppKit —— 那必须在主线程）
    视口槽 = {"视口": None, "待换模型": None}
    def 收到状态(快照):
        # ⚠️ 这个函数在**仿真线程**里被调用：只允许做"放好引用"这种事
        视口 = 视口槽["视口"]
        if 视口 is not None:
            视口.收_状态(快照)

    def 收到模型事件(事件):
        # 模型桥在换模型成功后会广播 ModelEvent；这里只记路径，绝不碰 AppKit。
        # 主线程的 _主线程每帧 会取走它，停旧渲染线程、重装新模型。
        路径 = str(getattr(事件, "path", "") or "")
        if 路径:
            视口槽["待换模型"] = 路径

    启动.设状态观察者(收到状态)
    启动.设模型观察者(收到模型事件)

    # `启动外壳(...后台线程=True)` 自己负责创建仿真线程。这里不再额外包一层
    # “启动线程”，也不猜固定等待时间；模型和插件真正就绪后会发出事件。
    启动码 = 启动.启动外壳(
        配置, 模型路径, None, 插件清单, 注册表,
        插件框架.通知模型加载, 项目名=项目名,
        无窗=True, 后台线程=True)
    if 启动码 != 0:
        Web桥.关闭()
        return int(启动码)
    已就绪, 就绪说明 = 启动.等待就绪(15.0)
    if not 已就绪:
        print(f"✗ {就绪说明}", flush=True)
        启动.请求停止()
        Web桥.关闭()
        return 1

    if 要开重力:
        # 装配完成后再开（见上面 `要开重力` 的说明）。
        # 走**和 Web 命令同一条路**：`命令桥.命令入队` → 仿真循环每圈排空。
        # 这样"命令行开的重力"和"界面上点的重力"走的是同一条通道，不会两套逻辑。
        try:
            import 命令桥 as _命令桥
            # ★ 主题名要用**契约里的名字**（`命令.重力`），不是消息类名（`重力状态`）。
            #   写错的话 `命令入队` 会回一句"不是登记过的上行命令"，然后静默不入队 ——
            #   表现就是"命令行说要开重力，仿真却一直停在 t=0.00s"（本次实测踩到）。
            好, 说明 = _命令桥.命令入队(
                启动.取命令队列(), "命令.重力", {"重力开": True}, 打印=False)
            if not 好:
                print(f"  ⚠ 开重力没能入队：{说明}", flush=True)
            print("  ✓ 已请求开重力（装配之后生效）", flush=True)
        except Exception as 异常:                                     # noqa: BLE001
            print(f"  ⚠ 开重力失败（不影响起窗口）：{type(异常).__name__}: {异常}",
                  flush=True)

    # ---- 4. 起窗口（这一步必须在主线程）----
    窗口码 = 0
    try:
        # 视口槽交给平台层：它建好原生渲染面后回填，状态观察者据此把每步状态喂进去。
        窗口码 = 平台.起(
            地址=地址, 标题=args.标题, 宽=args.宽, 高=args.高,
            命令队列=启动.取命令队列(), 无3D=args.无3D, 视口槽=视口槽)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在退出…", flush=True)
        窗口码 = 0
    finally:
        # 关闭顺序：先断开观察者，防止再给已销毁的视口送帧；再停仿真；
        # 最后关闭本地 Web 服务，释放端口。重复关闭也是安全的。
        启动.设状态观察者(None)
        启动.设模型观察者(None)
        已停止, 停止说明 = 启动.请求停止(3.0)
        if not 已停止:
            print(f"⚠ {停止说明}", flush=True)
            窗口码 = 1
        Web桥.关闭()
    return int(窗口码)


if __name__ == "__main__":
    raise SystemExit(main())
