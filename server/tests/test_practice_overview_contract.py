# -*- coding: utf-8 -*-
"""u8 练·科目统计首页 /api/practice/overview 契约测试（Flask test client）。

运行方式（server/ 目录）：python -m pytest tests/test_practice_overview_contract.py -v
覆盖：鉴权 401、新用户真实空数据（内层 success 双层契约）、科目统计口径
（-1 未评估哨兵不参与均值、笔记关联、练习/错题计数）、推荐位排序
（未评估优先→掌握度升序 top3）、错题待强化提示追加、summary 汇总。
种子数据用独立测试用户直连库写入（user_id 唯一，不污染正式数据）。
"""
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "u8ov_" + uuid.uuid4().hex[:8]
PW = "pass1234"


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


def _h(token):
    return {"Authorization": "Bearer " + token}


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


class TestOverviewSequence:
    """有序用例序列：空数据 → 建科建点 → 统计口径 → 练习/错题联动。"""

    MOD = "U8OV" + uuid.uuid4().hex[:6]

    def test_1_requires_auth(self, client):
        assert client.get("/api/practice/overview").status_code == 401

    def test_2_new_user_real_empties(self, client, au):
        r = client.get("/api/practice/overview", headers=_h(au["token"]))
        assert r.status_code == 200
        outer = r.get_json()
        assert outer["success"] is True
        d = outer["data"]
        # 桥协议双层契约（P032 教训）：内层必须显式带 success
        assert d["success"] is True
        assert d["subjects"] == []
        assert d["summary"] == {
            "subjects": 0, "knowledge_total": 0,
            "practice_total": 0, "errors_pending_total": 0,
        }

    def test_3_subject_stats_and_sentinel(self, client, au):
        tk, uid = au["token"], au["user_id"]
        subject = f"{self.MOD}_统计科"
        r = client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk))
        assert r.status_code == 200
        # 先清同科目旧点，保证用例可重跑
        conn0 = _conn()
        try:
            c0 = conn0.cursor()
            c0.execute("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name = ?", (uid, subject))
            conn0.commit()
        finally:
            conn0.close()
        # batch-save 真实语义：DB 建点 mastery=-1（UI 回填 50 是展示层），直连补写分数造齐四种口径
        r = client.post("/api/knowledge/batch-save", json={
            "filePath": f"u8ov_{self.MOD}.md", "subject": subject,
            "knowledgePoints": [
                {"name": f"{self.MOD}点50", "description": "d"},
                {"name": f"{self.MOD}点50b", "description": "d"},
            ],
        }, headers=_h(tk))
        assert r.get_json()["data"]["saved_count"] == 2
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE knowledge_points SET mastery_score = 50 "
                "WHERE user_id = ? AND subject_name = ? AND point_name NOT LIKE ? AND point_name NOT LIKE ?",
                (uid, subject, "%未评", "%点90"))
            for name, score in ((f"{self.MOD}点未评", -1), (f"{self.MOD}点90", 90)):
                cur.execute(
                    "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) "
                    "VALUES (?,?,?,?,?)", (uid, subject, name, "d", score))
            conn.commit()
        finally:
            conn.close()

        r = client.get("/api/practice/overview", headers=_h(tk))
        d = r.get_json()["data"]
        assert len(d["subjects"]) == 1
        s = d["subjects"][0]
        assert s["subject"] == subject
        assert s["knowledge_count"] == 4
        assert s["unrated_count"] == 1
        assert s["knowledge_mastered"] == 1  # 仅 90 分点 >=80
        assert s["avg_mastery"] == round((50 + 50 + 90) / 3)  # -1 不参与均值
        assert s["notes_count"] == 1  # batch-save 关联了 1 条笔记
        assert s["best_point"]["name"] == f"{self.MOD}点90"
        assert s["worst_point"]["name"] in (f"{self.MOD}点50", f"{self.MOD}点50b")
        assert s["practice_count"] == 0 and s["errors_total"] == 0
        assert s["last_practice_time"] is None
        # 推荐：未评估优先 → 掌握度升序，最多 3 个
        rec = s["recommend"]
        assert len(rec) == 3
        assert rec[0]["name"] == f"{self.MOD}点未评"
        assert "尚未评估" in rec[0]["reason"]
        assert rec[1]["score"] == 50 and "%" in rec[1]["reason"]
        assert d["summary"]["subjects"] == 1 and d["summary"]["knowledge_total"] == 4

    def test_4_practice_and_error_counts(self, client, au):
        tk, uid = au["token"], au["user_id"]
        subject = f"{self.MOD}_统计科"
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ? LIMIT 1",
                (uid, subject))
            kp_id = cur.fetchone()[0]
            for days_ago, ok_ in ((0, 1), (0, 0), (9, 1)):
                ts = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
                cur.execute(
                    "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                    "question_content, user_answer, is_correct, practice_time) VALUES (?,?,?,?,?,?,?)",
                    (uid, subject, kp_id, "q", "a", ok_, ts))
            # 2 道待强化错题（review_status=0）+ 1 道已复习
            cur.execute(
                "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                "practice_record_id, review_status) VALUES (?,?,?,?,?)",
                (uid, subject, kp_id, 1, 0))
            cur.execute(
                "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                "practice_record_id, review_status) VALUES (?,?,?,?,?)",
                (uid, subject, kp_id, 2, 0))
            cur.execute(
                "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                "practice_record_id, review_status) VALUES (?,?,?,?,?)",
                (uid, subject, kp_id, 1, 1))
            conn.commit()
        finally:
            conn.close()

        r = client.get("/api/practice/overview", headers=_h(tk))
        s = r.get_json()["data"]["subjects"][0]
        assert s["practice_count"] == 3
        assert s["practice_this_week"] == 2  # 9 天前那条不计本周
        assert s["last_practice_time"] is not None
        assert s["errors_total"] == 3
        assert s["errors_pending"] == 2
        # 待强化错题提示追加到首条推荐（unrated 点仍排首位）
        assert f"另有 2 道错题待强化" in s["recommend"][0]["reason"]
        assert r.get_json()["data"]["summary"]["practice_total"] == 3
        assert r.get_json()["data"]["summary"]["errors_pending_total"] == 2

    def test_5_other_user_isolation(self, client):
        u2 = "u8ov_x_" + uuid.uuid4().hex[:8]
        r = client.post("/api/auth/register", json={"username": u2, "password": PW})
        tk2 = r.get_json()["data"]["token"]
        r = client.get("/api/practice/overview", headers=_h(tk2))
        d = r.get_json()["data"]
        assert d["subjects"] == [] and d["summary"]["knowledge_total"] == 0
