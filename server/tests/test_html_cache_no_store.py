# -*- coding: utf-8 -*-
"""HTML 页面全局防缓存断言（实弹轮八追 2026-11-13：项目此前 0 缓存控制头，
Chromium/Electron 对无 validators 的 HTML 走启发式缓存，部署修复用户碰不到）。

运行方式（server/ 目录）：python -m pytest tests/test_html_cache_no_store.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _app():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


def test_page_html_no_store():
    """GET /learn_goals：text/html 响应必须带 Cache-Control: no-store。"""
    with _app().test_client() as c:
        r = c.get("/learn_goals")
        assert r.status_code == 200
        assert r.mimetype == "text/html"
        assert r.headers.get("Cache-Control") == "no-store", dict(r.headers)


def test_shell_html_no_store():
    """SPA 壳 GET /：同样 no-store（壳内同样可能承载页面脚本）。"""
    with _app().test_client() as c:
        r = c.get("/")
        assert r.status_code == 200
        assert r.mimetype == "text/html"
        assert r.headers.get("Cache-Control") == "no-store"


def test_api_json_not_touched():
    """JSON API 不属于 text/html：不加 no-store（本修复只管页面文档）。"""
    with _app().test_client() as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.mimetype == "application/json"
        assert r.headers.get("Cache-Control") != "no-store"


def test_static_css_not_no_store():
    """静态资源不受影响（CodeReview Minor-1）：cl.css 保持 mtime 版本号缓存机制，
    不得被误加 no-store；200/304 均可，关键看头。"""
    with _app().test_client() as c:
        r = c.get("/static/css/cl.css")
        assert r.status_code in (200, 304)
        assert r.headers.get("Cache-Control") != "no-store"


def test_spa_fragment_no_store():
    """SPA 主页面通道 /fragments/<id>（八追核心）：learn_goals 等页面的 HTML+JS 实经
    此 JSON 包裹通道送达用户——虽 mimetype 是 application/json 也必须 no-store，
    否则「改了但用户碰不到」依旧重演。未鉴权 401 同样应带头。"""
    with _app().test_client() as c:
        r = c.get("/fragments/learn_goals")
        assert r.status_code in (200, 401)
        assert r.headers.get("Cache-Control") == "no-store"


def test_error_html_page_no_store():
    """文档级 HTML 错误页同样带 no-store（CodeReview Minor-2）：防旧错误页被缓存。
    取非 /api/ 前缀的不存在路径（/api/ 错误回 JSON 不属 text/html 分支）。
    TESTING 模式默认 PROPAGATE_EXCEPTIONS=True 会把 NotFound 直抛给测试方，
    生产路径实为渲染 HTML 错误页，故显式关 PROPAGATE_EXCEPTIONS 对齐。"""
    app = _app()
    app.config["PROPAGATE_EXCEPTIONS"] = False
    with app.test_client() as c:
        r = c.get("/no_such_page_zzz")
        assert r.status_code == 404
        assert r.mimetype == "text/html"
        assert r.headers.get("Cache-Control") == "no-store"


def test_api_error_stays_json():
    """/api/ 前缀错误仍回 JSON 形（钉住追问笔记树轮 errorhandler 分支 + 八追修复不串道）：
    API 路径 404 不得因 HTTPException 优先分支变成 HTML。"""
    app = _app()
    app.config["PROPAGATE_EXCEPTIONS"] = False
    with app.test_client() as c:
        r = c.get("/api/no_such_zzz")
        assert r.status_code == 404
        assert r.mimetype == "application/json"
        assert r.get_json()["success"] is False
