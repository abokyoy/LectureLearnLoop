# -*- coding: utf-8 -*-
"""OllamaProvider 双协议兼容（OpenAI 兼容端点 / 原生 /api/generate）白盒断言，零真实外呼。

背景（2026-11-10 知识点提取失败排查）：用户自备 Key 场景下 provider="Ollama"，
api_url 填的是 OpenAI 兼容网关（如 https://xxx.trycloudflare.com/v1，要求
Authorization: Bearer + /chat/completions 报文），旧 OllamaProvider 只会按原生
{"model","prompt","stream"} 打完整 URL（当作 /api/generate 接口本身），也不会带
Key，导致网关侧 404/401，最终自动回落系统 DeepSeek Key。

本测试覆盖：
- 端点识别 _resolve_endpoint()：/v1、/v1/、/chat/completions → OpenAI 兼容；
  裸主机名、/api/generate → 原生；
- OpenAI 兼容模式：请求打到 <base>/chat/completions，messages 报文，带
  Authorization: Bearer <key>，响应从 choices[0].message.content 取文本，
  usage 从 data["usage"] 取 prompt_tokens/completion_tokens；
- 原生模式：报文不变 {"model","prompt","stream":False}，响应从 data["response"]
  取文本（行为不回归）；
- HTTP 错误路径（404/401）不得因状态码提取写法再抛新异常（旧写法
  getattr(e,'response',{}).get(...) 对 requests.Response 对象会 AttributeError）。
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
    """伪造 requests.Response（成功路径）；_sse 非空时支持 iter_lines 流式读取。
    镜像真实 requests 行为：响应 Content-Type 无 charset 时 encoding 默认 ISO-8859-1，
    iter_lines(decode_unicode=True) 按该 encoding 解码（2026-11-10 乱码坑的根因载体）。"""

    def __init__(self, payload, status_code=200, ok=True, sse=None):
        self._payload = payload
        self.status_code = status_code
        self.ok = ok
        self.text = ""
        self._sse = sse or []
        self.encoding = "ISO-8859-1"

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=True):
        lines = []
        for line in self._sse:
            if decode_unicode:
                # 真实 requests：按响应 encoding 解码 bytes（拼不出 latin-1 的字节→\ufffd）
                lines.append(line.encode("utf-8").decode(self.encoding, "replace"))
            else:
                lines.append(line.encode("utf-8"))
        return iter(lines)

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def _sse_chunks(content, usage=None):
    """拼 OpenAI SSE 分片：若干 delta.content + 可选末尾 usage 帧 + [DONE]。
    ensure_ascii=False：中文以真实 UTF-8 字节上线，与真机网关行为一致。"""
    import json as _j
    out = []
    for piece in content:
        out.append('data: ' + _j.dumps(
            {"choices": [{"index": 0, "delta": {"content": piece}}]},
            ensure_ascii=False))
    tail = {"choices": []}
    if usage is not None:
        tail["usage"] = usage
    out.append('data: ' + _j.dumps(tail))
    out.append("data: [DONE]")
    return out


class _HttpErrorResp(_Resp):
    """伪造 4xx/5xx 响应：raise_for_status() 抛 requests.HTTPError（带 .response）。"""

    def __init__(self, status_code):
        super().__init__({}, status_code=status_code, ok=False)


class ResolveEndpointTest(unittest.TestCase):
    def test_01_openai_v1_base(self):
        mode, url = F.OllamaProvider._resolve_endpoint("https://x.trycloudflare.com/v1")
        self.assertEqual(mode, "openai")
        self.assertEqual(url, "https://x.trycloudflare.com/v1/chat/completions")

    def test_02_openai_v1_trailing_slash(self):
        mode, url = F.OllamaProvider._resolve_endpoint("https://x.example.com/v1/")
        self.assertEqual(mode, "openai")
        self.assertEqual(url, "https://x.example.com/v1/chat/completions")

    def test_03_openai_chat_completions_given(self):
        mode, url = F.OllamaProvider._resolve_endpoint("https://x.example.com/v1/chat/completions")
        self.assertEqual(mode, "openai")
        self.assertEqual(url, "https://x.example.com/v1/chat/completions")

    def test_04_native_bare_host(self):
        mode, url = F.OllamaProvider._resolve_endpoint("http://localhost:11434")
        self.assertEqual(mode, "native")
        self.assertEqual(url, "http://localhost:11434/api/generate")

    def test_05_native_explicit_generate(self):
        mode, url = F.OllamaProvider._resolve_endpoint("http://localhost:11434/api/generate")
        self.assertEqual(mode, "native")
        self.assertEqual(url, "http://localhost:11434/api/generate")


class OllamaCallTest(unittest.TestCase):
    def setUp(self):
        self._orig_post = F.requests.post
        self.captured = {}

    def tearDown(self):
        F.requests.post = self._orig_post

    def _fake_post_ok(self, payload_resp, sse=None):
        def fake_post(url, headers=None, json=None, timeout=None, stream=False):
            self.captured["url"] = url
            self.captured["headers"] = headers
            self.captured["payload"] = json
            self.captured["timeout"] = timeout
            self.captured["stream"] = stream
            return _Resp(payload_resp, sse=sse)
        F.requests.post = fake_post

    def test_10_openai_mode_streams_messages_and_auth(self):
        # 2026-11-10 二修根因：非流式请求在 trycloudflare 边缘节点 ~60s 空闲即被
        # 掉线（RemoteDisconnected），OpenAI 兼容模式必须流式，逐片累计文本+末尾 usage 帧
        self._fake_post_ok({}, sse=_sse_chunks(["hel", "lo"],
                                               {"prompt_tokens": 3, "completion_tokens": 7}))
        p = F.OllamaProvider({"ollama_api_url": "https://x.example.com/v1",
                              "ollama_model": "qwen36", "ollama_api_key": "sk-abc"})
        usage = {}
        out = p.call("提问内容", usage_out=usage)
        self.assertEqual(out, "hello")
        self.assertEqual(self.captured["url"], "https://x.example.com/v1/chat/completions")
        self.assertIn("messages", self.captured["payload"])
        self.assertNotIn("prompt", self.captured["payload"])
        self.assertEqual(self.captured["payload"]["stream"], True)
        self.assertEqual(self.captured["stream"], True)
        self.assertEqual(self.captured["headers"].get("Authorization"), "Bearer sk-abc")
        self.assertEqual(usage["prompt_tokens"], 3)
        self.assertEqual(usage["completion_tokens"], 7)

    def test_10b_openai_stream_chinese_utf8_not_mojibake(self):
        # 乱码实弹复现：网关 SSE 响应 Content-Type 无 charset → requests 默认按
        # ISO-8859-1 解码 UTF-8 字节 → "脏读"变"è„å»"。修复后必须原样还原中文。
        self._fake_post_ok({}, sse=_sse_chunks(["脏读", "：一个事务", "读取…"]))
        p = F.OllamaProvider({"ollama_api_url": "https://x.example.com/v1",
                              "ollama_model": "qwen36"})
        out = p.call("提取知识点")
        self.assertEqual(out, "脏读：一个事务读取…")
        self.assertNotIn("Ã", out or "")
        self.assertNotIn("\ufffd", out or "")

    def test_11_native_mode_unchanged(self):
        self._fake_post_ok({"response": "原生回复", "prompt_eval_count": 5, "eval_count": 9})
        p = F.OllamaProvider({"ollama_api_url": "http://localhost:11434/api/generate",
                              "ollama_model": "deepseek-r1:1.5b"})
        usage = {}
        out = p.call("提问内容", usage_out=usage)
        self.assertEqual(out, "原生回复")
        self.assertEqual(self.captured["url"], "http://localhost:11434/api/generate")
        self.assertEqual(self.captured["payload"],
                         {"model": "deepseek-r1:1.5b", "prompt": "提问内容", "stream": False})
        self.assertEqual(usage["prompt_tokens"], 5)
        self.assertEqual(usage["completion_tokens"], 9)

    def test_12_native_bare_host_appends_generate(self):
        self._fake_post_ok({"response": "ok"})
        p = F.OllamaProvider({"ollama_api_url": "http://localhost:11434", "ollama_model": "m"})
        p.call("q")
        self.assertEqual(self.captured["url"], "http://localhost:11434/api/generate")
        # 原生模式保持非流式（本机快，不回归）
        self.assertEqual(self.captured["stream"], False)

    def test_13_openai_mode_no_key_no_auth_header(self):
        self._fake_post_ok({}, sse=_sse_chunks(["ok"]))
        p = F.OllamaProvider({"ollama_api_url": "https://x.example.com/v1", "ollama_model": "m"})
        p.call("q")
        self.assertNotIn("Authorization", self.captured["headers"] or {})

    def test_14_default_timeout_is_300s(self):
        """2026-11-10 二修：远程慢模型（云端隧道 qwen 量化版）4.5k 字提取 prompt
        超 120s 未吐首字节被截，回落 DeepSeek 又遇 402。默认超时放宽到 300s。"""
        self._fake_post_ok({}, sse=_sse_chunks(["ok"]))
        p = F.OllamaProvider({"ollama_api_url": "https://x.example.com/v1", "ollama_model": "m"})
        p.call("q")
        self.assertEqual(self.captured["timeout"], 300)

    def test_15_explicit_timeout_passthrough(self):
        self._fake_post_ok({}, sse=_sse_chunks(["ok"]))
        p = F.OllamaProvider({"ollama_api_url": "https://x.example.com/v1", "ollama_model": "m"})
        p.call("q", timeout=45)
        self.assertEqual(self.captured["timeout"], 45)

    def test_16_openai_stream_without_usage_frame_yields_text(self):
        # 网关不发 usage 帧时：文本正常累计，usage 归 0，不得报错
        self._fake_post_ok({}, sse=_sse_chunks(["a", "b", "c"]))
        p = F.OllamaProvider({"ollama_api_url": "https://x.example.com/v1", "ollama_model": "m"})
        usage = {}
        out = p.call("q", usage_out=usage)
        self.assertEqual(out, "abc")
        self.assertEqual(usage["prompt_tokens"], 0)

    def test_20_http_error_does_not_swallow_real_exception(self):
        """4xx/5xx 必须抛出带状态码的 Ollama 调用失败异常，不得再因
        getattr(...).get(...) 写法对 Response 对象取 .get 抛 AttributeError 而掩盖真因。"""
        def fake_post(url, headers=None, json=None, timeout=None, stream=False):
            return _HttpErrorResp(404)
        F.requests.post = fake_post
        p = F.OllamaProvider({"ollama_api_url": "https://x.example.com/v1",
                              "ollama_model": "m", "ollama_api_key": "sk-abc"})
        with self.assertRaises(Exception) as ctx:
            p.call("q")
        msg = str(ctx.exception)
        self.assertNotIn("AttributeError", msg)
        self.assertIn("404", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
