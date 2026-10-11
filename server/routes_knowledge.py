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
import config as _cfg  # 手机传图公网地址等运行期配置（photo-session 端点用）
from logger_module import debug_logger as log
from services import fsrs_service as F

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
        # FSRS 两阶段口径：先全量衰减回写再统计（PG 下 10 分钟节流，避免每请求重算）
        try:
            F.decay_flush(uid, conn=conn)
        except Exception as fe:  # noqa: BLE001
            # CodeReview c2 Major-1：PG 事务 aborted 必须回滚重置，否则后续同连接统计查询全被拖崩
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            log.log_error("dashboard", "decay_flush_failed", fe)
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


@kb_bp.route("/api/practice/overview", methods=["GET"])
@require_auth
def practice_overview():
    """u8 练·科目统计首页数据：按科目聚合知识点/笔记/练习/错题与熟练度概况。

    口径（与 dashboard 一致，绝不用假数据兑底）：
    - mastery_score = -1 是「未评估」哨兵值，不参与均值；推荐位未评估点优先；
    - 推荐练习（业务规则）：每科取最多 3 个 —— 先推未评估（还没测过掌握度），
      再按掌握度升序推最低者；若该科有待强化错题，在首条推荐理由中追加提示；
    - 学习次数 = practice_records 总题数；本周口径同 dashboard（UTC 周一起）。
    """
    import datetime as _dt
    uid = g.user_id
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    week_start = (now - _dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    ws = week_start.strftime("%Y-%m-%d %H:%M:%S")
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        # FSRS 两阶段口径：先按用户全量衰减回写再统计（与 dashboard/memory_overview 同法，PG 节流）
        try:
            F.decay_flush(uid, conn=conn)
        except Exception as fe:  # noqa: BLE001
            try:
                conn.rollback()  # CodeReview c2 Major-1：aborted 事务必须重置后同连接才可用
            except Exception:  # noqa: BLE001
                pass
            log.log_error("api", "practice_overview_decay_flush_failed", fe)
        cur = conn.cursor()
        cur.execute("SELECT subject_name FROM user_subjects WHERE user_id = ? ORDER BY subject_name", (uid,))
        subject_names = [r[0] for r in cur.fetchall()]

        cur.execute(
            "SELECT subject_name, COUNT(*), "
            "AVG(CASE WHEN mastery_score >= 0 THEN mastery_score END), "
            "SUM(CASE WHEN mastery_score IS NULL OR mastery_score < 0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN mastery_score >= 80 THEN 1 ELSE 0 END) "
            "FROM knowledge_points WHERE user_id = ? GROUP BY subject_name", (uid,))
        kp_stats = {r[0]: {"knowledge_count": r[1], "avg_mastery": r[2], "unrated": r[3] or 0, "mastered": r[4] or 0}
                    for r in cur.fetchall()}

        cur.execute(
            "SELECT kp.subject_name, COUNT(DISTINCT kps.note_id) "
            "FROM knowledge_point_sources kps JOIN knowledge_points kp ON kp.id = kps.knowledge_point_id "
            "WHERE kp.user_id = ? GROUP BY kp.subject_name", (uid,))
        notes_stats = {r[0]: r[1] for r in cur.fetchall()}

        cur.execute(
            "SELECT subject_name, COUNT(*), SUM(CASE WHEN practice_time >= ? THEN 1 ELSE 0 END), MAX(practice_time) "
            "FROM practice_records WHERE user_id = ? GROUP BY subject_name", (ws, uid))
        pr_stats = {r[0]: {"practice_count": r[1], "practice_this_week": r[2] or 0, "last_practice_time": r[3]}
                    for r in cur.fetchall()}

        cur.execute(
            "SELECT subject_name, COUNT(*), SUM(CASE WHEN review_status = 0 THEN 1 ELSE 0 END) "
            "FROM error_questions WHERE user_id = ? GROUP BY subject_name", (uid,))
        eq_stats = {r[0]: {"errors_total": r[1], "errors_pending": r[2] or 0} for r in cur.fetchall()}

        cur.execute(
            "SELECT id, subject_name, point_name, mastery_score FROM knowledge_points WHERE user_id = ?",
            (uid,))
        all_points = cur.fetchall()
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        log.log_error("api", "practice_overview_failed", exc)
        return _err(f"统计失败: {exc}", 500)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    points_by_subject = {}
    for pid, subj, name, score in all_points:
        points_by_subject.setdefault(subj, []).append({"id": pid, "name": name, "score": score})

    subjects_out = []
    for subj in subject_names:
        kp = kp_stats.get(subj, {"knowledge_count": 0, "avg_mastery": None, "unrated": 0, "mastered": 0})
        pr = pr_stats.get(subj, {"practice_count": 0, "practice_this_week": 0, "last_practice_time": None})
        eq = eq_stats.get(subj, {"errors_total": 0, "errors_pending": 0})
        pts = points_by_subject.get(subj, [])
        for p in pts:
            p["unrated"] = p["score"] is None or p["score"] < 0
        rated = [p for p in pts if not p["unrated"]]
        best = max(rated, key=lambda p: p["score"]) if rated else None
        worst = min(rated, key=lambda p: p["score"]) if rated else None
        # 推荐练习：未评估优先，再按掌握度升序，最多 3 个
        unrated_pts = [p for p in pts if p["unrated"]]
        ranked = unrated_pts + sorted(rated, key=lambda p: p["score"])
        recommend = []
        for p in ranked[:3]:
            if p["unrated"]:
                reason = "尚未评估掌握度，先测一测"
            else:
                reason = f"掌握度仅 {p['score']}%，建议巩固"
            recommend.append({"id": p["id"], "name": p["name"], "score": p["score"], "reason": reason})
        if recommend and eq["errors_pending"] > 0:
            recommend[0]["reason"] += f"；另有 {eq['errors_pending']} 道错题待强化"
        subjects_out.append({
            "subject": subj,
            "knowledge_count": kp["knowledge_count"],
            "knowledge_mastered": kp["mastered"],
            "unrated_count": kp["unrated"],
            "avg_mastery": round(kp["avg_mastery"]) if kp["avg_mastery"] is not None else None,
            "notes_count": notes_stats.get(subj, 0),
            "practice_count": pr["practice_count"],
            "practice_this_week": pr["practice_this_week"],
            "last_practice_time": pr["last_practice_time"],
            "errors_total": eq["errors_total"],
            "errors_pending": eq["errors_pending"],
            "best_point": {"id": best["id"], "name": best["name"], "score": best["score"]} if best else None,
            "worst_point": {"id": worst["id"], "name": worst["name"], "score": worst["score"]} if worst else None,
            "recommend": recommend,
        })

    summary = {
        "subjects": len(subject_names),
        "knowledge_total": sum(s["knowledge_count"] for s in subjects_out),
        "practice_total": sum(s["practice_count"] for s in subjects_out),
        "errors_pending_total": sum(s["errors_pending"] for s in subjects_out),
    }
    return _ok({"success": True, "subjects": subjects_out, "summary": summary})


@kb_bp.route("/api/memory/overview", methods=["GET"])
@require_auth
def memory_overview():
    """u9 记·科目统计首页数据：每科待记知识点/错题待复习/复习进度与推荐。

    口径（全部真实数据，无假兑底；对齐 pm_pages.js 头注释：无 FSRS/到期复习引擎，
    禁止编造「今日到期」类字段，推荐一律基于掌握度/熟练度/复习状态）：
    - 待记知识点 = mastery_score < 80（含 -1 未评估哨兵）；均值/熟练点判断排除 -1；
    - 错题卡片 = error_questions 行数（错题复练即记忆卡片本体）；题干需 JOIN practice_records；
      last_error_time = 该科最后一条错题入库时间（表无复习时刻列，字段名如实命名）；
    - 错得最多 = 同科目下同一题干积累的 error_questions 行数 ≥ 2 中的最多者；
    - 推荐复习 = 待复习错题中熟练度升序（null 视作最弱排前），最多 3 条。
    """
    uid = g.user_id
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        # FSRS 两阶段口径：先按用户全量衰减回写再统计（与 dashboard 同法，PG 节流）
        try:
            F.decay_flush(uid, conn=conn)
        except Exception as fe:  # noqa: BLE001
            try:
                conn.rollback()  # CodeReview c2 Major-1：aborted 事务必须重置后同连接才可用
            except Exception:  # noqa: BLE001
                pass
            log.log_error("api", "memory_overview_decay_flush_failed", fe)
        cur = conn.cursor()
        cur.execute("SELECT subject_name FROM user_subjects WHERE user_id = ? ORDER BY subject_name", (uid,))
        subject_names = [r[0] for r in cur.fetchall()]

        cur.execute(
            "SELECT subject_name, COUNT(*), "
            "AVG(CASE WHEN mastery_score >= 0 THEN mastery_score END), "
            "SUM(CASE WHEN mastery_score IS NULL OR mastery_score < 0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN mastery_score >= 80 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN mastery_score >= 0 AND mastery_score < 80 THEN 1 ELSE 0 END) "
            "FROM knowledge_points WHERE user_id = ? GROUP BY subject_name", (uid,))
        kp_stats = {r[0]: {"total": r[1], "avg": r[2], "unrated": r[3] or 0, "mastered": r[4] or 0, "weak": r[5] or 0}
                    for r in cur.fetchall()}

        cur.execute(
            "SELECT subject_name, COUNT(*), "
            "SUM(CASE WHEN review_status = 0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN review_status = 1 THEN 1 ELSE 0 END), "
            "AVG(CASE WHEN current_proficiency >= 0 THEN current_proficiency END), "
            "MAX(created_time) "
            "FROM error_questions WHERE user_id = ? GROUP BY subject_name", (uid,))
        eq_stats = {r[0]: {"cards": r[1], "pending": r[2] or 0, "reviewed": r[3] or 0, "avg_prof": r[4], "last_err": r[5]}
                    for r in cur.fetchall()}

        # 错得最多：同科目同题干答错次数（JOIN 原句取题干，题干空则回落占位）
        cur.execute(
            "SELECT e.subject_name, COALESCE(NULLIF(p.question_content, ''), '（题干缺失）'), COUNT(*) "
            "FROM error_questions e LEFT JOIN practice_records p ON p.id = e.practice_record_id "
            "WHERE e.user_id = ? GROUP BY e.subject_name, COALESCE(NULLIF(p.question_content, ''), '（题干缺失）') "
            "HAVING COUNT(*) >= 2", (uid,))
        most_freq_by_subj = {}
        for subj, qtext, cnt in cur.fetchall():
            best = most_freq_by_subj.get(subj)
            if best is None or cnt > best["count"]:
                most_freq_by_subj[subj] = {"question": qtext, "count": cnt}

        cur.execute(
            "SELECT id, subject_name, point_name, mastery_score FROM knowledge_points WHERE user_id = ?",
            (uid,))
        all_points = cur.fetchall()

        cur.execute(
            "SELECT e.id, e.subject_name, e.current_proficiency, COALESCE(NULLIF(p.question_content, ''), '（题干缺失）') "
            "FROM error_questions e LEFT JOIN practice_records p ON p.id = e.practice_record_id "
            "WHERE e.user_id = ? AND e.review_status = 0", (uid,))
        pending_errors = cur.fetchall()
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        log.log_error("api", "memory_overview_failed", exc)
        return _err(f"统计失败: {exc}", 500)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    pts_by_subj = {}
    for pid, subj, name, score in all_points:
        pts_by_subj.setdefault(subj, []).append({"id": pid, "name": name, "score": score})
    errs_by_subj = {}
    for eid, subj, prof, qtext in pending_errors:
        errs_by_subj.setdefault(subj, []).append({"id": eid, "prof": prof, "question": qtext})

    subjects_out = []
    for subj in subject_names:
        kp = kp_stats.get(subj, {"total": 0, "avg": None, "unrated": 0, "mastered": 0, "weak": 0})
        eq = eq_stats.get(subj, {"cards": 0, "pending": 0, "reviewed": 0, "avg_prof": None, "last_err": None})
        pts = pts_by_subj.get(subj, [])
        to_learn = sum(1 for p in pts if p["score"] is None or p["score"] < 80)
        rated = [p for p in pts if p["score"] is not None and p["score"] >= 0]
        strongest = max(rated, key=lambda p: p["score"]) if rated else None
        # 推荐记忆：未评估优先，再按掌握度升序，最多 3 个
        unrated_pts = [p for p in pts if p["score"] is None or p["score"] < 0]
        ranked = unrated_pts + sorted(rated, key=lambda p: p["score"])
        rec_points = []
        for p in ranked[:3]:
            reason = "尚未评估掌握度，先测一测" if p["score"] is None or p["score"] < 0 else f"掌握度仅 {p['score']}%，待加强"
            rec_points.append({"id": p["id"], "name": p["name"], "score": p["score"], "reason": reason})
        # 推荐复习错题：熟练度升序（null 视作最弱排前），最多 3 条
        perrs = errs_by_subj.get(subj, [])
        ordered = sorted(perrs, key=lambda e: (e["prof"] is not None, e["prof"] if e["prof"] is not None else 0))
        rec_errors = [{"id": e["id"], "question": e["question"][:90],
                       "proficiency": e["prof"]}
                      for e in ordered[:3]]
        for i, r in enumerate(rec_errors):
            prof_txt = "未记录熟练度" if r["proficiency"] is None or r["proficiency"] < 0 else f"熟练度 {r['proficiency']}%"
            r["reason"] = f"待复习错题 · {prof_txt}" + ("，建议优先" if i == 0 else "")
        subjects_out.append({
            "subject": subj,
            "knowledge_total": kp["total"],
            "to_learn_count": to_learn,
            "unrated_count": kp["unrated"],
            "mastered_count": kp["mastered"],
            "weak_count": kp["weak"],
            "avg_mastery": round(kp["avg"]) if kp["avg"] is not None else None,
            "error_cards": eq["cards"],
            "errors_pending": eq["pending"],
            "errors_reviewed": eq["reviewed"],
            "avg_error_proficiency": round(eq["avg_prof"]) if eq["avg_prof"] is not None else None,
            "last_error_time": eq["last_err"],
            "strongest_point": {"id": strongest["id"], "name": strongest["name"], "score": strongest["score"]} if strongest else None,
            "weakest_point": ({"id": ranked[0]["id"], "name": ranked[0]["name"], "score": ranked[0]["score"]} if ranked else None),
            "most_frequent_error": most_freq_by_subj.get(subj),
            "recommend_points": rec_points,
            "recommend_errors": rec_errors,
        })

    summary = {
        "subjects": len(subject_names),
        "to_learn_total": sum(s["to_learn_count"] for s in subjects_out),
        "error_cards_total": sum(s["error_cards"] for s in subjects_out),
        "errors_pending_total": sum(s["errors_pending"] for s in subjects_out),
    }
    return _ok({"success": True, "subjects": subjects_out, "summary": summary})


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


@kb_bp.route("/api/knowledge/points/<int:pid>", methods=["DELETE"])
@require_auth
def knowledge_point_delete(pid):
    """知识点删除（知识库管理增强）：关联错题自动解绑保留，流水历史保留。"""
    ok = get_kms().delete_knowledge_point(pid, user_id=g.user_id)
    if not ok:
        return _err("知识点不存在或无权访问", 404)
    return _ok({"deleted": True})


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


@kb_bp.route("/api/kb/errors", methods=["POST"])
@require_auth
def create_manual_error():
    """手动新增独立错题（题干为 MD，图片用 vault 相对路径引用）。
    影子练习记录架构：同事务写 practice_records + error_questions(source='manual')。"""
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject_name") or "").strip()
    question = (body.get("question") or "").strip()
    kp_id = body.get("knowledge_point_id")
    if not subject:
        return _err("subject_name 不能为空", 400)
    if not question:
        return _err("题干不能为空", 400)
    if kp_id is not None:
        try:
            kp_id = int(kp_id)
        except (TypeError, ValueError):
            return _err("knowledge_point_id 非法", 400)
        conn = get_kms().db_manager.get_connection()
        try:
            # 归属学科一并校验：防跨学科绑点造成「按科目/按知识点」两条查询链路视图不一致（CodeReview Minor-6）
            row = conn.execute(
                "SELECT id FROM knowledge_points WHERE id = ? AND user_id = ? AND subject_name = ?",
                (kp_id, g.user_id, subject)).fetchone()
        finally:
            conn.close()
        if not row:
            return _err("知识点不存在、不属于该学科或无权访问", 404)
    else:
        kp_id = None
    kms = get_kms()
    kms.add_subject(subject, user_id=g.user_id)  # 科目不存在时自动建（与 point-new 同口径）
    eid = kms.save_manual_error(
        subject, question,
        correct_answer=(body.get("correct_answer") or None),
        explanation=(body.get("explanation") or None),
        knowledge_point_id=kp_id, user_id=g.user_id)
    if eid is None:
        return _err("错题保存失败", 500)
    log.log("api", "create_manual_error", "success", {"eid": eid, "subject": subject, "kp": kp_id})
    return _ok({"id": eid})


@kb_bp.route("/api/kb/errors/<int:eid>/unbind", methods=["POST"])
@require_auth
def error_unbind_kp(eid):
    """错题与知识点解绑：错题变独立（知识点页不再展示，科目错题列表仍在）。"""
    ok = get_kms().unbind_error_knowledge_point(eid, user_id=g.user_id)
    if not ok:
        return _err("错题不存在或无权访问", 404)
    return _ok({"unbound": True})


# ---------------------------------------------------------------- 错题图片 OCR 识别
@kb_bp.route("/api/kb/error-ocr", methods=["POST"])
@require_auth
def error_ocr_start():
    """提交错题图片识别（异步）：body {image: vault 相对路径} → task_id。
    图片由前端先经 /api/vault/screenshot 上传落盘；服务不可用时任务以 error 结束，前端降级手填。"""
    from services import error_ocr
    body = request.get_json(silent=True) or {}
    rel = (body.get("image") or "").strip()
    target = _safe_vault_path(g.user_id, rel)
    if target is None or not target.is_file():
        return _err("图片不存在或路径非法", 400)
    if not error_ocr.is_image(target.name):
        return _err("仅支持图片文件识别", 400)
    task_id = error_ocr.start_ocr(str(target), user_id=g.user_id)
    return _ok({"task_id": task_id})


@kb_bp.route("/api/kb/error-ocr/<task_id>", methods=["GET"])
@require_auth
def error_ocr_result(task_id):
    from services import error_ocr
    res = error_ocr.get_result(task_id, user_id=g.user_id)
    if res is None:
        return _err("识别任务不存在或已过期，请重新提交", 404)
    return _ok(res)


# ---------------------------------------------------------------- 错题智能分析（图片+文字 → 视觉大模型整理，2026-10-13）
@kb_bp.route("/api/kb/error-analyze", methods=["POST"])
@require_auth
def error_analyze_start():
    """提交智能分析（异步）：body {content: 题干 MD} → task_id。
    MD 内图片路径逐个过 _safe_vault_path；任一非法即整体 400（用户应看到明确错误而非静默跳过）。"""
    from services import error_analyze
    body = request.get_json(silent=True) or {}
    content = str(body.get("content") or "")
    items = []
    for rel in error_analyze.md_image_paths(content):
        target = _safe_vault_path(g.user_id, rel)
        if target is None or not target.is_file():
            return _err(f"引用的图片不存在或路径非法：{rel}", 400)
        items.append((rel, str(target)))
    if not content.strip() and not items:
        return _err("没有可分析的内容", 400)
    task_id = error_analyze.start_analyze(content, items, user_id=g.user_id)
    log.log("api", "error_analyze_start", "success", {"task": task_id, "imgs": len(items)})
    return _ok({"task_id": task_id})


@kb_bp.route("/api/kb/error-analyze/<task_id>", methods=["GET"])
@require_auth
def error_analyze_result(task_id):
    """轮询智能分析结果；done 后 TTL 内可重复读取（前端处理异常可重试）。"""
    from services import error_analyze
    res = error_analyze.get_result(task_id, user_id=g.user_id)
    if res is None:
        return _err("分析任务不存在或已过期，请重新提交", 404)
    return _ok(res)


# ---------------------------------------------------------------- 手机拍照传图（错题录入，2026-10-13）
@kb_bp.route("/api/kb/photo-session", methods=["POST"])
@require_auth
def photo_session_create():
    """创建一次性手机传图会话：返回 token + 可扫码地址候选（局域网 IP × 小服务端口，附公网前缀）。"""
    from services import photo_drop
    body = request.get_json(silent=True) or {}
    port = photo_drop.current_port()
    if port is None:
        return _err("手机传图服务未启动（端口 9900-9999 全占用或已禁用）", 503)
    token = photo_drop.create_session(g.user_id, (body.get("subject") or "").strip())
    paths = {"page": f"/c/{token}"}
    lan = photo_drop.lan_ip_candidates()
    public = (_cfg.PHOTO_PUBLIC_BASE or "").rstrip("/")
    log.log("api", "photo_session_create", "success", {"token": token, "ips": lan[:3]})
    return _ok({"token": token, "port": port, "lan_ips": lan, "public_base": public, "paths": paths})


@kb_bp.route("/api/kb/photo-session/<token>", methods=["GET"])
@require_auth
def photo_session_poll(token):
    """PC 轮询取新图：?since=已收数量；非本人/失效一律 404（前端据此停轮询并提示）。"""
    from services import photo_drop
    since = max(0, request.args.get("since", default=0, type=int) or 0)  # 负值会致 images[-n:] 重复下发旧图（CodeReview m-2）
    res = photo_drop.touch(token, g.user_id, since)
    if res is None:
        return _err("会话已失效或不属于当前用户", 404)
    return _ok(res)


@kb_bp.route("/api/kb/photo-session/<token>", methods=["DELETE"])
@require_auth
def photo_session_close(token):
    """PC 关闭弹窗即失效：手机后续上传/打开页一律拒绝。"""
    from services import photo_drop
    photo_drop.close(token, g.user_id)
    return _ok({"closed": True})


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


# --------------------------------------------- 记忆内核共享：星值/手动熟练度/曲线/四档自评（kind=kp|error）
_FSR_KINDS = ("kp", "error")


@kb_bp.route("/api/kb/<kind>/<int:rid>/stars", methods=["POST"])
@require_auth
def fsr_set_stars(kind, rid):
    """调星唯一 HTTP 入口（知识点/错题共用）：入参为 0-10 存储分（星×2），服务端截断。"""
    if kind not in _FSR_KINDS:
        return _err("kind 必须为 kp 或 error", 400)
    body = request.get_json(silent=True) or {}
    dif, imp = body.get("difficulty"), body.get("importance")
    if dif is None and imp is None:
        return _err("difficulty/importance 至少给一项", 400)
    try:
        ok = F.set_stars(kind, rid, g.user_id, difficulty=dif, importance=imp)
    except (ValueError, TypeError) as e:
        return _err(f"星值非法: {e}", 400)
    if not ok:
        return _err("记录不存在或不属于当前用户", 404)
    return _ok({"updated": True})


@kb_bp.route("/api/kb/<kind>/<int:rid>/mastery_manual", methods=["POST"])
@require_auth
def fsr_set_mastery_manual(kind, rid):
    """滑杆手动设定熟练度（手动=最高优先级，持续至下次真实复习）。value 0-100 整数。"""
    if kind not in _FSR_KINDS:
        return _err("kind 必须为 kp 或 error", 400)
    body = request.get_json(silent=True) or {}
    try:
        ok = F.set_mastery_manual(kind, rid, g.user_id, body.get("value"))
    except ValueError as e:
        return _err(str(e), 400)
    if not ok:
        return _err("记录不存在或不属于当前用户", 404)
    return _ok({"mastery": int(body.get("value")), "manual": True})


@kb_bp.route("/api/kb/<kind>/<int:rid>/curve", methods=["GET"])
@require_auth
def fsr_proficiency_curve(kind, rid):
    """熟练度曲线：kp 含复习时点 retrievability；error 表无该列返回 None。"""
    if kind not in _FSR_KINDS:
        return _err("kind 必须为 kp 或 error", 400)
    # 与 stars/mastery_manual 统一 404 口径（不存在/非本人不得静默空曲线）
    if not F.entity_exists(kind, rid, g.user_id):
        return _err("记录不存在或不属于当前用户", 404)
    conn = get_kms().db_manager.get_connection()
    try:
        if kind == "kp":
            rows = conn.execute(
                "SELECT timestamp, mastery, retrievability FROM kp_proficiency_history "
                "WHERE knowledge_point_id = ? AND user_id = ? "
                "ORDER BY timestamp ASC, id ASC", (rid, g.user_id)).fetchall()
            pts = [{"ts": r[0], "mastery": int(r[1]), "retrievability": r[2]} for r in rows]
        else:
            rows = conn.execute(
                "SELECT eph.timestamp, eph.proficiency FROM error_proficiency_history eph "
                "JOIN error_questions eq ON eph.error_question_id = eq.id "
                "WHERE eph.error_question_id = ? AND eq.user_id = ? "
                "ORDER BY eph.timestamp ASC, eph.id ASC", (rid, g.user_id)).fetchall()
            pts = [{"ts": r[0], "mastery": int(r[1]), "retrievability": None} for r in rows]
    finally:
        conn.close()
    return _ok({"points": pts, "count": len(pts)})


@kb_bp.route("/api/kb/<kind>/<int:rid>/fsrs", methods=["GET"])
@require_auth
def fsr_entity_view(kind, rid):
    """记忆数据面板快照：星值/熟练度/状态/到期/手动标记（曲线端点的同伴只读入口）。"""
    if kind not in _FSR_KINDS:
        return _err("kind 必须为 kp 或 error", 400)
    info = F.get_fsrs_view(kind, rid, g.user_id)
    if info is None:
        return _err("记录不存在或不属于当前用户", 404)
    return _ok(info)


@kb_bp.route("/api/kb/<kind>/<int:rid>/rate", methods=["POST"])
@require_auth
def fsr_rate_entity(kind, rid):
    """翻卡四档自评（无卡片行的裸实体入口，与 /api/memory/cards/<id>/rate 同口径）。

    body {self_assessment: 'not_at_all'|'vague'|'familiar'|'perfect'} → F.apply_review。
    """
    if kind not in _FSR_KINDS:
        return _err("kind 必须为 kp 或 error", 400)
    body = request.get_json(silent=True) or {}
    key = (body.get("self_assessment") or "").strip()
    if key not in F.CARD_SELF_RATINGS:
        return _err("self_assessment 必须为 not_at_all/vague/familiar/perfect 之一", 400)
    new_st = F.apply_review(kind, rid, g.user_id, F.CARD_SELF_RATINGS[key])
    if new_st is None:
        return _err("记录不存在或不属于当前用户", 404)
    # 复习后读回熟练度展示值（评审 M-2：走公共函数，不跨模块访问私有表映射）
    mastery = F.get_mastery(kind, rid, g.user_id)
    log.log("api", "fsr_rate_entity", "success",
            {"kind": kind, "rid": rid, "self_assessment": key, "state": new_st["fsrs_state"], "mastery": mastery})
    return _ok({
        "kind": kind, "ref_id": rid, "self_assessment": key,
        "mastery": mastery, "state": new_st["fsrs_state"],
    })


@kb_bp.route("/api/kb/errors/<int:eid>", methods=["PUT"])
@require_auth
def error_update_content(eid):
    """P5 错题编辑：支持题干/选项（同步流水行）+ 正确答案/解析（同步错题行）。

    仅传 content 时保持旧行为（只改题干）；None/缺失字段不动。
    """
    body = request.get_json(silent=True) or {}
    ok = get_kms().update_error_question_content(
        eid, body.get("content", ""), user_id=g.user_id,
        options=body.get("options"), correct_answer=body.get("correct_answer"),
        explanation=body.get("explanation"))
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
    """P5 错题删除（确认制由前端把门）：purge 整题——错题行+熟练度历史+该知识点下同题干流水/收藏行。"""
    ok = get_kms().delete_error_question(eid, user_id=g.user_id, purge=True)
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
    if result is None:
        # 与脑图路由同口径（相似业务相似实现）：把“无知识点/LLM 无有效结构”的失败原因透传给前端
        return _err("学习路径生成失败：学科无知识点或 LLM 未返回有效结构", 500)
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
