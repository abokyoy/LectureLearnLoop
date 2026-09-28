"""
P3 业务 API 蓝图 —— 知识点/科目/错题/收藏/脑图/学习路径/练习/笔记/配置。

约定：
- 全部端点挂 @require_auth，用户身份取自 g.user_id（多用户隔离，P1 已验证）；
- 响应统一 {success: bool, data|error}，与旧 app_flask.py 前端习惯保持兼容；
- LLM 相关调用失败直接返回 500 + 详细错误（用户确认 Q6：不降级、不兜底）。
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, g, jsonify, request

from auth import require_auth
import credits_service as cr
from config import VAULT_DIR, load_config
from logger_module import debug_logger as log

kb_bp = Blueprint("kb", __name__)

# ---------------------------------------------------------------- KMS 单例
_kms = None


def get_kms():
    global _kms
    if _kms is None:
        from knowledge_management import KnowledgeManagementSystem
        _kms = KnowledgeManagementSystem(load_config())
    return _kms


def _ok(data=None, **extra):
    body = {"success": True, "data": data}
    body.update(extra)
    return jsonify(body)


def _err(message: str, code: int = 500):
    return jsonify({"success": False, "error": str(message)}), code


def _user_vault_root(user_id: str) -> Path:
    root = Path(VAULT_DIR) / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_vault_path(user_id: str, rel_path: str) -> Path | None:
    """解析 vault 相对路径并防止目录穿越；非法返回 None。"""
    if not rel_path or rel_path.startswith("/") or rel_path.startswith("\\"):
        return None
    root = _user_vault_root(user_id)
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


# ---------------------------------------------------------------- 科目
@kb_bp.route("/api/subjects", methods=["GET"])
@require_auth
def list_subjects():
    return _ok(get_kms().get_subjects(user_id=g.user_id))


@kb_bp.route("/api/subjects", methods=["POST"])
@require_auth
def create_subject():
    body = request.get_json(silent=True) or {}
    name = (body.get("subject_name") or "").strip()
    if not name:
        return _err("subject_name 不能为空", 400)
    created = get_kms().create_subject(name, user_id=g.user_id)
    return _ok({"subject_name": name, "created": bool(created)})


@kb_bp.route("/api/subjects/<name>", methods=["PUT"])
@require_auth
def rename_subject(name):
    body = request.get_json(silent=True) or {}
    new_name = (body.get("new_name") or "").strip()
    if not new_name:
        return _err("new_name 不能为空", 400)
    ok = get_kms().update_subject_name(name, new_name, user_id=g.user_id)
    return _ok({"renamed": bool(ok)})


@kb_bp.route("/api/subjects/<name>", methods=["DELETE"])
@require_auth
def delete_subject(name):
    ok = get_kms().delete_subject(name, user_id=g.user_id)
    if not ok:
        return _err("删除失败：学科可能仍有知识点", 400)
    return _ok({"deleted": True})


@kb_bp.route("/api/subjects/stats", methods=["GET"])
@require_auth
def subject_stats():
    return _ok(get_kms().get_subject_stats(user_id=g.user_id))


# ---------------------------------------------------------------- 工作台真实统计（四期：假数据全面下线）
@kb_bp.route("/api/dashboard/stats", methods=["GET"])
@require_auth
def dashboard_stats():
    """首页统计：本周学习资料数/练习正确率/已掌握知识点/在学科目/最近活动。

    口径：笔记时间存 UTC "%Y-%m-%d %H:%M:%S"，周边界按本周一起（本地周概念用 UTC 近似）；
    本周无练习记录时 accuracy 返回 None，前端显示“—”，绝不假数据兜底。
    """
    import datetime as _dt
    uid = g.user_id
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    week_start = (now - _dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    ws = week_start.strftime("%Y-%m-%d %H:%M:%S")
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(DISTINCT id) FROM notes WHERE user_id = ? AND (created_time >= ? OR updated_time >= ?)",
            (uid, ws, ws))
        materials_this_week = cur.fetchone()[0] or 0

        cur.execute(
            "SELECT COUNT(*), SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) "
            "FROM practice_records WHERE user_id = ? AND practice_time >= ?",
            (uid, ws))
        row = cur.fetchone()
        total_pr, correct_pr = (row[0] or 0), (row[1] or 0)
        accuracy = round(correct_pr * 100.0 / total_pr) if total_pr else None

        cur.execute("SELECT COUNT(*) FROM knowledge_points WHERE user_id = ?", (uid,))
        kp_total = cur.fetchone()[0] or 0
        cur.execute(
            "SELECT COUNT(*) FROM knowledge_points WHERE user_id = ? AND mastery_score >= 80", (uid,))
        kp_mastered = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM user_subjects WHERE user_id = ?", (uid,))
        subjects = cur.fetchone()[0] or 0
        cur.execute(
            "SELECT COUNT(*) FROM error_questions WHERE user_id = ? AND review_status = 0", (uid,))
        errors_pending = cur.fetchone()[0] or 0

        activities = []
        cur.execute(
            "SELECT COALESCE(title, file_name), updated_time FROM notes "
            "WHERE user_id = ? ORDER BY updated_time DESC LIMIT 5",
            (uid,))
        for t, ts in cur.fetchall():
            activities.append({"kind": "note", "title": f"学习/更新了《{t or '未命名笔记'}》", "time": ts})
        cur.execute(
            "SELECT subject_name, is_correct, practice_time FROM practice_records "
            "WHERE user_id = ? ORDER BY practice_time DESC LIMIT 3",
            (uid,))
        for subj, ok_, ts in cur.fetchall():
            activities.append({"kind": "practice",
                               "title": f"完成《{subj}》练习（{'答对' if ok_ else '答错'}）",
                               "time": ts})
        activities.sort(key=lambda a: str(a["time"]), reverse=True)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        log.log_error("dashboard", "stats_failed", exc)
        return _err(f"统计失败: {exc}", 500)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    return _ok({
        "materials_this_week": materials_this_week,
        "practice_count_this_week": total_pr,
        "practice_accuracy": accuracy,
        "knowledge_total": kp_total,
        "knowledge_mastered": kp_mastered,
        "subjects": subjects,
        "errors_pending": errors_pending,
        "recent_activities": activities[:5],
    })


# ---------------------------------------------------------------- 知识点提取/确认
@kb_bp.route("/api/knowledge/extract", methods=["POST"])
@require_auth
def extract_knowledge():
    """断点 D1 修复：请求体必须携带 subject_name。"""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    subject_name = (body.get("subject_name") or "").strip()
    if not text:
        return _err("text 不能为空", 400)
    if not subject_name:
        return _err("subject_name 不能为空（提取必须指定学科）", 400)
    log.log("api", "extract_knowledge_start", data={"text_len": len(text), "subject": subject_name})
    try:
        result = get_kms().extract_and_process_knowledge_points(subject_name, text, user_id=g.user_id)
    except Exception as e:
        log.log_error("api", "extract_knowledge_failed", str(e), data={"subject": subject_name})
        return _err(f"知识点提取失败: {e}", 500)
    n = len(result.get("processed_points", [])) if isinstance(result, dict) else 0
    log.log_success("api", "extract_knowledge_done", data={"count": n})
    return _ok(result)


@kb_bp.route("/api/knowledge/confirm", methods=["POST"])
@require_auth
def confirm_knowledge():
    body = request.get_json(silent=True) or {}
    confirmations = body.get("confirmations") or []
    if not isinstance(confirmations, list) or not confirmations:
        return _err("confirmations 必须为非空列表", 400)
    note_uuid = body.get("note_uuid")
    saved = get_kms().confirm_knowledge_points(confirmations, note_uuid=note_uuid, user_id=g.user_id)
    return _ok({"saved_point_ids": saved})


@kb_bp.route("/api/knowledge/points", methods=["GET"])
@require_auth
def knowledge_points():
    subject = (request.args.get("subject") or "").strip()
    if not subject:
        return _err("subject 参数不能为空", 400)
    return _ok(get_kms().get_knowledge_points_by_subject(subject, user_id=g.user_id))


@kb_bp.route("/api/knowledge/points/<int:pid>/sources", methods=["GET"])
@require_auth
def knowledge_point_sources(pid):
    return _ok(get_kms().get_knowledge_point_sources(pid, user_id=g.user_id))


# ---------------------------------------------------------------- 知识库统计（别名，兼容旧页面命名）
@kb_bp.route("/api/kb/stats", methods=["GET"])
@require_auth
def kb_stats():
    return _ok(get_kms().get_subject_stats(user_id=g.user_id))


# ---------------------------------------------------------------- 错题本
@kb_bp.route("/api/kb/errors", methods=["GET"])
@require_auth
def list_errors():
    subject = (request.args.get("subject") or "").strip()
    kp = request.args.get("kp_id", type=int)
    keyword = request.args.get("keyword") or ""
    if not subject:
        return _err("subject 参数不能为空", 400)
    return _ok(get_kms().search_error_questions(subject, knowledge_point_id=kp, keyword=keyword, user_id=g.user_id))


@kb_bp.route("/api/kb/errors/<int:eid>/history", methods=["GET"])
@require_auth
def error_history(eid):
    history = get_kms().get_proficiency_history(eid, user_id=g.user_id)
    return _ok([{"timestamp": t, "proficiency": p} for t, p in history])


@kb_bp.route("/api/kb/errors/<int:eid>/proficiency", methods=["POST"])
@require_auth
def error_append_proficiency(eid):
    body = request.get_json(silent=True) or {}
    p = body.get("proficiency")
    if p is None:
        return _err("proficiency 不能为空", 400)
    get_kms().append_proficiency(eid, int(p), user_id=g.user_id)
    return _ok({"proficiency": int(p)})


@kb_bp.route("/api/kb/errors/<int:eid>/reviewed", methods=["POST"])
@require_auth
def error_mark_reviewed(eid):
    ok = get_kms().mark_error_reviewed(eid, user_id=g.user_id)
    return _ok({"reviewed": bool(ok)})


@kb_bp.route("/api/kb/errors/<int:eid>", methods=["PUT"])
@require_auth
def error_update_content(eid):
    body = request.get_json(silent=True) or {}
    ok = get_kms().update_error_question_content(eid, body.get("content", ""), user_id=g.user_id)
    return _ok({"updated": bool(ok)})


@kb_bp.route("/api/kb/errors/<int:eid>/move", methods=["POST"])
@require_auth
def error_move_kp(eid):
    body = request.get_json(silent=True) or {}
    kp = body.get("knowledge_point_id")
    if kp is None:
        return _err("knowledge_point_id 不能为空", 400)
    ok = get_kms().update_error_knowledge_point(eid, int(kp), user_id=g.user_id)
    return _ok({"moved": bool(ok)})


@kb_bp.route("/api/kb/errors/<int:eid>/to_favorite", methods=["POST"])
@require_auth
def error_to_favorite(eid):
    fav_id = get_kms().convert_error_to_favorite(eid, user_id=g.user_id)
    if fav_id is None:
        return _err("转收藏失败：错题不存在或无权访问", 404)
    return _ok({"favorite_id": fav_id})


@kb_bp.route("/api/kb/errors/<int:eid>", methods=["DELETE"])
@require_auth
def error_delete(eid):
    ok = get_kms().delete_error_question(eid, user_id=g.user_id)
    return _ok({"deleted": bool(ok)})


# ---------------------------------------------------------------- 收藏本
@kb_bp.route("/api/kb/favorites", methods=["GET"])
@require_auth
def list_favorites():
    subject = (request.args.get("subject") or "").strip()
    kp = request.args.get("kp_id", type=int)
    keyword = request.args.get("keyword") or ""
    if not subject:
        return _err("subject 参数不能为空", 400)
    return _ok(get_kms().get_favorite_questions(subject, knowledge_point_id=kp, keyword=keyword, user_id=g.user_id))


@kb_bp.route("/api/kb/favorites", methods=["POST"])
@require_auth
def add_favorite():
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject_name") or "").strip()
    content = (body.get("question_content") or "").strip()
    kp = body.get("knowledge_point_id")
    if not subject or not content or kp is None:
        return _err("subject_name/question_content/knowledge_point_id 均不能为空", 400)
    fav_id = get_kms().save_favorite_question(
        subject, int(kp), content,
        correct_answer=body.get("correct_answer"),
        explanation=body.get("explanation"),
        user_id=g.user_id,
    )
    return _ok({"favorite_id": fav_id})


# ---------------------------------------------------------------- 脑图 / 学习路径
@kb_bp.route("/api/mindmap", methods=["GET"])
@require_auth
def get_mindmap():
    subject = (request.args.get("subject") or "").strip()
    if not subject:
        return _err("subject 参数不能为空", 400)
    return _ok(get_kms().get_mindmap(subject, user_id=g.user_id))


@kb_bp.route("/api/mindmap/generate", methods=["POST"])
@require_auth
def generate_mindmap():
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject_name") or "").strip()
    if not subject:
        return _err("subject_name 不能为空", 400)
    try:
        result = get_kms().generate_or_get_mindmap(subject, user_id=g.user_id)
    except cr.InsufficientCreditsError as e:
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except Exception as e:
        log.log_error("api", "mindmap_generate_failed", str(e), data={"subject": subject})
        return _err(f"脑图生成失败: {e}", 500)
    if result is None:
        return _err("脑图生成失败：学科无知识点或 LLM 未返回有效结构", 500)
    return _ok(result, **cr.billing_for_response())


@kb_bp.route("/api/mindmap/clear", methods=["POST"])
@require_auth
def clear_mindmap():
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject_name") or "").strip()
    if not subject:
        return _err("subject_name 不能为空", 400)
    ok = get_kms().clear_mindmap_cache(subject, user_id=g.user_id)
    return _ok({"cleared": bool(ok)})


@kb_bp.route("/api/learning-path", methods=["GET"])
@require_auth
def get_learning_path():
    subject = (request.args.get("subject") or "").strip()
    if not subject:
        return _err("subject 参数不能为空", 400)
    try:
        result = get_kms().get_or_generate_learning_path(subject, user_id=g.user_id)
    except cr.InsufficientCreditsError as e:
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except Exception as e:
        log.log_error("api", "learning_path_failed", str(e), data={"subject": subject})
        return _err(f"学习路径生成失败: {e}", 500)
    return _ok(result, **cr.billing_for_response())


@kb_bp.route("/api/learning-path/clear", methods=["POST"])
@require_auth
def clear_learning_path():
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject_name") or "").strip()
    if not subject:
        return _err("subject_name 不能为空", 400)
    ok = get_kms().clear_learning_path_cache(subject, user_id=g.user_id)
    return _ok({"cleared": bool(ok)})


# ---------------------------------------------------------------- 练习（出题/提交，熟练度重算在 P5 完善）
@kb_bp.route("/api/practice/generate", methods=["POST"])
@require_auth
def practice_generate():
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject_name") or "").strip()
    kp = body.get("knowledge_point_id")
    count = int(body.get("count") or 2)
    if not subject or kp is None:
        return _err("subject_name/knowledge_point_id 不能为空", 400)
    try:
        questions = get_kms().generate_new_questions(
            subject, int(kp), count=count,
            reference_text=body.get("reference_text"), user_id=g.user_id,
        )
    except cr.InsufficientCreditsError as e:
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except Exception as e:
        log.log_error("api", "practice_generate_failed", str(e), data={"subject": subject, "kp": kp})
        return _err(f"出题失败: {e}", 500)
    return _ok(questions, **cr.billing_for_response())


@kb_bp.route("/api/practice/results", methods=["POST"])
@require_auth
def practice_results():
    body = request.get_json(silent=True) or {}
    records = body.get("records") or []
    if not isinstance(records, list) or not records:
        return _err("records 必须为非空列表", 400)
    for r in records:
        r.setdefault("subject_name", "通用学科")
    saved = get_kms().save_practice_results(records, user_id=g.user_id)
    return _ok({"saved_record_ids": saved})


# ---------------------------------------------------------------- 笔记 / vault 文件
@kb_bp.route("/api/vault/tree", methods=["GET"])
@require_auth
def vault_tree():
    root = _user_vault_root(g.user_id)
    tree = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        for fn in filenames:
            fp = Path(dirpath) / fn
            tree.append({
                "path": (f"{rel_dir}/{fn}" if rel_dir else fn).lstrip("/"),
                "size": fp.stat().st_size,
                "mtime": fp.stat().st_mtime,
            })
    return _ok(tree)


@kb_bp.route("/api/vault/file", methods=["GET"])
@require_auth
def vault_read_file():
    rel = request.args.get("path") or ""
    target = _safe_vault_path(g.user_id, rel)
    if target is None:
        return _err("非法路径", 403)
    if not target.is_file():
        return _err("文件不存在", 404)
    content = target.read_text(encoding="utf-8", errors="replace")
    return _ok({"path": rel.replace("\\", "/"), "content": content})


@kb_bp.route("/api/vault/file", methods=["PUT"])
@require_auth
def vault_write_file():
    body = request.get_json(silent=True) or {}
    rel = (body.get("path") or "").strip()
    content = body.get("content") or ""
    target = _safe_vault_path(g.user_id, rel)
    if target is None:
        return _err("非法路径", 403)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    # 同步登记到 notes 表（供知识点来源关联）
    kms = get_kms()
    note_id = kms.register_note(
        file_name=target.name,
        file_path=str(target),
        title=body.get("title"),
        user_id=g.user_id,
    )
    note_uuid = None
    try:
        conn = kms.db_manager.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT note_uuid FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id))
        row = cur.fetchone()
        note_uuid = row[0] if row else None
        conn.close()
    except Exception:
        pass
    return _ok({"note_id": note_id, "note_uuid": note_uuid, "saved": True})


@kb_bp.route("/api/notes", methods=["GET"])
@require_auth
def list_notes():
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, note_uuid, file_name, title, created_time, updated_time "
        "FROM notes WHERE user_id = ? ORDER BY updated_time DESC",
        (g.user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return _ok([
        {"id": r[0], "note_uuid": r[1], "file_name": r[2], "title": r[3],
         "created_time": r[4], "updated_time": r[5]}
        for r in rows
    ])


# ---------------------------------------------------------------- LLM 日志 / 通用调用 / 配置
@kb_bp.route("/api/llm/logs", methods=["GET"])
@require_auth
def llm_logs():
    from llm_call_logger import get_llm_call_records
    limit = request.args.get("limit", default=50, type=int) or 50
    return _ok(get_llm_call_records(limit))


@kb_bp.route("/api/llm/stats", methods=["GET"])
@require_auth
def llm_stats():
    from llm_call_logger import get_llm_call_statistics
    return _ok(get_llm_call_statistics())


@kb_bp.route("/api/llm/call", methods=["POST"])
@require_auth
def llm_call():
    """通用 LLM 调用（笔记追问等）。失败直接 500（Q6）。"""
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return _err("prompt 不能为空", 400)
    from llm_provider_factory import LLMProviderFactory
    try:
        result = LLMProviderFactory().call_llm(prompt, body.get("context", ""))
    except Exception as e:
        if isinstance(e, cr.InsufficientCreditsError):
            return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                            "credit_balance": e.balance}), 402
        log.log_error("api", "llm_call_failed", str(e))
        return _err(f"LLM调用失败: {e}", 500)
    return _ok(result, **cr.billing_for_response())


@kb_bp.route("/api/config", methods=["GET"])
@require_auth
def get_config():
    """返回给前端的配置——绝不包含任何密钥明文（掩码回显供设置页表单）。"""
    cfg = load_config()

    def _mask(key_val):
        v = (key_val or "").strip()
        if not v:
            return ""
        return "•" * 8 + v[-4:]

    safe = {
        "llm_provider": cfg.get("llm_provider"),
        # DeepSeek（当前唯一提供商）
        "deepseek_api_key": _mask(cfg.get("deepseek_api_key")),
        "deepseek_model": cfg.get("deepseek_model"),
        "deepseek_api_url": cfg.get("deepseek_api_url"),
        "deepseek_is_selected": True,
        # 其余提供商（保留键位防前端 undefined；已废弃但表单需要）
        "ollama_model": cfg.get("ollama_model", ""),
        "ollama_api_url": cfg.get("ollama_api_url", ""),
        "ollama_is_selected": False,
        "gemini_api_key": "",
        "gemini_model": cfg.get("gemini_model", ""),
        "gemini_is_selected": False,
        "qwen_api_key": "",
        "qwen_model": cfg.get("qwen_model", ""),
        "qwen_api_url": cfg.get("qwen_api_url", ""),
        "qwen_is_selected": False,
        # 运行时设置
        "summary_mode": cfg.get("summary_mode", "auto"),
        "auto_summary_interval": cfg.get("auto_summary_interval", 60),
        "whisper_language": cfg.get("whisper_language", "auto"),
        "auto_summary_max_chars": cfg.get("auto_summary_max_chars", 4000),
        "manual_summary_max_chars": cfg.get("manual_summary_max_chars", 6000),
        "llm_call_logging_enabled": cfg.get("llm_call_logging_enabled", True),
        "selected_audio_device_index": cfg.get("selected_audio_device_index", -1),
        "selected_audio_device_name": cfg.get("selected_audio_device_name", ""),
        "similarity_min_score": cfg.get("similarity_min_score"),
        "has_deepseek_key": bool(cfg.get("deepseek_api_key")),
        "has_deepgram_key": bool(os.getenv("DEEPGRAM_API_KEY")),
    }
    return _ok(safe)
