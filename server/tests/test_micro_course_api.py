# -*- coding: utf-8 -*-
"""微课蓝图集成断言（U6，2026-10-30）。in-process test_client + 真 PG（独立测试用户，测后清理）。

零真实 LLM 消耗：monkeypatch routes_micro_course.call_llm_for_user 为 fake，
同步驱动 _run_generation/_regen_scene_wrap，覆盖：
1. 端点参数校验与内层契约（estimate/list/detail/create）
2. 越权隔离（评审 M-3：user_id 双条件，B 看不见 A 的课）
3. 在飞去重（同锚定 kp 已有 generating → reused）
4. 两阶段逐页增量落库：全 done→ready、quiz 页绑 kp（对象契约）、单页失败→partial
5. 积分不足截断：该页 failed + 余页置 failed，不重发请求
6. 单页重生成乐观锁（页 generating 中二次派发被拒）
7. 启动恢复钩子（generating 孤儿 → failed 页 + partial 课）
8. 删除闸（generating 禁止 / ready 可删两表行）
9. SPA 片段白名单（/fragments/micro_course 可达）
10. 二期：interactive 页 done+外链警告；大纲 interactive 超页降级留痕
11. 五期：explain/example 分步画布页（canvas+steps 落库/缺画布置败不重发/外链只警告/
    旧大纲 has_widget 残留静默丢弃且调用数回归 1+N，widget 追加链路已退役）
12. 六期：错题深度讲解（error_id 入口校验/素材块/全链生成/去重双轨互不劫持/
    在飞唯一索引双轨共存/estimate?mode=error/history?error_id/单页重生成带回错题素材）
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import credits_service as cr  # noqa: E402
import routes_micro_course as RMC  # noqa: E402
from app import create_app  # noqa: E402
from config import DB_PATH  # noqa: E402
from knowledge_management import DatabaseManager  # noqa: E402

APP = create_app()

OUTLINE = {"title": "极限微课", "sections": [
    {"title": "讲概念", "scene_type": "explain", "intent": "i1"},
    {"title": "随堂检测", "scene_type": "quiz", "intent": "i2"},
    {"title": "小结", "scene_type": "summary", "intent": "i3"},
]}  # 七期：无互动页→校验器末尾自动补 1 页 standby 占位（worthy 保守 false）
# 七期：自带互动页 + worthy=true 的大样本（验证透传与跳过生成）
OUTLINE_W = {"title": "极限微课探究版", "interactive_worthy": True,
             "interactive_note": "函数图像参数可拖拽观察", "sections": [
    {"title": "讲概念", "scene_type": "explain", "intent": "i1"},
    {"title": "动手探究", "scene_type": "interactive", "intent": "i2"},
    {"title": "随堂检测", "scene_type": "quiz", "intent": "i3"},
    {"title": "小结", "scene_type": "summary", "intent": "i4"},
]}
OUTLINE_INTER = {"title": "极限微课实验版", "sections": [
    {"title": "讲概念", "scene_type": "explain", "intent": "i1"},
    {"title": "动手探究", "scene_type": "interactive", "intent": "i2"},
    {"title": "再探一次", "scene_type": "interactive", "intent": "i3"},  # 超页应降级 explain
    {"title": "随堂检测", "scene_type": "quiz", "intent": "i4"},
    {"title": "小结", "scene_type": "summary", "intent": "i5"},
]}
Q_SINGLE = {"type": "single", "question": "lim x→0 sinx/x = ?",
            "options": ["0", "1", "2", "不存在"], "correct_answer": "B",
            "difficulty": "容易", "explanation": "重要极限"}
Q_JUDGE = {"type": "judge", "question": "收敛数列必收敛于唯一极限",
           "correct_answer": "正确", "difficulty": "中等", "explanation": "唯一性定理"}
# 二期：实验页样本 html（含 CDN 外链→应触发警告；含 xmlns/注释→不得误杀）
INTER_HTML = ('<!DOCTYPE html><html><body>'
              '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
              '<script>// 本地注释 let a=1;</script>'
              '<img src="https://cdn.example.com/a.png">'
              '</body></html>')
# 五期：分步画布舞台样本（纯内联无外链 / 含外链只警告同 interactive 纪律）
CANVAS_HTML = ('<!DOCTYPE html><html><body><svg xmlns="http://www.w3.org/2000/svg"></svg>'
               '<script>window.addEventListener("message", function(e){});</script></body></html>')
CANVAS_HTML_EXT = ('<!DOCTYPE html><html><body>'
                   '<script src="https://cdn.example.com/stage.js"></script></body></html>')
# 五期：旧大纲残留 has_widget（四期产物），regenerate 重读时应静默丢弃不再追加调用
OUTLINE_LEGACY = {"title": "极限微课旧大纲", "sections": [
    {"title": "讲概念", "scene_type": "explain", "intent": "i1", "has_widget": True},
    {"title": "随堂检测", "scene_type": "quiz", "intent": "i2"},
    {"title": "小结", "scene_type": "summary", "intent": "i3"},
]}
# 六期：错题深度讲解大纲（硬性结构样本：拆题 explain + 错因 explain + quiz）
OUTLINE_ERR = {"title": "错题讲解：重要极限", "sections": [
    {"title": "这道题考什么", "scene_type": "explain", "intent": "拆题目条件与知识点"},
    {"title": "你错在哪", "scene_type": "explain", "intent": "对照作答诊断错因"},
    {"title": "变式自测", "scene_type": "quiz", "intent": "两道变式题对准错因"},
]}


def _canvas_obj(title, canvas=CANVAS_HTML, n=5):
    return {"title": title, "canvas_html": canvas,
            "steps": [{"caption": f"字幕{i}", "narration": f"第{i}步口播"} for i in range(n)]}


def make_fake_llm(fail_types=(), insufficient_types=(), delay=0.0, outline=None,
                  canvas_mode="ok"):
    """fake call_llm_for_user：按 prompt 标记分流大纲/页型；可注入失败与积分不足。
    五期：widget 独立分流已退役；canvas_mode 控制画布页返回形态。"""
    calls = {"n": 0}
    outline_json = json.dumps(outline or OUTLINE, ensure_ascii=False)

    def fake(uid, prompt, context="", scene="", timeout=None):  # 路由按页型传 180/300，签名兼容
        calls["n"] += 1
        if delay:
            time.sleep(delay)
        if "教学大纲" in prompt:
            return outline_json
        m = re.search(r"页型=(\w+)", prompt)
        st = m.group(1) if m else "explain"
        if st in insufficient_types:
            raise cr.InsufficientCreditsError(0.0)
        if st in fail_types:
            return "抱歉，本次生成失败"
        if st in ("explain", "example"):
            # 五期：分步画布契约 {title, canvas_html, steps[]}
            if canvas_mode == "garbage":
                return json.dumps({"title": "讲概念", "narration": "没有画布的旧形态"},
                                  ensure_ascii=False)
            html = CANVAS_HTML_EXT if canvas_mode == "external" else CANVAS_HTML
            return json.dumps(_canvas_obj("讲概念" if st == "explain" else "例题", canvas=html),
                              ensure_ascii=False)
        if st == "quiz":
            return json.dumps({"narration": "下面两道小题检验本页面内容",
                               "questions": [Q_SINGLE, Q_JUDGE]}, ensure_ascii=False)
        if st == "summary":
            return json.dumps({"title": "小结", "body_md": "课后复习第2节",
                               "narration": "我们来回顾一下"}, ensure_ascii=False)
        return json.dumps({"title": "动手探究", "html": INTER_HTML,
                           "narration": "拖动滑杆观察曲线变化"}, ensure_ascii=False)
    fake.calls = calls
    return fake


class TestMicroCourseIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 预热 kms 懒初始化（schema DDL 含 ALTER TABLE，需 AccessExclusive）：
        # 必须在 cls.conn 开任何事务之前完成，否则本类 idle-in-transaction 的
        # ACCESS SHARE 会与运行时 DDL 互等造成进程内自锁死挂起（2026-10-30 实测）。
        from routes_knowledge import get_kms
        get_kms()
        cls.conn = DatabaseManager(str(DB_PATH)).get_connection()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.client = APP.test_client()
        cls.uidA, cls.tokA = cls._register("mcA_" + cls.suffix)
        cls.uidB, cls.tokB = cls._register("mcB_" + cls.suffix)
        cls.hA = {"Authorization": f"Bearer {cls.tokA}"}
        cls.hB = {"Authorization": f"Bearer {cls.tokB}"}
        cur = cls.conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) "
            "VALUES (?, ?, ?, ?, ?)", (cls.uidA, "测试学科MC" + cls.suffix, "极限", "数列与函数极限", 45))
        cls.conn.commit()
        row = cls.conn.execute("SELECT id FROM knowledge_points WHERE user_id = ?", (cls.uidA,)).fetchone()
        cls.kp = row[0]
        cls.conn.commit()
        cls._orig_llm = RMC.call_llm_for_user
        # 六期：create 全链用例要过积分预检闸——给测试用户发余额（懒建号后 UPDATE）
        cr.get_balance(cls.uidA)
        cr.get_balance(cls.uidB)
        cls.conn.execute("UPDATE user_credits SET balance = 2000 WHERE user_id IN (?, ?)",
                         (cls.uidA, cls.uidB))
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        RMC.call_llm_for_user = cls._orig_llm
        for uid in (cls.uidA, cls.uidB):
            cls.conn.execute(
                "DELETE FROM micro_scenes WHERE course_id IN (SELECT id FROM micro_courses WHERE user_id = ?)",
                (uid,))
            cls.conn.execute("DELETE FROM micro_courses WHERE user_id = ?", (uid,))
            cls.conn.execute("DELETE FROM knowledge_points WHERE user_id = ?", (uid,))
            # 六期：错题影子行与测内充值余额一并清理
            cls.conn.execute("DELETE FROM error_questions WHERE user_id = ?", (uid,))
            cls.conn.execute("DELETE FROM practice_records WHERE user_id = ?", (uid,))
            cls.conn.execute("DELETE FROM user_credits WHERE user_id = ?", (uid,))
        cls.conn.commit()
        cls.conn.close()

    @classmethod
    def _register(cls, username):
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        return uid, tok

    def tearDown(self):
        # 函数快照存类属性后用 type(self) 取：self._orig_llm 会触发描述符绑定，
        # 恢复出去的是吞掉首参的污染函数（test_board_explainer 同型事故 2026-11-10）
        RMC.call_llm_for_user = type(self)._orig_llm

    # ---- 工具 ----
    def _get(self, url, h=None):
        return self.client.get(url, headers=h or self.hA).get_json()

    def _post(self, url, body, h=None):
        return self.client.post(url, json=body, headers=h or self.hA).get_json()

    def _data(self, body):
        """双层契约剥壳：外层 {success,data}，内层业务 {success,...}。"""
        self.assertTrue(body.get("success"), f"外层失败: {body}")
        return body.get("data") or {}

    def _course(self, uid=None, status="generating", anchor=None, outline="{}"):
        key = uuid.uuid4().hex[:16]
        self.conn.execute(
            "INSERT INTO micro_courses (course_key, user_id, subject_name, title, source_type, "
            "source_ref, outline_json, status) VALUES (?, ?, ?, '', 'kp', ?, ?, ?)",
            (key, uid or self.uidA, "测试学科",
             json.dumps({"anchor_kp_id": anchor} if anchor else {}), outline, status))
        self.conn.commit()
        return key

    def _course_row(self, key):
        r = self.conn.execute(
            "SELECT id, status, title, outline_json FROM micro_courses WHERE course_key = ?",
            (key,)).fetchone()
        self.conn.commit()
        return r

    def _scenes(self, cid):
        r = self.conn.execute(
            "SELECT seq, status, error_note, content_json, kp_id FROM micro_scenes "
            "WHERE course_id = ? ORDER BY seq", (cid,)).fetchall()
        self.conn.commit()
        return r

    def _kp_row(self):
        r = self.conn.execute(
            "SELECT id, point_name, core_description, subject_name, mastery_score "
            "FROM knowledge_points WHERE id = ?", (self.kp,)).fetchone()
        self.conn.commit()
        return r

    def _mk_error(self, uid=None, kp="__use__"):
        """六期：自建错题影子行（流水+错题表 JOIN 素材源）；kp=None 模拟手动独立错题。"""
        kpid = self.kp if kp == "__use__" else kp
        q = "错题测试" + uuid.uuid4().hex[:8] + "：lim x→0 sinx/x = ?"
        pr = self.conn.execute(
            "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
            "question_content, user_answer, is_correct, options_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (uid or self.uidA, "测试学科MC" + self.suffix, kpid, q,
             "我选了D不存在", 0, json.dumps(["0", "1", "2", "不存在"], ensure_ascii=False))
        ).fetchone()[0]
        eid = self.conn.execute(
            "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
            "practice_record_id, correct_answer, explanation, current_proficiency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (uid or self.uidA, "测试学科MC" + self.suffix, kpid, pr,
             "B", "重要极限，答案趋近1", 30)
        ).fetchone()[0]
        self.conn.commit()
        return eid

    def _course_error(self, uid=None, status="generating", anchor=None, eids=()):
        """六期：手工插错题讲解课行（在飞去重/索引/历史断言用，不派发线程）。"""
        key = uuid.uuid4().hex[:16]
        self.conn.execute(
            "INSERT INTO micro_courses (course_key, user_id, subject_name, title, source_type, "
            "source_ref, outline_json, status) VALUES (?, ?, ?, '', 'error', ?, '{}', ?)",
            (key, uid or self.uidA, "测试学科MC" + self.suffix,
             json.dumps({"anchor_kp_id": anchor, "error_ids": list(eids),
                         "error_explain": True}), status))
        self.conn.commit()
        return key

    def _wait_course(self, key, timeout=30):
        """轮询等后台线程收敛（create 派发 daemon 线程，fake LLM 秒级）。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            row = self._course_row(key)
            if row and row[1] not in ("generating", "regenerating"):
                return row
            time.sleep(0.3)
        self.fail(f"课程 {key} 超时未收敛: {self._course_row(key)}")

    # ---- 1. 端点契约 ----
    def test_01_estimate_and_list(self):
        d = self._data(self._get("/api/micro-course/estimate"))
        self.assertTrue(d.get("success"))
        self.assertIsInstance(d.get("estimated_credits"), (int, float))
        self.assertGreater(d["estimated_credits"], 0)

    def test_02_create_param_validation(self):
        d = self._data(self._post("/api/micro-course/create", {}))
        self.assertFalse(d.get("success"))
        self.assertIn("发起", d.get("error", ""))
        d = self._data(self._post("/api/micro-course/create", {"error_ids": ["a"]}))
        self.assertFalse(d.get("success"))
        self.assertIn("参数格式", d.get("error", ""))
        d = self._data(self._post("/api/micro-course/create", {"error_ids": [True]}))
        self.assertFalse(d.get("success"))  # bool 不得冒充整数 id（评审 Nit）
        d = self._data(self._post("/api/micro-course/create", {"kp_id": "abc"}))
        self.assertFalse(d.get("success"))  # 非数字 kp_id 不得穿透 500（评审 R1-3）
        self.assertIn("参数格式", d.get("error", ""))
        d = self._data(self._post("/api/micro-course/create", {"kp_id": 999999999}))
        self.assertFalse(d.get("success"))  # 不存在的 kp 锚定失败

    def test_03_cross_user_isolation(self):
        # status=ready：避免残留 generating 行污染 test_05 的在飞去重断言
        key = self._course(anchor=self.kp, status="ready")
        d = self._data(self._get("/api/micro-course/" + key, h=self.hB))
        self.assertFalse(d.get("success"))
        self.assertIn("未找到", d.get("error", ""))
        d = self._data(self._get("/api/micro-course/" + key))
        self.assertTrue(d.get("success"))
        self.assertEqual(d["course"]["course_key"], key)

    def test_04_fragment_registered(self):
        r = self.client.get("/fragments/micro_course", headers=self.hA)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn('data-pm-page="micro_course"', body.get("data") or "")

    # ---- 2. 在飞去重 ----
    def test_05_dedup_reuse_generating(self):
        # 清掉历史用例残留的 generating 课，确保去重命中的是本用例新插的行
        self.conn.execute("DELETE FROM micro_scenes WHERE course_id IN "
                          "(SELECT id FROM micro_courses WHERE user_id = ?)", (self.uidA,))
        self.conn.execute("DELETE FROM micro_courses WHERE user_id = ?", (self.uidA,))
        self.conn.commit()
        key = self._course(status="generating", anchor=self.kp)
        d = self._data(self._post("/api/micro-course/create", {"kp_id": self.kp}))
        self.assertTrue(d.get("success"))
        self.assertTrue(d.get("reused"))
        self.assertEqual(d.get("course_key"), key)

    # ---- 3. 两阶段生成：全 done → ready ----
    def test_06_generation_all_done(self):
        # anchor 置 None：避开 uq_mcourse_inflight 与其它用例的 generating 行碰撞
        # （索引对 anchor_kp_id 为 NULL 的行不生效）
        key = self._course()
        RMC.call_llm_for_user = make_fake_llm()
        RMC._run_generation(self.uidA, key, tuple(self._kp_row()), "", "", "")
        row = self._course_row(key)
        self.assertEqual(row[1], "ready")
        self.assertEqual(row[2], "极限微课")
        scenes = self._scenes(row[0])
        self.assertEqual(len(scenes), 4)  # 七期：fake 大纲无互动页→自动补位 1 页 standby
        self.assertTrue(all(s[1] == "done" for s in scenes[:3]))
        self.assertEqual(scenes[3][1], "standby")  # 互动页占位不烧 LLM 不计 done
        self.assertEqual(scenes[3][3], "")          # 占位页无正文
        quiz = [s for s in scenes if s[4] == self.kp and s[0] == 2]
        self.assertEqual(len(quiz), 1)
        obj = json.loads(quiz[0][3])  # 二期断档：quiz 为 {narration, questions} 对象
        self.assertEqual(len(obj["questions"]), 2)
        self.assertEqual(obj["questions"][0]["correct_answer"], "B")  # 题目契约与出题同构
        self.assertTrue(obj["narration"])  # 语音旁白随页落库
        exp_obj = json.loads(scenes[0][3])
        # 五期：explain 页落库为分步画布形态（声画同源，无页级 narration）
        self.assertIn("canvas_html", exp_obj)
        self.assertEqual(len(exp_obj["steps"]), 5)
        self.assertTrue(exp_obj["steps"][0]["narration"])

    # ---- 4. 单页失败 → partial ----
    def test_07_generation_partial_on_scene_fail(self):
        key = self._course()
        RMC.call_llm_for_user = make_fake_llm(fail_types={"quiz"})
        RMC._run_generation(self.uidA, key, tuple(self._kp_row()), "", "", "")
        row = self._course_row(key)
        self.assertEqual(row[1], "partial")
        scenes = self._scenes(row[0])
        self.assertEqual(scenes[1][1], "failed")
        self.assertTrue(scenes[1][2])  # error_note 有内容
        self.assertEqual(scenes[0][1], "done")

    # ---- 5. 大纲失败 → 整课 failed，不重发 ----
    def test_08_outline_fail(self):
        key = self._course()
        calls = {"n": 0}

        def fake(uid, prompt, context="", scene="", timeout=None):
            calls["n"] += 1
            return "完全不是JSON"

        RMC.call_llm_for_user = fake
        RMC._run_generation(self.uidA, key, tuple(self._kp_row()), "", "", "")
        self.assertEqual(calls["n"], 1)  # 失败绝不重发（防双扣分）
        row = self._course_row(key)
        self.assertEqual(row[1], "failed")
        # 整课失败必须留原因（评审 R1-7，前端 failed+0 页分支展示它）
        note = self.conn.execute("SELECT error_note FROM micro_courses WHERE course_key = ?",
                                 (key,)).fetchone()[0]
        self.conn.commit()
        self.assertTrue(note)

    # ---- 6. 积分不足截断 ----
    def test_09_insufficient_credits_cutoff(self):
        key = self._course()
        RMC.call_llm_for_user = make_fake_llm(insufficient_types={"quiz"})
        RMC._run_generation(self.uidA, key, tuple(self._kp_row()), "", "", "")
        row = self._course_row(key)
        scenes = self._scenes(row[0])
        self.assertEqual(scenes[1][1], "failed")
        self.assertIn("积分不足", scenes[1][2])
        self.assertEqual(scenes[2][1], "failed")  # 余页不再发起请求
        self.assertIn("前置积分不足", scenes[2][2])
        self.assertEqual(scenes[3][1], "standby")  # 七期：积分不足截断不得波及占位互动页
        self.assertEqual(row[1], "partial")

    # ---- 7. 单页重生成 + 乐观锁 ----
    def test_10_regenerate_scene(self):
        key = self._course()
        RMC.call_llm_for_user = make_fake_llm(fail_types={"quiz"})
        RMC._run_generation(self.uidA, key, tuple(self._kp_row()), "", "", "")
        cid = self._course_row(key)[0]
        # fake 慢 1s：派发后立刻二次请求 → 页 generating 中被乐观锁拒绝
        RMC.call_llm_for_user = make_fake_llm(delay=1.0)
        d = self._data(self._post(f"/api/micro-course/{key}/regenerate-scene", {"seq": 2}))
        self.assertTrue(d.get("success"))
        d2 = self._data(self._post(f"/api/micro-course/{key}/regenerate-scene", {"seq": 2}))
        self.assertFalse(d2.get("success"))
        self.assertIn("正在生成中", d2.get("error", ""))
        # 等后台线程收尾（页 done 且课程状态归位，fake 1s 级）
        t0 = time.time()
        while time.time() - t0 < 15:
            sc = self.conn.execute(
                "SELECT status FROM micro_scenes WHERE course_id = ? AND seq = 2", (cid,)).fetchone()
            cs = self._course_row(key)[1]
            if sc and sc[0] == "done" and cs != "regenerating":
                break
            time.sleep(0.3)
        self.assertEqual(self.conn.execute(
            "SELECT status FROM micro_scenes WHERE course_id = ? AND seq = 2", (cid,)).fetchone()[0], "done")
        self.assertEqual(self._course_row(key)[1], "ready")  # 全页 done 归位

    def test_11_regenerate_unknown_seq(self):
        key = self._course(anchor=self.kp, status="ready")
        d = self._data(self._post(f"/api/micro-course/{key}/regenerate-scene", {"seq": 99}))
        self.assertFalse(d.get("success"))
        self.assertIn("未找到该页", d.get("error", ""))

    # ---- 8. 启动恢复钩子（评审 R1-1：pending 残页同样归 failed；R2-1：0 页在飞课也要收敛）----
    def test_12_startup_recovery(self):
        key = self._course(status="generating")
        # 0 页在飞课（大纲 LLM 未返回即重启）：钩子必须收敛为 failed，不留永久 generating
        key0 = self._course(status="generating")
        cid = self._course_row(key)[0]
        for seq, stt in ((1, "generating"), (2, "pending"), (3, "done")):
            self.conn.execute(
                "INSERT INTO micro_scenes (course_id, seq, scene_type, kp_id, title, status, content_json) "
                "VALUES (?, ?, 'explain', ?, ?, ?, '')",
                (cid, seq, self.kp, f"页{seq}", stt))
        self.conn.commit()
        RMC.init_micro_course_recovery(lambda: DatabaseManager(str(DB_PATH)).get_connection())
        scenes = self._scenes(cid)
        self.assertEqual([s[1] for s in scenes], ["failed", "failed", "done"])
        self.assertIn("重启", scenes[0][2])
        self.assertIn("重启", scenes[1][2])
        # 收敛口径与 _recalc 一致：有 done 有 failed → partial（评审 R1-8）
        self.assertEqual(self._course_row(key)[1], "partial")
        # R2-1：0 页在飞课重启后收敛 failed（原早退不落库会永久卡 generating）
        row0 = self._course_row(key0)
        self.assertEqual(row0[1], "failed")

    # ---- 9. 删除闸 ----
    def test_13_delete_guard_and_success(self):
        key = self._course(status="generating")
        d = self._data(self._post(f"/api/micro-course/{key}/delete", {}))
        self.assertFalse(d.get("success"))
        self.assertIn("生成中", d.get("error", ""))
        key2 = self._course(status="ready")
        cid2 = self._course_row(key2)[0]
        self.conn.execute("INSERT INTO micro_scenes (course_id, seq, scene_type, title) "
                          "VALUES (?, 1, 'explain', 't')", (cid2,))
        self.conn.commit()
        d = self._data(self._post(f"/api/micro-course/{key2}/delete", {}))
        self.assertTrue(d.get("success"))
        self.assertIsNone(self._course_row(key2))
        self.assertEqual(len(self._scenes(cid2)), 0)

    # ---- 10. list 汇总形态 ----
    def test_14_list_shape(self):
        key = self._course(anchor=self.kp, status="ready")
        d = self._data(self._get("/api/micro-course/list"))
        self.assertTrue(d.get("success"))
        hit = [x for x in d["items"] if x["course_key"] == key]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["status"], "ready")

    # ---- 11. 二期：interactive 页按需生成 + 外链警告不置败（七期重构：不再随课 done）----
    def test_15_interactive_done_with_external_warning(self):
        key = self._course()
        RMC.call_llm_for_user = make_fake_llm(outline=OUTLINE_INTER)
        RMC._run_generation(self.uidA, key, tuple(self._kp_row()), "", "", "")
        row = self._course_row(key)
        self.assertEqual(row[1], "ready")  # 七期：standby 不拉低课程状态
        # 大纲降级留痕：第 3 页 interactive → explain（存于落库的 outline_json）
        oj = json.loads(row[3])
        self.assertEqual([s["scene_type"] for s in oj["sections"]],
                         ["explain", "interactive", "explain", "quiz", "summary"])
        self.assertIs(oj["interactive_worthy"], False)  # 无 worthy 字段→保守 false
        scenes = self._scenes(row[0])
        self.assertEqual(len(scenes), 5)
        self.assertEqual(scenes[1][1], "standby")  # 互动页占位，正文未生成
        # 用户翻开→按需生成（复用 regenerate-scene）
        d = self._data(self._post(f"/api/micro-course/{key}/regenerate-scene", {"seq": 2}))
        self.assertTrue(d.get("success"), d)
        t0 = time.time()
        while time.time() - t0 < 15:
            sc = self.conn.execute("SELECT status FROM micro_scenes WHERE course_id = ? AND seq = 2",
                                   (row[0],)).fetchone()
            if sc and sc[0] == "done":
                break
            time.sleep(0.3)
        scenes = self._scenes(row[0])
        inter = json.loads(scenes[1][3])
        self.assertIn("cdn.example.com", inter["html"])  # html 不被黑名单剥除
        self.assertEqual(scenes[1][1], "done")
        self.assertIn("cdn.example.com", scenes[1][2])  # 警告写 error_note，不改终态
        self.assertIn("www.w3.org", inter["html"])  # xmlns 保留未被误杀
        self.assertTrue(inter["narration"])
        self.assertEqual(self._wait_course(key)[1], "ready")  # 按需生成完同样归位 ready

    # ---- 12. 三期入口管理：知识点微课历史 + 列表锚定知识点名 ----
    def test_16_history_by_kp(self):
        k1 = self._course(status="ready", anchor=self.kp)
        k2 = self._course(status="failed", anchor=self.kp)
        d = self._data(self._get("/api/micro-course/history?kp_id=%d" % self.kp))
        self.assertTrue(d.get("success"))
        self.assertEqual(d["anchor_kp"]["id"], self.kp)
        self.assertEqual(d["anchor_kp"]["name"], "极限")
        keys = {c["course_key"] for c in d["courses"]}
        self.assertTrue({k1, k2} <= keys)
        # 全部返回项必须锚定到本 kp（不得泄漏其他知识点的课）
        for c in d["courses"]:
            self.assertIn(c["status"], ("generating", "ready", "partial", "failed", "regenerating"))

    def test_17_history_param_validation_and_isolation(self):
        d = self._data(self._get("/api/micro-course/history"))
        self.assertFalse(d.get("success"))  # 无锚定参数
        d = self._data(self._get("/api/micro-course/history?kp_id=abc"))
        self.assertFalse(d.get("success"))  # 非数字 kp_id 不穿透 500
        d = self._data(self._get("/api/micro-course/history?kp_id=999999999"))
        self.assertFalse(d.get("success"))  # 不存在 kp 定位失败
        d = self._data(self._get("/api/micro-course/history?kp_id=%d" % self.kp, h=self.hB))
        self.assertFalse(d.get("success"))  # 跨用户：B 请求 A 的 kp 不得看到 A 的课

    def test_18_list_includes_kp_name(self):
        key = self._course(status="ready", anchor=self.kp)
        d = self._data(self._get("/api/micro-course/list"))
        hit = [c for c in d["items"] if c["course_key"] == key]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["kp_name"], "极限")
        self.assertEqual(hit[0]["anchor_kp_id"], self.kp)

    # ---- 13. 五期：分步画布页（落库形态/置败不重发/外链警告/widget 链路退役）----
    def test_19_canvas_page_persist_and_call_count(self):
        # 旧大纲残留 has_widget：静默丢弃不再追加图解调用，总数回归 1+N
        key = self._course()
        fake = make_fake_llm(outline=OUTLINE_LEGACY)
        RMC.call_llm_for_user = fake
        RMC._run_generation(self.uidA, key, tuple(self._kp_row()), "", "", "")
        row = self._course_row(key)
        self.assertEqual(row[1], "ready")
        oj = json.loads(row[3])
        self.assertNotIn("has_widget", oj["sections"][0])  # 落库大纲已归一
        scenes = self._scenes(row[0])
        exp_obj = json.loads(scenes[0][3])
        self.assertEqual(exp_obj["canvas_html"], CANVAS_HTML)
        self.assertEqual(len(exp_obj["steps"]), 5)
        self.assertTrue(all(s["caption"] and s["narration"] for s in exp_obj["steps"]))
        self.assertNotIn("widget", exp_obj)  # 画布页不再带 widget 字段
        self.assertIsNone(scenes[0][2])      # 纯内联无外链无警告
        self.assertEqual(fake.calls["n"], 4)  # 大纲 1 + 正文 3（widget 追加链路已退役）

    def test_20_canvas_missing_scene_failed_no_resend(self):
        # 非法即该页 failed（同 interactive 口径），绝不重发；余页照常、整课 partial
        key = self._course()
        fake = make_fake_llm(canvas_mode="garbage")
        RMC.call_llm_for_user = fake
        RMC._run_generation(self.uidA, key, tuple(self._kp_row()), "", "", "")
        row = self._course_row(key)
        self.assertEqual(row[1], "partial")
        scenes = self._scenes(row[0])
        self.assertEqual(scenes[0][1], "failed")
        self.assertIn("canvas_html", scenes[0][2])  # 错误留痕指向缺画布
        self.assertEqual([s[1] for s in scenes[1:3]], ["done", "done"])
        self.assertEqual(scenes[3][1], "standby")  # 七期：自动补位页不受他页失败影响
        self.assertEqual(fake.calls["n"], 4)  # 1 大纲 + 3 页，失败页无第二次调用（standby 不烧）

    def test_21_canvas_external_warning_only(self):
        # 画布舞台外链只警告不置败（同 interactive 纪律）：html 不剥除，警告进 error_note
        key = self._course()
        RMC.call_llm_for_user = make_fake_llm(canvas_mode="external")
        RMC._run_generation(self.uidA, key, tuple(self._kp_row()), "", "", "")
        row = self._course_row(key)
        scenes = self._scenes(row[0])
        self.assertEqual(scenes[0][1], "done")
        self.assertIn("cdn.example.com", json.loads(scenes[0][3])["canvas_html"])
        self.assertIn("cdn.example.com", scenes[0][2])

    def _clear_courses(self, uid=None):
        """清本人全部课程行（六期用例开头防残留 generating 干扰去重/索引断言）。"""
        self.conn.execute("DELETE FROM micro_scenes WHERE course_id IN "
                          "(SELECT id FROM micro_courses WHERE user_id = ?)", (uid or self.uidA,))
        self.conn.execute("DELETE FROM micro_courses WHERE user_id = ?", (uid or self.uidA,))
        self.conn.commit()

    # ---- 14. 六期：错题深度讲解 ----
    def test_22_create_error_param_validation(self):
        d = self._data(self._post("/api/micro-course/create", {"error_id": "abc"}))
        self.assertFalse(d.get("success"))
        self.assertIn("参数格式", d.get("error", ""))
        # 评审 m1：bool 不得静默混当整数 id（True→1 会命中真实错题）
        for bad in (True, False):
            d = self._data(self._post("/api/micro-course/create", {"error_id": bad}))
            self.assertFalse(d.get("success"), f"error_id={bad} 应被拒绝")
            self.assertIn("参数格式", d.get("error", ""))
        d = self._data(self._post("/api/micro-course/create", {"error_id": 999999999}))
        self.assertFalse(d.get("success"))
        self.assertIn("不存在或不属于你", d.get("error", ""))
        # 数字字符串可转整：报归属不存在而非参数格式
        d = self._data(self._post("/api/micro-course/create", {"error_id": "999999999"}))
        self.assertIn("不存在或不属于你", d.get("error", ""))
        # 跨用户：B 不得用 A 的错题发起（同一归属文案，不泄露存在性）
        eid = self._mk_error()
        d = self._data(self._post("/api/micro-course/create", {"error_id": eid}, h=self.hB))
        self.assertFalse(d.get("success"))
        self.assertIn("不存在或不属于你", d.get("error", ""))
        # 手动独立错题（kp NULL）：用户裁定放行（无锚合成 kp_row，知识点由大纲从题干归纳）
        eid_none = self._mk_error(kp=None)
        d = self._data(self._post("/api/micro-course/create", {"error_id": eid_none}))
        self.assertTrue(d.get("success"), d)
        self._clear_courses()  # 清本次派发的在飞课，防污染后续用例的去重/索引断言

    def test_23_error_explain_pack(self):
        from routes_knowledge import get_kms
        eid = self._mk_error()
        pack = RMC._error_explain_pack(get_kms(), self.uidA, eid)
        self.assertIsNotNone(pack)
        self.assertEqual(pack["kp_id"], self.kp)
        t = pack["text"]
        for marker in ("【题目】错题测试", "【选项】A. 0", "【你的作答】我选了D不存在",
                       "【正确答案】B", "【题目解析】重要极限",
                       "累计答错 1 次", "当前熟练度 30%"):
            self.assertIn(marker, t)
        self.assertIsNone(RMC._error_explain_pack(get_kms(), self.uidB, eid))  # 非本人
        self.assertIsNone(RMC._error_explain_pack(get_kms(), self.uidA, 999999999))

    def test_24_create_error_full_generation(self):
        # create 全链：错题入口派发后台线程→大纲走错题 prompt→逐页 canvas 落库
        self._clear_courses()
        eid = self._mk_error()
        base = make_fake_llm(outline=OUTLINE_ERR)
        seen = []

        def cap(uid, prompt, context="", scene="", timeout=None):
            seen.append(prompt)
            return base(uid, prompt, context=context, scene=scene, timeout=timeout)
        RMC.call_llm_for_user = cap
        d = self._data(self._post("/api/micro-course/create", {"error_id": eid}))
        self.assertTrue(d.get("success"), d)
        key = d["course_key"]
        row = self._wait_course(key)
        self.assertEqual(row[1], "ready")
        self.assertEqual(row[2], "错题讲解：重要极限")
        r = self.conn.execute("SELECT source_type, source_ref FROM micro_courses "
                              "WHERE course_key = ?", (key,)).fetchone()
        self.conn.commit()
        self.assertEqual(r[0], "error")
        ref = json.loads(r[1])
        self.assertTrue(ref.get("error_explain"))
        self.assertEqual(ref.get("error_ids"), [eid])
        self.assertEqual(ref.get("anchor_kp_id"), self.kp)
        # 大纲 prompt 接线：错题专用（含错题全貌素材块）而非知识点课 prompt
        self.assertIn("错题深度讲解", seen[0])
        self.assertIn("【题目】", seen[0])
        self.assertIn("【你的作答】", seen[0])
        scenes = self._scenes(row[0])
        self.assertEqual(len(scenes), 4)  # 七期：自动补位 1 页互动占位
        self.assertTrue(all(s[1] == "done" for s in scenes[:3]))
        self.assertEqual(scenes[3][1], "standby")
        self.assertEqual(scenes[3][4], self.kp)  # 占位页同样绑锚定 kp（知识点课轨）
        for s in scenes[:2]:  # explain 页分步画布契约与知识点课同源
            obj = json.loads(s[3])
            self.assertIn("canvas_html", obj)
            self.assertTrue(obj["steps"])
        qobj = json.loads(scenes[2][3])  # quiz 页对象契约 + 绑锚定 kp（判分入池同链路）
        self.assertEqual(len(qobj["questions"]), 2)
        self.assertEqual(scenes[2][4], self.kp)

    def test_25_dedup_dual_track_no_cross_hijack(self):
        # 双轨互不劫持：错题课在飞拦不住知识点课，知识点课在飞也拦不住错题课
        self._clear_courses()
        e1 = self._mk_error()
        kErr = self._course_error(anchor=self.kp, eids=[e1])
        RMC.call_llm_for_user = make_fake_llm()
        d = self._data(self._post("/api/micro-course/create", {"kp_id": self.kp}))
        self.assertTrue(d.get("success"), d)
        self.assertFalse(d.get("reused"))  # 未被错题课劫持
        kKp = d["course_key"]
        self.assertNotEqual(kKp, kErr)
        self.assertEqual(self._wait_course(kKp)[1], "ready")
        # 反向：再插一门知识点课在飞（手工行不派线程），发起错题讲解不得被复用
        kKp2 = self._course(anchor=self.kp, status="generating")
        e2 = self._mk_error()
        d2 = self._data(self._post("/api/micro-course/create", {"error_id": e2}))
        self.assertTrue(d2.get("success"), d2)
        self.assertFalse(d2.get("reused"))
        self.assertNotEqual(d2["course_key"], kKp2)
        self.assertEqual(self._wait_course(d2["course_key"])[1], "ready")
        self._clear_courses()  # 手工 kp 在飞行残留会撞后续用例的 anchor 断言

    def test_26_inflight_reuse_same_error(self):
        # 同题在飞：Python 侧按 error_ids 集合命中复用，不双开双扣分
        self._clear_courses()
        e3 = self._mk_error()
        k = self._course_error(anchor=self.kp, eids=[e3])
        d = self._data(self._post("/api/micro-course/create", {"error_id": e3}))
        self.assertTrue(d.get("success"))
        self.assertTrue(d.get("reused"))
        self.assertEqual(d.get("course_key"), k)

    def test_27_inflight_unique_index_dual_track(self):
        # 新双轨索引：同 kp 的 kp 课与错题课在飞可共存；同 error_ids 的错题课互斥；异 error_ids 可共存
        self._clear_courses()
        idef = self.conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_mcourse_inflight'").fetchone()[0]
        self.conn.commit()
        self.assertIn("error_ids", idef)
        self.assertIn("anchor_kp_id", idef)
        self.assertIn("'error'", idef)
        self._course(anchor=self.kp, status="generating")           # kp 轨在飞
        self._course_error(anchor=self.kp, eids=[777001])           # error 轨同 kp 共存→不抛
        collide = False
        try:
            self._course_error(anchor=self.kp, eids=[777001])       # 同 error_ids 再插→必互斥
        except Exception as e:  # noqa: BLE001
            collide = "duplicate key" in str(e).lower() or "重复" in str(e)
            self.conn.rollback()
        self.assertTrue(collide, "同 user+error_ids 在飞课应撞唯一索引")
        self._course_error(anchor=self.kp, eids=[777002])           # 异题不同键→可共存
        self._clear_courses()

    def test_28_estimate_error_mode(self):
        d_err = self._data(self._get("/api/micro-course/estimate?mode=error"))
        d_std = self._data(self._get("/api/micro-course/estimate"))
        self.assertTrue(d_err.get("success"))
        self.assertGreater(d_err["estimated_credits"], 0)
        self.assertLess(d_err["estimated_credits"], d_std["estimated_credits"])  # 4页 < 6页
        # 七期：预估文案必须声明互动页按需计费口径（防用户按弹窗金额预期对不上账）
        self.assertIn("不翻不扣", d_err["note"])
        self.assertIn("不翻不扣", d_std["note"])

    def test_29_history_error_id_scope(self):
        # 历史按 error_ids 口径隔离：不与同锚定知识点课串（三期确认闸防重复扣费依据）
        self._clear_courses()
        e5 = self._mk_error()
        ke = self._course_error(status="ready", anchor=self.kp, eids=[e5])
        kk = self._course(status="ready", anchor=self.kp)
        d = self._data(self._get("/api/micro-course/history?error_id=%d" % e5))
        self.assertTrue(d.get("success"))
        self.assertEqual({c["course_key"] for c in d["courses"]}, {ke})
        d = self._data(self._get("/api/micro-course/history?error_id=%d" % e5, h=self.hB))
        self.assertEqual(d.get("courses"), [])  # 跨用户隔离
        d = self._data(self._get("/api/micro-course/history?error_id=987654321"))
        self.assertEqual(d.get("courses"), [])  # 无既往课空列表而非报错
        d = self._data(self._get("/api/micro-course/history?error_id=abc"))
        self.assertFalse(d.get("success"))  # 非数字落到锚定参数校验，不穿透 500
        # 知识点口径 history 不得混入错题课
        d = self._data(self._get("/api/micro-course/history?kp_id=%d" % self.kp))
        self.assertTrue(d.get("success"))
        self.assertNotIn(ke, {c["course_key"] for c in d["courses"]})
        self.assertIn(kk, {c["course_key"] for c in d["courses"]})
        self._clear_courses()

    def test_30_regenerate_error_scene_brings_material(self):
        # 错题课单页重生成必须带回该题专属素材（否则错因诊断页退化成泛讲知识点）
        self._clear_courses()
        e6 = self._mk_error()
        RMC.call_llm_for_user = make_fake_llm(outline=OUTLINE_ERR, fail_types={"quiz"})
        d = self._data(self._post("/api/micro-course/create", {"error_id": e6}))
        key = d["course_key"]
        row = self._wait_course(key)
        self.assertEqual(row[1], "partial")
        seen = []

        def fake2(uid, prompt, context="", scene="", timeout=None):
            seen.append(prompt)
            return json.dumps({"narration": "再来一遍", "questions": [Q_SINGLE, Q_JUDGE]},
                              ensure_ascii=False)
        RMC.call_llm_for_user = fake2
        d2 = self._data(self._post(f"/api/micro-course/{key}/regenerate-scene", {"seq": 3}))
        self.assertTrue(d2.get("success"), d2)
        self.assertEqual(self._wait_course(key)[1], "ready")
        self.assertTrue(seen)
        self.assertTrue(any("错题测试" in p and "【你的作答】" in p for p in seen),
                        "重生成 prompt 应含该错题专属素材块")

    def test_31_create_error_no_kp_full_generation(self):
        # 六期用户裁定补丁：独立错题（kp NULL）全链生成——无锚合成行、
        # 页行 kp_id 全 NULL、学科取错题行归属、大纲 prompt 走「归纳知识点」分支文案
        self._clear_courses()
        eid = self._mk_error(kp=None)
        subj = "测试学科MC" + self.suffix
        base = make_fake_llm(outline=OUTLINE_ERR)
        seen = []

        def cap(uid, prompt, context="", scene="", timeout=None):
            seen.append(prompt)
            return base(uid, prompt, context=context, scene=scene, timeout=timeout)
        RMC.call_llm_for_user = cap
        try:
            d = self._data(self._post("/api/micro-course/create", {"error_id": eid}))
            self.assertTrue(d.get("success"), d)
            key = d["course_key"]
            row = self._wait_course(key)
            self.assertEqual(row[1], "ready")
            r = self.conn.execute("SELECT source_type, source_ref, subject_name FROM micro_courses "
                                  "WHERE course_key = ?", (key,)).fetchone()
            self.conn.commit()
            self.assertEqual(r[0], "error")
            ref = json.loads(r[1])
            self.assertTrue(ref.get("error_explain"))
            self.assertIsNone(ref.get("anchor_kp_id"))  # 无锚：JSON null
            self.assertEqual(ref.get("error_ids"), [eid])
            self.assertEqual(r[2], subj)  # 学科回落错题行自身归属（非「未分学科」）
            self.assertIn("尚未关联知识点", seen[0])  # 大纲走无 kp 分支
            self.assertIn("归纳", seen[0])
            self.assertIn("无掌握度数据", seen[0])
            self.assertNotIn("尚未评估", seen[0])  # 无锚形态不引用掌握度哨兵
            scenes = self._scenes(row[0])
            self.assertEqual(len(scenes), 4)  # 七期：自动补位 1 页互动占位
            self.assertTrue(all(s[1] == "done" for s in scenes[:3]))
            self.assertEqual(scenes[3][1], "standby")
            self.assertTrue(all(s[4] is None for s in scenes))  # 页行 kp_id 全 NULL（含占位页）
            self.assertTrue(any("页型=quiz" in p and "题目锚定" in p for p in seen[1:]),
                            "页生成 prompt 应走题目锚定回落文案")
            qobj = json.loads(scenes[2][3])  # 变式题照常产出（判分由前端回落错题轨）
            self.assertEqual(len(qobj["questions"]), 2)
        finally:
            self._clear_courses()

    def test_32_regenerate_no_kp_scene(self):
        # 无锚错题课单页重生成：不得误报「知识点已删除」，且仍带回该题专属素材
        self._clear_courses()
        eid = self._mk_error(kp=None)
        RMC.call_llm_for_user = make_fake_llm(outline=OUTLINE_ERR, fail_types={"quiz"})
        d = self._data(self._post("/api/micro-course/create", {"error_id": eid}))
        key = d["course_key"]
        row = self._wait_course(key)
        self.assertEqual(row[1], "partial")
        seen = []

        def fake2(uid, prompt, context="", scene="", timeout=None):
            seen.append(prompt)
            return json.dumps({"narration": "再来一遍", "questions": [Q_SINGLE, Q_JUDGE]},
                              ensure_ascii=False)
        RMC.call_llm_for_user = fake2
        try:
            d2 = self._data(self._post(f"/api/micro-course/{key}/regenerate-scene", {"seq": 3}))
            self.assertTrue(d2.get("success"), d2)
            self.assertEqual(self._wait_course(key)[1], "ready")
            self.assertTrue(seen)
            self.assertTrue(any("错题测试" in p and "题目锚定" in p for p in seen),
                            "无锚重生成应带专属素材且走题目锚定文案")
        finally:
            self._clear_courses()
            RMC.call_llm_for_user = make_fake_llm()

    def test_33_standby_on_demand_full_chain_and_detail_fields(self):
        # 七期：知识点课 create 全链——互动页 standby 占位不烧 LLM；detail 透传
        # worthy/note/单页价；翻到该页 regenerate 点亮；已生成完的 standby 再点拒绝双烧
        self._clear_courses()
        fake = make_fake_llm()  # 默认 OUTLINE 无互动页→自动补位，worthy 保守 false
        RMC.call_llm_for_user = fake
        try:
            d = self._data(self._post("/api/micro-course/create", {"kp_id": self.kp}))
            self.assertTrue(d.get("success"), d)
            key = d["course_key"]
            row = self._wait_course(key)
            self.assertEqual(row[1], "ready")
            self.assertEqual(fake.calls["n"], 4)  # 1 大纲 + 3 页，占位互动页零消耗
            dd = self._data(self._get("/api/micro-course/" + key))
            self.assertIs(dd["interactive_worthy"], False)  # 按钮分支（不自动烧钱）
            self.assertGreater(dd["scene_unit_cost"], 0)    # 同屏积分提示可用
            inter_sc = [s for s in dd["scenes"] if s["scene_type"] == "interactive"]
            self.assertEqual(len(inter_sc), 1)
            self.assertEqual(inter_sc[0]["status"], "standby")
            self.assertIsNone(inter_sc[0]["content"])  # 占位页无正文下发
            # 用户点「生成互动实验」→ regenerate-scene 点亮
            d2 = self._data(self._post(f"/api/micro-course/{key}/regenerate-scene",
                                       {"seq": inter_sc[0]["seq"]}))
            self.assertTrue(d2.get("success"), d2)
            self.assertEqual(self._wait_course(key)[1], "ready")
            dd2 = self._data(self._get("/api/micro-course/" + key))
            done_sc = [s for s in dd2["scenes"] if s["seq"] == inter_sc[0]["seq"]][0]
            self.assertEqual(done_sc["status"], "done")
            self.assertIn("html", done_sc["content"] or {})
            # 乐观锁回归：pending 残页不得被白名单放进（防烧穿双重生成）
            cid = row[0]
            self.conn.execute("INSERT INTO micro_scenes (course_id, seq, scene_type, kp_id, title, "
                              "status, content_json) VALUES (?, 9, 'explain', ?, '残页', 'pending', '')",
                              (cid, self.kp))
            self.conn.commit()
            d3 = self._data(self._post(f"/api/micro-course/{key}/regenerate-scene", {"seq": 9}))
            self.assertFalse(d3.get("success"))
            self.assertIn("正在生成中", d3.get("error", ""))
            self.conn.execute("DELETE FROM micro_scenes WHERE course_id = ? AND seq = 9", (cid,))
            self.conn.commit()
        finally:
            self._clear_courses()

    def test_34_worthy_true_passthrough_not_generated(self):
        # 七期：大纲自带互动页且 worthy=true → detail 透传 true/note；创建期仍零消耗
        self._clear_courses()
        fake = make_fake_llm(outline=OUTLINE_W)
        RMC.call_llm_for_user = fake
        try:
            d = self._data(self._post("/api/micro-course/create", {"kp_id": self.kp}))
            key = d["course_key"]
            row = self._wait_course(key)
            self.assertEqual(row[1], "ready")
            self.assertEqual(fake.calls["n"], 4)  # 1 大纲 + explain/quiz/summary 三页
            dd = self._data(self._get("/api/micro-course/" + key))
            self.assertIs(dd["interactive_worthy"], True)  # 前端据此翻开自动生成
            self.assertEqual(dd["interactive_note"], "函数图像参数可拖拽观察")
            sc2 = [s for s in dd["scenes"] if s["seq"] == 2][0]
            self.assertEqual(sc2["status"], "standby")
        finally:
            self._clear_courses()


if __name__ == "__main__":
    unittest.main(verbosity=2)
