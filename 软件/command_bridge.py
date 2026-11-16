"""
command_bridge.py —— 把 Web 界面发来的命令送进官方消息通道（P1 的上行那一半）

它解决什么问题：
    P0 只做了下行（仿真 → 浏览器）。界面要真的能用，必须有上行：切模型、换算法、
    开物理、开始辨识、开始录制… 而官方通道的方向是从**界面侧**往仿真侧发的
    （`viewer.send_to_sim(...)`）——也就是说：

        只有持有官方端点的那个线程（界面/绘制线程）才能发命令。

    网络线程直接发 = 跨线程改状态，正是本项目一直在避免的那类问题
    （见 `runtime_engine.py` 顶部关于线程排法的说明）。所以链路做成：

        Web 客户端 ──► WebSocket 线程：只做「契约校验 + 入队」
                              ↓
        viewer 每帧 ──► 本模块.转发待发命令(viewer)：取走 → 构消息 → send_to_sim

    ★ 为什么每帧的钩子挂在 `界面桥._每帧发目标` 里，而不新写一个 viewer 插件：
      那个方法**已经**是"每帧、在 viewer 线程、手里有 viewer"的现成接缝
      （它本来在转发 Controls 滑杆值）。复用它 = 不新增线程、不改仿真循环、
      不需要动 `制作窗口类` 的类继承。一行调用就接上了，拆掉也只需删那一行。

安全纪律（为什么命令要单独一套规矩）：
    下行数据错了最多是"显示不对"；上行命令错了是"让机器人做别的事"。所以：
      ① **白名单**：只有 `contract.py` 里登记过的上行主题能进来（在 `Web桥` 就拦掉）；
      ② **逐条校验**：类型 + 枚举 + 数值范围（`contract.validate`）；
      ③ **回执**：每条命令都回一条 `__回执__`，前端不必靠猜；
      ④ **有界队列**：界面线程卡住时丢命令，而不是无限占内存。
"""
from __future__ import annotations

import importlib
import os
import sys
from typing import Any

_runtime_directory = os.path.dirname(os.path.abspath(__file__))
if _runtime_directory not in sys.path:
    sys.path.insert(0, _runtime_directory)

import contract as _contract                                                      # noqa: E402

# 主题名（契约里的上行主题名）→ 到哪个模块拿对应的消息类。
#   ★ 与 `contract.find_drift()` 里那张表是同一份知识，所以两边都只登记"类名 → 模块"，
#     新增一条上行命令时只改 `contract.py`，本文件自动跟上（`contract.BY_CLASS_NAME` 提供映射）。
SOURCE_MODULES = {
    "GravityState": "simulation_control",
    "SimulationControlCommand": "simulation_control",
    "ExperimentCommand": "experiment_bridge",
    "ControlTargetCommand": "control_bridge",
    "ParameterUpdate": "parameter_bridge",
    "SwitchModelCommand": "model_bridge",
    "ApplyAlgorithmsCommand": "model_bridge",
    "辨识命令": "identification_bridge",
    "录制命令": "recording_bridge",
    "诊断命令": "diagnostics_bridge",
    "高亮命令": "highlight_bridge",
    "部署命令": "deployment_bridge",
    "PlanningCommand": "planning_bridge",
    "ParameterTransactionCommand": "parameter_bridge",
    "连接命令": "devices.connection_bridge",
}

# 记账（状态接口里能看到；用模块级变量，避免为了统计去建对象）
forwarded_count = 0
failure_count = 0


def get_message_class(class_name: str):
    module_name = SOURCE_MODULES.get(class_name)
    if module_name is None:
        return None
    try:
        from wire_compatibility import resolve_wire_class
        return resolve_wire_class(importlib.import_module(module_name), class_name)
    except Exception:                                                 # noqa: BLE001
        return None


def create_message(topic_name: str, payload: dict):
    """把一条契约命令造成对应的官方消息对象。失败返回 (None, 原因)。

    ★ 有窗与无窗**共用这一个函数**：造消息是纯数据的事情，与通道无关。
      分开写两份的话，"契约里加了字段、只有一边跟上"这种漂移迟早会发生。
    """
    topic = _contract.get_topic(topic_name)
    if topic is None or topic.direction != "上行":
        return None, f'不是登记过的上行命令：{topic_name}'
    message_class = get_message_class(topic.class_name)
    if message_class is None:
        return None, f'找不到消息类 {topic.class_name}（源模块表要更新）'
    known_fields = {f.name for f in topic.fields}
    arguments = {k: v for k, v in payload.items() if k in known_fields}
    try:
        return message_class(**arguments), ""
    except Exception as exc:                                         # noqa: BLE001
        return None, f'构造 {topic.class_name} 失败：{type(exc).__name__}: {exc}'


def _put_message(queue: Any, message: Any) -> None:
    """同时兼容线程安全 Queue 和旧的 list 调用方。"""
    put = getattr(queue, "put_nowait", None)
    if callable(put):
        put(message)
        return
    queue.append(message)


def enqueue_command(queue: Any, topic_name: str, payload: dict,
             print_result: bool = True) -> tuple[bool, str]:
    """**无窗模式**的命令注入：把 Web 命令造好后放进仿真循环的收件队列。

    ★ 为什么无窗模式是这个形状：
      有窗时"发命令"必须由 viewer 线程做（只有它持有官方端点），
      所以走 `转发待发命令(viewer)`。无窗之后窗口没了、也没有那个线程，
      浏览器入口下仿真可在主线程，桌面宿主下仿真在后台线程；两种形态都把消息
      放进循环每圈排空的同一个队列。桌面宿主使用标准库 Queue 保证跨线程安全。
    """
    global forwarded_count, failure_count
    message, reason = create_message(topic_name, payload)
    if message is None:
        failure_count += 1
        if print_result:
            print(f'【Web命令】✗ {reason}', flush=True)
        return False, reason
    _put_message(queue, message)
    _sync_ui_state(topic_name, payload)
    forwarded_count += 1
    if print_result:
        print(f'【Web命令】✓ 已入队 {topic_name}', flush=True)
    return True, "ok"


def drain_and_inject(queue: Any, print_result: bool = True) -> int:
    """无窗模式的每圈调用：把 Web 收到、还没入队的命令转进本地 `队列`。

    与 `转发待发命令` 的唯一区别是"往哪儿放"：这里放本地队列，那里调 `send_to_sim`。
    校验、造消息、状态同步三件事完全共用。
    """
    try:
        import web_bridge as _web_bridge
    except Exception:                                                 # noqa: BLE001
        return 0
    pending = _web_bridge.get_commands()
    if not pending:
        return 0
    success_count = 0
    for topic_name, payload in pending:
        success, _ = enqueue_command(queue, topic_name, payload, print_result=print_result)
        if success:
            success_count += 1
    if success_count:
        try:
            _web_bridge.record_dispatch(success_count)
        except Exception:                                             # noqa: BLE001
            pass
    return success_count


def _sync_ui_state(topic_name: str, payload: dict) -> None:
    """有些命令会**改写"界面侧那份共享状态"**，必须同步，否则会被界面顶回去。

    ★ 这不是可选的收尾工作，而是踩出来的坑。以重力开关为例：
      它是"界面是真相源"的设计 —— 展示面板 **每帧（10 Hz）**都会把
      `simulation_control.UI_GRAVITY_ENABLED` 这份共享状态发给仿真侧。
      于是：Web 命令把仿真侧设成"开" → 下一帧界面就把"关"重新盖上 →
      **物理又被冻回去**。实测现象就是"命令回执说转发成功，但仿真时间不推进"。

      正确做法与那个面板手动点击时**完全一致**：先改共享状态，再让它自己发出去
      （`展示面板.py:147` 就是这个顺序）。这样两个入口不可能互相顶掉，
      而且界面上那个勾选框会**可见地**跟着变 —— 用户不会遇到"我没点它却自己变了"。

      为什么这个知识放这里：契约把 `命令.重力` 登记为"界面→仿真"，但真正的事实是
      **它是两处状态的一次同步**。把这个不对称性写在一个地方，比让每个调用方自己记得更可靠。
    """
    if topic_name == "command.gravity":
        try:
            import simulation_control
            simulation_control.set_ui_gravity(bool(payload.get("gravity_enabled", False)))
        except Exception:                                             # noqa: BLE001
            pass


def forward_pending_commands(viewer: Any, print_result: bool = True) -> int:
    """取走 Web 来的命令并注入官方通道。返回本次成功转发的条数。

    ★ 必须在 viewer 线程每帧调用一次（`界面桥._每帧发目标` 里已接好）。
      没有队列时它只做一次 `Web桥.取命令()`，那是个加锁取空表的操作，代价可忽略。
    """
    global forwarded_count, failure_count
    if viewer is None:
        return 0
    try:
        import web_bridge as _web_bridge
    except Exception:                                                 # noqa: BLE001
        return 0

    pending = _web_bridge.get_commands()
    if not pending:
        return 0

    success_count = 0
    for topic_name, payload in pending:
        topic = _contract.get_topic(topic_name)
        if topic is None or topic.direction != "上行":
            failure_count += 1
            if print_result:
                print(f'【Web命令】✗ 不是登记过的上行命令：{topic_name}', flush=True)
            continue
        message_class = get_message_class(topic.class_name)
        if message_class is None:
            failure_count += 1
            if print_result:
                print(f'【Web命令】✗ 找不到消息类 {topic.class_name}（源模块表要更新）', flush=True)
            continue
        # 二次保险：只传契约登记过的字段（`Web桥` 已经拒过多余字段）
        known_fields = {f.name for f in topic.fields}
        arguments = {k: v for k, v in payload.items() if k in known_fields}
        try:
            message = message_class(**arguments)
        except Exception as exc:                                     # noqa: BLE001
            failure_count += 1
            if print_result:
                print(f'【Web命令】✗ 构造 {topic.class_name} 失败：{type(exc).__name__}: {exc}',
                      flush=True)
            continue
        try:
            viewer.send_to_sim(message)
        except Exception as exc:                                     # noqa: BLE001
            failure_count += 1
            if print_result:
                print(f'【Web命令】✗ 发送失败：{type(exc).__name__}: {exc}', flush=True)
            continue
        # ★ 发出去之后同步"界面侧共享状态"，否则界面下一帧会把它顶回来
        _sync_ui_state(topic_name, arguments)
        success_count += 1
        forwarded_count += 1
        if print_result:
            print(f'【Web命令】✓ 已转发 {topic_name} {arguments}', flush=True)

    if success_count:
        try:
            _web_bridge.record_dispatch(success_count)
        except Exception:                                             # noqa: BLE001
            pass
    return success_count


def status() -> dict:
    return {"已转发": forwarded_count, "失败": failure_count}


__all__ = ["create_message", "enqueue_command", "drain_and_inject", "forward_pending_commands", "status"]


if __name__ == "__main__":       # 自检：只验证"契约→消息类"这条映射是通的
    print("=" * 72)
    print("  命令桥 自检（主题 → 消息类）")
    print("=" * 72)
    failure_total = 0
    for t in _contract.INBOUND_TOPICS:
        message_class = get_message_class(t.class_name)
        if message_class is None:
            print(f'  ✗ {t.name:12} → {t.class_name} 拿不到（源模块表缺 {t.class_name}）')
            failure_total += 1
            continue
        # 用契约字段名的空值试构造一次，确认字段名真的对得上
        sample = {f.name: (False if f.type == "boolean" else
                    0.0 if f.type == "number" else
                    "" if f.type == "string" else
                    [] if f.type.endswith("[]") else {})
              for f in t.fields}
        try:
            message_class(**sample)
            result = "✓"
        except Exception as exc:                                     # noqa: BLE001
            result = f'✗ {type(exc).__name__}: {exc}'
            failure_total += 1
        print(f'  {result} {t.name:12} → {t.class_name}')
    print(f"\n  结论：{('✓ 全部对得上' if failure_total == 0 else f'✗ {failure_total} 处对不上')}")
    raise SystemExit(1 if failure_total else 0)
