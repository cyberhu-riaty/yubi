"""
project_registry.py —— 模型、算法列表与参数项目的唯一数据源

它解决什么问题（方案 C）
----------------------------------------------------------------------------
在这之前，"用哪些控制算法"这件事写在 `主程序.py` 的【插件清单】里：
一份硬编码的 Python 列表，加一个算法要改代码、注释一大段、重启软件。
于是有三个后果：
    ① 换模型不会换算法 —— 点 UR5e 和点 xArm7，界面上挂的是同一套算法；
    ② 同一个算法想用在两台模型上，只能"两份代码"或者"全局都挂上"；
    ③ 「当时跑的是哪个算法、参数多少」没有任何地方记录（录制元信息里的插件清单是空的）。

现在改成**声明式装配**：

    模型（物理对象）  ──┐
    算法（写一次）    ──┼──►  项目文件（一份 JSON）  ──►  外壳按它 new 出插件实例
    参数（旋钮）      ──┘       项目/xxx.json

一个"项目" = (模型 × 算法列表 × 参数) 的一次命名快照。三者解耦的好处：
    · 同一个算法用在两台模型上 → 写两个项目文件，算法只有一份；
    · 同一个模型跑两组参数     → 写两个项目文件；
    · 同一个模型换一组算法     → 还是项目文件。
所以**项目不是模型的附庸，模型只是项目里的一个字段**（`模型`）。

为什么不做成"一个模型一个目录"（那种方案的代价）
----------------------------------------------------------------------------
把算法按模型分目录，看着直观，但会在三处卡住：
    ① 同一个模型上对比 PD / 计算力矩 / 自适应 → 算法该放哪个"模型的目录"？
    ② 在 UR5e 上调好的算法想拿到 xArm7 上验证 → 复制一份还是共享？
    ③ 同一模型跑两组参数做消融 → 又得复制。
本模块的目录布局是"线性的"（`算法库/` 下平铺），而**项目文件里的算法是一个列表**，
所以上面三件事都只是"多写一个项目文件 / 多写一行"，不需要复制代码。

文件长什么样
----------------------------------------------------------------------------
`项目/UR5e_基础PD.json`：

    {
      "_说明": "给人看的说明（可选）",
      "项目": "UR5e_基础PD",
      "模型": "模型/universal_robots_ur5e/ur5e_torque.xml",
      "算法": [
        {"插件": "joint_pd_control", "类": "JointPDController"},
        {"插件": "data_recorder",    "类": "DataRecorderPlugin"}
      ],
      或者 "算法": "*"  = 用算法库里的全部算法（探索阶段省事，加新算法不用改项目文件）
      "参数": {"关节 PD 位置控制": {"KP": 320.0, "KD": 42.0}},
      "外观": {"风格": "现代深色", "主题": "dark"},
      "备注": "论文第三章的基线"
    }

字段的三种写法（`模型` 与 `算法[].插件` 通用）
    · 绝对路径                 "/Users/…/ur5e_torque.xml"
    · 相对包根（**推荐**）      "模型/universal_robots_ur5e/ur5e_torque.xml"
    · 只写文件名               "ur5e_torque.xml"      —— 按 `模型库.json` 反查
`算法[].类` 可以省：省了就用该模块里唯一的 `ControlPlugin` 子类；有多个才必须写。

怎么找项目
----------------------------------------------------------------------------
点模型时按"**项目里的 `模型` 字段指到这个模型**"反查，全部扫一遍 `项目/*.json`。
匹配用的是**规范化后的绝对路径**，所以同一个模型写 `模型/x/y.xml` 或绝对路径都认得。
一个模型可以对应多个项目（同一模型两组参数）；这时取文件名排序第一个，
并把"还有哪几个"打进终端 —— 界面上的完整选择器是后续的事，先把链路跑通。

用法
----------------------------------------------------------------------------
    import project_registry
    data = project_registry.load_project("UR5e_基础PD")
    name = project_registry.find_project_by_model(model_path)
    project_registry.save_parameters(name, plugin_name, {"KP": 320.0})
"""
from __future__ import annotations

import glob
import json
import os
import sys

# ---------------------------------------------------------------------------
# 路径（相对本文件定位，跟着包走 —— 不写死任何绝对路径）
# ---------------------------------------------------------------------------
RUNTIME_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(RUNTIME_DIRECTORY)
PROJECT_DIRECTORY = os.path.join(PACKAGE_ROOT, "项目")
ALGORITHM_DIRECTORY = os.path.join(PACKAGE_ROOT, "算法库")
MODEL_DIRECTORY = os.path.join(PACKAGE_ROOT, "模型")
SETTINGS_PATH = os.path.join(PACKAGE_ROOT, "输出", "设置.json")

# 项目文件的后缀（`项目/索引.json` 这种不是项目，靠"必须有 `项目` 与 `模型` 字段"排除）
PROJECT_SUFFIX = ".json"


def _read_json(path: str) -> dict:
    """读一个 JSON 文件；失败返回 {}（并打一句人话提示，不抛异常）。

    ★ 为什么这里要临时抬高递归上限（这是个踩出来的坑）：
      `mujoco.MjModel.from_xml_path()` 是原生扩展，调用它会吃掉 Python 解释器
      **C 层的递归余量**。之后再用 `json.load` 解析中等嵌套深度的文件（本项目的
      `模型库.json` 就够深）会抛 `RecursionError: maximum recursion depth exceeded
      while decoding a JSON array` —— 而 `sys.getrecursionlimit()` 明明还是 1000，
      看起来"上限没变"，所以这个错很难理解。
      实测复现条件：**在循环里**先建 MjModel、再读模型库。
      代价很隐蔽：`_读json` 返回 {} → 模型库"看起来是空的" → 界面列表为空、
      路径反查全部退化成全盘搜索。所以这里在解析期间临时抬高上限，读完还原。
    """
    old_limit = sys.getrecursionlimit()
    try:
        if old_limit < 8000:
            sys.setrecursionlimit(8000)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:                                          # noqa: BLE001
        print(f'⚠ 读取失败 {os.path.basename(path)}：{type(exc).__name__}: {exc}')
        return {}
    finally:
        sys.setrecursionlimit(old_limit)


def _write_json(path: str, data: dict) -> bool:
    """原子写一个 JSON 文件（先写 .tmp 再 replace —— 中途崩了不会留下半个文件）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        return True
    except Exception as exc:                                          # noqa: BLE001
        print(f'⚠ 保存失败 {os.path.basename(path)}：{type(exc).__name__}: {exc}')
        return False


# ---------------------------------------------------------------------------
# 路径解析
# ---------------------------------------------------------------------------
def absolute_path(path: str) -> str:
    """把项目文件里的路径写法规范成绝对路径。

    三种输入都要能吃下（顺序就是判断顺序）：
      · 已经是绝对路径且存在        → 原样
      · 相对包根（`模型/x/y.xml`）  → 拼包根
      · 只有文件名（`y.xml`）       → 先在 `模型库.json` 里反查，再全库搜一遍
    找不到就返回"按相对包根拼出来"的结果（让调用方拿到一个能显示给人看的路径）。

    ★ 反查模型库时走的是 `_模型库里的写法()` + `_直接解析()`（纯字符串处理），
      **不能**在反查分支里递归调回本函数 —— `模型库.json` 的 `扭矩模型` 字段本身
      就是相对路径，递归会变成"绝对 → 查模型库 → 绝对 → 查模型库"的无限递归。
      实测撞上过：5 个模型的循环里抛 `RecursionError: maximum recursion depth exceeded`，
      看起来像 mujoco 的问题，其实是本函数自己绕圈。
    """
    text = str(path or "").strip()
    if not text:
        return ""
    for candidates in (text, os.path.join(PACKAGE_ROOT, text)):
        if os.path.exists(candidates):
            return os.path.abspath(candidates)

    # 只有文件名 → 查模型库（用纯字符串候选，见下面的★）
    name = os.path.basename(text)
    for original in _library_spelling(name):
        matches = _parse_direct(original)
        if matches:
            return matches

    # 再全库搜一遍（模型库里没登记的模型也能用）
    for root in (MODEL_DIRECTORY, ALGORITHM_DIRECTORY, PROJECT_DIRECTORY):
        if not os.path.isdir(root):
            continue
        for current, _directory, files in os.walk(root):
            if name in files:
                return os.path.abspath(os.path.join(current, name))
    return os.path.normpath(os.path.join(PACKAGE_ROOT, text))


def _parse_direct(spelling: str) -> str:
    """只做"绝对路径 / 相对包根"两种解析，**不反查模型库**（用来打断递归）。"""
    text = str(spelling or "").strip()
    if not text:
        return ""
    for candidates in (text, os.path.join(PACKAGE_ROOT, text)):
        if os.path.exists(candidates):
            return os.path.abspath(candidates)
    return ""


def _library_spelling(filename: str) -> list[str]:
    """在模型库索引里找出某个文件名对应的**原始写法**（只做字符串比较，不解析路径）。"""
    result: list[str] = []
    for m in model_library_entries():
        if not isinstance(m, dict):
            continue
        for key in ("扭矩模型", "位置模型", "路径", "XML"):
            candidates = str(m.get(key) or "")
            if candidates and os.path.basename(candidates.replace("\\", "/")) == filename:
                result.append(candidates)
    return result


def relative_to_package(path: str) -> str:
    """把绝对路径写回项目文件时用：能相对包根就相对，否则保留绝对。"""
    absolute = absolute_path(path)
    prefix = PACKAGE_ROOT + os.sep
    return absolute[len(prefix):] if absolute.startswith(prefix) else absolute


def model_library_entries() -> list[dict]:
    """读 `模型/模型库.json` 的条目（读不到就返回空表，调用方按"没有"处理）。"""
    data = _read_json(os.path.join(MODEL_DIRECTORY, "模型库.json"))
    entry = data.get("模型", [])
    return entry if isinstance(entry, list) else []


def display_model_name(absolute_model_path: str) -> str:
    """给一个模型路径起个给人看的名字（模型库里有就用库里的显示名）。"""
    target = os.path.normpath(absolute_path(absolute_model_path))
    for m in model_library_entries():
        for key in ("扭矩模型", "位置模型", "路径", "XML"):
            candidates = str(m.get(key) or "")
            if candidates and os.path.normpath(absolute_path(candidates)) == target:
                return str(m.get("显示名") or m.get("标识") or os.path.basename(target))
    return os.path.basename(target)


# ---------------------------------------------------------------------------
# 项目清单：扫描 / 读 / 写
# ---------------------------------------------------------------------------
def list_projects(valid_only: bool = True) -> list[str]:
    """列出所有项目名（按名字排序）。

    怎么判断"这是一个项目文件"：**必须是 dict 且有非空的 `项目` 与 `模型` 两个字段**。
    所以 `项目/索引.json`、`.DS_Store`、临时文件都会被自动跳过，不需要额外维护排除表。
    """
    result = []
    for path in sorted(glob.glob(os.path.join(PROJECT_DIRECTORY, "*" + PROJECT_SUFFIX))):
        if os.path.basename(path).startswith("_"):
            continue
        data = _read_json(path)
        if not data:
            continue
        if valid_only and not (data.get("项目") and data.get("模型")):
            continue
        result.append(str(data.get("项目") or os.path.splitext(os.path.basename(path))[0]))
    return result


def project_file_path(project_name: str) -> str:
    """项目名 → 文件路径。优先同名文件；找不到就按名字新建一个（保存时用）。"""
    candidates = os.path.join(PROJECT_DIRECTORY, str(project_name) + PROJECT_SUFFIX)
    if os.path.exists(candidates):
        return candidates
    for path in sorted(glob.glob(os.path.join(PROJECT_DIRECTORY, "*" + PROJECT_SUFFIX))):
        data = _read_json(path)
        if str(data.get("项目") or "") == str(project_name):
            return path
    return candidates


def load_project(project_name: str) -> dict | None:
    """按名字读一个项目；不存在返回 None。"""
    path = project_file_path(project_name)
    if not os.path.exists(path):
        return None
    data = _read_json(path)
    return data or None


def save_project(data: dict) -> bool:
    """整体写回一个项目（`数据["项目"]` 必须有名字）。"""
    name = str(data.get("项目") or "").strip()
    if not name:
        print("⚠ 项目没有名字，拒绝保存")
        return False
    return _write_json(project_file_path(name), data)


def find_project_for_model(model_path: str) -> str:
    """★ 核心入口：点一个模型 → 找到它对应的项目名。

    匹配规则 = **项目里的 `模型` 字段规范化后相等**。一个模型对应多个项目时，
    取名字排序第一个，并把其余几个打到终端（提示还有别的选择）。
    找不到返回空串 —— 调用方按"这个模型还没有项目"处理（用空算法集启动）。
    """
    target = os.path.normpath(absolute_path(model_path)) if model_path else ""
    if not target:
        return ""
    matches = []
    for name in list_projects():
        data = load_project(name) or {}
        # 实验专用项目只能由 ExperimentRegistry 显式选择，普通“点模型”流程不自动命中。
        # 否则同一模型有多个实验时，按字母排序随便挑一个会让机器人意外开始运动。
        if bool(data.get("实验专用", False)):
            continue
        if os.path.normpath(absolute_path(str(data.get("模型") or ""))) == target:
            matches.append(name)
    if not matches:
        return ""
    if len(matches) > 1:
        print(f"ℹ 模型「{display_model_name(model_path)}」对应 {len(matches)} 个项目：{'、'.join(matches)}"
              f' —— 本次用第一个「{matches[0]}」（切换项目：改 项目/{matches[0]}{PROJECT_SUFFIX}，'
              f"或删掉其余几个的同名 `模型` 字段）", flush=True)
    return matches[0]


# ---------------------------------------------------------------------------
# 算法解析
# ---------------------------------------------------------------------------
ALGORITHM_ALIASES = {
    "关节pd控制": "joint_pd_control",
    "关节pid控制": "joint_pid_control",
    "参数辨识插件": "parameter_identification_plugin",
    "数据录制": "data_recorder",
    "末端两点运动": "two_point_task_space",
    "正弦摆动": "sinusoidal_joint_motion",
    "轨迹目标执行": "trajectory_target_player",
    "Panda_官方MPC移植": "panda_mjpc_port",
    "Panda_抓取演示": "panda_pick_place",
}


def normalize_algorithm_name(display_name: str) -> str:
    """把历史插件文件名转换为当前稳定标识；未知名称保持原样。"""
    name = str(display_name or "").strip()
    return ALGORITHM_ALIASES.get(name, name)


def algorithm_file(entry) -> str:
    """算法条目 → 绝对文件路径。

    条目可以是两种写法：
        {"插件": "joint_pd_control", "类": "JointPDController"}
        "joint_pd_control"                                  ← 简写（类由扫描推断）
    """
    module_name = normalize_algorithm_name(
        (entry or {}).get("插件") if isinstance(entry, dict) else entry or "")
    if not module_name:
        return ""
    if os.path.isabs(module_name) and module_name.endswith(".py"):
        return module_name
    # ① 算法库里找（含子目录，所以"通用/关节pd控制"这种写法也认）
    candidates = os.path.join(ALGORITHM_DIRECTORY, module_name.replace("\\", "/"))
    for attempt in (candidates + ".py", candidates, os.path.join(RUNTIME_DIRECTORY, "plugins", module_name + ".py")):
        if os.path.isfile(attempt):
            return os.path.abspath(attempt)
    # ② 全库按文件名找（大小写与中文都按原样比）
    for root in (ALGORITHM_DIRECTORY, os.path.join(RUNTIME_DIRECTORY, "plugins")):
        if not os.path.isdir(root):
            continue
        for current, _directory, files in os.walk(root):
            for file in files:
                if file == module_name + ".py" or os.path.splitext(file)[0] == module_name:
                    return os.path.abspath(os.path.join(current, file))
    return ""


def parse_algorithms(data: dict | None) -> list[dict]:
    """项目数据 → 规范化后的算法条目列表（外壳装配插件时用）。

    三种写法都收：
        "算法": "*"                        → 算法库里的**全部**算法
        "算法": ["关节PD控制", "数据录制"]  → 这些（简写：类名由装配时按模块推断）
        "算法": [{"插件": …, "类": …}]      → 这些（显式指定类名，模块里有多个子类时必须写）
    不认识的条目只打警告、跳过 —— 一个写错的项目文件不该让整个软件起不来。
    """
    original = (data or {}).get("算法", "*")
    known = discover_algorithms()                      # 只扫一次目录（扫盘不便宜，别在循环里反复扫）
    if isinstance(original, str):
        if original.strip() in ("*", "全部", "all"):
            entry = [{"插件": d["插件"], "文件": d["文件"]} for d in known]
        elif original.strip():
            entry = [{"插件": original.strip()}]
        else:
            entry = []
    elif isinstance(original, list):
        entry = list(original)
    else:
        entry = []

    result: list[dict] = []
    recognized = {d["插件"] for d in known}
    for item in entry:
        name = normalize_algorithm_name(
            (item or {}).get("插件") if isinstance(item, dict) else item or "")
        if not name:
            continue
        if name not in recognized:
            print(f'⚠ 项目里写了算法「{name}」，但算法库里找不到这个文件（已跳过）。'
                  f"现有：{'、'.join(sorted(recognized)) or '（空）'}")
            continue
        normalized = {"插件": name}
        if isinstance(item, dict):
            if item.get("类"):
                normalized["类"] = str(item["类"])
            if item.get("文件"):
                normalized["文件"] = str(item["文件"])
        result.append(normalized)
    return result


def discover_algorithms() -> list[dict]:
    """扫一遍算法库，返回"有哪些算法、各自在哪个文件、类名是什么"。

    这一步**只读文件、不 import**（import 有副作用，不能在扫描阶段做）：
    类名靠"条目里写了就用条目的，没写就等装配时按模块里的子类推断"。
    界面上的"可选算法清单"、`工具/` 下的检查脚本都用它。
    """
    result: list[dict] = []
    roots = [ALGORITHM_DIRECTORY, os.path.join(RUNTIME_DIRECTORY, "plugins")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for current, directories, files in os.walk(root):
            directories[:] = [d for d in directories if not d.startswith(("_", ".")) and d != "__pycache__"]
            for file in sorted(files):
                if not file.endswith(".py") or file.startswith("_"):
                    continue
                module_name = os.path.splitext(file)[0]
                # 模板不是算法：文件名里带「模板」的一律跳过（`我的控制律_模板.py` 这种），
                # 否则它会被当成一个可装配的算法，而它里面的 `我的插件` 只是给人抄的示例。
                if "模板" in module_name or "template" in module_name.lower():
                    continue
                result.append({
                    "插件": module_name,
                    "文件": os.path.abspath(os.path.join(current, file)),
                    "相对包根": relative_to_package(os.path.join(current, file)),
                    "分组": os.path.relpath(current, root).replace("\\", "/")
                            if os.path.relpath(current, root) != "." else "",
                })
    return result


# ---------------------------------------------------------------------------
# 参数（按项目持久化）
# ---------------------------------------------------------------------------
def load_parameters(project_name: str) -> dict:
    """读一个项目里已保存的参数：{插件名: {参数名: 值}}。"""
    return dict((load_project(project_name) or {}).get("参数") or {})


def save_parameters(project_name: str, plugin_name: str, parameters: dict) -> bool:
    """把某个插件的参数写回项目文件（其它插件的参数保持不动）。

    ★ 为什么要落盘：参数面板拖出来的值今天只活在内存里，换项目/重启就没了。
      落到项目文件之后，"这一组参数"成了实验记录的一部分 —— 这正是方案 C 要的。
    """
    data = load_project(project_name)
    if data is None:
        return False
    if not parameters:
        return True
    all_parameters = dict(data.get("参数") or {})
    plugin_parameters = dict(all_parameters.get(plugin_name) or {})
    plugin_parameters.update({str(k): float(v) for k, v in parameters.items()})
    all_parameters[plugin_name] = plugin_parameters
    data["参数"] = all_parameters
    return save_project(data)


# ---------------------------------------------------------------------------
# 记住"上次用的项目"（启动时恢复用）
# ---------------------------------------------------------------------------
def _read_settings() -> dict:
    data = _read_json(SETTINGS_PATH)
    return data


def load_last_project() -> str:
    """上次用的项目名；没有 / 项目文件已不在 → 返回空串。"""
    name = str(_read_settings().get("上次项目") or "")
    if name and load_project(name) is None:
        return ""
    return name


def save_last_project(project_name: str) -> None:
    """记住这次用的项目（空串 = 清掉）。写失败不影响使用。"""
    data = _read_settings()
    if data.get("上次项目") == project_name:
        return
    if project_name:
        data["上次项目"] = project_name
    else:
        data.pop("上次项目", None)
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    _write_json(SETTINGS_PATH, data)


# ---------------------------------------------------------------------------
# Stable English public API
# ---------------------------------------------------------------------------



__all__ = [
    "PACKAGE_ROOT", "PROJECT_DIRECTORY", "ALGORITHM_DIRECTORY", "MODEL_DIRECTORY",
    "SETTINGS_PATH", "PROJECT_SUFFIX", "absolute_path", "relative_to_package",
    "model_library_entries", "display_model_name", "list_projects",
    "project_file_path", "load_project", "save_project", "find_project_for_model",
    "ALGORITHM_ALIASES", "normalize_algorithm_name", "algorithm_file",
    "parse_algorithms", "discover_algorithms", "load_parameters", "save_parameters",
    "load_last_project", "save_last_project",
]
