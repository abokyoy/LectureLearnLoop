# Stitch MCP 直连客户端（HTTP JSON-RPC，走 V2RAYN 代理）
# 用法:
#   python stitch_client.py tools/list                    -> 列工具
#   python stitch_client.py tools/call <tool> '<json>'    -> 调工具
# 输出统一落盘 server/logs/stitch_last.json 并打印摘要
import json, sys, io, os
import requests

URL = "https://stitch.googleapis.com/mcp"
KEY = "*REMOVED-BY-FILTER-REPO*"
PROXY = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}
OUT = r"e:\LLM\LectureLearnLoop\server\logs\stitch_last.json"

def rpc(method, params=None, rid=1, timeout=60):
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
    r = requests.post(URL, json=body, headers={
        "X-Goog-Api-Key": KEY,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }, proxies=PROXY, timeout=timeout)
    text = r.text
    # streamable HTTP 可能返回 SSE 格式（data: {...}），取最后一个 data 行
    if text.lstrip().startswith("event:") or "\ndata: " in text or text.lstrip().startswith("data:"):
        datas = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        if datas:
            text = datas[-1]
    try:
        return r.status_code, json.loads(text)
    except Exception:
        return r.status_code, {"raw": text[:2000]}

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    method = sys.argv[1] if len(sys.argv) > 1 else "tools/list"
    params = {}
    if method == "tools/call" and len(sys.argv) > 3:
        params = {"name": sys.argv[2], "arguments": json.loads(sys.argv[3])}
    st, j = rpc(method, params)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=1)
    print("HTTP", st, "-> saved", OUT)
    if method == "tools/list":
        for t in (j.get("result", {}).get("tools") or []):
            print("-", t.get("name"), ":", (t.get("description") or "")[:100])
    else:
        print(json.dumps(j, ensure_ascii=False)[:1500])
