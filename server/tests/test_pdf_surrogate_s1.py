# -*- coding: utf-8 -*-
"""PDF 文本层孤立代理字符清洗回归测试（2026-11-02）。

用户实测：《测试.pdf》含数学字体（ToUnicode CMap 把码位映射为 UTF-16 代理位），
pypdf 提取出未配对代理字符（\ud835 等），worker 写 .md/入库 utf-8 编码即抛
"can't encode character '\\ud835': surrogates not allowed" → 转换任务 failed。

断言：
- 成对代理（高+低相邻）必须重组为真实增补字符（数学斜体 B 不丢）；
- 孤立代理替换为 \ufffd，产物保证可 utf-8 编码；
- 正常文本零 diff；
- extract_pdf_text_layer 端到端（真实畸形 CMap PDF）产物可直接 write_text。

运行（server/ 目录）：python -m pytest tests/test_pdf_surrogate_s1.py -v
"""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import import_service as imps  # noqa: E402


def _clean(s):
    return imps._clean_surrogates(s)


# ---------------------------------------------------------------- 纯函数

def test_clean_pair_recombined_to_astral():
    """成对代理（\ud835\udc35）→ 真实字符 U+1D435（数学斜体 B），不得丢字。"""
    assert _clean("x\ud835\udc35y") == "x\U0001D435y"


def test_clean_lone_surrogate_replaced():
    """孤立高/低代理 → \ufffd，产物必须可 utf-8 严格编码。"""
    out = _clean("a\ud835b\udc00c")
    assert "\ud835" not in out and "\udc00" not in out
    out.encode("utf-8")  # 不抛即通过
    assert out.count("\ufffd") == 2


def test_clean_normal_text_zero_diff():
    for s in ["", "abc DEF 中文 ·——《》", "\U0001D435 already astral"]:
        assert _clean(s) == s


# ---------------------------------------------------------------- 跨空格代理对重组（2026-11-02 二段）
# 真实《测试.pdf》CambriaMath CMap 把代理对拆成两个独立码位，pypdf 提取时
# TJ kerning 在高低半之间插入空格（探针实锤：0xd835 0x20 0xdc43），需跨空格配对。
# 不跨换行：跨 \n 的相邻高代理多为结构性丢低位（探针：d835 0xa d835），且合并会破坏行对齐。

def test_clean_pair_recombined_across_space():
    assert _clean("a\ud835 \udc43b") == "a\U0001D443b"


def test_clean_pair_recombined_across_multi_space():
    # 多个空格/制表符（≤3）同样重组
    assert _clean("x\ud835   \udc35y") == "x\U0001D435y"
    assert _clean("x\ud835\t\udc35y") == "x\U0001D435y"


def test_clean_no_merge_across_newline():
    # 换行不跨：各成 \ufffd，行数不变（保行对齐）
    out = _clean("a\ud835\n\udc35b")
    assert out == "a\ufffd\n\ufffdb"


def test_clean_gap_join_keeps_other_spacing():
    # 普通文本里的空格不受影响，只有代理位两侧的空格被吞并
    assert _clean("\ud835 \udc43 和 \ud835\udc35") == "\U0001D443 和 \U0001D435"


# ---------------------------------------------------------------- 端到端（真实畸形 ToUnicode CMap PDF）

def _malformed_cmap_pdf(repeat: int = 300) -> bytes:
    """构造 Type0 字体 PDF：码位 1→𝐵(代理位对)、2→孤立高代理 D835、3→'T'，正文重复 repeat 次。

    复刻用户《测试.pdf》失败场景：pypdf 按 UTF-16BE 解码 CMap 值，成对产出两个孤立
    代理码点、以及一个天然孤立代理。repeat≥300 时提取量超 PDF_TEXT_MIN_CHARS，
    整文件路径才会命中文本层（否则回落 None，测试空跑）。
    """
    def hexstr(u16: str) -> str:
        return "".join(f"{ord(c):04X}" for c in u16)
    # 码位 1 -> "\ud835\udc35"(U+1D435 的代理位对)，2 -> 孤立\ud835，3 -> 'T'
    cmap = (
        "/CIDInit /ProcSet findresource begin\n"
        "12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        f"3 beginbfchar\n<01> <{hexstr(chr(0xD835) + chr(0xDC35))}>\n"
        f"<02> <{hexstr(chr(0xD835))}>\n"
        f"<03> <{hexstr('T')}>\n"
        "endbfchar\nendcmap\nCMapName currentdict /CMap defineresource pop\n"
        "end\nend\n"
    )
    body = b"BT /F1 14 Tf 40 760 Td 12 TL\n"
    for _ in range(repeat):
        body += b"(\x01\x03\x03\x03\x02) Tj T*\n"
    text = body + b"ET\n"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /MathSym /Encoding /Identity-H "
        b"/DescendantFonts [6 0 R] /ToUnicode 7 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /MathSym "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        b"/FontDescriptor 8 0 R /CIDToGIDMap /Identity >>",
        b"<< /Length " + str(len(cmap.encode("latin-1"))).encode() + b" >>\nstream\n"
        + cmap.encode("latin-1") + b"\nendstream",
        b"<< /Type /FontDescriptor /FontName /MathSym /Flags 4 /FontBBox [-500 -300 1200 1000] "
        b"/ItalicAngle 0 /Ascent 900 /Descent -300 /CapHeight 700 /StemV 80 >>",
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


def test_extract_layer_no_surrogates_end_to_end(tmp_path):
    """真实畸形 CMap PDF 整文件路径：命中文本层、无孤立代理、成对代理还原、可直接写盘。"""
    raw = _malformed_cmap_pdf()
    path = tmp_path / "测试.pdf"
    path.write_bytes(raw)
    # 前置事实确认：pypdf 原生提取必须产出代理位且无法 utf-8 编码（否则本测试失去意义）
    from pypdf import PdfReader
    t0 = PdfReader(io.BytesIO(raw)).pages[0].extract_text() or ""
    assert any(0xD800 <= ord(c) <= 0xDFFF for c in t0), "构造失效：pypdf 未产出代理位"
    try:
        t0.encode("utf-8")
        raise AssertionError("构造失效：原生提取结果竟可 utf-8 编码，无法复现用户报错")
    except UnicodeEncodeError:
        pass
    md, cnt = imps.extract_pdf_text_layer(path)
    assert md is not None, "整文件路径未命中文本层，测试空跑"
    assert not any(0xD800 <= ord(c) <= 0xDFFF for c in md), "产物仍含孤立代理"
    assert "\U0001D435" in md, "成对代理未还原为真实增补字符（丢字）"
    assert "T" in md
    (tmp_path / "out.md").write_text(md, encoding="utf-8")   # worker 同款写盘
    # 兑底路径（文本层判定）也必须不抛
    assert imps.pdf_is_text_layer(path) is True


def test_segment_anchor_path_writable_no_char_loss(tmp_path):
    """带锚点段路径同样清洗，且增补字符不丢：产物可直接 write_text。"""
    path = tmp_path / "测试2.pdf"
    path.write_bytes(_malformed_cmap_pdf())
    md, _ = imps.extract_pdf_text_layer(path, None, "", page_from=1, page_to=1, with_anchors=True)
    assert md is not None
    assert not any(0xD800 <= ord(c) <= 0xDFFF for c in md)
    assert "\U0001D435" in md, "段路径成对代理未还原"
    (tmp_path / "out.md").write_text(md, encoding="utf-8")
