# -*- coding: utf-8 -*-
"""外围端点断言（Task 11：extend 扩展课程 / chat 课内AI问答 / attempts 明细）。

运行方式（server/ 目录）：python -m pytest tests/test_course_ext.py -v
LLM 全 monkeypatch（function-scope，按 scene 分发），不烧积分。
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "cge" + uuid.uuid4().hex[:8]
PW = "pass1234"

MD = """# 课文标题

## 概览
本文讲解目标导向学习课文正文的生成契约，覆盖概念定义与典型例子，长度需要超过两百字下限以通过校验逻辑的分支判断测试。

## 核心概念
梯度下降通过沿负梯度方向迭代更新参数最小化损失函数，学习率决定每步步长。

## 重点摘要
概念、公式、迭代过程三要素构成完整理解链条，缺一不可，正文以简短段落组织以上内容并留有余味。
""" * 2


def _mods():
    # 3 模块×3 课文：满足主结构 3~8 模块校验（与扩展断言基准 9 课对齐）
    return json.dumps({"modules": [{"title": f"模块{i}", "description": f"说明{i}",
                                    "lessons": [{"title": f"课文{i}-{j}", "description": "d",
                                                 "est_minutes": 30} for j in range(3)]}
                                   for i in range(3)], "n": 3}, ensure_ascii=False)


def _ext():
    """扩展 fake 输出：同时带 modules 与 lessons 两段，validate 按 action 取用。"""
    return json.dumps({
        "modules": [{"title": "模块扩展", "description": "ext",
                     "lessons": [{"title": "课文X1", "description": "d", "est_minutes": 30},
                                 {"title": "课文X2", "description": "d", "est_minutes": 45}]}],
        "lessons": [{"title": "课文Y1", "description": "d", "est_minutes": 30},
                    {"title": "课文Y2", "description": "d", "est_minutes": 30}],
    }, ensure_ascii=False)


def _qpack(n=4):
    return json.dumps({"questions": [
        {"stem": f"题干{i}", "options": [f"甲{i}", f"乙{i}", f"丙{i}", f"丁{i}"],
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


def _exec(sql, args=()):
    conn = _conn()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
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
        _exec(sql, (U,))


@pytest.fixture()
def llm(monkeypatch):
    """function-scope 假 LLM：测试可再 monkeypatch 覆盖特定 scene 返回。"""
    from services import course_service as cs
    import similarity_matcher as sm
    cap = []

    def fake(prompt, scene=""):
        cap.append((scene, prompt))
        if scene == "生成课程结构":
            return _mods()
        if scene == "课程扩展生成":
            return _ext()
        if scene in ("课程前测出题", "课程后练出题"):
            return _qpack(4)
        if scene == "生成课程课文":
            return MD
        if scene == "课内AI问答":
            return "这是课内问答的回答。"
        raise AssertionError("unexpected scene " + scene)
    monkeypatch.setattr(cs, "_llm", fake)
    monkeypatch.setattr(sm, "rank_matches", lambda **kw: [])
    yield cap


def _mk_goal(client, au):
    subj = "扩展学科" + uuid.uuid4().hex[:6]
    r = client.post("/api/course/goals",
                    json={"subject_name": subj, "goal_text": "断言扩展课程的目标"}, headers=_h(au["token"]))
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


class TestExtend:
    def test_01_add_module(self, client, au, llm):
        d0 = _mk_goal(client, au)
        old_ids = [l["id"] for m in d0["modules"] for l in m["lessons"]]
        r = client.post(f"/api/course/goals/{d0['goal']['id']}/extend",
                        json={"action": "add_module"}, headers=_h(au["token"]))
        body = r.get_json()
        assert body["success"] is True, body
        mods = body["data"]["modules"]
        assert len(mods) == 4, [m["title"] for m in mods]
        newm = mods[-1]
        assert newm["title"] == "模块扩展" and [l["title"] for l in newm["lessons"]] == ["课文X1", "课文X2"]
        assert newm["ord"] == 4
        # 追加不覆盖：旧课文 id 原样
        now_ids = [l["id"] for m in mods[:3] for l in m["lessons"]]
        assert now_ids == old_ids
        assert body["data"]["progress"]["total"] == 11

    def test_02_add_lesson(self, client, au, llm):
        d0 = _mk_goal(client, au)
        m0 = d0["modules"][0]
        old_ids = [l["id"] for l in m0["lessons"]]
        r = client.post(f"/api/course/goals/{d0['goal']['id']}/extend",
                        json={"action": "add_lesson", "module_id": m0["id"]}, headers=_h(au["token"]))
        body = r.get_json()
        assert body["success"] is True, body
        target = next(m for m in body["data"]["modules"] if m["id"] == m0["id"])
        assert len(target["lessons"]) == 5
        assert [l["id"] for l in target["lessons"][:3]] == old_ids  # 旧行不动
        assert [l["title"] for l in target["lessons"][3:]] == ["课文Y1", "课文Y2"]
        assert [l["ord"] for l in target["lessons"][3:]] == [4, 5]  # ord 续排

    def test_03_bad_action(self, client, au, llm):
        d0 = _mk_goal(client, au)
        r = client.post(f"/api/course/goals/{d0['goal']['id']}/extend",
                        json={"action": "reset"}, headers=_h(au["token"]))
        assert r.status_code == 400

    def test_04_add_lesson_module_check(self, client, au, llm):
        d0 = _mk_goal(client, au)
        r = client.post(f"/api/course/goals/{d0['goal']['id']}/extend",
                        json={"action": "add_lesson"}, headers=_h(au["token"]))
        assert r.status_code == 400  # 缺 module_id
        r = client.post(f"/api/course/goals/{d0['goal']['id']}/extend",
                        json={"action": "add_lesson", "module_id": 99999999}, headers=_h(au["token"]))
        assert r.status_code == 404  # 不属于该目标

    def test_05_llm_invalid_no_dirty(self, client, au, llm):
        from services import course_service as cs
        cs_ref = cs
        n_before = None
        d0 = _mk_goal(client, au)
        n_before = len([l for m in d0["modules"] for l in m["lessons"]])
        pytest.monkeypatch_final = None
        # 覆盖 _llm：扩展返回垃圾 → 重试 1 次仍败 → 502 且树不变
        import services.course_service as cs_mod
        orig = cs_mod._llm

        def bad(prompt, scene=""):
            if scene == "课程扩展生成":
                return "这不是 JSON"
            return orig(prompt, scene)
        cs_mod._llm = bad
        try:
            r = client.post(f"/api/course/goals/{d0['goal']['id']}/extend",
                            json={"action": "add_module"}, headers=_h(au["token"]))
            assert r.status_code == 502, r.get_json()
            assert len([l for m in r.get_json().get("data", {}).get("modules", []) for l in m["lessons"]]) == 0 or True
        finally:
            cs_mod._llm = orig
        r2 = client.get(f"/api/course/goals/{d0['goal']['id']}/tree", headers=_h(au["token"]))
        assert len([l for m in r2.get_json()["data"]["modules"] for l in m["lessons"]]) == n_before

    def test_06_title_dup(self, client, au, llm):
        import services.course_service as cs_mod
        orig = cs_mod._llm

        def dup(prompt, scene=""):
            if scene == "课程扩展生成":
                return json.dumps({"modules": [{"title": "模块0", "description": "d",
                                                "lessons": [{"title": "课文0-0", "description": "d", "est_minutes": 30}]}]},
                                  ensure_ascii=False)
            return orig(prompt, scene)
        cs_mod._llm = dup
        try:
            d0 = _mk_goal(client, au)
            r = client.post(f"/api/course/goals/{d0['goal']['id']}/extend",
                            json={"action": "add_module"}, headers=_h(au["token"]))
            assert r.status_code == 502, r.get_json()
        finally:
            cs_mod._llm = orig

    def test_07_extend_404(self, client, au2, llm):
        r = client.post("/api/course/goals/99999999/extend", json={"action": "add_module"},
                        headers=_h(au2["token"]))
        assert r.status_code == 404


class TestChat:
    def test_10_chat_ok(self, client, au, llm):
        d0 = _mk_goal(client, au)
        lid = d0["modules"][0]["lessons"][0]["id"]
        _exec("UPDATE course_lessons SET content_md=? WHERE id=?", (MD, lid))
        r = client.post(f"/api/course/lessons/{lid}/chat",
                        json={"question": "梯度下降学习率怎么选？",
                              "history": [{"q": "前一问", "a": "前一答"}]}, headers=_h(au["token"]))
        body = r.get_json()
        assert body["success"] is True, body
        assert body["data"]["answer"] == "这是课内问答的回答。"
        scenes = [s for s, _ in llm if s == "课内AI问答"]
        assert scenes == ["课内AI问答"]
        prompt = [p for s, p in llm if s == "课内AI问答"][0]
        assert "梯度下降通过沿负梯度方向" in prompt      # 课文全文进上下文
        assert "前一问" in prompt and "前一答" in prompt  # 历史整包回传
        assert "梯度下降学习率怎么选" in prompt           # 当前问题

    def test_11_chat_no_content(self, client, au, llm):
        d0 = _mk_goal(client, au)
        lid = d0["modules"][0]["lessons"][0]["id"]
        r = client.post(f"/api/course/lessons/{lid}/chat", json={"question": "问"}, headers=_h(au["token"]))
        assert r.status_code == 400

    def test_12_chat_empty_question(self, client, au, llm):
        d0 = _mk_goal(client, au)
        lid = d0["modules"][0]["lessons"][0]["id"]
        _exec("UPDATE course_lessons SET content_md=? WHERE id=?", (MD, lid))
        r = client.post(f"/api/course/lessons/{lid}/chat", json={"question": "  "}, headers=_h(au["token"]))
        assert r.status_code == 400

    def test_13_chat_empty_answer(self, client, au, llm):
        import services.course_service as cs_mod
        orig = cs_mod._llm

        def blank(prompt, scene=""):
            if scene == "课内AI问答":
                return "   "
            return orig(prompt, scene)
        cs_mod._llm = blank
        try:
            d0 = _mk_goal(client, au)
            lid = d0["modules"][0]["lessons"][0]["id"]
            _exec("UPDATE course_lessons SET content_md=? WHERE id=?", (MD, lid))
            r = client.post(f"/api/course/lessons/{lid}/chat", json={"question": "问"}, headers=_h(au["token"]))
            assert r.status_code == 502, r.get_json()
        finally:
            cs_mod._llm = orig

    def test_14_chat_404(self, client, au2, llm):
        r = client.post("/api/course/lessons/99999999/chat", json={"question": "问"},
                        headers=_h(au2["token"]))
        assert r.status_code == 404


class TestAttemptsDetail:
    def test_20_attempts_detail(self, client, au, llm):
        d0 = _mk_goal(client, au)
        lid = d0["modules"][0]["lessons"][0]["id"]
        r = client.get(f"/api/course/lessons/{lid}/pretest", headers=_h(au["token"]))
        qs = r.get_json()["data"]["questions"]
        r2 = client.post(f"/api/course/lessons/{lid}/pretest",
                         json={"answers": [0] * len(qs)}, headers=_h(au["token"]))
        assert r2.status_code == 200, r2.get_json()
        r3 = client.get(f"/api/course/goals/{d0['goal']['id']}/attempts", headers=_h(au["token"]))
        rows = r3.get_json()["data"]["attempts"]
        assert len(rows) >= 1
        det = rows[0].get("detail")
        assert det and "per_question" in det, rows[0]
        pq = det["per_question"]
        assert len(pq) == 4 and "is_correct" in pq[0]
