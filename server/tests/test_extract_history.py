# -*- coding: utf-8 -*-
"""知识点提取历史 + 上课历史课件端点断言（画图硬纪律轮 2026-11-18）。

覆盖三块：
1. /api/course/lessons/<lid>/extracts GET/POST（留档、幂等、清洗、越权）
2. board_lesson.list_lesson_courses（source_ref 归属记法、LIKE 前缀撞号负例、
   只回有页的课、uid 隔离）
3. /api/board/lesson_courses 端点（参数闸 + 登录态数据）

运行方式（server/ 目录）：python -m pytest tests/test_extract_history.py -v
仿 test_course_notes 范式：LLM monkeypatch 只造课程结构，不碰真实模型。
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "exh" + uuid.uuid4().hex[:8]
PW = "pass1234"


def _mods():
    return json.dumps({"modules": [{"title": f"模块{i}", "description": f"说明{i}",
                                    "lessons": [{"title": f"课文{i}-{j}", "description": "d",
                                                 "est_minutes": 30} for j in range(3)]}
                                   for i in range(3)], "n": 3}, ensure_ascii=False)


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
    uids = [r[0] for r in conn.execute(
        "SELECT user_id FROM users WHERE username IN (?, ?)", (U, U + "x")).fetchall()]
    for uid in uids:
        conn.execute("DELETE FROM micro_scenes WHERE course_id IN "
                     "(SELECT id FROM micro_courses WHERE user_id=?)", (uid,))
    for sql in (
        "DELETE FROM lesson_extracts WHERE user_id=?",
        "DELETE FROM micro_courses WHERE user_id=?",
        "DELETE FROM course_tests WHERE lesson_id IN (SELECT l.id FROM course_lessons l "
        "JOIN course_modules m ON l.module_id=m.id JOIN learning_goals g ON m.goal_id=g.id WHERE g.user_id=?)",
        "DELETE FROM course_lessons WHERE module_id IN (SELECT id FROM course_modules "
        "WHERE goal_id IN (SELECT id FROM learning_goals WHERE user_id=?))",
        "DELETE FROM course_modules WHERE goal_id IN (SELECT id FROM learning_goals WHERE user_id=?)",
        "DELETE FROM learning_goals WHERE user_id=?",
    ):
        for uid in uids:
            conn.execute(sql, (uid,))
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def llm():
    from services import course_service as cs
    m = pytest.MonkeyPatch()
    m.setattr(cs, "_llm", lambda prompt, scene="": _mods())
    yield m
    m.undo()


@pytest.fixture(scope="module")
def lid(client, au, llm):
    """建目标取第一篇课文 id（extracts 归属的课文）。"""
    subj = "提取历史学科" + uuid.uuid4().hex[:6]
    r = client.post("/api/course/goals",
                    json={"subject_name": subj, "goal_text": "断言提取历史与上课历史"},
                    headers=_h(au["token"]))
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["modules"][0]["lessons"][0]["id"]


@pytest.fixture(scope="module")
def myuid(client, au):
    conn = _conn()
    try:
        row = conn.execute("SELECT user_id FROM users WHERE username = ?", (U,)).fetchone()
    finally:
        conn.close()
    return str(row[0])


# ---------------- 1. extracts 端点 ----------------

def test_x1_post_then_get(client, au, lid):
    r = client.post(f"/api/course/lessons/{lid}/extracts",
                    json={"items": [{"name": "子空间"}, {"name": "基的个数"}]},
                    headers=_h(au["token"]))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["data"]["added"] == 2
    g = client.get(f"/api/course/lessons/{lid}/extracts", headers=_h(au["token"]))
    assert g.status_code == 200
    items = g.get_json()["data"]["items"]
    names = {it["name"] for it in items}
    assert names == {"子空间", "基的个数"}
    assert all(it["time"] for it in items)          # 留档带时间可回看
    assert items[0]["name"] == "基的个数"            # id DESC：新提的在前


def test_x2_same_name_idempotent(client, au, lid):
    """同名重提不重复记（UNIQUE 三元组幂等跳过），也不报错。"""
    r = client.post(f"/api/course/lessons/{lid}/extracts",
                    json={"items": [{"name": "子空间"}]}, headers=_h(au["token"]))
    assert r.status_code == 200
    assert r.get_json()["data"]["added"] == 0
    g = client.get(f"/api/course/lessons/{lid}/extracts", headers=_h(au["token"]))
    names = [it["name"] for it in g.get_json()["data"]["items"]]
    assert names.count("子空间") == 1


def test_x3_wash_bad_names(client, au, lid):
    """空名/纯空白清洗后无有效名 → 400；超长名截到 120 落档。"""
    r = client.post(f"/api/course/lessons/{lid}/extracts",
                    json={"items": [{"name": ""}, {"name": "   "}]},
                    headers=_h(au["token"]))
    assert r.status_code == 400
    longname = "长" * 300
    r2 = client.post(f"/api/course/lessons/{lid}/extracts",
                     json={"items": [{"name": longname}]}, headers=_h(au["token"]))
    assert r2.status_code == 200
    g = client.get(f"/api/course/lessons/{lid}/extracts", headers=_h(au["token"]))
    saved = [it["name"] for it in g.get_json()["data"]["items"] if it["name"].startswith("长长")]
    assert saved and len(saved[0]) == 120


def test_x4_items_shape_gates(client, au, lid):
    for bad in ({}, {"items": []}, {"items": "子空间"}):
        r = client.post(f"/api/course/lessons/{lid}/extracts", json=bad,
                        headers=_h(au["token"]))
        assert r.status_code == 400, bad


def test_x5_cross_user_isolated(client, au, au2, lid):
    """越权双条件隔离：别人的课文，读写都 404。"""
    r = client.get(f"/api/course/lessons/{lid}/extracts", headers=_h(au2["token"]))
    assert r.status_code == 404
    r2 = client.post(f"/api/course/lessons/{lid}/extracts",
                     json={"items": [{"name": "蹭一条"}]}, headers=_h(au2["token"]))
    assert r2.status_code == 404


def test_x6_unknown_lesson(client, au):
    g = client.get("/api/course/lessons/99999999/extracts", headers=_h(au["token"]))
    assert g.status_code == 404


# ---------------- 2. list_lesson_courses 服务层 ----------------

def _mk_course(uid, course_lesson_id, title="课堂课件"):
    from services import board_lesson as BL
    lk = uuid.uuid4().hex[:16]
    c = BL.ensure_course(uid, lk, title=title, course_lesson_id=course_lesson_id)
    assert c.get("success"), c
    return lk, c["course"]["id"]


def _add_scene(course_id, seq=1):
    conn = _conn()
    try:
        conn.execute("INSERT INTO micro_scenes (course_id, seq, scene_type, title, "
                     "content_json, status) VALUES (?, ?, 'board', '页一', '{}', 'done')",
                     (course_id, seq))
        conn.commit()
    finally:
        conn.close()


def test_c1_ref_written_and_queryable(client, au, myuid, lid):
    """建课记归属 → 反查命中；无页课被过滤（上了半页没存成不算历史）。"""
    lk, cid = _mk_course(myuid, str(lid))
    from services import board_lesson as BL
    assert BL.list_lesson_courses(myuid, str(lid)) == []      # pages=0 不出
    _add_scene(cid)
    out = BL.list_lesson_courses(myuid, str(lid))
    assert len(out) == 1 and out[0]["lesson_key"] == lk
    assert out[0]["pages"] == 1 and out[0]["title"] == "课堂课件"


def test_c2_prefix_collision_negative(client, au, myuid):
    """前缀撞号负例：课文 88001 的查询绝不能命中 880011 的课。"""
    lk_a, cid_a = _mk_course(myuid, "88001", title="课A")
    lk_b, cid_b = _mk_course(myuid, "880011", title="课B")
    _add_scene(cid_a)
    _add_scene(cid_b)
    from services import board_lesson as BL
    keys_a = {c["lesson_key"] for c in BL.list_lesson_courses(myuid, "88001")}
    keys_b = {c["lesson_key"] for c in BL.list_lesson_courses(myuid, "880011")}
    assert keys_a == {lk_a} and keys_b == {lk_b}
    # 清理两门撞号测试课（不属于本用户数据链路）
    conn = _conn()
    try:
        conn.execute("DELETE FROM micro_scenes WHERE course_id IN (?, ?)", (cid_a, cid_b))
        conn.execute("DELETE FROM micro_courses WHERE id IN (?, ?)", (cid_a, cid_b))
        conn.commit()
    finally:
        conn.close()


def test_c3_bad_inputs_isolated(client, au, myuid):
    from services import board_lesson as BL
    assert BL.list_lesson_courses(myuid, "abc") == []          # 非数字直接空
    assert BL.list_lesson_courses(myuid, "") == []
    other = "u" + uuid.uuid4().hex[:12]
    lk, cid = _mk_course(other, "99001")
    _add_scene(cid)
    assert BL.list_lesson_courses(myuid, "99001") == []        # uid 隔离
    assert len(BL.list_lesson_courses(other, "99001")) == 1
    conn = _conn()
    try:
        conn.execute("DELETE FROM micro_scenes WHERE course_id = ?", (cid,))
        conn.execute("DELETE FROM micro_courses WHERE id = ?", (cid,))
        conn.commit()
    finally:
        conn.close()


# ---------------- 3. /api/board/lesson_courses 端点 ----------------

def test_e1_endpoint_gate_and_data(client, au, au2, myuid, lid):
    r = client.get("/api/board/lesson_courses?lesson_id=abc", headers=_h(au["token"]))
    assert r.status_code == 400
    lk, cid = _mk_course(myuid, str(lid), title="断言端点课")
    _add_scene(cid)
    g = client.get(f"/api/board/lesson_courses?lesson_id={lid}", headers=_h(au["token"]))
    assert g.status_code == 200
    courses = g.get_json()["data"]["courses"]
    assert any(c["lesson_key"] == lk and c["title"] == "断言端点课" for c in courses)
    # 别人的登录态查同一课文：uid 隔离，查不到
    g2 = client.get(f"/api/board/lesson_courses?lesson_id={lid}", headers=_h(au2["token"]))
    assert g2.status_code == 200
    assert all(c["lesson_key"] != lk for c in g2.get_json()["data"]["courses"])
