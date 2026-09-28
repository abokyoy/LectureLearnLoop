"""提取页面内联 <script> 并逐段做语法检查，定位 'Unexpected token' 来源。"""
import re
import subprocess
import sys
import urllib.request
import pathlib

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:6001/"
html = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", "replace")
scripts = re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", html, re.S)
tmp = pathlib.Path("tests/_tmp_script_check.js")
bad = []
for i, body in enumerate(scripts):
    if not body.strip():
        continue
    tmp.write_text(body, encoding="utf-8")
    p = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
    if p.returncode != 0:
        # 找到报错行号
        m = re.search(r"_tmp_script_check\.js:(\d+)", p.stderr)
        line = int(m.group(1)) if m else 0
        lines = body.splitlines()
        ctx = "\n".join(lines[max(0, line - 3): line + 2])
        bad.append((i, line, ctx))
        print(f"--- script #{i} syntax error near line {line} ---\n{ctx}\n")
tmp.unlink(missing_ok=True)
if not bad:
    print("all inline scripts pass syntax check")
else:
    print(f"{len(bad)} scripts with syntax errors")
