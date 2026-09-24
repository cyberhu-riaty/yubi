#!/bin/bash
# 重建小软件的运行环境（换机器后跑一次即可）
#
# 为什么需要它：
#   .app 本身只含"启动器 + 图标"，不含 Python 环境（环境 300+ MB，且路径写死）。
#   所以换台机器后，先跑这个脚本生成 .venv，再双击 .app。
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

# ---------- 2. 造"叠加层"（借用基础环境的 numpy 等，但 mujoco 用新的）----------
echo
echo "== 1/3 创建叠加层 .venv =="
if [ -x "$PKG/.venv/bin/python" ]; then
  echo "  已存在，跳过创建（要重建就先把 .venv 删掉）"
else
  "$BASE" -m venv --system-site-packages "$PKG/.venv"
fi

# ---------- 3. 装官方完整版 mujoco（优先用离线包）----------
echo
echo "== 2/3 安装 mujoco 3.13.0 =="
if ls "$PKG/离线依赖/"mujoco-*.whl >/dev/null 2>&1; then
  echo "  用离线包安装"
  "$PKG/.venv/bin/pip" install --no-index --find-links="$PKG/离线依赖" "mujoco==3.13.0"
else
  echo "  离线包不在，走网络安装"
  "$PKG/.venv/bin/pip" install "mujoco==3.13.0"
fi

# ---------- 4. 修 macOS 上的 glfw（不修则 mjpython 开不了窗）----------
echo
echo "== 3/3 修 glfw 动态库（macOS 必需）=="
"$PKG/.venv/bin/pip" install --force-reinstall --no-deps "glfw==2.10.2"

# ---------- 5. 可选：参数辨识用的依赖 ----------
if ls "$PKG/离线依赖/"scipy-*.whl >/dev/null 2>&1; then
  echo
  echo "== 附加：安装参数辨识依赖（离线包）=="
  "$PKG/.venv/bin/pip" install --no-index --find-links="$PKG/离线依赖" \
      scipy colorama imageio imageio-ffmpeg plotly pyyaml tabulate typing_extensions \
      || echo "  （部分依赖没装上，参数辨识可能不可用；界面和执行控制不受影响）"
fi

# ---------- 6. 自检 ----------
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
PY

echo
echo "完成。双击启动："
echo "  open \"$PKG/$(basename "$PKG").app\""
