# -*- coding: utf-8 -*-
"""P3 知识点描述编辑端点契约测试（Flask test client）。

运行方式（server/ 目录）：python -m pytest tests/test_p3_description.py -v
覆盖：PUT /api/knowledge/points/<pid>/description（手动保存/校验/隔离）、
POST .../description-assist 的 extract（纯字符串摘取，无 LLM）、
generate/polish（monkeypatch _llm_call，含积分不足分支）。
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "p3desc_" + uuid.uuid4().hex[:8]
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


NOTE_MD = """# 优化笔记

这是无关段落，只讲卷积池化，不含目标关键字内容一二三。

梯度下降通过沿负梯度方向迭代更新参数最小化损失，学习率决定步长。

另一段：随机梯度下降是梯度下降的批量近似变体，收敛更快但震荡更大。
"""


class TestP3Description:
    MOD = "P3D" + uuid.uuid4().hex[:6]
    PID = None       # 有描述+关联笔记
    PID_EMPTY = None  # 空描述无笔记

    def test_1_setup(self, client, au):
        import tempfile
        tk, uid = au["token"], au["user_id"]
        subject = f"{self.MOD}_科"
        client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk))
        fd = Path(tempfile.mkdtemp(prefix="p3cdp_"))
        note_file = fd / "p3note.md"
        note_file.write_text(NOTE_MD, encoding="utf-8")
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description) "
                "VALUES (?,?,?,?)", (uid, subject, "梯度下降", "旧描述一句话"))
            cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
            self.__class__.PID = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description) "
                "VALUES (?,?,?,?)", (uid, subject, f"{self.MOD}空点", ""))
            cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
            self.__class__.PID_EMPTY = cur.fetchone()[0]
            uuid_ = "p3cdp-" + uuid.uuid4().hex
            cur.execute(
                "INSERT INTO notes (user_id, note_uuid, file_name, file_path, title) VALUES (?,?,?,?,?)",
                (uid, uuid_, "p3note.md", str(note_file), f"{self.MOD}优化笔记"))
            cur.execute("SELECT id FROM notes WHERE note_uuid = ?", (uuid_,))
            nid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO knowledge_point_sources (knowledge_point_id, note_id, note_uuid) VALUES (?,?,?)",
                (self.PID, nid, uuid_))
            conn.commit()
        finally:
            conn.close()

    def test_2_put_manual_save(self, client, au):
        r = client.put(f"/api/knowledge/points/{self.PID}/description",
                       json={"description": "  手工新描述：步长与凸性。  "}, headers=_h(au["token"]))
        d = r.get_json()["data"]
        assert d["success"] is True
        assert d["core_description"] == "手工新描述：步长与凸性。"  # strip 后落库
        det = client.get(f"/api/knowledge/points/{self.PID}/detail", headers=_h(au["token"])).get_json()["data"]
        assert det["detail"]["description"] == "手工新描述：步长与凸性。"

    def test_3_put_validation(self, client, au):
        d = client.put(f"/api/knowledge/points/{self.PID}/description",
                       json={"description": 123}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False
        d = client.put(f"/api/knowledge/points/{self.PID}/description",
                       json={"description": "x" * 5001}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False and "过长" in d["error"]
        d = client.put("/api/knowledge/points/99999999/description",
                       json={"description": "a"}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False  # 不存在的点
        # 跨用户隔离：另注册用户不得改写他人点
        u2 = "p3cdp_other_" + uuid.uuid4().hex[:6]
        tk2 = client.post("/api/auth/register", json={"username": u2, "password": PW}).get_json()["data"]["token"]
        d = client.put(f"/api/knowledge/points/{self.PID}/description",
                       json={"description": "越权"}, headers=_h(tk2)).get_json()["data"]
        assert d["success"] is False
        # 无 token
        assert client.put(f"/api/knowledge/points/{self.PID}/description", json={"description": "a"}).status_code == 401

    def test_4_extract_pure_match(self, client, au):
        d = client.post(f"/api/knowledge/points/{self.PID}/description-assist",
                        json={"action": "extract"}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is True and d["llm"] is False
        assert "梯度下降通过沿负梯度方向" in d["text"]
        assert "随机梯度下降是梯度下降的批量近似变体" in d["text"]
        assert "卷积池化" not in d["text"]  # 未命中段落不摘

    def test_5_extract_no_source(self, client, au):
        d = client.post(f"/api/knowledge/points/{self.PID_EMPTY}/description-assist",
                        json={"action": "extract"}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False and "未找到" in d["error"]
        d = client.post(f"/api/knowledge/points/{self.PID}/description-assist",
                        json={"action": "bogus"}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False  # 非法 action

    def test_6_generate_mock(self, client, au, monkeypatch):
        import routes_bridge
        calls = []

        def fake(prompt, context=""):
            calls.append((prompt, context))
            return "AI 生成的描述：梯度下降是一阶迭代优化算法。"
        monkeypatch.setattr(routes_bridge, "_llm_call", fake)
        d = client.post(f"/api/knowledge/points/{self.PID}/description-assist",
                        json={"action": "generate"}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is True and d["llm"] is True
        assert d["text"].startswith("AI 生成的描述")
        assert len(calls) == 1
        assert "梯度下降" in calls[0][0] and "优化笔记" in calls[0][0]  # prompt 含点名与笔记上下文

    def test_7_polish(self, client, au, monkeypatch):
        import routes_bridge
        # 空描述先报错（不发 LLM）
        d = client.post(f"/api/knowledge/points/{self.PID_EMPTY}/description-assist",
                        json={"action": "polish"}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False and "为空" in d["error"]
        captured = []

        def rec(prompt, context=""):
            captured.append(prompt)
            return "润色后描述"
        monkeypatch.setattr(routes_bridge, "_llm_call", rec)
        d = client.post(f"/api/knowledge/points/{self.PID}/description-assist",
                        json={"action": "polish"}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is True and d["text"] == "润色后描述"
        # 传编辑框未保存内容：以传入值为润色基底
        client.post(f"/api/knowledge/points/{self.PID}/description-assist",
                    json={"action": "polish", "description": "草稿中的新写法"}, headers=_h(au["token"]))
        assert "草稿中的新写法" in captured[-1] and "手工新描述" not in captured[-1]

    def test_8_credits_insufficient(self, client, au, monkeypatch):
        import routes_bridge
        import credits_service as cr

        def boom(prompt, context=""):
            raise cr.InsufficientCreditsError(balance=3)
        monkeypatch.setattr(routes_bridge, "_llm_call", boom)
        d = client.post(f"/api/knowledge/points/{self.PID}/description-assist",
                        json={"action": "generate"}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False and d.get("credits_insufficient") is True
        assert d["credit_balance"] == 3

    def test_9_cleanup(self, client, au):
        uid = au["user_id"]
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN "
                "(SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ?)", (uid, f"{self.MOD}_科"))
            cur.execute("DELETE FROM notes WHERE user_id = ? AND title LIKE ?", (uid, f"{self.MOD}%"))
            cur.execute("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name = ?", (uid, f"{self.MOD}_科"))
            cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name = ?", (uid, f"{self.MOD}_科"))
            cur.execute("DELETE FROM knowledge_points WHERE user_id = ? AND point_name LIKE ?",
                        (uid, f"%{self.MOD}%"))
            conn.commit()
        finally:
            conn.close()
