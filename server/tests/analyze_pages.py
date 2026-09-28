"""检查大页面模板形态：是否Jinja语句/是否完整HTML/依赖哪些全局函数。"""
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TPL = pathlib.Path(r"e:\LLM\LectureLearnLoop\server\templates\pages")
for name in ["online_course_notes.html", "learn_from_materials.html", "practice_materials.html",
             "settings.html", "knowledge_base.html", "llm_logs.html", "dashboard.html",
             "practice_knowledge.html", "practice_errors.html", "memory_knowledge.html", "memory_errors.html"]:
    fp = TPL / name
    if not fp.exists():
        print(name, "MISSING")
        continue
    s = fp.read_text(encoding="utf-8", errors="replace")
    jinja = sorted(set(re.findall(r"\{%\s*(\w+)", s)))
    has_doctype = "<!DOCTYPE" in s[:200] or "<!doctype" in s[:200]
    uses_api = sorted(set(re.findall(r"\b(KnowledgeAPI|PracticeAPI|LLMAPI|FileAPI|NoteAPI|ConfigAPI|api\.(get|post))\b", s)))[:8]
    pyb = sorted(set(re.findall(r"pybridge\.([A-Za-z_]\w*)", s)))
    br = sorted(set(re.findall(r"window\.bridge\.([A-Za-z_]\w*)", s)))
    print(f"\n== {name}: len={len(s)} jinja={jinja} doctype={has_doctype}")
    print(f"   api.js={uses_api}")
    print(f"   pybridge({len(pyb)})={pyb}")
    print(f"   window.bridge({len(br)})={br}")
