"""
命令桥.py —— 把 Web 界面发来的命令送进官方消息通道（P1 的上行那一半）

它解决什么问题：
    P0 只做了下行（仿真 → 浏览器）。界面要真的能用，必须有上行：切模型、换算法、
    开物理、开始辨识、开始录制… 而官方通道的方向是从**界面侧**往仿真侧发的
    （`viewer.send_to_sim(...)`）——也就是说：

        只有持有官方端点的那个线程（界面/绘制线程）才能发命令。

    网络线程直接发 = 跨线程改状态，正是本项目一直在避免的那类问题
    （见 `启动.py` 顶部关于线程排法的说明）。所以链路做成：

        Web 客户端 ──► WebSocket 线程：只做「契约校验 + 入队」
                              ↓
        viewer 每帧 ──► 本模块.转发待发命令(viewer)：取走 → 构消息 → send_to_sim

    ★ 为什么每帧的钩子挂在 `界面桥._每帧发目标` 里，而不新写一个 viewer 插件：
      那个方法**已经**是"每帧、在 viewer 线程、手里有 viewer"的现成接缝
      （它本来在转发 Controls 滑杆值）。复用它 = 不新增线程、不改仿真循环、
      不需要动 `制作窗口类` 的类继承。一行调用就接上了，拆掉也只需删那一行。

安全纪律（为什么命令要单独一套规矩）：
    下行数据错了最多是"显示不对"；上行命令错了是"让机器人做别的事"。所以：
      ① **白名单**：只有 `契约.py` 里登记过的上行主题能进来（在 `Web桥` 就拦掉）；
      ② **逐条校验**：类型 + 枚举 + 数值范围（`契约.校验`）；
      ③ **回执**：每条命令都回一条 `__回执__`，前端不必靠猜；
      ④ **有界队列**：界面线程卡住时丢命令，而不是无限占内存。
"""
from __future__ import annotations

import importlib
import os
import sys
from typing import Any

_软件目录 = os.path.dirname(os.path.abspath(__file__))
if _软件目录 not in sys.path:
    sys.path.insert(0, _软件目录)

import 契约 as _契约                                                      # noqa: E402

# 主题名（契约里的上行主题名）→ 到哪个模块拿对应的消息类。
#   ★ 与 `契约.查漂移()` 里那张表是同一份知识，所以两边都只登记"类名 → 模块"，
#     新增一条上行命令时只改 `契约.py`，本文件自动跟上（`契约.按类名` 提供映射）。
源模块 = {
    "重力状态": "重力桥",
    "参数消息": "参数桥",
    "换模型命令": "模型桥",
    "应用算法命令": "模型桥",
    "辨识命令": "辨识桥",
    "录制命令": "录制桥",
}

# 记账（状态接口里能看到；用模块级变量，避免为了统计去建对象）
已转发 = 0
失败 = 0


def _取消息类(类名: str):
    模块名 = 源模块.get(类名)
    if 模块名 is None:
        return None
    try:
        return getattr(importlib.import_module(模块名), 类名)
    except Exception:                                                 # noqa: BLE001
        return None


def 造消息(主题名: str, 负载: dict):
    """把一条契约命令造成对应的官方消息对象。失败返回 (None, 原因)。

    ★ 有窗与无窗**共用这一个函数**：造消息是纯数据的事情，与通道无关。
      分开写两份的话，"契约里加了字段、只有一边跟上"这种漂移迟早会发生。
    """
    主题 = _契约.取(主题名)
    if 主题 is None or 主题.方向 != "上行":
        return None, f"不是登记过的上行命令：{主题名}"
    类 = _取消息类(主题.类名)
    if 类 is None:
        return None, f"找不到消息类 {主题.类名}（源模块表要更新）"
    已知 = {f.名 for f in 主题.字段}
    实参 = {k: v for k, v in 负载.items() if k in 已知}
    try:
        return 类(**实参), ""
    except Exception as 异常:                                         # noqa: BLE001
        return None, f"构造 {主题.类名} 失败：{type(异常).__name__}: {异常}"


def 命令入队(队列: list, 主题名: str, 负载: dict,
             打印: bool = True) -> tuple[bool, str]:
    """**无窗模式**的命令注入：把 Web 命令造好后放进仿真循环的收件队列。

    ★ 为什么无窗模式是这个形状：
      有窗时"发命令"必须由 viewer 线程做（只有它持有官方端点），
      所以走 `转发待发命令(viewer)`。无窗之后窗口没了、也没有那个线程，
      仿真就坐在主线程上 —— 于是**没有跨线程问题**，直接把消息放进
      循环每圈都会排空的那个队列即可，与"界面自己发的消息"是同一条路。
    """
    global 已转发, 失败
    消息, 原因 = 造消息(主题名, 负载)
    if 消息 is None:
        失败 += 1
        if 打印:
            print(f"【Web命令】✗ {原因}", flush=True)
        return False, 原因
    队列.append(消息)
    _同步界面侧共享状态(主题名, 负载)
    已转发 += 1
    if 打印:
        print(f"【Web命令】✓ 已入队 {主题名}", flush=True)
    return True, "ok"


def 排空并注入(队列: list, 打印: bool = True) -> int:
    """无窗模式的每圈调用：把 Web 收到、还没入队的命令转进本地 `队列`。

    与 `转发待发命令` 的唯一区别是"往哪儿放"：这里放本地队列，那里调 `send_to_sim`。
    校验、造消息、状态同步三件事完全共用。
    """
    try:
        import Web桥 as _Web桥
    except Exception:                                                 # noqa: BLE001
        return 0
    待发 = _Web桥.取命令()
    if not 待发:
        return 0
    成功 = 0
    for 主题名, 负载 in 待发:
        好, _ = 命令入队(队列, 主题名, 负载, 打印=打印)
        if 好:
            成功 += 1
    if 成功:
        try:
            _Web桥.记派发(成功)
        except Exception:                                             # noqa: BLE001
            pass
    return 成功


def _同步界面侧共享状态(主题名: str, 负载: dict) -> None:
    """有些命令会**改写"界面侧那份共享状态"**，必须同步，否则会被界面顶回去。

    ★ 这不是可选的收尾工作，而是踩出来的坑。以重力开关为例：
      它是"界面是真相源"的设计 —— 展示面板 **每帧（10 Hz）**都会把
      `重力桥.界面重力开` 这份共享状态发给仿真侧（见 `重力桥.发布器.也许发布共享`）。
      于是：Web 命令把仿真侧设成"开" → 下一帧界面就把"关"重新盖上 →
      **物理又被冻回去**。实测现象就是"命令回执说转发成功，但仿真时间不推进"。

      正确做法与那个面板手动点击时**完全一致**：先改共享状态，再让它自己发出去
      （`展示面板.py:147` 就是这个顺序）。这样两个入口不可能互相顶掉，
      而且界面上那个勾选框会**可见地**跟着变 —— 用户不会遇到"我没点它却自己变了"。

      为什么这个知识放这里：契约把 `命令.重力` 登记为"界面→仿真"，但真正的事实是
      **它是两处状态的一次同步**。把这个不对称性写在一个地方，比让每个调用方自己记得更可靠。
    """
    if 主题名 == "命令.重力":
        try:
            import 重力桥
            重力桥.设界面重力(bool(负载.get("重力开", False)))
        except Exception:                                             # noqa: BLE001
            pass


def 转发待发命令(viewer: Any, 打印: bool = True) -> int:
    """取走 Web 来的命令并注入官方通道。返回本次成功转发的条数。

    ★ 必须在 viewer 线程每帧调用一次（`界面桥._每帧发目标` 里已接好）。
      没有队列时它只做一次 `Web桥.取命令()`，那是个加锁取空表的操作，代价可忽略。
    """
    global 已转发, 失败
    if viewer is None:
        return 0
    try:
        import Web桥 as _Web桥
    except Exception:                                                 # noqa: BLE001
        return 0

    待发 = _Web桥.取命令()
    if not 待发:
        return 0

    成功 = 0
    for 主题名, 负载 in 待发:
        主题 = _契约.取(主题名)
        if 主题 is None or 主题.方向 != "上行":
            失败 += 1
            if 打印:
                print(f"【Web命令】✗ 不是登记过的上行命令：{主题名}", flush=True)
            continue
        类 = _取消息类(主题.类名)
        if 类 is None:
            失败 += 1
            if 打印:
                print(f"【Web命令】✗ 找不到消息类 {主题.类名}（源模块表要更新）", flush=True)
            continue
        # 二次保险：只传契约登记过的字段（`Web桥` 已经拒过多余字段）
        已知 = {f.名 for f in 主题.字段}
        实参 = {k: v for k, v in 负载.items() if k in 已知}
        try:
            消息 = 类(**实参)
        except Exception as 异常:                                     # noqa: BLE001
            失败 += 1
            if 打印:
                print(f"【Web命令】✗ 构造 {主题.类名} 失败：{type(异常).__name__}: {异常}",
                      flush=True)
            continue
        try:
            viewer.send_to_sim(消息)
        except Exception as 异常:                                     # noqa: BLE001
            失败 += 1
            if 打印:
                print(f"【Web命令】✗ 发送失败：{type(异常).__name__}: {异常}", flush=True)
            continue
        # ★ 发出去之后同步"界面侧共享状态"，否则界面下一帧会把它顶回来
        _同步界面侧共享状态(主题名, 实参)
        成功 += 1
        已转发 += 1
        if 打印:
            print(f"【Web命令】✓ 已转发 {主题名} {实参}", flush=True)

    if 成功:
        try:
            _Web桥.记派发(成功)
        except Exception:                                             # noqa: BLE001
            pass
    return 成功


def 状态() -> dict:
    return {"已转发": 已转发, "失败": 失败}


if __name__ == "__main__":       # 自检：只验证"契约→消息类"这条映射是通的
    print("=" * 72)
    print("  命令桥 自检（主题 → 消息类）")
    print("=" * 72)
    坏 = 0
    for t in _契约.上行主题:
        类 = _取消息类(t.类名)
        if 类 is None:
            print(f"  ✗ {t.名:12} → {t.类名} 拿不到（源模块表缺 {t.类名}）")
            坏 += 1
            continue
        # 用契约字段名的空值试构造一次，确认字段名真的对得上
        试 = {f.名: (False if f.类型 == "boolean" else
                    0.0 if f.类型 == "number" else
                    "" if f.类型 == "string" else
                    [] if f.类型.endswith("[]") else {})
              for f in t.字段}
        try:
            类(**试)
            结果 = "✓"
        except Exception as 异常:                                     # noqa: BLE001
            结果 = f"✗ {type(异常).__name__}: {异常}"
            坏 += 1
        print(f"  {结果} {t.名:12} → {t.类名}")
    print(f"\n  结论：{'✓ 全部对得上' if 坏 == 0 else f'✗ {坏} 处对不上'}")
    raise SystemExit(1 if 坏 else 0)
