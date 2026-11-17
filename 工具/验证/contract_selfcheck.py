"""
contract_selfcheck.py —— P1 的 L0 层"可机检的不变量"

它检查什么（三类，都是"会静默出错"的地方）：
    ① **契约 vs 真实 dataclass**：`contract.py` 是手写的，手写就会漂移。
       字段名/顺序/数量不一致时，前端的类型定义会与后端实际发出的东西对不上，
       而**运行期不会报错** —— 只是某个字段永远显示不出来。
    ② **生成物是否过期**：`frontend/src/generated/contract.ts`、`theme.css`、`themes.ts`
       是从 `contract.py` 与 `风格表.json` 生成的。来源改了没重新生成 = 前端拿旧契约解析新数据。
    ③ **上行命令是否真的能落地**：每条登记的上行命令都要能构造出对应的消息类，
       否则"契约里有、实际发不出去"。

用法：
    .venv/bin/python 工具/验证/contract_selfcheck.py          # 跑全部检查
    .venv/bin/python 工具/验证/contract_selfcheck.py --简      # 只打结论
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
SOFTWARE_DIR = os.path.join(PACKAGE_ROOT, "软件")
FIXTURE_DIR = os.path.join(SCRIPT_DIR, "夹具")
if SOFTWARE_DIR not in sys.path:
    sys.path.insert(0, SOFTWARE_DIR)

passed = 0
failed = 0
details: list[str] = []


def check(condition: bool, description: str) -> bool:
    global passed, failed
    if condition:
        passed += 1
        details.append(f"  ✓ {description}")
    else:
        failed += 1
        details.append(f"  ✗ {description}")
    return condition


def check_contract_definitions() -> None:
    import contract
    details.append("\n【① 契约 vs 真实 dataclass】")
    issues = contract.find_drift()
    check(not issues, f'登记了 {len(contract.ALL_TOPICS)} 个主题（下行 {len(contract.OUTBOUND_TOPICS)} / '
                f'上行 {len(contract.INBOUND_TOPICS)}），字段与 dataclass 逐项一致')
    for p in issues:
        details.append(f"      · {p}")


def check_generated_assets() -> None:
    details.append("\n【② 生成物是否过期】")
    script = os.path.join(PACKAGE_ROOT, "工具", "generate_frontend_assets.py")
    result = subprocess.run([sys.executable, "-X", "utf8", script, "--check"],
                          capture_output=True, encoding="utf-8")
    check(result.returncode == 0,
      "前端生成物（contract.ts / theme.css / themes.ts）与来源一致")
    if result.returncode != 0:
        for line in result.stdout.strip().splitlines():
            if "✗" in line:
                details.append(f"      {line.strip()}")


def check_command_construction() -> None:
    details.append("\n【③ 上行命令能否真的构造出消息】")
    import importlib
    import contract
    import command_bridge
    for t in contract.INBOUND_TOPICS:
        message_class = command_bridge.get_message_class(t.class_name)                                    # noqa: SLF001
        if message_class is None:
            check(False, f'{t.name} → {t.class_name}：拿不到消息类')
            continue
        # 用契约字段名构造一次（值按类型给最小合法值），确认字段名真的对得上
        payload = {}
        for f in t.fields:
            if f.type == "boolean":
                payload[f.name] = False
            elif f.type == "number":
                payload[f.name] = 1.0
            elif f.type == "string":
                payload[f.name] = "测试"
            elif f.type.endswith("[]"):
                payload[f.name] = []
            else:
                payload[f.name] = {}
        try:
            message_class(**payload)
            check(True, f'{t.name:12} → {t.class_name}（字段名与顺序都对得上）')
        except Exception as exc:                                     # noqa: BLE001
            check(False, f'{t.name} → {t.class_name}：构造失败 {type(exc).__name__}: {exc}')


def check_validator() -> None:
    details.append("\n【④ 校验器：坏命令必须被挡、好命令必须放行】")
    import contract
    cases = [
        # (主题, 负载, 期望通过, 说明)
        ("command.gravity", {"gravity_enabled": True}, True, "合法布尔"),
        ("command.gravity", {"gravity_enabled": "yes"}, False, "字符串冒充布尔"),
        ("command.gravity", {"gravity_enabled": 1}, False, "数字冒充布尔（Python 里 1 == True，必须拦住）"),
        ("command.gravity", {"gravity_enabled": True, "乱写": 1}, False, "多余字段"),
        ("command.gravity", {}, True, "缺省字段交给 dataclass 默认值"),
        ("command.simulation", {"action": "pause"}, True, "合法仿真控制动作"),
        ("command.simulation", {"action": "reverse"}, False, "非法仿真控制动作"),
        ("command.model", {"path": "模型/x.xml"}, True, "只给必填"),
        ("command.model", {"path": 123}, False, "路径给了数字"),
        ("命令.辨识", {"动作": "开始", "时长": 10}, True, "合法"),
        ("命令.辨识", {"动作": "起飞"}, False, "枚举外取值"),
        ("命令.辨识", {"动作": "开始", "时长": 0}, False, "时长超范围（<0.1）"),
        ("命令.录制", {"动作": "回放", "频率": 100}, True, "合法"),
        ("命令.录制", {"动作": "停止", "频率": 0.5}, False, "频率超范围（<1）"),
        ("指标", {"数值": {}}, False, "下行主题不能当命令发"),
        ("命令.不存在", {}, False, "未登记主题"),
        ("command.gravity", "不是对象", False, "负载不是对象"),
    ]
    for topic, payload, expected, description in cases:
        valid, _ = contract.validate(topic, payload)
        check(valid == expected, f"{'放行' if expected else '拦住'}：{description}")


def check_topic_allowlist() -> None:
    details.append("\n【⑤ 通道白名单必须从契约派生（不许有幽灵条目）】")
    import importlib
    import contract
    bridge = importlib.import_module("web_bridge")
    contract_class_names = {t.class_name for t in contract.OUTBOUND_TOPICS}
    allowlist = set(bridge.TOPIC_ALLOWLIST)
    unknown_entries = allowlist - contract_class_names
    missing_entries = contract_class_names - allowlist
    check(not unknown_entries, f"白名单没有契约外的幽灵条目" + (f"（多出：{unknown_entries}）" if unknown_entries else ""))
    check(not missing_entries, f"契约里登记的下行主题都在白名单里" + (f"（漏掉：{missing_entries}）" if missing_entries else ""))


def check_registered_messages() -> None:
    details.append("\n【⑥ 桥模块里定义的消息是否都登记进契约】")
    import ast
    import glob
    import os

    import contract

    registered_class_names = {t.class_name for t in (contract.OUTBOUND_TOPICS + contract.INBOUND_TOPICS)}
    # 明确**不参与** Web 契约的内部消息（每条都要写清为什么不参与，
    # 否则这个白名单迟早变成"什么都往里塞"的垃圾桶）。
    internal_messages = {
        "PanelTargetMessage":
            "viewer→sim 的滑杆目标（官方窗口内部用）。"
            "Web 界面改参数走 `command.parameters`，不走这条，所以它不该进契约。",
    }
    # ★ 用文件顶部算好的 `软件目录`。我第一版这里又算了一遍，还少了一层
    #   （`工具/验证` → `工具`），于是 glob 到空目录、扫了 0 个类、"全部通过" ——
    #   **一个什么都不查的检查比没有检查更糟**：它会给你一个假的绿灯。
    missing = []
    scanned = 0
    for path in sorted(glob.glob(os.path.join(SOFTWARE_DIR, "*.py"))):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError):
            continue
        # English implementation classes may retain a legacy wire name while
        # frontend contract keys are migrated separately.  Modules declare that
        # relationship explicitly instead of hiding it in the validator.
        wire_class_names: dict[str, str] = {}
        for top_level_node in tree.body:
            if not isinstance(top_level_node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = (top_level_node.targets if isinstance(top_level_node, ast.Assign)
                   else [top_level_node.target])
            if not any(isinstance(target, ast.Name) and target.id == "WIRE_CLASS_ALIASES"
                       for target in targets):
                continue
            try:
                value_node = top_level_node.value
                wire_class_names = {
                    str(k): str(v) for k, v in ast.literal_eval(value_node).items()
                }
            except (ValueError, TypeError, AttributeError):
                wire_class_names = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [getattr(b, "id", getattr(b, "attr", "")) for b in node.bases]
            if not any(x in ("Snapshot", "Message") for x in bases):
                continue
            scanned += 1
            wire_class_name = wire_class_names.get(node.name, node.name)
            if wire_class_name in internal_messages:
                continue
            if wire_class_name not in registered_class_names:
                description = (f"{node.name} → {wire_class_name}"
                      if wire_class_name != node.name else node.name)
                missing.append(f"{os.path.basename(path)}: class {description}")
    check(not missing,
       f"扫了 {scanned} 个消息类，全部在契约里登记"
       if not missing else "有消息类没登记进契约（发不出去）：" + "；".join(missing))


def check_version_history() -> None:
    details.append("\n【⑦ 契约版本号与变更记录】")
    import re

    import contract

    source = open(contract.__file__, encoding="utf-8").read()
    declaration = re.search(r"^VERSION = (\d+)$", source, re.M)
    if declaration is None:
        check(False, "contract.py 里找不到 `VERSION = N`")
        return
    declared_version = int(declaration.group(1))
    check(declared_version == contract.VERSION, f'contract.VERSION = {contract.VERSION}（与文件里的声明一致）'
       if declared_version == contract.VERSION else f'contract.py 里写 {declared_version}，运行时是 {contract.VERSION}')

    # 版本注释清单的最后一条，必须等于当前版本。
    # ★ 为什么查这个：`版本` 是前端判断"要不要提示刷新"的唯一依据。
    #   加了字段忘了升版本 → 前端不刷新、类型对不上；
    #   升了版本没写注释 → 下次没人知道为什么升。
    #   这两种都**不会报错**，只会悄悄漂移（我真踩过：加了两条主题、版本还停在 4）。
    versions = [int(x) for x in re.findall(r"^#\s+(\d+)（", source, re.M)]
    if not versions:
        check(False, "contract.py 的版本注释里一条编号都没有")
        return
    maximum = max(versions)
    check(maximum == contract.VERSION,
       f'变更记录到第 {maximum} 条，与版本 {contract.VERSION} 一致'
       if maximum == contract.VERSION
       else f'变更记录最后一条是 {maximum}，但版本是 {contract.VERSION} —— 加了主题没升版本，或升了没记录')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", "--简", dest="brief", action="store_true", help="只打结论")
    args = ap.parse_args()

    if not args.brief:
        print("=" * 74)
        print("  契约自检（P1 · L0 层）")
        print("=" * 74)

    check_contract_definitions()
    check_generated_assets()
    check_command_construction()
    check_validator()
    check_topic_allowlist()
    check_registered_messages()     # ★ 反向检查：该登记却没登记的
    check_version_history()

    if not args.brief:
        print("\n".join(details))
    print()
    print("=" * 74)
    print(f"  结果：{passed} 通过 / {failed} 失败")
    print("=" * 74)
    if failed:
        print("  失败项：")
        for line in details:
            if "✗" in line:
                print(f"  {line.strip()}")
    return 1 if failed else 0


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
