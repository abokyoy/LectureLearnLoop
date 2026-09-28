# -*- coding: utf-8 -*-
"""三期知识脑图（Mermaid mindmap）验收测试（Flask test client，LLM 用 monkeypatch）。

运行方式（server/ 目录）：python -m pytest tests/test_mindmap_p3.py -v
覆盖：首次插入、幂等替换（只保留一段）、库/文件一致、录音中 409、
路径穿越 403、空知识点 400、未认证 401、_extract_mindmap 解析分支。
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

UA = "p3mmap_a_" + uuid.uuid4().hex[:6]
UB = "p3mmap_b_" + uuid.uuid4().hex[:6]

MM1 = "mindmap\n  root((测试文档))\n    知识点甲\n      甲的一句话讲解\n    知识点乙\n      乙的一句话讲解"
MM2 = "mindmap\n  root((测试文档))\n    新知识点\n      重新生成的讲解"

FAKE_FENCED = "```mermaid\n" + MM1 + "\n```"
FAKE_FENCELESS = MM1
FAKE_ROOT_ONLY = "root((测试文档))\n  知识点甲\n    讲解甲"
FAKE_INVALID = "这是一段说明文字，不是代码。"


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


def _mk_note(client, token, content="# 学习笔记\n\n正文内容\n"):
    rel = "vault/脑图笔记_" + uuid.uuid4().hex[:6] + ".md"
    r = client.post("/api/notes/autosave", json={"path": rel, "content": content}, headers=_h(token))
    assert r.status_code == 200 and r.get_json()["data"]["success"]
    return rel


def _body(client, token, rel):
    r = client.get("/api/notes/content?path=" + rel, headers=_h(token))
    assert r.status_code == 200
    return r.get_json()["data"]


class TestMindmapGenerate:
    def test_first_generate_inserts_section(self, client, tokens, monkeypatch):
        ta, _ = tokens
        import routes_notes
        monkeypatch.setattr(routes_notes, "_llm_call", lambda p, c="": FAKE_FENCED)
        rel = _mk_note(client, ta)
        r = client.post("/api/notes/mindmap", json={
            "path": rel, "title": "测试文档",
            "points": [{"name": "知识点甲", "description": "讲解甲"},
                       {"name": "知识点乙", "description": "讲解乙"}]}, headers=_h(ta))
        assert r.status_code == 200, r.get_json()
        d = r.get_json()["data"]
        assert d["success"] and d["mermaid"].startswith("mindmap") and d["replaced"] is False

        body = _body(client, ta, rel)
        assert "<!-- LL:MMAP:BEGIN -->" in body["content"]
        assert "<!-- LL:MMAP:END -->" in body["content"]
        assert "```mermaid" in body["content"] and "知识点甲" in body["content"]
        assert "正文内容" in body["content"]          # 原正文保留
        assert body["source"] == "db"

    def test_second_generate_replaces_only_section(self, client, tokens, monkeypatch):
        ta, _ = tokens
        import routes_notes
        monkeypatch.setattr(routes_notes, "_llm_call", lambda p, c="": FAKE_FENCED)
        rel = _mk_note(client, ta)
        r1 = client.post("/api/notes/mindmap", json={"path": rel, "points": [{"name": "甲"}]}, headers=_h(ta))
        assert r1.status_code == 200
        monkeypatch.setattr(routes_notes, "_llm_call",
                            lambda p, c="": "```mermaid\n" + MM2 + "\n```")
        r2 = client.post("/api/notes/mindmap", json={"path": rel, "points": [{"name": "新知识点"}]}, headers=_h(ta))
        assert r2.status_code == 200 and r2.get_json()["data"]["replaced"] is True

        content = _body(client, ta, rel)["content"]
        assert content.count("<!-- LL:MMAP:BEGIN -->") == 1
        assert content.count("<!-- LL:MMAP:END -->") == 1
        assert "新知识点" in content and "知识点甲" not in content

    def test_db_and_file_identical(self, client, tokens, monkeypatch):
        ta, _ = tokens
        import routes_notes
        monkeypatch.setattr(routes_notes, "_llm_call", lambda p, c="": FAKE_FENCELESS)
        rel = _mk_note(client, ta)
        r = client.post("/api/notes/mindmap", json={"path": rel, "points": [{"name": "甲"}]}, headers=_h(ta))
        assert r.status_code == 200
        f = client.get("/api/vault/rawfile?path=" + rel, headers=_h(ta))
        assert f.status_code == 200
        assert f.get_json()["data"] == _body(client, ta, rel)["content"]

    def test_recording_note_rejected_409(self, client, tokens, monkeypatch):
        ta, _ = tokens
        import routes_notes
        monkeypatch.setattr(routes_notes, "_llm_call", lambda p, c="": FAKE_FENCED)
        rel = _mk_note(client, ta)
        assert client.post("/api/notes/recording", json={"path": rel, "on": True},
                           headers=_h(ta)).status_code == 200
        r = client.post("/api/notes/mindmap", json={"path": rel, "points": [{"name": "甲"}]}, headers=_h(ta))
        assert r.status_code == 409
        client.post("/api/notes/recording", json={"path": rel, "on": False}, headers=_h(ta))
        r2 = client.post("/api/notes/mindmap", json={"path": rel, "points": [{"name": "甲"}]}, headers=_h(ta))
        assert r2.status_code == 200


class TestMindmapGuards:
    def test_invalid_llm_output_500(self, client, tokens, monkeypatch):
        ta, _ = tokens
        import routes_notes
        monkeypatch.setattr(routes_notes, "_llm_call", lambda p, c="": FAKE_INVALID)
        rel = _mk_note(client, ta)
        r = client.post("/api/notes/mindmap", json={"path": rel, "points": [{"name": "甲"}]}, headers=_h(ta))
        assert r.status_code == 500
        assert "甲" not in _body(client, ta, rel)["content"]  # 失败不写坏笔记

    def test_empty_llm_output_500(self, client, tokens, monkeypatch):
        ta, _ = tokens
        import routes_notes
        monkeypatch.setattr(routes_notes, "_llm_call", lambda p, c="": "")
        rel = _mk_note(client, ta)
        r = client.post("/api/notes/mindmap", json={"path": rel, "points": [{"name": "甲"}]}, headers=_h(ta))
        assert r.status_code == 500

    def test_requires_points(self, client, tokens):
        ta, _ = tokens
        rel = _mk_note(client, ta)
        r = client.post("/api/notes/mindmap", json={"path": rel, "points": []}, headers=_h(ta))
        assert r.status_code == 400

    def test_traversal_403(self, client, tokens):
        ta, _ = tokens
        r = client.post("/api/notes/mindmap", json={"path": "../evil.md", "points": [{"name": "甲"}]}, headers=_h(ta))
        assert r.status_code == 403

    def test_requires_auth(self, client):
        r = client.post("/api/notes/mindmap", json={"path": "a.md", "points": [{"name": "甲"}]})
        assert r.status_code == 401

    def test_user_isolation(self, client, tokens):
        ta, tb = tokens
        rel = _mk_note(client, ta)
        # u2 用同一相对路径生成：落到 u2 自己的 vault，不得出现在 u1 笔记里
        import routes_notes
        routes_notes._llm_call  # noqa: B018（仅确认可导入）
        orig = routes_notes._llm_call
        routes_notes._llm_call = lambda p, c="": FAKE_FENCED
        try:
            r = client.post("/api/notes/mindmap", json={"path": rel, "points": [{"name": "乙的甲"}]}, headers=_h(tb))
            assert r.status_code == 200
        finally:
            routes_notes._llm_call = orig
        assert "<!-- LL:MMAP:BEGIN -->" not in _body(client, ta, rel)["content"]  # u1 笔记未被触碰
        assert "<!-- LL:MMAP:BEGIN -->" in _body(client, tb, rel)["content"]      # u2 自己 vault 生成成功


class TestExtractMindmapUnit:
    def test_fenced(self):
        from routes_notes import _extract_mindmap
        assert _extract_mindmap(FAKE_FENCED) == MM1

    def test_fenceless(self):
        from routes_notes import _extract_mindmap
        assert _extract_mindmap(FAKE_FENCELESS) == MM1

    def test_root_only_autocompletes_declaration(self):
        from routes_notes import _extract_mindmap
        out = _extract_mindmap(FAKE_ROOT_ONLY)
        assert out and out.startswith("mindmap") and "root((测试文档))" in out

    def test_invalid_and_empty(self):
        from routes_notes import _extract_mindmap
        assert _extract_mindmap(FAKE_INVALID) is None
        assert _extract_mindmap("") is None
        assert _extract_mindmap(None) is None
        assert _extract_mindmap("```mermaid\n不\n```") is None  # 无 root 行

    def test_splice_idempotent(self):
        from routes_notes import _splice_mindmap
        c1, rep1 = _splice_mindmap("旧正文", MM1)
        assert rep1 is False and "旧正文" in c1
        c2, rep2 = _splice_mindmap(c1, MM2)
        assert rep2 is True and c2.count("LL:MMAP:BEGIN") == 1
        assert MM2 in c2 and MM1 not in c2 and "旧正文" in c2
