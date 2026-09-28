"""
统一调试日志模块（后端）
========================
所有模块的调试/测试信息都写入同一个文件：logs/debug_trace.jsonl

设计原则：
- 单例：整个进程只有一个 DebugLogger 实例
- 线程安全：使用 threading.Lock 保护写入
- JSON Lines 格式：每行一条 JSON，方便 grep / tail 分析
- 来源标识：source 字段区分 backend / frontend / mobile

使用示例（后端）：
    from logger_module import debug_logger
    debug_logger.log('api', 'extract_knowledge_start', data={'text_len': len(text)})
    debug_logger.log('llm', 'call_success', status='success', data={'provider': 'Qwen', 'duration_ms': 1234})

前端日志通过 POST /api/debug/log 端点转发，最终也写入同一文件：
    debug_logger.log_frontend(module, action, status, data)
"""

from __future__ import annotations  # 必须最先导入，兼容 Python 3.9 的联合类型注解

import json
import os
import threading
from datetime import datetime, timezone


# 日志文件相对于项目根目录的路径
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'debug_trace.jsonl')


class DebugLogger:
    """统一调试日志写入器，线程安全单例。"""

    _instance: 'DebugLogger | None' = None
    _lock = threading.Lock()

    def __new__(cls) -> 'DebugLogger':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._write_lock = threading.Lock()
        os.makedirs(LOG_DIR, exist_ok=True)
        self._initialized = True

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def log(
        self,
        module: str,
        action: str,
        status: str = 'info',
        data: dict | None = None,
        source: str = 'backend',
    ) -> None:
        """
        写入一条调试日志。

        参数：
            module  : 功能模块名，如 'api' / 'knowledge' / 'practice' / 'llm' / 'db'
            action  : 动作名，如 'extract_start' / 'call_success' / 'db_write'
            status  : 'info' | 'success' | 'error' | 'warning' | 'debug'
            data    : 任意可序列化的附加数据字典
            source  : 'backend' | 'frontend' | 'mobile'
        """
        entry = {
            'timestamp': datetime.now(timezone.utc).astimezone().isoformat(),
            'source': source,
            'module': module,
            'action': action,
            'status': status,
            'data': data or {},
        }
        self._write(entry)

    def log_error(self, module: str, action: str, error: Exception | str, data: dict | None = None) -> None:
        """快捷记录错误日志。"""
        err_data = dict(data or {})
        err_data['error'] = str(error)
        self.log(module, action, status='error', data=err_data)

    def log_success(self, module: str, action: str, data: dict | None = None) -> None:
        """快捷记录成功日志。"""
        self.log(module, action, status='success', data=data)

    def log_frontend(
        self,
        module: str,
        action: str,
        status: str = 'info',
        data: dict | None = None,
        source: str = 'frontend',
    ) -> None:
        """专用于接收客户端上报日志（默认 source=frontend，移动端传 mobile）。"""
        self.log(module, action, status=status, data=data, source=source)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _write(self, entry: dict) -> None:
        try:
            line = json.dumps(entry, ensure_ascii=False, default=str)
            with self._write_lock:
                with open(LOG_FILE, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
        except Exception as e:
            # 调试日志本身不能抛出异常影响业务，降级到 stderr
            import sys
            print(f'[DebugLogger] 写入失败: {e}', file=sys.stderr)

    # ------------------------------------------------------------------
    # 辅助：读取最近 N 条日志（Agent 验证时调用）
    # ------------------------------------------------------------------

    @staticmethod
    def read_recent(n: int = 20, source_filter: str | None = None) -> list[dict]:
        """
        读取最近 n 条日志（供 Agent 测试验证使用）。

        参数：
            n            : 返回条数
            source_filter: 可选，只返回指定 source 的日志，如 'frontend'
        """
        if not os.path.exists(LOG_FILE):
            return []
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            # 取最后 n 条（从尾部截取）
            tail = lines[-n * 3:]  # 多取一些再过滤
            entries: list[dict] = []
            for line in reversed(tail):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if source_filter and entry.get('source') != source_filter:
                        continue
                    entries.append(entry)
                    if len(entries) >= n:
                        break
                except json.JSONDecodeError:
                    continue
            entries.reverse()  # 恢复时间顺序
            return entries
        except Exception:
            return []


# 模块级单例，供业务代码直接 import 使用
debug_logger = DebugLogger()
