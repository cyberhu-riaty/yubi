"""
部署桥.py —— 「部署」：把当前项目导出成一个**能带走的包**（P4 · Deploy）

★ 先说清楚这一步**不做什么**（否则它就是本项目最容易变成骗人的一格）：

    **不做真机连接。** 软件有设备抽象、安全层和模拟后端，但没有 UDP/串口/CAN
    协议后端，也没有物理急停。所以部署页的设备控制台永远标明"模拟后端"，
    遥测数字来自真实帧时间戳与后端统计 —— 但那条链路不是你的机器人。

那它做什么：**导出一个可带走的包**。真机部署的第一步永远是"把东西交给别人/搬到另一台机器"，
而这一步是可以做实的、也能验证：

    <项目名>_<时间戳>/
      项目.json          —— 模型路径/算法清单/参数，原样
      算法/<插件>.py     —— 当前项目用到的算法**源码**（不是名字引用）
      模型清单.md        —— 模型文件的路径/大小/sha256（**不复制模型本体**：动辄几十 MB）
      从这里开始.md      —— 这个包是什么、缺什么、下一步要接什么

为什么模型不打包：
    `模型/` 下单个资产解包后可达 30 MB+，塞进部署包会让它难以传输；
    而真机侧需要的是**同一个模型文件**，复制一份不如给出**校验和**——
    对方按 sha256 核对，能确认拿到的就是这一份。

★ 为什么"从这里开始.md"是必需项而不是可选：
    一个只有文件的压缩包，接手的人不知道哪一步该做什么，也不知道**什么没有**。
    把"只有模拟后端"写在第一屏，比让他在真机上试半天才发现要强得多。
"""
from __future__ import annotations

import dataclasses
from wire_compatibility import legacy_wire
import hashlib
import json
import os
import shutil
import time
from typing import Any, Callable

from official_api import messages          # 全部走适配层，见 软件/official_api.py


# ---------------------------------------------------------------------------
# 界面 → 仿真侧
# ---------------------------------------------------------------------------
@legacy_wire('部署命令', {'action': '动作'})
@dataclasses.dataclass(frozen=True)
class DeploymentCommand(messages.Snapshot):
    action: str = "导出"           # 目前只认"导出"


# ---------------------------------------------------------------------------
# 仿真侧 → 界面
# ---------------------------------------------------------------------------
@legacy_wire('部署状态', {'state': '状态', 'directory': '目录', 'file_count': '文件数', 'bytes': '字节', 'time': '时间', 'manifest': '清单', 'description': '说明', 'errors': '出错'})
@dataclasses.dataclass(frozen=True)
class DeploymentState(messages.Snapshot):
    state: str = "空闲"           # 空闲 / 导出中 / ✓ 完成 / ✗ 失败
    directory: str = ""
    file_count: int = 0
    bytes: int = 0
    time: str = ""
    # 每项：{文件, 说明, 字节}
    manifest: tuple = ()
    description: str = ""
    errors: str = ""


def _sha256(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "（读不到）"


def _deployment_directory(package_root: str) -> str:
    return os.path.join(package_root, "输出", "部署")


def export(package_root: str, project_name: str) -> dict:
    """把项目导出成一个包。返回 {目录, 文件数, 字节, 清单[]}；失败抛异常。"""
    import project_registry as _project

    config = _project.load_project(project_name) if project_name else None
    if not config:
        raise ValueError(f"读不到项目「{project_name}」")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in (project_name or "未命名") if c not in '/\\:*?"<>|').strip() or "未命名"
    target = os.path.join(_deployment_directory(package_root), f'{safe_name}_{timestamp}')
    os.makedirs(target, exist_ok=True)
    algorithm_directory = os.path.join(target, "算法")
    os.makedirs(algorithm_directory, exist_ok=True)

    manifest: list[dict] = []

    def record(file: str, description: str) -> int:
        size = os.path.getsize(os.path.join(target, file)) if os.path.exists(
            os.path.join(target, file)) else 0
        manifest.append({"文件": file, "说明": description, "字节": size})
        return size

    # ① 项目配置原样带走
    with open(os.path.join(target, "项目.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    record("项目.json", "模型路径 / 算法清单 / 参数")

    # ② 算法源码（真源码，不是名字）
    discovered = {d["plugin"]: d for d in _project.discover_algorithms()}
    used_plugins = []
    for items in (config.get("algorithms") or []):
        name = str((items or {}).get("plugin") or "") if isinstance(items, dict) else ""
        if name and name in discovered:
            source = discovered[name]["file"]
            if os.path.exists(source):
                shutil.copyfile(source, os.path.join(algorithm_directory, f"{name}.py"))
                record(f"算法/{name}.py", f"算法源码（{name}）")
                used_plugins.append(name)

    # ③ 模型清单（不复制本体，给校验和）
    relative_model_path = str(config.get("model") or "")
    absolute_model_path = _project.absolute_path(relative_model_path) if relative_model_path else ""
    lines = ["| 文件 | 大小 | sha256 |", "|---|---|---|"]
    for path, label in ((absolute_model_path, "入口模型"),):
        if path and os.path.exists(path):
            lines.append(f'| `{os.path.basename(path)}`（{label}） | '
                       f'{os.path.getsize(path) / 1024:.0f} KB | `{_sha256(path)}` |')
        else:
            lines.append(f'| （{label}缺失） | -- | -- |')
        lines.append("")
        if path:
            lines.append(f'相对路径：`{relative_model_path}`  ')
            lines.append(f'绝对路径（生成时）：`{path}`  ')
    lines.append("")
    lines.append("> **模型本体没有复制**：单套资产解包后可达 30 MB+，塞进包里不便传输。")
    lines.append("> 请把上表里那个模型文件一并带到真机侧，并用 sha256 核对。")
    with open(os.path.join(target, "模型清单.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    record("模型清单.md", "模型文件的路径 / 大小 / sha256")

    # ④ 从这里开始.md —— 第一屏就说清楚"缺什么"
    parameters = config.get("parameters") or {}
    algorithm_lines = "\n".join(f"- `{n}`" for n in used_plugins) or "- （这个项目没挂算法）"
    parameter_lines = ("\n".join(f'- `{plugins}`：{len(values or {})} 个参数'
                        for plugins, values in parameters.items())
              if isinstance(parameters, dict) and parameters else "- （没有存过参数）")
    description = f"# {project_name or '未命名'} —— 部署包\n\n生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n生成工具：驭臂（小软件）\n\n## 这个包里有什么\n\n| 文件 | 内容 |\n|---|---|\n| `项目.json` | 模型路径、算法清单、参数（原样，与本机一致） |\n| `算法/*.py` | 当前项目用到的算法**源码**（可直接读、可改） |\n| `模型清单.md` | 模型文件的路径 / 大小 / sha256 |\n\n算法：\n{algorithm_lines}\n\n参数：\n{parameter_lines}\n\n## ⚠️ 这个包里**没有**什么\n\n- **没有真机协议后端**。软件有设备抽象、安全层与模拟后端，但没有 UDP/串口/CAN\n  实现，也没有物理急停。所以它不会连你的机器人，也不会替你下发指令。\n- **没有模型本体**（见 `模型清单.md` 的说明）。\n\n## 下一步要接什么\n\n1. 把 `模型清单.md` 里那个模型文件一起带到真机侧，用 sha256 核对；\n2. 读 `算法/*.py` —— 里面是控制律本体（`每步控制()` 每步算一次 `data.ctrl`）；\n3. 参照 `软件/设备/契约.py` 实现一个协议后端：读真机状态 → 填状态帧 →\n   走安全层的限幅与看门狗 → 把 `ctrl` 下发；\n4. 真机必须另做硬件看门狗与独立的物理急停回路，不能只依赖软件。\n\n> 之所以把这段写在第一屏：一个只有文件的包，接手的人不知道**什么没有**，\n> 会先在真机上试半天才发现缺协议后端。\n"
    with open(os.path.join(target, "从这里开始.md"), "w", encoding="utf-8") as f:
        f.write(description)
    record("从这里开始.md", "这个包是什么 / 缺什么 / 下一步接什么")

    total_bytes = sum(x["字节"] for x in manifest)
    return {"目录": target, "文件数": len(manifest), "字节": total_bytes, "清单": manifest}


class Deployer:
    """收到「部署命令」就导出一个包，然后发「部署状态」。

    ★ 导出是**同步**做的，但很快（只复制几个 .py + 算一次 sha256），
      而且它由命令触发、不是每帧——不值得为它开线程。
      （如果是大模型复制，那就要开线程；这里刻意不复制模型，所以不需要。）
    """

    def __init__(self, send: Callable[[Any], None], package_root: str):
        self._send = send
        self._package_root = package_root
        self._last_report: DeploymentState | None = None
        self.export_count = 0

    @messages.handler
    def receive_command(self, command: DeploymentCommand) -> bool:
        if str(getattr(command, "action", "")) != "导出":
            return False
        self.export()
        return False

    def export(self, project_name: str = "") -> None:
        # 项目名不给就用当前项目（由外壳在构造时告诉我们的是空，所以这里兜底读设置）
        if not project_name:
            try:
                import model_bridge as _model_bridge
                project_name = str(_model_bridge.read_setting("上次项目", "") or "")
            except Exception:                                         # noqa: BLE001
                project_name = ""
        try:
            self._send(DeploymentState(state="导出中", time=time.strftime("%H:%M:%S")))
        except Exception:                                             # noqa: BLE001
            pass
        try:
            result = export(self._package_root, project_name)
            state = DeploymentState(
                state="✓ 完成",
                directory=result["目录"],
                file_count=result["文件数"],
                bytes=result["字节"],
                time=time.strftime("%H:%M:%S"),
                manifest=tuple(result["清单"]),
                description=f"已导出到 {result['目录']}",
                errors="",
            )
            self.export_count += 1
        except Exception as exc:                                         # noqa: BLE001
            state = DeploymentState(
                state="✗ 失败",
                time=time.strftime("%H:%M:%S"),
                description="",
                errors=f"{type(exc).__name__}: {exc}",
            )
        self._last_report = state
        try:
            self._send(state)
        except Exception as exc:                                         # noqa: BLE001
            print(f"⚠ 部署状态发送失败：{type(exc).__name__}: {exc}", flush=True)

WIRE_CLASS_ALIASES = {'DeploymentState': '部署状态', 'DeploymentCommand': '部署命令'}
