"""Legacy naming compatibility; new code imports observation_core."""
from __future__ import annotations

from functools import wraps
import observation_core as _implementation

_ALIASES = {'发送函数': 'send', '包根': 'package_root', '_发送': '_send', '_包根': '_package_root', '_线程': '_thread', '_上次': '_last_report', '收命令': 'receive_command', '命令': 'command', '动作': 'action', '项': 'items', '说明': 'description', '时间': 'time', '耗时': 'elapsed_time', '路径': 'path', '出': 'output', '文件': 'file', '状态': 'state', '参数': 'parameters', '插件': 'plugins', '发现': 'discovered', '字节': 'bytes', '清单': 'manifest', '环形缓冲': 'SignalBuffer', '保留秒': 'retention_seconds', '_点': '_points', '记': 'record', '取': 'get_values', '最近秒': 'recent_seconds', '截止': 'cutoff', '跨度秒': 'span_seconds', '点数': 'point_count', '告警': 'Alert', '类型': 'kind', '严重度': 'severity', '信号': 'signal', '开始秒': 'start_seconds', '结束秒': 'end_seconds', '证据': 'evidence', '建议': 'recommendation', '曲线': 'curve', '曲线t': 'curve_times', '最后见': 'last_seen', '告警消息': 'AlertSnapshot', '活动': 'active', '已检出': 'detected_count', '阈值': 'Threshold', '振荡振幅': 'oscillation_amplitude', '超差均值': 'tracking_error_mean', '发散倍数': 'divergence_ratio', '判定们': 'detectors', '阈值表': 'THRESHOLDS', '取阈值': 'get_threshold', '关键词': 'keyword', '阈': 'threshold', '最短窗口秒': 'MIN_WINDOW_SECONDS', '最少样本数': 'MIN_SAMPLE_COUNT', '振荡最少过零': 'MIN_OSCILLATION_CROSSINGS', '超差持续秒': 'TRACKING_ERROR_DURATION_SECONDS', '告警留存秒': 'ALERT_RETENTION_SECONDS', '_均值': '_mean', '_峰半振幅': '_half_peak_to_peak', '判振荡': 'detect_oscillation', '数': 'count', '均': 'mean', '去均值': 'centered', '过零': 'crossings', '上次符号': 'previous_sign', '符': 'sign', '跨度': 'span', '频率': 'frequency', '振幅': 'amplitude', '三分': 'third', '前幅': 'initial_amplitude', '后幅': 'final_amplitude', '判发散': 'detect_divergence', '箱数': 'bin_count', '箱长': 'bin_size', '包络': 'envelope', '块': 'chunk', '涨': 'growth', '单调': 'monotonic_count', '判超差': 'detect_tracking_error', '判饱和': 'detect_saturation', '有': 'saturated', '占比': 'fraction', '最多': 'maximum', '判定器们': 'DETECTORS', '判定间隔': 'evaluation_interval', '_缓冲': '_buffers', '_保留秒': '_retention_seconds', '_判定间隔': '_evaluation_interval', '_下次': '_next_evaluation', '_活动': '_active', '_上次仿真时间': '_last_simulation_time', '已判定次数': 'evaluation_count', '已发出': 'published_count', '仿真时间': 'simulation_time', '数值': 'values', '墙钟': 'wall_clock', '缓冲': 'buffer', '函数': 'detector', '果': 'result', '旧': 'previous', '视窗': 'window', '截': 'window_start', '索引': 'indices', '长': 'sample_size', '新': 'new_alert', '死了': 'expired', '_发布': '_publish', '表': 'table', '活动告警': 'active_alerts', '重置计数': 'reset_count'}
_KEYWORDS = {'发送函数': 'send', '包根': 'package_root', '_发送': '_send', '_包根': '_package_root', '_线程': '_thread', '_上次': '_last_report', '收命令': 'receive_command', '命令': 'command', '动作': 'action', '项': 'items', '说明': 'description', '时间': 'time', '耗时': 'elapsed_time', '路径': 'path', '出': 'output', '文件': 'file', '状态': 'state', '参数': 'parameters', '插件': 'plugins', '发现': 'discovered', '字节': 'bytes', '清单': 'manifest', '环形缓冲': 'SignalBuffer', '保留秒': 'retention_seconds', '_点': '_points', '记': 'record', '取': 'get_values', '最近秒': 'recent_seconds', '截止': 'cutoff', '跨度秒': 'span_seconds', '点数': 'point_count', '告警': 'Alert', '类型': 'kind', '严重度': 'severity', '信号': 'signal', '开始秒': 'start_seconds', '结束秒': 'end_seconds', '证据': 'evidence', '建议': 'recommendation', '曲线': 'curve', '曲线t': 'curve_times', '最后见': 'last_seen', '告警消息': 'AlertSnapshot', '活动': 'active', '已检出': 'detected_count', '阈值': 'Threshold', '振荡振幅': 'oscillation_amplitude', '超差均值': 'tracking_error_mean', '发散倍数': 'divergence_ratio', '判定们': 'detectors', '阈值表': 'THRESHOLDS', '取阈值': 'get_threshold', '关键词': 'keyword', '阈': 'threshold', '最短窗口秒': 'MIN_WINDOW_SECONDS', '最少样本数': 'MIN_SAMPLE_COUNT', '振荡最少过零': 'MIN_OSCILLATION_CROSSINGS', '超差持续秒': 'TRACKING_ERROR_DURATION_SECONDS', '告警留存秒': 'ALERT_RETENTION_SECONDS', '_均值': '_mean', '_峰半振幅': '_half_peak_to_peak', '判振荡': 'detect_oscillation', '数': 'count', '均': 'mean', '去均值': 'centered', '过零': 'crossings', '上次符号': 'previous_sign', '符': 'sign', '跨度': 'span', '频率': 'frequency', '振幅': 'amplitude', '三分': 'third', '前幅': 'initial_amplitude', '后幅': 'final_amplitude', '判发散': 'detect_divergence', '箱数': 'bin_count', '箱长': 'bin_size', '包络': 'envelope', '块': 'chunk', '涨': 'growth', '单调': 'monotonic_count', '判超差': 'detect_tracking_error', '判饱和': 'detect_saturation', '有': 'saturated', '占比': 'fraction', '最多': 'maximum', '判定器们': 'DETECTORS', '判定间隔': 'evaluation_interval', '_缓冲': '_buffers', '_保留秒': '_retention_seconds', '_判定间隔': '_evaluation_interval', '_下次': '_next_evaluation', '_活动': '_active', '_上次仿真时间': '_last_simulation_time', '已判定次数': 'evaluation_count', '已发出': 'published_count', '仿真时间': 'simulation_time', '数值': 'values', '墙钟': 'wall_clock', '缓冲': 'buffer', '函数': 'detector', '果': 'result', '旧': 'previous', '视窗': 'window', '截': 'window_start', '索引': 'indices', '长': 'sample_size', '新': 'new_alert', '死了': 'expired', '_发布': '_publish', '表': 'table', '活动告警': 'active_alerts', '重置计数': 'reset_count'}

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
    runpy.run_module("observation_core", run_name="__main__")
