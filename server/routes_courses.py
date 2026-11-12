# -*- coding: utf-8 -*-
"""目标导向学习（体系化课程）API 蓝图（2026-11-11）。

设计权威源：docs/superpowers/specs/2026-11-11-goal-driven-learning-design.md
- 五表：learning_goals / course_modules / course_lessons / course_tests / course_attempts；
- 响应统一 {success, data|error}（_ok/_err 现例），全部端点 @require_auth，
  所有 SQL 一律 user_id 双条件隔离；
- LLM 编排全部收敛在 services/course_service（_llm 单缝自动计费）；
  积分不足 → 402 + credits_insufficient（照 routes_notes 现例）；
  生成/校验失败 → 不落任何脏数据行（LLM 输出不可信原则）；
- 删除目标级联清五表关联行；practice_records / error_questions 是独立资产，不动（Spec §5）。
"""
from __future__ import annotations

import json

from flask import Blueprint, g, jsonify, request

from auth import require_auth
from config import load_config
import credits_service as cr
from logger_module import debug_logger as log
from routes_knowledge import get_kms, _ok, _err
from services import course_service as cs
from services import board_explainer as BE
from services import fsrs_service as F

courses_bp = Blueprint("courses", __name__)


def _conn():
    return get_kms().db_manager.get_connection()


# ---------------------------------------------------------------- DB 私有函数（后续任务沿用）

def _goal_row(conn, goal_id, user_id):
    """按 id+user_id 双条件取目标行；不存在返回 None（越权同 404 语义）。"""
    row = conn.execute(
        "SELECT id, subject_name, goal_text, status, created_time "
        "FROM learning_goals WHERE id = ? AND user_id = ?", (goal_id, str(user_id))).fetchone()
    return dict(zip(("id", "subject_name", "goal_text", "status", "created_time"), row)) if row else None


def _tree_rows(conn, goal_id, user_id):
    """课程树：模块（按 ord）→ 课文（按 ord）。跨用户 goal_id 查不到即空树。

    返回 (modules, progress)；progress = {done, total}（done 口径 status=='done'）。"""
    mods = []
    total = done = 0
    for mid, mord, mtitle, mdesc in conn.execute(
            "SELECT m.id, m.ord, m.title, m.description FROM course_modules m "
            "JOIN learning_goals g ON m.goal_id = g.id "
            "WHERE g.id = ? AND g.user_id = ? ORDER BY m.ord", (goal_id, str(user_id))).fetchall():
        lessons = []
        for (lid, lord, ltitle, ldesc, est, st, cmode, pscore, regen) in conn.execute(
                "SELECT id, ord, title, description, est_minutes, status, content_mode, "
                "pretest_score, regen_count FROM course_lessons WHERE module_id = ? ORDER BY ord",
                (mid,)).fetchall():
            lessons.append({"id": lid, "ord": lord, "title": ltitle, "description": ldesc,
                            "est_minutes": est, "status": st, "content_mode": cmode,
                            "pretest_score": pscore, "regen_count": regen})
            total += 1
            if st == "done":
                done += 1
        mods.append({"id": mid, "ord": mord, "title": mtitle, "description": mdesc,
                     "lessons": lessons})
    return mods, {"done": done, "total": total}


def subject_open_lesson_count(conn, user_id, subject_name) -> int:
    """该学科下未完成（status != 'done'）的课程课文数（学科删除防护用，Spec §9）。"""
    return conn.execute(
        "SELECT COUNT(1) FROM course_lessons l "
        "JOIN course_modules m ON l.module_id = m.id "
        "JOIN learning_goals g ON m.goal_id = g.id "
        "WHERE g.user_id = ? AND g.subject_name = ? AND l.status <> 'done'",
        (str(user_id), subject_name)).fetchone()[0]


# ---------------------------------------------------------------- 目标 API

@courses_bp.route("/api/course/goals", methods=["GET"])
@require_auth
def list_goals():
    rows = _conn().execute(
        "SELECT id, subject_name, goal_text, status, created_time FROM learning_goals "
        "WHERE user_id = ? ORDER BY id DESC", (str(g.user_id),)).fetchall()
    return _ok({"goals": [dict(zip(("id", "subject_name", "goal_text", "status", "created_time"), r))
                          for r in rows]})


@courses_bp.route("/api/course/goals", methods=["POST"])
@require_auth
def create_goal():
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject_name") or "").strip()
    goal_text = (body.get("goal_text") or "").strip()
    if not subject:
        return _err("subject_name 不能为空", 400)
    if len(goal_text) < 4:
        return _err("goal_text 至少 4 个字", 400)
    kms = get_kms()
    # 学科不存在则自动建档（目标归属学科是用户直觉操作，不设前置门槛）
    if not kms.create_subject(subject, user_id=g.user_id):
        conn = _conn()
        try:
            exists = conn.execute("SELECT 1 FROM user_subjects WHERE user_id=? AND subject_name=?",
                                  (str(g.user_id), subject)).fetchone()
        finally:
            conn.close()
        if not exists:
            return _err("学科创建失败", 500)
    # 已有知识点概览供提示词衔接（避免与已学内容重复编排）
    conn = _conn()
    try:
        kps = [r[0] for r in conn.execute(
            "SELECT point_name FROM knowledge_points WHERE user_id=? AND subject_name=? LIMIT 200",
            (str(g.user_id), subject)).fetchall()]
    finally:
        conn.close()
    try:
        structure = cs.generate_course_structure(goal_text, subject, kps)
    except cr.InsufficientCreditsError as e:
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except cs.CourseError as e:
        log.log_error("course", "create_goal", e, {"uid": str(g.user_id), "subject": subject})
        return _err(f"课程结构生成失败: {e}", 502)
    except Exception as e:  # noqa: BLE001 LLM 链路异常不落脏数据
        log.log_error("course", "create_goal", f"uid={g.user_id} err={e}")
        return _err(f"课程生成失败: {e}", 500)
    # 单事务落库：goals → modules → lessons（校验已通过，此处不会产出脏结构）
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO learning_goals (user_id, subject_name, goal_text, status) VALUES (?,?,?,'ready')",
            (str(g.user_id), subject, goal_text))
        goal_id = cur.lastrowid
        for mo, m in enumerate(structure["modules"], 1):
            cur = conn.execute(
                "INSERT INTO course_modules (goal_id, ord, title, description) VALUES (?,?,?,?)",
                (goal_id, mo, m["title"], m["description"]))
            mid = cur.lastrowid
            for lo, l in enumerate(m["lessons"], 1):
                conn.execute(
                    "INSERT INTO course_lessons (module_id, ord, title, description, est_minutes) "
                    "VALUES (?,?,?,?,?)",
                    (mid, lo, l["title"], l["description"], l["est_minutes"]))
        conn.commit()
        goal = _goal_row(conn, goal_id, g.user_id)
        mods, progress = _tree_rows(conn, goal_id, g.user_id)
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        log.log_error("course", "create_goal_persist", e, {"uid": str(g.user_id)})
        return _err(f"课程落库失败: {e}", 500)
    finally:
        conn.close()
    log.log_success("course", "create_goal",
                    {"uid": str(g.user_id), "goal": goal_id, "modules": len(mods)})
    return _ok({"goal": goal, "modules": mods, "progress": progress})


@courses_bp.route("/api/course/goals/<int:goal_id>", methods=["DELETE"])
@require_auth
def delete_goal(goal_id):
    conn = _conn()
    try:
        if not _goal_row(conn, goal_id, g.user_id):
            return _err("目标不存在", 404)
        # 级联五表：attempts/tests 按 lesson/module/goal 归属删，再 lessons→modules→goal；
        # practice_records / error_questions 为独立学习资产，随目标删除不动（Spec §5）
        conn.execute("DELETE FROM course_attempts WHERE goal_id = ? AND user_id = ?",
                     (goal_id, str(g.user_id)))
        conn.execute(
            "DELETE FROM course_tests WHERE lesson_id IN (SELECT l.id FROM course_lessons l "
            "JOIN course_modules m ON l.module_id = m.id WHERE m.goal_id = ?)", (goal_id,))
        conn.execute("DELETE FROM course_tests WHERE module_id IN "
                     "(SELECT id FROM course_modules WHERE goal_id = ?)", (goal_id,))
        conn.execute(
            "DELETE FROM course_lessons WHERE module_id IN "
            "(SELECT id FROM course_modules WHERE goal_id = ?)", (goal_id,))
        conn.execute("DELETE FROM course_modules WHERE goal_id = ?", (goal_id,))
        conn.execute("DELETE FROM learning_goals WHERE id = ? AND user_id = ?",
                     (goal_id, str(g.user_id)))
        conn.commit()
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        return _err(f"删除失败: {e}", 500)
    finally:
        conn.close()
    return _ok({"deleted": True})


@courses_bp.route("/api/course/goals/<int:goal_id>/tree", methods=["GET"])
@require_auth
def goal_tree(goal_id):
    conn = _conn()
    try:
        goal = _goal_row(conn, goal_id, g.user_id)
        if not goal:
            return _err("目标不存在", 404)
        mods, progress = _tree_rows(conn, goal_id, g.user_id)
    finally:
        conn.close()
    return _ok({"goal": goal, "modules": mods, "progress": progress})


@courses_bp.route("/api/course/goals/<int:goal_id>/attempts", methods=["GET"])
@require_auth
def goal_attempts(goal_id):
    """成绩历史列表（Spec §5；详情用 detail_json，骨架阶段先取列表行）。"""
    conn = _conn()
    try:
        if not _goal_row(conn, goal_id, g.user_id):
            return _err("目标不存在", 404)
        rows = conn.execute(
            "SELECT id, test_id, kind, lesson_title, score, created_time, detail_json "
            "FROM course_attempts WHERE goal_id = ? AND user_id = ? ORDER BY id DESC LIMIT 200",
            (goal_id, str(g.user_id))).fetchall()
    finally:
        conn.close()
    keys = ("id", "test_id", "kind", "lesson_title", "score", "created_time", "detail_json")
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        dj = d.pop("detail_json")
        try:
            d["detail"] = json.loads(dj) if dj else None
        except (TypeError, ValueError):
            d["detail"] = None  # 明细损坏不阻断列表（历史行降级只展示得分）
        out.append(d)
    return _ok({"attempts": out})


# ---------------------------------------------------------------- 判分落库链（Task 6，R3/R7）

def _resolve_kp_id(conn, user_id, subject, kp_name):
    """题目标 kp_name → 既有知识点 id（精确名 → 相似度阈值内 → 自动建档）。

    返回 (kp_id, created)。相似匹配复用公共函数 similarity_matcher.rank_matches，
    阈值与设页/智能难度同口径（config.similarity_min_score，默认 0.35）；
    建档行 core_description 固定标注来源，mastery_score 初始 50（中性）。"""
    name = (kp_name or "").strip()
    if not name:
        return None, False
    row = conn.execute(
        "SELECT id FROM knowledge_points WHERE user_id=? AND subject_name=? AND point_name=?",
        (str(user_id), subject, name)).fetchone()
    if row:
        return row[0], False
    rows = conn.execute(
        "SELECT id, point_name, core_description FROM knowledge_points "
        "WHERE user_id=? AND subject_name=?",
        (str(user_id), subject)).fetchall()
    if rows:
        kps = [{"id": r[0], "point_name": r[1], "core_description": r[2] or ""} for r in rows]
        cfg = load_config()
        from similarity_matcher import rank_matches  # 延迟导入（embedding 依赖，同 routes_bridge 现例）
        ranked = rank_matches(question=name, knowledge_points=kps, cfg=cfg,
                              top_k=1, min_score=float(cfg.get("similarity_min_score", 0.35)))
        if ranked:
            return ranked[0]["id"], False
    cur = conn.execute(
        "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) "
        "VALUES (?,?,?,?,50)",
        (str(user_id), subject, name, f"目标导向学习自动建档：{name}"))
    return cur.lastrowid, True


def grade_pack(user_id, subject, pack, answers, kind=None, goal_id=None, test_id=None,
               lesson_title=""):
    """题包判分 + 全链路落库（与 practice-submit/error-set-submit 同口径，禁止另发明）：

    逐题：kp 解析（建档失败不阻断，kp_id=None 仍写流水）→ save_practice_record
    （答错自动入池、同题不堆行由该函数内部处理）→ 错题行 'error' FSRS；
    整批：kp 按组折叠一次 'kp' FSRS（min rating + 实测正确率封顶）；
    传 goal_id/test_id/kind 时追加 course_attempts 一行；判分后失效脑图/学习路径缓存。

    返回 {score, per_question:[{stem, options, user_answer, correct_answer_index,
    is_correct, kp_name, explanation}], mode}。answers 非法抛 ValueError（路由层 400）。"""
    if not isinstance(answers, list) or len(answers) != len(pack):
        raise ValueError("answers 数量与题包不匹配")
    for a in answers:
        if isinstance(a, bool) or not isinstance(a, int) or not 0 <= a <= 3:
            raise ValueError(f"答案选项非法: {a!r}")
    kms = get_kms()
    now = F.utcnow()  # 同一批共用时钟，保证状态机链式推演一致
    conn = _conn()
    per_question = []
    kp_groups = {}  # kp_id -> {ratings, correct, total}（整组折叠一次复习）
    memo = {}       # kp_name -> kp_id（同题包同名只解析一次）
    try:
        for q, ans in zip(pack, answers):
            opts = q["options"]
            ok = ans == q["answer_index"]
            rating = F.rating_from_practice(ok)
            kp_name = q.get("kp_name") or ""
            if kp_name in memo:
                kp_id = memo[kp_name]
            else:
                try:
                    kp_id, _created = _resolve_kp_id(conn, user_id, subject, kp_name)
                    conn.commit()
                except Exception as e:  # noqa: BLE001 建档失败不阻断落库（Spec R3）
                    kp_id = None
                    conn.rollback()
                    log.log_error("course", "grade_kp_resolve", e, {"kp": kp_name})
                memo[kp_name] = kp_id
            rec_id = None
            try:
                rec_id = kms.practice_manager.save_practice_record(
                    subject, kp_id, q["stem"], opts[ans], ok, str(user_id),
                    opts[q["answer_index"]], q.get("explanation", ""),
                    question_type="single", options=list(opts), difficulty_score=None)
            except Exception as e:  # noqa: BLE001 单题流水失败不中断整批（同 bridge 现例）
                log.log_error("course", "grade_persist", e, {"stem": q["stem"][:60]})
            if not ok and rec_id:
                try:
                    eid = kms.practice_manager.get_error_id_for_record(rec_id, str(user_id))
                    if eid:
                        F.apply_review("error", eid, str(user_id), rating, now=now)
                except Exception as e:  # noqa: BLE001
                    log.log_error("course", "grade_error_fsrs", e, {"rec": rec_id})
            if kp_id is not None:
                grp = kp_groups.setdefault(kp_id, {"ratings": [], "correct": 0, "total": 0})
                grp["ratings"].append(rating)
                grp["total"] += 1
                grp["correct"] += 1 if ok else 0
            per_question.append({"stem": q["stem"], "options": opts, "user_answer": ans,
                                 "correct_answer_index": q["answer_index"], "is_correct": ok,
                                 "kp_name": kp_name, "explanation": q.get("explanation", "")})
        # ---- kp 分组折叠更新（不共享事务：单条失败不污染已提交流水，同 error-set-submit m-1）----
        for kp_id, grp in kp_groups.items():
            if not grp["ratings"]:
                continue
            acc = grp["correct"] / grp["total"]
            try:
                F.apply_review("kp", kp_id, str(user_id), min(grp["ratings"]), now=now,
                               mastery_cap=round(100 * acc))
            except Exception as e:  # noqa: BLE001
                log.log_error("course", "grade_kp_fsrs", e, {"kp": kp_id})
        correct_count = sum(1 for p in per_question if p["is_correct"])
        score = correct_count / len(pack) if pack else 0.0
        if kind is not None and goal_id is not None and test_id is not None:
            conn.execute(
                "INSERT INTO course_attempts (user_id, goal_id, test_id, kind, lesson_title, score, detail_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (str(user_id), goal_id, test_id, kind, lesson_title or "", score,
                 json.dumps({"per_question": per_question}, ensure_ascii=False)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    # 掌握度已变化：失效该学科脑图/学习路径缓存（同 routes_bridge 现例，不阻断）
    for fn in (kms.clear_mindmap_cache, kms.clear_learning_path_cache):
        try:
            fn(subject, user_id=str(user_id))
        except Exception:  # noqa: BLE001
            pass
    return {"score": score, "per_question": per_question, "mode": cs.decide_mode(score)}


# ---------------------------------------------------------------- 课文闭环端点（Task 7）

_L_KEYS = ("id", "module_id", "ord", "title", "description", "est_minutes", "status",
           "content_md", "content_mode", "pretest_score", "regen_count", "done_time",
           "goal_id", "subject_name")


def _lesson_ctx(conn, lid, user_id):
    """课文 + 归属链（module/goal）一次性取出；user_id 双条件隔离，越权返回 None。"""
    row = conn.execute(
        "SELECT l.id, l.module_id, l.ord, l.title, l.description, l.est_minutes, l.status, "
        "l.content_md, l.content_mode, l.pretest_score, l.regen_count, l.done_time, "
        "m.goal_id, g.subject_name "
        "FROM course_lessons l JOIN course_modules m ON l.module_id = m.id "
        "JOIN learning_goals g ON m.goal_id = g.id WHERE l.id = ? AND g.user_id = ?",
        (lid, str(user_id))).fetchone()
    return dict(zip(_L_KEYS, row)) if row else None


def _module_ctx(conn, mid, user_id):
    row = conn.execute(
        "SELECT m.id, m.goal_id, m.ord, m.title, m.description, g.subject_name "
        "FROM course_modules m JOIN learning_goals g ON m.goal_id = g.id "
        "WHERE m.id = ? AND g.user_id = ?", (mid, str(user_id))).fetchone()
    return dict(zip(("id", "goal_id", "ord", "title", "description", "subject_name"), row)) \
        if row else None


def _pub_questions(pack):
    """对外题包：剩 answer_index/explanation（答案与解析只在判分后回传）。"""
    return [{"stem": q["stem"], "options": q["options"], "kp_name": q["kp_name"]} for q in pack]


def _modexam_weak_points(conn, goal_id, user_id, limit=10):
    """模块考薄弱点（2026-11-12 用户裁定：模块考结果驱动后续课文生成）。

    同目标下每个题包只取最近一次模块考 attempt，收集答错的知识点名（去重、
    最近一次作答优先，上限 limit）；明细损坏的行降级跳过，不阻断生成。"""
    rows = conn.execute(
        "SELECT a.detail_json FROM course_attempts a "
        "WHERE a.goal_id = ? AND a.kind = 'moduleexam' AND a.user_id = ? "
        "  AND a.id = (SELECT MAX(b.id) FROM course_attempts b "
        "             WHERE b.goal_id = a.goal_id AND b.kind = 'moduleexam' "
        "               AND b.user_id = a.user_id AND b.test_id = a.test_id) "
        "ORDER BY a.id DESC", (goal_id, str(user_id))).fetchall()
    seen, out = set(), []
    for dj in [r[0] for r in rows]:
        # 评审M-1：遍历也纳入保护，合法 JSON 但结构异常的行同样降级跳过
        try:
            for p in json.loads(dj)["per_question"]:
                kp = (p.get("kp_name") or "").strip()
                if kp and not p.get("is_correct") and kp not in seen:
                    seen.add(kp)
                    out.append(kp)
                    if len(out) >= limit:
                        return out
        except Exception:  # noqa: BLE001 单行明细损坏不影响其余薄弱点收集
            continue
    return out


def _merged_weak(conn, goal_id, user_id, pretest_wrong):
    """前测错题 + 模块考薄弱点合并去重（前测在前），供课文生成 prompt 素材。"""
    seen, out = set(), []
    for kp in [str(x or "").strip() for x in (pretest_wrong or [])] \
            + _modexam_weak_points(conn, goal_id, user_id):
        if kp and kp not in seen:
            seen.add(kp)
            out.append(kp)
    return out


def _get_or_make_pack(conn, kind, lesson_id, module_id, source_text, n, title, subject):
    """题包幂等取用：已有直接复用（不重烧积分），没有才生成并入库。返回 (test_id, pack)。"""
    col = "lesson_id" if lesson_id is not None else "module_id"
    ref = lesson_id if lesson_id is not None else module_id
    row = conn.execute(
        f"SELECT id, questions_json FROM course_tests WHERE {col} = ? AND kind = ? "  # noqa: B950 列名白名单内
        "ORDER BY id DESC LIMIT 1", (ref, kind)).fetchone()
    if row:
        return row[0], json.loads(row[1])
    pack = cs.generate_test_pack(kind, source_text, n, title=title, subject=subject)
    cur = conn.execute(
        "INSERT INTO course_tests (kind, lesson_id, module_id, questions_json) VALUES (?,?,?,?)",
        (kind, lesson_id, module_id, json.dumps(pack, ensure_ascii=False)))
    conn.commit()
    return cur.lastrowid, pack


def _lesson_out(ctx):
    return {k: ctx[k] for k in ("id", "title", "description", "est_minutes", "status",
                                "content_md", "content_mode", "pretest_score", "regen_count",
                                "goal_id", "module_id", "subject_name")}


def _gen_guard(fn):
    """LLM 生成调用统一异常口径：402 积分 / 502 生成失败（与 create_goal 同式）。"""
    try:
        return fn(), None
    except cr.InsufficientCreditsError as e:
        return None, (jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                               "credit_balance": e.balance}), 402)
    except cs.CourseError as e:
        log.log_error("course", "gen_fail", e)
        return None, _err(f"生成失败: {e}", 502)


@courses_bp.route("/api/course/lessons/<int:lid>", methods=["GET"])
@require_auth
def lesson_detail(lid):
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
    finally:
        conn.close()
    if not ctx:
        return _err("课文不存在", 404)
    return _ok({"lesson": _lesson_out(ctx)})


@courses_bp.route("/api/course/lessons/<int:lid>/pretest", methods=["GET"])
@require_auth
def lesson_pretest_get(lid):
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
        if not ctx:
            return _err("课文不存在", 404)
        _, pack = _get_or_make_pack(conn, "pretest", lid, None,
                                    f"{ctx['title']}\n{ctx['description']}", 4,
                                    ctx["title"], ctx["subject_name"])
        tid = conn.execute("SELECT id FROM course_tests WHERE lesson_id=? AND kind='pretest' "
                           "ORDER BY id DESC LIMIT 1", (lid,)).fetchone()[0]
    except cr.InsufficientCreditsError as e:
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except cs.CourseError as e:
        log.log_error("course", "pretest_pack", e, {"lid": lid})
        return _err(f"前测出题失败: {e}", 502)
    finally:
        conn.close()
    return _ok({"test_id": tid, "kind": "pretest", "questions": _pub_questions(pack),
                **cr.billing_for_response()})


@courses_bp.route("/api/course/lessons/<int:lid>/pretest", methods=["POST"])
@require_auth
def lesson_pretest_submit(lid):
    body = request.get_json(silent=True) or {}
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
        if not ctx:
            return _err("课文不存在", 404)
        subject = ctx["subject_name"]
        if body.get("reset"):
            # Spec §9 重新前测：删旧题包重新生成（attempt 历史保留）；旧课文保留，可再重生成
            conn.execute("DELETE FROM course_tests WHERE lesson_id = ? AND kind = 'pretest'", (lid,))
            conn.commit()
            tid, pack = _get_or_make_pack(conn, "pretest", lid, None,
                                          f"{ctx['title']}\n{ctx['description']}", 4,
                                          ctx["title"], subject)
            return _ok({"test_id": tid, "kind": "pretest", "questions": _pub_questions(pack),
                        "credits_note": "重新前测已再次消耗积分；交卷后成绩重定详略，旧课文保留",
                        **cr.billing_for_response()})
        row = conn.execute("SELECT id, questions_json FROM course_tests "
                           "WHERE lesson_id = ? AND kind = 'pretest' ORDER BY id DESC LIMIT 1",
                           (lid,)).fetchone()
        if not row:
            return _err("请先获取前测题目", 409)
        tid, pack = row[0], json.loads(row[1])
        try:
            res = grade_pack(g.user_id, subject, pack, body.get("answers") or [],
                             kind="pretest", goal_id=ctx["goal_id"], test_id=tid,
                             lesson_title=ctx["title"])
        except ValueError as e:
            return _err(str(e), 400)
        conn.execute("UPDATE course_lessons SET pretest_score = ? WHERE id = ?",
                     (res["score"], lid))
        # 状态机软前进：仅首次（new）推 pretested；已越过则不回退（重新前测场景）
        if ctx["status"] == "new":
            cs.advance_lesson(conn, lid, g.user_id, "pretested")
        ctx2 = _lesson_ctx(conn, lid, g.user_id)
        if not ctx2["content_md"]:
            # 测完即出内容（一次请求，Spec §5）；已有课文不重生成不重烧积分
            # 2026-11-12 裁定：同目标模块考错题也作为薄弱点喂给生成
            wrong = _merged_weak(conn, ctx["goal_id"], g.user_id,
                                 [p["kp_name"] for p in res["per_question"] if not p["is_correct"]])
            md, err = _gen_guard(lambda: cs.generate_lesson_md(
                subject, ctx["title"], ctx["description"], res["mode"], wrong))
            if err:
                # 判分链（attempts/practice/FSRS）已由 grade_pack 自行提交，无法回滚：
                # 成绩与 pretested 状态照常落库，重试时走 POST /generate 补生成，
                # 避免重交前测造成重复判分与 FSRS 二次叠加（评审 Major-1）
                conn.commit()
                resp, code = err
                j = dict(resp.get_json() or {})
                j["success"] = False
                j["error"] = ("前测已判分并记录；课文生成失败：" + str(j.get("error") or "")
                              + "。请重新进入课文重试生成")
                return jsonify(j), code
            conn.execute("UPDATE course_lessons SET content_md = ?, content_mode = ? WHERE id = ?",
                         (md, res["mode"], lid))
            if ctx2["status"] in ("new", "pretested"):
                cs.advance_lesson(conn, lid, g.user_id, "content_ready")
        conn.commit()
        out = _lesson_out(_lesson_ctx(conn, lid, g.user_id))
    except cr.InsufficientCreditsError as e:
        # reset 分支重新出题走 LLM：积分不足同样 402（其余路径不烧积分）
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except cs.CourseError as e:
        log.log_error("course", "pretest_submit", e, {"lid": lid})
        return _err(f"前测处理失败: {e}", 502)
    finally:
        conn.close()
    log.log_success("course", "pretest_submit", {"lid": lid, "score": res["score"]})
    return _ok({"score": res["score"], "per_question": res["per_question"], "mode": res["mode"],
                "lesson": out, **cr.billing_for_response()})


@courses_bp.route("/api/course/lessons/<int:lid>/regenerate", methods=["POST"])
@require_auth
def lesson_regenerate(lid):
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
        if not ctx:
            return _err("课文不存在", 404)
        if not ctx["content_md"]:
            return _err("课文尚未生成，请先完成前测", 400)
        if ctx["regen_count"] >= 3:
            return _err("重生成次数已达上限（3 次）", 400)
        mode = ctx["content_mode"] or cs.decide_mode(ctx["pretest_score"] or 0.0)
        # 错题概念取最近一次前测 attempt（按题包归属到本课文）
        wrong = []
        arow = conn.execute(
            "SELECT a.detail_json FROM course_attempts a JOIN course_tests t ON a.test_id = t.id "
            "WHERE t.lesson_id = ? AND a.kind = 'pretest' AND a.user_id = ? ORDER BY a.id DESC LIMIT 1",
            (lid, str(g.user_id))).fetchone()
        if arow:
            wrong = [p["kp_name"] for p in json.loads(arow[0])["per_question"] if not p["is_correct"]]
        wrong = _merged_weak(conn, ctx["goal_id"], g.user_id, wrong)  # 模块考薄弱点一并喂给生成
        md, err = _gen_guard(lambda: cs.generate_lesson_md(
            ctx["subject_name"], ctx["title"], ctx["description"], mode, wrong))
        if err:
            return err
        conn.execute("UPDATE course_lessons SET content_md = ?, regen_count = regen_count + 1 "
                     "WHERE id = ?", (md, lid))
        conn.commit()
        out = _lesson_out(_lesson_ctx(conn, lid, g.user_id))
    finally:
        conn.close()
    log.log_success("course", "lesson_regen", {"lid": lid, "regen": out["regen_count"]})
    return _ok({"lesson": out, **cr.billing_for_response()})


@courses_bp.route("/api/course/lessons/<int:lid>/generate", methods=["POST"])
@require_auth
def lesson_generate_retry(lid):
    """前测已判分但课文生成失败后的补生成：不重复判分、不计重生成上限（评审 Major-1）。"""
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
        if not ctx:
            return _err("课文不存在", 404)
        if ctx["content_md"]:
            return _err("课文已在，如需更换版本请使用重生成", 400)
        if ctx["status"] != "pretested":
            return _err("无可补生成：请先完成前测", 409)
        mode = cs.decide_mode(ctx["pretest_score"] or 0.0)
        wrong = []
        arow = conn.execute(
            "SELECT a.detail_json FROM course_attempts a JOIN course_tests t ON a.test_id = t.id "
            "WHERE t.lesson_id = ? AND a.kind = 'pretest' AND a.user_id = ? ORDER BY a.id DESC LIMIT 1",
            (lid, str(g.user_id))).fetchone()
        if arow:
            try:
                wrong = [p["kp_name"] for p in json.loads(arow[0])["per_question"] if not p["is_correct"]]
            except Exception:  # noqa: BLE001 明细损坏降级为无薄弱点，不阻断补生成
                wrong = []
        wrong = _merged_weak(conn, ctx["goal_id"], g.user_id, wrong)  # 模块考薄弱点一并喂给生成
        md, err = _gen_guard(lambda: cs.generate_lesson_md(
            ctx["subject_name"], ctx["title"], ctx["description"], mode, wrong))
        if err:
            return err
        conn.execute("UPDATE course_lessons SET content_md = ?, content_mode = ? WHERE id = ?",
                     (md, mode, lid))
        cs.advance_lesson(conn, lid, g.user_id, "content_ready")
        conn.commit()
        out = _lesson_out(_lesson_ctx(conn, lid, g.user_id))
    finally:
        conn.close()
    log.log_success("course", "lesson_generate_retry", {"lid": lid, "mode": mode})
    return _ok({"lesson": out, **cr.billing_for_response()})


# ---------------------------------------------------------------- 课文图文结合（2026-11-12 用户裁定 A 方案）
# 两个常驻展示位（原理图/交互实验）：进页查产物直显（纯读库零扣分），
# 没有才点击开工（一次 LLM，之后同课文永久复用）。作业轮询复用黑板链
# GET /api/board/explain/<job_id>（同一张作业表，不复制路由）。

@courses_bp.route("/api/course/lessons/<int:lid>/visual", methods=["GET"])
@require_auth
def lesson_visual(lid):
    """两类课级产物当前状态：{principle: done视图|null, lab: 同}；无权限 404。"""
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
    finally:
        conn.close()
    if not ctx:
        return _err("课文不存在", 404)
    out = {k: BE.lesson_latest(g.user_id, lid, k) for k in BE.LESSON_VIS_KINDS}
    return _ok({"visual": out, "has_content": bool((ctx["content_md"] or "").strip())})


@courses_bp.route("/api/course/lessons/<int:lid>/visual/<kind>", methods=["POST"])
@require_auth
def lesson_visual_gen(lid, kind):
    """开一单课文级原理图/实验（body 可选 {refresh:true} 深度重画）。

    复用口径同黑板：库命中→reused="cache" 秒回零扣分；同槽位在飞→reused=true；
    正文未生成/kind 非法→拒收（不开工不扣分，200 带 success=false，黑板同纪律）。"""
    body = request.get_json(silent=True) or {}
    refresh = bool(body.get("refresh"))
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
    finally:
        conn.close()
    if not ctx:
        return _err("课文不存在", 404)
    r = BE.start_for_lesson(g.user_id, ctx, kind, refresh=refresh)
    if not r.get("success"):
        return jsonify({"success": False, "error": r.get("error") or "暂时开不了工，稍后再试"})
    return _ok({"job": r["job"], "reused": r.get("reused") or False})


@courses_bp.route("/api/course/lessons/<int:lid>/postquiz", methods=["GET"])
@require_auth
def lesson_postquiz_get(lid):
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
        if not ctx:
            return _err("课文不存在", 404)
        if not ctx["content_md"]:
            return _err("请先生成课文", 409)
        tid, pack = _get_or_make_pack(conn, "postquiz", lid, None,
                                      ctx["content_md"][:6000], 4, ctx["title"], ctx["subject_name"])
    except cr.InsufficientCreditsError as e:
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except cs.CourseError as e:
        log.log_error("course", "postquiz_pack", e, {"lid": lid})
        return _err(f"后练出题失败: {e}", 502)
    finally:
        conn.close()
    return _ok({"test_id": tid, "kind": "postquiz", "questions": _pub_questions(pack),
                **cr.billing_for_response()})


@courses_bp.route("/api/course/lessons/<int:lid>/postquiz", methods=["POST"])
@require_auth
def lesson_postquiz_submit(lid):
    body = request.get_json(silent=True) or {}
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
        if not ctx:
            return _err("课文不存在", 404)
        if not ctx["content_md"]:
            return _err("请先生成课文", 409)
        row = conn.execute("SELECT id, questions_json FROM course_tests "
                           "WHERE lesson_id = ? AND kind = 'postquiz' ORDER BY id DESC LIMIT 1",
                           (lid,)).fetchone()
        if not row:
            return _err("请先获取课后练习题", 409)
        try:
            res = grade_pack(g.user_id, ctx["subject_name"], json.loads(row[1]), body.get("answers") or [],
                             kind="postquiz", goal_id=ctx["goal_id"], test_id=row[0],
                             lesson_title=ctx["title"])
        except ValueError as e:
            return _err(str(e), 400)
        status = ctx["status"]
        if status in ("content_ready", "learned"):
            # 后练完成 → learned；done 留给 complete 端点（Task 12，读完+练完用户点完成）
            status = cs.advance_lesson(conn, lid, g.user_id, "learned")
        conn.commit()
    finally:
        conn.close()
    return _ok({"score": res["score"], "per_question": res["per_question"],
                "lesson_status": status, **cr.billing_for_response()})


@courses_bp.route("/api/course/lessons/<int:lid>/read", methods=["POST"])
@require_auth
def lesson_read(lid):
    conn = _conn()
    try:
        if not _lesson_ctx(conn, lid, g.user_id):
            return _err("课文不存在", 404)
        try:
            status = cs.advance_lesson(conn, lid, g.user_id, "learned")
        except cs.CourseError as e:
            return _err(str(e), 409)
        conn.commit()
    finally:
        conn.close()
    return _ok({"status": status})


@courses_bp.route("/api/course/modules/<int:mid>/exam", methods=["GET"])
@require_auth
def module_exam_get(mid):
    conn = _conn()
    try:
        mctx = _module_ctx(conn, mid, g.user_id)
        if not mctx:
            return _err("模块不存在", 404)
        lessons = conn.execute(
            "SELECT title, description FROM course_lessons WHERE module_id = ? ORDER BY ord",
            (mid,)).fetchall()
        source = "\n".join(f"- {t}: {d}" for t, d in lessons)
        tid, pack = _get_or_make_pack(conn, "moduleexam", None, mid, source, 8,
                                      mctx["title"], mctx["subject_name"])
    except cr.InsufficientCreditsError as e:
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except cs.CourseError as e:
        log.log_error("course", "exam_pack", e, {"mid": mid})
        return _err(f"模块考出题失败: {e}", 502)
    finally:
        conn.close()
    return _ok({"test_id": tid, "kind": "moduleexam", "questions": _pub_questions(pack),
                **cr.billing_for_response()})


@courses_bp.route("/api/course/modules/<int:mid>/exam", methods=["POST"])
@require_auth
def module_exam_submit(mid):
    body = request.get_json(silent=True) or {}
    conn = _conn()
    try:
        mctx = _module_ctx(conn, mid, g.user_id)
        if not mctx:
            return _err("模块不存在", 404)
        row = conn.execute("SELECT id, questions_json FROM course_tests "
                           "WHERE module_id = ? AND kind = 'moduleexam' ORDER BY id DESC LIMIT 1",
                           (mid,)).fetchone()
        if not row:
            return _err("请先获取模块考试题", 409)
        try:
            res = grade_pack(g.user_id, mctx["subject_name"], json.loads(row[1]),
                             body.get("answers") or [],
                             kind="moduleexam", goal_id=mctx["goal_id"], test_id=row[0],
                             lesson_title=mctx["title"])
        except ValueError as e:
            return _err(str(e), 400)
    finally:
        conn.close()
    # 模块考不改变课文状态（Spec §7：done 前也可考，只作参考）
    return _ok({"score": res["score"], "per_question": res["per_question"],
                **cr.billing_for_response()})


# ---------------------------------------------------------------- 扩展课程 + 课内问答（Task 11）

@courses_bp.route("/api/course/goals/<int:goal_id>/extend", methods=["POST"])
@require_auth
def extend_goal(goal_id):
    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip()
    if action not in ("add_module", "add_lesson"):
        return _err("action 须为 add_module 或 add_lesson", 400)
    conn = _conn()
    try:
        goal = _goal_row(conn, goal_id, g.user_id)
        if not goal:
            return _err("目标不存在", 404)
        mctx = None
        if action == "add_lesson":
            mid = body.get("module_id")
            if not mid:
                return _err("add_lesson 需要 module_id", 400)
            mctx = _module_ctx(conn, mid, g.user_id)
            if not mctx or mctx["goal_id"] != goal_id:
                return _err("模块不存在", 404)
        # 现有标题全量收集（去重约束交给服务层校验，此处只提供事实）
        existing = [r[0] for r in conn.execute(
            "SELECT title FROM course_modules WHERE goal_id = ? ORDER BY ord", (goal_id,)).fetchall()]
        existing += [r[0] for r in conn.execute(
            "SELECT l.title FROM course_lessons l JOIN course_modules m ON l.module_id = m.id "
            "WHERE m.goal_id = ? ORDER BY m.ord, l.ord", (goal_id,)).fetchall()]
    finally:
        conn.close()
    ext, err = _gen_guard(lambda: cs.generate_course_extension(
        goal["goal_text"], goal["subject_name"], existing, action,
        mctx["title"] if mctx else ""))
    if err:
        return err
    # 单事务追加落库：ord 续排，已有行一律不动（追加不覆盖，Spec §5）
    conn = _conn()
    try:
        if action == "add_module":
            mord = conn.execute("SELECT COALESCE(MAX(ord), 0) + 1 FROM course_modules "
                                 "WHERE goal_id = ?", (goal_id,)).fetchone()[0]
            for i, m in enumerate(ext["modules"]):
                cur = conn.execute(
                    "INSERT INTO course_modules (goal_id, ord, title, description) VALUES (?,?,?,?)",
                    (goal_id, mord + i, m["title"], m["description"]))
                mid_new = cur.lastrowid
                for lo, l in enumerate(m["lessons"], 1):
                    conn.execute(
                        "INSERT INTO course_lessons (module_id, ord, title, description, est_minutes) "
                        "VALUES (?,?,?,?,?)", (mid_new, lo, l["title"], l["description"], l["est_minutes"]))
        else:
            lo0 = conn.execute("SELECT COALESCE(MAX(ord), 0) + 1 FROM course_lessons "
                               "WHERE module_id = ?", (mctx["id"],)).fetchone()[0]
            for i, l in enumerate(ext["lessons"]):
                conn.execute(
                    "INSERT INTO course_lessons (module_id, ord, title, description, est_minutes) "
                    "VALUES (?,?,?,?,?)", (mctx["id"], lo0 + i, l["title"], l["description"], l["est_minutes"]))
        conn.commit()
        goal = _goal_row(conn, goal_id, g.user_id)
        mods, progress = _tree_rows(conn, goal_id, g.user_id)
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        log.log_error("course", "extend_persist", e, {"uid": str(g.user_id), "goal": goal_id})
        return _err(f"扩展落库失败: {e}", 500)
    finally:
        conn.close()
    log.log_success("course", "extend_goal", {"uid": str(g.user_id), "goal": goal_id, "action": action})
    return _ok({"goal": goal, "modules": mods, "progress": progress,
                **cr.billing_for_response()})


@courses_bp.route("/api/course/lessons/<int:lid>/chat", methods=["POST"])
@require_auth
def lesson_chat(lid):
    body = request.get_json(silent=True) or {}
    question = str(body.get("question") or "").strip()
    if not question:
        return _err("question 不能为空", 400)
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
    finally:
        conn.close()
    if not ctx:
        return _err("课文不存在", 404)
    if not ctx["content_md"]:
        return _err("课文学完正文后才能提问", 400)
    answer, err = _gen_guard(lambda: cs.generate_lesson_chat(
        ctx["subject_name"], ctx["title"], ctx["content_md"], body.get("history") or [], question))
    if err:
        return err
    return _ok({"answer": answer, **cr.billing_for_response()})


# ---------------------------------------------------------------- 提取确认 + 完成（Task 12，R4）

@courses_bp.route("/api/course/lessons/<int:lid>/extract", methods=["POST"])
@require_auth
def lesson_extract(lid):
    """从课文提取知识点候选（不入库）：解包口径同 routes_bridge 现例，
    入库确认走现有 POST /api/knowledge/confirm（前端确认后调用）。"""
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
    finally:
        conn.close()
    if not ctx:
        return _err("课文不存在", 404)
    if not ctx["content_md"]:
        return _err("请完成课文后再提取知识点", 400)
    kms = get_kms()
    try:
        result = kms.extract_and_process_knowledge_points(
            ctx["subject_name"], ctx["content_md"], user_id=str(g.user_id))
    except cr.InsufficientCreditsError as e:
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except Exception as e:  # noqa: BLE001 提取链异常不阻断语义
        log.log_error("course", "extract", e, {"lid": lid})
        return _err(f"知识点提取失败: {e}", 500)
    points = []
    for p in (result or {}).get("processed_points") or []:
        if not isinstance(p, dict):
            continue
        # processed_points 元素是包装结构 {extracted_point, similar_points, match_status}，
        # 真实字段在 extracted_point 内层（routes_bridge 同口径）
        ep = p.get("extracted_point")
        if not isinstance(ep, dict):
            ep = p
        points.append({
            "name": (ep.get("point_name") or ep.get("concept_name") or ep.get("name") or "").strip(),
            "description": (ep.get("core_description") or ep.get("core_definition") or ep.get("description") or "").strip(),
            "category": ep.get("category") or "核心概念",
            "importance": ep.get("importance") or "中等",
            "match_status": p.get("match_status") or "",
            "similar_count": len(p.get("similar_points") or []),
        })
    points = [pt for pt in points if pt["name"]]
    if not points:
        return _err("未能从课文提取到有效知识点", 400)
    return _ok({"points": points, **cr.billing_for_response()})


@courses_bp.route("/api/course/lessons/<int:lid>/complete", methods=["POST"])
@require_auth
def lesson_complete(lid):
    """标记本课完成（R4：读完+后练交卷才能 done）；done 重复请求幂等。"""
    conn = _conn()
    try:
        ctx = _lesson_ctx(conn, lid, g.user_id)
        if not ctx:
            return _err("课文不存在", 404)
        if ctx["status"] == "done":
            return _ok({"status": "done", "done_time": ctx["done_time"]})
        if ctx["status"] != "learned":
            return _err("请先完成课后小练习再标记完成", 409)
        arow = conn.execute(
            "SELECT 1 FROM course_attempts a JOIN course_tests t ON a.test_id = t.id "
            "WHERE t.lesson_id = ? AND a.kind = 'postquiz' AND a.user_id = ? LIMIT 1",
            (lid, str(g.user_id))).fetchone()
        if not arow:
            return _err("需要至少一次课后小练习交卷记录才能标记完成", 409)
        try:
            status = cs.advance_lesson(conn, lid, g.user_id, "done")
        except cs.CourseError as e:
            return _err(str(e), 409)
        conn.commit()
        out = _lesson_ctx(conn, lid, g.user_id)
    finally:
        conn.close()
    log.log_success("course", "lesson_complete", {"lid": lid, "uid": str(g.user_id)})
    return _ok({"status": status, "done_time": out["done_time"]})
