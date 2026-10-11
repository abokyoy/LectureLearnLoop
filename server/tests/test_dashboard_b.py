# -*- coding: utf-8 -*-
"""四期 B 组：工作台真实统计 + batch-save 科目校验验收测试（Flask test client）。

运行方式（server/ 目录）：python -m pytest tests/test_dashboard_b.py -v
覆盖：/api/dashboard/stats 鉴权与新用户真 0 值、保存知识点后统计联动、
batch-save 空/不存在科目拒绝且不 auto-create、显式建科后保存成功、
页面静态断言（假兜底下线、老流程硬编码清除）。
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "p4user_b_" + uuid.uuid4().hex[:6]
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


TPL = Path(__file__).resolve().parents[1] / "templates"


class TestDashboardStats:
    def test_stats_requires_auth(self, client):
        r = client.get("/api/dashboard/stats")
        assert r.status_code == 401

    def test_new_user_stats_are_real_zeros(self, client, au):
        r = client.get("/api/dashboard/stats", headers=_h(au["token"]))
        assert r.status_code == 200
        d = r.get_json()["data"]
        # 全新用户：一切从真实 DB 来，绝不允许 12/85%/156 假兜底
        assert d["materials_this_week"] == 0
        assert d["practice_accuracy"] is None
        assert d["knowledge_total"] == 0
        assert d["knowledge_mastered"] == 0
        assert d["subjects"] == 0
        assert d["recent_activities"] == []

    def test_stats_reflect_saved_knowledge(self, client, au):
        tk = au["token"]
        subject = "P4B学科_" + uuid.uuid4().hex[:4]
        r = client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk))
        assert r.status_code == 200
        r = client.post("/api/knowledge/batch-save", json={
            "filePath": f"p4b_note_{subject}.md", "subject": subject,
            "knowledgePoints": [
                {"name": "P4B概念甲", "description": "描述甲"},
                {"name": "P4B概念乙", "description": "描述乙"},
            ],
        }, headers=_h(tk))
        d = r.get_json()["data"]
        assert d["success"] and d["saved_count"] == 2

        r = client.get("/api/dashboard/stats", headers=_h(tk))
        s = r.get_json()["data"]
        assert s["knowledge_total"] == 2
        assert s["subjects"] == 1
        assert s["knowledge_mastered"] == 0  # mastery=50 < 80
        # batch-save find-or-create 登记了 notes → 本周学习资料数为真值
        assert s["materials_this_week"] == 1
        kinds = [a["kind"] for a in s["recent_activities"]]
        assert "note" in kinds


class TestBatchSaveSubjectGuard:
    def test_empty_subject_rejected(self, client, au):
        r = client.post("/api/knowledge/batch-save", json={
            "filePath": "x.md", "subject": "",
            "knowledgePoints": [{"name": "n", "description": "d"}],
        }, headers=_h(au["token"]))
        d = r.get_json()["data"]
        assert d["success"] is False and "科目" in d["error"]

    def test_nonexistent_subject_rejected_and_not_created(self, client, au):
        tk = au["token"]
        ghost = "P4B幽灵学科_" + uuid.uuid4().hex[:4]
        r = client.post("/api/knowledge/batch-save", json={
            "filePath": "y.md", "subject": ghost,
            "knowledgePoints": [{"name": "n1", "description": "d1"}],
        }, headers=_h(tk))
        d = r.get_json()["data"]
        assert d["success"] is False and "不存在" in d["error"]
        # 关键：不得 auto-create（原串写 bug 根因）
        r = client.get("/api/subjects", headers=_h(tk))
        assert ghost not in (r.get_json()["data"] or [])

    def test_existing_subject_saves(self, client, au):
        tk = au["token"]
        subject = "P4B学科2_" + uuid.uuid4().hex[:4]
        client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk))
        r = client.post("/api/knowledge/batch-save", json={
            "filePath": f"p4b2_{subject}.md", "subject": subject,
            "knowledgePoints": [{"name": "有效点", "description": "d"}],
        }, headers=_h(tk))
        d = r.get_json()["data"]
        assert d["success"] is True and d["saved_count"] == 1


class TestPageStatics:
    def test_dashboard_no_fake_defaults(self):
        text = (TPL / "pages" / "dashboard.html").read_text(encoding="utf-8")
        for fake in ("default(12)", "default('85%')", "default(156)", "default(85%)"):
            assert fake not in text, f"dashboard.html 仍残留假兜底 {fake}"
        assert "/api/dashboard/stats" in text

    def test_spa_layout_loads_dashboard_fragment(self):
        text = (TPL / "spa_layout.html").read_text(encoding="utf-8")
        # P1 改造后首帧为三元分支：存在未过期 pm_pending_point 旗标时先跳知识点落地页，否则去工作台
        assert "loadContent(pendingKp ? 'knowledge_point' : 'dashboard')" in text
        assert "loadContent('dashboard')" not in text  # 无旗标分支仍须走 dashboard（上面三元已覆盖）

    def test_learn_materials_no_hardcoded_subject(self):
        text = (TPL / "pages" / "learn_from_materials.html").read_text(encoding="utf-8")
        assert "subject: '机器学习'" not in text
        assert "subject:'机器学习'" not in text
        assert "chosenSubject" in text  # 已改为读面板用户选择
