# -*- coding: utf-8 -*-
"""course_service 课文生成 + 状态机断言（LLM 全 monkeypatch，DB 用独立测试数据）。

运行方式（server/ 目录）：python -m pytest tests/test_course_md.py -v
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import course_service as cs  # noqa: E402

MD = """# 课文标题

## 概览
本文讲解目标导向学习课文正文的生成契约，覆盖概念定义与典型例子，长度需要超过两百字下限以通过校验逻辑的分支判断测试。

## 核心概念
梯度下降通过沿负梯度方向迭代更新参数最小化损失函数，学习率决定每步步长，过大震荡过大不收敛。

## 范例
设 $f(x)=x^2$，从 $x_0=3$、$\\eta=0.1$ 出发迭代三步的数值演练过程与结果解释。

## 重点摘要
概念、公式、迭代过程三要素构成完整理解链条，缺一不可，正文以简短段落组织以上内容并留有余味。
""" * 2  # 保证 ≥200 字


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


@pytest.fixture()
def lesson_id():
    """造 目标→模块→课文 一行链，返回 (user_id, lesson_id)，用完清理。"""
    uid = "cgmd" + uuid.uuid4().hex[:8]
    conn = _conn()
    try:
        cur = conn.execute("INSERT INTO learning_goals (user_id, subject_name, goal_text, status) "
                           "VALUES (?,?,'测试目标','ready')", (uid, "MD科"))
        gid = cur.lastrowid
        cur = conn.execute("INSERT INTO course_modules (goal_id, ord, title) VALUES (?,1,'模块')", (gid,))
        mid = cur.lastrowid
        cur = conn.execute("INSERT INTO course_lessons (module_id, ord, title, description) "
                           "VALUES (?,1,'课文A','概要A')", (mid,))
        lid = cur.lastrowid
        conn.commit()
        yield uid, lid, gid
    finally:
        conn.execute("DELETE FROM course_lessons WHERE module_id IN "
                     "(SELECT id FROM course_modules WHERE goal_id=?)", (gid,))
        conn.execute("DELETE FROM course_modules WHERE goal_id=?", (gid,))
        conn.execute("DELETE FROM learning_goals WHERE id=?", (gid,))
        conn.commit()
        conn.close()


def test_validate_md_ok():
    out = cs.validate_lesson_md("```markdown\n" + MD + "\n```")
    assert out.startswith("# 课文标题")  # 围栏剥除
    assert "```" not in out


# ids 必须显式指定：默认 ID 会带上超长参数内容（含 `*`、换行等），在 Windows 下
# pytest 写缓存时报 setup error（2026-11-11 掉坑）
@pytest.mark.parametrize("bad", ["", "   ", "太短了" * 10, MD * 100],
                       ids=["empty", "blank", "too_short", "too_long"])
def test_validate_md_reject(bad):
    with pytest.raises(cs.CourseError):
        cs.validate_lesson_md(bad)


def test_generate_md_modes(monkeypatch):
    cap = []

    def fake(prompt, scene=""):
        cap.append(prompt)
        return MD
    monkeypatch.setattr(cs, "_llm", fake)
    out = cs.generate_lesson_md("机器学习", "过拟合", "概念概要", "full", ["正则化", "交叉验证"])
    assert out.startswith("# 课文标题")
    assert "过拟合" in cap[0] and "机器学习" in cap[0]
    assert "正则化" in cap[0]  # full 模式错题置顶素材进 prompt
    cs.generate_lesson_md("机器学习", "过拟合", "概要", "concise", [])
    assert "concise" in cap[1] or "摘要" in cap[1] or "要点" in cap[1]


def test_generate_md_retry_then_fail(monkeypatch):
    calls = []
    monkeypatch.setattr(cs, "_llm", lambda p, scene="": (calls.append(1), "短")[1])
    with pytest.raises(cs.CourseError):
        cs.generate_lesson_md("科", "题", "述", "full", [])
    assert len(calls) == 2


def test_advance_flow(lesson_id):
    uid, lid, _ = lesson_id
    conn = _conn()
    try:
        assert cs.advance_lesson(conn, lid, uid, "pretested") == "pretested"
        conn.commit()
        # 跳步拒绝：pretested → learned
        with pytest.raises(cs.CourseError):
            cs.advance_lesson(conn, lid, uid, "learned")
        # 回退拒绝
        with pytest.raises(cs.CourseError):
            cs.advance_lesson(conn, lid, uid, "new")
        # 原地幂等
        assert cs.advance_lesson(conn, lid, uid, "pretested") == "pretested"
        for nxt in ("content_ready", "learned", "done"):
            assert cs.advance_lesson(conn, lid, uid, nxt) == nxt
            conn.commit()
        row = conn.execute("SELECT status, done_time FROM course_lessons WHERE id=?", (lid,)).fetchone()
        assert row[0] == "done" and row[1]  # done_time 已写
        # 越权：他人 user_id 改不动
        with pytest.raises(cs.CourseError):
            cs.advance_lesson(conn, lid, uid + "x", "done")
        # 完成后不再前进
        with pytest.raises(cs.CourseError):
            cs.advance_lesson(conn, lid, uid, "content_ready")
    finally:
        conn.close()
