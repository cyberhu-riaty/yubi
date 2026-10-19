#!/usr/bin/env python3
"""
假后端.py —— **给界面做冒烟测试用的最小 WebSocket 对端**（不是产品代码，不参与打包）。

它为什么存在：
    这一层是"只做界面"，而界面里唯一能证明"没写假数据"的办法，
    就是让它对着一个**真的在说话的对端**跑一遍 —— 曲线要真的动、回执要真的回、
    状态栏里的运行字段要真的有字。空跑（连不上）只能验证"空态画得对"，
    验证不了"有数据时画得对"。

它是什么：
    · 一个 60 行的 websockets 服务，按 `软件/契约.py` 的主题名发帧，形状与 `生成/契约.ts` 一致
    · 用**正弦波**造指标值 —— 所以图上的波形是"这一层真的收到了这些数"，
      不是这一层自己算的（界面上任何数字仍然只来自网络）
    · 同时提供 HTTP：把 `软件/web/` 的产物按同源方式发给浏览器，
      这样 `猜地址()` 推出的 `ws://<同一个 host>/` 正好连到它

它不是什么：
    · 不是后端，不替代 `软件/Web桥.py`，不进 `软件/web/` 产物，不参与启动流程
    · 只在"改前端、想看一眼"的时候手动跑：
        /Users/huspark/Desktop/驭臂/.venv/bin/python 前端/测试/假后端.py
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

包根 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
前端目录 = os.path.join(包根, "软件", "web")
软件目录 = os.path.join(包根, "软件")
if 软件目录 not in sys.path:
    sys.path.insert(0, 软件目录)

# 端口可用环境变量改：真后端正在 8712 上跑时，冒烟测试不要抢它的端口。
端口 = int(os.environ.get("驭臂_测试端口", "8712"))
广播间隔 = 0.05

# ★ 契约版本必须与产品同源，否则前端会正确地拒绝连接（协议版本守卫）。
#   早先这里写死 1，产品到 9 之后冒烟测试连不上；现在直接从契约模块取。
try:
    import 契约 as _契约
    协议版本 = int(_契约.版本)
    契约全文 = _契约.转字典()
except Exception:                                                     # noqa: BLE001
    协议版本 = 1
    契约全文 = {
        "版本": 1,
        "下行": [],
        "上行": [],
    }

类型表 = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}

# ★ 只承诺本对端真的会发的主题。契约全文可以很长（产品有十几条），
#   但「问题」页签会拿 `可用主题` 对账，谎称全都会发只会制造假问题。
可用主题 = ["指标", "参数表", "模型状态", "项目状态", "系统"]

状态 = {"重力开": False, "模型": "冒烟测试臂", "路径": "模型/冒烟/scene.xml", "换模型次数": 0}
# 参数表的当前值（可被 命令.改参数 改写；广播时按它重发）
参数值 = {
    "Joint PD·kp": 120.0,
    "Joint PD·kd": 8.0,
    "Joint PD·限幅": 40.0,
    "OSC·刚度": 200.0,
}


def 帧(主题: str, 数据: dict, 序号: int) -> str:
    return json.dumps(
        {"协议": 协议版本, "主题": 主题, "序号": 序号, "墙钟": time.time(), "数据": 数据},
        ensure_ascii=False,
    )


async def 静态页(连接, 请求):
    """HTTP 分支：只服务 软件/web/ 里的产物；WebSocket 升级请求放行。"""
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    if (getattr(请求, "headers", None) or {}).get("Upgrade", "").lower() == "websocket":
        return None
    路径 = getattr(请求, "path", "/").split("?", 1)[0]
    if 路径 in ("/", "/index.html"):
        路径 = "/index.html"
    目标 = os.path.normpath(os.path.join(前端目录, 路径.lstrip("/")))
    if not 目标.startswith(前端目录) or not os.path.isfile(目标):
        return Response(404, "Not Found", Headers({"Content-Type": "text/plain"}), b"not found")
    with open(目标, "rb") as f:
        体 = f.read()
    头 = Headers({
        "Content-Type": 类型表.get(os.path.splitext(目标)[1].lower(), "application/octet-stream"),
        "Content-Length": str(len(体)),
        "Cache-Control": "no-store",
    })
    return Response(200, "OK", 头, 体)


async def 服务(连接):
    序号 = 0

    async def 发(主题, 数据):
        nonlocal 序号
        序号 += 1
        await 连接.send(帧(主题, 数据, 序号))

    await 连接.send(json.dumps({
        "协议": 协议版本,
        "主题": "__问候__",
        "数据": {"可用主题": 可用主题, "广播间隔": 广播间隔, "契约": 契约全文},
    }, ensure_ascii=False))

    def 项目状态():
        return {
            "项目": "冒烟项目",
            "模型路径": 状态["路径"],
            "模型显示名": 状态["模型"],
            "算法": [
                {"名称": "Joint PD", "版本": "1.0", "接管控制": True},
                {"名称": "Gravity Comp", "版本": "0.3", "接管控制": False},
            ],
            "报告": ["装配 Joint PD → ctrl", "跳过 1 个（模型不兼容）"],
            "算法库": ["Joint PD", "Gravity Comp", "OSC", "Whole Body"],
            "已存盘": False,
            "控盘": "Joint PD",
            "被覆盖": ["Gravity Comp"],
            "重力开": 状态["重力开"],
        }

    await 发("项目状态", 项目状态())

    async def 收命令():
        async for 原文 in 连接:
            try:
                消息 = json.loads(原文)
            except Exception:
                continue
            主题 = 消息.get("主题", "")
            数据 = 消息.get("数据", {})
            if 主题 == "命令.重力":
                状态["重力开"] = bool(数据.get("重力开"))
                说明 = f"重力开={状态['重力开']}（假后端已受理）"
            elif 主题 == "命令.换模型":
                状态["换模型次数"] += 1
                状态["路径"] = str(数据.get("路径", ""))
                # 故意让第二次换模型失败：用来验证"失败要同时进控制台和提示"
                if 状态["换模型次数"] % 2 == 0:
                    说明 = "假后端故意拒绝：这个路径不存在"
                else:
                    说明 = "已加载（假后端）"
            elif 主题 == "命令.辨识":
                说明 = "辨识命令已受理（假后端）"
            elif 主题 == "命令.改参数":
                改动 = 数据.get("改动", {}) or {}
                for 键, 值 in 改动.items():
                    if 键 in 参数值:
                        参数值[键] = float(值)
                说明 = "参数已更新（假后端）"
            else:
                说明 = "这个主题假后端不认识"
            通过 = not 说明.startswith("假后端故意拒绝")
            await 连接.send(json.dumps({
                "协议": 协议版本, "主题": "__回执__",
                "数据": {"主题": 主题, "通过": 通过, "说明": 说明},
            }, ensure_ascii=False))
            await 发("项目状态", 项目状态())

    async def 广播():
        起 = time.time()
        下一指标 = 0.0
        下一参数 = 0.0
        下一模型 = 0.0
        下一辨识 = 0.0
        下一系统 = 0.0
        while True:
            现在 = time.time()
            经过 = 现在 - 起
            if 现在 >= 下一指标:
                下一指标 = 现在 + 1 / 30
                await 发("指标", {
                    "时间": 经过,
                    "墙钟": 现在,
                    "数值": {
                        "joint1·位置": math.sin(经过 * 1.2) * 0.8,
                        "joint1·速度": math.cos(经过 * 1.2) * 0.96,
                        "joint2·位置": math.sin(经过 * 0.7 + 1.0) * 0.4,
                        "actuator1·力矩": math.sin(经过 * 3.0) * 2.5,
                        "sim·实时因子": 0.95 + 0.05 * math.sin(经过 * 0.3),
                    },
                })
            if 现在 >= 下一参数:
                下一参数 = 现在 + 0.1
                # ★ 形状必须与产品一致：`{参数: {"插件名·参数名": 参数项}}`。
                #   早先这里画成了 `{插件: {参数: {...}}}`，界面上只会出现两行 `--`，
                #   参数编辑冒烟也就跟着失败 —— 是夹具漂移，不是产品坏了。
                await 发("参数表", {"参数": {
                    "Joint PD·kp": {
                        "插件": "Joint PD", "插件版本": "1.0", "参数": "kp",
                        "值": 参数值["Joint PD·kp"], "范围": [0.0, 500.0], "步长": 1.0,
                        "单位": "", "说明": "比例增益",
                    },
                    "Joint PD·kd": {
                        "插件": "Joint PD", "插件版本": "1.0", "参数": "kd",
                        "值": 参数值["Joint PD·kd"], "范围": [0.0, 100.0], "步长": 0.5,
                        "单位": "", "说明": "微分增益",
                    },
                    "Joint PD·限幅": {
                        "插件": "Joint PD", "插件版本": "1.0", "参数": "限幅",
                        "值": 参数值["Joint PD·限幅"], "范围": [0.0, 200.0], "步长": 1.0,
                        "单位": "N·m", "说明": "力矩上限",
                    },
                    "OSC·刚度": {
                        "插件": "OSC", "插件版本": "0.3", "参数": "刚度",
                        "值": 参数值["OSC·刚度"], "范围": [10.0, 2000.0], "步长": 10.0,
                        "单位": "N/m", "说明": "笛卡尔刚度",
                    },
                }})
            if 现在 >= 下一模型:
                下一模型 = 现在 + 0.5
                await 发("项目状态", 项目状态())
                await 发("模型状态", {
                    "当前路径": 状态["路径"], "当前显示名": 状态["模型"],
                    "自由度": 7, "执行器数": 7, "状态": "✓ 就绪", "耗时": 0.184,
                })
            if 现在 >= 下一系统:
                下一系统 = 现在 + 1.0
                await 发("系统", {
                    "仿真时间": 经过,
                    "墙钟": 经过,
                    "RTF": 0.97,
                    "步频": 500.0,
                    "仿真步长": 0.002,
                    "内存MB": 280.0,
                    "插件数": 2,
                    "出错": "",
                })
            if 现在 >= 下一辨识:
                下一辨识 = 现在 + 0.2
                await 发("辨识状态", {
                    "状态": "采样中" if 经过 < 6 else "完成",
                    "进度": f"已采 {min(经过, 6.0):.1f} / 6.0 s",
                    "采样步数": int(min(经过, 6.0) * 100),
                    "结果": [
                        {"名称": "joint1.阻尼", "标称": 0.1, "辨识值": 0.137, "变化": "+37%"},
                        {"名称": "joint2.阻尼", "标称": 0.1, "辨识值": 0.094, "变化": "-6%"},
                    ],
                    "拟合": {"前": 3.2e-3, "后": 8.1e-4},
                    "耗时": round(经过, 2),
                    "日志": [f"[{经过:.2f}s] 采样 step={int(经过 * 100)}", "激励：正弦扫频"],
                })
            await asyncio.sleep(广播间隔)

    任务 = [asyncio.create_task(广播()), asyncio.create_task(收命令())]
    try:
        await asyncio.gather(*任务)
    finally:
        for t in 任务:
            t.cancel()


async def 主():
    print(f"假后端：ws + http 都在 {端口}（产物目录 {前端目录}）", flush=True)
    # origins=None：跨源检查关掉。开发时页面在 5273、本对端在 8712，
    # websockets 默认按 Origin 拒绝跨源连接 —— 那不是我们要测的东西。
    async with websockets.serve(服务, "127.0.0.1", 端口, process_request=静态页, origins=None):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(主())
    except KeyboardInterrupt:
        print("假后端：停了", flush=True)
