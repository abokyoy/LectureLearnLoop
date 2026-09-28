"""定位 base.html 中 bridge 初始化/导航机制，决定兼容层插入点。"""
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

s = pathlib.Path(r"e:\LLM\LectureLearnLoop\server\templates\base.html").read_text(encoding="utf-8", errors="replace")

for kw in ["pybridge", "QWebChannel", "window.bridge", "var bridge", "let bridge", "const bridge",
           "on_bridge_ready", "block scripts", "</head>", "{% block", "window.location"]:
    for m in re.finditer(re.escape(kw), s):
        ln = s[:m.start()].count("\n") + 1
        line_start = s.rfind("\n", 0, m.start()) + 1
        line_end = s.find("\n", m.start())
        print(f"L{ln:>5} {kw:<18} | {s[line_start:line_end].strip()[:110]}")
    print("-" * 40)
