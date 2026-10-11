# -*- coding: utf-8 -*-
"""错题智能分析·全链路集成自证（2026-10-13）。真调 Paddle 版面 + 系统 VL，打外网。

流程：PIL 造仿真几何题图（文字题干+三角形+学生错误解答）→ 写入测试用户 vault
→ POST /api/kb/error-analyze → 轮询 done → 断言回填契约 → 核对 debug_trace.jsonl。

前置：服务端已在 127.0.0.1:6001 运行（新代码+VL .env 已加载）。
运行：python tests/integ_error_analyze_e2e.py（结果落盘 tests/_integ_ae_result.txt，避免管道噪声）
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import uuid

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:6001"
RESULT = pathlib.Path(__file__).with_name("_integ_ae_result.txt")
FONT = r"C:\Windows\Fonts\msyh.ttc"

checks = []


def step(name, ok, detail=""):
    checks.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def make_geom_image(path: pathlib.Path) -> None:
    """仿真错题图：印刷体题干 + 几何三角形图 + 学生手写体错误解答。"""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1200, 800
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    f_big = ImageFont.truetype(FONT, 34)
    f_mid = ImageFont.truetype(FONT, 30)
    f_small = ImageFont.truetype(FONT, 26)

    d.text((40, 40), "如图所示，在三角形 ABC 中，AB = AC，", font=f_big, fill="black")
    d.text((40, 100), "角 A = 40°，则角 B 的度数为 ____ 度。", font=f_big, fill="black")

    # 三角形（居中偏右）：A 顶、B 左下、C 右下
    A, B, C = (760, 180), (560, 470), (960, 470)
    d.line([A, B, C, A], fill="black", width=4)
    d.text((A[0] - 10, A[1] - 50), "A", font=f_mid, fill="black")
    d.text((B[0] - 40, B[1] - 10), "B", font=f_mid, fill="black")
    d.text((C[0] + 14, C[1] - 10), "C", font=f_mid, fill="black")
    d.text((655, 300), "40°", font=f_small, fill="black")  # 顶角标注

    d.text((40, 560), "解：因为 AB = AC，", font=f_big, fill=(20, 20, 200))
    d.text((40, 620), "所以角 B = 角 A = 40°。", font=f_big, fill=(20, 20, 200))
    im.save(path)


def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    u = f"ae2e_{suffix}"
    requests.post(BASE + "/api/auth/register",
                  json={"username": u, "password": "test123456"}, timeout=15)
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": u, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    tok = r.json()["data"]["token"]
    h = {"Authorization": f"Bearer {tok}"}
    uid = str(requests.get(BASE + "/api/auth/me", headers=h, timeout=15
                           ).json()["data"]["user_id"])

    from config import VAULT_DIR
    vdir = pathlib.Path(VAULT_DIR) / uid / "截图"
    vdir.mkdir(parents=True, exist_ok=True)
    img = vdir / f"geom_{suffix}.png"
    make_geom_image(img)
    rel = f"截图/{img.name}"
    print(f"vault img: {img}")

    draft = (f"我在三角形题上错了，题目如图。\n![题目]({rel})\n"
             f"我的解答写在图下方：AB=AC 所以角B=角A=40°。")
    r = requests.post(BASE + "/api/kb/error-analyze", headers=h,
                      json={"content": draft}, timeout=30)
    step("api200_task_created", r.status_code == 200, r.text[:120])
    if r.status_code != 200:
        return dump_finish(1)

    tid = r.json()["data"]["task_id"]
    deadline = time.time() + 300
    res = None
    while time.time() < deadline:
        rr = requests.get(f"{BASE}/api/kb/error-analyze/{tid}", headers=h, timeout=30)
        if rr.status_code != 200:
            time.sleep(3)
            continue
        res = rr.json()["data"]
        if res.get("status") in ("done", "error"):
            break
        time.sleep(3)

    step("task_finished", res is not None and res.get("status") in ("done", "error"),
         f"status={res and res.get('status')}")
    print("RAW_RESULT:", json.dumps(res, ensure_ascii=False)[:1200])
    if not res or res.get("status") != "done":
        step("done_status", False, f"error={res and res.get('error')}")
        return dump_finish(1)

    stem = res.get("stem_md") or ""
    answer = res.get("correct_answer") or ""
    explain = res.get("explanation") or ""
    step("stem_not_empty", bool(stem), f"len={len(stem)}")
    step("stem_keeps_key_text", ("三角形" in stem or "ABC" in stem) and "40" in stem,
         stem[:120])
    step("stem_refs_crop_slice", "_fig" in stem, stem[-160:])
    step("answer_present", bool(answer), answer[:80])
    step("explain_has_solution_section", explain.startswith("## 我的解答"), explain[:100])
    step("explain_has_error_analysis", "## 错在哪里" in explain)
    step("crop_files_on_disk", any(vdir.glob(f"geom_{suffix}_fig*.png")),
         str([p.name for p in vdir.iterdir()]))

    # debug_trace 链路核对
    dt = pathlib.Path(__file__).resolve().parents[1] / "logs" / "debug_trace.jsonl"  # server/logs
    analyze_rows = []
    if dt.exists():
        for line in dt.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("module") == "analyze":
                analyze_rows.append(o.get("action"))
    step("debug_trace_analyze_chain",
         "paddle_layout_done" in analyze_rows and "error_analyze_done" in analyze_rows,
         str(analyze_rows[-8:]))

    # 清理 vault 测试文件（切片+原图）
    for p in vdir.glob(f"geom_{suffix}*"):
        p.unlink(missing_ok=True)
    try:
        vdir.rmdir()
    except OSError:
        pass
    return dump_finish(0)


def dump_finish(code: int) -> int:
    fails = [n for n, ok in checks if not ok]
    RESULT.write_text(
        f"TOTAL={len(checks)} FAIL={len(fails)} {fails}\n", encoding="utf-8")
    print(f"== finish code={code} fails={fails}")
    return code


if __name__ == "__main__":
    sys.exit(main())
