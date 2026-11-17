"""命令回执自检：连续同主题命令必须各自收到对应的请求编号。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SOFTWARE = ROOT / "runtime"
if str(SOFTWARE) not in sys.path:
    sys.path.insert(0, str(SOFTWARE))

import console_support  # noqa: E402

console_support.prepare_output()

import web_bridge  # noqa: E402


class FakeConnection:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw_message: str) -> None:
        self.sent.append(json.loads(raw_message))


async def check_receipts() -> None:
    server = web_bridge.Server("127.0.0.1", 0)
    connection = FakeConnection()

    for request_id, enabled in (("same-topic-1", True), ("same-topic-2", False)):
        await server._receive_frame(connection, json.dumps({
            "请求": request_id,
            "主题": "command.gravity",
            "数据": {"gravity_enabled": enabled},
        }, ensure_ascii=False))

    assert len(connection.sent) == 2, "两条命令应分别产生回执"
    receipts = [frame["数据"] for frame in connection.sent]
    assert [receipt["请求"] for receipt in receipts] == ["same-topic-1", "same-topic-2"]
    assert all(receipt["主题"] == "command.gravity" for receipt in receipts)
    assert all(receipt["通过"] for receipt in receipts)
    assert len(server.get_commands()) == 2, "两条合法命令都应进入后端命令队列"

    await server._receive_frame(connection, json.dumps({
        "请求": 123,
        "主题": "command.gravity",
        "数据": {"gravity_enabled": True},
    }, ensure_ascii=False))
    error_receipt = connection.sent[-1]["数据"]
    assert not error_receipt["通过"]
    assert "请求编号" in error_receipt["说明"]


def main() -> int:
    asyncio.run(check_receipts())
    print("[PASS] 同主题命令回执按请求编号一一对应")
    print("命令回执自检：1 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
