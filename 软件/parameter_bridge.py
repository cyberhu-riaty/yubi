"""
parameter_bridge.py —— 把界面滑杆的值送回插件（控制器参数面板）

数据流向（和"指标"正好相反）：
    指标：  插件 → 外壳 → 界面（画曲线）
    参数：  界面 → 外壳 → 插件（改参数）

为什么不用直接调用：
    界面（viewer 侧）和插件（仿真侧）在两个线程/两个"世界"里，
    只能靠消息通信。所以定义一条参数消息：
        面板发 `ParameterUpdate` → `ParameterApplier` → 插件的 set_parameter()

插件侧要做什么（就一步）：
    声明哪些类属性可以调，界面就会自动出现滑杆：

        def adjustable_parameters(self) -> dict:
            return {"KP": {"value": self.KP, "range": (10.0, 20000.0)},
                    "KD": {"value": self.KD, "range": (0.0, 500.0)}}
"""
from __future__ import annotations

import dataclasses
import time
from typing import Any

from official_api import messages


def _plugin_name(plugin: Any) -> str:
    return str(getattr(plugin, "name", None) or "")


def _plugin_english_name(plugin: Any) -> str:
    return str(getattr(plugin, "english_name", None) or "")


def _plugin_version(plugin: Any) -> str:
    return str(getattr(plugin, "version", None) or "-")


def _adjustable_parameters(plugin: Any) -> dict:
    query = getattr(plugin, "adjustable_parameters", None)
    return dict(query() or {}) if callable(query) else {}


def _set_parameter(plugin: Any, name: str, value: float):
    setter = getattr(plugin, "set_parameter", None)
    if not callable(setter):
        return f"插件【{_plugin_name(plugin) or type(plugin).__name__}】不支持参数修改"
    return setter(name, value)


@dataclasses.dataclass(frozen=True)
class ParameterTable(messages.Snapshot):
    """仿真侧 → 界面：当前所有可调参数（值 + 范围）。

    为什么是 Snapshot：滑杆只需要"最新状态"，旧的不排队正合适。
    """

    parameters: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class ParameterUpdate(messages.Snapshot):
    """界面 → 仿真侧：这一帧被拖动过的参数。

    Snapshot 语义（只保留最新一条）在这里正合适：
    拖动滑杆会连续产生很多条，旧的没处理也无所谓 —— 最新值才是要的。
    """

    updates: dict = dataclasses.field(default_factory=dict)   # {参数名: 新值}


def collect_parameters(registry) -> dict[str, dict]:
    """向每个插件问一次"你有哪些可调参数"，合并成一张表。

    同名参数（比如两个插件都有 KP）会带上插件名前缀区分：
        "关节 PD 位置控制·KP"
    这样界面上不会互相串。

    ★ 只问**有 `名称` 的**对象，也就是项目声明的那些用户算法：
      注册表里还混着 StepControl / 模型应用器 / 参数应用器这些内部插件，
      它们不该出现在参数面板上（虽然它们本来也没实现 adjustable_parameters()，
      但靠"恰好没实现"来保证正确性太脆 —— 显式跳过更稳）。

    ★ 每个插件名后面缀上它的**版本号**也很重要：换项目时算法可能同名不同版本
      （比如 `算法库/实验/关节pd控制.py` 与 `算法库/通用/关节pd控制.py`），
      面板上要能看出来现在挂的是哪一个。
    """
    table: dict[str, dict] = {}
    for plugin in getattr(registry, "_目标", []):
        name = _plugin_name(plugin)
        if not name:
            continue
        if not callable(getattr(plugin, "adjustable_parameters", None)):
            continue
        name = str(name)
        english_name = _plugin_english_name(plugin)
        try:
            items = _adjustable_parameters(plugin)
        except Exception as exc:                                     # noqa: BLE001
            print(f"⚠ 插件【{name}】的 adjustable_parameters() 出错（已跳过）：{type(exc).__name__}: {exc}")
            continue
        for parameter_name, info in items.items():
            value_range = info.get("range") or (0.0, 1.0)
            table[f"{name}·{parameter_name}"] = {
                "plugin": name,
                "plugin_english": english_name,
                "plugin_version": _plugin_version(plugin),
                "parameter": parameter_name,
                "value": float(info.get("value", 0.0)),
                "range": (float(value_range[0]), float(value_range[1])),
                "step": float(info.get("step", 0.0)),
                "unit": str(info.get("unit", "")),
            }
    return table


@dataclasses.dataclass(frozen=True)
class ParameterTransactionCommand(messages.Snapshot):
    """界面 → 仿真侧：**一次性**应用一组参数（事务语义）。

    ★ 为什么需要它（单条 `参数消息` 做不到的事）：
      单条消息是"改一个算一个"。用户在参数表里改了 8 个值然后点"应用"，
      如果第 5 个非法，前 4 个已经生效了 —— 机器人就处在**一个谁也没想要**的
      中间状态。真机上这是危险的（比如 KP 已改而 KD 没改，会直接振荡）。
      所以这一条要求：**全成功，或者一个都不动**。
    """
    action: str = "apply"
    parameters: tuple = ()            # ((全名, 值), ...) —— 用元组保证可哈希、可比较


@dataclasses.dataclass(frozen=True)
class ParameterTransactionResult(messages.Snapshot):
    """仿真侧 → 界面：这次事务到底做成了什么。"""
    state: str = "idle"          # idle / committed / rolled_back
    success_count: int = 0
    failure_count: int = 0
    timestamp: str = ""
    # 每项：{全名, 旧值, 新值}
    changes: tuple = ()
    # 失败原因（给人看的，逐条）
    failures: tuple = ()
    description: str = ""


class ParameterApplier:
    """仿真侧：收到参数消息后，把它转给对应插件的 set_parameter()。

    插件的 每步控制() 读的是自己的类属性，所以改完**下一次步进就生效**，
    不需要插件写任何接收代码。

    ★ 方案 C 之后它还负责**把参数存回项目文件**（`参数存盘` 回调）：
      以前拖出来的值只活在内存里，换项目/重启就没了。存进项目文件之后，
      "这一组参数"成了实验记录的一部分（录制元信息里也会记下当时的参数值）。
    """

    def __init__(self, persist_parameters=None):
        self.applied_count = 0
        self.latest = {}
        self.errors: list[str] = []
        self._plugin_by_name = {}
        # 存盘回调：(插件名, {参数名: 值}) -> None。由外壳注入（它知道"当前是哪个项目"）。
        self._persist_parameters = persist_parameters

    def rebind(self, registry) -> "ParameterApplier":
        """`绑定` 的别名 —— 强调"换了一组算法之后要重新绑一次"这件事。

        ★ 保留 `绑定` 这个名字是为了不破坏已有调用（外壳启动时用的是它）。
          两个名字指向同一件事：把"插件名 → 实例"这本账重新拍一遍。
          详见 `绑定()` 的说明（不重绑会导致滑杆静默失效）。
        """
        return self.bind(registry)

    def bind(self, registry) -> "ParameterApplier":
        """记住插件实例，便于按名字找。**换项目 / 换一组算法之后必须再调一次。**

        ★ 为什么这是必须的（原来漏掉的一步）：
          这里把"插件名 → 实例"拍成一张快照。方案 C 之前插件集合启动后永不改变，
          所以绑定一次就够；现在点模型会换掉整组算法 —— 如果不再绑一次，
          下面 `收参数()` 里 `self._插件名到实例.get(插件名)` 会拿到**旧实例**（或 None），
          结果是：滑杆拖了没反应，而且**一句提示都没有**（`实例 is None` 时直接 continue）。
          这种"静默失效"比抛异常难查得多，所以**绑定必须和装配成对出现**。

        绑定时跳过没有 `名称` 的对象（注册表里混着 StepControl / 模型应用器 /
        参数应用器自己这些内部插件，它们本来也不该出现在参数面板上）。
        """
        self._plugin_by_name = {
            _plugin_name(p): p
            for p in getattr(registry, "_目标", [])
            if _plugin_name(p)
        }
        return self

    @messages.handler
    def on_update(self, message: ParameterUpdate) -> bool:
        updates = getattr(message, "updates", None) or {}
        grouped_by_plugin: dict[str, dict] = {}
        for full_name, value in updates.items():
            plugin_name, _, parameter_name = full_name.partition("·")
            plugin = self._plugin_by_name.get(plugin_name)
            if plugin is None:
                # ★ 不再静默 continue：换项目/换算法组之后如果忘了重绑，
                #   这里就是"滑杆拖了没反应"的地方 —— 至少要说一声。
                print(f"ℹ 参数「{full_name}」没有对应的算法实例（当前这一组里没有【{plugin_name}】）—— "
                      f"已忽略；如果刚换过模型，这是正常的（那个算法不在本项目里）")
                continue
            error = _set_parameter(plugin, parameter_name, float(value))
            if error:
                if error not in self.errors:
                    self.errors.append(error)
                    print(f"⚠ {error}")
                continue
            self.applied_count += 1
            self.latest[full_name] = float(value)
            grouped_by_plugin.setdefault(plugin_name, {})[parameter_name] = float(value)

        # 存回项目文件（"上次调好的参数"要能延续到下次打开这个项目）
        if grouped_by_plugin and self._persist_parameters is not None:
            for plugin_name, values in grouped_by_plugin.items():
                try:
                    self._persist_parameters(plugin_name, values)
                except Exception as exc:                                  # noqa: BLE001
                    if "persistence" not in getattr(self, "_persistence_errors_reported", set()):
                        self._persistence_errors_reported = (
                            getattr(self, "_persistence_errors_reported", set()) | {"persistence"}
                        )
                        print(f"⚠ 参数存盘失败（参数已生效，只是没记住）："
                              f"{type(exc).__name__}: {exc}")
        return False


    # ------------------------------------------------------------------
    # 事务式批量应用（全成功，或一个都不动）
    # ------------------------------------------------------------------
    @messages.handler
    def on_transaction(self, command: ParameterTransactionCommand) -> bool:
        if str(getattr(command, "action", "")) != "apply":
            return False
        # ★ 契约里 `参数` 是 object[]，每项 `{全名, 值}`（能被 JSON Schema 描述的写法）。
        #   但内部/测试里也会写成 dict 或 (全名, 值) 元组 —— 三种都接。
        #   第一版只认元组，于是 Web 发来的对象数组被当成"空改动"，
        #   报出"当前这组算法里没有【全名】"这种让人摸不着头脑的错。
        updates: dict[str, Any] = {}
        for item in (getattr(command, "parameters", None) or ()):
            if isinstance(item, dict):
                name = str(item.get("full_name") or "")
                if name:
                    updates[name] = item.get("value")
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                updates[str(item[0])] = item[1]
        if not updates:
            self._publish_transaction(ParameterTransactionResult(state="rolled_back", timestamp=time.strftime("%H:%M:%S"),
                                     description="没有要改的参数"))
            return False

        # ── 第一步：**预检**（一个都不写）。这一步是事务能成立的关键。
        plan: list[tuple[Any, str, str, float, float]] = []
        failures: list[str] = []
        for full_name, requested_value in updates.items():
            plugin_name, _, parameter_name = str(full_name).partition("·")
            plugin = self._plugin_by_name.get(plugin_name)
            if plugin is None:
                failures.append(f"{full_name}：当前这组算法里没有【{plugin_name}】")
                continue
            try:
                table = _adjustable_parameters(plugin)
            except Exception as exc:                                     # noqa: BLE001
                failures.append(f"{full_name}：读不到参数表（{type(exc).__name__}）")
                continue
            declaration = table.get(parameter_name)
            if not isinstance(declaration, dict):
                failures.append(f"{full_name}：插件没有声明这个参数")
                continue
            old_value = float(declaration.get("value", 0.0))
            try:
                new_value = float(requested_value)
            except (TypeError, ValueError):
                failures.append(f"{full_name}：{requested_value!r} 不是数字")
                continue
            value_range = declaration.get("range")
            if isinstance(value_range, (tuple, list)) and len(value_range) == 2:
                low, high = float(value_range[0]), float(value_range[1])
                if not (low <= new_value <= high):
                    failures.append(f"{full_name}：{new_value:g} 超出范围 [{low:g}, {high:g}]")
                    continue
            plan.append((plugin, str(full_name), parameter_name, old_value, new_value))

        # 任何一条不合格 → 一个都不写（这正是"事务"的意思）
        if failures or not plan:
            self._publish_transaction(ParameterTransactionResult(
                state="rolled_back", failure_count=len(failures), failures=tuple(failures),
                timestamp=time.strftime("%H:%M:%S"),
                description="预检未通过，所有参数保持原值"))
            for line in failures:
                print(f"⚠ 参数事务被拒：{line}", flush=True)
            return False

        # ── 第二步：逐个写；**任何一步失败就把已写的退回去**
        written: list[tuple[Any, str, float]] = []
        changes: list[dict] = []
        grouped_by_plugin: dict[str, dict] = {}
        for plugin, full_name, parameter_name, old_value, new_value in plan:
            error = _set_parameter(plugin, parameter_name, new_value)
            if error:
                failures.append(f"{full_name}：{error}")
                break
            written.append((plugin, parameter_name, old_value))
            changes.append({"full_name": full_name, "old_value": old_value, "new_value": new_value})
            self.applied_count += 1
            self.latest[full_name] = new_value
            grouped_by_plugin.setdefault(full_name.partition("·")[0], {})[parameter_name] = new_value

        if failures:
            # 回滚：按**写入顺序的逆序**退回，保证互相依赖的参数也回到一致状态
            rollback_failures = []
            for plugin, parameter_name, old_value in reversed(written):
                try:
                    if _set_parameter(plugin, parameter_name, old_value):
                        rollback_failures.append(parameter_name)
                except Exception:                                         # noqa: BLE001
                    rollback_failures.append(parameter_name)
            self._publish_transaction(ParameterTransactionResult(
                state="rolled_back", success_count=len(written) - len(rollback_failures), failure_count=len(failures),
                changes=tuple(changes), failures=tuple(failures), timestamp=time.strftime("%H:%M:%S"),
                description=("已把写过的参数全部退回原值"
                      if not rollback_failures else f"回滚有 {len(rollback_failures)} 项失败：{rollback_failures}")))
            print(f"⚠ 参数事务失败并回滚：{failures[0]}", flush=True)
            return False

        # ── 第三步：提交（存盘只在这里做一次，不会写半套）
        if grouped_by_plugin and self._persist_parameters is not None:
            for plugin_name, values in grouped_by_plugin.items():
                try:
                    self._persist_parameters(plugin_name, values)
                except Exception as exc:                                 # noqa: BLE001
                    print(f"⚠ 参数存盘失败（参数已生效，只是没记住）："
                          f"{type(exc).__name__}: {exc}", flush=True)
        self._publish_transaction(ParameterTransactionResult(
            state="committed", success_count=len(changes), changes=tuple(changes),
            timestamp=time.strftime("%H:%M:%S"),
            description=f"已应用 {len(changes)} 项"))
        print(f"[OK] 参数事务提交：{len(changes)} 项", flush=True)
        return False

    def bind_publisher(self, send) -> "ParameterApplier":
        """注入"把事务结果发出去"的通道（外壳在装配时接上）。"""
        self._send = send
        return self

    def _publish_transaction(self, result: ParameterTransactionResult) -> None:
        send = getattr(self, "_send", None)
        if send is None:
            return
        try:
            send(result)
        except Exception:                                             # noqa: BLE001
            pass


class ParameterPublisher:
    """周期性把"可调参数表"发给界面（默认 10 Hz —— 滑杆不需要更密）。"""

    def __init__(self, send, frequency: float = 10.0):
        self._send = send
        self._interval = 1.0 / max(frequency, 1e-6)
        self._next_publish = 0.0
        self.published_count = 0
        self.latest: dict[str, dict] = {}

    def maybe_publish(self, registry, simulation_time: float, wall_time: float) -> bool:
        if wall_time < self._next_publish:
            return False
        self._next_publish = wall_time + self._interval
        table = collect_parameters(registry)
        self.latest = table
        if not table:
            return False                     # 没有可调参数就不发，省得界面刷空
        try:
            self._send(ParameterTable(parameters=table))
            self.published_count += 1
            return True
        except Exception as exc:                                     # noqa: BLE001
            if self.published_count == 0:
                print(f"⚠ 参数表发布失败（不影响控制）：{type(exc).__name__}: {exc}")
            return False


__all__ = [
    "ParameterTable",
    "ParameterUpdate",
    "collect_parameters",
    "ParameterTransactionCommand",
    "ParameterTransactionResult",
    "ParameterApplier",
    "ParameterPublisher",
]
