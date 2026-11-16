"""Legacy import compatibility; implementation is owned by official_api.

Keep old plugins working while application callers migrate to English names.
Removal criteria are recorded in docs/naming-migration-plan.md.
"""
from __future__ import annotations

import official_api as _official_api


_LEGACY_EXPORTS = {
    "MUJOCO版本要求": "MUJOCO_VERSION_REQUIREMENT",
    "已知可用版本": "KNOWN_GOOD_VERSIONS",
    "必需子模块": "REQUIRED_SUBMODULES",
    "必需消息符号": "REQUIRED_MESSAGE_SYMBOLS",
    "自检": "self_check",
    "_缺东西提示": "missing_dependency_hint",
    "_环境命令": "_environment_command",
    "_导入": "_load_required_modules",
    "_取": "_required_module",
    "_错误": "_import_error",
}
__all__ = [
    *_official_api.__all__, *_official_api.REQUIRED_SUBMODULES, "mujoco",
    *[name for name in _LEGACY_EXPORTS if not name.startswith("_")],
]


def __getattr__(name: str):
    return getattr(_official_api, _LEGACY_EXPORTS.get(name, name))


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_official_api)) | set(_LEGACY_EXPORTS))


if __name__ == "__main__":
    import runpy
    runpy.run_module("official_api", run_name="__main__")
