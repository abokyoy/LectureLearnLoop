# -*- coding: utf-8 -*-
"""u7 回归：/api/practice/new 响应契约测试（打桩 _llm_call，不调真实 LLM、不消耗积分）。

背景（2026-10-02 白页修复）：base.html generateNewPractice 判定
`result.success ? loadNewPracticeData(result.data) : alert(...)`，其中 result 是
api.js req() unwrap 后的内层 data。旧实现成功分支内层无 success 字段 → 前端永远
走失败分支弹“生成新练习失败: 未知错误”，练习面板空白（白页）。本测试锁定契约：
- 成功：内层 {success: true, data: {id, question, questions, selectedText, ...}}
- 积分不足：内层 {success: false, error: 文案, credits_insufficient: true}
- 未捕获异常：内层 {success: false, error: 非空文案}（str(e) 为空时兜底）

运行方式（server/ 目录）：python -m pytest tests/test_practice_new_contract.py -v
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "pn_a_" + uuid.uuid4().hex[:6]


@pytest.fixture(scope="module")
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/api/auth/register", json={"username": U, "password": "pass1234"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["token"]


def _h(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture()
def bridge_mod():
    import routes_bridge
    return routes_bridge


def test_success_shape_has_inner_success_and_data(client, token, bridge_mod, monkeypatch):
    """LLM 成功：内层必须 {success: true, data: {...}}，题目字段在 data 内。"""
    fake_q = "1. 选择题题目 A) x B) y\n2. 简答题"
    monkeypatch.setattr(bridge_mod, "_llm_call", lambda prompt, context="": fake_q)
    r = client.post("/api/practice/new", json={}, headers=_h(token))
    assert r.status_code == 200
    outer = r.get_json()
    assert outer["success"] is True
    inner = outer["data"]
    # 前端契约三要素：success 标志、data 载荷、载荷内题目字段
    assert inner.get("success") is True, f"内层缺 success 会触发前端未知错误白页: {inner}"
    payload = inner["data"]
    assert payload["id"].startswith("TECH-")
    assert payload["question"] == fake_q
    assert payload["questions"] == fake_q  # 兼容字段名
    assert payload["selectedText"]  # 默认内置学习内容非空
    # 评审修复（MINOR）：计费字段必须在内层顶层（api.js billingHook 只 pick 到 j.data 层），
    # 若未来重构误嵌套进 payload，前端余额提示会静默消失
    billing_keys = {"credit_note", "credits_deducted", "credit_balance"}
    assert not billing_keys & set(payload.keys()), f"计费字段不应嵌套在 data 内层: {set(payload.keys())}"


def test_llm_exception_falls_back_to_generated_questions(client, token, bridge_mod, monkeypatch):
    """LLM 抛任意异常：走 _gen_fallback，仍返回成功契约（不白页）。"""
    def boom(prompt, context=""):
        raise RuntimeError("网络抖动")
    monkeypatch.setattr(bridge_mod, "_llm_call", boom)
    r = client.post("/api/practice/new", json={}, headers=_h(token))
    inner = r.get_json()["data"]
    assert inner.get("success") is True
    assert inner["data"]["question"]  # 兜底题目非空


def test_insufficient_credits_shape(client, token, bridge_mod, monkeypatch):
    """积分不足：内层 {success: false, error: 充值文案, credits_insufficient: true}。"""
    import credits_service as cr

    def boom(prompt, context=""):
        raise cr.InsufficientCreditsError(0.0)
    monkeypatch.setattr(bridge_mod, "_llm_call", boom)
    r = client.post("/api/practice/new", json={}, headers=_h(token))
    inner = r.get_json()["data"]
    assert inner.get("success") is False
    assert "积分不足" in inner["error"]
    assert inner.get("credits_insufficient") is True


def test_outer_exception_error_message_never_empty(client, token, bridge_mod, monkeypatch):
    """外层兜底：异常 str(e) 为空串时，error 必须回填非空文案（前端不报“未知错误”空来源）。"""
    monkeypatch.setattr(bridge_mod, "_llm_call", lambda prompt, context="": "ok")
    import credits_service as cr
    monkeypatch.setattr(cr, "billing_for_response", lambda: (_ for _ in ()).throw(ValueError("")))
    r = client.post("/api/practice/new", json={}, headers=_h(token))
    inner = r.get_json()["data"]
    assert inner.get("success") is False
    assert inner["error"], "error 不得为空串，否则前端只显示“未知错误”无法定位"
