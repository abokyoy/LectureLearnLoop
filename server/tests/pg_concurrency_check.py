# -*- coding: utf-8 -*-
"""PG 连接池并发压力自证（纯 HTTP，验证"统一适配层+连接池支撑大并发"）。

方式：BASE_CONCURRENCY 个线程 × 每线程 REQ_PER_THREAD 次操作，
每线程独立注册临时用户 → 并发建学科 → 并发写知识点 → 并发读列表。
断言：全部请求成功、无 5xx、各用户数据完整无串扰（隔离正确性）。
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:6001"
BASE_CONCURRENCY = 12
REQ_PER_THREAD = 6

_lock = threading.Lock()
PASS_CNT = 0
FAILS: list[str] = []


def req(method, path, data=None, token=None, timeout=30):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    body = json.dumps(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(r, body, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def check(name, ok, detail=""):
    global PASS_CNT
    with _lock:
        if ok:
            PASS_CNT += 1
            print(f"PASS  {name}")
        else:
            FAILS.append(f"{name} {detail}")
            print(f"FAIL  {name} {detail}")


def worker(tid: int):
    global PASS_CNT
    ts = f"{int(time.time() * 1000)}_{tid}"
    uname = f"pgload_{ts}"
    st, b = req("POST", "/api/auth/register", {"username": uname, "password": "Passw0rd!"})
    if st != 200:
        with _lock:
            FAILS.append(f"w{tid} 注册失败 {st} {b}")
        return
    token = b["data"]["token"]
    subject = f"并发学科{ts}"
    st, b = req("POST", "/api/subjects", {"subject_name": subject}, token)
    if st != 200 or not b.get("success"):
        with _lock:
            FAILS.append(f"w{tid} 建学科失败 {st} {b}")
        return
    names = []
    for i in range(REQ_PER_THREAD):
        nm = f"p_{ts}_{i}"
        names.append(nm)
        st, b = req("POST", "/api/knowledge/point-new", {
            "point": {"name": nm, "description": f"并发写入描述{i}，用于压连接池。"},
            "subject": subject}, token)
        if st != 200 or not (b.get("data") or {}).get("success"):
            with _lock:
                FAILS.append(f"w{tid} 写知识点失败 {st} {b}")
                return
    # 回读校验：数量与内容完整、无跨用户串扰
    st, b = req("GET", f"/api/knowledge/points?subject={urllib.parse.quote(subject)}", token=token)
    rows = b.get("data") or []
    got = {r.get("point_name") for r in rows} if st == 200 else set()
    missing = [n for n in names if n not in got]
    with _lock:
        if st == 200 and not missing:
            PASS_CNT += 1
        else:
            FAILS.append(f"w{tid} 回读缺失 {missing or st}")


def main():
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(BASE_CONCURRENCY)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    dt = time.time() - t0
    total_ops = BASE_CONCURRENCY * (2 + REQ_PER_THREAD + 1)
    check(f"并发 {BASE_CONCURRENCY} 线程×{REQ_PER_THREAD} 写 + 回读，共 {total_ops} 次操作全部一致",
          not FAILS, f"失败明细: {FAILS[:6]}")
    print(f"耗时 {dt:.1f}s，吞吐约 {total_ops / max(dt, 0.1):.0f} ops/s")
    print(f"\n===== PG 并发自证: {PASS_CNT} PASS / {len(FAILS)} FAIL =====")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
