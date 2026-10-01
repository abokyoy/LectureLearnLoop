# -*- coding: utf-8 -*-
"""列出 r2 相关蓝图的全部路由（路径+方法），供测试文档核对。"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
FILES = [
    r"e:\LLM\LectureLearnLoop-integ\server\routes_kp_polish.py",
    r"e:\LLM\LectureLearnLoop-integ\server\routes_err_polish.py",
    r"e:\LLM\LectureLearnLoop-integ\server\routes_memory.py",
    r"e:\LLM\LectureLearnLoop-integ\server\routes_knowledge.py",
]
pat = re.compile(r"@(\w+)\.route\(\s*[\"']([^\"']+)[\"'](?:[^)]*methods=\[([^\]]+)\])?", re.S)
for f in FILES:
    text = open(f, encoding="utf-8").read()
    print("==== " + f.split("\\")[-1])
    for bp, path, methods in pat.findall(text):
        ms = (methods or '"GET"').replace("'", "").replace(" ", "")
        print(f"  {ms:<20} {path}")
