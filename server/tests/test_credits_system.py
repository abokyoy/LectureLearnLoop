# -*- coding: utf-8 -*-
"""积分与充值系统黑盒断言测试（2026-09-28 积分功能，PostgreSQL 唯一后端）。

覆盖计划 crd-13 要求的全路径：
1. Token→积分换算（比例/最小 0.1/下限 1 防误配）
2. 登录每日赠送 + 自然日幂等（服务层二次调用不重复发）
3. /api/credits/balance 字段与充值文案下发
4. 卡密：后台生成 → 兑换 → 重复兑换拦截 → 作废拦截 → 并发 8 线程只成功一次
5. 管理员豁免：system_config 配 0 关闭赠送；admin/adjust 防护（负余额拒绝/用户不存在）
6. ASR：费率扣分 / 超 24h 自报封顶 / asr-charge 允许负余额（欠费）
7. require_admin：普通用户访问管理 API 403
8. 计费路由（factory，桩 provider，不触网）：
   usage 缺失按字符估算扣分 / 自备 Key 不扣分且记流水 / 余额不足预检拦截 / 管理员豁免流水

运行：
  python -m pytest tests/test_credits_system.py -q          # PG 不可达时整体 skip（非失败）
注意：系统已全面废除 SQLite，本测试仅跑 PostgreSQL；
测试在生产库中使用唯一前缀测试用户（crdt_*/cadmin_*），结束即时清理，不碰正式数据。
"""
from __future__ import annotations

import os
import sys
import threading
import uuid
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))

import config  # noqa: E402
from database import db_adapter  # noqa: E402


def _pg_available() -> bool:
    try:
        import psycopg2  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    try:
        import psycopg2 as pg
        cn = pg.connect(host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
                        password=config.PG_PASSWORD, dbname=config.PG_DATABASE,
                        connect_timeout=4)
        cn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


BACKENDS = ["postgres"]


@pytest.fixture(scope="module")
def app():
    from app import create_app
    _app = create_app()
    yield _app
    # 清理 PG 生产库中的测试痕迹
    _cleanup_pg_test_rows()


def _cleanup_pg_test_rows():
    """删除 PG 库中本次测试产生的用户/流水/卡密，并恢复被测试改动的共享业务参数。
    注意：psycopg2 中空参数 + SQL 内裸 % 会被当占位符报错，LIKE 的模式必须走参数绑定。"""
    if not _pg_available():
        return
    try:
        with db_adapter.get_connection() as conn:
            rows = conn.execute(
                "SELECT user_id FROM users WHERE username LIKE ? OR username LIKE ?",
                ('crdt%', 'cadmin%')).fetchall()
            ids = tuple(r[0] for r in rows)
            if ids:
                q = ','.join('?' * len(ids))
                conn.execute(f"DELETE FROM credit_transactions WHERE user_id IN ({q})", ids)
                conn.execute(f"DELETE FROM user_credits WHERE user_id IN ({q})", ids)
                conn.execute(f"DELETE FROM user_llm_config WHERE user_id IN ({q})", ids)
                conn.execute(f"DELETE FROM activation_codes WHERE created_by IN ({q})", ids)
                conn.execute(f"DELETE FROM users WHERE user_id IN ({q})", ids)
    except Exception:
        pass
    # 配置恢复独立于用户删除（互不影响，避免前者失败连带跳过）
    try:
        with db_adapter.get_connection() as conn:
            for k, v in (("credits_daily_bonus", "100"), ("credits_token_ratio", "4000"),
                         ("credits_asr_per_minute", "1")):
                conn.execute("UPDATE system_config SET value = ? WHERE key = ?", (v, k))
    except Exception:
        pass


def _new_user(client, username: str, password: str = "test123456"):
    client.post("/api/auth/register", json={"username": username, "password": password})
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    d = r.get_json()["data"]
    # 登录响应平铺字段：bonus_granted / bonus_credits（与 auth.login 实际结构对齐）
    bonus = {"granted": d.get("bonus_granted", False), "credits": d.get("bonus_credits", 0.0)}
    return d["token"], bonus


def _hdr(token: str):
    return {"Authorization": f"Bearer {token}"}


def _fetch_one(sql, params=()):
    with db_adapter.get_connection() as conn:
        return conn.execute(sql, params).fetchone()


def _fetch_all(sql, params=()):
    with db_adapter.get_connection() as conn:
        return conn.execute(sql, params).fetchall()


@pytest.mark.skipif(not _pg_available(), reason="PostgreSQL 不可达")
@pytest.mark.parametrize("backend", BACKENDS)
class TestCreditsSystem:
    """断言测试在 PostgreSQL 上执行。"""

    @pytest.fixture(autouse=True)
    def _set_backend(self, backend):
        config.DB_BACKEND = backend
        yield

    # ---------------------------------------------------------------- 1 换算
    def test_token_conversion(self, app):
        import credits_service as cr
        with app.app_context():
            cr.set_config_value("credits_token_ratio", "4000")
            assert cr.token_credit_ratio() == 4000
            assert cr.tokens_to_credits(0) == 0.0
            assert cr.tokens_to_credits(4000) == 1.0
            assert cr.tokens_to_credits(200) == 0.1      # 有消耗最小 0.1
            assert cr.tokens_to_credits(10000) == 2.5
            cr.set_config_value("credits_token_ratio", "0")
            assert cr.token_credit_ratio() == 1          # 下限 1，防除零
            cr.set_config_value("credits_token_ratio", "4000")

    # ---------------------------------------------------------------- 2 登录赠送
    def test_daily_bonus(self, app):
        import credits_service as cr
        with app.app_context():
            cr.set_config_value("credits_daily_bonus", "100")
            client = app.test_client()
            uname = "crdt_" + uuid.uuid4().hex[:8]
            token, bonus = _new_user(client, uname)
            assert bonus.get("granted") is True and bonus.get("credits") == 100.0
            uid = _fetch_one("SELECT user_id FROM users WHERE username=?", (uname,))[0]
            bal = cr.get_balance(uid)["balance"]
            assert bal == 100.0
            # 自然日幂等：再次调用不重复发
            again = cr.grant_daily_bonus(uid)
            assert again["granted"] is False
            assert cr.get_balance(uid)["balance"] == 100.0
            # 登录不依赖赠送：配 0 关闭
            cr.set_config_value("credits_daily_bonus", "0")
            _, bonus0 = _new_user(client, "crdt0_" + uuid.uuid4().hex[:8])
            assert bonus0.get("granted") is False

    # ---------------------------------------------------------------- 3 余额 API
    def test_balance_api(self, app):
        with app.app_context():
            client = app.test_client()
            token, _ = _new_user(client, "crdtb_" + uuid.uuid4().hex[:8])
            r = client.get("/api/credits/balance", headers=_hdr(token))
            assert r.status_code == 200
            d = r.get_json()["data"]
            for k in ("balance", "total_recharged", "total_granted", "total_used",
                      "recharge_text", "credits_per_yuan", "is_admin"):
                assert k in d, k
            assert d["is_admin"] is False
            # 未登录 → 401/403
            assert client.get("/api/credits/balance").status_code in (401, 403)

    # ---------------------------------------------------------------- 4 卡密全链路
    def test_codes_flow(self, app):
        import credits_service as cr
        with app.app_context():
            client = app.test_client()
            a_uname = "cadmin_" + uuid.uuid4().hex[:8]
            atoken, _ = _new_user(client, a_uname)
            aid = _fetch_one("SELECT user_id FROM users WHERE username=?", (a_uname,))[0]
            with db_adapter.get_connection(str(config.DB_PATH)) as conn:
                conn.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (aid,))
            ah = _hdr(atoken)

            g = client.post("/api/admin/codes/generate", headers=ah,
                            json={"credits": 500, "count": 3})
            assert g.status_code == 200, g.text
            codes = [c for c in g.get_json()["data"]["codes"]]
            assert len(codes) == 3

            u_uname = "crdru_" + uuid.uuid4().hex[:8]
            utoken, _ = _new_user(client, u_uname)
            uid = _fetch_one("SELECT user_id FROM users WHERE username=?", (u_uname,))[0]
            uh = _hdr(utoken)

            before = cr.get_balance(uid)["balance"]
            r1 = client.post("/api/credits/redeem", headers=uh, json={"code": codes[0].lower()})
            assert r1.status_code == 200, r1.text
            bal_after = r1.get_json()["data"]["balance"]
            assert abs(bal_after - (before + 500.0)) < 0.01  # 相对断言，不受日赠时序影响

            r2 = client.post("/api/credits/redeem", headers=uh, json={"code": codes[0]})
            assert r2.status_code == 400
            assert "已被使用" in r2.get_json()["error"]

            r3 = client.post("/api/credits/redeem", headers=uh, json={"code": "LL-DEADBEEF-DEADBEEF"})
            assert r3.status_code == 400
            assert "无效" in r3.get_json()["error"]

            v = client.post("/api/admin/codes/void", headers=ah, json={"code": codes[1]})
            assert v.status_code == 200
            r4 = client.post("/api/credits/redeem", headers=uh, json={"code": codes[1]})
            assert r4.status_code == 400
            assert "作废" in r4.get_json()["error"]

            # 流水：兑换记录 type=recharge，note 只含掩码后 4 位
            txs = client.get("/api/credits/transactions", headers=uh).get_json()["data"]
            rc = [t for t in txs if t["type"] == "recharge"]
            assert rc and rc[0]["credits_delta"] == 500.0
            assert codes[0][-4:] in rc[0]["note"] and codes[0] not in rc[0]["note"]

            # 并发防重：8 线程同时兑同一码，只成功一次
            code9 = codes[2]
            u2 = "crdrc_" + uuid.uuid4().hex[:8]
            results = []
            lock = threading.Lock()

            def worker():
                t, _ = _new_user(client, u2)  # 已存在则走 login，同一账号
                rr = client.post("/api/credits/redeem", headers=_hdr(t), json={"code": code9})
                with lock:
                    results.append(rr.status_code == 200)

            ths = [threading.Thread(target=worker) for _ in range(8)]
            [th.start() for th in ths]
            [th.join() for th in ths]
            assert sum(1 for x in results if x) == 1, results
            # 净入账只加一次：最终余额 = 之前余额 + 500
            assert cr.get_balance(_fetch_one("SELECT user_id FROM users WHERE username=?", (u2,))[0])["balance"] == 500.0

    # ---------------------------------------------------------------- 5 管理员调整
    def test_admin_adjust(self, app):
        import credits_service as cr
        with app.app_context():
            client = app.test_client()
            a_uname = "cadmin2_" + uuid.uuid4().hex[:8]
            atoken, _ = _new_user(client, a_uname)
            aid = _fetch_one("SELECT user_id FROM users WHERE username=?", (a_uname,))[0]
            with db_adapter.get_connection(str(config.DB_PATH)) as conn:
                conn.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (aid,))
            ah = _hdr(atoken)
            u_uname = "crdad_" + uuid.uuid4().hex[:8]
            utoken, _ = _new_user(client, u_uname)
            uid = _fetch_one("SELECT user_id FROM users WHERE username=?", (u_uname,))[0]

            ok = client.post("/api/admin/adjust", headers=ah, json={"user_id": uid, "delta": 50, "note": "补偿"})
            assert ok.status_code == 200 and ok.get_json()["data"]["balance"] >= 50.0
            bad = client.post("/api/admin/adjust", headers=ah,
                              json={"user_id": uid, "delta": -999999, "note": "x"})
            assert bad.status_code in (400, 200)
            assert bad.get_json()["success"] is False
            ghost = client.post("/api/admin/adjust", headers=ah,
                                json={"user_id": "no_such_user_zzz", "delta": 1})
            assert ghost.get_json()["success"] is False and "不存在" in ghost.get_json()["error"]
            # 审计流水
            txs = client.get(f"/api/admin/transactions/{uid}", headers=ah).get_json()["data"]
            assert any(t["type"] == "admin_adjust" for t in txs)

    # ---------------------------------------------------------------- 6 ASR
    def test_asr_charge(self, app):
        import credits_service as cr
        with app.app_context():
            cr.set_config_value("credits_asr_per_minute", "1")
            cr.set_config_value("credits_daily_bonus", "0")
            client = app.test_client()
            uname = "crdtasr_" + uuid.uuid4().hex[:8]
            token, _ = _new_user(client, uname)
            uid = _fetch_one("SELECT user_id FROM users WHERE username=?", (uname,))[0]
            cr.admin_adjust(uid, 10, "seed", "test")

            r = client.post("/api/credits/asr-charge", headers=_hdr(token), json={"seconds": 125})
            assert r.status_code == 200
            d = r.get_json()["data"]
            assert d["minutes"] == 3 and d["credits"] == 3.0

            # 超 24h 自报封顶
            big = cr.charge_asr(uid, 99999999)
            assert big["credits"] <= 1440.0

            # 允许负余额（录音已发生，欠费后补）
            small = "crdlow_" + uuid.uuid4().hex[:8]
            stoken, _ = _new_user(client, small)
            sid = _fetch_one("SELECT user_id FROM users WHERE username=?", (small,))[0]
            cr.admin_adjust(sid, 1, "seed", "test")
            r2 = client.post("/api/credits/asr-charge", headers=_hdr(stoken), json={"seconds": 300})
            assert r2.status_code == 200 and r2.get_json()["data"]["credits"] == 5.0
            assert cr.get_balance(sid)["balance"] == -4.0
            # 负余额 → LLM 预检拦截
            assert cr.precheck(sid)["allowed"] is False
            # 非法 seconds
            bad = client.post("/api/credits/asr-charge", headers=_hdr(stoken), json={"seconds": "abc"})
            assert bad.status_code == 400

    # ---------------------------------------------------------------- 7 require_admin
    def test_admin_guard(self, app):
        with app.app_context():
            client = app.test_client()
            token, _ = _new_user(client, "crdtadm_" + uuid.uuid4().hex[:8])
            for path in ("/api/admin/credits/config", "/api/admin/llm-config", "/api/admin/users"):
                r = client.get(path, headers=_hdr(token))
                assert r.status_code in (403, 401), (path, r.status_code)
            r = client.post("/api/admin/codes/generate", headers=_hdr(token), json={"credits": 1, "count": 1})
            assert r.status_code in (403, 401)
            # 管理员自身可访问
            a_uname = "cadmin3_" + uuid.uuid4().hex[:8]
            atoken, _ = _new_user(client, a_uname)
            aid = _fetch_one("SELECT user_id FROM users WHERE username=?", (a_uname,))[0]
            with db_adapter.get_connection(str(config.DB_PATH)) as conn:
                conn.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (aid,))
            ok = client.get("/api/admin/credits/config", headers=_hdr(atoken))
            assert ok.status_code == 200
            # 掩码：密钥值不得含明文完整 Key，配置读取含 ****
            cfg = ok.get_json()["data"]
            for k, v in cfg.items():
                if k.endswith("api_key"):
                    assert v["value"] == "" or "*" in v["value"] or "•" in v["value"], k

    # ---------------------------------------------------------------- 8 计费路由（桩 provider）
    def test_billing_routing(self, app):
        import credits_service as cr
        import llm_provider_factory as lpf
        with app.app_context():
            cr.set_config_value("credits_daily_bonus", "0")
            cr.set_config_value("credits_token_ratio", "4000")
            cr.set_config_value("credits_asr_per_minute", "1")
            client = app.test_client()

            class StubProvider:
                model = "stub-model"

                def __init__(self, usage):
                    self.usage = usage

                def call(self, prompt, context="", usage_out=None):
                    if usage_out is not None and self.usage:
                        usage_out.update(self.usage)
                    return "OK-reply"

            factory = lpf.LLMProviderFactory()

            def seed_credit(user_id, amount=5000.0):
                # 直接正余额入账（不走 admin_adjust，避免其 total_recharged 记账干扰扣分断言）
                with db_adapter.get_connection(str(config.DB_PATH)) as conn:
                    cr.ensure_account(conn, user_id)
                    conn.execute("UPDATE user_credits SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                    conn.execute("INSERT INTO credit_transactions (user_id, type, scene, prompt_tokens, "
                                 "completion_tokens, total_tokens, credits_delta, credits_after, use_own_key, note, "
                                 "created_at) VALUES (?, 'recharge', 'seed', 0,0,0,?,0,0,'测试入账','2026-01-01 00:00:00')",
                                 (user_id, amount))

            def chat_as(token, usage, own_cfg=None, prompt="x" * 500):
                from werkzeug.test import EnvironBuilder
                builder = EnvironBuilder(path="/api/ai_chat_async", method="POST")
                try:
                    env = builder.get_environ()
                finally:
                    builder.close()
                with app.request_context(env):
                    from flask import g
                    g.user_id = _fetch_one("SELECT user_id FROM users WHERE username=?", (token,))[0]
                    if own_cfg is not None:
                        monkey = pytest.MonkeyPatch()
                        monkey.setattr(cr, "get_user_llm_config", lambda uid: own_cfg)
                    factory_stub = StubProvider(usage)
                    monkey2 = pytest.MonkeyPatch()
                    monkey2.setattr(factory, "_provider_from_cfg", staticmethod(lambda cfg, logger: factory_stub))
                    try:
                        return g.user_id, factory.call_llm(prompt, context="测试场景", scene="test")
                    finally:
                        monkey2.undo()
                        if own_cfg is not None:
                            monkey.undo()

            # a) usage 缺失 → 按字符估算扣分
            uname = "crdtbil_" + uuid.uuid4().hex[:8]
            _new_user(client, uname)
            uid0 = _fetch_one("SELECT user_id FROM users WHERE username=?", (uname,))[0]
            seed_credit(uid0)
            uid, res = chat_as(uname, usage={})
            assert res == "OK-reply"
            b = cr.get_balance(uid)
            assert 0 < b["balance"] < 5000.0  # 估算路径必扣分且不扣穿
            tx = _fetch_all("SELECT note FROM credit_transactions WHERE user_id=? AND type='llm'", (uid,))
            assert any("估算" in str(r[0]) for r in tx)

            # b) 正常 usage → 精确扣分 4000+0 → 1.0
            uname2 = "crdtbil2_" + uuid.uuid4().hex[:8]
            _new_user(client, uname2)
            seed_credit(_fetch_one("SELECT user_id FROM users WHERE username=?", (uname2,))[0])
            uid2, _ = chat_as(uname2, usage={"prompt_tokens": 4000, "completion_tokens": 0})
            assert abs(cr.get_balance(uid2)["balance"] - 4999.0) < 0.01

            # c) 自备 Key 成功 → 不扣分但记流水 use_own_key=1
            uname3 = "crdtown_" + uuid.uuid4().hex[:8]
            _new_user(client, uname3)
            uid3, _ = chat_as(uname3, usage={"prompt_tokens": 8000, "completion_tokens": 0},
                              own_cfg={"llm_provider": "DeepSeek", "api_key": "sk-user",
                                       "model": "u", "api_url": ""})
            assert cr.get_balance(uid3)["total_used"] == 0.0
            assert cr.get_balance(uid3)["balance"] == 0.0  # 未充值也不拦截（自备 Key 不走预检）
            own_tx = _fetch_all("SELECT use_own_key, credits_delta FROM credit_transactions "
                                "WHERE user_id=? AND type='llm'", (uid3,))
            assert own_tx and own_tx[0][0] in (1, True) and float(own_tx[0][1]) == 0.0

            # d) 余额不足 → 预检拦截抛 InsufficientCreditsError
            uname4 = "crdtlow_" + uuid.uuid4().hex[:8]
            _new_user(client, uname4)
            uid4 = _fetch_one("SELECT user_id FROM users WHERE username=?", (uname4,))[0]
            assert cr.precheck(uid4)["allowed"] is False  # 余额 0 初始即拦截
            with pytest.raises(cr.InsufficientCreditsError):
                chat_as(uname4, usage={"prompt_tokens": 4000})

            # e) 管理员 → 豁免但流水留痕
            auname = "cadmin4_" + uuid.uuid4().hex[:8]
            _new_user(client, auname)
            aid = _fetch_one("SELECT user_id FROM users WHERE username=?", (auname,))[0]
            with db_adapter.get_connection(str(config.DB_PATH)) as conn:
                conn.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (aid,))
            uid5, _ = chat_as(auname, usage={"prompt_tokens": 4000, "completion_tokens": 4000})
            assert cr.get_balance(aid)["total_used"] == 0.0
            atx = _fetch_all("SELECT note FROM credit_transactions WHERE user_id=? AND type='llm'", (aid,))
            assert atx and "管理员" in str(atx[0][0])
