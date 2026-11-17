"""
诊断桥.py —— 界面里的「诊断」（P4 · Diagnose）

它解决什么问题：
    这个项目有 **11 套断言**（契约、项目、语言、风格表、
    官方层、平台层、作用域…），但它们只能在终端里跑。
    用户点开软件看到的界面，和"这些东西到底过没过"之间没有任何连接 ——
    于是"我刚改了个东西，还能不能用"只能靠开发者去敲命令。

    这一步把那些断言搬进界面：点一下「开始检查」，把 11 套真跑一遍，逐条报结果。
    **跑的是同一批脚本**（子进程调用 `tools/selfchecks/*.py`），不是另写一份"看起来像检查"的东西 ——
    两套检查迟早会不一致，而不一致的那个一定会在关键时刻骗人。

★ 为什么用子进程而不是 import 进来跑：
    · 那些脚本是**独立可执行**的（有 `--简` 参数、有自己的退出码），
      子进程调用 = 用它们**已经被验证过的那条路**；
    · 更重要的是**隔离**：某个检查脚本自己崩了、卡死了，不会把仿真拖下水。
      卡死有超时兜底。

★ 为什么必须异步 + 后台线程：
    11 套跑完要一两秒。放在仿真循环或窗口线程里同步跑，会明显卡一下
    （物理掉帧、3D 视图冻住）。所以命令只是**起一个线程**，跑完再发结果。
"""
from __future__ import annotations

import dataclasses
from wire_compatibility import legacy_wire
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from official_api import messages          # 全部走适配层，见 runtime/official_api.py


# ---------------------------------------------------------------------------
# 界面 → 仿真侧
# ---------------------------------------------------------------------------
@legacy_wire('诊断命令', {'action': '动作'})
@dataclasses.dataclass(frozen=True)
class DiagnosticsCommand(messages.Snapshot):
    action: str = "运行"           # "运行"（目前只有这一个）


# ---------------------------------------------------------------------------
# 仿真侧 → 界面
# ---------------------------------------------------------------------------
@legacy_wire('诊断报告', {'running': '运行中', 'passed': '通过', 'total': '总数', 'elapsed_seconds': '耗时秒', 'time': '时间', 'items': '项', 'errors': '出错'})
@dataclasses.dataclass(frozen=True)
class DiagnosticsReport(messages.Snapshot):
    running: bool = False
    passed: int = 0
    total: int = 0
    elapsed_seconds: float = 0.0
    time: str = ""
    # 每项：{名, 通过, 说明, 秒}
    items: tuple = ()
    errors: str = ""


# 要跑的套件。顺序有意：先跑"与运行环境最相关"的，用户最关心。
#   (显示名, 脚本相对路径)
SUITES: tuple[tuple[str, str], ...] = (
    ("官方层", "tools/selfchecks/official_api_selfcheck.py"),
    ("平台层", "tools/selfchecks/platform_selfcheck.py"),
    ("契约", "tools/selfchecks/contract_selfcheck.py"),
    ("项目", "tools/selfchecks/project_selfcheck.py"),
    ("作用域", "tools/selfchecks/scope_selfcheck.py"),
    ("语言", "tools/selfchecks/language_selfcheck.py"),
    ("风格表", "tools/selfchecks/theme_selfcheck.py"),
    ("轨迹规划", "tools/selfchecks/trajectory_planning_selfcheck.py"),
    ("参数事务", "tools/selfchecks/parameter_transaction_selfcheck.py"),
    ("病态检出", "tools/selfchecks/observation_selfcheck.py"),
    ("设备契约", "tools/selfchecks/device_contract_selfcheck.py"),
)

SUITE_TIMEOUT_SECONDS = 120.0        # 任何一项超时就判失败，别让界面永远"检查中"


def _run_suite(script: str, package_root: str) -> tuple[bool, str, float]:
    """跑一个检查脚本，返回 (通过?, 说明, 耗时秒)。"""
    started_at = time.perf_counter()
    try:
        # ★ 不猜参数：直接跑脚本的默认行为。
        #   我第一版按脚本名猜着加 `--简`，结果 `project_selfcheck.py` 不认这个参数，
        #   于是"诊断把好脚本报成失败"——诊断自己报假错是最不能接受的那类错。
        result = subprocess.run(
            [sys.executable, "-X", "utf8", script],
            cwd=package_root, capture_output=True, encoding="utf-8", timeout=SUITE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f'超时（>{SUITE_TIMEOUT_SECONDS:.0f}s）', time.perf_counter() - started_at
    except Exception as exc:                                         # noqa: BLE001
        return False, f"跑不起来：{type(exc).__name__}: {exc}", time.perf_counter() - started_at

    elapsed_time = time.perf_counter() - started_at
    passed = result.returncode == 0

    # 说明：优先取**含结论关键词**的行（那些脚本的结论都带"结果/通过/失败/项"），
    #   取不到才退回最后一行非空。★ 不能只取最后一行 —— 好几个脚本最后一行是
    #   `======` 分隔线，界面上就会显示一整排等号，等于没说。
    lines = [l.strip() for l in (result.stdout or "").splitlines() if l.strip()]
    keywords = ("结果", "通过", "失败", "不含", "不在", "全部")
    candidates = [l for l in lines if any(k in l for k in keywords)]
    description = (candidates[-1] if candidates else (lines[-1] if lines else ""))
    if not description:
        error_lines = [l.strip() for l in (result.stderr or "").splitlines() if l.strip()]
        description = error_lines[-1] if error_lines else "（没有输出）"
    if len(description) > 130:
        description = description[:130] + "…"
    return passed, description, elapsed_time


def run_all(package_root: str) -> tuple[list[dict], float]:
    """把 套件表 里每一套真跑一遍。返回 (结果列表, 总耗时)。"""
    started_at = time.perf_counter()
    output: list[dict] = []
    for name, script in SUITES:
        passed, description, elapsed_time = _run_suite(script, package_root)
        output.append({"名": name, "通过": passed, "说明": description, "秒": round(elapsed_time, 2)})
    return output, time.perf_counter() - started_at


class DiagnosticsRunner:
    """收到「诊断命令」就在**后台线程**里跑一遍，跑完发「诊断报告」。

    ★ 它不做节流、不做缓存：诊断是**用户主动点**的低频操作，
      每次都真跑一遍才有意义（缓存住的"上次全绿"会在你真的改坏东西时骗你）。
    """

    def __init__(self, send: Callable[[Any], None], package_root: str):
        self._send = send
        self._package_root = package_root
        self._thread: threading.Thread | None = None
        self._last_report: DiagnosticsReport | None = None
        self.run_count = 0

    # ---- 仿真侧：接命令 ----
    # ★ 必须打 `@messages.handler`：官方按"被这个装饰器标记过 + 类型标注"来发现处理器。
    #   漏了它的话方法就是普通方法 —— 注册表不会调用它，表现为"命令发出去了、
    #   回执也成功，但什么也没发生"（我第一次就漏了，靠实测才抓到）。
    @messages.handler
    def receive_command(self, command: DiagnosticsCommand) -> bool:
        if str(getattr(command, "action", "")) != "运行":
            return False
        self.start()
        return False        # 不消费：别挡住别的插件

    def start(self) -> bool:
        """起一次诊断。已经在跑就不重复起（否则用户连点会开一堆线程）。"""
        if self._thread is not None and self._thread.is_alive():
            return False
        self._thread = threading.Thread(target=self._run, daemon=True, name="诊断线程")
        self._thread.start()
        return True

    def _run(self) -> None:
        # 先发一条"运行中"，界面据此把按钮变成"检查中…"
        try:
            self._send(DiagnosticsReport(running=True,
                             time=time.strftime("%H:%M:%S"), errors=""))
        except Exception:                                             # noqa: BLE001
            pass
        items, elapsed_time = run_all(self._package_root)
        passed = sum(1 for x in items if x["通过"])
        report = DiagnosticsReport(
            running=False,
            passed=int(passed),
            total=len(items),
            elapsed_seconds=round(elapsed_time, 2),
            time=time.strftime("%H:%M:%S"),
            items=tuple(items),
            errors="",
        )
        self._last_report = report
        self.run_count += 1
        try:
            self._send(report)
        except Exception as exc:                                         # noqa: BLE001
            print(f"⚠ 诊断报告发送失败：{type(exc).__name__}: {exc}", flush=True)

    def resend_last(self) -> None:
        """界面刚连上时补一条（不然要等用户点一次才看得到历史）。"""
        if self._last_report is not None:
            try:
                self._send(self._last_report)
            except Exception:                                         # noqa: BLE001
                pass

WIRE_CLASS_ALIASES = {'DiagnosticsReport': '诊断报告', 'DiagnosticsCommand': '诊断命令'}
