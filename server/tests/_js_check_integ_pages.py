# -*- coding: utf-8 -*-
"""提取 integ 工作树指定页面的 <script> 内联 JS，逐个 node --check 校验语法。"""
import re
import subprocess
import sys
import tempfile
import os

ROOT = r"e:\LLM\LectureLearnLoop-integ\server\templates\pages"
PAGES = ["practice_knowledge.html", "memory_knowledge.html", "memory_errors.html",
         "online_course_notes.html", "practice_errors.html", "practice_materials.html",
         "memory_knowledge.html"]
NODE = r"e:\LLM\LectureLearnLoop\tools\node\node.exe"
if not os.path.exists(NODE):
    NODE = "node"

fail = 0
for pg in sorted(set(PAGES)):
    text = open(os.path.join(ROOT, pg), encoding="utf-8", errors="replace").read()
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", text, flags=re.S | re.I)
    for i, b in enumerate(blocks):
        if not b.strip() or 'src=' in b[:60]:
            continue
        # 去 jinja 模板标记，避免误报
        cleaned = re.sub(r"{{.*?}}", "0", b, flags=re.S)
        cleaned = re.sub(r"{%.*?%}", "", cleaned, flags=re.S)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(cleaned)
            path = f.name
        r = subprocess.run([NODE, "--check", path], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            fail += 1
            print(f"[JS FAIL] {pg} block#{i}: {r.stderr.strip()[:200]}")
        os.unlink(path)
    print(f"[done] {pg}")
print("RESULT:", "ALL OK" if fail == 0 else f"{fail} blocks failed")
sys.exit(1 if fail else 0)
