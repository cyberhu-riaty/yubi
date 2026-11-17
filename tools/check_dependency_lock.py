"""
check_dependency_lock.py —— 当前环境是否与"实测跑通过"的版本一致

为什么要有它（第 3 步 C1）：
    官方把插件系统所在模块标为 experimental，官方升级会直接冲击外壳。
    我们把实测通过的版本钉在 `requirements.lock` 里，用这个脚本随时核对：
      · 版本一致 → 放心
      · 版本不同 → 明确警告（并告出怎么退回实测版本）
    配合 `runtime/official_api.py` 的自检与 `tools/selfchecks/official_api_selfcheck.py`，
    形成"版本 + 接口"两道防线：版本对了接口不一定对，接口对了版本也未必对，两道都要。

用法：
    .venv/bin/python tools/check_dependency_lock.py
    .venv/bin/python tools/check_dependency_lock.py --锁 某个别的.lock
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from importlib import metadata


def parse_lock_file(path: str) -> tuple[dict[str, str], dict[str, str]]:
    """返回 (必需包, 可选包)。规则：'# ===== 可选' 之后的条目算可选。"""
    required: dict[str, str] = {}
    optional: dict[str, str] = {}
    current = required
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("#"):
            if "可选" in line:
                current = optional
            continue
        if not line:
            continue
        # requirements 的 `; sys_platform == "..."` 是平台条件，不是版本号。
        # 只检查当前平台实际应该安装的条目，避免 macOS 把 PySide6 报成缺失、
        # Windows 又把 PyObjC 报成缺失。
        if ";" in line:
            entry, condition = (section.strip() for section in line.split(";", 1))
            platform_marker = re.fullmatch(r"sys_platform\s*==\s*['\"]([^'\"]+)['\"]", condition)
            if platform_marker and sys.platform != platform_marker.group(1):
                continue
            line = entry
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s#]+)", line)
        if match:
            current[match.group(1)] = match.group(2)
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+)\s*(#.*)?$", line)
        if match:
            current.setdefault(match.group(1), "")   # 只声明不钉版本
    return required, optional


def installed_version(package_name: str) -> str | None:
    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return None


def main(argv: list[str]) -> int:
    directory = os.path.dirname(os.path.abspath(__file__))
    default_lock = os.path.normpath(os.path.join(directory, "..", "..", "requirements.lock"))
    # 兼容资料包结构（tools/ 在包根下）
    if not os.path.exists(default_lock):
        default_lock = os.path.normpath(os.path.join(directory, "..", "requirements.lock"))

    ap = argparse.ArgumentParser(description="核对版本锁")
    ap.add_argument("--lock", "--锁", default=default_lock, help="锁文件路径")
    args = ap.parse_args(argv)

    if not os.path.exists(args.lock):
        print(f"✗ 找不到锁文件：{args.lock}")
        return 2

    required, optional = parse_lock_file(args.lock)
    print("=" * 74)
    print("版本锁核对")
    print(f"  锁文件：{args.lock}")
    print("=" * 74)

    mismatches: list[str] = []
    missing: list[str] = []

    print("【必需】外壳运行靠这些")
    for package, expected in sorted(required.items()):
        actual = installed_version(package)
        if actual is None:
            missing.append(package)
            print(f"  ✗ {package:16s} 未安装（锁要求 {expected or '任意版本'}）")
        elif expected and actual != expected:
            mismatches.append(f"{package}: 装的是 {actual}，锁要求 {expected}")
            print(f"  ⚠ {package:16s} 装的是 {actual}，锁要求 {expected}")
        else:
            print(f"  ✓ {package:16s} {actual}")

    print("\n【可选】第 4 步 D3（参数辨识）用")
    for package, expected in sorted(optional.items()):
        actual = installed_version(package)
        if actual is None:
            print(f"  – {package:16s} 未安装（不影响外壳；装法见 requirements.lock 注释）")
        else:
            print(f"  ✓ {package:16s} {actual}")

    print()
    if mismatches or missing:
        print("⚠ 环境与实测版本不一致 —— 官方 API 可能已变，建议：")
        print("   ① 先跑接口自检：  .venv/bin/python run_yubi.py --check")
        print("   ② 若自检有失败项，退回实测版本：")
        print("      .venv/bin/pip install -r requirements.lock")
        return 1
    print("✓ 必需包全部与实测版本一致")
    print("  提示：版本一致不代表接口一定对，请再跑一次 `run_yubi.py --check`。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
