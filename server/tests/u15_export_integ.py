# -*- coding: utf-8 -*-
"""从 feat/integration 分支按字节导出核心文件，绕开 PowerShell 编码转坏问题（P037 族）。"""
import subprocess
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]  # server/
BR = "feat/integration"
FILES = [
    ("server/services/fsrs_service.py", "_integ_fsrs_service.py"),
    ("server/static/js/widgets.js", "_integ_widgets.js"),
    ("server/routes_memory.py", "_integ_routes_memory.py"),
    ("server/tools/apply_fsrs_schema.py", "_integ_apply_fsrs_schema.py"),
    # 集成线被改过的页面/路由参考（评审移植面）
    ("server/templates/pages/memory_knowledge.html", "_integ_memory_knowledge.html"),
    ("server/templates/pages/memory_errors.html", "_integ_memory_errors.html"),
]

out = []
# 集成线 routes_knowledge 的 curve/stars/mastery_manual 端点段（L330-470）落盘供阅读
rk = subprocess.run(["git", "-C", str(ROOT.parent), "show", f"{BR}:server/routes_knowledge.py"], capture_output=True)
if rk.returncode == 0:
    txt = rk.stdout.decode("utf-8", "replace").splitlines()
    (ROOT / "logs" / "u15_routes_kn_seg.txt").write_text(
        "\n".join(f"{i+300:4d}| {l}" for i, l in enumerate(txt[299:480])), encoding="utf-8")
    out.append("OK routes_knowledge seg 300-480")

for src, dst in FILES:
    r = subprocess.run(["git", "-C", str(ROOT.parent), "show", f"{BR}:{src}"], capture_output=True)
    if r.returncode != 0:
        out.append(f"FAIL {src}: {r.stderr.decode('utf-8', 'replace')[:120]}")
        continue
    (ROOT / dst).write_bytes(r.stdout)
    out.append(f"OK {src} -> {dst} ({len(r.stdout)} bytes)")

(ROOT / "logs" / "u15_export.txt").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
