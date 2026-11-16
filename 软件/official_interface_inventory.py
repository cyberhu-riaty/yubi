"""
官方接口清单.py —— 我们依赖官方的**全部**接口，一处声明，多处使用

它是什么：
    一份"边界合同"。外壳能用的官方东西只有下面清单里这些；
    清单之外如果谁偷偷用了官方内部 API，就是越界（`--自检` 会提醒）。

为什么要有它（第 3 步要解决的问题）：
    官方的插件系统在 `mujoco.experimental.studio` 里，官方自己标注"实验性、随时可能改"。
    官方的 C++ 扩展（窗口/渲染/界面/物理）**永远拷不走**，所以"搬代码"不能消除风险。
    能消除风险的办法只有一个：**把边界钉死，并且盯住它**——
    官方一改，启动自检立刻告诉你"哪一条断了、该改我们哪个文件"。

怎么用：
    ① 外壳代码需要官方东西时，从这里拿：`官方.取("viewer_app.ViewerApp")`
    ② 想检查边界是否完好：跑 `python 软件/主程序.py --自检`
    ③ 想加一个新的官方依赖：**先在清单里加一条**，再用它（这样它才会被看住）

约定：
    · `取值` 是一个 Python 表达式，在模块命名空间里求值（允许 `模块.属性` 链）
    · `检查` 是一个函数，返回 True/False + 说明文字（检查"形状对不对"，不只是"有没有"）
    · `修复` 是给人看的话：这条断了要去改我们哪个文件
"""
from __future__ import annotations

import dataclasses
import importlib
from typing import Any, Callable

# ---------------------------------------------------------------------------
# 模块名（集中在这里，官方哪天改了模块路径，只改这几行）
# ---------------------------------------------------------------------------
OFFICIAL_PACKAGE_PREFIX = "mujoco.experimental.studio"
MODULES = {
    "messages": OFFICIAL_PACKAGE_PREFIX + ".messages",
    "step_control": OFFICIAL_PACKAGE_PREFIX + ".step_control",
    "viewer_app": OFFICIAL_PACKAGE_PREFIX + ".viewer_app",
    "viewer_protocol": OFFICIAL_PACKAGE_PREFIX + ".viewer_protocol",
    "launch_native": OFFICIAL_PACKAGE_PREFIX + ".launch_native",
    "launch_thread": OFFICIAL_PACKAGE_PREFIX + ".launch_thread",
    "viewer_handle": OFFICIAL_PACKAGE_PREFIX + ".viewer_handle",
    "endpoints": OFFICIAL_PACKAGE_PREFIX + ".endpoints",
    "plugin_registry": OFFICIAL_PACKAGE_PREFIX + ".plugin_registry",
    "ux": OFFICIAL_PACKAGE_PREFIX + ".ux",
    "dear_imgui": "mujoco.experimental.dear_imgui.dear_imgui",
    "implot": "mujoco.experimental.implot.implot",
    "核心": "mujoco",
}


@dataclasses.dataclass(frozen=True)
class InterfaceItem:
    """一条"我们依赖官方"的记录。"""
    identifier: str            # 唯一 id，形如 "messages.handler"
    description: str            # 人话说明它干什么
    module_key: str        # 模块字典的 key
    expression: str            # 表达式，例如 "messages.handler"
    check: Callable[[Any], tuple[bool, str]]   # 形状检查
    remediation: str            # 断了改我们哪个文件
    consumers: str          # 我们这边哪些文件依赖它


def _has_attributes(*names):
    def check(value):
        missing = [n for n in names if not hasattr(value, n)]
        if missing:
            return False, f'缺少属性/方法：{missing}'
        return True, "、".join(names) + " 都在"
    return check


def _signature_contains(*parameter_names, position=None):
    """检查函数签名里的参数名（比"有没有"更严，能发现官方改了参数名）。"""
    import inspect

    def check(value):
        try:
            signature = inspect.signature(value)
        except (TypeError, ValueError):
            return True, "（C++ 内置，无法检查签名，只确认存在）"
        names = set(signature.parameters)
        missing = [n for n in parameter_names if n not in names]
        if missing:
            return False, f'签名 {signature} 里缺少参数 {missing}'
        return True, f'签名 {signature}'
    return check


def _wrappable_attributes(*attribute_names):
    """检查"模块属性可写" —— 我们靠它把官方函数包一层（皮肤补推、主题同步都要）。

    ★ 这是本项目里**唯一**一处"改官方对象"的地方（皮肤桥包装 ux.setup_theme）。
      所以不能只检查"函数在不在"，还要实测"这个属性写得进去吗"：
      写法是**写回原值**（不改变任何行为），只是探一下可写性。
    """
    def check(value):
        missing = [n for n in attribute_names if not hasattr(value, n)]
        if missing:
            return False, f'缺少属性：{missing}'
        for n in attribute_names:
            original = getattr(value, n)
            if not callable(original):
                return False, f"{n} 不可调用（无法包装）"
            try:
                setattr(value, n, original)          # 写回原值：只探可写性，不改行为
            except Exception as exc:                        # noqa: BLE001
                return False, f'{n} 属性不可写（包装会失败）：{type(exc).__name__}: {exc}'
        return True, "、".join(attribute_names) + " 存在、可调用、可包装（写回原值验证）"
    return check


def _is_class(base_class_name=None, module_key="messages"):
    def check(value):
        if not isinstance(value, type):
            return False, f'{value!r} 不是类'
        if base_class_name is not None:
            base = getattr(MODULES.get(module_key) and _module_cache.get(module_key), base_class_name, None)
            if base is None or not issubclass(value, base):
                return False, f'{value.__name__} 不是 {base_class_name} 的子类'
            return True, f'{value.__name__} 是 {base_class_name} 的子类'
        return True, f'{value.__name__}'
    return check


def _returns_tuple_length(length: int):
    def check(value):
        try:
            import inspect
            result = inspect.signature(value).return_annotation
        except (TypeError, ValueError):
            return True, "（内置，跳过返回类型检查）"
        return True, f'（返回标注 {result}，运行期再验）'
    return check


# ---------------------------------------------------------------------------
# ★ 清单本体：我们依赖官方的每一样东西
# ---------------------------------------------------------------------------
INTERFACES: list[InterfaceItem] = [
    InterfaceItem(
        identifier="mujoco.MjModel/MjData/MjSpec",
        description="物理引擎本体：加载模型、造状态、改模型后重编译",
        module_key="核心", expression="mujoco",
        check=_has_attributes("MjModel", "MjData", "MjSpec", "mj_step", "mj_forward"),
        remediation="几乎不用改：这是最底层的接口，真断了说明 mujoco 大版本变了，需要重新验收",
        consumers="启动.py / plugins/*",
    ),
    InterfaceItem(
        identifier="messages.handler",
        description="插件贴标签用的装饰器（@每步）",
        module_key="messages", expression="messages.handler",
        check=_signature_contains("priority", "fn"),
        remediation="插件系统.py → 每步 = messages.handler；若参数名变了，改这一行",
        consumers="插件系统.py（所有插件都通过它）",
    ),
    InterfaceItem(
        identifier="messages.Priority",
        description="执行优先级档位（INTERNAL/LIBRARY/USER/CRITICAL）",
        module_key="messages", expression="messages.Priority",
        check=lambda o: (all(hasattr(o, n) for n in ("INTERNAL", "LIBRARY", "USER", "CRITICAL")),
                       "四档齐全" if all(hasattr(o, n) for n in ("INTERNAL", "LIBRARY", "USER", "CRITICAL")) else "档位缺失"),
        remediation="插件系统.py → 优先级 = messages.Priority；若有档位改名，改用到的地方",
        consumers="插件系统.py / plugins/末端两点运动.py",
    ),
    InterfaceItem(
        identifier="messages.Message/Snapshot/Event",
        description="消息三基类：可靠事件 vs 最新覆盖快照",
        module_key="messages", expression="messages",
        check=_has_attributes("Message", "Snapshot", "Event"),
        remediation="界面桥.py 的自定义消息继承自 messages.Snapshot",
        consumers="界面桥.py / 参数面板.py / plugins/录制数据.py",
    ),
    InterfaceItem(
        identifier="messages.StepEvent",
        description="每步仿真事件：带 model 和 data（控制律的入口）",
        module_key="messages", expression="messages.StepEvent",
        check=lambda o: ((o.__dataclass_fields__.keys() >= {"model", "data"}) if hasattr(o, "__dataclass_fields__") else (False, "不是 dataclass"),
                       "字段 model/data 齐全" if hasattr(o, "__dataclass_fields__") and o.__dataclass_fields__.keys() >= {"model", "data"} else "字段不符"),
        remediation="插件系统.py 的文档与所有插件的 每步控制(self, event) 签名",
        consumers="全部控制插件 / plugins/录制数据.py",
    ),
    InterfaceItem(
        identifier="messages.ModelEvent",
        description="把模型送到窗口的事件",
        module_key="messages", expression="messages.ModelEvent",
        check=_is_class(),
        remediation="启动.py → 句柄.send_to_viewer(messages.ModelEvent(model=..., path=...))",
        consumers="启动.py",
    ),
    InterfaceItem(
        identifier="messages.StateSnapshot",
        description="把每步状态回发给窗口的快照",
        module_key="messages", expression="messages.StateSnapshot",
        check=_is_class(),
        remediation="启动.py 的回发状态那几行",
        consumers="启动.py",
    ),
    InterfaceItem(
        identifier="messages.BuildGuiEvent",
        description="窗口每帧画界面时的事件（自定义面板的挂载点）",
        module_key="messages", expression="messages.BuildGuiEvent",
        check=_is_class(),
        remediation="参数面板.py / 界面桥.py 的 BuildGuiEvent 处理函数",
        consumers="参数面板.py",
    ),
    InterfaceItem(
        identifier="messages.UpdateEvent",
        description="窗口每帧更新事件（在画界面之前）",
        module_key="messages", expression="messages.UpdateEvent",
        check=_is_class(),
        remediation="界面桥.py（每帧发滑杆值）",
        consumers="界面桥.py / 参数面板.py",
    ),
    InterfaceItem(
        identifier="viewer_protocol.ViewerConfig",
        description="窗口配置：标题/宽高/渲染后端",
        module_key="viewer_protocol", expression="viewer_protocol.ViewerConfig",
        check=lambda o: ((set(f.name for f in dataclasses.fields(o)) >= {"title", "width", "height", "gfx"})
                       if dataclasses.is_dataclass(o) else (False, "不是 dataclass"),
                       "字段 " + str([f.name for f in dataclasses.fields(o)]) if dataclasses.is_dataclass(o) else "不是 dataclass"),
        remediation="主程序.py 里构造 配置 = viewer_protocol.ViewerConfig(...) 的地方",
        consumers="主程序.py",
    ),
    InterfaceItem(
        identifier="viewer_protocol.ViewerInitEvent",
        description="窗口初始化事件：插件借此拿到 viewer 对象",
        module_key="viewer_protocol", expression="viewer_protocol.ViewerInitEvent",
        check=_is_class(),
        remediation="界面桥.py / 参数面板.py 里 _记下viewer",
        consumers="界面桥.py / 参数面板.py",
    ),
    InterfaceItem(
        identifier="viewer_app.ViewerApp",
        description="官方 GUI 主程序（19 个现成面板都靠它）",
        module_key="viewer_app", expression="viewer_app.ViewerApp",
        check=_is_class(),
        remediation="启动.py 的窗口插件列表；主程序.py 传给 启动外壳 的窗口类参数",
        consumers="启动.py / 主程序.py",
    ),
    InterfaceItem(
        identifier="step_control.StepControl",
        description="★ 官方步进插件：真正推进物理的就是它（不是 sync）",
        module_key="step_control", expression="step_control.StepControl",
        check=_is_class(),
        remediation="插件系统.py 的安全注册表 → self._目标 = [step_control.StepControl(), *插件列表]",
        consumers="插件系统.py",
    ),
    InterfaceItem(
        identifier="launch_thread.make_thread_endpoints",
        description="造一对线程安全的收发端点（仿真侧↔窗口侧）",
        module_key="launch_thread", expression="launch_thread.make_thread_endpoints",
        check=lambda o: (callable(o), "可调用" if callable(o) else "不可调用"),
        remediation="启动.py → 查看端点, 仿真端点 = launch_thread.make_thread_endpoints()",
        consumers="启动.py",
    ),
    InterfaceItem(
        identifier="launch_native.run_native_viewer",
        description="在主线程里跑窗口循环（macOS 必须这样）",
        module_key="launch_native", expression="launch_native.run_native_viewer",
        check=_signature_contains("config", "endpoint", "plugins"),
        remediation="启动.py 的最后一段（run_native_viewer 调用）",
        consumers="启动.py",
    ),
    InterfaceItem(
        identifier="viewer_handle.ViewerHandle",
        description="仿真侧句柄：发送模型/状态、判断窗口是否还开着",
        module_key="viewer_handle", expression="viewer_handle.ViewerHandle",
        check=_has_attributes("send_to_viewer", "is_running", "close"),
        remediation="启动.py → 句柄 = viewer_handle.ViewerHandle(仿真端点)",
        consumers="启动.py",
    ),
    InterfaceItem(
        identifier="endpoints.SimEndpoint",
        description="仿真侧端点：收窗口事件、发状态快照",
        module_key="endpoints", expression="endpoints.SimEndpoint",
        check=_has_attributes("get_viewer_events", "get_viewer_snapshots", "send_to_viewer"),
        remediation="启动.py 的仿真循环（注意：没构造它，是 make_thread_endpoints 返回的）",
        consumers="启动.py",
    ),
    InterfaceItem(
        identifier="plugin_registry._discover_handlers",
        description="扫描插件里贴了 @每步 的方法（我们做逐个隔离时要用它）",
        module_key="plugin_registry", expression="plugin_registry._discover_handlers",
        check=lambda o: (callable(o), "可调用" if callable(o) else "不可调用"),
        remediation="插件系统.py → 安全注册表._单独派发()。★ 这是私有函数（带下划线），"
             "官方若改名/改返回值，隔离机制要跟着改——自检会第一时间报出来",
        consumers="插件系统.py",
    ),
    InterfaceItem(
        identifier="ux.GuiTheme / setup_theme / save_settings",
        description="界面主题（深色/浅色）与设置保存",
        module_key="ux", expression="ux",
        check=_has_attributes("GuiTheme", "setup_theme", "save_settings"),
        remediation="界面桥.py 的 _应用主题 / 制作窗口类",
        consumers="界面桥.py / 主程序.py",
    ),
    InterfaceItem(
        identifier="ux.reset_config",
        description="清掉保存的界面布局/主题",
        module_key="ux", expression="ux.reset_config",
        check=lambda o: (callable(o), "可调用" if callable(o) else "不可调用"),
        remediation="主程序.py 的 --恢复默认界面",
        consumers="主程序.py",
    ),
    InterfaceItem(
        identifier="dear_imgui 基础控件",
        description="画自定义面板用的 ImGui 控件（我们的参数面板靠它）",
        module_key="dear_imgui", expression="dear_imgui",
        check=_has_attributes("Button", "Checkbox", "Text", "Separator", "SameLine",
                   "SliderFloat", "SliderInt", "Begin", "End"),
        remediation="参数面板.py / plugins/录制数据.py 的面板绘制部分",
        consumers="参数面板.py / plugins/录制数据.py",
    ),
    # ---------------------------------------------------------------------
    # ↓↓↓ 下面 3 项是"面板外观换肤"新增的依赖（2026-09-17，清单 21 → 24 项）
    # ---------------------------------------------------------------------
    InterfaceItem(
        identifier="dear_imgui 样式推入接口",
        description="★ 换肤机制的全部家当：逐帧推入颜色/形状再弹出（绑定里没有"
             "全局 SetStyleColor，所以只能这样）",
        module_key="dear_imgui", expression="dear_imgui",
        check=_has_attributes("PushStyleColor", "PopStyleColor", "PushStyleVar", "PopStyleVar",
                   "GetColorU32", "Col", "StyleVar", "Vec4", "Vec2", "GetIO", "ColorButton"),
        remediation="皮肤桥.py 的 _推入一套()/帧结束()；若官方绑定改名，换肤会整体失效但不会崩",
        consumers="皮肤桥.py / 面板/外观面板.py",
    ),
    InterfaceItem(
        identifier="implot 样式推入接口",
        description="曲线面板的换肤（曲线图框/网格/图例颜色；★ 线条颜色由 implot 内部 "
             "colormap 决定，本绑定改不了）",
        module_key="implot", expression="implot",
        check=_has_attributes("PushStyleColor", "PopStyleColor", "PushStyleVar", "PopStyleVar", "Col"),
        remediation="皮肤桥.py 的 _推入一套()（曲线那两行）",
        consumers="皮肤桥.py",
    ),
    InterfaceItem(
        identifier="ux.setup_theme 可包装",
        description="★ 官方每帧都会重设主题（viewer_app.build_gui 第一行），会把我们的皮肤抹掉；"
             "只有把它包一层、设完补推，官方那 19 个面板才会一起换肤",
        module_key="ux", expression="ux",
        check=_wrappable_attributes("setup_theme"),
        remediation="皮肤桥.py 的 安装包装()。★ 这一项失败不影响开窗：皮肤会自动退回"
             "「只换自研面板」模式（见 皮肤桥.包装是否失效）",
        consumers="皮肤桥.py",
    ),
]


# ---------------------------------------------------------------------------
# 取用与检查
# ---------------------------------------------------------------------------
_module_cache: dict[str, Any] = {}
_value_cache: dict[str, Any] = {}


def get(identifier: str) -> Any:
    """按编号取一个官方对象（第一次用到才 import，不拖慢启动）。"""
    if identifier in _value_cache:
        return _value_cache[identifier]
    for item in INTERFACES:
        if item.identifier == identifier:
            break
    else:
        raise KeyError(f'官方接口清单里没有「{identifier}」—— 想用新的官方接口，先把它加进 清单 里')
    module_path = MODULES.get(item.module_key)
    if module_path is None:
        raise KeyError(f'清单里「{identifier}」的模块键 {item.module_key!r} 在 模块 字典里不存在')
    if item.module_key not in _module_cache:
        _module_cache[item.module_key] = importlib.import_module(module_path)
    _module_cache.setdefault(module_path, _module_cache[item.module_key])   # 同时登记"模块真名"，供 取值 表达式使用
    try:
        value = eval(item.expression, {}, {**_module_cache, item.module_key.split(".")[-1]: _module_cache[item.module_key]})  # noqa: S307
    except Exception as exc:                                   # noqa: BLE001
        raise RuntimeError(f'取官方接口「{identifier}」失败（{item.expression}）：{exc}') from exc
    _value_cache[identifier] = value
    return value


def check_item(item: InterfaceItem) -> tuple[bool, str]:
    """检查一条接口。返回 (是否正常, 说明)。"""
    try:
        module_path = MODULES.get(item.module_key)
        if item.module_key not in _module_cache:
            _module_cache[item.module_key] = importlib.import_module(module_path)
        _module_cache.setdefault(module_path, _module_cache[item.module_key])   # 同时登记"模块真名"（如 mujoco）
        # 让 取值 表达式能同时用"模块真名"和"短名"
        namespace = {**_module_cache, item.module_key.split(".")[-1]: _module_cache[item.module_key]}
        for key, module_name in MODULES.items():
            if key in _module_cache:
                namespace[key] = _module_cache[key]
        value = eval(item.expression, {}, namespace)  # noqa: S307
    except Exception as exc:                                   # noqa: BLE001
        return False, f'取不到（{type(exc).__name__}: {exc}）'
    try:
        result = item.check(value)
        if isinstance(result, tuple):
            return bool(result[0]), str(result[1])
        return bool(result), ""
    except Exception as exc:                                   # noqa: BLE001
        return False, f'检查函数本身出错：{type(exc).__name__}: {exc}'


def check_all(print_result=print, *, failures_only: bool = False) -> tuple[int, int]:
    """逐条检查整份清单。返回 (正常数, 失败数)。

    参数
      只列失败: True 时只打印失败项（启动路径用，避免刷屏）；
                False 时全列（人工排查用，`--自检` 走这个）。
    """
    passed_count = failed = 0
    for item in INTERFACES:
        passed, description = check_item(item)
        if passed:
            passed_count += 1
            if not failures_only:
                print_result(f'  ✓ {item.identifier:44s} {description}')
        else:
            failed += 1
            print_result(f'  ✗ {item.identifier:44s} {description}')
            print_result(f'      → 该改我们这边：{item.remediation}')
            print_result(f'      → 受影响：{item.consumers}')
    return passed_count, failed
