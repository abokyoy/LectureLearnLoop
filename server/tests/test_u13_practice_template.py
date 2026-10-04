# -*- coding: utf-8 -*-
"""
u13 知识点结构化练习模板 契约测试（2026-10-02 多题型答题改造）。

覆盖：
1. practice-submit 客观题判分（单选/判断/填空，含答案变体与宽松归一）+ 难度加权掌握度手算
2. 提交全量落库：practice_records 流水聚合可见、答错自动入 error_questions（错题数可见）
3. 评估通道补留痕（9-29 A 方案）：/assessment 提交后流水与错题池同步增长
4. generate-practice 空态：no_notes / no_errors / 非法 source
5. （真实 LLM，容错跳过）笔记出题 8 题结构校验 + 全对提交（含简答题 LLM 判分）全链路
6. 错题选项落库（翻卡复习数据源）：单选答错入库带 question_type/options，判断题无选项（存量降级口径对应面）

运行前置：服务端已在 127.0.0.1:6001 运行。数据全部落在独立测试用户内，结束清理。
"""
from __future__ import annotations

import sys
import time
import unittest
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import db_adapter
import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:6001"
SUBJECT = f"U13练习学科{int(time.time()) % 100000}_{uuid.uuid4().hex[:4]}"
NOTE_FILE = Path(__file__).resolve().parents[1] / "logs" / f"u13_note_{uuid.uuid4().hex[:6]}.md"
WEIGHTS = {"容易": 1.0, "中等": 1.2, "困难": 1.5}


def register_and_token(username: str) -> str:
    requests.post(BASE + "/api/auth/register",
                  json={"username": username, "password": "test123456"}, timeout=15)
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["token"]


def _uid(tk):
    import base64, json as _json
    seg = tk.split(".")[1]
    seg += "=" * (-len(seg) % 4)
    pl = _json.loads(base64.urlsafe_b64decode(seg))
    return pl.get("uid") or pl.get("user_id")


def _exec(sql, params=None, fetch=False):
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = c.cursor()
        cur.execute(sql, params or ())
        rows = cur.fetchall() if fetch else None
        c.commit()
        return rows
    finally:
        c.close()


class TestU13PracticeTemplate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = register_and_token("u13_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}
        cls.uid = _uid(cls.token)

    @classmethod
    def tearDownClass(cls):
        # 清理测试用户全部相关数据（禁止污染正式数据；独立用户隔离）
        try:
            pids = [r[0] for r in _exec(
                "SELECT id FROM knowledge_points WHERE user_id = ?", (cls.uid,), fetch=True)]
            for pid in pids:
                for t in ("practice_records", "error_questions", "favorite_questions"):
                    _exec(f"DELETE FROM {t} WHERE user_id = ? AND knowledge_point_id = ?",
                          (cls.uid, pid))
                _exec("DELETE FROM knowledge_point_sources WHERE knowledge_point_id = ?", (pid,))
            _exec("DELETE FROM notes WHERE user_id = ?", (cls.uid,))
            _exec("DELETE FROM knowledge_points WHERE user_id = ?", (cls.uid,))
            _exec("DELETE FROM user_subjects WHERE user_id = ? AND subject_name = ?",
                  (cls.uid, SUBJECT))
        finally:
            NOTE_FILE.unlink(missing_ok=True)

    def _get(self, path, **kw):
        return requests.get(BASE + path, headers=self.h, timeout=kw.pop("timeout", 60), **kw)

    def _post(self, path, **kw):
        return requests.post(BASE + path, headers=self.h, timeout=kw.pop("timeout", 180), **kw)

    # ---------- 1. 建知识点 ----------
    def test_01_create_point(self):
        point = {"name": "U13特征值基础", "description": "Av=λv 定义的方阵特征问题"}
        r = self._post("/api/knowledge/point-new", json={"point": point, "subject": SUBJECT})
        self.assertTrue(r.json()["success"], r.text)
        type(self).kp_id = int(r.json()["data"]["knowledge_id"])

    # ---------- 2. 客观题判分 + FSRS 整批折叠掌握度 + 全量落库 ----------
    def test_02_objective_judging(self):
        questions = [
            {"type": "single", "question": "U13OBJ-Q1 易单选", "options": ["a", "b", "c", "d"],
             "correct_answer": "A", "difficulty": "容易", "explanation": "e1"},
            {"type": "single", "question": "U13OBJ-Q2 中单选", "options": ["a", "b", "c", "d"],
             "correct_answer": "B", "difficulty": "中等", "explanation": "e2"},
            {"type": "judge", "question": "U13OBJ-Q3 易判断", "correct_answer": "正确",
             "difficulty": "容易", "explanation": "e3"},
            {"type": "judge", "question": "U13OBJ-Q4 中判断", "correct_answer": "错误",
             "difficulty": "中等", "explanation": "e4"},
            {"type": "fill", "question": "U13OBJ-Q5 中填空 ______", "correct_answer": "甲方|乙方",
             "difficulty": "中等", "explanation": "e5"},
            {"type": "fill", "question": "U13OBJ-Q6 难填空 ______", "correct_answer": "Hello World",
             "difficulty": "困难", "explanation": "e6"},
        ]
        # Q1√ Q2× Q3√(同义变体"对") Q4×(答"正确") Q5√(带空格+变体2) Q6√(大小写差异)
        answers = ["A", "C", "对", "正确", " 乙方 ", "helloworld"]
        # FSRS 集成线回归（2026-10-01）：整批折叠一次复习，新行首次复习派生值为空
        # → 写入实测正确率封顶 round(100*4/6)=67（0929 A 方案）
        cap = int(round(100 * 4 / 6))

        r = self._post(f"/api/knowledge/points/{self.kp_id}/practice-submit",
                       json={"questions": questions, "answers": answers})
        body = r.json()
        self.assertTrue(body.get("success"), r.text)
        data = body["data"]
        self.assertEqual(data["correct_count"], 4, "同义判断/变体填空/大小写归一须判对")
        self.assertEqual(data["total_count"], 6)
        self.assertEqual(data["mastery_score"], cap, "新行整批折叠后掌握度=正确率封顶")
        det = {d["question_index"]: d for d in data["detailed_results"]}
        self.assertFalse(det[1]["is_correct"] and det[3]["is_correct"])
        self.assertTrue(det[4]["is_correct"] and det[5]["is_correct"])
        # 逐题 rating 回显：答对=Good(3)，答错=Again(1)
        self.assertEqual([det[i]["rating"] for i in range(6)], [3, 1, 3, 1, 3, 3])

        # 落库留痕：6 题全部进聚合，2 道答错进错题池
        r2 = self._get(f"/api/knowledge/points/{self.kp_id}/questions")
        agg = r2.json()["data"]["questions"]
        self.assertEqual(len(agg), 6, "全部作答应进关联题目聚合")
        self.assertEqual(sum(q["practice_count"] for q in agg), 6)
        det_r = self._get(f"/api/knowledge/points/{self.kp_id}/detail").json()["data"]["detail"]
        self.assertEqual(det_r["error_count"], 2, "答错 2 题应自动入错题池")
        self.assertEqual(det_r["mastery_score"], cap, "掌握度已落库（FSRS 封顶值）")
        self.assertEqual(len(det_r["recent_practices"]), 5, "最近练习面板取最近 5 条（detail LIMIT 5 口径）")
        self.assertTrue(all(r["question"].startswith("U13OBJ-") for r in det_r["recent_practices"]),
                        "面板应全是本轮作答流水")

        # u14 错题翻卡契约：答错的选择题入库必须带题型与选项（复习时才有选项可看）
        errs = self._get("/api/kb/errors", params={"subject": SUBJECT}).json()["data"]
        q2 = next((x for x in errs if str(x.get("question_content", "")).startswith("U13OBJ-Q2")), None)
        self.assertIsNotNone(q2, "U13OBJ-Q2 答错应在错题池")
        self.assertEqual(q2["question_type"], "single", "错题应回问题型")
        self.assertEqual(q2["options"], ["a", "b", "c", "d"], "单选错题选项须原样落库回现")
        self.assertEqual(q2.get("correct_answer"), "B", "正确答案随错题回现（翻卡背面高亮依据）")
        self.assertEqual(q2.get("user_answer"), "C")
        q4 = next((x for x in errs if str(x.get("question_content", "")).startswith("U13OBJ-Q4")), None)
        self.assertIsNotNone(q4)
        self.assertEqual(q4["question_type"], "judge")
        self.assertIsNone(q4["options"], "判断题无选项，落库为 NULL（前端按缺失降级）")

    # ---------- 3. 评估通道补留痕（A 方案） ----------
    def test_03_assessment_persist(self):
        before_agg = len(self._get(f"/api/knowledge/points/{self.kp_id}/questions").json()["data"]["questions"])
        questions = [
            {"question": "U13EVAL-Q1", "options": ["a", "b", "c", "d"], "correct_answer": "A",
             "difficulty": "容易", "explanation": "x"},
            {"question": "U13EVAL-Q2", "options": ["a", "b", "c", "d"], "correct_answer": "B",
             "difficulty": "中等", "explanation": "y"},
        ]
        r = self._post(f"/api/knowledge/points/{self.kp_id}/assessment",
                       json={"questions": questions, "answers": ["A", "Z"]})
        self.assertTrue(r.json()["data"]["success"], r.text)
        agg = self._get(f"/api/knowledge/points/{self.kp_id}/questions").json()["data"]["questions"]
        self.assertEqual(len(agg), before_agg + 2, "评估作答同样全量留痕")
        det = self._get(f"/api/knowledge/points/{self.kp_id}/detail").json()["data"]["detail"]
        self.assertEqual(det["error_count"], 3, "评估答错应入错题池（2+1）")

    # ---------- 4. 空态与非法参数 ----------
    def test_04_empty_states(self):
        point = {"name": "U13孤立知识点", "description": "无笔记无错题"}
        r = self._post("/api/knowledge/point-new", json={"point": point, "subject": SUBJECT})
        orphan = int(r.json()["data"]["knowledge_id"])
        d = self._post(f"/api/knowledge/points/{orphan}/generate-practice",
                       json={"source": "notes"}).json()["data"]
        self.assertFalse(d["success"])
        self.assertTrue(d.get("no_notes"), "无笔记应返回 no_notes 空态而非报错")
        d = self._post(f"/api/knowledge/points/{orphan}/generate-practice",
                       json={"source": "analogy"}).json()["data"]
        self.assertTrue(d.get("no_errors"), "无错题应返回 no_errors 空态")
        d = self._post(f"/api/knowledge/points/{orphan}/generate-practice",
                       json={"source": "bogus"}).json()["data"]
        self.assertFalse(d["success"])
        self.assertIn("source", d.get("error", ""))
        # 数量不匹配防御
        d = self._post(f"/api/knowledge/points/{orphan}/practice-submit",
                       json={"questions": [{"type": "single", "question": "q", "correct_answer": "A"}],
                             "answers": []}).json()["data"]
        self.assertFalse(d["success"])

    # ---------- 5. 真实 LLM：笔记出题结构校验（容错跳过） ----------
    def test_05_generate_notes_llm(self):
        NOTE_FILE.write_text(
            "# 特征值入门\n\n若方阵A与非零向量v满足 Av=λv，则称λ为A的特征值，v为对应特征向量。"
            "求特征值的经典方法是解特征方程 det(λI-A)=0。矩阵的迹等于全部特征值之和，"
            "行列式等于全部特征值之积。对称矩阵的特征值必为实数。", encoding="utf-8")
        nuid = uuid.uuid4().hex
        row = _exec("INSERT INTO notes (user_id, note_uuid, file_name, file_path, title) "
                    "VALUES (?, ?, ?, ?, ?) RETURNING id",
                    (self.uid, nuid, NOTE_FILE.name, str(NOTE_FILE), "U13特征值笔记"), fetch=True)
        # kps 表无 user_id 列；note_id NOT NULL，关联键用 note_uuid（与桥查询 JOIN 口径一致）
        _exec("INSERT INTO knowledge_point_sources (knowledge_point_id, note_id, note_uuid) VALUES (?, ?, ?)",
              (self.kp_id, row[0][0], nuid))
        r = self._post(f"/api/knowledge/points/{self.kp_id}/generate-practice", json={"source": "notes"})
        data = r.json()["data"]
        if not data.get("success"):
            self.skipTest("LLM 出题未成功（网络/额度/格式）：" + str(data.get("error")))
        qs = data["questions"]
        type(self).gen_qs = qs
        self.assertEqual(len(qs), 8, "应生成 8 题")
        seen = set()
        for q in qs:
            self.assertIn(q["type"], {"single", "judge", "fill", "short"})
            seen.add(q["type"])
            if q["type"] == "single":
                self.assertEqual(len(q["options"]), 4)
                self.assertIn(q["correct_answer"], ["A", "B", "C", "D"])
            if q["type"] == "judge":
                self.assertIn(q["correct_answer"], ["正确", "错误"])
            if q["type"] == "fill":
                self.assertIn("____", q["question"])
        self.assertEqual(seen, {"single", "judge", "fill", "short"}, "四种题型齐全")

    # ---------- 6. 真实 LLM：全链路提交（含简答判分，容错跳过） ----------
    def test_06_full_submit_with_short(self):
        if not hasattr(type(self), "gen_qs"):
            self.skipTest("上轮 LLM 出题未成功")

        def _answer_for(q):
            ca = str(q["correct_answer"])
            # 填空多解用 "|" 分隔：整串作必被判错，取首个合法答案
            if q.get("type") == "fill":
                ca = ca.replace("｜", "|").split("|")[0].strip()
            return ca

        answers = [_answer_for(q) for q in self.gen_qs]
        r = self._post(f"/api/knowledge/points/{self.kp_id}/practice-submit",
                       json={"questions": self.gen_qs, "answers": answers})
        data = r.json()["data"]
        if not data.get("success"):
            self.skipTest("LLM 简答判分未成功（网络/额度）：" + str(data.get("error")))
        self.assertEqual(data["total_count"], 8)
        self.assertGreaterEqual(data["correct_count"], 7, "按参考答案作答应基本全对（简答判分容忍 1 题波动）")
        shorts = [d for d in data["detailed_results"] if d["type"] == "short"]
        self.assertEqual(len(shorts), 1)
        self.assertTrue(shorts[0]["comment"], "简答题应返回 AI 判分点评")

    # ---------- 7. 举一反三：错题已存在（前面答错 3 题）应可出题（容错跳过） ----------
    def test_07_analogy_not_empty(self):
        r = self._post(f"/api/knowledge/points/{self.kp_id}/generate-practice", json={"source": "analogy"})
        data = r.json()["data"]
        self.assertFalse(data.get("no_errors"), "已有答错记录，举一反三不应再报空态")
        if not data.get("success"):
            self.skipTest("LLM 出题未成功：" + str(data.get("error")))
        self.assertEqual(len(data["questions"]), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
