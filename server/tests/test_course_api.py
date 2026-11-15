# -*- coding: utf-8 -*-
"""目标导向学习 API 契约测试（Flask test client，LLM 全 monkeypatch 不烧积分）。

运行方式（server/ 目录）：python -m pytest tests/test_course_api.py -v
覆盖：POST/GET/DELETE /api/course/goals、GET .../goals/<id>/tree、
积分不足 402、LLM 非法不落脏数据、删除级联、学科删除防护（Spec §9）。
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "cg" + uuid.uuid4().hex[:8]
PW = "pass1234"


def _mods(nm=4, nl=4):
    return json.dumps({"modules": [{"title": f"模块{i}", "description": f"说明{i}",
                                    "lessons": [{"title": f"课文{i}-{j}", "description": "d",
                                                 "est_minutes": 15 * (j % 4 + 1)} for j in range(nl)]}
                                   for i in range(nm)]}, ensure_ascii=False)


@pytest.fixture(scope="module")
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _reg(client, uname):
    r = client.post("/api/auth/register", json={"username": uname, "password": PW})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


@pytest.fixture(scope="module")
def au(client):
    return _reg(client, U)


@pytest.fixture(scope="module")
def au2(client):
    return _reg(client, U + "b")


def _h(token):
    return {"Authorization": "Bearer " + token}


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


@pytest.fixture()
def good_llm(monkeypatch):
    from services import course_service as cs
    monkeypatch.setattr(cs, "_llm", lambda prompt, scene="": _mods())


class TestCourseGoals:
    MOD = "CG" + uuid.uuid4().hex[:6]

    def test_create_goal(self, client, au, good_llm):
        subj = self.MOD + "S1"
        r = client.post("/api/course/goals", json={"subject_name": subj, "goal_text": "我要系统学会" + subj},
                        headers=_h(au["token"]))
        body = r.get_json()
        assert body["success"], body
        d = body["data"]
        gid = d["goal"]["id"]
        assert gid > 0
        assert d["goal"]["status"] == "ready"
        assert len(d["modules"]) == 4
        assert all(len(m["lessons"]) == 4 for m in d["modules"])
        assert d["progress"] == {"done": 0, "total": 16}
        # lesson 字段契约
        l0 = d["modules"][0]["lessons"][0]
        assert set(["id", "ord", "title", "description", "est_minutes",
                    "status", "content_mode", "pretest_score", "regen_count"]) <= set(l0)
        assert l0["status"] == "new"
        # 学科自动建档
        conn = _conn()
        try:
            n = conn.execute("SELECT COUNT(1) FROM user_subjects WHERE user_id=? AND subject_name=?",
                             (au["user_id"], subj)).fetchone()[0]
            assert n == 1
        finally:
            conn.close()
        type(self).GID = gid
        type(self).SUBJ = subj

    def test_create_goal_bad_param(self, client, au, good_llm):
        r = client.post("/api/course/goals", json={"subject_name": self.SUBJ, "goal_text": "短"},
                        headers=_h(au["token"]))
        assert r.status_code == 400
        assert r.get_json()["success"] is False

    def test_tree_get(self, client, au):
        r = client.get(f"/api/course/goals/{self.GID}/tree", headers=_h(au["token"]))
        body = r.get_json()
        assert body["success"] and len(body["data"]["modules"]) == 4
        # 越权：另一用户不可见
        r2 = client.get(f"/api/course/goals/{self.GID}/tree", headers=_h(_tok(client)))
        assert r2.get_json()["success"] is False

    def test_list_isolation(self, client, au, au2, good_llm):
        r = client.get("/api/course/goals", headers=_h(au2["token"]))
        ids = [g["id"] for g in r.get_json()["data"]["goals"]]
        assert self.GID not in ids
        r2 = client.get("/api/course/goals", headers=_h(au["token"]))
        assert self.GID in [g["id"] for g in r2.get_json()["data"]["goals"]]

    def test_insufficient_credits(self, client, au, monkeypatch):
        import credits_service as cr
        from services import course_service as cs

        def boom(prompt, scene=""):
            raise cr.InsufficientCreditsError(balance=1)
        monkeypatch.setattr(cs, "_llm", boom)
        r = client.post("/api/course/goals", json={"subject_name": self.SUBJ, "goal_text": "积分不足测试目标"},
                        headers=_h(au["token"]))
        assert r.status_code == 402
        body = r.get_json()
        assert body["credits_insufficient"] is True and body["credit_balance"] == 1

    def test_llm_invalid_twice_no_dirty_row(self, client, au, monkeypatch):
        from services import course_service as cs
        calls = []
        monkeypatch.setattr(cs, "_llm", lambda prompt, scene="": (calls.append(1), "垃圾输出")[1])
        before = _goal_count(client, au)
        r = client.post("/api/course/goals", json={"subject_name": self.SUBJ, "goal_text": "必然失败的目标啊"},
                        headers=_h(au["token"]))
        body = r.get_json()
        assert body["success"] is False and body["error"]
        assert len(calls) == 2
        assert _goal_count(client, au) == before  # 失败不落库

    def test_subject_delete_guard(self, client, au, good_llm):
        r = client.delete(f"/api/subjects/{self.SUBJ}", headers=_h(au["token"]))
        assert r.status_code == 409
        assert r.get_json()["success"] is False

    def test_delete_goal_cascade(self, client, au):
        # 造一条外部资产（练习记录）验证删除目标不动它
        conn = _conn()
        try:
            kp = conn.execute("SELECT id FROM knowledge_points WHERE user_id=? LIMIT 1",
                              (au["user_id"],)).fetchone()
            if kp:
                cur = conn.execute(
                    "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id,"
                    " question_content, user_answer, is_correct) VALUES (?,?,?,?,?,1)",
                    (au["user_id"], self.SUBJ, kp[0], "课程删除防护题", "A"))
                conn.commit()
                prid = cur.lastrowid
            else:
                prid = None
        finally:
            conn.close()
        r = client.delete(f"/api/course/goals/{self.GID}", headers=_h(au["token"]))
        assert r.get_json()["success"], r.get_json()
        conn = _conn()
        try:
            for t, col, key in (("learning_goals", "id", self.GID),):
                assert conn.execute(f"SELECT COUNT(1) FROM {t} WHERE {col}=?", (key,)).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(1) FROM course_modules WHERE goal_id=?", (self.GID,)).fetchone()[0] == 0
            assert conn.execute(
                "SELECT COUNT(1) FROM course_lessons WHERE module_id IN "
                "(SELECT id FROM course_modules WHERE goal_id=?)", (self.GID,)).fetchone()[0] == 0
            if prid:
                assert conn.execute("SELECT COUNT(1) FROM practice_records WHERE id=?",
                                    (prid,)).fetchone()[0] == 1
        finally:
            conn.close()
        # 目标删除后学科可删
        r2 = client.delete(f"/api/subjects/{self.SUBJ}", headers=_h(au["token"]))
        assert r2.get_json()["success"], r2.get_json()


_tok_cache = {}


def _tok(client):
    if "t" not in _tok_cache:
        _tok_cache["t"] = _reg(client, U + "c")["token"]
    return _tok_cache["t"]


def _goal_count(client, au):
    r = client.get("/api/course/goals", headers=_h(au["token"]))
    return len(r.get_json()["data"]["goals"])
