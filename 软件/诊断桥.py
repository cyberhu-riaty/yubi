"""
诊断桥.py —— 界面里的「诊断」（P4 · Diagnose）

它解决什么问题：
    这个项目有 **12 套断言**（契约、项目、面板注册表、语言、菜单栏、风格表、
    官方层、平台层、作用域…），但它们只能在终端里跑。
    用户点开软件看到的界面，和"这些东西到底过没过"之间没有任何连接 ——
    于是"我刚改了个东西，还能不能用"只能靠开发者去敲命令。

    这一步把那些断言搬进界面：点一下「开始检查」，把 12 套真跑一遍，逐条报结果。
    **跑的是同一批脚本**（子进程调用 `工具/验证/*.py`），不是另写一份"看起来像检查"的东西 ——
    两套检查迟早会不一致，而不一致的那个一定会在关键时刻骗人。

★ 为什么用子进程而不是 import 进来跑：
    · 那些脚本是**独立可执行**的（有 `--简` 参数、有自己的退出码），
      子进程调用 = 用它们**已经被验证过的那条路**；
    · 更重要的是**隔离**：某个检查脚本自己崩了、卡死了，不会把仿真拖下水。
      卡死有超时兜底。

★ 为什么必须异步 + 后台线程：
    12 套跑完要一两秒。放在仿真循环或窗口线程里同步跑，会明显卡一下
    （物理掉帧、3D 视图冻住）。所以命令只是**起一个线程**，跑完再发结果。
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from 官方层 import messages          # 全部走适配层，见 软件/官方层.py


# ---------------------------------------------------------------------------
# 界面 → 仿真侧
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 诊断命令(messages.Snapshot):
    动作: str = "运行"           # "运行"（目前只有这一个）


# ---------------------------------------------------------------------------
# 仿真侧 → 界面
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 诊断报告(messages.Snapshot):
    运行中: bool = False
    通过: int = 0
    总数: int = 0
    耗时秒: float = 0.0
    时间: str = ""
    # 每项：{名, 通过, 说明, 秒}
    项: tuple = ()
    出错: str = ""


# 要跑的套件。顺序有意：先跑"与运行环境最相关"的，用户最关心。
#   (显示名, 脚本相对路径)
套件表: tuple[tuple[str, str], ...] = (
    ("官方层", "工具/验证/官方层自检.py"),
    ("平台层", "工具/验证/平台层自检.py"),
    ("契约", "工具/验证/契约自检.py"),
    ("项目", "工具/验证/校验项目.py"),
    ("作用域", "工具/验证/作用域自检.py"),
    ("面板注册表", "工具/验证/面板注册表自检.py"),
    ("面板窗", "工具/验证/面板窗自检.py"),
    ("菜单栏", "工具/验证/菜单栏自检.py"),
    ("语言", "工具/验证/语言自检.py"),
    ("风格表", "工具/验证/校验风格表.py"),
    ("轨迹规划", "工具/验证/轨迹规划自检.py"),
    ("参数事务", "工具/验证/参数事务自检.py"),
)

单项超时秒 = 120.0        # 任何一项超时就判失败，别让界面永远"检查中"


def _跑一项(脚本: str, 包根: str) -> tuple[bool, str, float]:
    """跑一个检查脚本，返回 (通过?, 说明, 耗时秒)。"""
    起 = time.perf_counter()
    try:
        # ★ 不猜参数：直接跑脚本的默认行为。
        #   我第一版按脚本名猜着加 `--简`，结果 `校验项目.py` 不认这个参数，
        #   于是"诊断把好脚本报成失败"——诊断自己报假错是最不能接受的那类错。
        结果 = subprocess.run(
            [sys.executable, 脚本],
            cwd=包根, capture_output=True, text=True, timeout=单项超时秒,
        )
    except subprocess.TimeoutExpired:
        return False, f"超时（>{单项超时秒:.0f}s）", time.perf_counter() - 起
    except Exception as 异常:                                         # noqa: BLE001
        return False, f"跑不起来：{type(异常).__name__}: {异常}", time.perf_counter() - 起

    耗时 = time.perf_counter() - 起
    通过 = 结果.returncode == 0

    # 说明：优先取**含结论关键词**的行（那些脚本的结论都带"结果/通过/失败/项"），
    #   取不到才退回最后一行非空。★ 不能只取最后一行 —— 好几个脚本最后一行是
    #   `======` 分隔线，界面上就会显示一整排等号，等于没说。
    行们 = [l.strip() for l in (结果.stdout or "").splitlines() if l.strip()]
    关键词 = ("结果", "通过", "失败", "不含", "不在", "全部")
    候选 = [l for l in 行们 if any(k in l for k in 关键词)]
    说明 = (候选[-1] if 候选 else (行们[-1] if 行们 else ""))
    if not 说明:
        错误行 = [l.strip() for l in (结果.stderr or "").splitlines() if l.strip()]
        说明 = 错误行[-1] if 错误行 else "（没有输出）"
    if len(说明) > 130:
        说明 = 说明[:130] + "…"
    return 通过, 说明, 耗时


def 运行全部(包根: str) -> tuple[list[dict], float]:
    """把 套件表 里每一套真跑一遍。返回 (结果列表, 总耗时)。"""
    起 = time.perf_counter()
    出: list[dict] = []
    for 名, 脚本 in 套件表:
        通过, 说明, 耗时 = _跑一项(脚本, 包根)
        出.append({"名": 名, "通过": 通过, "说明": 说明, "秒": round(耗时, 2)})
    return 出, time.perf_counter() - 起


class 诊断器:
    """收到「诊断命令」就在**后台线程**里跑一遍，跑完发「诊断报告」。

    ★ 它不做节流、不做缓存：诊断是**用户主动点**的低频操作，
      每次都真跑一遍才有意义（缓存住的"上次全绿"会在你真的改坏东西时骗你）。
    """

    def __init__(self, 发送函数: Callable[[Any], None], 包根: str):
        self._发送 = 发送函数
        self._包根 = 包根
        self._线程: threading.Thread | None = None
        self._上次: 诊断报告 | None = None
        self.运行次数 = 0

    # ---- 仿真侧：接命令 ----
    # ★ 必须打 `@messages.handler`：官方按"被这个装饰器标记过 + 类型标注"来发现处理器。
    #   漏了它的话方法就是普通方法 —— 注册表不会调用它，表现为"命令发出去了、
    #   回执也成功，但什么也没发生"（我第一次就漏了，靠实测才抓到）。
    @messages.handler
    def 收命令(self, 命令: 诊断命令) -> bool:
        if str(getattr(命令, "动作", "")) != "运行":
            return False
        self.开始()
        return False        # 不消费：别挡住别的插件

    def 开始(self) -> bool:
        """起一次诊断。已经在跑就不重复起（否则用户连点会开一堆线程）。"""
        if self._线程 is not None and self._线程.is_alive():
            return False
        self._线程 = threading.Thread(target=self._跑, daemon=True, name="诊断线程")
        self._线程.start()
        return True

    def _跑(self) -> None:
        # 先发一条"运行中"，界面据此把按钮变成"检查中…"
        try:
            self._发送(诊断报告(运行中=True,
                             时间=time.strftime("%H:%M:%S"), 出错=""))
        except Exception:                                             # noqa: BLE001
            pass
        项, 耗时 = 运行全部(self._包根)
        通过 = sum(1 for x in 项 if x["通过"])
        报告 = 诊断报告(
            运行中=False,
            通过=int(通过),
            总数=len(项),
            耗时秒=round(耗时, 2),
            时间=time.strftime("%H:%M:%S"),
            项=tuple(项),
            出错="",
        )
        self._上次 = 报告
        self.运行次数 += 1
        try:
            self._发送(报告)
        except Exception as 异常:                                         # noqa: BLE001
            print(f"⚠ 诊断报告发送失败：{type(异常).__name__}: {异常}", flush=True)

    def 重发上次(self) -> None:
        """界面刚连上时补一条（不然要等用户点一次才看得到历史）。"""
        if self._上次 is not None:
            try:
                self._发送(self._上次)
            except Exception:                                         # noqa: BLE001
                pass
