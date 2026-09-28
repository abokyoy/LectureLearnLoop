"""
P6 证据层2/3：Electron 真机 CDP 验证（9222）。

流程：
 1) 主窗口 → llShell.openOverlay() 打开悬浮窗（断言 /overlay target 出现）
 2) 悬浮窗：DOM.setFileInputFiles 注入真实 YouTube 音频 p6_audio.wav → 触发 change
    → 点击"开始学习" → 轮询 #subs 中文实时字幕增长（zh-CN 流式链路）→ 停止
 3) 主窗口：Page.navigate 到 YouTube 视频页 → 断言标题/URL → 截图存档 p6_electron_youtube.png
运行：服务端 6001 + Electron(9222, start:debug) 已启动。
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
import websockets

sys.stdout.reconfigure(encoding="utf-8", errors="replace") if hasattr(sys.stdout, "reconfigure") else None

CDP = "http://127.0.0.1:9222"
BASE = "http://127.0.0.1:6001"
FIX = Path(__file__).parent / "fixtures"
WAV = FIX / "p6_audio.wav"
YT_URL = "https://www.youtube.com/watch?v=aJydWxn2zRk"

fails = []


def step(cond, name, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {detail[:160]}")
    if not cond:
        fails.append(name)


class Tab:
    """单 target 的 CDP ws 客户端（id 递增，串行使用）。"""

    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self._id = 0

    async def __aenter__(self):
        self.ws = await websockets.connect(self.ws_url, max_size=64 * 1024 * 1024)
        return self

    async def __aexit__(self, *a):
        await self.ws.close()

    async def send(self, method, **params):
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def evaluate(self, expr, await_promise=False, return_value=True):
        r = await self.send(
            "Runtime.evaluate",
            expression=expr,
            awaitPromise=await_promise,
            returnByValue=return_value,
        )
        if r.get("exceptionDetails"):
            raise RuntimeError("JS: " + json.dumps(r["exceptionDetails"])[:300])
        return r.get("result", {}).get("value")


async def list_pages():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{CDP}/json/list")
        return [t for t in r.json() if t.get("type") == "page"]


async def wait_page(url_frag, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for t in await list_pages():
            if url_frag in t.get("url", ""):
                return t
        await asyncio.sleep(0.5)
    return None


def ensure_token() -> str:
    """独立注册一个新 token（主窗口 localStorage 注入用，保证悬浮窗可用）。"""
    u = "p6cdp_" + uuid.uuid4().hex[:6]
    r = httpx.post(BASE + "/api/auth/register", json={"username": u, "password": "test123456"}, timeout=20)
    r.raise_for_status()
    return r.json()["data"]["token"]


async def main() -> int:
    pages = await list_pages()
    main_page = next((t for t in pages if "127.0.0.1:6001" in t.get("url", "")), None)
    if not main_page:
        step(False, "主窗口 target 存在", str(pages))
        return 1
    step(True, "主窗口 target 存在", main_page["url"])

    async with Tab(main_page["webSocketDebuggerUrl"]) as mt:
        # 注入有效 token（隔离验证，不依赖历史登录态）
        tok = ensure_token()
        await mt.evaluate(f"localStorage.setItem('ll_token', {json.dumps(tok)}); 'ok'")

        # 1) 打开悬浮窗
        ok = await mt.evaluate("typeof window.llShell !== 'undefined' && typeof window.llShell.openOverlay === 'function'")
        step(bool(ok), "preload llShell.openOverlay 可用")
        await mt.evaluate("window.llShell.openOverlay()")
        ov = await wait_page("/overlay", timeout=25)
        step(ov is not None, "悬浮窗 /overlay target 出现", ov["url"] if ov else "timeout")
        if not ov:
            return 1

        # 2) 悬浮窗注入音频文件 → 开始 → 字幕增长
        async with Tab(ov["webSocketDebuggerUrl"]) as ot:
            await ot.send("Runtime.enable")
            # 确认桥与语言控件
            has_asr = await ot.evaluate("!!(window.llAsr && window.llAsr.start && window.llAsr.sendChunk)")
            step(has_asr, "overlay llAsr 桥可用")
            lang = await ot.evaluate("document.getElementById('lang').value")
            step(lang == "zh-CN", "overlay 语言默认 zh-CN", f"lang={lang}")

            # 文件注入：objectId → DOM.setFileInputFiles → 手动派发 change
            r = await ot.send("Runtime.evaluate", expression="document.getElementById('file')")
            obj_id = r["result"]["objectId"]
            await ot.send("DOM.setFileInputFiles", files=[str(WAV)], objectId=obj_id)
            await ot.evaluate("document.getElementById('file').dispatchEvent(new Event('change'))")
            # pickFile 解码需要时间
            prep = None
            deadline = time.time() + 30
            while time.time() < deadline:
                prep = await ot.evaluate(
                    "(window.__p6peek = document.getElementById('status') ? document.getElementById('status').textContent : '')")
                n = await ot.evaluate("document.querySelectorAll('#file').length")
                if n:
                    break
                await asyncio.sleep(1)
            await asyncio.sleep(3)  # 等 decodeAudioData/parseWavPcm 完成

            await ot.evaluate("document.getElementById('btnStart').click()")
            best_len, zh_len, samples = 0, 0, []
            deadline = time.time() + 150
            got_final = False
            while time.time() < deadline:
                await asyncio.sleep(4)
                subs = await ot.evaluate("document.getElementById('subs').textContent || ''")
                live = await ot.evaluate("document.getElementById('live').textContent || ''")
                zh = len(re.findall(r"[\u4e00-\u9fa5]", subs))
                best_len, zh_len = max(best_len, len(subs)), max(zh_len, zh)
                samples.append(f"{len(subs)}/{live[:10]}")
                if zh > 60 and "final" not in live.lower():
                    # 中文最终字幕足够
                    await ot.evaluate("window.__p6final = true")
                    got_final = True
                    break
            step(got_final, "真实音频中文实时字幕增长", f"subs_len={best_len} zh_chars={zh_len} samples={samples[-4:]}")
            await ot.evaluate("document.getElementById('btnStop').click()")

        # 3) 主窗口导航 YouTube（应用内可达性，证据层3）
        await mt.send("Page.enable")
        await mt.send("Page.navigate", url=YT_URL)
        title, url2 = "", ""
        deadline = time.time() + 60
        while time.time() < deadline:
            await asyncio.sleep(3)
            title = await mt.evaluate("document.title || ''")
            url2 = await mt.evaluate("location.href || ''")
            if title and "youtube" in url2.lower():
                break
        step("watch" in url2 and bool(title) and "Just a moment" not in title,
             "应用内 YouTube 视频页可达", f"title={title[:60]}")
        shot = await mt.send("Page.captureScreenshot", format="png")
        (FIX / "p6_electron_youtube.png").write_bytes(base64.b64decode(shot["data"]))
        step((FIX / "p6_electron_youtube.png").stat().st_size > 10000, "YouTube 截图存档",
             str(FIX / "p6_electron_youtube.png"))
        # 还原主窗口到应用首页
        await mt.send("Page.navigate", url=BASE + "/")

    print("\n==== P6 CDP(Electron): " + ("ALL PASS" if not fails else f"FAIL({len(fails)}): " + " | ".join(fails)) + " ====")
    return 0 if not fails else 2


if __name__ == "__main__":
    asyncio.run(main())
