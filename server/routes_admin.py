# -*- coding: utf-8 -*-
"""管理后台 API（2026-09-28 积分功能，蓝图 admin_bp）。

仅管理员可访问（auth.require_admin）。提供：
- 积分业务参数配置（system_config 表）
- 系统级大模型配置（密钥掩码返回；提交值等于掩码时不覆盖）
- 用户积分总览 / 手工调整（审计流水）
- 卡密：批量生成 / 列表 / 作废
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

import credits_service as credits
from auth import require_admin
from database.schema_credits import LLM_CONFIG_KEYS
from logger_module import debug_logger

admin_bp = Blueprint("admin", __file__)

# 允许管理员在后台修改的积分业务参数键（白名单，防止误写任意键）
_EDITABLE_CREDIT_KEYS = {
    "credits_daily_bonus", "credits_token_ratio", "credits_asr_per_minute",
    "credits_per_yuan", "credits_recharge_text", "credits_recharge_url",
}


def _mask_key(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 8:
        return "********"
    return val[:4] + "****" + val[-4:]


def _looks_masked(val: str) -> bool:
    """形似掩码串（含 **** 或 •）的提交值一律拒写，防掩码覆盖真实密钥（跨页掩码算法不同也一并拦截）。"""
    return "****" in val or "•" in val


@admin_bp.route("/api/admin/credits/config", methods=["GET"])
@require_admin
def get_credit_config():
    """全部系统配置（含大模型键，密钥掩码）。"""
    all_cfg = credits.list_all_config()
    out = {}
    for k, item in all_cfg.items():
        v = item["value"]
        if k.endswith("api_key"):
            v = _mask_key(v)
        out[k] = {"value": v, "description": item["description"]}
    return jsonify({"success": True, "data": out})


@admin_bp.route("/api/admin/credits/config", methods=["POST"])
@require_admin
def set_credit_config():
    """批量更新配置。密钥字段提交值等于当前掩码时视为未修改，跳过写入。"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({"success": False, "error": "请提交 {key: value} 配置对象"}), 400
    current = credits.effective_llm_config(None)
    changed = []
    rejected_masked = []
    for key, value in data.items():
        sval = str(value if value is not None else "")
        if key.endswith("api_key"):
            # 比对基准用生效配置（含 .env/runtime 文件值）；掩码形态直接拒绝，绝不落库
            if _looks_masked(sval):
                if sval and sval != _mask_key(str(current.get(key, ""))):
                    rejected_masked.append(key)  # 改动过的掩码串，显式提示需重新粘贴完整 Key
                continue
        if key in _EDITABLE_CREDIT_KEYS or key in LLM_CONFIG_KEYS:
            credits.set_config_value(key, sval)
            changed.append(key)
    debug_logger.log("admin", "set_config", "success", {"operator": g.user_id, "keys": changed,
                                                        "rejected_masked": rejected_masked})
    return jsonify({"success": True, "data": {"updated": changed, "rejected_masked": rejected_masked}})


# ---------------------------------------------------------------- 系统大模型
@admin_bp.route("/api/admin/llm-config", methods=["GET"])
@require_admin
def get_llm_config():
    cfg = credits.system_llm_overrides()
    env_cfg = credits.effective_llm_config(None)
    out = {}
    for key in LLM_CONFIG_KEYS:
        v = cfg.get(key) or env_cfg.get(key) or ""
        out[key] = _mask_key(v) if key.endswith("api_key") else v
    return jsonify({"success": True, "data": out})


@admin_bp.route("/api/admin/llm-config", methods=["POST"])
@require_admin
def set_llm_config():
    data = request.get_json(silent=True) or {}
    current = credits.effective_llm_config(None)
    changed = []
    for key, value in data.items():
        if key not in LLM_CONFIG_KEYS:
            continue
        sval = str(value if value is not None else "").strip()
        if key.endswith("api_key") and (_looks_masked(sval) or (sval and sval == _mask_key(str(current.get(key, ""))))):
            continue  # 掩码形态或掩码回传，不覆盖真值
        credits.set_config_value(key, sval)
        changed.append(key)
    debug_logger.log("admin", "set_llm_config", "success", {"operator": g.user_id, "keys": changed})
    return jsonify({"success": True, "data": {"updated": changed}})


# ---------------------------------------------------------------- 用户与调整
@admin_bp.route("/api/admin/users", methods=["GET"])
@require_admin
def users_credits():
    return jsonify({"success": True, "data": credits.list_users_credits()})


@admin_bp.route("/api/admin/adjust", methods=["POST"])
@require_admin
def adjust():
    data = request.get_json(silent=True) or {}
    target = (data.get("user_id") or "").strip()
    if not target:
        return jsonify({"success": False, "error": "缺少 user_id"}), 400
    try:
        delta = float(data.get("delta") or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "delta 需为数字"}), 400
    result = credits.admin_adjust(target, delta, str(data.get("note") or ""), g.user_id)
    debug_logger.log("admin", "adjust", "success" if result.get("success") else "warning",
                     {"operator": g.user_id, "target": target, "delta": delta, "result": result})
    status = 200 if result.get("success") else 400
    return jsonify(result if not result.get("success") else {"success": True, "data": result}), status


@admin_bp.route("/api/admin/transactions/<user_id>", methods=["GET"])
@require_admin
def user_transactions(user_id: str):
    limit = min(int(request.args.get("limit", default=100, type=int) or 100), 500)
    return jsonify({"success": True, "data": credits.list_transactions(user_id, limit=limit)})


# ---------------------------------------------------------------- 卡密
@admin_bp.route("/api/admin/codes/generate", methods=["POST"])
@require_admin
def gen_codes():
    data = request.get_json(silent=True) or {}
    try:
        each = float(data.get("credits") or 0)
        count = int(data.get("count") or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "credits/count 需为数字"}), 400
    if each <= 0 or count <= 0 or count > 1000:
        return jsonify({"success": False, "error": "credits 需>0，count 范围 1-1000"}), 400
    codes = credits.generate_codes(g.user_id, each, count)
    return jsonify({"success": True, "data": {"batch_count": len(codes), "codes": [c["code"] for c in codes]}})


@admin_bp.route("/api/admin/codes", methods=["GET"])
@require_admin
def codes():
    status = (request.args.get("status") or "").strip()
    limit = min(int(request.args.get("limit", default=200, type=int) or 200), 1000)
    return jsonify({"success": True, "data": credits.list_codes(status=status, limit=limit)})


@admin_bp.route("/api/admin/codes/void", methods=["POST"])
@require_admin
def void():
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    ok = credits.void_code(code)
    debug_logger.log("admin", "void_code", "success" if ok else "warning",
                     {"operator": g.user_id, "code": code, "ok": ok})
    if not ok:
        return jsonify({"success": False, "error": "卡密不存在或已被使用"}), 400
    return jsonify({"success": True})
