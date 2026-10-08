"""
文案.py —— 界面文字的中英两套 + 语言开关（**唯一真源**）

为什么要有这个文件：
    · 用户要"一键切中英文"。界面上任何一句写死的话，切语言时都不会跟着变 ——
      所以**所有画到界面上的文字都必须从这里取**（`文案.取("键")`）。
    · 校验闸门：`验证/语言自检.py` 会扫描面板目录，**发现硬编码的界面中文就报错**。
      注释 / docstring / 终端 print 里的中文不算（那三类不画到界面上）。

三层现实（用户问过"能不能整个界面都中文"）：
    ① 我们自己的面板 + 菜单栏 + 面板窗 → **全部可切**（就是本文件管的）
    ② 官方用 **Python** 画的顶栏（File / Simulation / View / Help 及其条目）→ 也能切：
       见 `菜单栏.py` 里对 `imgui.BeginMenu/MenuItem` 的包装 + 下面的 `官方顶栏` 表
    ③ 官方用 **C++** 画的面板（Options 里那 19 个段、Inspector 里的 Noise/Joints/…）→
       **切不了**，字符串编译在 ux.*.so 里。这是天花板，已记进设计规格。

语言选择的优先级（`决定启动语言`）：命令行 `--语言` > 环境变量 `YUBI_LANG` / `驭臂_语言` > 存档 > **默认中文**。
存档位置：`输出/设置.json` 的 `语言` 键（和"上次模型"等设置共用一个文件）。
"""
from __future__ import annotations

import json
import os as _os

中文 = "zh"
英文 = "en"
合法语言 = (中文, 英文)
文案默认语言 = 中文
语言名 = {中文: "中文", 英文: "English"}

_包根 = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
设置路径 = _os.path.join(_包根, "输出", "设置.json")

当前语言 = 文案默认语言


# ---------------------------------------------------------------------------
# 文案表：键 → (中文, English)
#   ★ 加文案就在这里加一行；面板里写 `文案.取("键")`。
#   ★ 键用"区域.含义"的短中文没关系 —— 它不进界面，只是索引。
# ---------------------------------------------------------------------------
表: dict[str, tuple[str, str]] = {
    # ---- 通用 ----
    "通用.打开": ("打开", "Open"),
    "通用.关闭": ("关闭", "Close"),
    "通用.是": ("是", "Yes"),
    "通用.否": ("否", "No"),
    "通用.刷新": ("刷新", "Refresh"),
    "通用.应用": ("应用", "Apply"),
    "通用.保存": ("保存", "Save"),
    "通用.取消": ("取消", "Cancel"),
    "通用.等待": ("等待中…", "waiting…"),
    "通用.就绪": ("就绪", "ready"),

    # ---- 顶部菜单栏（我们自己挂的） ----
    "顶栏.外观": ("外观", "Appearance"),
    "顶栏.面板": ("面板", "Panels"),
    "顶栏.切到英文": ("EN", "EN"),
    "顶栏.切到中文": ("中文", "中文"),
    "顶栏.语言提示": ("点击切换界面语言", "Click to switch UI language"),
    "顶栏.语言": ("语言", "Language"),
    "顶栏.显示面板窗": ("显示面板窗", "Show panels window"),
    "顶栏.隐藏面板窗": ("收起面板窗", "Hide panels window"),
    "顶栏.全部恢复": ("全部恢复 (F9)", "Reveal all (F9)"),
    "顶栏.重置版面": ("重置版面 (Shift+F9)", "Reset panel layout (Shift+F9)"),
    "顶栏.打开外观面板": ("打开完整外观面板（色卡/预览/FPS）", "Open full Appearance panel (swatches/preview/FPS)"),
    "顶栏.皮肤": ("皮肤（我们自己的）", "Skin (ours)"),
    "顶栏.基底主题": ("基底主题（皮肤关掉时用它）", "Base theme (used when skin is off)"),
    "顶栏.快捷键提示": ("F10 轮换皮肤", "F10 cycles the skin"),
    "顶栏.面板区提示": ("面板（Ctrl+1..7）", "panels (Ctrl+1..7)"),
    "顶栏.面板窗提示": ("Esc 收起面板窗", "Esc closes the panels window"),
    "顶栏.浅色": ("浅色", "Light"),
    "顶栏.深色": ("深色", "Dark"),
    "顶栏.经典": ("经典", "Classic"),

    # ---- 官方顶栏那 11 条（只有这些是 Python 画的，能翻） ----
    "官方.File": ("文件", "File"),
    "官方.Simulation": ("仿真", "Simulation"),
    "官方.View": ("视图", "View"),
    "官方.Help": ("帮助", "Help"),
    "官方.Quit": ("退出", "Quit"),
    "官方.Save Config": ("保存配置", "Save Config"),
    "官方.Reset Config": ("恢复默认配置", "Reset Config"),
    "官方.Hide Toolbar": ("隐藏工具栏", "Hide Toolbar"),
    "官方.Show Toolbar": ("显示工具栏", "Show Toolbar"),
    "官方.Info": ("信息", "Info"),
    "官方.Profiler": ("性能分析", "Profiler"),

    # ---- 面板窗（Panels 窗） ----
    "面板窗.标题": ("面板", "Panels"),
    "面板窗.已开数": ("已展开 {开}/{总}", "{开}/{总} open"),
    "面板窗.全开": ("全开", "all"),
    "面板窗.全收": ("全收", "none"),
    "面板窗.提示": ("Ctrl+1..7 跳段｜Esc 收起", "Ctrl+1..7 jumps | Esc closes"),
    "面板窗.未加载": ("（这个面板没被加载）", "(this panel is not loaded)"),
    "面板窗.出错": ("[出错] {类型}（详情在终端）", "[fail] {类型} (details in the terminal)"),
    "面板窗.页签.Inspector": ("检查器", "Inspector"),
    "面板窗.页签.Panels": ("面板", "Panels"),

    # ---- 展示（Display，物理总闸） ----
    "展示.标题": ("显示", "Display"),
    "展示.加载重力": ("加载重力", "Load gravity"),
    "展示.重力生效": ("重力生效 —— 模型可以动了", "gravity acts - the model can move"),
    "展示.没算法": ("（没挂算法？那它就自由下落）", "(no algorithm? it just falls)"),
    "展示.冻结中": ("冻结在默认姿态", "frozen at the default pose"),
    "展示.无物理": ("（不推进物理、不受重力）", "(no physics, no gravity)"),
    "展示.勾选提示": ("勾上它才施用重力", "check it to let gravity act"),

    # ---- 监控（实时曲线） ----
    "监控.收帧": ("收到的指标帧 = {n}", "metric frames received = {n}"),

    # ---- 录制 ----
    "录制.标题": ("数据录制", "Recorder"),
    "录制.开始": ("开始录制", "Start"),
    "录制.停止保存": ("停止并保存", "Stop and save"),
    "录制.回放": ("回放", "Replay"),
    "录制.频率": ("采样率 Hz", "Hz"),
    "录制.备注": ("备注", "note"),
    "录制.状态": ("状态={值}", "state={值}"),
    "录制.产物说明": ("产物：CSV + .meta.json（完整路径打在终端）",
                 "files -> CSV + .meta.json (exact path printed in terminal)"),

    # ---- 控制器参数 ----
    "参数.标题": ("控制器参数", "Controller params"),
    "参数.无可调": ("没有可调参数。在你的插件里加这个方法：", "No tunable parameters. Add to your plugin:"),
    "参数.说明": ("（方法名/键名不是 ASCII；完整示例打在终端）",
              "(the method/key names are non-ASCII; full example printed in terminal)"),
    "参数.统计": ("重绘 {帧} 帧｜已发改动 {改动}", "frames={帧}  changes sent={改动}"),
    "参数.重置": ("重置为项目里的值", "Reset"),

    # ---- 曲线基类（所有曲线面板共用） ----
    "曲线.清空": ("清空", "Clear"),
    "曲线.暂停": ("暂停", "Pause"),
    "曲线.继续": ("继续", "Resume"),
    "曲线.时间窗": ("时间窗（秒）", "window (s)"),
    "曲线.暂无数据": ("还没有数据…", "No data yet…"),
    "曲线.等待数据": ("等待数据…", "Waiting for data…"),
    "曲线.读数": ("= {值:+.3f}（峰值 {峰:.3f}）", "= {值:+.3f}  (peak {峰:.3f})"),

    # ---- 参数辨识 ----
    "辨识.标题": ("参数辨识", "System identification"),
    "辨识.非ASCII日志": ("（另有 {条} 行非 ASCII 日志，见终端）",
                    "(+{条} non-ASCII log line(s) - shown in terminal)"),
    "辨识.第一步": ("1. 激励采样", "1. Excitation sample"),
    "辨识.第二步": ("2. 辨识", "2. Identify"),
    "辨识.采样时长": ("采样时长（秒）", "sample (s)"),
    "辨识.空闲状态": ("空闲｜已采样步数={步数}", "idle   sampled steps={步数}"),
    "辨识.结果表头": ("结果（名称 / 标称 / 辨识值 / 变化）",
                 "Result (name / nominal / estimated / change)"),
    "辨识.拟合": ("拟合残差：{前:.6f} → {后:.6f}", "Fit residual:  {前:.6f} -> {后:.6f}"),
    "辨识.残差说明一": ("残差下降 = 这组参数更贴合**这批数据**",
                  "residual down = params fit THIS data better"),
    "辨识.残差说明二": ("（它**不能**证明这组参数等于真实机器人）",
                  "(it does NOT prove they equal the real robot)"),
    "辨识.日志": ("日志（最新在上）", "log (latest first)"),
    "辨识.统计": ("重绘 {帧} 帧｜已发命令 {命令}", "frames={帧}  cmds={命令}"),

    # ---- 关于 ----
    "关于.标题": ("关于", "About"),
    "关于.版本行": ("版本 {版本}　构建于 {构建}", "version {版本}   built {构建}"),
    "关于.运行环境": ("运行环境", "Runtime"),
    "关于.引擎行": ("MuJoCo {版本}", "MuJoCo {版本}"),
    "关于.Python行": ("Python {版本}（{架构}）", "Python {版本} ({架构})"),
    "关于.后端": ("物理后端：MuJoCo（CPU）｜渲染器：Filament",
               "physics backend: MuJoCo (CPU), renderer: Filament"),
    "关于.已加载算法": ("已加载的控制算法", "Loaded control plugins"),
    "关于.无": ("（无）", "(none)"),
    "关于.面板": ("面板", "Panels"),
    "关于.模型": ("模型", "Model"),
    "关于.声明": ("声明", "Notices"),
    "关于.重绘": ("已重绘 {n} 次", "drawn {n} times"),

    # ---- 模型库（选机械臂） ----
    "模型库.标题": ("模型库", "Model library"),
    "模型库.列表标头": ("模型库（{n} 台可选，点一下即切换）",
                  "Model library ({n} arms; click to switch)"),
    "模型库.轴数": ("{n} 个自由度", "{n} axes"),
    "模型库.空库": ("  模型库里没有可用的机械臂。", "  No usable arms in the library."),
    "模型库.空库提示": ("  先跑模型导入工具（命令打在终端）。",
                  "  Run the model import tool (command printed in terminal)."),
    "模型库.许可行": ("{轴} 个自由度 ｜ {许可}", "{轴} axes | {许可}"),
    "模型库.导入": ("从本地导入模型…", "Import model file..."),
    "模型库.导入中": ("（在系统对话框里选一个文件…）", "(pick a file in the system dialog...)"),
    "模型库.空场景": ("空场景", "Empty scene"),
    "模型库.重载": ("重新加载当前", "Reload current"),
    "模型库.刷新": ("刷新列表", "Refresh list"),
    "模型库.走这个路径": ("加载这个路径", "Load this path"),
    "模型库.路径不存在": ("  这个路径不存在", "  path not found"),
    "模型库.拖拽提示": ("也可以把 .xml / .mjb / .mjz **文件**直接拖进窗口（内建能力）",
                  "You can also drag an .xml / .mjb / .mjz FILE into the window (built in)"),
    "模型库.拖拽注意": ("注意：拖**文件夹**不行 —— 加载器只认文件",
                  "Note: dropping a FOLDER does not work - the loader only accepts files"),
    "模型库.统计": ("重绘 {帧} 帧｜切换 {切换} 次｜库 {库} 台",
               "frames={帧}  switches={切换}  draw={绘制}  lib={库}"),
    "模型库.当前项目无算法": ("  算法（0）：这个项目没挂算法",
                      "  Algorithms (0): none for this project"),
    "模型库.项目算法": ("  算法（{n}）：", "  Algorithms ({n}):"),
    "模型库.装配报告": ("    → 加项目文件（见终端提示），或在面板里勾算法",
                  "    -> add a project file (see terminal), or tick algorithms in the panel"),
    "模型库.跳过算法": ("  {n} 个算法被跳过（与这个模型不兼容）",
                  " {n} algorithm(s) skipped (model incompatible)"),
    "模型库.跳过详情": ("    详情打在终端", "    details printed in the terminal"),
    "模型库.无算法": ("（没挂算法）", "(none - no algorithms loaded)"),
    "模型库.加项目": ("    → 加一个项目文件（文件夹名见终端）",
                 "    -> add a project file (see terminal for the folder name)"),
    "模型库.算法行": ("    · {名} v{版}{后缀}", "    · {名} v{版}{后缀}"),
    "模型库.参数数": ("（{n} 个参数）", "({n} params)"),
    "模型库.手动路径提示": ("路径不在模型库里时，直接粘进来",
                    "paste a path here when it is not in the library"),
}


# 不改：这些字符串**不随语言变**（专有名词/数据/文件路径里的中文），
#   语言自检会把它们从"硬编码中文"里豁免掉。往这里加东西要谨慎 —— 它等于"这句不翻译"。
不改 = {
    "小软件",              # 应用名（产品名，不翻）
    "驭臂",
}


def 取(键: str, 默认: str = "") -> str:
    """取当前语言的文案。查不到就用 `默认`（这样漏登记的键不会画成空白）。"""
    对 = 表.get(键)
    if 对 is None:
        return 默认
    return 对[0] if 当前语言 == 中文 else 对[1]


def 状态(原文: str) -> str:
    """状态串：中文模式原样，英文模式走 `界面文字.英文()` 的既有翻译表。

    （`界面文字.py` 是旧 ASCII 时代留下的"中文→英文"表，状态串的翻译继续复用它。）
    """
    if 当前语言 == 中文:
        return str(原文)
    try:
        import 界面文字
        return 界面文字.英文(str(原文)) or str(原文)
    except Exception:                                                    # noqa: BLE001
        return str(原文)


def 有(键: str) -> bool:
    return 键 in 表


def 格式化(键: str, 默认: str = "", **值) -> str:
    """取文案并把 `{名}` 占位换掉（中英两版都要有同名占位符）。"""
    文本 = 取(键, 默认)
    try:
        return 文本.format(**值)
    except Exception:                                                    # noqa: BLE001
        return 文本


def 另一个(语言: str = "") -> str:
    语 = 语言 or 当前语言
    return 英文 if 语 == 中文 else 中文


def 语言显示名(语言: str = "") -> str:
    return 语言名.get(语言 or 当前语言, "?")


def 切换() -> str:
    """一键切换，返回切换后的语言。"""
    设语言(另一个())
    return 当前语言


# ---------------------------------------------------------------------------
# 语言状态与存档
# ---------------------------------------------------------------------------
def 设语言(语言: str, *, 记住: bool = True) -> bool:
    """设置语言。返回是否认得这个值（改成功才写存档）。"""
    global 当前语言
    语 = str(语言 or "").strip().lower()
    别名 = {"zh": 中文, "cn": 中文, "chinese": 中文, "中文": 中文,
            "en": 英文, "english": 英文, "英文": 英文}
    语 = 别名.get(语, 语)
    if 语 not in 合法语言:
        return False
    if 语 != 当前语言:
        当前语言 = 语
        print(f"【语言】界面语言 → {语言名[语]}", flush=True)
    if 记住:
        写存档(语)
    return True


def _读设置() -> dict:
    try:
        with open(设置路径, encoding="utf-8") as f:
            数据 = json.load(f)
        return 数据 if isinstance(数据, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:                                                    # noqa: BLE001
        return {}


def _写设置(数据: dict) -> None:
    try:
        _os.makedirs(_os.path.dirname(设置路径), exist_ok=True)
        with open(设置路径, "w", encoding="utf-8") as f:
            json.dump(数据, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as 异常:                                            # noqa: BLE001
        print(f"⚠ 设置保存失败（不影响使用）：{type(异常).__name__}: {异常}")


def 读存档() -> str:
    """存档里的语言；没有/认不出就回空串。"""
    语 = str(_读设置().get("语言") or "").strip().lower()
    return 语 if 语 in 合法语言 else ""


def 写存档(语言: str) -> None:
    """写语言到 输出/设置.json（空串 = 清掉这一项，交回默认）。"""
    数据 = _读设置()
    if 语言:
        数据["语言"] = 语言
    else:
        数据.pop("语言", None)
    _写设置(数据)


def 决定启动语言(命令行语言: str = "") -> tuple[str, str]:
    """启动时用哪种语言。优先级：命令行 > 环境变量 > 存档 > 默认中文。

    返回 (语言, 来源说明) —— 来源说明只用于启动时打印一行，方便排查"为什么是这样"。
    """
    if 命令行语言:
        语 = str(命令行语言).strip().lower()
        if 设语言(语, 记住=False):
            return 当前语言, "命令行 --语言"
        print(f"⚠ 认不出语言「{命令行语言}」，可选：zh / en（已按默认处理）")
    环境 = (_os.environ.get("YUBI_LANG") or _os.environ.get("驭臂_语言") or "").strip()
    if 环境:
        if 设语言(环境, 记住=False):
            return 当前语言, "环境变量 YUBI_LANG"
    存档 = 读存档()
    if 存档:
        设语言(存档, 记住=False)
        return 当前语言, "存档（输出/设置.json）"
    return 文案默认语言, "默认"
