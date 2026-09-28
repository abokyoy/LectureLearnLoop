"""P2 页面迁移 pytest 冒烟：路由可达 + fragments 鉴权/渲染 + 桥端点形状。

运行：pytest tests/test_p2_pages.py -v（服务需已在 6001 运行）。
"""
from __future__ import annotations

import json
import uuid

import pytest
import requests

BASE_URL = "http://127.0.0.1:6001"


def register_and_token(username: str) -> str:
    r = requests.post(BASE_URL + "/api/auth/register",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["token"]


PAGE_ROUTES = ["/", "/online_course", "/knowledge_base",
               "/settings", "/llm_logs", "/practice", "/practice_simple",
               "/login", "/register", "/logout"]

FRAGMENT_IDS = ["dashboard", "online_course_notes",
                "practice_knowledge", "practice_errors", "memory_knowledge",
                "memory_errors", "knowledge_base", "settings", "llm_logs"]


@pytest.mark.parametrize("path", PAGE_ROUTES)
def test_page_routes_ok(path):
    r = requests.get(BASE_URL + path, timeout=15)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    assert len(r.text) > (50 if path == "/logout" else 1000)


def test_learn_materials_redirects_to_online_course():
    """四期D组：资料学习已合并进网课笔记，老入口 302 重定向。"""
    r = requests.get(BASE_URL + "/learn_materials", timeout=15, allow_redirects=False)
    assert r.status_code == 302, f"status={r.status_code}"
    assert "/online_course" in r.headers.get("Location", "")
    followed = requests.get(BASE_URL + "/learn_materials", timeout=15)
    assert followed.status_code == 200 and len(followed.text) > 1000


def test_learn_from_materials_fragment_removed():
    """四期D组：片段白名单已移除 learn_from_materials → 404。"""
    token = register_and_token("p2t_" + uuid.uuid4().hex[:6])
    r = requests.get(BASE_URL + "/fragments/learn_from_materials", timeout=15,
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_fragments_require_auth():
    r = requests.get(BASE_URL + "/fragments/settings", timeout=10)
    assert r.status_code == 401


@pytest.mark.parametrize("cid", FRAGMENT_IDS)
def test_fragment_renders_html(cid):
    token = register_and_token("p2t_" + uuid.uuid4().hex[:6])
    r = requests.get(BASE_URL + f"/fragments/{cid}", timeout=15,
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] and isinstance(body["data"], str) and len(body["data"]) > 10


def test_practice_materials_embeds_as_iframe_fragment():
    """产品反馈修复：脑图练习不再整页跳转冲掉左菜单，
    /fragments/practice_materials 返回 iframe 片段（嵌入 SPA 壳），
    /practice 整页仍可用（作为 iframe 的 src）。"""
    token = register_and_token("p2t_" + uuid.uuid4().hex[:6])
    r = requests.get(BASE_URL + "/fragments/practice_materials", timeout=10,
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] and "iframe" in body["data"] and "/practice" in body["data"]
    full = requests.get(BASE_URL + "/practice", timeout=15)
    assert full.status_code == 200 and "</html>" in full.text


def test_shell_contains_bridge_and_spa_markers():
    r = requests.get(BASE_URL + "/", timeout=15)
    assert "/static/js/api.js" in r.text
    assert "updateContentArea" in r.text and "content-area" in r.text
