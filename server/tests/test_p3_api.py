"""
P3 业务 API 全链路测试（真实调用 DeepSeek）。

覆盖：配置读取 / 科目CRUD / 提取(D1含subject_name) / 确认 / 知识点列表 /
统计 / vault 文件读写与目录穿越防护 / 练习出题与答题入库错题 / 未认证401。
运行前置：服务端已在 127.0.0.1:6001 运行。
"""
from __future__ import annotations

import sys
import time
import unittest

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:6001"
SUBJECT = f"P3测试学科{int(time.time())}"

NOTE_TEXT = (
    "导数是微积分的核心概念之一。函数 f(x) 在 x0 处的导数定义为增量比的极限："
    "f'(x0) = lim(Δx→0) [f(x0+Δx) - f(x0)] / Δx。"
    "几何上，导数表示曲线在该点处切线的斜率。"
    "可导必连续，但连续不一定可导，例如 y=|x| 在 x=0 处连续但不可导。"
    "常用求导法则包括四则运算法则、复合函数链式法则与反函数求导法则。"
)


def _login_admin() -> str:
    r = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"}, timeout=10)
    r.raise_for_status()
    return r.json()["data"]["token"]


class TestP3Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = _login_admin()
        cls.h = {"Authorization": f"Bearer {cls.token}"}

    def _get(self, path, **kw):
        return requests.get(f"{BASE}{path}", headers=self.h, timeout=kw.pop("timeout", 60), **kw)

    def _post(self, path, **kw):
        return requests.post(f"{BASE}{path}", headers=self.h, timeout=kw.pop("timeout", 120), **kw)

    # ---- 认证与配置 ----
    def test_01_unauthenticated_401(self):
        r = requests.get(f"{BASE}/api/subjects", timeout=10)
        self.assertEqual(r.status_code, 401)

    def test_02_config_no_secret_leak(self):
        r = self._get("/api/config")
        self.assertTrue(r.json()["success"])
        cfg = r.json()["data"]
        self.assertTrue(cfg["has_deepseek_key"])
        # deepseek_api_key 允许掩码回显（设置页表单需要，保存时掩码值被服务端忽略）；
        # 断言：仅尾 4 位可见，绝不泄漏完整 key；其余密钥字段不得出现
        ds = cfg.get("deepseek_api_key", "")
        self.assertTrue(ds == "" or (ds.startswith("•") and len(ds) <= 12), f"mask 异常: {ds!r}")
        for k in ("api_key", "deepgram_api_key", "jwt_secret"):
            self.assertNotIn(k, cfg)

    # ---- 科目 ----
    def test_03_subject_crud(self):
        r = self._post("/api/subjects", json={"subject_name": SUBJECT})
        self.assertTrue(r.json()["success"], r.text)
        r = self._get("/api/subjects")
        self.assertIn(SUBJECT, r.json()["data"])

    # ---- 提取（真实 DeepSeek，D1 修复断言）----
    def test_04_extract_requires_subject(self):
        r = self._post("/api/knowledge/extract", json={"text": NOTE_TEXT})
        self.assertEqual(r.status_code, 400)

    def test_05_extract_with_llm(self):
        r = self._post("/api/knowledge/extract", json={"text": NOTE_TEXT, "subject_name": SUBJECT})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertTrue(body["success"], body)
        points = body["data"]["processed_points"]
        self.assertGreaterEqual(len(points), 1, "DeepSeek 应至少提取出 1 个核心概念")
        # 供确认测试使用
        type(self).extracted = points

    # ---- 确认 → 知识点列表 → 统计 ----
    def test_06_confirm_and_list(self):
        if not hasattr(type(self), "extracted"):
            self.skipTest("提取测试未产生数据")
        confirmations = []
        for item in self.extracted[:3]:
            ep = item["extracted_point"]
            confirmations.append({
                "action": "new",
                "point_data": {
                    "point_name": ep.get("concept_name") or ep.get("point_name") or "未命名",
                    "core_description": ep.get("core_definition") or ep.get("core_description") or "",
                },
                "subject_name": SUBJECT,
            })
        r = self._post("/api/knowledge/confirm", json={"confirmations": confirmations})
        self.assertTrue(r.json()["success"], r.text)
        saved_ids = r.json()["data"]["saved_point_ids"]
        self.assertGreaterEqual(len(saved_ids), 1)
        type(self).kp_id = saved_ids[0]

        r = self._get("/api/knowledge/points", params={"subject": SUBJECT})
        names = [p["point_name"] for p in r.json()["data"]]
        self.assertGreaterEqual(len(names), 1)

        r = self._get("/api/subjects/stats")
        stats = {s["subject_name"]: s for s in r.json()["data"]}
        self.assertGreaterEqual(stats[SUBJECT]["kp_count"], 1)

    # ---- vault 文件 ----
    def test_07_vault_write_read_tree(self):
        rel = f"notes/p3-{int(time.time())}.md"
        r = requests.put(f"{BASE}/api/vault/file", headers=self.h,
                         json={"path": rel, "content": "# P3 测试笔记\n导数"}, timeout=30)
        self.assertTrue(r.json()["success"], r.text)
        note_uuid = r.json()["data"]["note_uuid"]
        self.assertTrue(note_uuid)
        type(self).note_uuid = note_uuid

        r = self._get("/api/vault/file", params={"path": rel})
        self.assertIn("P3 测试笔记", r.json()["data"]["content"])

        r = self._get("/api/vault/tree")
        paths = [item["path"] for item in r.json()["data"]]
        self.assertIn(rel, paths)

    def test_08_vault_path_traversal_blocked(self):
        r = requests.put(f"{BASE}/api/vault/file", headers=self.h,
                         json={"path": "../../evil.md", "content": "x"}, timeout=30)
        self.assertEqual(r.status_code, 403)

    # ---- 练习：出题（真实 DeepSeek）→ 答题入库 → 错题可见 ----
    def test_09_practice_generate(self):
        if not hasattr(type(self), "kp_id"):
            self.skipTest("无知识点 ID")
        r = self._post("/api/practice/generate", json={
            "subject_name": SUBJECT, "knowledge_point_id": self.kp_id, "count": 2,
        })
        self.assertEqual(r.status_code, 200, r.text)
        questions = r.json()["data"]
        self.assertGreaterEqual(len(questions), 1, "工厂收敛后应能经 DeepSeek 正常出题")
        type(self).question = questions[0]

    def test_10_submit_results_creates_error(self):
        if not hasattr(type(self), "question"):
            self.skipTest("无题目")
        q = self.question
        record = {
            "subject_name": SUBJECT,
            "knowledge_point_id": self.kp_id,
            "question_content": q.get("question", ""),
            "user_answer": "测试错误答案",
            "is_correct": False,
            "correct_answer": q.get("correct_answer"),
            "explanation": q.get("explanation"),
        }
        r = self._post("/api/practice/results", json={"records": [record]})
        self.assertTrue(r.json()["success"], r.text)
        self.assertGreaterEqual(len(r.json()["data"]["saved_record_ids"]), 1)

        r = self._get("/api/kb/errors", params={"subject": SUBJECT, "kp_id": self.kp_id})
        errors = r.json()["data"]
        self.assertGreaterEqual(len(errors), 1, "答错应自动进入错题库")
        type(self).error_id = errors[0]["id"]

    def test_11_error_history_and_reviewed(self):
        if not hasattr(type(self), "error_id"):
            self.skipTest("无错题 ID")
        r = self._post(f"/api/kb/errors/{self.error_id}/proficiency", json={"proficiency": 45})
        self.assertTrue(r.json()["success"], r.text)
        r = self._get(f"/api/kb/errors/{self.error_id}/history")
        hist = r.json()["data"]
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["proficiency"], 45)
        r = self._post(f"/api/kb/errors/{self.error_id}/reviewed")
        self.assertTrue(r.json()["data"]["reviewed"])

    def test_99_cleanup_subject(self):
        # 有知识点的学科应拒绝删除（隔离与约束验证）
        r = requests.delete(f"{BASE}/api/subjects/{SUBJECT}", headers=self.h, timeout=30)
        self.assertEqual(r.status_code, 400, "有知识点的学科应拒绝删除")


if __name__ == "__main__":
    unittest.main(verbosity=2)
