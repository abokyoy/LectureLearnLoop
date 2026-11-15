# -*- coding: utf-8 -*-
"""目标导向学习课文闭环端点断言（Task 7：pretest/postquiz/exam/regenerate/read）。

运行方式（server/ 目录）：python -m pytest tests/test_course_flow.py -v
LLM 全 monkeypatch（按 scene 分发结构/题包/课文），不烧积分。
"""
import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "cgf" + uuid.uuid4().hex[:8]
PW = "pass1234"

MD = """# 课文标题

## 概览
本文讲解目标导向学习课文正文的生成契约，覆盖概念定义与典型例子，长度需要超过两百字下限以通过校验逻辑的分支判断测试。

## 核心概念
梯度下降通过沿负梯度方向迭代更新参数最小化损失函数，学习率决定每步步长。

## 范例
设 $f(x)=x^2$，从 $x_0=3$、$\\eta=0.1$ 出发迭代三步的数值演练过程与结果解释。

## 重点摘要
概念、公式、迭代过程三要素构成完整理解链条，缺一不可，正文以简短段落组织以上内容并留有余味。
""" * 2


def _mods():
    return json.dumps({"modules": [{"title": f"模块{i}", "description": f"说明{i}",
                                    "lessons": [{"title": f"课文{i}-{j}", "description": "d",
                                                 "est_minutes": 30} for j in range(4)]}
                                   for i in range(4)], "n": 4}, ensure_ascii=False)


def _qpack(n=4):
    return json.dumps({"questions": [
        {"stem": f"题干{i}", "options": [f"甲{i}", f"乙{i}", f"丙{i}", f"丁{i}"],
         "answer_index": i % 4, "kp_name": f"知识点{i}", "explanation": f"解析{i}"}
        for i in range(n)]}, ensure_ascii=False)


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
def au2(client):
    r = client.post("/api/auth/register", json={"username": U + "x", "password": PW})
    return r.get_json()["data"]


def _h(token):
    return {"Authorization": "Bearer " + token}


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


@pytest.fixture(scope="module")
def llm():
    """按 scene 分发的假 LLM；cap 记录 (scene, prompt) 供断言。

    rank_matches 同步打桩为空：判分链 kp 解析不走真实 embedding（否则每人数秒，
    相似复用口径已由 test_course_grade 单独断言）。"""
    from services import course_service as cs
    import similarity_matcher as sm
    cap = []

    def fake(prompt, scene=""):
        cap.append((scene, prompt))
        if scene == "生成课程结构":
            return _mods()
        if scene == "模块考试出题":
            return _qpack(8)
        if scene in ("课程前测出题", "课程后练出题"):
            return _qpack(4)
        if scene == "生成课程课文":
            return MD
        raise AssertionError("unexpected scene " + scene)
    cs_monkey = pytest.MonkeyPatch()
    cs_monkey.setattr(cs, "_llm", fake)
    cs_monkey.setattr(sm, "rank_matches", lambda **kw: [])
    yield cap
    cs_monkey.undo()


def _db_pack(lid, kind):
    """读库中题包（含 answer_index，模拟出题方视角构造答案）。"""
    conn = _conn()
    try:
        row = conn.execute("SELECT id, questions_json FROM course_tests WHERE lesson_id=? AND kind=? "
                           "ORDER BY id DESC LIMIT 1", (lid, kind)).fetchone()
        return (row[0], json.loads(row[1])) if row else (None, None)
    finally:
        conn.close()


def _count(sql, args=()):
    conn = _conn()
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


class TestLessonFlow:
    MOD = "CF" + uuid.uuid4().hex[:6]
    goal_id = None
    lids = []      # 16 篇课文 id（树序）
    mids = []      # 4 个模块 id

    # ---------- 建目标 ----------
    def test_01_create_goal(self, client, au, llm):
        subj = self.MOD + "S"
        r = client.post("/api/course/goals", json={"subject_name": subj, "goal_text": "掌握" + subj},
                        headers=_h(au["token"]))
        d = r.get_json()["data"]
        type(self).goal_id = d["goal"]["id"]
        type(self).lids = [l["id"] for m in d["modules"] for l in m["lessons"]]
        type(self).mids = [m["id"] for m in d["modules"]]
        assert len(self.lids) == 16 and self.MOD

    # ---------- pretest GET ----------
    def test_02_get_pretest_new_pack(self, client, au):
        lid = self.lids[0]
        r = client.get(f"/api/course/lessons/{lid}/pretest", headers=_h(au["token"]))
        d = r.get_json()["data"]
        assert d["kind"] == "pretest" and len(d["questions"]) == 4
        assert "answer_index" not in d["questions"][0]  # 答案不外泄
        assert "explanation" not in d["questions"][0]
        tid = d["test_id"]
        # 再进不重烧：同 test_id、不新增行
        r2 = client.get(f"/api/course/lessons/{lid}/pretest", headers=_h(au["token"]))
        assert r2.get_json()["data"]["test_id"] == tid
        assert _count("SELECT COUNT(1) FROM course_tests WHERE lesson_id=? AND kind='pretest'",
                      (lid,)) == 1

    # ---------- pretest POST 全对 ----------
    def test_03_pretest_all_correct(self, client, au, llm):
        lid = self.lids[0]
        tid, pack = _db_pack(lid, "pretest")
        answers = [q["answer_index"] for q in pack]
        n_md_before = sum(1 for s, _ in llm if s == "生成课程课文")
        r = client.post(f"/api/course/lessons/{lid}/pretest", json={"answers": answers},
                        headers=_h(au["token"]))
        body = r.get_json()
        assert body["success"], body
        d = body["data"]
        assert d["score"] == 1.0 and d["mode"] == "concise"
        assert d["lesson"]["content_md"].startswith("# 课文标题")
        assert d["lesson"]["content_mode"] == "concise"
        assert d["lesson"]["status"] == "content_ready"
        # 落库核对：pretest_score、attempt 一行、课文生成一次
        conn = _conn()
        try:
            row = conn.execute("SELECT pretest_score, status, content_mode FROM course_lessons WHERE id=?",
                               (lid,)).fetchone()
            assert row == (1.0, "content_ready", "concise")
            assert _count("SELECT COUNT(1) FROM course_attempts WHERE goal_id=? AND kind='pretest'",
                          (self.goal_id,)) == 1
        finally:
            conn.close()
        assert sum(1 for s, _ in llm if s == "生成课程课文") == n_md_before + 1

    # ---------- 再交卷幂等（不重生成课文）----------
    def test_04_pretest_resubmit_idempotent(self, client, au, llm):
        lid = self.lids[0]
        tid, pack = _db_pack(lid, "pretest")
        n_md_before = sum(1 for s, _ in llm if s == "生成课程课文")
        r = client.post(f"/api/course/lessons/{lid}/pretest",
                        json={"answers": [q["answer_index"] for q in pack]},
                        headers=_h(au["token"]))
        d = r.get_json()["data"]
        assert d["lesson"]["status"] == "content_ready"  # 不回退不重生成
        assert sum(1 for s, _ in llm if s == "生成课程课文") == n_md_before
        # attempt 追加一行（历史保留）
        assert _count("SELECT COUNT(1) FROM course_attempts WHERE goal_id=? AND kind='pretest'",
                      (self.goal_id,)) == 2

    # ---------- 有错 → full + 错题概念进 prompt ----------
    def test_05_pretest_wrong_full(self, client, au, llm):
        lid = self.lids[1]
        client.get(f"/api/course/lessons/{lid}/pretest", headers=_h(au["token"]))
        tid, pack = _db_pack(lid, "pretest")
        answers = [(q["answer_index"] + 1) % 4 for q in pack]  # 全错
        n_rec = _count("SELECT COUNT(1) FROM practice_records WHERE subject_name=?", (self.MOD + "S",))
        n_md = sum(1 for s, _ in llm if s == "生成课程课文")
        r = client.post(f"/api/course/lessons/{lid}/pretest", json={"answers": answers},
                        headers=_h(au["token"]))
        d = r.get_json()["data"]
        assert d["score"] == 0.0 and d["mode"] == "full"
        assert d["lesson"]["content_mode"] == "full"
        # full 模式 prompt 带错题知识点名（R2 置顶详讲素材）
        md_prompt = [p for s, p in llm if s == "生成课程课文"][-1]
        assert "知识点0" in md_prompt
        assert sum(1 for s, _ in llm if s == "生成课程课文") == n_md + 1
        # R3：全错 4 题 → 新增 4 条练习流水（判分链细节已由 test_course_grade 断言，这里验证端点串联落库）
        assert _count("SELECT COUNT(1) FROM practice_records WHERE subject_name=?",
                      (self.MOD + "S",)) == n_rec + 4

    # ---------- reset 重新前测 ----------
    def test_06_pretest_reset(self, client, au):
        lid = self.lids[0]
        old_tid, _ = _db_pack(lid, "pretest")
        r = client.post(f"/api/course/lessons/{lid}/pretest", json={"reset": True},
                        headers=_h(au["token"]))
        d = r.get_json()["data"]
        assert d["test_id"] != old_tid and len(d["questions"]) == 4
        assert d.get("credits_note")  # 明示再次消耗积分
        # 旧题包行已删，attempt 历史保留（T3+T4+T5 共 3 次 pretest 交卷）
        assert _count("SELECT COUNT(1) FROM course_tests WHERE lesson_id=? AND kind='pretest'",
                      (lid,)) == 1
        assert _count("SELECT COUNT(1) FROM course_attempts WHERE goal_id=? AND kind='pretest'",
                      (self.goal_id,)) == 3

    # ---------- postquiz ----------
    def test_07_postquiz_requires_content(self, client, au):
        lid = self.lids[2]  # 未前测的课文
        r = client.get(f"/api/course/lessons/{lid}/postquiz", headers=_h(au["token"]))
        assert r.status_code == 409

    def test_08_postquiz_flow(self, client, au):
        lid = self.lids[0]
        r = client.get(f"/api/course/lessons/{lid}/postquiz", headers=_h(au["token"]))
        d = r.get_json()["data"]
        assert d["kind"] == "postquiz" and len(d["questions"]) == 4
        tid, pack = _db_pack(lid, "postquiz")
        answers = [q["answer_index"] for q in pack]
        r2 = client.post(f"/api/course/lessons/{lid}/postquiz", json={"answers": answers},
                         headers=_h(au["token"]))
        d2 = r2.get_json()["data"]
        assert d2["score"] == 1.0
        assert d2["lesson_status"] == "learned"  # 后练完成 → learned（done 留给 complete）
        assert _count("SELECT COUNT(1) FROM course_attempts WHERE goal_id=? AND kind='postquiz'",
                      (self.goal_id,)) == 1

    # ---------- read ----------
    def test_09_read_gate(self, client, au):
        r = client.post(f"/api/course/lessons/{self.lids[3]}/read", json={}, headers=_h(au["token"]))
        assert r.status_code == 409  # new 直接 read 跳步拒绝
        lid = self.lids[1]  # content_ready
        r2 = client.post(f"/api/course/lessons/{lid}/read", json={}, headers=_h(au["token"]))
        assert r2.get_json()["data"]["status"] == "learned"

    # ---------- regenerate ----------
    def test_10_regenerate_limit(self, client, au, llm):
        lid = self.lids[0]
        for i in range(1, 4):
            r = client.post(f"/api/course/lessons/{lid}/regenerate", json={}, headers=_h(au["token"]))
            assert r.status_code == 200, r.get_json()
            assert r.get_json()["data"]["lesson"]["regen_count"] == i
        r4 = client.post(f"/api/course/lessons/{lid}/regenerate", json={}, headers=_h(au["token"]))
        assert r4.status_code == 400
        # 未前测课文拒绝重生成
        r5 = client.post(f"/api/course/lessons/{self.lids[4]}/regenerate", json={}, headers=_h(au["token"]))
        assert r5.status_code == 400

    # ---------- module exam ----------
    def test_11_module_exam(self, client, au):
        mid = self.mids[0]
        r = client.get(f"/api/course/modules/{mid}/exam", headers=_h(au["token"]))
        d = r.get_json()["data"]
        assert d["kind"] == "moduleexam" and len(d["questions"]) == 8
        conn = _conn()
        try:
            row = conn.execute("SELECT id, questions_json FROM course_tests WHERE module_id=? AND kind='moduleexam' "
                               "ORDER BY id DESC LIMIT 1", (mid,)).fetchone()
            tid, pack = row[0], json.loads(row[1])
        finally:
            conn.close()
        answers = [q["answer_index"] for q in pack]
        r2 = client.post(f"/api/course/modules/{mid}/exam", json={"answers": answers},
                         headers=_h(au["token"]))
        d2 = r2.get_json()["data"]
        assert d2["score"] == 1.0
        assert _count("SELECT COUNT(1) FROM course_attempts WHERE goal_id=? AND kind='moduleexam'",
                      (self.goal_id,)) == 1

    # ---------- 参数与越权 ----------
    def test_12_bad_answers_400(self, client, au):
        lid = self.lids[1]
        r = client.post(f"/api/course/lessons/{lid}/pretest", json={"answers": [0]},
                        headers=_h(au["token"]))
        assert r.status_code == 400

    def test_13_cross_user_404(self, client, au, au2):
        lid = self.lids[0]
        r = client.get(f"/api/course/lessons/{lid}/pretest", headers=_h(au2["token"]))
        assert r.status_code == 404
        r2 = client.post(f"/api/course/lessons/{lid}/postquiz", json={"answers": [0, 1, 2, 3]},
                         headers=_h(au2["token"]))
        assert r2.status_code == 404
        r3 = client.get(f"/api/course/modules/{self.mids[0]}/exam", headers=_h(au2["token"]))
        assert r3.status_code == 404

    # ---------- 课文详情 ----------
    def test_14_lesson_detail(self, client, au):
        r = client.get(f"/api/course/lessons/{self.lids[0]}", headers=_h(au["token"]))
        d = r.get_json()["data"]["lesson"]
        assert d["content_md"] and d["status"] == "learned"
        assert d["goal_id"] == self.goal_id

    # ---------- 成绩历史端点（骨架 Tab 已引用，随 Task 8 落地）----------
    def test_15_attempts_list(self, client, au, au2):
        r = client.get(f"/api/course/goals/{self.goal_id}/attempts", headers=_h(au["token"]))
        rows = r.get_json()["data"]["attempts"]
        # pretest 3 + postquiz 1 + moduleexam 1
        assert len(rows) == 5
        kinds = [a["kind"] for a in rows]
        assert kinds.count("pretest") == 3 and "postquiz" in kinds and "moduleexam" in kinds
        assert all(a["score"] is not None and a["created_time"] for a in rows)
        # 越权：他人目标 404
        r2 = client.get(f"/api/course/goals/{self.goal_id}/attempts", headers=_h(au2["token"]))
        assert r2.status_code == 404

    # ---------- 生成失败 → 补生成链（评审 Major-1 修复断言）----------
    def test_16_generate_retry_after_fail(self, client, au, llm, monkeypatch):
        from services import course_service as cs
        lid = self.lids[5]
        client.get(f"/api/course/lessons/{lid}/pretest", headers=_h(au["token"]))
        tid, pack = _db_pack(lid, "pretest")
        answers = [(q["answer_index"] + 1) % 4 for q in pack]  # 全错 → full
        att_sql = ("SELECT COUNT(1) FROM course_attempts WHERE goal_id=? AND kind='pretest'",
                   (self.goal_id,))
        n_att = _count(*att_sql)
        n_rec = _count("SELECT COUNT(1) FROM practice_records WHERE subject_name=?", (self.MOD + "S",))

        def bad(prompt, scene=""):
            if scene == "生成课程课文":
                raise cs.CourseError("模拟生成失败")
            if scene in ("课程前测出题", "课程后练出题"):
                return _qpack(4)
            if scene == "生成课程结构":
                return _mods()
            raise AssertionError("unexpected scene " + scene)
        monkeypatch.setattr(cs, "_llm", bad)
        # 交卷：判分落库成功但课文生成失败 → 502，成绩不回滚（重试不重判的前提）
        r = client.post(f"/api/course/lessons/{lid}/pretest", json={"answers": answers},
                        headers=_h(au["token"]))
        body = r.get_json()
        assert r.status_code == 502 and "已判分并记录" in body["error"], body
        assert _count(*att_sql) == n_att + 1
        conn = _conn()
        try:
            row = conn.execute("SELECT status, pretest_score, content_md FROM course_lessons WHERE id=?",
                               (lid,)).fetchone()
        finally:
            conn.close()
        assert row[0] == "pretested" and row[1] == 0.0 and row[2] is None
        # 补生成仍失败（LLM 仍 bad）：不落脏数据、不重复判分
        r2 = client.post(f"/api/course/lessons/{lid}/generate", headers=_h(au["token"]))
        assert r2.status_code == 502
        assert _count(*att_sql) == n_att + 1
        # 恢复后补生成成功：不重烧出题、不计重生成上限、判分链不二次落库
        def good(prompt, scene=""):
            if scene == "生成课程课文":
                return MD
            return bad(prompt, scene)
        monkeypatch.setattr(cs, "_llm", good)
        r3 = client.post(f"/api/course/lessons/{lid}/generate", headers=_h(au["token"]))
        d3 = r3.get_json()["data"]
        assert d3["lesson"]["status"] == "content_ready"
        assert d3["lesson"]["content_mode"] == "full" and d3["lesson"]["regen_count"] == 0
        assert _count(*att_sql) == n_att + 1
        assert _count("SELECT COUNT(1) FROM practice_records WHERE subject_name=?",
                      (self.MOD + "S",)) == n_rec + 4  # 仅首次判分写入，补生成不叠加
        # 已有课文再补 → 400；未前测 new 课文 → 409
        r4 = client.post(f"/api/course/lessons/{lid}/generate", headers=_h(au["token"]))
        assert r4.status_code == 400
        r5 = client.post(f"/api/course/lessons/{self.lids[6]}/generate", headers=_h(au["token"]))
        assert r5.status_code == 409

    @classmethod
    def teardown_class(cls):
        """删除本测试类创建的目标（级联五表），练习/错题资产留给 T6 已覆盖口径不清理用户级？——统一清理测试用户数据。"""
        if cls.goal_id:
            conn = _conn()
            try:
                lsub = ("SELECT l.id FROM course_lessons l JOIN course_modules m ON l.module_id=m.id "
                        "WHERE m.goal_id=?")
                conn.execute("DELETE FROM course_attempts WHERE goal_id=?", (cls.goal_id,))
                conn.execute(f"DELETE FROM course_tests WHERE lesson_id IN ({lsub})", (cls.goal_id,))
                conn.execute(f"DELETE FROM course_tests WHERE module_id IN "
                             "(SELECT id FROM course_modules WHERE goal_id=?)", (cls.goal_id,))
                conn.execute("DELETE FROM course_lessons WHERE module_id IN "
                             "(SELECT id FROM course_modules WHERE goal_id=?)", (cls.goal_id,))
                conn.execute("DELETE FROM course_modules WHERE goal_id=?", (cls.goal_id,))
                conn.execute("DELETE FROM learning_goals WHERE id=?", (cls.goal_id,))
                conn.commit()
            finally:
                conn.close()
