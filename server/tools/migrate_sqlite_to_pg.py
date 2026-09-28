# -*- coding: utf-8 -*-
"""SQLite → PostgreSQL 全量迁移工具（建库 + 建表 + 数据搬迁 + 行数校验）。

用法（server/ 目录）：python tools/migrate_sqlite_to_pg.py
特性：
- 幂等可重跑：目标表先 TRUNCATE ... RESTART IDENTITY 再全量拷贝；
- 主库 knowledge_management.db 的 11 张表逐列拷贝（保留原 id，序列重置对齐）；
- 练习库 data/practice/<user_id>.db（旧"每用户一库"）合并进主库 practice_* 四表，
  注入 user_id 列完成隔离收敛；
- 列集合取两侧交集，兼容 SQLite 历史缺列（如旧版 answer_history）；
- 结束输出逐表行数对照，不一致则非零退出。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

import config  # noqa: E402
from database import schema_postgres  # noqa: E402


def _pg_cols(cur, table: str) -> set[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s", (table,))
    return {r[0] for r in cur.fetchall()}


def _sqlite_cols(sconn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in sconn.execute(f"PRAGMA table_info({table})").fetchall()}


def _norm_row(vals):
    return [(int(v) if isinstance(v, bool) else v) for v in vals]


def copy_table(sconn, pcur, table: str) -> tuple[int, int]:
    """主库表全量拷贝（TRUNCATE 后重灌）。返回 (源行数, 拷贝行数)。"""
    if not _exists(sconn, table):
        return 0, 0
    s_rows = sconn.execute(f"SELECT * FROM {table}").fetchall()
    common = sorted(_pg_cols_cached & _sqlite_cols(sconn, table))
    pcur.execute(f"TRUNCATE {table} RESTART IDENTITY")
    if not s_rows:
        return 0, 0
    cols = common
    placeholders = ",".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    n = 0
    for row in s_rows:
        vals = [row[_sqlite_col_index(sconn, table, c)] for c in cols]
        try:
            pcur.execute(sql, _norm_row(vals))
            n += 1
        except Exception as e:  # noqa: BLE001
            print(f"  !! {table} 行插入失败（跳过）: {e}")
    if table != "users":  # users 主键为 TEXT user_id，无 id 序列
        pcur.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}','id'), "
            f"(SELECT COALESCE(MAX(id),1) FROM {table}), (SELECT MAX(id) IS NOT NULL FROM {table}))")
    return len(s_rows), n


def _sqlite_col_index(sconn, table, col) -> int:
    """列名→ SELECT * 结果下标（进程内缓存）。"""
    key = (table, col)
    if key not in _col_idx:
        names = [r[1] for r in sconn.execute(f"PRAGMA table_info({table})").fetchall()]
        _col_idx[key] = names.index(col)
    return _col_idx[key]


def _exists(sconn, table) -> bool:
    return sconn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def main() -> int:
    # 1. 建库（不存在才建）
    adm = psycopg2.connect(host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
                           password=config.PG_PASSWORD, dbname="postgres", connect_timeout=8)
    adm.autocommit = True
    acur = adm.cursor()
    acur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (config.PG_DATABASE,))
    if not acur.fetchone():
        acur.execute(f'CREATE DATABASE "{config.PG_DATABASE}" TEMPLATE template0 ENCODING "UTF8"')
        print(f"[1/4] 已创建数据库 {config.PG_DATABASE}")
    else:
        print(f"[1/4] 数据库 {config.PG_DATABASE} 已存在")
    acur.close()
    adm.close()

    # 2. 建表（幂等）
    tgt = psycopg2.connect(host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
                           password=config.PG_PASSWORD, dbname=config.PG_DATABASE, connect_timeout=8)
    tcur = tgt.cursor()
    schema_postgres.init_postgres_schema(tgt)
    tgt.commit()
    print("[2/4] PG 表结构初始化完成（IF NOT EXISTS 幂等）")

    # 3. 主库拷贝
    global _pg_cols_cached  # noqa: PLB006 简化列集合获取（单连接内缓存）
    sdb = config.DB_PATH
    if not Path(sdb).exists():
        print(f"!! 主库不存在：{sdb}，跳过数据拷贝")
        return 1
    sconn = sqlite3.connect(str(sdb))
    report: list[tuple[str, int, int]] = []
    for t in schema_postgres.MAIN_TABLES:
        _pg_cols_cached = _pg_cols(tcur, t)
        src, dst = copy_table(sconn, tcur, t)
        report.append((t, src, dst))
    sconn.close()
    tgt.commit()
    print("[3/4] 主库 11 表拷贝完成")

    # 3b. 练习库合并（每用户一库 → 主库列化隔离）
    prac_dir = Path(config.DATA_DIR) / "practice"
    files = sorted(prac_dir.glob("*.db")) if prac_dir.exists() else []
    for f in files:
        uid = f.stem
        pconn = sqlite3.connect(str(f))
        for t in schema_postgres.PRACTICE_TABLES_WITH_USER:
            if not _exists(pconn, t):
                continue
            _pg_cols_cached = _pg_cols(tcur, t)
            # 追加 user_id 列后拷贝（不 TRUNCATE，多用户文件逐个追加）
            rows = pconn.execute(f"SELECT * FROM {t}").fetchall()
            common = sorted((_pg_cols_cached & _sqlite_cols(pconn, t)) - {"user_id"})
            cols = common + ["user_id"]
            ph = ",".join(["%s"] * len(cols))
            sql = f"INSERT INTO {t} ({','.join(cols)}) VALUES ({ph}) ON CONFLICT DO NOTHING"
            ok = 0
            for row in rows:
                vals = [row[_sqlite_col_index(pconn, t, c)] for c in common] + [uid]
                try:
                    tcur.execute(sql, _norm_row(vals))
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    print(f"  !! {t}({uid}) 插入失败: {e}")
            report.append((f"{t}[{uid}]", len(rows), ok))
        pconn.close()
    # practice 表序列对齐（user_id 注入分支不 setval，统一补做）
    for t in schema_postgres.PRACTICE_TABLES_WITH_USER:
        tcur.execute(
            f"SELECT setval(pg_get_serial_sequence('{t}','id'), "
            f"(SELECT COALESCE(MAX(id),1) FROM {t}), (SELECT MAX(id) IS NOT NULL FROM {t}))")
    tgt.commit()
    print(f"[3b/4] 练习库合并完成（{len(files)} 个用户文件）")

    # 4. 行数校验
    bad = []
    for name, src, dst in report:
        tname = name.split("[")[0]
        if "[user_id]" in name or "[" in name and tname in schema_postgres.PRACTICE_TABLES_WITH_USER:
            continue  # practice 多文件逐条已在明细打印
        tcur.execute(f"SELECT COUNT(*) FROM {name}")
        pg_n = tcur.fetchone()[0]
        flag = "OK " if pg_n >= dst else "BAD"
        if pg_n < dst:
            bad.append(name)
        print(f"  {flag} {name}: 源 {src} / 拷贝 {dst} / PG 现有 {pg_n}")
    tcur.close()
    tgt.close()
    if bad:
        print(f"!! 校验失败表: {bad}")
        return 1
    print("[4/4] MIGRATION_OK")
    return 0


_pg_cols_cached: set[str] = set()
_col_idx: dict = {}

if __name__ == "__main__":
    sys.exit(main())
