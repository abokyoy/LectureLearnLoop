# -*- coding: utf-8 -*-
"""独立错题（手动录入）全链路 API 断言（2026-10-12 知识库管理增强）。

覆盖：
1. 手动新增独立错题（无知识点）→ 列表回显 source='manual'、题干 MD 原样
2. 新增时指定知识点归属；unbind 解绑后 knowledge_point_id 为 null
3. 编辑（PUT）在 kp 为 NULL 时题干/答案/解析仍生效（P5 锚定 NULL 适配回归）
4. move 重新绑定后编辑锁组生效（c5 排查修复回归：影子流水 kp 同步）
5. 删除知识点 → 关联错题自动解绑保留，仍可复习（rate 四档自评）
6. 删除错题（purge）后列表消失
7. subjects/stats 错题计数含独立错题
8. OCR 端点参数校验（非法路径 400；真实识别走 e2e，不在单测打外网）

运行前置：服务端已在 127.0.0.1:6001 运行（schema 迁移随启动幂等执行）。
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
SUBJECT = f"独立错题学科{int(time.time()) % 100000}_{uuid.uuid4().hex[:4]}"


def register_and_token(username: str) -> str:
    requests.post(BASE + "/api/auth/register",
                  json={"username": username, "password": "test123456"}, timeout=15)
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["token"]


class TestManualErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = register_and_token("merr_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}

    def _get(self, path, **kw):
        return requests.get(BASE + path, headers=self.h, timeout=kw.pop("timeout", 30), **kw)

    def _post(self, path, **kw):
        return requests.post(BASE + path, headers=self.h, timeout=kw.pop("timeout", 60), **kw)

    def _put(self, path, **kw):
        return requests.put(BASE + path, headers=self.h, timeout=kw.pop("timeout", 30), **kw)

    def _del(self, path, **kw):
        return requests.delete(BASE + path, headers=self.h, timeout=kw.pop("timeout", 30), **kw)

    def _list_errors(self, keyword=""):
        r = self._get(f"/api/kb/errors?subject={SUBJECT}&keyword={keyword}")
        body = r.json()
        self.assertTrue(body["success"], r.text)
        return {int(e["id"]): e for e in body["data"]}

    # ---------- 1. 知识点建（供归属/删除用例） ----------
    def test_01_create_point(self):
        r = self._post("/api/knowledge/point-new", json={
            "point": {"name": "矩阵乘法", "description": "行列点积规则"}, "subject": SUBJECT})
        self.assertTrue(r.json()["success"], r.text)
        type(self).kp_id = int(r.json()["data"]["knowledge_id"])

    # ---------- 2. 手动新增独立错题（无知识点，MD 题干含图片引用） ----------
    def test_02_manual_create_independent(self):
        md = "求极限 $\\lim\\limits_{x\\to0}\\frac{\\sin x}{x}$，如图：\n\n![题目](截图/fake.png)"
        r = self._post("/api/kb/errors", json={"subject_name": SUBJECT, "question": md})
        body = r.json()
        self.assertTrue(body["success"], r.text)
        type(self).eid_alone = int(body["data"]["id"])
        row = self._list_errors().get(self.eid_alone)
        self.assertIsNotNone(row, "独立错题应出现在科目错题列表")
        self.assertEqual(row["source"], "manual")
        self.assertIsNone(row["knowledge_point_id"], "未绑定知识点应为 null")
        self.assertEqual(row["question_content"], md, "MD 题干必须原样存取")

    # ---------- 3. 新增时指定知识点归属 ----------
    def test_03_manual_create_with_kp(self):
        r = self._post("/api/kb/errors", json={
            "subject_name": SUBJECT, "question": "计算 2x^2+3x=5 的实数解",
            "correct_answer": "x=1 或 x=-2.5", "explanation": "因式分解",
            "knowledge_point_id": self.kp_id})
        body = r.json()
        self.assertTrue(body["success"], r.text)
        type(self).eid_bound = int(body["data"]["id"])
        row = self._list_errors().get(self.eid_bound)
        self.assertEqual(int(row["knowledge_point_id"]), self.kp_id)
        self.assertEqual(row["correct_answer"], "x=1 或 x=-2.5")

    # ---------- 4. 非法知识点拒绝 ----------
    def test_04_bad_kp_rejected(self):
        r = self._post("/api/kb/errors", json={
            "subject_name": SUBJECT, "question": "x", "knowledge_point_id": 99999999})
        self.assertEqual(r.status_code, 404, r.text)

    # ---------- 4b. 跨学科绑点拒绝（CodeReview Minor-6：防两条查询链路视图不一致） ----------
    def test_04b_cross_subject_kp_rejected(self):
        r = self._post("/api/knowledge/point-new", json={
            "point": {"name": "其他学科点", "description": "d"}, "subject": SUBJECT + "_其他"})
        other_pid = int(r.json()["data"]["knowledge_id"])
        r = self._post("/api/kb/errors", json={
            "subject_name": SUBJECT, "question": "跨学科绑定题", "knowledge_point_id": other_pid})
        self.assertEqual(r.status_code, 404, "kp 存在但学科不匹配必须拒绝")
        # 清理：删掉临时建的学科知识点
        self._del(f"/api/knowledge/points/{other_pid}")

    # ---------- 4c. OCR 任务归属隔离（CodeReview Minor-5：非发起者读不到） ----------
    def test_04c_ocr_task_user_isolation(self):
        import pathlib
        import sys as _sys
        import time as _t
        _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        from services import error_ocr as eo
        tid = eo.start_ocr(r"e:\__nonexistent_for_test__.png", user_id="user-A")
        _t.sleep(0.5)  # 后台线程会因图不存在快速转 error，但归属断言不依赖终态
        self.assertIsNone(eo.get_result(tid, user_id="user-B"), "跨用户读取必须视同不存在")
        res = eo.get_result(tid, user_id="user-A")
        self.assertIsNotNone(res, "发起者本人可读")
        self.assertNotIn("user", res, "内部字段不外泄")

    # ---------- 5. 编辑独立错题（kp NULL 锚定回归） ----------
    def test_05_edit_independent(self):
        r = self._put(f"/api/kb/errors/{self.eid_alone}", json={
            "content": "改后的题干 MD v2", "correct_answer": "答案B", "explanation": "解析B"})
        self.assertTrue(r.json()["data"]["updated"], r.text)
        row = self._list_errors().get(self.eid_alone)
        self.assertEqual(row["question_content"], "改后的题干 MD v2", "NULL 归属下题干更新必须生效")
        self.assertEqual(row["correct_answer"], "答案B")
        self.assertEqual(row["explanation"], "解析B")

    # ---------- 6. 解绑：绑定题 unbind 后 kp 为 null ----------
    def test_06_unbind(self):
        r = self._post(f"/api/kb/errors/{self.eid_bound}/unbind")
        self.assertTrue(r.json()["success"], r.text)
        row = self._list_errors().get(self.eid_bound)
        self.assertIsNone(row["knowledge_point_id"])

    # ---------- 7. move 重绑后编辑仍生效（影子流水 kp 同步回归） ----------
    def test_07_move_then_edit(self):
        r = self._post(f"/api/kb/errors/{self.eid_bound}/move",
                       json={"knowledge_point_id": self.kp_id})
        self.assertTrue(r.json()["data"]["moved"], r.text)
        r = self._put(f"/api/kb/errors/{self.eid_bound}", json={"content": "重绑后改题干"})
        self.assertTrue(r.json()["data"]["updated"], r.text)
        row = self._list_errors().get(self.eid_bound)
        self.assertEqual(row["question_content"], "重绑后改题干",
                         "move 后影子流水 kp 未同步会导致锁组落空（c5 回归点）")
        # 再解绑，留给知识点删除用例验证自动解绑
        self._post(f"/api/kb/errors/{self.eid_bound}/unbind")

    # ---------- 8. 复习链路：独立错题可四档自评 + 标记复习 ----------
    def test_08_review_chain(self):
        r = self._post(f"/api/kb/error/{self.eid_alone}/rate",
                       json={"self_assessment": "familiar"})
        body = r.json()
        self.assertTrue(body["success"], r.text)
        r = self._post(f"/api/kb/errors/{self.eid_alone}/reviewed")
        self.assertTrue(r.json()["data"]["reviewed"], r.text)

    # ---------- 9. 删除知识点 → 关联错题自动解绑保留 ----------
    def test_09_delete_point_unbinds_errors(self):
        # 先绑一道再删点
        self._post(f"/api/kb/errors/{self.eid_bound}/move",
                   json={"knowledge_point_id": self.kp_id})
        r = self._del(f"/api/knowledge/points/{self.kp_id}")
        self.assertTrue(r.json()["success"], r.text)
        row = self._list_errors().get(self.eid_bound)
        self.assertIsNotNone(row, "知识点删除后错题必须保留")
        self.assertIsNone(row["knowledge_point_id"], "知识点删除后错题自动解绑")

    # ---------- 10. 删除错题（purge） ----------
    def test_10_delete_error(self):
        r = self._del(f"/api/kb/errors/{self.eid_bound}")
        self.assertTrue(r.json()["data"]["deleted"], r.text)
        self.assertNotIn(self.eid_bound, self._list_errors())

    # ---------- 11. 科目统计含独立错题 ----------
    def test_11_subject_stats(self):
        r = self._get("/api/subjects/stats")
        rows = {s["subject_name"]: s for s in r.json()["data"]}
        self.assertIn(SUBJECT, rows)
        self.assertGreaterEqual(rows[SUBJECT]["error_count"], 1)

    # ---------- 12. OCR 参数校验（不打外网，真实识别走 e2e） ----------
    def test_12_ocr_validation(self):
        r = self._post("/api/kb/error-ocr", json={"image": "../../etc/passwd"})
        self.assertEqual(r.status_code, 400, r.text)
        r = self._post("/api/kb/error-ocr", json={"image": "截图/不存在.png"})
        self.assertEqual(r.status_code, 400, r.text)
        r = self._get("/api/kb/error-ocr/nonexistent_task")
        self.assertEqual(r.status_code, 404, r.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
