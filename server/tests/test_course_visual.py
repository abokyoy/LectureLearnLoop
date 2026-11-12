# -*- coding: utf-8 -*-
"""课文图文结合轮（2026-11-12 用户裁定 A 方案）断言测试。

零真实 LLM 调用（BE.call_llm_for_user / cs._llm 全打桩）：
- 生成侧：课文 prompt 含 mermaid 配图纪律段；MD_MAX 提升到 12000 的边界；
- 课级产物链 start_for_lesson：done 秒回复用、在飞去重、拒收、失败终态、
  键隔离（principle/lab 互不覆盖；course_lesson 轨与黑板 lesson 轨互不串）；
- HTTP 端点：GET/POST /api/course/lessons/<lid>/visual（真实注册测试用户 +
  独立课文行，轮询复用黑板作业端点），数据用完即清。
运行方式（server/ 目录）：python -m pytest tests/test_course_visual.py -v
"""
from __future__ import annotations

import base64
import json
import threading
import time
import uuid
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import credits_service as cr
from app import create_app
from services import board_explainer as BE
from services import course_service as cs
from services import lecture_board as LB
from services import micro_course as MC
from services import principle_cache as PC

APP = create_app()

_GOOD_HTML = ('<!DOCTYPE html><html><body><style>:root{--c1:#2a7}</style>'
              '<button onclick="1">next</button></body></html>')


def _json_ok(**over):
    d = {"title": "课文原理交互页", "narration": "跟着这句话看原理展开",
         "html": _GOOD_HTML}
    d.update(over)
    return json.dumps(d, ensure_ascii=False)


class Stub:
    """可控 LLM 打桩：记调用（含 scene/thinking 口径）、可阻塞、可抛错。"""

    def __init__(self, result=None, raises=None, gate=None):
        self.result, self.raises, self.gate = result, raises, gate
        self.calls = []

    def __call__(self, uid, prompt, context="", scene="", timeout=None,
                 thinking=None):
        self.calls.append({"uid": uid, "prompt": prompt, "scene": scene,
                           "timeout": timeout, "thinking": thinking})
        if self.gate is not None:
            assert self.gate.wait(10), "stub gate 卡死"
        if self.raises is not None:
            raise self.raises
        return self.result


def _ctx(**over):
    c = {"id": 900001, "title": "梯度下降", "subject_name": "机器学习",
         "description": "迭代优化入门", "content_md": "# 梯度下降\n正文 enough length " * 30}
    c.update(over)
    return c


def _conn():
    from database import db_adapter
    import config
    return db_adapter.get_connection(str(config.DB_PATH))


def _wait_done(uid, job_id, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = BE.get_job(uid, job_id)
        if j and j["state"] != "generating":
            return j
        time.sleep(0.05)
    raise AssertionError(f"作业 {job_id} 未达终态")


def _purge_pc(uid):
    conn = _conn()
    try:
        conn.execute("DELETE FROM micro_scenes WHERE course_id IN "
                     "(SELECT id FROM micro_courses WHERE user_id=?)", (str(uid),))
        conn.execute("DELETE FROM micro_courses WHERE user_id=?", (str(uid),))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """默认桩：LLM 合法产出、黑板无课堂键（库轨隔离测试用）；作业表前后清空。"""
    monkeypatch.setattr(BE, "call_llm_for_user", Stub(result=_json_ok()))
    monkeypatch.setattr(LB, "get_lesson_key", lambda uid: None)
    with BE._LOCK:
        BE._JOBS.clear()
    yield
    with BE._LOCK:
        BE._JOBS.clear()


# ---------------------------------------------------------------- 生成侧：配图纪律 + MD_MAX

def test_01_md_prompt_mermaid_rules():
    p = cs._build_md_prompt("机器学习", "过拟合", "概要", "full", ["正则化"])
    assert "图文结合要求" in p
    assert "```mermaid" in p and "graph TD" in p
    assert "写图纪律" in p and "12 个节点" in p          # 与黑板闸门同源的防渲染失败纪律
    assert "不要写进 mermaid 块" in p                     # 公式与图块互不侵犯
    assert cs.MD_MAX == 12000


def test_02_md_max_boundary():
    ok = cs.validate_lesson_md("x" * 12000)              # 带图课文字数上浮后仍收
    assert len(ok) == 12000
    with pytest.raises(cs.CourseError):
        cs.validate_lesson_md("x" * 12001)
    # 内层 mermaid 围栏不受剥外层围栏逻辑影响
    md = "# 题\n\n```mermaid\ngraph TD\nA-->B\n```\n\n" + "正文" * 100
    out = cs.validate_lesson_md("```markdown\n" + md + "\n```")
    assert "```mermaid" in out and "graph TD" in out


# ---------------------------------------------------------------- build_lesson_prompt

def test_10_prompt_principle_vs_lab():
    pp = BE.build_lesson_prompt(_ctx(), "principle")
    assert "原理图" in pp and "一场景一焦点" in pp
    assert "梯度下降" in pp and "机器学习" in pp           # 课文素材进提示词
    pl = BE.build_lesson_prompt(_ctx(), "lab")
    assert "交互实验" in pl and "可调参数" in pl and "观察要点" in pl
    for p in (pp, pl):
        assert '"narration"' in p and str(MC.MAX_HTML_LEN) in p   # 输出契约与硬上限同口径
    big = _ctx(content_md="长" * 20000)
    body = BE.build_lesson_prompt(big, "principle")
    assert body.count("长" * 1000) <= BE._LESSON_MAT_MAX // 1000   # 素材有顶，不无限喂


# ---------------------------------------------------------------- start_for_lesson 状态机

def test_20_start_done_and_archive():
    uid = "cv" + uuid.uuid4().hex[:8]
    try:
        r = BE.start_for_lesson(uid, _ctx(), "principle")
        assert r["success"] and r["job"]["state"] == "generating"
        j = _wait_done(uid, r["job"]["job_id"])
        assert j["state"] == "done" and j["html"].startswith("<!DOCTYPE html>")
        hit = BE.lesson_latest(uid, 900001, "principle")
        assert hit and hit["state"] == "done" and hit["seq"] == 1
    finally:
        _purge_pc(uid)


def test_21_cache_reuse_zero_calls():
    uid = "cv" + uuid.uuid4().hex[:8]
    try:
        r1 = BE.start_for_lesson(uid, _ctx(), "principle")
        _wait_done(uid, r1["job"]["job_id"])
        stub = Stub(result=_json_ok())
        BE.call_llm_for_user = stub
        r2 = BE.start_for_lesson(uid, _ctx(), "principle")
        assert r2["success"] and r2.get("reused") == "cache"
        assert r2["job"]["state"] == "done"                 # 秒回 done job
        assert len(stub.calls) == 0                         # 零外呼零扣分（规则 2）
        # 深度重画：跳库、开思考、版本 +1（规则 1，与黑板口径一致）
        r3 = BE.start_for_lesson(uid, _ctx(), "principle", refresh=True)
        assert len(stub.calls) == 1 and stub.calls[0]["thinking"] == "on"
        assert stub.calls[0]["scene"] == "原理图生成"
        _wait_done(uid, r3["job"]["job_id"])
        assert BE.lesson_latest(uid, 900001, "principle")["seq"] == 2
    finally:
        _purge_pc(uid)


def test_22_inflight_reuse_same_slot():
    uid = "cv" + uuid.uuid4().hex[:8]
    gate = threading.Event()
    BE.call_llm_for_user = Stub(result=_json_ok(), gate=gate)
    try:
        r1 = BE.start_for_lesson(uid, _ctx(), "principle")
        r2 = BE.start_for_lesson(uid, _ctx(), "principle")   # 同槽位双击
        assert r2.get("reused") is True
        assert r1["job"]["job_id"] == r2["job"]["job_id"]    # 防双开双扣分
        r3 = BE.start_for_lesson(uid, _ctx(), "lab")         # 异槽位不受阻塞（一课两槽）
        assert r3["success"] and not r3.get("reused")
        gate.set()
        _wait_done(uid, r1["job"]["job_id"])
        _wait_done(uid, r3["job"]["job_id"])
    finally:
        _purge_pc(uid)


def test_23_rejects():
    uid = "cv" + uuid.uuid4().hex[:8]
    r = BE.start_for_lesson(uid, _ctx(), "poster")
    assert not r["success"] and "未知" in r["error"]
    r = BE.start_for_lesson(uid, _ctx(content_md="  "), "principle")
    assert not r["success"] and "正文" in r["error"]          # 没课文不配图，不开工不扣分
    assert BE.lesson_latest(uid, 900001, "principle") is None


def test_24_llm_fail_terminal_no_double_charge():
    uid = "cv" + uuid.uuid4().hex[:8]
    stub = Stub(raises=cr.InsufficientCreditsError(0))
    BE.call_llm_for_user = stub
    try:
        r = BE.start_for_lesson(uid, _ctx(), "lab")
        j = _wait_done(uid, r["job"]["job_id"])
        assert j["state"] == "failed" and "积分" in j["error"]
        assert len(stub.calls) == 1                           # 失败不重发（微课纪律）
        assert BE.lesson_latest(uid, 900001, "lab") is None   # 失败不落库
    finally:
        _purge_pc(uid)


def test_25_key_isolation():
    """同课文 principle/lab 互不覆盖；课级 course_lesson 轨与黑板 lesson 轨互不串。"""
    uid = "cv" + uuid.uuid4().hex[:8]
    monkey_lk = "lkt_" + uuid.uuid4().hex[:8]
    orig_gs = LB.get_state
    LB.get_lesson_key = lambda u: monkey_lk
    LB.get_state = lambda u, since=0: {"rev": 1, "items": [
        {"id": 1, "kind": "step", "text": "黑板素材" * 30}],
        "speech": [], "focus": None, "outbox": [], "lesson_key": monkey_lk}
    try:
        r = BE.start_for_lesson(uid, _ctx(), "principle")
        _wait_done(uid, r["job"]["job_id"])
        r = BE.start_for_lesson(uid, _ctx(), "lab")
        _wait_done(uid, r["job"]["job_id"])
        assert BE.lesson_latest(uid, 900001, "principle")["seq"] == 1
        assert BE.lesson_latest(uid, 900001, "lab")["seq"] == 1     # 两槽独立版本链
        # 黑板链各走各的键：课级产物不会被黑板 start 劫持复用，反之亦然
        rb = BE.start(uid)
        _wait_done(uid, rb["job"]["job_id"])
        assert PC.latest(uid, "lesson", monkey_lk)["seq"] == 1      # 黑板轨独立
        rb2 = BE.start(uid)
        assert rb2.get("reused") == "cache"                         # 黑板命中自己的库
        BE.call_llm_for_user = Stub(result=_json_ok())
        r2 = BE.start_for_lesson(uid, _ctx(), "principle")
        assert r2.get("reused") == "cache"                          # 课级命中自己的库
    finally:
        LB.get_state = orig_gs
        _purge_pc(uid)


# ---------------------------------------------------------------- HTTP 端点


def test_26_board_not_hijacked_by_lesson_job():
    """评审 Major-1 回归：课级作业在飞时黑板 start 不得跨轨复用（语境不同）。"""
    uid = "cv" + uuid.uuid4().hex[:8]
    gate = threading.Event()
    BE.call_llm_for_user = Stub(result=_json_ok(), gate=gate)
    orig_gs, orig_lk = LB.get_state, LB.get_lesson_key
    LB.get_lesson_key = lambda u: "lkt_" + uuid.uuid4().hex[:8]
    LB.get_state = lambda u, since=0: {"rev": 1, "items": [
        {"id": 1, "kind": "step", "text": "黑板素材" * 30}],
        "speech": [], "focus": None, "outbox": [], "lesson_key": "lk"}
    try:
        r = BE.start_for_lesson(uid, _ctx(), "lab")       # 课级作业卡在 gate 在飞
        rb = BE.start(uid)                                 # 黑板必须另开自己的作业
        assert rb["success"] and not rb.get("reused")
        assert rb["job"]["job_id"] != r["job"]["job_id"]
        rb2 = BE.start(uid)                                # 黑板双击仍自家去重
        assert rb2.get("reused") is True and rb2["job"]["job_id"] == rb["job"]["job_id"]
        gate.set()
        _wait_done(uid, r["job"]["job_id"])
        _wait_done(uid, rb["job"]["job_id"])
    finally:
        LB.get_state, LB.get_lesson_key = orig_gs, orig_lk
        _purge_pc(uid)

@pytest.fixture()
def lesson_http():
    """真实注册测试用户 + 一行成品课文（content_ready 带正文），返回 (client, hdr, lid, uid)。"""
    client = APP.test_client()
    uname = "cvh_" + uuid.uuid4().hex[:6]
    client.post("/api/auth/register", json={"username": uname, "password": "test123456"})
    tok = client.post("/api/auth/login", json={
        "username": uname, "password": "test123456"}).get_json()["data"]["token"]
    seg = tok.split(".")[1]
    uid = str(json.loads(base64.urlsafe_b64decode(
        seg + "=" * (-len(seg) % 4)))["uid"])
    hdr = {"Authorization": "Bearer " + tok}
    conn = _conn()
    gid = lid = None
    try:
        cur = conn.execute("INSERT INTO learning_goals (user_id, subject_name, goal_text, status) "
                           "VALUES (?,?,'视觉链测试','ready')", (uid, "ML科"))
        gid = cur.lastrowid
        cur = conn.execute("INSERT INTO course_modules (goal_id, ord, title) VALUES (?,1,'模块V')", (gid,))
        mid = cur.lastrowid
        cur = conn.execute("INSERT INTO course_lessons (module_id, ord, title, description, status, content_md) "
                           "VALUES (?,1,'梯度下降入门','概要','content_ready',?)",
                           (mid, "# 梯度下降\n\n" + "正文内容足够长" * 60))
        lid = cur.lastrowid
        conn.commit()
        yield client, hdr, lid, uid
    finally:
        conn.execute("DELETE FROM course_lessons WHERE module_id IN "
                     "(SELECT id FROM course_modules WHERE goal_id=?)", (gid,))
        conn.execute("DELETE FROM course_modules WHERE goal_id=?", (gid,))
        conn.execute("DELETE FROM learning_goals WHERE id=?", (gid,))
        conn.commit()
        conn.close()
        _purge_pc(uid)


def test_30_visual_get_shape(lesson_http):
    client, hdr, lid, _ = lesson_http
    g = client.get(f"/api/course/lessons/{lid}/visual", headers=hdr).get_json()
    assert g["success"]
    assert set(g["data"]["visual"]) == {"principle", "lab"}
    assert g["data"]["visual"]["principle"] is None
    assert g["data"]["visual"]["lab"] is None
    assert g["data"]["has_content"] is True
    # 越权/不存在 → 404
    assert client.get("/api/course/lessons/99999999/visual", headers=hdr).status_code == 404


def test_31_visual_roundtrip(lesson_http):
    client, hdr, lid, uid = lesson_http
    BE.call_llm_for_user = Stub(result=_json_ok(title="课级原理图"))
    p = client.post(f"/api/course/lessons/{lid}/visual/principle",
                    json={}, headers=hdr).get_json()
    assert p["success"] and p["data"]["job"]["state"] == "generating"
    jid = p["data"]["job"]["job_id"]
    _wait_done(uid, jid)                                  # 后台线程开工，轮询到终态再断言
    # 轮询复用黑板作业端点（同一张作业表）
    g = client.get(f"/api/board/explain/{jid}", headers=hdr).get_json()
    assert g["success"] and g["data"]["job"]["state"] == "done"
    assert "课级原理图" in g["data"]["job"]["title"]
    v = client.get(f"/api/course/lessons/{lid}/visual", headers=hdr).get_json()
    assert v["data"]["visual"]["principle"]["state"] == "done"
    assert v["data"]["visual"]["lab"] is None                 # 两槽互不污染
    # 再开工：库命中秒回（reused=cache 经路由层归一为真值透传）
    stub2 = Stub(result=_json_ok())
    BE.call_llm_for_user = stub2
    p2 = client.post(f"/api/course/lessons/{lid}/visual/principle",
                     json={}, headers=hdr).get_json()
    assert p2["success"] and p2["data"]["reused"] == "cache"
    assert p2["data"]["job"]["state"] == "done"
    assert len(stub2.calls) == 0                              # 零外呼


def test_32_visual_reject_paths(lesson_http):
    client, hdr, lid, _ = lesson_http
    r = client.post(f"/api/course/lessons/{lid}/visual/poster", json={},
                    headers=hdr).get_json()
    assert r["success"] is False and "未知" in r["error"]      # kind 非法：200 拒收（黑板纪律）
    r = client.post("/api/course/lessons/99999999/visual/lab",
                    json={}, headers=hdr)
    assert r.status_code == 404                                 # 不存在课文
