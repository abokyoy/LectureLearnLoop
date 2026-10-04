# 通用 CDP 截图（连 Electron :9222，自设超时，绕开 browser-use 15s 限制）
# 用法: python ui_cdp_shot.py <url> <out_file.jpeg|png> [wait_sec]
import asyncio, base64, json, sys, time
import requests, websockets

CDP = "http://127.0.0.1:9222"

async def shoot(url: str, out: str, wait_sec: float = 8.0) -> int:
    r = requests.put(CDP + "/json/new", params={"url": url}, timeout=10)
    if r.status_code != 200 or not r.text.strip():
        # 部分 Electron 版本不支持 /json/new 带 url，降级：POST 试一次
        r2 = requests.post(CDP + "/json/new", params={"url": url}, timeout=10)
        if r2.status_code == 200 and r2.text.strip().startswith("{"):
            r = r2
        else:
            print("json/new failed:", r.status_code, r.text[:200], "|", r2.status_code, r2.text[:200])
            return 2
    tgt = r.json()
    ws_url = tgt["webSocketDebuggerUrl"]
    mid = 0
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        async def send(method, params=None):
            nonlocal mid
            mid += 1
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
                if msg.get("id") == mid:
                    if "error" in msg:
                        print("CDP error:", msg["error"])
                    return msg.get("result", {})
        await send("Page.enable")
        await send("Emulation.setDeviceMetricsOverride",
                   {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        # 同源的登录态注入：先到登录页写 localStorage，再跳目标页
        tok = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
        import urllib.parse as up
        origin = up.parse.urlparse(url)
        await send("Page.navigate", {"url": f"{origin.scheme}://{origin.netloc}/login"})
        await asyncio.sleep(1.5)
        await send("Runtime.evaluate", {"expression": f"localStorage.setItem('ll_token', '{tok}')"})
        await send("Page.navigate", {"url": url})
        await asyncio.sleep(wait_sec)
        fmt = "jpeg" if out.lower().endswith((".jpg", ".jpeg")) else "png"
        shot = await send("Page.captureScreenshot", {"format": fmt, "quality": 70} if fmt == "jpeg" else {"format": fmt})
        data = shot.get("data")
        if not data:
            print("no screenshot data"); return 1
        with open(out, "wb") as f:
            f.write(base64.b64decode(data))
        await send("Browser.close") if False else None
    try:
        requests.get(CDP + "/json/close/" + tgt["id"], timeout=5)
    except Exception:
        pass
    print("saved:", out)
    return 0

if __name__ == "__main__":
    url, out = sys.argv[1], sys.argv[2]
    wait = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0
    sys.exit(asyncio.run(shoot(url, out, wait)))
