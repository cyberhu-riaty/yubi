"""
规划桥.py —— 「规划」的落地端：记录航点 → 调内核 → 回报结果

分工（沿用本项目"桥只翻译、算法只算数"的既有形状）：

    `软件/轨迹规划.py`  —— **纯函数**：数组进、数组出，不碰 mujoco、不碰 UI
    本模块              —— 插件：收命令、拿模型、调内核、发结果

★ 这一层唯一"知道 mujoco"的地方，就是把 `MjModel` 的**真实限位**读出来：
    `jnt_limited` / `jnt_range` / `actuator_ctrlrange`
  这直接消掉了 LE 的缺陷 ⑧（ER15/6 轴硬编码）：限位跟着当前加载的模型走，
  换成 6 轴 UR5e 就是 6 条限位，换成 7 轴 iiwa14 就是 7 条。

⚠️ 限位从哪来（这件事必须写清楚，否则"规划通过"是假的）：
    MuJoCo 的 `jnt_range` 是**位置**范围，不是速度/加速度限位。
    速度/加速度/加加速度限位在 MJCF 里没有标准字段，所以我们按下面的顺序取：
      ① 用户在界面上显式给的（`命令.规划` 里带）—— 最优先
      ② 模型里若有 `jnt_user` 之类的自定义字段 —— 目前不读（没有约定）
      ③ 兜底：按"关节能在 1 秒内走完整个行程"估速度上限，加速度取 4×v，jerk 取 20×a
    ③ 是**估算**，所以结果里会标明 `限位来源 = 估算`，界面上也照实显示 ——
    不能让用户以为那是厂家给的额定值。
"""
from __future__ import annotations

import dataclasses
import time
from typing import Any, Callable

import numpy as np

from 官方层 import messages          # 全部走适配层，见 软件/官方层.py


# ---------------------------------------------------------------------------
# 界面 → 仿真侧
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 规划命令(messages.Snapshot):
    动作: str = "规划"           # "规划" / "记录航点" / "清空航点" / "载入航点"
    # 直接给航点（每项是一组关节角）。给了就用它，不给就用已记录的。
    #   ★ 这条不是"为了方便测试"才加的：规格里"关节航点"本来就是一种**显式输入**，
    #     用户应该有办法直接贴一组航点进来，而不是只能靠"摆姿势 → 记录"。
    航点: tuple = ()
    # 显式限位（可选；不给就用下面 `限位来源` 里说的规则）
    速度上限: tuple = ()          # (n,) rad/s
    加速度上限: tuple = ()        # (n,) rad/s²
    加加速度上限: tuple = ()      # (n,) rad/s³
    网格数: int = 2000
    平滑轮数: int = 0
    平滑系数: float = 0.4
    偏差容差: float = 0.02


# ---------------------------------------------------------------------------
# 仿真侧 → 界面
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class 规划结果(messages.Snapshot):
    状态: str = "空闲"           # 空闲 / 规划中 / ✓ 完成 / ✗ 失败
    航点数: int = 0
    自由度: int = 0
    总时长: float = 0.0
    路径长度: float = 0.0
    # ---- 校验（全部来自内核的回算，不是估的）----
    最大关节速度: float = 0.0
    最大关节加速度: float = 0.0
    最大关节加加速度: float = 0.0
    速度余量: float = 0.0
    加速度余量: float = 0.0
    加加速度余量: float = 0.0
    终端速度: float = 0.0
    平滑偏差: float = 0.0
    # ---- 诊断 ----
    瓶颈关节: int = -1
    瓶颈类型: str = ""
    瓶颈位置: float = 0.0
    最优下界: float = 0.0
    实际比下界: float = 0.0
    限位来源: str = ""           # 显式 / 估算
    时间: str = ""
    原因: str = ""
    # ---- 曲线（给界面画速度包络与 s(t)）----
    包络: tuple = ()             # v_s_max(s)
    s轴: tuple = ()              # 对应的 s
    sd轴: tuple = ()             # 实际 sd(s)


def _解析航点(原始) -> list[list[float]]:
    """宽容解析：`[{"关节": [...]}, ...]` 或 `[[...], ...]` 都接受。

    ★ 契约里只放**对象**形式（`object[]`），因为那是能被 JSON Schema 描述的；
      但内部接收时对裸数组也宽容 —— 用户从文档里复制一组数过来不该报错。
    """
    出: list[list[float]] = []
    for 项 in (原始 or []):
        if isinstance(项, dict):
            值 = 项.get("关节") or 项.get("q") or 项.get("值") or []
        else:
            值 = 项
        组 = [float(x) for x in 值]
        if 组:
            出.append(组)
    return 出


# ---------------------------------------------------------------------------
# 限位推断
# ---------------------------------------------------------------------------
def 从模型取限位(模型) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """返回 (vlim, alim, jlim, 来源说明)。

    ★ 只认**位置**范围，速度/加速度按"1 秒走完全行程"的经验规则估算 ——
      并**明确回报是估算**。这一点很关键：把估算值当成厂家额定值，
      规划"通过"也毫无意义。
    """
    数 = int(getattr(模型, "nq", 0))
    if 数 <= 0:
        raise ValueError("模型没有自由度（nq = 0）")
    位置范围 = np.asarray(getattr(模型, "jnt_range", np.zeros((数, 2))), dtype=float)
    受限 = np.asarray(getattr(模型, "jnt_limited", np.zeros(数, dtype=bool)), dtype=bool)
    行程 = np.zeros(数)
    for i in range(数):
        if i < 位置范围.shape[0] and bool(受限[i]) if i < 受限.size else False:
            低, 高 = 位置范围[i]
            if np.isfinite(低) and np.isfinite(高) and 高 > 低:
                行程[i] = float(高 - 低)
        if 行程[i] <= 0:
            行程[i] = 2.0 * np.pi        # 没有限位声明 → 按一整圈算
    vlim = 行程 / 1.0                    # 1 秒走完全行程
    alim = 4.0 * vlim
    jlim = 20.0 * alim
    return vlim, alim, jlim, "估算（模型未声明速度/加速度限位，按「1 秒走完全行程」推算）"


# ---------------------------------------------------------------------------
# 插件
# ---------------------------------------------------------------------------
class 规划器:
    名称 = "轨迹规划"
    版本 = "0.1"

    def __init__(self, 发送函数: Callable[[Any], None]):
        self._发送 = 发送函数
        self.模型 = None
        self.航点: list[list[float]] = []
        self.最近: 规划结果 | None = None
        self.规划次数 = 0
        self._上次命令 = 规划命令()
        self.错误 = ""
        self.待记录 = False        # 由仿真循环消费（见 `收命令`）

    # ---- 拿模型 ----
    # ★ 方法名必须是 `收到模型`、而且**不能**加 @messages.handler：
    #   `插件系统.通知模型加载` 是**直接按名字调**这个方法的（它不是消息派发），
    #   加了装饰器反而会要求严格类型标注并报错。
    def 收到模型(self, event) -> None:
        """拿到真实模型（换模型时也会被再调一次）。"""
        模型 = getattr(event, "model", None)
        if 模型 is not None:
            self.模型 = 模型
            self.航点 = []          # 换模型 → 自由度可能变了，旧航点作废

    # ---- 记录当前姿态（由外壳调用：只有它拿得到 data）----
    def 记录航点(self, qpos) -> int:
        q = [float(x) for x in np.asarray(qpos, dtype=float).ravel()]
        if self.航点 and max(abs(a - b) for a, b in zip(q, self.航点[-1])) < 1e-9:
            return len(self.航点)         # 与上一个相同就不重复记
        self.航点.append(q)
        return len(self.航点)

    def 清空航点(self) -> int:
        self.航点 = []
        return 0

    # ---- 接命令 ----
    @messages.handler
    def 收命令(self, 命令: 规划命令) -> bool:
        动作 = str(getattr(命令, "动作", ""))
        if 动作 == "规划":
            self._上次命令 = 命令
            self.规划()
        elif 动作 == "清空航点":
            self.清空航点()
            self.发航点数()
        elif 动作 == "载入航点":
            try:
                self.航点 = _解析航点(命令.航点)
                self.发航点数()
            except Exception as 异常:                                     # noqa: BLE001
                print(f"⚠ 载入航点失败：{异常}", flush=True)
        elif 动作 == "记录航点":
            # ★ 本插件拿不到 `data.qpos`（那是外壳的局部变量），所以这里只**挂个标记**，
            #   由仿真循环在下一圈消费。这样"记录当前姿态"这个动作仍然只有一条路径。
            self.待记录 = True
        return False

    def 规划(self) -> None:
        """跑一次规划。**最后一次性构造结果**（dataclass 是 frozen 的，不能逐字段改）。"""
        import 轨迹规划 as TP

        命令 = self._上次命令
        动作是规划 = str(getattr(命令, "动作", "规划")) == "规划"
        try:
            self._发送(规划结果(状态="规划中", 时间=time.strftime("%H:%M:%S")))
        except Exception:                                             # noqa: BLE001
            pass

        # ★ 先攒成一个 dict，最后 `规划结果(**值)` 一次构造。
        #   原来我是 `结果.状态 = ...` 逐字段赋值，而 dataclass 写了 `frozen=True`
        #   → `FrozenInstanceError`。frozen 是有意的（消息不该被改），所以改的是写法。
        值: dict[str, Any] = {"状态": "空闲", "时间": time.strftime("%H:%M:%S")}
        try:
            if self.模型 is None:
                raise RuntimeError("还没有加载模型")
            用哪个 = (_解析航点(命令.航点)
                      if (命令.航点 and 动作是规划 and len(命令.航点) >= 2)
                      else self.航点)
            if len(用哪个) < 2:
                raise RuntimeError(f"至少要 2 个航点（现在 {len(用哪个)} 个）")

            W = np.asarray(用哪个, dtype=float)
            数 = W.shape[1]

            # 限位：显式优先，否则从模型推断
            来源 = "显式"
            if len(命令.速度上限) == 数:
                vlim = np.asarray(命令.速度上限, dtype=float)
                alim = np.asarray(命令.加速度上限, dtype=float) if len(命令.加速度上限) == 数 \
                    else 4.0 * vlim
                jlim = np.asarray(命令.加加速度上限, dtype=float) if len(命令.加加速度上限) == 数 \
                    else 20.0 * alim
            else:
                vlim, alim, jlim, 来源 = 从模型取限位(self.模型)
                if vlim.size != 数:
                    vlim, alim, jlim = (np.resize(x, 数) for x in (vlim, alim, jlim))

            报 = TP.规划(W, TP.约束(vlim=vlim, alim=alim, jlim=jlim), TP.参数(
                网格数=int(getattr(命令, "网格数", 2000) or 2000),
                平滑轮数=int(getattr(命令, "平滑轮数", 0) or 0),
                平滑系数=float(getattr(命令, "平滑系数", 0.4) or 0.4),
                偏差容差=float(getattr(命令, "偏差容差", 0.02) or 0.02),
            ))

            值.update({
                "状态": "✓ 完成" if 报.成功 else "✗ 失败",
                "航点数": int(报.航点数),
                "自由度": int(报.自由度),
                "总时长": float(报.总时长),
                "路径长度": float(报.路径长度),
                "最大关节速度": float(报.最大关节速度),
                "最大关节加速度": float(报.最大关节加速度),
                "最大关节加加速度": float(报.最大关节加加速度),
                "速度余量": float(报.速度余量),
                "加速度余量": float(报.加速度余量),
                "加加速度余量": float(报.加加速度余量),
                "终端速度": float(报.终端速度),
                "平滑偏差": float(报.平滑偏差),
                "瓶颈关节": int(报.瓶颈关节),
                "瓶颈类型": str(报.瓶颈类型),
                "瓶颈位置": float(报.瓶颈位置),
                "最优下界": float(报.最优下界),
                "实际比下界": float(报.实际比下界),
                "限位来源": 来源,
                "原因": str(报.原因),
            })

            # 包络曲线：全量 2000 点没必要发给界面，取 200 个点
            包络 = 报.包络
            if 包络 is not None and len(包络):
                包络 = np.asarray(包络, dtype=float)
                取 = np.linspace(0, 包络.size - 1, min(200, 包络.size)).astype(int)
                值["包络"] = tuple(float(x) for x in 包络[取] if np.isfinite(x))
                if 报.s is not None:
                    值["s轴"] = tuple(float(x) for x in np.asarray(报.s)[取])
                if 报.sd is not None:
                    值["sd轴"] = tuple(float(x) for x in np.asarray(报.sd)[取])
            if 报.成功:
                self.规划次数 += 1
        except Exception as 异常:                                         # noqa: BLE001
            值["状态"] = "✗ 失败"
            值["原因"] = f"{type(异常).__name__}: {异常}"
            self.错误 = str(值["原因"])

        结果 = 规划结果(**值)
        self.最近 = 结果
        try:
            self._发送(结果)
        except Exception as 异常:                                         # noqa: BLE001
            print(f"⚠ 规划结果发送失败：{type(异常).__name__}: {异常}", flush=True)

    def 发航点数(self) -> None:
        """航点变化时让界面知道（用户想知道"记了几个点"）。"""
        try:
            self._发送(规划结果(状态="空闲", 航点数=len(self.航点),
                              时间=time.strftime("%H:%M:%S")))
        except Exception:                                             # noqa: BLE001
            pass
