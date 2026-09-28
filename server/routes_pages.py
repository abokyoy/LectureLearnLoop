"""
P2c 页面路由蓝图 —— 旧 app_flask.py 的 7 个页面路由 1:1 迁移 + 登录/注册页 + SPA 片段端点。

渲染策略（与开发计划架构决定 #1 对应）：
- 旧 Jinja2 页面模板全部保留不拆；pages/*.html 中裸片段直接 include 进 SPA 壳；
- / 与 6 个功能页统一走 spa_layout.html 壳（侧边栏/顶栏不重复渲染）；
- /fragments/<content_id> 供 api.js 的 loadContent（SPA 内无刷新切换），
  返回 {success, data:"<html片段>"}，走 Bearer JWT（401 时前端自动跳 /login）；
- practice_materials.html / practice_materials_simple.html 是完整 HTML 文档
  （Qt 里就是整页 load_html），保持整页渲染；SPA 菜单入口通过
  practice_materials_frame 片段（内嵌 iframe 指向 /practice）留在主框架内，
  不再整页跳转冲掉左侧菜单（产品要求）；
- /login /register 为自绘登录页（Stitch MCP 不可用，按规格降级本地 CSS）。
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, jsonify, redirect, render_template, request
from jinja2 import TemplateNotFound

from auth import require_auth

pages_bp = Blueprint("pages", __name__)

# 模板目录（server/templates）
_TMPL_DIR = Path(__file__).resolve().parent / "templates"

# 旧页面路由表：URL -> SPA 壳内渲染的内容 id
# 四期D组：“从资料学习”已合并进网课笔记，/learn_materials 302 重定向，不再列入。
_SPA_PAGES = {
    "/online_course": "online_course_notes",
    "/knowledge_base": "knowledge_base",
    "/settings": "settings",
    "/llm_logs": "llm_logs",
    "/admin/credits": "admin_credits",
}

# /fragments/<id> 白名单：pages/ 下存在同名裸片段（或与 Qt menuId 对齐）的才允许渲染。
# practice_materials = 脑图练习 iframe 片段（嵌入后左侧菜单不丢，见 frame 模板）。
_FRAGMENT_IDS = {
    "dashboard",
    "online_course_notes",
    "practice_knowledge",
    "practice_errors",
    "practice_materials",
    "memory_knowledge",
    "memory_errors",
    "knowledge_base",
    "settings",
    "llm_logs",
    "admin_credits",
}


def _render_template_block(tpl_path: str, block_name: str, context: dict) -> str | None:
    """只渲染模板中某个 block（用于 dashboard.html 这种 extends base.html 的页面）。

    返回 None 表示该模板没有此 block（即裸片段，调用方应整体渲染）。
    """
    try:
        tpl = current_app.jinja_env.get_template(tpl_path)
    except TemplateNotFound:
        return None
    block = getattr(tpl, "blocks", {}).get(block_name)
    if block is None:
        return None
    return "".join(block(tpl.new_context(context)))


def _fragment_or_page(content_id: str) -> str:
    """按内容 id 渲染页面主体 HTML（dashboard 走 'content' block，其余裸片段整体渲染）。"""
    if content_id == "practice_materials":
        # 脑图练习整页是独立文档，用 iframe 片段嵌入 SPA 壳，保留左侧菜单
        return render_template("pages/practice_materials_frame.html")
    tpl_path = f"pages/{content_id}.html"
    if content_id == "dashboard":
        html = _render_template_block(tpl_path, "content", {"stats": {}})
        if html is not None:
            return html
    return render_template(tpl_path)


# ---------------------------------------------------------------- 页面路由

@pages_bp.route("/")
def index():
    """工作台：SPA 壳默认 page_content 即 dashboard 概览卡。"""
    return render_template("spa_layout.html", active_menu="dashboard")


@pages_bp.route("/learn_materials")
def page_learn_materials():
    """四期D组：资料学习已合并进网课笔记，老入口 302 重定向（模板文件保留不删，作回退备份）。"""
    return redirect("/online_course", code=302)


@pages_bp.route("/online_course")
def page_online_course():
    return render_template("spa/page.html", page="pages/online_course_notes.html",
                           content_id="online_course_notes", active_menu="online_course_notes")


@pages_bp.route("/knowledge_base")
def page_knowledge_base():
    return render_template("spa/page.html", page="pages/knowledge_base.html",
                           content_id="knowledge_base", active_menu="knowledge_base")


@pages_bp.route("/settings")
def page_settings():
    return render_template("spa/page.html", page="pages/settings.html",
                           content_id="settings", active_menu="settings")


@pages_bp.route("/llm_logs")
def page_llm_logs():
    return render_template("spa/page.html", page="pages/llm_logs.html",
                           content_id="llm_logs", active_menu="llm_logs")


@pages_bp.route("/admin/credits")
@require_auth
def page_admin_credits():
    """管理后台（2026-09-28 积分系统）：页面壳登录后即可渲染，数据端点全部 require_admin 把关。"""
    return render_template("spa/page.html", page="pages/admin_credits.html",
                           content_id="admin_credits", active_menu="settings")


@pages_bp.route("/practice")
def page_practice():
    """练习脑图：完整 HTML 文档整页渲染（与 Qt load_html 行为一致）。"""
    return render_template("pages/practice_materials.html")


@pages_bp.route("/practice_simple")
def page_practice_simple():
    return render_template("pages/practice_materials_simple.html")


# ---------------------------------------------------------------- SPA 片段端点

@pages_bp.route("/fragments/<content_id>", methods=["GET"])
@require_auth
def fragment(content_id):
    """api.js loadContent 的无刷新内容加载；data 为纯 HTML 片段字符串。"""
    if content_id not in _FRAGMENT_IDS:
        return jsonify({"success": False, "error": f"未知页面片段: {content_id}"}), 404
    try:
        html = _fragment_or_page(content_id)
        return jsonify({"success": True, "data": html})
    except TemplateNotFound:
        return jsonify({"success": False, "error": f"页面模板缺失: {content_id}"}), 404
    except Exception as e:  # noqa: BLE001
        return jsonify({"success": False, "error": f"片段渲染失败: {e}"}), 500


# ---------------------------------------------------------------- 登录 / 登出

@pages_bp.route("/login")
def login_page():
    return render_template("login.html")


@pages_bp.route("/register")
def register_page():
    # 同一张卡片页，前端 tab 默认切到注册（用 query 提示，行为仍由用户控制）
    return render_template("login.html", mode="register")


@pages_bp.route("/logout")
def logout_page():
    """登出落地页：清除 JWT（两处存储）与记住登录凭证后回登录页（服务端 JWT 无状态）。"""
    return (
        "<script>try{localStorage.removeItem('ll_token');sessionStorage.removeItem('ll_token');"
        "localStorage.removeItem('ll_remember');}catch(e){}"
        "location.replace('/login');</script>",
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )


# ---------------------------------------------------------------- 悬浮窗 / 截屏（P4）

@pages_bp.route("/overlay")
def overlay_page():
    """悬浮录音窗（Electron overlay BrowserWindow 加载；同源共享 localStorage token）。

    服务端不做鉴权重定向：token 由页面脚本自取并调用受保护 API，
    未登录时悬浮窗自行提示。"""
    return render_template("overlay.html")


@pages_bp.route("/capture")
def capture_page():
    """框选截屏窗口页（Electron capture BrowserWindow 加载）。"""
    return render_template("capture.html")


@pages_bp.route("/note-picker")
def note_picker_page():
    """学习笔记选择/新建窗口页（Electron notePicker BrowserWindow 加载，二期）。

    与 /overlay 同理：不做服务端鉴权重定向，token 由同源 localStorage 自取。"""
    return render_template("note_picker.html")
