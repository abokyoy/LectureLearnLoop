# -*- coding: utf-8 -*-
"""文件导入功能验收测试（2026-09-30 导入功能，Flask test client，双后端通用）。

运行方式（server/ 目录）：python -m pytest tests/test_import_feature.py -v
覆盖：
- MD/TXT 直落（含 gb18030 解码、重名序号、MF-5 正文入库可见）；
- 非法类型/路径穿越/空文件拒绝；
- 任务查询用户隔离（横向越权）；
- PDF 端到端：真实调 PaddleOCR-VL Job API（外网依赖，不可用时 skip）→
  MD 落盘 + 原件进附件/ + 轮询状态 done + notes 入库。
- DOCX 端到端（第七轮追加）：带正文/表格/内嵌图的最小 docx → MD+附件图入库；
- 图片导入：即时嵌图建新笔记；
- URL 导入（打桩 requests，不出网）：data-src 回填、图片本地化、反爬页/短文/
  断网/文件直链报错文案、SSRF 与协议拒绝。
临时注册用户（隔离 vault，不碰真实用户数据）。
"""
import io
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

UA = "imp_a_" + uuid.uuid4().hex[:6]
UB = "imp_b_" + uuid.uuid4().hex[:6]


@pytest.fixture(scope="module")
def client():
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _register(client, username):
    r = client.post("/api/auth/register", json={"username": username, "password": "pass1234"})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["token"]


def _h(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture(scope="module")
def tokens(client):
    return _register(client, UA), _register(client, UB)


# ---------------------------------------------------------------- 工具：最小文字 PDF 生成

def _make_min_pdf(lines):
    """构造单页英文文字 PDF（不引新依赖；偏移动态计算，保证结构合法）。"""
    content_lines = ["BT /F1 14 Tf 60 720 Td 16 TL"]
    for ln in lines:
        safe = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content_lines.append(f"({safe}) Tj T*")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1")
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
    xref_pos = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n").encode()
    return out


def _make_pdf_with_image(lines):
    """单页文字+一张内嵌图（FlateDecode RGB 200x150）的 PDF；图 top_y=550。"""
    import zlib
    img_raw = zlib.compress(b"\xff\x00\x00" * (200 * 150))
    content_lines = ["BT /F1 14 Tf 60 720 Td 16 TL"]
    for ln in lines:
        safe = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content_lines.append(f"({safe}) Tj T*")
    content_lines.append("ET")
    content_lines.append("q 200 0 0 150 60 400 cm /Im1 Do Q")
    stream = "\n".join(content_lines).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /XObject /Subtype /Image /Width 200 /Height 150 /ColorSpace /DeviceRGB "
        b"/BitsPerComponent 8 /Filter /FlateDecode /Length " + str(len(img_raw)).encode()
        + b" >>\nstream\n" + img_raw + b"\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n").encode()
    return out


def _upload(client, token, filename, data: bytes, folder_path):
    return client.post(
        "/api/vault/import",
        data={"file": (io.BytesIO(data), filename), "folder_path": folder_path},
        content_type="multipart/form-data",
        headers=_h(token),
    )


def _status(client, token, task_id):
    r = client.get(f"/api/vault/import/{task_id}", headers=_h(token))
    return r.get_json()["data"]


def _user_vault_dir(token) -> Path:
    """JWT uid 声明→本 run 临时用户的 vault 目录（不 glob 跨 run 残留，断言确定性）。"""
    import base64
    import json as _json
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    uid = _json.loads(base64.b64decode(payload))["uid"]
    return Path(__file__).resolve().parents[1] / "data" / "vault" / str(uid)


def _wait_done(client, token, task_id, timeout=240, interval=3):
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = _status(client, token, task_id)
        if last.get("status") in ("done", "failed"):
            return last
        time.sleep(interval)
    return last


# ---------------------------------------------------------------- 一、文本直落

class TestTextImport:
    def test_md_import_done_immediately(self, client, tokens):
        ta, _ = tokens
        r = _upload(client, ta, "导入测试笔记.md", "# 标题\n\n讲义正文内容 ABC".encode("utf-8"), "vault")
        d = r.get_json()["data"]
        assert d["success"], d
        st = _status(client, ta, d["task_id"])
        assert st["status"] == "done"
        assert st["file_name"].endswith(".md")
        # MF-5：写盘必须同步正文入库，笔记面板（/api/notes/content）可见
        r = client.get("/api/notes/content?path=vault/" + st["file_name"], headers=_h(ta))
        nd = r.get_json()["data"]
        assert nd["exists"] and "讲义正文内容" in nd["content"]

    def test_txt_gb18030_decoded(self, client, tokens):
        ta, _ = tokens
        data = "旧记事本GBK文本 中文测试".encode("gb18030")
        r = _upload(client, ta, "gbk笔记.txt", data, "vault")
        d = r.get_json()["data"]
        assert d["success"], d
        st = _status(client, ta, d["task_id"])
        assert st["status"] == "done"

    def test_duplicate_name_gets_suffix(self, client, tokens):
        ta, _ = tokens
        name = "重名测试.md"
        d1 = _upload(client, ta, name, b"# one", "vault").get_json()["data"]
        d2 = _upload(client, ta, name, b"# two", "vault").get_json()["data"]
        assert d1["success"] and d2["success"]
        assert d2["file_name"] != d1["file_name"]
        assert "_1" in d2["file_name"]

    def test_rejects_bad_extension_and_empty(self, client, tokens):
        ta, _ = tokens
        d = _upload(client, ta, "evil.exe", b"MZ...", "vault").get_json()["data"]
        assert not d["success"] and "不支持" in d["error"]
        d = _upload(client, ta, "空.md", b"", "vault").get_json()["data"]
        assert not d["success"] and "空" in d["error"]

    def test_path_traversal_rejected(self, client, tokens):
        ta, _ = tokens
        d = _upload(client, ta, "x.md", b"# hi", "../..").get_json()["data"]
        assert not d["success"]

    def test_import_into_subfolder_then_parent_of_file(self, client, tokens):
        """落点规则：先建子目录导入验证（文件→所在文件夹由前端冻结逻辑负责，此处验证后端接受任意合法子路径）。"""
        ta, _ = tokens
        r = client.post("/api/vault/folder", json={"parent_path": "vault", "name": "imp_sub"}, headers=_h(ta))
        assert r.get_json()["success"]
        from app import create_app  # noqa: F401  仅为提示：下面用相对子路径
        d = _upload(client, ta, "子目录笔记.md", b"# sub", "imp_sub").get_json()["data"]
        assert d["success"], d


# ---------------------------------------------------------------- 二、越权隔离

class TestIsolation:
    def test_other_user_cannot_see_task(self, client, tokens):
        ta, tb = tokens
        d = _upload(client, ta, "私密.md", b"# secret", "vault").get_json()["data"]
        st = _status(client, tb, d["task_id"])
        assert st["success"] is False or st.get("status") is None


# ---------------------------------------------------------------- 三、PDF 端到端（外网依赖）

class TestPdfEndToEnd:
    def test_pdf_converts_to_md(self, client, tokens):
        ta, _ = tokens
        import config
        if not config.PADDLE_OCR_TOKEN:
            pytest.skip("未配置 PADDLE_OCR_TOKEN")
        pdf = _make_min_pdf([
            "Lecture Notes: Resource Management Chapter 3",
            "Scarcity means unlimited wants meet limited resources.",
            "Opportunity cost is the next best alternative forgone.",
        ])
        r = _upload(client, ta, "讲义第三章.pdf", pdf, "vault")
        d = r.get_json()["data"]
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=240)
        if st.get("status") == "failed" and "PaddleOCR" in (st.get("error") or ""):
            pytest.skip(f"PaddleOCR API 不可用: {st['error']}")
        assert st["status"] == "done", st
        # 产物结构：<目标>/<名>.md + 原件在 <目标>/附件/
        md_name = st["file_name"]
        vault_root = Path(__file__).resolve().parents[1] / "data" / "vault"
        # 找到该用户目录下的产物（临时用户唯一前缀 imp_a_*）
        hits = list(vault_root.glob(f"*/{md_name}"))
        assert hits, f"未找到转换产物 {md_name}"
        md_text = hits[0].read_text(encoding="utf-8")
        assert "Scarcity" in md_text or "scarcity" in md_text.lower(), md_text[:200]
        pdfs = list(hits[0].parent.glob("附件/*.pdf"))
        assert pdfs, "原件 PDF 未落入附件目录"
        # MF-5：转换产物也要入正文库
        rr = client.get("/api/notes/content?path=" + md_name, headers=_h(ta))
        nd = rr.get_json()["data"]
        assert nd["exists"] and "Scarcity" in (nd["content"] or "")


# ---------------------------------------------------------------- 四、网络抖动容错（2026-10-01 用户误报修复）

class TestTransientRetry:
    def test_poll_transient_failures_do_not_kill_task(self, client, tokens, monkeypatch):
        """状态查询连续报 Transient 后恢复 → 任务仍能 done（旧逻辑一次异常即判死）。"""
        import json as _json
        import services.paddle_doc_client as paddle
        from services import import_service as imp
        ta, _ = tokens
        calls = {"q": 0}

        def fake_submit(path):
            return "fake-job-1"

        def fake_query(job_id):
            calls["q"] += 1
            if calls["q"] <= 2:
                raise paddle.PaddleDocTransientError("模拟 SSL 握手失败（V2RAYN 抖动）")
            if calls["q"] == 3:
                return {"state": "running", "extractProgress": {"extractedPages": 1, "totalPages": 2}}
            return {"state": "done", "resultUrl": {"jsonUrl": "https://example.invalid/r.jsonl"}}

        def fake_download(url):
            return _json.dumps({"result": {"layoutParsingResults": [
                {"markdown": {"text": "网络抖动后恢复的笔记。", "images": {}}}]}})

        monkeypatch.setattr(paddle, "submit_job", fake_submit)
        monkeypatch.setattr(paddle, "query_job", fake_query)
        monkeypatch.setattr(paddle, "download_jsonl", fake_download)
        monkeypatch.setattr(imp, "POLL_INTERVAL_S", 0.2)

        d = _upload(client, ta, "抖动恢复.pdf", b"%PDF-1.4 fake", "vault").get_json()["data"]
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=1)
        assert st["status"] == "done", st
        assert calls["q"] >= 3, "未发生重试即完成，断言无效"

    def test_persistent_outage_fails_and_removes_placeholder(self, client, tokens, monkeypatch):
        """持续断网超阈值 → failed（错误含网络提示）；预占空 .md 被自动清理，不留空笔记。"""
        import services.paddle_doc_client as paddle
        from services import import_service as imp
        ta, _ = tokens

        def fake_submit(path):
            return "fake-job-2"

        def fake_query(job_id):
            raise paddle.PaddleDocTransientError("持续断网模拟")

        monkeypatch.setattr(paddle, "submit_job", fake_submit)
        monkeypatch.setattr(paddle, "query_job", fake_query)
        monkeypatch.setattr(imp, "POLL_INTERVAL_S", 0.1)
        monkeypatch.setattr(imp, "POLL_TRANSIENT_MAX_FAILS", 3)

        d = _upload(client, ta, "断网.pdf", b"%PDF-1.4 fake", "vault").get_json()["data"]
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=1)
        assert st["status"] == "failed", st
        assert "网络" in (st.get("error") or ""), st
        vault_root = Path(__file__).resolve().parents[1] / "data" / "vault"
        leftovers = [p for p in vault_root.glob("*/断网*.md") if p.stat().st_size == 0]
        assert not leftovers, f"空占位 .md 未清理: {leftovers}"


# ---------------------------------------------------------------- 五、文本层优先（2026-10-01 网页打印 PDF 丢字修复）

class TestTextLayerPriority:
    def test_text_layer_pdf_skips_remote_ocr(self, client, tokens, monkeypatch):
        """内嵌文本层充足的 PDF → 本地直转，绝不调用远端 OCR（视觉模型对超长单页会严重丢字）。"""
        import services.paddle_doc_client as paddle
        ta, _ = tokens

        def boom(path):
            raise AssertionError("有文本层的 PDF 不应调用远端 OCR")

        monkeypatch.setattr(paddle, "submit_job", boom)
        lines = [f"Isolation level line {i}: readers must never see uncommitted dirty data." for i in range(10)]
        d = _upload(client, ta, "文本层讲义.pdf", _make_min_pdf(lines), "vault").get_json()["data"]
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=1)
        assert st["status"] == "done", st
        # 隔离修复：只看当前测试用户目录（历史运行残留 vault 子目录会让全库 glob 撞名误判）
        hits = list(_user_vault_dir(ta).glob("文本层讲义.md"))
        assert hits, "文本层产物未落盘"
        text = hits[0].read_text(encoding="utf-8")
        assert "Isolation level line 3" in text and len(text) > 300, text[:200]

    def test_text_layer_pdf_extracts_inline_images(self, client, tokens, monkeypatch):
        """文本层路径同步提取内嵌图：存附件/、正文按位置插入引用，非堆文末。"""
        import services.paddle_doc_client as paddle
        ta, _ = tokens

        def boom(path):
            raise AssertionError("文本层路径不应调用远端 OCR")

        monkeypatch.setattr(paddle, "submit_job", boom)
        lines = [f"Row {i}: committed data rows require row locks and next key gaps must stay stable forever." for i in range(20)]
        d = _upload(client, ta, "带图讲义.pdf", _make_pdf_with_image(lines), "vault").get_json()["data"]
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=1)
        assert st["status"] == "done", st
        md_path = next(iter(_user_vault_dir(ta).glob("带图讲义*.md")), None)
        assert md_path, "产物未落盘"
        text = md_path.read_text(encoding="utf-8")
        assert "![图片](附件/" in text, text[:300]
        # 按本任务 id 前缀过滤（同用户附件目录可能有其他用例产物）
        pngs = list((md_path.parent / "附件").glob(f"img_{d['task_id']}_*.png"))
        assert len(pngs) == 1, pngs
        from PIL import Image
        im = Image.open(pngs[0])
        assert im.size == (200, 150), im.size
        # 图 top_y=550 在页面中部：引用段不应堆在文末（20 行正文，图约应在第 11 行前）
        paras = [p for p in text.split("\n\n") if p.strip()]
        img_idx = next(i for i, p in enumerate(paras) if p.startswith("!["))
        assert img_idx <= len(paras) - 2, f"图片被堆到文末: idx={img_idx}/{len(paras)}"

    def test_scanned_pdf_falls_back_to_ocr(self, client, tokens, monkeypatch):
        """文本层不足（模拟扫描件）→ 回落 PaddleOCR 视觉路径。"""
        import json as _json
        import services.paddle_doc_client as paddle
        from services import import_service as imp
        ta, _ = tokens
        called = {"submit": 0}

        def fake_submit(path):
            called["submit"] += 1
            return "fake-job-3"

        def fake_query(job_id):
            return {"state": "done", "resultUrl": {"jsonUrl": "https://example.invalid/r.jsonl"}}

        def fake_download(url):
            return _json.dumps({"result": {"layoutParsingResults": [
                {"markdown": {"text": "扫描版识别结果。", "images": {}}}]}})

        monkeypatch.setattr(paddle, "submit_job", fake_submit)
        monkeypatch.setattr(paddle, "query_job", fake_query)
        monkeypatch.setattr(paddle, "download_jsonl", fake_download)
        monkeypatch.setattr(imp, "POLL_INTERVAL_S", 0.2)

        d = _upload(client, ta, "扫描版.pdf", _make_min_pdf(["Short note."]), "vault").get_json()["data"]
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=1)
        assert st["status"] == "done", st
        assert called["submit"] == 1, "未回落远端 OCR"


# ---------------------------------------------------------------- 六、文本层后处理（2026-10-01 二轮：断行/变体字/网页残渣）

class TestTextLayerPostprocess:
    """postprocess_pdf_text_layer 纯函数断言：部首归一 + 断行重排 + 装饰/尾部推荐位过滤。"""

    def test_wrapped_lines_join_and_english_heading_standalone(self):
        from services.import_service import postprocess_pdf_text_layer
        raw = ("数据库事务的隔离级别有4种，由低到高分别为Read\n"
               "uncommitted 、Read committed 。\n"
               "Read uncommitted\n"
               "读未提交，就是一个事务可以读取另一个未提交事务的数据。")
        out = postprocess_pdf_text_layer(raw)
        assert "由低到高分别为Read uncommitted 、Read committed 。" in out, out
        paras = [p for p in out.split("\n\n") if p]
        assert "Read uncommitted" in paras, "纯英文标题行应独立成段"
        assert "读未提交，就是一个事务可以读取另一个未提交事务的数据。" in paras

    def test_radical_variant_chars_normalized(self):
        from services.import_service import postprocess_pdf_text_layer
        out = postprocess_pdf_text_layer("老板发现不对，⻢上回滚了⾼优先级数据，⻚面⻓度也变了。")
        for bad in ("⻢", "⾼", "⻚", "⻓"):
            assert bad not in out, f"残留部首变体字 {bad}"
        assert "马上回滚" in out and "高优先级" in out and "页面" in out and "长度" in out

    def test_wechat_chrome_and_tail_zone_dropped(self):
        from services.import_service import postprocess_pdf_text_layer
        raw = ("喜欢此内容的人还喜欢\n收录于合集\n"
               "脏读就是读到了别的事务回滚前的脏数据。\n"
               "出处：https://www.cnblogs.com/dingpeng905\n5/p/11190203.html\n"
               "版权声明：本文来源于网友收集\n【腾讯云】多款云产品1折起，买云服务器\n"
               "送免费机器，最长免费续 3个月\n上一篇·一道经典面试题\n"
               "推荐20个开源的前端低代码项目\n几何心凉的核心圈")
        out = postprocess_pdf_text_layer(raw)
        assert "收录于合集" not in out and "腾讯云" not in out and "低代码" not in out, out
        assert "脏读就是读到了别的事务回滚前的脏数据。" in out, "正文被误杀"
        # URL 跨行拼接不插空格，且后接正文不被推荐位区误杀（推荐位在句后才被丢弃）
        assert "https://www.cnblogs.com/dingpeng9055/p/11190203.html" in out, out


# ---------------------------------------------------------------- 七、DOCX 导入（第七轮追加需求）

def _make_png_bytes(w=200, h=150, color=(255, 0, 0)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _make_min_docx(png: bytes):
    """手工拼最小合法 docx（zip+OOXML）：标题段+正文段+v:imagedata 内嵌图+2x2 表格。"""
    import zipfile
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Default Extension="png" ContentType="image/png"/>'
          '<Override PartName="/word/document.xml"'
          ' ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1"'
            ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"'
            ' Target="word/document.xml"/></Relationships>')
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
           'xmlns:v="urn:schemas-microsoft-com:vml" '
           'xmlns:o="urn:schemas-microsoft-com:office:office" '
           'xmlns:w10="urn:schemas-microsoft-com:office:word"><w:body>'
           '<w:p><w:r><w:t>DOCX 导入测试</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>正文第一段：事务隔离级别与锁机制要点复习。</w:t></w:r></w:p>'
           '<w:p><w:r><w:pict><v:shape type="#_x0000_t75" style="width:200pt;height:150pt">'
           '<v:imagedata r:id="rId2" o:title="图解"/></v:shape></w:pict></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>级别</w:t></w:r></w:p></w:tc>'
           '<w:tc><w:p><w:r><w:t>防止的问题</w:t></w:r></w:p></w:tc></w:tr>'
           '<w:tr><w:tc><w:p><w:r><w:t>读已提交</w:t></w:r></w:p></w:tc>'
           '<w:tc><w:p><w:r><w:t>脏读</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
           '</w:body></w:document>')
    docrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId2"'
               ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"'
               ' Target="media/image1.png"/></Relationships>')
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", docrels)
        z.writestr("word/media/image1.png", png)
    return bio.getvalue()


class TestDocxImport:
    def test_docx_converts_to_md_with_image_and_table(self, client, tokens):
        """DOCX 端到端：正文/MD 表格/内嵌图全保留，原件入附件，产物入库可见；纯本地不耗额度。"""
        ta, _ = tokens
        d = _upload(client, ta, "复习讲义.docx", _make_min_docx(_make_png_bytes()), "vault").get_json()["data"]
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=60, interval=1)
        assert st["status"] == "done", st
        udir = _user_vault_dir(ta)
        md_path = udir / "复习讲义.md"
        assert md_path.exists(), "DOCX 转换产物未落盘"
        text = md_path.read_text(encoding="utf-8")
        assert "事务隔离级别与锁机制要点复习" in text, text[:300]
        assert "读已提交" in text and "|" in text, f"表格未保留为 MD 表格: {text[:300]}"
        assert "附件/img_" in text, f"正文未引用本地化图片: {text[:300]}"
        # 按本任务 id 前缀过滤（同用户附件目录可能存其他用例产物）
        pngs = list((udir / "附件").glob(f"img_{d['task_id']}_*.png"))
        assert len(pngs) == 1, pngs
        from PIL import Image
        assert Image.open(pngs[0]).size == (200, 150)
        assert (udir / "附件" / "复习讲义.docx").exists(), "原件未入附件"
        rr = client.get("/api/notes/content?path=vault/复习讲义.md", headers=_h(ta))
        nd = rr.get_json()["data"]
        assert nd["exists"] and "事务隔离级别" in (nd["content"] or "")


# ---------------------------------------------------------------- 八、图片导入（仅嵌图，用户确认不做 OCR）

class TestImageImport:
    def test_image_embeds_into_new_note_immediately(self, client, tokens):
        ta, _ = tokens
        png = _make_png_bytes(80, 60)
        d = _upload(client, ta, "随手截图.png", png, "vault").get_json()["data"]
        assert d["success"], d
        st = _status(client, ta, d["task_id"])
        assert st["status"] == "done", st
        assert st["file_name"] == "随手截图.md"
        udir = _user_vault_dir(ta)
        md_path = udir / "随手截图.md"
        assert md_path.exists(), "嵌图笔记未落盘"
        text = md_path.read_text(encoding="utf-8")
        assert text == "![图片](附件/随手截图.png)", text
        stored = udir / "附件" / "随手截图.png"
        assert stored.read_bytes() == png, "原图未存入附件"

    def test_image_name_with_spaces_percent_encoded(self, client, tokens):
        """评审 R2 回归：文件名含空格（清洗白名单保留）→ link destination 百分号编码，文件按原名落盘。"""
        ta, _ = tokens
        png = _make_png_bytes(60, 40)
        d = _upload(client, ta, "my shot.png", png, "vault").get_json()["data"]
        assert d["success"], d
        st = _status(client, ta, d["task_id"])
        assert st["status"] == "done", st
        udir = _user_vault_dir(ta)
        text = (udir / "my shot.md").read_text(encoding="utf-8")
        assert text == "![图片](附件/my%20shot.png)", text
        assert (udir / "附件" / "my shot.png").read_bytes() == png, "原图未按含空格原名落盘"


# ---------------------------------------------------------------- 九、URL 导入（打桩 requests，全程不出网）

_WX_ARTICLE_HTML = """<!DOCTYPE html><html><head>
<meta property="og:title" content="数据库事务隔离级别详解"/>
<title>某个公众号名称</title></head><body>
<div class="rich_media">
<h1 class="rich_media_title" id="activity-name">数据库事务隔离级别详解</h1>
<div id="js_content">
<p>事务隔离级别由低到高分为读未提交、读已提交、可重复读和串行化四种，每一级都用不同的代价换来不同强度的一致性保证，需要结合业务场景仔细权衡。</p>
<p>读未提交允许一个事务读到另一个事务尚未提交的数据，于是产生脏读；读已提交避免了脏读，但同一事务内两次相同查询可能因其他事务提交而出现不可重复读。</p>
<p><img class="rich_pages" data-src="https://mmbiz.qpic.cn/mmbiz_png/abcdef/640?wx_fmt=png"/></p>
<p>可重复读级别下，InnoDB 通过 MVCC 快照读与 next-key lock 当前读相结合的方案，同时压制不可重复读与幻读两类问题，这也是 MySQL 的默认隔离级别。</p>
<p>串行化把所有读都变成当前读，一致性最强但并发度最低，通常只在报表或对账等批处理场景才会启用。</p>
</div></div></body></html>"""


class _FakeResp:
    def __init__(self, text="", content=None, ctype="text/html; charset=utf-8",
                 encoding="utf-8", apparent="utf-8", status_code=200, location=None, url=""):
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = {"Content-Type": ctype}
        self.encoding = encoding
        self.apparent_encoding = apparent
        self.status_code = status_code
        self.url = url
        if location is not None:
            self.headers["Location"] = location

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as _rq
            raise _rq.HTTPError(f"{self.status_code} fake")
        return None


def _url_post(client, token, url, folder="vault"):
    r = client.post("/api/vault/import-url", json={"url": url, "folder_path": folder}, headers=_h(token))
    return r.get_json()["data"]


class TestUrlExtractPure:
    """纯函数：data-src 回填 / 标题优先级 / SSRF 护栏。"""

    def test_datasrc_backfill_and_title(self):
        from services import import_service as imp
        md, title = imp.html_to_markdown_note(_WX_ARTICLE_HTML)
        assert title == "数据库事务隔离级别详解"
        assert "https://mmbiz.qpic.cn/mmbiz_png/abcdef/640?wx_fmt=png" in md, md[:400]
        assert "脏读" in md

    def test_title_fallback_activity_name(self):
        from services import import_service as imp
        html = _WX_ARTICLE_HTML.replace(
            '<meta property="og:title" content="数据库事务隔离级别详解"/>\n'
            '<title>某个公众号名称</title>', "")
        _md, title = imp.html_to_markdown_note(html)
        assert title == "数据库事务隔离级别详解", title

    def test_is_safe_http_url(self, monkeypatch):
        from services import import_service as imp
        # 评审 Major 修复后域名分支走 DNS 复检；桩定确定性解析，不依赖真实网络
        dns = {
            'mp.weixin.qq.com': '101.91.10.21',
            'example.com': '93.184.216.34',
            'localhost': '127.0.0.1',
        }

        def fake_dns(host, port, *a, **kw):
            if host not in dns:
                raise OSError('no such host')
            return [(2, 1, 6, '', (dns[host], port or 80))]
        monkeypatch.setattr(imp.socket, 'getaddrinfo', fake_dns)
        assert imp.is_safe_http_url("https://mp.weixin.qq.com/s/x", allow_http=True)
        assert imp.is_safe_http_url("http://example.com/x", allow_http=True)
        assert not imp.is_safe_http_url("http://example.com/x")  # PDF 切图上下文仅 https
        for bad in ("http://127.0.0.1/x", "http://192.168.1.10/x", "https://localhost/x",
                    "http://[::1]/x", "file:///etc/passwd", "https://10.0.0.5/x"):
            assert not imp.is_safe_http_url(bad, allow_http=True), bad

    def test_redirect_to_internal_blocked(self, monkeypatch):
        """评审 R1 回归：公开 URL 302 跳内网 → 拒绝且第二跳绝不出网。"""
        from services import import_service as imp
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            return _FakeResp(status_code=302, location="http://127.0.0.1:6021/api/health",
                             url="https://public.example/x")

        monkeypatch.setattr(imp.requests, "get", fake_get)
        with pytest.raises(ValueError) as ei:
            imp._fetch_html("https://public.example/x")
        assert "重定向" in str(ei.value) and "内网" in str(ei.value), str(ei.value)
        assert calls == ["https://public.example/x"], calls

    def test_public_redirect_still_followed(self, monkeypatch):
        """评审 R1 不破坏正常链路：公开→公开重定向照常跟随取到正文。"""
        from services import import_service as imp
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            if "shorlly" in url:
                return _FakeResp(status_code=302, location="https://final.example/article",
                                 url="https://shorlly.example/a")
            return _FakeResp(text=_WX_ARTICLE_HTML, url=url)

        monkeypatch.setattr(imp.requests, "get", fake_get)
        # 2026-10-02 评审 Major 修复后域名分支会 getaddrinfo 复检；*.example 假域名不可解析，
        # 桩成公网 IP 模拟“域名解析到公网”的真实场景，断言护栏不拦公网链路。
        monkeypatch.setattr(imp.socket, "getaddrinfo",
                            lambda host, port, *a, **kw: [(2, 1, 6, '', ('93.184.216.34', port or 443))])
        html = imp._fetch_html("https://shorlly.example/a")
        assert "js_content" in html
        assert calls == ["https://shorlly.example/a", "https://final.example/article"], calls

    def test_nip_io_wildcard_resolving_to_internal_blocked(self, monkeypatch):
        """评审 Major 回归：域名外表合法但 DNS 解析到内网（nip.io 类泛解析）必须拒绝。"""
        from services import import_service as imp
        monkeypatch.setattr(imp.socket, "getaddrinfo",
                            lambda host, port, *a, **kw: [(2, 1, 6, '', ('127.0.0.1', port or 80))])
        assert not imp.is_safe_http_url("http://127.0.0.1.nip.io/x", allow_http=True)
        # 解析失败同样拒绝（不得拿“解析不了”当“安不安全”放行理由）
        def _fail(host, port, *a, **kw):
            raise OSError("name or service not known")
        monkeypatch.setattr(imp.socket, "getaddrinfo", _fail)
        assert not imp.is_safe_http_url("https://unresolvable.invalid/x")


class TestUrlImportE2E:
    def test_wechat_article_end_to_end(self, client, tokens, monkeypatch):
        """公众号文章全流程：抓取→提取→图本地化（去 /640 取原图）→标题命名→入库。"""
        import requests as _rq
        from services import import_service as imp
        ta, _ = tokens
        png_bytes = _make_png_bytes(120, 90)
        requested = []

        def fake_get(url, **kw):
            requested.append(url)
            if url.startswith("https://mp.weixin.qq.com/s/"):
                return _FakeResp(text=_WX_ARTICLE_HTML)
            if "mmbiz.qpic.cn" in url:
                return _FakeResp(content=png_bytes, ctype="image/png")
            raise _rq.ConnectionError("unexpected url " + url)

        monkeypatch.setattr(imp.requests, "get", fake_get)
        d = _url_post(client, ta, "https://mp.weixin.qq.com/s/testArticle")
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=0.5)
        assert st["status"] == "done", st
        assert st["result_name"] == "数据库事务隔离级别详解.md"
        udir = _user_vault_dir(ta)
        md_path = udir / "数据库事务隔离级别详解.md"
        assert md_path.exists(), "URL 产物未落盘"
        text = md_path.read_text(encoding="utf-8")
        assert "脏读" in text and "数据库事务隔离级别详解" in text, text[:300]
        assert "mmbiz.qpic.cn" not in text, f"远程图未本地化: {text[:400]}"
        import re as _re
        assert _re.search(r"!\[[^\]]*\]\(附件/img_\w+\.png\)", text), text[:400]
        # 图床去尺寸后缀：优先请求原图（无 /640），命中即不回落
        assert "https://mmbiz.qpic.cn/mmbiz_png/abcdef?wx_fmt=png" in requested, requested
        assert not any("/640" in u for u in requested), requested
        pngs = list((udir / "附件").glob(f"img_{d['task_id']}_*.png"))
        assert len(pngs) == 1 and pngs[0].read_bytes() == png_bytes, pngs
        rr = client.get("/api/notes/content?path=vault/数据库事务隔离级别详解.md", headers=_h(ta))
        nd = rr.get_json()["data"]
        assert nd["exists"] and "脏读" in (nd["content"] or "")

    def test_latin1_misdeclared_utf8_bytes_no_garbled(self, client, tokens, monkeypatch):
        """在线端到端实测 bug 回归：无 charset 声明→requests 默认 iso-8859-1，字节实为 UTF-8 不得乱码。"""
        from services import import_service as imp
        ta, _ = tokens
        body_utf8 = _WX_ARTICLE_HTML.encode("utf-8")
        png_bytes = _make_png_bytes(50, 50)

        def fake_get(url, **kw):
            if url.startswith("https://mp.weixin.qq.com/s/"):
                return _FakeResp(content=body_utf8, ctype="text/html",
                                 encoding="iso-8859-1", apparent="ISO-8859-1")
            if "mmbiz.qpic.cn" in url:
                return _FakeResp(content=png_bytes, ctype="image/png")
            raise ConnectionError("unexpected " + url)

        monkeypatch.setattr(imp.requests, "get", fake_get)
        d = _url_post(client, ta, "https://mp.weixin.qq.com/s/encTest")
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=0.5)
        assert st["status"] == "done", st
        md_path = _user_vault_dir(ta) / st["result_name"]
        text = md_path.read_text(encoding="utf-8")
        assert "事务隔离级别" in text, text[:200]
        for mojibake in ("ä¸", "åŠ¡", "æ•°"):
            assert mojibake not in text, f"乱码残留 {mojibake}"

    def test_antibot_page_clear_guidance(self, client, tokens, monkeypatch):
        """微信反爬页 → failed，错误文案含验证说明与本地导入指引。"""
        from services import import_service as imp
        ta, _ = tokens
        block_html = ("<html><body><div>环境异常" "当前环境异常，完成验证后即可继续访问。"
                      "</div></body></html>")

        def fake_get(url, **kw):
            return _FakeResp(text=block_html)

        monkeypatch.setattr(imp.requests, "get", fake_get)
        d = _url_post(client, ta, "https://mp.weixin.qq.com/s/blocked")
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=0.5)
        assert st["status"] == "failed", st
        assert "验证" in st["error"] and "本地导入" in st["error"], st["error"]

    def test_too_short_body_fails_with_guidance(self, client, tokens, monkeypatch):
        """正文提取不足 50 字（纯视频页/登录墙）→ failed 并引导本地导入。"""
        from services import import_service as imp
        ta, _ = tokens

        def fake_get(url, **kw):
            return _FakeResp(text="<html><body><p>很短</p></body></html>")

        monkeypatch.setattr(imp.requests, "get", fake_get)
        d = _url_post(client, ta, "https://example.com/short")
        assert d["success"], d
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=0.5)
        assert st["status"] == "failed", st
        assert "未能提取到正文" in st["error"] and "本地导入" in st["error"], st["error"]

    def test_unreachable_and_file_direct_link_errors(self, client, tokens, monkeypatch):
        """连接异常→网页无法访问；非 html Content-Type→提示文件直链走本地导入。"""
        import requests as _rq
        from services import import_service as imp
        ta, _ = tokens

        mode = {"v": "conn"}

        def fake_get(url, **kw):
            if mode["v"] == "conn":
                raise _rq.ConnectionError("模拟断网")
            return _FakeResp(content=b"%PDF-1.4 fake", ctype="application/pdf")

        monkeypatch.setattr(imp.requests, "get", fake_get)
        d = _url_post(client, ta, "https://example.com/a")
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=0.5)
        assert st["status"] == "failed" and "网页无法访问" in st["error"], st
        mode["v"] = "pdf"
        d = _url_post(client, ta, "https://example.com/b")
        st = _wait_done(client, ta, d["task_id"], timeout=30, interval=0.5)
        assert st["status"] == "failed" and "不是网页" in st["error"], st

    def test_ssrf_and_bad_scheme_rejected_at_endpoint(self, client, tokens):
        """端点层拦截：内网地址与非法协议不建任务、不出网。"""
        ta, _ = tokens
        d = _url_post(client, ta, "http://127.0.0.1:6021/api/health")
        assert not d["success"] and "内网" in d["error"], d
        d = _url_post(client, ta, "ftp://mp.weixin.qq.com/s/x")
        assert not d["success"] and "http" in d["error"], d
        d = _url_post(client, ta, "")
        assert not d["success"], d

