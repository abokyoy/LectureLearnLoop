# -*- coding: utf-8 -*-
"""书籍任务同存同删 S7 验收测试（2026-10-07）。

背景：用户删旧书→重导入→转换面板报"原件丢失或不可用"。根因：删书文件夹时
pdf_book 主任务行未回收，僵尸行被路径反查命中并遮蔽同名新书。

覆盖：
- purge_book_tasks_under：删目录回收其下书籍主任务 + 连带 convert_segment 子任务；
  路径前缀隔离（兄弟目录不误删）；直删原件 PDF 同样回收；非书籍任务不动。
- find_book_task_by_pdf：同路径多行取最新；原件缺失返回 None。

运行（server/ 目录）：python -m pytest tests/test_pdf_book_s7_purge.py -v
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


def _mk_book(app, tmp_path, with_children=True):
    """建书：tmp 下 book/书.pdf + book/书·0001-0020.md，登记 pdf_book 主任务(+2 段子任务)。"""
    from services import import_service as imps
    uid = "s7_" + uuid.uuid4().hex[:8]
    book = tmp_path / f"book_{uid}"
    (book / "附件").mkdir(parents=True)
    orig = book / "书.pdf"
    orig.write_bytes(b"%PDF-1.4 fake")
    main = imps.create_task(uid, "书.pdf", str(book), "pdf_book",
                            result_pdf=str(orig), status="done")
    kids = []
    if with_children:
        for sf, st in [(1, 20), (21, 40)]:
            kids.append(imps.create_task(uid, f"书·{sf:04d}-{st:04d}.md", str(book),
                                         "convert_segment", parent_task_id=main,
                                         seg_from=sf, seg_to=st, status="done"))
    return uid, book, orig, main, kids


def _count(app, ids):
    if not ids:
        return 0
    qmarks = ",".join("?" for _ in ids)
    with _conn(app)() as conn:
        return len(conn.execute(
            f"SELECT 1 FROM import_tasks WHERE task_id IN ({qmarks})", tuple(ids)).fetchall())


def test_purge_dir_removes_book_and_children(app, tmp_path):
    from services import import_service as imps
    uid, book, _orig, main, kids = _mk_book(app, tmp_path)
    assert _count(app, [main] + kids) == 3
    purged = imps.purge_book_tasks_under(uid, book)
    assert purged == [main]
    assert _count(app, [main] + kids) == 0, "主任务与子任务行应一并回收"


def test_purge_sibling_prefix_isolation(app, tmp_path):
    from services import import_service as imps
    uid, book, _orig, main, _kids = _mk_book(app, tmp_path, with_children=False)
    # 兄弟目录（名字同前缀 book_xxx vs book_xxx2）不得误删
    sib = tmp_path / (book.name + "2")
    sib.mkdir()
    assert imps.purge_book_tasks_under(uid, sib) == []
    assert _count(app, [main]) == 1
    # 直删原件 PDF（target 即文件本身）同样回收
    assert imps.purge_book_tasks_under(uid, book / "书.pdf") == [main]
    assert _count(app, [main]) == 0


def test_purge_does_not_touch_other_kinds(app, tmp_path):
    from services import import_service as imps
    uid, book, _orig, main, _kids = _mk_book(app, tmp_path, with_children=False)
    other = imps.create_task(uid, "n.md", str(book), "md")  # 同目录下非书籍任务
    imps.purge_book_tasks_under(uid, book)
    assert _count(app, [other]) == 1, "非 pdf_book 任务行不得被回收"
    assert _count(app, [main]) == 0
    with _conn(app)() as conn:
        conn.execute("DELETE FROM import_tasks WHERE user_id = ?", (uid,))


def test_find_book_prefers_newest_live_row(app, tmp_path):
    from services import import_service as imps
    uid = "s7f_" + uuid.uuid4().hex[:8]
    d = tmp_path / f"fb_{uid}"
    d.mkdir()
    orig = d / "b.pdf"
    orig.write_bytes(b"%PDF-1.4 fake")
    # 先插"旧僵尸行"（更早 created_at 由插入顺序模拟：直接改列），再插新行
    zombie = imps.create_task(uid, "b.pdf", str(d), "pdf_book", result_pdf=str(orig), status="done")
    fresh = imps.create_task(uid, "b.pdf", str(d), "pdf_book", result_pdf=str(orig), status="done")
    with _conn(app)() as conn:
        conn.execute("UPDATE import_tasks SET created_at='2026-01-01 00:00:00' WHERE task_id=?", (zombie,))
        conn.execute("UPDATE import_tasks SET created_at='2026-09-01 00:00:00' WHERE task_id=?", (fresh,))
    got = imps.find_book_task_by_pdf(uid, str(orig))
    assert got and got["task_id"] == fresh, "同路径多行必须取最新行"
    # 原件删除后：反查必须未命中（不再返回僵尸/失效行）
    orig.unlink()
    assert imps.find_book_task_by_pdf(uid, str(orig)) is None
    with _conn(app)() as conn:
        conn.execute("DELETE FROM import_tasks WHERE user_id = ?", (uid,))
