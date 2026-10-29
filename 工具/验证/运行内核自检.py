"""运行内核自检：线程安全队列、就绪信号和可控退出。"""
from __future__ import annotations

import os
from pathlib import Path
import queue
import sys
import threading


包根 = Path(__file__).resolve().parents[2]
软件目录 = 包根 / "软件"
if str(软件目录) not in sys.path:
    sys.path.insert(0, str(软件目录))

# 自检不占 Web 端口，也不创建窗口。
os.environ["驭臂_关Web"] = "1"

import 控制台  # noqa: E402

控制台.准备输出()

import 启动  # noqa: E402
import 插件系统  # noqa: E402
import 命令桥  # noqa: E402
import 重力桥  # noqa: E402


def 检查队列() -> None:
    待测 = 启动.取命令队列()
    assert isinstance(待测, queue.Queue), "本地命令通道必须使用线程安全 Queue"
    启动._排空本地队列()

    def 生产者(编号: int) -> None:
        for 序号 in range(200):
            待测.put_nowait((编号, 序号))

    线程们 = [threading.Thread(target=生产者, args=(编号,)) for 编号 in range(4)]
    for 线程 in 线程们:
        线程.start()
    for 线程 in 线程们:
        线程.join()

    结果 = 启动._排空本地队列()
    assert len(结果) == 800, f"并发入队后应收到 800 条，实际 {len(结果)}"
    assert len(set(结果)) == 800, "队列中出现重复或丢失"

    好, 说明 = 命令桥.命令入队(待测, "命令.重力", {"重力开": False}, 打印=False)
    assert 好, 说明
    好, 说明 = 命令桥.命令入队(待测, "命令.仿真", {"动作": "暂停"}, 打印=False)
    assert 好, 说明
    assert len(启动._排空本地队列()) == 2, "Web 命令没有进入线程安全队列"


def 检查仿真控制语义() -> None:
    复位调用: list[str] = []
    状态调用: list[str] = []
    应用器 = 重力桥.重力应用器(
        仿真复位回调=lambda: (复位调用.append("reset") or "已重建算法"),
        状态回调=lambda: 状态调用.append("state"),
    )
    # 单元检查不需要真的向官方 StepControl 发快照；这里只验证三种动作的状态语义。
    应用器._发官方暂停 = lambda 暂停: None                       # noqa: SLF001

    应用器.收仿真控制(重力桥.仿真控制命令(动作="运行"))
    assert 应用器.运行中, "Run 应打开步进闸门"
    assert not 复位调用, "Run 不应触发复位"

    应用器.收仿真控制(重力桥.仿真控制命令(动作="暂停"))
    assert not 应用器.运行中, "Pause 应关闭步进闸门"
    assert not 复位调用, "Pause 必须保持当前位置，不能偷偷复位"

    应用器.收仿真控制(重力桥.仿真控制命令(动作="复位"))
    assert not 应用器.运行中, "Reset 后应保持暂停"
    assert 复位调用 == ["reset"], "Reset 应且只应重建当前算法一次"
    assert 应用器.复位次数 == 1, "Reset 次数没有记账"
    assert len(状态调用) == 3, "每个动作都应主动回报一次真实状态"

    已发 = []
    发布器 = 重力桥.仿真状态发布器(已发.append)
    assert 发布器.发布(应用器, 0.0, 强制=True)
    assert 已发[-1].状态 == "暂停" and 已发[-1].仿真时间 == 0.0


def 检查生命周期() -> None:
    模型路径 = 包根 / "模型" / "空场景.xml"
    assert 模型路径.is_file(), f"缺少自检模型：{模型路径}"

    # 模型加载会正常地记住“上次模型”。自检不能改变用户下一次启动时的选择，
    # 所以完整保存并恢复这个本地设置文件。
    设置路径 = 包根 / "输出" / "设置.json"
    原设置 = 设置路径.read_bytes() if 设置路径.exists() else None

    try:
        注册表 = 插件系统.安全注册表([])
        配置 = 插件系统.viewer_protocol.ViewerConfig(
            title="运行内核自检", width=640, height=480, gfx="")
        码 = 启动.启动外壳(
            配置, str(模型路径), None, [], 注册表,
            插件系统.通知模型加载, 项目名="", 无窗=True, 后台线程=True)
        assert 码 == 0, f"后台仿真启动返回 {码}"

        好, 说明 = 启动.等待就绪(10.0)
        assert 好, 说明
        好, 说明 = 启动.请求停止(3.0)
        assert 好, 说明
    finally:
        启动.请求停止(3.0)
        if 原设置 is None:
            设置路径.unlink(missing_ok=True)
        else:
            设置路径.parent.mkdir(parents=True, exist_ok=True)
            设置路径.write_bytes(原设置)


def main() -> int:
    检查队列()
    print("[PASS] 线程安全命令队列")
    检查仿真控制语义()
    print("[PASS] Run / Pause / Reset 语义")
    检查生命周期()
    print("[PASS] 仿真就绪信号与可控退出")
    print("运行内核自检：3 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
