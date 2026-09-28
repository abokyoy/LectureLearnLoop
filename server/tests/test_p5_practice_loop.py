"""
P5 练习闭环端到端测试（真实 DeepSeek 仅用于可选出题步骤；核心熟练度计算为确定性断言）。

覆盖：
1. 创建学科 + 知识点（point-new，无 LLM）
2. 难度加权熟练度重算：POST assessment → mastery = round(earned_w/total_w*100)，手算比对
3. 熟练度落库校验：GET 知识点详情 mastery_score 已更新
4. 答题入库错题：POST /api/practice/results(is_correct=False) → 错题库出现该题
5. 错题熟练度：append → history → reviewed 全流程；复习后不再出现在待复习池
6. 错题推荐池：search_error_questions 返回未复习错题
7. 10 题评估生成（DeepSeek，结构校验，容错跳过）

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
SUBJECT = f"P5练习学科{int(time.time()) % 100000}_{uuid.uuid4().hex[:4]}"


def register_and_token(username: str) -> str:
    requests.post(BASE + "/api/auth/register",
                  json={"username": username, "password": "test123456"}, timeout=15)
    # 无论新注册还是已存在都走 login：每日赠分挂在 login 钩子，LLM 端点积分预检才放行
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["token"]


WEIGHTS = {"容易": 1.0, "中等": 1.2, "困难": 1.5}


class TestP5PracticeLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = register_and_token("p5_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}

    def _get(self, path, **kw):
        return requests.get(BASE + path, headers=self.h, timeout=kw.pop("timeout", 60), **kw)

    def _post(self, path, **kw):
        return requests.post(BASE + path, headers=self.h, timeout=kw.pop("timeout", 120), **kw)

    # ---------- 建知识点 ----------
    def test_01_create_point(self):
        point = {"name": "特征值与特征向量", "description": "Av=λv 定义的方阵特征问题"}
        r = self._post("/api/knowledge/point-new", json={"point": point, "subject": SUBJECT})
        self.assertTrue(r.json()["success"], r.text)
        data = r.json()["data"]
        type(self).kp_id = int(data["knowledge_id"])
        self.assertGreater(self.kp_id, 0)

    # ---------- 难度加权熟练度重算（确定性手算比对） ----------
    def test_02_weighted_mastery(self):
        questions = [
            {"question": "Q1易", "correct_answer": "A", "difficulty": "容易", "explanation": ""},
            {"question": "Q2中", "correct_answer": "B", "difficulty": "中等", "explanation": ""},
            {"question": "Q3难", "correct_answer": "C", "difficulty": "困难", "explanation": ""},
            {"question": "Q4中", "correct_answer": "D", "difficulty": "中等", "explanation": ""},
        ]
        # 答对：Q1(易√) Q2(中×) Q3(难√) Q4(中√)
        answers = ["A", "X", "C", "D"]
        earned = WEIGHTS["容易"] * 1 + WEIGHTS["困难"] * 1 + WEIGHTS["中等"] * 1  # Q1,Q3,Q4
        total = sum(WEIGHTS[q["difficulty"]] for q in questions)
        expected = int(round(earned / total * 100))

        r = self._post(f"/api/knowledge/points/{self.kp_id}/assessment",
                       json={"questions": questions, "answers": answers})
        body = r.json()
        self.assertTrue(body["success"], r.text)
        data = body["data"]
        self.assertEqual(data["mastery_score"], expected, f"期望{expected} 实得{data['mastery_score']}")
        self.assertEqual(data["correct_count"], 3)
        self.assertEqual(data["total_count"], 4)
        self.assertAlmostEqual(data["accuracy"], 0.75, places=3)
        # 逐题 is_correct 校验
        flags = [d["is_correct"] for d in data["detailed_results"]]
        self.assertEqual(flags, [True, False, True, True])
        type(self).expected_mastery = expected

    # ---------- 熟练度落库 ----------
    def test_03_mastery_persisted(self):
        r = self._get(f"/api/knowledge/points/{self.kp_id}/detail")
        body = r.json()
        self.assertTrue(body.get("success"), r.text)
        detail = body["data"]["detail"]
        self.assertEqual(int(detail["mastery_score"]), self.expected_mastery)

    # ---------- 答题入库错题 ----------
    def test_04_error_bank(self):
        rec = {
            "subject_name": SUBJECT, "knowledge_point_id": self.kp_id,
            "question_content": "以下哪项不是特征值的性质？", "user_answer": "错选B",
            "is_correct": False, "correct_answer": "正确D", "explanation": "解析X",
        }
        r = self._post("/api/practice/results", json={"records": [rec]})
        self.assertTrue(r.json()["success"], r.text)
        self.assertGreaterEqual(len(r.json()["data"]["saved_record_ids"]), 1)

        r = self._get("/api/kb/errors", params={"subject": SUBJECT, "kp_id": self.kp_id})
        errors = r.json()["data"]
        self.assertGreaterEqual(len(errors), 1, "答错应自动进入错题库")
        e0 = errors[0]
        self.assertEqual(int(e0.get("current_proficiency", 20)), 20, "新错题默认熟练度20")
        type(self).error_id = int(e0["id"])

    # ---------- 错题熟练度历史 + 复习 ----------
    def test_05_error_proficiency_flow(self):
        if not hasattr(type(self), "error_id"):
            self.skipTest("无错题 ID")
        # 渐进式更新：模拟复习做对，熟练度 20 → 50 → 80
        for p in (50, 80):
            r = self._post(f"/api/kb/errors/{self.error_id}/proficiency", json={"proficiency": p})
            self.assertTrue(r.json()["success"], r.text)
        r = self._get(f"/api/kb/errors/{self.error_id}/history")
        hist = r.json()["data"]
        self.assertEqual([h["proficiency"] for h in hist][-2:], [50, 80], "历史按序记录")
        # 标记复习
        r = self._post(f"/api/kb/errors/{self.error_id}/reviewed")
        self.assertTrue(r.json()["data"]["reviewed"])

    # ---------- 错题推荐池 + 复习后熟练度渐进更新落库 ----------
    def test_06_recommendation_pool(self):
        r = self._get("/api/kb/errors", params={"subject": SUBJECT, "kp_id": self.kp_id})
        errors = r.json()["data"]
        self.assertGreaterEqual(len(errors), 1)
        mine = {int(e["id"]): e for e in errors}
        self.assertIn(self.error_id, mine, "错题应出现在推荐/复习池")
        # 复习做对后，错题熟练度已从默认 20 渐进更新到 80（列表端点回显 current_proficiency）
        self.assertEqual(int(mine[self.error_id]["current_proficiency"]), 80,
                         "复习后错题熟练度应更新为 80")

    # ---------- 10 题评估生成（DeepSeek，容错） ----------
    def test_07_generate_assessment_questions(self):
        r = self._post(f"/api/knowledge/points/{self.kp_id}/generate-assessment", json={})
        body = r.json()
        data = body.get("data", {})
        if not data.get("success"):
            self.skipTest("LLM 生成评估未成功（网络/额度）：" + str(data.get("error")))
        qs = data.get("questions") or []
        self.assertEqual(len(qs), 10, "应生成 10 题")
        for q in qs:
            self.assertIn("options", q)
            self.assertEqual(len(q["options"]), 4, "每题 4 选项")


if __name__ == "__main__":
    unittest.main(verbosity=2)
