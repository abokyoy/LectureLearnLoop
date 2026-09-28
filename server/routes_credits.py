# -*- coding: utf-8 -*-
"""用户积分 API（2026-09-28 积分功能，蓝图 credits_bp）。

全部端点需登录（require_auth）。计费核心逻辑一律走 credits_service（公共函数注册制），
本模块只做参数校验与响应封装。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

import credits_service as credits
from auth import require_auth
from logger_module import debug_logger

credits_bp = Blueprint("credits", __file__)


@credits_bp.route("/api/credits/balance", methods=["GET"])
@require_auth
def balance():
    """余额 + 兑换入口展示所需配置（充值文案/店铺链接/汇率）。"""
    b = credits.get_balance(g.user_id)
    return jsonify({"success": True, "data": {
        **b,
        "recharge_text": credits.get_config_value("credits_recharge_text"),
        "recharge_url": credits.get_config_value("credits_recharge_url"),
        "credits_per_yuan": credits.get_number("credits_per_yuan", 100),
        "is_admin": credits.is_admin_user(g.user_id),
    }})


@credits_bp.route("/api/credits/transactions", methods=["GET"])
@require_auth
def transactions():
    limit = min(int(request.args.get("limit", default=50, type=int) or 50), 200)
    offset = max(int(request.args.get("offset", default=0, type=int) or 0), 0)
    rows = credits.list_transactions(g.user_id, limit=limit, offset=offset)
    return jsonify({"success": True, "data": rows, "total_balance": credits.get_balance(g.user_id)})


@credits_bp.route("/api/credits/redeem", methods=["POST"])
@require_auth
def redeem():
    """卡密兑换入账。"""
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    result = credits.redeem_code(g.user_id, code)
    debug_logger.log("credits", "api_redeem", "success" if result.get("success") else "warning",
                     {"user_id": g.user_id, "result": {k: v for k, v in result.items() if k != "balance"} or result.get("error")})
    if not result.get("success"):
        return jsonify({"success": False, "error": result.get("error", "兑换失败")}), 400
    return jsonify({"success": True, "data": result})


@credits_bp.route("/api/credits/asr-charge", methods=["POST"])
@require_auth
def asr_charge():
    """录音转文字停止后按总时长扣分（LLRecorder done() 上报）。"""
    data = request.get_json(silent=True) or {}
    try:
        seconds = int(float(data.get("seconds") or 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "seconds 需为数字"}), 400
    seconds = max(0, min(seconds, 24 * 3600))  # 上限 24h，防异常自报值
    if seconds <= 0:
        return jsonify({"success": True, "data": {"credits": 0.0, "minutes": 0,
                                                  "balance": credits.get_balance(g.user_id)["balance"]}})
    # 录音已实际发生：直接扣分允许负余额（欠费由后续 LLM 调用预检拦截补齐）
    result = credits.charge_asr(g.user_id, seconds)
    return jsonify({"success": True, "data": result})


# ---------------------------------------------------------------- 用户级大模型配置
@credits_bp.route("/api/user/llm-config", methods=["GET"])
@require_auth
def get_llm_config():
    """查看自备 Key（掩码）+ 系统 Key 可用状态（前端提示"未配置将走系统 Key 扣积分"）。"""
    cfg = credits.get_user_llm_config_masked(g.user_id)
    sys_cfg = credits.effective_llm_config(None)
    return jsonify({"success": True, "data": {
        "user_config": cfg,
        "system_provider": sys_cfg.get("llm_provider", ""),
        "system_ready": bool(sys_cfg.get("deepseek_api_key") or sys_cfg.get("qwen_api_key")
                             or sys_cfg.get("gemini_api_key") or sys_cfg.get("ollama_api_url")),
        "token_ratio": credits.token_credit_ratio(),
    }})


@credits_bp.route("/api/user/llm-config", methods=["POST"])
@require_auth
def save_llm_config():
    """保存/更新用户自备 Key。语义：api_key 缺省/空串 = 保持原 Key 不变；
    显式清除需传 clear_key=true（防前端“留空”误销毁已存 Key 后静默回落系统 Key 扣分）。"""
    data = request.get_json(silent=True) or {}
    provider = (data.get("provider") or "DeepSeek").strip()
    if provider not in ("DeepSeek", "Gemini", "Qwen", "Ollama"):
        return jsonify({"success": False, "error": "不支持的提供商"}), 400
    enabled = bool(data.get("enabled", True))
    model = (data.get("model") or "").strip()
    api_url = (data.get("api_url") or "").strip()
    if data.get("clear_key"):
        credits.save_user_llm_config(g.user_id, provider, "", model, api_url, False)
        debug_logger.log("credits", "clear_user_llm", "success", {"user_id": g.user_id})
        return jsonify({"success": True, "data": credits.get_user_llm_config_masked(g.user_id)})
    api_key = (data.get("api_key") or "").strip()
    if not api_key:
        existing = credits.get_user_llm_config(g.user_id) or {}
        api_key = str(existing.get("api_key") or "")  # 空串提交：保持原 Key
        if not api_key and enabled:
            return jsonify({"success": False, "error": "首次启用自备 Key 必须填写 API Key"}), 400
    credits.save_user_llm_config(g.user_id, provider, api_key, model, api_url, enabled)
    debug_logger.log("credits", "save_user_llm", "success",
                     {"user_id": g.user_id, "provider": provider, "enabled": enabled, "has_key": bool(api_key)})
    return jsonify({"success": True, "data": credits.get_user_llm_config_masked(g.user_id)})
