"""English public API for offline model-parameter identification."""
from __future__ import annotations

import 参数辨识 as _legacy


ParameterDefinition = _legacy.参数定义
CollectedData = _legacy.采集数据
IdentificationResult = _legacy.辨识结果
default_excitation = _legacy.默认激励
collect_data = _legacy.采数据
identify = _legacy.辨识
write_parameter = _legacy._写参数


def __getattr__(name: str):
    return getattr(_legacy, name)


__all__ = [
    "ParameterDefinition", "CollectedData", "IdentificationResult",
    "default_excitation", "collect_data", "identify", "write_parameter",
]
