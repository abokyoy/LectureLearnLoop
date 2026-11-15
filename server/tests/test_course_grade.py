# -*- coding: utf-8 -*-
"""course 判分落库链断言（Task 6，R3/R7 核心；LLM/相似度全 monkeypatch，DB 独立测试数据）。

运行方式（server/ 目录）：python -m pytest tests/test_course_grade.py -v
断言口径：
- 逐题流水：practice_records 行数 = 题数（grade_pack 不烧 LLM，纯判分）；
- 答错自动入池：error_questions 行数 = 答错题数，同题再错不堆行；
- kp 自动建档：精确名复用、rank_matches 阈值内复用、否则新建（created=True）；
- FSRS 折叠：错题行 'error' 逐题 apply、kp 按组折叠 apply（min rating + 正确率封顶）；
- course_attempts：传 test_id/goal_id 才落一行，score/detail_json 正确；
- kp 建档失败不阻断落库（kp_id=None 流水照常）。
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes_courses as rc  # noqa: E402
from services import fsrs_service as F  # noqa: E402


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


def _pack(n=4, kp_base="kp"):
    return [{"stem": f"{kp_base}题干{i}", "options": [f"甲{i}", f"乙{i}", f"丙{i}", f"丁{i}"],
             "answer_index": i % 4, "kp_name": f"{kp_base}点{i}", "explanation": f"解析{i}"}
            for i in range(n)]


@pytest.fixture()
def env(monkeypatch):
    """独立测试用户+学科；rank_matches 默认打桩为空（走建档路径，防真实 embedding 依赖）。"""
    uid = "cgg" + uuid.uuid4().hex[:8]
    subject = "测试学科CG" + uuid.uuid4().hex[:6]
    try:
        import similarity_matcher as sm
        monkeypatch.setattr(sm, "rank_matches", lambda **kw: [])
    except Exception:  # noqa: BLE001
        pass
    yield uid, subject
    conn = _conn()
    try:
        for sql, args in (
            ("DELETE FROM course_attempts WHERE user_id=?", (uid,)),
            ("DELETE FROM practice_records WHERE user_id=?", (uid,)),
            ("DELETE FROM error_questions WHERE user_id=?", (uid,)),
            ("DELETE FROM knowledge_points WHERE user_id=?", (uid,)),
        ):
            conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _count(conn, table, uid):
    return conn.execute(f"SELECT COUNT(1) FROM {table} WHERE user_id=?", (uid,)).fetchone()[0]


def test_grade_pack_records(env):
    """流水行数=题数、错题入池行数=答错数、返回值结构完整。"""
    uid, subject = env
    pack = _pack(4)
    answers = [0, 1, 0, 0]  # answer_index 依次 0,1,2,3：题0/1 对，题2/3 错 → 0.5
    out = rc.grade_pack(uid, subject, pack, answers)
    assert out["score"] == 0.5
    assert len(out["per_question"]) == 4
    assert out["per_question"][2]["is_correct"] is False
    assert out["per_question"][0]["user_answer"] == 0
    assert out["mode"] == "full"
    conn = _conn()
    try:
        assert _count(conn, "practice_records", uid) == 4
        assert _count(conn, "error_questions", uid) == 2
        # 未传 test_id/goal_id 不落 attempt 行
        assert _count(conn, "course_attempts", uid) == 0
    finally:
        conn.close()


def test_grade_full_score_concise(env):
    uid, subject = env
    out = rc.grade_pack(uid, subject, _pack(4), [q["answer_index"] for q in _pack(4)])
    assert out["score"] == 1.0 and out["mode"] == "concise"
    conn = _conn()
    try:
        assert _count(conn, "error_questions", uid) == 0
    finally:
        conn.close()


def test_bad_answers_rejected(env):
    uid, subject = env
    with pytest.raises(ValueError):
        rc.grade_pack(uid, subject, _pack(4), [0, 1])          # 数量不匹配
    with pytest.raises(ValueError):
        rc.grade_pack(uid, subject, _pack(4), [0, 1, 2, 9])    # 选项越界
    with pytest.raises(ValueError):
        rc.grade_pack(uid, subject, _pack(4), [0, 1, 2, "x"])  # 非 int


def test_kp_autocreate_and_exact_reuse(env):
    """建档后同名精确复用；不重复建行。"""
    uid, subject = env
    pack = _pack(4, kp_base="新建")
    rc.grade_pack(uid, subject, pack, [0, 0, 0, 0])  # 全错也无妨，重点是 kp 建档
    conn = _conn()
    try:
        ids1 = [r[0] for r in conn.execute(
            "SELECT id FROM knowledge_points WHERE user_id=? AND subject_name=? ORDER BY id",
            (uid, subject)).fetchall()]
        assert len(ids1) == 4
        # 自动建档描述口径
        desc, mscore = conn.execute(
            "SELECT core_description, mastery_score FROM knowledge_points WHERE id=?",
            (ids1[0],)).fetchone()
        assert desc == "目标导向学习自动建档：新建点0"
        assert int(mscore) == 50
        rc.grade_pack(uid, subject, pack, [0, 0, 0, 0])
        ids2 = [r[0] for r in conn.execute(
            "SELECT id FROM knowledge_points WHERE user_id=? AND subject_name=? ORDER BY id",
            (uid, subject)).fetchall()]
        assert ids2 == ids1  # 精确名复用，未新建
    finally:
        conn.close()


def test_kp_similarity_reuse(env):
    """精确名未命中但 rank_matches 阈值内命中 → 复用既有 kp，不建档。"""
    uid, subject = env
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) "
            "VALUES (?,?,?,?,50)", (uid, subject, "梯度下降法", "既有描述", ))
        conn.commit()
        pid = cur.lastrowid
    finally:
        conn.close()
    import similarity_matcher as sm
    # 打桩 rank_matches：阈值内命中既有 kp（复用公共函数入参口径，不依赖真实 embedding）
    orig = sm.rank_matches

    def fake_rank(question=None, knowledge_points=None, cfg=None, top_k=None, min_score=0.0):
        if min_score > 0.5:
            return []
        return [{"id": p["id"], "score": 0.9, "point_name": p["point_name"]} for p in knowledge_points]
    sm.rank_matches = fake_rank
    try:
        pack = [{"stem": "s", "options": ["a", "b", "c", "d"], "answer_index": 0,
                 "kp_name": "梯度下降", "explanation": "e"}] * 2
        conn = _conn()
        try:
            kp_id, created = rc._resolve_kp_id(conn, uid, subject, "梯度下降")
            assert kp_id == pid and created is False
            cnt = conn.execute("SELECT COUNT(1) FROM knowledge_points WHERE user_id=?",
                               (uid,)).fetchone()[0]
            assert cnt == 1
        finally:
            conn.close()
    finally:
        sm.rank_matches = orig


def test_apply_review_called(env, monkeypatch):
    """'error' 逐题、'kp' 按组折叠各调用一次；参数含 mastery_cap。"""
    uid, subject = env
    calls = []
    orig = F.apply_review

    def spy(kind, ref_id, user_id, rating, now=None, conn=None, mastery_cap=None):
        calls.append((kind, ref_id, rating, mastery_cap))
        return orig(kind, ref_id, user_id, rating, now=now, conn=conn, mastery_cap=mastery_cap)
    monkeypatch.setattr(F, "apply_review", spy)
    pack = _pack(4, kp_base="FSRS")
    # 题0、1 同组答对/答错混合，题2、3 各独立 kp
    pack[1]["kp_name"] = pack[0]["kp_name"]
    answers = [pack[0]["answer_index"], 0, 0, pack[3]["answer_index"]]
    out = rc.grade_pack(uid, subject, pack, answers)
    kp_calls = [c for c in calls if c[0] == "kp"]
    err_calls = [c for c in calls if c[0] == "error"]
    assert len(kp_calls) == 3  # 3 个 kp 组
    assert len(err_calls) == 2  # 2 道答错
    # 折叠取最保守：混合组 rating=1（Again）；封顶=组内正确率
    grp = next(c for c in kp_calls if c[1] is not None and c[3] == 50)
    assert grp[2] == 1


def test_wrong_again_no_pile(env):
    """同题再答错：错题行不堆叠，流水照常追加（save_practice_record 内部口径）。"""
    uid, subject = env
    pack = _pack(1, kp_base="堆")
    wrong_ans = (pack[0]["answer_index"] + 1) % 4
    rc.grade_pack(uid, subject, pack, [wrong_ans])
    rc.grade_pack(uid, subject, pack, [wrong_ans])
    conn = _conn()
    try:
        assert _count(conn, "practice_records", uid) == 2
        assert _count(conn, "error_questions", uid) == 1
    finally:
        conn.close()


def test_attempt_row_written(env):
    """传 goal/test 上下文时落 course_attempts 一行，score 与 detail_json 正确。"""
    uid, subject = env
    conn = _conn()
    try:
        cur = conn.execute("INSERT INTO learning_goals (user_id, subject_name, goal_text, status) "
                           "VALUES (?,?,'attempt测试','ready')", (uid, subject))
        gid = cur.lastrowid
        conn.execute("INSERT INTO course_tests (kind, lesson_id, questions_json) VALUES ('pretest', NULL, '[]')")
        conn.commit()
        tid = conn.execute("SELECT id FROM course_tests WHERE kind='pretest' ORDER BY id DESC LIMIT 1",
                           ).fetchone()[0]
    finally:
        conn.close()
    pack = _pack(4, kp_base="ATT")
    out = rc.grade_pack(uid, subject, pack, [0, 1, 0, 0],  # 对2/4 → 0.5
                        kind="pretest", goal_id=gid, test_id=tid, lesson_title="课文X")
    conn = _conn()
    try:
        row = conn.execute("SELECT goal_id, test_id, kind, lesson_title, score, detail_json "
                           "FROM course_attempts WHERE user_id=?", (uid,)).fetchone()
        assert row is not None
        assert row[0] == gid and row[1] == tid and row[2] == "pretest"
        assert row[3] == "课文X" and abs(row[4] - 0.5) < 1e-9
        detail = json.loads(row[5])
        assert len(detail["per_question"]) == 4
    finally:
        conn.execute("DELETE FROM learning_goals WHERE id=?", (gid,))
        conn.execute("DELETE FROM course_tests WHERE id=?", (tid,))
        conn.commit()
        conn.close()


def test_kp_resolve_fail_not_block(env, monkeypatch):
    """建档链路异常（rank/INSERT 均不可用）→ kp_id=None 流水照常，不阻断判分。"""
    uid, subject = env
    def boom(conn, user_id, subj, name):
        raise RuntimeError("建档炸了")
    monkeypatch.setattr(rc, "_resolve_kp_id", boom)
    out = rc.grade_pack(uid, subject, _pack(3, kp_base="炸"), [0, 0, 0])  # 题0对 → 1/3
    assert abs(out["score"] - 1 / 3) < 1e-9
    conn = _conn()
    try:
        assert _count(conn, "practice_records", uid) == 3
        rows = conn.execute("SELECT knowledge_point_id FROM practice_records WHERE user_id=?",
                            (uid,)).fetchall()
        assert all(r[0] is None for r in rows)
    finally:
        conn.close()
