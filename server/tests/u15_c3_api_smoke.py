# -*- coding: utf-8 -*-
"""c3 记忆数据面板 API 冒烟：/fsrs 快照 + curve + stars + mastery_manual + rate 清手动 全链路。
测试数据 U15C3S 前缀，跑完 DB 直删（遵循 PG 测试数据隔离，同 u15_c2 口径）。
"""
import base64
import json
import sys
import urllib.request
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import db_adapter  # noqa: E402
import config  # noqa: E402

BASE = "http://127.0.0.1:6001"
TK = open(r"logs\ui_walk_token.txt", encoding="utf-8").read().strip()
_seg = TK.split(".")[1]
_seg += "=" * (-len(_seg) % 4)
UID = json.loads(base64.urlsafe_b64decode(_seg))["uid"]
SUBJECT = "U15C3S" + uuid.uuid4().hex[:6]


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Authorization": "Bearer " + TK,
                                        "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _purge(pid):
    c = db_adapter.get_connection(str(config.DB_PATH))
    try:
        cur = c.cursor()
        cur.execute("DELETE FROM kp_proficiency_history WHERE user_id = ? AND knowledge_point_id = ?", (UID, pid))
        cur.execute("DELETE FROM knowledge_point_sources WHERE knowledge_point_id = ?", (pid,))
        cur.execute("DELETE FROM knowledge_points WHERE id = ? AND user_id = ?", (pid, UID))
        cur.execute("DELETE FROM user_subjects WHERE user_id = ? AND subject_name = ?", (UID, SUBJECT))
        c.commit()
    finally:
        c.close()


def main():
    created = req("POST", "/api/knowledge/point-new",
                  {"subject": SUBJECT, "point": {"name": "U15C3P 冒烟点", "description": "c3 面板冒烟"}})
    assert created["data"]["success"], created
    pid = created["data"]["knowledge_id"]
    print("kp created:", pid)

    # 1) /fsrs 快照
    view = req("GET", f"/api/kb/kp/{pid}/fsrs")["data"]
    assert set(view) == {"difficulty", "importance", "mastery", "state", "due", "manual"}, view
    print("fsrs view:", view)

    # 2) curve（新建应为空点集，不报错）
    cur = req("GET", f"/api/kb/kp/{pid}/curve")["data"]
    assert "points" in cur, cur
    print("curve count:", cur["count"])

    # 3) stars 写入并读回
    req("POST", f"/api/kb/kp/{pid}/stars", {"difficulty": 8, "importance": 6})
    view2 = req("GET", f"/api/kb/kp/{pid}/fsrs")["data"]
    assert view2["difficulty"] == 8 and view2["importance"] == 6, view2
    print("stars roundtrip OK:", view2["difficulty"], view2["importance"])

    # 4) mastery_manual 写入并读回（manual=1）
    req("POST", f"/api/kb/kp/{pid}/mastery_manual", {"value": 77})
    view3 = req("GET", f"/api/kb/kp/{pid}/fsrs")["data"]
    assert view3["mastery"] == 77 and view3["manual"] == 1, view3
    print("manual mastery roundtrip OK:", view3["mastery"], "manual:", view3["manual"])

    # 5) curve 应含手动设定追写的历史点
    cur2 = req("GET", f"/api/kb/kp/{pid}/curve")["data"]
    assert cur2["count"] >= 1 and cur2["points"][-1]["mastery"] == 77, cur2
    print("curve after manual:", cur2["count"], "pts, last mastery", cur2["points"][-1]["mastery"])

    # 6) 自评后 manual 标记被清（apply_review 语义）
    req("POST", f"/api/kb/kp/{pid}/rate", {"self_assessment": "familiar"})
    view4 = req("GET", f"/api/kb/kp/{pid}/fsrs")["data"]
    assert view4["manual"] == 0, view4
    print("rate cleared manual OK; state:", view4["state"], "mastery:", view4["mastery"])

    # 7) 404 口径：不存在的 rid
    try:
        req("GET", "/api/kb/kp/99999999/fsrs")
        print("FAIL: expected 404")
        sys.exit(1)
    except urllib.error.HTTPError as e:
        assert e.code == 404, e.code
        print("404 gate OK")

    _purge(pid)
    print("cleanup done")
    print("ALL_PASS")


if __name__ == "__main__":
    try:
        main()
    finally:
        pass
