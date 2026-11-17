"""
model_bridge.py —— 模型库、模型切换与项目状态的界面↔仿真通道

它解决什么问题：
    需求是"启动先给空白界面，然后在界面里选/切换机械臂"。
    官方底座其实已经把"换模型"做成了一等公民能力（发一条 `ModelEvent` 就会
    重建 model/data、重置节拍、重置界面状态），但**我们自己的外壳绕过了官方的
    `ViewerHandle.sync()`**（为了做出错隔离），所以那条路只走了一半：
    窗口侧的画面换了，仿真侧的物理还在旧模型上跑。

    这个模块把"换模型"收敛到**一个地方**，两条入口都经过它：
      ① 界面【模型库】面板发来的 `换模型命令`
      ② 窗口侧发来的 `messages.ModelEvent`（官方内建的"把文件拖进窗口"）
    真正的加载与"重绑 model/data + 通知插件"由外壳注入的回调完成（见 runtime_engine.py）。

另外它会记录"上次用的模型"：
    `输出/设置.json` 里存 `上次模型`，用于保留操作记录和空场景缺失时兜底；
    普通启动仍固定进入空场景，不会自动恢复机械臂。
    启动外壳会在每次切换成功后记录。

用法（界面侧）：
    from model_bridge import (
        SwitchModelCommand, ModelState, read_model_library,
        select_local_model_file,
    )
    self.viewer.send_to_sim(SwitchModelCommand(path=…, display_name=…))
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from typing import Any, Callable

from official_api import messages

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
_software_directory = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(_software_directory)
MODEL_DIRECTORY = os.path.join(PACKAGE_ROOT, "模型")
LIBRARY_INDEX_PATH = os.path.join(MODEL_DIRECTORY, "模型库.json")
SETTINGS_PATH = os.path.join(PACKAGE_ROOT, "输出", "设置.json")
EMPTY_SCENE_PATH = os.path.join(MODEL_DIRECTORY, "空场景.xml")


# ---------------------------------------------------------------------------
# 模型库（界面侧与仿真侧都能直接读，不需要走消息）
# ---------------------------------------------------------------------------
def read_model_library(arms_only: bool = True) -> list[dict]:
    """读 `模型/模型库.json`，返回可选的模型条目。

    只取机械臂时过滤掉夹爪 / 不可控制的模型 —— 界面上列出来点一下就报错的条目没有意义。

    `类别 == "arm_task"` 是例外：它表示"能加载、但不是关节力矩接口"的任务模型
    （例如 MJPC 的 Panda：6 维末端力控 + 夹爪，nu != nq）。
    这类模型不能挂 `关节pd控制`，但可以给 MPC/自定义插件用，所以仍然上架。
    """
    try:
        with open(LIBRARY_INDEX_PATH, encoding="utf-8") as f:
            index_data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as exc:                                       # noqa: BLE001
        print(f"⚠ 模型库索引读取失败：{type(exc).__name__}: {exc}")
        return []
    entries = index_data.get("models", index_data.get("模型", []))
    if arms_only:
        entries = [m for m in entries if (
            (_model_field(m, "category", "类别") == "arm" and _model_field(m, "controllable", "可控制"))
            or _model_field(m, "category", "类别") == "arm_task"
        )]
    return entries


def _model_field(entry: dict, english: str, legacy: str, default=None):
    """Model-library field with a legacy Chinese-key fallback."""
    return entry[english] if english in entry else entry.get(legacy, default)


def arm_joint_count(model) -> int:
    """Count arm hinge/slide joints without gripper or free-joint coordinates."""
    try:
        import mujoco
        count = 0
        for index in range(int(getattr(model, "njnt", 0))):
            if int(model.jnt_type[index]) not in (
                int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE)
            ):
                continue
            body = mujoco.mj_id2name(
                model, mujoco.mjtObj.mjOBJ_BODY, int(model.jnt_bodyid[index])) or ""
            if "finger" not in body.lower() and "thumb" not in body.lower():
                count += 1
        return count
    except Exception:
        return int(getattr(model, "nq", 0))


def absolute_path(package_relative_path: str) -> str:
    """把模型路径规范成绝对路径。

    三种输入都要能吃下：
      · 已经是绝对路径            → 原样返回
      · 相对包根（模型库索引里的写法，如 `universal_robots_ur5e/ur5e_torque.xml`）
      · 相对当前工作目录（用户手输的 `模型/xxx.xml`）
    判断办法：先看这个路径本身存不存在，存在就认它。
    """
    path = str(package_relative_path or "")
    if not path:
        return ""
    for candidate in (path, os.path.join(PACKAGE_ROOT, path)):
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
    return os.path.normpath(os.path.join(MODEL_DIRECTORY, path))


def display_name(path: str) -> str:
    """给一个模型路径起个人看的名字（能在模型库里查到就用库里的显示名）。"""
    absolute = absolute_path(path)
    if absolute and os.path.normpath(absolute) == os.path.normpath(EMPTY_SCENE_PATH):
        return "空场景（无机械臂）"
    for m in read_model_library(arms_only=False):
        if os.path.normpath(absolute_path(_model_field(m, "torque_model", "扭矩模型", ""))) == os.path.normpath(absolute):
            return str(_model_field(m, "display_name", "显示名")
                       or _model_field(m, "identifier", "标识") or os.path.basename(path))
    return os.path.basename(path)


# ---------------------------------------------------------------------------
# 记住上次用的模型（启动默认②）
# ---------------------------------------------------------------------------
def _read_settings() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:                                        # noqa: BLE001
        print(f"⚠ 设置读取失败（按默认处理）：{type(exc).__name__}: {exc}")
        return {}


def _write_settings(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as exc:                                        # noqa: BLE001
        print(f"⚠ 设置保存失败（不影响使用）：{type(exc).__name__}: {exc}")


def read_setting(key: str, default=None):
    """读一个设置项（`输出/设置.json`）。"""
    return _read_settings().get(key, default)


def write_setting(key: str, value) -> None:
    """写一个设置项。"""
    data = _read_settings()
    if data.get(key) == value:
        return
    data[key] = value
    _write_settings(data)


def read_last_model() -> str:
    """返回上次成功加载的模型路径；没有 / 文件已不在 → 返回空串。"""
    path = str(_read_settings().get("上次模型") or "")
    if path and os.path.exists(path):
        return path
    return ""


def remember_model(path: str) -> None:
    """记住这次用的模型。空场景也记（等价于"上次我就是要空着"）。"""
    data = _read_settings()
    if data.get("上次模型") == path:
        return
    data["上次模型"] = path
    _write_settings(data)
    print(f"【模型】已记录最近选择：{display_name(path)}（普通启动仍进入空场景）", flush=True)


# ---------------------------------------------------------------------------
# 界面 → 仿真侧：换模型命令
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class SwitchModelCommand(messages.Snapshot):
    """面板发来的"换到这个模型"。

    ★ Snapshot 语义（只保留最新一条）正合适：用户连点几个模型时，
      旧的那些还没处理就已经过期了，最新的才是要的。
    """

    path: str = ""
    display_name: str = ""


# ---------------------------------------------------------------------------
# 仿真侧 → 界面：当前模型状态
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class ModelState(messages.Snapshot):
    current_path: str = ""
    current_display_name: str = ""
    dof: int = 0
    actuator_count: int = 0
    status: str = "就绪"          # 就绪 / ✓ … / ✗ …
    duration_s: float = 0.0


# ---------------------------------------------------------------------------
# 仿真侧 → 界面：**可选模型清单**（资产库）
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class AssetLibrary(messages.Snapshot):
    """可选模型清单（资产库视图的数据源）。

    ★ 为什么不复用 `模型状态`：那是"**当前**装的是哪台"（2 Hz 覆盖），
      这是"**能选**哪些"（几秒才变一次）。两者生命周期完全不同 ——
      清单在启动时发一次就够，而当前状态会随换模型变。

    ★ 字段里**不带绝对路径**：`目录` 是相对包根的（如 `模型/kuka_iiwa_14`），
      界面要的是"能不能点"，不是"文件在哪"。真要路径时用 `模型文件`。
    """
    count: int = 0
    # 每项：{标识, 显示名, 类别, 自由度, 执行器数, 许可, 可控制, 路径}
    #   `路径` 是**可直接加载**的那个文件（= 清单里的「扭矩模型」绝对路径），
    #   界面点一下就把它放进 `命令.换模型`。别改成「模型文件」——
    #   那是这个资产包里所有 xml 的列表，不是"该加载哪个"。
    models: tuple = ()


def asset_manifest(arms_only: bool = True) -> dict:
    """给发布器用：把 `读取模型库()` 的结果整成一条消息负载。

    ★ 转成**普通 dict / list**：numpy 类型和自定义对象过不了 JSON，
      而这条消息最终要经 Web 桥发出去（见 `Web桥._浅转`）。
    """
    library = read_model_library(arms_only=arms_only)
    output = []
    for m in library:
        # ★ 用「扭矩模型」而不是「模型文件」：前者是"该加载的那一个"，
        #   后者是这个资产包里的全部 xml（含 mjx_* 变体），拿它去加载会挑错。
        relative = str(_model_field(m, "torque_model", "扭矩模型", "") or "")
        absolute = absolute_path(relative) if relative else ""
        if not absolute:
            continue                       # 没有可加载文件的条目不上架（点了也白点）
        output.append({
            "id": str(_model_field(m, "identifier", "标识", "")),
            "display_name": str(_model_field(m, "display_name", "显示名", "")),
            "category": str(_model_field(m, "category", "类别", "")),
            "dof": int(_model_field(m, "dof", "自由度", 0) or 0),
            "actuator_count": int(_model_field(m, "actuator_count", "执行器数", 0) or 0),
            "license": str(_model_field(m, "license", "许可", "")),
            "controllable": bool(_model_field(m, "controllable", "可控制", False)),
            "path": absolute,
        })
    return {"count": len(output), "models": output}


# ---------------------------------------------------------------------------
# 仿真侧：唯一负责"把模型换掉"的插件
# ---------------------------------------------------------------------------
class ModelApplier:
    """仿真侧插件。它自己**不加载模型** —— 加载与重绑由外壳注入的 `换模型回调` 做。

    这样安排的原因：重绑 model/data 必须动 `ViewerHandle` 和外壳的局部变量，
    那些东西只有 `runtime_engine.py` 拿得到。这个插件只负责把消息翻译成回调调用。
    """

    name = "模型应用器"
    version = "1.0"

    def __init__(self, switch_model: Callable[..., tuple[bool, str]]):
        self._switch_model = switch_model
        self.status = "就绪"
        self.current_path = ""
        self.current_display_name = ""
        self.dof = 0
        self.actuator_count = 0
        self.duration_s = 0.0
        self._first_window_event = True

    # ---- 入口 ①：我们自己的面板 ----
    @messages.handler
    def on_command(self, command: SwitchModelCommand) -> bool:
        path = str(getattr(command, "path", "") or "")
        if not path or os.path.normpath(path) == os.path.normpath(self.current_path):
            return False
        self._first_window_event = False
        success, description = self._switch_model(path=path, notify_window=True)
        self._record_result(path, success, description)
        return False

    # ---- 入口 ②：官方内建的"把文件拖进窗口" ----
    #   窗口侧已经把文件解析成 MjModel 了（event.model），直接采用它的对象，
    #   不重复解析；也不需要再回发 ModelEvent（窗口自己已经有了）。
    #   ★ 启动时窗口也会发一条同样的 ModelEvent（同步它加载好的模型），
    #     不能一律写"（拖拽）"—— 这曾让"命令行加载"看起来像用户拖进来的。
    @messages.handler
    def on_model_event(self, event: messages.ModelEvent) -> bool:
        model = getattr(event, "model", None)
        path = str(getattr(event, "path", "") or "")
        if model is None:
            return False
        same_path = bool(path) and bool(self.current_path) and (
            os.path.normpath(path) == os.path.normpath(self.current_path))
        if self._first_window_event:
            source = "启动同步"
            self._first_window_event = False
        elif same_path:
            source = "窗口同步"
        else:
            source = "拖拽"
        success, description = self._switch_model(model=model, path=path, notify_window=False)
        self._record_result(path, success, f"（{source}）{description}")
        return False

    def _record_result(self, path: str, success: bool, description: str) -> None:
        self.status = ("✓ " if success else "✗ ") + description
        if success:
            self.current_path = path
            self.current_display_name = display_name(path) if path else "（未知来源）"
        print(f"【模型】{self.status}", flush=True)

    # ---- 给发布器用 ----
    def snapshot(self) -> ModelState:
        return ModelState(current_path=self.current_path, current_display_name=self.current_display_name,
                        dof=self.dof, actuator_count=self.actuator_count,
                        status=self.status, duration_s=self.duration_s)


class ModelPublisher:
    """周期性把当前模型状态发给界面（默认 2 Hz —— 只在切换时才会变，不用更密）。"""

    def __init__(self, send: Callable[[Any], None], frequency: float = 2.0):
        self._send = send
        self._interval = 1.0 / max(frequency, 1e-6)
        self._next_publish = 0.0
        self.published_count = 0

    def maybe_publish(self, applier, wall_time: float) -> bool:
        if wall_time < self._next_publish:
            return False
        self._next_publish = wall_time + self._interval
        if applier is None:
            return False
        try:
            self._send(applier.snapshot())
            self.published_count += 1
            return True
        except Exception as exc:                                     # noqa: BLE001
            if self.published_count == 0:
                print(f"⚠ 模型状态发布失败（不影响控制）：{type(exc).__name__}: {exc}")
            return False


class AssetLibraryPublisher:
    """把"可选模型清单"发给界面。

    ★ 它**不需要节流、也不需要比对内容**：清单只在启动时装一次（几秒才可能变一次），
      和 `模型状态`（2 Hz）那种随状态变化的东西不是一类。
      所以这里只有一个 `发布()`，由外壳在装配完成后主动调一次。
      真要在运行期刷新（比如从本地导入新模型），再调一次 `发布()` 即可。
    """

    def __init__(self, send: Callable[[Any], None]):
        self._send = send
        self.published_count = 0
        self.last_count = 0

    def publish(self) -> bool:
        try:
            payload = asset_manifest(arms_only=True)
            self._send(AssetLibrary(
                count=payload["count"], models=tuple(payload["models"])))
            self.published_count += 1
            self.last_count = payload["count"]
            return True
        except Exception as exc:                                         # noqa: BLE001
            print(f"⚠ 资产库发布失败（不影响控制）：{type(exc).__name__}: {exc}")
            return False


# ---------------------------------------------------------------------------
# 仿真侧 → 界面：当前**项目**状态（方案 C：点模型 → 界面更新算法列表）
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class ProjectState(messages.Snapshot):
    """当前项目 + 这一组装了哪些算法。

    ★ 为什么和 `模型状态` 分成两条消息（而不是合并成一条）：
      `模型状态` 变的是**物理对象**（哪台机械臂、多少轴、切换耗时）；
      `项目状态` 变的是**工作环境**（哪个项目、挂了哪些算法、参数多少）。
      两者的更新时机不同（换算法不一定换模型），关心它们的界面也不同
      （【Model library】关心前者，【Controller params】关心后者）。
      合成一条会让"只想知道算法列表"的面板每 2 Hz 收一堆无关字段。

    `algorithms` 保持 v21 线上形状（中文键，前端适配层负责转英文）：
        [{"名称": …, "版本": …, "英文名": …, "接管控制": …, "参数": {...}}, …]
    内部元信息由 `plugin_system.collect_algorithm_info()` 以英文字段产生，
    发布前经 `plugin_system.algorithm_info_wire()` 编码。
    """

    project: str = ""
    model_path: str = ""
    model_display_name: str = ""
    algorithms: list = dataclasses.field(default_factory=list)
    report: list = dataclasses.field(default_factory=list)   # 装配结果（✓/✗ 各一行）
    algorithm_library: list = dataclasses.field(default_factory=list)  # 算法库里**全部**可选算法（给界面做选择器）
    saved: bool = False        # 这一组是否与项目文件一致（False = 是界面上临时 Apply 的）
    # ---- 抢方向盘提示（多个算法都写 ctrl[:] 时，只有最后一个真正生效）----
    #   `控盘`   = 真正在驱动机器人的那个算法的**显示名**（没有则为空串）
    #   `被覆盖` = 输出被整体盖掉、基本等于没挂的那些算法（显示名列表）
    #   ★ 为什么要在状态里带上：用户看不到终端，而"挂了的算法其实没生效"必须让他看见，
    #     否则只会觉得"这个算法的效果怎么是这样"。检测逻辑见 装配器._抢方向盘体检()。
    active_controller: str = ""
    overridden_controllers: list = dataclasses.field(default_factory=list)
    # 兼容字段：只表示是否使用模型重力，不代表仿真是否运行。
    gravity_enabled: bool = True


# ---------------------------------------------------------------------------
# 界面 → 仿真侧：换一组算法（【Algorithms】面板的 Apply / Save）
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class ApplyAlgorithmsCommand(messages.Snapshot):
    """把用户在界面上勾出来的一组算法交给仿真侧去装配。

    ★ 为什么必须走消息、不能在界面里直接改：
      装配要换掉**正在被仿真的那批插件实例**（`registry.set_user_plugins()` + 参数应用器重绑 +
      通知各插件）。这些对象归仿真线程所有，界面线程去碰就是跨线程改状态。
      所以界面只负责"说想要哪几个"，装配由仿真线程做。

    `算法` = 插件名（模块名）的**有序**列表；顺序就是每步的执行顺序，
    **最后一项最后写 `ctrl[:]`，它说了算**（见 项目.py 的说明）。
    `落盘=True` 表示同时把这组选择写回项目文件（对应【Save】按钮）。
    Snapshot 语义（只保留最新一条）正合适：连点 Apply 时旧的那些本来也已过期。
    """

    algorithms: list = dataclasses.field(default_factory=list)
    persist: bool = False
    reset_pose: bool = True
    #   ★ 为什么要有这个开关（这是实测出来的真实困扰）：
    #     换算法时**物理状态（qpos/qvel）默认是不动的**，而多数控制算法的设计是
    #     "拿第一次看到的位置当基准"（例如 关节pd控制 的 `目标`、正弦摆动 的 `基准`）。
    #     于是新算法会在**上一个算法留下的姿态**上开始控制 —— 表现就是
    #     "机器人回不到默认位置了"。
    #     实测数据：默认姿态误差 0 → 正弦摆动跑 400 步后偏离 0.33 rad →
    #     切到关节 PD 时它把这个姿态当了基准（目标 = 离开姿态 + 抬臂偏移）。
    #     所以默认 True：每次 Apply/Save 都把机器人摆回默认姿态再让新算法接手。
    #     想看"接着上一个算法的姿态继续"就把这个勾去掉（研究切换过程时会要）。


class AlgorithmSelector:
    """仿真侧插件：收 `应用算法命令` → 调外壳注入的回调重新装配。

    它自己**不装配** —— 真正的装配在外壳的 `_装配项目()` 里（那里才拿得到
    句柄、注册表、参数应用器）。本插件只把消息翻译成一次回调调用，
    和 `模型应用器` 完全同一个套路。
    """

    name = "算法选择器"          # 有名字 → 会出现在算法清单/状态里，便于排查
    version = "1.0"

    def __init__(self, switch_algorithms: Callable[..., tuple[bool, str]]):
        self._switch = switch_algorithms
        self.applied_count = 0
        self.latest = ""

    @messages.handler
    def on_command(self, command: ApplyAlgorithmsCommand) -> bool:
        # ★ 契约里 `算法` 是 **object[]**（每项 `{插件: "名字"}`），不是字符串数组。
        #   原来这里写 `[str(x) for x in ...]`，把整条 dict 变成了字符串
        #   `"{'插件': '关节pd控制'}"` —— 于是装配器按这个名字找不到插件，
        #   报"已装配 0 个算法；1 个失败"。
        #
        #   为什么这个 bug 能活很久：官方 ImGui 的算法面板是**在自己进程里直接调回调**的
        #   （根本不走这条消息），所以那条路一直"看起来正常"；
        #   而 Web 界面走的是消息 → 这里是唯一入口 → 一碰就露。
        #   教训：`str(x)` 这种"兜底转换"会把**形状错误**藏成**内容错误**，排查时最难找。
        algorithms: list[str] = []
        for x in (getattr(command, "algorithms", None) or []):
            if isinstance(x, dict):
                name = str(x.get("plugin") or "").strip()
            else:
                name = str(x).strip()
            if name:
                algorithms.append(name)
        persist = bool(getattr(command, "persist", False))
        reset_pose = bool(getattr(command, "reset_pose", True))
        success, description = self._switch(algorithms, persist, reset_pose)
        self.latest = ("✓ " if success else "✗ ") + description
        if success:
            self.applied_count += 1
        print(f"【算法】{self.latest}", flush=True)
        return False


class ProjectStatePublisher:
    """把当前项目状态发给界面。

    ★ 只在信息**真的变了**的时候才发（内容比对）。
      理由有两个：
        ① `Snapshot` 语义是"只保留最新一条"，每 2 Hz 重发一模一样的内容纯浪费；
        ② 更关键的是"点模型 → 界面**立刻**更新算法列表"这条体验要求
           —— 必须在装配完成的那一刻主动发，而不是等下一个 2 秒的节拍。
      所以主路径是装配完调一次 `发布()`；`也许发布()` 只作兜底
      （界面万一漏收了，最迟 0.5 秒后还能对上）。
    """

    def __init__(self, send: Callable[[Any], None], frequency: float = 2.0):
        self._send = send
        self._interval = 1.0 / max(frequency, 1e-6)
        self._next_publish = 0.0
        self._last_content: tuple | None = None
        self.published_count = 0

    @staticmethod
    def _fingerprint(status: ProjectState) -> tuple:
        """把状态压成一个可比较的元组（用来判断"变没变"）。

        参数值也进指纹：拖滑杆改了参数，界面上的算法列表那一行也该跟着变。
        """
        return (
            str(status.project),
            str(status.model_path),
            str(status.model_display_name),
            bool(status.saved),
            str(status.active_controller),
            tuple(str(x) for x in (status.overridden_controllers or [])),
            bool(status.gravity_enabled),
            # 可选算法库：**必须进指纹** —— 否则往算法库里加/删一个 .py 之后，
            # 【Algorithms】面板上的候选列表不会刷新（内容没变就不发，见类文档）。
            tuple(sorted(str(x) for x in (status.algorithm_library or []))),
            tuple((str(a.get("名称")), str(a.get("版本")),
                   tuple(sorted((str(k), float(v)) for k, v in (a.get("参数") or {}).items())))
                  for a in (status.algorithms or []) if isinstance(a, dict)),
        )

    def publish(self, status: ProjectState, force: bool = False) -> bool:
        """发一条项目状态。内容没变就跳过（除非 `force=True`）。"""
        fingerprint = self._fingerprint(status)
        if not force and fingerprint == self._last_content:
            return False
        try:
            self._send(status)
        except Exception as exc:                                         # noqa: BLE001
            if self.published_count == 0:
                print(f"⚠ 项目状态发布失败（不影响控制）：{type(exc).__name__}: {exc}")
            return False
        self._last_content = fingerprint
        self.published_count += 1
        return True

    def maybe_publish(self, status: ProjectState, wall_time: float) -> bool:
        """按节拍兜底重发（内容没变就什么都不做，见类文档）。"""
        if wall_time < self._next_publish:
            return False
        self._next_publish = wall_time + self._interval
        return self.publish(status)


# ---------------------------------------------------------------------------
# 界面侧：调 macOS 原生文件选择器
# ---------------------------------------------------------------------------
def select_local_model_file(initial_directory: str = "") -> str:
    """弹 macOS 原生"打开文件"对话框，返回选中的路径（取消返回空串）。

    ★ 为什么不用官方接口：mujoco 的 Python 层**没有**暴露任何文件选择器
      （File 菜单只有 Quit，也没有 tinyfd 绑定）。而本项目已有用 osascript
      弹中文对话框的先例（见启动器脚本），所以这里沿用同一条路 —— 零新依赖。

    ★ 注意：这个函数是**阻塞**的（对话框关掉才返回）。在窗口线程里直接调用
      会把整个界面冻住（3D 视图不刷新，看起来像卡死），所以界面请用下面的
      `后台选择器` 包一层。
    """
    directory = initial_directory or MODEL_DIRECTORY
    script = (
        'try\n'
        f'  set f to choose file with prompt "选择 MuJoCo 模型（.xml / .mjb / .mjz）" '
        f'default location POSIX file "{directory}" of type {{"xml", "mjb", "mjz"}}\n'
        '  return POSIX path of f\n'
        'on error number -128\n'
        '  return ""\n'
        'end try\n'
    )
    try:
        result = subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=600)
    except Exception as exc:                                        # noqa: BLE001
        print(f"⚠ 打开文件对话框失败：{type(exc).__name__}: {exc}")
        return ""
    if result.returncode != 0:
        error = (result.stderr or "").strip()
        if error:
            print(f"⚠ 文件选择器返回错误：{error[:200]}")
        return ""
    return (result.stdout or "").strip()


class BackgroundSelector:
    """把阻塞的文件对话框丢到后台线程，界面就不会被冻住。

    用法：
        选择器.开始(起始目录)      # 点按钮时
        if 选择器.进行中: …        # 界面上显示"选择中…"
        路径 = 选择器.取()         # 每帧调一次；没选完返回 None，选完返回路径（只返回一次）
    """

    def __init__(self):
        import threading
        self._threading = threading
        self._thread = None
        self._result: str | None = None
        self.pending = False

    def start(self, initial_directory: str = "") -> None:
        if self.pending:
            return
        self.pending = True
        self._result = None
        self._thread = self._threading.Thread(target=self._run, args=(initial_directory,), daemon=True)
        self._thread.start()

    def _run(self, initial_directory: str) -> None:
        try:
            self._result = select_local_model_file(initial_directory)
        except Exception as exc:                                     # noqa: BLE001
            print(f"⚠ 文件选择器线程出错：{type(exc).__name__}: {exc}")
            self._result = ""
        finally:
            self.pending = False

    def poll(self) -> str | None:
        """每帧调一次。有结果就返回并清空（只返回一次）；否则 None。"""
        if self.pending or self._result is None:
            return None
        result = self._result
        self._result = None
        return result


__all__ = [
    "PACKAGE_ROOT", "MODEL_DIRECTORY", "EMPTY_SCENE_PATH", "read_model_library",
    "absolute_path", "display_name", "read_setting", "write_setting",
    "read_last_model", "remember_model", "asset_manifest", "select_local_model_file",
    "SwitchModelCommand", "ModelState", "AssetLibrary", "ModelApplier",
    "ModelPublisher", "AssetLibraryPublisher", "ProjectState",
    "ApplyAlgorithmsCommand", "AlgorithmSelector", "ProjectStatePublisher",
    "BackgroundSelector",
]
