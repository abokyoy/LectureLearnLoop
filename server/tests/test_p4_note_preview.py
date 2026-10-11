# -*- coding: utf-8 -*-
"""P4 笔记完整预览端点契约测试（Flask test client）。

运行方式（server/ 目录）：python -m pytest tests/test_p4_note_preview.py -v
覆盖：GET /api/notes/<nid>/content 去 1000 字符截断（P4）——完整正文、
content_length 一致、related_knowledge_points 列表、不存在/跨用户防御。
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "p4prev_" + uuid.uuid4().hex[:8]
PW = "pass1234"


@pytest.fixture(scope="module")
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def au(client):
    r = client.post("/api/auth/register", json={"username": U, "password": PW})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def _h(token):
    return {"Authorization": "Bearer " + token}


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


class TestP4NotePreview:
    MOD = "P4PV" + uuid.uuid4().hex[:6]
    NID = None
    PID = None

    def test_1_setup_long_note(self, client, au):
        import tempfile
        tk, uid = au["token"], au["user_id"]
        subject = f"{self.MOD}_科"
        client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk))
        # 2000+ 字符长文（远超旧 1000 截断线），含知识点名供前端定位
        body = "\n\n".join(
            f"第{i}节 特征工程与采样策略：本节讨论{self.MOD}背景下的特征变换，编号{i:04d}。"
            for i in range(40))
        assert len(body) > 1500
        fd = Path(tempfile.mkdtemp(prefix="p4cdp_"))
        note_file = fd / "p4note.md"
        note_file.write_text("# 长笔记\n\n" + body, encoding="utf-8")
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description) "
                "VALUES (?,?,?,?)", (uid, subject, f"{self.MOD}特征", "描述"))
            cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
            self.__class__.PID = cur.fetchone()[0]
            uuid_ = "p4cdp-" + uuid.uuid4().hex
            cur.execute(
                "INSERT INTO notes (user_id, note_uuid, file_name, file_path, title) VALUES (?,?,?,?,?)",
                (uid, uuid_, "p4note.md", str(note_file), f"{self.MOD}长笔记"))
            cur.execute("SELECT id FROM notes WHERE note_uuid = ?", (uuid_,))
            self.__class__.NID = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO knowledge_point_sources (knowledge_point_id, note_id, note_uuid) VALUES (?,?,?)",
                (self.PID, self.NID, uuid_))
            conn.commit()
        finally:
            conn.close()

    def test_2_full_content_no_truncation(self, client, au):
        d = client.get(f"/api/notes/{self.NID}/content", headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is True
        note = d["note"]
        assert note["content_length"] > 1500
        assert len(note["content"]) == note["content_length"]  # 完整返回，非 clipped
        assert not note["content"].endswith("...")
        assert "第39节" in note["content"]  # 尾部内容存在（旧实现 1000 字处即截断）

    def test_3_related_points(self, client, au):
        d = client.get(f"/api/notes/{self.NID}/content", headers=_h(au["token"])).get_json()["data"]
        kps = d["note"]["related_knowledge_points"]
        assert any(k["id"] == self.PID and k["name"] == f"{self.MOD}特征" for k in kps)

    def test_4_guards(self, client, au):
        d = client.get("/api/notes/99999999/content", headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False  # 不存在
        u2 = "p4cdp_other_" + uuid.uuid4().hex[:6]
        tk2 = client.post("/api/auth/register", json={"username": u2, "password": PW}).get_json()["data"]["token"]
        d = client.get(f"/api/notes/{self.NID}/content", headers=_h(tk2)).get_json()["data"]
        assert d["success"] is False  # 跨用户不可读
        assert client.get(f"/api/notes/{self.NID}/content").status_code == 401

    def test_5_size_gate(self, client, au):
        # 评审 m-3：>2MB 文件拒绝全量返回（防误挂超大文件拖垮前端）
        import tempfile
        fd = Path(tempfile.mkdtemp(prefix="p4cdp_big_"))
        big = fd / "big.md"
        big.write_text("x" * (2 * 1024 * 1024 + 10), encoding="utf-8")
        conn = _conn()
        try:
            cur = conn.cursor()
            uuid_ = "p4cdp-big-" + uuid.uuid4().hex
            cur.execute(
                "INSERT INTO notes (user_id, note_uuid, file_name, file_path, title) VALUES (?,?,?,?,?)",
                (au["user_id"], uuid_, "big.md", str(big), f"{self.MOD}超大笔记"))
            cur.execute("SELECT id FROM notes WHERE note_uuid = ?", (uuid_,))
            nid_big = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        d = client.get(f"/api/notes/{nid_big}/content", headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False and "过大" in d["error"]
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM notes WHERE id = ?", (nid_big,))
            conn.commit()
        finally:
            conn.close()

    def test_9_cleanup(self, client, au):
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM knowledge_point_sources WHERE knowledge_point_id = ?", (self.PID,))
            cur.execute("DELETE FROM notes WHERE id = ?", (self.NID,))
            cur.execute("DELETE FROM knowledge_points WHERE id = ?", (self.PID,))
            cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name = ?",
                        (au["user_id"], f"{self.MOD}_科"))
            cur.execute("DELETE FROM users WHERE user_id = ?", (au["user_id"],))
            conn.commit()
        finally:
            conn.close()
