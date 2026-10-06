# -*- coding: utf-8 -*-
"""大PDF分段 S3 接口验收测试（2026-10-04，Flask test client，sqlite 后端，无网络）。

覆盖：
- 80 页文本 PDF 导入 → 走书籍分支（is_book, segments=4, is_text_layer=True）；
- 整书串行 worker 后台真实本地转换 → book 接口逐段 converted=True；
- 段 MD 落盘含页锚点；
- /api/vault/pdf/sign 签发 + /api/vault/pdf 流式：200 / Range 206 / 篡改 403 / 缺参 400；
- 已转段再 convert（非 force）→ need_confirm=False 且无待转。

运行（server/ 目录）：python -m pytest tests/test_pdf_book_s3.py -v
"""
import io
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _one_page_pdf(marker: str) -> bytes:
    filler = " ".join(f"{marker}word{k}" for k in range(80))
    lines = [marker, filler]
    content = ["BT /F1 14 Tf 40 760 Td 12 TL"]
    for ln in lines:
        safe = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        for j in range(0, len(safe), 80):
            content.append(f"({safe[j:j+80]}) Tj T*")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return out


@pytest.fixture(scope="module")
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _register(client):
    u = "s3_" + uuid.uuid4().hex[:6]
    r = client.post("/api/auth/register", json={"username": u, "password": "pass1234"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["token"]


def _h(tok):
    return {"Authorization": "Bearer " + tok}


@pytest.fixture(scope="module")
def book(client):
    """导入 80 页文本 PDF，等待整书 worker 本地转换完成，返回 (client, token, main_id, book_meta)。"""
    tok = _register(client)
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for i in range(1, 81):
        r = PdfReader(io.BytesIO(_one_page_pdf(f"PG{i}")))
        w.add_page(r.pages[0])
    buf = io.BytesIO()
    w.write(buf)
    buf.seek(0)
    up = client.post("/api/vault/import", data={"file": (buf, "大书.pdf"), "folder_path": "vault"},
                     headers=_h(tok), content_type="multipart/form-data")
    j = up.get_json()["data"]
    assert j["success"] is True, j
    assert j.get("is_book") is True, j
    assert j["segments"] == 4, j           # ceil(80/20)
    assert j["is_text_layer"] is True, j
    main = j["task_id"]
    # 轮询 book 接口直到 done（worker 在后台线程串行本地转换）
    meta = None
    for _ in range(60):
        time.sleep(0.5)
        b = client.get("/api/import/pdf/book", query_string={"main_task_id": main}, headers=_h(tok)).get_json()
        meta = b.get("data") or {}
        if meta.get("status") == "done":
            break
    assert meta and meta.get("status") == "done", meta
    assert all(s["state"] == "converted" for s in meta["segments"]), meta["segments"]
    return client, tok, main, meta


def test_book_end_to_end(book):
    client, tok, main, meta = book
    # 段数与页覆盖
    segs = meta["segments"]
    assert len(segs) == 4
    assert segs[0]["from"] == 1 and segs[0]["to"] == 20
    assert segs[-1]["from"] == 61 and segs[-1]["to"] == 80
    assert all(s["converted"] for s in segs)
    # pdf_path 用于签名/流式
    assert meta["pdf_path"].endswith(".pdf")


def test_segment_md_has_anchors_on_disk(book):
    client, tok, main, meta = book
    # 通过 HTTP /api/vault/file 读取段文件，验证含页锚点（不依赖内部实现）
    pdf_rel = meta["pdf_path"].replace("\\", "/")     # 如 大书/大书.pdf
    dirpart, _, fname = pdf_rel.rpartition("/")
    base = Path(fname).stem
    seg_rel = f"{dirpart}/{base}\u00b70001-0020.md" if dirpart else f"{base}\u00b70001-0020.md"
    r = client.get("/api/vault/file", query_string={"path": seg_rel}, headers=_h(tok)).get_json()
    content = (r.get("data") or {}).get("content", "")
    assert "<!-- llpage:1 -->" in content and "<!-- llpage:20 -->" in content, seg_rel
    assert "PG1" in content


def test_sign_and_stream_pdf(book):
    client, tok, main, meta = book
    sign = client.get("/api/vault/pdf/sign", query_string={"path": meta["pdf_path"]}, headers=_h(tok)).get_json()["data"]
    assert sign["t"] and sign["exp"]
    args = {"u": sign["u"], "path": sign["path"], "exp": sign["exp"], "t": sign["t"]}
    resp = client.get("/api/vault/pdf", query_string=args)
    assert resp.status_code == 200, resp.data[:100]
    assert resp.mimetype == "application/pdf"
    # Range 请求 → 206 部分内容
    r2 = client.get("/api/vault/pdf", query_string=args, headers={"Range": "bytes=0-1"})
    assert r2.status_code == 206
    assert r2.headers.get("Content-Range", "").startswith("bytes 0-1/")


def test_stream_rejects_tamper_and_missing(book):
    client, tok, main, meta = book
    sign = client.get("/api/vault/pdf/sign", query_string={"path": meta["pdf_path"]}, headers=_h(tok)).get_json()["data"]
    # 篡改签名 → 403
    bad = dict(u=sign["u"], path=sign["path"], exp=sign["exp"], t="deadbeef")
    assert client.get("/api/vault/pdf", query_string=bad).status_code == 403
    # 缺参 → 400
    assert client.get("/api/vault/pdf", query_string={"u": sign["u"]}).status_code == 400


def test_converted_seg_convert_skips_without_force(book):
    client, tok, main, meta = book
    # 已全部转完，请求转第 1 段（非 force）→ 无待转
    est = client.post("/api/import/pdf/segments/estimate",
                      json={"main_task_id": main, "segs": [1]}, headers=_h(tok)).get_json()["data"]
    assert est["segs"] == 0, est
    cv = client.post("/api/import/pdf/segments/convert",
                     json={"main_task_id": main, "segs": [1], "confirm": True}, headers=_h(tok)).get_json()
    assert cv["data"]["success"] is False
