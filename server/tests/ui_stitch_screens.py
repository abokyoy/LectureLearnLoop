# 查询 Stitch 项目下已有屏幕（确认超时调用是否已在服务端生成，避免重复耗额度）
# 调用登记：2026-10-01 本脚本 1 次 list_projects + 1 次 list_screens = 2 次
import sys, io, os, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stitch_client import rpc

OUTFILE = r"e:\LLM\LectureLearnLoop\server\logs\stitch_screens_out.txt"
lines = []
st, j = rpc("tools/call", {"name": "list_projects", "arguments": {}})
txt = json.dumps(j, ensure_ascii=False)
pid = None
tp = txt.find('"CorgiStudy UI Redesign"')
if tp >= 0:
    seg = txt[:tp]
    pm = re.search(r'projects/(\d+)(?!.*projects/\d+)', seg, re.S)
    if pm:
        pid = pm.group(1)
lines.append(f"HTTP {st} pid={pid}")
if pid:
    st2, j2 = rpc("tools/call", {"name": "list_screens", "arguments": {"projectId": pid}}, timeout=90)
    t2 = json.dumps(j2, ensure_ascii=False)
    lines.append(f"list_screens HTTP {st2} len={len(t2)}")
    # 提取每个 screen 的 name/displayName 与缩略图 URL
    for sm in re.finditer(r'\{[^{}]*?"displayName"\s*:\s*"([^"]*)"[^{}]*?\}', t2):
        lines.append("screen: " + sm.group(1))
    names = re.findall(r'"displayName"\s*:\s*"([^"]{0,80})"', t2)
    lines.append("displayNames: " + str(names))
    urls = [u for u in re.findall(r'https://[^\s"\\]+', t2) if any(k in u.lower() for k in ("png", "jpg", "screenshot", "storage", "download"))]
    lines.append("urls (%d):" % len(urls))
    lines.extend(urls[:20])
    with open(r"e:\LLM\LectureLearnLoop\server\logs\stitch_screens_raw.json", "w", encoding="utf-8") as f:
        f.write(t2)
with open(OUTFILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("written", OUTFILE)
