# 2026-09-28 SQLite → PostgreSQL 全量迁移改造

> 任务来源：用户指令——从另一项目部署文档提取 PG 服务器凭据，对本服务端做 PostgreSQL 改造：统一连接适配层（含连接池）、DAO 屏蔽方言、全局配置开关、存量数据全量迁移，最终废弃 SQLite。全过程用户不参与。

## 一、环境事实（凭据仅存 `server/.env`，本文档不重复密码）

| 项 | 值 |
|---|---|
| PG 服务器 | 本机 `127.0.0.1:5432`，PostgreSQL 18.1，`max_connections=100` |
| 管理员账号 | `postgres`（密码见 `server/.env → PG_PASSWORD`） |
| 本项目数据库 | `lecturelearnloop`（本次新建，UTF8） |
| 驱动 | psycopg2-binary 2.9.12 |

## 二、改造清单与落点（全部完成）

### 1. 统一数据库适配层（新建 `server/database/db_adapter.py`）
全项目**唯一数据库出口**，DAO 层屏蔽差异的具体承担者：
- **连接池**：PG 用 `psycopg2.ThreadedConnectionPool(min=2, max=20)` 懒建单例+双检锁；取用前 `SELECT 1` 存活探测，坏连接销毁重建；`application_name=lecturelearnloop-server` 便于服务器侧观测。
- **方言翻译**（引号感知扫描器 `_translate_sql`）：`?`→`%s`、字面 `%`→`%%`、`CURRENT_TIMESTAMP`→UTC `to_char` 表达式（与 SQLite 存量时间格式逐字节一致）、`INSERT OR IGNORE`→`ON CONFLICT DO NOTHING`；字符串字面量/双引号标识符/`--` 注释内不误替换。
- **lastrowid 回填**：PG 分支对 `INSERT INTO <表>` 自动追加 `RETURNING id`（`users` 表主键为 TEXT，例外不回填）。
- **异常归一**：两后端完整性/操作类错误统一为 `db_adapter.IntegrityError / OperationalError / DatabaseError`。**关键教训**：psycopg2 的具体子类（如 `UniqueViolation`）类名不含 "Integrity" 字样，必须按 `isinstance(e, psycopg2.IntegrityError)` 类层级判定，类名字符串匹配只是兜底——此 bug 由 r10 回归暴露（重复学科 500），已修复。
- **归还语义**：`close()` 与 `with conn:` 退出均归还池连接（先回滚残余事务），`__del__` 兜底，`_released` 幂等——兼容旧代码"with 后不 close"写法，杜绝池泄漏。
- sqlite 分支同样经包装（异常归一行为统一），保留完整回退能力。

### 2. PG 表结构（新建 `server/database/schema_postgres.py`）
16 张表（users + 主库 11 + practice 4）。设计决策：
- 时间列统一 `TEXT` + UTC `to_char` 默认值（兼容存量混合格式，JSON 序列化行为不变）；
- **不建 FOREIGN KEY**（SQLite 从未启用外键，业务不依赖；建 FK 会阻断含孤儿行的存量迁移）；UNIQUE 约束完整保留；
- `practice_*` 四表新增 `user_id` 列 + `UNIQUE(user_id, practice_id)`，把旧"每用户一个 sqlite 文件"的隔离方式收敛为主库列化隔离。

### 3. 全局配置（`server/config.py` + `server/.env`）
- `DB_BACKEND`（`postgres` | `sqlite`）为网站全局后端开关，当前 `.env` 已置 `postgres`；
- `PG_HOST/PORT/DATABASE/USER/PASSWORD/PG_POOL_MIN(2)/PG_POOL_MAX(20)` 全部 env 化，凭据只落 `.env`；
- `load_config()` 暴露 `db_backend` 并列入保护键（设置页不可覆盖）。
- **回退方法**：把 `server/.env` 中 `DB_BACKEND` 改为 `sqlite` 并重启服务即可，业务代码零改动。

### 4. 业务层收敛（改造点全清单）
| 模块 | 原状 | 现状 |
|---|---|---|
| `knowledge_management.py`（85 处 SQL） | 裸 `sqlite3.connect` | `DatabaseManager` 统一走 `db_adapter.get_connection()`；`init_database` PG 分支建表；`IntegrityError` 归一捕获；业务 SQL 零改动（`?`/lastrowid 由适配层翻译） |
| `auth.py`（5 处） | `sqlite3` | 经同一适配层（`with _get_db() as conn:` 模式由归还语义兜住） |
| `services/practice_service.py`（15 处） | 每用户一个 db 文件 | 整体重写：所有方法首参 `user_id`，查询 `WHERE user_id = ?`，共享单例连接 |
| `routes_bridge.py`（19 处+practice 端点） | 每请求建 PracticeService | `_practice_service()` 共享单例，5 个端点传 `g.user_id` |
| `routes_knowledge.py`（2 处）/`app.py` | 零星 sqlite3 | 去除直接 sqlite3 依赖 |
| `dal/practice_dao.py` | 死代码（无引用且含方言雷区） | **已删除** |

### 5. 存量迁移（新建 `server/tools/migrate_sqlite_to_pg.py`，已执行）
建库→幂等建表→主库 11 表 `TRUNCATE RESTART IDENTITY` 后逐列拷贝（列集合取两侧交集、保留原 id、bool→int、`setval` 序列对齐）→练习库按文件注入 user_id 合并→逐表行数校验。**迁移结果**：users 117 / user_subjects 34 / knowledge_points 60 / practice_records 29 / error_questions 23 / notes 12 / 其余合计 39，全部 `OK`，`MIGRATION_OK`。SQLite 源文件保留未动（回退保险）。

## 三、验证证据（全部在 PG 后端下取得）

| 验证 | 结果 | 证据文件 |
|---|---|---|
| 迁移行数校验 | 11/11 表一致，MIGRATION_OK | `server/logs/migrate_pg.txt` |
| pytest 全量 | **49 passed**（含 PG 下连接/lastrowid/跨用户隔离断言） | 终端输出 |
| r9 功能验收（HTTP） | **12 PASS / 0 FAIL** | `server/logs/r9_pg_run.txt` |
| r10 提取链路（真实 DeepSeek） | **8 PASS / 0 FAIL**（修复异常归一后） | `server/logs/r10_pg_run2.txt` |
| 并发压测（新增 `tests/pg_concurrency_check.py`） | **13 PASS / 0 FAIL**：12 线程×注册/建学科/写 6 知识点/回读，108 次操作数据完整无串扰 | `server/logs/pg_conc_run2.txt` |
| PG 侧直查（`tests/pg_data_verify.py`） | users 172、knowledge_points 223、pgload 压测账号 24、池内活动连接=2（min 热备生效） | `server/logs/pg_verify.txt` |

## 四、遗留与说明
- 测试账号（`qa_extract_*`、`pgload_*`、`r9_*` 等）与其数据保留在 PG 中，可按需 SQL 清理；
- `data/knowledge_management.db` 与 `data/practice/*.db` 作为回退保险保留，确认稳定后可归档删除；
- 新增知识点重复学科等 IntegrityError 路径今后两后端行为一致（返回 False 而非 500）。
