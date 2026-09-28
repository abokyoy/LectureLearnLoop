# -*- coding: utf-8 -*-
"""二期学习笔记入库验收测试（Flask test client，双后端通用）。

运行方式（server/ 目录）：python -m pytest tests/test_notes_p2.py -v
覆盖：autosave 写库+轮询读库、recording 标志与 active、用户清单、
跨用户越权防护（403）、路径穿越防护、rawfile PUT 同步入库。
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

UA = "p2notes_a_" + uuid.uuid4().hex[:6]
UB = "p2notes_b_" + uuid.uuid4().hex[:6]


@pytest.fixture(scope="module")
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _register(client, username):
    r = client.post("/api/auth/register", json={"username": username, "password": "pass1234"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["token"]


def _h(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture(scope="module")
def tokens(client):
    return _register(client, UA), _register(client, UB)


class TestNotesAutosave:
    def test_autosave_then_poll_from_db(self, client, tokens):
        ta, _ = tokens
        rel = "vault/笔记甲_" + uuid.uuid4().hex[:6] + ".md"
        body = "# 听课笔记\n\n## 转写全文\n\n实时保存测试内容 123\n"
        r = client.post("/api/notes/autosave", json={"path": rel, "content": body}, headers=_h(ta))
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["success"] and d["updated_time"] and d["note_id"]

        r = client.get("/api/notes/content?path=" + rel, headers=_h(ta))
        d = r.get_json()["data"]
        assert d["exists"] and d["source"] == "db" and d["content"] == body
        assert d["word_count"] > 0 and d["recording"] is False

    def test_autosave_twice_updates_watermark(self, client, tokens):
        ta, _ = tokens
        rel = "vault/笔记乙_" + uuid.uuid4().hex[:6] + ".md"
        r1 = client.post("/api/notes/autosave", json={"path": rel, "content": "第一版"}, headers=_h(ta))
        r2 = client.post("/api/notes/autosave", json={"path": rel, "content": "第二版内容更长"}, headers=_h(ta))
        d1, d2 = r1.get_json()["data"], r2.get_json()["data"]
        assert d1["success"] and d2["success"] and d2["note_id"] == d1["note_id"]
        r = client.get("/api/notes/content?path=" + rel, headers=_h(ta))
        assert r.get_json()["data"]["content"] == "第二版内容更长"

    def test_autosave_rejects_traversal(self, client, tokens):
        ta, _ = tokens
        r = client.post("/api/notes/autosave", json={"path": "../evil.md", "content": "x"}, headers=_h(ta))
        assert r.status_code == 403

    def test_requires_auth(self, client):
        assert client.post("/api/notes/autosave", json={"path": "a.md", "content": "x"}).status_code == 401
        assert client.get("/api/notes/content?path=a.md").status_code == 401
        assert client.get("/api/notes/list").status_code == 401
        assert client.get("/api/notes/active").status_code == 401


class TestRecordingFlag:
    def test_set_clear_and_active(self, client, tokens):
        ta, _ = tokens
        rel = "vault/笔记丙_" + uuid.uuid4().hex[:6] + ".md"
        assert client.post("/api/notes/autosave", json={"path": rel, "content": "录制测试"}, headers=_h(ta)).status_code == 200

        r = client.post("/api/notes/recording", json={"path": rel, "on": True}, headers=_h(ta))
        assert r.status_code == 200 and r.get_json()["data"]["success"]
        r = client.get("/api/notes/active", headers=_h(ta))
        names = [i["name"] for i in r.get_json()["data"]["items"]]
        assert rel.split("/")[-1] in names

        r = client.get("/api/notes/content?path=" + rel, headers=_h(ta))
        assert r.get_json()["data"]["recording"] is True

        r = client.post("/api/notes/recording", json={"path": rel, "on": False}, headers=_h(ta))
        assert r.get_json()["data"]["success"]
        r = client.get("/api/notes/active", headers=_h(ta))
        names = [i["name"] for i in r.get_json()["data"]["items"]]
        assert rel.split("/")[-1] not in names

    def test_list_contains_note_with_meta(self, client, tokens):
        ta, _ = tokens
        rel = "vault/笔记丁_" + uuid.uuid4().hex[:6] + ".md"
        client.post("/api/notes/autosave", json={"path": rel, "content": "清单测试内容"}, headers=_h(ta))
        r = client.get("/api/notes/list", headers=_h(ta))
        items = r.get_json()["data"]["items"]
        hit = [i for i in items if i["name"] == rel.split("/")[-1]]
        assert hit and hit[0]["word_count"] > 0 and hit[0]["updated_time"]


class TestUserIsolation:
    def test_cross_user_relative_path_no_leak(self, client, tokens):
        ta, tb = tokens
        rel = "vault/机密_" + uuid.uuid4().hex[:6] + ".md"
        client.post("/api/notes/autosave", json={"path": rel, "content": "A 的机密笔记"}, headers=_h(ta))
        # B 用同一相对路径读取：命中 B 自己的 root，不应存在、不泄露 A 正文
        r = client.get("/api/notes/content?path=" + rel, headers=_h(tb))
        d = r.get_json()["data"]
        assert not d.get("content")

    def test_cross_user_absolute_path_403(self, client, tokens):
        ta, tb = tokens
        rel = "vault/机密乙_" + uuid.uuid4().hex[:6] + ".md"
        client.post("/api/notes/autosave", json={"path": rel, "content": "A 绝对路径机密"}, headers=_h(ta))
        r = client.get("/api/notes/list", headers=_h(ta))
        hit = [i for i in r.get_json()["data"]["items"] if i["name"] == rel.split("/")[-1]]
        assert hit and hit[0]["path"]
        r = client.get("/api/notes/content?path=" + hit[0]["path"], headers=_h(tb))
        assert r.status_code == 403

    def test_active_isolation(self, client, tokens):
        ta, tb = tokens
        rel = "vault/录制隔离_" + uuid.uuid4().hex[:6] + ".md"
        client.post("/api/notes/autosave", json={"path": rel, "content": "x"}, headers=_h(ta))
        client.post("/api/notes/recording", json={"path": rel, "on": True}, headers=_h(ta))
        r = client.get("/api/notes/active", headers=_h(tb))
        assert not r.get_json()["data"]["items"]
        client.post("/api/notes/recording", json={"path": rel, "on": False}, headers=_h(ta))


class TestRawfileDbSync:
    def test_rawfile_put_syncs_note_content(self, client, tokens):
        ta, _ = tokens
        rel = "vault/旧通道_" + uuid.uuid4().hex[:6] + ".md"
        r = client.put("/api/vault/rawfile", json={"path": rel, "content": "旧保存通道正文"}, headers=_h(ta))
        assert r.status_code == 200 and r.get_json()["data"] is True
        r = client.get("/api/notes/content?path=" + rel, headers=_h(ta))
        d = r.get_json()["data"]
        assert d["source"] == "db" and d["content"] == "旧保存通道正文"
