"""公式定界符落库兜底断言测试（2026-10-15 用户裁定 B）。

模式同 test_error_unit_upgrade.py：HTTP 集成测真实服务（127.0.0.1:6001），
独立测试用户 + 独立学科隔离数据，不污染正式数据。

覆盖：
- practice/results 错题入池：裸 LaTeX 题干/答案/解析落库前补 $$ 定界；user_answer 如实原文不动
- POST /api/kb/errors 手动录题：同兜底
- PUT /api/kb/errors/<eid> 编辑：同兜底
- 幂等：已带定界符的内容读回不变（不二次包裹）
- 行为边界锁定：中英混合叙述行（保守判定刻意不包）原样保留
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
SUBJECT = f"定界兜底{int(time.time()) % 100000}_{uuid.uuid4().hex[:4]}"

# 整行裸 LaTeX（强特征 \命令，_wrap_bare_latex 判定必包）
BARE_LINE = "x = \\frac{-b \\pm \\sqrt{\\Delta}}{2a}"
# 中英混合叙述行（无强特征，保守判定刻意不包——id=1253 真实形态）
PROSE_LINE = "Δ=(n-4)^2-4(-4n)=n^2+8n+16=(n+4)^2≥0。方程可化为 (x-4)(x+n)=0。"


def register_and_token(username: str) -> str:
    requests.post(BASE + "/api/auth/register",
                  json={"username": username, "password": "test123456"}, timeout=15)
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["token"]


class TestMathDelimiterGuard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.token = register_and_token("mdg_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}
        r = requests.post(BASE + "/api/knowledge/point-new", headers=cls.h, timeout=30,
                          json={"point": {"name": "一元二次方程", "description": "判别式与求根公式"},
                                "subject": SUBJECT})
        assert r.json()["success"], r.text
        cls.pid = int(r.json()["data"]["knowledge_id"])

    # ---- 1. 练习流水入池兜底 ----

    def test_01_practice_results_wraps_bare(self):
        expl = "解方程过程：\n" + BARE_LINE
        r = requests.post(BASE + "/api/practice/results", headers=self.h, timeout=30, json={"records": [{
            "subject_name": SUBJECT, "knowledge_point_id": self.pid,
            "question_content": "用求根公式解 $ax^2+bx+c=0$：\n" + BARE_LINE,
            "user_answer": BARE_LINE,  # 用户原始作答：不得被包裹
            "is_correct": False,
            "correct_answer": BARE_LINE, "explanation": expl,
        }]})
        assert r.json()["success"], r.text
        e = self._find("用求根公式解")
        self.assertIn("$$" + BARE_LINE + "$$", e["explanation"].replace("\r", ""))
        self.assertIn("$$", e["question_content"])
        self.assertEqual(e["correct_answer"], "$$" + BARE_LINE + "$$")
        # user_answer 如实留原文（迁移脚本既有纪律）
        self.assertNotIn("$$", e["user_answer"])

    # ---- 2. 手动录题兜底 ----

    def test_02_manual_error_wraps_bare(self):
        r = requests.post(BASE + "/api/kb/errors", headers=self.h, timeout=30, json={
            "subject_name": SUBJECT, "knowledge_point_id": self.pid,
            "question": "手动录入裸公式题：\n" + BARE_LINE,
            "correct_answer": BARE_LINE, "explanation": "推导：\n" + BARE_LINE})
        assert r.json()["success"], r.text
        e = self._find("手动录入裸公式题")
        self.assertIn("$$" + BARE_LINE + "$$", e["question_content"])
        self.assertIn("$$" + BARE_LINE + "$$", e["explanation"])

    # ---- 3. 编辑兜底 ----

    def test_03_error_edit_wraps_bare(self):
        e = self._find("手动录入裸公式题")
        r = requests.put(BASE + f"/api/kb/errors/{e['id']}", headers=self.h, timeout=30,
                         json={"explanation": "改后裸解析：\n" + BARE_LINE})
        assert r.json()["data"]["updated"] is True, r.text
        e2 = self._find("手动录入裸公式题")
        self.assertIn("$$" + BARE_LINE + "$$", e2["explanation"])

    # ---- 4. 幂等：已带定界符不变 ----

    def test_04_already_delimited_untouched(self):
        wrapped = "$$" + BARE_LINE + "$$"
        r = requests.post(BASE + "/api/kb/errors", headers=self.h, timeout=30, json={
            "subject_name": SUBJECT, "knowledge_point_id": self.pid,
            "question": "已定界题 " + wrapped,
            "correct_answer": wrapped, "explanation": wrapped})
        assert r.json()["success"], r.text
        e = self._find("已定界题")
        self.assertEqual(e["explanation"], wrapped)  # 不二次包裹
        self.assertEqual(e["correct_answer"], wrapped)

    # ---- 5. 行为边界：混合叙述行刻意不包（保守判定宁漏不错包） ----

    def test_05_prose_mixed_line_not_wrapped(self):
        r = requests.post(BASE + "/api/kb/errors", headers=self.h, timeout=30, json={
            "subject_name": SUBJECT, "knowledge_point_id": self.pid,
            "question": "叙述行边界题：若 n 为整数，则取值范围是______。",
            "correct_answer": "n≥-3", "explanation": PROSE_LINE})
        assert r.json()["success"], r.text
        e = self._find("叙述行边界题")
        self.assertEqual(e["explanation"], PROSE_LINE)  # 原样保留，不误包

    def _find(self, keyword: str) -> dict:
        rows = requests.get(BASE + "/api/kb/errors", headers=self.h, timeout=30,
                            params={"subject": SUBJECT}).json()["data"]
        for e in rows:
            if keyword in (e.get("question_content") or ""):
                return e
        self.fail("未找到含关键字的错题: " + keyword)


if __name__ == "__main__":
    unittest.main(verbosity=2)
