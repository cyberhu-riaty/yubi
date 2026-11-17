"""ASCII environment-variable names with legacy aliases.

Machine-facing configuration uses ``YUBI_*`` names.  Older launchers and user
scripts may still export the previous Chinese names; reads accept both, writes
only use the ASCII name.  Keeping the alias table here makes the compatibility
boundary explicit and testable.
"""
from __future__ import annotations

import os

LEGACY_NAMES = {
    "YUBI_MODEL": "驭臂_模型",
    "YUBI_WEB_PORT": "驭臂_Web端口",
    "YUBI_CURRENT_MODEL": "驭臂_当前模型",
    "YUBI_CURRENT_PROJECT": "驭臂_当前项目",
    "YUBI_DIAGNOSTIC": "驭臂_宿主诊断",
    "YUBI_DISABLE_WEB": "驭臂_关Web",
    "YUBI_GFX": "驭臂_gfx",
    "YUBI_LANG": "驭臂_语言",
    "YUBI_PACKAGE_PATH": "小软件_包路径",
}


def read(name: str, default: str = "") -> str:
    """Read an ASCII variable; fall back to its legacy alias when unset."""
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    legacy = LEGACY_NAMES.get(name)
    if legacy:
        value = os.environ.get(legacy)
        if value not in (None, ""):
            return value
    return default


def write(name: str, value: str) -> None:
    """Write only the ASCII name (new launchers and child processes see it)."""
    os.environ[name] = str(value)


def clear(name: str) -> None:
    os.environ.pop(name, None)


def source(name: str) -> str:
    """Diagnostic helper: return the variable name actually used."""
    if os.environ.get(name) not in (None, ""):
        return name
    legacy = LEGACY_NAMES.get(name)
    if legacy and os.environ.get(legacy) not in (None, ""):
        return legacy
    return ""
