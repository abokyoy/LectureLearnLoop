# 一次性：交付自检——线上服务出的 JS/接口已含评审修复后代码
import urllib.request

js = urllib.request.urlopen("http://127.0.0.1:6001/static/js/pm_pages.js", timeout=10).read().decode("utf-8")
res = [
    ("SERVE_FLIPCARD", "pm-flip-scene" in js),
    ("SERVE_INDEX_LETTER", "String.fromCharCode(65 + idx)" in js),
    ("SERVE_PREF_SUBJ", "preferredSubject" in js),
    ("SERVE_MARK_LOCK", "CodeReview Minor-6" in js or "lockSel" in js),
]
open(r"e:\LLM\LectureLearnLoop\server\logs\u14_servecheck.txt", "w", encoding="utf-8").write(
    "\n".join(f"{k}={v}" for k, v in res))
print("\n".join(f"{k}={v}" for k, v in res))
