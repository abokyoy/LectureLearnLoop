# 落盘 list_projects 原始响应，检查项目是否存在及其字段结构
import sys, io, os, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stitch_client import rpc
st, j = rpc("tools/call", {"name": "list_projects", "arguments": {}}, timeout=90)
with open(r"e:\LLM\LectureLearnLoop\server\logs\stitch_projects_raw.json", "w", encoding="utf-8") as f:
    json.dump(j, f, ensure_ascii=False, indent=1)
print("HTTP", st)
