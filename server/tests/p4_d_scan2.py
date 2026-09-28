# 四期D组调研：确认 block1 旧菜单变量在删除区(8954-9257)之外无引用
import re
from pathlib import Path

text = Path(__file__).resolve().parents[1].joinpath("templates/pages/online_course_notes.html").read_text(encoding="utf-8")
lines = text.splitlines()

pats = {
    "selectedText": re.compile(r"\bselectedText\b"),
    "contextMenu(bare)": re.compile(r"(?<![.\w-])contextMenu(?![\w-])"),
    "hideContextMenu": re.compile(r"hideContextMenu"),
    "initContextMenu": re.compile(r"initContextMenu"),
    "createContextMenu": re.compile(r"createContextMenu"),
    "handleContextMenu": re.compile(r"handleContextMenu"),
    "handleTextSelection": re.compile(r"handleTextSelection"),
}

for name, pat in pats.items():
    hits = [i + 1 for i, l in enumerate(lines) if pat.search(l)]
    outside = [n for n in hits if not (8954 <= n <= 9257)]
    print(f"{name}: total={len(hits)} 删除区外={outside}")
