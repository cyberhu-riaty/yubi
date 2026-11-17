"""
official_api.py —— **全工程唯一**一处 `import mujoco.experimental.*` 的地方

为什么要有这个文件（P3-b 的核心）：
    `mujoco.experimental.studio` 名字里的 "experimental" 是**真的**：官方不保证不改。
    而它原来散落在 **11 个文件**里被直接 import —— 一旦 MuJoCo 升级改了 API，
    报错会从十几个不相干的地方冒出来，而且往往是 `AttributeError: module has no
    attribute 'Xxx'` 这种 "看不出该改哪" 的形状。

    收敛到这里之后，**爆炸半径 = 1 个文件**；并且 `self_check()` 会在启动时把
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
    from official_api import messages, viewer_protocol          # 常规：模块对象
    from official_api import ux                                 # 需要时再取（较重的子模块）

    其余文件**不允许**再出现 `mujoco.experimental`（有专门的断言盯着，见
    `tools/selfchecks/official_api_selfcheck.py`）。
"""
from __future__ import annotations

import sys
from types import ModuleType

MUJOCO_VERSION_REQUIREMENT = ">=3.12"
KNOWN_GOOD_VERSIONS = ("3.13.0",)

# 我们实际依赖的名字。`self_check()` 会逐个核对；改 MuJoCo 版本后先跑它。
REQUIRED_SUBMODULES = (
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
REQUIRED_MESSAGE_SYMBOLS = (
    "handler", "Priority", "Message", "Snapshot", "Event", "StepEvent",
    "ModelEvent", "StateSnapshot", "StepControlSnapshot", "StepEvent",
)

_import_error: str = ""


def _load_required_modules():
    """一次性导入。失败时**不在这里抛**，把原因存下来交给 `self_check()` 说人话。"""
    global _import_error, mujoco
    try:
        import mujoco  # noqa: F401  （下面用它的版本号）
        from mujoco.experimental import studio  # noqa: F401
    except ImportError as exc:
        _import_error = f'{type(exc).__name__}: {exc}'
        return
    finally:
        pass

    for name in REQUIRED_SUBMODULES:
        try:
            module = __import__(f'mujoco.experimental.studio.{name}', fromlist=[name])
            globals()[name] = module
        except ImportError as exc:
            _import_error = f'子模块 {name} 导入失败：{exc}'
            return


_load_required_modules()
mujoco: ModuleType | None = globals().get("mujoco")


def _environment_command(arguments: str) -> str:
    """给当前平台返回仓库虚拟环境中的 Python 命令。"""
    if sys.platform == "win32":
        return f'.\\.venv\\Scripts\\python.exe {arguments}'
    return f'.venv/bin/python {arguments}'


def _required_module(name: str) -> ModuleType:
    """取子模块；拿不到就抛人话版异常（绝大多数调用点应该永远走不到这里）。"""
    module = globals().get(name)
    if module is None:
        raise SystemExit(missing_dependency_hint(name))
    return module


def __getattr__(attribute: str):
    """`from official_api import x` / `官方层.x` 的兜底：没导入成功时给人话版异常。

    ★ 为什么用 `__getattr__` 而不是在导入期直接 raise：
      导入期抛异常会变成"整个程序起不来"，连自检都跑不了。
      这样至少能进到 `self_check()`，把"到底缺哪一样、怎么修"打出来。
    """
    if attribute in REQUIRED_SUBMODULES:
        return _required_module(attribute)
    if attribute in ("ux", "dear_imgui", "implot"):
        # implot 在 mujoco.experimental 下（不在 studio 里），单独处理
        # 这条是**延迟**导入：dear_imgui 比 studio 本体更重，
        # 而且只有原生界面那条路才需要它。
        try:
            if attribute == "ux":
                module = __import__("mujoco.experimental.studio.ux", fromlist=["ux"])
            elif attribute == "implot":
                module = __import__("mujoco.experimental.implot", fromlist=["implot"]).implot
            else:
                module = __import__("mujoco.experimental.dear_imgui.dear_imgui",
                                  fromlist=["dear_imgui"])
        except ImportError as exc:
            check_command = _environment_command('-c "from official_api import ux; print(ux)"')
            raise SystemExit(
                f'\n✗ 取不到 {attribute}（{exc}）。\n'
                f'  它属于官方 experimental 子模块；当前 mujoco 可能不是完整 pip 包。\n'
                f'  检查：{check_command}\n') from exc
        globals()[attribute] = module
        return module
    raise AttributeError(f'官方层 里没有 {attribute!r}')


def missing_dependency_hint(name: str | None = None) -> str:
    '''拼一段"缺什么 + 为什么 + 怎么修"的人话。'''
    version = getattr(mujoco, "__version__", "未知") if mujoco else "未知"
    header = ("缺少：" + name) if name else ""
    startup_command = _environment_command("run_yubi.py")
    return (
        f'\n✗ 当前 Python 环境里没有可用的 Studio 插件系统：{header}\n\n'
        f'  你现在用的是：{sys.executable}\n'
        f"  mujoco 版本  ：{version}（要求 {MUJOCO_VERSION_REQUIREMENT}，实测可用 {', '.join(KNOWN_GOOD_VERSIONS)}）\n"
        f"  出错原因     ：{_import_error or '（见上）'}\n\n"
        f'  Studio 只在官方 **pip 包**（mujoco >= 3.12 完整版）里有；\n'
        f'  conda 渠道装的 mujoco 是「零件版」，不含界面层与插件系统。\n\n'
        f'  解决：\n'
        f'    cd <仓库根目录>\n'
        f'    {startup_command}\n'
        f'  （请确认 VS Code 也选中了仓库里的 .venv 解释器。）\n'
    )


# ---------------------------------------------------------------------------
# 自检：逐条核对"我们依赖的东西都还在"
# ---------------------------------------------------------------------------
def self_check() -> tuple[int, int, list[str]]:
    """返回 (通过项, 总项数, 问题列表)。任何问题都是**人话**，直接能照着修。"""
    passed = 0
    total = 0
    issues: list[str] = []

    # ① mujoco 本体
    total += 1
    if mujoco is None:
        issues.append(f'mujoco 导入失败：{_import_error}')
    else:
        passed += 1

    # ② 子模块
    for name in REQUIRED_SUBMODULES:
        total += 1
        module = globals().get(name)
        if module is None:
            issues.append(f"子模块 studio.{name} 缺失（{_import_error or '原因未知'}）")
        else:
            passed += 1

    # ③ messages 里的关键符号
    message_module = globals().get("messages")
    if message_module is not None:
        for symbol in REQUIRED_MESSAGE_SYMBOLS:
            total += 1
            if hasattr(message_module, symbol):
                passed += 1
            else:
                issues.append(
                    f'messages.{symbol} 不见了 —— 官方的消息类型/标签被改名或删掉了。\n'
                    f'      改法：在 软件/official_api.py 的 `REQUIRED_MESSAGE_SYMBOLS` 里更新名字，'
                    f'并在全工程搜 `messages.{symbol}` 跟着改。')

    # ④ 端点做 isinstance 校验用的三个基类（**在 messages 里**，不在 viewer_protocol）
    #    ★ 查证过：`endpoints.py` 第 16 行是
    #        from mujoco.experimental.studio import messages as vp
    #      所以源码里写的 `vp.Snapshot` 其实指的是 `messages.Snapshot`。
    #      （我第一版把这里写成 viewer_protocol，自检立刻报了三条假警报 —— 留下来当注释。）
    if message_module is not None:
        for symbol in ("Message", "Event", "Snapshot"):
            total += 1
            if hasattr(message_module, symbol):
                passed += 1
            else:
                issues.append(f'messages.{symbol} 不见了（端点按它做 isinstance 校验，必须有）')

    protocol_module = globals().get("viewer_protocol")

    # ⑤ 步进插件与配置类
    step_module = globals().get("step_control")
    total += 1
    if step_module is not None and hasattr(step_module, "StepControl"):
        passed += 1
    else:
        issues.append("step_control.StepControl 不见了（物理推进靠它，缺了仿真不动）")

    total += 1
    if protocol_module is not None and hasattr(protocol_module, "ViewerConfig"):
        passed += 1
    else:
        issues.append("viewer_protocol.ViewerConfig 不见了（起窗口要它）")

    return passed, total, issues


__all__ = [
    "MUJOCO_VERSION_REQUIREMENT", "KNOWN_GOOD_VERSIONS",
    "self_check", "missing_dependency_hint",
]


if __name__ == "__main__":
    passed, total, issues = self_check()
    print("=" * 74)
    print(f'  官方层自检：{passed}/{total}')
    print("=" * 74)
    if issues:
        for issue in issues:
            print(f'  ✗ {issue}')
        print(missing_dependency_hint())
        raise SystemExit(1)
    print("  ✓ 我们依赖的每一个名字都还在（升级 MuJoCo 后先跑这个）")
    print(f'  mujoco {mujoco.__version__}')
