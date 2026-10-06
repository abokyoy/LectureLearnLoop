# -*- coding: utf-8 -*-
"""积分计费核心服务 —— 全项目唯一的积分读写入口（公共函数注册制）。

业务规则（2026-09-28 与用户对齐，均可在管理后台 system_config 配置）：
- 4000 Token = 1 积分（credits_token_ratio），展示保留 1 位小数；
- 单次 LLM 扣分不足 0.1 按 0.1 计（有实际 Token 消耗时）；
- 录音转文字每分钟 1 积分（credits_asr_per_minute），不足 1 分钟向上取整；
- 每日首次登录赠送 100 积分（credits_daily_bonus），按自然日幂等；
- 余额预检：balance <= 0 时拒绝系统 Key 调用（用户自备 Key / 管理员不受限）；
- 管理员使用系统大模型豁免扣分（流水仍记录，credits_delta=0）；
- 充值：卡密兑换入账，100 积分 = 1 元（credits_per_yuan，仅展示口径）。

线程模型：last_billing 为 threading.local，供 LLM 工厂写入、端点读取本次调用的
计费信息（扣了多少分/是否自备 Key/余额），保证响应可携带扣分提示。
"""
from __future__ import annotations

import datetime as dt
import math
import secrets
import threading
from typing import Optional

from flask import current_app, has_app_context, has_request_context

from database.db_adapter import is_postgres
from database.schema_credits import DEFAULT_SYSTEM_CONFIG, LLM_CONFIG_KEYS
from logger_module import debug_logger

# 兜底默认（表内无值时；与 DEFAULT_SYSTEM_CONFIG 一致）
_FALLBACK = {k: v for k, v, _d in DEFAULT_SYSTEM_CONFIG}


class InsufficientCreditsError(Exception):
    """积分不足，已拦截本次系统大模型调用（前端统一提示充值）。"""

    def __init__(self, balance: float):
        super().__init__("积分不足，请充值后继续使用")
        self.balance = balance


# ---------------------------------------------------------------- 连接
def _conn():
    if has_app_context():
        return current_app.config["DB_CONN_FACTORY"]()
    # 启动期/脚本环境（无 app context）：直连适配层
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


def _now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return dt.date.today().isoformat()


# ---------------------------------------------------------------- 系统配置
def get_config_value(key: str, default: str = "") -> str:
    try:
        with _conn() as conn:
            row = conn.execute("SELECT value FROM system_config WHERE key = ?", (key,)).fetchone()
            if row is not None and str(row[0] or "") != "":
                return str(row[0])
    except Exception:  # noqa: BLE001 表未建等异常回退默认值（DB 抖动不得静默影响计费，留告警可查）
        debug_logger.log("credits", "config_read_fallback", "warning", {"key": key})
        pass
    return _FALLBACK.get(key, default)


def set_config_value(key: str, value: str, description: str = "") -> None:
    with _conn() as conn:
        row = conn.execute("SELECT key FROM system_config WHERE key = ?", (key,)).fetchone()
        if row:
            conn.execute(
                "UPDATE system_config SET value = ?, updated_at = ? WHERE key = ?",
                (str(value), _now(), key),
            )
        else:
            conn.execute(
                "INSERT INTO system_config (key, value, description, updated_at) VALUES (?,?,?,?)",
                (key, str(value), description, _now()),
            )


def get_number(key: str, default: float) -> float:
    raw = get_config_value(key, str(default))
    try:
        v = float(raw)
        # 0 是合法配置（如关闭每日赠送/免费 ASR）；仅负数/非法回落默认
        return v if v >= 0 else float(default)
    except (TypeError, ValueError):
        return float(default)


def list_all_config() -> dict:
    with _conn() as conn:
        rows = conn.execute("SELECT key, value, description FROM system_config ORDER BY key").fetchall()
    return {r[0]: {"value": r[1], "description": r[2]} for r in rows}


# ---------------------------------------------------------------- 换算（仿 AIFinFlowX usage_service 口径）
def token_credit_ratio() -> int:
    # 下限 1：防止管理员误配小数被 int() 截断为 0 导致全站计费除零
    return max(1, int(round(get_number("credits_token_ratio", 4000))))


def tokens_to_credits(tokens: int) -> float:
    """Token → 积分（1 位小数；有 Token 消耗时最小 0.1，避免微量免费）。"""
    if not tokens or tokens <= 0:
        return 0.0
    credits = round(tokens / token_credit_ratio(), 1)
    return max(0.1, credits)


# ---------------------------------------------------------------- 账户
def ensure_account(conn, user_id: str):
    conn.execute(
        "INSERT OR IGNORE INTO user_credits (user_id, balance, total_recharged, total_granted, total_used, last_bonus_date, updated_at) "
        "VALUES (?, 0, 0, 0, 0, '', ?)",
        (user_id, _now()),
    )


def get_balance(user_id: str) -> dict:
    with _conn() as conn:
        ensure_account(conn, user_id)
        row = conn.execute(
            "SELECT balance, total_recharged, total_granted, total_used FROM user_credits WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    balance, recharged, granted, used = (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
    total_earned = round(recharged + granted, 1)
    return {
        "balance": round(balance, 1),
        "total_earned": round(total_earned, 1),
        "total_recharged": round(recharged, 1),
        "total_granted": round(granted, 1),
        "total_used": round(used, 1),
    }


def is_admin_user(user_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return bool(row and int(row[0] or 0) == 1)


def _record_tx(conn, user_id: str, tx_type: str, scene: str, *, prompt_tokens: int = 0,
               completion_tokens: int = 0, total_tokens: int = 0, credits_delta: float = 0.0,
               credits_after: float = 0.0, use_own_key: bool = False, note: str = "") -> None:
    conn.execute(
        "INSERT INTO credit_transactions (user_id, type, scene, prompt_tokens, completion_tokens, "
        "total_tokens, credits_delta, credits_after, use_own_key, note, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, tx_type, scene, prompt_tokens, completion_tokens, total_tokens,
         round(credits_delta, 1), round(credits_after, 1), 1 if use_own_key else 0, note, _now()),
    )


# ---------------------------------------------------------------- 扣分
def charge_llm(user_id: str, prompt_tokens: int, completion_tokens: int, scene: str = "",
               provider: str = "", model: str = "", tokens_estimated: bool = False) -> dict:
    """LLM 调用后按 Token 折算扣分并记流水。管理员豁免（流水记录 delta=0）。

    返回 billing dict：{credits, tokens, balance, exempt_admin, use_own_key:False}
    """
    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    credits = tokens_to_credits(total)
    admin = is_admin_user(user_id)
    note = f"{provider}/{model}" if provider else ""
    if tokens_estimated:
        note = (note + " ").lstrip() + "usage缺失，按字符估算"
    with _conn() as conn:
        ensure_account(conn, user_id)
        if admin:
            row = conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()
            balance = float(row[0])
            _record_tx(conn, user_id, "llm", scene, prompt_tokens=prompt_tokens or 0,
                       completion_tokens=completion_tokens or 0, total_tokens=total,
                       credits_delta=0.0, credits_after=balance, note="管理员不消耗积分 " + note)
            return {"credits": 0.0, "tokens": total, "balance": round(balance, 1),
                    "exempt_admin": True, "use_own_key": False}
        conn.execute(
            "UPDATE user_credits SET balance = balance - ?, total_used = total_used + ?, updated_at = ? "
            "WHERE user_id = ?",
            (credits, credits, _now(), user_id),
        )
        row = conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()
        balance = float(row[0])
        _record_tx(conn, user_id, "llm", scene, prompt_tokens=prompt_tokens or 0,
                   completion_tokens=completion_tokens or 0, total_tokens=total,
                   credits_delta=-credits, credits_after=balance, note=note)
    debug_logger.log("credits", "charge_llm", data={
        "user_id": user_id, "scene": scene, "tokens": total, "credits": credits, "balance": round(balance, 1)})
    return {"credits": round(credits, 1), "tokens": total, "balance": round(balance, 1),
            "exempt_admin": False, "use_own_key": False}


def record_own_key_call(user_id: str, prompt_tokens: int = 0, completion_tokens: int = 0,
                        scene: str = "", provider: str = "") -> None:
    """自备 Key 调用不扣分但记流水（delta=0，use_own_key=1），供管理员审计用量。"""
    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    try:
        with _conn() as conn:
            ensure_account(conn, user_id)
            balance = float(conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()[0])
            _record_tx(conn, user_id, "llm", scene, prompt_tokens=int(prompt_tokens or 0),
                       completion_tokens=int(completion_tokens or 0), total_tokens=total,
                       credits_delta=0.0, credits_after=balance, use_own_key=True,
                       note=f"自备Key不扣分 {provider}".strip())
    except Exception as exc:  # noqa: BLE001 审计流水失败不阻断主调用
        debug_logger.log("credits", "record_own_key_fail", "warning", {"user_id": user_id, "error": str(exc)})


def charge_asr(user_id: str, seconds: float) -> dict:
    """录音转文字按分钟扣分：ceil(秒/60) × 每分钟费率。返回 {credits, minutes, balance}。"""
    seconds = max(0, int(float(seconds or 0)))
    seconds = min(seconds, 24 * 3600)  # 上限 24h，防异常自报值
    minutes = math.ceil(seconds / 60) if seconds > 0 else 0
    per_min = get_number("credits_asr_per_minute", 1)
    credits = round(minutes * per_min, 1)
    if credits <= 0:
        return {"credits": 0.0, "minutes": minutes, "balance": get_balance(user_id)["balance"]}
    admin = is_admin_user(user_id)
    if admin:
        credits = 0.0
    with _conn() as conn:
        ensure_account(conn, user_id)
        row = conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()
        balance = float(row[0])
        if credits > 0:
            conn.execute(
                "UPDATE user_credits SET balance = balance - ?, total_used = total_used + ?, updated_at = ? "
                "WHERE user_id = ?",
                (credits, credits, _now(), user_id),
            )
            row = conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()
            balance = float(row[0])
        note = f"录音转文字 {minutes} 分钟" + ("（管理员不消耗积分）" if admin else "")
        _record_tx(conn, user_id, "asr", "录音转文字", total_tokens=0,
                   credits_delta=-credits, credits_after=balance, note=note)
    debug_logger.log("credits", "charge_asr", data={
        "user_id": user_id, "seconds": seconds, "minutes": minutes, "credits": credits})
    return {"credits": round(credits, 1), "minutes": minutes, "balance": round(balance, 1),
            "exempt_admin": admin}


def precheck(user_id: str) -> dict:
    """系统 Key 调用前预检：balance <= 0 拦截（透支修复后即恢复放行）。"""
    bal = get_balance(user_id)["balance"]
    if is_admin_user(user_id):
        return {"allowed": True, "reason": "admin_exempt", "balance": bal}
    if bal <= 0:
        return {"allowed": False, "reason": "insufficient", "balance": bal}
    return {"allowed": True, "reason": "", "balance": bal}


# ---------------------------------------------------------------- 赠送 / 兑换 / 调整
def grant_daily_bonus(user_id: str) -> dict:
    """当天首次登录赠送积分（按自然日幂等）。返回 {granted, credits, balance}。"""
    amount = get_number("credits_daily_bonus", 100)
    if amount <= 0:  # 管理员可通过配置 0 关闭赠送
        return {"granted": False, "credits": 0.0, "balance": get_balance(user_id)["balance"]}
    today = _today()
    with _conn() as conn:
        ensure_account(conn, user_id)
        row = conn.execute("SELECT last_bonus_date, balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()
        if row and str(row[0] or "") == today:
            return {"granted": False, "credits": 0.0, "balance": round(float(row[1]), 1)}
        # 条件更新保证并发幂等：仅当 last_bonus_date 仍非今日才发放（防读后写重复刷赠送）
        cur = conn.execute(
            "UPDATE user_credits SET balance = balance + ?, total_granted = total_granted + ?, "
            "last_bonus_date = ?, updated_at = ? WHERE user_id = ? "
            "AND (last_bonus_date IS NULL OR last_bonus_date <> ?)",
            (amount, amount, today, _now(), user_id, today),
        )
        if cur.rowcount < 1:  # 并发窗口内另一请求已发放
            row = conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()
            return {"granted": False, "credits": 0.0, "balance": round(float(row[0]), 1)}
        row = conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()
        balance = float(row[0])
        _record_tx(conn, user_id, "gift", "每日登录赠送", credits_delta=amount,
                   credits_after=balance, note=f"赠送 {amount} 积分")
    debug_logger.log("credits", "daily_bonus", data={"user_id": user_id, "credits": amount})
    return {"granted": True, "credits": round(amount, 1), "balance": round(balance, 1)}


def redeem_code(user_id: str, code: str) -> dict:
    """卡密兑换。行级锁（PG FOR UPDATE）保证同一卡密并发只成功一次。"""
    code = (code or "").strip().upper()
    if not code:
        return {"success": False, "error": "请输入卡密"}
    with _conn() as conn:
        if is_postgres():
            row = conn.execute(
                "SELECT credits, status FROM activation_codes WHERE code = ? FOR UPDATE", (code,)).fetchone()
        else:
            row = conn.execute("SELECT credits, status FROM activation_codes WHERE code = ?", (code,)).fetchone()
        if not row:
            return {"success": False, "error": "卡密无效，请核对后重试"}
        credits, status = float(row[0]), str(row[1])
        if status != "active":
            reason = "该卡密已被使用" if status == "used" else "该卡密已作废"
            return {"success": False, "error": reason}
        cur = conn.execute(
            "UPDATE activation_codes SET status = 'used', used_by = ?, used_at = ? WHERE code = ? AND status = 'active'",
            (user_id, _now(), code),
        )
        # rowcount 反映实际更新行数（PG 下 UPDATE 冪等安全）
        if cur.rowcount < 1:
            return {"success": False, "error": "该卡密已被使用"}
        ensure_account(conn, user_id)
        conn.execute(
            "UPDATE user_credits SET balance = balance + ?, total_recharged = total_recharged + ?, updated_at = ? "
            "WHERE user_id = ?",
            (credits, credits, _now(), user_id),
        )
        balance = float(conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()[0])
        _record_tx(conn, user_id, "recharge", "卡密充值", credits_delta=credits,
                   credits_after=balance, note=f"卡密 ****{code[-4:]} 兑换 +{credits}")
    debug_logger.log("credits", "redeem_ok", data={"user_id": user_id, "code_tail": code[-4:], "credits": credits})
    return {"success": True, "credits": round(credits, 1), "balance": round(balance, 1)}


def generate_codes(operator_id: str, credits_each: float, count: int) -> list:
    """管理员批量生成卡密。"""
    batch = "B" + dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    codes = []
    with _conn() as conn:
        for _ in range(max(1, int(count))):
            code = "LL-" + secrets.token_hex(4).upper() + "-" + secrets.token_hex(4).upper()
            conn.execute(
                "INSERT INTO activation_codes (code, credits, batch_id, status, created_by, created_at) "
                "VALUES (?,?,?,'active',?,?)",
                (code, round(float(credits_each), 1), batch, operator_id, _now()),
            )
            codes.append({"code": code, "credits": round(float(credits_each), 1)})
    debug_logger.log("credits", "gen_codes", data={"operator": operator_id, "batch": batch, "count": len(codes)})
    return codes


def admin_adjust(user_id: str, delta: float, note: str, operator_id: str) -> dict:
    """管理员手工调整积分（留审计流水）。相对更新防并发覆盖（lost update）。"""
    delta = round(float(delta), 1)
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone():
            return {"success": False, "error": "目标用户不存在"}
        ensure_account(conn, user_id)
        balance = float(conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()[0])
        if round(balance + delta, 1) < 0:
            return {"success": False, "error": f"调整后余额为负（{round(balance + delta, 1)}），不允许"}
        if delta >= 0:
            conn.execute("UPDATE user_credits SET balance = balance + ?, total_recharged = total_recharged + ?, updated_at = ? WHERE user_id = ?",
                         (delta, delta, _now(), user_id))
        else:
            conn.execute("UPDATE user_credits SET balance = balance - ?, total_used = total_used + ?, updated_at = ? WHERE user_id = ?",
                         (-delta, -delta, _now(), user_id))
        new_balance = round(float(conn.execute("SELECT balance FROM user_credits WHERE user_id = ?", (user_id,)).fetchone()[0]), 1)
        _record_tx(conn, user_id, "admin_adjust", "管理员调整", credits_delta=delta,
                   credits_after=new_balance, note=(note or "") + f"（操作人 {operator_id}）")
    return {"success": True, "balance": new_balance}


def list_transactions(user_id: str, limit: int = 50, offset: int = 0) -> list:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT type, scene, total_tokens, credits_delta, credits_after, use_own_key, note, created_at "
            "FROM credit_transactions WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (user_id, int(limit), int(offset)),
        ).fetchall()
    return [{"type": r[0], "scene": r[1], "total_tokens": r[2], "credits_delta": float(r[3]),
             "credits_after": float(r[4]), "use_own_key": bool(r[5]), "note": r[6], "created_at": r[7]} for r in rows]


def list_codes(status: str = "", limit: int = 200) -> list:
    with _conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT code, credits, batch_id, status, used_by, created_at, used_at "
                "FROM activation_codes WHERE status = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (status, int(limit))).fetchall()
        else:
            rows = conn.execute(
                "SELECT code, credits, batch_id, status, used_by, created_at, used_at "
                "FROM activation_codes ORDER BY created_at DESC, id DESC LIMIT ?", (int(limit),)).fetchall()
    return [{"code": r[0], "credits": float(r[1]), "batch_id": r[2], "status": r[3],
             "used_by": r[4], "created_at": r[5], "used_at": r[6]} for r in rows]


def void_code(code: str) -> bool:
    with _conn() as conn:
        cur = conn.execute("UPDATE activation_codes SET status = 'void' WHERE code = ? AND status = 'active'",
                           ((code or "").strip().upper(),))
        return cur.rowcount > 0


def list_users_credits() -> list:
    """管理后台：全部用户余额一览。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT u.user_id, u.username, COALESCE(u.display_name,''), COALESCE(c.balance,0), "
            "COALESCE(c.total_recharged,0), COALESCE(c.total_granted,0), COALESCE(c.total_used,0) "
            "FROM users u LEFT JOIN user_credits c ON c.user_id = u.user_id ORDER BY u.username"
        ).fetchall()
    return [{"user_id": r[0], "username": r[1], "display_name": r[2], "balance": float(r[3]),
             "total_recharged": float(r[4]), "total_granted": float(r[5]), "total_used": float(r[6])} for r in rows]


# ---------------------------------------------------------------- 用户级大模型配置
def get_user_llm_config(user_id: str) -> Optional[dict]:
    """返回用户自备的大模型配置（未配置/未启用/无 Key 时返回 None）。"""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT provider, api_key, model, api_url, enabled FROM user_llm_config WHERE user_id = ?",
                (user_id,)).fetchone()
    except Exception:  # noqa: BLE001 表未建等异常视为未配置
        return None
    if not row or not str(row[1] or "").strip() or int(row[4] or 0) != 1:
        return None
    return {"llm_provider": str(row[0]), "api_key": str(row[1]),
            "model": str(row[2] or ""), "api_url": str(row[3] or "")}


def save_user_llm_config(user_id: str, provider: str, api_key: str, model: str,
                         api_url: str, enabled: bool) -> None:
    with _conn() as conn:
        row = conn.execute("SELECT user_id FROM user_llm_config WHERE user_id = ?", (user_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE user_llm_config SET provider=?, api_key=?, model=?, api_url=?, enabled=?, updated_at=? "
                "WHERE user_id=?",
                (provider, api_key.strip(), model.strip(), api_url.strip(), 1 if enabled else 0, _now(), user_id),
            )
        else:
            conn.execute(
                "INSERT INTO user_llm_config (user_id, provider, api_key, model, api_url, enabled, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (user_id, provider, api_key.strip(), model.strip(), api_url.strip(), 1 if enabled else 0, _now()),
            )


def get_user_llm_config_masked(user_id: str) -> Optional[dict]:
    cfg = get_user_llm_config(user_id)
    if not cfg:
        with _conn() as conn:
            row = conn.execute(
                "SELECT provider, api_key, model, api_url, enabled FROM user_llm_config WHERE user_id = ?",
                (user_id,)).fetchone()
        if not row:
            return None
        cfg = {"llm_provider": str(row[0]), "api_key": str(row[1] or ""), "model": str(row[2] or ""),
               "api_url": str(row[3] or ""), "enabled": bool(int(row[4] or 0))}
    masked = dict(cfg)
    key = masked.get("api_key") or ""
    masked["api_key"] = ("*" * 8 + key[-4:]) if len(key) > 12 else (key[:4] + "*" * max(0, len(key) - 4))
    masked["has_key"] = bool((cfg.get("api_key") or "").strip())
    masked["enabled"] = bool(masked.get("enabled", True))
    return masked


# ---------------------------------------------------------------- 系统大模型有效配置
def system_llm_overrides() -> dict:
    """system_config 表中的系统大模型键（空值不覆盖 .env/runtime 文件）。"""
    out = {}
    with _conn() as conn:
        rows = conn.execute("SELECT key, value FROM system_config").fetchall()
    table = {r[0]: str(r[1] or "") for r in rows}
    for key in LLM_CONFIG_KEYS:
        v = table.get(key, "")
        if v:
            out[key] = v
    return out


def effective_llm_config(user_id: Optional[str] = None) -> dict:
    """组装当前生效的 LLM 配置：.env < runtime_config.json < system_config 表。"""
    import config as _cfg
    c = _cfg.load_config()
    c.update(system_llm_overrides())
    if user_id:
        own = get_user_llm_config(user_id)
        if own:
            c = dict(c)
            c["llm_provider"] = own["llm_provider"]
            key_map = {"DeepSeek": "deepseek", "Gemini": "gemini", "Qwen": "qwen", "Ollama": "ollama"}
            p = key_map.get(own["llm_provider"], "deepseek")
            c[f"{p}_api_key"] = own["api_key"]
            if own["model"]:
                c[f"{p}_model"] = own["model"]
            if own["api_url"]:
                c[f"{p}_api_url"] = own["api_url"]
    return c


# ---------------------------------------------------------------- 本次调用计费信息（线程内传递）
_tls = threading.local()


def set_last_billing(info: Optional[dict]) -> None:
    _tls.last_billing = info


def get_last_billing() -> Optional[dict]:
    return getattr(_tls, "last_billing", None)


def billing_for_response() -> dict:
    """端点统一调用：把本次 LLM 调用的计费信息转成响应附带字段（无计费上下文返回空 dict）。"""
    b = get_last_billing()
    if not b:
        return {}
    if b.get("use_own_key"):
        return {"credits_deducted": 0, "credit_note": "使用自备大模型，不扣积分", "credit_balance": b.get("balance")}
    if b.get("exempt_admin"):
        return {"credits_deducted": 0, "credit_note": "管理员不消耗积分", "credit_balance": b.get("balance")}
    if b.get("blocked"):
        return {"credits_deducted": 0, "credit_note": "积分不足，请充值后继续使用", "credits_insufficient": True}
    return {"credits_deducted": b.get("credits", 0), "credit_note":
            f"本次消耗 {b.get('credits', 0)} 积分", "credit_balance": b.get("balance")}
