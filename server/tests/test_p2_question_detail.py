# -*- coding: utf-8 -*-
"""P2 关联题目详情端点契约测试（Flask test client）。

运行方式（server/ 目录）：python -m pytest tests/test_p2_question_detail.py -v
覆盖：/api/knowledge/points/<pid>/question-detail 的流水聚合、错题信息与
reference_answer 口径（错题行优先/回退历史正确作答）、题型与选项还原、
启发式回退、参数校验与跨用户隔离。
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "p2qd_" + uuid.uuid4().hex[:8]
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


class TestP2QuestionDetail:
    MOD = "P2QD" + uuid.uuid4().hex[:6]
    PID = None

    def test_1_setup_records(self, client, au):
        tk, uid = au["token"], au["user_id"]
        subject = f"{self.MOD}_科"
        client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk))
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description) "
                "VALUES (?,?,?,?)", (uid, subject, f"{self.MOD}树遍历", "前中后序"))
            cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND point_name = ?",
                        (uid, f"{self.MOD}树遍历"))
            self.__class__.PID = cur.fetchone()[0]
            pid = self.__class__.PID
            # 题A：选择题 3 次流水（错→对→错），错题行带正确答案/解析/熟练度
            self.__class__.qa = f"{self.MOD}题A：树的先序遍历访问顺序是？A.根左右 B.左右根 C.左根右 D.根右左"
            rec_a = []
            for i, (ans, ok) in enumerate([("A", 0), ("B", 1), ("C", 0)]):
                cur.execute(
                    "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                    "question_content, user_answer, is_correct, question_type, options_json, practice_time) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, subject, pid, self.qa, ans, ok, "single",
                     '["根左右", "左右根", "左根右", "根右左"]', f"2026-10-0{i + 1} 08:00:00"))
                cur.execute("SELECT id FROM practice_records WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
                rec_a.append(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                "practice_record_id, review_status, current_proficiency, correct_answer, explanation) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (uid, subject, pid, rec_a[2], 0, 35, "A", "先序=根左右"))
            # 题B：简答题仅答对一次（无错题行）→ reference 回退历史正确作答
            self.__class__.qb = f"{self.MOD}题B：简述中序遍历的定义。"
            cur.execute(
                "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                "question_content, user_answer, is_correct, question_type, practice_time) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (uid, subject, pid, self.qb, "左根右递归", 1, "short", "2026-10-05 09:00:00"))
            # 题C：老数据无 question_type/options_json → 题干启发式回退
            self.__class__.qc = f"{self.MOD}题C：求 _ 的值。"
            cur.execute(
                "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                "question_content, user_answer, is_correct, practice_time) VALUES (?,?,?,?,?,?,?)",
                (uid, subject, pid, self.qc, "3", 1, "2026-10-06 10:00:00"))
            # 题A 收藏一行
            cur.execute(
                "INSERT INTO favorite_questions (user_id, subject_name, knowledge_point_id, question_content) VALUES (?,?,?,?)",
                (uid, subject, pid, self.qa))
            conn.commit()
        finally:
            conn.close()

    def _detail(self, client, tk, content):
        import urllib.parse
        r = client.get(f"/api/knowledge/points/{self.PID}/question-detail?content="
                       + urllib.parse.quote(content), headers=_h(tk))
        assert r.status_code == 200
        return r.get_json()["data"]

    def test_2_error_question_detail(self, client, au):
        d = self._detail(client, au["token"], self.qa)
        assert d["success"] is True
        q = d["question"]
        assert q["type"] == "single"
        assert q["options"] == ["根左右", "左右根", "左根右", "根右左"]
        assert q["practice_count"] == 3 and q["correct_count"] == 1
        assert q["is_favorite"] is True
        # 流水按时间降序：最新是第三次（C 答错）
        assert [bool(r["is_correct"]) for r in q["records"]] == [False, True, False]
        assert q["error"] and q["error"]["correct_answer"] == "A"
        assert q["error"]["explanation"] == "先序=根左右"
        assert q["error"]["current_proficiency"] == 35
        # reference 优先取错题行 correct_answer
        assert q["reference_answer"] == "A"

    def test_3_correct_only_question(self, client, au):
        d = self._detail(client, au["token"], self.qb)
        q = d["question"]
        assert d["success"] is True and q["error"] is None
        assert q["type"] == "short"
        # 无错题行 → 回退最近一次答对的 user_answer
        assert q["reference_answer"] == "左根右递归"
        assert q["is_favorite"] is False

    def test_4_legacy_row_heuristic(self, client, au):
        d = self._detail(client, au["token"], self.qc)
        q = d["question"]
        # 流水缺 type：题干含 "_" 启发式 → 填空题
        assert q["type"] == "fill"
        assert q["options"] == []

    def test_5_validation_and_isolation(self, client, au):
        # 缺题干
        r = client.get(f"/api/knowledge/points/{self.PID}/question-detail", headers=_h(au["token"]))
        assert r.get_json()["data"]["success"] is False
        # 无该题流水
        d = self._detail(client, au["token"], self.MOD + "不存在的题")
        assert d["success"] is False
        # 跨用户隔离：他人 token 查同点同题 → 无记录
        u2 = "p2qd_x_" + uuid.uuid4().hex[:8]
        tk2 = client.post("/api/auth/register", json={"username": u2, "password": PW}).get_json()["data"]["token"]
        d2 = self._detail(client, tk2, self.qa)
        assert d2["success"] is False

    def test_6_cleanup(self, client, au):
        uid = au["user_id"]
        conn = _conn()
        try:
            cur = conn.cursor()
            for tbl in ("favorite_questions", "error_questions", "practice_records", "knowledge_points"):
                cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (uid,))
            cur.execute("DELETE FROM user_subjects WHERE user_id = ?", (uid,))
            conn.commit()
        finally:
            conn.close()
