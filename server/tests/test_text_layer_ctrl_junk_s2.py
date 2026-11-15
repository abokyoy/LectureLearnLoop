# -*- coding: utf-8 -*-
"""文本层字体解码垃圾 token 剔除（2026-11-04，九下数学页脚出版社乱码）。

背景：书籍 PDF 页脚「华东师范大学出版社」用装饰字体，pypdf 无 ToUnicode 解码成
`SNN\x1c^\x08\x83\x03Y'[fQúrHy>` 类垃圾——每页一条，或独立成行、或粘连页眉行尾。
此类垃圾必含 C0/C1 控制字符，且总以空格分隔 token 形态出现；正常正文（CJK+数学
符号+ASCII）零控制字符，按 token 剔除不误伤。乱码非 \ufffd，不触发 OCR 回落门，
在清洗层去除即可（正文质量本身完好，无需白耗远端额度）。

运行（server/ 目录）：python -m pytest tests/test_text_layer_ctrl_junk_s2.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import import_service as imp  # noqa: E402

JUNK = "SNN\x1c^\x08\x83\x03Y'[fQúrHy>"


def test_fused_header_line_junk_stripped():
    """垃圾粘连页眉行尾：正文部分保留，垃圾 token 剔除。"""
    out = imp.postprocess_pdf_text_layer(f"第 26 章　 二次函数· 35 {JUNK}")
    assert "第 26 章" in out and "二次函数" in out
    assert "SNN" not in out and "\x08" not in out and "\x1c" not in out


def test_standalone_junk_line_dropped():
    """垃圾独立成行：整段消失，不留空壳。"""
    out = imp.postprocess_pdf_text_layer(f"劣弧的区别吗?\n{JUNK}\n圆的位置由圆心确定")
    assert "SNN" not in out and "\x83" not in out
    assert "劣弧" in out and "圆心确定" in out
    # 不应产生空段落
    assert "\n\n\n" not in out


def test_normal_text_zero_diff():
    """正常文本（CJK/数学符号/ASCII 标点）零改动。"""
    s = "在☉O 中, AC (= BAC, ∵∴△●⌒ 12.5 优弧(major arc)"
    assert imp.postprocess_pdf_text_layer(s) == s


def test_img_markers_untouched():
    """\x00IMG 标记行为不受影响（先于 token 剔除处理）。"""
    out = imp.postprocess_pdf_text_layer("前文\n\x00IMG1\n后文", {1: "a.jpg"})
    assert "![图片](附件/a.jpg)" in out
