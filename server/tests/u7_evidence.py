# u7 后端取证：最近 practice/new 相关错误
import json

out = []
# debug_trace 最近 30 条含 practice 的
try:
    with open(r"e:\LLM\LectureLearnLoop\server\logs\debug_trace.jsonl", encoding="utf-8") as f:
        rows = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        recent = [r for r in rows[-200:] if "practice" in json.dumps(r, ensure_ascii=False).lower() or "error" in str(r.get("status", "")).lower()]
        out.append("DEBUG_TRACE_RECENT:")
        for r in recent[-12:]:
            out.append(json.dumps(r, ensure_ascii=False)[:300])
except Exception as e:
    out.append("debug_trace err: " + str(e))

# llm_calls 今日
import glob, os
for fp in sorted(glob.glob(r"e:\LLM\LectureLearnLoop\server\logs\llm_calls_*.jsonl"))[-1:]:
    out.append("LLM_LOG_FILE: " + fp)
    with open(fp, encoding="utf-8", errors="ignore") as f:
        lines = [l.strip() for l in f if l.strip()]
    out.append("LLM_CALLS_TAIL:")
    for l in lines[-6:]:
        out.append(l[:400])

# s3 stderr tail
for fp in (r"e:\LLM\LectureLearnLoop\server\logs\s3_stderr.log", r"e:\LLM\LectureLearnLoop\server\logs\s3_stdout.log"):
    if os.path.exists(fp):
        with open(fp, encoding="utf-8", errors="ignore") as f:
            t = f.read()
        out.append(os.path.basename(fp) + " TAIL:")
        out.append(t[-1500:])

open(r"e:\LLM\LectureLearnLoop\server\logs\u7_evidence.txt", "w", encoding="utf-8").write("\n".join(out))
print("written")
