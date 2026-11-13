"""
plugin_assembler.py —— 按项目把算法文件变成插件实例

它解决什么问题
----------------------------------------------------------------------------
`project_registry.py` 负责"读声明"，本文件负责"把声明变成活的对象"。
中间隔着三件必须小心的事：

① 模块名冲突（踩过就知道有多难受）
   `主程序.py` 把 `plugins/` 插进 `sys.path`，用的是平铺 `import`。
   一旦算法库里有子目录（比如 `算法库/实验/关节pd控制.py` 与 `算法库/通用/关节pd控制.py`），
   两个文件同名 → 第二次 `import` 直接命中 `sys.modules` 里的旧模块，**你改的代码不生效**。
   而且 `sys.modules` 不会因为路径变了自动失效。
   → 本文件的解法：**用文件路径算出唯一模块名**再 import，并且在 import 之前
     清掉这个唯一名上一次留下的模块对象。等价于给每个算法文件一个独占命名空间。

② 类名不写死
   项目文件里 `类` 字段可以省（推荐省）。省了就在这里按
   "MRO 是 ControlPlugin 子类"推断：
   只有一个候选就用它；有多个才要求显式写 `类` —— 报错信息直接告诉你该写什么。

③ 一个算法坏了不能拖垮整台软件
   某个算法 import 失败 / 类名写错 → 跳过它，把原因打出来，其余算法照常装配。

用法
----------------------------------------------------------------------------
    import plugin_assembler
    实例表, 报告 = plugin_assembler.assemble_project(项目数据)
    for 行 in 报告: print(行)                      # 给人看的装配结果
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys

# 让本模块无论在哪个目录被导入，都能 import 到同目录的插件与项目模块
# （和 面板/*.py 里的写法一致：外壳、面板、工具脚本三条入口都能用）
_SOFTWARE_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if _SOFTWARE_DIRECTORY not in sys.path:
    sys.path.insert(0, _SOFTWARE_DIRECTORY)

import plugin_system as plugin                                                # noqa: E402
import project_registry as _projects                                            # noqa: E402

# 同一个文件被反复装配时，模块名保持一致（便于排查），但每次都会重建模块对象
_MODULE_PREFIX = "小软件算法"


def _unique_module_name(file_path: str) -> str:
    """给一个算法文件算一个**不会和别的文件撞车**的模块名。

    用相对**包根**的路径（去掉 .py、把分隔符换成点）拼出来，例如：
        算法库/通用/关节pd控制.py  →  驭臂算法.算法库.通用.关节pd控制
    这样两个不同目录下的同名文件天然不冲突。

    ★ 包根从 `项目.包根` 取，不在这里自己数 `dirname` 的层数 ——
      算法文件可能在 `算法库/通用/`、也可能在 `算法库/子目录/`，
      层数不一样，自己数必然错一次（这个坑踩过：多退一层导致模块名为空、
      `发现的算法()` 静默返回空表）。
    """
    absolute_path = os.path.abspath(file_path)
    relative_path = os.path.relpath(absolute_path, _projects.PACKAGE_ROOT)
    if relative_path.startswith(".."):                        # 文件在包根之外 → 用绝对路径兜底
        relative_path = absolute_path.lstrip(os.sep)
    stem = os.path.splitext(relative_path)[0].replace(os.sep, ".").replace("/", ".")
    return f"{_MODULE_PREFIX}.{stem}"


def _clear_cached_module(module_name: str) -> None:
    """卸载这个模块名（含它下面的子模块）—— 保证 import 拿到的是**磁盘上的新代码**。

    ★ 为什么必须做：算法是"改文件 → 重启软件"的开发方式，很容易撞上
      "改了代码但跑的还是旧的"。清掉 sys.modules 是唯一可靠的办法。
    """
    for key in [k for k in sys.modules if k == module_name or k.startswith(module_name + ".")]:
        sys.modules.pop(key, None)


def import_algorithm_file(file_path: str):
    """按路径导入一个算法文件，返回 (模块, "")；失败返回 (None, 原因)。

    ★ 导入之前会保证两个目录在 `sys.path` 上（算法文件要 import 它们）：
        · `软件/`      —— `插件系统`、`参数辨识`、`辨识桥` 等外壳侧模块
        · `算法库/`    —— 算法之间可能的互相 import
      为什么由这里统一保证：算法文件从 `软件/plugins/` 搬到 `算法库/通用/` 之后，
      原来"`主程序.py` 已经把 `plugins/` 加进 sys.path"这个**隐含前提**就不成立了
      （迁移时实测撞上：`参数辨识插件` 的 `from 辨识桥 import …` 直接 ImportError）。
      把它写在这里，算法文件就只需要 `import plugin_system`，不必自己操心路径。
    """
    file_path = os.path.abspath(file_path)
    if not os.path.isfile(file_path):
        return None, f"文件不存在：{file_path}"

    for directory in (_SOFTWARE_DIRECTORY, _projects.ALGORITHM_DIRECTORY):
        if os.path.isdir(directory) and directory not in sys.path:
            sys.path.insert(0, directory)

    module_name = _unique_module_name(file_path)
    _clear_cached_module(module_name)
    try:
        # ① 优先用 importlib 的"按路径加载"：不依赖 sys.path，也就不会被同名文件抢
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            return None, f"无法为 {os.path.basename(file_path)} 建立加载器"
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module            # 先登记：算法里的 dataclass / 自引用才找得到自己
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)     # 加载失败不要留下半个模块
            raise
        return module, ""
    except Exception as exc:                                          # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def _is_preferred_plugin_class(obj) -> bool:
    """继承 `ControlPlugin` 的类（首选，新算法建议这么写）。"""
    return (isinstance(obj, type) and issubclass(obj, plugin.ControlPlugin)
            and obj is not plugin.ControlPlugin)


def _is_duck_plugin_class(obj) -> bool:
    """没有继承 `ControlPlugin`、但具备插件契约的类（兼容已有算法）。

    ★ 为什么需要这一条：本项目的插件**并不都继承基类**，实测 5 个算法里只有 3 个继承
      （`关节PD控制` / `正弦摆动` / `末端两点运动`），另外 2 个
      （`数据录制` / `参数辨识`）是随官方插件约定写的"鸭子类型"类。
      如果这里只认继承，那两个算法就会被装配器判为"不是插件"而静默丢掉。
      这是一种**已有事实**，不是设计目标 —— 新写的算法仍然建议继承 `ControlPlugin`
      （基类给了 adjustable_parameters/set_parameter/receive_model 的默认实现）。

    判定条件（两条都要）：类属性有 `name`，且至少有一个消息处理方法
    （`@step_handler` / `@messages.handler` 会留下属性 `_studio_handler_info`）。

    ★ 属性名取自官方常量 `messages._HANDLER_INFO_ATTR`，不写死字符串 ——
      官方哪天改了属性名，这里跟着变，不会静默失效（和 `骨架/官方接口清单.py` 一个思路）。
    """
    if not isinstance(obj, type) or obj is plugin.ControlPlugin:
        return False
    if not getattr(obj, "name", None):
        return False
    handler_marker = getattr(plugin.messages, "_HANDLER_INFO_ATTR", "_studio_handler_info")
    for attribute_name in dir(obj):
        if attribute_name.startswith("__"):
            continue
        attribute = getattr(obj, attribute_name, None)
        if callable(attribute) and hasattr(attribute, handler_marker):
            return True
    return False


def _is_plugin_class(obj) -> bool:
    return _is_preferred_plugin_class(obj) or _is_duck_plugin_class(obj)


def find_plugin_class(module, requested_name: str = "") -> tuple[type | None, str]:
    """在模块里找要实例化的插件类。返回 (类, 原因)；找不到时类为 None。

    规则（顺序就是优先级）：
        ① 项目文件里写了 `类` → 就用它（写错则报错，不猜）
        ② 模块里有 `plugin_class = XxxPlugin` → 用它（显式约定）
        ③ 模块里只有一个插件类 → 用它（最常见，所以项目文件可以省 `类`）
        ④ 有多个 → 报错并列出候选，让人在项目文件的 `类` 字段里选一个

    "是插件类"的判定见 `_是插件类`：继承 `ControlPlugin` 的优先，
    没继承但满足契约（有 `name` + 有消息处理方法）的也算。
    """
    if requested_name:
        candidate = getattr(module, requested_name, None)
        if candidate is None:
            return None, f"模块里没有「{requested_name}」这个名字"
        if not _is_plugin_class(candidate):
            return None, f"「{requested_name}」不像一个控制插件（缺 `name` 或没有任何消息处理方法）"
        return candidate, ""

    explicit_class = getattr(module, "plugin_class", None)
    if explicit_class is not None:
        if _is_plugin_class(explicit_class):
            return explicit_class, ""
        return None, "模块里的 `plugin_class` 不像一个控制插件"

    # 继承基类的优先；一个都没有才退到鸭子类型
    candidates = [v for v in vars(module).values() if _is_preferred_plugin_class(v)]\
        or [v for v in vars(module).values() if _is_duck_plugin_class(v)]
    # 按定义顺序去重（同一个类可能被 import 成两个名字）
    unique_classes: list[type] = []
    for cls in candidates:
        if cls not in unique_classes:
            unique_classes.append(cls)
    if len(unique_classes) == 1:
        return unique_classes[0], ""
    if not unique_classes:
        return None, "模块里没有控制插件（要么继承 `ControlPlugin`，要么有 `name` + 一个消息处理方法）"
    return None, ("模块里有多个控制插件：" + "、".join(c.__name__ for c in unique_classes)
                  + " —— 请在项目文件的 算法 条目里加 \"类\": \"其中一个的名字\"")


def read_metadata(cls) -> dict:
    """从插件类上取元信息（面板/清单/录制元信息都要用，所以统一在这里取一次）。"""
    return {
        "名称": str(getattr(cls, "name", None) or cls.__name__),
        "版本": str(getattr(cls, "version", "-")),
        "英文名": str(getattr(cls, "english_name", "") or ""),
        "说明": str(getattr(cls, "description", "") or ""),
        "作者": str(getattr(cls, "author", "") or ""),
    }


def check_compatibility(instances: list, model) -> tuple[list, list[dict]]:
    """对每个算法问一次"这个模型你能跑吗"。返回 (能跑的, 被跳过的说明表)。

    `模型` 为 None（`--检查` / `--列项目` 这种没有模型的场景）时全部放行 ——
    预检是为了少踩坑，没有模型就不该拦任何东西。

    被跳过的每一项形如：`{"名称": "末端两点运动（任务空间 PD）", "原因": "需要 6 轴手臂"}`
    """
    if model is None:
        return list(instances), []
    compatible: list = []
    skipped: list[dict] = []
    for plugin in instances:
        checker = getattr(plugin, "check_model_compatibility", None)
        if checker is None:
            compatible.append(plugin)
            continue
        name = str(getattr(plugin, "name", type(plugin).__name__))
        try:
            reason = str(checker(model) or "")
        except Exception as exc:                                          # noqa: BLE001
            # ★ 预检自己出错**不能**判成不兼容：那会把一个本来能跑的算法挡在外面。
            #   按"放行 + 提示"处理（宁可跑起来报错，也不要静默少一个算法）。
            print(f"ℹ 算法【{name}】的 模型兼容性() 出错（按兼容处理）："
                  f"{type(exc).__name__}: {exc}")
            compatible.append(plugin)
            continue
        (skipped if reason else compatible).append({"名称": name, "原因": reason} if reason else plugin)
    return compatible, skipped


def create_plugin(entry: dict | str) -> tuple[object | None, dict, str]:
    """按注册名创建一个插件实例，供项目装配与 ``ControllerRegistry`` 共用。

    返回 ``(实例, 元信息, 错误说明)``。这里是唯一真正执行“路径 → 模块 → 类 →
    实例”的地方；注册表和项目装配不再各写一份动态导入逻辑。
    """
    if isinstance(entry, str):
        entry = {"插件": entry}
    module_name = _projects.normalize_algorithm_name((entry or {}).get("插件") or "")
    entry = dict(entry or {})
    entry["插件"] = module_name
    file_path = (entry or {}).get("文件") or _projects.algorithm_file(entry)
    if not module_name:
        return None, {}, "没有给插件注册名"
    if not file_path:
        return None, {}, "算法库里找不到这个文件（已跳过）"

    module, reason = import_algorithm_file(file_path)
    if module is None:
        return None, {}, f"导入失败 —— {reason}"

    cls, reason = find_plugin_class(module, str((entry or {}).get("类") or ""))
    if cls is None:
        return None, {}, reason

    metadata = read_metadata(cls)
    metadata.update({"插件": module_name, "文件": os.path.abspath(file_path), "类": cls.__name__})
    try:
        return cls(), metadata, ""
    except Exception as exc:                                      # noqa: BLE001
        return None, metadata, f"实例化失败 —— {type(exc).__name__}: {exc}"


def assemble_project(project_data: dict | None, project_name: str = "",
              model=None, algorithm_override: list | None = None) -> tuple[list, list[str]]:
    """★ 核心入口：项目数据 → (插件实例列表, 给人看的报告行列表)。

    `项目数据` 为 None / 空 → 返回空算法集（等于"只开窗口，不挂算法" = `--无插件`）。
    任何单个算法的失败都只影响它自己：报告里会出现一行 `✗`，其余算法正常装配。

    `模型` 传进来时（外壳换模型/启动时都会传）会多做一次**兼容性预检**：
    跟当前模型不匹配的算法**不启用**，报告里出现一行 `–` 并说明原因。
    于是"界面上挂着的算法"和"真正在跑的算法"永远一致
    —— 见 `plugin_system.ControlPlugin.check_model_compatibility` 的说明。

    `算法覆盖` 是**用户当场选的一组算法**（【Algorithms】面板按 Apply 之后走这条）。
      传了它就用它，**忽略项目文件里的 `算法` 字段** —— 但项目名、参数、外观等其余字段
      仍然照项目文件走。这是"临时试一下"与"存进项目"分开的关键：
      临时试不落盘，界面按 Save 才写回项目文件。
    """
    instances: list = []
    report: list[str] = []
    if algorithm_override is not None:
        # 用户指定的顺序就是执行顺序，**不能**在这里重排（最后一项说了算，见 项目.py）
        entries = [{"插件": _projects.normalize_algorithm_name(str(x))}
                 for x in algorithm_override if str(x).strip()]
        discovered = {d["插件"]: d for d in _projects.discover_algorithms()}
        for item in entries:
            if item["插件"] in discovered:
                item["文件"] = discovered[item["插件"]]["文件"]
        report.append(f"（算法由界面指定：{len(entries)} 个，顺序即执行顺序）")
    else:
        entries = _projects.parse_algorithms(project_data)
    used_plugin_names: set[str] = set()

    if not entries:
        report.append("（这个项目没有声明任何算法）" if project_data else "（没有项目 → 不挂算法）")
        return instances, report

    for entry in entries:
        module_name = entry.get("插件", "")
        instance, metadata, reason = create_plugin(entry)
        if instance is None:
            report.append(f"✗ {module_name}：{reason}")
            continue
        if metadata["名称"] in used_plugin_names:
            # 参数面板/消息按"插件名"寻址，重名会让它们串台 —— 直接拒绝，别留隐患
            report.append(f"✗ {module_name}：插件名「{metadata['名称']}」和前面某个算法重名（已跳过）")
            continue

        used_plugin_names.add(metadata["名称"])
        instances.append(instance)
        report.append(f"✓ {metadata['名称']} v{metadata['版本']}"
                    + (f"  —— {metadata['作者']}" if metadata["作者"] else "")
                    + (f"  [{os.path.basename(metadata['文件'])}]" if metadata["说明"] else ""))

    # ---- 兼容性预检：跟当前模型对不上的算法**不启用**（见 检查兼容性 的说明）----
    if model is not None:
        instances, skipped = check_compatibility(instances, model)
        for skipped_item in skipped:
            report.append(f"– {skipped_item['名称']}：与当前模型不兼容，本次不启用 —— {skipped_item['原因']}")
        if skipped:
            report.append(f"（{len(skipped)} 个算法因模型不兼容被跳过；要改就编辑项目文件里的算法列表）")

    # ---- 发送钩子契约自检：项目里引用的算法有没有实现必需的钩子 ----
    if instances:
        report.extend(_check_handlers(instances))

    # ---- ★ 抢方向盘检查：多个算法都写 ctrl[:] 时，只有最后一个真正生效 ----
    report.extend(_check_control_conflicts(instances))

    if project_name:
        report.append(f"（项目「{project_name}」共装配 {len(instances)} 个算法）")
    return instances, report


# 必需钩子：算法不实现也不报错（有默认行为），但**不该什么都没有**。
# 检查的是"能不能干活"这件最基本的事，不是风格问题。
_REQUIRED_HOOKS = ("step",)


def _check_control_conflicts(instances: list) -> list[str]:
    """报告"哪些算法在抢同一个方向盘"——因为只有**最后一个**真正生效。

    ★ 这是踩出来的真实困扰（用户报的："为什么 UR5e 的末端两点运动效果是这样"）：
      `末端两点运动`（任务空间）和 `关节pd控制` 都会写 `event.data.ctrl[:]`，
      而派发是**逐个插件依次调用**、后写的整体覆盖先写的。
      于是无论怎么努力，**只有排在最后的那个算法在驱动机器人**，
      前面那些算法一步都没生效 —— 但界面上照样显示"✓ 已加载"，
      用户完全看不出来，只会觉得"这个算法的效果怎么是这样"。

      实测数据（UR5e，末端要从 [0.45,0.10,0.50] 走到 [0.30,-0.20,0.35]）：
        · 只挂 末端两点运动            → 末端离终点 **0.1 mm**（正常工作）
        · 末端两点运动 + 关节pd控制(在后) → 末端离终点 **394.7 mm**（末端算法被整体盖掉）
      逐步打印同一个仿真步里的 ctrl 也证实：最终值与关节PD 的输出**完全一致**。

    所以这里把"静默被掩盖"变成**看得见的提示**：列出抢方向盘的算法、指出谁赢。
    只提示、不阻止 —— 有时候"叠两个"是用户故意的（比如想比较谁赢）。
    """
    controllers = [p for p in instances if getattr(p, "takes_control", True)]
    if len(controllers) <= 1:
        return []
    names = [str(getattr(p, "name", type(p).__name__)) for p in controllers]
    winner = names[-1]
    losers = "、".join(names[:-1])
    return [
        f"⚠ 有 {len(controllers)} 个算法都在写 ctrl[:]（都在驱动同一台机器人）：{'、'.join(names)}",
        f"   → 只有**最后一个**【{winner}】真正生效；{losers} 的输出被整体覆盖，"
        f"基本等于没挂（这是「后写的覆盖先写的」的直接后果）",
        "   → 想换谁生效：在【Algorithms】面板把它调到列表最后；"
        "只想跑一个就把另一个取消勾选。",
    ]


def _check_handlers(instances: list) -> list[str]:
    """报告里加一行提示：哪些算法一个消息处理方法都没有（挂上去也不会干活）。

    为什么不做成"直接拒绝"：有些算法确实是**纯被动**的（比如某些只提供 `指标()`
    给别的插件看的辅助件）。所以这里只提示，不拦 —— 但提示必须出现，
    否则"挂了个什么都不干的算法"会让人查半天。
    """
    handler_marker = getattr(plugin.messages, "_HANDLER_INFO_ATTR", "_studio_handler_info")
    inactive_plugins = []
    for instance in instances:                      # ★ 别用 `插件` 当循环变量：会遮住模块名 `插件`
        has_handler = any(callable(getattr(instance, name, None)) and hasattr(getattr(instance, name), handler_marker)
                     for name in dir(type(instance)) if not name.startswith("__"))
        if not has_handler:
            inactive_plugins.append(str(getattr(instance, "name", type(instance).__name__)))
    return [f"ℹ 这些算法没有任何消息处理方法（挂上也不会干活）：{'、'.join(inactive_plugins)}"] if inactive_plugins else []


# ---------------------------------------------------------------------------
# 给"没有项目"的模型一个兜底项目（第一次点一个还没建过项目的模型时用）
# ---------------------------------------------------------------------------
def project_from_model(model_path: str, algorithms: object = "*", note: str = "") -> dict:
    """按一个模型造一份新项目数据（**不落盘** —— 落盘由调用方决定）。

    默认 `算法 = "*"`：新模型的起步项目就把算法库里现有的算法都挂上，
    用户点开就能看到东西，之后再按需要往项目文件里删减。
    """
    name = _projects.display_model_name(model_path)
    data = {
        "_说明": "由外壳按模型自动生成的项目（首次点开这个模型时创建）。"
                 "算法 字段写 \"*\" = 用算法库全部；想只留几个就把它们列出来。",
        "项目": name,
        "模型": _projects.relative_to_package(model_path),
        "算法": algorithms,
        "参数": {},
    }
    if note:
        data["备注"] = note
    return data


__all__ = [
    "import_algorithm_file", "find_plugin_class", "read_metadata",
    "check_compatibility", "create_plugin", "assemble_project", "project_from_model",
]
