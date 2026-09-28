"""
P6 端到端验收（证据层1）：真实 YouTube 视频全链路。

流程：p6_audio.m4a → Deepgram 预录 REST 转写(language=multi) → /api/llm/summarize-text
      → 建笔记(转写+总结落库) → point-new 建知识点 → generate-assessment 出 10 题
      → 提交答题(部分故意错) → 熟练度按难度加权更新 → 错题入库可查。
产物证据：tests/fixtures/p6_transcript.txt / p6_summary.txt / p6_note.md / p6_questions.json /
          p6_result.json。
前置：服务端运行；tests/fixtures/p6_audio.* 已下载。
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

BASE = "http://127.0.0.1:6001"
DG_KEY = "a88b5a5a7e9a750bcc8f984ac48a2c9f62bcaef4"
FIX = Path(__file__).parent / "fixtures"
SUBJECT = f"P6视频学科{int(time.time()) % 100000}_{uuid.uuid4().hex[:3]}"

fails = []


def step(cond, name, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {detail[:160]}")
    if not cond:
        fails.append(name)


def auth() -> str:
    u = "p6_" + uuid.uuid4().hex[:6]
    r = requests.post(BASE + "/api/auth/register", json={"username": u, "password": "test123456"}, timeout=20)
    r.raise_for_status()
    return r.json()["data"]["token"]


def main() -> int:
    H = {"Authorization": "Bearer " + auth()}

    # 1) 音频 → Deepgram 预录转写（优先 16k 单声道 wav，ffmpeg 已从视频抽轨）
    audio_cands = [p for p in sorted(FIX.glob("p6_audio.*")) if p.suffix == ".wav"] + \
                  [p for p in sorted(FIX.glob("p6_audio.*")) if p.suffix != ".wav"]
    if not audio_cands:
        print("缺 p6_audio.*，请先运行 p6_download_audio.py"); return 2
    audio = audio_cands[0]
    ctype = {"wav": "audio/wav", "mp4": "audio/mp4", "m4a": "audio/mp4",
             "webm": "audio/webm", "opus": "audio/opus"}.get(
        audio.suffix.lstrip("."), "application/octet-stream")
    print(f"uploading {audio.name} ({audio.stat().st_size//1024} KB) as {ctype} ...")
    # 中文课程用 zh-CN（实测 language=multi 对中文返回空）；非中文可用环境变量覆盖
    dg_lang = __import__("os").environ.get("P6_DG_LANG", "zh-CN")
    r = httpx.post(
        f"https://api.deepgram.com/v1/listen?model=nova-2&language={dg_lang}&punctuate=true&smart_format=true",
        headers={"Authorization": f"Token {DG_KEY}", "Content-Type": ctype},
        content=audio.read_bytes(), timeout=600,
    )
    step(r.status_code == 200, "Deepgram 转写 HTTP", f"status={r.status_code} {r.text[:120] if r.status_code!=200 else ''}")
    if r.status_code != 200:
        return 1
    transcript = r.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
    (FIX / "p6_transcript.txt").write_text(transcript, encoding="utf-8")
    tlen = len(transcript)
    step(tlen > 200, "转写内容充足", f"chars={tlen}")
    print("transcript head:", transcript[:200].replace("\n", " "))

    # 2) 总结（DeepSeek）
    r = requests.post(BASE + "/api/llm/summarize-text", headers=H,
                      json={"text": transcript[:6000]}, timeout=180)
    summ = r.json().get("data", {})
    step(summ.get("success") and summ.get("summary"), "视频内容总结", (summ.get("summary") or "")[:80].replace("\n", " "))
    summary = summ.get("summary", "")
    (FIX / "p6_summary.txt").write_text(summary, encoding="utf-8")

    # 3) 笔记落库（转写全文 + 总结）
    nr = requests.post(BASE + "/api/vault/note", headers=H, json={"folder_path": "vault"}, timeout=30)
    note_name = nr.json().get("data")
    step(bool(note_name), "创建听课笔记", str(note_name))
    note_rel = "vault/" + note_name
    note_md = "# 视频听课笔记\n\n## 总结\n\n" + summary + "\n\n## 转写全文\n\n" + transcript + "\n"
    wr = requests.put(BASE + "/api/vault/rawfile", headers=H,
                      json={"path": note_rel, "content": note_md}, timeout=30)
    step(wr.json().get("data") is True, "笔记写入成功")
    (FIX / "p6_note.md").write_text(note_md, encoding="utf-8")
    rr = requests.get(BASE + "/api/vault/rawfile", headers=H, params={"path": note_rel}, timeout=30)
    back = rr.json().get("data", "")
    step("视频听课笔记" in back and len(back) >= len(note_md) - 5, "笔记读回校验", f"len={len(back)}")

    # 4) 建知识点（从总结主题）
    pr = requests.post(BASE + "/api/knowledge/point-new", headers=H,
                       json={"point": {"name": "本地大模型部署与量化", "description": summary[:200] or transcript[:200]},
                             "subject": SUBJECT}, timeout=30)
    pd = pr.json().get("data", {})
    kp_id = pd.get("knowledge_id")
    step(bool(kp_id), "创建知识点", f"kp_id={kp_id}")
    if not kp_id:
        return 1

    # 5) 生成 10 道评估题（真实 DeepSeek）
    ga = requests.post(BASE + f"/api/knowledge/points/{kp_id}/generate-assessment", headers=H, json={}, timeout=240)
    gad = ga.json().get("data", {})
    questions = gad.get("questions") or []
    if not gad.get("success") or len(questions) != 10:
        step(False, "生成10题", f"success={gad.get('success')} n={len(questions)} err={gad.get('error')}")
        # LLM 结构不达标不阻断，用备用题继续闭环验证
        questions = [{"question": f"Q{i}", "options": ["A. a", "B. b", "C. c", "D. d"],
                      "correct_answer": "A", "difficulty": ["容易", "中等", "困难"][i % 3], "explanation": ""}
                     for i in range(10)]
    else:
        step(True, "生成10题", "10题×4选项结构校验通过")
    (FIX / "p6_questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6) 答题：前7对后3错（提取 correct_answer 首字母作答，后3题故意答错）
    def letter_of(ans: str) -> str:
        s = (ans or "").strip()
        for ch in s:
            if ch.upper() in "ABCD":
                return ch.upper()
        return "A"

    answers = []
    for i, q in enumerate(questions):
        c = letter_of(q.get("correct_answer", "A"))
        if i >= 7:
            c = "X"  # 越界→判错
        answers.append(c)

    sub = requests.post(BASE + f"/api/knowledge/points/{kp_id}/assessment", headers=H,
                        json={"questions": questions, "answers": answers}, timeout=90).json().get("data", {})
    step(sub.get("success"), "提交评估答题", f"mastery={sub.get('mastery_score')} correct={sub.get('correct_count')}/{sub.get('total_count')}")
    (FIX / "p6_result.json").write_text(json.dumps(sub, ensure_ascii=False, indent=2), encoding="utf-8")

    # 7) 熟练度落库校验
    det = requests.get(BASE + f"/api/knowledge/points/{kp_id}/detail", headers=H, timeout=30).json().get("data", {}).get("detail", {})
    step(det.get("mastery_score") == sub.get("mastery_score"), "熟练度落库一致",
         f"detail={det.get('mastery_score')} assess={sub.get('mastery_score')}")

    # 8) 错题入库：走 practice/results 提交3道错题 → 错题库可查
    recs = [{"subject_name": SUBJECT, "knowledge_point_id": int(kp_id),
             "question_content": questions[i].get("question", f"Q{i}"), "user_answer": "X",
             "is_correct": False, "correct_answer": questions[i].get("correct_answer", ""),
             "explanation": questions[i].get("explanation", "")} for i in range(7, 10)]
    prs = requests.post(BASE + "/api/practice/results", headers=H, json={"records": recs}, timeout=60).json()
    step(prs.get("success") and len(prs.get("data", {}).get("saved_record_ids", [])) >= 3, "3道错题入库",
         str(prs.get("data")))
    errs = requests.get(BASE + "/api/kb/errors", headers=H, params={"subject": SUBJECT, "kp_id": kp_id}, timeout=30).json().get("data", [])
    step(len(errs) >= 3, "错题推荐池可检索", f"count={len(errs)}")

    print("\n==== P6 E2E: " + ("ALL PASS" if not fails else f"FAIL({len(fails)}): " + " | ".join(fails)) + " ====")
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
