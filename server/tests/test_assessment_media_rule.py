# -*- coding: utf-8 -*-
"""v0.1.9 出题媒体规则与评估材料注入 契约测试（Flask test client，LLM 全部打桩）。

背景（用户反馈 2026-10-12）：出题模型没见过材料里的表却问「在表1-1中…」，学生无法作答。
用户裁定：熟练度评估通道注入关联笔记原文作出题材料；看表作答的题必须原样带表进题干。
覆盖：
- generate-assessment：无关联笔记 → prompt 不含材料块但含统一「表格与图片规则」；
  有关联笔记（打桩公共函数）→ prompt 注入「关联笔记内容」块且含表原文；
- quiz-generate：prompt 含统一媒体规则，旧「图片规则：学习内容中若含」单独文案已移除（防口径漂移）；
- generate-practice(analogy)：知识点练习 prompt 同样含统一媒体规则。

运行方式（server/ 目录）：python -m pytest tests/test_assessment_media_rule.py -v
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "v19mr_" + uuid.uuid4().hex[:8]
PW = "pass1234"
MOD = "V19MR" + uuid.uuid4().hex[:6]


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


def _assess_json():
    """10 道合法选择题 JSON（严格满足 generate-assessment 的 10 题×4 选项校验）。"""
    return json.dumps([{
        "question": f"{MOD}评估题{i + 1}？",
        "options": ["甲", "乙", "丙", "丁"],
        "correct_answer": "A",
        "difficulty": ["容易", "中等", "困难"][i % 3],
        "explanation": "甲正确",
    } for i in range(10)], ensure_ascii=False)


def _prac_json(n):
    arr = [{"type": "single", "question": f"{MOD}练习选择？",
            "options": ["甲", "乙", "丙", "丁"], "correct_answer": "A",
            "difficulty": "容易", "explanation": "甲正确"}]
    while len(arr) < n:
        arr.append({"type": "short", "question": f"{MOD}练习简答{len(arr) + 1}。",
                    "correct_answer": "要点一；要点二", "difficulty": "中等", "explanation": "略"})
    return json.dumps(arr, ensure_ascii=False)


class TestAssessmentMediaRule:
    PID = None
    RULE = "表格与图片规则"

    def test_1_seed_point(self, client, au):
        tk, uid = au["token"], au["user_id"]
        subject = f"{MOD}_科"
        client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk))
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description) "
                "VALUES (?,?,?,?)", (uid, subject, f"{MOD}特征", "描述里带 表1-1 字样"))
            cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND point_name = ?",
                        (uid, f"{MOD}特征"))
            self.__class__.PID = cur.fetchone()[0]
            # 举一反三所需的错题行（答错留痕口径同 P5 样板）
            cur.execute(
                "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                "question_content, user_answer, is_correct, question_type, practice_time) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (uid, subject, self.PID, f"{MOD}错题：在表1-1中特征X对应什么？", "B", 0, "single",
                 "2026-10-12 08:00:00"))
            cur.execute("SELECT id FROM practice_records WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
            rid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                "practice_record_id, review_status, current_proficiency, correct_answer) "
                "VALUES (?,?,?,?,?,?,?)", (uid, subject, self.PID, rid, 0, 10, "A"))
            conn.commit()
        finally:
            conn.close()

    def test_2_assessment_no_notes_has_rule(self, client, au, monkeypatch):
        """无关联笔记：不注入材料块，但统一媒体规则必须在 prompt 里（禁编造表/图）。"""
        import routes_bridge
        calls = []
        monkeypatch.setattr(routes_bridge, "_llm_call",
                            lambda p, c="": (calls.append(p), _assess_json())[1])
        d = client.post(f"/api/knowledge/points/{self.PID}/generate-assessment",
                        json={}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is True and len(d["questions"]) == 10
        assert self.RULE in calls[0]
        assert "关联笔记内容" not in calls[0]
        assert f"{MOD}特征" in calls[0]  # 知识点信息仍照常传入

    def test_3_assessment_with_notes_injects_material(self, client, au, monkeypatch):
        """有关联笔记（打桩公共函数）：材料块注入且表格原文可达模型。"""
        import routes_bridge
        table_md = "**表1-1 常见激活函数对比**\n| 激活函数 | 输出范围 | 是否饱和 |\n| --- | --- | --- |\n| ReLU | [0,+∞) | 否 |"
        monkeypatch.setattr(routes_bridge, "_collect_point_notes_text",
                            lambda kms, pid: f"笔记正文片段\n{table_md}")
        calls = []
        monkeypatch.setattr(routes_bridge, "_llm_call",
                            lambda p, c="": (calls.append(p), _assess_json())[1])
        d = client.post(f"/api/knowledge/points/{self.PID}/generate-assessment",
                        json={}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is True
        assert "关联笔记内容" in calls[0] and "表1-1 常见激活函数对比" in calls[0]
        assert self.RULE in calls[0]

    def test_4_quiz_generate_unified_rule(self, client, au, monkeypatch):
        """考卷通道：统一媒体规则取代旧「图片规则」单独文案（单一口径）。"""
        import routes_bridge
        calls = []
        monkeypatch.setattr(routes_bridge, "_llm_call",
                            lambda p, c="": (calls.append(p), _prac_json(1))[1])
        d = client.post("/api/practice/quiz-generate", headers=_h(au["token"]), json={
            "selected_text": f"{MOD}选段内容", "types": ["single"], "count": 1,
            "difficulty": "中等"}).get_json()["data"]
        assert d["success"] is True, d.get("error")
        assert self.RULE in calls[0]
        assert "**图片规则：** 学习内容中若含" not in calls[0]

    def test_5_point_practice_analogy_rule(self, client, au, monkeypatch):
        """举一反三通道：prompt 同样含统一媒体规则。"""
        import routes_bridge
        calls = []
        monkeypatch.setattr(routes_bridge, "_llm_call",
                            lambda p, c="": (calls.append(p), _prac_json(2))[1])
        d = client.post(f"/api/knowledge/points/{self.PID}/generate-practice",
                        json={"source": "analogy", "count": 2},
                        headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is True, d.get("error")
        assert self.RULE in calls[0]
        assert "表1-1中特征X" in calls[0]  # 错题原文照常作为材料
