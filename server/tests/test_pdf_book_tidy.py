# -*- coding: utf-8 -*-
"""PDF④ 书籍段规则后处理单测（2026-10-07）。

覆盖 tidy_book_text 三层规则 + postprocess_pdf_text_layer 标记落地：
- R1 标题：黑体/粗体且字号≥1.15×正文众数 → \x01 标记（≥1.8× 为 H1）；纯数字行不得标标题；
- R1 页眉/页脚：行 y 位于顶/底边距带整行剔除；
- R2 装饰：连续 ≥3 纯数字行整组剔除（孤行保留）；水印行、Word 域错误行剔除；
- R3 目录：点线行改写为 \x02- 标题 · 页码；
- 双层降级：字体元数据对齐失败（匹配率<0.7）时跳过 R1，但 R2/R3 纯文本规则仍生效；
- 对齐前缀匹配：目录页点线被拆为独立 fl 行（fl 是 txt 前缀）时仍可对齐。
- 落地：\x01/\x02 标记在清洗阶段转为 #/## 标题与独立段落，控制字符零泄漏。

运行（server/ 目录）：python -m pytest tests/test_pdf_book_tidy.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.import_service import postprocess_pdf_text_layer, tidy_book_text  # noqa: E402

PAGE_H = 683.0


def _fl(text, fs, dom, y, hei=None, ratio=None):
    """font_lines 元组形态：[文本, 代表字号, 主字体名, x, y(, 行内黑体片段最大字号(, 黑体汉字覆盖率))]。"""
    row = [text, fs, dom, 50.0, y]
    if hei is not None:
        row.append(hei)
        if ratio is not None:
            row.append(ratio)
    return row


# ---------------------------------------------------------------- R1 标题 + 页眉

def test_r1_headings_detected_and_header_footer_removed():
    body = "这是正文内容段落示例需要足够长以便成段。"
    txt = "\n".join([
        "机器学习  V",              # 页眉：y=615 ≥ 0.885h → 剔除
        body,                        # 正文 10.5pt 宋体（众数）
        body,
        "译 者 序",                  # 23pt simhei ≥1.8× → H1
        "读者对象",                  # 14pt simhei 1.15~1.8× → H2
        "普通行不加标记",             # 10.5pt 宋体，不标
        "Bold 12pt 非黑体名不标",     # bold 之外的普通字体名 12pt <1.15× 不标
    ])
    fl = [
        _fl("机器学习  V", 10.5, "/Songti", 615.0),
        _fl(body, 10.5, "/Songti", 500.0),
        _fl(body, 10.5, "/Songti", 480.0),
        _fl("译 者 序", 23.0, "/SimHei", 460.0),
        _fl("读者对象", 14.0, "/STHeiti", 440.0),
        _fl("普通行不加标记", 10.5, "/Songti", 420.0),
        _fl("Bold 12pt 非黑体名不标", 12.0, "/TimesNewRoman", 400.0),
    ]
    out = tidy_book_text(txt, fl, PAGE_H)
    lines = out.split("\n")
    assert lines[0] == ""                                   # 页眉剔除
    assert "\x011 译 者 序" in out
    assert "\x012 读者对象" in out
    assert "\x01 普通行" not in out.replace("\x011", "")    # 正文字号行不标
    assert "Bold 12pt 非黑体名不标" in out                   # 原样保留

    # 落地：postprocess 转 Markdown，控制字符消失
    md = postprocess_pdf_text_layer(out)
    assert "# 译 者 序" in md
    assert "## 读者对象" in md
    assert "\x01" not in md and "\x02" not in md


def test_r1_pure_digit_line_never_heading():
    """目录导航图编号（12pt Bold 纯数字）不得被标成 ## 1 伪标题（用户验收发现）。"""
    body = "正文句子，字数足够形成为众数字体基准。"
    txt = "\n".join([body, body, "1", "2", ""])
    fl = [
        _fl(body, 10.5, "/Songti", 400.0),
        _fl(body, 10.5, "/Songti", 380.0),
        _fl("1", 12.0, "/SimHeiBold", 360.0),
        _fl("2", 12.0, "/SimHeiBold", 350.0),
    ]
    out = tidy_book_text(txt, fl, PAGE_H)
    assert "\x01" not in out                       # 不标标题
    assert "\n1\n" in out and "\n2\n" in out       # 保留交给后续清洗（2 行 <3 不剔除）


def test_r1_hei_fragment_fallback_when_spaces_steal_dom():
    """正文 1.1 节标题：汉字黑体 14pt，但空格 run 属 Arial 抢走主导字体→靠 hei_fs 兜底识别（探针实变）。"""
    body = "这是一行足够长的正文内容句子，用来构成含中文字符的字号众数基准。"
    txt = "\n".join([body, body, "1.1 何谓机器学习", body])
    fl = [
        _fl(body, 10.0, "/FZSSJW--GB1-0", 400.0),
        _fl(body, 10.0, "/FZSSJW--GB1-0", 380.0),
        _fl("1.1 何谓机器学习", 14.0, "/BKMDOH+Arial", 360.0, hei=14.0),  # dom 被空格抢走
        _fl(body, 10.0, "/FZSSJW--GB1-0", 340.0),
    ]
    out = tidy_book_text(txt, fl, PAGE_H)
    assert "\x012 1.1 何谓机器学习" in out          # 14/10=1.4 ≥1.3 → H2
    md = postprocess_pdf_text_layer(out)
    assert "## 1.1 何谓机器学习" in md


def test_r1_third_level_section_h3():
    """三级标题（12pt/基准10pt=1.2）落 ### ，与二级（14pt=1.4）分层。"""
    body = "这是一行足够长的正文内容句子，用来构成含中文字符的字号众数基准。"
    txt = "\n".join([body, body, "1.1.1 传感器和海量数据", body])
    fl = [
        _fl(body, 10.0, "/FZSSJW--GB1-0", 400.0),
        _fl(body, 10.0, "/FZSSJW--GB1-0", 380.0),
        _fl("1.1.1 传感器和海量数据", 12.0, "/BKMDOH+Arial", 360.0, hei=12.0, ratio=1.0),
        _fl(body, 10.0, "/FZSSJW--GB1-0", 340.0),
    ]
    out = tidy_book_text(txt, fl, PAGE_H)
    assert "\x013 1.1.1 传感器和海量数据" in out
    md = postprocess_pdf_text_layer(out)
    assert "### 1.1.1 传感器和海量数据" in md


def test_r1_inline_hei_emphasis_not_marked():
    """评审 Warning 回归：正文短句仅个别内联黑体强调（汉字覆盖率<0.5）不得被兜底误标为标题；
    黑体覆盖全部汉字的真实标题（含拉丁占比高的「1.6 Python…」型）仍命中。"""
    body = "这是一行足够长的正文内容句子，用来构成含中文字符的字号众数基准。"
    emph = "术语 X 是本节核心概念"      # 12字≤ 30，含 CJK；仅「术语」两字黑体 12pt
    py = "1.6 Python语言的优势"          # Python 属 Arial，但汉字全黑体→覆盖率 1.0
    txt = "\n".join([body, body, emph, py, "1.3 机器学习的主要任务", body])
    fl = [
        _fl(body, 10.0, "/FZSSJW--GB1-0", 400.0),
        _fl(body, 10.0, "/FZSSJW--GB1-0", 380.0),
        _fl(emph, 12.0, "/FZSSJW--GB1-0", 360.0, hei=12.0, ratio=2 / 9),    # 汉字覆盖率 0.22 <0.5
        _fl(py, 12.0, "/BKMDOH+Arial", 350.0, hei=12.0, ratio=1.0),          # 拉丁不计入分母
        _fl("1.3 机器学习的主要任务", 14.0, "/BKMDOH+Arial", 340.0, hei=14.0, ratio=1.0),
        _fl(body, 10.0, "/FZSSJW--GB1-0", 320.0),
    ]
    out = tidy_book_text(txt, fl, PAGE_H)
    lines = out.split("\n")
    assert not any(ln.startswith("\x01") and "术语" in ln for ln in lines)   # 内联强调行未被标记
    assert emph in out                                                        # 原样保留
    assert any(ln == "\x013 1.6 Python语言的优势" for ln in lines)            # 12/10=1.2 → H3
    assert any(ln == "\x012 1.3 机器学习的主要任务" for ln in lines)           # 真实标题仍命中


def test_body_baseline_from_long_cjk_lines_not_code_fragments():
    """代码页：大量短 12pt 拉丁行不得抬高质量基准——基准取 CJK 长行众数 10pt，12pt 黑体标题仍命中。"""
    body = "这是一行足够长的正文内容句子，用来构成含中文字符的字号众数基准。"
    code_lines = ["def knn(data, label, k):" for _ in range(6)]     # 短 ASCII 12pt（不计入基准）
    txt = "\n".join([body, body] + code_lines + ["2.2 准备数据"])
    fl = ([_fl(body, 10.0, "/FZSSJW--GB1-0", 400.0 - i) for i in (0, 1)]
          + [_fl(c, 12.0, "/CourierNew", 300.0 - i) for i, c in enumerate(code_lines)]
          + [_fl("2.2 准备数据", 12.0, "/SimHei", 200.0)])
    out = tidy_book_text(txt, fl, PAGE_H)
    assert "\x013 2.2 准备数据" in out              # 12/10=1.2 → H3（旧基准 12 会漏标）


def test_hdr_band_guards_bad_coordinates():
    """异常坐标（y 负值/y=0 重置点/矩阵残留超大 y）与正文长行不得被页眉带规则误删；真页眉短行仍剔除。"""
    long_body = "这一行是正文长句，字符数肯定超过三十四个字的短行门槛，用来验证不会被误删除。"
    txt = "\n".join([
        "第 1 章 概述",          # y=615 页眉带短行 → 剔除
        long_body,                # y=16.4 坐标残留的正文长行 → 保留
        "。然后创建矩阵",       # y=0.0 重置点短行 → 保留
        "短行负y坐标残片",       # y=-133 负值 → 保留
        "短行超大y坐标异常残片",   # y=6138 矩阵残留 → 保留（超出合法页范围）
    ])
    fl = [
        _fl("第 1 章 概述", 10.5, "/TimesNewRoman", 615.7),
        _fl(long_body, 10.0, "/FZSSJW--GB1-0", 16.4),
        _fl("。然后创建矩阵", 10.0, "/FZSSJW--GB1-0", 0.0),
        _fl("短行负y坐标残片", 10.0, "/FZSSJW--GB1-0", -133.0),
        _fl("短行超大y坐标异常残片", 10.0, "/FZSSJW--GB1-0", 6138.2),
    ]
    out = tidy_book_text(txt, fl, PAGE_H)
    assert "第 1 章 概述" not in out                 # 真页眉（y=615.7 合法带内短行）仍被剔
    assert "坐标残片" in out and "然后创建矩阵" in out
    assert long_body.split("，")[0] in out           # 正文长行保留（探针实变 344 行误删回归）


# ---------------------------------------------------------------- R2 装饰与噪声

def test_r2_digit_run_removed_lone_kept():
    txt = "段落前正文文字内容足够长成句。\n1\n2\n3\n4\n段落后正文文字内容也长。\n7\n正文尾行。"
    out = tidy_book_text(txt, None, 0.0)
    lines = [ln.strip() for ln in out.split("\n")]
    assert "3" not in lines and "4" not in lines   # ≥3 连续组整组剔除
    assert "7" in lines                            # 孤行数字保留
    assert "段落前正文文字内容足够长成句。" in out

    md = postprocess_pdf_text_layer(out)
    assert "\n1\n" not in md                       # 纯数字碎片不独立成段


def test_r2_watermark_and_field_error_removed():
    txt = "正常正文一。\n图灵社区会员 张三 专享——尊重版权\n错误！文档中没有指定样式的文字。\n正常正文二。"
    out = tidy_book_text(txt, None, 0.0)
    assert "图灵社区会员" not in out
    assert "错误！" not in out
    md = postprocess_pdf_text_layer(out)
    assert "正常正文一" in md and "正常正文二" in md


# ---------------------------------------------------------------- R3 目录点线

def test_r4_caption_bold_standalone_and_refs_untouched():
    """R4：行首「图/表x-x+空格」题注→编号加粗独立段；正文引用（无空格）与叙述句（句末标点）不改。"""
    txt = ("图 2-1 使用打斗和接吻镜头数分类电影\n"
           "表1-1是我们用于区分不同鸟类需要使用的四个不同的属性值\n"
           "图1-1集中展示了使用到的机器学习应用。\n"
           "图 3-2 展示的是完整流程，值得注意。\n"
           "正文句子结束。")
    out = tidy_book_text(txt, None, 0.0)
    assert "\x02**图 2-1** 使用打斗和接吻镜头数分类电影" in out
    assert "表1-1是我们" in out            # 无空格→不改
    assert "图1-1集中展示了" in out        # 无空格→不改
    assert "图 3-2 展示的是完整流程，值得注意。" in out  # 句末标点→正文叙述句不改
    md = postprocess_pdf_text_layer(out)
    assert md.split("\n\n")[0] == "**图 2-1** 使用打斗和接吻镜头数分类电影"  # 独立成段
    assert "\x02" not in md

def test_r3_toc_dot_leader_to_list_item():
    txt = (
        "8.2 局部加权线性回归 ......... 141\n"
        "9.7.2 集成 Matplotlib 和 Tkinter .... 179\n"
        "普通句子结尾是句号。\n"
        "无页码的行 .... 没有数字不算目录\n"
    )
    out = tidy_book_text(txt, None, 0.0)
    assert "\x02- 8.2 局部加权线性回归 \u00b7 141" in out
    assert "\x02- 9.7.2 集成 Matplotlib 和 Tkinter \u00b7 179" in out
    assert "普通句子结尾是句号。" in out
    assert "\x02" not in out.split("无页码")[1].split("\n")[0]  # 尾无数字不改写

    md = postprocess_pdf_text_layer(out)
    assert "- 8.2 局部加权线性回归 \u00b7 141" in md
    assert "\x02" not in md


def test_r3_does_not_overwrite_r1_marked_heading():
    """评审 Critical 回归：黑体大字号节标题自带点线页码时，R1 标记不得被 R3 覆写而泄漏 \x01。"""
    body = "正文内容句子需要足够长以构成字体众数基准。"
    txt = "\n".join([body, body, "附录 B 矢量图 .... 201", "普通目录行 .... 205"])
    fl = [
        _fl(body, 10.5, "/Songti", 400.0),
        _fl(body, 10.5, "/Songti", 380.0),
        _fl("附录 B 矢量图", 18.0, "/SimHei", 360.0),  # 1.71× → R1 标 H2
    ]
    out = tidy_book_text(txt, fl, PAGE_H)
    assert "\x012 附录 B 矢量图 .... 201" in out        # R1 标记保留，未被 R3 改写
    assert "\x02- 普通目录行 \u00b7 205" in out          # 未标记行照常走 R3

    md = postprocess_pdf_text_layer(out)
    assert "\x01" not in md and "\x02" not in md        # 控制字符零泄漏


# ---------------------------------------------------------------- 降级与对齐

def test_degrade_when_font_lines_misaligned_r2_r3_still_apply():
    """元数据与文本行严重失配（匹配率<0.7）→ 跳过 R1 标题/页眉，但 R2/R3 文本规则仍生效。"""
    txt = "完全对不上的真实正文行一。\n完全对不上的真实正文行二。\n1\n2\n3\n某节标题 ........ 25"
    fl = [_fl("无关元数据行A", 20.0, "/SimHei", 100.0)]
    out = tidy_book_text(txt, fl, PAGE_H)
    assert "\x01" not in out                       # R1 未启用（标题不标）
    assert "\x02- 某节标题 \u00b7 25" in out        # R3 仍生效
    lines = [ln.strip() for ln in out.split("\n")]
    assert "2" not in lines                        # R2 仍生效（≥3 连续数字剔除）


def test_align_prefix_match_for_dot_leader_rows():
    """点线被拆为独立 fl 行时（fl 行是 txt 行前缀）仍对齐，从而取到元数据走 R3。"""
    body = "正文行内容需要长一点构成有效匹配样本。"
    txt = "\n".join([body, body, "10.4 示例 对地图上的点进行聚类 .... 193"])
    fl = [
        _fl(body, 10.5, "/Songti", 400.0),
        _fl(body, 10.5, "/Songti", 380.0),
        _fl("10.4 示例 对地图上的点进行聚类", 10.5, "/Songti", 360.0),  # 无点线的前缀行
    ]
    out = tidy_book_text(txt, fl, PAGE_H)
    assert "\x02- 10.4 示例 对地图上的点进行聚类 \u00b7 193" in out
