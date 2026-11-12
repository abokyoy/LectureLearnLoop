# -*- coding: utf-8 -*-
"""GLMProvider（智谱 Coding Plan）白盒断言，零真实外呼。

背景（2026-11-11 用户裁定接入 GLM Coding Plan）：Coding Plan 走专属网关
https://open.bigmodel.cn/api/coding/paas/v4（OpenAI Chat Completion 兼容），
Coding Plan Key 与模型标准 API Key 互不通用（401 时须提示这一点）。

本测试覆盖：
- 端点归一化 _resolve_endpoint()：空→官方默认；base（…/v4）补 /chat/completions；
  完整 chat/completions 原样；尾部斜杠容错；
- Key 缺失构造即抛 ValueError（禁止静默空呼）；
- 调用报文：messages + stream=False + Bearer 头；文本从 choices[0].message.content；
  usage 四字段（prompt/completion/cached/reasoning）回写；
- thinking="off"/"on" 下发智谱 thinking 字段，None 不碰 payload；
- HTTP 401 报错文案含「Coding Plan Key 与标准 API Key 互不通用」提示，
  且错误路径不得再抛 AttributeError（ getattr 猜类型教训，2026-11-10）；
- 工厂分发：llm_provider="GLM" 时 _provider_from_cfg 与 get_provider 均建 GLMProvider；
- 计费配置映射：用户自备 provider="GLM" 时 key/model/api_url 落到 glm_* 键；
- 默认超时 300s（2026-11-12 实弹：图文长回答撞 120s 误报超时回落系统 Key）；
- 回落链报错显首跳原因（自备失败→系统也失败时文案必须同时含两段）；
- 课文追问讲解 scene 默认关思考（入单漏追加回归钉）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

import llm_provider_factory as F


class _Resp:
    """伪造 requests.Response（GLM 为非流式，只需 json()）。"""

    def __init__(self, payload, status_code=200, ok=True):
        self._payload = payload
        self.status_code = status_code
        self.ok = ok
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class _HttpErrorResp(_Resp):
    def __init__(self, status_code):
        super().__init__({}, status_code=status_code, ok=False)


class GlmResolveEndpointTest(unittest.TestCase):
    def test_01_empty_falls_back_to_official_coding_base(self):
        url = F.GLMProvider._resolve_endpoint("")
        self.assertEqual(url, "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions")

    def test_02_v4_base_appends_chat_completions(self):
        url = F.GLMProvider._resolve_endpoint("https://open.bigmodel.cn/api/coding/paas/v4")
        self.assertEqual(url, "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions")

    def test_03_full_endpoint_unchanged(self):
        full = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
        self.assertEqual(F.GLMProvider._resolve_endpoint(full + "/"), full)

    def test_04_generic_openai_base_also_appends(self):
        # 用户填标准 API 网关（非 coding 专属）也应能拼出合法端点
        url = F.GLMProvider._resolve_endpoint("https://open.bigmodel.cn/api/paas/v4")
        self.assertEqual(url, "https://open.bigmodel.cn/api/paas/v4/chat/completions")


class GlmProviderInitTest(unittest.TestCase):
    def test_05_missing_key_raises(self):
        with self.assertRaises(ValueError):
            F.GLMProvider({"glm_api_key": "  "})

    def test_06_default_model(self):
        p = F.GLMProvider({"glm_api_key": "k", "glm_model": ""})
        self.assertEqual(p.model, "glm-4.7")


class GlmCallTest(unittest.TestCase):
    def setUp(self):
        self._orig_post = F.requests.post
        self.captured = {}

    def tearDown(self):
        F.requests.post = self._orig_post

    def _fake_post(self, resp):
        def fake_post(url, headers=None, json=None, timeout=None, stream=False):
            self.captured.update(url=url, headers=headers, payload=json,
                                 timeout=timeout, stream=stream)
            return resp
        F.requests.post = fake_post

    def test_10_success_payload_and_usage(self):
        self._fake_post(_Resp({
            "choices": [{"message": {"content": " 好 "}}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 3,
                      "prompt_tokens_details": {"cached_tokens": 5},
                      "completion_tokens_details": {"reasoning_tokens": 0}},
        }))
        p = F.GLMProvider({"glm_api_key": "sk-glm", "glm_model": "glm-4.6"})
        usage = {}
        out = p.call("回复一个字：好", usage_out=usage)
        self.assertEqual(out, "好")
        self.assertEqual(self.captured["url"],
                         "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions")
        self.assertEqual(self.captured["headers"]["Authorization"], "Bearer sk-glm")
        self.assertEqual(self.captured["payload"]["stream"], False)
        self.assertNotIn("prompt", self.captured["payload"])  # OpenAI 兼容 messages 报文
        self.assertEqual(usage, {"prompt_tokens": 17, "completion_tokens": 3,
                                 "cached_tokens": 5, "reasoning_tokens": 0})

    def test_11_chinese_content_not_mojibake(self):
        # 内容级断言（乱码坑口径）：非空≠正确，必须原样还原中文
        self._fake_post(_Resp({"choices": [{"message": {"content": "光合作用：光→化学能"}}],
                               "usage": {}}))
        p = F.GLMProvider({"glm_api_key": "k"})
        out = p.call("介绍光合作用")
        self.assertEqual(out, "光合作用：光→化学能")
        self.assertNotIn("Ã", out)
        self.assertNotIn("\ufffd", out)

    def test_12_thinking_field_dispatch(self):
        self._fake_post(_Resp({"choices": [{"message": {"content": "ok"}}]}))
        p = F.GLMProvider({"glm_api_key": "k"})
        p.call("x", thinking="off")
        self.assertEqual(self.captured["payload"]["thinking"], {"type": "disabled"})
        p.call("x", thinking="on")
        self.assertEqual(self.captured["payload"]["thinking"], {"type": "enabled"})
        p.call("x")
        self.assertNotIn("thinking", self.captured["payload"])

    def test_13_http_401_message_guides_key_type(self):
        self._fake_post(_HttpErrorResp(401))
        p = F.GLMProvider({"glm_api_key": "bad"})
        with self.assertRaises(Exception) as cm:
            p.call("x")
        msg = str(cm.exception)
        self.assertIn("GLM API调用失败: HTTP 401", msg)
        self.assertIn("互不通用", msg)
        # 旧坑回归钉：错误路径不得抛 AttributeError（getattr 猜类型写法）
        self.assertNotIn("AttributeError", msg)

    def test_14_timeout_and_conn_error_messages(self):
        def boom(url, headers=None, json=None, timeout=None, stream=False):
            raise requests.exceptions.Timeout("read timeout")
        F.requests.post = boom
        p = F.GLMProvider({"glm_api_key": "k"})
        with self.assertRaises(Exception) as cm:
            p.call("x")
        self.assertIn("GLM请求超时", str(cm.exception))

    def test_15_default_timeout_300_explicit_override(self):
        # 2026-11-12 实弹回归钉：默认 300s（同 Ollama 二修口径），显式 timeout 仍可覆盖
        self._fake_post(_Resp({"choices": [{"message": {"content": "ok"}}]}))
        p = F.GLMProvider({"glm_api_key": "k"})
        p.call("x")
        self.assertEqual(self.captured["timeout"], 300)
        p.call("x", timeout=30)
        self.assertEqual(self.captured["timeout"], 30)


class GlmDispatchTest(unittest.TestCase):
    def test_20_provider_from_cfg_glm(self):
        prov = F.LLMProviderFactory._provider_from_cfg(
            {"llm_provider": "GLM", "glm_api_key": "k", "glm_model": "glm-4.6"}, None)
        self.assertIsInstance(prov, F.GLMProvider)
        self.assertEqual(prov.model, "glm-4.6")

    def test_21_unknown_provider_still_rejected(self):
        with self.assertRaises(ValueError):
            F.LLMProviderFactory._provider_from_cfg({"llm_provider": "GPT"}, None)


class GlmBillingConfigTest(unittest.TestCase):
    def test_30_user_own_key_maps_to_glm_keys(self):
        # 计费链 effective_llm_config：自备 GLM 时 key/model/api_url 必须落 glm_*，
        # 不得污染 deepseek_*（防回落链拿错 Key，2026-11-10 协议错配同族防线）
        import credits_service as C
        orig_own = C.get_user_llm_config
        orig_sys = C.system_llm_overrides
        try:
            C.system_llm_overrides = lambda: {}
            C.get_user_llm_config = lambda uid: {
                "llm_provider": "GLM", "api_key": "sk-glm",
                "model": "glm-4.7", "api_url": "https://open.bigmodel.cn/api/coding/paas/v4"}
            cfg = C.effective_llm_config("u_glm_test")
        finally:
            C.get_user_llm_config = orig_own
            C.system_llm_overrides = orig_sys
        self.assertEqual(cfg["llm_provider"], "GLM")
        self.assertEqual(cfg["glm_api_key"], "sk-glm")
        self.assertEqual(cfg["glm_model"], "glm-4.7")
        self.assertEqual(cfg["glm_api_url"], "https://open.bigmodel.cn/api/coding/paas/v4")
        self.assertNotEqual(cfg.get("deepseek_api_key"), "sk-glm")


class FallbackFirstHopReasonTest(unittest.TestCase):
    """回落链报错显首跳（2026-11-12 用户实弹铁证：GLM 超时→系统 DeepSeek 530，
    界面只报「DeepSeek 失败」让用户误以为在用智谱）。零真实外呼。"""

    class _Own:
        supports_vision = False

        def call(self, *a, **k):
            raise Exception("GLM请求超时: 请检查网络连接")

    class _SysFail:
        supports_vision = False
        model = "sys"

        def call(self, *a, **k):
            raise Exception("DeepSeek API调用失败: HTTP 530")

    class _SysOk:
        supports_vision = False
        model = "sys"

        def call(self, *a, **k):
            return "系统答案"

    def setUp(self):
        import credits_service as C
        self.C = C
        self.orig = (C.get_user_llm_config, C.effective_llm_config, C.precheck,
                     C.set_last_billing, C.charge_llm, F.LLMProviderFactory._provider_from_cfg)
        C.get_user_llm_config = lambda uid: {"llm_provider": "GLM"}
        C.effective_llm_config = lambda uid: ({"llm_provider": "GLM", "glm_api_key": "k"}
                                              if uid else {"llm_provider": "DeepSeek"})
        C.precheck = lambda uid: {"allowed": True, "balance": 9.9}
        C.set_last_billing = lambda b: None
        C.charge_llm = lambda *a, **k: {"credits": 0.1, "balance": 9.8}

    def tearDown(self):
        C = self.C
        (C.get_user_llm_config, C.effective_llm_config, C.precheck,
         C.set_last_billing, C.charge_llm, F.LLMProviderFactory._provider_from_cfg) = self.orig

    def _wire(self, sys_prov):
        own, sf, sok = type(self)._Own, type(self)._SysFail, type(self)._SysOk
        F.LLMProviderFactory._provider_from_cfg = staticmethod(
            lambda cfg, logger: own() if cfg.get("llm_provider") == "GLM" else sys_prov())

    def test_40_both_fail_message_has_first_hop(self):
        self._wire(type(self)._SysFail)
        with self.assertRaises(Exception) as cm:
            F.llm_factory._call_billed("u_x", "prompt", "", "课文追问讲解")
        msg = str(cm.exception)
        self.assertIn("GLM请求超时", msg)   # 首跳真凶必须在文案里
        self.assertIn("HTTP 530", msg)      # 末跳原因不丢
        self.assertIn("回落", msg)

    def test_41_system_success_returns_normally(self):
        # 自备失败但系统成功：正常返回，不得拼前缀异常
        self._wire(type(self)._SysOk)
        out = F.llm_factory._call_billed("u_x", "prompt", "", "课文追问讲解")
        self.assertEqual(out, "系统答案")

    def test_42_followup_scene_thinking_off(self):
        # 追问讲解漏入白名单回归钉：默认关思考，不再走长思考撞超时
        self.assertEqual(F._resolve_thinking("课文追问讲解", None), "off")


if __name__ == "__main__":
    unittest.main(verbosity=2)
