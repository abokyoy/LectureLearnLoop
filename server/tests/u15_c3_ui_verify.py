# -*- coding: utf-8 -*-
"""c3 记忆数据面板 E2E：详情页默认面板 + 记知识点/记错题折叠面板（曲线/双星/滑杆挂载）。
种子 U15C3MOD 前缀，跑完 DB 直删。API 写链路已由 u15_c3_api_smoke 覆盖，此处验证 UI 挂载与交互。
"""
import json
import sys
import uuid
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import db_adapter  # noqa: E402
import config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\u15_c3_ui_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
import base64
_seg = TOKEN.split(".")[1]
_seg += "=" * (-len(_seg) % 4)
UID = json.loads(base64.urlsafe_b64decode(_seg))["uid"]
H = {"Authorization": "Bearer " + TOKEN}
MOD = "U15C3" + uuid.uuid4().hex[:6]
SUBJECT = f"{MOD}_探针科"
PFX = "U15C3%"

lines = []
fails = []


def step(name, ok, extra=""):
    lines.append(f"{'PASS' if ok else 'FAIL'} {name} {extra}")
    if not ok:
        fails.append(name)


def _exec(sql, params=None, fetch=False):
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = c.cursor()
        cur.execute(sql, params or ())
        rows = cur.fetchall() if fetch else None
        c.commit()
        return rows
    finally:
        c.close()


def _purge():
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = c.cursor()
        cur.execute("SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        pids = [x[0] for x in cur.fetchall()]
        if pids:
            ph = ",".join(str(int(i)) for i in pids)
            cur.execute("DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN (" + ph + ")")
            cur.execute("DELETE FROM practice_records WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
            cur.execute("DELETE FROM kp_proficiency_history WHERE user_id = ? AND knowledge_point_id IN (" + ph + ")", (UID,))
            cur.execute("DELETE FROM knowledge_points WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        cur.execute("SELECT id FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        eids = [x[0] for x in cur.fetchall()]
        if eids:
            ph2 = ",".join(str(int(i)) for i in eids)
            cur.execute("DELETE FROM error_proficiency_history WHERE error_question_id IN (" + ph2 + ")")
            cur.execute("DELETE FROM error_questions WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name LIKE ?", (UID, PFX))
        c.commit()
    finally:
        c.close()


# ---------- 种子：学科 + 1 知识点（自评+手动熟练度造曲线点） + 1 道错题 ----------
_purge()
requests.post(BASE + "/api/subjects", json={"subject_name": SUBJECT}, headers=H, timeout=15)
rr = requests.post(BASE + "/api/knowledge/point-new",
                   json={"point": {"name": f"{MOD}曲线点", "description": f"{MOD}描述：记忆面板验证"}, "subject": SUBJECT},
                   headers=H, timeout=20).json()
pid = int(rr["data"]["knowledge_id"])
step("seed_point", True, f"pid={pid}")
# 星值 + 两次自评 → 造 FSRS 状态；手动熟练度放最后（后续真实复习会清 manual 标记，apply_review 语义）
requests.post(f"{BASE}/api/kb/kp/{pid}/stars", json={"difficulty": 8, "importance": 6}, headers=H, timeout=15)
requests.post(f"{BASE}/api/kb/kp/{pid}/rate", json={"self_assessment": "vague"}, headers=H, timeout=15)
requests.post(f"{BASE}/api/kb/kp/{pid}/rate", json={"self_assessment": "familiar"}, headers=H, timeout=15)
q = [{"type": "single", "question": f"{MOD}Q1 必错单选", "options": ["a", "b", "c", "d"],
      "correct_answer": "A", "difficulty": "容易", "explanation": "e"}]
requests.post(f"{BASE}/api/knowledge/points/{pid}/practice-submit",
              json={"questions": q, "answers": ["C"]}, headers=H, timeout=60)
errs = requests.get(BASE + "/api/kb/errors", params={"subject": SUBJECT}, headers=H, timeout=15).json()["data"]
eid = next((x["id"] for x in errs if str(x.get("question_content", "")).startswith(MOD)), None)
step("seed_error_found", eid is not None, f"eid={eid}")
requests.post(f"{BASE}/api/kb/error/{eid}/rate", json={"self_assessment": "familiar"}, headers=H, timeout=15)
requests.post(f"{BASE}/api/kb/kp/{pid}/mastery_manual", json={"value": 66}, headers=H, timeout=15)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pageerrs = []
    pg.on("pageerror", lambda e: pageerrs.append("pageerror: " + str(e)[:300]))
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(600)

    def wait_page(cid, timeout_loops=90):
        pg.evaluate(f"handleMenuClick('{cid}')")
        for _ in range(timeout_loops):
            if pg.evaluate(f"() => document.querySelector('[data-pm-page=\"{cid}\"]') !== null"):
                pg.wait_for_timeout(1200)
                return True
            pg.wait_for_timeout(400)
        return False

    # ---------- 详情页：默认展开记忆数据面板 ----------
    pg.evaluate(f"localStorage.setItem('pm_pending_point', JSON.stringify({{id: {pid}, name: '{MOD}曲线点', ts: Date.now()}}))")
    ok = wait_page("knowledge_point")
    step("detail_page_rendered", ok)
    pg.wait_for_timeout(1500)  # 面板异步取数
    root_sel = '[data-pm-page="knowledge_point"] [data-mw-root]'
    has_root = pg.evaluate(f"() => !!document.querySelector('{root_sel}')")
    step("detail_panel_exists", has_root)
    mounts = pg.evaluate(f"""() => {{
        const r = document.querySelector('{root_sel}');
        return {{
            stars: r ? r.querySelectorAll('.ll-stars').length : 0,
            slider: r ? r.querySelectorAll('.ll-mastery-slider').length : 0,
            svg: r ? r.querySelectorAll('[data-mw="curve"] svg').length : 0,
            meta: r && r.querySelector('[data-mw="meta"]') ? r.querySelector('[data-mw="meta"]').textContent : ''
        }};
    }}""")
    step("detail_stars_mounted", mounts["stars"] == 2, str(mounts))
    step("detail_slider_mounted", mounts["slider"] == 1, str(mounts))
    step("detail_curve_svg", mounts["svg"] == 1, str(mounts))
    step("detail_meta_state", "状态" in mounts["meta"] and "手动" in mounts["meta"], mounts["meta"][:80])

    # ---------- 记知识点页：卡片下折叠面板，点击展开挂载 ----------
    ok = wait_page("memory_knowledge")
    step("kp_page_rendered", ok)
    picked = pg.evaluate(f"""() => {{
        const x = [...document.querySelectorAll('[data-pm-page="memory_knowledge"] [data-subj]')]
            .find(b => b.getAttribute('data-subj') === '{SUBJECT}');
        if (x) x.click();
        return !!x;
    }}""")
    step("kp_pick_subject", picked)
    pg.wait_for_timeout(1500)
    hidden = pg.evaluate("() => document.querySelector('[data-pm-page=\"memory_knowledge\"] [data-mw-root]').classList.contains('hidden')")
    step("kp_panel_initially_hidden", hidden)
    pg.evaluate("() => document.querySelector('[data-pm-page=\"memory_knowledge\"] [data-mw-toggle]').click()")
    pg.wait_for_timeout(1500)
    state = pg.evaluate("""() => {
        const r = document.querySelector('[data-pm-page="memory_knowledge"] [data-mw-root]');
        return {
            hidden: r.classList.contains('hidden'),
            btn: document.querySelector('[data-pm-page="memory_knowledge"] [data-mw-toggle]').textContent,
            stars: r.querySelectorAll('.ll-stars').length,
            svg: r.querySelectorAll('[data-mw="curve"] svg').length
        };
    }""")
    step("kp_panel_expanded", (not state["hidden"]) and "收起" in state["btn"], str(state))
    step("kp_panel_widgets", state["stars"] == 2 and state["svg"] >= 1, str(state))
    # 曲线有点（种子 3 次历史）→ svg 内 polyline/path 数 >=1
    kps = pg.evaluate("""() => {
        const r = document.querySelector('[data-pm-page="memory_knowledge"] [data-mw-root] [data-mw="curve"]');
        return r ? r.querySelectorAll('svg polyline, svg path').length : 0;
    }""")
    step("kp_curve_has_lines", kps >= 1, f"lines={kps}")

    # ---------- 记错题页：同口径折叠面板 ----------
    ok = wait_page("memory_errors")
    step("err_page_rendered", ok)
    picked = pg.evaluate(f"""() => {{
        const x = [...document.querySelectorAll('[data-pm-page="memory_errors"] [data-subj]')]
            .find(b => b.getAttribute('data-subj') === '{SUBJECT}');
        if (x) x.click();
        return !!x;
    }}""")
    step("err_pick_subject", picked)
    pg.wait_for_timeout(1500)
    pg.evaluate("() => document.querySelector('[data-pm-page=\"memory_errors\"] [data-mw-toggle]').click()")
    pg.wait_for_timeout(1500)
    state2 = pg.evaluate("""() => {
        const r = document.querySelector('[data-pm-page="memory_errors"] [data-mw-root]');
        return {
            hidden: r ? r.classList.contains('hidden') : true,
            stars: r ? r.querySelectorAll('.ll-stars').length : 0,
            svg: r ? r.querySelectorAll('[data-mw="curve"] svg').length : 0,
            meta: r && r.querySelector('[data-mw="meta"]') ? r.querySelector('[data-mw="meta"]').textContent : ''
        };
    }""")
    step("err_panel_expanded_widgets", (not state2["hidden"]) and state2["stars"] == 2 and state2["svg"] >= 1, str(state2))
    step("err_panel_meta", "状态" in state2["meta"], state2["meta"][:80])

    # ---------- 星值交互：详情页点难度星 → DB 落库 ----------
    pg.evaluate(f"localStorage.setItem('pm_pending_point', JSON.stringify({{id: {pid}, name: '{MOD}曲线点', ts: Date.now()}}))")
    wait_page("knowledge_point")
    pg.wait_for_timeout(1800)
    box = pg.evaluate("""() => {
        const el = document.querySelector('[data-pm-page="knowledge_point"] [data-mw="diff"] svg');
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {x: r.x, y: r.y, w: r.width, h: r.height};
    }""")
    clicked = False
    if box:
        # 点 svg 最右（第5星右半 → set(12) 服务端截断 10）；label 无事件，必须落在 svg 内
        pg.mouse.click(box["x"] + box["w"] - 3, box["y"] + box["h"] / 2)
        pg.wait_for_timeout(1200)
        clicked = True
    db_diff = _exec("SELECT difficulty_score FROM knowledge_points WHERE id = ? AND user_id = ?", (pid, UID), fetch=True)[0][0]
    step("detail_star_click_persisted", clicked and float(db_diff) != 8.0, f"difficulty={db_diff}")

    # ---------- 评审 Minor-4 回归：滑杆手动设定后头部徽标/进度条同步 ----------
    slider_ok = pg.evaluate("""() => {
        const inp = document.querySelector('[data-pm-page="knowledge_point"] [data-mw="slider"] input');
        if (!inp) return false;
        inp.value = 42;
        inp.dispatchEvent(new Event('change'));
        return true;
    }""")
    pg.wait_for_timeout(1500)
    head_txt = pg.evaluate("""() => {
        const ms = document.querySelector('[data-pm-page="knowledge_point"] [data-role="mastery-slot"]');
        return ms ? ms.textContent : '';
    }""")
    step("detail_slider_syncs_header", slider_ok and "42" in head_txt, f"head={head_txt[:40]}")

    b.close()

step("no_page_errors", not pageerrs, "; ".join(pageerrs[:3]))

_purge()
result = "ALL_PASS" if not fails else "FAILED: " + ", ".join(fails)
lines.append(result)
Path(OUT).write_text("\n".join(lines), encoding="utf-8")
print(result)
sys.exit(0 if not fails else 1)
