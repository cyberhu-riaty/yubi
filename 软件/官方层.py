"""
官方层.py —— **全工程唯一**一处 `import mujoco.experimental.*` 的地方

为什么要有这个文件（P3-b 的核心）：
    `mujoco.experimental.studio` 名字里的 "experimental" 是**真的**：官方不保证不改。
    而它原来散落在 **11 个文件**里被直接 import —— 一旦 MuJoCo 升级改了 API，
    报错会从十几个不相干的地方冒出来，而且往往是 `AttributeError: module has no
    attribute 'Xxx'` 这种 "看不出该改哪" 的形状。

    收敛到这里之后，**爆炸半径 = 1 个文件**；并且 `自检()` 会在启动时把
    "我们依赖的每一个名字都还在不在" 逐条核一遍，缺了就直接说人话。

═══ 为什么不能"自己定义一套消息类"把官方彻底甩掉 ═══════════════════════
    认真查过官方实现，答案是**不行**（至少不能只改一边）：

      · `endpoints.ViewerEndpoint.send_to_sim()` 第一件事就是
            if isinstance(message, vp.Event):   ...
            elif isinstance(message, vp.Snapshot): ...
            else: raise TypeError('expected Event or Snapshot, got ...')
        ——**必须是官方基类的实例**，我们自造的类会被直接拒收。

      · `plugin_registry.PluginRegistry.dispatch()` 按 `type(message).__mro__`
        逐层找 handler —— 所以消息的**类身份**参与路由，不只是字段。

    结论：只要还想用官方那个 19 面板窗口（`主程序.py` 那条路），
    消息就必须是真的官方类。我们能做、且真正降低风险的是：
      **把依赖集中到一处 + 启动时逐条自检 + 升级只改一处**。
    （想彻底甩掉 Studio，等价于"官方窗口整条路都不要了"，那是另一个量级的工程，
      而且会丢掉 19 个现成面板 —— 与"功能一点也不能少"冲突。）

═══ 用法 ═══════════════════════════════════════════════════════════════
    from 官方层 import messages, viewer_protocol          # 常规：模块对象
    from 官方层 import ux                                 # 需要时再取（较重的子模块）

    其余文件**不允许**再出现 `mujoco.experimental`（有专门的断言盯着，见
    `工具/验证/官方层自检.py`）。
"""
from __future__ import annotations

import sys
from types import ModuleType

MUJOCO版本要求 = ">=3.12"
已知可用版本 = ("3.13.0",)

# 我们实际依赖的名字。`自检()` 会逐个核对；改 MuJoCo 版本后先跑它。
必需子模块 = (
    "messages",         # 消息类型 + @handler 标签 + Priority
    "step_control",     # 官方默认步进插件（物理推进靠它）
    "viewer_app",       # 官方 GUI（19 个面板）
    "viewer_protocol",  # 配置类 / 端点协议
    "launch_native",    # 原生窗口
    "launch_thread",    # 线程版端点（无窗模式用不到，但接口要一致）
    "viewer_handle",    # 仿真侧句柄
    "endpoints",        # 消息通道
    "plugin_registry",  # 插件注册表
    "sim",              # 仿真侧辅助（重力桥用）
)

# `messages` 里我们用到的具体名字（不只子模块存在，内部符号也得在）
必需消息符号 = (
    "handler", "Priority", "Message", "Snapshot", "Event", "StepEvent",
    "ModelEvent", "StateSnapshot", "StepControlSnapshot", "StepEvent",
)

_错误: str = ""


def _导入():
    """一次性导入。失败时**不在这里抛**，把原因存下来交给 `自检()` 说人话。"""
    global _错误, mujoco
    try:
        import mujoco  # noqa: F401  （下面用它的版本号）
        from mujoco.experimental import studio  # noqa: F401
    except ImportError as 异常:
        _错误 = f"{type(异常).__name__}: {异常}"
        return
    finally:
        pass

    for 名 in 必需子模块:
        try:
            模块 = __import__(f"mujoco.experimental.studio.{名}", fromlist=[名])
            globals()[名] = 模块
        except ImportError as 异常:
            _错误 = f"子模块 {名} 导入失败：{异常}"
            return


_导入()
mujoco: ModuleType | None = globals().get("mujoco")


def _环境命令(参数: str) -> str:
    """给当前平台返回仓库虚拟环境中的 Python 命令。"""
    if sys.platform == "win32":
        return rf".\.venv\Scripts\python.exe {参数}"
    return f".venv/bin/python {参数}"


def _取(名: str) -> ModuleType:
    """取子模块；拿不到就抛人话版异常（绝大多数调用点应该永远走不到这里）。"""
    模块 = globals().get(名)
    if 模块 is None:
        raise SystemExit(_缺东西提示(名))
    return 模块


def __getattr__(属性: str):
    """`from 官方层 import x` / `官方层.x` 的兜底：没导入成功时给人话版异常。

    ★ 为什么用 `__getattr__` 而不是在导入期直接 raise：
      导入期抛异常会变成"整个程序起不来"，连自检都跑不了。
      这样至少能进到 `自检()`，把"到底缺哪一样、怎么修"打出来。
    """
    if 属性 in 必需子模块:
        return _取(属性)
    if 属性 in ("ux", "dear_imgui", "implot"):
        # implot 在 mujoco.experimental 下（不在 studio 里），单独处理
        # 这条是**延迟**导入：dear_imgui 比 studio 本体更重，
        # 而且只有原生界面那条路才需要它。
        try:
            if 属性 == "ux":
                模块 = __import__("mujoco.experimental.studio.ux", fromlist=["ux"])
            elif 属性 == "implot":
                模块 = __import__("mujoco.experimental.implot", fromlist=["implot"]).implot
            else:
                模块 = __import__("mujoco.experimental.dear_imgui.dear_imgui",
                                  fromlist=["dear_imgui"])
        except ImportError as 异常:
            raise SystemExit(
                f"\n✗ 取不到 {属性}（{异常}）。\n"
                f"  它属于官方 experimental 子模块；当前 mujoco 可能不是完整 pip 包。\n"
                f"  检查：{_环境命令('-c \"from 官方层 import ux; print(ux)\"')}\n") from 异常
        globals()[属性] = 模块
        return 模块
    raise AttributeError(f"官方层 里没有 {属性!r}")


def _缺东西提示(名: str | None = None) -> str:
    '''拼一段"缺什么 + 为什么 + 怎么修"的人话。'''
    版本 = getattr(mujoco, "__version__", "未知") if mujoco else "未知"
    头 = ("缺少：" + 名) if 名 else ""
    启动命令 = _环境命令("软件/主程序窗口.py")
    return (
        f"\n✗ 当前 Python 环境里没有可用的 Studio 插件系统：{头}\n\n"
        f"  你现在用的是：{sys.executable}\n"
        f"  mujoco 版本  ：{版本}（要求 {MUJOCO版本要求}，实测可用 {', '.join(已知可用版本)}）\n"
        f"  出错原因     ：{_错误 or '（见上）'}\n\n"
        f"  Studio 只在官方 **pip 包**（mujoco >= 3.12 完整版）里有；\n"
        f"  conda 渠道装的 mujoco 是「零件版」，不含界面层与插件系统。\n\n"
        f"  解决：\n"
        f"    cd <仓库根目录>\n"
        f"    {启动命令}\n"
        f"  （请确认 VS Code 也选中了仓库里的 .venv 解释器。）\n"
    )


# ---------------------------------------------------------------------------
# 自检：逐条核对"我们依赖的东西都还在"
# ---------------------------------------------------------------------------
def 自检() -> tuple[int, int, list[str]]:
    """返回 (通过项, 总项数, 问题列表)。任何问题都是**人话**，直接能照着修。"""
    通过 = 0
    总数 = 0
    问题: list[str] = []

    # ① mujoco 本体
    总数 += 1
    if mujoco is None:
        问题.append(f"mujoco 导入失败：{_错误}")
    else:
        通过 += 1

    # ② 子模块
    for 名 in 必需子模块:
        总数 += 1
        模块 = globals().get(名)
        if 模块 is None:
            问题.append(f"子模块 studio.{名} 缺失（{_错误 or '原因未知'}）")
        else:
            通过 += 1

    # ③ messages 里的关键符号
    消息 = globals().get("messages")
    if 消息 is not None:
        for 符号 in 必需消息符号:
            总数 += 1
            if hasattr(消息, 符号):
                通过 += 1
            else:
                问题.append(
                    f"messages.{符号} 不见了 —— 官方的消息类型/标签被改名或删掉了。\n"
                    f"      改法：在 软件/官方层.py 的 `必需消息符号` 里更新名字，"
                    f"并在全工程搜 `messages.{符号}` 跟着改。")

    # ④ 端点做 isinstance 校验用的三个基类（**在 messages 里**，不在 viewer_protocol）
    #    ★ 查证过：`endpoints.py` 第 16 行是
    #        from mujoco.experimental.studio import messages as vp
    #      所以源码里写的 `vp.Snapshot` 其实指的是 `messages.Snapshot`。
    #      （我第一版把这里写成 viewer_protocol，自检立刻报了三条假警报 —— 留下来当注释。）
    if 消息 is not None:
        for 符号 in ("Message", "Event", "Snapshot"):
            总数 += 1
            if hasattr(消息, 符号):
                通过 += 1
            else:
                问题.append(f"messages.{符号} 不见了（端点按它做 isinstance 校验，必须有）")

    协议 = globals().get("viewer_protocol")

    # ⑤ 步进插件与配置类
    步进 = globals().get("step_control")
    总数 += 1
    if 步进 is not None and hasattr(步进, "StepControl"):
        通过 += 1
    else:
        问题.append("step_control.StepControl 不见了（物理推进靠它，缺了仿真不动）")

    总数 += 1
    if 协议 is not None and hasattr(协议, "ViewerConfig"):
        通过 += 1
    else:
        问题.append("viewer_protocol.ViewerConfig 不见了（起窗口要它）")

    return 通过, 总数, 问题


if __name__ == "__main__":
    通过, 总数, 问题 = 自检()
    print("=" * 74)
    print(f"  官方层自检：{通过}/{总数}")
    print("=" * 74)
    if 问题:
        for 条 in 问题:
            print(f"  ✗ {条}")
        print(_缺东西提示())
        raise SystemExit(1)
    print("  ✓ 我们依赖的每一个名字都还在（升级 MuJoCo 后先跑这个）")
    print(f"  mujoco {mujoco.__version__}")
