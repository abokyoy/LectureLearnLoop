---
kind: error_handling
name: Flask 服务端的分层异常与静默降级策略
category: error_handling
scope:
    - '**'
source_files:
    - server/database/db_adapter.py
    - server/credits_service.py
    - server/routes_knowledge.py
    - server/app.py
---

## 1. 总体方案

LectureLearnLoop 的 Flask 服务端（`server/`）没有使用统一的错误中间件或全局 `@app.errorhandler`，而是采用**「DAO 层归一 + 业务层显式 raise + 路由层 `_err()` 返回」**的分层模式，配合大量 `except Exception: # noqa: BLE001` 实现**静默降级**。

- 数据库访问：通过 `database/db_adapter.py` 将 sqlite3 / psycopg2 的具体异常统一包装为自定义异常。
- 积分计费：在 `credits_service.py` 中定义领域异常 `InsufficientCreditsError`。
- 路由响应：各蓝图用本地 `_ok()` / `_err()` 辅助函数返回 `{success, data|error}` 格式，与旧 `app_flask.py` 前端约定保持一致。
- 全局错误处理：**不存在** `@app.errorhandler(Exception)`，未捕获异常直接走 Flask 默认 500 行为；调试日志通道 `/api/debug/log` 刻意 `try/except Exception` 后返回 `200 {success:false}`。

## 2. 关键文件与类型

### 数据库异常层次（`server/database/db_adapter.py`）
```python
class DatabaseError(Exception): ...
class IntegrityError(DatabaseError): ...
class OperationalError(DatabaseError): ...
```
所有底层异常在 `CursorWrapper._guard()` 中统一转换：
- `sqlite3.IntegrityError` → `IntegrityError`
- `sqlite3.OperationalError` → `OperationalError`
- psycopg2 的 `IntegrityError` / `OperationalError` / `InterfaceError` → 同上
- 其他异常 → `DatabaseError`

### 积分领域异常（`server/credits_service.py`）
```python
class InsufficientCreditsError(Exception):
    def __init__(self, balance: float):
        super().__init__("积分不足，请充值后继续使用")
        self.balance = balance
```
用于在余额不足时拦截系统大模型调用，由上层路由转换为 JSON 错误。

### 路由响应助手（以 `server/routes_knowledge.py` 为代表）
```python
def _ok(data=None, **extra):
    return jsonify({"success": True, "data": data})

def _err(message: str, code: int = 500):
    return jsonify({"success": False, "error": str(message)}), code
```
所有业务端点遵循注释约定："全部端点挂 @require_auth，响应统一 {success: bool, data|error}"。

### 应用入口（`server/app.py`）
- 无 `@app.errorhandler`。
- `/api/debug/log` 是唯一的“静默失败”端点：捕获所有异常并返回 `200 {success: False}`，确保前端上报不会拖垮服务。
- 健康检查 `/api/health` 返回固定结构。

## 3. 架构与约定

| 层级 | 职责 | 约定 |
|---|---|---|
| DAO (`db_adapter.py`) | 屏蔽 sqlite/pg 差异、连接池管理、SQL 方言翻译 | 只抛出 `DatabaseError` 及其子类，不暴露底层驱动异常 |
| 业务服务 (`credits_service.py` 等) | 封装领域规则 | 抛出自定义领域异常（如 `InsufficientCreditsError`），内部 DB 调用一律 `try/except Exception` 回退默认值 |
| 路由层 (`routes_*.py`) | HTTP 契约 | 用 `_ok` / `_err` 构造响应；参数校验失败返回 400；未知异常记录日志后返回 500 |
| 应用入口 (`app.py`) | 装配蓝图、CORS、配置 | 不注册全局异常处理器，依赖 Flask 默认 500 |

## 4. 开发者应遵守的规则

1. **不要直接抛出 sqlite3 / psycopg2 异常**：所有数据库访问必须经过 `db_adapter.get_connection()`，由 `CursorWrapper._guard` 统一归一。
2. **新增领域错误时定义专用 Exception 子类**：参考 `InsufficientCreditsError`，携带必要上下文字段（如 `balance`），便于上层区分处理。
3. **路由层统一使用 `_ok` / `_err`**：保持 `{success, data|error}` 响应格式，避免前端解析分支爆炸。
4. **参数校验失败返回 400**：如 `subject_name 不能为空`；业务逻辑失败返回 500 并在日志中记录。
5. **对非关键路径使用 `except Exception: # noqa: BLE001` 做静默降级**：例如 config 读取失败回退 `.env`、审计流水失败不阻断主调用、表不存在时返回默认值——注释需说明为何可以吞掉异常。
6. **不要在路由层 try/except 所有异常后返回 200**：只有像 `/api/debug/log` 这种“可完全忽略”的通道才这样做；普通 API 应保留 5xx 状态码以便监控告警。
7. **不使用 `raise ... from None` 或 `pass` 掩盖异常**：当前代码库几乎不用 `from None`，所有 `except Exception` 都附带 `# noqa: BLE001` 和中文注释解释原因，这是审查时的重点。
8. **不引入新的全局错误中间件**：现有设计有意保持轻量，新增统一错误处理应先评估是否值得替换现有的 `_err()` + 日志记录模式。