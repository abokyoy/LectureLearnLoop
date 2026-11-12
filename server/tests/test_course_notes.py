# -*- coding: utf-8 -*-
"""课文追问笔记树端点 + assign kind='text' 断言（追问笔记树轮 2026-11-12）。

运行方式（server/ 目录）：python -m pytest tests/test_course_notes.py -v
LLM 全 monkeypatch（仿 test_course_extract 范式）；追问讲解场景 prompt 留痕供
图文并茂纪律与父链上下文断言；空回答 → 502 且不落库（LLM 输出不可信原则）。
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "cgn" + uuid.uuid4().hex[:8]
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

# 追问讲解场景：答案可控 + prompt 留痕（空回答/图文纪律/父链断言共用）
FOLLOW = {"answer": "这是追问回答：\n```mermaid\ngraph TB\n  A[损失] --> B[参数]\n```",
          "capture": []}


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
    # 库内 user_id 是 uuid（非用户名）：先回查真实 uid 再按域清理
    uids = [r[0] for r in conn.execute(
        "SELECT user_id FROM users WHERE username IN (?, ?)", (U, U + "x")).fetchall()]
    for sql in (
        "DELETE FROM lesson_notes WHERE user_id=?",
        "DELETE FROM course_attempts WHERE user_id=?",
        "DELETE FROM course_tests WHERE lesson_id IN (SELECT l.id FROM course_lessons l "
        "JOIN course_modules m ON l.module_id=m.id JOIN learning_goals g ON m.goal_id=g.id WHERE g.user_id=?)",
        "DELETE FROM course_lessons WHERE module_id IN (SELECT id FROM course_modules "
        "WHERE goal_id IN (SELECT id FROM learning_goals WHERE user_id=?))",
        "DELETE FROM course_modules WHERE goal_id IN (SELECT id FROM learning_goals WHERE user_id=?)",
        "DELETE FROM learning_goals WHERE user_id=?",
        "DELETE FROM practice_records WHERE user_id=?",
        "DELETE FROM error_questions WHERE user_id=?",
        "DELETE FROM knowledge_points WHERE user_id=?",
    ):
        for uid in uids:
            conn.execute(sql, (uid,))
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def llm():
    from services import course_service as cs
    import similarity_matcher as sm
    FOLLOW["capture"].clear()

    def fake(prompt, scene=""):
        FOLLOW["capture"].append((scene, prompt))
        if scene == "生成课程结构":
            return _mods()
        if scene in ("课程前测出题", "课程后练出题"):
            return _qpack(4)
        if scene == "生成课程课文":
            return MD
        if scene == "课文追问讲解":
            if FOLLOW["answer"] is None:
                raise AssertionError("不应走到该场景")
            return FOLLOW["answer"]
        raise AssertionError("unexpected scene " + scene)
    m = pytest.MonkeyPatch()
    m.setattr(cs, "_llm", fake)
    m.setattr(sm, "rank_matches", lambda **kw: [])
    yield m
    m.undo()


def _mk_lesson(client, au):
    """建目标取第一篇课文 id。"""
    subj = "笔记学科" + uuid.uuid4().hex[:6]
    r = client.post("/api/course/goals", json={"subject_name": subj, "goal_text": "断言追问笔记树流程"},
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
    """走完前测生成课文，课文正文在库（追问前置条件）。"""
    r = client.get(f"/api/course/lessons/{lid}/pretest", headers=_h(au["token"]))
    assert r.status_code == 200, r.get_json()
    answers = [q["answer_index"] for q in _db_pack(lid, "pretest")]
    r2 = client.post(f"/api/course/lessons/{lid}/pretest", json={"answers": answers},
                     headers=_h(au["token"]))
    assert r2.status_code == 200, r2.get_json()
    return r2.get_json()["data"]


def _ready_lesson(client, au):
    return _mk_lesson(client, au)  # 调用方自行 _pass_pretest


def _note_count(lid, uid):
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM lesson_notes WHERE lesson_id = ? AND user_id = ?",
                            (lid, str(uid))).fetchone()[0]
    finally:
        conn.close()


def _post_note(client, tok, lid, **body):
    return client.post(f"/api/course/lessons/{lid}/notes", json=body, headers=_h(tok))


def _put_note(client, tok, nid, **body):
    return client.put(f"/api/course/notes/{nid}", json=body, headers=_h(tok))


class TestNotesBasics:
    def test_01_list_empty(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        r = client.get(f"/api/course/lessons/{lid}/notes", headers=_h(au["token"]))
        body = r.get_json()
        assert r.status_code == 200 and body["data"]["notes"] == []

    def test_02_list_404_foreign(self, client, au, au2, llm):
        lid = _mk_lesson(client, au)
        r = client.get(f"/api/course/lessons/{lid}/notes", headers=_h(au2["token"]))
        assert r.status_code == 404, r.get_json()

    def test_03_create_needs_content(self, client, au, llm):
        lid = _mk_lesson(client, au)  # status=new，正文未生成
        r = _post_note(client, au["token"], lid, anchor_text="甲", question="能追问吗")
        assert r.status_code == 400, r.get_json()
        assert "正文" in r.get_json()["error"]

    def test_04_create_ok(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        r = _post_note(client, au["token"], lid, anchor_text="梯度下降", question="为什么学习率重要？")
        body = r.get_json()
        assert r.status_code == 200, body
        n = body["data"]["note"]
        assert n["id"] and n["lesson_id"] == lid and n["parent_id"] is None
        assert n["anchor_text"] == "梯度下降" and n["question"] == "为什么学习率重要？"
        assert n["answer_md"].startswith("这是追问回答")
        assert _note_count(lid, au["user_id"]) == 1

    def test_05_question_empty_rejected(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        r = _post_note(client, au["token"], lid, anchor_text="甲", question="   ")
        assert r.status_code == 400, r.get_json()
        assert _note_count(lid, au["user_id"]) == 0

    def test_06_anchor_overlong_rejected(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        r = _post_note(client, au["token"], lid, anchor_text="锚" * 601, question="超长锚")
        assert r.status_code == 400, r.get_json()
        r600 = _post_note(client, au["token"], lid, anchor_text="锚" * 600, question="边界锚")
        assert r600.status_code == 200, r600.get_json()

    def test_07_parent_id_invalid(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        for bad in ("abc", -1, True, 0):
            r = _post_note(client, au["token"], lid, anchor_text="甲", question="父非法", parent_id=bad)
            assert r.status_code == 400, (bad, r.get_json())

    def test_08_parent_foreign_lesson(self, client, au, llm):
        lid_a = _mk_lesson(client, au); _pass_pretest(client, au, lid_a)
        lid_b = _mk_lesson(client, au); _pass_pretest(client, au, lid_b)
        n_a = _post_note(client, au["token"], lid_a, anchor_text="甲", question="A课笔记").get_json()["data"]["note"]
        r = _post_note(client, au["token"], lid_b, anchor_text="乙", question="跨课挂父", parent_id=n_a["id"])
        assert r.status_code == 400, r.get_json()

    def test_09_nested_tree(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        top = _post_note(client, au["token"], lid, anchor_text="学习率", question="什么是学习率").get_json()["data"]["note"]
        kid = _post_note(client, au["token"], lid, anchor_text="步长", question="那它取多大合适", parent_id=top["id"]).get_json()["data"]["note"]
        assert kid["parent_id"] == top["id"]
        rows = client.get(f"/api/course/lessons/{lid}/notes", headers=_h(au["token"])).get_json()["data"]["notes"]
        assert [n["id"] for n in rows] == sorted(n["id"] for n in rows)  # 平铺按 id 升序，前端组树
        assert {n["id"]: n["parent_id"] for n in rows} == {top["id"]: None, kid["id"]: top["id"]}

    def test_10_empty_answer_502_no_row(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        keep = FOLLOW["answer"]
        FOLLOW["answer"] = "   "
        try:
            r = _post_note(client, au["token"], lid, anchor_text="甲", question="空回答")
            assert r.status_code == 502, r.get_json()
            assert "生成失败" in r.get_json()["error"]
        finally:
            FOLLOW["answer"] = keep
        assert _note_count(lid, au["user_id"]) == 0

    def test_11_credits_402(self, client, au, llm, monkeypatch):
        import credits_service as cr
        from services import course_service as cs

        def boom(prompt, scene=""):
            if scene == "课文追问讲解":
                raise cr.InsufficientCreditsError(2.5)
            FOLLOW["capture"].append((scene, prompt))
            if scene == "生成课程结构":
                return _mods()
            if scene == "课程前测出题":
                return _qpack(4)
            if scene == "生成课程课文":
                return MD
            raise AssertionError("unexpected scene " + scene)
        monkeypatch.setattr(cs, "_llm", boom)
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        r = _post_note(client, au["token"], lid, anchor_text="甲", question="积分不足")
        body = r.get_json()
        assert r.status_code == 402, body
        assert body.get("credits_insufficient") is True and body.get("credit_balance") == 2.5
        assert _note_count(lid, au["user_id"]) == 0

    def test_12_lesson_cap_500(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        conn = _conn()
        try:
            for i in range(500):
                conn.execute("INSERT INTO lesson_notes (user_id, lesson_id, anchor_text, question, answer_md) "
                             "VALUES (?,?,?,?,?)", (str(au["user_id"]), lid, "锚", f"灌入{i}", "a"))
            conn.commit()
        finally:
            conn.close()
        r = _post_note(client, au["token"], lid, anchor_text="甲", question="第501条")
        assert r.status_code == 400, r.get_json()
        assert "上限" in r.get_json()["error"]
        conn = _conn()
        conn.execute("DELETE FROM lesson_notes WHERE lesson_id = ?", (lid,))
        conn.commit()
        conn.close()

    def test_13_question_truncated(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        r = _post_note(client, au["token"], lid, anchor_text="甲", question="问" * 2500)
        assert r.status_code == 200, r.get_json()
        assert len(r.get_json()["data"]["note"]["question"]) == 2000


class TestNoteEdit:
    def _note(self, client, au):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        return lid, _post_note(client, au["token"], lid, anchor_text="梯度下降", question="原问题").get_json()["data"]["note"]

    def test_20_put_ok(self, client, au, llm):
        lid, n = self._note(client, au)
        r = _put_note(client, au["token"], n["id"], question="改后的问题", answer_md="改后的回答")
        body = r.get_json()
        assert r.status_code == 200, body
        assert body["data"]["note"]["question"] == "改后的问题"
        assert body["data"]["note"]["answer_md"] == "改后的回答"
        assert body["data"]["note"]["anchor_text"] == "梯度下降"  # 锚跟问题走，不可改

    def test_21_put_empty_question(self, client, au, llm):
        lid, n = self._note(client, au)
        assert _put_note(client, au["token"], n["id"], question="  ").status_code == 400

    def test_22_put_answer_overlong(self, client, au, llm):
        lid, n = self._note(client, au)
        assert _put_note(client, au["token"], n["id"], answer_md="答" * 20001).status_code == 400

    def test_23_put_no_fields(self, client, au, llm):
        lid, n = self._note(client, au)
        assert _put_note(client, au["token"], n["id"]).status_code == 400

    def test_24_put_foreign_404(self, client, au, au2, llm):
        lid, n = self._note(client, au)
        assert _put_note(client, au2["token"], n["id"], question="越权改").status_code == 404
        # 越权不落：原内容未动
        row = client.get(f"/api/course/lessons/{lid}/notes", headers=_h(au["token"])).get_json()["data"]["notes"][0]
        assert row["question"] == "原问题"

    def test_25_put_missing_404(self, client, au, llm):
        assert _put_note(client, au["token"], 99999999, question="不存在").status_code == 404


class TestFollowupPromptDiscipline:
    def test_30_prompt_has_anchor_and_rich_md_rules(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        FOLLOW["capture"].clear()
        _post_note(client, au["token"], lid, anchor_text="学习率决定每步步长", question="为什么？").get_json()
        scene, prompt = [c for c in FOLLOW["capture"] if c[0] == "课文追问讲解"][-1]
        assert "学习率决定每步步长" in prompt          # 锚点原文交模型
        assert "图文并茂" in prompt and "mermaid" in prompt and "$" in prompt
        assert 'subgraph sg1["标题"]' in prompt      # 写图纪律与课文同源（裸标题括号实弹轮 2026-11-12）
        assert "为什么？" in prompt

    def test_31_parent_ctx_max_3_layers(self, client, au, llm):
        lid = _mk_lesson(client, au)
        _pass_pretest(client, au, lid)
        prev = None
        qs = [f"祖{i}问题标记" for i in range(5)]
        for i, q in enumerate(qs):
            body = dict(anchor_text="锚", question=q)
            if prev:
                body["parent_id"] = prev
            prev = _post_note(client, au["token"], lid, **body).get_json()["data"]["note"]["id"]
        FOLLOW["capture"].clear()
        _post_note(client, au["token"], lid, anchor_text="锚", question="叶子新问", parent_id=prev)
        _, prompt = [c for c in FOLLOW["capture"] if c[0] == "课文追问讲解"][-1]
        assert "祖4问题标记" in prompt and "祖3问题标记" in prompt and "祖2问题标记" in prompt
        assert "祖1问题标记" not in prompt and "祖0问题标记" not in prompt  # 只带上 3 层


class TestAssignText:
    def test_40_assign_ok_label_and_store(self, client, au, llm):
        import services.lecture_board as LB
        long_text = "梯度下降通过沿负梯度方向迭代更新参数最小化损失函数，" * 10  # 远超 24 字
        r = client.post("/api/board/assign", json={"kind": "text", "text": long_text}, headers=_h(au["token"]))
        body = r.get_json()
        assert r.status_code == 200 and body["success"], body
        assert body["data"]["kind"] == "text"
        assert len(body["data"]["label"]) <= 25  # 提示条限长 + 省略号（同 error/kp 口径）
        a = LB.get_assign(au["user_id"])
        assert a and a["kind"] == "text" and a["raw_text"]  # 原文随指派存储（指导语要用）

    def test_41_assign_text_empty_rejected(self, client, au, llm):
        import services.lecture_board as LB
        LB.set_assign(au["user_id"], "text", 7, "旧指派", raw_text="旧原文")  # 先立一个
        r = client.post("/api/board/assign", json={"kind": "text", "text": "  "}, headers=_h(au["token"]))
        assert r.get_json()["success"] is False
        assert LB.get_assign(au["user_id"])["id"] == 7  # 拒收不覆写

    def test_42_assign_invalid_kind_rejected(self, client, au2, llm):
        import services.lecture_board as LB
        r = client.post("/api/board/assign", json={"kind": "video", "text": "甲"}, headers=_h(au2["token"]))
        j = r.get_json()
        assert j["success"] is False and "kind" in j["error"]
        assert LB.get_assign(au2["user_id"]) is None

    def test_43_assign_get_inject_consume(self, client, au, llm):
        import services.lecture_board as LB
        r = client.post("/api/board/assign", json={"kind": "text", "text": "学习率决定每步步长"},
                        headers=_h(au["token"]))
        assert r.get_json()["success"], r.get_json()
        d = client.get("/api/board/assign", headers=_h(au["token"])).get_json()["data"]
        assert d["assign"]["kind"] == "text"  # GET 不消费
        text = LB.execute_tool("get_lesson_material", {}, au["user_id"])
        assert text.startswith("📌网页指定讲解"), text[:60]
        assert "学习率决定每步步长" in text
        text2 = LB.execute_tool("get_lesson_material", {}, au["user_id"])
        assert "📌" not in text2  # 一次性消费

    def test_44_assign_overwrite(self, client, au, llm):
        import services.lecture_board as LB
        client.post("/api/board/assign", json={"kind": "text", "text": "第一段"}, headers=_h(au["token"]))
        client.post("/api/board/assign", json={"kind": "text", "text": "第二段"}, headers=_h(au["token"]))
        a = LB.get_assign(au["user_id"])
        assert a["raw_text"] == "第二段"  # 学生改口覆写
        text = LB.execute_tool("get_lesson_material", {}, au["user_id"])
        assert "第二段" in text and "第一段" not in text
