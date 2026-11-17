"""
plugin_system.py —— 控制器插件、消息派发和错误隔离的运行核心

为什么要单独一个文件？
  官方的插件系统在 `mujoco.experimental.studio` 里，"experimental" = 官方不保证不改。
  11 周内它已经改过 4 次结构。所以我们把**所有官方调用集中在这一个文件**，
  以后官方再改，只需要改这里；主程序和 plugins/ 里的控制算法一行都不用动。

这个文件给外壳补了 3 件官方没有的东西：
  ① 插件出错隔离 —— 一个插件崩了，只停它自己，整个软件继续跑（官方会一起挂）
  ② 版本自检     —— 启动时打印 mujoco 版本 + API 指纹，跟"已知能跑"的版本比对
  ③ 插件清单     —— 每个插件的名字/版本/需要什么，启动时列一张表出来

★ 给用户（你）的规则：**写控制算法不需要看懂这个文件**，
  只要 `from plugin_system import ControlPlugin, step_handler`，然后照着算法库里的例子写。
"""
from __future__ import annotations

import os
import sys
import time
import traceback

# ---------------------------------------------------------------------------
# ① 官方 API 的唯一入口
# ---------------------------------------------------------------------------
MUJOCO_VERSION_REQUIREMENT = ">=3.12"          # 插件系统从这个版本开始有
KNOWN_GOOD_VERSIONS = ("3.13.0",)          # 我们实测跑通过的 mujoco 版本（见第 0 步验收报告）


def _import_official():
    """取官方 Studio 的各子模块。

    ★ 现在**不在本文件碰 `mujoco.experimental`** —— 全部经由 `软件/official_api.py`
      （全工程唯一一处 import 官方实验层的地方）。
      好处：MuJoCo 升级改了 API，只需改那一个文件，`official_api.self_check()` 会逐条指出缺什么。
      失败时抛人话版异常（附解决办法）。
    """
    try:
        import official_api as _official
        mujoco = _official.mujoco
        messages = _official.messages
        step_control = _official.step_control
        viewer_app = _official.viewer_app
        viewer_protocol = _official.viewer_protocol
        launch_native = _official.launch_native
        launch_thread = _official.launch_thread
        viewer_handle = _official.viewer_handle
        endpoints = _official.endpoints
        if mujoco is None:
            raise ImportError("官方层里 mujoco 为空")
    except (ImportError, SystemExit) as exc:
        try:
            import official_api as _official_check
            passed, total, issues = _official_check.self_check()
            details = "\n".join(f"    · {issue}" for issue in issues) or "    （无明细）"
            hint = _official_check.missing_dependency_hint()
        except Exception:                                             # noqa: BLE001
            passed, total, details, hint = 0, 0, "    （连自检都跑不起来）", ""
        raise SystemExit(
            f"\n✗ 取不到 Studio 插件系统（{type(exc).__name__}: {exc}）\n\n"
            f"  官方层自检：{passed}/{total}\n{details}\n{hint}"
        ) from exc
    return (mujoco, messages, step_control, viewer_app, viewer_protocol,
            launch_native, launch_thread, viewer_handle, endpoints)


(mujoco, messages, step_control, viewer_app, viewer_protocol,
 launch_native, launch_thread, viewer_handle, endpoints) = _import_official()

# 全局仿真速度命令属于工作台外壳，不属于用户控制器。放在实时步进器里处理，
# 这样倍率只改变每个物理步之间的墙钟等待，不会改 MuJoCo timestep。
from simulation_control import SimulationControlCommand  # noqa: E402

step_handler = messages.handler              # Mark a method as a Studio message handler.

# ---------------------------------------------------------------------------
# 优先级：**仿真侧不参与排序**（但别搞混 —— 窗口侧是参与的，两侧行为不一样）
# ---------------------------------------------------------------------------
# ★ 先记住这条分界线，把两侧混起来想会得出错误结论：
#
#   ┌ 窗口侧（面板 / 界面桥 …）：走**官方**派发 → priority **有效**
#   │   插件由 `runtime_engine.py` 通过 `launch_native.run_native_viewer(..., plugins=窗口插件)`
#   │   交给官方；官方 `Viewer.dispatch` → `PluginRegistry.dispatch` 把同类型处理器
#   │   收成一条链并**按 priority 降序执行**（`sort(key=…, reverse=True)`，实测见
#   │   `mujoco/experimental/studio/plugin_registry.py`）。
#   │   所以面板里写 `priority=CRITICAL` 是**真起作用**的
#   │   （例如外观面板必须在所有窗口 Begin 之前跑完换肤）。
#   │
#   └ 仿真侧（控制算法 / 模型应用器 / 参数应用器 …）：走**我们的**派发 → priority **无效**
#       本文件为了做出错隔离没有走官方那条路：`SafeRegistry.process_message()` 是逐个插件
#       依次调用，顺序 = `_targets` 列表顺序 = 项目文件里
#       `算法` 列表的顺序（官方 StepControl 固定排在第 0 个）。
#
#   一句话：**面板看 priority，控制算法看装配顺序。**
#
# 仿真侧的三条后果（都实测过）：
#   ① **跨插件**"谁说了算"只看列表顺序：排在最后的最后写 `ctrl[:]`，它赢。
#      `@每步(priority=…)` 在这里**完全不起作用** —— 它只是把档位记在处理器上，
#      我们的 `_单独派发()` 不读它（官方 `_discover_handlers` 本身也不排序）。
#   ② **单个插件内部**的多个处理器按 `dir()` 字母序走，所以同一个插件里想控制先后，
#      别指望 priority，改方法名或合并成一个方法。
#   ③ 算法作者写的 priority 声明**不算白写**：保留它贴合官方语义，
#      日后若真改成按 priority 排序，这些声明会自然生效。
#
# 想让某个算法赢：在界面【Algorithms】面板把它调到列表最后，或改项目文件的算法列表。
# 历史教训：曾有 5 个项目都写 `"算法": "*"`，扫描顺序让【正弦摆动】排到最后，
# 于是它偷偷盖住了关节 PD（表现为"机械臂按正弦来回摆"）。见 CHANGELOG v0.4.1。
Priority = messages.Priority                 # CRITICAL=1000 > USER=100 > LIBRARY=10 > INTERNAL=1


# ---------------------------------------------------------------------------
# ② 插件基类：给用户一个"填空题"模板
# ---------------------------------------------------------------------------
class ControlPlugin:
    """所有控制算法的爸爸。子类只需要写：名称 + 每步控制()。

    类属性（写在子类里，纯数据，不执行代码）：
        名称    : str   插件名，启动清单里显示
        版本    : str   插件版本
        说明    : str   一句话说明（中文，可以写很清楚）
        作者    : str   谁写的（可选）
    方法（必须实现）：
        每步控制(self, event: messages.StepEvent) -> bool
            每转一圈仿真调用一次。在这里读状态、算力矩、写 event.data.ctrl[:]。
            ★ 必须写类型标注 event: messages.StepEvent，否则官方 @每步 会报错。
            ★ 返回 False = 不拦截（让别人也能看到）；返回 True = 吃掉消息（后面的人收不到）。
    """

    name = "未命名插件"
    version = "0.0"
    english_name = ""
    description = ""
    author = ""
    # 本算法是否"接管方向盘"——也就是会不会往 `event.data.ctrl[:]` 里写力矩。
    #
    # ★ 为什么要声明这件事（踩过的真实困扰）：
    #   多个算法都写 `ctrl[:]` 时，**后装配的整体覆盖前面的** —— 被覆盖的那个
    #   其实一步都没生效，但界面上照样显示"✓ 已加载"，用户完全看不出来。
    #   实测：`末端两点运动`(任务空间) + `关节pd控制` 同时挂、关节PD 在后时，
    #   末端算法的输出被整体盖掉，机械臂纹丝不动地按关节 PD 走，
    #   末端离目标点 394.7 mm（单独跑它时是 0.1 mm）。
    #
    #   有了这个声明，外壳就能在装配时报一句"这几个都在写 ctrl，只有最后一个生效"，
    #   把"静默被掩盖"变成"看得见的提示"。
    #
    # 语义说明（别当它保证"永不写 ctrl"）：这个标记表示**默认会不会驱动机器人**，
    # 用来判断"多个算法是否在抢同一个方向盘"。所以：
    #   · 默认 True —— 新写算法的人多半就是要控制机器人，忘了声明也不会被漏报；
    #   · 平时不写 ctrl 的算法（录制/辨识/展示）显式声明 False，
    #     否则会被算进"抢方向盘"的名单里、制造假警告；
    #   · 像"数据录制"这种**平时不写、回放时才写**的，仍算 False
    #     —— 回放是用户主动点的，不是它的默认行为。
    takes_control = True
    # Set by the assembler to the stable module identifier (ASCII).  Parameter
    # tables and persisted project parameters are addressed by this identifier,
    # never by the Chinese display `name`.
    plugin_id = ""
    # Legacy persisted parameter names map to the current English identifier.
    # Old project files keep loading after the parameter IDs were migrated.
    parameter_aliases: dict[str, str] = {}

    # ---- 插件自己的状态（比如"跑了多少步"），由外壳负责收集 ----
    def status(self) -> dict:
        """返回要在启动清单里显示的一行摘要，例如 {'跟踪误差': '0.12 mm'}。"""
        return {}

    # ------------------------------------------------------------------
    # ★ 可调参数：让界面上的滑杆直接改你插件的参数（不用改文件、不用重启）
    #
    # 你在插件里声明"哪些类属性可以调"，界面上就会出现对应的滑杆：
    #
    #     def adjustable_parameters(self) -> dict:
    #         return {"KP": {"value": self.KP, "range": (10.0, 20000.0)},
    #                 "KD": {"value": self.KD, "range": (0.0, 500.0)}}
    #
    # 键名必须是**插件的类属性名**（例如 KP）。界面拖动后，外壳会自动改它，
    # 你的 每步控制() 下一次执行就直接用上新值 —— 不需要写任何接收代码。
    #
    # 不声明 `adjustable_parameters()` 的插件不会出现在参数面板里，没有任何影响。
    # ------------------------------------------------------------------
    def adjustable_parameters(self) -> dict:
        """Return {name: {value, range, step?, unit?}} for GUI editing."""
        return {}

    def set_parameter(self, name: str, value: float) -> str:
        """外壳调这个来改参数。返回 "" 表示成功，否则返回失败原因。

        ★ 这里会**按插件自己声明的 `范围` 校验**（P1 加）。
          为什么必须校验，而不是"界面会限制所以不用管"：
            界面的滑杆确实被限制在 `范围` 内，但参数的来源**不止界面** ——
            项目文件（人可以直接编辑）、Web 命令、识别结果回填都能送值进来。
            实测踩过：Web 端发了 KP=99999（范围是 10~20000），
            基类不校验 → 照单全收 → 写回项目文件 → 界面上显示的仍是旧值，
            而**实际生效的是那个越界值**。这种"显示和实际不一致"比直接报错危险得多。
          校验点放在基类而不是各插件里：`adjustable_parameters()` 声明的范围就是契约，
          基类照着执行一次，所有插件自动受益，也让"范围"这个字段真的有意义。
        """
        canonical_name = self.parameter_aliases.get(name, name)
        attribute_name = canonical_name
        if not hasattr(self, attribute_name):
            return f"插件 {type(self).__name__} 没有参数「{name}」"
        numeric_value = float(value)
        value_range = None
        try:
            declarations = self.adjustable_parameters() or {}
            item = declarations.get(canonical_name) or {}
            value_range = item.get("range")
        except Exception:                                                # noqa: BLE001
            # 参数声明出错不该让"改参数"整个失败：退回旧行为（不校验）
            value_range = None
        if value_range is not None:
            try:
                low, high = float(value_range[0]), float(value_range[1])
                if not (low <= numeric_value <= high):
                    return (f"【{getattr(self, 'name', type(self).__name__)}】"
                            f"参数「{name}」超出范围：{numeric_value:g} 不在 [{low:g}, {high:g}] 内")
            except (TypeError, ValueError, IndexError):
                pass                       # 范围写得不规范就跳过校验，不因它拦住改参数
        try:
            setattr(self, attribute_name, numeric_value)
            return ""
        except Exception as exc:                                        # noqa: BLE001
            return f"设置 {name} 失败：{exc}"

    def receive_model(self, event) -> None:
        """可选：模型加载后调一次。要记住模型/数据对象时在这里拿（比如做逆运动学）。"""
        return None

    def check_model_compatibility(self, model) -> str:
        """可选：**切换模型前**的兼容性预检。返回 "" = 兼容；否则返回人话原因。

        ★ 为什么要有这个钩子（这是踩过坑才加的）：
          以前一个算法在该模型上跑不了，只能"跑起来 → 抛异常 → 被出错隔离停用"。
          代价有三个，都很糟：
            ① 停用是**不可恢复**的（同一个插件再错一次才停，但换回合适的模型也不会自动
               恢复），用户看到的现象是"切回 UR5e 也不动了"；
            ② 异常发生在每步控制() 里，终端刷一堆堆栈，真正的原因被淹没；
            ③ 界面上的算法列表照样显示它挂着 —— 看起来在跑，其实早停了。

          有了这个钩子，外壳在**装配时**就问一遍：不兼容的算法**根本不启用**，
          并把原因写进项目状态发给界面。于是"挂着的算法"和"真正在跑的算法"
          永远一致，也不会有异常。

        写实现时的约定（两条，都很重要）：
          · **别抛异常**：拿不准就返回 ""（放行）。预检是为了少踩坑，不是为了拦人。
          · **用属性判断，别读 data**：这里只知道 model（`模型.nq` / `模型.nu` /
            `模型.nbody` / `模型.body()` / `模型.jnt_type` …），data 还没建好。
        """
        return ""

    def bind_model_path(self, path: str) -> None:
        """可选：模型文件路径变化时调一次（要按路径查表、重建模型的插件用它）。

        ★ 以前这个钩子只存在于 `外壳/启动.py` 的 `hasattr` 探测里，基类没声明，
          所以"有哪些扩展点"要靠读外壳代码才知道。现在收进基类，成为正式契约。
        """
        return None

    def model_changed(self, path: str, model, data) -> None:
        """可选：换模型**之后**调一次 —— 清掉跟旧模型绑定的缓存与中间结果。

        与 `模型兼容性` 的分工：
            `模型兼容性` 在换**之前**问"能不能跑"（不兼容就不启用）；
            `模型已切换` 在换**之后**通知"换好了"（清缓存、重建索引、重置状态）。

        典型实现见 `算法库/通用/参数辨识插件.py`：它在这里把采样数据、
        标称值、辨识结果全部清空，并按新模型重查可辨识参数表 —— 不清的话，
        你会看到"xArm7 的辨识结果"里混着 UR5e 的数据。
        """
        return None


# ---------------------------------------------------------------------------
# ③ 安全注册表：插件出错隔离（官方没有，这是我们要补的第一个功能）
# ---------------------------------------------------------------------------
# 当前生效的注册表（给"仿真侧插件"一个正规的取用入口）
#
# ★ 为什么需要它：插件有时要"再派发一条消息"（例如【Display】展示模式要在官方 StepControl
#   之前把暂停状态改写掉）。派发的唯一入口是 `SafeRegistry.process_message` ——
#   这个函数就是那个受控入口。
# ---------------------------------------------------------------------------
_current_registry = None

# `StepEvent` 的类型在这里缓存一次：`处理消息()` 是 ~500 Hz 的热路径，
# 每次去 `messages.StepEvent` 查属性是白花的时间。
_STEP_EVENT_TYPE = messages.StepEvent


def get_registry():
    """返回当前生效的安全注册表；还没建好时返回 None。"""
    return _current_registry


# ---------------------------------------------------------------------------
# 背景：以前"用哪些算法"写在 `主程序.py` 的【插件清单】里，启动后永不改变；
#       方案 C 改成由 `项目/xxx.json` 声明，**点模型 → 换一组算法**。
#       于是需要"运行期替换用户算法集合"这个能力 —— 而它就是 `安全注册表` 的本职
#       （它拥有 `_用户插件` 这本账），所以加在这里，而不是让外壳去 append 私有列表。
#
# `SafeRegistry` 负责替换用户插件集合，运行引擎无需直接修改它的私有列表。
# ---------------------------------------------------------------------------
class FixedStep:
    """每次 StepEvent 恰好推进一个物理步；供离线批处理实验使用。

    无界面批处理实验不需要等待墙钟时间，但必须保持
    “一次控制计算对应一个物理步”，所以不能简单把实时倍率调得很大。
    """

    @messages.handler(priority=messages.Priority.INTERNAL)
    def step(self, event: messages.StepEvent) -> bool:
        mujoco.mj_step(event.model, event.data)
        return False


class RealtimeFixedStep:
    """无窗工作台的实时物理节拍器。

    每条 StepEvent 只执行一次 ``mj_step``，并按模型 timestep 等待；
    因此“一次控制计算 = 一个物理步”，且仿真时间大致跟墙钟时间一致。
    暂停由安全注册表的“世界冻结闸门”处理，本类只负责步进与节拍。
    """

    def __init__(self):
        self._next_step_time: float | None = None
        self._model_identity: int | None = None
        self._speed_multiplier = 1.0

    @messages.handler
    def set_speed(self, command: SimulationControlCommand) -> bool:
        action = str(getattr(command, "action", "") or "")
        if action != "speed":
            return False
        self._speed_multiplier = max(
            0.25, min(4.0, float(getattr(command, "speed_multiplier", 1.0)))
        )
        # 重新从当前墙钟对齐，防止切换倍率后追赶旧节拍而突然连跑。
        self._next_step_time = None
        return False

    @messages.handler(priority=messages.Priority.INTERNAL)
    def step(self, event: messages.StepEvent) -> bool:
        now = time.perf_counter()
        physics_dt = max(float(event.model.opt.timestep), 1e-6)
        wall_dt = physics_dt / self._speed_multiplier

        # 换模型、刚启动或暂停较久后，从“现在”重新对齐；
        # 否则会为了追赶旧时刻而瞬间连跑很多步。
        if (self._next_step_time is None or self._model_identity != id(event.model)
                or now - self._next_step_time > 0.1):
            self._next_step_time = now
            self._model_identity = id(event.model)

        remaining = self._next_step_time - now
        if remaining > 0:
            time.sleep(remaining)

        mujoco.mj_step(event.model, event.data)
        self._next_step_time += wall_dt
        return False


class SafeRegistry:

    """包住官方的 PluginRegistry，给每个插件加「出错隔离」。

    官方行为：任何一个插件抛异常 → 整个 dispatch 中断 → 软件直接挂。
    我们的行为：某个插件抛异常 → 中文报错 + 关掉这一个插件 → 其余照常跑。

    ★ 一个必须记住的前提（我们踩过这个坑）：
      **真正"把物理往前推"的是官方的 StepControl 插件**，不是 ViewerHandle.sync。
      sync 只负责"派发 StepEvent"；StepControl 收到 StepEvent 才去 mj_step。
      所以这里必须把 StepControl 一起注册进来，否则你的控制律会被调用 25 万次，
      但仿真时间一直停在 0（机械臂纹丝不动）。
    """

    def __init__(self, plugins: list, step_plugin=None):
        global _current_registry
        # 未显式指定时保持官方 StepControl；工作台和批处理会在入口处
        # 分别传入“实时固定步进”和“固定一步”，避免隐式改变其它模式。
        self._targets = [step_plugin or step_control.StepControl(), *plugins]
        _current_registry = self          # 登记给 取注册表() 用（见文件上方说明）
        self._user_plugins = list(plugins)
        self._error_counts: dict[str, int] = {}
        self._disabled: set[str] = set()
        # ---- ★ 契约例外 ③：世界冻结闸门（见文件上方那段说明）----
        #   `_冻结判据` 是一组无参可调用：任一返回 True 就**不派发步进事件** →
        #   官方 StepControl 收不到 StepEvent → 不调 advance() → 物理完全不走。
        self._freeze_predicates: list = []

    def add_plugin(self, plugin) -> None:
        """运行期再挂一个插件进来（外壳内部用，比如参数应用器）。

        注意：不放进 `_用户插件`（那本账是给用户控制算法用的），
        所以它不会出现在插件清单/状态快照里，但同样享受逐个派发与出错隔离。
        """
        self._targets.append(plugin)

    def add_freeze_predicate(self, predicate) -> None:
        """★ 契约例外 ③：登记一个"世界是否冻结"的判据（无参、返回 bool）。

        任一判据返回 True → `处理消息()` **不派发** `StepEvent` → 官方 StepControl
        收不到步进事件 → 不调 `advance()` → **物理完全不走**。

        为什么需要这个闸门（这是实测踩出来的）：
          「加载重力」曾经靠"在派发快照时改写 `StepControlSnapshot.pause_state`"来实现冻结。
          那条路**依赖官方 ViewerApp 每帧发快照**，而实测在真实运行里
          **6 秒内收到 0 条快照** —— 于是冻结从未生效，模型一进模型就掉到偏离默认位置
          0.5~0.8 rad 的地方。单独写小程序测时因为手工构造快照，反而是"通过"的。
          所以改成不依赖任何外部消息：直接在外壳唯一的派发入口上问一句。
        """
        if predicate not in self._freeze_predicates:
            self._freeze_predicates.append(predicate)

    def remove_freeze_predicate(self, predicate) -> None:
        """注销判据（换模型/卸载内置件时用）。"""
        try:
            self._freeze_predicates.remove(predicate)
        except ValueError:
            pass

    def is_frozen(self) -> bool:
        """现在是否应冻结物理（任一判据为真即冻结）。"""
        for predicate in list(self._freeze_predicates):
            try:
                if predicate():
                    return True
            except Exception:                                        # noqa: BLE001
                continue                    # 判据自己坏了不能把物理卡死/放开，按"不冻结"处理
        return False

    def official_speed(self) -> float | None:
        """Read the current official StepControl speed, expressed as a percent."""
        for plugin in self._targets:
            if isinstance(plugin, step_control.StepControl):
                try:
                    return float(plugin.step_control.get_speed())
                except Exception:
                    return None
        return None

    def set_user_plugins(self, plugins: list) -> None:
        """★ 换掉整组**用户算法**（方案 C：点模型 → 按项目清单重新装配）。

        与 `加插件` 的分工（这条界线很重要，别混用）：
            · `加插件`    —— 外壳自己的内部插件（模型应用器 / 参数应用器 / 辨识…）。
                             它们**跨项目常驻**，不属于任何项目，换了模型也该继续在。
                             所以它们**不在本方法的清理范围内**。
            · `设用户插件` —— 项目声明的控制算法。换项目时整组换掉。

        怎么保证内部插件不被误删：`_目标` 里排在官方 StepControl 之后、但**不在**
        `_用户插件` 里的那些，就是内部插件 —— 重建时把它们原样接回去。

        ★ 换掉老算法时会顺手把它的"出错计数/停用状态"清掉（同一个插件名重新装配
          应该是一次干净的开始；旧环境的错误不该延续到新项目上）。这一点和
          P0-2（停用可恢复）想做的事是一致的，只是触发点是"换项目"。
        """
        # 内部插件 = 除了 StepControl 与旧用户插件之外的所有（保持原有相对顺序）
        old_user_ids = {id(p) for p in self._user_plugins}
        internal_plugins = [p for p in self._targets[1:] if id(p) not in old_user_ids]

        self._user_plugins = list(plugins)
        self._targets = [self._targets[0] if self._targets else step_control.StepControl(),
                      *plugins, *internal_plugins]
        self._error_counts.clear()
        self._disabled.clear()

    def plugin_snapshot(self) -> str:
        """收集所有**用户插件**的状态，拼成一行（终端实时反馈用）。"""
        lines = [f"已停用: {', '.join(sorted(self._disabled))}"] if self._disabled else []
        for plugin in self._user_plugins:
            name = self._name(plugin)
            if name in self._disabled:
                continue
            try:
                status_details = plugin.status()
            except Exception:                                 # noqa: BLE001
                continue
            lines.append(name + "(" + "、".join(f"{k}={v}" for k, v in status_details.items()) + ")")
        return " | ".join(lines)

    @staticmethod
    def _name(plugin) -> str:
        # 允许实例自带名字，否则用类名
        return str(
            getattr(plugin, "name", None) or type(plugin).__name__
        )

    def process_message(self, message) -> None:
        """带隔离地派发一条消息。

        为什么不用官方的「一锅端」派发：官方 dispatch 里没有 try/except，
        任何一个插件抛异常都会中断整条链（后面的插件和内置逻辑全部收不到消息）。
        所以这里改成**逐个插件单独调用**，谁崩了只影响谁。

        ★ 顺序很关键：官方 StepControl 排在列表最前，所以它先推进物理，
          你的控制律再基于"这一步之后"的状态算力矩 —— 写进去的 ctrl 下一步生效，
          这正是标准控制回路的时序（和第 1 步教程里 while 循环的写法等价）。
        """
        # ★ 世界冻结闸门（契约例外 ③）：冻结时不派发步进事件。
        #   为什么拦的是"派发"而不是"推进物理"：真正推进物理的是官方的 `StepControl` 插件，
        #   它也是靠收 StepEvent 才去 `advance()`。所以让这条事件到不了它手上，
        #   物理就一步都不走 —— 比"改暂停状态"稳得多（不依赖任何外部消息）。
        #   注意只拦 `StepEvent`：其它消息（快照/命令/参数）照常派发，
        #   否则界面会失去响应。
        if self._freeze_predicates and isinstance(message, _STEP_EVENT_TYPE) and self.is_frozen():
            return
        for plugin in self._targets:
            name = self._name(plugin)
            if name in self._disabled:
                continue
            self._dispatch_one(plugin, message)

    def _dispatch_one(self, plugin, message) -> None:
        """只把消息交给这一个插件；它崩了就隔离它。"""
        from official_api import plugin_registry     # 走适配层
        for info, handler in plugin_registry._discover_handlers(plugin):  # noqa: SLF001
            # 按 MRO 匹配：消息类型是标注类型的子类也算命中（官方同款规则）
            if not issubclass(type(message), info.message_type):
                continue
            try:
                handler(message)
            except Exception as exc:                        # noqa: BLE001
                self._handle_exception(exc, message, plugin)

    def _handle_exception(self, exc, message, plugin) -> None:
        name = self._name(plugin)
        self._error_counts[name] = self._error_counts.get(name, 0) + 1
        if self._error_counts[name] == 1:
            print(f"⚠ 插件【{name}】出错（已隔离，软件继续运行）：{type(exc).__name__}: {exc}")
            # 只打印"出错在插件的哪一行"，不打印官方库内部的长堆栈（那会淹没重点）
            tb = exc.__traceback__
            locations = []
            while tb is not None:
                frame = tb.tb_frame
                filename = frame.f_code.co_filename
                path = filename.replace("\\", "/")
                # 跳过官方库（mujoco/experimental/…）和本兼容层自己的帧，只留"你的插件文件"
                if filename.endswith(".py") and "mujoco/experimental" not in path\
                        and not path.endswith(("/plugin_system.py", "/插件系统.py")):
                    locations.append(f"{os.path.basename(filename)} 第 {tb.tb_lineno} 行（{frame.f_code.co_name}）")
                tb = tb.tb_next
            if locations:
                print("  出错位置：" + " → ".join(locations[-3:]))
            print(f"  → 先跳过它继续跑；再错一次就停用它。改好代码后重启即可。")
        else:
            print(f"✗ 插件【{name}】再次出错 → 已停用。其他插件和界面不受影响。")
            self._disabled.add(name)

    # -- 给外面看的状态 --
    @property
    def failed_plugins(self) -> dict[str, int]:
        return dict(self._error_counts)

    @property
    def disabled_plugins(self) -> set[str]:
        return set(self._disabled)


# ---------------------------------------------------------------------------
# ④ 版本自检 + API 指纹（官方没有，这是我们要补的第二个功能）
# ---------------------------------------------------------------------------
def check_version() -> dict:
    """打印并返回环境指纹。官方升级导致 API 变化时，这张表能第一时间看出来。"""
    import platform

    fingerprint = {
        "mujoco": getattr(mujoco, "__version__", "未知"),
        "python": platform.python_version(),
        "executable": sys.executable,
        "viewer_config_fields": tuple(f.name for f in __import__("dataclasses").fields(viewer_protocol.ViewerConfig)),
        "gfx_mode_count": len(getattr(viewer_protocol, "GFX_MODES", ())),
        "message_type_count": len([n for n in dir(messages) if isinstance(getattr(messages, n), type)
                                   and issubclass(getattr(messages, n), messages.Message)]),
    }

    print("─" * 78)
    print("【环境自检】")
    print(f"  mujoco 版本 : {fingerprint['mujoco']}   （实测跑通过的版本：{', '.join(KNOWN_GOOD_VERSIONS)}）")
    print(f"  Python      : {fingerprint['python']}  @ {fingerprint['executable']}")
    print(f"  官方 API    : ViewerConfig{fingerprint['viewer_config_fields']}、"
          f"gfx {fingerprint['gfx_mode_count']} 种、消息 {fingerprint['message_type_count']} 类")

    if fingerprint["mujoco"] not in KNOWN_GOOD_VERSIONS:
        print(f"  ⚠ 当前 mujoco {fingerprint['mujoco']} 不在「实测跑通」名单里 —— "
              f"如果出现奇怪的报错，多半是官方 API 变了。请对照本文件开头的导入清单检查。")
    else:
        print("  ✓ 版本与实测一致")
    print("─" * 78)
    return fingerprint


# ---------------------------------------------------------------------------
# ⑤ 插件清单
# ---------------------------------------------------------------------------
def print_plugin_list(plugins: list, project_name: str = "") -> None:
    """打印"这一组装了哪些算法"。

    ★ 方案 C 之后加算法**不再改代码**：把 .py 放进 `算法库/`，在项目的 `算法`
      字段里写上它（写 `"*"` 就是用全部）。所以这里的提示语跟着改了 ——
      以前写的是"新建 plugins/xx.py，再在 主程序.py 顶部加一个名字"。
    """
    header = f"（项目：{project_name}）" if project_name else ""
    print(f"【已加载 {len(plugins)} 个算法】{header}"
          f"（加算法：把 .py 放进 controllers/common/，在项目文件的 algorithms 字段里写上它；"
          f"参见 --列项目）")
    for i, plugin in enumerate(plugins, 1):
        name = str(getattr(plugin, "name", type(plugin).__name__))
        version = str(getattr(plugin, "version", "-"))
        author = str(getattr(plugin, "author", "") or "")
        description = str(getattr(plugin, "description", "") or "")
        print(f"  {i}. 【{name}】 v{version}" + (f"  —— {author}" if author else ""))
        if description:
            print(f"     {description}")
        try:
            extra = plugin.status()
        except Exception:                                     # noqa: BLE001
            extra = {}
        if extra:
            print("     " + "、".join(f"{k}={v}" for k, v in extra.items()))
    print()


def notify_model_loaded(plugins: list, model, data, algorithm_info: list | None = None,
                        project_name: str = "") -> None:
    """模型准备好 / 换了模型之后，告诉每个插件一声。

    插件要缓存 model/data 时用 `event.model` / `event.data`。

    ★ `算法信息` 是**方案 C 之后新增的参数**（可选，默认 None）：
      一段"这次装的是哪些算法、各自参数多少"的描述，由外壳用
      `收集算法信息()` 现算出来。事件对象上带 `算法信息` 属性，插件直接取用：

          def receive_model(self, event):
              self.algorithm_info = getattr(event, "algorithm_info", [])

      为什么由外壳算、而不是让插件去问注册表：注册表里混着内部插件
      （模型应用器/参数应用器/StepControl），"哪些是用户算法"这本账只有外壳清楚。
      数据录制插件原来就是因为没有这条信息，写出来的元信息里算法清单一直是空的。

    ★ `project_name` 同样挂在事件上：元信息里记下"这次属于哪个项目"，
      配合项目文件里的模型/参数，一条录制数据才真正可追溯。
    """
    info = list(algorithm_info or [])
    # 事件对象用 type(...) 现场造：官方没有"模型加载"事件类型（StepEvent 是每步的），
    # 这里只要一个能挂属性的轻量载体，不值得为它往 messages 里加一个新类型。
    event = type("ModelLifecycleEvent", (), {
        "model": model,
        "data": data,
        "algorithm_info": info,
        "plugins": plugins,
        "project_name": str(project_name or ""),
    })()
    for plugin in plugins:
        callback = getattr(plugin, "receive_model", None)
        if callback is None:
            continue
        try:
            callback(event)
        except Exception as exc:                                  # noqa: BLE001
            plugin_name = getattr(plugin, "name", None) or plugin
            print(f"⚠ 插件【{plugin_name}】处理模型时出错：{exc}")


def collect_algorithm_info(plugins: list) -> list[dict]:
    """把"这一组装了哪些算法、各自参数现在是多少"整理成可 JSON 序列化的描述。

    这是**可复现性**的关键一环：录制元信息、项目快照都靠它回答
    "当时跑的是哪个控制律、参数多少"。以前这份信息没人收集，
    所以录制出来的 `.meta.json` 里 `插件清单` 永远是空数组。

    返回形如：
        [{"name": "关节 PD 位置控制", "version": "1.1",
          "english_name": "Joint PD position control",
          "takes_control": True, "parameters": {"KP": 200.0, "KD": 30.0}}, …]

    只收"插件自己声明过的可调参数"（`adjustable_parameters()` 的键），不 dump 整个 `__dict__` ——
    那里有 model/data 引用、numpy 数组、文件句柄，序列化不了也没意义。
    """
    result: list[dict] = []
    for plugin in plugins:
        name = str(getattr(plugin, "name", None) or type(plugin).__name__)
        entry = {
            "name": name,
            "version": str(getattr(plugin, "version", "-")),
            "english_name": str(getattr(plugin, "english_name", "") or ""),
            # ★ `takes_control` 必须一起带上：外壳要靠它判断"几个算法在抢同一个方向盘"
            #   （多个都写 ctrl[:] 时只有最后一个生效，被覆盖的等于没挂）。
            #   漏带这个键的后果实测过：会被当成"全都接管"，于是默认项目也误报冲突。
            "takes_control": bool(getattr(plugin, "takes_control", True)),
            "parameters": {},
        }
        get_parameters = getattr(plugin, "adjustable_parameters", None)
        if get_parameters is not None:
            try:
                for parameter_name, info in (get_parameters() or {}).items():
                    try:
                        entry["parameters"][str(parameter_name)] = float(info.get("value"))
                    except (TypeError, ValueError, AttributeError):
                        continue          # 不是数字的参数不进元信息（元信息要能 JSON 化）
            except Exception as exc:                                  # noqa: BLE001
                print(f"⚠ 收集【{name}】的参数时出错（元信息里该算法的参数为空）：{exc}")
        result.append(entry)
    return result


WIRE_ALGORITHM_KEYS = {
    "name": "名称", "version": "版本", "english_name": "英文名",
    "takes_control": "接管控制", "parameters": "参数",
}


def algorithm_info_wire(info: list[dict]) -> list[dict]:
    """Encode English algorithm metadata for the frozen v21 wire payload."""
    return [{WIRE_ALGORITHM_KEYS[key]: item[key] for key in WIRE_ALGORITHM_KEYS if key in item}
            for item in (info or [])]


# ---------------------------------------------------------------------------
# ⑥ 给控制算法用的小工具
# ---------------------------------------------------------------------------
def slider_target(ux_state, default):
    """读取官方"控制"面板里的滑杆值（就是 GUI 里能拖的那 6 个目标）。

    有了它，你的控制律不用改代码就能在界面里实时调目标 —— 这就是"参数面板"的雏形。
    官方没提供（或者面板被关掉）时，返回 默认 值。
    """
    try:
        if ux_state is not None and getattr(ux_state, "ctrl_target", None) is not None:
            return ux_state.ctrl_target
    except Exception:                                         # noqa: BLE001
        pass
    return default


def print_plugin_status(plugins: list, interval_seconds: float = 5.0) -> None:
    """（可选）定期在终端打印插件的运行状态。想要就在主程序里用。"""
    import time
    last_print = time.time()
    while True:
        time.sleep(0.5)
        if time.time() - last_print < interval_seconds:
            continue
        last_print = time.time()
        lines = []
        for plugin in plugins:
            try:
                lines.append(f"{getattr(plugin, 'name', '?')}: " +
                          "、".join(f"{k}={v}" for k, v in plugin.status().items()))
            except Exception:                                 # noqa: BLE001
                continue
        if lines:
            print("  [状态] " + " | ".join(lines), flush=True)


__all__ = [
    "mujoco", "messages", "viewer_protocol", "ControlPlugin", "step_handler",
    "Priority", "FixedStep", "RealtimeFixedStep", "SafeRegistry", "get_registry",
    "check_version", "print_plugin_list", "notify_model_loaded",
    "collect_algorithm_info", "algorithm_info_wire", "slider_target", "print_plugin_status",
]
