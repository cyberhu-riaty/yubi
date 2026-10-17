"""
契约自检.py —— P1 的 L0 层"可机检的不变量"

它检查什么（三类，都是"会静默出错"的地方）：
    ① **契约 vs 真实 dataclass**：`契约.py` 是手写的，手写就会漂移。
       字段名/顺序/数量不一致时，前端的类型定义会与后端实际发出的东西对不上，
       而**运行期不会报错** —— 只是某个字段永远显示不出来。
    ② **生成物是否过期**：`前端/src/生成/契约.ts`、`主题.css`、`风格.ts`
       是从 `契约.py` 与 `风格表.json` 生成的。来源改了没重新生成 = 前端拿旧契约解析新数据。
    ③ **上行命令是否真的能落地**：每条登记的上行命令都要能构造出对应的消息类，
       否则"契约里有、实际发不出去"。

用法：
    .venv/bin/python 工具/验证/契约自检.py          # 跑全部检查
    .venv/bin/python 工具/验证/契约自检.py --简      # 只打结论
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

本目录 = os.path.dirname(os.path.abspath(__file__))
包根 = os.path.dirname(os.path.dirname(本目录))
软件目录 = os.path.join(包根, "软件")
夹具目录 = os.path.join(本目录, "夹具")
if 软件目录 not in sys.path:
    sys.path.insert(0, 软件目录)

通过 = 0
失败 = 0
明细: list[str] = []


def 判(条件: bool, 说明: str) -> bool:
    global 通过, 失败
    if 条件:
        通过 += 1
        明细.append(f"  ✓ {说明}")
    else:
        失败 += 1
        明细.append(f"  ✗ {说明}")
    return 条件


def 检查契约与代码一致() -> None:
    import 契约
    明细.append("\n【① 契约 vs 真实 dataclass】")
    问题 = 契约.查漂移()
    判(not 问题, f"登记了 {len(契约.所有主题)} 个主题（下行 {len(契约.下行主题)} / "
                f"上行 {len(契约.上行主题)}），字段与 dataclass 逐项一致")
    for p in 问题:
        明细.append(f"      · {p}")


def 检查生成物() -> None:
    明细.append("\n【② 生成物是否过期】")
    脚本 = os.path.join(包根, "工具", "生成前端资产.py")
    结果 = subprocess.run([sys.executable, 脚本, "--检查"],
                          capture_output=True, text=True)
    判(结果.returncode == 0,
      "前端生成物（契约.ts / 主题.css / 风格.ts）与来源一致")
    if 结果.returncode != 0:
        for 行 in 结果.stdout.strip().splitlines():
            if "✗" in 行:
                明细.append(f"      {行.strip()}")


def 检查上行命令能落地() -> None:
    明细.append("\n【③ 上行命令能否真的构造出消息】")
    import importlib
    import 契约
    import 命令桥
    for t in 契约.上行主题:
        类 = 命令桥._取消息类(t.类名)                                    # noqa: SLF001
        if 类 is None:
            判(False, f"{t.名} → {t.类名}：拿不到消息类")
            continue
        # 用契约字段名构造一次（值按类型给最小合法值），确认字段名真的对得上
        试 = {}
        for f in t.字段:
            if f.类型 == "boolean":
                试[f.名] = False
            elif f.类型 == "number":
                试[f.名] = 1.0
            elif f.类型 == "string":
                试[f.名] = "测试"
            elif f.类型.endswith("[]"):
                试[f.名] = []
            else:
                试[f.名] = {}
        try:
            类(**试)
            判(True, f"{t.名:12} → {t.类名}（字段名与顺序都对得上）")
        except Exception as 异常:                                     # noqa: BLE001
            判(False, f"{t.名} → {t.类名}：构造失败 {type(异常).__name__}: {异常}")


def 检查校验器() -> None:
    明细.append("\n【④ 校验器：坏命令必须被挡、好命令必须放行】")
    import 契约
    用例 = [
        # (主题, 负载, 期望通过, 说明)
        ("命令.重力", {"重力开": True}, True, "合法布尔"),
        ("命令.重力", {"重力开": "yes"}, False, "字符串冒充布尔"),
        ("命令.重力", {"重力开": 1}, False, "数字冒充布尔（Python 里 1 == True，必须拦住）"),
        ("命令.重力", {"重力开": True, "乱写": 1}, False, "多余字段"),
        ("命令.重力", {}, True, "缺省字段交给 dataclass 默认值"),
        ("命令.换模型", {"路径": "模型/x.xml"}, True, "只给必填"),
        ("命令.换模型", {"路径": 123}, False, "路径给了数字"),
        ("命令.辨识", {"动作": "开始", "时长": 10}, True, "合法"),
        ("命令.辨识", {"动作": "起飞"}, False, "枚举外取值"),
        ("命令.辨识", {"动作": "开始", "时长": 0}, False, "时长超范围（<0.1）"),
        ("命令.录制", {"动作": "回放", "频率": 100}, True, "合法"),
        ("命令.录制", {"动作": "停止", "频率": 0.5}, False, "频率超范围（<1）"),
        ("指标", {"数值": {}}, False, "下行主题不能当命令发"),
        ("命令.不存在", {}, False, "未登记主题"),
        ("命令.重力", "不是对象", False, "负载不是对象"),
    ]
    for 主题, 负载, 期望, 说明 in 用例:
        通过否, _ = 契约.校验(主题, 负载)
        判(通过否 == 期望, f"{'放行' if 期望 else '拦住'}：{说明}")


def 检查主题白名单与契约同源() -> None:
    明细.append("\n【⑤ 通道白名单必须从契约派生（不许有幽灵条目）】")
    import importlib
    import 契约
    桥 = importlib.import_module("Web桥")
    契约类名 = {t.类名 for t in 契约.下行主题}
    白名单 = set(桥.主题白名单)
    幽灵 = 白名单 - 契约类名
    漏掉 = 契约类名 - 白名单
    判(not 幽灵, f"白名单没有契约外的幽灵条目" + (f"（多出：{幽灵}）" if 幽灵 else ""))
    判(not 漏掉, f"契约里登记的下行主题都在白名单里" + (f"（漏掉：{漏掉}）" if 漏掉 else ""))


def 检查桥模块的消息都已登记() -> None:
    明细.append("\n【⑥ 桥模块里定义的消息是否都登记进契约】")
    import ast
    import glob
    import os

    import 契约

    已登记类名 = {t.类名 for t in (契约.下行主题 + 契约.上行主题)}
    # 明确**不参与** Web 契约的内部消息（每条都要写清为什么不参与，
    # 否则这个白名单迟早变成"什么都往里塞"的垃圾桶）。
    内部消息 = {
        "面板目标消息":
            "viewer→sim 的滑杆目标（官方窗口内部用）。"
            "Web 界面改参数走 `命令.改参数`，不走这条，所以它不该进契约。",
    }
    # ★ 用文件顶部算好的 `软件目录`。我第一版这里又算了一遍，还少了一层
    #   （`工具/验证` → `工具`），于是 glob 到空目录、扫了 0 个类、"全部通过" ——
    #   **一个什么都不查的检查比没有检查更糟**：它会给你一个假的绿灯。
    漏 = []
    扫过 = 0
    for 路径 in sorted(glob.glob(os.path.join(软件目录, "*.py"))):
        try:
            树 = ast.parse(open(路径, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for 节点 in ast.walk(树):
            if not isinstance(节点, ast.ClassDef):
                continue
            基 = [getattr(b, "id", getattr(b, "attr", "")) for b in 节点.bases]
            if not any(x in ("Snapshot", "Message") for x in 基):
                continue
            扫过 += 1
            if 节点.name in 内部消息:
                continue
            if 节点.name not in 已登记类名:
                漏.append(f"{os.path.basename(路径)}: class {节点.name}")
    判(not 漏,
       f"扫了 {扫过} 个消息类，全部在契约里登记"
       if not 漏 else "有消息类没登记进契约（发不出去）：" + "；".join(漏))


def 检查版本号与变更记录一致() -> None:
    明细.append("\n【⑦ 契约版本号与变更记录】")
    import re

    import 契约

    源 = open(契约.__file__, encoding="utf-8").read()
    声明 = re.search(r"^版本 = (\d+)$", 源, re.M)
    if 声明 is None:
        判(False, "契约.py 里找不到 `版本 = N`")
        return
    声明版本 = int(声明.group(1))
    判(声明版本 == 契约.版本, f"契约.版本 = {契约.版本}（与文件里的声明一致）"
       if 声明版本 == 契约.版本 else f"契约.py 里写 {声明版本}，运行时是 {契约.版本}")

    # 版本注释清单的最后一条，必须等于当前版本。
    # ★ 为什么查这个：`版本` 是前端判断"要不要提示刷新"的唯一依据。
    #   加了字段忘了升版本 → 前端不刷新、类型对不上；
    #   升了版本没写注释 → 下次没人知道为什么升。
    #   这两种都**不会报错**，只会悄悄漂移（我真踩过：加了两条主题、版本还停在 4）。
    号们 = [int(x) for x in re.findall(r"^#\s+(\d+)（", 源, re.M)]
    if not 号们:
        判(False, "契约.py 的版本注释里一条编号都没有")
        return
    最大 = max(号们)
    判(最大 == 契约.版本,
       f"变更记录到第 {最大} 条，与版本 {契约.版本} 一致"
       if 最大 == 契约.版本
       else f"变更记录最后一条是 {最大}，但版本是 {契约.版本} —— 加了主题没升版本，或升了没记录")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--简", action="store_true", help="只打结论")
    args = ap.parse_args()

    if not args.简:
        print("=" * 74)
        print("  契约自检（P1 · L0 层）")
        print("=" * 74)

    检查契约与代码一致()
    检查生成物()
    检查上行命令能落地()
    检查校验器()
    检查主题白名单与契约同源()
    检查桥模块的消息都已登记()     # ★ 反向检查：该登记却没登记的
    检查版本号与变更记录一致()

    if not args.简:
        print("\n".join(明细))
    print()
    print("=" * 74)
    print(f"  结果：{通过} 通过 / {失败} 失败")
    print("=" * 74)
    if 失败:
        print("  失败项：")
        for 行 in 明细:
            if "✗" in 行:
                print(f"  {行.strip()}")
    return 1 if 失败 else 0


if __name__ == "__main__":
    raise SystemExit(main())


# ---------------------------------------------------------------------------
# ⑥ 反向检查：每个桥模块里定义的 Snapshot/命令类，都必须在契约里登记
# ---------------------------------------------------------------------------
# ★ 为什么需要这条（不是理论，是我真踩了）：
#   给「诊断」加主题时，我那个改文件的脚本在**第二个断言**处就抛异常了 ——
#   于是 `write_text` 根本没执行，契约里其实没加。
#   而当时 `契约自检` 报的是「26 通过 / 0 失败」——因为它检查的是
#   "**已登记**的主题对不对"，发现不了"**该登记却没登记**"。
#   结果：消息类写好了、处理器也接上了，但 Web 白名单里没有它 → 页面上永远不出现，
#   排查时还以为是发送端坏了（白花了不少时间）。
#
#   这条检查反过来看：扫 软件/*桥.py，找出所有 `messages.Snapshot`（及 messages.Message）
#   的子类，逐个核对"类名是否在契约里出现过"。漏登记立刻报出来。
