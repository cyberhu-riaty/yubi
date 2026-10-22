#!/bin/bash
# 重建驭臂的运行环境（换机器后跑一次即可）
#
# 为什么需要它：
#   .venv 有 190 MB 左右，且路径写死，不能随仓库分发。
#   换台机器后先跑这个脚本，再启动 软件/主程序窗口.py。
#
# 为什么不用 conda 的 robot 环境直接用：
#   conda 渠道装的 mujoco 是"零件版"，**不含界面层和插件系统**
#   （实测报错 ImportError: cannot import name 'sim' from 'mujoco.experimental.studio'）。
#   官方 pip 完整版才有那些东西。
#
# 用法：
#   bash 工具/重建环境.sh
set -e
cd "$(dirname "$0")/.."          # 切到包根
PKG="$(pwd)"
echo "包根：$PKG"

# ---------- 1. 找基础 Python（要 3.10 左右）----------
BASE=""
for CAND in "$HOME/miniforge3/envs/robot/bin/python" "$HOME/miniforge3/bin/python" \
            "$(command -v python3.10 || true)" "$(command -v python3 || true)"; do
  if [ -n "$CAND" ] && [ -x "$CAND" ]; then BASE="$CAND"; break; fi
done
if [ -z "$BASE" ]; then
  echo "✗ 找不到 Python。请先装 miniforge/conda，或改本脚本里的 BASE。"
  exit 1
fi
echo "基础 Python：$BASE"
"$BASE" -c "import sys; print('  版本', sys.version.split()[0])"
"$BASE" - <<'PY'
import sys
if not (sys.version_info[:2] == (3, 10)):
    print(f"  ⚠ 本机实测基线是 Python 3.10，当前是 {sys.version.split()[0]}；"
          "其他版本可能没有对应的 mujoco wheel。")
PY

# ---------- 2. 造"叠加层"（借用基础环境的 numpy 等，但 mujoco 用新的）----------
echo
echo "== 1/4 创建叠加层 .venv =="
if [ -x "$PKG/.venv/bin/python" ]; then
  echo "  已存在，跳过创建（要重建就先把 .venv 删掉）"
else
  "$BASE" -m venv --system-site-packages "$PKG/.venv"
fi

离线依赖目录="$PKG/归档/离线依赖"

# ---------- 3. 装官方完整版 mujoco（优先用离线包）----------
echo
echo "== 2/4 安装 mujoco 3.13.0 =="
if ls "$离线依赖目录/"mujoco-*.whl >/dev/null 2>&1; then
  echo "  用离线包安装"
  "$PKG/.venv/bin/pip" install --no-index --find-links="$离线依赖目录" "mujoco==3.13.0"
else
  echo "  离线包不在，走网络安装"
  "$PKG/.venv/bin/pip" install "mujoco==3.13.0"
fi

# ---------- 4. 修 macOS 上的 glfw（不修则 mjpython 开不了窗）----------
echo
echo "== 3/4 修 glfw 动态库（macOS 必需）=="
"$PKG/.venv/bin/pip" install --force-reinstall --no-deps "glfw==2.10.2"

# ---------- 4/4 界面通信与 macOS 窗口依赖 ----------
#   · websockets：Web 桥（前端 ↔ Python）必须
#   · PyObjC：宿主窗口（NSWindow + WKWebView + NSOpenGLView）必须
#   缺了它们时窗口入口会打印人话提示，浏览器入口也起不来（Web 桥依赖 websockets）。
echo
echo "== 4/4 安装界面依赖 =="
"$PKG/.venv/bin/pip" install "websockets>=13" \
    || echo "  ⚠ websockets 没装上：Web 桥不可用"
if [ "$(uname -s)" = "Darwin" ]; then
  "$PKG/.venv/bin/pip" install \
      pyobjc-framework-Cocoa pyobjc-framework-WebKit pyobjc-framework-Quartz \
      || echo "  ⚠ PyObjC 没装上：宿主窗口不可用（可改用 软件/主程序Web.py）"
else
  echo "  （非 macOS：跳过 PyObjC，宿主窗口不可用）"
fi

# ---------- 5. 可选：参数辨识用的依赖 ----------
if ls "$离线依赖目录/"scipy-*.whl >/dev/null 2>&1; then
  echo
  echo "== 附加：安装参数辨识依赖（离线包）=="
  "$PKG/.venv/bin/pip" install --no-index --find-links="$离线依赖目录" \
      scipy colorama imageio imageio-ffmpeg plotly pyyaml tabulate typing_extensions \
      || echo "  （部分依赖没装上，参数辨识可能不可用；界面和执行控制不受影响）"
else
  echo
  echo "== 参数辨识依赖（可选）=="
  echo "  离线包不在，跳过；需要辨识时手动装："
  echo "    \"$PKG/.venv/bin/pip\" install scipy colorama imageio imageio-ffmpeg plotly pyyaml tabulate typing_extensions"
fi

# ---------- 6. 前端生成物（把契约与风格表同步到前端）----------
#   前端是 Web 技术栈，但它**不是**运行时的必需品：
#     · `软件/web/` 里若没有构建产物，Web 数据出口会自动回落到内置的单文件仪表盘；
#     · 但只要前端源码在，生成物就必须与来源同步，否则前端会拿旧契约解析新数据。
#   所以这一步总是跑（纯 Python，秒级，无网络、无 Node 依赖）。
echo
echo "== 前端生成物（契约 → TS、风格表 → CSS）=="
"$PKG/.venv/bin/python" "$PKG/工具/生成前端资产.py" \
    || echo "  （生成失败，不影响软件本体；前端可能显示旧契约）"

#   注意：**构建**前端（vite build）需要 Node，且只在"改了前端"时才需要。
#   构建产物入库，所以普通用户双击启动不需要 Node。要重新构建见 前端/约定.md §四。

# ---------- 7. 自检 ----------
echo
echo "== 自检 =="
"$PKG/.venv/bin/python" - <<'PY'
import sys
try:
    import mujoco
    print("  ✓ mujoco", mujoco.__version__)
except Exception as e:
    print("  ✗ mujoco 导入失败：", e); sys.exit(1)
try:
    from mujoco.experimental.studio import launch_passive, viewer_app, step_control
    print("  ✓ 界面层与插件系统可用")
except Exception as e:
    print("  ✗ 界面层不可用：", e); sys.exit(1)
try:
    import websockets
    print("  ✓ websockets", websockets.__version__)
except Exception as e:
    print("  ⚠ websockets 不可用（Web 桥起不来）：", e)
if sys.platform == "darwin":
    try:
        import objc, AppKit, WebKit  # noqa: F401
        print("  ✓ PyObjC（宿主窗口可用）")
    except Exception as e:
        print("  ⚠ PyObjC 不可用（宿主窗口起不来，可改用 软件/主程序Web.py）：", e)
PY

echo
echo "完成。启动："
echo "  \"$PKG/.venv/bin/python\" \"$PKG/软件/主程序窗口.py\""
echo "  （浏览器入口：\"$PKG/.venv/bin/python\" \"$PKG/软件/主程序Web.py\"）"
echo "  想要双击图标：.venv/bin/python 工具/打包应用.py --主程序 软件/主程序窗口.py"
