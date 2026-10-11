# -*- coding: utf-8 -*-
"""P5 错题练习/举一反三/错题编辑删除 契约测试（Flask test client，LLM 全部打桩）。

运行方式（server/ 目录）：python -m pytest tests/test_p5_error_practice.py -v
覆盖：
- POST /api/knowledge/points/<pid>/error-practice：smart 按熟练度升序（NULL 视为 0 最弱）
  取前 N、同题干去重取最弱代表行、无答案行跳过计数；manual 按 error_ids 勾选（跨用户/
  跨知识点 id 自动过滤）；参数与鉴权校验。
- POST .../generate-practice：count 参数化（默认 8 兼容）、analogy 支持 error_ids 来源、
  LLM 返回数量与 count 不符时校验失败。
- PUT /api/kb/errors/<eid>：题干/选项同步该知识点下同题干全部流水行（别的知识点不动）、
  答案/解析同步同题干全部错题行、仅传 content 保持旧行为、改名撞车已存在题干不得覆写无关组。
- POST .../error-practice 零 LLM 调用（打桩计数）；mode 非字符串友好报错。
- DELETE /api/kb/errors/<eid>：purge 整题（错题行+熟练度历史+流水+收藏）；
  转收藏路径（服务层默认 purge=False）流水保留的回归。
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "p5ep_" + uuid.uuid4().hex[:8]
PW = "pass1234"
MOD = "P5EP" + uuid.uuid4().hex[:6]


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


@pytest.fixture(scope="module")
def other(client):
    r = client.post("/api/auth/register",
                    json={"username": U + "_b", "password": PW})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def _h(token):
    return {"Authorization": "Bearer " + token}


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


def _llm_questions(n):
    """构造 n 题合法 JSON：1 选择 + 1 判断 + 其余简答（满足逐题结构校验）。"""
    arr = [{"type": "single", "question": f"{MOD}新题选择？",
            "options": ["甲", "乙", "丙", "丁"], "correct_answer": "A",
            "difficulty": "容易", "explanation": "甲正确"}]
    if n >= 2:
        arr.append({"type": "judge", "question": f"{MOD}新题判断。",
                    "correct_answer": "正确", "difficulty": "中等", "explanation": "对"})
    while len(arr) < n:
        arr.append({"type": "short", "question": f"{MOD}新题简答{len(arr) + 1}。",
                    "correct_answer": "要点一；要点二", "difficulty": "中等", "explanation": "略"})
    return json.dumps(arr, ensure_ascii=False)


class TestP5ErrorPractice:
    PID = PID2 = None
    EID = {}   # 题干 → 代表错题行 id
    Q = {}     # 场景题干常量

    def test_1_seed(self, client, au, other):
        tk, uid = au["token"], au["user_id"]
        subject = f"{MOD}_科"
        client.post("/api/subjects", json={"subject_name": subject}, headers=_h(tk))
        conn = _conn()
        try:
            cur = conn.cursor()
            def mk_point(name):
                cur.execute(
                    "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description) "
                    "VALUES (?,?,?,?)", (uid, subject, name, "P5 测试描述"))
                cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND point_name = ?",
                            (uid, name))
                return cur.fetchone()[0]
            self.__class__.PID = pid = mk_point(f"{MOD}树遍历")
            self.__class__.PID2 = mk_point(f"{MOD}排序")

            def add_rec(qtext, ans, ok, kp=pid, qtype="single",
                        opts='["根左右", "左右根", "左根右", "根右左"]', ts="2026-10-01 08:00:00"):
                cur.execute(
                    "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                    "question_content, user_answer, is_correct, question_type, options_json, practice_time) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, subject, kp, qtext, ans, ok, qtype, opts, ts))
                cur.execute("SELECT id FROM practice_records WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
                return cur.fetchone()[0]

            def add_err(rid, prof, ca, expl=None, kp=pid):
                cur.execute(
                    "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                    "practice_record_id, review_status, current_proficiency, correct_answer, explanation) "
                    "VALUES (?,?,?,?,?,?,?,?)", (uid, subject, kp, rid, 0, prof, ca, expl))
                cur.execute("SELECT id FROM error_questions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (uid,))
                return cur.fetchone()[0]

            # 题1：同题干两条错题行（prof 10 / 90）→ smart 去重取最弱代表行
            q1 = self.Q["q1"] = f"{MOD}题1：先序遍历顺序是？"
            r1a = add_rec(q1, "B", 0)
            r1b = add_rec(q1, "C", 0, ts="2026-10-02 08:00:00")
            self.EID["q1_weak"] = add_err(r1a, 10, "A", "先序=根左右")
            self.EID["q1_strong"] = add_err(r1b, 90, "A", "先序=根左右")
            # 题2：中等 prof
            q2 = self.Q["q2"] = f"{MOD}题2：中序遍历顺序是？"
            self.EID["q2"] = add_err(add_rec(q2, "C", 0), 25, "A")
            # 题3：无 correct_answer → 应被跳过并计数
            q3 = self.Q["q3"] = f"{MOD}题3：后序遍历顺序是？"
            self.EID["q3"] = add_err(add_rec(q3, "D", 0), 40, None)
            # 题4：prof NULL → COALESCE 0 排最前
            q4 = self.Q["q4"] = f"{MOD}题4：二叉树高度定义？"
            self.EID["q4"] = add_err(add_rec(q4, "x", 0, qtype="short", opts=None), None, "树深度")
            # 另一知识点下同题干流水（删除 purge 不得越界触碰）
            add_rec(q1, "B", 0, kp=self.PID2)
            # 题5：待删除整题（2 错题行 + 3 流水 + 1 收藏 + 历史）
            q5 = self.Q["q5"] = f"{MOD}题5：待删题？"
            r5a = add_rec(q5, "A", 0)
            r5b = add_rec(q5, "B", 0, ts="2026-10-03 08:00:00")
            add_rec(q5, "A", 1, ts="2026-10-04 08:00:00")
            e5a = add_err(r5a, 20, "A", "待删解析")
            add_err(r5b, 30, "A", "待删解析")
            cur.execute("INSERT INTO error_proficiency_history (error_question_id, proficiency, timestamp) "
                        "VALUES (?,?,?)", (e5a, 20, "2026-10-05 10:00:00"))
            cur.execute("INSERT INTO favorite_questions (user_id, subject_name, knowledge_point_id, question_content) "
                        "VALUES (?,?,?,?)", (uid, subject, pid, q5))
            self.EID["q5"] = e5a
            # 题6：待转收藏回归题
            q6 = self.Q["q6"] = f"{MOD}题6：转收藏题？"
            self.EID["q6"] = add_err(add_rec(q6, "B", 0), 15, "A", "收藏前解析")
            # 跨用户错题（other）：manual 传其 id 必须被过滤
            cur.execute(
                "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description) "
                "VALUES (?,?,?,?)", (other["user_id"], subject, f"{MOD}他人口", "x"))
            cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND point_name = ?",
                        (other["user_id"], f"{MOD}他人口"))
            opid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                "question_content, user_answer, is_correct) VALUES (?,?,?,?,?,?)",
                (other["user_id"], subject, opid, f"{MOD}他人题", "A", 0))
            cur.execute("SELECT id FROM practice_records WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                        (other["user_id"],))
            # 错题行归属必须是 other（add_err 闭包绑的是 au，不可复用）
            cur.execute(
                "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                "practice_record_id, review_status, current_proficiency, correct_answer, explanation) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (other["user_id"], subject, opid, cur.fetchone()[0], 0, 5, "B", "他人解析"))
            cur.execute("SELECT id FROM error_questions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                        (other["user_id"],))
            self.EID["foreign"] = cur.fetchone()[0]
            # 借用 other 的类变量存 uid 无意义，清理时按 user_id 删
            self.__class__.OTHER_OPID = opid
            conn.commit()
        finally:
            conn.close()

    # ---------- error-practice ----------
    def _ep(self, client, tk, body):
        r = client.post(f"/api/knowledge/points/{self.PID}/error-practice",
                        json=body, headers=_h(tk))
        assert r.status_code == 200
        return r.get_json()["data"]

    def test_2_smart_order_dedup_and_skip(self, client, au):
        d = self._ep(client, au["token"], {"mode": "smart", "count": 8})
        assert d["success"] is True
        qs = d["questions"]
        # 全量错题池按熟练度升序：q4(0) < q1(10) < q6(15) < q5(20) < q2(25) < q3(40,无答案跳过)
        contents = [q["question"] for q in qs]
        assert contents == [self.Q["q4"], self.Q["q1"], self.Q["q6"], self.Q["q5"], self.Q["q2"]], contents
        assert d["skipped_no_answer"] == 1
        # 代表行取最弱错题行（prof=10 那条）
        q1_row = next(q for q in qs if q["question"] == self.Q["q1"])
        assert q1_row["error_id"] == self.EID["q1_weak"]
        assert q1_row["correct_answer"] == "A" and q1_row["type"] == "single"
        assert q1_row["options"] == ["根左右", "左右根", "左根右", "根右左"]
        # 简答题无选项：空数组而非 None
        q4_row = next(q for q in qs if q["question"] == self.Q["q4"])
        assert q4_row["options"] == [] and q4_row["type"] == "short"

    def test_3_smart_count_limit(self, client, au):
        d = self._ep(client, au["token"], {"mode": "smart", "count": 2})
        assert d["success"] is True
        assert [q["question"] for q in d["questions"]] == [self.Q["q4"], self.Q["q1"]]

    def test_4_manual_ids_dedup_and_foreign_filter(self, client, au):
        d = self._ep(client, au["token"], {
            "mode": "manual",
            "error_ids": [self.EID["q1_weak"], self.EID["q1_strong"], self.EID["q2"], self.EID["foreign"]]})
        assert d["success"] is True
        contents = sorted(q["question"] for q in d["questions"])
        assert contents == sorted([self.Q["q1"], self.Q["q2"]])  # 他人题被过滤、同题干去重
        # 勾选双行时代表行为熟练度最低行
        ids = {q["error_id"] for q in d["questions"]}
        assert self.EID["q1_weak"] in ids and self.EID["q1_strong"] not in ids

    def test_5_param_and_auth_errors(self, client, au):
        d = self._ep(client, au["token"], {"mode": "wave"})
        assert d["success"] is False and "mode" in d["error"]
        # CodeReview 盲区：mode 非字符串不得 500，应返友好错误
        d = self._ep(client, au["token"], {"mode": 123})
        assert d["success"] is False and "mode" in d["error"]
        d = self._ep(client, au["token"], {"mode": ["smart"]})
        assert d["success"] is False and "mode" in d["error"]
        d = self._ep(client, au["token"], {"mode": "smart", "count": "abc"})
        assert d["success"] is False and "count" in d["error"]
        # count 显式 null → 同非整数路径，不得 500
        d = self._ep(client, au["token"], {"mode": "smart", "count": None})
        assert d["success"] is False and "count" in d["error"]
        d = self._ep(client, au["token"], {"mode": "manual", "error_ids": []})
        assert d["success"] is False
        # 仅有他人 id 的 manual → 无可判分错题
        d = self._ep(client, au["token"], {"mode": "manual", "error_ids": [self.EID["foreign"]]})
        assert d["success"] is False and d.get("no_errors") is True
        # 未带 token → 401
        r = client.post(f"/api/knowledge/points/{self.PID}/error-practice", json={})
        assert r.status_code == 401

    # ---------- generate-practice 参数化 ----------
    def test_6_generate_count(self, client, au, monkeypatch):
        import routes_bridge
        calls = []

        def fake(prompt, context=""):
            calls.append(prompt)
            return _llm_questions(3)
        monkeypatch.setattr(routes_bridge, "_llm_call", fake)
        r = client.post(f"/api/knowledge/points/{self.PID}/generate-practice",
                        json={"source": "analogy", "count": 3}, headers=_h(au["token"]))
        d = r.get_json()["data"]
        assert d["success"] is True and len(d["questions"]) == 3
        assert "3 道练习题" in calls[0] and "恰好为 3" in calls[0]
        # 智能来源：错题按熟练度升序取，prompt 应含最弱题不含被跳过题以外全集
        assert self.Q["q4"] in calls[0] and self.Q["q1"] in calls[0]

    def test_7_generate_default_8_compat(self, client, au, monkeypatch):
        import routes_bridge
        seen = []

        def fake(prompt, context=""):
            seen.append(prompt)
            return _llm_questions(8)
        monkeypatch.setattr(routes_bridge, "_llm_call", fake)
        d = client.post(f"/api/knowledge/points/{self.PID}/generate-practice",
                        json={"source": "notes"}, headers=_h(au["token"])).get_json()["data"]
        # notes 无关联笔记 → 空态契约（no_notes），不发 LLM；改用 analogy 验证默认 8
        assert d["success"] is False and d.get("no_notes") is True
        d = client.post(f"/api/knowledge/points/{self.PID}/generate-practice",
                        json={"source": "analogy"}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is True and len(d["questions"]) == 8
        assert "8 道练习题" in seen[-1]

    def test_8_generate_error_ids(self, client, au, monkeypatch):
        import routes_bridge
        calls = []

        def fake(prompt, context=""):
            calls.append(prompt)
            return _llm_questions(2)
        monkeypatch.setattr(routes_bridge, "_llm_call", fake)
        d = client.post(f"/api/knowledge/points/{self.PID}/generate-practice",
                        json={"source": "analogy", "count": 2, "error_ids": [self.EID["q2"]]},
                        headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is True and len(d["questions"]) == 2
        assert self.Q["q2"] in calls[0] and self.Q["q1"] not in calls[0]

    def test_9_generate_count_mismatch(self, client, au, monkeypatch):
        import routes_bridge
        monkeypatch.setattr(routes_bridge, "_llm_call", lambda p, c="": _llm_questions(5))
        d = client.post(f"/api/knowledge/points/{self.PID2}/generate-practice",
                        json={"source": "analogy", "count": 3}, headers=_h(au["token"])).get_json()
        # PID2 无错题 → no_errors 先短路
        assert d["data"]["success"] is False and d["data"].get("no_errors") is True
        monkeypatch.setattr(routes_bridge, "_llm_call", lambda p, c="": _llm_questions(5))
        d = client.post(f"/api/knowledge/points/{self.PID}/generate-practice",
                        json={"source": "analogy", "count": 3}, headers=_h(au["token"])).get_json()["data"]
        assert d["success"] is False and "3" in d["error"]  # 数量校验按 count 而非固定 8

    # ---------- PUT 错题编辑 ----------
    def test_10_put_full_edit(self, client, au):
        q = self.Q["q1"]
        new_q = f"{MOD}题1改：先序遍历访问顺序（新题干）？"
        new_opts = ["新甲", "新乙", "新丙", "新丁"]
        r = client.put(f"/api/kb/errors/{self.EID['q1_weak']}", json={
            "content": new_q, "options": new_opts,
            "correct_answer": "B", "explanation": "新解析"}, headers=_h(au["token"]))
        assert r.get_json()["data"]["updated"] is True
        conn = _conn()
        try:
            cur = conn.cursor()
            # 本知识点下同题干两行流水全部更新（题干+选项）
            cur.execute("SELECT question_content, options_json FROM practice_records "
                        "WHERE user_id = ? AND knowledge_point_id = ? AND question_content = ?",
                        (au["user_id"], self.PID, new_q))
            rows = cur.fetchall()
            assert len(rows) == 2, rows
            assert all(json.loads(x[1]) == new_opts for x in rows)
            # 另一知识点下同题干流水不受影响
            cur.execute("SELECT COUNT(*) FROM practice_records WHERE user_id = ? AND knowledge_point_id = ? "
                        "AND question_content = ?", (au["user_id"], self.PID2, q))
            assert cur.fetchone()[0] == 1
            # 同题干全部错题行（含未直接编辑的 q1_strong）答案/解析一致
            cur.execute("SELECT correct_answer, explanation FROM error_questions "
                        "WHERE user_id = ? AND id = ?", (au["user_id"], self.EID["q1_strong"]))
            ca, expl = cur.fetchone()
            assert ca == "B" and expl == "新解析"
        finally:
            conn.close()
        self.Q["q1"] = new_q  # 后续断言用新题干

    def test_11_put_content_only_compat(self, client, au):
        q2 = self.Q["q2"]
        new_q2 = f"{MOD}题2改：中序遍历（新题干）？"
        r = client.put(f"/api/kb/errors/{self.EID['q2']}", json={"content": new_q2},
                       headers=_h(au["token"]))
        assert r.get_json()["data"]["updated"] is True
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT options_json FROM practice_records WHERE user_id = ? AND question_content = ?",
                        (au["user_id"], new_q2))
            assert json.loads(cur.fetchone()[0]) == ["根左右", "左右根", "左根右", "根右左"]  # 选项未被清空
        finally:
            conn.close()
        # 不存在 / 跨用户 → updated False
        assert client.put("/api/kb/errors/99999999", json={"content": "x"},
                          headers=_h(au["token"])).get_json()["data"]["updated"] is False
        assert client.put(f"/api/kb/errors/{self.EID['foreign']}", json={"content": "x"},
                          headers=_h(au["token"])).get_json()["data"]["updated"] is False

    # ---------- DELETE 整题 ----------
    def test_12_delete_purge(self, client, au):
        q5 = self.Q["q5"]
        r = client.delete(f"/api/kb/errors/{self.EID['q5']}", headers=_h(au["token"]))
        assert r.get_json()["data"]["deleted"] is True
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM error_questions eq "
                        "JOIN practice_records pr ON eq.practice_record_id = pr.id "
                        "WHERE pr.user_id = ? AND pr.question_content = ?", (au["user_id"], q5))
            assert cur.fetchone()[0] == 0, "同题干错题行须全删"
            cur.execute("SELECT COUNT(*) FROM practice_records WHERE user_id = ? AND question_content = ?",
                        (au["user_id"], q5))
            assert cur.fetchone()[0] == 0, "流水行须清除"
            cur.execute("SELECT COUNT(*) FROM favorite_questions WHERE user_id = ? AND question_content = ?",
                        (au["user_id"], q5))
            assert cur.fetchone()[0] == 0, "收藏行须清除"
            cur.execute("SELECT COUNT(*) FROM error_proficiency_history WHERE error_question_id = ?",
                        (self.EID["q5"],))
            assert cur.fetchone()[0] == 0, "熟练度历史须清除"
            # 其他题流水不受影响（题2 组已在 test_11 改名，用题4 验证）
            cur.execute("SELECT COUNT(*) FROM practice_records WHERE user_id = ? AND question_content = ?",
                        (au["user_id"], self.Q["q4"]))
            assert cur.fetchone()[0] == 1
        finally:
            conn.close()
        # 再删同一 id → deleted False
        assert client.delete(f"/api/kb/errors/{self.EID['q5']}",
                             headers=_h(au["token"])).get_json()["data"]["deleted"] is False

    def test_13_to_favorite_keeps_records(self, client, au):
        """回归：转收藏走服务层默认 purge=False，原始练习流水必须保留。"""
        q6 = self.Q["q6"]
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM practice_records WHERE user_id = ? AND question_content = ?",
                        (au["user_id"], q6))
            before = cur.fetchone()[0]
        finally:
            conn.close()
        r = client.post(f"/api/kb/errors/{self.EID['q6']}/to_favorite", headers=_h(au["token"]))
        assert r.get_json()["data"]["favorite_id"]
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM practice_records WHERE user_id = ? AND question_content = ?",
                        (au["user_id"], q6))
            assert cur.fetchone()[0] == before, "转收藏不得删流水"
            cur.execute("SELECT COUNT(*) FROM error_questions WHERE id = ?", (self.EID["q6"],))
            assert cur.fetchone()[0] == 0
        finally:
            conn.close()

    def test_14_put_rename_collision_no_overwrite(self, client, au):
        """CodeReview Major-1 回归：改名撞上同知识点已存在题干时，
        撞车组自身的流水/错题行不得被覆写（旧实现按新题干反查会误伤）。"""
        q_src = f"{MOD}题7：待改名撞车题？"
        q_col = f"{MOD}题7r：已存在的撞车靶题？"
        conn = _conn()
        try:
            cur = conn.cursor()

            def rec(qtext):
                cur.execute(
                    "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
                    "question_content, user_answer, is_correct, question_type, options_json, practice_time) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (au["user_id"], f"{MOD}_科", self.PID, qtext, "A", 0, "single",
                     '["a", "b", "c", "d"]', "2026-10-06 08:00:00"))
                cur.execute("SELECT id FROM practice_records WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                            (au["user_id"],))
                return cur.fetchone()[0]

            def err(rid, ca, expl):
                cur.execute(
                    "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
                    "practice_record_id, review_status, current_proficiency, correct_answer, explanation) "
                    "VALUES (?,?,?,?,?,?,?,?)", (au["user_id"], f"{MOD}_科", self.PID, rid, 0, 50, ca, expl))
                cur.execute("SELECT id FROM error_questions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                            (au["user_id"],))
                return cur.fetchone()[0]

            src_eid = err(rec(q_src), "A", "源解析")
            col_rid = rec(q_col)
            col_eid = err(col_rid, "D", "撞车靶解析")  # 靶组自身答案 D，不得被覆写
            conn.commit()
        finally:
            conn.close()
        r = client.put(f"/api/kb/errors/{src_eid}", json={
            "content": q_col, "correct_answer": "B", "explanation": "撞车后新解析"},
            headers=_h(au["token"]))
        assert r.get_json()["data"]["updated"] is True
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT correct_answer, explanation FROM error_questions WHERE id = ?",
                        (col_eid,))
            ca, expl = cur.fetchone()
            assert ca == "D" and expl == "撞车靶解析", "撞车靶组答案/解析被覆写（Major-1 未修）"
            cur.execute("SELECT COUNT(*) FROM practice_records WHERE user_id = ? AND knowledge_point_id = ? "
                        "AND question_content = ?", (au["user_id"], self.PID, q_col))
            assert cur.fetchone()[0] == 2  # 改名后两组同题干共存（列表口径自然合并），靶行未被删改
            cur.execute("SELECT COUNT(*) FROM error_questions WHERE id = ? AND practice_record_id = ?",
                        (src_eid, col_rid))
            assert cur.fetchone()[0] == 0  # 源错题行仍锚自己的流水，未被换绑
        finally:
            conn.close()

    def test_15_error_practice_zero_llm(self, client, au, monkeypatch):
        """CodeReview 盲区：错题练习组卷绝不得触发 LLM（零积分口径）。"""
        import routes_bridge
        calls = []
        monkeypatch.setattr(routes_bridge, "_llm_call",
                            lambda p, c="": calls.append(p) or "[]")
        d = self._ep(client, au["token"], {"mode": "smart", "count": 3})
        assert d["success"] is True and d["questions"]
        assert calls == [], "error-practice 不得调用 LLM"

    def test_99_cleanup(self, client, au, other):
        conn = _conn()
        try:
            cur = conn.cursor()
            for uid in (au["user_id"], other["user_id"]):
                cur.execute("DELETE FROM error_proficiency_history WHERE error_question_id IN "
                            "(SELECT id FROM error_questions WHERE user_id = ?)", (uid,))
                cur.execute("DELETE FROM error_questions WHERE user_id = ?", (uid,))
                cur.execute("DELETE FROM practice_records WHERE user_id = ?", (uid,))
                cur.execute("DELETE FROM favorite_questions WHERE user_id = ?", (uid,))
                cur.execute("DELETE FROM knowledge_points WHERE user_id = ?", (uid,))
                cur.execute("DELETE FROM user_subjects WHERE user_id = ?", (uid,))
            conn.commit()
        finally:
            conn.close()
