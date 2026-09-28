# -*- coding: utf-8 -*-
"""四期 A 组：登录免登录修正 + 用户设置端点验收测试（Flask test client）。

运行方式（server/ 目录）：python -m pytest tests/test_user_p4.py -v
覆盖：JWT 7 天 TTL、expires_in_days 下发、me 返回昵称/到期、昵称编辑、
修改密码（错误旧密码/短密码/成功后新旧密码验证）、鉴权防护、页面静态改造断言。
"""
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

UA = "p4user_a_" + uuid.uuid4().hex[:6]
UB = "p4user_b_" + uuid.uuid4().hex[:6]
PW = "pass1234"
PW2 = "newpass99"


@pytest.fixture(scope="module")
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _register(client, username):
    r = client.post("/api/auth/register", json={"username": username, "password": PW})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def _h(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture(scope="module")
def da(client):
    return _register(client, UA)


@pytest.fixture(scope="module")
def db_(client):
    return _register(client, UB)


class TestTokenTtl:
    def test_register_expires_in_days(self, da):
        # 注册响应下发免登录天数（前端 ll_remember TTL 依据）
        assert da.get("expires_in_days") == 7

    def test_jwt_exp_about_7_days(self, da):
        import base64
        import json as _json
        payload = da["token"].split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = _json.loads(base64.urlsafe_b64decode(payload))
        days = (claims["exp"] - time.time()) / 86400
        assert 6.5 <= days <= 7.5, f"JWT 实际有效期 {days:.2f} 天"

    def test_login_returns_days_and_display_name(self, client):
        r = client.post("/api/auth/login", json={"username": UA, "password": PW})
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["expires_in_days"] == 7
        assert "display_name" in d


class TestMeAndProfile:
    def test_me_fields(self, client, da):
        r = client.get("/api/auth/me", headers=_h(da["token"]))
        assert r.status_code == 200
        d = r.get_json()["data"]
        assert d["username"] == UA
        assert d["display_name"] == ""
        assert d["token_exp"] and d["token_exp"] > time.time()

    def test_update_nickname(self, client, da):
        r = client.post("/api/auth/profile", json={"display_name": "测试昵称甲"}, headers=_h(da["token"]))
        assert r.status_code == 200
        me = client.get("/api/auth/me", headers=_h(da["token"])).get_json()["data"]
        assert me["display_name"] == "测试昵称甲"

    def test_nickname_isolated_between_users(self, client, da, db_):
        me_b = client.get("/api/auth/me", headers=_h(db_["token"])).get_json()["data"]
        assert me_b["display_name"] == ""

    def test_nickname_truncated_32(self, client, da):
        long = "昵" * 50
        r = client.post("/api/auth/profile", json={"display_name": long}, headers=_h(da["token"]))
        assert r.status_code == 200
        assert len(r.get_json()["data"]["display_name"]) <= 32

    def test_profile_requires_auth(self, client):
        r = client.post("/api/auth/profile", json={"display_name": "x"})
        assert r.status_code == 401


class TestChangePassword:
    def test_wrong_old_password_401(self, client, da):
        r = client.post("/api/auth/password", json={"old_password": "wrongold", "new_password": PW2},
                        headers=_h(da["token"]))
        assert r.status_code == 401
        assert "旧密码" in r.get_json()["error"]

    def test_short_new_password_400(self, client, da):
        r = client.post("/api/auth/password", json={"old_password": PW, "new_password": "123"},
                        headers=_h(da["token"]))
        assert r.status_code == 400

    def test_change_then_relogin(self, client, da):
        r = client.post("/api/auth/password", json={"old_password": PW, "new_password": PW2},
                        headers=_h(da["token"]))
        assert r.status_code == 200 and r.get_json()["data"]["changed"]
        # 旧密码登录失败、新密码登录成功
        bad = client.post("/api/auth/login", json={"username": UA, "password": PW})
        assert bad.status_code == 401
        ok = client.post("/api/auth/login", json={"username": UA, "password": PW2})
        assert ok.status_code == 200
        # 改密后 me 仍可查（老 token 未失效属无状态 JWT 预期语义）
        me = client.get("/api/auth/me", headers=_h(da["token"])).get_json()
        assert me["success"]

    def test_password_requires_auth(self, client):
        r = client.post("/api/auth/password", json={"old_password": "a", "new_password": "bbbbbb"})
        assert r.status_code == 401


class TestPageStatic:
    """页面静态断言：免登录语义与用户设置入口已交付。"""

    @staticmethod
    def _tpl(name):
        p = Path(__file__).resolve().parents[1] / "templates" / name
        return p.read_text(encoding="utf-8")

    def test_login_page_semantics(self):
        html = self._tpl("login.html")
        assert "sessionStorage" in html
        assert "7 天内免登录" in html
        assert "setToken(j.token, !!rememberBox.checked)" in html
        assert "57 * 24 * 3600 * 1000" not in html

    def test_logout_clears_all(self):
        src = Path(__file__).resolve().parents[1] / "routes_pages.py"
        text = src.read_text(encoding="utf-8")
        assert "sessionStorage.removeItem('ll_token')" in text
        assert "localStorage.removeItem('ll_remember')" in text

    def test_api_js_dual_storage(self):
        src = Path(__file__).resolve().parents[1] / "static" / "js" / "api.js"
        text = src.read_text(encoding="utf-8")
        assert "llGetToken" in text and "sessionStorage.getItem('ll_token')" in text

    def test_user_settings_modal(self):
        html = self._tpl("components/user_settings.html")
        for key in ["us-nickname", "us-pw-old", "us-remember-days", "us-remember-apply",
                    "/api/auth/profile", "/api/auth/password", "openUserSettings"]:
            assert key in html, f"用户设置模态缺少 {key}"

    def test_sidebar_avatar_entry(self):
        html = self._tpl("components/sidebar.html")
        assert "user-avatar-btn" in html
        assert "柯基的主人" not in html and "Lv.5" not in html
        spa = self._tpl("spa_layout.html")
        assert 'include "components/user_settings.html"' in spa
        assert "llRefreshUserBadge" in spa
