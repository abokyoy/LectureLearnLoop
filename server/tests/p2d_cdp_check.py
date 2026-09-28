"""P2d 冒烟：Electron 已启动并带 --remote-debugging-port=9222 时，用 CDP 断言主窗口加载服务端页面。

- HTTP /json/list：必须存在 url 以 SERVER_BASE 开头的 page target；
- 最小 WS 实现执行 Runtime.evaluate：断言 window.pybridge 兼容层挂载 + SPA 壳/登录页标记其一。
"""
from __future__ import annotations

import base64
import json
import socket
import struct
import sys
import urllib.request

CDP = "127.0.0.1:9222"
SERVER_BASE = "http://127.0.0.1:6001"


def ws_connect(ws_url: str) -> socket.socket:
    # ws://127.0.0.1:9222/devtools/page/<id>
    rest = ws_url.split("//", 1)[1]
    hostport, path = rest.split("/", 1)
    host, port = hostport.split(":")
    s = socket.create_connection((host, int(port)), timeout=10)
    key = base64.b64encode(b"LL-p2d-smoke1234").decode()
    req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    # 读到握手响应结束
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    return s


def ws_send(s: socket.socket, payload: bytes):
    header = bytearray([0x81])  # FIN + text
    n = len(payload)
    mask = b"\x01\x02\x03\x04"
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    s.sendall(bytes(header) + mask + masked)


def ws_recv(s: socket.socket) -> bytes:
    def rn(k: int) -> bytes:
        data = b""
        while len(data) < k:
            chunk = s.recv(k - len(data))
            if not chunk:
                raise ConnectionError("ws closed")
            data += chunk
        return data
    b1, b2 = rn(2)
    ln = b2 & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", rn(2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", rn(8))[0]
    return rn(ln)


def evaluate(expr: str):
    targets = json.loads(urllib.request.urlopen(f"http://{CDP}/json/list", timeout=10).read())
    pages = [t for t in targets if t.get("type") == "page"]
    page = next((p for p in pages if p.get("url", "").startswith(SERVER_BASE)), pages[0] if pages else None)
    if page is None:
        return None, None
    s = ws_connect(page["webSocketDebuggerUrl"])
    cmd = {"id": 1, "method": "Runtime.evaluate",
           "params": {"expression": expr, "returnByValue": True, "awaitPromise": True}}
    ws_send(s, json.dumps(cmd).encode())
    result = None
    for _ in range(50):  # 跳过事件帧，直到 id=1 响应
        msg = ws_recv(s)
        try:
            obj = json.loads(msg)
        except Exception:
            continue
        if obj.get("id") == 1:
            result = obj
            break
    s.close()
    val = None
    if result and "result" in result:
        val = result["result"].get("result", {}).get("value")
    return page.get("url"), val


def main():
    targets_raw = urllib.request.urlopen(f"http://{CDP}/json/list", timeout=10).read()
    targets = json.loads(targets_raw)
    pages = [t for t in targets if t.get("type") == "page"]
    print("page targets:", [(p.get("url"), p.get("title")) for p in pages])
    ok_url = any(p.get("url", "").startswith(SERVER_BASE) for p in pages)
    print(("PASS" if ok_url else "FAIL"), "electron loaded server page")
    if not ok_url:
        sys.exit(1)

    checks = [
        ("pybridge mounted", "!!window.pybridge && typeof window.pybridge.getConfig === 'function'"),
        ("shell or login", "!!document.getElementById('content-area') || !!document.getElementById('auth-form')"),
    ]
    failed = 0
    for name, expr in checks:
        url, val = evaluate(expr)
        cond = bool(val) if not isinstance(val, str) else bool(val)
        print(("PASS" if cond else "FAIL"), f"{name} -> {val!r} (url={url})")
        if not cond:
            failed += 1
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
