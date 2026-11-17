#!/usr/bin/env python3
"""
fake_backend.py —— **给界面做冒烟测试用的最小 WebSocket 对端**（不是产品代码，不参与打包）。

它为什么存在：
    这一层是"只做界面"，而界面里唯一能证明"没写假数据"的办法，
    就是让它对着一个**真的在说话的对端**跑一遍 —— 曲线要真的动、回执要真的回、
    状态栏里的运行字段要真的有字。空跑（连不上）只能验证"空态画得对"，
    验证不了"有数据时画得对"。

它是什么：
    · 一个 60 行的 websockets 服务，按 `软件/contract.py` 的主题名发帧，形状与 `生成/contract.ts` 一致
    · 用**正弦波**造指标值 —— 所以图上的波形是"这一层真的收到了这些数"，
      不是这一层自己算的（界面上任何数字仍然只来自网络）
    · 同时提供 HTTP：把 `软件/web/` 的产物按同源方式发给浏览器，
      这样 `猜地址()` 推出的 `ws://<同一个 host>/` 正好连到它

它不是什么：
    · 不是后端，不替代 `软件/Web桥.py`，不进 `软件/web/` 产物，不参与启动流程
    · 只在"改前端、想看一眼"的时候手动跑：
        /Users/huspark/Desktop/驭臂/.venv/bin/python frontend/tests/fake_backend.py
      然后浏览器开 http://127.0.0.1:8712/

用到的主题名一律照抄契约（`下行元` / `上行元`），名字对不上就是白测。
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time

import websockets

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRONTEND_DIR = os.path.join(PACKAGE_ROOT, "软件", "web")
SOFTWARE_DIR = os.path.join(PACKAGE_ROOT, "软件")
if SOFTWARE_DIR not in sys.path:
    sys.path.insert(0, SOFTWARE_DIR)

# 端口可用环境变量改：真后端正在 8712 上跑时，冒烟测试不要抢它的端口。
PORT = int(os.environ.get("驭臂_测试端口", "8712"))
BROADCAST_INTERVAL = 0.05

# ★ 契约版本必须与产品同源，否则前端会正确地拒绝连接（协议版本守卫）。
#   早先这里写死 1，产品到 9 之后冒烟测试连不上；现在直接从契约模块取。
try:
    import contract as _contract
    PROTOCOL_VERSION = int(_contract.VERSION)
    CONTRACT_DATA = _contract.to_dict()
except Exception:                                                     # noqa: BLE001
    PROTOCOL_VERSION = 1
    CONTRACT_DATA = {
        "版本": 1,
        "下行": [],
        "上行": [],
    }

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}

# ★ 只承诺本对端真的会发的主题。契约全文可以很长（产品有十几条），
#   但「问题」页签会拿 `可用主题` 对账，谎称全都会发只会制造假问题。
AVAILABLE_TOPICS = ["指标", "parameter.table", "model.state", "model.library", "project.state", "插件目录", "系统", "simulation.state"]

state = {
    "重力开": False,
    "模型": "冒烟测试臂",
    "路径": "模型/冒烟/scene.xml",
    "换模型次数": 0,
    "算法": ["joint_pd", "gravity_comp"],
    "算法已存盘": False,
    "仿真状态": "暂停",
    "仿真时间": 0.0,
    "复位次数": 0,
    "最近墙钟": time.time(),
}
# 参数表的当前值（可被 command.parameters 改写；广播时按它重发）
parameter_values = {
    "Joint PD·kp": 120.0,
    "Joint PD·kd": 8.0,
    "Joint PD·限幅": 40.0,
    "OSC·刚度": 200.0,
}


def encode_frame(topic: str, data: dict, sequence: int) -> str:
    return json.dumps(
        {"协议": PROTOCOL_VERSION, "主题": topic, "序号": sequence, "墙钟": time.time(), "数据": data},
        ensure_ascii=False,
    )


async def serve_static(connection, request):
    """HTTP 分支：只服务 软件/web/ 里的产物；WebSocket 升级请求放行。"""
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    if (getattr(request, "headers", None) or {}).get("Upgrade", "").lower() == "websocket":
        return None
    path = getattr(request, "path", "/").split("?", 1)[0]
    if path in ("/", "/index.html"):
        path = "/index.html"
    target = os.path.normpath(os.path.join(FRONTEND_DIR, path.lstrip("/")))
    if not target.startswith(FRONTEND_DIR) or not os.path.isfile(target):
        return Response(404, "Not Found", Headers({"Content-Type": "text/plain"}), b"not found")
    with open(target, "rb") as f:
        body = f.read()
    headers = Headers({
        "Content-Type": CONTENT_TYPES.get(os.path.splitext(target)[1].lower(), "application/octet-stream"),
        "Content-Length": str(len(body)),
        "Cache-Control": "no-store",
    })
    return Response(200, "OK", headers, body)


async def serve(connection):
    sequence = 0

    async def send(topic, data):
        nonlocal sequence
        sequence += 1
        await connection.send(encode_frame(topic, data, sequence))

    await connection.send(json.dumps({
        "协议": PROTOCOL_VERSION,
        "主题": "__问候__",
        "数据": {"可用主题": AVAILABLE_TOPICS, "广播间隔": BROADCAST_INTERVAL, "契约": CONTRACT_DATA},
    }, ensure_ascii=False))

    def project_state():
        metadata = {
            "joint_pd": {"名称": "Joint PD", "版本": "1.0", "接管控制": True},
            "gravity_comp": {"名称": "Gravity Comp", "版本": "0.3", "接管控制": False},
            "osc": {"名称": "OSC", "版本": "0.3", "接管控制": True},
            "whole_body": {"名称": "Whole Body", "版本": "0.1", "接管控制": True},
        }
        return {
            "project": "冒烟项目",
            "model_path": state["路径"],
            "model_display_name": state["模型"],
            "algorithms": [metadata[x] for x in state["算法"] if x in metadata],
            "report": ["装配 Joint PD → ctrl", "跳过 1 个（模型不兼容）"],
            "algorithm_library": ["Joint PD", "Gravity Comp", "OSC", "Whole Body"],
            "saved": state["算法已存盘"],
            "active_controller": "Joint PD",
            "overridden_controllers": ["Gravity Comp"],
            "gravity_enabled": state["重力开"],
        }

    def model_library():
        return {
            "count": 1,
            "models": [{
                "id": "smoke_arm", "display_name": "冒烟测试臂",
                "category": "test", "dof": 7, "actuator_count": 7,
                "license": "test", "controllable": True, "path": state["路径"],
            }],
        }

    def plugin_catalog():
        items = [
            ("joint_pd", "Joint PD", "1.0", "关节控制"),
            ("gravity_comp", "Gravity Comp", "0.3", "动力学"),
            ("osc", "OSC", "0.3", "末端控制"),
            ("whole_body", "Whole Body", "0.1", "全身控制"),
        ]
        return {
            "数量": len(items),
            "插件": [
                {
                    "插件": module, "名称": actuator_name, "版本": version, "分组": group,
                    "说明": f"{actuator_name} 冒烟测试插件", "作者": "test",
                    "文件": f"算法库/{module}.py", "被项目使用": ["冒烟项目"],
                    "当前启用": module in state["算法"],
                    "当前顺序": state["算法"].index(module) if module in state["算法"] else None,
                }
                for module, actuator_name, version, group in items
            ],
            "说明": "冒烟测试插件目录",
        }

    def simulation_state():
        return {
            "state": "running" if state["仿真状态"] == "运行" else "paused",
            "gravity_enabled": state["重力开"],
            "simulation_time": state["仿真时间"],
            "reset_count": state["复位次数"],
            "speed_multiplier": 1.0,
            "description": "冒烟测试仿真状态",
        }

    await send("project.state", project_state())
    await send("model.library", model_library())
    await send("插件目录", plugin_catalog())
    await send("simulation.state", simulation_state())

    async def receive_commands():
        async for raw in connection:
            try:
                message = json.loads(raw)
            except Exception:
                continue
            topic = message.get("主题", "")
            request_id = message.get("请求", "")
            data = message.get("数据", {})
            if topic == "command.gravity":
                state["重力开"] = bool(data.get("gravity_enabled"))
                description = f"重力开={state['重力开']}（假后端已受理）"
            elif topic == "command.simulation":
                action = str(data.get("action", ""))
                if action == "run":
                    state["仿真状态"] = "运行"
                    state["重力开"] = True
                    description = "仿真已运行（假后端）"
                elif action == "pause":
                    state["仿真状态"] = "暂停"
                    state["重力开"] = False
                    description = "仿真已暂停（假后端）"
                elif action == "reset":
                    state["仿真状态"] = "暂停"
                    state["重力开"] = False
                    state["仿真时间"] = 0.0
                    state["复位次数"] += 1
                    description = "仿真已复位（假后端）"
                else:
                    description = "假后端故意拒绝：未知仿真动作"
            elif topic == "command.model":
                state["换模型次数"] += 1
                state["路径"] = str(data.get("path", ""))
                # 故意让第二次换模型失败：用来验证"失败要同时进控制台和提示"
                if state["换模型次数"] % 2 == 0:
                    description = "假后端故意拒绝：这个路径不存在"
                else:
                    description = "已加载（假后端）"
            elif topic == "命令.辨识":
                description = "辨识命令已受理（假后端）"
            elif topic == "command.parameters":
                changes = data.get("updates", {}) or {}
                for key, value in changes.items():
                    if key in parameter_values:
                        parameter_values[key] = float(value)
                description = "参数已更新（假后端）"
            elif topic == "command.algorithms":
                state["算法"] = [
                    str(item.get("plugin", ""))
                    for item in (data.get("algorithms", []) or [])
                    if isinstance(item, dict) and item.get("plugin")
                ]
                state["算法已存盘"] = bool(data.get("persist", False))
                description = "算法已保存（假后端）" if state["算法已存盘"] else "算法已临时应用（假后端）"
            else:
                description = "这个主题假后端不认识"
            passed = not description.startswith("假后端故意拒绝")
            await connection.send(json.dumps({
                "协议": PROTOCOL_VERSION, "主题": "__回执__",
                "数据": {"请求": request_id, "主题": topic, "通过": passed, "说明": description},
            }, ensure_ascii=False))
            await send("project.state", project_state())
            await send("插件目录", plugin_catalog())
            await send("simulation.state", simulation_state())

    async def broadcast():
        started_at = time.time()
        next_metrics = 0.0
        next_parameters = 0.0
        next_model = 0.0
        next_identification = 0.0
        next_system = 0.0
        next_simulation_state = 0.0
        while True:
            now = time.time()
            elapsed = now - started_at
            delta = max(0.0, now - state["最近墙钟"])
            state["最近墙钟"] = now
            if state["仿真状态"] == "运行":
                state["仿真时间"] += delta
            if now >= next_metrics:
                next_metrics = now + 1 / 30
                await send("指标", {
                    "时间": elapsed,
                    "墙钟": now,
                    "数值": {
                        "joint1·位置": math.sin(elapsed * 1.2) * 0.8,
                        "joint1·速度": math.cos(elapsed * 1.2) * 0.96,
                        "joint2·位置": math.sin(elapsed * 0.7 + 1.0) * 0.4,
                        "actuator1·力矩": math.sin(elapsed * 3.0) * 2.5,
                        "sim·实时因子": 0.95 + 0.05 * math.sin(elapsed * 0.3),
                    },
                })
            if now >= next_parameters:
                next_parameters = now + 0.1
                # ★ 形状必须与产品一致：`{参数: {"插件名·参数名": 参数项}}`。
                #   早先这里画成了 `{插件: {参数: {...}}}`，界面上只会出现两行 `--`，
                #   参数编辑冒烟也就跟着失败 —— 是夹具漂移，不是产品坏了。
                await send("parameter.table", {"parameters": {
                    "Joint PD·kp": {
                        "plugin": "Joint PD", "plugin_version": "1.0", "parameter": "kp",
                        "value": parameter_values["Joint PD·kp"], "range": [0.0, 500.0], "step": 1.0,
                        "unit": "", "description": "比例增益",
                    },
                    "Joint PD·kd": {
                        "plugin": "Joint PD", "plugin_version": "1.0", "parameter": "kd",
                        "value": parameter_values["Joint PD·kd"], "range": [0.0, 100.0], "step": 0.5,
                        "unit": "", "description": "微分增益",
                    },
                    "Joint PD·限幅": {
                        "plugin": "Joint PD", "plugin_version": "1.0", "parameter": "限幅",
                        "value": parameter_values["Joint PD·限幅"], "range": [0.0, 200.0], "step": 1.0,
                        "unit": "N·m", "description": "力矩上限",
                    },
                    "OSC·刚度": {
                        "plugin": "OSC", "plugin_version": "0.3", "parameter": "刚度",
                        "value": parameter_values["OSC·刚度"], "range": [10.0, 2000.0], "step": 10.0,
                        "unit": "N/m", "description": "笛卡尔刚度",
                    },
                }})
            if now >= next_model:
                next_model = now + 0.5
                await send("project.state", project_state())
                await send("model.state", {
                    "current_path": state["路径"], "current_display_name": state["模型"],
                    "dof": 7, "actuator_count": 7, "status": "✓ 就绪", "duration_s": 0.184,
                })
            if now >= next_system:
                next_system = now + 1.0
                await send("系统", {
                    "仿真时间": state["仿真时间"],
                    "墙钟": elapsed,
                    "RTF": 0.97 if state["仿真状态"] == "运行" else 0.0,
                    "步频": 500.0 if state["仿真状态"] == "运行" else 0.0,
                    "仿真步长": 0.002,
                    "内存MB": 280.0,
                    "插件数": 2,
                    "出错": "",
                })
            if now >= next_simulation_state:
                next_simulation_state = now + 0.2
                await send("simulation.state", simulation_state())
            if now >= next_identification:
                next_identification = now + 0.2
                await send("辨识状态", {
                    "状态": "采样中" if elapsed < 6 else "完成",
                    "进度": f"已采 {min(elapsed, 6.0):.1f} / 6.0 s",
                    "采样步数": int(min(elapsed, 6.0) * 100),
                    "结果": [
                        {"名称": "joint1.阻尼", "标称": 0.1, "辨识值": 0.137, "变化": "+37%"},
                        {"名称": "joint2.阻尼", "标称": 0.1, "辨识值": 0.094, "变化": "-6%"},
                    ],
                    "拟合": {"前": 3.2e-3, "后": 8.1e-4},
                    "耗时": round(elapsed, 2),
                    "日志": [f"[{elapsed:.2f}s] 采样 step={int(elapsed * 100)}", "激励：正弦扫频"],
                })
            await asyncio.sleep(BROADCAST_INTERVAL)

    task = [asyncio.create_task(broadcast()), asyncio.create_task(receive_commands())]
    try:
        await asyncio.gather(*task)
    finally:
        for t in task:
            t.cancel()


async def main():
    print(f"假后端：ws + http 都在 {PORT}（产物目录 {FRONTEND_DIR}）", flush=True)
    # origins=None：跨源检查关掉。开发时页面在 5273、本对端在 8712，
    # websockets 默认按 Origin 拒绝跨源连接 —— 那不是我们要测的东西。
    async with websockets.serve(serve, "127.0.0.1", PORT, process_request=serve_static, origins=None):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("假后端：停了", flush=True)
