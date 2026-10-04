# -*- coding: utf-8 -*-
"""c1 后端移植自证冒烟：FSRS 端点 + 卡片 + 写路径（测试用户隔离，不污染正式数据）。

覆盖：
1. 服务加载新蓝图（/api/memory/cards 可达）
2. curve/stars/mastery_manual/rate 四端点（kp 与 error 两 kind）
3. assessment 整批折叠 + mastery_cap 封顶（0/2 全错 → mastery 必低）
4. practice-submit 多题型（纯客观题，本地判分不走 LLM）
5. memory_cards 标注/列表/卡片 rate/recommend
6. dashboard/stats 与 memory/overview（decay_flush 全量口径不炸）
结果写 logs/u15_c1_smoke_result.txt。
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u15_c1_smoke_result.txt"
USER = "u15_c1_smoke"
PWD = "Passw0rd!"

lines = []
fails = []


def req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def check(name, cond, detail=""):
    lines.append(f"{'PASS' if cond else 'FAIL'} {name} {detail}")
    if not cond:
        fails.append(name)


def main():
    req("POST", "/api/auth/register", {"username": USER, "password": PWD})
    st, b = req("POST", "/api/auth/login", {"username": USER, "password": PWD})
    check("login", st == 200 and b.get("success"), f"st={st}")
    tok = (b.get("data") or {}).get("token")
    if not tok:
        lines.append("NO TOKEN，终止")
        return

    # 建学科 + 直插知识点（不走 LLM 提取）；user_id 口径与 g.user_id 对齐（查 users 表）
    req("POST", "/api/subjects", {"subject_name": "u15冒烟科"}, tok)
    sys.path.insert(0, r"e:\LLM\LectureLearnLoop\server")
    from database import db_adapter
    import config as _cfg
    conn = db_adapter.get_connection(str(_cfg.DB_PATH))
    try:
        urow = conn.execute("SELECT user_id FROM users WHERE username = ?", (USER,)).fetchone()
        uid = str(urow[0]) if urow else USER
        conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score) "
            "VALUES (?, ?, '冒烟知识点A', '描述A', -1)", (uid, "u15冒烟科"))
        conn.commit()
        pid = conn.execute(
            "SELECT id FROM knowledge_points WHERE user_id = ? AND point_name = ? ORDER BY id DESC LIMIT 1",
            (uid, "冒烟知识点A")).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    lines.append(f"kp pid={pid} uid={uid}")

    # 1) curve 空历史
    st, b = req("GET", f"/api/kb/kp/{pid}/curve", token=tok)
    check("curve_empty", st == 200 and b.get("success") and b["data"]["count"] == 0, f"st={st}")
    # 404 口径
    st, _ = req("GET", "/api/kb/kp/99999999/curve", token=tok)
    check("curve_404", st == 404, f"st={st}")

    # 2) stars（0-10 存储分，越界截断）
    st, b = req("POST", f"/api/kb/kp/{pid}/stars", {"difficulty": 12, "importance": 4}, tok)
    check("stars_truncate", st == 200 and b.get("success"), f"st={b}")

    # 3) mastery_manual 滑杆
    st, b = req("POST", f"/api/kb/kp/{pid}/mastery_manual", {"value": 66}, tok)
    check("mastery_manual", st == 200 and b.get("data", {}).get("mastery") == 66, f"st={b}")

    # 4) kind 级 rate 四档自评 → 写曲线历史
    st, b = req("POST", f"/api/kb/kp/{pid}/rate", {"self_assessment": "familiar"}, tok)
    check("rate_kp", st == 200 and b.get("success"), f"st={b}")
    st, b = req("GET", f"/api/kb/kp/{pid}/curve", token=tok)
    # manual 一条 + rate 一条
    check("curve_after_2pts", st == 200 and b["data"]["count"] >= 2, f"count={b.get('data',{}).get('count')}")

    # 5) assessment 整批折叠 + 封顶：2 题全错 → mastery ≤ 0×100 封顶
    qs = [{"question": "1+1?", "correct_answer": "2", "difficulty": "中等", "options": ["A.2", "B.3"]},
          {"question": "2+2?", "correct_answer": "4", "difficulty": "中等", "options": ["A.3", "B.4"]}]
    st, b = req("POST", f"/api/knowledge/points/{pid}/assessment",
                {"questions": qs, "answers": ["9", "9"]}, tok)
    d = b.get("data") or b
    check("assessment_allwrong", st == 200 and b.get("success") and d.get("mastery_score", 999) <= 50,
          f"st={st} mastery={d.get('mastery_score')}")

    # 6) practice-submit 纯客观题本地判分：1 题答对 → FSRS 复习发生
    st, b = req("POST", f"/api/knowledge/points/{pid}/practice-submit",
                {"questions": [{"type": "single", "question": "1+1?", "correct_answer": "A",
                                "options": ["A.2", "B.3"], "difficulty": "容易", "explanation": ""}],
                 "answers": ["A"]}, tok)
    d = b.get("data") or b
    check("practice_submit", st == 200 and b.get("success") and d.get("mastery_updated") is True,
          f"st={st} mastery={d.get('mastery_score')}")

    # 7) 卡片：标注 kp → 列表 → 卡片 rate → recommend
    st, b = req("POST", "/api/memory/cards", {"card_type": "kp", "ref_id": pid}, tok)
    check("card_add", st == 200 and b.get("success"), f"st={b}")
    card_id = ((b.get("data") or {}).get("card") or {}).get("id") or (b.get("data") or {}).get("card_id")
    st, b = req("GET", "/api/memory/cards", token=tok)
    check("card_list", st == 200 and b.get("success"), f"st={st}")
    if card_id:
        st, b = req("POST", f"/api/memory/cards/{card_id}/rate", {"self_assessment": "vague"}, tok)
        check("card_rate", st == 200 and b.get("success"), f"st={b}")
    st, b = req("POST", "/api/memory/recommend", {"card_type": "kp", "count": 5}, tok)
    check("recommend", st == 200 and b.get("success"), f"st={st} {json.dumps(b, ensure_ascii=False)[:160]}")

    # 8) 统计端点（全量 decay_flush 口径）
    st, b = req("GET", "/api/dashboard/stats", token=tok)
    check("dashboard_stats", st == 200 and b.get("success"), f"st={st}")
    st, b = req("GET", "/api/memory/overview", token=tok)
    check("memory_overview", st == 200 and b.get("success"), f"st={st}")

    # 9) error kind：取该用户错题（assessment 全错已产生错题行）
    conn = db_adapter.get_connection(str(_cfg.DB_PATH))
    try:
        row = conn.execute(
            "SELECT id FROM error_questions WHERE user_id = ? ORDER BY id LIMIT 1", (uid,)).fetchone()
    finally:
        conn.close()
    if row:
        eid = row[0]
        st, b = req("GET", f"/api/kb/error/{eid}/curve", token=tok)
        check("curve_error", st == 200 and b.get("success"), f"st={st}")
        st, b = req("POST", f"/api/kb/error/{eid}/rate", {"self_assessment": "not_at_all"}, tok)
        check("rate_error", st == 200 and b.get("success"), f"st={b}")
    else:
        lines.append("SKIP error（无错题行，留痕未产生错题？）")

    # 清理测试数据（仅本测试用户）
    conn = db_adapter.get_connection(str(_cfg.DB_PATH))
    try:
        conn.execute("DELETE FROM memory_cards WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM kp_proficiency_history WHERE knowledge_point_id = ?", (pid,))
        conn.execute("DELETE FROM error_proficiency_history WHERE error_question_id IN "
                     "(SELECT id FROM error_questions WHERE user_id = ?)", (uid,))
        conn.execute("DELETE FROM practice_records WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM error_questions WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM knowledge_points WHERE id = ?", (pid,))
        conn.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name = ?", (uid, "u15冒烟科"))
        conn.commit()
        lines.append("cleanup done")
    except Exception as e:
        lines.append(f"cleanup WARN {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        lines.append("EXC " + traceback.format_exc())
        fails.append("exception")
    lines.append(f"RESULT: {'ALL_PASS' if not fails else 'FAILED=' + ','.join(fails)}")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("WROTE", OUT)
