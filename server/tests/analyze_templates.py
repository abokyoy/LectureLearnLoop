"""分析模板：SPA 页面加载机制 / pybridge 调用清单 / API 路径清单。"""
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TPL = pathlib.Path(r"e:\LLM\LectureLearnLoop\server\templates")

for f in ["base.html", "components/sidebar.html", "components/header.html"]:
    s = (TPL / f).read_text(encoding="utf-8", errors="replace")
    print(f"\n========== {f} (len={len(s)}) ==========")
    for p in ["loadPage", "content-area", "fetch(", "pybridge", "window.location",
              "loadContent", "navigate", "onclick=\"location", "handleMenuClick"]:
        print(f"  {p!r}: {len(re.findall(re.escape(p), s))}")
    print("  /api paths:", sorted(set(re.findall(r"""['"](/api/[\w/\-]+)""", s))))
    print("  page urls:", sorted(set(re.findall(r"""['"](/[\w_\-]+\.html|/[\w_\-/]+)['"][^<]*['"]""", s)))[:20])

# 汇总所有模板引用的后端 URL（api.js 兼容层设计依据）
all_urls = {}
for fp in TPL.rglob("*.html"):
    s = fp.read_text(encoding="utf-8", errors="replace")
    for u in set(re.findall(r"""['"](/api/[\w/\-]+)['"]""", s)):
        all_urls.setdefault(u, []).append(fp.name)
print("\n========== 全部模板引用的 /api 路径 ==========")
for u, files in sorted(all_urls.items()):
    print(f"  {u}  <- {len(files)} files")
