"""Legacy naming compatibility; new code imports web_bridge."""
from __future__ import annotations

from functools import wraps
import web_bridge as _implementation

_ALIASES = {'转干净': 'make_json_safe', '打包': 'pack_frame', '待发布': 'PendingMessages', '服务端': 'Server', '启动': 'start', '投递': 'publish', '健康': 'health', '关闭': 'close', '取水龙头': 'get_faucet', '取命令': 'get_commands', '记派发': 'record_dispatch', '_契约字典': '_contract_dict', '水龙头': 'Faucet', '_浅转': '_shallow_values', '安装水龙头': 'install_faucet', '仪表盘页': 'dashboard_page', '默认端口': 'DEFAULT_PORT', '默认主机': 'DEFAULT_HOST', '广播间隔': 'BROADCAST_INTERVAL', '主题上限': 'TOPIC_LIMIT', '命令队列上限': 'COMMAND_QUEUE_LIMIT', '前端目录': 'FRONTEND_DIRECTORY', '_类型表': '_MIME_TYPES', '_单例': '_instance', '_龙头': '_faucet', '_仪表盘_HTML': '_DASHBOARD_HTML'}
_KEYWORDS = {'协议版本': 'PROTOCOL_VERSION', '默认端口': 'DEFAULT_PORT', '默认主机': 'DEFAULT_HOST', '广播间隔': 'BROADCAST_INTERVAL', '主题上限': 'TOPIC_LIMIT', '命令队列上限': 'COMMAND_QUEUE_LIMIT', '前端目录': 'FRONTEND_DIRECTORY', '_类型表': '_MIME_TYPES', '转干净': 'make_json_safe', '值': 'value', '_深度': '_depth', '打包': 'pack_frame', '主题': 'topic', '消息': 'message', '序号': 'sequence', '待发布': 'PendingMessages', '_锁': '_lock', '_表': '_table', '_版本': '_version', '投递': 'publish', '取走': 'take_updates', '已发': 'sent_versions', '出': 'output', '版本': 'version', '主题们': 'topics', '服务端': 'Server', '主机': 'host', '端口': 'port', '客户端数': 'client_count', '已广播': 'broadcast_count', '已发送字节': 'sent_bytes', '丢弃': 'dropped_count', '出错': 'error', '启用': 'enabled', '_线程': '_thread', '_循环': '_loop', '_停止': '_stop', '_客户端': '_clients', '_命令': '_commands', '_命令锁': '_command_lock', '已收命令': 'received_commands', '已派发命令': 'dispatched_commands', '拒收': 'rejected_commands', '最近拒收原因': 'last_rejection', '启动': 'start', '_跑': '_run', '关闭': 'close', '状态': 'status', '收命令': 'receive_command', '主题名': 'topic_name', '负载': 'payload', '通过': 'passed', '说明': 'description', '取命令': 'get_commands', '异常': 'exc', '主': 'main', '服务器': 'server', '_接入': '_accept', '_静态页': '_serve_http', '广播任务': 'broadcast_task', '_广播循环': '_broadcast_loop', '_等到停止': '_wait_for_stop', '连接': 'connection', '请求': 'request', '头们': 'headers', '是升级': 'is_upgrade', '路径': 'path', '体': 'body', '头': 'header', '_契约字典': '_contract_dict', '_读静态': '_read_static', '数据': 'data', '类型': 'mime_type', '仪表盘页': 'dashboard_page', '相对': 'relative', '目标': 'target', '原文': 'raw_text', '_收一帧': '_receive_frame', '_回执': '_receipt', '帧': 'frame', '请求号': 'request_id', '项': 'item', '文本': 'text', '死': 'disconnected', '_单例': '_instance', '_龙头': '_faucet', '健康': 'health', '取水龙头': 'get_faucet', '记派发': 'record_dispatch', '条数': 'count', '主题白名单': 'TOPIC_ALLOWLIST', '_契约异常': '_contract_error', '水龙头': 'Faucet', '下一个': 'next_handler', '放过': 'passed_count', '抄送': 'copied_count', '最近状态': 'latest_state', '表': 'table', '_浅转': '_shallow_values', '安装水龙头': 'install_faucet', '原': 'original', '龙头': 'faucet', '_仪表盘_HTML': '_DASHBOARD_HTML', '桥': 'bridge'}

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
    runpy.run_module("web_bridge", run_name="__main__")
