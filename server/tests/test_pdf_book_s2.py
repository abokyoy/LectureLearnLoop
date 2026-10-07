# -*- coding: utf-8 -*-
"""大PDF分段 S2 核心逻辑验收测试（2026-10-04）。

只覆盖**无需外部 PaddleOCR** 的本地路径（纯函数 + 文本层段提取 + 页锚点合并 + 覆盖率门槛）。
OCR 段路径（_ocr_convert_segment/_paddle_convert）依赖外网，另在 S6 集成测试中真实验证。

运行（server/ 目录）：python -m pytest tests/test_pdf_book_s2.py -v
"""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import import_service as imps  # noqa: E402


# ---------------------------------------------------------------- 多页文本 PDF 生成（pypdf 合并单页）

def _one_page_pdf(marker: str, rich: bool = True) -> bytes:
    """构造单页英文文字 PDF；rich=True 时内容 ≥300 字符（含 marker 便于逐页断言）。"""
    lines = [marker]
    if rich:
        lines.append(" ".join(f"{marker}word{k}" for k in range(80)))  # 足够长
    content = ["BT /F1 14 Tf 40 760 Td 12 TL"]
    for ln in lines:
        safe = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        # 折行避免超长单行
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
def big_pdf(tmp_path_factory):
    """45 页文本 PDF，每页含唯一 marker=P<页号>。"""
    from pypdf import PdfReader, PdfWriter
    n = 45
    w = PdfWriter()
    for i in range(1, n + 1):
        r = PdfReader(io.BytesIO(_one_page_pdf(f"P{i}")))
        w.add_page(r.pages[0])
    d = tmp_path_factory.mktemp("pdfbook")
    path = d / "book.pdf"
    with open(path, "wb") as f:
        w.write(f)
    return path, n


# ---------------------------------------------------------------- 纯函数

def test_compute_segments_tail_keeps_real_count():
    segs = imps.compute_pdf_segments(45, 20)
    assert segs == [(1, 20), (21, 40), (41, 45)]
    assert imps.compute_pdf_segments(40, 20) == [(1, 20), (21, 40)]
    assert imps.compute_pdf_segments(0, 20) == []


def test_segment_md_name_format():
    name = imps.segment_md_name("书", 21, 40)
    assert name == "书\u00b70021-0040.md"
    # 4 位补零保证字典序=页序
    names = sorted(imps.segment_md_name("b", f, t) for f, t in [(1, 20), (41, 45), (21, 40)])
    assert names[0].endswith("0001-0020.md")


def test_split_anchors_roundtrip():
    md = "# 标题\n\n<!-- llpage:3 -->\n正文三\n\n<!-- llpage:5 -->\n正文五\n"
    d = imps._split_anchors(md)
    assert set(d) == {3, 5}
    assert "正文三" in d[3] and "正文五" in d[5]


# ---------------------------------------------------------------- 页数/文本层判定

def test_page_count_and_text_layer(big_pdf):
    path, n = big_pdf
    assert imps.pdf_page_count(path) == n
    assert imps.pdf_is_text_layer(path) is True


def test_is_text_layer_skewed_distribution(tmp_path):
    """回归 2026-10-07 取样盲区：正文只集中在书中段（首尾仅水印短页），
    旧“前3/中3/后3”9 点采样判 False → 用户实测分段导入不自转。等距 21 点后必须判 True。"""
    from pypdf import PdfReader, PdfWriter
    n = 90
    w = PdfWriter()
    for i in range(n):
        rich = 30 <= i < 60  # 正文集中在中段，与《机器学习实战》分布同形
        blob = _one_page_pdf(f"P{i}", rich=rich)
        w.add_page(PdfReader(io.BytesIO(blob)).pages[0])
    path = tmp_path / "skew.pdf"
    with open(path, "wb") as f:
        w.write(f)
    assert imps.pdf_is_text_layer(path) is True

    # 扫描书+首页版权页（仅 1 富页）：仍必须判 False，防新口径反向误判
    w2 = PdfWriter()
    for i in range(n):
        blob = _one_page_pdf("COPYRIGHT", rich=(i == 0))
        w2.add_page(PdfReader(io.BytesIO(blob)).pages[0])
    path2 = tmp_path / "scan.pdf"
    with open(path2, "wb") as f:
        w2.write(f)
    assert imps.pdf_is_text_layer(path2) is False


# ---------------------------------------------------------------- 文本层段提取（带锚点）

def test_extract_segment_with_anchors(big_pdf):
    path, _ = big_pdf
    md, non_empty = imps.extract_pdf_text_layer(
        path, None, "", page_from=21, page_to=40, with_anchors=True)
    assert md is not None
    assert non_empty == 20
    # 锚点用绝对页码：21..40 全覆盖，不含 20/41
    pages = set(imps._split_anchors(md))
    assert pages == set(range(21, 41))
    assert "P21" in md and "P40" in md


def test_whole_file_path_unchanged_no_anchors(big_pdf):
    path, n = big_pdf
    md, cnt = imps.extract_pdf_text_layer(path)  # 旧调用（整文件，无锚点）
    assert md is not None
    assert "llpage" not in md  # 旧路径产物零 diff：不含锚点


# ---------------------------------------------------------------- 页锚点合并

def test_write_segment_merge_and_override(tmp_path):
    seg = tmp_path / "书\u00b70021-0040.md"
    title = "# 书 (0021-0040页)"
    anchored = "\n\n".join(f"<!-- llpage:{p} -->\nold{p}" for p in range(21, 41))
    cnt, out = imps.write_segment_md(seg, title, anchored, attempted=list(range(21, 41)))
    assert cnt == 20
    assert seg.exists() and seg.stat().st_size > 0
    assert out.startswith(title)
    # 重转只覆盖第 25 页，其余保留
    cnt2, out2 = imps.write_segment_md(seg, title, "<!-- llpage:25 -->\nNEW25", attempted=[25])
    d = imps._split_anchors(out2)
    assert "NEW25" in d[25]
    assert "old21" in d[21] and "old40" in d[40]
    #  attempted 内但本次缺失的页 → 显式覆盖为空节（P2-9 修脏页）
    cnt3, out3 = imps.write_segment_md(seg, title, "", attempted=[30])
    d3 = imps._split_anchors(out3)
    assert d3[30].strip() == ""
    assert "NEW25" in d3[25]  # 未被本次 attempted 影响的页保留


def test_write_segment_atomic_no_tmp_leftover(tmp_path):
    seg = tmp_path / "b\u00b70001-0020.md"
    imps.write_segment_md(seg, "# t", "<!-- llpage:1 -->\nx", attempted=[1])
    tmp = seg.with_suffix(seg.suffix + ".tmp")
    assert not tmp.exists(), "原子写不应残留 .tmp"


# ---------------------------------------------------------------- 段转换（文本层，无网络）

def test_convert_one_segment_text_coverage_gate(big_pdf):
    path, _ = big_pdf
    md, covered, requested, method = imps._convert_one_segment(
        path, path.parent / "附件", 21, 40, "t_fake", "text")
    assert method == "text"
    assert requested == 20
    assert covered == 20
    assert covered / requested >= 0.5  # 达门槛


def test_book_segment_status_reflects_filesystem(tmp_path):
    base = "书"
    # 预生成 3 段空占位（45 页）
    for sf, st in imps.compute_pdf_segments(45, 20):
        (tmp_path / imps.segment_md_name(base, sf, st)).write_text("", encoding="utf-8")
    status = imps.book_segment_status(tmp_path, base, 45, 20)
    assert all(not s["converted"] for s in status)
    # 转完第 2 段后非空 → converted True
    (tmp_path / imps.segment_md_name(base, 21, 40)).write_text("# x\n\n<!-- llpage:21 -->\nhi\n", encoding="utf-8")
    status2 = imps.book_segment_status(tmp_path, base, 45, 20)
    conv = {s["from"]: s["converted"] for s in status2}
    assert conv == {1: False, 21: True, 41: False}
