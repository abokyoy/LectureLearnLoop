"""错题学习单元升级（P1~P4）契约与流程断言测试。

模式同 test_p5_practice_loop.py：HTTP 集成测真实服务（127.0.0.1:6001），
独立测试用户 + 独立学科隔离数据，不污染正式数据。

覆盖（随阶段追加）：
- P1：/api/kb/errors 返回难度/重要度存储分；答案/解析全文不再截断
- P2：入池继承（出题难度映射 + 知识点重要度）、重练答错不重复入池、practice-history
- P3：error-pool 三模式、error-set-submit 双写（错题+kp FSRS）、派生题答错照常入池
- P4：weakness_report 严格 JSON 校验（纯函数）；报告生成→落库→列表/详情（test client
  monkeypatch _llm_call，模式同 test_p5_error_practice）；校验失败不落库

运行前置：服务端已在 127.0.0.1:6001 运行。
"""
from __future__ import annotations

import sys
import time
import unittest
import uuid

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:6001"
SUBJECT = f"错题单元{int(time.time()) % 100000}_{uuid.uuid4().hex[:4]}"


def register_and_token(username: str) -> str:
    requests.post(BASE + "/api/auth/register",
                  json={"username": username, "password": "test123456"}, timeout=15)
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["token"]


class TestP1Display(unittest.TestCase):
    """P1：列表返回三属性存储分 + 展开信息完整（无截断字段丢失）"""

    @classmethod
    def setUpClass(cls):
        cls.token = register_and_token("eu_p1_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}
        # 建知识点（无 LLM）
        r = requests.post(BASE + "/api/knowledge/point-new", headers=cls.h, timeout=30,
                          json={"point": {"name": "行列式计算", "description": "二阶三阶行列式的展开法则"},
                                "subject": SUBJECT})
        assert r.json()["success"], r.text
        cls.pid = int(r.json()["data"]["knowledge_id"])
        # 长解析 + 公式（>300 字符，旧版会被 truncate(300) 砍掉）
        cls.long_expl = "第一步展开 " + "公式 $m \\geq -1$ 成立。" * 30
        # 通过错题结果接口入一条错题（is_correct=False → 入池）
        r = requests.post(BASE + "/api/practice/results", headers=cls.h, timeout=30, json={"records": [{
            "subject_name": SUBJECT, "knowledge_point_id": cls.pid,
            "question_content": "求 $\\begin{vmatrix}1&2\\\\3&4\\end{vmatrix}$",
            "user_answer": "2", "is_correct": False,
            "correct_answer": "-2", "explanation": cls.long_expl,
        }]})
        assert r.json()["success"], r.text

    def test_01_list_returns_star_scores(self):
        r = requests.get(BASE + "/api/kb/errors", headers=self.h, timeout=30,
                         params={"subject": SUBJECT})
        rows = r.json()["data"]
        self.assertTrue(rows, "错题应已入池")
        e = rows[0]
        # P1 契约：难度/重要度随列表返回，默认 5.0（0-10 存储分）
        self.assertIn("difficulty_score", e)
        self.assertIn("importance_score", e)
        self.assertEqual(e["difficulty_score"], 5.0)
        self.assertEqual(e["importance_score"], 5.0)

    def test_02_explanation_full_no_truncation_field(self):
        r = requests.get(BASE + "/api/kb/errors", headers=self.h, timeout=30,
                         params={"subject": SUBJECT})
        e = r.json()["data"][0]
        # 后端返回全文（截断曾在前端；后端全文 + 前端不再 truncate 即完整）
        self.assertEqual(e["explanation"], self.long_expl)
        self.assertGreater(len(e["explanation"]), 300)


class TestP2Inherit(unittest.TestCase):
    """P2：入池继承 + 防重复 + 练习历史"""

    @classmethod
    def setUpClass(cls):
        cls.token = register_and_token("eu_p2_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}
        r = requests.post(BASE + "/api/knowledge/point-new", headers=cls.h, timeout=30,
                          json={"point": {"name": "矩阵求逆", "description": "伴随矩阵法与初等行变换法"},
                                "subject": SUBJECT})
        assert r.json()["success"], r.text
        cls.pid = int(r.json()["data"]["knowledge_id"])

    def _errors(self):
        r = requests.get(BASE + "/api/kb/errors", headers=self.h, timeout=30,
                         params={"subject": SUBJECT})
        return r.json()["data"]

    def test_01_stars_endpoint_wers(self):
        """调星端点（kind=error）对错题生效，列表读回新值"""
        self._seed_error()
        errs = self._errors()
        self.assertTrue(errs)
        eid = errs[0]["id"]
        r = requests.post(BASE + f"/api/kb/error/{eid}/stars", headers=self.h, timeout=30,
                          json={"difficulty": 8, "importance": 6})
        self.assertTrue(r.json()["success"], r.text)
        got = [x for x in self._errors() if x["id"] == eid][0]
        self.assertEqual(got["difficulty_score"], 8.0)
        self.assertEqual(got["importance_score"], 6.0)

    def _seed_error(self):
        requests.post(BASE + "/api/practice/results", headers=self.h, timeout=30, json={"records": [{
            "subject_name": SUBJECT, "knowledge_point_id": self.pid,
            "question_content": "A^{-1} 等于什么", "user_answer": "错答", "is_correct": False,
            "correct_answer": "伴随/|A|", "explanation": "用伴随矩阵公式",
        }]})

    def test_02_practice_submit_inherits_difficulty(self):
        """practice-submit 答错入池：q.difficulty 映射难度分（容易→3 中等→5 困难→8）"""
        q = [{"type": "single", "question": f"继承测试Q 2A?", "options": ["a", "b", "c", "d"],
              "correct_answer": "A", "difficulty": "困难", "explanation": "e"}]
        r = requests.post(BASE + f"/api/knowledge/points/{self.pid}/practice-submit",
                          headers=self.h, timeout=120,
                          json={"questions": q, "answers": ["B"]})
        body = r.json()
        self.assertTrue(body.get("success"), r.text)
        hit = [x for x in self._errors() if x["question_content"] == "继承测试Q 2A?"]
        self.assertTrue(hit, "答错题应入池")
        self.assertEqual(hit[0]["difficulty_score"], 8.0)
        # 重要度继承知识点当前值（新知识点默认 5.0）
        self.assertEqual(hit[0]["importance_score"], 5.0)

    def test_03_reerror_not_duplicated(self):
        """同题重练再答错：不重复入池（同题干只保有一行待强化）"""
        q = [{"type": "single", "question": f"重复防护Q 3B?", "options": ["a", "b", "c", "d"],
              "correct_answer": "A", "difficulty": "中等", "explanation": "e"}]
        for _ in range(2):
            r = requests.post(BASE + f"/api/knowledge/points/{self.pid}/practice-submit",
                              headers=self.h, timeout=120,
                              json={"questions": q, "answers": ["C"]})
            self.assertTrue(r.json().get("success"), r.text)
        hit = [x for x in self._errors() if x["question_content"] == "重复防护Q 3B?"]
        self.assertEqual(len(hit), 1, "同题干答错多次只应有一行错题")

    def test_04_practice_history(self):
        """错题练习历史：重练流水可挂回该错题"""
        errs = self._errors()
        target = [x for x in errs if x["question_content"] == "重复防护Q 3B?"][0]
        eid = target["id"]
        # 单题重练一次（答对）
        q = [{"type": "single", "question": target["question_content"], "options": ["a", "b", "c", "d"],
              "correct_answer": "A", "difficulty": "中等", "explanation": "e"}]
        r = requests.post(BASE + "/api/practice/error-set-submit", headers=self.h, timeout=120,
                          json={"subject_name": SUBJECT,
                                "questions": [dict(q[0], error_id=eid)], "answers": ["A"]})
        body = r.json()
        self.assertTrue(body.get("success"), r.text)
        h = requests.get(BASE + f"/api/kb/errors/{eid}/practice-history", headers=self.h, timeout=30)
        rows = h.json()["data"]
        self.assertTrue(rows, "练习历史应至少含本次重练")
        self.assertEqual(rows[0]["is_correct"], 1)


class TestP3Pool(unittest.TestCase):
    """P3：科目级 error-pool 三模式 + error-set-submit 双写 + 派生入池裁定"""

    @classmethod
    def setUpClass(cls):
        cls.token = register_and_token("eu_p3_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}
        r = requests.post(BASE + "/api/knowledge/point-new", headers=cls.h, timeout=30,
                          json={"point": {"name": "函数连续性", "description": "可去/跳跃/无穷间断点分类"},
                                "subject": SUBJECT})
        assert r.json()["success"], r.text
        cls.pid = int(r.json()["data"]["knowledge_id"])
        for i, (ans, corr) in enumerate([("B", "A"), ("C", "A")]):
            r = requests.post(BASE + "/api/practice/results", headers=cls.h, timeout=30, json={"records": [{
                "subject_name": SUBJECT, "knowledge_point_id": cls.pid,
                "question_content": f"P3组卷题干{i}?", "user_answer": ans, "is_correct": False,
                "correct_answer": corr, "explanation": f"解析{i}",
                "question_type": "single", "options": ["a", "b", "c", "d"],
            }]})
            assert r.json()["success"], r.text

    def _errors(self):
        r = requests.get(BASE + "/api/kb/errors", headers=self.h, timeout=30,
                         params={"subject": SUBJECT})
        return r.json()["data"]

    def test_01_pool_smart(self):
        """smart：FSRS 三因子组卷，每题带 error_id/kp_id，题干不重复"""
        r = requests.post(BASE + "/api/practice/error-pool", headers=self.h, timeout=30,
                          json={"subject": SUBJECT, "mode": "smart", "count": 5})
        data = r.json()["data"]
        self.assertTrue(data.get("success"), r.text)
        qs = data["questions"]
        self.assertEqual(len(qs), 2)
        for q in qs:
            self.assertIsNotNone(q["error_id"])
            self.assertEqual(q["kp_id"], self.pid)
            self.assertIn(q["type"], ("single", "judge", "fill", "short"))
        self.assertEqual(len({q["question"] for q in qs}), len(qs))

    def test_02_pool_manual_and_single(self):
        errs = self._errors()
        ids = [e["id"] for e in errs]
        r = requests.post(BASE + "/api/practice/error-pool", headers=self.h, timeout=30,
                          json={"subject": SUBJECT, "mode": "manual", "error_ids": ids})
        self.assertTrue(r.json()["data"]["success"], r.text)
        self.assertEqual(len(r.json()["data"]["questions"]), len(ids))
        # single：练这题
        r = requests.post(BASE + "/api/practice/error-pool", headers=self.h, timeout=30,
                          json={"subject": SUBJECT, "mode": "single", "error_id": ids[0]})
        qs = r.json()["data"]["questions"]
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0]["error_id"], ids[0])
        # 跨用户/不存在 id 拦截
        r = requests.post(BASE + "/api/practice/error-pool", headers=self.h, timeout=30,
                          json={"subject": SUBJECT, "mode": "single", "error_id": 99999999})
        self.assertFalse(r.json()["data"]["success"])

    def test_03_set_submit_dual_write(self):
        """重练答对：错题行 FSRS 熟练度写入 + kp 掌握度同步更新 + 流水挂回（用户裁定 1）"""
        r = requests.post(BASE + "/api/practice/error-pool", headers=self.h, timeout=30,
                          json={"subject": SUBJECT, "mode": "single", "error_id": self._errors()[0]["id"]})
        q = r.json()["data"]["questions"][0]
        eid = q["error_id"]
        r = requests.post(BASE + "/api/practice/error-set-submit", headers=self.h, timeout=120,
                          json={"subject_name": SUBJECT, "questions": [q], "answers": [q["correct_answer"]]})
        body = r.json()["data"]
        self.assertTrue(body.get("success"), r.text)
        self.assertEqual(body["correct_count"], 1)
        self.assertIn(str(self.pid), body["kp_mastery"])  # kp 分组折叠更新
        # 错题行熟练度被 FSRS 写入（之前未评估）
        got = [x for x in self._errors() if x["id"] == eid][0]
        self.assertIsNotNone(got["current_proficiency"])
        h = requests.get(BASE + f"/api/kb/errors/{eid}/practice-history", headers=self.h, timeout=30).json()["data"]
        self.assertTrue(any(row["is_correct"] == 1 for row in h))

    def test_04_derived_wrong_pools_new_row(self):
        """派生题（新题干）答错：照常入池新行；流水仍挂 root；root 原题行不堆行"""
        eid = self._errors()[0]["id"]
        derived = {"type": "single", "question": "P3派生新题干XYZ?", "options": ["a", "b", "c", "d"],
                   "correct_answer": "A", "difficulty": "困难", "explanation": "d", "error_id": eid, "kp_id": self.pid}
        r = requests.post(BASE + "/api/practice/error-set-submit", headers=self.h, timeout=120,
                          json={"subject_name": SUBJECT, "questions": [derived], "answers": ["B"]})
        body = r.json()["data"]
        self.assertTrue(body.get("success"), r.text)
        self.assertTrue(body["detailed_results"][0]["derived"])
        errs = self._errors()
        # 新题干入池（继承标注难度 8 + root 重要度）
        new = [x for x in errs if x["question_content"] == "P3派生新题干XYZ?"]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["difficulty_score"], 8.0)
        # root 原题仍只有一行（重练路径未受派生影响；本例只答了派生题）
        self.assertEqual(len([x for x in errs if x["question_content"].startswith("P3组卷题干")]), 2)
        # 派生流水挂 root：历史含答错记录
        h = requests.get(BASE + f"/api/kb/errors/{eid}/practice-history", headers=self.h, timeout=30).json()["data"]
        self.assertTrue(any(row["question_content"] == "P3派生新题干XYZ?" and row["is_correct"] == 0 for row in h))


class TestP4Service(unittest.TestCase):
    """P4：报告服务纯函数——extract_json_object 围栏/修复；validate_report 严格校验与幻觉 ID 过滤"""

    @classmethod
    def setUpClass(cls):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from services import weakness_report as WR
        cls.WR = WR

    def test_01_extract_fenced_and_trailing_comma(self):
        obj = self.WR.extract_json_object('```json\n{"summary_md": "a", "nodes": [1,],}\n```')
        self.assertEqual(obj["summary_md"], "a")
        with self.assertRaises(ValueError):
            self.WR.extract_json_object("模型拒绝回答，没有 JSON")

    def test_02_validate_strict(self):
        vid = {11, 12}
        rep = self.WR.validate_report({"summary_md": "## 总体", "nodes": [
            {"name": "行列式", "kind": "kp", "status": "weak", "evidence": [11, 99999, "12"],
             "children": [{"name": "符号展开失误", "kind": "point", "status": "weak"}]}]}, vid)
        # 幻觉 ID 过滤、字符串数字归一、children 缺省补齐
        self.assertEqual(rep["nodes"][0]["evidence"], [11, 12])
        self.assertEqual(rep["nodes"][0]["children"][0]["evidence"], [])
        for bad in ({"summary_md": "", "nodes": []},
                    {"summary_md": "x", "nodes": []},
                    {"summary_md": "x", "nodes": [{"name": "n", "kind": "kp", "status": "maybe"}]},
                    {"summary_md": "x", "nodes": [{"name": "", "kind": "kp", "status": "ok"}]},
                    {"summary_md": "x", "nodes": [{"name": "n", "kind": "other", "status": "ok"}]}):
            with self.assertRaises(ValueError):
                self.WR.validate_report(bad, vid)


class TestP4Report(unittest.TestCase):
    """P4：报告生成→落库→列表/详情；校验失败不落库（进程内 test client + monkeypatch LLM）"""

    @classmethod
    def setUpClass(cls):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        cls.c = app.test_client()
        u = "eu_p4_" + uuid.uuid4().hex[:8]
        r = cls.c.post("/api/auth/register", json={"username": u, "password": "test123456"})
        assert r.status_code == 200, r.get_json()
        cls.h = {"Authorization": "Bearer " + r.get_json()["data"]["token"]}
        cls.subj = f"薄弱报告{uuid.uuid4().hex[:6]}"
        r = cls.c.post("/api/knowledge/point-new", headers=cls.h,
                       json={"point": {"name": "行列式计算", "description": "二阶三阶展开法则"},
                             "subject": cls.subj})
        assert r.get_json()["success"], r.get_json()
        r = cls.c.post("/api/practice/results", headers=cls.h, json={"records": [{
            "subject_name": cls.subj, "knowledge_point_id": int(r.get_json()["data"]["knowledge_id"]),
            "question_content": "求二阶行列式 |1 2; 3 4|?", "user_answer": "2", "is_correct": False,
            "correct_answer": "-2", "explanation": "按第一行展开得 -2"}]})
        assert r.get_json()["success"], r.get_json()
        rows = cls.c.get("/api/kb/errors?subject=" + cls.subj, headers=cls.h).get_json()["data"]
        cls.eid = rows[0]["id"]

    def _fake_llm(self, payload):
        """临时替换 routes_bridge._llm_call（测试结束恢复，不发真实请求不耗积分）。"""
        import routes_bridge
        original = routes_bridge._llm_call
        routes_bridge._llm_call = lambda p, c="": payload
        self.addCleanup(setattr, routes_bridge, "_llm_call", original)

    def _reports(self):
        return self.c.get("/api/practice/weakness-reports?subject=" + self.subj,
                          headers=self.h).get_json()["data"]

    def test_01_generate_global_persist_and_read(self):
        import json as _json
        good = _json.dumps({"summary_md": "## 总体\n薄弱：符号展开，公式 $m \\geq -1$",
                            "nodes": [{"name": "行列式计算", "kind": "kp", "status": "weak",
                                       "evidence": [self.eid, 999999],
                                       "children": [{"name": "符号展开失误", "kind": "point",
                                                     "status": "weak", "evidence": [self.eid]}]}]},
                           ensure_ascii=False)
        self._fake_llm(good)
        r = self.c.post("/api/practice/weakness-report", headers=self.h,
                        json={"subject": self.subj, "scope": "global"})
        d = r.get_json()["data"]
        self.assertTrue(d.get("success"), d)
        self.assertTrue(d["report_id"])
        self.assertEqual(d["nodes"][0]["evidence"], [self.eid])  # 幻觉 ID 已过滤
        lst = self._reports()
        self.assertTrue(lst["success"] and len(lst["reports"]) == 1)
        self.assertEqual(lst["reports"][0]["error_count"], 1)
        det = self.c.get(f"/api/practice/weakness-report/{d['report_id']}", headers=self.h).get_json()["data"]
        self.assertTrue(det["success"])
        self.assertEqual(det["report"]["report_md"], d["report_md"])
        self.assertEqual(det["report"]["nodes"][0]["children"][0]["status"], "weak")

    def test_02_bad_llm_json_not_persisted(self):
        before = len(self._reports()["reports"])
        self._fake_llm("模型返回了一堆废话，没有 JSON")
        d = self.c.post("/api/practice/weakness-report", headers=self.h,
                        json={"subject": self.subj, "scope": "global"}).get_json()["data"]
        self.assertFalse(d["success"])
        self.assertIn("校验", d["error"])
        self.assertEqual(len(self._reports()["reports"]), before)  # 失败不落库

    def test_03_selected_and_contract_guards(self):
        d = self.c.post("/api/practice/weakness-report", headers=self.h,
                        json={"subject": self.subj, "scope": "selected", "error_ids": [99999999]}).get_json()["data"]
        self.assertFalse(d["success"])  # 错题不存在
        d = self.c.post("/api/practice/weakness-report", headers=self.h,
                        json={"scope": "global"}).get_json()["data"]
        self.assertFalse(d["success"])  # subject 必填
        d = self.c.post("/api/practice/weakness-report", headers=self.h,
                        json={"subject": self.subj, "scope": "other"}).get_json()["data"]
        self.assertFalse(d["success"])  # 非法 scope
        d = self.c.get("/api/practice/weakness-report/99999999", headers=self.h).get_json()["data"]
        self.assertFalse(d["success"])  # 不存在报告
        # selected 真实错题：勾选范围可生成（新报告落库，列表 +1）
        import json as _json
        self._fake_llm(_json.dumps({"summary_md": "勾选题目分析", "nodes": [
            {"name": "行列式", "kind": "kp", "status": "weak", "evidence": [self.eid]}]}, ensure_ascii=False))
        before = len(self._reports()["reports"])
        d = self.c.post("/api/practice/weakness-report", headers=self.h,
                        json={"subject": self.subj, "scope": "selected", "error_ids": [self.eid]}).get_json()["data"]
        self.assertTrue(d.get("success"), d)
        self.assertEqual(len(self._reports()["reports"]), before + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
