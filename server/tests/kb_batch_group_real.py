# -*- coding: utf-8 -*-
"""真机验证：一张图两题裁剪 → 一次 VL 分组调用返回一组题（2026-10-15 用户裁定实弹）。

与离线测试（test_error_batch_group.py）互补：这里走真实 Paddle + Qwen3-VL，
验证「模型真的能按 JSON 数组一次返回多题」这一方案成立前提，并留 token 账单证据。
断言：
  gR01 任务 done，两题均成功（组路径或回退路径都算成功，但组路径必须被真实尝试）
  gR02 两题题干内容各归各题（第一题含「周长」、第二题含「文具盒」，不串题）
  gR03 debug 日志出现 batch_group_done n=2（确系一次分组、全组 2 题）
  gR04 debug 日志 group_pipeline_done questions=2 且 ok=2（组内零回退，一次调用全中）
  gR05 本批 VL 外呼仅 1 次（llm 调用日志 scene 含「批量识别错题」的视觉调用计数）
运行前置：服务端已在 LL_TEST_BASE（默认 http://127.0.0.1:6150）运行。
零残留：删除上传原图与全部裁剪/切片文件。
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("LL_TEST_BASE", "http://127.0.0.1:6150")
API = "/api/kb/error-batch"
DEBUG_LOG = SERVER / "logs" / "debug_trace.jsonl"

RESULTS = {}


def check(cid, desc, ok, detail=""):
    RESULTS[cid] = (ok, desc, detail)
    print(f"[{'PASS' if ok else 'FAIL'}] {cid} {desc}" + (f" | {detail}" if detail else ""))


def register_and_token(username):
    requests.post(BASE + "/api/auth/register",
                  json={"username": username, "password": "test123456"}, timeout=15)
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    tok = r.json()["data"]["token"]
    import base64
    seg = tok.split(".")[1]
    uid = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"]
    return tok, str(uid)


def make_sheet(path):
    """900x600 白纸两题（中文题面，真实字体渲染）。"""
    im = Image.new("RGB", (900, 600), "white")
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 30)
    except OSError:
        font = ImageFont.load_default()
    dr.text((30, 60), "1. 一个长方形长8厘米，宽5厘米。", font=font, fill="black")
    dr.text((30, 120), "它的周长是多少厘米？请列式计算。", font=font, fill="black")
    dr.text((30, 340), "2. 小明有50元，买文具盒花了27元，", font=font, fill="black")
    dr.text((30, 400), "又买书包花了15元，还剩多少元？", font=font, fill="black")
    im.save(path)


def tail_debug(n=400):
    if not DEBUG_LOG.exists():
        return []
    lines = DEBUG_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-n:]


def llm_lines():
    """所有 llm_calls_*.jsonl 的行集合（文件按日命名）。"""
    out = []
    for f in sorted(glob.glob(str(SERVER / "logs" / "llm_calls_*.jsonl")) +
                    glob.glob(str(SERVER.parent / "logs" / "llm_calls_*.jsonl"))):
        try:
            out += Path(f).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            pass
    return out


def main():
    from config import VAULT_DIR
    tag = uuid.uuid4().hex[:8]
    tok, uid = register_and_token(f"ebgrp_{tag}")
    # vault 按用户隔离：图片必须落在 VAULT_DIR/<uid>/截图/（同 test_error_batch_api 口径）
    udir = os.path.join(str(VAULT_DIR), uid, "截图")
    os.makedirs(udir, exist_ok=True)
    rel = f"截图/grp_{tag}.png"
    abs_p = os.path.join(udir, f"grp_{tag}.png")
    make_sheet(abs_p)

    h = {"Authorization": f"Bearer {tok}"}
    debug_mark = len(tail_debug(10_000_000))  # 只看本次之后的日志
    llm_mark = len(llm_lines())

    body = {"items": [{"image": rel, "boxes": [
        {"id": 1, "x": 0.02, "y": 0.05, "w": 0.9, "h": 0.40},
        {"id": 2, "x": 0.02, "y": 0.55, "w": 0.9, "h": 0.35},
    ]}]}
    r = requests.post(BASE + API, headers=h, json=body, timeout=30)
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["task_id"]

    end = time.time() + 300  # 组路径：2 次 Paddle + 1 次大输出 VL，预算 5 分钟
    data = None
    while time.time() < end:
        d = requests.get(BASE + API + f"/{tid}", headers=h, timeout=15).json()["data"]
        if d.get("status") != "running":
            data = d
            break
        time.sleep(3)
    if data is None:
        check("gR01", "任务进入终态", False, "300s 超时")
        return finish(abs_p, tag)

    res = data.get("results") or []
    ok_n = sum(1 for x in res if x.get("ok"))
    check("gR01", "任务 done 且两题成功", data.get("status") == "done" and ok_n == 2,
          f"status={data.get('status')} ok={ok_n} err={[x.get('error') for x in res if not x.get('ok')]}")

    stems = {x["box_id"]: x.get("stem_md") or "" for x in res}
    check("gR02", "两题各归各题不串题",
          "周长" in stems.get(1, "") and "文具盒" in stems.get(2, ""),
          f"q1={stems.get(1, '')[:40]!r} q2={stems.get(2, '')[:40]!r}")

    all_lines = tail_debug(10_000_000)
    new_lines = all_lines[debug_mark:] if debug_mark <= len(all_lines) else all_lines
    events = []
    for ln in new_lines:
        try:
            events.append(json.loads(ln))
        except ValueError:
            continue

    def ev(name, **kw):
        for e in events:
            d = e.get("data") or {}
            if e.get("action") == name and all(str(d.get(k)) == str(v) for k, v in kw.items()):
                return True
        return False

    check("gR03", "分组尝试发生（batch_group_done n=2）",
          ev("batch_group_done", n=2))
    check("gR04", "一次调用全组命中（group_pipeline_done questions=2 ok=2，零回退）",
          ev("group_pipeline_done", questions=2, ok=2))

    # VL 外呼计数：提交后新增的成行功 LL 调用（组提示词开头可识别；回退单题会是「错题整理器」）
    new_llm = llm_lines()[llm_mark:]
    grp_calls = single_calls = 0
    for ln in new_llm:
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if not o.get("success"):
            continue
        prev = o.get("prompt_preview") or ""
        if "错题批量整理器" in prev:
            grp_calls += 1
        elif "错题整理器" in prev:
            single_calls += 1
    check("gR05", "整批 VL 调用恰为 1 次分组调用（零单题回退外呼）",
          grp_calls == 1 and single_calls == 0, f"group_calls={grp_calls} single_calls={single_calls}")
    return finish(abs_p, tag)


def finish(abs_p, tag):
    # 清理：上传原图 + 其全部裁剪/切片
    try:
        os.remove(abs_p)
    except OSError:
        pass
    d = os.path.dirname(abs_p)
    for f in os.listdir(d):
        if f.startswith(f"grp_{tag}_q") or (f.startswith(f"grp_{tag}") and "_fig" in f):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    fails = [c for c, (ok, _, _) in RESULTS.items() if not ok]
    print("ALL_PASS" if not fails else f"FAILED: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
