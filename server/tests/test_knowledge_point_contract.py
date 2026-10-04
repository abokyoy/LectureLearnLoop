# -*- coding: utf-8 -*-
"""u10 知识点详情直达页契约测试（Flask test client）。

运行方式（server/ 目录）：python -m pytest tests/test_knowledge_point_contract.py -v
覆盖：/fragments/knowledge_point 白名单可达、/detail 双层契约与统计口径
（错题数/收藏/笔记数/最近练习排序与条数上限）、不存在点与跨用户隔离、
/assessment 难度加权评分（纯计算无 LLM）与 mastery_score 落库、题答数量校验。
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "u10kp_" + uuid.uuid4().hex[:8]
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


class TestKnowledgePoint:
    MOD = "U10KP" + uuid.uuid4().hex[:6]
    PID = None  # test_2 建点后回填

    def test_1_fragment_registered(self, client, au):
        # 白名单 + 片段可达（含 data-pm-page 挂载标记与共享模块引用）
        r = client.get("/fragments/knowledge_point", headers=_h(au["token"]))
        assert r.status_code == 200
        body = r.get_json()
        assert body["success"] is True
        assert 'data-pm-page="knowledge_point"' in body["data"]
        assert "pm_pages.js" in body["data"]

    def test_2_detail_contract(self, client, au):
        tk, uid = au["token"], au["user_id"]
        subject = f"{self.MOD}_科"
        client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk))
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) "
                "VALUES (?,?,?,?,?)", (uid, subject, f"{self.MOD}排序算法", "先学原理再写题", 42))
            cur.execute(
                "SELECT id FROM knowledge_points WHERE user_id = ? AND point_name = ?",
                (uid, f"{self.MOD}排序算法"))
            self.__class__.PID = cur.fetchone()[0]
            pid = self.__class__.PID
            # 6 条练习记录：断言只回最近 5 条且按 practice_time 降序
            rec_ids = []
            for i in range(6):
                cur.execute(
                    "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                    "question_content, user_answer, is_correct, practice_time) VALUES (?,?,?,?,?,?,?)",
                    (uid, subject, pid, f"{self.MOD}题干{i}", "a", i % 2,
                     f"2026-09-{10 + i:02d} 08:00:00"))
                cur.execute(
                    "SELECT id FROM practice_records WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
                rec_ids.append(cur.fetchone()[0])
            # 2 条错题挂该点（practice_record_id 非空约束）
            for rid in rec_ids[:2]:
                cur.execute(
                    "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                    "practice_record_id, review_status, current_proficiency) VALUES (?,?,?,?,?,?)",
                    (uid, subject, pid, rid, 0, 20))
            conn.commit()
        finally:
            conn.close()

        r = client.get(f"/api/knowledge/points/{self.PID}/detail", headers=_h(tk))
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["success"] is True  # 双层契约（P032）
        det = d["detail"]
        assert det["name"] == f"{self.MOD}排序算法"
        assert det["mastery_score"] == 42
        assert det["subject_name"] == subject
        assert det["error_count"] == 2
        assert det["favorite_count"] == 0
        assert det["notes_count"] == 0
        rp = det["recent_practices"]
        assert len(rp) == 5  # LIMIT 5
        assert rp[0]["question"] == f"{self.MOD}题干5"  # practice_time 降序
        assert rp[-1]["question"] == f"{self.MOD}题干1"
        # is_correct 布尔化：i 奇存 1（对），偶存 0（错）→ 题干5 True，题干4 False
        assert rp[0]["is_correct"] is True
        assert rp[1]["is_correct"] is False

    def test_3_detail_missing_and_isolation(self, client, au):
        # 不存在的点：内层 success False（HTTP 仍 200，_ok 包装）
        r = client.get("/api/knowledge/points/99999999/detail", headers=_h(au["token"]))
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["success"] is False and "未找到" in d["error"]
        # 跨用户隔离：另注册用户不可见本测试点
        u2 = "u10kp_x_" + uuid.uuid4().hex[:8]
        tk2 = client.post("/api/auth/register", json={"username": u2, "password": PW}).get_json()["data"]["token"]
        d2 = client.get(f"/api/knowledge/points/{self.PID}/detail", headers=_h(tk2)).get_json()["data"]
        assert d2["success"] is False

    def test_4_assessment_fsrs_fold_scoring(self, client, au):
        tk, uid = au["token"], au["user_id"]
        questions = [
            {"question": "q1", "options": ["A1", "A2", "A3", "A4"], "correct_answer": "A", "difficulty": "容易", "explanation": "e1"},
            {"question": "q2", "options": ["B1", "B2", "B3", "B4"], "correct_answer": "B", "difficulty": "中等", "explanation": "e2"},
            {"question": "q3", "options": ["C1", "C2", "C3", "C4"], "correct_answer": "C", "difficulty": "困难", "explanation": "e3"},
        ]
        answers = ["A", "B", "D"]  # 对2错1 → 整批折叠 Again，正确率封顶 round(100*2/3)=67
        r = client.post(f"/api/knowledge/points/{self.PID}/assessment",
                        json={"questions": questions, "answers": answers}, headers=_h(tk))
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["success"] is True
        # FSRS 集成线回归（2026-10-01）：不再难度加权直写；非 Review 态派生值为空，
        # 写 min(原值, 封顶)=min(42,67)=42，原值保留
        assert d["mastery_score"] == 42
        assert d["correct_count"] == 2 and d["total_count"] == 3
        assert abs(d["accuracy"] - 2 / 3) < 1e-6
        dr = d["detailed_results"]
        assert len(dr) == 3
        assert dr[0]["is_correct"] is True and dr[2]["is_correct"] is False
        # 逐题 rating 回显：答对=Good(3)，答错=Again(1)（卡片四档/练习映射同源）
        assert dr[0]["rating"] == 3 and dr[1]["rating"] == 3 and dr[2]["rating"] == 1
        assert dr[2]["user_answer"] == "D" and dr[2]["correct_answer"] == "C"
        assert dr[0]["explanation"] == "e1"
        # DB 已回写（详情反映新分数）且曲线历史追加一条
        det = client.get(f"/api/knowledge/points/{self.PID}/detail", headers=_h(tk)).get_json()["data"]["detail"]
        assert det["mastery_score"] == 42
        curve = client.get(f"/api/kb/kp/{self.PID}/curve", headers=_h(tk)).get_json()["data"]
        assert curve["count"] >= 1
        assert curve["points"][-1]["mastery"] == 42

    def test_5_assessment_validation(self, client, au):
        tk = au["token"]
        # 题答数量不匹配
        r = client.post(f"/api/knowledge/points/{self.PID}/assessment",
                        json={"questions": [{"question": "q"}], "answers": []}, headers=_h(tk))
        d = r.get_json()["data"]
        assert d["success"] is False and "不匹配" in d["error"]
        # 不存在的点
        d2 = client.post("/api/knowledge/points/99999999/assessment",
                         json={"questions": [], "answers": []}, headers=_h(tk)).get_json()["data"]
        assert d2["success"] is False and "未找到" in d2["error"]

    def test_6_cleanup(self, client, au):
        # 清理探针数据（sources → points → records → errors → subjects），防污染其他测试
        uid = au["user_id"]
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN "
                "(SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ?)", (uid, f"{self.MOD}_科"))
            # FSRS 曲线历史随点清理（不留孤儿行，防污染后续统计）
            cur.execute(
                "DELETE FROM kp_proficiency_history WHERE knowledge_point_id IN "
                "(SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ?)", (uid, f"{self.MOD}_科"))
            cur.execute(
                "DELETE FROM error_proficiency_history WHERE error_question_id IN "
                "(SELECT id FROM error_questions WHERE user_id = ? AND subject_name = ?)", (uid, f"{self.MOD}_科"))
            cur.execute("DELETE FROM memory_cards WHERE user_id = ? AND subject_name = ?", (uid, f"{self.MOD}_科"))
            for t, col in (("knowledge_points", "subject_name"), ("practice_records", "subject_name"),
                           ("error_questions", "subject_name")):
                cur.execute(f"DELETE FROM {t} WHERE user_id = ? AND {col} = ?", (uid, f"{self.MOD}_科"))
            cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name = ?", (uid, f"{self.MOD}_科"))
            conn.commit()
        finally:
            conn.close()
