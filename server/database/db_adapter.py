# -*- coding: utf-8 -*-
"""统一数据库连接适配层（全项目唯一数据库出口，PostgreSQL 唯一后端）。

架构职责（DAO 层屏蔽底层差异）：
- PostgreSQL：psycopg2 ThreadedConnectionPool 连接池，支撑高并发访问；
- 方言屏蔽：业务层统一使用 `?` 占位符与 conn.execute / with conn: / close() 语义，
  由本模块翻译为 PG 语法，业务代码零方言感知；
- 异常归一：完整性/操作类错误统一转换为 IntegrityError / OperationalError；
- 连接归还：close() 与 with 块退出均把 PG 连接归还连接池。

约束：
- PG 凭据只从 server/.env 读取。
"""
from __future__ import annotations

import re
import threading

import config
import psycopg2
import psycopg2.extras  # noqa: F401

# ---------------------------------------------------------------- 统一异常
class DatabaseError(Exception):
    """数据库访问统一基类异常。"""


class IntegrityError(DatabaseError):
    """唯一约束/外键等完整性冲突（两后端归一）。"""


class OperationalError(DatabaseError):
    """连接、SQL 语法等操作性异常（两后端归一）。"""


# ---------------------------------------------------------------- 后端配置（PostgreSQL 唯一）
def get_backend() -> str:
    return "postgres"


def is_postgres() -> bool:
    return True


# ---------------------------------------------------------------- PG 连接池（懒建单例）
_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            import psycopg2
            from psycopg2 import pool as pg_pool
            _pool = pg_pool.ThreadedConnectionPool(
                config.PG_POOL_MIN, config.PG_POOL_MAX,
                host=config.PG_HOST, port=config.PG_PORT,
                user=config.PG_USER, password=config.PG_PASSWORD,
                database=config.PG_DATABASE, connect_timeout=8,
                application_name="lecturelearnloop-server",
            )
    return _pool


# ---------------------------------------------------------------- SQL 方言翻译
_RE_INSERT_TABLE = re.compile(r"^\s*INSERT\s+INTO\s+([\"\w]+)", re.IGNORECASE)
_RE_INSERT_OR_IGNORE = re.compile(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\s+", re.IGNORECASE)

# PG 下各表主键列（用于 RETURNING 回填 lastrowid；None=不回填）。
# 仅作为显式覆盖表；未登记的表由 _needs_returning 按实际表结构探测 id 列。
_PG_PK = {
    "users": None,  # user_id 为 TEXT 主键，代码不使用 lastrowid
}

# 探测结果缓存：表名 -> 回填主键列（"id"）或 None（无 id 列，如 TEXT 主键表）
_pk_probe_cache = {}


_CT_PG = "(to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))"


def _translate_sql(sql: str) -> str:
    """SQLite 风格 → PostgreSQL：? 占位符、% 转义、CURRENT_TIMESTAMP→UTC 文本（与
    SQLite TEXT 存储格式一致）、引号感知；INSERT OR IGNORE → ON CONFLICT DO NOTHING。"""
    out = []
    i, n = 0, len(sql)
    in_str = False
    while i < n:
        c = sql[i]
        if in_str:
            out.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":  # SQL 内转义 ''
                    out.append("'")
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if c == "'":
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == '"':  # 带引号标识符整体拷贝
            j = sql.find('"', i + 1)
            if j == -1:
                out.append(c)
                i += 1
            else:
                out.append(sql[i:j + 1])
                i = j + 1
            continue
        if sql.startswith("--", i):  # 行注释内不做替换
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(sql[i:j])
            i = j
            continue
        if sql.upper().startswith("CURRENT_TIMESTAMP", i) and (
                i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")) and not (
                i + 17 < n and (sql[i + 17].isalnum() or sql[i + 17] == "_")):
            out.append(_CT_PG)
            i += 17
            continue
        if c == "%":  # psycopg2 参数风格中字面 % 需转义
            out.append("%%")
            i += 1
            continue
        if c == "?":
            out.append("%s")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _adapt_insert(sql: str) -> str:
    """PG 方言：INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING。"""
    if _RE_INSERT_OR_IGNORE.match(sql):
        sql = _RE_INSERT_OR_IGNORE.sub("INSERT INTO ", sql)
        return sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


def _needs_returning(raw_conn, sql: str) -> str | None:
    """判断是否为需要回填 lastrowid 的 INSERT，返回主键列名或 None。

    旧实现对所有未登记表盲注 RETURNING id ——无 id 列的 TEXT 主键表（如
    system_config/user_credits）在 PG 下直接报「字段 id 不存在」，导致
    新代码冷启动建表事务整体回滚死循环。改为按表结构探测（进程级缓存），
    探测失败或未命中时保守不回填。"""
    m = _RE_INSERT_TABLE.match(sql)
    if not m or "RETURNING" in sql.upper():
        return None
    table = m.group(1).strip('"').lower()
    if table in _PG_PK:
        return _PG_PK[table]
    if table not in _pk_probe_cache:
        try:
            cur = raw_conn.cursor()
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = 'id' LIMIT 1", (table,))
            _pk_probe_cache[table] = "id" if cur.fetchone() else None
            cur.close()
        except Exception:  # noqa: BLE001 探测异常不阻断业务，保守不回填
            _pk_probe_cache[table] = None
    return _pk_probe_cache[table]


def _psycopg_integrity(e) -> bool:
    try:
        import psycopg2
    except ImportError:  # pragma: no cover
        return False
    return isinstance(e, psycopg2.IntegrityError)


def _psycopg_operational(e) -> bool:
    try:
        import psycopg2
    except ImportError:  # pragma: no cover
        return False
    return isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError))


# ---------------------------------------------------------------- 行对象（列名+下标双访问，对齐 sqlite3.Row 常用面）
class _Row(tuple):
    def __init__(self, _):
        self._keys = {}

    def __getitem__(self, k):
        if isinstance(k, str):
            return tuple.__getitem__(self, self._keys[k])
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._keys)


# ---------------------------------------------------------------- Cursor 包装
class CursorWrapper:
    def __init__(self, raw, conn):
        self._raw = raw
        self._conn = conn
        self._lastrowid = None

    # -- 异常归一（SQL 翻译由调用方完成一次，避免 % 二次转义）
    def _guard(self, fn, *args):
        try:
            return fn(*args)
        except (IntegrityError, OperationalError, DatabaseError):
            raise
        except Exception as e:  # psycopg2 异常先按类层级 isinstance 归一（子类名如
            # UniqueViolation 不含 Integrity 字样），再退化到类名匹配
            if _psycopg_integrity(e):
                raise IntegrityError(str(e)) from e
            if _psycopg_operational(e):
                raise OperationalError(str(e)) from e
            name = type(e).__name__
            if "Integrity" in name:
                raise IntegrityError(str(e)) from e
            if "Operational" in name or "Interface" in name:
                raise OperationalError(str(e)) from e
            raise DatabaseError(str(e)) from e

    def execute(self, sql, params=()):
        if params is None:
            params = ()
        if self._conn.backend == "postgres":
            sql = _translate_sql(_adapt_insert(sql))
            pk = _needs_returning(self._conn._raw, sql)
            if pk:
                sql = sql.rstrip().rstrip(";") + f" RETURNING {pk}"
            self._guard(self._raw.execute, sql, params)
            if pk:
                row = self._raw.fetchone()
                self._lastrowid = int(row[0]) if row else None
            return self
        self._guard(self._raw.execute, sql, params)
        return self

    def executemany(self, sql, seq):
        if self._conn.backend == "postgres":
            sql = _translate_sql(_adapt_insert(sql))
        self._guard(self._raw.executemany, sql, seq)
        return self

    # -- 结果读取
    def fetchone(self):
        r = self._raw.fetchone()
        return self._mk(r)

    def fetchall(self):
        return [self._mk(r) for r in self._raw.fetchall()]

    def fetchmany(self, size=None):
        rs = self._raw.fetchmany(size) if size else self._raw.fetchmany()
        return [self._mk(r) for r in rs]

    def _mk(self, row):
        if row is None or self._conn.backend != "postgres":
            return row
        m = _Row(row)
        desc = getattr(self._raw, "description", None)
        if desc:
            m._keys = {d[0]: i for i, d in enumerate(desc)}
        return m

    def __iter__(self):
        while True:
            r = self.fetchone()
            if r is None:
                return
            yield r

    # -- 属性透传
    @property
    def lastrowid(self):
        if self._conn.backend == "postgres":
            return self._lastrowid
        return self._raw.lastrowid

    @property
    def rowcount(self):
        return self._raw.rowcount

    @property
    def description(self):
        return self._raw.description

    def close(self):
        try:
            self._raw.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- Connection 包装
class ConnWrapper:
    """PostgreSQL 连接包装（模拟统一语义接口）。

    - 内部持有池连接，close()/with 退出 → 归还池（未提交自动回滚）。
    """

    def __init__(self, raw, backend, pool=None):
        self._raw = raw
        self.backend = backend
        self._pool = pool
        self._released = False
        self.row_factory = None  # 兼容旧代码赋值（PG 行默认支持列名访问）

    # 统一便捷接口
    def execute(self, sql, params=()):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, script: str):
        cur = self._raw.cursor()
        for stmt in filter(None, (s.strip() for s in script.split(";"))):
            cur.execute(stmt)
        cur.close()
        return self._raw.cursor()

    def cursor(self):
        return CursorWrapper(self._raw.cursor(), self)

    def commit(self):
        if not self._released:
            self._raw.commit()

    def rollback(self):
        if not self._released:
            self._raw.rollback()

    # with 语义对齐 sqlite3：退出不关闭 → 但池化场景必须归还，视为一次性使用
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._released:
            return False
        try:
            if exc_type is None:
                self._raw.commit()
            else:
                self._raw.rollback()
        finally:
            self._release()
        return False

    def close(self):
        if self._released:
            return
        try:
            # 未提交事务残余先回滚，保证归还的是干净连接
            self._raw.rollback()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._release()

    def _release(self):
        if self._released:
            return
        self._released = True
        if self.backend == "postgres" and self._pool is not None:
            try:
                self._pool.putconn(self._raw)
            except Exception:  # noqa: BLE001
                pass

    def __del__(self):
        # 兜底：调用方忘记 close 时防止池饥饿
        try:
            if not self._released and self.backend == "postgres":
                self.close()
        except Exception:  # noqa: BLE001
            pass


def _pg_acquire():
    pool = _get_pool()
    conn = pool.getconn()
    # 存活探测：处理 PG 服务端断连/空闲超时，坏连接丢弃重建
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
    except Exception:  # noqa: BLE001
        try:
            pool.closeconn(conn)
        except Exception:  # noqa: BLE001
            pass
        conn = pool.getconn()
    return pool, conn


def get_connection(db_path: str | None = None) -> ConnWrapper:
    """全项目唯一连接入口（PG 连接池）。db_path 参数保留兼容签名，实际忽略。"""
    pool, raw = _pg_acquire()
    return ConnWrapper(raw, "postgres", pool=pool)


def run_on_pg(sql_statements, params_list=None):
    """执行一组 DDL/SQL。用于建表初始化。"""
    conn = get_connection()
    try:
        cur = conn._raw.cursor()
        for i, sql in enumerate(sql_statements):
            cur.execute(sql, (params_list[i] if params_list else ()))
        cur.close()
        conn.commit()
    finally:
        conn.close()
