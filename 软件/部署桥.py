"""
部署桥.py —— 「部署」：把当前项目导出成一个**能带走的包**（P4 · Deploy）

★ 先说清楚这一步**不做什么**（否则它就是本项目最容易变成骗人的一格）：

    **不做真机连接。** 这个软件没有设备抽象、没有传输层、没有时间戳/序号/错误码、
    没有安全状态机。所以界面上**没有**"连接"按钮、没有绿灯、没有遥测曲线、
    没有"健康检查 ok" —— 那些在没有任何传输层的情况下只能是假的。
    （`目标功能规格.md` 的"假实现识别清单"里写着：Deploy 页面没有"未接入"状态，
      必是假 —— 因为真部署一定有"没连上"这个状态，而假实现永远显示"已连接"。）

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
    把"没有传输层"写在第一屏，比让他在真机上试半天才发现要强得多。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import time
from typing import Any, Callable

from 官方层 import messages          # 全部走适配层，见 软件/官方层.py


# ---------------------------------------------------------------------------
# 界面 → 仿真侧
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 部署命令(messages.Snapshot):
    动作: str = "导出"           # 目前只认"导出"


# ---------------------------------------------------------------------------
# 仿真侧 → 界面
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 部署状态(messages.Snapshot):
    状态: str = "空闲"           # 空闲 / 导出中 / ✓ 完成 / ✗ 失败
    目录: str = ""
    文件数: int = 0
    字节: int = 0
    时间: str = ""
    # 每项：{文件, 说明, 字节}
    清单: tuple = ()
    说明: str = ""
    出错: str = ""


def _sha256(路径: str) -> str:
    try:
        h = hashlib.sha256()
        with open(路径, "rb") as f:
            for 块 in iter(lambda: f.read(1 << 20), b""):
                h.update(块)
        return h.hexdigest()
    except OSError:
        return "（读不到）"


def _项目目录(包根: str) -> str:
    return os.path.join(包根, "输出", "部署")


def 导出(包根: str, 项目名: str) -> dict:
    """把项目导出成一个包。返回 {目录, 文件数, 字节, 清单[]}；失败抛异常。"""
    import 项目 as _项目

    配置 = _项目.读项目(项目名) if 项目名 else None
    if not 配置:
        raise ValueError(f"读不到项目「{项目名}」")

    时间戳 = time.strftime("%Y%m%d_%H%M%S")
    安全名 = "".join(c for c in (项目名 or "未命名") if c not in '/\\:*?"<>|').strip() or "未命名"
    目标 = os.path.join(_项目目录(包根), f"{安全名}_{时间戳}")
    os.makedirs(目标, exist_ok=True)
    算法目录 = os.path.join(目标, "算法")
    os.makedirs(算法目录, exist_ok=True)

    清单: list[dict] = []

    def 记(文件: str, 说明: str) -> int:
        大小 = os.path.getsize(os.path.join(目标, 文件)) if os.path.exists(
            os.path.join(目标, 文件)) else 0
        清单.append({"文件": 文件, "说明": 说明, "字节": 大小})
        return 大小

    # ① 项目配置原样带走
    with open(os.path.join(目标, "项目.json"), "w", encoding="utf-8") as f:
        json.dump(配置, f, ensure_ascii=False, indent=2)
    记("项目.json", "模型路径 / 算法清单 / 参数")

    # ② 算法源码（真源码，不是名字）
    发现 = {d["插件"]: d for d in _项目.发现的算法()}
    用到 = []
    for 项 in (配置.get("算法") or []):
        名 = str((项 or {}).get("插件") or "") if isinstance(项, dict) else ""
        if 名 and 名 in 发现:
            源 = 发现[名]["文件"]
            if os.path.exists(源):
                shutil.copyfile(源, os.path.join(算法目录, f"{名}.py"))
                记(f"算法/{名}.py", f"算法源码（{名}）")
                用到.append(名)

    # ③ 模型清单（不复制本体，给校验和）
    模型相对 = str(配置.get("模型") or "")
    模型绝对 = _项目.绝对(模型相对) if 模型相对 else ""
    行们 = ["| 文件 | 大小 | sha256 |", "|---|---|---|"]
    for 路径, 标签 in ((模型绝对, "入口模型"),):
        if 路径 and os.path.exists(路径):
            行们.append(f"| `{os.path.basename(路径)}`（{标签}） | "
                       f"{os.path.getsize(路径) / 1024:.0f} KB | `{_sha256(路径)}` |")
        else:
            行们.append(f"| （{标签}缺失） | -- | -- |")
        行们.append("")
        if 路径:
            行们.append(f"相对路径：`{模型相对}`  ")
            行们.append(f"绝对路径（生成时）：`{路径}`  ")
    行们.append("")
    行们.append("> **模型本体没有复制**：单套资产解包后可达 30 MB+，塞进包里不便传输。")
    行们.append("> 请把上表里那个模型文件一并带到真机侧，并用 sha256 核对。")
    with open(os.path.join(目标, "模型清单.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(行们) + "\n")
    记("模型清单.md", "模型文件的路径 / 大小 / sha256")

    # ④ 从这里开始.md —— 第一屏就说清楚"缺什么"
    参数 = 配置.get("参数") or {}
    算法行 = "\n".join(f"- `{n}`" for n in 用到) or "- （这个项目没挂算法）"
    参数行 = ("\n".join(f"- `{插件}`：{len(值表 or {})} 个参数"
                        for 插件, 值表 in 参数.items())
              if isinstance(参数, dict) and 参数 else "- （没有存过参数）")
    说明 = f"""# {项目名 or "未命名"} —— 部署包

生成时间：{time.strftime("%Y-%m-%d %H:%M:%S")}
生成工具：驭臂（小软件）

## 这个包里有什么

| 文件 | 内容 |
|---|---|
| `项目.json` | 模型路径、算法清单、参数（原样，与本机一致） |
| `算法/*.py` | 当前项目用到的算法**源码**（可直接读、可改） |
| `模型清单.md` | 模型文件的路径 / 大小 / sha256 |

算法：
{算法行}

参数：
{参数行}

## ⚠️ 这个包里**没有**什么

- **没有真机传输**。这个软件没有设备抽象、没有 UDP/串口实现、没有安全状态机。
  所以它不会连你的机器人，也不会替你下发指令。
- **没有模型本体**（见 `模型清单.md` 的说明）。

## 下一步要接什么

1. 把 `模型清单.md` 里那个模型文件一起带到真机侧，用 sha256 核对；
2. 读 `算法/*.py` —— 里面是控制律本体（`每步控制()` 每步算一次 `data.ctrl`）；
3. 自己实现一个"读真机状态 → 填 `qpos/qvel` → 调一次 → 把 `ctrl` 下发"的桥。
   这个桥就是本软件**没有**的那一层，必须你自己按真机协议写。

> 之所以把这段写在第一屏：一个只有文件的包，接手的人不知道**什么没有**，
> 会先在真机上试半天才发现缺传输层。
"""
    with open(os.path.join(目标, "从这里开始.md"), "w", encoding="utf-8") as f:
        f.write(说明)
    记("从这里开始.md", "这个包是什么 / 缺什么 / 下一步接什么")

    总字节 = sum(x["字节"] for x in 清单)
    return {"目录": 目标, "文件数": len(清单), "字节": 总字节, "清单": 清单}


class 部署器:
    """收到「部署命令」就导出一个包，然后发「部署状态」。

    ★ 导出是**同步**做的，但很快（只复制几个 .py + 算一次 sha256），
      而且它由命令触发、不是每帧——不值得为它开线程。
      （如果是大模型复制，那就要开线程；这里刻意不复制模型，所以不需要。）
    """

    def __init__(self, 发送函数: Callable[[Any], None], 包根: str):
        self._发送 = 发送函数
        self._包根 = 包根
        self._上次: 部署状态 | None = None
        self.导出次数 = 0

    @messages.handler
    def 收命令(self, 命令: 部署命令) -> bool:
        if str(getattr(命令, "动作", "")) != "导出":
            return False
        self.导出()
        return False

    def 导出(self, 项目名: str = "") -> None:
        # 项目名不给就用当前项目（由外壳在构造时告诉我们的是空，所以这里兜底读设置）
        if not 项目名:
            try:
                import 模型桥 as _模型桥
                项目名 = str(_模型桥.读取设置("上次项目", "") or "")
            except Exception:                                         # noqa: BLE001
                项目名 = ""
        try:
            self._发送(部署状态(状态="导出中", 时间=time.strftime("%H:%M:%S")))
        except Exception:                                             # noqa: BLE001
            pass
        try:
            结果 = 导出(self._包根, 项目名)
            状态 = 部署状态(
                状态="✓ 完成",
                目录=结果["目录"],
                文件数=结果["文件数"],
                字节=结果["字节"],
                时间=time.strftime("%H:%M:%S"),
                清单=tuple(结果["清单"]),
                说明=f"已导出到 {结果['目录']}",
                出错="",
            )
            self.导出次数 += 1
        except Exception as 异常:                                         # noqa: BLE001
            状态 = 部署状态(
                状态="✗ 失败",
                时间=time.strftime("%H:%M:%S"),
                说明="",
                出错=f"{type(异常).__name__}: {异常}",
            )
        self._上次 = 状态
        try:
            self._发送(状态)
        except Exception as 异常:                                         # noqa: BLE001
            print(f"⚠ 部署状态发送失败：{type(异常).__name__}: {异常}", flush=True)
