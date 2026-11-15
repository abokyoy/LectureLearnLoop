# -*- coding: utf-8 -*-
"""知识点提取确认 + complete 端点断言（Task 12）。

运行方式（server/ 目录）：python -m pytest tests/test_course_extract.py -v
LLM 全 monkeypatch；提取链 monkeypatch kms 方法（不触发真实提取/相似度）。
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "cgx" + uuid.uuid4().hex[:8]
PW = "pass1234"

MD = """# 课文标题

## 概览
本文讲解目标导向学习课文正文的生成契约，覆盖概念定义与典型例子，长度需要超过两百字下限以通过校验逻辑的分支判断测试。

## 核心概念
梯度下降通过沿负梯度方向迭代更新参数最小化损失函数，学习率决定每步步长。

## 范例
设 $f(x)=x^2$，从 $x_0=3$、$\\eta=0.1$ 出发迭代三步的数值演练过程与结果解释。

## 重点摘要
概念、公式、迭代过程三要素构成完整理解链条，缺一不可，正文以简短段落组织以上内容并留有余味。
""" * 2


def _mods():
    return json.dumps({"modules": [{"title": f"模块{i}", "description": f"说明{i}",
                                    "lessons": [{"title": f"课文{i}-{j}", "description": "d",
                                                 "est_minutes": 30} for j in range(3)]}
                                   for i in range(3)], "n": 3}, ensure_ascii=False)


def _qpack(n=4):
    return json.dumps({"questions": [
        {"stem": f"题干{i}", "options": [f"甲{i}", "乙{i}", "丙{i}", "丁{i}"],
         "answer_index": i % 4, "kp_name": f"知识点{i}", "explanation": f"解析{i}"}
        for i in range(n)]}, ensure_ascii=False)


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


@pytest.fixture(scope="module")
def au2(client):
    r = client.post("/api/auth/register", json={"username": U + "x", "password": PW})
    return r.get_json()["data"]


def _h(token):
    return {"Authorization": "Bearer " + token}


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    conn = _conn()
    for sql in (
        "DELETE FROM course_attempts WHERE user_id=?",
        "DELETE FROM course_tests WHERE lesson_id IN (SELECT l.id FROM course_lessons l "
        "JOIN course_modules m ON l.module_id=m.id JOIN learning_goals g ON m.goal_id=g.id WHERE g.user_id=?)",
        "DELETE FROM course_tests WHERE module_id IN (SELECT m.id FROM course_modules m "
        "JOIN learning_goals g ON m.goal_id=g.id WHERE g.user_id=?)",
        "DELETE FROM course_lessons WHERE module_id IN (SELECT id FROM course_modules "
        "WHERE goal_id IN (SELECT id FROM learning_goals WHERE user_id=?))",
        "DELETE FROM course_modules WHERE goal_id IN (SELECT id FROM learning_goals WHERE user_id=?)",
        "DELETE FROM learning_goals WHERE user_id=?",
        "DELETE FROM practice_records WHERE user_id=?",
        "DELETE FROM error_questions WHERE user_id=?",
        "DELETE FROM knowledge_points WHERE user_id=?",
    ):
        conn.execute(sql, (U,))
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def llm():
    from services import course_service as cs
    import similarity_matcher as sm

    def fake(prompt, scene=""):
        if scene == "生成课程结构":
            return _mods()
        if scene in ("课程前测出题", "课程后练出题"):
            return _qpack(4)
        if scene == "生成课程课文":
            return MD
        raise AssertionError("unexpected scene " + scene)
    m = pytest.MonkeyPatch()
    m.setattr(cs, "_llm", fake)
    m.setattr(sm, "rank_matches", lambda **kw: [])
    yield
    m.undo()


def _mk_lesson(client, au):
    """建目标取第一篇课文 id。"""
    subj = "提取学科" + uuid.uuid4().hex[:6]
    r = client.post("/api/course/goals", json={"subject_name": subj, "goal_text": "断言提取与完成流程"},
                    headers=_h(au["token"]))
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["modules"][0]["lessons"][0]["id"]


def _db_pack(lid, kind):
    conn = _conn()
    try:
        row = conn.execute("SELECT questions_json FROM course_tests "
                           "WHERE lesson_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
                           (lid, kind)).fetchone()
    finally:
        conn.close()
    return json.loads(row[0]) if row else []


def _pass_pretest(client, au, lid):
    """走完前测（全对→concise 也生成课文），课文在库。"""
    r = client.get(f"/api/course/lessons/{lid}/pretest", headers=_h(au["token"]))
    assert r.status_code == 200, r.get_json()
    pack = _db_pack(lid, "pretest")
    answers = [q["answer_index"] for q in pack]
    r2 = client.post(f"/api/course/lessons/{lid}/pretest", json={"answers": answers},
                     headers=_h(au["token"]))
    assert r2.status_code == 200, r2.get_json()
    return r2.get_json()["data"]


def _pass_postquiz(client, au, lid):
    pack = _db_pack(lid, "postquiz")
    answers = [q["answer_index"] for q in pack]
    r = client.post(f"/api/course/lessons/{lid}/postquiz", json={"answers": answers},
                    headers=_h(au["token"]))
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


class TestComplete:
    def test_01_complete_ok(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        client.get(f"/api/course/lessons/{lid}/postquiz", headers=_h(au["token"]))
        d = _pass_postquiz(client, au, lid)
        assert d["lesson_status"] == "learned"
        r = client.post(f"/api/course/lessons/{lid}/complete", headers=_h(au["token"]))
        body = r.get_json()
        assert r.status_code == 200, body
        assert body["data"]["status"] == "done"
        assert body["data"].get("done_time")

    def test_02_complete_needs_postquiz(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)  # content_ready：后练 attempt 还没有
        r = client.post(f"/api/course/lessons/{lid}/complete", headers=_h(au["token"]))
        assert r.status_code == 409, r.get_json()

    def test_03_complete_from_new(self, client, au, llm):
        lid = _mk_lesson(client, au)
        r = client.post(f"/api/course/lessons/{lid}/complete", headers=_h(au["token"]))
        assert r.status_code == 409, r.get_json()

    def test_04_complete_idempotent(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        client.get(f"/api/course/lessons/{lid}/postquiz", headers=_h(au["token"]))
        _pass_postquiz(client, au, lid)
        client.post(f"/api/course/lessons/{lid}/complete", headers=_h(au["token"]))
        r = client.post(f"/api/course/lessons/{lid}/complete", headers=_h(au["token"]))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["data"]["status"] == "done"

    def test_05_complete_404(self, client, au2, llm):
        r = client.post("/api/course/lessons/99999999/complete", headers=_h(au2["token"]))
        assert r.status_code == 404


class TestExtract:
    def _patch_extract(self, monkeypatch, ret):
        from routes_knowledge import get_kms
        kms = get_kms()
        monkeypatch.setattr(type(kms), "extract_and_process_knowledge_points",
                            lambda self, subject, content, user_id="0001": ret, raising=True)

    def test_10_extract_ok(self, client, au, llm, monkeypatch):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        self._patch_extract(monkeypatch, {"processed_points": [
            {"extracted_point": {"concept_name": "梯度下降", "core_definition": "沿负梯度迭代更新参数",
                                 "category": "方法", "importance": "高"},
             "similar_points": [{"id": 1}, {"id": 2}], "match_status": "已存在相似知识点"},
            {"extracted_point": {"point_name": "学习率", "core_description": "决定每步步长"},
             "similar_points": [], "match_status": ""},
        ]})
        r = client.post(f"/api/course/lessons/{lid}/extract", headers=_h(au["token"]))
        body = r.get_json()
        assert body["success"] is True, body
        pts = body["data"]["points"]
        assert len(pts) == 2
        p0 = pts[0]
        assert p0["name"] == "梯度下降" and p0["description"] == "沿负梯度迭代更新参数"
        assert p0["category"] == "方法" and p0["importance"] == "高"
        assert p0["match_status"] == "已存在相似知识点" and p0["similar_count"] == 2
        assert pts[1]["name"] == "学习率" and pts[1]["similar_count"] == 0

    def test_11_extract_empty(self, client, au, llm, monkeypatch):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        self._patch_extract(monkeypatch, {"processed_points": []})
        r = client.post(f"/api/course/lessons/{lid}/extract", headers=_h(au["token"]))
        assert r.status_code == 400, r.get_json()

    def test_12_extract_no_content(self, client, au, llm):
        lid = _mk_lesson(client, au)
        r = client.post(f"/api/course/lessons/{lid}/extract", headers=_h(au["token"]))
        assert r.status_code == 400, r.get_json()

    def test_13_extract_credits(self, client, au, llm, monkeypatch):
        import credits_service as cr
        from routes_knowledge import get_kms
        kms = get_kms()

        def boom(self, subject, content, user_id="0001"):
            raise cr.InsufficientCreditsError(3.5)
        monkeypatch.setattr(type(kms), "extract_and_process_knowledge_points", boom, raising=True)
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        r = client.post(f"/api/course/lessons/{lid}/extract", headers=_h(au["token"]))
        assert r.status_code == 402, r.get_json()
        body = r.get_json()
        assert body.get("credits_insufficient") is True and body.get("credit_balance") == 3.5

    def test_14_extract_404(self, client, au2, llm):
        r = client.post("/api/course/lessons/99999999/extract", headers=_h(au2["token"]))
        assert r.status_code == 404
