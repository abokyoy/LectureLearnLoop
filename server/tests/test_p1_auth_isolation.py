"""
P1 多用户隔离验收测试。

运行方式（server/ 目录）：python -m pytest tests/ -v
覆盖：
1. HTTP 认证流（注册/登录/401/409/JWT）
2. Manager 层双账号渗透：A 建的知识点/错题/科目，B 不可见、不可改
（不依赖 LLM：直接走 save/merge 路径）
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from knowledge_management import KnowledgeManagementSystem  # noqa: E402


UA = "pen_tester_" + uuid.uuid4().hex[:6]
UB = "pen_tester_" + uuid.uuid4().hex[:6]


@pytest.fixture(scope="module")
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _register(client, username):
    r = client.post("/api/auth/register", json={"username": username, "password": "pass1234"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["token"]


class TestAuthFlow:
    def test_register_and_login(self, client):
        assert client.post("/api/auth/register", json={"username": UA, "password": "pass1234"}).status_code == 200
        dup = client.post("/api/auth/register", json={"username": UA, "password": "pass1234"})
        assert dup.status_code == 409
        r = client.post("/api/auth/login", json={"username": UA, "password": "pass1234"})
        assert r.status_code == 200 and r.get_json()["data"]["token"]

    def test_bad_password_401(self, client):
        r = client.post("/api/auth/login", json={"username": UA, "password": "wrong"})
        assert r.status_code == 401

    def test_me_requires_token(self, client):
        assert client.get("/api/auth/me").status_code == 401
        token = _register(client, UB)
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and r.get_json()["data"]["username"] == UB

    def test_weak_password_rejected(self, client):
        r = client.post("/api/auth/register", json={"username": "weak_" + uuid.uuid4().hex[:4], "password": "123"})
        assert r.status_code == 400


class TestUserIsolation:
    """Manager 层渗透：B 不能看到/修改 A 的数据"""

    @pytest.fixture(scope="class")
    def system(self):
        return KnowledgeManagementSystem(config.load_config())

    def test_cross_user_invisibility_and_immunity(self, system):
        subject = "渗透学科_" + uuid.uuid4().hex[:4]
        assert system.subject_manager.add_subject(subject, user_id=UA)
        kp_id = system.knowledge_manager.save_knowledge_point(
            subject, "知识点A独有", "只有用户A应该看到", user_id=UA
        )
        assert kp_id

        # 1) B 的科目列表不含 A 的科目
        assert subject not in system.subject_manager.get_user_subjects(user_id=UB)
        # 2) B 按学科查知识点为空
        assert system.get_knowledge_points_by_subject(subject, user_id=UB) == []
        # 3) A 自己可见
        pts = system.get_knowledge_points_by_subject(subject, user_id=UA)
        assert any(p["id"] == kp_id for p in pts)
        # 4) B 尝试 merge 到 A 的知识点 → 失败（且不得修改数据）
        ok = system.knowledge_manager.merge_to_existing_point(
            kp_id, {"point_name": "篡改", "core_description": "篡改"}, user_id=UB
        )
        assert ok is False
        merged = [p for p in system.get_knowledge_points_by_subject(subject, user_id=UA) if p["id"] == kp_id]
        assert merged[0]["point_name"] == "知识点A独有"
        # 5) B 的学科统计不含 A 的学科
        stats = {s["subject_name"] for s in system.get_subject_stats(user_id=UB)}
        assert subject not in stats
        # 6) A 的统计含 1 个知识点
        s_a = [s for s in system.get_subject_stats(user_id=UA) if s["subject_name"] == subject]
        assert s_a and s_a[0]["kp_count"] >= 1

    def test_proficiency_history_isolation(self, system):
        subject = "渗透学科B_" + uuid.uuid4().hex[:4]
        system.subject_manager.add_subject(subject, user_id=UA)
        kp_id = system.knowledge_manager.save_knowledge_point(subject, "点", "描述", user_id=UA)
        # 手工插入 A 的错题
        conn = system.db_manager.get_connection()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, question_content, user_answer, is_correct)
               VALUES (?, ?, ?, '题干A', '答案A', 0)""",
            (UA, subject, kp_id),
        )
        pr_id = cur.lastrowid
        cur.execute(
            """INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, practice_record_id, review_status, current_proficiency)
               VALUES (?, ?, ?, ?, 0, 20)""",
            (UA, subject, kp_id, pr_id),
        )
        eq_id = cur.lastrowid
        conn.commit()
        conn.close()

        # B 读取 A 错题的熟练度历史 → 空
        assert system.get_proficiency_history(eq_id, user_id=UB) == []
        # B 更新 A 错题熟练度 → 无效
        system.append_proficiency(eq_id, 80, user_id=UB)
        assert system.get_proficiency_history(eq_id, user_id=UA) == []
        # B 删除 A 错题 → 失败
        assert system.error_manager.delete_error_question(eq_id, user_id=UB) is False
        # A 操作正常
        system.append_proficiency(eq_id, 80, user_id=UA)
        hist = system.get_proficiency_history(eq_id, user_id=UA)
        assert len(hist) == 1 and hist[0][1] == 80
        assert system.error_manager.delete_error_question(eq_id, user_id=UA) is True
