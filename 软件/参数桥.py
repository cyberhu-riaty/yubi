"""
参数桥.py —— 把界面滑杆的值送回插件（第 4 步：控制器参数面板）

数据流向（和"指标"正好相反）：
    指标：  插件 → 外壳 → 界面（画曲线）
    参数：  界面 → 外壳 → 插件（改参数）

为什么不用直接调用：
    界面（viewer 侧）和插件（仿真侧）在两个线程/两个"世界"里，
    只能靠消息通信。所以定义一条参数消息：
        面板发 `参数消息`（改了哪些参数）→ 仿真侧的 `参数应用器` 收 → 调插件的 设置参数()

插件侧要做什么（就一步）：
    声明哪些类属性可以调，界面就会自动出现滑杆：

        def 可调参数(self) -> dict:
            return {"KP": {"值": self.KP, "范围": (10.0, 20000.0)},
                    "KD": {"值": self.KD, "范围": (0.0, 500.0)}}
"""
from __future__ import annotations

import dataclasses
import time
from typing import Any

from 官方层 import messages          # 全部走适配层，见 软件/官方层.py


@dataclasses.dataclass(frozen=True)
class 参数表消息(messages.Snapshot):
    """仿真侧 → 界面：当前所有可调参数（值 + 范围）。

    为什么是 Snapshot：滑杆只需要"最新状态"，旧的不排队正合适。
    """

    参数: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class 参数消息(messages.Snapshot):
    """界面 → 仿真侧：这一帧被拖动过的参数。

    Snapshot 语义（只保留最新一条）在这里正合适：
    拖动滑杆会连续产生很多条，旧的没处理也无所谓 —— 最新值才是要的。
    """

    改动: dict = dataclasses.field(default_factory=dict)   # {参数名: 新值}


def 采集可调参数(注册表) -> dict[str, dict]:
    """向每个插件问一次"你有哪些可调参数"，合并成一张表。

    同名参数（比如两个插件都有 KP）会带上插件名前缀区分：
        "关节 PD 位置控制·KP"
    这样界面上不会互相串。

    ★ 只问**有 `名称` 的**对象，也就是项目声明的那些用户算法：
      注册表里还混着 StepControl / 模型应用器 / 参数应用器这些内部插件，
      它们不该出现在参数面板上（虽然它们本来也没实现 可调参数()，
      但靠"恰好没实现"来保证正确性太脆 —— 显式跳过更稳）。

    ★ 每个插件名后面缀上它的**版本号**也很重要：换项目时算法可能同名不同版本
      （比如 `算法库/实验/关节pd控制.py` 与 `算法库/通用/关节pd控制.py`），
      面板上要能看出来现在挂的是哪一个。
    """
    表: dict[str, dict] = {}
    for 插件 in getattr(注册表, "_目标", []):
        名 = getattr(插件, "名称", None)
        if not 名:
            continue
        问 = getattr(插件, "可调参数", None)
        if 问 is None:
            continue
        名 = str(名)
        英文 = str(getattr(插件, "英文名", "") or "")   # 面板上显示用（UI 字体无中文字形）
        try:
            一条 = 问() or {}
        except Exception as 异常:                                     # noqa: BLE001
            print(f"⚠ 插件【{名}】的可调参数() 出错（已跳过）：{type(异常).__name__}: {异常}")
            continue
        for 参数名, 信息 in 一条.items():
            范围 = 信息.get("范围") or (0.0, 1.0)
            表[f"{名}·{参数名}"] = {
                "插件": 名,
                "插件英文": 英文,
                "插件版本": str(getattr(插件, "版本", "-")),
                "参数": 参数名,
                "值": float(信息.get("值", 0.0)),
                "范围": (float(范围[0]), float(范围[1])),
                "步长": float(信息.get("步长", 0.0)),
                "单位": str(信息.get("单位", "")),
            }
    return 表


@dataclasses.dataclass(frozen=True)
class 批量参数命令(messages.Snapshot):
    """界面 → 仿真侧：**一次性**应用一组参数（事务语义）。

    ★ 为什么需要它（单条 `参数消息` 做不到的事）：
      单条消息是"改一个算一个"。用户在参数表里改了 8 个值然后点"应用"，
      如果第 5 个非法，前 4 个已经生效了 —— 机器人就处在**一个谁也没想要**的
      中间状态。真机上这是危险的（比如 KP 已改而 KD 没改，会直接振荡）。
      所以这一条要求：**全成功，或者一个都不动**。
    """
    动作: str = "应用"          # 应用 / 回滚
    参数: tuple = ()            # ((全名, 值), ...) —— 用元组保证可哈希、可比较


@dataclasses.dataclass(frozen=True)
class 参数事务结果(messages.Snapshot):
    """仿真侧 → 界面：这次事务到底做成了什么。"""
    状态: str = "空闲"          # 空闲 / ✓ 已提交 / ✗ 已回滚
    成功数: int = 0
    失败数: int = 0
    时间: str = ""
    # 每项：{全名, 旧值, 新值}
    差异: tuple = ()
    # 失败原因（给人看的，逐条）
    失败: tuple = ()
    说明: str = ""


class 参数应用器:
    """仿真侧：收到参数消息后，把它转给对应插件的 设置参数()。

    插件的 每步控制() 读的是自己的类属性，所以改完**下一次步进就生效**，
    不需要插件写任何接收代码。

    ★ 方案 C 之后它还负责**把参数存回项目文件**（`参数存盘` 回调）：
      以前拖出来的值只活在内存里，换项目/重启就没了。存进项目文件之后，
      "这一组参数"成了实验记录的一部分（录制元信息里也会记下当时的参数值）。
    """

    def __init__(self, 参数存盘=None):
        self.已应用 = 0
        self.最近 = {}
        self.错误: list[str] = []
        self._插件名到实例 = {}
        # 存盘回调：(插件名, {参数名: 值}) -> None。由外壳注入（它知道"当前是哪个项目"）。
        self._参数存盘 = 参数存盘

    def 重绑(self, 注册表) -> "参数应用器":
        """`绑定` 的别名 —— 强调"换了一组算法之后要重新绑一次"这件事。

        ★ 保留 `绑定` 这个名字是为了不破坏已有调用（外壳启动时用的是它）。
          两个名字指向同一件事：把"插件名 → 实例"这本账重新拍一遍。
          详见 `绑定()` 的说明（不重绑会导致滑杆静默失效）。
        """
        return self.绑定(注册表)

    def 绑定(self, 注册表) -> "参数应用器":
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
        self._插件名到实例 = {
            str(getattr(p, "名称", type(p).__name__)): p
            for p in getattr(注册表, "_目标", [])
            if getattr(p, "名称", None)
        }
        return self

    @messages.handler
    def 收参数(self, 消息: 参数消息) -> bool:
        改动 = getattr(消息, "改动", None) or {}
        按插件归并: dict[str, dict] = {}
        for 全名, 值 in 改动.items():
            插件名, _, 参数名 = 全名.partition("·")
            实例 = self._插件名到实例.get(插件名)
            if 实例 is None:
                # ★ 不再静默 continue：换项目/换算法组之后如果忘了重绑，
                #   这里就是"滑杆拖了没反应"的地方 —— 至少要说一声。
                print(f"ℹ 参数「{全名}」没有对应的算法实例（当前这一组里没有【{插件名}】）—— "
                      f"已忽略；如果刚换过模型，这是正常的（那个算法不在本项目里）")
                continue
            错 = 实例.设置参数(参数名, float(值))
            if 错:
                if 错 not in self.错误:
                    self.错误.append(错)
                    print(f"⚠ {错}")
                continue
            self.已应用 += 1
            self.最近[全名] = float(值)
            按插件归并.setdefault(插件名, {})[参数名] = float(值)

        # 存回项目文件（"上次调好的参数"要能延续到下次打开这个项目）
        if 按插件归并 and self._参数存盘 is not None:
            for 插件名, 值表 in 按插件归并.items():
                try:
                    self._参数存盘(插件名, 值表)
                except Exception as 异常:                                  # noqa: BLE001
                    if "存盘" not in getattr(self, "_存盘已报错", set()):
                        self._存盘已报错 = getattr(self, "_存盘已报错", set()) | {"存盘"}
                        print(f"⚠ 参数存盘失败（参数已生效，只是没记住）："
                              f"{type(异常).__name__}: {异常}")
        return False


    # ------------------------------------------------------------------
    # 事务式批量应用（全成功，或一个都不动）
    # ------------------------------------------------------------------
    @messages.handler
    def 收批量(self, 命令: 批量参数命令) -> bool:
        if str(getattr(命令, "动作", "")) != "应用":
            return False
        # ★ 契约里 `参数` 是 object[]，每项 `{全名, 值}`（能被 JSON Schema 描述的写法）。
        #   但内部/测试里也会写成 dict 或 (全名, 值) 元组 —— 三种都接。
        #   第一版只认元组，于是 Web 发来的对象数组被当成"空改动"，
        #   报出"当前这组算法里没有【全名】"这种让人摸不着头脑的错。
        改动: dict[str, Any] = {}
        for 项 in (getattr(命令, "参数", None) or ()):
            if isinstance(项, dict):
                名 = str(项.get("全名") or 项.get("名") or "")
                if 名:
                    改动[名] = 项.get("值")
            elif isinstance(项, (tuple, list)) and len(项) == 2:
                改动[str(项[0])] = 项[1]
        if not 改动:
            self._发事务(参数事务结果(状态="✗ 已回滚", 时间=time.strftime("%H:%M:%S"),
                                     说明="没有要改的参数"))
            return False

        # ── 第一步：**预检**（一个都不写）。这一步是事务能成立的关键。
        计划: list[tuple[Any, str, str, float, float]] = []
        失败: list[str] = []
        for 全名, 新值 in 改动.items():
            插件名, _, 参数名 = str(全名).partition("·")
            实例 = self._插件名到实例.get(插件名)
            if 实例 is None:
                失败.append(f"{全名}：当前这组算法里没有【{插件名}】")
                continue
            try:
                表 = 实例.可调参数() or {}
            except Exception as 异常:                                     # noqa: BLE001
                失败.append(f"{全名}：读不到参数表（{type(异常).__name__}）")
                continue
            声明 = 表.get(参数名)
            if not isinstance(声明, dict):
                失败.append(f"{全名}：插件没有声明这个参数")
                continue
            旧 = float(声明.get("值", 0.0))
            try:
                新 = float(新值)
            except (TypeError, ValueError):
                失败.append(f"{全名}：{新值!r} 不是数字")
                continue
            范围 = 声明.get("范围")
            if isinstance(范围, (tuple, list)) and len(范围) == 2:
                低, 高 = float(范围[0]), float(范围[1])
                if not (低 <= 新 <= 高):
                    失败.append(f"{全名}：{新:g} 超出范围 [{低:g}, {高:g}]")
                    continue
            计划.append((实例, str(全名), 参数名, 旧, 新))

        # 任何一条不合格 → 一个都不写（这正是"事务"的意思）
        if 失败 or not 计划:
            self._发事务(参数事务结果(
                状态="✗ 已回滚", 失败数=len(失败), 失败=tuple(失败),
                时间=time.strftime("%H:%M:%S"),
                说明="预检未通过，所有参数保持原值"))
            for 行 in 失败:
                print(f"⚠ 参数事务被拒：{行}", flush=True)
            return False

        # ── 第二步：逐个写；**任何一步失败就把已写的退回去**
        已写: list[tuple[Any, str, float]] = []
        差异: list[dict] = []
        按插件归并: dict[str, dict] = {}
        for 实例, 全名, 参数名, 旧, 新 in 计划:
            错 = 实例.设置参数(参数名, 新)
            if 错:
                失败.append(f"{全名}：{错}")
                break
            已写.append((实例, 参数名, 旧))
            差异.append({"全名": 全名, "旧值": 旧, "新值": 新})
            self.已应用 += 1
            self.最近[全名] = 新
            按插件归并.setdefault(全名.partition("·")[0], {})[参数名] = 新

        if 失败:
            # 回滚：按**写入顺序的逆序**退回，保证互相依赖的参数也回到一致状态
            退不回 = []
            for 实例, 参数名, 旧 in reversed(已写):
                try:
                    if 实例.设置参数(参数名, 旧):
                        退不回.append(参数名)
                except Exception:                                         # noqa: BLE001
                    退不回.append(参数名)
            self._发事务(参数事务结果(
                状态="✗ 已回滚", 成功数=len(已写) - len(退不回), 失败数=len(失败),
                差异=tuple(差异), 失败=tuple(失败), 时间=time.strftime("%H:%M:%S"),
                说明=("已把写过的参数全部退回原值"
                      if not 退不回 else f"回滚有 {len(退不回)} 项失败：{退不回}")))
            print(f"⚠ 参数事务失败并回滚：{失败[0]}", flush=True)
            return False

        # ── 第三步：提交（存盘只在这里做一次，不会写半套）
        if 按插件归并 and self._参数存盘 is not None:
            for 插件名, 值表 in 按插件归并.items():
                try:
                    self._参数存盘(插件名, 值表)
                except Exception as 异常:                                 # noqa: BLE001
                    print(f"⚠ 参数存盘失败（参数已生效，只是没记住）："
                          f"{type(异常).__name__}: {异常}", flush=True)
        self._发事务(参数事务结果(
            状态="✓ 已提交", 成功数=len(差异), 差异=tuple(差异),
            时间=time.strftime("%H:%M:%S"),
            说明=f"已应用 {len(差异)} 项"))
        print(f"✓ 参数事务提交：{len(差异)} 项", flush=True)
        return False

    def 绑定发布(self, 发送函数) -> "参数应用器":
        """注入"把事务结果发出去"的通道（外壳在装配时接上）。"""
        self._发送 = 发送函数
        return self

    def _发事务(self, 结果: 参数事务结果) -> None:
        发送 = getattr(self, "_发送", None)
        if 发送 is None:
            return
        try:
            发送(结果)
        except Exception:                                             # noqa: BLE001
            pass


class 发布器:
    """周期性把"可调参数表"发给界面（默认 10 Hz —— 滑杆不需要更密）。"""

    def __init__(self, 发送函数, 频率: float = 10.0):
        self._发送 = 发送函数
        self._间隔 = 1.0 / max(频率, 1e-6)
        self._下次 = 0.0
        self.已发布 = 0
        self.最近: dict[str, dict] = {}

    def 也许发布(self, 注册表, 仿真时间: float, 墙钟: float) -> bool:
        if 墙钟 < self._下次:
            return False
        self._下次 = 墙钟 + self._间隔
        表 = 采集可调参数(注册表)
        self.最近 = 表
        if not 表:
            return False                     # 没有可调参数就不发，省得界面刷空
        try:
            self._发送(参数表消息(参数=表))
            self.已发布 += 1
            return True
        except Exception as 异常:                                     # noqa: BLE001
            if self.已发布 == 0:
                print(f"⚠ 参数表发布失败（不影响控制）：{type(异常).__name__}: {异常}")
            return False
