"""Legacy naming compatibility; new code imports parameter_identification."""
from __future__ import annotations

from functools import wraps
import parameter_identification as _implementation

_ALIASES = {'参数定义': 'ParameterDefinition', '采集数据': 'CollectedData', '辨识结果': 'IdentificationResult', '默认激励': 'default_excitation', '采数据': 'collect_data', '_造模型': '_make_model', '_写参数': 'write_parameter', '辨识': 'identify'}
_KEYWORDS = {'参数定义': 'ParameterDefinition', '名称': 'name', '目标': 'target', '初值': 'initial', '下界': 'lower', '上界': 'upper', '真值': 'reference', '单位': 'unit', '采集数据': 'CollectedData', '时间': 'time', '模型路径': 'model_path', '备注': 'note', '步数': 'step_count', '辨识结果': 'IdentificationResult', '参数': 'parameters', '估计值': 'estimates', '残差历史': 'residual_history', '往返次数': 'rollout_count', '耗时': 'elapsed_time', '表格': 'rows', '误': 'error', '对比表': 'comparison_table', '行': 'lines', '名': 'name', '初': 'initial', '估': 'estimate', '真': 'reference', '真s': 'reference_text', '误s': 'error_text', '默认激励': 'default_excitation', '幅度': 'amplitude', '激励': 'excitation', '采数据': 'collect_data', '时长': 'duration', '质量覆盖': 'mass_overrides', '连杆': 'body', '质量': 'mass', '模型': 'model', '期望': 'desired', '力矩': 'torque', '_造模型': '_make_model', '值': 'value', '参数们': 'parameter_definitions', '_写参数': 'write_parameter', '体名': 'body_name', '字段': 'field_name', '序': 'index', '辨识': 'identify', '数据': 'data', '抽稀': 'stride', '最大轮数': 'max_iterations', '打印': 'print_result', '参数名': 'parameter_name', '下': 'lower_bounds', '上': 'upper_bounds', '下标': 'indices', '合计': 'total', '自由度': 'dof', '残差': 'residual', '值向量': 'values', '偏差': 'offset', '代价': 'cost', '历史': 'history', '轮': 'iteration', '步': 'step', '实际步': 'actual_step', '增益': 'gain', '改进': 'improvement', '尝试': 'attempt', 'r新': 'new_residual', '代价新': 'new_cost'}

def __getattr__(name):
    value = getattr(_implementation, _ALIASES.get(name, name))
    if callable(value) and not isinstance(value, type) and _KEYWORDS:
        @wraps(value)
        def call(*args, **kwargs):
            mapped = {}
            for key, item in kwargs.items():
                translated = _KEYWORDS.get(key, key)
                if translated in mapped:
                    raise TypeError(f"Multiple values for argument {translated!r}")
                mapped[translated] = item
            return value(*args, **mapped)
        return call
    return value

def __dir__():
    return sorted(set(globals()) | set(dir(_implementation)) | set(_ALIASES))

if __name__ == "__main__":
    import runpy
    runpy.run_module("parameter_identification", run_name="__main__")
