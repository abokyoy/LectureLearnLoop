---
kind: logging_system
name: 统一调试日志与LLM调用追踪体系
category: logging_system
scope:
    - '**'
source_files:
    - server/logger_module.py
    - server/static/js/unified_logger.js
    - server/app.py
    - server/llm_logger.py
    - server/llm_call_logger.py
---

## 1. 总体方案

本仓库没有引入第三方日志框架（如 `logging`、`loguru`、`structlog`），而是自建了 **三层日志子系统**：

| 层级 | 文件 | 用途 | 输出格式 |
|---|---|---|---|
| 统一调试日志 | `server/logger_module.py` + `server/static/js/unified_logger.js` | 后端/前端/移动端跨端调试，统一写入 `logs/debug_trace.jsonl` | JSON Lines |
| LLM API 调用日志 | `server/llm_logger.py` | 记录 Gemini/Ollama/Qwen/DeepSeek 的输入输出摘要 | 文本 `.log` + `_detailed.jsonl` |
| LLM 调用统计日志 | `server/llm_call_logger.py` | 按 provider/model 维度统计耗时、首字节时间、成功率 | 每日 `logs/llm_calls_YYYYMMDD.jsonl` |

Flask 入口 `app.py` 暴露两个调试通道：
- `POST /api/debug/log` — 接收前端批量上报，落盘到 `debug_trace.jsonl`
- `GET /api/debug/recent` — 读取最近 N 条（需认证）

## 2. 关键文件

- `server/logger_module.py` — 后端统一调试日志单例 `DebugLogger`，线程安全，字段固定为 `{timestamp, source, module, action, status, data}`。
- `server/static/js/unified_logger.js` — 前端 `UnifiedLogger` 单例，缓冲 10 条或每 5s flush，页面卸载前用 `sendBeacon` 强制上报。
- `server/app.py` — 装配 Flask app，注册 `/api/debug/log` 和 `/api/debug/recent`。
- `server/llm_logger.py` — 基于 Python `logging` 模块，按 provider 提供 `log_gemini_call` / `log_ollama_call` / `log_qwen_call` / `log_deepseek_call` 便捷函数。
- `server/llm_call_logger.py` — 基于 `dataclass` 的 `LLMCallRecord`，维护内存中最多 1000 条记录，支持 `start_call` / `record_first_byte` / `end_call` 三段式 API 与统计查询。

## 3. 架构约定

### 3.1 统一调试日志字段规范

所有通过 `debug_logger.log(...)` 或前端 `UnifiedLogger.log(...)` 产生的条目必须包含以下字段：

```
timestamp: ISO8601（后端用 UTC+本地时区，前端用 Date.toISOString()）
source: 'backend' | 'frontend' | 'mobile'
module: 功能模块名，如 'api' / 'knowledge' / 'practice' / 'llm' / 'db'
action: 动作名，如 'extract_start' / 'call_success' / 'db_write'
status: 'info' | 'success' | 'error' | 'warning' | 'debug'
data: 任意可序列化字典
```

### 3.2 单例模式

- `DebugLogger` 使用双重检查锁实现进程内单例；`debug_logger` 是模块级全局实例。
- `LLMLogger` 通过 `get_llm_logger()` 获取全局实例。
- `LLMCallLogger` 同样使用类级 `_instance` + `threading.Lock` 的单例模式。

### 3.3 线程安全

`DebugLogger._write` 使用独立的 `_write_lock` 保护文件写入；`LLMCallLogger` 对内存 records 列表加锁。写入失败时一律降级到 stderr/console，**不抛出异常影响业务**。

### 3.4 前端日志上报策略

- 缓冲队列：最多 10 条，满则立即 flush。
- 定时 flush：每 5 秒一次。
- 静默失败：网络错误仅 `console.warn`，不影响页面逻辑。
- 页面卸载：通过 `beforeunload` + `navigator.sendBeacon` 强制发送剩余缓冲。

### 3.5 LLM 调用日志分层

- `llm_logger.py`：面向具体 provider 的便捷函数，同时写人类可读的 `.log` 和结构化 `_detailed.jsonl`。
- `llm_call_logger.py`：面向性能分析的时序记录，按天分文件 `llm_calls_YYYYMMDD.jsonl`，并提供 `get_statistics()` 聚合 success_rate、avg_duration、provider_stats、model_stats。

## 4. 开发者规则

1. **新增业务调试日志**：统一通过 `from logger_module import debug_logger; debug_logger.log(module, action, status='info', data={...})`，禁止直接 `print` 或 `logging.info`。
2. **前端调试日志**：通过 `window.UnifiedLogger.log(...)` 或快捷函数 `debugLog(...)` / `debugLogError(...)`，不要直接 `fetch('/api/debug/log')`。
3. **记录 LLM 调用**：优先使用 `llm_call_logger.start_call(...)` → `record_first_byte(call_id)` → `end_llm_call(call_id, ...)` 三段式 API，以便自动计算首字节时间和总耗时。
4. **记录 provider 级输入输出**：使用 `llm_logger.log_<provider>_call(...)` 便捷函数。
5. **status 枚举**：只允许 `info` / `success` / `error` / `warning` / `debug`，不得自定义字符串。
6. **source 字段**：后端代码传 `source='backend'`（默认），前端传 `source='frontend'`（默认），移动端传 `source='mobile'`。
7. **日志文件位置**：全部位于 `server/logs/`，新日志文件命名遵循已有模式（`*.jsonl`、`*_err.log`、`*_out.log`、`llm_calls_YYYYMMDD.jsonl`）。
8. **禁止在日志中写入敏感信息**：密码、token、用户隐私数据不应进入 `data` 字段。