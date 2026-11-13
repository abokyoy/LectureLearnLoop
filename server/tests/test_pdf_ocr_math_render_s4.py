# -*- coding: utf-8 -*-
"""Paddle OCR 公式定界收口：$ x $ → $x$（2026-11-03，预览显示源码修复）。

背景：md_render.js 行内公式口径要求 `$` 后首个字符非空格（货币防误判），
而 Paddle OCR 产物风格是 `$ \frac{a}{x} $` 双侧带空格（《测试_3.md》实测 98 处）
→ 整篇公式不匹配、预览显示源码。修复在输出侧：_jsonl_to_markdown 组装时收口
内层空格，一处改动全渲染点（主窗/悬浮窗/知识库/在线课程）一致受益。

守卫（宁漏不错包）：体首字符为数字不动（"$ 5 $" 类货币语境）；体含 CJK 不动；
无空格的既有写法零 diff；`$$…$$` 块级结构不破坏。

运行（server/ 目录）：python -m pytest tests/test_pdf_ocr_math_render_s4.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import import_service as imp  # noqa: E402


# ---------------------------------------------------------------- 纯函数

def test_strip_both_sides():
    assert imp._normalize_ocr_math_delims("$ \\frac{a}{x} $") == "$\\frac{a}{x}$"


def test_strip_one_side():
    assert imp._normalize_ocr_math_delims("$ \\triangle APB $ 是") == "$\\triangle APB$ 是"
    assert imp._normalize_ocr_math_delims("$x $") == "$x$"


def test_no_space_zero_diff():
    s = "在$\\triangle AED$ 和$\\triangle BCE$ 中"
    assert imp._normalize_ocr_math_delims(s) == s


def test_digit_guard():
    # 货币语境：体首为纯数字无线索不收口（保持原文，交给渲染层按原文显示）
    s = "花了 $ 5 $ 元"
    assert imp._normalize_ocr_math_delims(s) == s


def test_digit_with_math_trace_closes():
    # 2026-11-13 收紧（与 md_render.js 货币规则同口径）：数字开头但含数学痕迹（_ ^ { } \ =）
    # 是真公式语境（如追问回答风 $ 2e_i $），照常收口交渲染
    assert imp._normalize_ocr_math_delims("求导得 $ 2e_i $ 再") == "求导得 $2e_i$ 再"
    assert imp._normalize_ocr_math_delims("即 $ 2(\\hat y_i - y_i) $") == "即 $2(\\hat y_i - y_i)$"


def test_cjk_guard():
    s = "四边形 $ 你好 $ 吗"
    assert imp._normalize_ocr_math_delims(s) == s


def test_block_math_structure_preserved():
    # 单行 $$…$$：收口后仍是合法块级定界（外层 $ 不丢）
    assert imp._normalize_ocr_math_delims("$$ x^2 $$") == "$$x^2$$"
    # 跨行块级不动（体不跨 \n）
    s = "$$\n\\frac{1}{2}\n$$"
    assert imp._normalize_ocr_math_delims(s) == s


def test_real_paddle_lines():
    # 《测试_3.md》真实样本行（Paddle 风格混排）
    line = ("（3）显然 $ \\triangle APD \\sim \\triangle CPE $，而 "
            "$ \\frac{AD}{CE} = \\frac{PD}{PE} $，因为 $ PD = CE $，")
    out = imp._normalize_ocr_math_delims(line)
    assert "$ \\triangle" not in out and "$\\triangle APD \\sim \\triangle CPE$" in out
    assert "$\\frac{AD}{CE} = \\frac{PD}{PE}$" in out
    assert "$PD = CE$" in out


def test_empty_and_plain():
    assert imp._normalize_ocr_math_delims("") == ""
    assert imp._normalize_ocr_math_delims("普通文字，无公式。") == "普通文字，无公式。"


# ---------------------------------------------------------------- 评审 W1/I4 回归

def test_latin_separator_zero_diff():
    # 已写对的公式串+拉丁/符号分隔：开 $ 前是上一公式闭合位，lookbehind 拒配
    for s in ("$x$ and $y$", "$x^2$ + $y^2$", "$a$, $b$"):
        assert imp._normalize_ocr_math_delims(s) == s


def test_closed_math_then_paddle_math():
    # 前一无空格公式的闭合 $ 不得吞掉后面的真公式（旧 prev-in-sub 方案在此配对错位）
    s = "$\\alpha$ 和 $ \\beta $"
    assert imp._normalize_ocr_math_delims(s) == "$\\alpha$ 和 $\\beta$"


def test_brace_close_formula_then_paddle_math():
    # 二轮评审 W1 反例：}`/`)`/`%`/`.` 收尾的闭合 $ 均不得错配吞后（拒配整个 ASCII 集）
    for s, exp in (("$\\frac{1}{2}$ and $ x $", "$\\frac{1}{2}$ and $x$"),
                   ("$(a+b)$ and $ g $", "$(a+b)$ and $g$"),
                   ("$a\\%$ and $ b $", "$a\\%$ and $b$"),
                   ("$a.$ and $ b $", "$a.$ and $b$")):
        assert imp._normalize_ocr_math_delims(s) == exp


def test_fullwidth_punct_prefix_still_normalized():
    # 全角标点/中文前置的真公式不漏收口（前导非 ASCII 即放行）
    assert imp._normalize_ocr_math_delims("，$ \\because AB $ 得") == "，$\\because AB$ 得"


def test_fence_and_inline_code_protected():
    s = "```sh\n$ p $HOME\n```"
    assert imp._normalize_ocr_math_delims(s) == s          # 围栏内不动
    s2 = "`$ p $` 与 $ x $"
    out = imp._normalize_ocr_math_delims(s2)
    assert "`$ p $`" in out and "$x$" in out               # 行内代码不动、正文照收


def test_dollar_count_preserved():
    # 不变式：收口不增不减 $ 总数
    s = "$$ x $$ 与 $ \\alpha $ 和 $x$ and $y$，旋转 $ 135^\\circ $ 得到 $AF$"
    assert imp._normalize_ocr_math_delims(s).count("$") == s.count("$")


def test_idempotent_real_patterns():
    # 真实文件实测：单轮因 $ 配对错位残留 2 处，二轮才稳→迭代收敛后必须幂等
    s = ("旋转 $ 135^\\circ $ 得到线段 $AF$，$ \\because 在 \\mathrm{Rt}\\triangle BPH 中，"
         "BH=\\sqrt{2}BP， $ 又 $ \\alpha $ 与 $ \\beta $，求证 $ \\triangle APB $ 等腰")
    one = imp._normalize_ocr_math_delims(s)
    assert imp._normalize_ocr_math_delims(one) == one  # 幂等
    assert "$\\triangle APB$" in one and "$\\alpha$" in one and "$\\beta$" in one
    # 2026-11-13 收紧：数字开头但含数学痕迹（^ \）的 $ 135^\circ $ 是真公式，照常收口；
    # 守卫项仅余含 CJK 的错位段（宁漏不错包）
    assert "$135^\\circ$" in one and "$ 135^\\circ $" not in one
    assert "\\because 在" in one


# ---------------------------------------------------------------- 端到端（_jsonl_to_markdown 出口）

def _fake_jsonl(text: str) -> str:
    return json.dumps({"result": {"layoutParsingResults": [
        {"markdown": {"text": text, "images": {}}}]}}) + "\n"


def test_jsonl_output_normalized(tmp_path):
    md = imp._jsonl_to_markdown(
        _fake_jsonl("则 $ \\frac{a}{x} = \\frac{x}{a - x} $，即可求解."),
        tmp_path / "附件", "t9")
    assert "$\\frac{a}{x} = \\frac{x}{a - x}$" in md
    assert "$ \\frac" not in md


def test_anchors_path_normalized(tmp_path):
    # 书籍分段出口（with_anchors=True）同样生效，锚点不破坏
    md = imp._jsonl_to_markdown(_fake_jsonl("则 $ \\frac{a}{x} $"), tmp_path / "附件",
                                "t9", page_from=41, with_anchors=True)
    assert "<!-- llpage:41 -->" in md and "$\\frac{a}{x}$" in md
