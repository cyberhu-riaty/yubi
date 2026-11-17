"""
planning_bridge.py — planning commands, trajectory generation and execution state

分工（沿用本项目"桥只翻译、算法只算数"的既有形状）：

    `软件/trajectory_planning.py` —— **纯函数**：数组进、数组出，不碰 mujoco、不碰 UI
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
import json
import os
import time
from typing import Any, Callable

import numpy as np

from official_api import messages


# ---------------------------------------------------------------------------
# 界面 → 仿真侧
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class PlanningCommand(messages.Snapshot):
    action: str = "plan"
    # 直接给航点（每项是一组关节角）。给了就用它，不给就用已记录的。
    #   ★ 这条不是"为了方便测试"才加的：规格里"关节航点"本来就是一种**显式输入**，
    #     用户应该有办法直接贴一组航点进来，而不是只能靠"摆姿势 → 记录"。
    waypoints: tuple = ()
    # 笛卡尔航点（每项 `{xyz: [x,y,z]}`，单位米）。给了就**先做逆解**再规划。
    #   ★ 只支持位置（3 个数）。姿态约束这一版**没做** —— 见 inverse_kinematics.py，
    #     宁可明确说"不支持"，也不要把姿态悄悄忽略掉。
    cartesian_waypoints: tuple = ()
    # 显式限位（可选；不给就用下面 `限位来源` 里说的规则）
    velocity_limits: tuple = ()
    acceleration_limits: tuple = ()
    jerk_limits: tuple = ()
    grid_size: int = 2000
    smoothing_iterations: int = 0
    smoothing_factor: float = 0.4
    deviation_tolerance: float = 0.02


# ---------------------------------------------------------------------------
# 仿真侧 → 界面
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class PlanningResult(messages.Snapshot):
    status: str = "idle"
    waypoint_count: int = 0
    dof: int = 0
    duration_s: float = 0.0
    path_length: float = 0.0
    # ---- 校验（全部来自内核的回算，不是估的）----
    max_joint_velocity: float = 0.0
    max_joint_acceleration: float = 0.0
    max_joint_jerk: float = 0.0
    velocity_margin: float = 0.0
    acceleration_margin: float = 0.0
    jerk_margin: float = 0.0
    terminal_velocity: float = 0.0
    smoothing_deviation: float = 0.0
    # ---- 诊断 ----
    bottleneck_joint: int = -1
    bottleneck_type: str = ""
    bottleneck_position: float = 0.0
    optimal_lower_bound: float = 0.0
    actual_to_lower_bound: float = 0.0
    limit_source: str = ""
    timestamp: str = ""
    reason: str = ""
    # ---- 换约束重规划后的对比（同一批航点、不同限位）----
    #   每项：{上次时长, 本次时长, 时长变化%, 上次最大速度, 本次最大速度,
    #          上次约束, 本次约束, 上次sd[], 本次sd[]}
    comparison: Any = None
    # ---- 笛卡尔航点的逆解结果 ----
    inverse_kinematics: str = ""
    # ---- 离线产物与执行 ----
    output_path: str = ""
    execution_status: str = "idle"
    execution_progress: float = 0.0
    # ---- 曲线（给界面画速度包络与 s(t)）----
    envelope: tuple = ()
    path_axis: tuple = ()
    speed_axis: tuple = ()


def _parse_waypoints(raw) -> list[list[float]]:
    """解析 `[{"q": [...]}, ...]` 或 `[[...], ...]` 形式的航点。

    ★ 契约里只放**对象**形式（`object[]`），因为那是能被 JSON Schema 描述的；
      但内部接收时对裸数组也宽容 —— 用户从文档里复制一组数过来不该报错。
    """
    output: list[list[float]] = []
    for item in (raw or []):
        if isinstance(item, dict):
            payload = item.get("q") or []
        else:
            payload = item
        group = [float(x) for x in payload]
        if group:
            output.append(group)
    return output


# ---------------------------------------------------------------------------
# 离线产物
# ---------------------------------------------------------------------------
def _trajectory_directory(package_root: str) -> str:
    return os.path.join(package_root, "输出", "05_轨迹")


def _save_trajectory(report, package_root: str, project_name: str = "") -> str:
    """把规划结果写成**离线产物**：`轨迹.csv` + `轨迹.meta.json`。

    ★ 为什么必须落盘（规格里"完整实现"明确要求"把这条轨迹作为离线产物存下来"）：
      规划出来的东西只在内存里 = 用户拿不走、下次打开就没了，
      这一项就永远停在"能算"而不是"能用"。
    ★ 为什么 CSV + 元信息分开：
      CSV 要能被 numpy/pandas/Excel 直接读（时间-位置-速度-加速度）；
      而约束、限位来源、校验数字是**给人看的上下文**，塞进 CSV 表头会把表弄脏。
    """
    import time as _t
    directory = os.path.join(_trajectory_directory(package_root),
                       f"{project_name or '未命名'}_{_t.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(directory, exist_ok=True)
    t_ = np.asarray(report.t, dtype=float)
    q = np.asarray(report.q, dtype=float)
    qd = np.asarray(report.qd, dtype=float)
    qdd = np.asarray(report.qdd, dtype=float)
    n = q.shape[1] if q.ndim == 2 else 0
    columns = ["t", "s", "sd"]
    series = [t_, np.asarray(report.s, dtype=float), np.asarray(report.sd, dtype=float)]
    for i in range(n):
        columns.append(f"q{i}")
        series.append(q[:, i])
    for i in range(n):
        columns.append(f"qd{i}")
        series.append(qd[:, i])
    for i in range(n):
        columns.append(f"qdd{i}")
        series.append(qdd[:, i])
    matrix = np.column_stack(series)
    np.savetxt(os.path.join(directory, "轨迹.csv"), matrix, delimiter=",",
               header=",".join(columns), comments="", fmt="%.9g")

    metadata = {
        "schema_version": 2,
        "generated_at": _t.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "驭臂 · 轨迹规划",
        "sampling": {"points": int(t_.size), "duration_s": float(report.duration_s),
                     "grid_size": int(report.grid_size)},
        "path": {"length": float(report.path_length), "waypoints": int(report.waypoint_count)},
        "validation": {
            "max_joint_velocity": float(report.max_joint_velocity),
            "max_joint_acceleration": float(report.max_joint_acceleration),
            "max_joint_jerk": float(report.max_joint_jerk),
            "velocity_margin": float(report.velocity_margin),
            "acceleration_margin": float(report.acceleration_margin),
            "jerk_margin": float(report.jerk_margin),
            "terminal_velocity": float(report.terminal_velocity),
            "smoothing_deviation": float(report.smoothing_deviation),
            "bottleneck": {"type": str(report.bottleneck_type),
                           "joint": int(report.bottleneck_joint),
                           "position_s": float(report.bottleneck_position)},
        },
        "notes": ("加加速度本版只校验不整形：峰值出现在前后向扫描的切换点，"
                  "要做 S 曲线整形才能真限住。"),
    }
    with open(os.path.join(directory, "轨迹.meta.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    return directory


# ---------------------------------------------------------------------------
# 限位推断
# ---------------------------------------------------------------------------
def infer_limits_from_model(model) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """返回 (vlim, alim, jlim, 来源说明)。

    ★ 只认**位置**范围，速度/加速度按"1 秒走完全行程"的经验规则估算 ——
      并**明确回报是估算**。这一点很关键：把估算值当成厂家额定值，
      规划"通过"也毫无意义。
    """
    dof = int(getattr(model, "nq", 0))
    if dof <= 0:
        raise ValueError("模型没有自由度（nq = 0）")
    position_range = np.asarray(getattr(model, "jnt_range", np.zeros((dof, 2))), dtype=float)
    limited = np.asarray(getattr(model, "jnt_limited", np.zeros(dof, dtype=bool)), dtype=bool)
    travel = np.zeros(dof)
    for i in range(dof):
        if i < position_range.shape[0] and bool(limited[i]) if i < limited.size else False:
            lower, upper = position_range[i]
            if np.isfinite(lower) and np.isfinite(upper) and upper > lower:
                travel[i] = float(upper - lower)
        if travel[i] <= 0:
            travel[i] = 2.0 * np.pi        # 没有限位声明 → 按一整圈算
    vlim = travel / 1.0                    # 1 秒走完全行程
    alim = 4.0 * vlim
    jlim = 20.0 * alim
    return vlim, alim, jlim, "估算（模型未声明速度/加速度限位，按「1 秒走完全行程」推算）"


# ---------------------------------------------------------------------------
# 插件
# ---------------------------------------------------------------------------
class TrajectoryPlanner:
    name = "轨迹规划"
    version = "0.1"

    def __init__(self, send: Callable[[Any], None], package_root: str = ""):
        self._send = send
        # 包根只用来决定"离线产物写哪儿"（输出/05_轨迹/），不参与算法
        self._package_root = package_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.model = None
        self.waypoints: list[list[float]] = []
        self.latest: PlanningResult | None = None
        self.plan_count = 0
        self._last_command = PlanningCommand()
        self.error = ""
        self.pending_record = False        # 由仿真循环消费（见 `on_command`）
        # 离线产物：规划成功就写一份，路径记在这里（界面显示的就是它）
        self.output_directory = ""
        # 执行态：轨迹存下来之后，由 `执行` 命令驱动
        self.executing = False
        self.execution_start = 0.0
        self.execution_progress = 0.0
        self._trajectory_time: np.ndarray | None = None
        self._trajectory_positions: np.ndarray | None = None
        self.execution_duration = 0.0
        self._next_publish = 0.0
        # 上一次成功的规划：用于"换约束重规划"后的逐点对比。
        #   ★ 只有当**航点完全一致**时才对比 —— 换一批航点再比时长没有意义
        #     （路径都不同，快慢没有可比性）。
        self._previous_plan: dict | None = None

    # ---- 拿模型 ----
    # ★ 方法名必须是 `receive_model`、而且**不能**加 @messages.handler：
    #   模型生命周期通知会直接按名字调用这个方法（它不是消息派发），
    #   加了装饰器反而会要求严格类型标注并报错。
    def receive_model(self, event) -> None:
        """拿到真实模型（换模型时也会被再调一次）。"""
        model = getattr(event, "model", None)
        if model is not None:
            self.model = model
            self.waypoints = []          # 换模型 → 自由度可能变了，旧航点作废

    # ---- 记录当前姿态（由外壳调用：只有它拿得到 data）----
    def record_waypoint(self, qpos) -> int:
        q = [float(x) for x in np.asarray(qpos, dtype=float).ravel()]
        if self.waypoints and max(abs(a - b) for a, b in zip(q, self.waypoints[-1])) < 1e-9:
            return len(self.waypoints)         # 与上一个相同就不重复记
        self.waypoints.append(q)
        return len(self.waypoints)

    def clear_waypoints(self) -> int:
        self.waypoints = []
        return 0

    # ---- 接命令 ----
    @messages.handler
    def on_command(self, command: PlanningCommand) -> bool:
        action = str(getattr(command, "action", ""))
        if action == "plan":
            self._last_command = command
            self.plan()
        elif action == "clear_waypoints":
            self.clear_waypoints()
            self.publish_waypoint_count()
        elif action == "load_waypoints":
            try:
                self.waypoints = _parse_waypoints(command.waypoints)
                self.publish_waypoint_count()
            except Exception as exc:                                     # noqa: BLE001
                print(f"⚠ 载入航点失败：{exc}", flush=True)
        elif action == "execute":
            self.start_execution()
        elif action == "stop_execution":
            self.stop_execution("手动停止")
        elif action == "record_waypoint":
            # ★ 本插件拿不到 `data.qpos`（那是外壳的局部变量），所以这里只**挂个标记**，
            #   由仿真循环在下一圈消费。这样"记录当前姿态"这个动作仍然只有一条路径。
            self.pending_record = True
        return False

    def plan(self) -> None:
        """跑一次规划。**最后一次性构造结果**（dataclass 是 frozen 的，不能逐字段改）。"""
        import trajectory_planning

        command = self._last_command
        is_plan_action = str(getattr(command, "action", "plan")) == "plan"
        try:
            self._send(PlanningResult(status="planning", timestamp=time.strftime("%H:%M:%S")))
        except Exception:                                             # noqa: BLE001
            pass

        # ★ 先攒成一个 dict，最后 `规划结果(**值)` 一次构造。
        #   原来我是 `结果.状态 = ...` 逐字段赋值，而 dataclass 写了 `frozen=True`
        #   → `FrozenInstanceError`。frozen 是有意的（消息不该被改），所以改的是写法。
        payload: dict[str, Any] = {"status": "idle", "timestamp": time.strftime("%H:%M:%S")}
        try:
            if self.model is None:
                raise RuntimeError("还没有加载模型")
            # ---- 笛卡尔航点 → 先逆解成关节航点 ----
            cartesian_input = list(getattr(command, "cartesian_waypoints", ()) or ())
            if cartesian_input and is_plan_action:
                import mujoco as _mj
                import inverse_kinematics as _inverse_kinematics
                _pts = []
                for item in cartesian_input:
                    # ★ 局部变量**不能叫 `值`** —— 外层那个 `值` 是本次结果 dict，
                    #   一旦被遮蔽，后面 `值["逆解"] = ...` 就变成 list["逆解"] → TypeError。
                    #   （实测踩过：插件被"出错隔离"停用，界面上只看到规划没结果。）
                    coordinates = item.get("xyz") if isinstance(item, dict) else item
                    _pts.append([float(x) for x in (coordinates or [])])
                # ★ 逆解要用**当前姿态**当第一个种子，所以得有一份 MjData
                _d = _mj.MjData(self.model)
                _mj.mj_forward(self.model, _d)
                _q, _residuals, ik_description = _inverse_kinematics.cartesian_to_joint(
                    self.model, _d, _pts, _mj)
                payload["inverse_kinematics"] = ik_description
                selected_waypoints = _q.tolist()
                is_plan_action = True
            else:
                selected_waypoints = (_parse_waypoints(command.waypoints)
                          if (command.waypoints and is_plan_action and len(command.waypoints) >= 2)
                          else self.waypoints)
            if len(selected_waypoints) < 2:
                raise RuntimeError(f"至少要 2 个航点（现在 {len(selected_waypoints)} 个）")

            W = np.asarray(selected_waypoints, dtype=float)
            dof = W.shape[1]

            # 限位：显式优先，否则从模型推断
            source = "显式"
            if len(command.velocity_limits) == dof:
                vlim = np.asarray(command.velocity_limits, dtype=float)
                alim = np.asarray(command.acceleration_limits, dtype=float) if len(command.acceleration_limits) == dof\
                    else 4.0 * vlim
                jlim = np.asarray(command.jerk_limits, dtype=float) if len(command.jerk_limits) == dof\
                    else 20.0 * alim
            else:
                vlim, alim, jlim, source = infer_limits_from_model(self.model)
                if vlim.size != dof:
                    vlim, alim, jlim = (np.resize(x, dof) for x in (vlim, alim, jlim))

            report = trajectory_planning.plan_trajectory(W, trajectory_planning.TrajectoryLimits(vlim=vlim, alim=alim, jlim=jlim), trajectory_planning.PlannerOptions(
                grid_size=int(getattr(command, "grid_size", 2000) or 2000),
                smoothing_iterations=int(getattr(command, "smoothing_iterations", 0) or 0),
                smoothing_factor=float(getattr(command, "smoothing_factor", 0.4) or 0.4),
                deviation_tolerance=float(getattr(command, "deviation_tolerance", 0.02) or 0.02),
            ))

            payload.update({
                "status": "completed" if report.success else "failed",
                "waypoint_count": int(report.waypoint_count),
                "dof": int(report.dof),
                "duration_s": float(report.duration_s),
                "path_length": float(report.path_length),
                "max_joint_velocity": float(report.max_joint_velocity),
                "max_joint_acceleration": float(report.max_joint_acceleration),
                "max_joint_jerk": float(report.max_joint_jerk),
                "velocity_margin": float(report.velocity_margin),
                "acceleration_margin": float(report.acceleration_margin),
                "jerk_margin": float(report.jerk_margin),
                "terminal_velocity": float(report.terminal_velocity),
                "smoothing_deviation": float(report.smoothing_deviation),
                "bottleneck_joint": int(report.bottleneck_joint),
                "bottleneck_type": str(report.bottleneck_type),
                "bottleneck_position": float(report.bottleneck_position),
                "optimal_lower_bound": float(report.optimal_lower_bound),
                "actual_to_lower_bound": float(report.actual_to_lower_bound),
                "limit_source": source,
                "inverse_kinematics": str(payload.get("inverse_kinematics", "")),
                "reason": str(report.reason),
            })

            # 包络曲线：全量 2000 点没必要发给界面，取 200 个点
            envelope = report.envelope
            if envelope is not None and len(envelope):
                envelope = np.asarray(envelope, dtype=float)
                indices = np.linspace(0, envelope.size - 1, min(200, envelope.size)).astype(int)
                payload["envelope"] = tuple(float(x) for x in envelope[indices] if np.isfinite(x))
                if report.s is not None:
                    payload["path_axis"] = tuple(float(x) for x in np.asarray(report.s)[indices])
                if report.sd is not None:
                    payload["speed_axis"] = tuple(float(x) for x in np.asarray(report.sd)[indices])
            if report.success:
                self.plan_count += 1
                # ---- 换约束重规划：与上一次同一批航点的结果对比 ----
                #   只在**航点一致**时比；否则"变快了"只是路径不同，没有意义。
                fingerprint = float(np.sum(np.abs(W))) + float(W.shape[1]) * 1e3
                same_path = (self._previous_plan is not None
                          and abs(self._previous_plan["fingerprint"] - fingerprint) < 1e-6
                          and self._previous_plan["waypoint_count"] == int(W.shape[0]))
                if same_path and report.sd is not None:
                    previous = self._previous_plan
                    indices = np.linspace(0, np.size(report.sd) - 1, 200).astype(int)
                    previous_speed_axis = np.asarray(previous["sd"], dtype=float)
                    previous_indices = np.linspace(0, np.size(previous_speed_axis) - 1, 200).astype(int)
                    # ★ 契约里 `对比` 是 **object**，所以直接给 dict。
                    #   我第一版写成了 `({...},)` —— 一个"含单个元素的元组"，
                    #   于是前端拿到的是数组，`对比.上次时长` 全是 undefined，
                    #   卡片上显示 "0.00 s → 0.00 s"。**结构对了内容才出得来**。
                    payload["comparison"] = {
                        "previous_duration": float(previous["duration_s"]),
                        "current_duration": float(report.duration_s),
                        "duration_change_percent": (
                            float(report.duration_s) / max(float(previous["duration_s"]), 1e-9) - 1.0
                        ) * 100.0,
                        "previous_max_velocity": float(previous["max_velocity"]),
                        "current_max_velocity": float(report.max_joint_velocity),
                        "previous_constraint": str(previous["constraint"]),
                        "current_constraint": str(source),
                        "previous_speed_axis": [float(x) for x in previous_speed_axis[previous_indices]],
                        "current_speed_axis": [float(x) for x in np.asarray(report.sd)[indices]],
                    }
                self._previous_plan = {
                    "fingerprint": fingerprint, "waypoint_count": int(W.shape[0]),
                    "duration_s": float(report.duration_s),
                    "max_velocity": float(report.max_joint_velocity),
                    "constraint": str(source), "sd": np.asarray(report.sd, dtype=float),
                }
                try:
                    import model_bridge as _model_bridge
                    _project_name = str(_model_bridge.read_setting("last_project", "") or "")
                except Exception:                                         # noqa: BLE001
                    _project_name = ""
                self.output_directory = _save_trajectory(report, self._package_root, _project_name)
                # 执行用的时间序列（与 CSV 同源，不另存一份"执行用"数据）
                self._trajectory_time = np.asarray(report.t, dtype=float)
                self._trajectory_positions = np.asarray(report.q, dtype=float)
                payload["output_path"] = self.output_directory or ""
        except Exception as exc:                                         # noqa: BLE001
            payload["status"] = "failed"
            payload["reason"] = f"{type(exc).__name__}: {exc}"
            self.error = str(payload["reason"])

        result = PlanningResult(**payload)
        self.latest = result
        try:
            self._send(result)
        except Exception as exc:                                         # noqa: BLE001
            print(f"⚠ 规划结果发送失败：{type(exc).__name__}: {exc}", flush=True)

    # ------------------------------------------------------------------
    # 执行：把轨迹当成"会动的目标"喂给现成的跟踪控制器
    # ------------------------------------------------------------------
    def start_execution(self) -> None:
        """开始按轨迹走。

        ★ 为什么不在这里直接写 `data.ctrl`：
          规格要求"由一个**独立的跟踪控制器**在仿真里忠实执行"。
          本项目里那个控制器**已经存在**（`算法库/通用/关节pd控制.py`），
          它的职责就是"跟一个目标走"。我们只要每步把"此刻该在哪"发过去，
          跟踪质量（超调、稳态误差）就由它负责 —— 这是**真实的解耦**，
          而不是在规划器里塞一段 PID 假装有控制器。
        ★ 走的还是 `面板目标消息` 这条既有通道（和界面滑杆同一条），
          所以不需要给规划器开特例通道。
        """
        if self._trajectory_time is None or self._trajectory_positions is None:
            print("⚠ 执行失败：还没有成功规划过（先点「规划」）", flush=True)
            return
        self.executing = True
        self.execution_start = time.time()
        self.execution_progress = 0.0
        self.execution_duration = float(self._trajectory_time[-1])
        self._publish_execution("running")
        print(f"▶ 开始执行轨迹：{self.execution_duration:.2f} 秒、"
              f"{self._trajectory_positions.shape[1]} 轴", flush=True)

    def stop_execution(self, reason: str = "") -> None:
        if not self.executing:
            return
        self.executing = False
        print(f"⏹ 轨迹执行结束：{reason}（进度 {self.execution_progress * 100:.0f}%）", flush=True)
        self._publish_execution("completed" if self.execution_progress >= 0.999 else "interrupted")

    @messages.handler
    def on_step(self, event: messages.StepEvent) -> bool:
        """每一步把"当前时刻该在的目标"发给跟踪控制器。"""
        if not self.executing or self._trajectory_time is None:
            return False
        try:
            elapsed = time.time() - self.execution_start
            if elapsed >= self.execution_duration:
                # 最后一帧保持在终点，让控制器收敛，而不是"到点就撒手"
                self.execution_progress = 1.0
                target = self._trajectory_positions[-1]
            else:
                self.execution_progress = elapsed / max(self.execution_duration, 1e-9)
                target = np.array([np.interp(elapsed, self._trajectory_time, self._trajectory_positions[:, i])
                                for i in range(self._trajectory_positions.shape[1])])
            from ui_bridge import PanelTargetMessage
            self._send(PanelTargetMessage(ctrl_target=target))
            # 2 Hz 播报进度（界面只需看到"走到哪了"，不需要每步一条）
            now = time.time()
            if now >= self._next_publish:
                self._next_publish = now + 0.5
                self._publish_execution("running")
            if elapsed >= self.execution_duration + 1.0:      # 到点后再多喂 1 秒让控制器收住
                self.stop_execution("到达终点")
        except Exception as exc:                                     # noqa: BLE001
            self.stop_execution(f"出错 {type(exc).__name__}: {exc}")
        return False

    def _publish_execution(self, status: str) -> None:
        """把执行状态发出去（复用最近一次规划结果的其余字段）。"""
        if self.latest is None:
            return
        try:
            self._send(dataclasses.replace(
                self.latest, execution_status=status,
                execution_progress=float(self.execution_progress)))
        except Exception:                                             # noqa: BLE001
            pass

    def publish_waypoint_count(self) -> None:
        """航点变化时让界面知道（用户想知道"记了几个点"）。"""
        try:
            self._send(PlanningResult(status="idle", waypoint_count=len(self.waypoints),
                                      timestamp=time.strftime("%H:%M:%S")))
        except Exception:                                             # noqa: BLE001
            pass


__all__ = ["PlanningCommand", "PlanningResult", "TrajectoryPlanner"]
