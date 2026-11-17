"""Panda_抓取演示.py —— 脚本化抓取（pick & place），用于把“能抓”跑通。

它**不是**官方 MPC，也不是学习型算法；它是一条可解释的抓取状态机：

    张开 → 到方块上方 → 下探到方块 → 闭合 → 抬起 → 搬到目标上方
         → 用方块位置做外环微调 → 放下 → 松开

为什么要有它：
  · MJPC 的 CEM 版只会优化“手到方块 / 方块到目标”的位置残差，
    代价里没有“张开/闭合夹爪”，也没有“手指是否跨住方块”；
  · 所以它攥着闭合的夹爪去够方块，一碰就把方块推走；
  · 这条状态机把“什么时候开、什么时候闭、什么时候搬”写死，
    用指垫中点（touch_left/right 的中点）而不是手掌中心去对准方块，
    先证明“这个模型能抓”，再谈更聪明的算法。

动作：6 维末端力/力矩（`eeff` site 执行器）+ 1 维夹爪；
夹爪 `+0.1` 张开、`-0.1` 闭合、`0` 保持。

目标点默认放到地面（`目标高度=0.02`）：空中悬停会要求夹爪长时间
抗重力，当前夹持力会打滑；放到地面是“抓起来、搬过去、放下”的完整闭环。

---------------------------------------------------------------------------
怎么读这个文件（建议顺序）
---------------------------------------------------------------------------
  ① `_旋转误差()`          —— 3D 姿态误差怎么算（轴角）
  ② `模型兼容性()`         —— 先确认“这个模型能不能用这套控制器”
  ③ `_初始化()`            —— 开局要记住哪些量：方块/目标/手掌姿态
  ④ `_阶段表()`            —— 抓取被拆成哪 8 段，每段的目标和夹爪命令
  ⑤ `每步控制()`           —— 500 Hz 真正跑的那段：状态机 + 笛卡尔阻抗
  ⑥ `可调参数/指标`        —— 怎么在界面调参、看结果
---------------------------------------------------------------------------
"""
# `from __future__ import annotations`：让类型注解（如 list[str]）延迟求值，
# Python 3.10 也能用新写法；对本文件的行为没有影响。
from __future__ import annotations

import numpy as np          # 向量/矩阵运算：位置、旋转、雅可比、clip
import mujoco               # MuJoCo 官方 API：取 site 位置、雅可比、传感器

import plugin_system as plugin       # 外壳的插件兼容层（唯一碰官方 Studio 的地方）
from plugin_system import ControlPlugin, step_handler  # 控制插件基类 + “每步调用”装饰器

# 这套控制器依赖 MJPC 任务模型里的 6 个传感器：
#   hand   = eeff（手掌）位置
#   box    = 方块几何中心
#   box1/2 = 方块两侧的 site
#   target1/2 = 目标两侧的 site
# 少一个就算不出“方块到目标”，所以模型兼容性会逐個检查。
REQUIRED_SENSORS = ("hand", "box", "box1", "box2", "target1", "target2")

# 这套控制器依赖的 3 个 site：
#   eeff        = 手掌上的参考点（6 维力/力矩执行器就作用在它上面）
#   touch_left  = 左手指垫
#   touch_right = 右手指垫
# 真正夹住方块的是两个指垫，不是 eeff —— 这是本文件最关键的几何认识。
REQUIRED_SITES = ("eeff", "touch_left", "touch_right")

# 夹爪执行器（intvelocity）的三种命令：
#   +0.1 张开到 0.04
#   -0.1 闭合到 0.005
#    0.0 保持当前开合
OPEN, CLOSE, HOLD = 0.1, -0.1, 0.0


def _rotation_error(desired_rotation: np.ndarray, current_rotation: np.ndarray) -> np.ndarray:
    """返回从 `R当前` 转到 `R目标` 的轴角向量（3 维）。

    输入都是 3x3 旋转矩阵（列 = 局部坐标轴在世界系里的方向）。
    这一步只用于“保持手掌朝向”，不参与位置控制。
    """
    # R = R目标 * R当前^T：把“当前姿态”先转回单位阵，再转到目标姿态。
    # 得到的 R 是一个“相对旋转”，它的轴角就是我们要的误差。
    R = desired_rotation @ current_rotation.T

    # 旋转矩阵的迹：tr(R) = 1 + 2cos(角度)
    # 所以 cos(角度) = (tr(R)-1)/2；clip 防止浮点误差越界。
    c = float(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))
    a = float(np.arccos(c))          # 旋转角（弧度）

    # 角度极小时，轴角公式的分母 sin(a) 接近 0，直接返回零误差，
    # 避免除零产生 NaN。
    if a < 1e-6:
        return np.zeros(3)

    # 旋转矩阵的反对称部分给出“旋转轴 × sin(角度)”：
    #   axis ∝ [R32-R23, R13-R31, R21-R12]
    # 再乘 a / (2 sin a) 就得到“轴 × 角度”的向量。
    axis = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return axis * a / (2.0 * np.sin(a))


class PandaPickPlaceController(ControlPlugin):
    """控制插件：外壳每 2 ms 调一次 `每步控制()`，这里写抓取状态机。"""
    parameter_aliases = {'朝向阻尼': 'orientation_damping', '速度阻尼': 'velocity_damping', '朝向增益': 'orientation_gain', '目标偏置Y': 'target_offset_y', '位置增益': 'position_gain', '目标高度': 'target_height', '目标偏置X': 'target_offset_x'}

    # ---- 插件元信息（启动清单/界面显示用）----
    name = "Panda 抓取演示（脚本化）"
    version = "0.1"
    english_name = "Panda scripted pick & place"
    description = "指垫对准 + 状态机：张开→下探→闭合→抬起→搬到目标→微调→放下。不是 MPC。"
    author = "数字样机"
    # 本插件会写 data.ctrl[:]，所以声明“接管控制”，
    # 外壳据此提示“多个算法抢方向盘”的情况。
    takes_control = True

    # ---- 控制器增益（都是“可调参数”，界面滑杆能直接改）----
    # 位置增益：位置误差（米）乘它变成力（牛）；越大越硬、越快。
    position_gain = 250.0
    # 速度阻尼：速度（米/秒）乘它变成阻尼力；抑制超调/振荡。
    velocity_damping = 35.0
    # 朝向增益：姿态误差（弧度）乘它变成力矩（牛·米）。
    orientation_gain = 1.5
    # 朝向阻尼：角速度乘它变成阻尼力矩。
    orientation_damping = 0.15
    # 目标点高度：0.02 = 地面（方块半高也是 0.02，放上去刚好贴地）。
    # 想挑战官方 5 cm 空中目标可以改大，但当前夹持力会打滑。
    target_height = 0.02
    # 开环偏置：补偿“方块落下时往 x/y 漂”的系统误差（实测值）。
    # 换模型/换初始位姿要重新标定。
    target_offset_x = 0.02
    target_offset_y = -0.01

    def __init__(self) -> None:
        # 下面这些是“运行时记忆”，不是配置；每次换模型/重置都会重新初始化。
        self._start_time = None             # 本回合开始的仿真时间（秒）
        self._last_time = -1.0         # 上一帧的 data.time，用来检测时间倒流（Reset）
        self._phase = "等待第一步"     # 当前阶段名（给界面看）
        self._phase_index = -1           # 当前阶段下标（0..7）
        self._phase_start = 0.0          # 本阶段开始时间（预留给按阶段计时用）
        self._initial_box = None              # 开局时方块中心位置（世界系，3 维）
        self._target = None             # 目标中心（target1/target2 的中点）
        self._aim = None             # 目标 + 偏置（实际要瞄的点）
        self._R0 = None               # 开局时手掌的姿态（要一直保持）
        self._sensor_ranges = {}               # 传感器名 -> (adr, adr+dim) 切片
        self._id = {}                 # site 名 -> MuJoCo id
        self._success = False            # 是否满足“box-target < 15 mm”
        self._final_box_target = float("nan")  # 最近一帧 box-target（米）
        self._final_box_height = float("nan")  # 最近一帧方块中心高度（米）
        self._last_action = np.zeros(7)  # 最近一次写出的 7 维 ctrl
        self._error = ""               # 异常信息（插件状态里显示）

    # ------------------------------------------------------------------
    def check_model_compatibility(self, model) -> str:
        """装配前的预检：返回 "" 表示能用，否则返回人话原因。

        ★ 这个函数在 data 建好之前调用，所以只能看 model，不能看 data。
        """
        # 动作必须是 7 维：6 个末端 wrench + 1 个夹爪。
        if int(getattr(model, "nu", 0)) != 7:
            return f"需要 7 维动作（6 力/力矩 + 夹爪），本模型 nu={getattr(model, 'nu', 0)}"

        # 传感器按名字查；缺一个后面的指标/外环就会失败。
        for name in REQUIRED_SENSORS:
            if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, name) < 0:
                return f'缺少传感器「{name}」'

        # site 按名字查；缺 eeff 没法施加 wrench，缺指垫没法对准。
        for name in REQUIRED_SITES:
            if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, name) < 0:
                return f'缺少站点「{name}」'

        return ""                     # 全部通过

    # ------------------------------------------------------------------
    def _initialize(self, model, data) -> None:
        """第一帧（或时间倒流）时调用：把“这一回合”的常量记下来。"""
        # site 名字 → id。MuJoCo 的高频 API 都用整数 id，不用字符串。
        self._id = {
            name: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, name)
            for name in REQUIRED_SITES
        }

        # 传感器名字 → 在 `data.sensordata` 里的切片 [起, 止)。
        # 为什么不直接 `data.sensor(名).data`？
        #   直接按名字查要遍历，500 Hz 下没必要；切片一次、之后只做数组索引。
        self._sensor_ranges = {
            name: (int(model.sensor_adr[mujoco.mj_name2id(
                model, mujoco.mjtObj.mjOBJ_SENSOR, name)]),
                 int(model.sensor_adr[mujoco.mj_name2id(
                     model, mujoco.mjtObj.mjOBJ_SENSOR, name)]
                     + model.sensor_dim[mujoco.mj_name2id(
                         model, mujoco.mjtObj.mjOBJ_SENSOR, name)]))
            for name in REQUIRED_SENSORS
        }

        # 目标点是一个 mocap body（可以理解成“手动拖动的虚拟目标”）。
        # 把它的 z 改到目标高度；改完必须 mj_forward，让 target1/target2
        # 这些 framepos 传感器立刻反映新位置。
        if data.mocap_pos.size:
            data.mocap_pos[0][2] = float(self.target_height)
            mujoco.mj_forward(model, data)

        # 记住方块的初始位置：后面“到方块上方 / 下探到方块”都相对它算。
        self._initial_box = np.array(data.sensor("box").data, dtype=float, copy=True)

        # 目标中心 = 目标两个侧点 target1/target2 的中点。
        self._target = 0.5 * (np.array(data.sensor("target1").data, dtype=float)
                            + np.array(data.sensor("target2").data, dtype=float))

        # 实际瞄准点 = 目标中心 + 开环偏置（补偿落下漂移）。
        self._aim = self._target + np.array(
            [self.target_offset_x, self.target_offset_y, 0.0], dtype=float)

        # 手掌初始姿态（3x3 旋转矩阵），后面一直保持它。
        # site_xmat 是 9 个数的扁平数组，reshape 成 3x3。
        self._R0 = data.site_xmat[self._id["eeff"]].reshape(3, 3).copy()

        # 记录本回合起点时间；阶段计时都以它为 0。
        self._start_time = float(data.time)
        self._phase_index = -1
        self._success = False
        self._error = ""

    # ------------------------------------------------------------------
    def _phases(self):
        """返回八段状态机的定义：[(时长秒, 名字, 指垫目标(世界系), 夹爪命令)]。

        注意：第 3、4 段（下探/闭合）的 z 都是方块中心；
        区别只在夹爪命令：下探时张开，闭合时才给 -0.1。
        """
        return [
            # 0.8 s：先张开，避免攥着闭合的夹爪去碰方块
            (0.8, "张开", self._initial_box + np.array([0, 0, 0.20]), OPEN),
            # 2.0 s：到方块上方 14 cm
            (2.0, "接近", self._initial_box + np.array([0, 0, 0.14]), OPEN),
            # 2.5 s：下探到方块中心；指垫会到方块两侧
            (2.5, "下探", self._initial_box + np.array([0, 0, 0.00]), OPEN),
            # 2.5 s：闭合夹爪；继续保持在方块中心，让手指夹紧
            (2.5, "闭合", self._initial_box + np.array([0, 0, 0.00]), CLOSE),
            # 2.5 s：抬起；夹爪用“保持 0”，不能继续 -0.1（会把方块挤出去）
            (2.5, "抬起", self._initial_box + np.array([0, 0, 0.25]), HOLD),
            # 3.0 s：搬到目标上方 20 cm；保持夹爪
            (3.0, "搬运", self._aim + np.array([0, 0, 0.20]), HOLD),
            # 8.0 s：对准；这一段会用方块实际位置做外环微调
            (8.0, "对准", self._aim, CLOSE),
            # 0.8 s：松开；方块落到地面目标上
            (0.8, "放下", self._aim, OPEN),
        ]

    def _get_phase(self, elapsed: float):
        """把“本回合经过的秒数”映射到第几段，返回 (序号, 名, 位置, 夹爪, 段内时间)。"""
        # 依次减掉每段时长；减不动的那一段就是当前段。
        for i, (duration, name, position, gripper) in enumerate(self._phases()):
            if elapsed < duration:
                return i, name, position, gripper, elapsed
            elapsed -= duration

        # 超时：停在最后一段（“放下”），返回段内时间=时长。
        i, (duration, name, position, gripper) = len(self._phases()) - 1, self._phases()[-1]
        return i, name, position, gripper, duration

    # ------------------------------------------------------------------
    @step_handler
    def step(self, event: plugin.messages.StepEvent) -> bool:
        """仿真每转一圈调用一次：读状态 → 算力/力矩 → 写 data.ctrl[:]。"""
        # event 由外壳构造，里面就是当前的 model/data；不要自己 new。
        model, data = event.model, event.data

        # 空场景/模型切换的瞬间可能没有关节或 ctrl 长度不对，直接跳过，
        # 否则下面的索引会越界，插件会被“出错隔离”停用。
        if data.qpos.size == 0 or data.ctrl.size != 7:
            return False
        try:
            # 第一帧，或时间倒流（Reset 后 data.time 回到 0）→ 重新初始化。
            if self._start_time is None or data.time + 1e-9 < self._last_time:
                self._initialize(model, data)
            self._last_time = float(data.time)   # 记住这一帧时间

            # 本回合经过了多久；用它查当前阶段。
            elapsed = float(data.time) - float(self._start_time)
            index, name, position, gripper, phase_elapsed = self._get_phase(elapsed)
            # 阶段切换时更新界面显示的名字。
            if index != self._phase_index:
                self._phase_index = index
                self._phase = name

            # 三个 site 的 id：eeff（受力点）、左右指垫（真正夹持点）。
            sid = self._id["eeff"]
            lid = self._id["touch_left"]
            rid = self._id["touch_right"]

            # p = 手掌参考点当前世界坐标（3 维）。
            p = np.array(data.site_xpos[sid], dtype=float, copy=True)
            # pad = 左右指垫的中点。真正要对准方块的是它，不是 p。
            pad = 0.5 * (np.array(data.site_xpos[lid], dtype=float)
                         + np.array(data.site_xpos[rid], dtype=float))

            # 这一段的指垫目标（世界系）。
            target = np.array(position, dtype=float, copy=True)

            if name == "对准":
                # 外环：夹住后“手 + 方块”近似刚体，所以可以用方块实际位置
                # 反推手应该往哪修：
                #   误差 = 瞄准点 - 方块当前位置
                #   指垫目标 = 当前指垫 + 0.08*误差（每步最多 0.2 mm）
                # 0.08 是比例增益；0.0002 m = 0.2 mm/步，限速防打滑。
                error = self._aim - np.array(data.sensor("box").data, dtype=float)
                target = pad + np.clip(0.08 * error, -0.0002, 0.0002)

            # 关键换算：控制器要控制 eeff，但用户给的是“指垫目标”。
            #   当前 eeff 和指垫的偏移 = pad - p；
            #   所以 eeff 目标 = 指垫目标 - (pad - p) = p + (目标 - pad)。
            target_position = p + (target - pad)

            # 取 eeff 的雅可比：jacp 把 qvel 映射成线速度，jacr 映射成角速度。
            # 形状都是 3 x nv；每次都要清零，mj_jacSite 是累加写入。
            jacp = np.zeros((3, model.nv))
            jacr = np.zeros((3, model.nv))
            mujoco.mj_jacSite(model, data, jacp, jacr, sid)

            # 当前末端线速度/角速度（世界系）。
            v = jacp @ data.qvel
            w = jacr @ data.qvel

            # 笛卡尔阻抗（PD）：
            #   力 = Kp * 位置误差 - Kd * 线速度
            #   力矩 = Kr * 姿态误差 - Kd_r * 角速度
            # 位置误差 (p目标 - p) 的单位是米；Kp=250 → 1 m 误差给 250 N（会饱和）。
            F = self.position_gain * (target_position - p) - self.velocity_damping * v
            T = self.orientation_gain * _rotation_error(
                self._R0, np.array(data.site_xmat[sid]).reshape(3, 3))\
                - self.orientation_damping * w

            # 执行器的 ctrl 范围是 [-1, 1]：
            #   前 3 个力执行器 gainprm=10 → ctrl=1 约 10 N，所以 F/10；
            #   后 3 个力矩执行器 gainprm=1 → ctrl=1 约 1 N·m，所以 T/2。
            # clip 防止超过执行器范围（MuJoCo 会截断，但显式写更清楚）。
            data.ctrl[:3] = np.clip(F / 10.0, -1.0, 1.0)
            data.ctrl[3:6] = np.clip(T / 2.0, -1.0, 1.0)

            # 第 7 维是夹爪：+0.1 开、-0.1 闭、0 保持。
            data.ctrl[6] = float(gripper)
            # 记下这一帧的动作，指标/调试用。
            self._last_action = np.array(data.ctrl, dtype=float, copy=True)

            # 指标：方块两侧到目标两侧的平均距离（米）。
            #   box1-target1 和 box2-target2 各是一个 3 维向量；
            #   取两个范数的平均，就是官方任务里的 “bring distance”。
            bt = (np.linalg.norm(np.array(data.sensor("box1").data)
                                 - np.array(data.sensor("target1").data))
                  + np.linalg.norm(np.array(data.sensor("box2").data)
                                   - np.array(data.sensor("target2").data))) / 2.0
            self._final_box_target = float(bt)
            self._final_box_height = float(data.sensor("box").data[2])

            # 只在整个 22 秒跑完、且 bring distance < 15 mm 时标记成功。
            # 15 mm 是官方 panda.cc 的 TransitionLocked 阈值。
            if elapsed >= sum(x[0] for x in self._phases()) - 0.05 and bt < 0.015:
                self._success = True
        except Exception as exc:                                       # noqa: BLE001
            # 控制回路里的异常不能把仿真线程带崩；记下来给界面看。
            self._error = f'{type(exc).__name__}: {exc}'
        return False      # 返回 False = 不拦截，让别的插件也能看到这一步

    # ------------------------------------------------------------------
    def adjustable_parameters(self) -> dict:
        """声明界面滑杆：键必须是本类的属性名，范围用于基类校验。"""
        return {
            "position_gain": {"value": self.position_gain, "range": (10.0, 2000.0), "label": "位置增益"},
            "velocity_damping": {"value": self.velocity_damping, "range": (0.0, 300.0), "label": "速度阻尼"},
            "orientation_gain": {"value": self.orientation_gain, "range": (0.0, 20.0), "label": "朝向增益"},
            "orientation_damping": {"value": self.orientation_damping, "range": (0.0, 5.0), "label": "朝向阻尼"},
            "target_height": {"value": self.target_height, "range": (0.0, 0.10), "unit": "m", "label": "目标高度"},
            "target_offset_x": {"value": self.target_offset_x, "range": (-0.10, 0.10), "unit": "m", "label": "目标偏置X"},
            "target_offset_y": {"value": self.target_offset_y, "range": (-0.10, 0.10), "unit": "m", "label": "目标偏置Y"},
        }

    def metrics(self) -> dict:
        """给「验证」页画曲线的数；返回的键会自动加插件名前缀。"""
        return {
            # box-target：越小越好；<15 mm 算搬运成功。
            "box-target(mm)": float(self._final_box_target * 1000.0)
            if np.isfinite(self._final_box_target) else 0.0,
            # box-z：抬升高度；地面目标时约 20 mm。
            "box-z(mm)": float(self._final_box_height * 1000.0)
            if np.isfinite(self._final_box_height) else 0.0,
            # 成功标志：0/1，方便画成台阶。
            "成功": 1.0 if self._success else 0.0,
            # 6 维 wrench 的模长（不含夹爪）。
            "动作范数": float(np.linalg.norm(self._last_action[:6])),
            # 夹爪命令：+0.1 开、-0.1 闭、0 保持。
            "夹爪": float(self._last_action[6]),
        }

    def status(self) -> dict:
        """终端每 2 秒打印的一行摘要。"""
        if self._error:
            return {"状态": f'失败：{self._error}'}
        return {
            "阶段": self._phase,
            "box-target": f'{self._final_box_target * 1000:.1f} mm'
            if np.isfinite(self._final_box_target) else "—",
            "成功": "是" if self._success else "否",
        }
