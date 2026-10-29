"""命令回执自检：连续同主题命令必须各自收到对应的请求编号。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys


包根 = Path(__file__).resolve().parents[2]
软件目录 = 包根 / "软件"
if str(软件目录) not in sys.path:
    sys.path.insert(0, str(软件目录))

import 控制台  # noqa: E402

控制台.准备输出()

import Web桥  # noqa: E402


class _假连接:
    def __init__(self) -> None:
        self.已发送: list[dict] = []

    async def send(self, 原文: str) -> None:
        self.已发送.append(json.loads(原文))


async def 检查() -> None:
    服务 = Web桥.服务端("127.0.0.1", 0)
    连接 = _假连接()

    for 请求号, 开 in (("same-topic-1", True), ("same-topic-2", False)):
        await 服务._收一帧(连接, json.dumps({
            "请求": 请求号,
            "主题": "命令.重力",
            "数据": {"重力开": 开},
        }, ensure_ascii=False))

    assert len(连接.已发送) == 2, "两条命令应分别产生回执"
    回执们 = [帧["数据"] for 帧 in 连接.已发送]
    assert [回执["请求"] for 回执 in 回执们] == ["same-topic-1", "same-topic-2"]
    assert all(回执["主题"] == "命令.重力" for 回执 in 回执们)
    assert all(回执["通过"] for 回执 in 回执们)
    assert len(服务.取命令()) == 2, "两条合法命令都应进入后端命令队列"

    await 服务._收一帧(连接, json.dumps({
        "请求": 123,
        "主题": "命令.重力",
        "数据": {"重力开": True},
    }, ensure_ascii=False))
    错误回执 = 连接.已发送[-1]["数据"]
    assert not 错误回执["通过"]
    assert "请求编号" in 错误回执["说明"]


def main() -> int:
    asyncio.run(检查())
    print("[PASS] 同主题命令回执按请求编号一一对应")
    print("命令回执自检：1 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
