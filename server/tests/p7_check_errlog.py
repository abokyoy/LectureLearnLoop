"""验收标准8自检：debug_trace.jsonl 无 error 级记录（近 2000 条）。"""
import io
import json

lines = io.open("logs/debug_trace.jsonl", encoding="utf-8").readlines()
errs = []
for l in lines:
    try:
        e = json.loads(l)
    except Exception:
        continue
    blob = json.dumps(e, ensure_ascii=False).lower()
    if '"level": "error"' in blob or '"status": "error"' in blob or '"error"' in blob and '"success"' not in blob:
        errs.append(e)
print("total:", len(lines), "error-like:", len(errs))
for e in errs[-8:]:
    print(json.dumps(e, ensure_ascii=False)[:220])
