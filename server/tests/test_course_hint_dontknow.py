# -*- coding: utf-8 -*-
"""题包提示（hint）与「我不会」（-1 协议）断言（2026-11-12 题包提示与我不会轮）。

运行方式（server/ 目录）：python -m pytest tests/test_course_hint_dontknow.py -v
断言口径：
- 三种出题 prompt 均含 hint 要求句 +「严禁指出」剧透纪律 + 契约样例 hint 字段；
- validate_questions：hint 透传、超 _Q_HINT_MAX 截断、缺失/非法降 ""（整包不因缺 hint 拒收）；
- grade_pack：-1 合法且判错（负下标雷：save_practice_record 收到 "我不会" 文本而非末选项）、
  per_question.user_answer 保持 -1、course_attempts detail 计入、全 -1 → score 0。
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes_courses as rc  # noqa: E402
from services import course_service as cs  # noqa: E402


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


def _q(i=0, **over):
    q = {"stem": f"提示轮题干{i}", "options": ["甲", "乙", "丙", "丁"],
         "answer_index": i % 4, "kp_name": f"提示轮点{i}", "explanation": f"解析{i}",
         "hint": f"术语{i}是人话解释，从概念方向思考。"}
    q.update(over)
    return q


# ---------------------------------------------------------------- 生成侧

@pytest.mark.parametrize("kind", ["pretest", "postquiz", "moduleexam"])
def test_prompts_require_hint(kind):
    p = cs._TEST_PROMPTS[kind]
    assert "hint" in p
    assert "严禁指出或暗示哪个选项正确" in p  # 剧透纪律句
    assert '"hint": "术语解释与思考提示"' in p  # 契约 JSON 样例同步


def test_validate_hint_passthrough_and_truncate():
    long_hint = "哈" * (cs._Q_HINT_MAX + 50)
    out = cs.validate_questions([_q(0), _q(1, hint=long_hint), _q(2, hint=None)], n_min=1)
    assert out[0]["hint"] == "术语0是人话解释，从概念方向思考。"
    assert len(out[1]["hint"]) == cs._Q_HINT_MAX  # 超长截断不拒收
    assert out[2]["hint"] == ""  # 缺失/None 降空串（软字段）


def test_validate_missing_hint_not_rejected():
    """旧契约（无 hint 字段）整包照常通过——模型漏写不报废重试成本。"""
    raw = [_q(i) for i in range(4)]
    for q in raw:
        q.pop("hint")
    out = cs.validate_questions(raw, n_min=4, n_max=10)
    assert all(q["hint"] == "" for q in out)


# ---------------------------------------------------------------- 判分链

def _pack(n=4, kp_base="hd"):
    return [_q(i, kp_name=f"{kp_base}点{i}", stem=f"{kp_base}题干{i}") for i in range(n)]


@pytest.fixture()
def env(monkeypatch):
    """独立测试用户+学科；rank_matches 打桩为空（走建档路径，防真实 embedding 依赖）。"""
    uid = "chd" + uuid.uuid4().hex[:8]
    subject = "测试学科HD" + uuid.uuid4().hex[:6]
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
            ("DELETE FROM learning_goals WHERE user_id=?", (uid,)),
        ):
            conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def test_minus_one_valid_and_wrong(env):
    """-1 合法（不再抛选项非法）、判错、user_answer 保持 -1、全 -1 → score 0 + full。"""
    uid, subject = env
    pack = _pack(4)
    out = rc.grade_pack(uid, subject, pack, [-1, -1, -1, -1])
    assert out["score"] == 0.0 and out["mode"] == "full"
    assert all(p["user_answer"] == -1 and p["is_correct"] is False for p in out["per_question"])
    conn = _conn()
    try:
        assert conn.execute("SELECT COUNT(1) FROM error_questions WHERE user_id=?",
                            (uid,)).fetchone()[0] == 4  # 我不会=按错题入薄弱点/错题本
    finally:
        conn.close()


def test_out_of_range_still_rejected(env):
    """-1 放开不波及真越界：-2/4/9/非 int 仍拒收（守住 test_course_grade 同口径）。"""
    uid, subject = env
    for bad in ([-2, 0, 0, 0], [0, 1, 2, 4], [0, 1, 2, 9], [0, 1, 2, "x"], [True, 0, 0, 0]):
        with pytest.raises(ValueError):
            rc.grade_pack(uid, subject, _pack(4), bad)


def test_negative_index_trap_fixed(env, monkeypatch):
    """核心雷：ans=-1 时 opts[-1] 会静默取末选项——流水必须收到文本「我不会」。"""
    uid, subject = env
    captured = []
    kms = rc.get_kms()
    orig = kms.practice_manager.save_practice_record

    def spy(subject_, kp_id, stem, user_answer, correct, user_id, *a, **kw):
        captured.append((stem, user_answer, correct))
        return None  # 断掉后续 get_error_id_for_record 分支（本测只钉流水入参）
    monkeypatch.setattr(kms.practice_manager, "save_practice_record", spy)
    pack = _pack(4, kp_base="雷")
    out = rc.grade_pack(uid, subject, pack, [-1, pack[1]["answer_index"], -1, 3])
    assert len(captured) == 4
    assert captured[0][1] == "我不会" and captured[0][2] is False
    assert captured[2][1] == "我不会"
    assert captured[1][1] == pack[1]["options"][pack[1]["answer_index"]]  # 正常路径不受影响
    assert captured[3][1] == "丁" and captured[3][2] is True
    assert out["per_question"][0]["user_answer"] == -1  # 返回值仍保持数值 -1（可 JSON 落库）
    monkeypatch.setattr(kms.practice_manager, "save_practice_record", orig)


def test_minus_one_in_attempt_detail(env):
    """-1 计入 course_attempts detail（回读 user_answer=-1）。"""
    uid, subject = env
    conn = _conn()
    try:
        cur = conn.execute("INSERT INTO learning_goals (user_id, subject_name, goal_text, status) "
                           "VALUES (?,?,'hint轮attempt','ready')", (uid, subject))
        gid = cur.lastrowid
        conn.execute("INSERT INTO course_tests (kind, lesson_id, questions_json) VALUES ('postquiz', NULL, '[]')")
        conn.commit()
        tid = conn.execute("SELECT id FROM course_tests WHERE kind='postquiz' ORDER BY id DESC LIMIT 1",
                           ).fetchone()[0]
    finally:
        conn.close()
    pack = _pack(4, kp_base="DET")
    rc.grade_pack(uid, subject, pack, [-1, 0, -1, 0],
                  kind="postquiz", goal_id=gid, test_id=tid, lesson_title="提示轮课文")
    conn = _conn()
    try:
        row = conn.execute("SELECT detail_json, score FROM course_attempts WHERE user_id=?",
                           (uid,)).fetchone()
        detail = json.loads(row[0])
        answers = [p["user_answer"] for p in detail["per_question"]]
        assert answers == [-1, 0, -1, 0]
        assert json.loads(json.dumps(detail))  # -1 可 JSON 往返
    finally:
        conn.execute("DELETE FROM learning_goals WHERE id=?", (gid,))
        conn.execute("DELETE FROM course_tests WHERE id=?", (tid,))
        conn.commit()
        conn.close()
