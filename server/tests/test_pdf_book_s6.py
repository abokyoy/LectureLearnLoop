# -*- coding: utf-8 -*-
"""大PDF分段 S6 黑盒补充验收（2026-10-04，方案 §7 缺口项，无外部 PaddleOCR）。

补齐 S1/S2/S3 未覆盖的 §7 缺口：
- §7.1 三态分流门槛（≤20 页 / 21-60 页且 ≤10MB 豁免单MD / >60 页建书；重名 → 书_2）；
- §7.5 扫描件 OCR 锚点注入（_jsonl_to_markdown mock，page_from 绝对页码）；
- §7.6 假绿防线（覆盖率 < 50% → 段任务 failed，达标 → done）；
- §7.7 API 越权（get_book_task 用户隔离）/ 非法路径 / non-pdf 拒签 / 过期签名 401；
- §7.9 recover 存活后 book 接口仍返完整段网格。

运行（server/ 目录）：python -m pytest tests/test_pdf_book_s6.py -v
"""
import io
import json
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------- PDF 构造工具

def _text_one_page_pdf(marker: str) -> bytes:
    """单页含 ≥300 字符文本，使 pdf_is_text_layer 采样判为文本层。"""
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


def _build_pdf(n_pages: int, text: bool) -> bytes:
    """合成 n 页 PDF。text=True 每页含文本层；False 全空白页（扫描版采样判据）。"""
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for i in range(1, n_pages + 1):
        if text:
            r = PdfReader(io.BytesIO(_text_one_page_pdf(f"T{i}")))
            w.add_page(r.pages[0])
        else:
            w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def app():
    from app import create_app
    a = create_app()
    a.config["TESTING"] = True
    return a


@pytest.fixture(scope="module")
def client(app):
    with app.test_client() as c:
        yield c


def _register(client):
    u = "s6_" + uuid.uuid4().hex[:6]
    r = client.post("/api/auth/register", json={"username": u, "password": "pass1234"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["token"]


def _h(tok):
    return {"Authorization": "Bearer " + tok}


def _import(client, tok, pdf_bytes, fname, folder="vault"):
    up = client.post("/api/vault/import", data={"file": (io.BytesIO(pdf_bytes), fname), "folder_path": folder},
                     headers=_h(tok), content_type="multipart/form-data")
    return up.get_json()["data"]


# ================================================================ §7.1 三态分流门槛

def test_routing_le20_pages_single_md(client):
    """≤20 页 → 不建书，走单 MD 现状流程（无 is_book）。"""
    tok = _register(client)
    d = _import(client, tok, _build_pdf(18, text=True), "小册.pdf")
    assert d["success"] is True, d
    assert not d.get("is_book"), d
    assert d.get("task_id"), d


def test_routing_exempt_21_60_under10mb_single_md(client):
    """21-60 页且 ≤10MB 小文件豁免 → 仍单 MD（确认1=B 豁免分支）。"""
    tok = _register(client)
    d = _import(client, tok, _build_pdf(45, text=True), "中册.pdf")
    assert d["success"] is True, d
    assert not d.get("is_book"), d


def test_routing_over60_builds_book(client):
    """>60 页（扫描空白版）→ 建书籍文件夹，段数 ceil(65/20)=4；扫描版即时 done、不投递整书 worker。"""
    tok = _register(client)
    d = _import(client, tok, _build_pdf(65, text=False), "大书.pdf")
    assert d["success"] is True, d
    assert d.get("is_book") is True, d
    assert d.get("is_text_layer") is False, d
    assert d.get("segments") == 4, d


def test_routing_boundary_60_exempt_61_book(client):
    """边界：60 页 ≤10MB 豁免（单MD），61 页建书。"""
    tok = _register(client)
    d60 = _import(client, tok, _build_pdf(60, text=False), "六十大限.pdf")
    assert not d60.get("is_book"), d60
    d61 = _import(client, tok, _build_pdf(61, text=False), "六十有一.pdf")
    assert d61.get("is_book") is True, d61


def test_routing_dup_name_book_suffix(client):
    """同名书籍重复导入 → 第二次 base 追加 _1（uniquify_name 首个冲突后缀）。"""
    tok = _register(client)
    first = _import(client, tok, _build_pdf(70, text=False), "同名书.pdf")
    assert first.get("is_book") is True and first["file_name"] == "同名书.pdf", first
    second = _import(client, tok, _build_pdf(70, text=False), "同名书.pdf")
    assert second.get("is_book") is True, second
    assert second["file_name"] == "同名书_1.pdf", second


# ================================================================ §7.5 OCR 锚点注入（mock）

def test_jsonl_to_markdown_anchors_absolute_page(tmp_path):
    """with_anchors=True：每页块前注绝对页码锚点 = page_from + 局部页序；默认无锚点（零 diff）。"""
    from services import import_service as imps
    att = tmp_path / "附件"
    pages = ["# 甲页内容", "# 乙页内容", "# 丙页内容"]
    jsonl = "\n".join('{"result":{"layoutParsingResults":[{"markdown":{"text": %s, "images": {}}}]}}'
                      % json.dumps(p, ensure_ascii=False) for p in pages)
    # 段起始物理页 41 → 锚点 41/42/43
    md_abs = imps._jsonl_to_markdown(jsonl, att, "t_mock", page_from=41, with_anchors=True)
    assert "<!-- llpage:41 -->" in md_abs
    assert "<!-- llpage:42 -->" in md_abs and "<!-- llpage:43 -->" in md_abs
    assert "<!-- llpage:40 -->" not in md_abs and "<!-- llpage:44 -->" not in md_abs
    # 默认（整文件路径）零 diff：不含锚点
    md_plain = imps._jsonl_to_markdown(jsonl, att, "t_mock")
    assert "llpage" not in md_plain


# ================================================================ §7.6 假绿防线（覆盖率门槛）

def _make_seg_task(app, uid):
    from services import import_service as imps
    return imps.create_task(uid, "seg", "v", "convert_segment", parent_task_id="P", seg_from=1, seg_to=20)


def test_low_coverage_segment_marks_failed(app, tmp_path, monkeypatch):
    """覆盖率 3/20 < 50% → 段任务置 failed（防“假绿 done”）。"""
    from services import import_service as imps
    uid = "s6_cov_" + uuid.uuid4().hex[:6]
    tid = _make_seg_task(app, uid)
    monkeypatch.setattr(imps, "_convert_one_segment",
                        lambda *a, **k: ("md", 3, 20, "text"))
    imps._segment_convert_worker(tid, uid, "P", tmp_path / "b.pdf", tmp_path, "b", 1, 20, "text")
    st = imps.get_task(tid, uid)["status"]
    with app.config["DB_CONN_FACTORY"]() as conn:
        conn.execute("DELETE FROM import_tasks WHERE user_id = ?", (uid,))
    assert st == "failed", st


def test_ok_coverage_segment_marks_done(app, tmp_path, monkeypatch):
    """覆盖率 20/20 达标 → 正常写盘并置 done。"""
    from services import import_service as imps
    uid = "s6_okcov_" + uuid.uuid4().hex[:6]
    tid = _make_seg_task(app, uid)
    anchored = "\n\n".join(f"<!-- llpage:{p} -->\nx{p}" for p in range(1, 21))
    monkeypatch.setattr(imps, "_convert_one_segment",
                        lambda *a, **k: (anchored, 20, 20, "text"))
    monkeypatch.setattr(imps, "sync_note_content", lambda *a, **k: True)
    imps._segment_convert_worker(tid, uid, "P", tmp_path / "b.pdf", tmp_path, "b", 1, 20, "text")
    st = imps.get_task(tid, uid)["status"]
    seg_file = tmp_path / imps.segment_md_name("b", 1, 20)
    with app.config["DB_CONN_FACTORY"]() as conn:
        conn.execute("DELETE FROM import_tasks WHERE user_id = ?", (uid,))
    assert st == "done", st
    assert seg_file.exists() and seg_file.stat().st_size > 0


# ================================================================ §7.7 API 越权 / 非法路径 / non-pdf

def test_get_book_task_user_isolation(app):
    """get_book_task 强制 (task_id, user_id) 双条件：他人 task_id 查不到。"""
    from services import import_service as imps
    uid_a = "s6_isoA_" + uuid.uuid4().hex[:6]
    uid_b = "s6_isoB_" + uuid.uuid4().hex[:6]
    tid = imps.create_task(uid_a, "book.pdf", "vault/book", "pdf_book", result_pdf="x")
    assert imps.get_book_task(tid, uid_a) is not None
    assert imps.get_book_task(tid, uid_b) is None, "跨用户不得命中"
    with app.config["DB_CONN_FACTORY"]() as conn:
        conn.execute("DELETE FROM import_tasks WHERE user_id IN (?,?)", (uid_a, uid_b))


def test_status_book_cross_user_returns_notfound(client):
    """B 用户带 A 的 main_task_id 调 book 接口 → 书籍任务不存在（用户隔离）。"""
    tok_a = _register(client)
    d = _import(client, tok_a, _build_pdf(70, text=False), "隔离书.pdf")
    main = d["task_id"]
    tok_b = _register(client)
    r = client.get("/api/import/pdf/book", query_string={"main_task_id": main}, headers=_h(tok_b)).get_json()
    assert r["data"]["success"] is False, r


def test_pdf_sign_rejects_nonpdf_and_traversal(client):
    """签发放行仅 vault 内 .pdf：非 pdf / 越权路径均拒绝。"""
    tok = _register(client)
    r_md = client.get("/api/vault/pdf/sign", query_string={"path": "笔记.md"}, headers=_h(tok)).get_json()
    assert r_md["data"]["success"] is False, r_md
    r_tr = client.get("/api/vault/pdf/sign", query_string={"path": "../../etc/passwd.pdf"}, headers=_h(tok)).get_json()
    assert r_tr["data"]["success"] is False, r_tr


def test_pdf_stream_rejects_expired(app, client):
    """过期签名 → 401（在签名校验前先判 exp < now）。"""
    from routes_bridge import _pdf_sign
    u = "s6_exp_" + uuid.uuid4().hex[:6]
    path = "vault/大书/大书.pdf"
    with app.test_request_context():
        exp = int(time.time()) - 5
        t = _pdf_sign(u, path, exp)
    resp = client.get("/api/vault/pdf", query_string={"u": u, "path": path, "exp": exp, "t": t})
    assert resp.status_code == 401, resp.status_code


# ================================================================ §7.9 recover 存活后网格完整

def test_recover_survives_then_book_grid_complete(app, client):
    """扫描书籍导入后执行启动 recover：主任务行存活，book 接口仍返完整段网格（4 段 pending）。"""
    from services import import_service as imps
    tok = _register(client)
    d = _import(client, tok, _build_pdf(65, text=False), "recover书.pdf")
    main = d["task_id"]
    assert d.get("is_book") is True and d.get("segments") == 4, d
    # 启动清理（>30 天判定；本次新建行 created_at 为当前时间，本不应被删，验证 pdf_book 双重保护仍存活）
    imps.recover_tasks_on_startup(app.config["DB_CONN_FACTORY"])
    r = client.get("/api/import/pdf/book", query_string={"main_task_id": main}, headers=_h(tok)).get_json()
    meta = r["data"]
    assert meta["success"] is True, meta
    assert meta["status"] == "done", meta  # 扫描版建后即 done
    assert len(meta["segments"]) == 4, meta["segments"]
    assert all(s["state"] == "pending" and not s["converted"] for s in meta["segments"]), meta["segments"]
