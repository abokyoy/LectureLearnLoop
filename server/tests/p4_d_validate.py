# -*- coding: utf-8 -*-
"""四期D组静态校验：py_compile + 全模板内联 JS node --check + api.js 语法。

直接运行：python tests/p4_d_validate.py（无需服务器）。
"""
import pathlib
import py_compile
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAILS = []


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (" " + detail[:200] if detail else ""))
    if not cond:
        FAILS.append(name)


# 1. python 文件编译
for pyf in ["routes_pages.py", "routes_bridge.py", "auth.py", "app.py"]:
    p = ROOT / pyf
    if not p.exists():
        continue
    try:
        py_compile.compile(str(p), doraise=True)
        check("py_compile " + pyf, True)
    except Exception as e:  # noqa: BLE001
        check("py_compile " + pyf, False, str(e))

# 2. api.js 语法
try:
    r = subprocess.run(["node", "--check", str(ROOT / "static" / "js" / "api.js")],
                       capture_output=True, text=True)
    check("node --check api.js", r.returncode == 0, r.stderr)
except Exception as e:  # noqa: BLE001
    check("node --check api.js", False, str(e))

# 3. 全部模板内联 <script>（非 src）逐段 node --check
tpl_dir = ROOT / "templates"
tmp = ROOT / "tests" / "_p4d_inline.js"  # 项目盘内临时文件（避免系统盘满）
total = bad = 0
for tpl in sorted(tpl_dir.rglob("*.html")):
    if "_backup" in tpl.name:
        continue  # 历史回退备份（不挂路由，Qt 期嵌套模板字面量不在本期校验范围）
    html = tpl.read_text(encoding="utf-8", errors="replace")
    # 去掉 jinja 表达式/控制语句，避免干扰 JS 解析（保留行结构）
    html = re.sub(r"\{\{.*?\}\}", "'jinja'", html, flags=re.S)
    html = re.sub(r"\{%.*?%\}", "", html, flags=re.S)
    for i, body in enumerate(re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", html, re.S)):
        if not body.strip():
            continue
        total += 1
        tmp.write_text(body, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
        if r.returncode != 0:
            bad += 1
            check("inline js %s#%d" % (tpl.name, i), False, r.stderr)
tmp.unlink(missing_ok=True)
check("templates inline JS: %d 段全部通过" % total, bad == 0, "bad=%d" % bad)

print("----")
print("PASS %d / FAIL %d" % (0, len(FAILS)) if FAILS else "ALL STATIC CHECKS OK")
sys.exit(1 if FAILS else 0)
