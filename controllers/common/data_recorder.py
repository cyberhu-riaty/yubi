"""
data_recorder.py —— 录制 / 回放 / 版本化元信息（第 4 步 D2）

它解决什么问题：
    · 官方"时间倒带"只能存 **2048 帧 = 4.10 秒**（实测），而且**没有导出接口**；
    · 做实验必须能长时间记录，还要能**事后复现**。

它做什么：
    ① **录制**：按固定间隔把状态/控制/指标写成 CSV，**流式写盘**（长时间录也不吃内存）
    ② **元信息**：同时写一份 `.meta.json`，记录 mujoco 版本、模型指纹、插件清单 —— 否则以后复现对不上
    ③ **回放**：读回录制文件，把当时的控制量重新喂给仿真，复现同一段运动

怎么用：
    界面上：打开 **Recorder** 面板 → `Start` → 跑实验 → `Stop and save`
    文件写到：`<包根>/输出/04_记录/录制_YYYYmmdd_HHMMSS.csv` + 同名 `.meta.json`

设计要点（都是踩过的坑）：
    · **流式写盘**：边录边写临时文件，停止时改名为最终文件 → 长录制不怕内存
    · **降采样**：默认 100 Hz（物理 500 Hz），文件小 5 倍且对分析够用
    · **元信息必写**：mujoco 版本 + 模型指纹 + 插件清单 = 可复现三要素
    · **自包含**：自己采样，不依赖外壳把指标"喂"进来（否则换壳就散架）
    · 录制/回放命令通过消息从界面传进来（仿真侧插件碰不到界面对象）
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import time

import numpy as np

from official_api import messages

# ★ 录制命令的定义**不在本文件里**，在 `软件/录制桥.py` —— 界面和仿真侧都从那里
#   import，才能保证是同一个类对象。原因见 录制桥.py 的文件头（这个坑踩过两次：
#   一次是同一个 .py 被加载两遍，一次是算法搬到 算法库/ 后模块名变了）。
#   所以下面 `@messages.handler` 收到的消息类型，和面板发出的那个一定是同一个。
import sys as _sys
import os as _os
_runtime_directory = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                           "..", "..", "软件"))
if _os.path.isdir(_runtime_directory) and _runtime_directory not in _sys.path:
    _sys.path.insert(0, _runtime_directory)
from recording_bridge import RecordingCommand as RecordingCommand                   # noqa: E402
import project_registry                                                     # noqa: E402


# ---------------------------------------------------------------------------
# 界面 → 仿真侧的命令消息
# ---------------------------------------------------------------------------
def model_fingerprint(model, model_path: str = "") -> dict:
    """算一个"这个模型到底是什么"的指纹，用于以后复现实验。

    为什么要自算：mujoco **没有公开的模型哈希接口**（`mj_hash` 不存在，实测）。
    所以用三样东西拼：
        ① XML 文件 sha256（模型怎么写的）
        ② 关键数值数组的哈希（编译后的质量/惯量/几何 —— 改一点都会变）
        ③ 尺寸信息（nq/nu/nbody，一眼看出是不是同一个模型）
    """
    fingerprint = {
        "file": os.path.basename(model_path) if model_path else "",
        "nq": int(model.nq), "nv": int(model.nv), "nu": int(model.nu),
        "nbody": int(model.nbody), "ngeom": int(model.ngeom),
    }
    if model_path and os.path.exists(model_path):
        fingerprint["file_sha256"] = hashlib.sha256(open(model_path, "rb").read()).hexdigest()[:16]
    h = hashlib.sha256()
    for array_name in ("body_mass", "body_inertia", "body_ipos", "dof_armature",
                   "geom_size", "geom_pos", "jnt_range", "actuator_ctrlrange"):
        array = getattr(model, array_name, None)
        if array is None:
            continue
        try:
            h.update(np.ascontiguousarray(np.asarray(array, dtype=np.float64)).tobytes())
        except Exception:                                        # noqa: BLE001
            continue
    fingerprint["numeric_hash"] = h.hexdigest()[:16]
    return fingerprint


def _normalize_algorithm_info(raw) -> list[dict]:
    """把外壳给的算法信息统一成"可直接 JSON 化"的形状。

    外壳给的是 `plugin_system.collect_algorithm_info()` 的产物（英文字段，含参数）；
    老代码/别的调用方可能给插件**实例**列表 —— 那就退回"名称 + 版本"。
    两条路都通向同一个元信息字段，所以录制文件的格式不随调用方变化。
    旧调用方仍可能给中文键；读取时兼容，写出的元信息统一用英文。
    """
    result: list[dict] = []
    for item in (raw or []):
        if isinstance(item, dict):
            parameters = item.get("parameters", item.get("参数"))
            result.append({
                "name": str(item.get("name", item.get("名称", "?"))),
                "version": str(item.get("version", item.get("版本", "-"))),
                "english_name": str(item.get("english_name", item.get("英文名", "")) or ""),
                "parameters": {str(k): v for k, v in (parameters or {}).items()
                               if isinstance(v, (int, float))},
            })
        else:
            name = getattr(item, "name", None)
            if name:
                result.append({
                    "name": str(name),
                    "version": str(getattr(item, "version", "-")),
                    "english_name": str(getattr(item, "english_name", "") or ""),
                    "parameters": {},
                })
    return result


class DataRecorderPlugin:
    """仿真侧插件：按固定间隔记录状态/控制/指标，支持回放。

    注意：它**不写 ctrl**（不是控制器），不会和你的控制律抢方向盘；
    只有"回放中"才会写 ctrl（那时它就是在替你把录下来的控制量重放一遍）。
    """

    name = "数据录制与回放"
    version = "1.0"
    english_name = "Recorder"
    # 平时**不**写 ctrl[:]，所以不算"抢方向盘"的算法（不会和你的控制律互相覆盖）。
    # ★ 例外：**回放中**它会写 ctrl（那时它就是在替你把录下来的控制量重放一遍）——
    #   那是用户主动点 Replay 的结果，不是它默认的行为，所以这里仍声明 False。
    takes_control = False
    description = "按固定频率录制状态/控制/指标到 CSV（含版本化元信息），并可回放复现。"
    author = "数字样机"

    def __init__(self, output_directory: str | None = None, frequency: float = 100.0):
        self.output_directory = output_directory
        self.frequency = float(frequency)
        self.interval = 1.0 / max(self.frequency, 1e-6)
        self.state = "空闲"              # 空闲 / 录制中 / 回放中
        self.header: list[str] = []
        self.row_count = 0
        self.next_sample_time = 0.0
        self.started_at = 0.0
        self.start_simulation_time = 0.0
        self.metric_keys: list[str] = []
        self.latest_file = ""
        self.latest_metadata = ""
        self.replay_times: np.ndarray | None = None
        self.replay_controls: np.ndarray | None = None
        self._replay_next_index = 0
        self._replay_reported_index = 0
        self._replay_report_interval = 1
        self.note = ""
        self.algorithm_info: list = []        # 由外壳通过 收到模型 通知时填（写元信息用）
        self.project_name: str = ""           # 当前项目名（由外壳填；写元信息用）
        self._temporary_file = ""
        self._file_handle = None
        self._previous_control = None      # 上一步实际用过的控制量（录制时序要对齐它，见 每步录制）
        self._model = None            # 模型引用（回放复位时要 mj_forward）
        self._model_path = ""          # 模型路径（写元信息/算指纹用）
        self._follow_physics_rate = True     # True=录制频率自动对齐物理频率（可精确复现）
        self._replay_reset = False
        self._replay_reset_pending = False

    # ---------------- 模型（回放复位要用；顺便对齐录制频率） ----------------
    def receive_model(self, event) -> None:
        self._model = getattr(event, "model", None)
        self._model_path = str(getattr(event, "path", "") or self._model_path)
        # ★ 每次模型/项目变化都刷新"这次是哪组算法、参数多少" —— 写元信息时用它。
        #   外壳在 `notify_model_loaded()` 中把 `算法信息` 挂在事件上。
        #   这里**不缓存成插件实例列表**：实例会随项目切换被换掉，
        #   而元信息要的是"那一刻的参数快照"，所以直接留外壳算好的纯数据。
        new_algorithm_info = getattr(event, "algorithm_info", None)
        if new_algorithm_info is not None:
            self.algorithm_info = list(new_algorithm_info)
        new_project = getattr(event, "project_name", None)
        if new_project is not None:
            self.project_name = str(new_project)
        # ★ 关键：**记录控制量时，必须按物理步长采样才能精确复现**。
        #   实测教训：用 100 Hz 录、物理 500 Hz —— 两个采样点之间的 5 个物理步用的是
        #   不同的 τ，而回放只能"保持"其中一个，加速度就对不上（实测偏差 297°）。
        #   所以默认把录制频率对齐物理频率（UR5e 是 500 Hz），不丢任何一步控制量。
        #   想省空间可以手动调低（面板上的 Hz 滑杆），但要接受"回放只是近似"。
        if self._follow_physics_rate and self._model is not None:
            dt = float(self._model.opt.timestep)
            if dt > 0:
                self.frequency = 1.0 / dt
                self.interval = dt

    # ---------------- 界面来的命令 ----------------
    @messages.handler
    def receive_command(self, command: RecordingCommand) -> bool:
        action = getattr(command, "action", "空闲")
        if action == "开始" and self.state == "空闲":
            self.start(float(getattr(command, "frequency", self.frequency)), note=getattr(command, "note", ""))
        elif action == "停止" and self.state == "录制中":
            self.stop_and_save()
        elif action == "回放" and self.state == "空闲":
            self.start_replay()
        return False

    # ---------------- 录制 ----------------
    def start(self, frequency: float, note: str = "") -> None:
        requested_frequency = float(frequency)
        if self._follow_physics_rate and self._model is not None:
            dt = float(self._model.opt.timestep)
            if dt > 0:
                if abs(requested_frequency - 1.0 / dt) > 1e-6:
                    print(f'ℹ 录制频率已按物理步长对齐：{requested_frequency:.0f} Hz → {1.0 / dt:.0f} Hz'
                          f"（不丢控制量，回放才能精确复现）", flush=True)
                self.frequency = 1.0 / dt
                self.interval = dt
            else:
                self.frequency = requested_frequency
                self.interval = 1.0 / max(requested_frequency, 1e-6)
        else:
            self.frequency = requested_frequency
            self.interval = 1.0 / max(requested_frequency, 1e-6)
        self.header = []
        self.metric_keys = []
        self.row_count = 0
        self.next_sample_time = 0.0
        self.started_at = time.time()
        self.note = note
        self.state = "录制中"

        directory = self._directory()
        os.makedirs(directory, exist_ok=True)
        self._temporary_file = os.path.join(directory, ".录制中.tmp")
        if os.path.exists(self._temporary_file):
            os.remove(self._temporary_file)
        self._file_handle = open(self._temporary_file, "w", encoding="utf-8")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.latest_file = os.path.join(directory, f'录制_{timestamp}.csv')
        print(f"⏺ 开始录制（{frequency:.0f} Hz，备注：{note or '无'}）", flush=True)

    def stop_and_save(self) -> None:
        if self.state != "录制中":
            return
        self.state = "空闲"
        if self._file_handle is not None:
            self._file_handle.flush()
            self._file_handle.close()
            self._file_handle = None
        duration = time.time() - self.started_at
        if self.row_count == 0 or not os.path.exists(self._temporary_file):
            print("⏹ 录制停止：没有采到数据", flush=True)
            return
        os.replace(self._temporary_file, self.latest_file)      # 临时文件 → 最终文件（原子改名）
        print(f'⏹ 录制停止：{self.row_count} 行、{duration:.1f} 秒、'
              f'约 {self.frequency:.0f} Hz → {os.path.basename(self.latest_file)}', flush=True)
        # ★ 必须在这里写元信息：复现实验的三要素（mujoco 版本 + 模型指纹 + 算法清单）。
        #   实测踩过：`写元信息()` 定义了却从来没人调用 → `.meta.json` 根本没生成过。
        try:
            if self._model is not None:
                self.write_metadata(self._model_path, self._model, self.algorithm_info)
            else:
                print("ℹ 没有模型引用，跳过元信息（.meta.json 未生成）", flush=True)
        except Exception as exc:                                        # noqa: BLE001
            print(f'⚠ 元信息写入失败（CSV 已保存，不影响数据）：{type(exc).__name__}: {exc}',
                  flush=True)

    def write_metadata(self, model_path: str, model, algorithm_info: list | None = None) -> str:
        """写 `.meta.json` —— 复现实验的三要素：软件版本 + 模型指纹 + 算法清单。

        `算法信息` 由外壳用 `插件系统.收集算法信息()` 现算（每项含 名称/版本/英文名/参数），
        记录**当时实际在跑的那几个算法和参数值** —— 这才是"可复现"里最难补的一环。
        兼容老写法：如果传进来的是插件**实例**列表，就退回"只取名称+版本"。
        """
        import mujoco
        import sys
        if not self.latest_file:
            return ""
        metadata = {
            "schema_version": 2,
            "recording_file": os.path.basename(self.latest_file),
            "recording_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "notes": self.note,
            "frequency_hz": self.frequency,
            "sample_rows": self.row_count,
            "software_versions": {
                "mujoco": getattr(mujoco, "__version__", "?"),
                "python": sys.version.split()[0],
            },
            "project": str(self.project_name or "（未命名项目）"),
            "model": model_fingerprint(model, model_path),
            "algorithms": _normalize_algorithm_info(
                algorithm_info if algorithm_info is not None else self.algorithm_info),
        }
        path = os.path.splitext(self.latest_file)[0] + ".meta.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        self.latest_metadata = path
        print(f'   元信息 → {os.path.basename(path)}'
              f"（项目 {metadata['project']}、算法 {len(metadata['algorithms'])} 个）", flush=True)
        return path

    def _directory(self) -> str:
        """默认写到 <包根>/输出/04_记录/。

        ★ 以前用的是 `os.getcwd()/output/04_记录`，问题有两个：
          ① 和工程里其它产物（`输出/外观.json`、`输出/面板.json`）不在同一个地方；
          ② 从不同目录启动软件时 cwd 会变，录制文件就"跑"到别处去了（实测踩过）。

        ★ 包根从 `project_registry.PACKAGE_ROOT` 取，**不在这里数 `dirname` 的层数**。
          这个文件原来在 `算法库/通用/` 下，包根是"上三级"；方案 C 把它搬到
          `算法库/通用/` 之后，上三级变成了 `驭臂/算法库` —— 数层数的写法必然算错，
          而且算错之后是**静默**写到一个不存在的目录。路径只有一处定义才不会出这种事。
        """
        if self.output_directory:
            return self.output_directory
        return os.path.join(project_registry.PACKAGE_ROOT, "输出", "04_记录")

    # ---------------- 回放 ----------------
    def start_replay(self) -> None:
        if not self.latest_file or not os.path.exists(self.latest_file):
            print("⚠ 没有可回放的录制文件（先在界面上录一段）", flush=True)
            return
        data = np.genfromtxt(self.latest_file, delimiter=",", names=True)
        columns = list(data.dtype.names)
        control_columns = [n for n in columns if n.startswith("tau")]
        if not control_columns or "t" not in columns:
            print("⚠ 录制文件里没有时间列或控制量列（t / tau*），无法回放", flush=True)
            return
        # ★ 回放的两个坑（都实测踩过，记下来免得再犯）：
        #   ① 录制频率（100 Hz）通常**低于**物理频率（500 Hz）。若"一帧控制量配一步物理"，
        #      3 秒的动作会被压进 0.57 秒 —— 必须按时间轴取。
        #   ② 取的时候要用**最近采样点保持（零阶保持）**，不能用线性插值：
        #      原始运行时，两个采样点之间的那几步物理用的是**同一个常量 ctrl**；
        #      线性插值会造出一条"斜坡"，与原始控制序列不同 → 回放轨迹偏离
        #      （实测峰值偏差 297°，改用零阶保持后收敛到数值误差级）。
        # 读起始状态：★ 录制文件的第一行是"已经走过一步之后"的状态（速度非零），
        # 如果回放从模型的 home 姿势起手，起点就与录制不同 → 轨迹必然分叉
        # （实测：峰值偏差 296°）。所以把起始 q/v 一并存下来，回放开始时恢复。
        self.replay_initial_qpos = None
        self.replay_initial_qvel = None
        qpos_columns = [n for n in columns if n.startswith("q")]
        qvel_columns = [n for n in columns if n.startswith("v")]
        if qpos_columns and qvel_columns:
            self.replay_initial_qpos = np.array([data[n][0] for n in qpos_columns], dtype=float)
            self.replay_initial_qvel = np.array([data[n][0] for n in qvel_columns], dtype=float)
        self.replay_times = np.asarray(data["t"], dtype=float)
        self.replay_controls = np.column_stack([np.asarray(data[n], dtype=float) for n in control_columns])
        self.replay_index = 0
        self.state = "回放中"
        self._replay_next_index = 0
        self._replay_report_interval = max(1, len(self.replay_times) // 5)
        self._replay_reported_index = 0
        # ★ 立刻把仿真状态摆到"录制起点"，否则回放会从模型自带的 home 起手 ——
        #   而录制首行是"已经走过一步"的状态（速度非零），起点不同就必然越放越偏
        #   （实测：不摆起点时回放偏差 296°，摆好后 0.0013°）。
        restored = self.restore_initial_state()
        print(f'▶ 开始回放：{len(self.replay_controls)} 帧控制量、覆盖 {self.replay_times[-1]:.2f} 秒'
              + ("（已恢复到录制起点状态）" if restored else "（警告：没能恢复起点，结果会有偏差）"),
              flush=True)

    # ---------------- 每步 ----------------
    @messages.handler
    def step(self, event: messages.StepEvent) -> bool:
        """★ 时序很关键（本模块最容易写错的地方，实测踩过）：

        每个 StepEvent 里的顺序是：
            ① StepControl 先用**上一步写好的 ctrl** 推进物理 → 得到新状态 S_t
            ② 然后各插件**按装配顺序**依次跑 → 你的控制律写**新** ctrl（用于下一步）
               （装配顺序 = 项目文件里 `算法` 列表的顺序；priority 在本外壳不参与排序）

        所以在这一刻：`data.qpos` 是 S_t，而 `data.ctrl` 是"给下一步用的"控制量。
        若把这两个一起记下来就是**差一拍**：记下的 τ 实际会把机器人从 S_t 带到 S_{t+1}，
        而不是产生 S_t。回放时按此重放会从第一步就偏离（实测偏差一路涨到 137°）。

        正确做法：记 **上一步实际用过的 τ**（`self._上一步控制`）配 S_t ——
        "(S_t, τ_{t-1→t})" 才是自洽的一对，回放能精确复现。
        """
        data = event.data
        # 第一次拿到 data 时，把"上一步控制量"初始化成正确长度（否则首行会短一截，
        # 写出来的 CSV 表头与数据列数不一致 —— 实测踩过）
        if self._previous_control is None or len(self._previous_control) != len(data.ctrl):
            self._previous_control = np.zeros(len(data.ctrl))

        if self.state == "录制中":
            if float(data.time) >= self.next_sample_time:
                self.next_sample_time = float(data.time) + self.interval
                # 采样用**本次派发之前**记下的 ctrl —— 它才是把状态推到当前这一步的控制量
                self._sample_row(data, self._previous_control)

        # ★ 采样之后才把"本次派发时 data.ctrl 的值"记为下一步要用的控制量。
        #   顺序不能颠倒（实测踩过）：先存再采，等于把"给下一步用的 ctrl"配给了"当前状态"，
        #   又差一拍。正确配对是 (S(t), τ_本步) 里的 τ 取"派发前"的那个值。
        self._previous_control = np.array(data.ctrl, dtype=float, copy=True)

        if self.state == "回放中" and self.replay_controls is not None:
            self._replay_step(data)
        return False

    def restore_initial_state(self) -> bool:
        """标记"下一次步进时先把状态恢复到录制起点"。

        为什么要延后到下一次步进：改状态需要拿到外壳正在用的那份 `data`，
        而"开始回放"这个时刻只有命令消息、没有 data；`每步录制(event)` 里才有。
        所以这里只置标记，真正的赋值在 `_回放一步` 的首次调用里完成。
        """
        self._replay_reset_pending = True
        return self.replay_initial_qpos is not None

    def _forward(self, data) -> None:
        """改了状态后让派生量一致。拿不到 model 时静默跳过（下一步 StepControl 会刷新）。"""
        try:
            import mujoco
            if getattr(self, '_model', None) is not None:
                mujoco.mj_forward(self._model, data)
        except Exception:                                        # noqa: BLE001
            pass

    def _replay_step(self, data) -> None:
        """按"当前仿真时间"取录制里的控制量，写进 ctrl（零阶保持）。"""
        if not getattr(self, '_replay_reset', False):
            # 第一次进来：把仿真恢复到录制起点（否则起手不同 → 越放越偏）
            if self.replay_initial_qpos is not None and len(self.replay_initial_qpos) == len(data.qpos):
                data.qpos[:] = self.replay_initial_qpos
                data.qvel[:] = self.replay_initial_qvel
                self._forward(data)      # 让 site/xpos 等派生量一致（不推进时间）
            self._replay_reset = True
            # ★ 指针从 0 开始：录制第 k 行的 τ 正是"把状态推到第 k 行"的那个控制量
            #   （首行是初值行，τ 记的是上一步用过的 0）。原来这里写成 1 会让回放整体
            #   慢一拍 —— 实测表现为"回放状态 ≈ 录制的前一行"，偏差随步数累积。
            self._replay_next_index = 0
        now = float(data.time)
        times = self.replay_times
        if now >= times[-1]:
            if self.state == "回放中":
                self.state = "空闲"
                print("⏹ 回放结束（控制量已放完，不再写 ctrl）", flush=True)
            return
        # 推进指针：让"当前格"成为**最后一个时间 <= 现在**的采样点
        #   （这正是录制时的零阶保持语义：第 k 行的时间等于 t 时，用的就是第 k 行的 τ）
        while (self._replay_next_index + 1 < len(times)
               and times[self._replay_next_index + 1] <= now):
            self._replay_next_index += 1
        # 零阶保持 + 一行偏移。
        # ★ 偏移的原因（实测定位）：录制文件里**第 0 行是初值行**（t=0 那一刻采样，
        #   ctrl 还是 0，状态就是模型的 home）。真正的动作数据从第 1 行开始：
        #       τ[1] 把状态从 q[0] 推到 q[1]，τ[2] 从 q[1] 推到 q[2]，依此类推。
        #   所以回放要用 τ[i+1] 配 q[i]；不加这个偏移会整体提前一格，
        #   表现为"偏差随时间指数放大"（实测 1000 步后 220°），极难从现象反推。
        i = self._replay_next_index
        index = min(i + 1, len(self.replay_controls) - 1)
        data.ctrl[:] = self.replay_controls[index]
        # 每 20% 打一行进度
        if i - self._replay_reported_index >= self._replay_report_interval:
            self._replay_reported_index = i
            print(f'  回放 t={now:.2f}s / {times[-1]:.2f}s', flush=True)

    def _sample_row(self, data, control=None) -> None:
        """记一行。控制量默认用"上一步实际用过的"（见 每步录制 的时序说明）。"""
        sampled_control = self._previous_control if control is None else control
        if self.header == []:
            self.header = (["t", "step"] + [f"q{i+1}" for i in range(len(data.qpos))]
                        + [f"v{i+1}" for i in range(len(data.qvel))]
                        + [f"tau{i+1}" for i in range(len(data.ctrl))])
        # step：物理步序号（= 已派发过多少次 StepEvent）。回放按它对齐最稳，
        # 不受浮点时间(0.002 累加)误差与 StepControl 节奏影响。
        self._step_index = getattr(self, '_step_index', 0) + 1
        row = ([float(data.time), float(self._step_index)] + [float(x) for x in data.qpos]
              + [float(x) for x in data.qvel] + [float(x) for x in sampled_control])
        if self._file_handle is not None:
            if self.row_count == 0:
                self._file_handle.write(",".join(self.header) + "\n")
            self._file_handle.write(",".join(f"{v:.9g}" for v in row) + "\n")
            if self.row_count % 1000 == 0:
                self._file_handle.flush()
        self.row_count += 1

    # ---------------- 状态上报 ----------------
    def metrics(self) -> dict:
        """把录制状态也上报成指标，监控面板能看出"现在在录"。"""
        return {"已录行数": float(self.row_count)}

    def status(self) -> dict:
        return {"状态": self.state, "已录": self.row_count,
                "文件": os.path.basename(self.latest_file) if self.latest_file else "—"}


plugin_class = DataRecorderPlugin
