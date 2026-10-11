# -*- coding: utf-8 -*-
"""错题智能分析服务层断言测试（2026-10-13，离线：不打外网、不依赖 Flask 进程）。

覆盖：
1. TaskRegistry：create/finish/get、consume 与可重复读语义、归属校验、TTL 回收
2. error_ocr 切换 TaskRegistry 后回归（mock paddle）：done 文本、读取即弃、跨用户不可见
3. md_image_paths：去重保序、拒 http/data、拒非图片
4. _parse_jsonl_and_crop：bbox 动态换算裁剪（非 2 倍比例样例）、texts/figures 提取、坏行容错
5. extract_json：裸 JSON/围栏/前后杂质/尾逗号修复/失败抛错
6. assemble_result：解析小节拼装（解答→错因→解析），空字段跳过
7. _run 降级链（mock paddle 抛错 + mock VL）：版面失败仍发原图；VL 返回不可解析 → 任务 error
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image  # noqa: E402

from services import error_analyze, error_ocr  # noqa: E402
from services.task_registry import TaskRegistry  # noqa: E402


def _fake_jsonl(page_w=2400, page_h=1400, blocks=None):
    res = {"prunedResult": {"width": page_w, "height": page_h,
                             "parsing_res_list": blocks or []},
           "markdown": {"text": "hello"}}
    return json.dumps({"result": {"layoutParsingResults": [res]}}, ensure_ascii=False)


def _make_png(path, w, h):
    Image.new("RGB", (w, h), "white").save(path)


class TestTaskRegistry(unittest.TestCase):
    def test_create_finish_get_consume(self):
        reg = TaskRegistry(ttl_s=600)
        tid = reg.create(user_id="u1")
        self.assertEqual(reg.get(tid, user_id="u1")["status"], "running")
        self.assertIsNone(reg.get(tid, user_id="u2"))  # 跨用户视同不存在
        reg.finish(tid, "done", text="abc")
        self.assertEqual(reg.get(tid, user_id="u1")["text"], "abc")
        # consume=False 可重复读
        self.assertIsNotNone(reg.get(tid, user_id="u1"))
        # consume=True 读取即弃
        self.assertIsNotNone(reg.get(tid, user_id="u1", consume=True))
        self.assertIsNone(reg.get(tid, user_id="u1", consume=True))

    def test_ttl_sweep(self):
        reg = TaskRegistry(ttl_s=1)
        tid = reg.create(user_id="u1")
        with reg._lock:
            reg._tasks[tid]["ts"] = time.time() - 2
            reg._sweep_locked(time.time())
        self.assertIsNone(reg.get(tid, user_id="u1"))


class TestErrorOcrRegression(unittest.TestCase):
    """error_ocr 切换公共 TaskRegistry 后行为回归（mock paddle，不打外网）。"""

    def _run_ok(self):
        tmp = tempfile.mkdtemp()
        img = os.path.join(tmp, "q.png")
        _make_png(img, 100, 80)
        jsonl = json.dumps({"result": {"layoutParsingResults": [
            {"markdown": {"text": "题目文字 ABC\n![](https://x/y.jpg)"}}]}})

        class FakePaddle:
            PaddleDocTransientError = error_ocr.paddle.PaddleDocTransientError
            PaddleDocError = error_ocr.paddle.PaddleDocError

            @staticmethod
            def submit_job(p):
                return "job-1"

            @staticmethod
            def query_job(j):
                return {"state": "done", "resultUrl": {"jsonUrl": "https://u"}}

            @staticmethod
            def download_jsonl(u):
                return jsonl

        with mock.patch.object(error_ocr, "paddle", FakePaddle):
            tid = error_ocr.start_ocr(img, user_id="ua")
            for _ in range(50):
                r = error_ocr.get_result(tid, user_id="ua")
                if r and r["status"] != "running":
                    break
                time.sleep(0.1)
        self.assertEqual(r["status"], "done")
        self.assertIn("题目文字 ABC", r["text"])
        self.assertNotIn("https://x/y.jpg", r["text"])  # 远程图片引用仍被剔除
        # 读取即弃语义保持
        self.assertIsNone(error_ocr.get_result(tid, user_id="ua"))

    def test_cross_user_invisible(self):
        tmp = tempfile.mkdtemp()
        img = os.path.join(tmp, "q.png")
        _make_png(img, 10, 10)
        tid = error_ocr.start_ocr(img, user_id="owner")
        self.assertIsNone(error_ocr.get_result(tid, user_id="other"))
        self.assertIsNotNone(error_ocr.get_result(tid, user_id="owner"))
        error_ocr._registry.finish(tid, "error", error="cleanup")


class TestMdImagePaths(unittest.TestCase):
    def test_extract(self):
        md = ("![a](截图/手机_x.png) text ![b](截图/手机_x.png) ![c](https://e.com/1.png)\n"
              "![d](pics/shot.JPG) ![e](data:image/png;base64,AAA) ![f](notes/a.txt)")
        self.assertEqual(error_analyze.md_image_paths(md), ["截图/手机_x.png", "pics/shot.JPG"])

    def test_empty(self):
        self.assertEqual(error_analyze.md_image_paths(""), [])


class TestParseJsonlAndCrop(unittest.TestCase):
    def test_crop_scaled_and_extracted(self):
        tmp = tempfile.mkdtemp()
        rel = "截图/prob.png"
        abs_p = os.path.join(tmp, "prob.png")
        _make_png(abs_p, 600, 350)  # 本地 600×350，页面 2400×1400 → 比例 0.25（非 2 倍样例）
        blocks = [
            {"block_label": "text", "block_bbox": [0, 0, 1200, 300], "block_content": "In triangle ABC"},
            {"block_label": "image", "block_bbox": [1200, 700, 2400, 1400]},
            {"block_label": "image", "block_bbox": [1200, 1000, 9999, 9999]},  # 部分越界 → clamp
            {"block_label": "image", "block_bbox": [2500, 0, 9999, 9999]},  # 完全越界 → 跳过裁剪
        ]
        out = error_analyze._parse_jsonl_and_crop(_fake_jsonl(2400, 1400, blocks), rel, abs_p)
        self.assertEqual(out["page_size"], [2400, 1400])
        self.assertEqual(len(out["texts"]), 1)
        self.assertEqual(out["texts"][0]["content"], "In triangle ABC")
        self.assertEqual(len(out["figures"]), 3)
        crop0 = out["figures"][0].get("crop_rel")
        self.assertEqual(crop0, "截图/prob_fig0.png")
        im = Image.open(os.path.join(tmp, "prob_fig0.png"))
        self.assertEqual(im.size, (300, 175))  # 1200*0.25 × 700*0.25 起算
        # 部分越界块 clamp 后裁出右下角截断区域：(300,250)→(600,350) = 300×100
        self.assertEqual(out["figures"][1].get("crop_rel"), "截图/prob_fig1.png")
        self.assertEqual(Image.open(os.path.join(tmp, "prob_fig1.png")).size, (300, 100))
        # 完全越界（x1 超图宽）→ 裁剪区域为空，不落盘（防护行为）
        self.assertIsNone(out["figures"][2].get("crop_rel"))

    def test_bad_line_tolerated(self):
        tmp = tempfile.mkdtemp()
        abs_p = os.path.join(tmp, "a.png")
        _make_png(abs_p, 100, 100)
        text = "not-json\n" + _fake_jsonl(100, 100, [
            {"block_label": "text", "block_bbox": [0, 0, 10, 10], "block_content": "ok"}])
        out = error_analyze._parse_jsonl_and_crop(text, "a.png", abs_p)
        self.assertEqual(out["texts"][0]["content"], "ok")
        self.assertEqual(out["figures"], [])


class TestExtractJson(unittest.TestCase):
    def test_variants(self):
        payload = '{"stem_md": "A", "correct_answer": "B", "explanation": "", "user_solution_md": "", "error_analysis": ""}'
        self.assertEqual(error_analyze.extract_json(payload)["stem_md"], "A")
        self.assertEqual(error_analyze.extract_json("```json\n" + payload + "\n```")["stem_md"], "A")
        self.assertEqual(error_analyze.extract_json("前置说明文字 " + payload + " 尾巴")["stem_md"], "A")
        fixed = '{"a": 1, "b": [1,2,],}'
        self.assertEqual(error_analyze.extract_json(fixed)["a"], 1)

    def test_fail_raises(self):
        with self.assertRaises(ValueError):
            error_analyze.extract_json("完全不是 JSON")


class TestAssembleResult(unittest.TestCase):
    def test_sections(self):
        r = error_analyze.assemble_result({
            "stem_md": "题干 ![图形](截图/a_fig0.png)",
            "user_solution_md": "B = 140/2 = 70",
            "error_analysis": "等腰角用错",
            "correct_answer": "70°",
            "explanation": "180-40=140, 140/2=70",
        })
        self.assertEqual(r["stem_md"], "题干 ![图形](截图/a_fig0.png)")
        self.assertEqual(r["correct_answer"], "70°")
        self.assertIn("## 我的解答（如实转录）\nB = 140/2 = 70", r["explanation"])
        self.assertIn("## 错在哪里\n等腰角用错", r["explanation"])
        self.assertIn("## 解析\n180-40=140, 140/2=70", r["explanation"])
        # 解答在解析开头（用户裁定 B）
        self.assertTrue(r["explanation"].startswith("## 我的解答"))

    def test_empty_optional(self):
        r = error_analyze.assemble_result({"stem_md": "x", "correct_answer": "", "explanation": ""})
        self.assertEqual(r["explanation"], "")


class TestWrapBareLatex(unittest.TestCase):
    """裸 LaTeX 定界保底（2026-10-13 用户裁定方案 A）：整行裸公式包 $$…$$，其余一字不动。"""

    # 取自库里 id=980 的真实转录（VL 无定界裸输出）
    REAL_980 = (
        "(1)\\Delta=(m-2)^{2}-4(-2m)\n"
        "=m^{2}-4m+4+8m\n"
        "=(m+2)^{2}\\geq0\n"
        "\\therefore\\text{不论}m\\text{取何值, 此方程总有实数根}.\n"
        "(2)\\text{由求根公式得: }x=\\frac{-(m-2)\\pm\\sqrt{(m+2)^{2}}}{2}=\\frac{2-m\\pm|m+2|}{2}\n"
        "\\text{即}x_1=\\frac{2-m+m+2}{2}=2\\text{, }x_2=\\frac{2-m-(m+2)}{2}=-m\n"
        "综上, $m>-2$, 又 m 为整数")

    def test_wraps_bare_lines_keeps_others(self):
        out = error_analyze._wrap_bare_latex(self.REAL_980)
        lines = out.split("\n")
        # 裸 LaTeX 行全部包成块级，内容不变仅加定界
        for i in range(6):
            self.assertTrue(lines[i].startswith("$$") and lines[i].endswith("$$"), lines[i])
            self.assertIn(self.REAL_980.split("\n")[i], lines[i])
        # 已带 $ 定界的行不动；无 \命令的纯中文行不动（“综上又m为整数”尾行含 $ 行除外）
        self.assertEqual(lines[6], "综上, $m>-2$, 又 m 为整数")

    def test_conservative_no_false_wrap(self):
        keep = ("## 标题行\n"
                "题目如图。\n"
                "![图形](截图/a_fig0.png)\n"
                "已包好的 $x_1=2$ 与 $$y=3$$\n"
                "照片存在 C:\\Users\\img 目录\n"
                "纯文字叙述没有任何反斜杠")
        self.assertEqual(error_analyze._wrap_bare_latex(keep), keep)

    def test_already_delimited_latex_style_untouched(self):
        # 库里老题干真实形态（id=2/15/1759）：中文叙述 + \\(..\\) 行内定界，不得整行包
        line = "设函数 \\(f(x)=x^2+1\\)，则 \\(\\lim\\limits_{h\\to 0}\\frac{f(2+h)-f(2)}{h}=\\)（ ）"
        self.assertEqual(error_analyze._wrap_bare_latex(line), line)
        # 跨行 \\[..\\] 块（id=76 真实形态）：块内部行二次包裹会砸坏公式，必须原样
        block = ("设函数 \\(f(x)=2x^2-x\\)，计算极限\n"
                 "\\[\n"
                 "\\lim_{\\Delta x\\to 0}\\frac{f(1+\\Delta x)-f(1)}{\\Delta x}\n"
                 "\\]\n"
                 "的值。")
        self.assertEqual(error_analyze._wrap_bare_latex(block), block)

    def test_unicode_math_prose_line_untouched(self):
        # 迁移抽查发现的真误判（pr#43）：Unicode 写法中文题干含 lim_{…} 结构，
        # 但公式外中文很多 → 叙述主体行，不得整行包进公式
        line = ("设函数 f(x) 在 x=3 处可导，且 lim_{Δx→0} [f(3+2Δx)-f(3)]/Δx = 8，"
                "则 f'(3)=（ ）。")
        self.assertEqual(error_analyze._wrap_bare_latex(line), line)

    def test_assemble_integration(self):
        r = error_analyze.assemble_result({
            "stem_md": "已知方程 $x^2-(m-2)x-2m=0$",   # 已带定界 → 不变
            "user_solution_md": "\\Delta=(m-2)^{2}-4(-2m)",
            "error_analysis": "漏了 $m\\geq-2$ 分支",   # 已带定界 → 不变
            "correct_answer": "m\\geq-1",
            "explanation": "见 C:\\note 无公式",          # 路径误判保护 → 不变
        })
        self.assertIn("$$\\Delta=(m-2)^{2}-4(-2m)$$", r["explanation"])
        self.assertIn("## 我的解答（如实转录）\n$$", r["explanation"])
        self.assertEqual(r["stem_md"], "已知方程 $x^2-(m-2)x-2m=0$")
        self.assertIn("$m\\geq-2$", r["explanation"])      # 错因行未被二次包裹
        self.assertEqual(r["correct_answer"], "$$m\\geq-1$$")
        self.assertEqual(r["explanation"].split("## 解析\n")[1], "见 C:\\note 无公式")

    def test_empty_and_passthrough(self):
        self.assertEqual(error_analyze._wrap_bare_latex(""), "")
        self.assertEqual(error_analyze._wrap_bare_latex("   \n  \n"), "   \n  \n")

    # ---- 2026-10-13 CodeReview 处置回归（Major-1 + Minor-2/3/4/5）----

    def test_midline_opener_tracks_block(self):
        # Major-1：行中部 \[ 开块必须被跟踪，块内裸 LaTeX 行不得二次包裹砸坏
        src = "foo \\[\n\\Delta=0\n\\]"
        self.assertEqual(error_analyze._wrap_bare_latex(src), src)
        # 奇数次 $$ 同理：块内行原样
        src2 = "前置 $$\nx=1\n$$"
        self.assertEqual(error_analyze._wrap_bare_latex(src2), src2)

    def test_list_and_quote_lines_never_wrapped(self):
        # Minor-2：Markdown 列表/引用行 marker 不得混入公式体
        src = ("- \\Delta=0\n"
               "1. \\frac{a}{b}=2\n"
               "> \\sqrt{9}=3")
        self.assertEqual(error_analyze._wrap_bare_latex(src), src)

    def test_short_prose_line_with_punctuation_untouched(self):
        # Minor-3：中文标点计入，叙述行“由…得…。”不得整行进公式
        line = "由 \\Delta=0 得 m=-2。"
        self.assertEqual(error_analyze._wrap_bare_latex(line), line)
        # 但结论行“故m\geq-1”（公式外仅 1 字）仍要包，不然 980 尾部又漏
        self.assertEqual(error_analyze._wrap_bare_latex("故m\\geq-1"),
                         "$$故m\\geq-1$$")

    def test_whitelist_needs_full_command_end(self):
        # Minor-4：\textbackslash 不能被 text 前缀误命中；路径类行不包
        src = "文件名为 \\textbackslash 符号"
        self.assertEqual(error_analyze._wrap_bare_latex(src), src)
        line2 = "路径 C:\\total\\dir 保留"
        self.assertEqual(error_analyze._wrap_bare_latex(line2), line2)

    def test_indent_preserved_on_wrap(self):
        # Minor-5：包裹保留行首/行尾空白，缩进推导结构不砸
        out = error_analyze._wrap_bare_latex("    \\Delta=0 ")
        self.assertEqual(out, "    $$\\Delta=0$$ ")


class TestRunDegradation(unittest.TestCase):
    """后台任务降级链：版面失败仍走 VL（仅原图）；VL 返回不可解析 → error 终态。"""

    def _mk(self):
        tmp = tempfile.mkdtemp()
        abs_p = os.path.join(tmp, "q.png")
        _make_png(abs_p, 64, 64)
        return tmp, abs_p

    def test_layout_fail_then_vl_unparsable(self):
        tmp, abs_p = self._mk()
        reg = error_analyze._registry
        tid = reg.create(user_id="u9")
        with mock.patch.object(error_analyze, "_analyze_one_image",
                               side_effect=RuntimeError("paddle down")), \
             mock.patch("llm_provider_factory.call_llm_vision", return_value="这不是JSON") as vl:
            error_analyze._run(tid, "u9", "看图 ![q](q.png)", [("q.png", abs_p)])
            r = reg.get(tid, user_id="u9")
        self.assertEqual(r["status"], "error")
        self.assertTrue(vl.called)  # 版面失败仍调用了 VL

    def test_done_path(self):
        tmp, abs_p = self._mk()
        reg = error_analyze._registry
        tid = reg.create(user_id="u9")
        good = json.dumps({"stem_md": "整理后题干 ![图形](q_fig0.png)",
                           "user_solution_md": "学生算式", "error_analysis": "错在约分",
                           "correct_answer": "1/2", "explanation": "正解过程"}, ensure_ascii=False)
        fake_info = {"image": "q.png", "page_size": [64, 64],
                     "texts": [{"bbox": [0, 0, 64, 32], "content": "原题"}],
                     "figures": [{"bbox": [0, 32, 64, 64], "crop_rel": "q_fig0.png"}]}
        crop = os.path.join(tmp, "q_fig0.png")
        _make_png(crop, 32, 32)
        with mock.patch.object(error_analyze, "_analyze_one_image", return_value=fake_info), \
             mock.patch("llm_provider_factory.call_llm_vision", return_value=good):
            error_analyze._run(tid, "u9", "原题 ![q](q.png)", [("q.png", abs_p)])
            r = reg.get(tid, user_id="u9")
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["stem_md"], "整理后题干 ![图形](q_fig0.png)")
        self.assertIn("## 我的解答（如实转录）", r["explanation"])
        # done 后 TTL 内可重复读（评审 M5）
        self.assertIsNotNone(reg.get(tid, user_id="u9"))


class TestNormalizeStemImages(unittest.TestCase):
    """用户裁定“图=切片”的确定性保底：VL 引原图时换为切片。"""

    def _pi(self, image, crops=None, err=False):
        if err:
            return {"image": image, "error": "paddle down"}
        return {"image": image, "texts": [],
                "figures": [{"bbox": [0, 0, 1, 1], "crop_rel": c} for c in (crops or [])]}

    def test_original_replaced_by_crop(self):
        stem = "题干文字 ![题目](截图/a.png) 尾"
        pi = [self._pi("截图/a.png", ["截图/a_fig0.png"])]
        out = error_analyze._normalize_stem_images(stem, pi)
        self.assertEqual(out, "题干文字 ![题目](截图/a_fig0.png) 尾")

    def test_already_crop_unchanged(self):
        stem = "题干 ![图](截图/a_fig0.png)"
        pi = [self._pi("截图/a.png", ["截图/a_fig0.png"])]
        self.assertEqual(error_analyze._normalize_stem_images(stem, pi), stem)

    def test_no_crop_keeps_original(self):
        stem = "题干 ![图](截图/a.png)"
        pi = [self._pi("截图/a.png", [])]  # 无切片
        self.assertEqual(error_analyze._normalize_stem_images(stem, pi), stem)

    def test_layout_error_skipped(self):
        stem = "题干 ![图](截图/a.png)"
        pi = [self._pi("截图/a.png", err=True)]
        self.assertEqual(error_analyze._normalize_stem_images(stem, pi), stem)

    def test_multi_crop_uses_first(self):
        stem = "![a](截图/a.png)"
        pi = [self._pi("截图/a.png", ["截图/a_fig0.png", "截图/a_fig1.png"])]
        self.assertEqual(error_analyze._normalize_stem_images(stem, pi), "![a](截图/a_fig0.png)")


class TestStripRemoteImages(unittest.TestCase):
    """评审 Major2：输出侧远程图引用一律剔除，与输入侧拒绝口径一致。"""

    def test_http_stripped(self):
        stem = "题干 ![外](https://evil.com/x.png) ![图](截图/a_fig0.png)"
        self.assertEqual(error_analyze._strip_remote_images(stem),
                         "题干  ![图](截图/a_fig0.png)")

    def test_data_and_ftp_stripped(self):
        stem = "![a](data:image/png;base64,xx)![b](ftp://h/y.png)ok"
        self.assertEqual(error_analyze._strip_remote_images(stem), "ok")

    def test_local_untouched(self):
        stem = "![图](截图/a.png) 普通文字(a.png)"
        self.assertEqual(error_analyze._strip_remote_images(stem), stem)

    def test_empty(self):
        self.assertEqual(error_analyze._strip_remote_images(""), "")


class TestInflightDedup(unittest.TestCase):
    """评审 Major1：同 (用户+草稿+图) 命中运行中任务复用 task_id，杜绝超时重点击双扣分。"""

    def setUp(self):
        error_analyze._inflight.clear()

    def tearDown(self):
        error_analyze._inflight.clear()

    def _start_noop_thread(self):
        return mock.patch.object(error_analyze.threading, "Thread")

    def test_same_content_reuses_running_task(self):
        items = [("截图/a.png", "/abs/a.png")]
        with self._start_noop_thread() as T:
            T.return_value.start = lambda: None
            tid1 = error_analyze.start_analyze("草稿", items, "dedup_u1")
            tid2 = error_analyze.start_analyze("草稿", items, "dedup_u1")
        self.assertEqual(tid1, tid2)

    def test_different_content_or_user_new_task(self):
        items = [("截图/a.png", "/abs/a.png")]
        with self._start_noop_thread() as T:
            T.return_value.start = lambda: None
            tid1 = error_analyze.start_analyze("草稿1", items, "dedup_u1")
            tid2 = error_analyze.start_analyze("草稿2", items, "dedup_u1")  # 草稿不同
            tid3 = error_analyze.start_analyze("草稿1", items, "dedup_u2")  # 用户不同
            tid4 = error_analyze.start_analyze("草稿1", [("截图/b.png", "/abs/b.png")], "dedup_u1")  # 图不同
        self.assertEqual(len({tid1, tid2, tid3, tid4}), 4)

    def test_finished_task_not_reused(self):
        items = [("截图/a.png", "/abs/a.png")]
        with self._start_noop_thread() as T:
            T.return_value.start = lambda: None
            tid1 = error_analyze.start_analyze("草稿", items, "dedup_u1")
            error_analyze._registry.finish(tid1, "done", user_id="dedup_u1")  # 模拟已终态但未及 pop
            tid2 = error_analyze.start_analyze("草稿", items, "dedup_u1")
        self.assertNotEqual(tid1, tid2)

    def test_run_finally_pops_inflight(self):
        key = error_analyze._dedup_key("u", "md", [("a.png", "/x")])
        with mock.patch.object(error_analyze, "_run_inner") as inner:
            error_analyze._run("t1", "u", "md", [("a.png", "/x")], key)
        inner.assert_called_once()
        self.assertNotIn(key, error_analyze._inflight)

    def test_pop_only_own_entry(self):
        # 旧任务收尾时 key 已被新任务占据：不得误删别人的登记
        error_analyze._inflight["k1"] = "other_task"
        with mock.patch.object(error_analyze, "_run_inner"):
            error_analyze._run("t1", "u", "md", [], "k1")
        self.assertEqual(error_analyze._inflight.get("k1"), "other_task")
        error_analyze._inflight.pop("k1", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
