# -*- coding: utf-8 -*-
"""记忆库卡片（memory-cards）REST 蓝图 —— feat/memory-cards 分支（2026-09-28）

职责：
- 卡片 CRUD：把知识点/错题标注入记忆库（正/反面快照），幂等入库；
- 卡片复习自评：4 档自评 → FSRS apply_review（单卡即单事件，不折叠）；
- 推荐学习：用 fsrs_service.build_sprint_pool / question_difficulty_mix 组卷。

约束（方案 §2.2/§3/§5.1）：
- 全部 @require_auth，查询/写入强制带 user_id 隔离；
- memory_cards 表已存在，UNIQUE(user_id,card_type,ref_id)，重复插入 INSERT OR IGNORE
  （适配层翻译为 ON CONFLICT DO NOTHING，幂等）；
- 熟练度/状态唯一写入口 = fsrs_service（本模块只调用，不直写 mastery 列）；
- 响应统一 {success, data|error}。

本端点 /api/memory/cards 为兄弟分支 kp-polish「确认页标注入记忆库」依赖的契约，
路径与字段严格固定，勿改。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from auth import require_auth
from logger_module import debug_logger as log
from services import fsrs_service as F

memory_bp = Blueprint("memory", __name__)

# 卡片类型 → 关联实体表/列口径（与 fsrs_service._KINDS 对齐）
_KINDS = {
    "kp": {
        "table": "knowledge_points",
        "mastery_col": "mastery_score",
        "front_col": "point_name",
        "back_col": "core_description",
    },
    "error": {
        "table": "error_questions",
        "mastery_col": "current_proficiency",
        "front_col": "question_content",
        "back_col": "correct_answer",
    },
}


def _get_conn():
    from routes_knowledge import get_kms
    return get_kms().db_manager.get_connection()


def _ok(data=None, **extra):
    body = {"success": True, "data": data}
    body.update(extra)
    return jsonify(body)


def _err(message, code=500):
    return jsonify({"success": False, "error": str(message)}), code


# ---------------------------------------------------------------- 实体读取辅助
def _load_entity(conn, kind, ref_id, user_id):
    """读取关联实体（subject_name + 正反面源文本 + 熟练度 + FSRS 状态）。

    不存在/非本人返回 None。返回 dict：
      subject_name, front_src, back_src, back_alt, mastery, state, difficulty_score, importance_score
    """
    spec = _KINDS[kind]
    row = conn.execute(
        f"SELECT subject_name, {spec['front_col']}, {spec['back_col']}, "
        f"{spec['mastery_col']}, difficulty_score, importance_score "
        f"FROM {spec['table']} WHERE id = ? AND user_id = ?",
        (ref_id, user_id)).fetchone()
    if row is None:
        return None
    # 错题背面兜底：correct_answer 为空时用 explanation
    back_alt = None
    if kind == "error":
        b2 = conn.execute(
            "SELECT explanation FROM error_questions WHERE id = ? AND user_id = ?",
            (ref_id, user_id)).fetchone()
        back_alt = b2[0] if b2 else None
    st = F.load_state(conn, kind, ref_id, user_id)
    return {
        "subject_name": row[0],
        "front_src": row[1],
        "back_src": row[2],
        "back_alt": back_alt,
        "mastery": F.mastery_view(row[3]),
        "difficulty_score": float(row[4]) if row[4] is not None else 5.0,
        "importance_score": float(row[5]) if row[5] is not None else 5.0,
        "state": st,
    }


def _default_snapshot(kind, ref_id, ent):
    """按实体生成正/反面快照：正面=题干/名称，背面=答案/描述。"""
    front = (ent["front_src"] or "").strip()
    if not front:
        front = ("知识点" if kind == "kp" else "错题") + f" #{ref_id}"
    back = (ent["back_src"] or "").strip() if ent["back_src"] else ""
    if not back and ent.get("back_alt"):
        back = (ent["back_alt"] or "").strip()
    if not back:
        back = (ent["front_src"] or "").strip()  # kp 无独立答案列，背面复用核心描述
    if not back:
        back = "（暂无内容）"
    return front, back


def _card_row_to_dict(conn, card_row, user_id):
    """memory_cards 行 → 列表/详情 dict（含关联实体熟练度摘要）。

    card_row 需含：id, card_type, ref_id, subject_name, front_text, back_text, added_time。
    """
    kind = card_row[1]
    ref_id = card_row[2]
    ent = _load_entity(conn, kind, ref_id, user_id)
    out = {
        "id": card_row[0],
        "card_type": kind,
        "ref_id": ref_id,
        "subject_name": card_row[3],
        "front_text": card_row[4],
        "back_text": card_row[5],
        "added_time": card_row[6],
        "entity_exists": ent is not None,
        "mastery": (ent["mastery"] if ent else -1),
        "difficulty_score": (ent["difficulty_score"] if ent else 5.0),
        "importance_score": (ent["importance_score"] if ent else 5.0),
        "retrievability": (round(F.row_retrievability(ent["state"] or {}), 4) if ent else 0.0),
    }
    return out


_CARD_COLS = "id, card_type, ref_id, subject_name, front_text, back_text, added_time"


# ---------------------------------------------------------------- 1) CRUD
@memory_bp.route("/api/memory/cards", methods=["POST"])
@require_auth
def create_card():
    """幂等标注入记忆库。body {card_type:'kp'|'error', ref_id:int, front?, back?}。

    front/back 缺省时按 ref_id 从实体自动快照；实体已删除返回 404。
    重复标注（同 user+card_type+ref_id）不产生第二行，返回既有卡片。
    """
    body = request.get_json(silent=True) or {}
    card_type = (body.get("card_type") or "").strip()
    if card_type not in _KINDS:
        return _err("card_type 必须为 kp 或 error", 400)
    try:
        ref_id = int(body.get("ref_id"))
    except (TypeError, ValueError):
        return _err("ref_id 必须为整数", 400)
    user_id = g.user_id

    conn = _get_conn()
    try:
        ent = _load_entity(conn, card_type, ref_id, user_id)
        if ent is None:
            log.log("memory", "card_add", "error", {"card_type": card_type, "ref_id": ref_id, "reason": "entity_missing"})
            return _err("关联实体不存在或已删除", 404)

        front = (body.get("front") or "").strip()
        back = (body.get("back") or "").strip()
        if not front or not back:
            dfront, dback = _default_snapshot(card_type, ref_id, ent)
            front = front or dfront
            back = back or dback

        cur = conn.execute(
            "INSERT OR IGNORE INTO memory_cards "
            "(user_id, card_type, ref_id, subject_name, front_text, back_text) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, card_type, ref_id, ent["subject_name"], front, back),
        )
        inserted = (cur.rowcount or 0) > 0
        row = conn.execute(
            f"SELECT {_CARD_COLS} FROM memory_cards "
            f"WHERE user_id = ? AND card_type = ? AND ref_id = ?",
            (user_id, card_type, ref_id)).fetchone()
        conn.commit()
        card = _card_row_to_dict(conn, row, user_id)
    finally:
        conn.close()

    log.log("memory", "card_add", "success", {
        "card_type": card_type, "ref_id": ref_id, "inserted": inserted, "card_id": card["id"],
    })
    return _ok({"created": inserted, "card": card})


@memory_bp.route("/api/memory/cards", methods=["GET"])
@require_auth
def list_cards():
    """卡片列表（含关联实体熟练度摘要）。query: card_type, subject。"""
    card_type = (request.args.get("card_type") or "").strip()
    subject = (request.args.get("subject") or "").strip()
    if card_type and card_type not in _KINDS:
        return _err("card_type 必须为 kp 或 error", 400)
    user_id = g.user_id

    sql = f"SELECT {_CARD_COLS} FROM memory_cards WHERE user_id = ?"
    params = [user_id]
    if card_type:
        sql += " AND card_type = ?"
        params.append(card_type)
    if subject:
        sql += " AND subject_name = ?"
        params.append(subject)
    sql += " ORDER BY added_time DESC, id DESC"

    conn = _get_conn()
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
        cards = [_card_row_to_dict(conn, r, user_id) for r in rows]
    finally:
        conn.close()
    return _ok({"cards": cards, "count": len(cards)})


@memory_bp.route("/api/memory/cards/<int:card_id>", methods=["GET"])
@require_auth
def get_card(card_id):
    """卡片详情（含实体熟练度摘要）。user_id 隔离。"""
    user_id = g.user_id
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT {_CARD_COLS} FROM memory_cards WHERE id = ? AND user_id = ?",
            (card_id, user_id)).fetchone()
        if row is None:
            return _err("卡片不存在或无权访问", 404)
        card = _card_row_to_dict(conn, row, user_id)
    finally:
        conn.close()
    return _ok(card)


@memory_bp.route("/api/memory/cards/<int:card_id>", methods=["DELETE"])
@require_auth
def delete_card(card_id):
    """移除卡片（只删行，不清关联实体 FSRS 状态，方案 §2.2）。"""
    user_id = g.user_id
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM memory_cards WHERE id = ? AND user_id = ?", (card_id, user_id))
        deleted = cur.rowcount or 0
        conn.commit()
    finally:
        conn.close()
    if deleted == 0:
        return _err("卡片不存在或无权访问", 404)
    log.log("memory", "card_delete", "success", {"card_id": card_id})
    return _ok({"deleted": True, "card_id": card_id})


# ---------------------------------------------------------------- 2) 复习自评
@memory_bp.route("/api/memory/cards/<int:card_id>/rate", methods=["POST"])
@require_auth
def rate_card(card_id):
    """4 档自评 → F.apply_review（单卡即单事件，不折叠）。

    body {self_assessment: 'not_at_all'|'vague'|'familiar'|'perfect'}。
    非法档 400；实体已删除 404。返回 mastery 视图。
    """
    body = request.get_json(silent=True) or {}
    key = (body.get("self_assessment") or "").strip()
    if key not in F.CARD_SELF_RATINGS:
        return _err("self_assessment 必须为 not_at_all/vague/familiar/perfect 之一", 400)
    rating = F.CARD_SELF_RATINGS[key]
    user_id = g.user_id

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT card_type, ref_id FROM memory_cards WHERE id = ? AND user_id = ?",
            (card_id, user_id)).fetchone()
        if row is None:
            return _err("卡片不存在或无权访问", 404)
        card_type, ref_id = row[0], row[1]
    finally:
        conn.close()

    # apply_review 自带事务与连接（own conn），实体不存在返回 None → 404
    new_st = F.apply_review(card_type, ref_id, user_id, rating)
    if new_st is None:
        log.log("memory", "card_rate", "error", {"card_id": card_id, "reason": "entity_missing"})
        return _err("关联实体不存在或已删除", 404)

    conn = _get_conn()
    try:
        ent = _load_entity(conn, card_type, ref_id, user_id)
    finally:
        conn.close()
    mastery = ent["mastery"] if ent else -1
    r_now = round(F.row_retrievability(ent["state"] or {}), 4) if ent else 0.0
    log.log("memory", "card_rate", "success", {
        "card_id": card_id, "card_type": card_type, "ref_id": ref_id,
        "self_assessment": key, "rating": rating, "mastery": mastery, "state": new_st["fsrs_state"],
    })
    return _ok({
        "card_id": card_id,
        "self_assessment": key,
        "rating": rating,
        "mastery": mastery,
        "retrievability": r_now,
        "fsrs_state": new_st["fsrs_state"],
        "due": F.fmt_ts(new_st["due"]),
        "scheduled_days": new_st["scheduled_days"],
    })


# ---------------------------------------------------------------- 3) 推荐组卷
_DIFF_LABELS = {
    "容易": "easy", "easy": "easy",
    "中等": "medium", "medium": "medium",
    "困难": "hard", "hard": "hard",
}


def _difficulty_bucket(difficulty_score):
    """难度 0-10 分 → easy(<=4)/medium(<=7)/hard(>7)。"""
    if difficulty_score <= 4.0:
        return "easy"
    if difficulty_score <= 7.0:
        return "medium"
    return "hard"


def _normalize_mix(difficulty_mix):
    """把 {容易/中等/困难 或 easy/medium/hard: 权重} 归一为 {easy,medium,hard: float}。"""
    out = {"easy": 0.0, "medium": 0.0, "hard": 0.0}
    if not isinstance(difficulty_mix, dict):
        return out
    for k, v in difficulty_mix.items():
        bucket = _DIFF_LABELS.get(str(k).strip())
        if bucket is None:
            continue
        try:
            out[bucket] += float(v)
        except (TypeError, ValueError):
            continue
    return out


@memory_bp.route("/api/memory/recommend", methods=["POST"])
@require_auth
def recommend():
    """推荐学习（建立推荐）：从记忆卡片池按 FSRS 排序 + 难度配比组卷。

    body {card_type, difficulty_mix?{容易/中等/困难 权重}, count, type?}。
    用 F.build_sprint_pool / question_difficulty_mix；返回卡片列表（正反面 + 当前 R）；
    池不足返回实际数并注明（note）。
    """
    body = request.get_json(silent=True) or {}
    card_type = (body.get("card_type") or body.get("type") or "").strip()
    if card_type not in _KINDS:
        return _err("card_type 必须为 kp 或 error", 400)
    try:
        count = int(body.get("count") or 10)
    except (TypeError, ValueError):
        return _err("count 必须为整数", 400)
    if count <= 0:
        return _err("count 必须为正整数", 400)
    subject = (body.get("subject") or "").strip()
    mix_raw = body.get("difficulty_mix")
    user_id = g.user_id

    sql = f"SELECT {_CARD_COLS} FROM memory_cards WHERE user_id = ? AND card_type = ?"
    params = [user_id, card_type]
    if subject:
        sql += " AND subject_name = ?"
        params.append(subject)

    conn = _get_conn()
    try:
        rows = conn.execute(sql, tuple(params)).fetchall()
        # 组装候选池（仅关联实体仍存在的卡片；含 state/star/R）
        pool_rows = []
        for r in rows:
            kind, ref_id = r[1], r[2]
            ent = _load_entity(conn, kind, ref_id, user_id)
            if ent is None:
                continue  # 实体已删除：不入池
            card = _card_row_to_dict(conn, r, user_id)
            srow = {
                "state": ent["state"],
                "importance_score": ent["importance_score"],
                "difficulty_score": ent["difficulty_score"],
            }
            pool_rows.append(srow)
            srow["_card"] = card
            srow["_bucket"] = _difficulty_bucket(ent["difficulty_score"])
    finally:
        conn.close()

    pool_total = len(pool_rows)

    # 目标难度配比：显式 mix 优先，否则按池平均掌握度 question_difficulty_mix 推导
    if isinstance(mix_raw, dict) and any(_normalize_mix(mix_raw).values()):
        target = _normalize_mix(mix_raw)
        mix_source = "request"
    else:
        masteries = [F.mastery_view(c["mastery"]) for c in (s["_card"] for s in pool_rows)]
        valid = [m for m in masteries if m >= 0]
        avg = round(sum(valid) / len(valid)) if valid else -1
        triple = F.question_difficulty_mix(avg)  # ['easy'|'medium'|'hard', ...]
        target = {"easy": 0.0, "medium": 0.0, "hard": 0.0}
        for b in triple:
            target[b] += 1.0
        mix_source = "derived"

    # 排序（build_sprint_pool 用 R 升序→importance 降序→difficulty 升序）
    ordered = F.build_sprint_pool(pool_rows, pool_total) if pool_rows else []

    selected, counts = _apply_mix(ordered, count, target)
    # 池内因配比缺额时用剩余序补齐（仍按 ordered 顺序）
    if len(selected) < count:
        chosen = {id(c) for c in selected}
        for c in ordered:
            if len(selected) >= count:
                break
            if id(c) not in chosen:
                selected.append(c)
                chosen.add(id(c))

    out_cards = []
    for c in selected:
        card = c["_card"]
        out_cards.append({
            "id": card["id"], "card_type": card["card_type"], "ref_id": card["ref_id"],
            "subject_name": card["subject_name"], "front_text": card["front_text"],
            "back_text": card["back_text"], "mastery": card["mastery"],
            "retrievability": card["retrievability"],
            "difficulty_score": card["difficulty_score"],
            "importance_score": card["importance_score"],
            "difficulty_bucket": c["_bucket"],
        })

    note = None
    if pool_total < count:
        note = f"记忆库卡片池仅 {pool_total} 张（请求 {count}），已返回全部可用卡片"

    log.log("memory", "recommend", "success", {
        "card_type": card_type, "count": count, "pool": pool_total,
        "returned": len(out_cards), "mix_source": mix_source,
        "mix": {k: counts.get(k, 0) for k in ("easy", "medium", "hard")},
    })
    return _ok({
        "cards": out_cards,
        "requested": count,
        "returned": len(out_cards),
        "pool_total": pool_total,
        "difficulty_mix_target": target,
        "difficulty_mix_actual": counts,
        "mix_source": mix_source,
        "note": note,
    })


def _apply_mix(ordered, count, target):
    """按目标难度配比从已排序池中挑选 count 张。

    ordered 内每项含 '_bucket'。返回 (selected, actual_counts)。
    配额取整后不足用最大余数法补齐，保证总数=min(count, len(ordered))。
    """
    actual_counts = {"easy": 0, "medium": 0, "hard": 0}
    want_total = min(count, len(ordered))
    if want_total <= 0:
        return [], actual_counts

    total_w = sum(target.values())
    buckets = {"easy": [], "medium": [], "hard": []}
    for c in ordered:
        buckets[c["_bucket"]].append(c)

    # 理想配额（按权重×总数），再按各桶实际容量截断
    if total_w > 0:
        ideal = {k: (target[k] / total_w) * want_total for k in ("easy", "medium", "hard")}
    else:
        ideal = {k: want_total / 3.0 for k in ("easy", "medium", "hard")}
    base = {k: int(ideal[k]) for k in ("easy", "medium", "hard")}
    alloc = dict(base)
    # 最大余数法补到 want_total
    rem = want_total - sum(base.values())
    order_by_frac = sorted(("easy", "medium", "hard"), key=lambda k: (ideal[k] - base[k]), reverse=True)
    i = 0
    while rem > 0 and i < len(order_by_frac) * 2:
        k = order_by_frac[i % 3]
        if alloc[k] < len(buckets[k]):
            alloc[k] += 1
            rem -= 1
        i += 1
    # 超容量截断的额度回收再分配给尚有余量的桶
    over = sum(max(0, alloc[k] - len(buckets[k])) for k in alloc)
    alloc = {k: min(alloc[k], len(buckets[k])) for k in alloc}
    for k in ("easy", "medium", "hard"):
        if over <= 0:
            break
        add = min(over, len(buckets[k]) - alloc[k])
        alloc[k] += add
        over -= add

    selected = []
    for k in ("easy", "medium", "hard"):
        take = alloc[k]
        for c in buckets[k][:take]:
            selected.append(c)
            actual_counts[k] += 1
    return selected, actual_counts
