"""
package_macos_app.py —— 生成 macOS 的 .app（双击即启动）

为什么不用 Platypus / PyInstaller：
    macOS 的 .app 本质就是一个"有固定目录结构的文件夹"：
        驭臂.app/Contents/Info.plist           ← 名字/版本/版权声明（XML）
        驭臂.app/Contents/MacOS/驭臂            ← **原生 arm64 启动器**（编译出来的小可执行文件）
        驭臂.app/Contents/Resources/启动.sh      ← 启动逻辑（bash 脚本，真正干活的那个）
    ★ Contents/MacOS/ 里只放 Mach-O，不放脚本 —— 这样整个 .app 才能被签名，
      也避免系统在判断架构时看到"非 Mach-O 的可执行文件"而产生歧义。
    PyInstaller 会试图把整个 Python 环境和 mujoco 的 16 个 .so 一起打包，
    mujoco 包里还带 Filament 材质资产，很容易漏文件；而我们的 .venv 本来就现成，
    启动脚本直接调它即可 —— **更小、更可控、不依赖打包工具**。

★ 为什么需要那个"原生 arm64 启动器"（踩过的坑，别删）：
    最初 .app 的 CFBundleExecutable 直接指向一个 **bash 脚本**。
    脚本没有架构信息 → macOS 查不到 `kMDItemExecutableArchitectures`（返回 null）
    → 在 Apple Silicon 上无法确认是原生应用 → **双击时弹"要安装 Rosetta"**。
    明明整个软件都是 arm64 原生的，却被要求装 Intel 翻译层。
    解决：编译一个几行的 arm64 C 程序作为 CFBundleExecutable，它只负责
    "算出自己在哪 → exec /bin/bash 那个脚本"。这样 macOS 一眼看出是原生 arm64，
    不再提示 Rosetta；而启动逻辑仍然留在 bash 脚本里（改代码不用重新打包）。

特点：
    · 启动器自己算"包根"（四级回退），所以**整个包搬到任何目录都能跑**
    · 环境缺失时弹中文对话框提示，而不是闪退
    · 运行日志写到 包根/启动日志.txt（双击时看不到终端，靠这个排查）
    · Bundle Identifier 自动保证唯一（避免两个 .app 撞 id、互相干扰）

用法：
    .venv/bin/python tools/package_macos_app.py                  # 在资料包根目录生成 .app
    .venv/bin/python tools/package_macos_app.py --包根 /路径       # 指定包根
    .venv/bin/python tools/package_macos_app.py --名字 "小软件"     # 换软件名
    .venv/bin/python tools/package_macos_app.py --标识 local.digitwin.yubi   # 显式指定 bundle id
"""
from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------------------
# ① bash 启动器（真正的启动逻辑）
#    ★ 三个踩过的坑都体现在这里：
#      ① bash 变量名只能用 ASCII（用中文会报 "No such file or directory"）
#      ② Contents/MacOS → Contents → .app → 包根，是上 3 级（写成 4 级会去找 /tmp/.venv）
#      ③ 用 exec 让 Python 接管进程，关窗口即退出，Dock 不留残影
# ---------------------------------------------------------------------------
LAUNCH_SCRIPT_TEMPLATE = """#!/bin/bash
# {app_name} 启动器（由 .app 双击调用；真正的启动逻辑都在这里）
#
# ★ 定位"包根"（装 .venv 和代码的那个目录）用了**四级回退**，
#   因为 .app 会被放到桌面、Dock、甚至别的目录 —— 写死相对路径一挪就废。
#   顺序：① 应用包内配置 → ② 环境变量 → ③ 常见位置搜 → ④ 相对路径（兼容老布局）
#
# ★ 本脚本住在 X.app/Contents/Resources/ 里，由 Contents/MacOS/ 下的
#   原生 arm64 启动器（{app_name}）exec 调起 —— 这样 macOS 才能认出这是原生应用、
#   不提示安装 Rosetta。（脚本不放 MacOS/ 是为了让整个 .app 能被签名。）
set -u
RES_DIR="$(cd "$(dirname "$0")" && pwd)"        # …/X.app/Contents/Resources
APP_CONTENTS="$(cd "$RES_DIR/.." && pwd)"       # …/X.app/Contents
PKG_DIR=""

# ① 应用包内配置（打包时写入，最准）
if [ -z "$PKG_DIR" ] && [ -f "$RES_DIR/包路径.txt" ]; then
  CAND="$(head -1 "$RES_DIR/包路径.txt" | tr -d '\\r\\n')"
  [ -n "$CAND" ] && [ -d "$CAND" ] && PKG_DIR="$CAND"
fi
# ② 环境变量（方便你自己指定）
if [ -z "$PKG_DIR" ]; then
  CAND="${YUBI_PACKAGE_PATH:-$(printenv '小软件_包路径')}"
  [ -n "$CAND" ] && [ -d "$CAND" ] && PKG_DIR="$CAND"
fi
# ③ 常见位置搜一遍（桌面 / 家目录 / 文档）
if [ -z "$PKG_DIR" ]; then
  for CAND in "$HOME/Desktop/{package_dir_name}" "$HOME/{package_dir_name}" "$HOME/Documents/{package_dir_name}"; do
    if [ -x "$CAND/.venv/bin/python" ]; then PKG_DIR="$CAND"; break; fi
  done
fi
# ④ 相对路径（.app 仍在包内时的老布局）：Contents/../.. 就是包根
if [ -z "$PKG_DIR" ]; then
  CAND="$(cd "$APP_CONTENTS/../.." && pwd)"
  [ -x "$CAND/.venv/bin/python" ] && PKG_DIR="$CAND"
fi

if [ -z "$PKG_DIR" ]; then
  osascript -e 'display dialog "找不到{app_name}的安装位置（含 .venv 的包文件夹）。\n\n请把整个包文件夹放到桌面，或设置环境变量 YUBI_PACKAGE_PATH 指向它。" buttons {{"好"}} default button 1 with icon stop' 2>/dev/null
  exit 1
fi
LOG="$PKG_DIR/启动日志.txt"
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 启动，包根=$PKG_DIR =====" >> "$LOG"
# ★ 首次双击时 macOS 会弹「"小软件" 想访问"桌面"文件夹中的文件」——
#   因为整个包在 ~/Desktop 下，而桌面是受保护目录。**必须点「允许」**，
#   否则进程会卡在那个 open() 上（日志只有这一行，什么错都不报）。
#   这是系统行为，不是程序 bug；同一个 .app 只需授权一次。
#   写在下面这句里，是为了让排查的人先看到它。
echo "（若卡住不动：请在弹出的「想访问桌面文件夹」对话框里点【允许】）" >> "$LOG"

PY="$PKG_DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then
  osascript -e 'display dialog "找到了包文件夹，但里面没有运行环境（.venv）。\n\n请先在终端执行：\nbash tools/rebuild_environment.sh" buttons {{"好"}} default button 1 with icon stop' 2>/dev/null
  echo "✗ 找不到 $PY" >> "$LOG"; exit 1
fi

# 主程序位置：不同包结构不一样（资料包 / 独立包），逐个试。
# ★ 入口**回退链**：宿主窗口优先（界面与 3D 都在自己的窗口里），
#   缺 PyObjC / 端口被占 / 起不来时退回浏览器版，再退回原生 ImGui 版 ——
#   双击图标不该"开不出东西"。
for CAND in "$PKG_DIR/{entry_path}" {fallback_candidates}; do
  if [ -f "$CAND" ]; then APP_PY="$CAND"; break; fi
done
if [ -z "$APP_PY" ]; then
  osascript -e 'display dialog "找到了包文件夹，但里面找不到主程序。\n\n期望位置：{entry_path} / run_yubi.py / run_yubi_web.py" buttons {{"好"}} default button 1 with icon stop' 2>/dev/null
  echo "✗ 找不到主程序（都试过了）" >> "$LOG"; exit 1
fi

# 运行期回退：当前入口**非 0 退出**时换下一个（0 = 用户正常关了窗口，不回退）
fallback() {
  case "$APP_PY" in
    */run_yubi.py)      NEXT_ENTRY="$PKG_DIR/run_yubi_web.py" ;;
    */run_yubi_web.py)  return 1 ;;
    *)                return 1 ;;
  esac
  [ -f "$NEXT_ENTRY" ] || return 1
  echo "----- $APP_PY 未能启动，回退到 $NEXT_ENTRY -----" >> "$LOG"
  APP_PY="$NEXT_ENTRY"
  return 0
}

cd "$PKG_DIR" || exit 1
# {extra_args} 由打包时写入（例如 Web 版是 --不开浏览器；原生版为空）。
# ★ 为什么固定参数写在包里而不是靠用户传：双击 .app **传不了参数**，
#   而两种前端的默认行为不一样（Web 版要自动开浏览器、且不能重复开）。
while :; do
  # shellcheck disable=SC2086
  "$PY" -u "$APP_PY" {extra_args} "$@" >> "$LOG" 2>&1
  EXIT_CODE=$?
  # 0 = 正常退出（用户关了窗口），不回退
  [ "$EXIT_CODE" -eq 0 ] && exit 0
  fallback || exit "$EXIT_CODE"
done
"""

# ---------------------------------------------------------------------------
# ② 原生 arm64 启动器（C 源码，编译成 Contents/MacOS/<软件名>）
#
#    它只做一件事：找到自己所在的目录 → exec /bin/bash 同目录下的"启动"脚本，
#    并把命令行参数原样转发。这样 CFBundleExecutable 是一个真正的 arm64 Mach-O，
#    macOS 就能确定这是原生应用 —— **不再提示安装 Rosetta**。
#
#    ★ 为什么用 /bin/bash 显式执行，而不是直接 exec 脚本：
#      脚本可能因为 zip/拷贝丢了可执行位，显式用 bash 更稳。
#    ★ 为什么用 _NSGetExecutablePath + realpath：
#      双击启动时工作目录是 /，argv[0] 可能不完整；必须自己问系统要绝对路径。
# ---------------------------------------------------------------------------
NATIVE_LAUNCHER_SOURCE = r"""// {app_name} 原生 arm64 启动器（由 tools/package_macos_app.py 生成，勿手改）
//
// 存在意义：让 macOS 认出 .app 是原生 arm64 应用，不提示安装 Rosetta。
// 做法：算出自己的绝对路径 → 上一级的 Resources/启动.sh → 转发全部参数。
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach-o/dyld.h>

int main(int argc, char** argv) {
  char self_path[PATH_MAX];
  uint32_t path_length = sizeof(self_path);
  if (_NSGetExecutablePath(self_path, &path_length) != 0) {
    fprintf(stderr, "{app_name}: 无法获取自身路径（路径过长？）\n");
    return 1;
  }
  char resolved_path[PATH_MAX];
  if (realpath(self_path, resolved_path) == NULL) {
    fprintf(stderr, "{app_name}: 无法解析自身路径\n");
    return 1;
  }
  // 目录 = …/X.app/Contents/MacOS
  char* slash = strrchr(resolved_path, '/');
  if (slash == NULL) {
    fprintf(stderr, "{app_name}: 自身路径异常：%s\n", resolved_path);
    return 1;
  }
  *slash = '\0';

  char script_path[PATH_MAX];
  if (snprintf(script_path, sizeof(script_path), "%s/../Resources/启动.sh", resolved_path) >= (int)sizeof(script_path)) {
    fprintf(stderr, "{app_name}: 路径过长\n");
    return 1;
  }
  if (access(script_path, R_OK) != 0) {
    fprintf(stderr, "{app_name}: 找不到启动脚本：%s\n", script_path);
    return 1;
  }

  // argv = ["/bin/bash", 脚本, 原参数…, NULL]
  char** new_argv = (char**)calloc((size_t)argc + 3, sizeof(char*));
  if (new_argv == NULL) {
    fprintf(stderr, "{app_name}: 内存不足\n");
    return 1;
  }
  new_argv[0] = (char*)"/bin/bash";
  new_argv[1] = script_path;
  for (int i = 1; i < argc; i++) {
    new_argv[i + 1] = argv[i];
  }
  new_argv[argc + 1] = NULL;

  execv("/bin/bash", new_argv);
  fprintf(stderr, "{app_name}: 无法执行 /bin/bash\n");
  return 1;
}
"""


def _identifier_suffix(app_name: str) -> str:
    """把软件名转成 bundle id 里可用的一段（必须是 ASCII）。

    纯 ASCII 名字直接用（去掉非法字符）；中文等非 ASCII 名字用名字的 sha256 前 8 位，
    保证"同一个名字每次都得到同一个 id"，且不会和别的软件撞。
    """
    clean_name = "".join(c.lower() for c in app_name if c.isascii() and (c.isalnum() or c == "-"))
    if clean_name:
        return clean_name
    return hashlib.sha256(app_name.encode("utf-8")).hexdigest()[:8]


def compile_native_launcher(target_path: str, app_name: str, build_dir: str) -> tuple[bool, str]:
    """把 启动器源码 编译成 arm64 可执行文件。返回 (是否成功, 说明)。"""
    compiler = shutil.which("cc") or shutil.which("clang")
    if compiler is None:
        return False, "找不到 cc / clang（需要 Xcode 命令行工具：xcode-select --install）"
    source_file = os.path.join(build_dir, "启动器.c")
    with open(source_file, "w", encoding="utf-8") as f:
        f.write(NATIVE_LAUNCHER_SOURCE.replace("{app_name}", app_name))
    # -arch arm64：明确只要 arm64 切片，让 macOS 一眼看出是原生应用
    command = [compiler, "-arch", "arm64", "-O2", "-Wall", "-o", target_path, source_file]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "编译失败").strip()[:400]
    if not os.path.exists(target_path):
        return False, "编译命令返回成功但没有产出文件"
    os.chmod(target_path, os.stat(target_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return True, compiler


def build_app(package_root: str, app_name: str, entry_path: str, bundle_id: str | None, version: str,
         extra_args: str = "",
         icon: str | None = None) -> str:
    app = os.path.join(package_root, f"{app_name}.app")
    os.makedirs(os.path.join(app, "Contents", "MacOS"), exist_ok=True)
    resources_dir = os.path.join(app, "Contents", "Resources")
    os.makedirs(resources_dir, exist_ok=True)
    plist_path = os.path.join(app, "Contents", "Info.plist")

    # 图标：把 .icns 复制进 Resources，并在 Info.plist 里声明 CFBundleIconFile
    icon_name = ""
    if icon and os.path.exists(icon):
        shutil.copyfile(icon, os.path.join(resources_dir, "图标.icns"))
        icon_name = "icon"
    else:
        print("  ℹ 没找到 .icns 图标（可先跑 tools/generate_app_icon.py），本次不设图标")

    # ---- ① 先写 bash 启动脚本（启动逻辑）----
    #      放在 Resources/ 而不是 MacOS/：MacOS/ 里只留 Mach-O，整个 .app 才能签名
    script_path = os.path.join(resources_dir, "启动.sh")
    package_dir_name = os.path.basename(os.path.normpath(package_root))
    # ★ 用 replace 而不是 str.format：启动器里有大量 shell 的 ${变量} 和 {{ }}，
    #   用 format 会把它们当占位符（实测报 KeyError: '驭臂_包路径'）。
    #
    # ★ 回退链里要去掉"已经是指定入口"的那一项，避免重复候选。
    #   （功能上无害，但读起来像 bug，而且真正的第二候选被挤到后面才试）。
    candidates = ["run_yubi.py", "run_yubi_web.py"]
    fallback_entries = [c for c in candidates if os.path.normpath(c) != os.path.normpath(entry_path)]
    fallback_args = " ".join(f'"$PKG_DIR/{c}"' for c in fallback_entries)
    script = (LAUNCH_SCRIPT_TEMPLATE
            .replace("{app_name}", app_name)
            .replace("{entry_path}", entry_path)
            .replace("{fallback_candidates}", fallback_args)
            .replace("{package_dir_name}", package_dir_name)
            .replace("{extra_args}", extra_args.strip()))
    # 上面把 shell 里被误写的 {{ }} 还原成 { }
    script = script.replace("{{", "{").replace("}}", "}")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    # 清掉老版本遗留在 MacOS/ 里的脚本（否则签名会失败：MacOS/ 里混进了非 Mach-O 文件）
    legacy_script = os.path.join(app, "Contents", "MacOS", "启动")
    # ---- ② 编译原生 arm64 启动器，作为 CFBundleExecutable ----
    executable_name = app_name
    executable_path = os.path.join(app, "Contents", "MacOS", executable_name)
    with tempfile.TemporaryDirectory(prefix="小软件打包_") as build_dir:
        compiled, detail = compile_native_launcher(executable_path, app_name, build_dir)
    if compiled:
        if legacy_script != executable_path and os.path.isfile(legacy_script):
            os.remove(legacy_script)
        print(f"  ✓ 已编译原生 arm64 启动器：Contents/MacOS/{executable_name}")
        executable = executable_name
    else:
        # 兜底：退回老做法（CFBundleExecutable 直接指向 bash 脚本）。
        # 副作用：double-click 时 macOS 可能提示安装 Rosetta（因为脚本没有架构信息）。
        print(f"  ⚠ 原生启动器编译失败，退回脚本启动器：{detail}")
        print("     → 副作用：双击时 macOS 可能提示安装 Rosetta（软件本身其实全是 arm64 原生）")
        print("     → 修好编译环境后重跑本脚本即可解决")
        executable = "启动"
        with open(legacy_script, "w", encoding="utf-8", newline="\n") as f:
            f.write('#!/bin/bash\nexec /bin/bash "$(dirname "$0")/../Resources/启动.sh" "$@"\n')
        os.chmod(legacy_script, os.stat(legacy_script).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # ---- ③ Bundle Identifier：显式 > 沿用已有的 > 按名字自动派生 ----
    #     为什么重要：两个 .app 用同一个 id 会互相干扰（实测踩过：
    #     驭臂.app 与 数字样机.app 撞 id，撞出一条带 LSArchitecturePriority 的旧记录，
    #     让 macOS 误判架构）。
    previous_id = ""
    if not bundle_id and os.path.exists(plist_path):
        try:
            with open(plist_path, "rb") as f:
                previous_id = plistlib.load(f).get("CFBundleIdentifier", "") or ""
        except Exception:                                          # noqa: BLE001
            previous_id = ""
    if bundle_id:
        resolved_bundle_id, id_source = bundle_id, "命令行 --bundle-id"
    elif previous_id:
        resolved_bundle_id, id_source = previous_id, "沿用上一次的 id"
    else:
        resolved_bundle_id, id_source = f"local.digitwin.{_identifier_suffix(app_name)}", "按名字自动派生"
    print(f"  Bundle ID：{resolved_bundle_id}（{id_source}）")

    # ---- ④ Info.plist ----
    #     版权声明里写清与 Google DeepMind 无关联（Apache-2.0 的商标要求）
    plist_info = {
        "CFBundleName": app_name,
        "CFBundleDisplayName": app_name,
        "CFBundleIdentifier": resolved_bundle_id,
        "CFBundleExecutable": executable,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        # ★ 声明"这是 macOS 原生应用"，配合原生启动器可彻底避免 Rosetta 提示
        "CFBundleSupportedPlatforms": ["MacOSX"],
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": (
            "本项目与 Google DeepMind 无关联，未获其背书。"
            "基于 MuJoCo（Apache-2.0）。"
        ),
    }
    # ★ 刻意不写 LSArchitecturePriority：写了反而可能让系统误判该用哪个架构。
    if icon_name:
        plist_info["CFBundleIconFile"] = icon_name
    with open(plist_path, "wb") as f:
        plistlib.dump(plist_info, f)

    # 把"包根"写进应用包，启动器优先读它 —— 这样 .app 放到哪里都能找到代码
    with open(os.path.join(resources_dir, "包路径.txt"), "w", encoding="utf-8") as f:
        f.write(package_root + "\n")

    # ---- ⑤ 对 .app 做 ad-hoc 签名 ----
    #     Apple Silicon 上所有可执行文件都必须有签名（编译时已自动 ad-hoc 签过 Mach-O），
    #     这里把整个 bundle 也签一下，让 macOS 把它当成一个"正常应用"，
    #     避免 LaunchServices / Gatekeeper 因为"未签名的 bundle"产生额外的架构猜测。
    if compiled:
        _sign_bundle(app)
    return app


def _sign_bundle(app: str) -> None:
    """对整个 .app 做 ad-hoc 签名（失败只提示，不影响使用）。"""
    if shutil.which("codesign") is None:
        print("  ℹ 找不到 codesign，跳过签名（不影响使用）")
        return
    result = subprocess.run(["codesign", "--force", "--sign", "-", app],
                          capture_output=True, text=True)
    if result.returncode == 0:
        print("  ✓ 已对 .app 做 ad-hoc 签名")
    else:
        detail = (result.stderr or result.stdout or "").strip().replace("\n", " ")[:300]
        print(f"  ⚠ .app 签名失败（不影响启动）：{detail}")


def refresh_registration(app: str) -> None:
    """让 LaunchServices 重新读一遍这个 .app（清掉旧的架构缓存）。

    为什么需要：macOS 会把 app 的架构信息缓存进 LaunchServices 数据库。
    换过启动器之后不刷新，系统可能还按旧记录判断 —— 于是仍然提示装 Rosetta。
    """
    lsr = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
           "LaunchServices.framework/Support/lsregister")
    if not os.path.exists(lsr):
        print("  ℹ 找不到 lsregister，跳过刷新（重启 Finder 或重新登录后也会自动刷新）")
        return
    result = subprocess.run([lsr, "-f", app], capture_output=True, text=True)
    if result.returncode == 0:
        print("  ✓ 已刷新 LaunchServices 注册（清掉旧的架构缓存）")
    else:
        print(f"  ⚠ 刷新 LaunchServices 失败（不影响使用）：{(result.stderr or '').strip()[:200]}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="生成 macOS .app（双击启动）")
    ap.add_argument("--package-root", "--包根", default=None, help="资料包根目录（默认：本脚本的上上级）")
    ap.add_argument("--name", "--名字", default="小软件", help="软件名（用于 Info.plist 的显示名）")
    ap.add_argument("--output-name", "--输出名", default=None,
                    help=".app 的文件名（默认与 --name 相同）。"
                         "同一台机器上有两个前端时用它区分文件，显示名仍可一致")
    ap.add_argument("--extra-args", "--附加参数", default="",
                    help="写进启动器的固定参数（双击传不了参数，所以固定参数要落在包里）")
    ap.add_argument("--entry", "--主程序", default="run_yubi.py",
                    help="主程序相对于包根的路径")
    ap.add_argument("--bundle-id", "--标识", default=None,
                    help="Bundle Identifier（默认：沿用已有的；没有则按名字自动派生一个唯一 id）")
    ap.add_argument("--version", "--版本", default="0.6.0", help="版本号")
    ap.add_argument("--icon", "--图标", default=None, help=".icns 路径（默认：tools/图标.icns）")
    ap.add_argument("--no-refresh", "--不刷新注册", action="store_true",
                    help="不调用 lsregister 刷新系统注册")
    args = ap.parse_args(argv)

    # 本脚本在 <包根>/tools/ 下 → 上一级就是包根
    #   （原来写的是上两级，那是"脚本在 tools/打包/ 里"的老结构，早已不成立）
    package_root = args.package_root or os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

    print("=" * 68)
    print("build_app macOS .app")
    print("=" * 68)
    print(f"  package_root    : {package_root}")
    if not os.path.isdir(package_root):
        print("  ✗ 包根不存在")
        return 1
    if not os.path.exists(os.path.join(package_root, args.entry)):
        print(f"  ⚠ 主程序不在预期位置：{args.entry}")
        print("     （仍会生成，但双击时会弹'找不到主程序'）")

    icon = args.icon or os.path.join(package_root, "tools", "图标.icns")
    app = build_app(package_root, args.output_name or args.name, args.entry, args.bundle_id, args.version,
               extra_args=args.extra_args, icon=icon)

    if not args.no_refresh:
        refresh_registration(app)

    print(f"  已生成  : {app}")
    print()
    print("  .app 结构：")
    for root, dirs, files in os.walk(app):
        for f in files:
            p = os.path.join(root, f)
            print(f"    {os.path.relpath(p, app)}")
    print()
    print("  双击即可启动。若没反应，看包根下的 启动日志.txt。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
