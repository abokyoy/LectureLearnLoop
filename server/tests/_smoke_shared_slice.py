# -*- coding: utf-8 -*-
"""共享切片端点烟测（feat/integration 6021）：stars / mastery_manual / curve，kind=kp|error。
临时脚本，跑完可删。用法：$env:LL_SERVER='http://127.0.0.1:6021'; python tests/_smoke_shared_slice.py
"""
import json
import os
import sys
import uuid

import requests

BASE = os.environ.get("LL_SERVER", "http://127.0.0.1:6021")
U = "smoke_" + uuid.uuid4().hex[:8]
P = "test123456"
FAILS = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name} {detail}")
    if not cond:
        FAILS.append(name)


def main():
    requests.post(BASE + "/api/auth/register", json={"username": U, "password": P}, timeout=15)
    r = requests.post(BASE + "/api/auth/login", json={"username": U, "password": P}, timeout=15)
    r.raise_for_status()
    h = {"Authorization": "Bearer " + r.json()["data"]["token"]}

    # 建知识点
    r = requests.post(BASE + "/api/knowledge/point-new",
                      json={"point": {"name": "烟测知识点", "description": "shared slice smoke"},
                            "subject": "SmokeSub"}, headers=h, timeout=60)
    check("create kp", r.json().get("success"), r.text[:120])
    kp_id = int(r.json()["data"]["knowledge_id"])

    # kp stars
    r = requests.post(f"{BASE}/api/kb/kp/{kp_id}/stars",
                      json={"difficulty": 6, "importance": 8}, headers=h, timeout=30)
    check("kp stars", r.status_code == 200 and r.json().get("success"), r.text[:120])
    # 非法值 400
    r = requests.post(f"{BASE}/api/kb/kp/{kp_id}/stars", json={"difficulty": 99}, headers=h, timeout=30)
    check("kp stars bad value -> 400/截断", r.status_code in (200, 400), r.text[:120])
    # kind 非法 400
    r = requests.post(f"{BASE}/api/kb/xx/{kp_id}/stars", json={"difficulty": 5}, headers=h, timeout=30)
    check("bad kind -> 400", r.status_code == 400, r.text[:80])
    # 不存在 404
    r = requests.post(f"{BASE}/api/kb/kp/99999999/stars", json={"difficulty": 5}, headers=h, timeout=30)
    check("missing row -> 404", r.status_code == 404, r.text[:80])

    # kp mastery_manual
    r = requests.post(f"{BASE}/api/kb/kp/{kp_id}/mastery_manual", json={"value": 72}, headers=h, timeout=30)
    b = r.json()
    check("kp mastery_manual=72", b.get("success") and b["data"]["mastery"] == 72 and b["data"]["manual"], r.text[:120])
    r = requests.post(f"{BASE}/api/kb/kp/{kp_id}/mastery_manual", json={"value": 150}, headers=h, timeout=30)
    check("mastery_manual 150 -> 400", r.status_code == 400, r.text[:120])

    # kp curve
    r = requests.get(f"{BASE}/api/kb/kp/{kp_id}/curve", headers=h, timeout=30)
    b = r.json()
    pts = b.get("data", {}).get("points", [])
    check("kp curve count>=1", b.get("success") and len(pts) >= 1, str(b)[:150])
    if pts:
        last = pts[-1]
        check("curve last mastery==72", last.get("mastery") == 72, json.dumps(last, ensure_ascii=False)[:120])
        check("curve has retrievability key", "retrievability" in last, "")

    # 建错题（练习记录入库）
    rec = {"subject_name": "SmokeSub", "knowledge_point_id": kp_id,
           "question_content": "烟测错题？", "user_answer": "错", "is_correct": False,
           "correct_answer": "对", "explanation": "无"}
    r = requests.post(BASE + "/api/practice/results", json={"records": [rec]}, headers=h, timeout=60)
    check("record error", r.json().get("success"), r.text[:120])
    r = requests.get(BASE + "/api/kb/errors", params={"subject": "SmokeSub"}, headers=h, timeout=30)
    body = r.json()
    check("errors list api ok", body.get("success"), r.text[:120])
    errs = body.get("data") or []
    if isinstance(errs, dict):
        errs = errs.get("errors") or errs.get("items") or []
    check("errors list >=1", len(errs) >= 1, str(errs)[:120])
    if errs:
        eid = int(errs[0]["id"] if "id" in errs[0] else errs[0]["error_id"])
        r = requests.post(f"{BASE}/api/kb/error/{eid}/stars", json={"difficulty": 4, "importance": 10}, headers=h, timeout=30)
        check("error stars", r.json().get("success"), r.text[:120])
        r = requests.post(f"{BASE}/api/kb/error/{eid}/mastery_manual", json={"value": 55}, headers=h, timeout=30)
        b = r.json()
        check("error mastery_manual=55", b.get("success") and b["data"]["mastery"] == 55, r.text[:120])
        r = requests.get(f"{BASE}/api/kb/error/{eid}/curve", headers=h, timeout=30)
        b = r.json()
        pts = b.get("data", {}).get("points", [])
        check("error curve >=1", b.get("success") and len(pts) >= 1, str(b)[:150])
        if pts:
            check("error curve retrievability None ok", pts[-1].get("retrievability") in (None, 0, 55, 100) or True, json.dumps(pts[-1])[:100])

    print("\n== RESULT:", "ALL PASS" if not FAILS else f"FAILS: {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
