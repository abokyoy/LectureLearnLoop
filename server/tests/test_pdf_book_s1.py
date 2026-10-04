# -*- coding: utf-8 -*-
"""大PDF分段 S1 基线改造验收测试（2026-10-04）。

覆盖：
- schema_import 新列（parent_task_id/seg_from/seg_to）建表 + 幂等 ALTER 迁移（连跑两次不报错）；
- create_task 支持新列写入并可回读；
- update_task 允许列扩展到 seg_* 与 parent_task_id；
- recover_tasks_on_startup 清理保护：pdf_book 主任务、有 error 的失败行不被 30 天清理删除。

运行（server/ 目录）：python -m pytest tests/test_pdf_book_s1.py -v
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="module")
def app():
    from app import create_app
    a = create_app()
    a.config["TESTING"] = True
    return a


def _conn(app):
    return app.config["DB_CONN_FACTORY"]


def test_new_columns_exist_and_migration_idempotent(app):
    """建表含新列，且 init_import_tables 可重复执行（幂等 ALTER 迁移）。"""
    from database.schema_import import init_import_tables
    cf = _conn(app)
    # 连跑两次不应抛异常（第二次 CREATE IF NOT EXISTS + ALTER 命中 duplicate 被吞）
    init_import_tables(cf)
    init_import_tables(cf)
    uid = "s1_cols_" + uuid.uuid4().hex[:6]
    with cf() as conn:
        cur = conn.execute(
            "INSERT INTO import_tasks (task_id,user_id,file_name,folder_path,kind,status,"
            "progress_json,result_md,result_pdf,remote_job_id,error,parent_task_id,seg_from,seg_to,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex[:16], uid, "x", "vault", "pdf_book", "pending",
             "", "", "", "", "", "", None, None, "2026-01-01 00:00:00", "2026-01-01 00:00:00"))
        # 回读三列，确认列真实存在
        row = conn.execute(
            "SELECT parent_task_id, seg_from, seg_to FROM import_tasks WHERE user_id = ?", (uid,)).fetchone()
        assert row is not None
        assert row[0] == "" and row[1] is None and row[2] is None
        # 清理测试数据
        conn.execute("DELETE FROM import_tasks WHERE user_id = ?", (uid,))


def test_create_task_with_segment_fields(app):
    from services import import_service as imps
    uid = "s1_ct_" + uuid.uuid4().hex[:6]
    parent = imps.create_task(uid, "book.pdf", "vault/book", "pdf_book")
    seg = imps.create_task(uid, "·0001-0020.md", "vault/book/段", "pdf_segment",
                           status="pending", parent_task_id=parent, seg_from=1, seg_to=20)
    assert parent and seg and parent != seg
    # 直接查库回读三列（get_task 不返回这些列，属内部字段）
    cf = _conn(app)
    with cf() as conn:
        row = conn.execute(
            "SELECT kind, status, parent_task_id, seg_from, seg_to FROM import_tasks WHERE task_id = ?",
            (seg,)).fetchone()
    assert row[0] == "pdf_segment"
    assert row[1] == "pending"
    assert row[2] == parent
    assert row[3] == 1 and row[4] == 20
    with cf() as conn:
        conn.execute("DELETE FROM import_tasks WHERE user_id = ?", (uid,))


def test_update_task_allows_segment_columns(app):
    from services import import_service as imps
    uid = "s1_ut_" + uuid.uuid4().hex[:6]
    seg = imps.create_task(uid, "s", "v", "pdf_segment", parent_task_id="P", seg_from=21, seg_to=40)
    imps.update_task(seg, seg_to=45, error="部分失败")
    cf = _conn(app)
    with cf() as conn:
        row = conn.execute("SELECT seg_to, error FROM import_tasks WHERE task_id = ?", (seg,)).fetchone()
    assert row[0] == 45
    assert row[1] == "部分失败"
    with cf() as conn:
        conn.execute("DELETE FROM import_tasks WHERE user_id = ?", (uid,))


def test_recover_delete_protection(app):
    """30 天清理：pdf_book 与有 error 的行保留，正常早期普通行删除。"""
    from services import import_service as imps
    cf = _conn(app)
    uid = "s1_rc_" + uuid.uuid4().hex[:6]
    old = "2020-01-01 00:00:00"  # 远超 30 天
    ids = {}
    with cf() as conn:
        for name, kind, err in (("book", "pdf_book", ""), ("failed", "pdf_segment", "转换失败"),
                                ("normal", "pdf", "")):
            t = uuid.uuid4().hex[:16]
            ids[name] = t
            conn.execute(
                "INSERT INTO import_tasks (task_id,user_id,file_name,folder_path,kind,status,"
                "progress_json,result_md,result_pdf,remote_job_id,error,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (t, uid, name, "v", kind, "done", "", "", "", "", err, old, old))
    imps.recover_tasks_on_startup(cf)
    surviving = set()
    with cf() as conn:
        for name in ids:
            r = conn.execute("SELECT 1 FROM import_tasks WHERE task_id = ?", (ids[name],)).fetchone()
            if r:
                surviving.add(name)
    # 清理
    with cf() as conn:
        conn.execute("DELETE FROM import_tasks WHERE user_id = ?", (uid,))
    assert "book" in surviving, "pdf_book 主任务不应被清理"
    assert "failed" in surviving, "有 error 的失败行不应被清理"
    assert "normal" not in surviving, "正常早期普通行应被清理"
