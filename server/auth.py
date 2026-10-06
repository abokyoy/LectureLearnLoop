"""
多用户认证模块 —— 本次迁移新增的核心基础设施。

业务规则（用户已确认）：
- 开放注册：用户名 + 密码（用户名大小写不敏感，统一归一化为小写存储）；
- 数据按用户隔离；存量/种子数据归 admin（user_id='0001'）；
- 鉴权方式：JWT（HS256），默认有效期 7 天（四期修正：原 57 天过长，可由环境变量
  JWT_TTL_DAYS 覆盖，配合客户端“记住登录”免登录窗口期，用户可在设置中改 7/30/57/关闭）。
"""
from __future__ import annotations

import datetime as dt
import os
import re
import uuid

import jwt
from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

import config
import credits_service
from logger_module import debug_logger

auth_bp = Blueprint("auth", __file__)

JWT_ALGORITHM = "HS256"
try:
    JWT_TTL_DAYS = max(1, int(os.environ.get("JWT_TTL_DAYS", "7")))
except ValueError:
    JWT_TTL_DAYS = 7
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{2,32}$")


# ---------------------------------------------------------------- 表结构与种子
def init_auth_table(db_conn_factory):
    """创建 users 表并保证 admin 种子账号存在。db_conn_factory 为获取数据库连接的函数。"""
    with db_conn_factory() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        # 四期新增：昵称列（旧库容错迁移，幂等）
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT ''")
        row = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (config.ADMIN_USER_ID,)
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO users (user_id, username, password_hash, is_admin, created_at) VALUES (?,?,?,?,?)",
                (
                    config.ADMIN_USER_ID,
                    "admin",
                    generate_password_hash("admin123"),
                    1,
                    dt.datetime.now().isoformat(),
                ),
            )
            debug_logger.log_success("auth", "seed_admin", {"username": "admin"})


def _get_db():
    return current_app.config["DB_CONN_FACTORY"]()


def _norm_username(raw: str) -> str:
    """用户名归一化：去空白 + 小写。

    修复根因：SQLite `=` 默认 BINARY 排序区分大小写，历史版本未归一化导致
    'ABOYKOY'/'aboykoy' 被当成两个账号（注册成功却登录提示用户不存在、
    科目随 user_id 分裂“消失”）。新数据统一小写写入，查询用 lower() 兼容历史脏数据。
    """
    return (raw or "").strip().lower()


def _find_user(conn, username: str):
    """按归一化用户名查账号（兼容历史大小写混杂的存量行）。"""
    return conn.execute(
        "SELECT user_id, username, password_hash, is_admin, "
        "COALESCE(display_name,'') FROM users WHERE lower(username) = ?",
        (username,),
    ).fetchone()


def _make_token(user_id: str, username: str) -> str:
    payload = {
        "uid": user_id,
        "uname": username,
        "exp": dt.datetime.now() + dt.timedelta(days=JWT_TTL_DAYS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------------- 装饰器
def require_auth(func):
    """JWT 鉴权装饰器：成功后将 g.user_id / g.username 注入。"""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"success": False, "error": "missing bearer token"}), 401
        token = header[7:].strip()
        try:
            payload = jwt.decode(token, config.JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return jsonify({"success": False, "error": "token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"success": False, "error": "invalid token"}), 401
        g.user_id = payload["uid"]
        g.username = payload.get("uname", "")
        g.token_exp = payload.get("exp")
        return func(*args, **kwargs)

    return wrapper


def require_admin(func):
    """管理员鉴权装饰器（仅 is_admin=1 可访问，2026-09-28 积分管理后台）。"""
    import functools

    @functools.wraps(func)
    @require_auth
    def wrapper(*args, **kwargs):
        with _get_db() as conn:
            row = conn.execute("SELECT is_admin FROM users WHERE user_id = ?", (g.user_id,)).fetchone()
        if not row or int(row[0] or 0) != 1:
            return jsonify({"success": False, "error": "需要管理员权限"}), 403
        g.is_admin = True
        return func(*args, **kwargs)

    return wrapper
# ---------------------------------------------------------------- 接口
@auth_bp.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    username = _norm_username(data.get("username"))
    password = data.get("password") or ""
    if not USERNAME_RE.match(username):
        return jsonify({"success": False, "error": "用户名需为2-32位字母/数字/下划线/中文"}), 400
    if len(password) < 6:
        return jsonify({"success": False, "error": "密码至少6位"}), 400

    user_id = uuid.uuid4().hex[:12]
    debug_logger.log("auth", "register_start", data={"username": username})
    try:
        with _get_db() as conn:
            exists = _find_user(conn, username)
            if exists:
                return jsonify({"success": False, "error": "用户名已存在"}), 409
            conn.execute(
                "INSERT INTO users (user_id, username, password_hash, is_admin, created_at) VALUES (?,?,?,?,?)",
                (user_id, username, generate_password_hash(password), 0, dt.datetime.now().isoformat()),
            )
        # 为新用户建立 vault 目录
        (config.VAULT_DIR / user_id).mkdir(parents=True, exist_ok=True)
        debug_logger.log_success("auth", "register_done", {"username": username, "user_id": user_id})
        return jsonify({"success": True, "data": {"token": _make_token(user_id, username), "user_id": user_id, "username": username, "expires_in_days": JWT_TTL_DAYS}})
    except Exception as exc:  # noqa: BLE001
        debug_logger.log_error("auth", "register_failed", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    username = _norm_username(data.get("username"))
    password = data.get("password") or ""
    with _get_db() as conn:
        row = _find_user(conn, username)
    if not row or not check_password_hash(row[2], password):
        debug_logger.log_error("auth", "login_failed", "bad credentials", {"username": username})
        return jsonify({"success": False, "error": "用户名或密码错误"}), 401
    token = _make_token(row[0], row[1])
    # 每日首次登录赠送积分（自然日幂等，2026-09-28 积分功能）
    bonus = {"granted": False, "credits": 0.0}
    try:
        bonus = credits_service.grant_daily_bonus(row[0])
    except Exception as exc:  # noqa: BLE001 赠送失败不阻断登录
        debug_logger.log_error("auth", "daily_bonus_failed", exc, {"user_id": row[0]})
    # 一并返回 Deepgram 临时配置：客户端不接触主密钥（架构决定 #2）
    debug_logger.log_success("auth", "login", {"username": username, "bonus": bonus})
    return jsonify({
        "success": True,
        "data": {
            "token": token,
            "user_id": row[0],
            "username": row[1],
            "display_name": row[4] if len(row) > 4 else "",
            "is_admin": bool(row[3]),
            "expires_in_days": JWT_TTL_DAYS,
            "bonus_granted": bonus.get("granted", False),
            "bonus_credits": bonus.get("credits", 0.0),
            "credit_balance": bonus.get("balance"),
        },
    })


@auth_bp.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    display_name = ""
    try:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT COALESCE(display_name,'') FROM users WHERE user_id = ?", (g.user_id,)
            ).fetchone()
            display_name = row[0] if row else ""
    except Exception:  # noqa: BLE001 列不存在等旧库异常不阻断
        pass
    return jsonify({"success": True, "data": {
        "user_id": g.user_id,
        "username": g.username,
        "display_name": display_name,
        "token_exp": getattr(g, "token_exp", None),
    }})


@auth_bp.route("/api/auth/password", methods=["POST"])
@require_auth
def change_password():
    """修改密码：验证旧密码，新密码至少 6 位。"""
    data = request.get_json(silent=True) or {}
    old_password = data.get("old_password") or ""
    new_password = data.get("new_password") or ""
    if len(new_password) < 6:
        return jsonify({"success": False, "error": "新密码至少6位"}), 400
    with _get_db() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE user_id = ?", (g.user_id,)
        ).fetchone()
        if not row:
            return jsonify({"success": False, "error": "用户不存在"}), 404
        if not check_password_hash(row[0], old_password):
            debug_logger.log_error("auth", "change_password_bad_old", "old password mismatch", {"user_id": g.user_id})
            return jsonify({"success": False, "error": "旧密码不正确"}), 401
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?",
            (generate_password_hash(new_password), g.user_id),
        )
    debug_logger.log_success("auth", "change_password", {"user_id": g.user_id})
    return jsonify({"success": True, "data": {"changed": True}})


@auth_bp.route("/api/auth/profile", methods=["POST"])
@require_auth
def update_profile():
    """更新用户资料（目前仅昵称 display_name，最长 32 字符）。"""
    data = request.get_json(silent=True) or {}
    display_name = (data.get("display_name") or "").strip()[:32]
    try:
        with _get_db() as conn:
            conn.execute(
                "UPDATE users SET display_name = ? WHERE user_id = ?",
                (display_name, g.user_id),
            )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"success": False, "error": str(exc)}), 500
    return jsonify({"success": True, "data": {"display_name": display_name}})


@auth_bp.route("/api/asr/config", methods=["GET"])
@require_auth
def asr_config():
    """向已登录客户端下发 Deepgram 流式连接所需的 key。

    MVP 说明：暂以登录态换取 key 的方式（客户端主进程持有，不落盘不分发）。
    技术债：正式部署应换成 Deepgram create-temporary-token 短期凭据，见掉坑笔记规划。

    语言参数（P6 产品级修复）：实测 language=multi 对中文音频返回空转写，
    因此默认下发 config.DEEPGRAM_LANGUAGE（zh-CN）；优先级：
    ?language= 请求参数 > 设置页 whisper_language 映射（mode=auto 时） > .env 固定值。
    """
    if not config.DEEPGRAM_API_KEY:
        return jsonify({"success": False, "error": "server missing DEEPGRAM_API_KEY"}), 500
    # 2026-09-28 积分系统：ASR 只走系统 Key，余额不足（≤0）拒绝下发凭据，防负余额无限白嫖
    _pre = credits_service.precheck(g.user_id)
    if not _pre["allowed"]:
        return jsonify({"success": False, "error": "积分不足，请充值后使用录音转文字",
                        "credits_insufficient": True, "credit_balance": _pre["balance"]}), 402
    # 允许的语言：Deepgram 原生码 + 旧设置页键位（归一化）
    alias = {"auto": "multi", "zh": "zh-CN", "cn": "zh-CN", "en": "en", "multi": "multi"}
    allowed = {"multi", "zh-CN", "en"}
    lang = config.DEEPGRAM_LANGUAGE
    if getattr(config, "DEEPGRAM_LANGUAGE_MODE", "fixed") == "auto":
        wl = (config.load_config().get("whisper_language") or "").strip()
        if wl in alias:
            lang = alias[wl]
    req_lang = (request.args.get("language") or "").strip()
    if req_lang:
        lang = alias.get(req_lang, req_lang)
    if lang not in allowed:
        return jsonify({"success": False, "error": f"unsupported language: {lang}"}), 400
    debug_logger.log("asr", "issue_key", {"user_id": g.user_id, "language": lang})
    return jsonify({
        "success": True,
        "data": {
            "api_key": config.DEEPGRAM_API_KEY,
            "ws_url": "wss://api.deepgram.com/v1/listen",
            "model": "nova-2",
            "language": lang,
            "encoding": "linear16",
            "sample_rate": 16000,
            "channels": 1,
        },
    })
