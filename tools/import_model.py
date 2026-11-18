"""
import_model.py —— 从 MuJoCo Menagerie 导入机器人模型，并自动生成"扭矩接口变体"

★ 为什么需要"扭矩接口变体"（这是本项目的一个硬约束）：
    驭臂的控制插件往 `event.data.ctrl[:]` 里写的是**关节力矩**（N·m）。
    但 menagerie 的模型默认用的是**位置伺服**：
        <general gainprm="2000" biasprm="0 -2000 -400"/>   →   τ = kp·(ctrl − q) − kd·q̇
    这种模型的 ctrl 是"目标关节角"，不是力矩。直接拿它跑我们的 PD 插件，
    控制量会被当成"目标角度"，机械臂行为完全不对。
    所以每个导入的模型都会额外生成一个 `<模型>_torque.xml`：把执行器换成
        <motor ctrlrange="-上限 上限"/>                        →   τ = ctrl（力矩接口）
    本项目默认的 `ur5e_torque.xml` 就是这么来的。

★ 另一条硬约束：`nu` 必须等于 `nv`
    `关节pd控制.py` 的算法是 `数据.ctrl[:] = KP*误差 - KD*数据.qvel + 数据.qfrc_bias`，
    `qvel`/`qfrc_bias` 的长度是 nv，所以 ctrl 的长度必须是 nv。
    但有些模型带夹爪（Panda 的 `panda.xml` 是 nq=9/nu=8；xArm7 带 gripper），
    长度对不上，插件会直接抛广播错误。
    解决办法：**优先用 menagerie 自带的 `<模型>_nohand.xml`**，并且扭矩变体
    **只为"关节类执行器"生成 motor**（丢掉 tendon/夹爪执行器），保证 nu == nv == 自由度。

用法：
    # 列出可导入的机械臂（24 个，全部是 MIT / BSD-3 / Apache-2.0 许可）
    .venv/bin/python tools/import_model.py --列表

    # 导入指定的几个
    .venv/bin/python tools/import_model.py franka_emika_panda universal_robots_ur10e

    # 导入清单里全部 24 个机械臂（约 40 MB 下载 / 250 MB 解包）
    .venv/bin/python tools/import_model.py --全部

    # 已经下过、想重新生成扭矩变体
    .venv/bin/python tools/import_model.py franka_emika_panda --只生成扭矩

    # 换下载通道（默认走 gh-proxy 代理，因为国内直连 GitHub 常常不通）
    .venv/bin/python tools/import_model.py ... --直连
    .venv/bin/python tools/import_model.py ... --代理 https://gh-proxy.com/

网络：GitHub 直连不通时用 `--代理`（默认 https://gh-proxy.com/ ）。不需要 pip 装任何东西。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
MODEL_DIR = os.path.join(PACKAGE_ROOT, "模型")
MANIFEST_PATH = os.path.join(SCRIPT_DIR, "model_manifest.json")
LEGACY_MANIFEST_PATH = os.path.join(SCRIPT_DIR, "模型清单.json")
LIBRARY_INDEX_PATH = os.path.join(MODEL_DIR, "模型库.json")

# ---------------------------------------------------------------------------
# 模型自身没给 forcerange 时，用这里的实测/手册扭矩上限（N·m）兜底
#   来源：厂家公开的关节峰值扭矩指标（只用于把位置伺服换成力矩接口时限幅，不影响动力学）
#   ★ 单位是 N·m，顺序与模型里的关节顺序一致
# ---------------------------------------------------------------------------
TORQUE_LIMIT_OVERRIDES: dict[str, list[float]] = {
    # KUKA LBR iiwa 14 R820：A1/A2 320、A3/A4 176、A5 110、A6/A7 40
    "kuka_iiwa_14": [320.0, 320.0, 176.0, 176.0, 110.0, 40.0, 40.0],
}

# ---------------------------------------------------------------------------
# 关节"电枢惯量"（armature）兜底值
#
# ★ 为什么必须补（实测踩过）：
#   KUKA iiwa14 的 menagerie 模型里 `<joint>` 既没有 armature 也没有 damping
#   （UR5e / Panda 都有 armature="0.1"）。原模型能稳，是因为它用**位置伺服**
#   （biasprm 给了 kd=200）——那个阻尼把"腕部关节惯量几乎为 0"这件事盖住了。
#   一旦换成力矩电机、用我们默认的 KP=200/KD=30、步长 0.002 s，腕关节就变成
#   数值发散（实测末误差 130°，机械臂乱甩）。
#   补上 armature=0.1（等效于减速器/转子折算到关节侧的惯量，真机本来就有，
#   menagerie 自己的 UR5e/Panda 也这么写）之后：实测末误差 0.0000°。
#
#   注意：只在**原值为 0 且该关节被我们驱动**时才补，不动其它关节。
# ---------------------------------------------------------------------------
DEFAULT_ARMATURE = 0.1

# Version-1 manifests used Chinese machine keys. New files use English keys; the
# reader accepts both so an existing checkout or a user's copy keeps working.
MANIFEST_TOP_KEYS = {
    "source": "来源", "asset_base_url": "资产基地址", "proxy_prefix": "代理前缀",
    "description": "说明", "models": "模型",
}
MANIFEST_MODEL_KEYS = {
    "display_name": "显示名", "category": "类别", "license": "许可",
    "asset": "资产", "download_bytes": "下载字节", "unpacked_bytes": "解包字节",
    "default_model": "默认模型", "scene": "场景", "entrypoints": "入口",
    "torque_limit": "扭矩上限", "description": "说明",
}


def _rename_keys(mapping: dict, aliases: dict[str, str]) -> dict:
    result = {}
    for key, value in mapping.items():
        result[str(key)] = value
    for english, legacy in aliases.items():
        if english not in result and legacy in result:
            result[english] = result[legacy]
    for legacy in aliases.values():
        if legacy in result and legacy not in aliases:
            result.pop(legacy, None)
    return result


def normalize_manifest(data: dict) -> dict:
    """Return the manifest with English machine keys (legacy keys still accepted)."""
    result = _rename_keys(data, MANIFEST_TOP_KEYS)
    models = result.get("models")
    if isinstance(models, dict):
        result["models"] = {
            str(name): _rename_keys(info, MANIFEST_MODEL_KEYS) if isinstance(info, dict) else info
            for name, info in models.items()
        }
    return result


def read_manifest() -> dict:
    path = MANIFEST_PATH if os.path.exists(MANIFEST_PATH) else LEGACY_MANIFEST_PATH
    if not os.path.exists(path):
        raise SystemExit(
            f"✗ 找不到模型清单：{MANIFEST_PATH}\n"
            f"  这个文件记录了 menagerie 各模型的下载地址与 sha256，是导入工具的依据。")
    with open(path, encoding="utf-8") as f:
        return normalize_manifest(json.load(f))


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------
def download(url: str, target: str, proxy_prefix: str = "") -> None:
    """下载到目标路径（带进度百分比）。代理前缀用于 gh-proxy 这类反代。"""
    full_url = (proxy_prefix + url) if proxy_prefix else url
    print(f"  ↓ {full_url}")
    request = urllib.request.Request(full_url, headers={"User-Agent": "yubi-import/1.0"})
    last_progress = -1
    with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as output:
        total_bytes = int(response.headers.get("Content-Length") or 0)
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            output.write(chunk)
            if total_bytes:
                percentage = int(output.tell() * 100 / total_bytes)
                if percentage // 10 != last_progress // 10:
                    last_progress = percentage
                    print(f"      {percentage:3d}%  ({output.tell()/1e6:.1f}/{total_bytes/1e6:.1f} MB)", flush=True)


def verify_checksum(path: str, expected: str) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()


# ---------------------------------------------------------------------------
# 生成扭矩变体
# ---------------------------------------------------------------------------
def _select_base_xml(model_id: str, directory: str, info: dict) -> str:
    """挑扭矩变体的基础 XML。

    优先 `*_nohand.xml`：它去掉了夹爪，能让 nu == nv == 自由度，
    正好符合我们控制插件"ctrl 长度 = qvel 长度"的假设。
    """
    default_model = info["default_model"]
    candidate = []
    if f"{default_model}_nohand" in info.get("entrypoints", []):
        candidate.append(f"{default_model}_nohand.xml")
    candidate += [f"{default_model}.xml"]
    for c in candidate:
        p = os.path.join(directory, c)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"{directory} 里找不到 {default_model}.xml")


def generate_torque_variant(model_id: str, directory: str, info: dict, torque_limit: list[float] | None,
                 log=print) -> tuple[str, dict]:
    """把位置伺服换成力矩电机，输出 `<模型>_torque.xml`。返回 (路径, 统计信息)。"""
    import mujoco

    base_xml = _select_base_xml(model_id, directory, info)
    model = mujoco.MjModel.from_xml_path(base_xml)

    # ---- 解析出每个执行器的"传动对象"和"扭矩上限"（forcerange 已经把 class 继承算好了）----
    actuators = []
    for i in range(model.nu):
        actuator_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, i) or f"act{i}"
        transmission_type = model.actuator_trntype[i]
        target_id = int(model.actuator_trnid[i, 0])
        if transmission_type == mujoco.mjtTrn.mjTRN_JOINT:
            joint_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, target_id)
            limit = [float(x) for x in model.actuator_forcerange[i]]
            actuators.append({"name": actuator_name, "joint": joint_name, "limit": limit, "is_joint": True})
        else:
            actuators.append({"name": actuator_name, "joint": None, "limit": None, "is_joint": False})

    joint_actuators = [e for e in actuators if e["is_joint"]]
    discarded_actuators = [e["name"] for e in actuators if not e["is_joint"]]

    # ---- 决定每个关节执行器的扭矩上限 ----
    torque_limits = []
    for e in joint_actuators:
        lo, hi = e["limit"]
        if abs(lo) < 1e-9 and abs(hi) < 1e-9:          # 模型没给 → 用补充表 / 命令行
            if torque_limit:
                value = float(torque_limit[len(torque_limits)])
                lo, hi = -abs(value), abs(value)
            else:
                raise SystemExit(
                    f"✗ {model_id} 的执行器「{e['name']}」没有 forcerange（扭矩无限），"
                    f"无法自动生成扭矩变体。\n"
                    f"  请在 tools/import_model.py 的 扭矩上限补充表 里为 {model_id} 补一组关节扭矩上限，"
                    f"或用 --扭矩上限 320,320,176,176,110,40,40 指定。")
        torque_limits.append(max(abs(lo), abs(hi)))

    # ---- 找出"电枢惯量为 0 且被我们驱动"的关节，准备补上默认值 ----
    armature_joints = []
    for e in joint_actuators:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, e["joint"])
        if joint_id < 0:
            continue
        dof_index = int(model.jnt_dofadr[joint_id])
        if dof_index >= 0 and float(model.dof_armature[dof_index]) < 1e-9:
            armature_joints.append(e["joint"])

    # ---- XML 手术：换掉 <actuator>，修好 <keyframe> ----
    #   insert_comments=True 保留原文件的注释（menagerie 的 XML 注释很有价值）
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(base_xml, parser=parser)
    root = tree.getroot()

    actuator_node = root.find("actuator")
    if actuator_node is None:
        raise SystemExit(f"✗ {base_xml} 里没有 <actuator> 段")
    for child in list(actuator_node):
        actuator_node.remove(child)

    for e, limit in zip(joint_actuators, torque_limits):
        motor = ET.SubElement(actuator_node, "motor")
        motor.set("name", str(e["name"]))
        motor.set("joint", str(e["joint"]))
        motor.set("gear", "1")
        # ctrlrange = 扭矩上限：MuJoCo 会把 ctrl 夹到这个范围内，等价于力矩限幅
        motor.set("ctrlrange", f"{-limit:g} {limit:g}")

    # 补电枢惯量（见上面 默认电枢惯量 的说明：不补的话某些模型力矩模式下会发散）
    if armature_joints:
        required_joints = set(armature_joints)
        for joint_node in root.iter("joint"):
            if joint_node.get("name") in required_joints:
                joint_node.set("armature", f"{DEFAULT_ARMATURE:g}")

    # keyframe 的 ctrl 长度变了，必须重写（否则加载时报尺寸不符）
    new_nu = len(joint_actuators)
    keyframes = root.find("keyframe")
    if keyframes is not None:
        for frame in keyframes.findall("key"):
            if frame.get("ctrl") is not None:
                frame.set("ctrl", " ".join(["0"] * new_nu))

    ET.indent(tree, space="  ")                            # 让输出可读
    output_path = os.path.join(directory, f"{info['default_model']}_torque.xml")
    try:
        source_path = os.path.relpath(base_xml, PACKAGE_ROOT)
    except ValueError:
        # Windows cannot express a relative path between different drives.
        source_path = os.path.abspath(base_xml)
    header = (
        f"<!-- ============================================================================\n"
        f"     {os.path.basename(output_path)} —— {info['display_name']} 的**力矩接口**变体\n"
        f"     由 tools/import_model.py 自动生成，**请勿手工编辑**（重新导入会覆盖）。\n"
        f"     来源模型 : {source_path}\n"
        f"     改了什么 : ① 执行器（位置伺服）→ <motor> 力矩电机（ctrl 就是关节力矩 N·m）\n"
        f"                ② 丢掉非关节执行器（{'、'.join(discarded_actuators) if discarded_actuators else '无'}）→ 保证 nu == nv\n"
        f"                ③ keyframe 的 ctrl 重写为 {new_nu} 个 0\n"
        f"                ④ 补电枢惯量 armature={DEFAULT_ARMATURE:g}："
        f"{'、'.join(armature_joints) if armature_joints else '（本模型已自带，无需补）'}\n"
        f"     扭矩上限 : {', '.join(f'{x:g}' for x in torque_limits)} N·m\n"
        f"     为什么   : 驭臂的控制插件往 data.ctrl[:] 写的是力矩，位置伺服模型会把力矩\n"
        f"                当成目标角度，行为完全不对。④ 是因为位置伺服的 kd 掩盖了\n"
        f"                \"关节电枢惯量为 0\"，换成力矩接口后会数值发散。\n"
        f"     详见     : tools/import_model.py 顶部说明\n"
        f"     ============================================================================ -->\n"
    )
    tree_xml = ET.tostring(root, encoding="unicode")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(header)
        f.write(tree_xml + "\n")

    statistics = {
        "base_xml": source_path,
        "torque_objects": len(joint_actuators),
        "discarded_actuators": discarded_actuators,
        "torque_limits": torque_limits,
        "armature_joints": armature_joints,
    }
    return output_path, statistics


# ---------------------------------------------------------------------------
# 验证：扭矩变体能不能被我们的控制律控制住
# ---------------------------------------------------------------------------
def validate_torque_variant(path: str, steps: int = 1500) -> dict:
    """用与 `关节pd控制.py` 完全相同的 PD 算式跑一段无窗口仿真，看是否收敛。"""
    import mujoco
    import numpy as np

    model = mujoco.MjModel.from_xml_path(path)
    data = mujoco.MjData(model)
    home_key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "home")
    if home_key >= 0:
        mujoco.mj_resetDataKeyframe(model, data, home_key)
    mujoco.mj_forward(model, data)

    if not (model.nu == model.nv == model.nq):
        return {"passed": False, "reason": f"nu={model.nu} nv={model.nv} nq={model.nq}（需要三者相等）"}

    target = data.qpos.copy()
    target[1] += 0.35                      # 和默认插件一样：抬一下肩
    KP, KD = 200.0, 30.0
    max_error = 0.0
    for _ in range(steps):
        error = target - data.qpos
        data.ctrl[:] = KP * error - KD * data.qvel + data.qfrc_bias
        mujoco.mj_step(model, data)
        max_error = max(max_error, float(np.abs(error).max()))
    final_error = float(np.abs(target - data.qpos).max())
    # 判定"收敛"：末误差 < 0.5°。
    #   为什么不是更严：模型里若带关节阻尼/摩擦，纯 PD（无积分项）本来就会有微小静差。
    #   实测参考：Panda 0.0000°、UR10e 0.0100°、xArm7 0.139°（都在正常范围）；
    #             发散的话会是几十到上百度的量级，一眼可分。
    return {
        "passed": bool(np.isfinite(final_error) and final_error < np.radians(0.5)),
        "final_error_deg": float(np.degrees(final_error)),
        "max_error_deg": float(np.degrees(max_error)),
    }


# ---------------------------------------------------------------------------
# 模型库索引（界面选模型时会读它）
# ---------------------------------------------------------------------------
def _detect_license(directory: str) -> str:
    """读模型目录里的 LICENSE 文件，判断许可类型（清单里有准确值时优先用清单）。"""
    for name in ("LICENSE", "license", "LICENCE"):
        p = os.path.join(directory, name)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            license_text = f.read()
        if "Apache License" in license_text or "apache.org/licenses/LICENSE-2.0" in license_text:
            return "Apache-2.0"
        if "BSD" in license_text or "Redistribution and use in source and binary forms" in license_text:
            # 三条款 vs 二条款：看有没有"endorse"那一条
            return "BSD-3-Clause" if "endorse" in license_text or "promote" in license_text else "BSD-2-Clause"
        if "MIT License" in license_text or "Permission is hereby granted, free of charge" in license_text:
            return "MIT"
        return "见目录内 LICENSE"
    return "未知"


def update_library_index(log=print) -> str:
    """扫描 模型/ 目录，重建 模型库.json（界面选模型时会读它）。

    元数据（显示名 / 许可 / 该加载哪个入口 / 类别）按下面的顺序合并：
      ① `tools/model_manifest.json`（menagerie 官方元数据，优先）
      ② 模型目录里的 `模型信息.json`（本地或非 menagerie 模型用）
         支持的键：显示名、许可、入口模型、类别、自由度、执行器数、说明。
         「入口模型」用于一个目录里有多个 XML、默认的 `*_torque.xml` 不是入口的情况
         （例如 panda_mjpc 的 task.xml）；「类别/自由度/执行器数」用于任务模型 ——
         nq 里混着方块和夹爪，自动读出来的轴数不是机械臂轴数。
    """
    try:
        manifest_models = read_manifest()["models"]
    except SystemExit:
        manifest_models = {}

    entries = []
    for child in sorted(os.listdir(MODEL_DIR)):
        directory = os.path.join(MODEL_DIR, child)
        if not os.path.isdir(directory) or child.startswith("."):
            continue
        xml_files = sorted(f for f in os.listdir(directory) if f.endswith(".xml"))
        if not xml_files:
            continue

        # ---- 元数据：清单优先，其次目录里的 模型信息.json ----
        info = dict(manifest_models.get(child, {}))
        metadata_path = os.path.join(directory, "模型信息.json")
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, encoding="utf-8") as f:
                    local_info = json.load(f)
                if isinstance(local_info, dict):
                    local_info = _rename_keys(local_info, {
                        **MANIFEST_MODEL_KEYS,
                        "entry_model": "入口模型", "torque_model": "扭矩模型",
                        "dof": "自由度", "actuator_count": "执行器数",
                    })
                    info = {**local_info, **info}
            except Exception as exc:                             # noqa: BLE001
                log(f"  ⚠ 读取 {metadata_path} 失败：{type(exc).__name__}: {exc}")

        # ---- 入口 XML：显式指定 > *_torque.xml > 字母序第一个 ----
        requested_entry = str(info.get("entry_model") or info.get("torque_model") or "").replace("\\", "/")
        primary_xml = ""
        if requested_entry:
            candidate = requested_entry.rsplit("/", 1)[-1]
            if candidate in xml_files:
                primary_xml = candidate
        torque_files = sorted(f for f in xml_files if f.endswith("_torque.xml"))
        if not primary_xml:
            primary_xml = torque_files[0] if torque_files else xml_files[0]

        joint_count = actuator_count = -1
        controllable = False
        try:
            import mujoco
            model = mujoco.MjModel.from_xml_path(os.path.join(directory, primary_xml))
            joint_count, actuator_count = int(model.nq), int(model.nu)
            # "可控制" = 本项目控制插件能直接驱动它：ctrl 长度必须等于 qvel 长度
            controllable = bool(model.nu == model.nv == model.nq and model.nu > 0)
        except Exception:                                        # noqa: BLE001
            pass
        if info.get("dof") is not None:
            joint_count = int(info["dof"])
        if info.get("actuator_count") is not None:
            actuator_count = int(info["actuator_count"])

        license_name = info.get("license") or _detect_license(directory)
        category = str(info.get("category") or "")
        if not category:
            if controllable and joint_count >= 6:
                category = "arm"
            elif controllable and joint_count in (1, 2):
                category = "gripper"
            elif controllable:
                category = "other"
            else:
                category = "不可直接控制"      # 例如位置伺服模型、带夹爪导致 nu != nv 的模型
        entry = {
            "identifier": child,
            "display_name": info.get("display_name") or child,
            "category": category,
            "directory": child,
            "torque_model": f"{child}/{primary_xml}",
            "controllable": controllable,
            "dof": joint_count,
            "actuator_count": actuator_count,
            "license": license_name,
            "model_files": [f"{child}/{f}" for f in xml_files],
        }
        if info.get("description"):
            entry["description"] = str(info["description"])
        entries.append(entry)

    index = {
        "schema_version": 2,
        "description": ("驭臂的模型库索引，由 tools/import_model.py 自动生成。"
                        "『扭矩模型』是推荐加载的那个 —— 它的 ctrl 就是关节力矩，能被本项目控制插件直接驱动；"
                        "『可控制』= true 表示 nu==nv==nq（控制插件写 ctrl 的前提）。"
                        "界面按『类别=arm』列出可选机械臂。"),
        "root": "模型",
        "models": entries,
    }
    with open(LIBRARY_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")
    arm_count = sum(1 for e in entries if e["category"] == "arm")
    log(f"  ✓ 已更新模型库索引：模型/模型库.json（{len(entries)} 个模型，其中可控制机械臂 {arm_count} 个）")
    return LIBRARY_INDEX_PATH


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def import_model(model_id: str, info: dict, proxy_prefix: str, torque_only: bool,
             torque_limit: list[float] | None, force: bool, log=print) -> dict:
    directory = os.path.join(MODEL_DIR, model_id)
    log(f"\n【{model_id}】{info['display_name']}　{info['license']}　"
         f"下载 {info['download_bytes']/1e6:.1f} MB / 解包 {info['unpacked_bytes']/1e6:.1f} MB")

    if not torque_only:
        if os.path.isdir(directory) and not force:
            existing = [f for f in os.listdir(directory) if f.endswith((".xml", ".stl", ".obj"))]
            if existing:
                log(f"  ℹ 已存在（{len(existing)} 个模型文件），跳过下载；要重下加 --强制")
        else:
            url = f"{info.get('asset_base_url') or ASSET_BASE_URL}/{info['asset']}"
            with tempfile.TemporaryDirectory(prefix="小软件导入_") as temporary:
                archive_path = os.path.join(temporary, info["asset"])
                download(url, archive_path, proxy_prefix)
                if not verify_checksum(archive_path, info["sha256"]):
                    raise SystemExit(f"  ✗ sha256 校验失败：{info['asset']}"
                                     f"\n     可能是代理返回了错误页，换 --直连 或别的 --代理 再试")
                log("  ✓ sha256 校验通过")
                os.makedirs(MODEL_DIR, exist_ok=True)
                with tarfile.open(archive_path, "r:xz") as tf:
                    try:
                        # filter="data" 是 Python 3.12+ 的安全解包参数；
                        # 3.10 会 TypeError，所以退化为普通解包
                        tf.extractall(MODEL_DIR, filter="data")
                    except TypeError:
                        tf.extractall(MODEL_DIR)
            log(f"  ✓ 已解包到 模型/{model_id}/")

    torque_path, statistics = generate_torque_variant(model_id, directory, info, torque_limit, log)
    log(f"  ✓ 扭矩变体：模型/{os.path.relpath(torque_path, MODEL_DIR)}"
         f"（{statistics['torque_objects']} 个力矩电机，上限 "
         f"{'/'.join(f'{x:g}' for x in statistics['torque_limits'])} N·m）")
    if statistics["discarded_actuators"]:
        log(f"    丢了非关节执行器：{'、'.join(statistics['discarded_actuators'])}（保证 nu == nv）")

    result = validate_torque_variant(torque_path)
    if result["passed"]:
        log(f"  ✓ 闭环验证通过：PD 控制后残差 {result['final_error_deg']:.4f}°"
             f"（历史最大 {result['max_error_deg']:.1f}°）")
    else:
        log(f"  ✗ 闭环验证未通过：{result.get('reason') or result}")
    return {"name": model_id, "stats": statistics, "validation": result}


ASSET_BASE_URL = ""


def main(argv: list[str]) -> int:
    global ASSET_BASE_URL
    ap = argparse.ArgumentParser(description="从 MuJoCo Menagerie 导入机械臂模型")
    ap.add_argument("model", nargs="*", metavar="模型", help="要导入的模型标识（见 --列表）")
    ap.add_argument("--list", "--列表", dest="list_models", action="store_true", help="列出清单里可导入的模型")
    ap.add_argument("--index", "--索引", dest="index", action="store_true", help="只重建 模型/模型库.json（不下载）")
    ap.add_argument("--all", "--全部", dest="all_models", action="store_true", help="导入清单里全部模型")
    ap.add_argument("--proxy", "--代理", dest="proxy", default=None,
                    help="下载代理前缀（默认取清单里的『代理前缀』；传空字符串表示直连）")
    ap.add_argument("--direct", "--直连", dest="direct", action="store_true", help="不用代理，直连 GitHub")
    ap.add_argument("--torque-only", "--只生成扭矩", dest="torque_only", action="store_true", help="不下载，只重新生成扭矩变体")
    ap.add_argument("--torque-limit", "--扭矩上限", dest="torque_limit", default=None,
                    help="模型没给 forcerange 时用的扭矩上限，逗号分隔，如 320,320,176,176,110,40,40")
    ap.add_argument("--force", "--强制", dest="force", action="store_true", help="已存在也重新下载")
    args = ap.parse_args(argv)

    manifest = read_manifest()
    ASSET_BASE_URL = manifest["asset_base_url"]
    all_models = manifest["models"]

    if args.index:
        print("重建模型库索引…")
        update_library_index()
        return 0

    if args.list_models:
        print("=" * 96)
        print(f"可导入的机械臂（{len(all_models)} 个）—— 来源：{manifest['source']}")
        print("=" * 96)
        print(f"  {'标识':26s}{'名称':30s}{'许可':15s}{'下载':>7s}{'解包':>8s}")
        for name, info in sorted(all_models.items(), key=lambda kv: kv[1]["display_name"]):
            installed = "✓" if os.path.isdir(os.path.join(MODEL_DIR, name)) else " "
            print(f"  {installed}{name:25s}{info['display_name'][:28]:30s}{info['license']:15s}"
                  f"{info['download_bytes']/1e6:6.1f}M{info['unpacked_bytes']/1e6:7.1f}M")
        print(f"\n  合计下载 {sum(v['download_bytes'] for v in all_models.values())/1e6:.0f} MB、"
              f"解包 {sum(v['unpacked_bytes'] for v in all_models.values())/1e6:.0f} MB")
        print(f"  协议：全部为 MIT / BSD-3-Clause / Apache-2.0，可自由使用与分发")
        return 0

    selected_models = list(args.model)
    if args.all_models:
        selected_models = sorted(all_models)
    if not selected_models:
        ap.print_help()
        return 1

    unknown_models = [n for n in selected_models if n not in all_models]
    if unknown_models:
        print(f"✗ 清单里没有这些模型：{unknown_models}")
        print("  用 --列表 看可用的标识。")
        return 2

    proxy_prefix = "" if args.direct else (manifest.get("proxy_prefix", "") if args.proxy is None else args.proxy)
    torque_limit = ([float(x) for x in args.torque_limit.replace("，", ",").split(",") if x.strip()]
                if args.torque_limit else None)

    print("=" * 96)
    print(f"导入机械臂模型 → {MODEL_DIR}")
    print(f"下载通道：{'直连 GitHub' if not proxy_prefix else proxy_prefix}")
    print("=" * 96)

    succeeded, failed = [], []
    for name in selected_models:
        override_limits = torque_limit or TORQUE_LIMIT_OVERRIDES.get(name)
        try:
            succeeded.append(import_model(name, all_models[name], proxy_prefix, args.torque_only, override_limits, args.force))
        except SystemExit as e:
            failed.append((name, str(e)))
            print(f"  ✗ 跳过：{e}")
        except Exception as e:                                  # noqa: BLE001
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ✗ 失败：{type(e).__name__}: {e}")

    print()
    update_library_index()

    print()
    print("=" * 96)
    print(f"完成：成功 {len(succeeded)} 个、失败 {len(failed)} 个")
    for r in succeeded:
        print(f"  ✓ {r['name']:24s} 扭矩模型 {'通过' if r['validation']['passed'] else '未通过'}")
    for name, reason in failed:
        print(f"  ✗ {name:24s} {reason[:100]}")
    print()
    print("  加载某个模型：")
    print("    ./.venv/bin/python run_yubi.py --model 模型/<标识>/<默认模型>_torque.xml")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
