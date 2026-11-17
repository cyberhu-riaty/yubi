"""
界面文字.py —— 中文术语/状态串的英文翻译表

> 注（2026-10-22）：字体补丁工具已随官方 ImGui 界面一起移除；当前界面是 React，
> 不再受 ImGui 字体限制。本文件现在主要供 `文案.取()` 的英文模式调用 `英文()`，
> 下面关于字体与 ASCII 的历史说明仅作背景。

★ 它解决什么问题（一个真实的观感缺陷）：
    官方 Studio 往 ImGui 字体图集里只装了两套字体：
        · Atkinson Hyperlegible Next / Mono（各 300 多个码位，**纯拉丁**）
        · fontawesome-webfont.ttf（图标）
    它们**一个中文字形都没有**，而且连 ● ○ ✓ ✗ ← → （） ｜ 这些符号也没有。
    ImGui 遇到图集里没有的字符会回退画 `ImFont::FallbackChar`（默认就是 `'?'`），
    于是面板上任何中文都会变成一串 `?????` —— 这就是"弹窗里很多问号"的原因。

    ★ 关于"能不能给它装个中文字体"—— 结论已经更新（2026-09-24 实测）：
      **Python 绑定确实没有任何字体接口**（没有 `AddFontFromFileTTF` / `ImFontAtlas`，
      `IO` 上也没有 `Fonts`，`FontGlobalScale` 还是只读的）—— 所以"运行时注入"这条路不通。
      但还有一条路当时没想到：**字体是按文件名从 assets/ 加载的，换文件不用碰二进制。**
      官方用的是 Dear ImGui 1.92 的**动态字形图集**（用到哪个码位就现烘焙哪个），
      所以把汉字字形**并进**那份 .ttf 就能显示中文，连 CJK 范围都不用声明。

      实测判定（数值，不靠肉眼）：
          原始： CalcTextSize('中').x = 6.00 = CalcTextSize('?').x   ← 走回退字形
          补丁后：CalcTextSize('中').x = 13.00 ≠ 6.00                ← 拿到真汉字字形
          5 组拉丁样本宽度（242/158/257/361/23）**逐位不变** → 拉丁观感没被改坏

      怎么开：`.venv/bin/python tools/打补丁_中文字体.py`（`--还原` 可退回）。
      生成物只写进 .venv、**不入库**（汉字源是 macOS 自带的 STHeiti，Apple 许可不允许再分发）。

    ⚠ 所以本文件的作用变了：它从"**唯一**的活路"降级为"**没打补丁时的兜底**"。
      判断当前是哪一种：`tools/打补丁_中文字体.py --状态`（或看下面的 字体覆盖.py 实测）。

    取证：`tools/selfchecks/字体覆盖.py`（用 fontTools 读 cmap 逐字符核对 + 静态扫面板代码），
          输出 `tools/selfchecks/字体覆盖_实测.txt`。
          运行时判定：`tools/selfchecks/字体探针.py`（开窗约 1 秒，量字符宽度）。

下面三条是「**没打字体补丁**」时的规矩（打了补丁以后它们不再是限制，但保留着有好处：
面板文字全 ASCII 时，换任何字体/任何机器都不会出问号）：
    ① 面板上只画 ASCII（外加 · … ± ° 这几个 Atkinson 确实有的符号），中文留给**终端与文档**
       —— 终端用系统字体，中文完全正常（启动提示、插件状态行、⚠ 警告都是中文，没问题）
    ② 面板要显示"名字"时，**优先用英文名**：插件声明 `英文名 = "Joint PD"`，
       风格表里也有 `英文名` / `英文说明`
    ③ 兜底走 `英文()`：先查术语表，再按"数字+单位"规则翻，最后才剥成 ASCII；
       还残留中文才在终端提醒一次（提醒在终端，不占面板）

★ 一条实测教训：**单字替换会翻错**。术语表里放过 "行"→"rows"，
  结果 "仿真进行中" 里的 "行" 被咬掉，整句变成 "rows" —— 翻错比问号更糟。
  所以：短语替换只认 **≥2 字** 的词条，单位（轴/秒/行/次）用正则按"数字+单位"精确匹配。
"""
from __future__ import annotations

import re

# Atkinson Hyperlegible 里确实存在、且不属于 ASCII 的少数符号（可以用）
ALLOWED_NON_ASCII = "·…±°"

_unsupported = re.compile("[^\\x20-\\x7E" + re.escape(ALLOWED_NON_ASCII) + "]")
_chinese_pattern = re.compile(r"[\u3400-\u9FFF]")
_warned: set[str] = set()

# ---------------------------------------------------------------------------
# ① 精确匹配表：整个字符串就是它 → 直接给英文（面板显示用；终端仍然说中文）
# ---------------------------------------------------------------------------
TERMS = {
    # —— 曲线/指标名（plugins/*.py 的 指标() 返回的键）——
    "最大误差(deg)": "max error (deg)",
    "力矩峰值(Nm)": "peak torque (Nm)",
    "已采样步数": "sampled steps",
    "已录行数": "recorded rows",
    # —— 插件名（优先用插件自己声明的 英文名 属性）——
    "关节 PD 位置控制": "Joint PD position control",
    "参数辨识": "System identification",
    "末端两点运动": "Two-point task-space motion",
    "正弦摆动": "Sinusoid swing",
    "数据录制与回放": "Recorder",
    # —— 面板名（About 面板里会列出面板清单）——
    "模型库": "Model library",
    "外观": "Appearance",
    "关于": "About",
    "控制器参数": "Controller params",
    "数据录制": "Recorder",
    "实时监控": "Monitor",
    # —— 常用短句/动词（≥2 字，会被当短语替换）——
    "正在激励采样": "sampling excitation",
    "正在加载": "loading",
    "正在保存": "saving",
    "已切换到": "switched to",
    "已记录": "recorded",
    "已完成": "done",
    "已停止": "stopped",
    "已应用": "applied",
    "识别完成": "identified",
    "采样完成": "sampling done",
    "耗时": "load time",
    "保存到": "saved to",
    "后台线程": "background thread",

    # —— 状态词 ——
    "空闲": "idle",
    "录制中": "recording",
    "采样中": "sampling",
    "辨识中": "identifying",
    "就绪": "ready",
    "不支持": "unsupported",
    "等待仿真侧…": "waiting for sim...",
    "等待第一步": "waiting",
    "正在加载": "loading",
    "辨识中（后台线程）…": "identifying (background thread)...",
    # —— 项目（方案 C：模型库面板上要显示"当前项目 + 算法个数"）——
    #   项目名按约定是 `<模型>_基础PD`，所以「_基础PD」当短语替换就够，
    #   不必为每个模型登记一条（模型名本身 UR5e / xArm7 / Panda 已经是 ASCII）。
    #   注意短语表只认 ≥2 字的词条，所以这里都是 2 字以上。
    "_基础PD": " Basic PD",
    "基础PD": "Basic PD",
    "项目：": "Project: ",
    "个项目": "projects",
    "个算法": "algorithms",
    # —— 模型相关 ——
    "空场景（无机械臂）": "Empty scene (no robot)",
    "空场景": "Empty scene",
    "（外来模型）": "(external model)",
    "（未知）": "(unknown)",
    "（未知来源）": "(unknown source)",
}
# 短语替换只认 ≥2 字的词条，并按长度从长到短（避免短词先把长词咬掉）
_phrases = sorted(((k, v) for k, v in TERMS.items() if len(k) >= 2), key=lambda kv: -len(kv[0]))

# ---------------------------------------------------------------------------
# ② 单位规则：只认"数字 + 单位"这种写法，避免把"进行"里的"行"咬掉
# ---------------------------------------------------------------------------
_unit_rules = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*轴"), r"\1 axes"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*秒"), r"\1 s"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*行"), r"\1 rows"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*次"), r"\1x"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*个"), r"\1"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*台"), r"\1"),
]


def is_supported(text) -> bool:
    """这段文字画在面板上会不会出现 ?（False = 会出现）。"""
    return not _unsupported.search(str(text))


def contains_non_ascii(text) -> bool:
    return not is_supported(text)


def sanitize(text, replacement: str = " ") -> str:
    """把字体画不出来的字符换成替代字符（默认换成空格），再把空白收拾干净。

    ★ 默认用空格而不是直接删：中文常常夹在全角括号/顿号里，全删掉会让
      前后两段英文粘成一坨（实测："正在激励采样（2.0 秒）" → "sampling excitation2.0 s"）。
      换成空格后是 "sampling excitation 2.0 s"。
    ★ 兜底结果可能"少几个字"，但不会出现一行问号 —— 观感优先。
    """
    result = _unsupported.sub(replacement, str(text))
    result = re.sub(r"[ \t]{2,}", " ", result)
    return result.strip().strip("·，、。：；,.:; ")


def to_english(text, default: str | None = None) -> str:
    """尽量给出英文。

    ① 原样就是 ASCII → 原样
    ② 整串命中术语表 → 用它
    ③ 短语替换（≥2 字词条）+ "数字+单位"规则
    ④ 剥成 ASCII（若还残留中文，在终端提醒一次）
    实在剥不出东西 → 用 `默认`（没有就返回空串）
    """
    text = str(text)
    if is_supported(text):
        return text
    original = text.strip()
    if original in TERMS:
        return TERMS[original]

    translated = original
    for chinese, english in _phrases:
        if chinese in translated:
            translated = translated.replace(chinese, english)
    for pattern, replacement in _unit_rules:
        translated = pattern.sub(replacement, translated)
    translated = re.sub(r"[ \t]{2,}", " ", translated).strip()
    if is_supported(translated):
        return translated

    result = sanitize(translated)
    if _chinese_pattern.search(translated):            # 还剩没登记的汉字 → 提醒一次
        warn_once(text)
    if not result:
        return default if default is not None else ""
    return result


def warn_once(text) -> None:
    """没登记的中文名：在终端提醒一次（终端中文正常，不影响面板）。"""
    key = str(text)[:24]
    if key in _warned:
        return
    _warned.add(key)
    print(f'【界面文字】面板上出现未登记的非 ASCII 文本「{str(text)[:40]}」'
          f"→ 已按 ASCII 显示。要显示成想给的英文，请："
          f"① 给插件/对象加 `英文名 = \"...\"`，或 ② 在 界面文字.py 的 术语表 里加一条", flush=True)
