# -*- coding: utf-8 -*-
"""导出 integ worktree 相对 feat/integration tip 的未提交 diff（字节安全）。"""
import subprocess, pathlib

WG = pathlib.Path("E:/LLM/LectureLearnLoop-integ")
OUT = pathlib.Path(__file__).resolve().parents[1] / "logs"
FILES = ["server/services/fsrs_service.py", "server/routes_bridge.py", "server/app.py",
         "server/static/js/api.js", "server/templates/pages/memory_knowledge.html",
         "server/templates/pages/memory_errors.html", "server/templates/pages/practice_knowledge.html"]
r = subprocess.run(["git", "-C", str(WG), "diff", "--"] + FILES, capture_output=True)
(OUT / "u15_integ_wt.diff").write_bytes(r.stdout)
print("diff bytes:", len(r.stdout), "err:", r.stderr.decode("utf-8", "replace")[:100])
# stat 版
r2 = subprocess.run(["git", "-C", str(WG), "diff", "--stat", "--"] + FILES, capture_output=True)
(OUT / "u15_integ_wt_stat.txt").write_bytes(r2.stdout)
print(r2.stdout.decode("utf-8", "replace"))
# 完整运行版拷贝（worktree 实际生效代码，供移植参考）
for f in FILES:
    src = WG / f
    dst_name = "_wt_" + f.split("/")[-1]
    (OUT.parent / dst_name).write_bytes(src.read_bytes())
    print("COPY", f, "->", dst_name, src.stat().st_size)

