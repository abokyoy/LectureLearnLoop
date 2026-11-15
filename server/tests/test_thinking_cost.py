# -*- coding: utf-8 -*-
"""原理图成本优化轮（2026-11-10）LLM 层与落库层白盒断言，零真实外呼：
- 场景策略表 _resolve_thinking：显式参数优先 / 白名单默认关 / 其余保持现状；
- DeepSeekProvider payload thinking 字段注入（off/on/None 三态）与 usage 明细采集；
- charge_llm usage_note 进流水；
- principle_cache 版本递增、latest 取最新、跨用户隔离、脏键拒收。
"""
from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import credits_service as cr
from app import create_app
import llm_provider_factory as F
from services import principle_cache as PC

APP = create_app()


class _Resp:
    ok = True
    status_code = 200

    def __init__(self, payload_usage):
        self._u = payload_usage

    def json(self):
        return {"choices": [{"message": {"content": "ok-reply"}}],
                "usage": self._u}


class ThinkingPolicyTest(unittest.TestCase):
    def test_01_resolve_explicit_wins(self):
        self.assertEqual(F._resolve_thinking("原理图生成", "on"), "on")
        self.assertEqual(F._resolve_thinking("AI聊天", "off"), "off")

    def test_02_resolve_scene_table(self):
        for scene in F.THINKING_OFF_SCENES:
            self.assertEqual(F._resolve_thinking(scene, None), "off")

    def test_03_resolve_default(self):
        self.assertIsNone(F._resolve_thinking("AI Chat", None))
        self.assertIsNone(F._resolve_thinking("", "banana"))


class DeepSeekPayloadTest(unittest.TestCase):
    def setUp(self):
        self._orig_post = F.requests.post
        self.captured = {}

        def fake_post(url, headers=None, json=None, timeout=None, stream=False):
            self.captured["payload"] = json
            self.captured["stream"] = stream
            return _Resp({"prompt_tokens": 10, "completion_tokens": 20,
                          "prompt_cache_hit_tokens": 7,
                          "completion_tokens_details": {"reasoning_tokens": 5}})
        F.requests.post = fake_post
        self.provider = F.DeepSeekProvider(
            {"deepseek_api_key": "test-key", "deepseek_model": "deepseek-chat"})

    def tearDown(self):
        F.requests.post = self._orig_post

    def test_10_off_injects_disabled(self):
        u = {}
        out = self.provider.call("p", usage_out=u, thinking="off")
        self.assertEqual(out, "ok-reply")
        self.assertEqual(self.captured["payload"]["thinking"], {"type": "disabled"})
        # OpenAI 兼容网关只认 chat_template_kwargs，off 时双发（2026-11-11）
        self.assertEqual(self.captured["payload"]["chat_template_kwargs"],
                         {"enable_thinking": False})
        self.assertEqual(u["cached_tokens"], 7)
        self.assertEqual(u["reasoning_tokens"], 5)

    def test_11_on_injects_enabled(self):
        self.provider.call("p", usage_out={}, thinking="on")
        self.assertEqual(self.captured["payload"]["thinking"], {"type": "enabled"})
        # on 不发 chat_template_kwargs（默认就是开思考，不额外碰网关）
        self.assertNotIn("chat_template_kwargs", self.captured["payload"])

    def test_12_none_leaves_payload_untouched(self):
        self.provider.call("p", usage_out={})
        self.assertNotIn("thinking", self.captured["payload"])
        self.assertNotIn("chat_template_kwargs", self.captured["payload"])
        # 非隧道端点保持非流式，官方行为不变
        self.assertFalse(self.captured["payload"]["stream"])
        self.assertFalse(self.captured["stream"])

    def test_13_tunnel_url_forces_stream(self):
        """trycloudflare 隧道端点：强制流式保活，躲开 Cloudflare ~100s 空闲掉线。"""
        p = F.DeepSeekProvider({
            "deepseek_api_key": "test-key", "deepseek_model": "m",
            "deepseek_api_url":
                "https://fake-sub.trycloudflare.com/v1/chat/completions"})
        orig = F._collect_openai_sse
        F._collect_openai_sse = lambda resp: ("sse-reply", {"completion_tokens": 3})
        try:
            out = p.call("p", usage_out={})
        finally:
            F._collect_openai_sse = orig
        self.assertEqual(out, "sse-reply")
        self.assertTrue(self.captured["payload"]["stream"])
        self.assertEqual(self.captured["payload"]["stream_options"],
                         {"include_usage": True})
        self.assertTrue(self.captured["stream"])


class UsageNoteFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        uname = "ucn_" + uuid.uuid4().hex[:6]
        cls.client.post("/api/auth/register",
                        json={"username": uname, "password": "test123456"})
        tok = cls.client.post("/api/auth/login", json={
            "username": uname, "password": "test123456"}).get_json()["data"]["token"]
        seg = tok.split(".")[1]
        cls.uid = str(json.loads(__import__("base64").urlsafe_b64decode(
            seg + "=" * (-len(seg) % 4)))["uid"])

    def _latest_note(self):
        with cr._conn() as conn:
            row = conn.execute(
                "SELECT note FROM credit_transactions WHERE user_id = ? "
                "ORDER BY id DESC LIMIT 1", (self.uid,)).fetchone()
        return str(row[0] if row else "")

    def test_20_usage_note_lands_in_ledger(self):
        cr.charge_llm(self.uid, 10, 20, scene="测试场景", provider="DeepSeek",
                      model="deepseek-chat",
                      usage_note="cache_hit=7 reasoning=120 thinking=off")
        note = self._latest_note()
        self.assertIn("cache_hit=7", note)
        self.assertIn("reasoning=120", note)
        self.assertIn("thinking=off", note)

    def test_21_no_usage_note_keeps_note_clean(self):
        cr.charge_llm(self.uid, 10, 20, scene="测试场景", provider="DeepSeek",
                      model="deepseek-chat")
        note = self._latest_note()
        self.assertNotIn("cache_hit", note)
        self.assertIn("DeepSeek/deepseek-chat", note)


class PrincipleCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uid = "pcu_" + uuid.uuid4().hex[:10]
        cls.uid2 = "pcv_" + uuid.uuid4().hex[:10]

    def test_30_put_latest_versioning(self):
        ref = "lk-" + uuid.uuid4().hex[:8]
        r1 = PC.put(self.uid, "lesson", ref, {"title": "T1", "html": "<!DOCTYPE html>a"},
                    mode="off")
        self.assertTrue(r1["success"])
        r2 = PC.put(self.uid, "lesson", ref, {"title": "T2", "html": "<!DOCTYPE html>b"},
                    mode="on")
        self.assertTrue(r2["success"])
        self.assertEqual(r2["seq"], r1["seq"] + 1)      # 版本递增，旧版留档
        hit = PC.latest(self.uid, "lesson", ref)
        self.assertEqual(hit["seq"], r2["seq"])         # latest 取最新
        self.assertEqual(hit["content"]["mode"], "on")
        self.assertEqual(hit["content"]["title"], "T2")

    def test_31_user_isolation(self):
        ref = "lk-" + uuid.uuid4().hex[:8]
        PC.put(self.uid, "lesson", ref, {"title": "T", "html": "h"}, mode="off")
        self.assertIsNone(PC.latest(self.uid2, "lesson", ref))

    def test_32_dirty_inputs_rejected(self):
        self.assertFalse(PC.put(self.uid, "", "x", {"title": "T"})["success"])
        self.assertFalse(PC.put(self.uid, "lesson", "", {"title": "T"})["success"])
        self.assertFalse(PC.put(self.uid, "lesson", "r", "not-a-dict")["success"])
        self.assertIsNone(PC.latest(self.uid, "", ""))

    def test_33_oversize_rejected(self):
        r = PC.put(self.uid, "lesson", "lk-oversize",
                   {"title": "T", "html": "x" * (PC._CONTENT_MAX + 1)})
        self.assertFalse(r["success"])
        self.assertIn("超限", r["error"])

    # ---- 旧版回看（用户裁定：可看可转正，纯读库/库内拷贝）----
    def test_40_versions_and_get(self):
        ref = "lk-" + uuid.uuid4().hex[:8]
        r1 = PC.put(self.uid, "lesson", ref, {"title": "T1", "html": "h1"}, mode="off")
        r2 = PC.put(self.uid, "lesson", ref, {"title": "T2", "html": "h2"}, mode="on")
        vs = PC.versions(self.uid, "lesson", ref)
        self.assertEqual([v["seq"] for v in vs], [r2["seq"], r1["seq"]])  # 最新在前
        self.assertEqual(vs[0]["mode"], "on")
        self.assertEqual(vs[1]["mode"], "off")
        self.assertTrue(vs[0]["created_time"])
        g1 = PC.get(self.uid, "lesson", ref, r1["seq"])
        self.assertEqual(g1["content"]["html"], "h1")
        self.assertIsNone(PC.get(self.uid, "lesson", ref, 999))   # 无此版
        self.assertEqual(PC.versions(self.uid2, "lesson", ref), [])  # 跨用户隔离

    def test_41_promote_copy_and_noop(self):
        ref = "lk-" + uuid.uuid4().hex[:8]
        r1 = PC.put(self.uid, "lesson", ref, {"title": "T1", "html": "h1"}, mode="off")
        r2 = PC.put(self.uid, "lesson", ref, {"title": "T2", "html": "h2"}, mode="on")
        p = PC.promote(self.uid, "lesson", ref, r1["seq"])
        self.assertTrue(p["success"])
        self.assertEqual(p["seq"], r2["seq"] + 1)      # 库内拷贝成新当前版
        hit = PC.latest(self.uid, "lesson", ref)
        self.assertEqual(hit["content"]["html"], "h1")  # 旧版内容成了当前版
        self.assertEqual(hit["content"]["mode"], "off")  # 保留旧版自己的思考标记
        p2 = PC.promote(self.uid, "lesson", ref, p["seq"])
        self.assertTrue(p2["success"])
        self.assertTrue(p2.get("noop"))                # 已是最新：不刷重复版本
        self.assertFalse(PC.promote(self.uid, "lesson", ref, 999)["success"])

    # ---- 作废（2026-11-10 坏产物被「同知识点永远复用」永久回放事故）----
    def test_42_void_hides_version_from_all_reads(self):
        ref = "lk-" + uuid.uuid4().hex[:8]
        r1 = PC.put(self.uid, "lesson", ref, {"title": "T1", "html": "h1"}, mode="off")
        r2 = PC.put(self.uid, "lesson", ref, {"title": "T2", "canvas_html": "bad"},
                    mode="off")
        v = PC.void(self.uid, "lesson", ref, r2["seq"])
        self.assertTrue(v["success"])
        self.assertFalse(v.get("noop"))
        hit = PC.latest(self.uid, "lesson", ref)
        self.assertEqual(hit["seq"], r1["seq"])          # 坏版不再当“当前版”回放
        self.assertIsNone(PC.get(self.uid, "lesson", ref, r2["seq"]))  # 指定版也筛掉
        self.assertEqual([x["seq"] for x in PC.versions(self.uid, "lesson", ref)],
                         [r1["seq"]])
        again = PC.void(self.uid, "lesson", ref, r2["seq"])
        self.assertTrue(again["success"])
        self.assertTrue(again.get("noop"))               # 已虚：重复作废不报错
        self.assertFalse(PC.void(self.uid, "", "", 1)["success"])
        self.assertFalse(PC.void(self.uid, "lesson", "lk-nope", 1)["success"])

    def test_43_void_does_not_touch_other_versions(self):
        ref = "lk-" + uuid.uuid4().hex[:8]
        r1 = PC.put(self.uid, "lesson", ref, {"title": "T1", "html": "h1"}, mode="off")
        r2 = PC.put(self.uid, "lesson", ref, {"title": "T2", "html": "h2"}, mode="on")
        PC.void(self.uid, "lesson", ref, r2["seq"])
        self.assertEqual(PC.get(self.uid, "lesson", ref, r1["seq"])["content"]["html"], "h1")
        # 旧版留档可回看：作废只针对被点名那一版，不连坐
        self.assertEqual(PC.latest(self.uid, "lesson", ref)["seq"], r1["seq"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
