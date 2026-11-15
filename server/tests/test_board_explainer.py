# -*- coding: utf-8 -*-
"""黑板「原理图」生成（html-explainer Demo 轮 2026-11-09）断言测试。

零真实 LLM 调用（BE.call_llm_for_user 打桩）、零小智云依赖：
- 认证走真实注册/登录链，独立随机测试用户，不污染正式数据；
- 板面素材 monkeypatch LB.get_state 构造（提示词内容/空板判定全可控）；
- 覆盖：提示词素材序列化纪律（学生话不进素材、图标记进素材）、作业状态机、
  在飞去重（防双击双扣分）、格式非法/超长/积分不足三类失败终态、外链警告、
  跨用户隔离、HTTP 端点（401 / POST 开工 / GET 轮询 / 空板拒收）。
"""
from __future__ import annotations

import base64
import copy
import json
import threading
import time
import unittest
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import credits_service as cr
from app import create_app
from services import board_explainer as BE
from services import lecture_board as LB
from services import principle_cache as PC

APP = create_app()

_GOOD_HTML = ('<!DOCTYPE html><html><body><style>:root{--c1:#2a7}</style>'
              '<button onclick="1">next</button></body></html>')
SNAP = {
    "rev": 9, "changed": True,
    "items": [
        {"id": 1, "kind": "step",
         "text": "由中位线定理可知，中位线平行于底边且等于底边的一半",
         "anchors": ["中位线定理", "底边"]},
        {"id": 2, "kind": "plot", "text": "三角形ABC",
         "data": {"plot_type": "geometry", "title": "中位线图",
                  "marks": [{"name": "点A"}, {"name": "点B"}],
                  "points": [{"label": "A", "x": 0, "y": 0}]}},
    ],
    "speech": [
        {"id": 3, "role": "teacher", "text": "我们先看这条中位线"},
        {"id": 4, "role": "student", "text": "暗号不能进素材XYZ"},
    ],
    "focus": None, "outbox": [], "lesson_key": "lk-hx-test",
}
SNAP_EMPTY = {"rev": 1, "changed": True, "items": [], "speech": [],
              "focus": None, "outbox": [], "lesson_key": None}


def _json_ok(**over):
    d = {"title": "中位线定理交互示意", "narration": "这张图演示中位线为什么是底边的一半",
         "html": _GOOD_HTML}
    d.update(over)
    return json.dumps(d, ensure_ascii=False)


class HxStub:
    """可控 LLM 打桩：记调用（含 thinking 模式）、可阻塞、可抛错/返回脏内容。"""

    def __init__(self, result=None, raises=None, gate=None):
        self.result, self.raises, self.gate = result, raises, gate
        self.calls = []

    def __call__(self, uid, prompt, context="", scene="", timeout=None,
                 thinking=None):
        self.calls.append({"uid": uid, "prompt": prompt, "scene": scene,
                           "timeout": timeout, "thinking": thinking})
        if self.gate is not None:
            assert self.gate.wait(10), "stub gate 卡死"
        if self.raises is not None:
            raise self.raises
        return self.result


class BoardExplainerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        uname = "hxt_" + uuid.uuid4().hex[:6]
        cls.client.post("/api/auth/register",
                        json={"username": uname, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": uname, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        cls.uid = str(json.loads(base64.urlsafe_b64decode(
            seg + "=" * (-len(seg) % 4)))["uid"])
        cls.h = {"Authorization": "Bearer " + tok}
        cls._orig_gs = LB.get_state
        cls._orig_llm = BE.call_llm_for_user
        cls._orig_lk = LB.get_lesson_key

    def setUp(self):
        # 重大纪律（本轮实捕污染事故）：函数存成类属性后绝不能用 self._orig_XXX 取——
        # 描述符协议会把实例绑成 self、吞掉首参，恢复出去的就是窄签名污染函数，
        # 后续任何文件真走该函数即 TypeError/500。统一用 type(self) 取原函数。
        LB.get_state = lambda uid, since=0: copy.deepcopy(SNAP)
        BE.call_llm_for_user = HxStub(result=_json_ok())
        LB.get_lesson_key = type(self)._orig_lk   # 默认无课堂键 → 库链路不参与（旧行为）
        with BE._LOCK:
            BE._JOBS.clear()

    def tearDown(self):
        LB.get_state = type(self)._orig_gs
        BE.call_llm_for_user = type(self)._orig_llm
        LB.get_lesson_key = type(self)._orig_lk
        with BE._LOCK:
            BE._JOBS.clear()

    # ---- 工具 ----
    def _wait_done(self, uid, job_id, timeout=10.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            j = BE.get_job(uid, job_id)
            if j and j["state"] != "generating":
                return j
            time.sleep(0.05)
        self.fail(f"作业 {job_id} 未达终态")

    # ---- 提示词素材纪律 ----
    def test_01_prompt_material(self):
        p = BE.build_prompt(copy.deepcopy(SNAP), "中位线定理")
        self.assertIn("中位线定理", p)                    # 板书正文进素材
        self.assertIn("三角形ABC", p)
        self.assertIn("点A/点B", p)                       # 图标记摘要进素材
        self.assertIn("我们先看这条中位线", p)             # 老师旁白进素材
        self.assertNotIn("暗号不能进素材XYZ", p)           # 学生的话不进素材
        self.assertIn("本课主题：中位线定理", p)
        self.assertIn("CSS 变量", p)                      # html-explainer 纪律移植
        self.assertIn("禁止引用任何外部资源", p)
        self.assertIn("上一步/下一步/自动播放", p)          # 交互硬要求
        self.assertIn("一场景一焦点", p)

    def test_02_prompt_truncation(self):
        big = copy.deepcopy(SNAP)
        big["items"] = [{"id": i, "kind": "step", "text": "长" * 500}
                        for i in range(60)]
        p = BE.build_prompt(big)
        self.assertLessEqual(len(p), 9000)               # 素材区有顶，不会无限喂

    # ---- 空板拒收 / 开工 ----
    def test_10_empty_board_rejected(self):
        LB.get_state = lambda uid, since=0: copy.deepcopy(SNAP_EMPTY)
        r = BE.start(self.uid)
        self.assertFalse(r["success"])
        self.assertIn("先请老师开讲", r["error"])

    def test_11_speech_only_board_ok(self):
        """板上卡被擦光但老师说过话：仍算有素材（课堂语境还在）。"""
        s = copy.deepcopy(SNAP_EMPTY)
        s["speech"] = [{"id": 1, "role": "teacher", "text": "刚才我们讲了中位线"}]
        LB.get_state = lambda uid, since=0: copy.deepcopy(s)
        r = BE.start(self.uid)
        self.assertTrue(r["success"])
        j = self._wait_done(self.uid, r["job"]["job_id"])
        self.assertEqual(j["state"], "done")

    def test_20_start_done(self):
        r = BE.start(self.uid)
        self.assertTrue(r["success"])
        j = self._wait_done(self.uid, r["job"]["job_id"])
        self.assertEqual(j["state"], "done")
        self.assertEqual(j["title"], "中位线定理交互示意")
        self.assertTrue(j["html"].startswith("<!DOCTYPE html>"))
        self.assertIsNone(j["warning"])                  # 无外链 → 无警告

    def test_21_billing_channel_params(self):
        stub = HxStub(result=_json_ok())
        BE.call_llm_for_user = stub
        r = BE.start(self.uid)
        self._wait_done(self.uid, r["job"]["job_id"])
        self.assertEqual(stub.calls[0]["uid"], self.uid)
        self.assertEqual(stub.calls[0]["scene"], "原理图生成")
        self.assertEqual(stub.calls[0]["timeout"], BE._LLM_TIMEOUT)
        # 成本优化轮：日常生成显式关思考（规则 1）
        self.assertEqual(stub.calls[0]["thinking"], "off")

    # ---- 在飞去重（防双击双扣分）----
    def test_30_inflight_reuse(self):
        gate = threading.Event()
        BE.call_llm_for_user = HxStub(result=_json_ok(), gate=gate)
        r1 = BE.start(self.uid)
        r2 = BE.start(self.uid)
        self.assertTrue(r2.get("reused"))
        self.assertEqual(r1["job"]["job_id"], r2["job"]["job_id"])
        gate.set()
        j = self._wait_done(self.uid, r1["job"]["job_id"])
        self.assertEqual(j["state"], "done")

    # ---- 三类失败终态 ----
    def test_40_bad_format(self):
        BE.call_llm_for_user = HxStub(result="我不会输出 JSON，抱歉")
        r = BE.start(self.uid)
        j = self._wait_done(self.uid, r["job"]["job_id"])
        self.assertEqual(j["state"], "failed")
        self.assertTrue(j.get("error"))

    def test_41_html_over_len(self):
        BE.call_llm_for_user = HxStub(result=_json_ok(html="x" * 20000))
        r = BE.start(self.uid)
        j = self._wait_done(self.uid, r["job"]["job_id"])
        self.assertEqual(j["state"], "failed")

    def test_42_credits_short(self):
        BE.call_llm_for_user = HxStub(raises=cr.InsufficientCreditsError(0))
        r = BE.start(self.uid)
        j = self._wait_done(self.uid, r["job"]["job_id"])
        self.assertEqual(j["state"], "failed")
        self.assertIn("积分", j["error"])

    # ---- 外链只警告不拦截（微课 C2 口径）----
    def test_50_external_warn(self):
        h = _GOOD_HTML + '<script src="https://cdn.example.com/x.js"></script>'
        BE.call_llm_for_user = HxStub(result=_json_ok(html=h))
        r = BE.start(self.uid)
        j = self._wait_done(self.uid, r["job"]["job_id"])
        self.assertEqual(j["state"], "done")
        self.assertTrue(j["warning"])
        self.assertIn("cdn.example.com", j["warning"])

    # ---- 跨用户隔离 ----
    def test_60_job_isolation(self):
        r = BE.start(self.uid)
        jid = r["job"]["job_id"]
        self._wait_done(self.uid, jid)
        self.assertIsNone(BE.get_job("999999999", jid))
        self.assertIsNotNone(BE.get_job(self.uid, jid))
        self.assertIsNone(BE.get_job(self.uid, "deadbeefdeadbeef"))

    # ---- HTTP 端点 ----
    def test_70_auth_401(self):
        r = self.client.post("/api/board/explain")
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/board/explain/abc123")
        self.assertEqual(r.status_code, 401)

    def test_71_http_roundtrip(self):
        r = self.client.post("/api/board/explain", headers=self.h)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        jid = body["data"]["job"]["job_id"]
        for _ in range(200):
            g = self.client.get(f"/api/board/explain/{jid}", headers=self.h).get_json()
            self.assertTrue(g["success"])
            if g["data"]["job"]["state"] != "generating":
                break
            time.sleep(0.05)
        self.assertEqual(g["data"]["job"]["state"], "done")
        self.assertIn("<!DOCTYPE html>", g["data"]["job"]["html"])

    def test_72_http_empty_board(self):
        LB.get_state = lambda uid, since=0: copy.deepcopy(SNAP_EMPTY)
        r = self.client.post("/api/board/explain", headers=self.h)
        body = r.get_json()
        self.assertFalse(body["success"])
        self.assertIn("黑板", body["error"])

    def test_73_http_foreign_job_404ish(self):
        r = self.client.post("/api/board/explain", headers=self.h)
        jid = r.get_json()["data"]["job"]["job_id"]
        # 换个用户来查：不存在
        u2 = "hxu_" + uuid.uuid4().hex[:6]
        self.client.post("/api/auth/register",
                         json={"username": u2, "password": "test123456"})
        tok2 = self.client.post("/api/auth/login", json={
            "username": u2, "password": "test123456"}).get_json()["data"]["token"]
        g = self.client.get(f"/api/board/explain/{jid}",
                            headers={"Authorization": "Bearer " + tok2}).get_json()
        self.assertFalse(g["success"])
        self.assertIn("不存在", g["error"])


    # ---- 库复用与 refresh（成本优化轮 2026-11-10，规则 1+2）----
    def test_80_cache_reuse_zero_calls(self):
        lkey = "lkt_" + uuid.uuid4().hex[:8]
        LB.get_lesson_key = lambda uid: lkey
        stub1 = HxStub(result=_json_ok())
        BE.call_llm_for_user = stub1
        r1 = BE.start(self.uid)
        j1 = self._wait_done(self.uid, r1["job"]["job_id"])
        self.assertEqual(j1["state"], "done")
        self.assertEqual(len(stub1.calls), 1)
        hit = PC.latest(self.uid, "lesson", lkey)
        self.assertIsNotNone(hit)                      # 完成即归档
        self.assertEqual(hit["content"]["mode"], "off")
        # 二次打开：库命中 → done job 秒回，零外呼零扣分（规则 2）
        stub2 = HxStub(result=_json_ok())
        BE.call_llm_for_user = stub2
        r2 = BE.start(self.uid)
        self.assertEqual(r2.get("reused"), "cache")
        self.assertEqual(r2["job"]["state"], "done")
        self.assertEqual(r2["job"]["html"], _GOOD_HTML)
        self.assertEqual(len(stub2.calls), 0)
        # 重新生成：跳过复用、开思考、新版本行覆盖（规则 1）
        stub3 = HxStub(result=_json_ok(title="深度重画版"))
        BE.call_llm_for_user = stub3
        r3 = BE.start(self.uid, refresh=True)
        j3 = self._wait_done(self.uid, r3["job"]["job_id"])
        self.assertEqual(j3["state"], "done")
        self.assertEqual(len(stub3.calls), 1)
        self.assertEqual(stub3.calls[0]["thinking"], "on")
        hit2 = PC.latest(self.uid, "lesson", lkey)
        self.assertEqual(hit2["seq"], hit["seq"] + 1)   # 版本 +1
        self.assertEqual(hit2["content"]["mode"], "on")

    def test_81_latest_endpoint(self):
        lkey = "lkt_" + uuid.uuid4().hex[:8]
        LB.get_lesson_key = lambda uid: lkey
        g = self.client.get("/api/board/explain/latest", headers=self.h).get_json()
        self.assertTrue(g["success"])
        self.assertIsNone(g["data"]["job"])             # 未生成过 → 空
        r = self.client.post("/api/board/explain", json={}, headers=self.h)
        jid = r.get_json()["data"]["job"]["job_id"]
        self._wait_done(self.uid, jid)
        g = self.client.get("/api/board/explain/latest", headers=self.h).get_json()
        self.assertEqual(g["data"]["job"]["state"], "done")
        self.assertIn("<!DOCTYPE html>", g["data"]["job"]["html"])
        # refresh 入参透传：带 body 的 POST 走开思考链路（桩不扣费，断参数）
        stub = HxStub(result=_json_ok())
        BE.call_llm_for_user = stub
        r2 = self.client.post("/api/board/explain",
                              json={"refresh": True}, headers=self.h)
        jid2 = r2.get_json()["data"]["job"]["job_id"]
        self._wait_done(self.uid, jid2)
        self.assertEqual(stub.calls[0]["thinking"], "on")

    # ---- 旧版回看端点（用户裁定 2026-11：可看可转正，全程零外呼零扣分）----
    def test_82_versions_view_promote_zero_calls(self):
        lkey = "lkt_" + uuid.uuid4().hex[:8]
        LB.get_lesson_key = lambda uid: lkey
        stub = HxStub(result=_json_ok(title="第一版"))
        BE.call_llm_for_user = stub
        jid = self.client.post("/api/board/explain", json={},
                               headers=self.h).get_json()["data"]["job"]["job_id"]
        self._wait_done(self.uid, jid)
        stub2 = HxStub(result=_json_ok(title="第二版"))
        BE.call_llm_for_user = stub2
        jid2 = self.client.post("/api/board/explain", json={"refresh": True},
                                headers=self.h).get_json()["data"]["job"]["job_id"]
        self._wait_done(self.uid, jid2)
        g = self.client.get("/api/board/explain/versions", headers=self.h).get_json()
        vs = g["data"]["versions"]
        self.assertEqual(len(vs), 2)
        self.assertEqual(vs[0]["seq"], vs[1]["seq"] + 1)   # 最新在前
        self.assertEqual(vs[0]["mode"], "on")              # v2 出自 refresh
        self.assertEqual(vs[1]["mode"], "off")
        # 看旧版：纯读库，一次外呼不多
        gv = self.client.get("/api/board/explain/version/%d" % vs[1]["seq"],
                             headers=self.h).get_json()
        self.assertEqual(gv["data"]["job"]["state"], "done")
        self.assertEqual(gv["data"]["job"]["seq"], vs[1]["seq"])
        self.assertIn("第一版", gv["data"]["job"]["title"])
        # 零外呼锁两个桩（评审 Nit：只看已被替换的旧桩锁不住后继路径）
        self.assertEqual((len(stub.calls), len(stub2.calls)), (1, 1))
        # 无此版 → 404
        r404 = self.client.get("/api/board/explain/version/999999", headers=self.h)
        self.assertEqual(r404.status_code, 404)
        # 旧版转正：库内拷贝成新当前版，latest 即切旧版内容，仍零外呼
        p = self.client.post("/api/board/explain/promote",
                             json={"seq": vs[1]["seq"]}, headers=self.h).get_json()
        self.assertTrue(p["success"])
        new_seq = p["data"]["seq"]
        self.assertEqual(new_seq, vs[0]["seq"] + 1)
        gl = self.client.get("/api/board/explain/latest", headers=self.h).get_json()
        self.assertEqual(gl["data"]["job"]["seq"], new_seq)
        self.assertIn("第一版", gl["data"]["job"]["title"])
        self.assertEqual((len(stub.calls), len(stub2.calls)), (1, 1))  # 转正也零外呼
        # 再转正最新版 → noop；脏参数 → 拒收
        p2 = self.client.post("/api/board/explain/promote",
                              json={"seq": new_seq}, headers=self.h).get_json()
        self.assertTrue(p2["data"]["noop"])
        p3 = self.client.post("/api/board/explain/promote", json={},
                              headers=self.h).get_json()
        self.assertFalse(p3["success"])
        p4 = self.client.post("/api/board/explain/promote", json={"seq": True},
                              headers=self.h).get_json()
        self.assertFalse(p4["success"])                    # bool 不穿透成版 1


if __name__ == "__main__":
    unittest.main(verbosity=2)
