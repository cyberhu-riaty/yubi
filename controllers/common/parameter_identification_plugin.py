"""
parameter_identification_plugin.py —— D3 的界面后端（仿真侧）

它把已验证的 `参数辨识.py` 接到界面上：
    ① 激励采样：在当前模型上做一段闭环激励，记录 q/v/τ（用于辨识）
    ② 辨识：后台线程跑 Gauss-Newton，不阻塞实时仿真
    ③ 用新参数验证：把辨识结果写进模型并重编译，和"贡献"对照

为什么辨识要放后台线程：
    一次辨识约 1 秒、上百次模型前向。如果塞进 每步控制() 里跑，
    仿真会卡住 1 秒（界面看起来像死了）。所以开线程，用状态消息把进度发回界面。

★ 验证指标的诚实说明（这条很重要，免得误判）：
    我们只能拿"**贡献模型的响应**"当参考，而不是真机。
    所以验证只能说明"辨识结果比原始标称值更贴近这段数据"，**不能**说明"找到了真值"。
    真正证明算法能找到真值的证据，是 `验证参数辨识.py` 那个离线闭环实验
    （造已知真值 → 辨识 → 误差 1.47%）。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import numpy as np

from official_api import messages

# ★ 本文件在 `算法库/通用/` 下，但它要 import 外壳侧的 `参数辨识`、`辨识桥`、`项目`
#   —— 那三个在 `runtime/` 里。所以先保证 `runtime/` 在 sys.path 上。
#   （外壳通过 `装配器` 装配时也会加，但本文件被单独 import 时同样要能跑，
#     所以这一道自己带 —— 不能依赖调用方帮忙铺路。）
import os as _os
import sys as _sys
_runtime_directory = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                           "..", "..", "runtime"))
if _os.path.isdir(_runtime_directory) and _runtime_directory not in _sys.path:
    _sys.path.insert(0, _runtime_directory)

from parameter_identification import (                                      # noqa: E402
    ParameterDefinition as ParameterDefinition,
    collect_data as collect_data,
    identify as identify,
)
from identification_bridge import (                                         # noqa: E402
    IdentificationCommand as IdentificationCommand,
    IdentificationState as IdentificationState,
)

# ★ 模型目录不在这里数 `dirname` 的层数：本文件原来在 `算法库/通用/` 下，
#   方案 C 搬到 `算法库/通用/` 之后层数变了，数层数的写法会**静默**指到别的目录
#   （读不到参数表 → 所有模型都显示"不支持辨识"，很难查）。
#   统一从 `project_registry.py` 取，路径只有一处定义。
import project_registry                                                    # noqa: E402
_model_directory = project_registry.MODEL_DIRECTORY
_parameter_table_path = os.path.join(_model_directory, "辨识参数表.json")


def read_parameter_table() -> dict:
    """读 `模型/辨识参数表.json`（每个模型可辨识哪些连杆）。读不到就返回空表。"""
    try:
        with open(_parameter_table_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("模型", {}) if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:                                        # noqa: BLE001
        print(f'⚠ 辨识参数表读取失败：{type(exc).__name__}: {exc}')
        return {}


def lookup_parameters(model_path: str) -> tuple[list[tuple] | None, str]:
    """按模型路径查可辨识参数。返回 (参数列表, 说明)；查不到返回 (None, 原因)。

    ★ 为什么要按模型查（而不是像以前那样写死）：
      UR 系列的连杆叫 forearm_link / upper_arm_link / wrist_1_link，
      而 Panda 是 link4、iiwa 是 link2、xArm7 是 link1 —— 名字完全不同。
      以前写死 UR5e 的名字，换成别的机械臂后点"辨识"只会得到一堆无效结果，
      用户看不出来为什么。现在按模型查表，表里没有的模型就**明说"不支持"**。
    """
    if not model_path:
        return None, "还不知道模型路径"
    table = read_parameter_table()
    if not table:
        return None, "找不到 模型/辨识参数表.json"
    normalized = os.path.normpath(model_path).replace("\\", "/")
    parts = normalized.split("/")
    relative_key = "/".join(parts[-2:]) if len(parts) >= 2 else normalized
    filename = parts[-1]
    for key, entry in table.items():
        if key == relative_key or os.path.basename(key) == filename:
            parameters = [(p["名称"], (p["连杆"], p["字段"]), float(p["初值"]),
                     (float(p["下界"]), float(p["上界"])))
                    for p in entry.get("参数", [])]
            if parameters:
                return parameters, str(entry.get("显示名", key))
    return None, f'模型库里没有「{filename}」的辨识参数配置'


class ParameterIdentificationPlugin:
    """仿真侧插件：接收界面命令，执行辨识，回传状态。

    ★ 可辨识参数**按模型查表**（`模型/辨识参数表.json`），不再写死 UR5e 的连杆名。
      表里没有的模型会明确显示"不支持"，而不是假装跑一遍。
    """

    name = "参数辨识"
    version = "1.1"
    english_name = "System identification"
    # 不写 ctrl[:]（不抢方向盘）→ 不会和别的算法互相覆盖
    takes_control = False
    description = "在界面上做闭环激励采样 → 后台辨识惯性参数 → 用新参数验证轨迹拟合。"
    author = "数字样机"

    def __init__(self, model_path: str = ""):
        self.model_path = model_path
        self.state = "空闲"          # 空闲 / 采样中 / 辨识中 / 不支持
        self.progress = ""
        self.result_rows: list[tuple] = []      # [(名称, 标称, 估计值, 误差%)]
        self.fit = {}                     # {"标称": …, "辨识后": …}
        self.sample_count = 0
        self.elapsed_time = 0.0
        self.log: list[str] = []
        self._thread = None
        self._data = None
        self._nominal_values = {}
        self._model = None
        self.identifiable_parameters: list[tuple] = []      # 当前模型的可辨识参数（由 _刷新参数表 填）
        self.supported = False
        self.unsupported_reason = ""
        self._refresh_parameters()

    # ------------------------------------------------------------------
    def _refresh_parameters(self) -> None:
        """按当前 模型路径 换一张可辨识参数表。"""
        parameters, description = lookup_parameters(self.model_path)
        if parameters is None:
            self.supported = False
            self.identifiable_parameters = []
            self.unsupported_reason = description
            self.state = "不支持"
            self.progress = description
        else:
            self.supported = True
            self.identifiable_parameters = parameters
            self.unsupported_reason = ""
            if self.state == "不支持":
                self.state = "空闲"
                self.progress = ""

    def receive_model(self, event) -> None:
        self._model = getattr(event, "model", None)
        if not self.model_path:
            self.model_path = getattr(event, "路径", "") or self.model_path
            self._refresh_parameters()

    def bind_model_path(self, path: str) -> "ParameterIdentificationPlugin":
        self.model_path = path
        self._refresh_parameters()
        return self

    def model_changed(self, path: str, model, data) -> None:
        """外壳在换模型后调用：清掉跟旧模型绑定的采样数据与结果。"""
        self.model_path = path
        self._data = None
        self._nominal_values = {}
        self._model = model
        self.result_rows = []
        self.fit = {}
        self.sample_count = 0
        self.elapsed_time = 0.0
        self.state = "空闲"
        self.progress = ""
        self._refresh_parameters()
        if self.supported:
            self._append_log(f'模型已切换为 {os.path.basename(path)}（可辨识 '
                     f'{len(self.identifiable_parameters)} 个连杆质量）')
        else:
            self._append_log(f'⚠ 模型已切换为 {os.path.basename(path)}，但{self.unsupported_reason}')

    # ------------------------------------------------------------------
    @messages.handler
    def receive_command(self, command: IdentificationCommand) -> bool:
        action = getattr(command, "action", "空闲")
        if action == "采样":
            self._start_sampling(float(getattr(command, "duration", 1.0)))
        elif action == "辨识":
            self._start_identification()
        return False

    # ------------------------------------------------------------------
    def _append_log(self, line: str) -> None:
        self.log.append(line)
        if len(self.log) > 12:
            self.log = self.log[-12:]
        print(f'  [辨识] {line}', flush=True)

    def _start_sampling(self, duration: float) -> None:
        if self.state != "空闲":
            return
        if not self.model_path:
            self._append_log("✗ 不知道模型路径，无法采样")
            return
        if not self.supported:
            # ★ 表里没有这个模型 → 明说，不要假装跑一遍（见 查参数表 的说明）
            self._append_log(f'✗ 当前模型不支持参数辨识：{self.unsupported_reason}')
            self._append_log("  要支持它，请在 模型/辨识参数表.json 里为它加一条配置")
            return
        self.state = "采样中"
        self.progress = f'正在激励采样（{duration:.1f} 秒）…'
        try:
            t0 = time.time()
            self._data = collect_data(self.model_path, duration=duration)
            self.sample_count = self._data.step_count
            # 记下当前模型的标称值（用于对比）
            self._nominal_values = {name: initial for name, _, initial, _ in self.identifiable_parameters}
            self._append_log(f'✓ 采到 {self.sample_count} 步（{time.time() - t0:.1f}s）')
            # 顺手算一个"标称模型的拟合残差"作为基线
            self.fit["标称"] = self._fit_residual(self._nominal_values)
            self._append_log(f"  标称参数下的拟合残差 {self.fit['标称']:.6f}")
        except Exception as exc:                                     # noqa: BLE001
            self._append_log(f'✗ 采样失败：{type(exc).__name__}: {exc}')
        finally:
            self.state = "空闲"
            self.progress = ""

    def _fit_residual(self, values: dict) -> float:
        """给定参数，用记录的 τ 做一步预测，返回残差范数（越小越贴合数据）。"""
        data = self._data
        parameters = [ParameterDefinition(name, target, values.get(name, initial), bounds[0], bounds[1])
                  for name, target, initial, bounds in self.identifiable_parameters]
        try:
            model = _make_model(self.model_path, parameters)
        except Exception:                                            # noqa: BLE001
            return float("inf")
        import mujoco
        d = mujoco.MjData(model)
        indices = np.arange(1, len(data.time), 5)
        squared_error = 0.0
        for k in indices:
            d.qpos[:] = data.qpos[k - 1]
            d.qvel[:] = data.qvel[k - 1]
            mujoco.mj_forward(model, d)
            d.ctrl[:] = data.ctrl[k]
            mujoco.mj_step(model, d)
            squared_error += float(np.sum((d.qpos - data.qpos[k]) ** 2))
        return float(np.sqrt(squared_error / max(len(indices), 1)))

    def _start_identification(self) -> None:
        if self.state != "空闲":
            return
        if not self.supported:
            self._append_log(f'✗ 当前模型不支持参数辨识：{self.unsupported_reason}')
            return
        if self._data is None:
            self._append_log("✗ 还没有采样数据，先点「激励采样」")
            return
        self.state = "辨识中"
        self.progress = "辨识中（后台线程）…"
        self._thread = threading.Thread(target=self._identify_in_thread, daemon=True)
        self._thread.start()

    def _identify_in_thread(self) -> None:
        try:
            parameters = [ParameterDefinition(name, target, initial, bounds[0], bounds[1])
                      for name, target, initial, bounds in self.identifiable_parameters]
            result = identify(self._data, parameters, stride=5,
                        print_result=lambda line: self._append_log(line.strip()))
            self.elapsed_time = result.elapsed_time
            estimates = {name: float(v) for (name, _, _, _), v in
                    zip(self.identifiable_parameters, result.estimates)}
            self.result_rows = []
            for name, _, initial, _ in self.identifiable_parameters:
                estimate = estimates[name]
                error = abs(estimate - initial) / max(abs(initial), 1e-9) * 100
                self.result_rows.append((name, initial, estimate, error))
            self.fit["辨识后"] = self._fit_residual(estimates)
            improvement = (self.fit.get("标称", 0) / max(self.fit.get("辨识后", 1e-12), 1e-12))
            self._append_log(f'✓ 辨识完成：耗时 {self.elapsed_time:.1f}s')
            self._append_log(f"  拟合残差 {self.fit.get('标称', float('nan')):.6f} → "
                     f"{self.fit.get('辨识后', float('nan')):.6f}（改善 {improvement:.1f}×）")
        except Exception as exc:                                     # noqa: BLE001
            self._append_log(f'✗ 辨识失败：{type(exc).__name__}: {exc}')
        finally:
            self.state = "空闲"
            self.progress = ""

    # ------------------------------------------------------------------
    def metrics(self) -> dict:
        return {"已采样步数": float(self.sample_count)}

    def status(self) -> dict:
        return {"状态": self.state, "采样": self.sample_count,
                "拟合改善": (f"{self.fit.get('标称', 0) / max(self.fit.get('辨识后', 1), 1e-12):.1f}×"
                            if "辨识后" in self.fit else "—")}

    def state_message(self) -> IdentificationState:
        """打包给界面的状态。"""
        return IdentificationState(state=self.state, progress=self.progress, sample_count=self.sample_count,
                        results=list(self.result_rows), fit=dict(self.fit),
                        elapsed_time=self.elapsed_time, log=list(self.log[-8:]))


def _make_model(model_path: str, parameters: list[ParameterDefinition]):
    """按参数造模型（复用 参数辨识 里的边界夹取与写入逻辑）。"""
    import mujoco
    from parameter_identification import write_parameter as _write_parameter
    spec = mujoco.MjSpec.from_file(model_path)
    for p in parameters:
        _write_parameter(spec, p.target, float(np.clip(p.initial, p.lower, p.upper)))
    return spec.compile()


plugin_class = ParameterIdentificationPlugin
