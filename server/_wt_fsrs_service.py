# -*- coding: utf-8 -*-
"""FSRS-5 间隔重复算法服务（练/记系统核心，2026-09-28）

定位：熟练度/复习排期的**唯一写入口**。知识点（knowledge_points）与
错题（error_questions）共用同一状态机；卡片自评、练习判分、Sprint 推荐
全部映射到 FSRS rating 后经由本模块落库。

公式与 open-spaced-repetition py-fsrs 3.0.0（FSRS-5，19 参数）逐式对齐：
  R = (1 + FACTOR·t/S) ^ DECAY          幂律遗忘曲线（DECAY=-0.5）
  S0(r) = max(w[r-1], 0.1)              首评稳定性查表
  D0(r) = clamp(w4 - exp(w5·(r-1)) + 1)  首评难度
  next_interval(S) = S/FACTOR·(rr^(1/DECAY) - 1)   rr=desired_retention
  short_term(S,r) = S·exp(w17·(r-3+w18))           当日多次学习（FSRS-5 新增）
  recall:  S' = S·(1+e^w8·(11-D)·S^-w9·(e^((1-R)w10)-1)·hard/easy·w15/w16)
  forget:  S' = w11·D^-w12·((S+1)^w13-1)·e^((1-R)w14)
  D' = clamp(mean_reversion(D0(Easy), D - w6·(r-3)))，mean_rev = w7·init+(1-w7)·cur

约束（方案文档 §2.3/§3）：
- 时间基准统一 tz-naive UTC datetime；DB TEXT 由本模块负责解析/格式化；
- mastery 统一口径 = round(100×R)，由 decay_flush 惰性回写；
- 「未评估」判定唯一保留 -1 哨兵（mastery_view），不引入 NULL 语义；
- 状态读写在事务内完成，PG 路径 SELECT ... FOR UPDATE 防并发双写。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

try:
    from logger_module import debug_logger
except Exception:  # 脚本环境兜底，单测不依赖 Flask 生态
    debug_logger = None

# ---------------------------------------------------------------------------
# 常量（FSRS-5 官方默认 19 参数，来源 open-spaced-repetition fsrs4anki）
# ---------------------------------------------------------------------------

DECAY = -0.5
FACTOR = 0.9 ** (1 / DECAY) - 1  # = 19/81 ≈ 0.2345679

DEFAULT_W = (
    0.4072, 1.1829, 3.1262, 15.4722, 7.2102, 0.5316, 1.0651, 0.0234,
    1.616, 0.1544, 1.0824, 1.9813, 0.0953, 0.2975, 2.2042, 0.2407,
    2.9466, 0.5034, 0.6567,
)

DESIRED_RETENTION = 0.9     # request_retention，方案 §3：默认 0.9
MAXIMUM_INTERVAL = 36500    # 天
MIN_DIFFICULTY, MAX_DIFFICULTY = 1.0, 10.0
STABILITY_MIN = 0.001
INIT_STABILITY_MIN = 0.1    # 与参考实现 init_stability 的 max(...,0.1) 一致

# Rating（FSRS 语义）
R_AGAIN, R_HARD, R_GOOD, R_EASY = 1, 2, 3, 4
# State（与 DB 列 fsrs_state 对应）
S_NEW, S_LEARNING, S_REVIEW, S_RELEARNING = 0, 1, 2, 3

# 卡片自评 4 档 → rating（方案 §3：很不熟悉/不熟悉/熟悉/非常熟悉）
CARD_SELF_RATINGS = {
    "not_at_all": R_AGAIN,
    "vague": R_HARD,
    "familiar": R_GOOD,
    "perfect": R_EASY,
}

# 学习状态内的短期分钟档（对齐 py-fsrs 3.0.0：New 分支 1/5/10min，schedule() 5/10min）
_NEW_DUE_MINUTES = {R_AGAIN: 1, R_HARD: 5, R_GOOD: 10}
_LEARN_DUE_MINUTES = {R_AGAIN: 5, R_HARD: 10}  # hard_interval=0 时的分钟档

_FLUSH_THROTTLE_SECONDS = 600  # 统计端点全量 flush 节流（方案 §2.3：10 分钟）
_FLUSH_CFG_PREFIX = "fsrs_last_flush:"


def _dbg(action, status, data):
    if debug_logger is not None:
        try:
            debug_logger.log("fsrs", action, status, data)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 时间工具（DB TEXT 兼容 'YYYY-MM-DD HH:MM:SS' 与 isoformat；统一 naive UTC）
# ---------------------------------------------------------------------------

def parse_ts(text):
    """TEXT → naive UTC datetime；解析失败返回 None。

    带偏移的串按 UTC 归一（与 _naive/utcnow 同一口径，不取本地时区）。
    """
    if not text:
        return None
    s = str(text).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt_val):
    """aware datetime → naive UTC（项目存储/比较约定），防调用方传入 tz-aware 炸减法。"""
    if dt_val is not None and dt_val.tzinfo is not None:
        return dt_val.astimezone(timezone.utc).replace(tzinfo=None)
    return dt_val


# ---------------------------------------------------------------------------
# FSRS-5 核心公式（纯函数，零依赖，逐式对齐 py-fsrs 3.0.0）
# ---------------------------------------------------------------------------

def init_stability(rating, w=DEFAULT_W):
    return max(w[rating - 1], INIT_STABILITY_MIN)


def init_difficulty(rating, w=DEFAULT_W):
    d = w[4] - math.exp(w[5] * (rating - 1)) + 1
    return min(max(d, MIN_DIFFICULTY), MAX_DIFFICULTY)


def retrievability(elapsed_days, stability):
    """幂律遗忘曲线；elapsed_days 取 max(0, ...) 由调用方保证。"""
    if stability is None or stability <= 0:
        return 0.0
    t = max(0, int(elapsed_days))
    return (1 + FACTOR * t / stability) ** DECAY


def next_interval(stability, w_rr=DESIRED_RETENTION, maximum=MAXIMUM_INTERVAL):
    """由稳定性反解到 desired_retention 对应天数（fsrs.py next_interval）。"""
    iv = stability / FACTOR * (w_rr ** (1 / DECAY) - 1)
    return min(max(round(iv), 1), maximum)


def next_difficulty(d, rating, w=DEFAULT_W):
    cur = d - w[6] * (rating - 3)
    init_easy = init_difficulty(R_EASY, w)
    reverted = w[7] * init_easy + (1 - w[7]) * cur
    return min(max(reverted, MIN_DIFFICULTY), MAX_DIFFICULTY)


def short_term_stability(s, rating, w=DEFAULT_W):
    """同日内连续学习（FSRS-5 新增 w[17]/w[18]）。下限保护见 _clamp_s。"""
    return _clamp_s(s * math.exp(w[17] * (rating - 3 + w[18])))


def recall_stability(d, s, r, rating, w=DEFAULT_W):
    hard_penalty = w[15] if rating == R_HARD else 1
    easy_bonus = w[16] if rating == R_EASY else 1
    return _clamp_s(s * (
        1 + math.exp(w[8]) * (11 - d) * math.pow(s, -w[9])
        * (math.exp((1 - r) * w[10]) - 1) * hard_penalty * easy_bonus
    ))


def forget_stability(d, s, r, w=DEFAULT_W):
    return _clamp_s(
        w[11] * math.pow(d, -w[12]) * (math.pow(s + 1, w[13]) - 1)
        * math.exp((1 - r) * w[14])
    )


def _clamp_s(s):
    return max(s, STABILITY_MIN)


# ---------------------------------------------------------------------------
# 状态机：一次复习（对齐 fsrs.py repeat() 的单 rating 视角）
# ---------------------------------------------------------------------------

def review(state, rating, now=None, w=DEFAULT_W, desired_retention=DESIRED_RETENTION):
    """输入当前 FSRS 状态 dict，输出复习后的新状态。

    state 键（可为 None，表示未初始化）：
      fsrs_state, fsrs_stability, fsrs_difficulty, fsrs_reps, fsrs_lapses,
      last_review_time（naive datetime）
    返回 dict：上述键 + 'due'(naive datetime)、'scheduled_days'、
      'retrievability_before'（复习时刻的 R，New 为 None）。
    """
    now = utcnow() if now is None else _naive(now)
    st = int(state.get("fsrs_state") or S_NEW)
    s = state.get("fsrs_stability")
    d = state.get("fsrs_difficulty")
    reps = int(state.get("fsrs_reps") or 0)
    lapses = int(state.get("fsrs_lapses") or 0)
    last_review = state.get("last_review_time")
    reps += 1

    if st == S_NEW:
        # 首评：S0/D0 查表（方案 §3：不做存量折算）
        new_s = init_stability(rating, w)
        new_d = init_difficulty(rating, w)
        r_before = None
        if rating == R_EASY:
            new_st, sched_days = S_REVIEW, next_interval(new_s, desired_retention)
            due = now + timedelta(days=sched_days)
        else:
            new_st, sched_days = S_LEARNING, 0
            due = now + timedelta(minutes=_NEW_DUE_MINUTES[rating])
    else:
        elapsed = max(0, (now - last_review).days) if last_review else 0
        if s is None:
            # 异常行防护：state 非 New 但 S 缺失（历史脏数据），按首评分重建初值，避免短期/长期公式炸 None
            s = init_stability(rating, w)
        r_before = retrievability(elapsed, s)
        new_d = next_difficulty(d if d is not None else init_difficulty(rating, w), rating, w)

        if st in (S_LEARNING, S_RELEARNING):
            # 短期路径：全部 rating 走 short_term（对齐 3.0.0 next_ds）
            stab = {r: short_term_stability(s, r, w) for r in (1, 2, 3, 4)}
            good_iv = next_interval(stab[R_GOOD], desired_retention)
            easy_iv = max(next_interval(stab[R_EASY], desired_retention), good_iv + 1)
            hard_iv = 0
            new_s = stab[rating]
            if rating == R_AGAIN:
                new_st, sched_days = st, 0
                due = now + timedelta(minutes=5)
            elif rating == R_HARD:
                new_st, sched_days = st, hard_iv
                due = now + timedelta(minutes=10)
            elif rating == R_GOOD:
                new_st, sched_days = S_REVIEW, good_iv
                due = now + timedelta(days=good_iv)
            else:
                new_st, sched_days = S_REVIEW, easy_iv
                due = now + timedelta(days=easy_iv)
        else:  # S_REVIEW
            # 长期路径：again→forget 公式，其余→recall 公式
            stab = {
                R_AGAIN: forget_stability(d, s, r_before, w),
                R_HARD: recall_stability(d, s, r_before, R_HARD, w),
                R_GOOD: recall_stability(d, s, r_before, R_GOOD, w),
                R_EASY: recall_stability(d, s, r_before, R_EASY, w),
            }
            hard_iv = next_interval(stab[R_HARD], desired_retention)
            good_iv = next_interval(stab[R_GOOD], desired_retention)
            hard_iv = min(hard_iv, good_iv)
            good_iv = max(good_iv, hard_iv + 1)
            easy_iv = max(next_interval(stab[R_EASY], desired_retention), good_iv + 1)
            new_s = stab[rating]
            if rating == R_AGAIN:
                new_st, sched_days = S_RELEARNING, 0
                lapses += 1
                due = now + timedelta(minutes=5)
            elif rating == R_HARD:
                new_st, sched_days = S_REVIEW, hard_iv
                due = now + timedelta(days=hard_iv)
            elif rating == R_GOOD:
                new_st, sched_days = S_REVIEW, good_iv
                due = now + timedelta(days=good_iv)
            else:
                new_st, sched_days = S_REVIEW, easy_iv
                due = now + timedelta(days=easy_iv)

    return {
        "fsrs_state": new_st,
        "fsrs_stability": new_s,
        "fsrs_difficulty": new_d,
        "fsrs_reps": reps,
        "fsrs_lapses": lapses,
        "last_review_time": now,
        "due": due,
        "scheduled_days": sched_days,
        "retrievability_before": r_before,
    }


# ---------------------------------------------------------------------------
# rating 映射（用户确认：LLM 细粒度评分；卡片 4 档自评）
# ---------------------------------------------------------------------------

_QUALITY_MAP = {
    "勉强答对": R_HARD,
    "正常答对": R_GOOD,
    "精准流畅": R_EASY,
}


def rating_from_practice(is_correct, answer_quality=None):
    """练习判分 → rating：答错=Again；答对按质量分档，缺失默认 Good。"""
    if not is_correct:
        return R_AGAIN
    return _QUALITY_MAP.get(str(answer_quality or "").strip(), R_GOOD)


def rating_from_card_self_assessment(key):
    """卡片 4 档自评 → rating；非法值按 Good 兜底。"""
    return CARD_SELF_RATINGS.get(str(key or "").strip(), R_GOOD)


# ---------------------------------------------------------------------------
# mastery 统一口径（方案 §2.3）
# ---------------------------------------------------------------------------

def mastery_view(score):
    """返回体回填唯一入口：None/-1 → -1（未评估，灰），其余原值整型化。

    收敛 routes_bridge/knowledge_management 的 6 处「回填 50 / 回填 -1」。
    """
    if score is None:
        return -1
    try:
        v = int(score)
    except (TypeError, ValueError):
        return -1
    return -1 if v == -1 else v


def mastery_of_state(state, now=None):
    """由 FSRS 状态派生 mastery=round(100·R)；非 Review 态返回 None（不覆盖）。"""
    if not state or state.get("fsrs_stability") is None:
        return None
    if int(state.get("fsrs_state") or 0) != S_REVIEW:
        return None
    last = state.get("last_review_time")
    if not last:
        return None
    now = utcnow() if now is None else _naive(now)
    elapsed = max(0, (now - last).days)
    return max(0, min(100, round(100 * retrievability(elapsed, state["fsrs_stability"]))))


# ---------------------------------------------------------------------------
# DB 集成：唯一写入口 + 惰性衰减回写
# ---------------------------------------------------------------------------

# kind → 表/列/历史表映射（知识点与错题同一状态机，方案 §3）
_KINDS = {
    "kp": {
        "table": "knowledge_points",
        "mastery_col": "mastery_score",
        "id_col": "id",
        "star_cols": ("difficulty_score", "importance_score"),
        "hist_table": "kp_proficiency_history",
    },
    "error": {
        "table": "error_questions",
        "mastery_col": "current_proficiency",
        "id_col": "id",
        "star_cols": ("difficulty_score", "importance_score"),
        "hist_table": "error_proficiency_history",
    },
}

_STATE_COLS = ("fsrs_stability", "fsrs_difficulty", "fsrs_state",
               "fsrs_reps", "fsrs_lapses", "last_review_time")


def _get_conn():
    """与 credits_service 同路径：app context 用工厂，脚本/测试直连适配层。"""
    try:
        from flask import current_app, has_app_context
        if has_app_context() and "DB_CONN_FACTORY" in current_app.config:
            return current_app.config["DB_CONN_FACTORY"]()
    except Exception:
        pass
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


def load_state(conn, kind, ref_id, user_id, for_update=False):
    """读取一行 FSRS 状态；user_id 隔离强制；PG 支持 FOR UPDATE。"""
    spec = _KINDS[kind]
    cols = ", ".join(_STATE_COLS)
    sql = f"SELECT {cols} FROM {spec['table']} WHERE {spec['id_col']} = ? AND user_id = ?"
    if for_update:
        from database import db_adapter
        if db_adapter.is_postgres():
            sql += " FOR UPDATE"
    row = conn.execute(sql, (ref_id, user_id)).fetchone()
    if row is None:
        return None
    return {
        "fsrs_stability": row[0],
        "fsrs_difficulty": row[1],
        "fsrs_state": row[2],
        "fsrs_reps": row[3],
        "fsrs_lapses": row[4],
        "last_review_time": parse_ts(row[5]),
    }


def apply_review(kind, ref_id, user_id, rating, now=None, conn=None, mastery_cap=None):
    """一次复习的唯一写入口：状态机 → 回写 fsrs_*/due/mastery → 追加历史曲线。

    事务内完成（PG 路径 FOR UPDATE），返回新状态 dict；行不存在返回 None。
    mastery_cap（2026-09-29 用户确认 A 方案）：实测正确率封顶（0-100）。
    在期之前复习时 R 估算≈100，答错显著却显示“精通”与用户感知不符，
    写入值取 min(派生值/当前列值, cap)；答对封顶不生效（cap=100）。
    封顶后 Relearning 期内 decay_flush 不覆盖（只处理 Review 态行），
    回到 Review 后恢复 FSRS 曲线演化。
    """
    spec = _KINDS[kind]
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        raise ValueError(f"invalid fsrs rating: {rating!r} (must be 1-4)") from None
    if not 1 <= rating <= 4:
        raise ValueError(f"invalid fsrs rating: {rating!r} (must be 1-4)")
    own = conn is None
    if own:
        conn = _get_conn()
    try:
        st = load_state(conn, kind, ref_id, user_id, for_update=True)
        if st is None:
            return None
        now = utcnow() if now is None else _naive(now)
        prev_state = int(st.get("fsrs_state") or S_NEW)
        new_st = review(st, rating, now=now)
        mastery = mastery_of_state(new_st, now)  # Review 态才有值
        if (mastery is None and prev_state == S_REVIEW
                and new_st["fsrs_state"] == S_RELEARNING
                and new_st["retrievability_before"] is not None):
            # 用户确认（2026-09-28）：lapse 瞬间（Review→Relearning）用复习前 R×100
            # 回写 mastery，图谱立即反映“退化”；Relearning 期内其余复习不覆盖，
            # 回到 Review 后恢复正常刷新。
            mastery = max(0, min(100, round(100 * new_st["retrievability_before"])))
        if mastery_cap is not None:
            cap = max(0, min(100, int(mastery_cap)))
            if mastery is None:
                cur_m = _current_mastery(conn, spec, ref_id, user_id)
                mastery = cap if cur_m < 0 else min(cur_m, cap)
            else:
                mastery = min(mastery, cap)
        sets = {
            "fsrs_stability": new_st["fsrs_stability"],
            "fsrs_difficulty": new_st["fsrs_difficulty"],
            "fsrs_state": new_st["fsrs_state"],
            "fsrs_reps": new_st["fsrs_reps"],
            "fsrs_lapses": new_st["fsrs_lapses"],
            "last_review_time": fmt_ts(new_st["last_review_time"]),
            "due_time": fmt_ts(new_st["due"]),
            "mastery_manual": 0,  # 真实复习后清手动标记，恢复 FSRS 派生优先（用户指令：手动为最高级仅持续至下次复习）
        }
        if mastery is not None:
            sets[spec["mastery_col"]] = mastery
        cols = ", ".join(f"{k} = ?" for k in sets)
        conn.execute(
            f"UPDATE {spec['table']} SET {cols} WHERE {spec['id_col']} = ? AND user_id = ?",
            tuple(sets.values()) + (ref_id, user_id),
        )
        # 曲线：每次复习必写历史（方案：每个知识点一条熟练度曲线）
        _append_history(conn, spec, kind, ref_id, user_id,
                        mastery if mastery is not None else _current_mastery(conn, spec, ref_id, user_id),
                        new_st["retrievability_before"], now=now)
        if own:
            conn.commit()
        _dbg("apply_review", "success", {
            "kind": kind, "ref_id": ref_id, "rating": int(rating),
            "state": new_st["fsrs_state"], "s": new_st["fsrs_stability"],
            "d": new_st["fsrs_difficulty"], "mastery": mastery,
            "due": fmt_ts(new_st["due"]),
        })
        return new_st
    finally:
        if own:
            conn.close()


def _current_mastery(conn, spec, ref_id, user_id):
    row = conn.execute(
        f"SELECT {spec['mastery_col']} FROM {spec['table']} "
        f"WHERE {spec['id_col']} = ? AND user_id = ?", (ref_id, user_id)).fetchone()
    return int(row[0]) if row and row[0] is not None else -1


def _append_history(conn, spec, kind, ref_id, user_id, mastery, r_val, now=None):
    # 曲线时间戳与状态机时钟同源（注入 now 的回放/测试不乱序）
    ts = fmt_ts(utcnow() if now is None else _naive(now))
    if spec["hist_table"] == "kp_proficiency_history":
        conn.execute(
            "INSERT INTO kp_proficiency_history "
            "(user_id, knowledge_point_id, mastery, retrievability, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, ref_id, int(mastery),
             float(r_val) if r_val is not None else None, ts),
        )
    else:
        conn.execute(
            "INSERT INTO error_proficiency_history (error_question_id, proficiency, timestamp) "
            "VALUES (?, ?, ?)",
            (ref_id, int(mastery), ts),
        )


def entity_exists(kind, ref_id, user_id, conn=None):
    """公共函数：校验 kind 实体行存在且属于 user_id（曲线等只读端点复用 404 口径）。"""
    spec = _KINDS[kind]
    own = conn is None
    if own:
        conn = _get_conn()
    try:
        return conn.execute(
            f"SELECT 1 FROM {spec['table']} WHERE {spec['id_col']} = ? AND user_id = ?",
            (ref_id, user_id)).fetchone() is not None
    finally:
        if own:
            conn.close()


def set_stars(kind, ref_id, user_id, difficulty=None, importance=None, conn=None):
    """调星唯一入口：入参/存储均为 0-10 分（星×2，0.5 星=1 分，整分步进）。

    服务端截断：最低 1 分（=0.5 星，不允许清零），最高 10 分（=5 星）。方案 §4。
    """
    spec = _KINDS[kind]
    updates = []
    for col, val in (("difficulty_score", difficulty), ("importance_score", importance)):
        if val is None:
            continue
        v = max(1.0, min(10.0, float(round(float(val)))))
        updates.append((col, v))
    if not updates:
        return False
    own = conn is None
    if own:
        conn = _get_conn()
    try:
        exists = conn.execute(
            f"SELECT 1 FROM {spec['table']} WHERE {spec['id_col']} = ? AND user_id = ?",
            (ref_id, user_id)).fetchone()
        if not exists:
            return False
        cols = ", ".join(f"{c} = ?" for c, _ in updates)
        conn.execute(
            f"UPDATE {spec['table']} SET {cols} WHERE {spec['id_col']} = ? AND user_id = ?",
            tuple(v for _, v in updates) + (ref_id, user_id),
        )
        if own:
            conn.commit()
        _dbg("set_stars", "success", {"kind": kind, "ref_id": ref_id,
                                      "values": {c: v for c, v in updates}})
        return True
    finally:
        if own:
            conn.close()


def set_mastery_manual(kind, ref_id, user_id, value, conn=None):
    """手动设定熟练度（用户指令 2026-09-28：手动=最高优先级）。

    写 mastery 列 0-100 整值并置 mastery_manual=1；标记期间 decay_flush 不再改写；
    下次 apply_review（真实复习）自动清标记恢复 FSRS 派生。同步追写一条曲线历史。
    行不存在/不属本人返回 False；非法值抛 ValueError。
    """
    spec = _KINDS[kind]
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid mastery value: {value!r} (must be 0-100)") from None
    if not 0 <= v <= 100:
        raise ValueError(f"invalid mastery value: {value!r} (must be 0-100)")
    own = conn is None
    if own:
        conn = _get_conn()
    try:
        cur = conn.execute(
            f"UPDATE {spec['table']} SET {spec['mastery_col']} = ?, mastery_manual = 1 "
            f"WHERE {spec['id_col']} = ? AND user_id = ?", (v, ref_id, user_id))
        if cur.rowcount == 0:
            return False
        _append_history(conn, spec, kind, ref_id, user_id, v, None)
        if own:
            conn.commit()
        _dbg("set_mastery_manual", "success", {"kind": kind, "ref_id": ref_id, "value": v})
        return True
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# decay_flush：惰性衰减回写（方案 §2.3 两阶段口径）
# ---------------------------------------------------------------------------

def _flush_rows(conn, kind, rows, now=None):
    """rows: [(id, state_dict)]；返回 [(id, new_mastery)]（仅值有变化的行）。"""
    spec = _KINDS[kind]
    now = utcnow() if now is None else _naive(now)
    changed = []
    for ref_id, st in rows:
        m = mastery_of_state(st, now)
        if m is None:
            continue
        cur = st.get("_mastery_now")
        if cur is not None and int(cur) == m:
            continue
        changed.append((ref_id, m))
    if changed:
        cur = conn.cursor()
        try:
            cur.executemany(
                f"UPDATE {spec['table']} SET {spec['mastery_col']} = ? WHERE {spec['id_col']} = ?",
                [(m, rid) for rid, m in changed],
            )
        finally:
            cur.close()
    return changed


def _load_flushable(conn, kind, user_id=None, ref_ids=None):
    spec = _KINDS[kind]
    cols = ", ".join(f"t.{c}" for c in _STATE_COLS)
    sql = (f"SELECT t.{spec['id_col']}, {cols}, t.{spec['mastery_col']} "
           f"FROM {spec['table']} t WHERE t.fsrs_state = {S_REVIEW} "
           f"AND t.fsrs_stability IS NOT NULL AND t.last_review_time IS NOT NULL "
           f"AND COALESCE(t.mastery_manual, 0) = 0")  # 手动设定行不被衰减回写覆盖（用户指令：最高优先级）
    params = []
    if user_id is not None:
        sql += f" AND t.user_id = ?"
        params.append(user_id)
    if ref_ids:
        sql += f" AND t.{spec['id_col']} IN ({', '.join('?' for _ in ref_ids)})"
        params.extend(ref_ids)
    out = []
    for row in conn.execute(sql, tuple(params)).fetchall():
        out.append((row[0], {
            "fsrs_stability": row[1], "fsrs_difficulty": row[2], "fsrs_state": row[3],
            "fsrs_reps": row[4], "fsrs_lapses": row[5],
            "last_review_time": parse_ts(row[6]),
            "_mastery_now": row[7],
        }))
    return out


def decay_flush(user_id, ref_ids=None, force=False, conn=None, now=None):
    """惰性回写 mastery=round(100·R)。

    - ref_ids 给定：行级 flush（列表/详情/脑图端点两阶段的第一阶段）；
    - ref_ids 为 None：按 user 全量 flush（统计端点用），PG 下 10 分钟节流，
      last_flush 记于 system_config；force=True 忽略节流。
    返回 {'kp': n, 'error': n} 实际回写行数。
    """
    own = conn is None
    if own:
        conn = _get_conn()
    try:
        from database import db_adapter
        throttled = False
        scope_all = ref_ids is None
        if scope_all and db_adapter.is_postgres() and not force and not _flush_due(conn, user_id):
            throttled = True
        if throttled:
            return {"kp": 0, "error": 0, "throttled": True}

        counts = {}
        for kind in ("kp", "error"):
            # 行级作用域：ref_ids 未包含/空列表的 kind 不顺带全表 flush
            if not scope_all and not list((ref_ids or {}).get(kind) or []):
                counts[kind] = 0
                continue
            rows = _load_flushable(
                conn, kind,
                user_id=user_id,
                ref_ids=(None if scope_all else list(ref_ids.get(kind) or [])) or None,
            )
            changed = _flush_rows(conn, kind, rows, now=now) if rows else []
            counts[kind] = len(changed)
        # 借调用方连接时不提前 commit（与本模块“own 才提交”约定一致），由调用方收尾
        if own:
            conn.commit()
        if scope_all and db_adapter.is_postgres():
            # 节流位点走独立连接幂等写入：不污染调用方事务，并发双 flush 不再撞主键。
            # 已知代价：调用方事务若在其后回滚，位点已落盘 → 最长 10 分钟内全量 flush 被节流（仅统计短暂滞后，可接受）
            _touch_flush(user_id)
        _dbg("decay_flush", "success", {"user_id": user_id, "scope": "all" if scope_all else "rows",
                                        "counts": counts})
        return counts
    finally:
        if own:
            conn.close()


def _flush_cfg_key(user_id):
    return f"{_FLUSH_CFG_PREFIX}{user_id}"


def _flush_due(conn, user_id):
    """10 分钟节流判定：距上次全量 flush 是否已超过阈值。"""
    row = conn.execute("SELECT value FROM system_config WHERE key = ?",
                       (_flush_cfg_key(user_id),)).fetchone()
    if not row or not row[0]:
        return True
    last = parse_ts(row[0])
    if last is None:
        return True
    return (utcnow() - last).total_seconds() >= _FLUSH_THROTTLE_SECONDS


def _touch_flush(user_id):
    """节流位点记于独立连接：INSERT OR IGNORE（适配层→ON CONFLICT DO NOTHING）+ UPDATE
    幂等写，并发不抛；失败仅记调试日志，不影响业务端点。"""
    tc = None
    try:
        tc = _get_conn()
        now = fmt_ts(utcnow())
        key = _flush_cfg_key(user_id)
        tc.execute("INSERT OR IGNORE INTO system_config (key, value, description, updated_at) "
                   "VALUES (?, ?, ?, ?)",
                   (key, now, "FSRS 全量 decay_flush 时间(UTC)", now))
        tc.execute("UPDATE system_config SET value = ?, updated_at = ? WHERE key = ?",
                   (now, now, key))
        tc.commit()
    except Exception as e:  # noqa: BLE001
        _dbg("touch_flush", "error", {"err": str(e)})
    finally:
        if tc is not None:
            try:
                tc.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Sprint 推荐与出题难度搭配（方案 §3.1）
# ---------------------------------------------------------------------------

def row_retrievability(state_dict, now=None):
    """行 → 当前 R；非 Review/未初始化返回 0.0（新行排前，优先被学）。"""
    m_state = mastery_of_state(state_dict, now)
    if m_state is None:
        return 0.0
    return m_state / 100.0


def sprint_sort_key(row, now=None):
    """候选池排序键：R 升序 → importance 降序 → difficulty 升序（方案 §3.1）。

    row 需含键：state(FSRS 状态 dict)、importance_score、difficulty_score。
    """
    r = row_retrievability(row.get("state") or {}, now)
    imp = float(row.get("importance_score") or 5.0)
    dif = float(row.get("difficulty_score") or 5.0)
    return (r, -imp, dif)


def build_sprint_pool(rows, n, now=None):
    """rows 排序取前 n；池不足返回全部（调用方按 len< n 提示）。"""
    ordered = sorted(rows, key=lambda r: sprint_sort_key(r, now))
    return ordered[:max(0, int(n))]


def question_difficulty_mix(mastery):
    """按熟练度给出出题难度搭配（方案 §3.1 三档）。"""
    m = mastery_view(mastery)
    if m < 0:  # 未评估：保守按简单为主
        return ["easy", "easy", "medium"]
    if m < 40:
        return ["easy", "easy", "medium"]
    if m <= 70:
        return ["easy", "medium", "medium"]
    return ["medium", "hard", "hard"]
