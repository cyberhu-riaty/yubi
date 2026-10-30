"""验证 GUI 的“加载实验 → 开始 → 自动停止 → 导出”后端闭环。"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
SOFTWARE = ROOT / "软件"
if str(SOFTWARE) not in sys.path:
    sys.path.insert(0, str(SOFTWARE))
os.environ["驭臂_关Web"] = "1"

import experiment_registry  # noqa: E402
import 命令桥  # noqa: E402
import 启动  # noqa: E402
import 插件系统  # noqa: E402


def main() -> int:
    experiment = experiment_registry.experiment_registry.create("ur5e_pd_tracking")
    output_root = ROOT / str(experiment.result.get("directory") or "输出/实验")
    before = {path.resolve() for path in output_root.glob("ur5e_pd_tracking_*")}

    empty_scene = ROOT / "模型" / "空场景.xml"
    registry = 插件系统.安全注册表([], 步进插件=插件系统.固定一步())
    config = 插件系统.viewer_protocol.ViewerConfig(
        title="实验 GUI 闭环自检", width=800, height=600, gfx="")
    启动.请求停止(1.0)
    启动._排空本地队列()                                      # noqa: SLF001
    视口快照数 = [0]
    启动.设状态观察者(lambda _快照: 视口快照数.__setitem__(0, 视口快照数[0] + 1))
    try:
        code = 启动.启动外壳(
            config, str(empty_scene), None, [], registry,
            插件系统.通知模型加载, 项目名="", 无窗=True, 后台线程=True)
        assert code == 0
        ready, reason = 启动.等待就绪(20.0)
        assert ready, reason

        # 默认暂停时只送初始状态，不应让 3D “状态同步”计数空转。
        time.sleep(0.15)
        paused_count = 视口快照数[0]
        time.sleep(0.15)
        assert 视口快照数[0] == paused_count, "暂停时仍在重复发送相同3D状态"

        queue = 启动.取命令队列()
        ok, reason = 命令桥.命令入队(
            queue, "命令.实验", {"动作": "加载", "实验": experiment.key}, 打印=False)
        assert ok, reason
        deadline = time.monotonic() + 15.0
        while os.environ.get("驭臂_当前实验") != experiment.key and time.monotonic() < deadline:
            time.sleep(0.02)
        assert os.environ.get("驭臂_当前实验") == experiment.key, "实验加载命令未生效"

        ok, reason = 命令桥.命令入队(
            queue, "命令.仿真", {"动作": "运行"}, 打印=False)
        assert ok, reason
        deadline = time.monotonic() + 25.0
        created: list[Path] = []
        while time.monotonic() < deadline:
            created = [p for p in output_root.glob("ur5e_pd_tracking_*")
                       if p.resolve() not in before and (p / "metrics.json").is_file()]
            if created:
                break
            time.sleep(0.05)
        assert created, "实验没有自动停止并导出结果"
        latest = max(created, key=lambda p: p.stat().st_mtime)
        for name in ("states.csv", "metrics.json", "curves.html", "experiment.json"):
            assert (latest / name).is_file(), f"缺少结果文件：{name}"
        time.sleep(0.15)
        completed_count = 视口快照数[0]
        time.sleep(0.15)
        assert 视口快照数[0] == completed_count, "实验完成后3D状态同步仍在增长"
        print(f"[PASS] GUI 实验闭环：加载 → 开始 → 自动停止 → 导出\n  {latest}")
        print("[PASS] 暂停/完成后3D状态快照不再重复增长")
        return 0
    finally:
        启动.设状态观察者(None)
        启动.请求停止(5.0)


if __name__ == "__main__":
    raise SystemExit(main())

