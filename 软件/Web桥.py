"""
Web桥.py —— 把仿真侧的消息开第二个出口：WebSocket + JSON（方案 B 的 P0）

它解决什么问题：
    现在仿真侧的全部状态只有一个消费者 —— 官方 ImGui 绘制层（C++ 编译进去的），
    所以界面长什么样、能不能加图表、能不能重排成任务流，全被那一层锁死。
    `LoongEnv对比与驭臂自检报告.md` §A.2 的取证结论是：
    **数据层已经天然无界面耦合**（7 个桥产出的都是纯 dataclass），
    所以正确的做法不是重写下面那层，而是**给上面那层再开一个出口**。

    本模块就是那个出口。它不改变任何现有行为：
    官方面板照旧收到消息，Web 只是"多一个订阅者"。

设计约束（为什么这么写）：
    ① **不许拖慢物理**。仿真循环是 ~500 Hz 的热路径，而纯 Python 忙线程
       会把物理饿死到 ×0.29（`软件/README.md` 性能段实测）。
       所以仿真侧只做一件事：把消息塞进一个**按主题覆盖的字典**（latest-wins），
       不做序列化、不做网络 IO、不建队列。序列化与广播全在独立线程里。
    ② **不许拖垮软件**。端口被占、库缺失、客户端乱发 —— 任何失败都只打一行字，
       界面与仿真继续跑。`启动.py` 里整个接入点包在 try 里。
    ③ **latest-wins 是官方语义**。`messages.Snapshot` 的 docstring 就写着
       "Intermediate values may be silently dropped" —— 正好是喂外部界面要的语义，
       不必自己造。所以这里也用"同主题新消息覆盖旧消息"，不做可靠投递。
    ④ **只监听本机**。默认 127.0.0.1，不对外开。

数据流：
    仿真线程                          广播线程                   浏览器
    ─────────                        ─────────                 ──────
    投递(主题, 消息) ──► 待发布{主题:消息} ──► JSON ──► WebSocket ──► 前端
                        （覆盖，不加锁阻塞）

用法（现在就能用，不用等界面改造）：
    .venv/bin/python 软件/主程序.py                 # 照常开窗口
    浏览器打开 http://127.0.0.1:8712/               # 看真实指标流

    换端口：--web口 8899    关掉：--无web
"""
from __future__ import annotations

import dataclasses
import json
import os
import threading
import time
from typing import Any

# ---- 接口常量 ----
# ★ 协议版本**等于契约版本**，不再单独维护一个数字。
#   理由：改动线上格式时两件事总是一起变；维护两个版本号只会出现
#   "契约 bump 了、协议忘了 bump" —— 前端版本守卫放行，然后拿新契约解析旧数据。
#   实测踩过：加了 `命令.改参数`（契约 1→2）却没改这里，前端正确地拒绝了连接，
#   页面上什么都没有 —— 守卫本身是对的，错在两个数字各说各话。
try:
    import 契约 as _契约版本源
    协议版本 = _契约版本源.版本
except Exception:                                                     # noqa: BLE001
    协议版本 = 1                      # 契约拿不到时退到一个保守值（前面已警告过）
默认端口 = 8712
默认主机 = "127.0.0.1"

# 广播节拍：50 ms = 20 Hz。指标本身是 30 Hz 发的，这里再压一道，
# 避免"客户端一多就把网络线程跑满"。想更密就改这个数。
广播间隔 = 0.05

# 待发布表最多保留的主题数（防御：万一有人用动态主题名灌爆内存）
主题上限 = 200

# 上行命令队列上限。界面线程每帧都取，正常情况恒为空；
# 堆到这个数说明界面线程卡住了，此时**宁可丢命令也不无限占内存**。
命令队列上限 = 256

# 前端静态产物目录（Vite 构建到 `软件/web/`）。
# 没构建过也不影响：回落到 P0 的单文件仪表盘。
前端目录 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# 只认这几种类型 —— 不做"猜测"，避免把奇怪的文件当脚本发给浏览器
_类型表 = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


# ---------------------------------------------------------------------------
# ① 序列化：官方消息是纯 dataclass，直接走 dataclasses.fields
# ---------------------------------------------------------------------------
def 转干净(值: Any, _深度: int = 0) -> Any:
    """把任意对象转成 json.dumps 能吃的东西。

    要处理三类麻烦（都来自实测）：
      · numpy 数组（StateSnapshot.state、qpos 快照都是）→ 列表
        ★ 不能用 `if 值` 判断，numpy 数组的真值判断会抛异常，必须 `is not None`
      · numpy 标量（np.float64 不是 float 的子类之外还有 np.bool_ 等）→ 用 .item()
      · 官方 dataclass 字段里可能有不可序列化的东西（比如 mjModel 句柄）→ 转成占位字符串
    """
    if 值 is None or isinstance(值, (bool, int, float, str)):
        return 值
    if _深度 > 6:                       # 防御：对象图成环
        return "…"
    # numpy 标量：有 .item() 且不是 ndarray 的就是标量（np.float64/np.int32/np.bool_）
    item = getattr(值, "item", None)
    if item is not None and not hasattr(值, "shape"):
        try:
            return 值.item()
        except Exception:                                             # noqa: BLE001
            pass
    # numpy 数组 / 列表 / 元组
    if hasattr(值, "tolist"):
        try:
            return 转干净(值.tolist(), _深度 + 1)
        except Exception:                                             # noqa: BLE001
            pass
    if isinstance(值, dict):
        return {str(k): 转干净(v, _深度 + 1) for k, v in 值.items()}
    if isinstance(值, (list, tuple, set)):
        return [转干净(v, _深度 + 1) for v in 值]
    # dataclass（官方消息、我们自己的桥接消息都是）
    if dataclasses.is_dataclass(值) and not isinstance(值, type):
        try:
            return {
                "类型": type(值).__name__,
                "字段": {f.name: 转干净(getattr(值, f.name, None), _深度 + 1)
                        for f in dataclasses.fields(值)},
            }
        except Exception:                                             # noqa: BLE001
            pass
    # 剩下的一律给个可读占位，绝不抛（宁可少一个字段，也不能让桥把软件弄崩）
    return f"<{type(值).__name__}>"


def 打包(主题: str, 消息: Any, 序号: int) -> str:
    """一帧出网的 JSON 文本。"""
    return json.dumps(
        {
            "协议": 协议版本,
            "主题": 主题,
            "序号": 序号,
            "墙钟": time.time(),
            "数据": 转干净(消息),
        },
        ensure_ascii=False,
        separators=(",", ":"),          # 省带宽：不加空格
        default=str,                    # 兜底，永不让 dumps 抛
    )


# ---------------------------------------------------------------------------
# ② 待发布表：仿真线程只写这里（不做 IO），广播线程只读这里
# ---------------------------------------------------------------------------
class 待发布:
    """按主题"最新覆盖"的消息表。仿真线程调用 `投递()` 必须是廉价的。"""

    def __init__(self) -> None:
        self._锁 = threading.Lock()
        self._表: dict[str, tuple[Any, int]] = {}     # {主题: (消息, 该主题的版本号)}
        self._版本 = 0

    def 投递(self, 主题: str, 消息: Any) -> None:
        with self._锁:
            self._版本 += 1
            if 主题 not in self._表 and len(self._表) >= 主题上限:
                return                                # 防御：不认识的洪水主题直接丢
            self._表[主题] = (消息, self._版本)

    def 取走(self, 已发: dict[str, int]) -> list[tuple[str, Any, int]]:
        """取走"版本号比已发的新"的项，并记住已发版本。"""
        出: list[tuple[str, Any, int]] = []
        with self._锁:
            for 主题, (消息, 版本) in self._表.items():
                if 已发.get(主题) == 版本:
                    continue
                已发[主题] = 版本
                出.append((主题, 消息, 版本))
        return 出

    def 主题们(self) -> list[str]:
        with self._锁:
            return sorted(self._表)


# ---------------------------------------------------------------------------
# ③ 服务端：WebSocket + 静态页，同端口
# ---------------------------------------------------------------------------
class 服务端:
    """一个线程里跑 asyncio 事件循环。任何一步失败都不抛给调用方。"""

    def __init__(self, 主机: str = 默认主机, 端口: int = 默认端口) -> None:
        self.主机, self.端口 = 主机, 端口
        self.待发布 = 待发布()
        self.已发: dict[str, int] = {}
        self.客户端数 = 0
        self.已广播 = 0

        self.已发送字节 = 0
        self.丢弃 = 0
        self.出错 = ""
        self.启用 = False
        self._线程: threading.Thread | None = None
        self._循环 = None
        self._停止 = threading.Event()
        self._客户端: dict[Any, Any] = {}
        # ---- 上行（命令）：网络线程只入队，界面线程取走并注入 ----
        #   ★ 为什么用有界队列而不是"直接执行"：命令必须由**界面线程**注入官方通道
        #     （`send_to_sim` 的调用者必须是持有官方端点的那个线程）。网络线程越界调用
        #     是跨线程改状态，属于本项目一直在避免的那类问题。
        self._命令: list[tuple[str, dict]] = []
        self._命令锁 = threading.Lock()
        self.已收命令 = 0
        self.已派发命令 = 0
        self.拒收 = 0
        self.最近拒收原因 = ""

    # ---- 生命周期 ----
    def 启动(self) -> bool:
        """起服务。返回是否成功（失败只记 self.出错，不抛）。"""
        if self.启用:
            return True
        self._线程 = threading.Thread(target=self._跑, name="Web桥", daemon=True)
        self._线程.start()
        # 等一下下，让"端口被占"这类错误尽早暴露给调用方（不阻塞启动）
        for _ in range(30):
            if self.启用 or self.出错:
                break
            time.sleep(0.02)
        return self.启用

    def 关闭(self) -> None:
        self._停止.set()
        if self._循环 is not None:
            try:
                self._循环.call_soon_threadsafe(self._循环.stop)
            except Exception:                                         # noqa: BLE001
                pass
        self.启用 = False

    def 状态(self) -> dict:
        return {
            "启用": self.启用,
            "地址": f"http://{self.主机}:{self.端口}/" if self.启用 else "",
            "客户端数": self.客户端数,
            "已广播": self.已广播,
            "已发送KB": round(self.已发送字节 / 1024, 1),
            "丢弃": self.丢弃,
            "出错": self.出错,
            "主题": self.待发布.主题们(),
            "已收命令": self.已收命令,
            "已派发命令": self.已派发命令,
            "拒收": self.拒收,
            "最近拒收原因": self.最近拒收原因,
        }

    # ---- 上行：网络线程入队（只有校验通过的命令才进得来）----
    def 收命令(self, 主题名: str, 负载: Any) -> tuple[bool, str]:
        try:
            import 契约 as _契约
        except Exception:                                             # noqa: BLE001
            return False, "契约模块不可用，命令一律拒收"
        通过, 说明 = _契约.校验(主题名, 负载)
        if not 通过:
            self.拒收 += 1
            self.最近拒收原因 = f"{主题名}：{说明}"
            return False, 说明
        with self._命令锁:
            if len(self._命令) >= 命令队列上限:
                self.拒收 += 1
                self.最近拒收原因 = "命令排队过多（界面线程没在消费？）"
                return False, self.最近拒收原因
            self._命令.append((主题名, dict(负载)))
            self.已收命令 += 1
        return True, "ok"

    def 取命令(self) -> list[tuple[str, dict]]:
        """界面线程每帧调一次，取走待派发的命令（取空即返回空表）。"""
        with self._命令锁:
            出, self._命令 = self._命令, []
        return 出

    # ---- 内部：一个线程里跑事件循环 ----
    def _跑(self) -> None:
        try:
            import asyncio
            from websockets.asyncio.server import serve
        except Exception as 异常:                                     # noqa: BLE001
            self.出错 = f"websockets 不可用：{type(异常).__name__}: {异常}"
            return

        async def 主() -> None:
            try:
                服务器 = await serve(
                    self._接入, self.主机, self.端口,
                    process_request=self._静态页,
                    max_size=1 << 20,          # 收 1 MB 上限（上行只有小命令）
                    max_queue=8,               # 客户端慢了就丢帧，不积压
                    ping_interval=20, ping_timeout=20,
                )
            except Exception as 异常:                                 # noqa: BLE001
                self.出错 = f"起服务失败（端口 {self.端口} 可能被占）：{type(异常).__name__}: {异常}"
                return
            self.启用 = True
            广播任务 = asyncio.ensure_future(self._广播循环())
            try:
                await self._等到停止()
            finally:
                广播任务.cancel()
                服务器.close()
                try:
                    await 服务器.wait_closed()
                except Exception:                                     # noqa: BLE001
                    pass

        try:
            self._循环 = asyncio.new_event_loop()
            asyncio.set_event_loop(self._循环)
            self._循环.run_until_complete(主())
        except Exception as 异常:                                     # noqa: BLE001
            self.出错 = f"事件循环异常：{type(异常).__name__}: {异常}"
        finally:
            try:
                self._循环.close()
            except Exception:                                         # noqa: BLE001
                pass
            self.启用 = False

    async def _等到停止(self) -> None:
        import asyncio
        while not self._停止.is_set():
            await asyncio.sleep(0.1)

    # ---- HTTP：同一个端口提供仪表盘，省掉第二个进程/端口 ----
    async def _静态页(self, 连接, 请求):
        """只要不是 WebSocket 升级请求，就当静态请求处理。

        ★ 必须放行升级请求（返回 None = 不接管），否则握手被 200 挡掉
          —— 实测踩过：浏览器/客户端会报 `InvalidStatus: HTTP 200`。
        """
        from websockets.http11 import Response
        from websockets.datastructures import Headers

        头们 = getattr(请求, "headers", None)
        是升级 = False
        try:
            是升级 = (头们 is not None and (头们.get("Upgrade") or "").lower() == "websocket")
        except Exception:                                             # noqa: BLE001
            pass
        if 是升级:
            return None                     # 交回给 websockets 做握手

        路径 = getattr(请求, "path", "/")
        # ★ 这里**不能**再放一个"路径是 / 就发仪表盘"的早返回：
        #   P0 时期有过那么一段，加了前端静态产物之后忘了删，结果是
        #   `_读静态` 永远轮不到执行 —— 表现是"构建成功、页面却还是旧仪表盘"，
        #   而且因为文件存在、_读静态单独调也对，极难从现象上看出来（实测踩过）。
        #   顺序必须是：先静态产物，最后才回落到仪表盘。
        if 路径 in ("/api/status", "/api/状态"):
            体 = json.dumps(self.状态(), ensure_ascii=False).encode("utf-8")
            头 = Headers({"Content-Type": "application/json; charset=utf-8",
                          "Content-Length": str(len(体)),
                          "Cache-Control": "no-store"})
            return Response(200, "OK", 头, 体)
        if 路径 in ("/api/contract", "/api/契约"):
            # 契约只读下发：前端可据此生成/校验自己的类型定义
            体 = json.dumps(_契约字典(), ensure_ascii=False).encode("utf-8")
            头 = Headers({"Content-Type": "application/json; charset=utf-8",
                          "Content-Length": str(len(体)),
                          "Cache-Control": "no-store"})
            return Response(200, "OK", 头, 体)

        # ---- 前端静态产物（P1 起）----
        #   `软件/web/` 是 Vite 构建出来的 React 应用。有它就用它；
        #   没有（还没跑过构建、或用户删了）就回落到 P0 的单文件仪表盘 ——
        #   **任何情况下都不该出现"打不开页面"**。
        体 = self._读静态(路径)
        if 体 is not None:
            数据, 类型 = 体
            头 = Headers({
                "Content-Type": 类型,
                "Content-Length": str(len(数据)),
                # 前端产物带内容哈希，可以长缓存；index.html 不能缓存
                "Cache-Control": "no-store" if 路径 in ("/", "/index.html")
                                 else "public, max-age=3600",
            })
            return Response(200, "OK", 头, 数据)

        if 路径 in ("/", "/index.html"):
            # 没构建过前端：给 P0 的仪表盘（功能少但真实）
            体 = 仪表盘页().encode("utf-8")
            头 = Headers({
                "Content-Type": "text/html; charset=utf-8",
                "Content-Length": str(len(体)),
                "Cache-Control": "no-store",
            })
            return Response(200, "OK", 头, 体)

        # 其它路径一律 404（不对外暴露任何文件）
        体 = b"not found"
        头 = Headers({"Content-Type": "text/plain; charset=utf-8",
                      "Content-Length": str(len(体))})
        return Response(404, "Not Found", 头, 体)

    # ---- 静态文件：只在 `软件/web/` 一个目录里找，且挡住路径穿越 ----
    def _读静态(self, 路径: str) -> tuple[bytes, str] | None:
        if not os.path.isdir(前端目录):
            return None
        相对 = 路径.split("?", 1)[0].split("#", 1)[0]
        if 相对 in ("", "/"):
            相对 = "/index.html"
        # ★ 路径穿越防护：解析成绝对路径后必须仍在 前端目录 之内。
        #   这里**不信任**任何来路字符串，包括百分号编码。
        try:
            from urllib.parse import unquote
            相对 = unquote(相对)
        except Exception:                                             # noqa: BLE001
            pass
        目标 = os.path.normpath(os.path.join(前端目录, 相对.lstrip("/")))
        if not 目标.startswith(前端目录 + os.sep) and 目标 != 前端目录:
            return None
        if not os.path.isfile(目标):
            # SPA 回落：前端用的是前端路由，未知路径交给 index.html
            if "." not in os.path.basename(目标):
                目标 = os.path.join(前端目录, "index.html")
                if not os.path.isfile(目标):
                    return None
            else:
                return None
        try:
            with open(目标, "rb") as f:
                数据 = f.read()
        except Exception:                                             # noqa: BLE001
            return None
        return 数据, _类型表.get(os.path.splitext(目标)[1].lower(),
                               "application/octet-stream")

    # ---- WebSocket ----
    async def _接入(self, 连接) -> None:
        self._客户端[连接] = True
        self.客户端数 = len(self._客户端)
        # ★ 新客户端接入时**清掉"已发版本"记录**，让它能收到一遍"只发一次"的主题。
        #
        #   为什么必须这么做（实测踩到的真 bug）：
        #     `已发` 原来是**全服务端共享**的一张 {主题: 版本} 表，而 `取走()` 只会返回
        #     "版本比已发新"的主题。于是像「资产库」「项目状态」这种**一次装配只发一条**
        #     的主题，第一个连上的客户端收走后，永远不再发给后来的人 ——
        #     表现是：**页面一刷新，"资产库/项目状态"就空了**（而 2 Hz 重发的
        #     「模型状态」「指标」看着正常，所以非常容易误判成"后端没发"）。
        #
        #   清空的代价很小：下一拍会给**所有**在线连接重发一遍最新快照
        #   （Snapshot 语义本来就是"最新覆盖"，重发无害）。
        #   而"新客户端拿不到当前状态"是硬错误，两害相权。
        self.已发.clear()
        try:
            import asyncio
            # 一进来先发问候：协议版本 + **契约全文** + 当前主题清单。
            # ★ 契约跟着握手一起下发，前端就不必"抄一遍字段名"——
            #   它可以直接校验自己的类型定义与后端是否同版本。
            await 连接.send(json.dumps(
                {"协议": 协议版本, "主题": "__问候__",
                 "数据": {"可用主题": self.待发布.主题们(),
                          "广播间隔": 广播间隔,
                          "契约": _契约字典()}},
                ensure_ascii=False))
            async for 原文 in 连接:            # 上行：命令
                await self._收一帧(连接, 原文)
        except Exception:                                             # noqa: BLE001
            pass
        finally:
            self._客户端.pop(连接, None)
            self.客户端数 = len(self._客户端)

    async def _收一帧(self, 连接, 原文) -> None:
        """解析一条上行消息。**任何格式错误都只回一条错误，绝不抛**。"""
        try:
            if isinstance(原文, (bytes, bytearray)):
                原文 = 原文.decode("utf-8", "replace")
            if len(原文) > 64 * 1024:
                await self._回执(连接, "", False, "消息过大")
                return
            帧 = json.loads(原文)
        except Exception as 异常:                                     # noqa: BLE001
            self.拒收 += 1
            self.最近拒收原因 = f"JSON 解析失败：{type(异常).__name__}"
            await self._回执(连接, "", False, self.最近拒收原因)
            return
        if not isinstance(帧, dict):
            await self._回执(连接, "", False, "消息必须是对象")
            return
        主题名 = str(帧.get("主题") or "")
        负载 = 帧.get("数据")
        通过, 说明 = self.收命令(主题名, 负载)
        await self._回执(连接, 主题名, 通过, 说明)

    async def _回执(self, 连接, 主题名: str, 通过: bool, 说明: str) -> None:
        """命令回执 —— 前端据此知道"我这条命令到底被收下没有"。

        ★ 为什么必须有回执：命令是**要动设备**的，前端不能"发了就假设成功"。
          没有回执的界面只能靠猜，那正是"看起来在工作其实没有"的来源。
        ★ 回执里的 `已派发` 是**发送这一刻现读**的，不是入队时算好的：
          入队时算的话，回执里的数字**永远比真实值小一**（这条命令还没被界面线程取走），
          而"回执说 0、其实已经派发"正好是最容易让人误判成"命令没生效"的那种假信息。
        """
        try:
            await 连接.send(json.dumps(
                {"协议": 协议版本, "主题": "__回执__",
                 "数据": {"主题": 主题名, "通过": 通过, "说明": 说明,
                          "已派发": self.已派发命令,
                          # 通过校验 ≠ 已经生效：真正生效要等界面线程把它转进官方通道。
                          # 前端据此能区分"被收下了"和"已经落地"。
                          "已生效": self.已派发命令 > 0 and 通过},
                 },
                ensure_ascii=False))
        except Exception:                                             # noqa: BLE001
            pass

    async def _广播循环(self) -> None:
        import asyncio
        while True:
            await asyncio.sleep(广播间隔)
            if not self._客户端:
                self.已发.clear()          # 没人在听就重置版本号，省得下次一次性发一堆
                continue
            项 = self.待发布.取走(self.已发)
            if not 项:
                continue
            for 主题, 消息, _版本 in 项:
                文本 = 打包(主题, 消息, self.已广播 + 1)
                死 = []
                for 连接 in list(self._客户端):
                    try:
                        # max_queue 满了会抛，这就是我们要的"丢帧"语义
                        await 连接.send(文本)
                    except Exception:                                 # noqa: BLE001
                        死.append(连接)
                for 连接 in 死:
                    self._客户端.pop(连接, None)
                self.客户端数 = len(self._客户端)
                self.已广播 += 1
                self.已发送字节 += len(文本)


# ---------------------------------------------------------------------------
# ④ 给仿真侧用的门面：一个模块级单例
# ---------------------------------------------------------------------------
_单例: 服务端 | None = None
# 当前装上的水龙头（给 3D 视口读「最近状态」用；见 `取水龙头()`）
_龙头 = None


def 启动(端口: int = 默认端口, 主机: str = 默认主机) -> 服务端:
    """起 Web 桥（幂等）。失败也返回对象，用 `健康()` 判断。"""
    global _单例
    if _单例 is None:
        _单例 = 服务端(主机, 端口)
    if not _单例.启用 and not _单例.出错:
        _单例.启动()
    return _单例


def 投递(主题: str, 消息: Any) -> None:
    """仿真线程调这个。没有服务端时是空操作（零代价）。"""
    if _单例 is not None and _单例.启用:
        _单例.待发布.投递(主题, 消息)


def 健康() -> dict:
    if _单例 is None:
        return {"启用": False, "地址": "", "说明": "未启动"}
    return _单例.状态()


def 关闭() -> None:
    global _单例
    if _单例 is not None:
        _单例.关闭()
        _单例 = None


def 取水龙头():
    """拿到当前装上的水龙头（没有就返回 None）。

    ★ 宿主窗口的 3D 视口要读 `水龙头.最近状态`（每步的集成状态），
      所以需要一个正式访问器 —— 让外面直接摸 `_单例._xxx` 这种私有字段
      是必然要坏的写法（改名就静默失效）。
    """
    return _龙头


def 取命令() -> list[tuple[str, dict]]:
    """界面线程每帧调一次：取走待派发的命令。没有服务端时返回空表。"""
    if _单例 is None or not _单例.启用:
        return []
    return _单例.取命令()


def 记派发(条数: int = 1) -> None:
    """派发成功记账（供 `命令桥` 调用，状态接口里能看到）。"""
    if _单例 is not None:
        _单例.已派发命令 += int(条数)


def _契约字典() -> dict:
    try:
        import 契约 as _契约
        return _契约.转字典()
    except Exception:                                                 # noqa: BLE001
        return {"版本": 0, "下行": [], "上行": [], "错误": "契约模块不可用"}


# ---------------------------------------------------------------------------
# ④b 通道水龙头：不改仿真循环，直接挂在既有的 send_to_viewer 上
# ---------------------------------------------------------------------------
# 只放行**契约里登记过的下行主题**。理由有两个，都很实在：
#   ① 性能：StateSnapshot 是 500 Hz 发的 qpos/qvel 大数组，而界面根本用不到它
#      （3D 视图有自己的通道）——放它过去等于每 2 ms 序列化一次几 KB 的数组。
#   ② 语义：白名单是"我们承诺给前端的接口"，加主题要**先在 契约.py 登记**，
#      不会因为哪天官方新增一个消息类型就悄悄灌到前端。
#
# ★ 这里不再手写一份名单，而是从 `契约.py` 派生 —— 写两份必然漂移
#   （P1 实测：曾有一条 `录制状态` 是幽灵条目，`录制桥` 压根没定义过它）。
try:
    import 契约 as _契约
    主题白名单: dict[str, str] = _契约.类名到主题()
except Exception as _契约异常:                                        # noqa: BLE001
    # 契约拿不到时**不放行任何东西**（宁可没数据，也不能绕过契约）
    主题白名单 = {}
    print(f"⚠ Web桥：契约模块不可用，数据出口将只发问候（{_契约异常}）", flush=True)


class 水龙头:
    """挂在 `仿真端点.send_to_viewer` 上的一层薄壳：复制一份给 Web，原件照发。

    ★ 为什么用"包一层"而不是去改 7 个桥接层：
      那些桥接层已经验证过、有断言护着；包一层意味着**桥接层一行都不用改**，
      而且出问题时把 `安装水龙头` 拆掉就完全回到原状（可回退）。
    ★ 为什么仿真线程里只做浅转换：
      这是 ~500 Hz 的热路径，纯 Python 忙线程会把物理饿死到 ×0.29。
      所以这里只做"取字段 + 标量 .item()"这种微秒级操作，
      `json.dumps` 与网络发送全在广播线程里做。
    """

    def __init__(self, 下一个):
        self.下一个 = 下一个
        self.放过 = 0
        self.抄送 = 0
        self.出错 = ""
        # ★ 最新一份**原始**状态快照（`messages.StateSnapshot`）。
        #   为什么留这个：宿主窗口的 **3D 视口**要跟着仿真动，而它和仿真在
        #   不同线程/不同 GL 上下文 —— 不能共享 `MjData`。最省事又安全的办法是
        #   把每步的集成状态搬过去，视口用它**自己那份** MjData `mj_setState` + `mj_forward`。
        #   这条通道本来就在 500 Hz 地流（只是不进 Web 白名单），顺手留一份几乎零成本。
        self.最近状态: Any = None

    def __call__(self, 消息: Any) -> Any:
        # ① 原件照发：任何情况下都不能影响既有行为
        try:
            self.下一个(消息)
        except Exception:                                             # noqa: BLE001
            raise                                  # 交给上层（原本的出错隔离）处理
        # ② 留一份最新状态给 3D 视口（这条不进 Web 白名单，只在本进程内用）
        try:
            if type(消息).__name__ == "StateSnapshot":
                self.最近状态 = 消息
        except Exception:                                             # noqa: BLE001
            pass
        # ③ 顺手抄一份给 Web（失败只记一笔，绝不抛出）
        try:
            主题 = 主题白名单.get(type(消息).__name__)
            if 主题 is None:
                self.放过 += 1
                return
            表 = _浅转(消息)
            if 表 is not None:
                投递(主题, 表)
                self.抄送 += 1
        except Exception as 异常:                                     # noqa: BLE001
            self.出错 = f"{type(异常).__name__}: {异常}"
        return


def _浅转(消息: Any) -> dict | None:
    """dataclass → {字段名: 浅值}。只做一层，且把 numpy 标量换成本机类型。"""
    if not dataclasses.is_dataclass(消息) or isinstance(消息, type):
        return None
    出: dict[str, Any] = {"_类型": type(消息).__name__}
    for f in dataclasses.fields(消息):
        值 = getattr(消息, f.name, None)
        if isinstance(值, (bool, int, float, str)) or 值 is None:
            出[f.name] = 值
        else:
            item = getattr(值, "item", None)
            if item is not None and not hasattr(值, "shape"):
                try:
                    出[f.name] = 值.item()
                    continue
                except Exception:                                     # noqa: BLE001
                    pass
            出[f.name] = 值          # dict / list / ndarray：留给广播线程转（只读快照）
    return 出


def 安装水龙头(目标: Any) -> tuple[水龙头 | None, Any]:
    """把水龙头装到"发送出口"上。返回 (水龙头, 装好之后的发送函数)。

    ★ 必须**尽早**调用：所有发布器都是在构造时把发送函数**抓走**的，
      装晚了它们抓到的还是原件，就抄送不到了（实测踩过）。

    ★ 两种形态都要支持，否则无窗模式会静默失效：
      · 有窗：给的是官方端点对象，出口是它的 `send_to_viewer`（要**改写属性**）；
      · 无窗：给的是 `启动.py` 里的局部函数 `发送`（闭包变量，**改不了它的属性**）。
        所以这里返回"装好之后的发送函数"，调用方必须用返回值，
        而不是假设"原对象已经被就地改写"。

    ⚠️ 早先这里只处理第一种，无窗模式下传进来一个函数 →
      `AttributeError` 被 except 吞掉 → 返回 None → **一条数据都发不出去**，
      而且只表现为"界面空着"，没有任何报错。所以现在把异常打出来，不再静默。
    """
    try:
        # 形态 ①：端点对象（有 send_to_viewer 属性）
        if hasattr(目标, "send_to_viewer"):
            原 = 目标.send_to_viewer
            龙头 = 水龙头(原)
            目标.send_to_viewer = 龙头
            global _龙头
            _龙头 = 龙头
            return 龙头, 龙头
        # 形态 ②：就是一个可调用的发送函数
        if callable(目标):
            龙头 = 水龙头(目标)
            return 龙头, 龙头
    except Exception as 异常:                                         # noqa: BLE001
        print(f"⚠ Web桥：装水龙头失败（数据出口将收不到任何消息）："
              f"{type(异常).__name__}: {异常}", flush=True)
        return None, 目标
    print(f"⚠ Web桥：装水龙头失败（不认识这个出口：{type(目标).__name__}）", flush=True)
    return None, 目标


# ---------------------------------------------------------------------------
# ⑤ 仪表盘页：P0 只做"看得见真实数据"，不做任何假数据
# ---------------------------------------------------------------------------
def 仪表盘页() -> str:
    return _仪表盘_HTML


_仪表盘_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>驭臂 · 数据出口自检（P0）</title>
<style>
  :root{
    --bg:#0b1016; --panel:#121a23; --line:#1e2b38; --fg:#dbe6f0; --dim:#7b8fa3;
    --accent:#4cc2ff; --ok:#3ddc97; --warn:#ffb454; --bad:#ff6b6b;
    --mono:"SF Mono",Menlo,Consolas,"Courier New",monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
  header{display:flex;align-items:center;gap:16px;padding:12px 18px;
    background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:2}
  h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.3px}
  h1 small{color:var(--dim);font-weight:400;margin-left:8px;font-size:12px}
  .pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:99px;
    background:#0e1620;border:1px solid var(--line);font-size:12px;color:var(--dim)}
  .dot{width:8px;height:8px;border-radius:99px;background:var(--dim);flex:0 0 auto}
  .dot.on{background:var(--ok);box-shadow:0 0 8px var(--ok)}
  .dot.off{background:var(--bad)}
  .spacer{flex:1}
  main{display:grid;grid-template-columns:260px 1fr;min-height:calc(100vh - 50px)}
  aside{border-right:1px solid var(--line);padding:14px;background:#0e151d}
  aside h2{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);
    margin:0 0 10px}
  .topic{display:flex;align-items:center;gap:8px;padding:7px 9px;border-radius:7px;
    cursor:pointer;font-size:13px;color:var(--dim);border:1px solid transparent}
  .topic:hover{background:#131d27;color:var(--fg)}
  .topic.sel{background:#16232f;color:var(--fg);border-color:var(--line)}
  .topic .n{margin-left:auto;font:11px/1 var(--mono);color:var(--dim)}
  section{padding:16px 18px;min-width:0}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 16px;margin-bottom:14px}
  .card h3{margin:0 0 10px;font-size:13px;color:var(--dim);font-weight:600;
    display:flex;align-items:center;gap:8px}
  canvas{width:100%;height:150px;display:block;background:#0d141c;border-radius:7px;
    border:1px solid var(--line)}
  table{width:100%;border-collapse:collapse;font:12.5px/1.5 var(--mono)}
  th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #16202b}
  th{color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase;
    letter-spacing:.06em}
  td.v{text-align:right;color:var(--accent)}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font:12.5px/1.6 var(--mono)}
  .kv b{color:var(--dim);font-weight:400}
  .warn{color:var(--warn)}
  .note{color:var(--dim);font-size:12px;margin-top:10px}
  pre{background:#0d141c;border:1px solid var(--line);border-radius:7px;padding:10px;
    overflow:auto;max-height:220px;font:12px/1.5 var(--mono);color:#a9c4dd;margin:0}
  .empty{color:var(--dim);padding:24px;text-align:center;font-size:13px}
</style>
</head>
<body>
<header>
  <h1>驭臂 · 数据出口自检 <small>P0：给仿真侧开第二个出口</small></h1>
  <span class="pill"><span class="dot" id="conn"></span><span id="connText">连接中…</span></span>
  <span class="pill">速率 <b id="rate" style="color:var(--accent);margin-left:4px">0</b> 帧/秒</span>
  <span class="pill">主题 <b id="topicCount" style="color:var(--accent);margin-left:4px">0</b></span>
  <span class="spacer"></span>
  <span class="pill" id="addr">—</span>
</header>
<main>
  <aside>
    <h2>主题（仿真侧在发什么）</h2>
    <div id="topicList"><div class="empty">等待数据…</div></div>
    <div class="note">这些名字对应 7 个桥接层实际发出的消息。<br>同一个主题的旧消息会被新消息覆盖（latest-wins），与官方 <code>Snapshot</code> 语义一致。</div>
  </aside>
  <section>
    <div class="card">
      <h3>实时数值 <span id="liveTopic" style="color:var(--accent)"></span></h3>
      <div id="live"><div class="empty">还没有收到 <b>指标</b> 主题 —— 挂一个算法（例如「正弦摆动」）并跑起物理就会有了。</div></div>
      <div class="note">曲线横轴为墙钟时间，纵轴自动缩放；只画最近 60 秒。</div>
    </div>
    <div class="card">
      <h3>这一帧的原始 JSON</h3>
      <pre id="raw">—</pre>
      <div class="note">这就是 Web 前端将来用的全部数据来源：纯 dataclass → JSON。没有一处假数据。</div>
    </div>
    <div class="card">
      <h3>对账用（与原生【实时监控】面板应为同源同频）</h3>
      <div class="kv" id="stats"></div>
    </div>
  </section>
</main>
<script>
(function(){
  "use strict";
  var 端口 = (location.port || "8712");
  var url = "ws://" + location.hostname + ":" + 端口 + "/";
  var ws = null, 收到的帧数 = 0, 上次计数 = 0, 上次时刻 = performance.now();
  var 主题表 = {}, 当前主题 = null, 原始 = document.getElementById("raw");
  var 曲线 = {};   // {系列名: [{t,v}]}
  var 画布 = null, 上下文 = null;

  function 建画布(){
    var box = document.getElementById("live");
    box.innerHTML = "";
    画布 = document.createElement("canvas");
    box.appendChild(画布);
    上下文 = 画布.getContext("2d");
    适配();
    window.addEventListener("resize", 适配);
  }
  function 适配(){
    if(!画布) return;
    var r = 画布.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    画布.width = Math.max(10, r.width * d); 画布.height = Math.max(10, r.height * d);
    上下文.setTransform(d,0,0,d,0,0);
  }

  function 连(){
    ws = new WebSocket(url);
    ws.onopen = function(){
      document.getElementById("conn").className = "dot on";
      document.getElementById("connText").textContent = "已连接";
      document.getElementById("addr").textContent = url;
    };
    ws.onclose = function(){
      document.getElementById("conn").className = "dot off";
      document.getElementById("connText").textContent = "断开，重连中…";
      setTimeout(连, 1000);
    };
    ws.onerror = function(){ try{ ws.close(); }catch(e){} };
    ws.onmessage = function(ev){
      var 帧; try{ 帧 = JSON.parse(ev.data); }catch(e){ return; }
      收到的帧数++;
      if(帧.主题 === "__问候__"){
        document.getElementById("topicCount").textContent = (帧.数据.可用主题||[]).length;
        return;
      }
      记主题(帧.主题);
      if(帧.主题 === "指标") 收指标(帧);
      if(帧.主题 === "模型状态" || 帧.主题 === "项目状态") 收状态(帧);
      原始.textContent = JSON.stringify(帧.数据, null, 2).slice(0, 4000);
    };
  }

  function 记主题(名){
    if(!主题表[名]) { 主题表[名] = {n:0}; 重画主题(); }
    主题表[名].n++;
    if(!当前主题){ 当前主题 = "指标"; 标选(); }
  }
  function 重画主题(){
    var box = document.getElementById("topicList");
    var 名 = Object.keys(主题表).sort();
    document.getElementById("topicCount").textContent = 名.length;
    if(!名.length){ box.innerHTML = '<div class="empty">等待数据…</div>'; return; }
    box.innerHTML = 名.map(function(k){
      return '<div class="topic'+(k===当前主题?' sel':'')+'" data-t="'+k+'">'
           + '<span>'+k+'</span><span class="n">'+主题表[k].n+'</span></div>';
    }).join("");
    Array.prototype.forEach.call(box.querySelectorAll(".topic"), function(el){
      el.onclick = function(){ 当前主题 = el.dataset.t; 标选(); };
    });
  }
  function 标选(){
    Array.prototype.forEach.call(document.querySelectorAll(".topic"), function(el){
      el.classList.toggle("sel", el.dataset.t === 当前主题);
    });
    document.getElementById("liveTopic").textContent = 当前主题 ? "（当前：" + 当前主题 + "）" : "";
  }

  function 收指标(帧){
    var d = 帧.数据 || {}, 数值 = d.数值;
    var t = d.墙钟 || 帧.墙钟 || 0;
    if(!数值) return;
    if(!画布) 建画布();
    Object.keys(数值).forEach(function(k){
      (曲线[k] = 曲线[k] || []).push({t:t, v:数值[k]});
      if(曲线[k].length > 3600) 曲线[k].shift();
    });
    画(数值);
  }

  function 画(数值){
    var w = 画布.clientWidth, h = 画布.clientHeight;
    上下文.clearRect(0,0,w,h);
    var 系列 = Object.keys(数值);
    if(!系列.length) return;
    var 全部 = [];
    系列.forEach(function(k){ 曲线[k].forEach(function(p){ 全部.push(p.t); }); });
    var t1 = Math.max.apply(null, 全部), t0 = t1 - 60;
    var 色 = ["#4cc2ff","#3ddc97","#ffb454","#ff6b6b","#b98cff","#5ee0d0","#ffd166"];
    // 网格
    上下文.strokeStyle = "#16202b"; 上下文.lineWidth = 1;
    for(var i=0;i<=4;i++){ var y = 8 + (h-16)*i/4;
      上下文.beginPath(); 上下文.moveTo(0,y); 上下文.lineTo(w,y); 上下文.stroke(); }
    var 图例 = [];
    系列.forEach(function(k, i){
      var pts = 曲线[k].filter(function(p){ return p.t >= t0; });
      if(pts.length < 2) return;
      var vs = pts.map(function(p){ return p.v; });
      var lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs);
      if(hi - lo < 1e-12){ lo -= 0.5; hi += 0.5; }
      var pad = (hi-lo)*0.1; lo -= pad; hi += pad;
      var 色值 = 色[i % 色.length];
      上下文.strokeStyle = 色值; 上下文.lineWidth = 1.6; 上下文.beginPath();
      pts.forEach(function(p, j){
        var x = (p.t - t0) / 60 * w;
        var y = 8 + (h-16) * (1 - (p.v - lo) / (hi - lo));
        j ? 上下文.lineTo(x,y) : 上下文.moveTo(x,y);
      });
      上下文.stroke();
      图例.push({名:k, 色:色值, 末:vs[vs.length-1]});
    });
    // 图例
    上下文.font = "11px ui-monospace,Menlo,monospace";
    图例.forEach(function(L, i){
      上下文.fillStyle = L.色;
      上下文.fillRect(10, 10 + i*15, 8, 3);
      上下文.fillText(L.名 + " = " + (Math.round(L.末*1000)/1000), 24, 15 + i*15);
    });
  }

  function 收状态(帧){
    var d = 帧.数据 || {};
    var 盒 = document.getElementById("stats");
    var 行 = [];
    Object.keys(d).forEach(function(k){
      if(k === "_类型") return;
      var v = d[k];
      if(v && typeof v === "object") v = "…（" + (Array.isArray(v) ? v.length + " 项" : "对象") + "）";
      行.push("<b>"+k+"</b><span>"+v+"</span>");
    });
    盒.innerHTML = 行.join("");
  }

  setInterval(function(){
    var 现在 = performance.now();
    var 速率 = (收到的帧数 - 上次计数) / ((现在 - 上次时刻)/1000);
    上次计数 = 收到的帧数; 上次时刻 = 现在;
    document.getElementById("rate").textContent = 速率.toFixed(1);
    if(画布) 画(曲线);
  }, 1000);

  // 初始也画一次，免得空等一秒
  setTimeout(function(){ if(!画布){ 建画布(); } 画({}); }, 600);
  连();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":       # 单独起一个桥来自测（不连仿真）
    桥 = 启动()
    print("=" * 70)
    print("  Web桥 自检")
    print("=" * 70)
    print(f"  websockets : ", end="")
    try:
        import websockets
        print(websockets.__version__)
    except Exception as 异常:                                         # noqa: BLE001
        print(f"不可用（{异常}）")
    print(f"  状态       : {json.dumps(健康(), ensure_ascii=False)}")
    if 桥.启用:
        print(f"\n  打开浏览器看： {健康()['地址']}")
        print("  （这个自检模式没有仿真数据，页面会显示「等待数据」）")
        print("\n  Ctrl+C 退出")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n  退出")
    else:
        print(f"\n  ✗ 没起来：{桥.出错}")
