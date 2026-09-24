"""
界面文字.py —— 面板上只画"字体画得出来"的字符（否则 ImGui 会画成一串 ?）

★ 它解决什么问题（一个真实的观感缺陷）：
    官方 Studio 往 ImGui 字体图集里只装了两套字体：
        · Atkinson Hyperlegible Next / Mono（各 300 多个码位，**纯拉丁**）
        · fontawesome-webfont.ttf（图标）
    它们**一个中文字形都没有**，而且连 ● ○ ✓ ✗ ← → （） ｜ 这些符号也没有。
    ImGui 遇到图集里没有的字符会回退画 `ImFont::FallbackChar`（默认就是 `'?'`），
    于是面板上任何中文都会变成一串 `?????` —— 这就是"弹窗里很多问号"的原因。

    ★ 为什么不能"给它装个中文字体"：这个 Python 绑定里**没有任何字体接口**
      （没有 `AddFontFromFileTTF` / `ImFontAtlas`，`IO` 上也没有 `Fonts`，
      `FontGlobalScale` 还是只读的）。imgui 自己的提示就写着"要用 CJK 得在 C++ 里
      `io.Fonts->AddFontFromFileTTF()`" —— 那意味着放弃官方 wheel、自己编 imgui，本项目不做。

    取证：`优化（软件优化的报告都放这里面来）/验证/字体覆盖.py`（用 fontTools 读 cmap 逐字符核对 + 静态扫面板代码），
          输出 `优化（软件优化的报告都放这里面来）/验证/字体覆盖_实测.txt`。

所以本项目的规矩（三条）：
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
允许的非ASCII = "·…±°"

_不支持 = re.compile("[^\\x20-\\x7E" + re.escape(允许的非ASCII) + "]")
_有中文 = re.compile(r"[\u3400-\u9FFF]")
_已提醒: set[str] = set()

# ---------------------------------------------------------------------------
# ① 精确匹配表：整个字符串就是它 → 直接给英文（面板显示用；终端仍然说中文）
# ---------------------------------------------------------------------------
术语表 = {
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
_短语表 = sorted(((k, v) for k, v in 术语表.items() if len(k) >= 2), key=lambda kv: -len(kv[0]))

# ---------------------------------------------------------------------------
# ② 单位规则：只认"数字 + 单位"这种写法，避免把"进行"里的"行"咬掉
# ---------------------------------------------------------------------------
_单位表 = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*轴"), r"\1 axes"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*秒"), r"\1 s"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*行"), r"\1 rows"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*次"), r"\1x"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*个"), r"\1"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*台"), r"\1"),
]


def 可用(文本) -> bool:
    """这段文字画在面板上会不会出现 ?（False = 会出现）。"""
    return not _不支持.search(str(文本))


def 有非ASCII(文本) -> bool:
    return not 可用(文本)


def 安全(文本, 替代: str = " ") -> str:
    """把字体画不出来的字符换成替代字符（默认换成空格），再把空白收拾干净。

    ★ 默认用空格而不是直接删：中文常常夹在全角括号/顿号里，全删掉会让
      前后两段英文粘成一坨（实测："正在激励采样（2.0 秒）" → "sampling excitation2.0 s"）。
      换成空格后是 "sampling excitation 2.0 s"。
    ★ 兜底结果可能"少几个字"，但不会出现一行问号 —— 观感优先。
    """
    结果 = _不支持.sub(替代, str(文本))
    结果 = re.sub(r"[ \t]{2,}", " ", 结果)
    return 结果.strip().strip("·，、。：；,.:; ")


def 英文(文本, 默认: str | None = None) -> str:
    """尽量给出英文。

    ① 原样就是 ASCII → 原样
    ② 整串命中术语表 → 用它
    ③ 短语替换（≥2 字词条）+ "数字+单位"规则
    ④ 剥成 ASCII（若还残留中文，在终端提醒一次）
    实在剥不出东西 → 用 `默认`（没有就返回空串）
    """
    文本 = str(文本)
    if 可用(文本):
        return 文本
    原样 = 文本.strip()
    if 原样 in 术语表:
        return 术语表[原样]

    换过 = 原样
    for 中, 英 in _短语表:
        if 中 in 换过:
            换过 = 换过.replace(中, 英)
    for 规则, 替换 in _单位表:
        换过 = 规则.sub(替换, 换过)
    换过 = re.sub(r"[ \t]{2,}", " ", 换过).strip()
    if 可用(换过):
        return 换过

    结果 = 安全(换过)
    if _有中文.search(换过):            # 还剩没登记的汉字 → 提醒一次
        提醒一次(文本)
    if not 结果:
        return 默认 if 默认 is not None else ""
    return 结果


def 提醒一次(文本) -> None:
    """没登记的中文名：在终端提醒一次（终端中文正常，不影响面板）。"""
    关键 = str(文本)[:24]
    if 关键 in _已提醒:
        return
    _已提醒.add(关键)
    print(f"【界面文字】面板上出现未登记的非 ASCII 文本「{str(文本)[:40]}」"
          f"→ 已按 ASCII 显示。要显示成想给的英文，请："
          f"① 给插件/对象加 `英文名 = \"...\"`，或 ② 在 界面文字.py 的 术语表 里加一条", flush=True)
