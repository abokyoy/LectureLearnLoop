# -*- coding: utf-8 -*-
"""u9 记·科目统计首页 /api/memory/overview 契约测试（Flask test client）。

运行方式（server/ 目录）：python -m pytest tests/test_memory_overview_contract.py -v
覆盖：鉴权 401、新用户真实空数据（内层 success 双层契约）、待记/已掌握口径
（-1 未评估计入待记、不参与均值与最强点）、错题卡片与复习状态、错得最多
（同题干 ≥2）、推荐复习排序（null 熟练度优先→升序）、summary 汇总、隔离。
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "u9ov_" + uuid.uuid4().hex[:8]
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


class TestMemoryOverview:
    MOD = "U9OV" + uuid.uuid4().hex[:6]

    def test_1_requires_auth(self, client):
        assert client.get("/api/memory/overview").status_code == 401

    def test_2_new_user_real_empties(self, client, au):
        r = client.get("/api/memory/overview", headers=_h(au["token"]))
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["success"] is True  # 双层契约（P032）
        assert d["subjects"] == []
        assert d["summary"] == {
            "subjects": 0, "to_learn_total": 0,
            "error_cards_total": 0, "errors_pending_total": 0,
        }

    def test_3_full_stats(self, client, au):
        tk, uid = au["token"], au["user_id"]
        subject = f"{self.MOD}_记忆科"
        assert client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk)).status_code == 200
        conn = _conn()
        try:
            cur = conn.cursor()
            # 4 知识点：-1 未评 / 30 弱 / 90 强 / 50 弱
            pid = {}
            for name, score in (("未评", -1), ("弱30", 30), ("强90", 90), ("中50", 50)):
                cur.execute(
                    "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) "
                    "VALUES (?,?,?,?,?)", (uid, subject, f"{self.MOD}点{name}", "d", score))
                pid[name] = cur.lastrowid if hasattr(cur, "lastrowid") else None
            cur.execute(
                "SELECT id, point_name FROM knowledge_points WHERE user_id = ? AND subject_name = ?", (uid, subject))
            kpid = {n.split(self.MOD)[1]: i for i, n in cur.fetchall()}
            # 练习记录：题干 A 答错 2 次 + 题干 B 答错 1 次
            rec_ids = []
            for q, ok_ in (("题干甲问法", 0), ("题干甲问法", 0), ("题干乙问法", 0)):
                cur.execute(
                    "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                    "question_content, user_answer, is_correct) VALUES (?,?,?,?,?,?)",
                    (uid, subject, kpid["点未评"], q, "a", ok_))
                cur.execute(
                    "SELECT id FROM practice_records WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
                rec_ids.append(cur.fetchone()[0])
            # 错题卡：2×题干甲（1 条 pending prof=10，1 条 reviewed）、1×题干乙（pending prof=null）
            cur.execute(
                "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                "practice_record_id, review_status, current_proficiency) VALUES (?,?,?,?,?,?)",
                (uid, subject, kpid["点未评"], rec_ids[0], 0, 10))
            cur.execute(
                "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                "practice_record_id, review_status, current_proficiency) VALUES (?,?,?,?,?,?)",
                (uid, subject, kpid["点未评"], rec_ids[1], 1, 70))
            cur.execute(
                "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                "practice_record_id, review_status, current_proficiency) VALUES (?,?,?,?,?,?)",
                (uid, subject, kpid["点弱30"], rec_ids[2], 0, None))
            conn.commit()
        finally:
            conn.close()

        r = client.get("/api/memory/overview", headers=_h(tk))
        d = r.get_json()["data"]
        s = next(x for x in d["subjects"] if x["subject"] == subject)
        # 知识点口径
        assert s["knowledge_total"] == 4
        assert s["to_learn_count"] == 3        # -1、30、50（<80 含未评估）
        assert s["unrated_count"] == 1
        assert s["mastered_count"] == 1
        assert s["weak_count"] == 2            # 30、50（0<=x<80）
        assert s["avg_mastery"] == round((30 + 90 + 50) / 3)
        assert s["strongest_point"]["name"] == f"{self.MOD}点强90"
        # 最薄弱 = ranked[0]（未评优先）
        assert s["weakest_point"]["name"] == f"{self.MOD}点未评"
        # 推荐记忆：未评首位，其后升序（30 → 50），恰好 3 条
        names = [x["name"] for x in s["recommend_points"]]
        assert names == [f"{self.MOD}点未评", f"{self.MOD}点弱30", f"{self.MOD}点中50"]
        # 错题口径
        assert s["error_cards"] == 3
        assert s["errors_pending"] == 2
        assert s["errors_reviewed"] == 1
        assert s["avg_error_proficiency"] == 40  # (10+70)/2，null 不入均值（精确断言见 test_4）
        # 错得最多：题干甲 2 条错题
        assert s["most_frequent_error"]["question"] == "题干甲问法"
        assert s["most_frequent_error"]["count"] == 2
        # 推荐复习：null 熟练度排前，其次 10
        rec_e = s["recommend_errors"]
        assert len(rec_e) == 2
        assert rec_e[0]["question"] == "题干乙问法" and rec_e[0]["proficiency"] is None
        assert "建议优先" in rec_e[0]["reason"]
        assert rec_e[1]["question"] == "题干甲问法" and rec_e[1]["proficiency"] == 10
        # summary
        assert d["summary"]["to_learn_total"] >= 3
        assert d["summary"]["errors_pending_total"] >= 2

    def test_4_avg_error_proficiency_excludes_null(self, client, au):
        tk = au["token"]
        r = client.get("/api/memory/overview", headers=_h(tk))
        d = r.get_json()["data"]
        s = next(x for x in d["subjects"] if x["subject"].endswith("_记忆科"))
        # pending 两条为 10 与 null；全表 3 条（10/70/null）→ avg=40
        assert s["avg_error_proficiency"] == 40

    def test_5_other_user_isolation(self, client):
        u2 = "u9ov_x_" + uuid.uuid4().hex[:8]
        r = client.post("/api/auth/register", json={"username": u2, "password": PW})
        tk2 = r.get_json()["data"]["token"]
        d = client.get("/api/memory/overview", headers=_h(tk2)).get_json()["data"]
        assert d["subjects"] == [] and d["summary"]["to_learn_total"] == 0
