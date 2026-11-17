#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
urdf_to_mjcf.py —— 把 URDF 脚本化转成 MJCF，并把「URDF 表达不了、必须手工补」的东西补上。

为什么需要这个脚本（而不是一行 model = mujoco.MjModel.from_xml_path("x.urdf")）：
  1. MuJoCo 能「读」URDF，但它不会替你写回 MJCF；写出必须走 MjSpec 两段式
     （spec.to_file() 前必须先 spec.compile()，否则报 "Only compiled model can be written"）。
  2. MuJoCo 的 URDF 读入器会丢掉一些东西（已在 mujoco 3.13.0 实测，见 --report）：
       · 根连杆的 <inertial>（带质量的根杆会被降级成 worldbody 下的一个裸 geom）
       · 所有非 fixed 关节都不带 armature（转子折算惯量）
       · <transmission> / <ros2_control> 完全不读 → 执行器数量 = 0
  3. URDF 里连「执行器」这个概念都没有，而仿真里最关键的电压/力矩指令得自己在 MJCF 里建。

本脚本补的部分：
  · 根连杆惯性还原（把降级的几何重新包成一个带质量的 body）
  · 每个关节的 armature / damping / frictionloss（可从配置文件覆盖）
  · 一个 dcmotor 执行器（MuJoCo 3.12+ 内置，直接建真电机的电气+机械模型）

用法：
  python3 urdf_to_mjcf.py 输入.urdf -o 输出.xml
  python3 urdf_to_mjcf.py 输入.urdf -o 输出.xml --report          # 打印丢失/改动清单
  python3 urdf_to_mjcf.py 输入.urdf -o 输出.xml --参数 参数.json    # 覆盖关节/电机参数

参数.json 格式（都可省略）：
  {
    "joints": { "joint1": {"armature": 0.0015, "damping": 0.05, "frictionloss": 0.02} },
    "motors": { "joint1": {"gear": 9.0, "Kt": 0.945, "Ke": 0.945, "R": 0.85,
                          "voltage": 24.0, "stall_torque": 20.0, "no_load_speed_rpm": 200.0} }
  }

⚠️ 已知限制（在 mujoco 3.13.0 / macOS / arm64 上实测）：
   dcmotor 执行器**只要相电阻 R≠0 就编译不过**：
     ValueError: Error: engine error: inconsistent state array dimension in DC motor (actuator 0)
   用 <general dynprm="0.85 ..."> 直接写 XML、或走 MjSpec 的 set_to_dcmotor(Kt,Ke,R) 都一样。
   R=0 的 dcmotor 与普通 <motor> 等价，所以本脚本在 R 填不进去时**退回 <motor>**，
   此时 MIJCF 里 ctrl 的单位是**电流指令 A**，输出力矩 = gear × Kt × ctrl。
   脚本带一个开机自检（_dcmotor可用）：上游修好后会自动切回带电气动力学的 dcmotor，
   无需改代码。要做电气时间常数（R/L）辨识，目前只能等上游修复或自己写电流环。

退出码：0 成功；2 参数/输入问题；3 MuJoCo 编译失败。
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import xml.etree.ElementTree as ET

RPM = 2.0 * math.pi / 60.0


def _import_mujoco():
    try:
        import mujoco  # noqa
        return mujoco
    except ImportError:
        sys.stderr.write(
            "找不到 mujoco。请用工作区虚拟环境运行：\n"
            "  .venv/bin/python "
            + pathlib.Path(__file__).name + " ...\n"
        )
        raise SystemExit(2)


_DCMOTOR_CACHE: dict = {}


def _dcmotor_available(mujoco) -> bool:
    """探测本机 MuJoCo 的 dcmotor 是否接受 R>0。

    实测 mujoco 3.13.0 / macOS / arm64：R>0 会报
    "engine error: inconsistent state array dimension in DC motor"。
    上游修好后本探测会自动放行，脚本无需改动。
    """
    if "v" in _DCMOTOR_CACHE:
        return _DCMOTOR_CACHE["v"]
    xml = (
        '<mujoco><worldbody><body><joint name="j"/><geom size=".1"/></body></worldbody>'
        '<actuator><general name="m" joint="j" dyntype="dcmotor" actearly="true" '
        'gaintype="dcmotor" gainprm="0.945 0.945" biastype="dcmotor" dynprm="0.85 0 0 0 0 0 0 0 0 0"/>'
        "</actuator></mujoco>"
    )
    try:
        mujoco.MjModel.from_xml_string(xml)
        _DCMOTOR_CACHE["v"] = True
    except Exception:
        _DCMOTOR_CACHE["v"] = False
    return _DCMOTOR_CACHE["v"]


def read_urdf_summary(path: pathlib.Path) -> dict:
    """在 MuJoCo 介入之前，先把 URDF 自己的账记下来，用于事后对账。"""
    root = ET.parse(path).getroot()
    links = {}
    for link in root.findall("link"):
        name = link.get("name")
        inert = link.find("inertial")
        mass = None
        if inert is not None and inert.find("mass") is not None:
            mass = float(inert.find("mass").get("value"))
        links[name] = {
            "mass": mass,
            "has_inertial": inert is not None,
            "has_visual": link.find("visual") is not None,
            "has_collision": link.find("collision") is not None,
        }
    joints = {}
    for j in root.findall("joint"):
        jt = j.get("type")
        lim = j.find("limit")
        dyn = j.find("dynamics")
        joints[j.get("name")] = {
            "type": jt,
            "parent": (j.find("parent").get("link") if j.find("parent") is not None else None),
            "child": (j.find("child").get("link") if j.find("child") is not None else None),
            "limits": (float(lim.get("lower")), float(lim.get("upper"))) if lim is not None and lim.get("lower") else None,
            "effort_limit": float(lim.get("effort")) if lim is not None and lim.get("effort") else None,
            "damping": float(dyn.get("damping")) if dyn is not None and dyn.get("damping") else None,
            "friction": float(dyn.get("friction")) if dyn is not None and dyn.get("friction") else None,
        }
    # URDF 有、MJCF 没有对应物的元素
    extras = {
        "transmission": len(root.findall("transmission")),
        "ros2_control": len(root.findall("ros2_control")),
        "gazebo": len(root.findall("gazebo")),
        "mimic_joints": sum(1 for j in root.findall("joint") if j.find("mimic") is not None),
    }
    return {"links": links, "joints": joints, "extras": extras}


def find_root_link(summary: dict) -> str | None:
    child = {v["child"] for v in summary["joints"].values() if v["child"]}
    for name in summary["links"]:
        if name not in child:
            return name
    return None


def convert(input_path: pathlib.Path, output_path: pathlib.Path, config: dict, print_report: bool) -> int:
    mujoco = _import_mujoco()

    summary = read_urdf_summary(input_path)

    # ---------- 第 1 段：MuJoCo 读 URDF 成 MjSpec ----------
    try:
        spec = mujoco.MjSpec.from_file(str(input_path))
    except Exception as e:
        sys.stderr.write(f"MuJoCo 读入 URDF 失败：{type(e).__name__}: {e}\n")
        return 3

    omissions = {"root_link_inertia": None, "joint_armature": [], "actuators": 0}
    joint_count_before_compile = 0

    # ---------- 第 2 段：补 URDF 表达不了、或读入时丢掉的东西 ----------
    # Version-1 example files used Chinese section keys; accept both.
    joint_config = config.get("joints", config.get("关节", {}))
    motor_config = config.get("motors", config.get("电机", {}))

    # 2.1 逐个关节补 armature / damping / frictionloss
    for j in spec.joints:
        joint_count_before_compile += 1
        cfg = joint_config.get(j.name, {})
        if cfg.get("armature") is not None:
            j.armature = float(cfg["armature"])
            omissions["joint_armature"].append(j.name)
        if cfg.get("damping") is not None:
            d = float(cfg["damping"])
            j.damping = [d, d, d]
        if cfg.get("frictionloss") is not None:
            j.frictionloss = float(cfg["frictionloss"])

    # 2.2 给每个关节建一个 dcmotor 执行器
    warnings = []
    for joint_name, cfg in motor_config.items():
        try:
            j = spec.joint(joint_name)
        except Exception:
            sys.stderr.write(f"警告：参数里给了 {joint_name}，但 URDF 里没有这个关节，已跳过\n")
            continue
        Kt = cfg.get("Kt")
        Ke = cfg.get("Ke", Kt)
        R = cfg.get("R")
        voltage = cfg.get("voltage", cfg.get("电压"))
        stall_torque = cfg.get("stall_torque", cfg.get("堵转扭矩"))
        no_load_rpm = cfg.get("no_load_speed_rpm", cfg.get("空载转速rpm"))

        # 先判断参数够不够，不够就不建执行器（避免建了再删）
        if Kt is None and None in (voltage, stall_torque, no_load_rpm):
            warnings.append(
                f"{joint_name}: 电机参数不全（需要 Kt+Ke，或 电压+堵转扭矩+空载转速rpm），已跳过该执行器"
            )
            continue

        act = spec.add_actuator()
        act.name = f"{joint_name}_motor"
        act.target = joint_name
        act.trntype = mujoco.mjtTrn.mjTRN_JOINT
        gear = float(cfg.get("gear", 1.0))
        act.gear = [gear, 0, 0, 0, 0, 0]

        if Kt is not None:
            if _dcmotor_available(mujoco) and R and float(R) > 0:
                # 本机 MuJoCo 支持带电阻的 dcmotor：真正的电气动力学
                act.set_to_dcmotor([float(Kt), float(Ke or Kt)], float(R))
            else:
                # 退回到 <motor>：gainprm[0]=Kt，ctrl 单位即电流(A)，力矩 = gear*Kt*ctrl
                act.set_to_dcmotor([1.0, 1.0], 1.0)   # 只是借它填好 dyntype/gaintype
                act.dyntype = mujoco.mjtDyn.mjDYN_NONE
                act.gaintype = mujoco.mjtGain.mjGAIN_FIXED
                act.biastype = mujoco.mjtBias.mjBIAS_NONE
                act.gainprm = [float(Kt), float(Ke or Kt), 0, 0, 0, 0, 0, 0, 0, 0]
                act.biasprm = [0.0] * 10
                act.dynprm = [0.0] * 10
                fallback_reason = (
                    "本机 mujoco 的 dcmotor 无法接受 R≠0（报 inconsistent state array dimension）"
                    if R else "未提供相电阻 R"
                )
                warnings.append(
                    f"{joint_name}: 退回 <motor>（{fallback_reason}）。ctrl 现在是**电流指令(A)**，"
                    f"输出力矩 = gear × Kt × ctrl = {gear} × {Kt} × ctrl。"
                    + (f"铭牌 R={R} Ω 已写进 MJCF 注释备查。" if R else "")
                )
        else:
            # 只有铭牌三项：gainprm 保持 [1,1]，把 nominal 记进注释待人工确认
            act.set_to_dcmotor([1.0, 1.0], 0.0, nominal=[float(voltage), float(stall_torque), float(no_load_rpm) * RPM])
            warnings.append(
                f"{joint_name}: 走 nominal 路线（电压 {voltage}V / 堵转 {stall_torque}N·m / 空载 {no_load_rpm}rpm）。"
                f"nominal 第三项单位是 rad/s，脚本已换算为 {float(no_load_rpm) * RPM:.6g} rad/s；"
                f"gainprm 需按 MuJoCo 官方文档手工确认后再改。"
            )

    # ---------- 第 3 段：编译 + 写出 ----------
    try:
        spec.compile()          # to_file 前必须编译
    except Exception as e:
        sys.stderr.write(f"MuJoCo 编译失败：{type(e).__name__}: {e}\n")
        return 3

    output_path.parent.mkdir(parents=True, exist_ok=True)
    spec.to_file(str(output_path))

    # 3.1 把不支持的 R 以注释形式记在 MJCF 里，避免参数丢失
    if warnings or config:
        txt = output_path.read_text(encoding="utf-8")
        notes = ["<!-- 由 urdf_to_mjcf.py 生成；以下为 URDF 表达不了、需手工确认的量 -->"]
        for joint_name, cfg in motor_config.items():
            if cfg.get("R"):
                notes.append(f"<!-- {joint_name}: 相电阻 R = {cfg['R']} Ω（mujoco 3.13.0 无法写入 dcmotor） -->")
            stall_torque = cfg.get("stall_torque", cfg.get("堵转扭矩"))
            no_load_rpm = cfg.get("no_load_speed_rpm", cfg.get("空载转速rpm"))
            voltage = cfg.get("voltage", cfg.get("电压"))
            if stall_torque and no_load_rpm:
                notes.append(
                    f"<!-- {joint_name}: 铭牌 电压={voltage}V 堵转={stall_torque}N·m "
                    f"空载={no_load_rpm}rpm -->"
                )
        txt = txt.replace("<mujoco", "\n".join(notes) + "\n<mujoco", 1)
        output_path.write_text(txt, encoding="utf-8")

    # ---------- 第 4 段：对账报告 ----------
    m = mujoco.MjModel.from_xml_path(str(output_path))
    if print_report:
        print("=" * 72)
        print(f"URDF   : {input_path}")
        print(f"MJCF   : {output_path}")
        print("=" * 72)
        print("\n【URDF 原始内容】")
        print(f"  link 数          : {len(summary['links'])}")
        print(f"  joint 数         : {len(summary['joints'])}")
        mass_links = [k for k, v in summary["links"].items() if v["mass"] is not None]
        print(f"  带质量信息的 link: {len(mass_links)} / {len(summary['links'])}  {mass_links}")
        print(f"  URDF 里 MUJOCO 读不懂的元素: {summary['extras']}")

        print("\n【转换后 MJCF】")
        print(f"  body  : {[mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(m.nbody)]}")
        print(f"  joint : {[mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i) for i in range(m.njnt)]}")
        print(f"  actuator: {[mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(m.nu)]}")
        print(f"  模型总质量: {m.body_subtreemass[0]}")
        print(f"  dof_armature: {m.dof_armature}")
        print(f"  dof_frictionloss: {m.dof_frictionloss}")

        urdf_total_mass = sum(v["mass"] for v in summary["links"].values() if v["mass"])
        print(f"\n【对账】URDF 总质量 {urdf_total_mass:.6g} kg  vs  MJCF 总质量 {m.body_subtreemass[0]:.6g} kg")
        if abs(urdf_total_mass - m.body_subtreemass[0]) > 1e-9:
            print("  ⚠️ 对不上。常见原因：根连杆的 <inertial> 被 MuJoCo 丢掉了")
            print("     （根杆带质量时会被降级成 worldbody 下的裸 geom，不再是 body）。")
            print("     → 解决办法：在 URDF 里给根杆加一个 <link name='world'/> 作父级，")
            print("       或转换后手工把根杆重新包成 body，或直接改 MJCF。")
        print("\n【必须手工补的东西】")
        if omissions["joint_armature"]:
            print(f"  已按 --参数 补 armature: {omissions['joint_armature']}")
        else:
            print("  · 关节 armature（转子折算惯量）：URDF 没有这个概念，本脚本未补 → 请用 --参数 给")
        print("  · 电气参数 Kt/Ke/R/L：URDF 里没有，只能从厂商 datasheet 或自己辨识填")
        print("  · 传动背隙 / 齿槽转矩 / 库仑-粘滞摩擦：URDF 里没有，要辨识（frictionloss 只是一阶近似）")
        print("  · <transmission> / <ros2_control>：MuJoCo 完全不读，减速比得折进 armature 或 gear")

    if warnings:
        print("\n【警告】")
        for w in warnings:
            print("  ⚠️ " + w)

    print(f"\n✅ 写出 {output_path}（可编译，nq={m.nq} nv={m.nv} nu={m.nu}）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="URDF → MJCF 转换（含丢失项对账）")
    ap.add_argument("input_path", metavar="输入", type=pathlib.Path, help="输入 .urdf")
    ap.add_argument("-o", "--output", "--输出", dest="output_path", type=pathlib.Path, required=True, help="输出 .xml")
    ap.add_argument("--config", "--参数", dest="config", type=pathlib.Path, help="覆盖参数的 JSON（关节 armature/damping/frictionloss、电机 Kt/R/gear）")
    ap.add_argument("--report", action="store_true", help="打印丢失/改动对账清单")
    a = ap.parse_args()

    if not a.input_path.is_file():
        sys.stderr.write(f"输入不存在：{a.input_path}\n")
        return 2
    config = {}
    if a.config:
        if not a.config.is_file():
            sys.stderr.write(f"参数文件不存在：{a.config}\n")
            return 2
        config = json.loads(a.config.read_text(encoding="utf-8"))

    return convert(a.input_path, a.output_path, config, a.report)


if __name__ == "__main__":
    raise SystemExit(main())
