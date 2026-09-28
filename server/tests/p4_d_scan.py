# -*- coding: utf-8 -*-
"""四期 D 组调研：清点 online_course_notes 中 pybridge.* 调用与 api.js 兼容层已实现方法的差集。"""
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
h = (root / "templates/pages/online_course_notes.html").read_text(encoding="utf-8")
a = (root / "static/js/api.js").read_text(encoding="utf-8")

used = sorted(set(re.findall(r"pybridge\.([A-Za-z_]\w*)", h)))
missing = [m for m in used if not re.search(r"bridge\.%s\s*=" % re.escape(m), a)
           and not re.search(r"['\"]%s['\"]\s*:" % re.escape(m), a)
           and not re.search(r"def\s+%s" % m, a)]
print("pybridge methods used in page:", len(used))
print("NOT provided by api.js (dead calls):")
for m in missing:
    print("  -", m)

# learn_from_materials 的文件树实现概览
lm = (root / "templates/pages/learn_from_materials.html").read_text(encoding="utf-8")
print("\nlearn_from_materials fetch endpoints:")
print(sorted(set(re.findall(r"fetch\('([^']+)'", lm))))
print("\nlearn_from_materials tree functions:")
print(sorted(set(re.findall(r"(?:function|window\.)\s*([A-Za-z]\w*(?:Folder|File|Tree|tree|Drop|drag)\w*)\s*[=(]", lm)))[:40])

# 网课笔记中的'测试文本'与双选中变量位置
for pat in ["测试文本", "selectedTextForMenu", "handlePractice", "深入学", "contextMenu"]:
    lines = [i + 1 for i, line in enumerate(h.splitlines()) if pat in line]
    print(f"\npattern {pat!r} lines: {lines}")
