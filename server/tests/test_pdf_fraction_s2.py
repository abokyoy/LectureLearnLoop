# -*- coding: utf-8 -*-
"""PDF 分数版式还原回归测试（2026-11-02 二段，用户裁定：还原为 LaTeX 分数）。

真实《测试.pdf》（九年级期中数学）分数为垂直堆叠排版：分子行 '5−1'(y=648.0,fs=10)、
分母行 '2'(y=632.9) Δ=15.1≈1.5×字号；普通换行 Δ/fs≈2.3+；同行上标碎片 Δ/fs≤0.6；
双栏错位候选 dx≥11.5 而真分数中心对齐 dx≤9.7（全页扫描实测）。

还原规则（_recover_fractions，输入 _build_font_lines 行元数据）：
- 候选：短行（≤12 字符）、纯数学白名单、可取字号；
- 配对：dy ≥ 5pt 且 dy/fs ∈ [0.85, 1.75]，水平中心 dx ≤ max(10, 0.6×较大跨度)；
- 命中：整页用 rows 重建（pypdf txt 把分数与正文粘连，行级替换不可行），分子行→
  $\\frac{分子}{分母}$（$ 定界符走系统 KaTeX 渲染管线），分母行删除；
- 未命中：返回 None，调用方保留原 txt（普通文档零 diff）。

运行（server/ 目录）：python -m pytest tests/test_pdf_fraction_s2.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import import_service as imps  # noqa: E402


def _row(text, x_min, x_max, y, fs=10.0):
    """构造 _build_font_lines 行元数据：[文本, fs, 字体, 首x, y, hei_fs, ratio, x_min, x_max]。"""
    return [text, fs, "TimesNewRomanPSMT", x_min, y, 0.0, 0.0, x_min, x_max]


def _txt_of(rows):
    """与 rows 同源的整页 txt（真实 extract_text 按内容流拼接同一批字符，守恒守卫字数相等）。"""
    return "\n".join(r[0] for r in rows)


def _prose(y):
    """正文行（长、含 CJK，永远不进候选）。"""
    return _row("本题考查了相似三角形的判定与性质并灵活", 60, 300, y)


# ---------------------------------------------------------------- 纯函数：命中

def test_basic_fraction_pair():
    rows = [_prose(700.0), _prose(677.0), _prose(654.0),
            _row("5−1", 100.0, 115.0, 564.0), _row("2", 105.0, 108.0, 548.9),
            _prose(525.0)]
    out = imps._recover_fractions(_txt_of(rows), rows)
    assert out is not None
    lines = out.split("\n")
    assert "$\\frac{5−1}{2}$" in lines
    assert "5−1" not in lines and lines.count("2") == 0


def test_multiple_pairs_in_one_page():
    rows = [_prose(760.0), _prose(737.0),
            _row("5−1", 100, 115, 714.0), _row("2", 105, 108, 698.9),
            _prose(676.0),
            _row("5+1", 200, 215, 653.0), _row("2", 205, 208, 637.9),
            _prose(615.0)]
    out = imps._recover_fractions(_txt_of(rows), rows)
    assert out is not None
    assert out.count("$\\frac{") == 2
    assert "$\\frac{5+1}{2}$" in out and "$\\frac{5−1}{2}$" in out


def test_closest_denominator_wins():
    # 同一分子多个候选分母：dy 升序贪心，取最近（15.0 优先于 16.5，fs=10 窗口 [8.5,17.5]）
    rows = [_prose(700.0), _prose(677.0), _prose(654.0),
            _row("5−1", 100, 115, 631.0), _row("3", 105, 108, 614.5),
            _row("2", 105, 108, 616.0), _prose(590.0)]
    out = imps._recover_fractions(_txt_of(rows), rows)
    assert out is not None
    assert "$\\frac{5−1}{2}$" in out
    assert "$\\frac{5−1}{3}$" not in out


def test_non_math_page_returns_none_zero_diff():
    # 无候选短行：返回 None，调用方保留 extract_text 原文
    rows = [_prose(700.0), _prose(677.0), _prose(654.0)]
    assert imps._recover_fractions(_txt_of(rows), rows) is None


# ---------------------------------------------------------------- 纯函数：拒绝

def test_reject_superscript_gap():
    # Δ/fs≤0.6：同一视觉行的上标碎片，不是分数
    rows = [_prose(700.0), _prose(677.0), _prose(654.0),
            _row("x", 100, 106, 631.0), _row("2", 107, 110, 628.5), _prose(605.0)]
    assert imps._recover_fractions(_txt_of(rows), rows) is None


def test_reject_normal_line_gap():
    # dy/fs≈2.3：普通换行的悬空短行，不在堆叠窗口
    rows = [_prose(700.0), _prose(677.0), _prose(654.0),
            _row("5−1", 100, 115, 631.0), _row("2", 105, 108, 608.0), _prose(585.0)]
    assert imps._recover_fractions(_txt_of(rows), rows) is None


def test_reject_cjk_line():
    # 候选含 CJK：双栏正文短句，白名单直接排除
    rows = [_prose(700.0), _prose(677.0), _prose(654.0),
            _row("得解；", 100, 130, 631.0), _row("2", 105, 108, 616.0), _prose(593.0)]
    assert imps._recover_fractions(_txt_of(rows), rows) is None


def test_reject_equals_line():
    # 含等号：完整等式不是分数部件
    rows = [_prose(700.0), _prose(677.0), _prose(654.0),
            _row("x=3", 100, 120, 631.0), _row("2", 105, 108, 616.0), _prose(593.0)]
    assert imps._recover_fractions(_txt_of(rows), rows) is None


def test_reject_cross_column_mispair():
    # 双栏：分子左栏、分母右栏（中心相距 200+pt），dx 排除
    rows = [_prose(700.0), _prose(677.0), _prose(654.0),
            _row("5−1", 60, 75, 631.0), _row("2", 320, 323, 616.0), _prose(593.0)]
    assert imps._recover_fractions(_txt_of(rows), rows) is None


def test_reject_unknown_font_size():
    # fs 取不到（0）：不猜测版式，不参与配对
    rows = [_prose(700.0), _prose(677.0), _prose(654.0),
            _row("5−1", 100, 115, 631.0, fs=0.0), _row("2", 105, 108, 616.0, fs=0.0),
            _prose(593.0)]
    assert imps._recover_fractions(_txt_of(rows), rows) is None


# ---------------------------------------------------------------- 端到端（构造堆叠版式 PDF）

def test_build_font_lines_blank_line_placeholder():
    """评审 C1：连续裸 '\n' 片段的空行占位必须与常规行同构（否则六字段解包崩、整页回落 OCR）。"""
    frags = [(677.0, 60.0, "first line", 10.0, "F1"),
             (0.0, 0.0, "\n", 0.0, ""),
             (0.0, 0.0, "\n", 0.0, ""),          # cur_t 已空 → 空行占位分支
             (654.0, 60.0, "second line", 10.0, "F1")]
    rows = imps._build_font_lines(frags)
    assert all(len(r) == 9 for r in rows)
    assert any(r[0] == "" for r in rows)         # 空行占位行存在

def _stacked_fraction_pdf() -> bytes:
    """构造含分数堆叠版式的 PDF：多行正文（23pt 行距）+ 分子/分母（Δ=11pt，fs=11）。"""
    lines = []
    y = 760.0
    for i in range(9):
        lines.append((y, f"Answer explanation line number {i:02d} padding text"))
        y -= 23.0
    lines.append((y, "(2x+1)"))      # 分子
    lines.append((y - 11.0, "4"))    # 分母：dy=11，fs=11 → r=1.0 命中窗口
    body = "BT /F1 11 Tf\n"
    for ly, t in lines:
        body += f"1 0 0 1 60 {ly:.1f} Tm ({t}) Tj\n"
    body += "ET\n"
    text = body.encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, b_ in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + b_ + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return out


def test_extract_layer_fraction_end_to_end(tmp_path):
    path = tmp_path / "分数.pdf"
    path.write_bytes(_stacked_fraction_pdf())
    md, _ = imps.extract_pdf_text_layer(path)
    assert md is not None, "整文件路径未命中文本层，测试空跑"
    assert "$\\frac{(2x+1)}{4}$" in md, f"分数未还原为 LaTeX：\n{md[-400:]}"
    assert "\n4\n" not in md  # 分母独立行已消失
    (tmp_path / "out.md").write_text(md, encoding="utf-8")


def test_no_fraction_page_zero_diff(tmp_path):
    # 无堆叠版式：不触发重建，无 \frac 痕迹
    content = "".join(
        f"BT /F1 11 Tf 1 0 0 1 60 {760 - i * 23:.1f} Tm "
        f"(Plain prose line number {i:02d} with padding padding text) Tj ET\n"
        for i in range(9))
    path = tmp_path / "普通.pdf"
    path.write_bytes(_plain_pdf(content))
    md, _ = imps.extract_pdf_text_layer(path)
    assert md is not None
    assert "\\frac" not in md


def _plain_pdf(content_text: str) -> bytes:
    text = content_text.encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, b_ in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + b_ + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return out


def test_book_path_untouched(tmp_path):
    """带锚点段路径（书籍）本阶段不做分数还原，产物零 diff：不出现 \frac。"""
    path = tmp_path / "分数段.pdf"
    path.write_bytes(_stacked_fraction_pdf())
    md, _ = imps.extract_pdf_text_layer(path, None, "", page_from=1, page_to=1, with_anchors=True)
    assert md is not None
    assert "\\frac" not in md
