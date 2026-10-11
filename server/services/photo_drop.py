# -*- coding: utf-8 -*-
"""手机拍照传图服务（知识库错题录入，2026-10-13）。

背景：错题弹窗点「手机拍照」出二维码，手机扫码打开极简上传页，拍照/选相册图
直传到本机独立小服务（0.0.0.0:9900-9999，默认 9991），落盘进该用户 vault 截图/，
PC 端轮询主服务拿新图后走既有 insertMD+OCR 管线。

安全口径（P006 约束的延伸）：
- 主 Flask 保持仅监听 127.0.0.1 不变；本小服务是独立 Flask 实例、独立端口，
  只有「手机页 + 带一次性 token 的传图」两类端点，不暴露任何业务 API。
- token 由 PC 端经 JWT 会话创建（谁登录谁拥有），一次性、30 分钟绝对过期、
  PC 关窗即失效（closed）；只收图片 magic bytes，落盘文件名服务端生成防注入。
- 公网访问依赖用户自备的 DDNS/内网穿透（.env PHOTO_PUBLIC_BASE 配置完整前缀），
  穿透公网端口由服务商决定，故公网地址只做整串配置、不自动拼。
"""
from __future__ import annotations

import base64
import io
import re
import socket
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request

import config
from logger_module import debug_logger as log

SESSION_TTL_S = 30 * 60      # 绝对有效期
SESSION_IDLE_S = 10 * 60     # PC 停止轮询（进程崩/断网）后的闲置回收
MAX_IMAGES_PER_SESSION = 30
MAX_IMG_BYTES = 20 * 1024 * 1024

# 图片 magic → 扩展名（只认这几种，其余拒绝；条目顺序即 (magic, ext)）
_MAGICS = [(b"\xff\xd8\xff", ".jpg"), (b"\x89PNG\r\n\x1a\n", ".png"),
           (b"RIFF", ".webp"), (b"BM", ".bmp")]


def _detect_ext(raw: bytes):
    """按 magic bytes 识别图片扩展名；RIFF 需额外校验 WEBP 签名（防 wav/avi 冒充）。"""
    for magic, ext in _MAGICS:
        if raw.startswith(magic):
            if magic != b"RIFF" or raw[8:12] == b"WEBP":
                return ext
    return None

_sessions: dict = {}
_lock = threading.Lock()
_port_holder = {"port": None}


# ---------------------------------------------------------------- 会话表
def create_session(user_id: str, subject: str = "") -> str:
    token = uuid.uuid4().hex[:16]
    now = time.time()
    with _lock:
        _sweep_locked(now)
        _sessions[token] = {"user": user_id, "subject": subject, "images": [],
                            "created": now, "last_seen": now, "closed": False}
    return token


def touch(token: str, user_id: str, since: int = 0):
    """PC 轮询：校验归属 + 刷新活跃 + 返回 since 之后的新图。None=不可用。"""
    now = time.time()
    with _lock:
        _sweep_locked(now)
        s = _sessions.get(token)
        if not s or s["user"] != user_id or s["closed"] or _expired(s, now):
            return None
        s["last_seen"] = now
        return {"images": list(s["images"][since:]), "total": len(s["images"])}


def close(token: str, user_id: str) -> bool:
    with _lock:
        s = _sessions.get(token)
        if s and s["user"] == user_id:
            s["closed"] = True
            return True
        return False


def accept_upload(token: str, b64: str):
    """手机上传：校验 token 有效 + 图片格式 → 落盘 vault/截图/ → 记入会话。
    登记与上限判定在同一把锁内原子完成；失效/超限时回滚删除已写文件，不留孤儿（CodeReview M-1/m-1）。
    返回 (resp_dict, http_status)。"""
    now = time.time()
    with _lock:
        s = _sessions.get(token)
        alive = bool(s) and not s["closed"] and not _expired(s, now)
        user = s["user"] if alive else None
    if not alive or not user:
        return {"ok": False, "error": "二维码已失效，请在电脑上重新打开「手机拍照」"}, 410
    try:
        if b64 and "," in b64[:64] and b64.startswith("data:"):
            b64 = b64.split(",", 1)[-1]
        raw = base64.b64decode(b64 or "", validate=False)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "图片数据无法解析"}, 400
    ext = _detect_ext(raw)
    if ext is None or not raw:
        return {"ok": False, "error": "仅支持 JPG/PNG/WebP/BMP 图片"}, 400
    if len(raw) > MAX_IMG_BYTES:
        return {"ok": False, "error": "图片超过 20MB，请降低分辨率后重试"}, 400
    name = f"手机_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}{ext}"
    target_dir = Path(config.VAULT_DIR) / str(user) / "截图"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_dir.joinpath(name).write_bytes(raw)
    except Exception as e:  # noqa: BLE001
        log.log_error("photo", "drop_save_failed", str(e))
        return {"ok": False, "error": "服务器保存失败"}, 500
    rel = f"截图/{name}"
    with _lock:
        s = _sessions.get(token)
        if not s or s["closed"]:
            _rollback_orphan(target_dir / name)
            return {"ok": False, "error": "二维码已失效，请在电脑上重新打开「手机拍照」"}, 410
        if len(s["images"]) >= MAX_IMAGES_PER_SESSION:
            _rollback_orphan(target_dir / name)
            return {"ok": False, "error": "本次上传数量已达上限，请在电脑上重新开始"}, 400
        s["images"].append(rel)
    log.log("photo", "drop_upload", "success", {"user": user, "rel": rel, "bytes": len(raw)})
    return {"ok": True, "rel": rel}, 200


def _rollback_orphan(path: Path) -> None:
    """会话在写盘后失效时删除孤儿文件（失败仅记日志，不改变响应）。"""
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        log.log_error("photo", "drop_rollback_failed", str(e))


def _expired(s: dict, now: float) -> bool:
    return now - s["created"] > SESSION_TTL_S or now - s["last_seen"] > SESSION_IDLE_S


def _sweep_locked(now: float) -> None:
    """过期/关闭超久的会话回收（调用方持锁）。"""
    dead = [k for k, v in _sessions.items()
            if v["closed"] or now - v["last_seen"] > SESSION_IDLE_S or now - v["created"] > SESSION_TTL_S]
    for k in dead:
        _sessions.pop(k, None)


# ---------------------------------------------------------------- 局域网 IP 候选
def lan_ip_candidates():
    """枚举本机非回环 IPv4（多网卡/虚拟网卡全列出，由 PC 界面选择生成哪个二维码）。"""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # 不发包，仅查路由表
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    ips = sorted(i for i in ips if not i.startswith(("127.", "0.")))
    # 常见局域网段优先（192.168.x / 10.x），虚拟适配器多为 172.x 或末位 .1
    return sorted(ips, key=lambda x: (not x.startswith(("192.168.", "10.")), x))


# ---------------------------------------------------------------- 手机页（内联，无外部依赖）
_PHONE_HTML = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>拍照录入错题</title>
<style>
 body{font-family:system-ui,-apple-system,sans-serif;background:#faf7f2;margin:0;padding:24px 16px;color:#333}
 .card{max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:24px 20px;box-shadow:0 2px 12px rgba(0,0,0,.06)}
 h1{font-size:18px;margin:0 0 4px}p.sub{color:#888;font-size:13px;margin:0 0 20px}
 .btn{display:block;width:100%;margin:10px 0;padding:16px;font-size:16px;font-weight:600;border:none;border-radius:12px}
 .b1{background:#ff7a45;color:#fff}.b2{background:#fff;color:#ff7a45;border:1.5px solid #ff7a45}
 #log{margin-top:16px;font-size:13px;max-height:38vh;overflow-y:auto}
 .ok{color:#18a058}.err{color:#d03050}
 .tip{margin-top:14px;font-size:12px;color:#aaa;line-height:1.6}
</style></head><body>
<div class="card">
 <h1>📷 拍照录入错题</h1><p class="sub">照片会直接出现在电脑的题目编辑器里，并自动识别文字</p>
 <button class="btn b1" id="cam">拍照（可连续拍）</button>
 <button class="btn b2" id="alb">从相册选择</button>
 <input type="file" id="f1" accept="image/*" capture="environment" hidden>
 <input type="file" id="f2" accept="image/*" multiple hidden>
 <div id="log"></div>
 <div class="tip">传好的照片不用管，回电脑继续编辑即可。二维码失效后请在电脑上重新打开。</div>
</div>
<script>
var TOKEN = location.pathname.split('/').pop();
function line(t, good){var d=document.createElement('div');d.className=good?'ok':'err';d.textContent=t;
 var L=document.getElementById('log');L.insertBefore(d,L.firstChild);}
async function send(file){
  line('正在压缩并上传…', true);
  try{
    var dataUrl = await compress(file);
    var r = await fetch('/c/'+TOKEN+'/upload', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({image_b64: dataUrl})});
    var j = await r.json();
    if (j.ok) line('✓ 已传到电脑：'+j.rel, true); else line('✗ '+j.error, false);
  }catch(e){ line('✗ 上传失败：'+e.message, false); }
}
function compress(file){return new Promise(function(res,rej){
  var img = new Image(); var url = URL.createObjectURL(file);
  img.onload = function(){
    var MAX = 2000, w = img.width, h = img.height;
    var k = Math.min(1, MAX / Math.max(w, h));
    var c = document.createElement('canvas'); c.width = Math.round(w*k); c.height = Math.round(h*k);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    URL.revokeObjectURL(url);
    res(c.toDataURL('image/jpeg', 0.92));
  };
  img.onerror = function(){ URL.revokeObjectURL(url); rej(new Error('图片读取失败')); };
  img.src = url;
});}
function hook(id){var el=document.getElementById(id);
 el.addEventListener('change', function(){ var fs=[].slice.call(el.files||[]);
   var chain = fs.reduce(function(p,f){return p.then(function(){return send(f);});}, Promise.resolve());
   chain.then(function(){}); el.value=''; });
}
hook('f1'); hook('f2');
document.getElementById('cam').onclick=function(){document.getElementById('f1').click();};
document.getElementById('alb').onclick=function(){document.getElementById('f2').click();};
</script></body></html>"""


# ---------------------------------------------------------------- 独立小服务
def build_app() -> Flask:
    app = Flask(__name__)
    # base64 膨胀 ~4/3：上限按解码后 20MB 折算编码体积，否则 len(raw) 校验不可达（CodeReview M-2）
    app.config["MAX_CONTENT_LENGTH"] = MAX_IMG_BYTES * 4 // 3 + 256 * 1024

    @app.route("/ping")
    def ping():
        # 不回 port 字段：公网 DDNS 可达时减少探测面（PC 端经主服务 API 拿端口，不依赖此处）
        return jsonify({"ok": True, "service": "photo-drop"})

    @app.route("/c/<token>")
    def phone_page(token):
        now = time.time()
        with _lock:
            s = _sessions.get(token)
            ok = bool(s) and not s["closed"] and not _expired(s, now)
        if not ok:
            return ("<!doctype html><meta charset='utf-8'><body style='font-family:system-ui;"
                    "text-align:center;padding-top:30vh'><h2>二维码已失效</h2>"
                    "<p>请在电脑上重新打开「手机拍照」</p></body>"), 410
        return _PHONE_HTML

    @app.route("/c/<token>/upload", methods=["POST"])
    def upload(token):
        body = request.get_json(silent=True) or {}
        resp, status = accept_upload(token, body.get("image_b64") or "")
        return jsonify(resp), status

    return app


def start_in_background() -> int | None:
    """主服务启动时调用：daemon 线程跑小 Flask，9991 起在 9900-9999 内自适应选口。
    返回实际端口；全部占用返回 None（功能降级为不可用手机传图，不影响主流程）。"""
    prefer = [config.PHOTO_PORT] + [p for p in range(9900, 10000) if p != config.PHOTO_PORT]
    app = build_app()
    for port in prefer:
        try:
            srv = _make_server("0.0.0.0", port, app)
        except OSError:
            continue
        _port_holder["port"] = port
        threading.Thread(target=srv.serve_forever, daemon=True, name="photo-drop").start()
        log.log("photo", "drop_server_started", "success", {"port": port})
        return port
    log.log("photo", "drop_server_no_port", "error", {"range": "9900-9999"})
    return None


def current_port():
    return _port_holder["port"]


def _make_server(host: str, port: int, app: Flask):
    # werkzeug 直接使用，避免 flask.run 的 banner/信号干扰（daemon 线程内跑）
    from werkzeug.serving import make_server
    return make_server(host, port, app, threaded=True)
