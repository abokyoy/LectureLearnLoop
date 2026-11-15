# -*- coding: utf-8 -*-
"""目标导向学习页面注册断言（Task 8：/learn_goals 路由 + fragment + 侧边栏 flyout）。

运行方式（server/ 目录）：python -m pytest tests/test_course_page_reg.py -v
"""
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

U = "cgr" + uuid.uuid4().hex[:8]
PW = "pass1234"


@pytest.fixture(scope="module")
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def au(client):
    r = client.post("/api/auth/register", json={"username": U, "password": PW})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def _h(token):
    return {"Authorization": "Bearer " + token}


def test_page_route_renders_skeleton(client):
    """GET /learn_goals：200 且骨架 DOM id 全在（cgGoalList/cgWorkbench/cgNewGoalBtn）。"""
    r = client.get("/learn_goals")
    assert r.status_code == 200, r.status_code
    html = r.get_data(as_text=True)
    for dom_id in ("cgGoalList", "cgNewGoalBtn", "cgWorkbench"):
        assert dom_id in html, dom_id


def test_page_route_tab_and_request_fns(client):
    html = client.get("/learn_goals").get_data(as_text=True)
    for token in ("cgTabMap", "cgTabOutline", "cgTabHistory", "cgGet", "cgPost"):
        assert token in html, token


def test_current_page_marker(client):
    html = client.get("/learn_goals").get_data(as_text=True)
    assert 'window.current_page = "learn_goals"' in html


def test_fragment_endpoint(client, au):
    r = client.get("/fragments/learn_goals", headers=_h(au["token"]))
    body = r.get_json()
    assert body["success"] is True, body
    assert "cgWorkbench" in body["data"]


def test_sidebar_flyout(client):
    """SPA 壳侧边栏：'学'父项直达 learn_goals + 两项二级菜单文案。"""
    html = client.get("/").get_data(as_text=True)
    assert 'data-cid="learn_goals"' in html
    assert "目标导向学习" in html and "笔记学习" in html
    # 笔记学习入口保留
    assert "handleMenuClick('online_course_notes')" in html


def test_online_course_unchanged(client):
    """/online_course 现有页面不受影响。"""
    r = client.get("/online_course")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "cgWorkbench" not in html  # 未污染
