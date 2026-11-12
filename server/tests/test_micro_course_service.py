# -*- coding: utf-8 -*-
"""微课生成服务契约断言（U6 + 二期交互仿真/语音旁白，2026-10-30）。零 DB、零 LLM 调用。

覆盖：
1. 大纲 prompt 材料块拼装/无材料不出现占位块/掌握度哨兵文案
2. 大纲校验：数量边界、页型枚举、quiz 必存在、标题长度、intent 截断；
   interactive 至多 1 页，超出降级 explain（不作废）；
   七期（用户裁定）：每课固定 1 页互动页——LLM 漏排则末尾自动补位且 worthy 强制 false；
   interactive_worthy/interactive_note 顶层透传（非 bool 一律 false，note 截 60 字）
3. 页内容校验：summary 必需字段与超长拒绝；quiz 对象契约 {narration, questions}（断档升级，
   与既有出题同构）；interactive 页 html 非空+长度上限；narration 清洗（剥符号/截断/空才非法）
4. 五期（2026-11-03 重做）：explain/example 分步画布契约 {title, canvas_html, steps[]}，
   逐步清洗不作废（非对象/空口播跳步、caption 补齐截断、步数边界）；prompt 含 mc-step
   舞台协议且不再含四期 has_widget/「500~2000 字」字样；widget 生成链路已退役
5. external_ref_note 外链警告（只警告不置败，w3.org 白名单）
6. outline_brief 目录行格式
7. estimate_credits 数值口径（calls=1+N，五期去 widget 参数；仅预估展示）
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import micro_course as MC  # noqa: E402


def _outline(sections, title="一次讲透「极限」"):
    return {"title": title, "sections": sections}


SECS_OK = [
    {"title": "讲概念", "scene_type": "explain", "intent": "i1"},
    {"title": "随堂检测", "scene_type": "quiz", "intent": "i2"},
    {"title": "小结", "scene_type": "summary", "intent": "i3"},
]


class TestOutlinePrompt(unittest.TestCase):
    def test_material_blocks_present(self):
        p = MC.build_outline_prompt(subject="高数", point_name="极限", core_desc="数列与函数极限",
                                     mastery_view="45/100", notes_material="笔记正文A",
                                     errors_material="错题正文B")
        for needle in ("极限", "高数", "45/100", "笔记正文A", "错题正文B",
                       "教学大纲", "quiz", "至少 1 个 quiz 页",
                       "恰好安排 1 页 interactive", "interactive_worthy", "interactive_note"):
            self.assertIn(needle, p)

    def test_no_material_blocks_omitted(self):
        p = MC.build_outline_prompt(subject="s", point_name="p", core_desc="c",
                                     mastery_view="尚未评估", notes_material="", errors_material="")
        self.assertNotIn("关联笔记原文", p)
        self.assertNotIn("错题记录（", p)
        self.assertIn("尚未评估", p)  # 未评估哨兵直出，不说 0 分

    def test_scene_prompt_carries_position_and_type(self):
        brief = MC.outline_brief(SECS_OK)
        p = MC.build_scene_prompt(subject="高数", course_title="极限微课",
                                  section=SECS_OK[1], point_name="极限", core_desc="c",
                                  outline_brief=brief, notes_material="笔记", errors_material="")
        self.assertIn("页型=quiz", p)
        self.assertIn("1. [explain] 讲概念", p)  # 目录含每页位置
        self.assertIn("极限微课", p)


class TestErrorOutlinePromptSixthPeriod(unittest.TestCase):
    """六期：错题深度讲解大纲 prompt——四线索硬性结构写死、素材块注入、
    输出契约与知识点课一致（validate_outline 直接复用不另写）。"""

    def _p(self):
        return MC.build_error_outline_prompt(subject="高数", point_name="极限",
                                             core_desc="数列与函数极限", mastery_view="45/100",
                                             error_material="【题目】lim sinx/x\n【你的作答】D")

    def test_required_clues_present(self):
        p = self._p()
        for needle in ("错题深度讲解", "教学大纲", "极限", "高数", "45/100",
                       "【题目】lim sinx/x", "【你的作答】D",   # 错题全貌素材块
                       "考哪些知识点", "你的作答与正确答案", "变式题", "灵魂",
                       "4~6 页", "恰好 1 页 interactive", "至多 1 页 example",
                       "interactive_worthy", "interactive_note"):
            self.assertIn(needle, p)

    def test_contract_reuses_validate_outline(self):
        # 与知识点课同一校验器：合规 3 页错题大纲直接过（七期：无互动页自动补 1 页占位），
        # 少于 MIN_SECTIONS 拒绝
        ok = {"title": "错题讲解课", "sections": [
            {"title": "考什么", "scene_type": "explain", "intent": "i1"},
            {"title": "错在哪", "scene_type": "explain", "intent": "i2"},
            {"title": "变式自测", "scene_type": "quiz", "intent": "i3"}]}
        out = MC.validate_outline(dict(ok))
        self.assertEqual(len(out["sections"]), 4)  # 七期：末尾补位互动页
        self.assertEqual(out["sections"][-1]["scene_type"], "interactive")
        with self.assertRaises(ValueError):
            MC.validate_outline({"title": "t", "sections": [
                {"title": "a", "scene_type": "explain", "intent": "i"}] * 2})

    def test_no_kp_branch(self):
        # 六期用户裁定补丁：point_name 空串即独立错题形态——不引用知识点/掌握度，
        # 线索①改为从题干归纳；「教学大纲」分流判别词仍必须在场
        p = MC.build_error_outline_prompt(subject="高数", point_name="", core_desc="",
                                          mastery_view="尚未评估",
                                          error_material="【题目】lim sinx/x\n【你的作答】D")
        for needle in ("教学大纲", "错题深度讲解", "尚未关联知识点", "归纳", "无掌握度数据",
                       "【题目】lim sinx/x", "变式题", "灵魂"):
            self.assertIn(needle, p)
        self.assertNotIn("尚未评估", p)  # 掌握度哨兵不得泄漏进无锚分支
        self.assertNotIn("「极限」", p)


class TestValidateOutline(unittest.TestCase):
    def test_ok(self):
        out = MC.validate_outline(_outline([dict(s) for s in SECS_OK]))
        # 七期：SECS_OK 无互动页 → 末尾自动补 1 页占位，worthy 保守 false
        self.assertEqual(len(out["sections"]), 4)
        self.assertEqual(out["sections"][-1]["scene_type"], "interactive")
        self.assertIs(out["interactive_worthy"], False)
        self.assertEqual(out["title"], "一次讲透「极限」")

    def test_interactive_one_page_kept(self):
        secs = [{"title": "a", "scene_type": "explain", "intent": "i"},
                {"title": "b", "scene_type": "interactive", "intent": "i"},
                {"title": "c", "scene_type": "quiz", "intent": "i"},
                {"title": "d", "scene_type": "summary", "intent": "i"}]
        out = MC.validate_outline(_outline(secs))
        self.assertEqual(out["sections"][1]["scene_type"], "interactive")
        self.assertEqual(len(out["sections"]), 4)  # 七期：已有互动页不重复补位

    def test_worthy_note_passthrough_and_sanitize(self):
        # 七期：顶层 interactive_worthy 仅认 bool true（字符串/其它值一律 false），note 截 60 字
        secs = [{"title": "a", "scene_type": "interactive", "intent": "i"},
                {"title": "b", "scene_type": "quiz", "intent": "i"},
                {"title": "c", "scene_type": "summary", "intent": "i"}]
        out = MC.validate_outline({"title": "t", "sections": secs,
                                   "interactive_worthy": True, "interactive_note": "适" * 100})
        self.assertIs(out["interactive_worthy"], True)
        self.assertEqual(len(out["interactive_note"]), 60)
        out2 = MC.validate_outline({"title": "t", "sections": secs,
                                    "interactive_worthy": "true"})
        self.assertIs(out2["interactive_worthy"], False)  # 非 bool 不当真

    def test_missing_interactive_autopend_not_counted_in_max(self):
        # 七期：LLM 满 8 页仍漏互动页 → 照样末尾补位（补位页不参与 MAX 复核），
        # 且违约时其 worthy 判断不可信 → 强制 false 走手动按钮（防误烧积分）
        secs = [{"title": "q", "scene_type": "quiz", "intent": "i"}] + \
               [{"title": "e", "scene_type": "explain", "intent": "i"}] * (MC.MAX_SECTIONS - 1)
        out = MC.validate_outline({"title": "t", "sections": secs, "interactive_worthy": True})
        self.assertEqual(len(out["sections"]), MC.MAX_SECTIONS + 1)
        self.assertEqual(out["sections"][-1]["scene_type"], "interactive")
        self.assertIs(out["interactive_worthy"], False)
        self.assertIn("手动生成", out["interactive_note"])

    def test_interactive_over_limit_downgraded_not_rejected(self):
        # 二期：interactive 超 1 页 → 多余页降级 explain，整单不作废（不浪费已扣大纲分）
        secs = [{"title": "a", "scene_type": "interactive", "intent": "i1"},
                {"title": "b", "scene_type": "interactive", "intent": ""},
                {"title": "c", "scene_type": "quiz", "intent": "i"},
                {"title": "d", "scene_type": "summary", "intent": "i"}]
        out = MC.validate_outline(_outline(secs))
        types = [s["scene_type"] for s in out["sections"]]
        self.assertEqual(types, ["interactive", "explain", "quiz", "summary"])
        self.assertEqual(out["sections"][1]["intent"], "补充讲解")  # 空 intent 补哨兵

    def test_requires_at_least_one_quiz(self):
        secs = [{"title": "a", "scene_type": "explain", "intent": "i"},
                {"title": "b", "scene_type": "example", "intent": "i"},
                {"title": "c", "scene_type": "summary", "intent": "i"}]
        with self.assertRaises(ValueError):
            MC.validate_outline(_outline(secs))

    def test_section_count_bounds(self):
        with self.assertRaises(ValueError):  # 少于 MIN_SECTIONS=3
            MC.validate_outline(_outline(SECS_OK[:2]))
        many = [{"title": "随堂", "scene_type": "quiz", "intent": "i"}] * (MC.MAX_SECTIONS + 1)
        with self.assertRaises(ValueError):  # 超过 MAX_SECTIONS=8
            MC.validate_outline(_outline(many))

    def test_bad_scene_type_rejected(self):
        secs = [{"title": "a", "scene_type": "game", "intent": "i"},
                {"title": "b", "scene_type": "quiz", "intent": "i"},
                {"title": "c", "scene_type": "summary", "intent": "i"}]
        with self.assertRaises(ValueError):
            MC.validate_outline(_outline(secs))

    def test_overlong_section_title_rejected(self):
        secs = [{"title": "长" * (MC.MAX_TITLE_LEN + 1), "scene_type": "explain", "intent": "i"},
                {"title": "b", "scene_type": "quiz", "intent": "i"},
                {"title": "c", "scene_type": "summary", "intent": "i"}]
        with self.assertRaises(ValueError):
            MC.validate_outline(_outline(secs))

    def test_non_dict_obj_rejected(self):
        for bad in (None, [], "x"):
            with self.assertRaises(ValueError):
                MC.validate_outline(bad)


def _q_single():
    return {"type": "single", "question": "lim x→0 sinx/x = ?",
            "options": ["0", "1", "2", "不存在"], "correct_answer": "B",
            "difficulty": "容易", "explanation": "重要极限"}


def _q_judge():
    return {"type": "judge", "question": "收敛数列必收敛于唯一极限",
            "correct_answer": "对", "difficulty": "中等", "explanation": "唯一性定理"}


class TestValidateSceneContent(unittest.TestCase):
    def test_summary_missing_body_rejected(self):
        # 五期：body_md 超长/缺失断言改挂 summary（explain/example 已转画布契约）
        with self.assertRaises(ValueError):
            MC.validate_scene_content("summary", json.dumps({"title": "t", "narration": "讲稿"}))
        big = json.dumps({"title": "t", "body_md": "字" * (MC.MAX_BODY_LEN + 1),
                          "narration": "讲稿"}, ensure_ascii=False)
        with self.assertRaises(ValueError):
            MC.validate_scene_content("summary", big)

    def test_summary_ok(self):
        raw = json.dumps({"title": "小结", "body_md": "课后建议",
                          "narration": "我们来回顾一下"}, ensure_ascii=False)
        out = MC.validate_scene_content("summary", raw)
        self.assertEqual(out["body_md"], "课后建议")
        self.assertTrue(out["narration"])

    def test_quiz_contract_object(self):
        raw = json.dumps({"narration": "接下来做两道小题检验一下", "questions": [_q_single(), _q_judge()]},
                         ensure_ascii=False)
        out = MC.validate_scene_content("quiz", raw)
        self.assertEqual(len(out["questions"]), MC.QUIZ_COUNT)
        self.assertEqual(out["questions"][0]["correct_answer"], "B")
        self.assertIn(out["questions"][1]["correct_answer"], ("正确", "错误"))  # judge 归一
        self.assertTrue(out["narration"])

    def test_quiz_wrong_count_rejected(self):
        raw = json.dumps({"narration": "讲稿", "questions": [_q_single()]}, ensure_ascii=False)
        with self.assertRaises(ValueError):
            MC.validate_scene_content("quiz", raw)

    def test_quiz_bad_options_rejected(self):
        q = _q_single()
        q["options"] = ["A1", "B2"]
        raw = json.dumps({"narration": "讲稿", "questions": [q, _q_judge()]}, ensure_ascii=False)
        with self.assertRaises(ValueError):
            MC.validate_scene_content("quiz", raw)

    def test_quiz_garbage_rejected(self):
        with self.assertRaises(Exception):
            MC.validate_scene_content("quiz", "抱歉我无法生成")

    def test_quiz_bare_array_rejected(self):
        # 断档升级：旧纯数组形态不再接受（不留兼容分支）
        with self.assertRaises(Exception):
            MC.validate_scene_content("quiz", json.dumps([_q_single(), _q_judge()], ensure_ascii=False))

    # ---- 二期：页级 narration 清洗（可修复瑕疵不作废；五期：画布页无页级 narration，用 summary 验）----
    def test_narration_symbol_cleaned_not_rejected(self):
        raw = json.dumps({"title": "t", "body_md": "正文",
                          "narration": "公式 $a^2$ 与 $|x|$ 还有 \alpha 符号，读出来要干净"},
                         ensure_ascii=False)
        out = MC.validate_scene_content("summary", raw)
        for ch in "$`\\|":
            self.assertNotIn(ch, out["narration"])
        self.assertIn("读出来要干净", out["narration"])

    def test_narration_missing_or_symbol_only_rejected(self):
        for bad_n in ("", "   ", "$`\\|"):
            raw = json.dumps({"title": "t", "body_md": "正文", "narration": bad_n},
                             ensure_ascii=False)
            with self.assertRaises(ValueError):
                MC.validate_scene_content("summary", raw)
        raw2 = json.dumps({"title": "t", "body_md": "正文"})
        with self.assertRaises(ValueError):
            MC.validate_scene_content("summary", raw2)

    def test_narration_truncated_to_max(self):
        raw = json.dumps({"title": "t", "body_md": "正文",
                          "narration": "字" * (MC.NARRATION_MAX + 100)}, ensure_ascii=False)
        out = MC.validate_scene_content("summary", raw)
        self.assertEqual(len(out["narration"]), MC.NARRATION_MAX)

    # ---- 二期：interactive 页契约 ----
    def test_interactive_ok(self):
        html = "<!DOCTYPE html><html><body><canvas></canvas><script>let a=1;</script></body></html>"
        raw = json.dumps({"title": "实3", "html": html, "narration": "拖动滑杆观察变化"},
                         ensure_ascii=False)
        out = MC.validate_scene_content("interactive", raw)
        self.assertEqual(out["html"], html)
        self.assertEqual(out["narration"], "拖动滑杆观察变化")

    def test_interactive_missing_or_overlong_html_rejected(self):
        with self.assertRaises(ValueError):
            MC.validate_scene_content("interactive",
                                      json.dumps({"title": "t", "narration": "讲稿"}))
        big = json.dumps({"title": "t", "html": "<p>" + "x" * (MC.MAX_HTML_LEN + 10),
                          "narration": "讲稿"}, ensure_ascii=False)
        with self.assertRaises(ValueError):
            MC.validate_scene_content("interactive", big)

    # ---- 二期：外链警告只警告不置败 ----
    def test_external_ref_note(self):
        clean = '<svg xmlns="http://www.w3.org/2000/svg"></svg><script>// 注释 http://x</script>'
        self.assertIsNone(MC.external_ref_note(clean))
        self.assertIsNone(MC.external_ref_note("<div>纯内联</div>"))
        bad = '<link href="https://cdn.foo.com/x.css"><img src="//img.cdn/a.png">'
        note = MC.external_ref_note(bad)
        self.assertTrue(note and "cdn.foo.com" in note and "img.cdn" in note)

    # ---- 实弹轮 2026-11-12：产物内联 JS 语法闸（实验台 `4++` SyntaxError 空白页事故）----
    # 坏产物原文取样自 2762:lab 入库产物尾部（真实 LLM 输出，非构造）
    _BAD_JS_HTML = ("<!DOCTYPE html><html><body><canvas></canvas>"
                    "<script>var W={value:'2'},B={value:'1'};"
                    "function d(){var p=(+W.value*4++B.value);}</script></body></html>")

    def test_js_gate_rejects_bad_interactive(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("语法闸依赖 node --check，本机无 node 时降级不拦")
        raw = json.dumps({"title": "t", "html": self._BAD_JS_HTML, "narration": "讲稿"},
                         ensure_ascii=False)
        with self.assertRaises(ValueError) as cm:
            MC.validate_scene_content("interactive", raw)
        self.assertIn("语法错误", str(cm.exception))

    def test_js_gate_rejects_bad_canvas_explain(self):
        import shutil
        if not shutil.which("node"):
            self.skipTest("语法闸依赖 node --check")
        steps = [{"caption": f"c{i}", "narration": "句子" * 5} for i in range(3)]
        raw = json.dumps({"title": "t", "canvas_html": self._BAD_JS_HTML, "steps": steps},
                         ensure_ascii=False)
        with self.assertRaises(ValueError):
            MC.validate_scene_content("explain", raw)

    def test_js_gate_passes_good_and_empty_script(self):
        good = ("<!DOCTYPE html><script>function f(a){return a+1;} f(1);</script>"
                "<script></script>")
        MC._html_js_syntax_check(good)          # 不抛即通过（空块无语法可查）

    def test_js_gate_degrades_without_node(self):
        orig = MC.subprocess.run
        try:
            def _boom(*a, **k):
                raise FileNotFoundError("node")
            MC.subprocess.run = _boom
            MC._html_js_syntax_check("<script>var a = (;</script>")  # 降级不拦，不抛
        finally:
            MC.subprocess.run = orig

    def test_js_blocks_skips_src_module_json(self):
        html = ('<script src="a.js"></script>'
                '<script type="module">import x from "y";</script>'
                '<script type="application/json">{"a": (;</script>'
                "<script>var ok=1;</script>")
        blocks = list(MC._js_blocks(html))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0], (0, "var ok=1;"))

    def test_unknown_scene_type_rejected(self):
        with self.assertRaises(ValueError):
            MC.validate_scene_content("dialogue", json.dumps({"title": "t"}))


class TestMisc(unittest.TestCase):
    def test_outline_brief_format(self):
        brief = MC.outline_brief(SECS_OK)
        self.assertEqual(brief.splitlines()[1], "2. [quiz] 随堂检测")

    def test_frontend_sandbox_contract(self):
        # 二期评审 Major-8：仿真 iframe 沙箱是唯一安全边界，静态钉死——
        # sandbox 仅 allow-scripts，pm_pages.js 全文不得出现 allow-same-origin
        # （srcdoc+allow-scripts+allow-same-origin=放弃沙箱）
        js = (Path(__file__).resolve().parents[1] / "static" / "js" / "pm_pages.js").read_text(encoding="utf-8")
        # 只看真实 sandbox 属性值（注释里允许出现反例说明字样）
        vals = re.findall(r'sandbox=\\?"([^"\\]+)', js)
        self.assertTrue(vals, "未找到仿真 iframe 的 sandbox 属性")
        self.assertTrue(all(v == "allow-scripts" for v in vals), f"sandbox 必须仅 allow-scripts：{vals}")
        # quiz 断档升级：前端只认对象形态，不留旧数组分支
        self.assertIn("(s.content || {}).questions || []", js)
        self.assertNotIn("var qs = s.content || [];", js)

    def test_quiz_prompt_object_contract(self):
        # 防漂移（评审 Major-1）：quiz prompt 必须要求对象且不得再要求纯数组
        secs = [{"title": "a", "scene_type": "quiz", "intent": "i"},
                {"title": "b", "scene_type": "explain", "intent": "i"},
                {"title": "c", "scene_type": "summary", "intent": "i"}]
        p = MC.build_scene_prompt(subject="s", course_title="c", section=secs[0],
                                  point_name="p", core_desc="", outline_brief=MC.outline_brief(secs),
                                  notes_material="", errors_material="")
        self.assertIn('"narration"', p)
        self.assertNotIn("只返回 JSON 数组", p)

    def test_estimate_credits_positive_and_scales(self):
        e3, e6 = MC.estimate_credits(3), MC.estimate_credits(6)
        self.assertGreater(e6, 0)
        self.assertGreater(e6, e3)

    def test_scene_types_constant_intact(self):
        self.assertEqual(MC.SCENE_TYPES,
                         ("explain", "example", "quiz", "summary", "interactive"))

    def test_scene_prompt_interactive_rules(self):
        # 二期：interactive prompt 含硬要求；所有页型含 narration 规则
        brief = MC.outline_brief(SECS_OK)
        p = MC.build_scene_prompt(subject="s", course_title="c", section={"title": "t", "scene_type": "interactive", "intent": "i"},
                                  point_name="p", core_desc="", outline_brief=brief,
                                  notes_material="", errors_material="")
        self.assertIn("页型=interactive", p)
        self.assertIn("narration", p)
        self.assertIn("www.w3.org", p)  # xmlns 白名单告知，防误删
        self.assertIn("朗读讲稿", p)


def _canvas_steps(n=5, canvas="<!DOCTYPE html><html></html>"):
    return {"title": "分步讲解", "canvas_html": canvas,
            "steps": [{"caption": f"字幕{i}", "narration": f"第{i}步口播讲解"} for i in range(n)]}


class TestCanvasStepsFifthPeriod(unittest.TestCase):
    """五期：explain/example 分步画布契约（声画同源：第 i 步 narration 驱动舞台第 i 个视觉态）。
    可修复瑕疵逐步清洗不作废；canvas 缺失/超长与步数不足非法（同 interactive 置败口径）。"""

    def test_explain_canvas_steps_ok(self):
        out = MC.validate_scene_content("explain", json.dumps(_canvas_steps(), ensure_ascii=False))
        self.assertEqual(out["title"], "分步讲解")
        self.assertEqual(out["canvas_html"], "<!DOCTYPE html><html></html>")
        self.assertEqual(out["steps"][0], {"caption": "字幕0", "narration": "第0步口播讲解"})
        self.assertNotIn("body_md", out)      # 旧文字块契约已退役
        self.assertNotIn("narration", out)    # 页级 narration 不再存在（只剩步内）

    def test_example_same_contract(self):
        out = MC.validate_scene_content("example", json.dumps(_canvas_steps(MC.MIN_STEPS), ensure_ascii=False))
        self.assertEqual(len(out["steps"]), MC.MIN_STEPS)
        self.assertIn("canvas_html", out)
        self.assertNotIn("problem_md", out)   # 旧题干/解答分区废除，题干并入舞台第 0 步

    def test_missing_or_overlong_canvas_rejected(self):
        for bad in ("", "   ", "x" * (MC.MAX_HTML_LEN + 1)):
            o = _canvas_steps()
            o["canvas_html"] = bad
            with self.assertRaises(ValueError):
                MC.validate_scene_content("explain", json.dumps(o, ensure_ascii=False))

    def test_steps_not_array_or_too_few_rejected(self):
        o = _canvas_steps()
        o["steps"] = "不是数组"
        with self.assertRaises(ValueError):
            MC.validate_scene_content("explain", json.dumps(o, ensure_ascii=False))
        # 非对象步/空口播步被跳过后不足 MIN_STEPS → 非法
        o["steps"] = ["垃圾", {"caption": "c", "narration": "  $`\\|  "}, _canvas_steps()["steps"][0]]
        with self.assertRaises(ValueError):
            MC.validate_scene_content("explain", json.dumps(o, ensure_ascii=False))

    def test_dirty_steps_cleaned_not_voided(self):
        o = _canvas_steps(4)
        o["steps"].insert(0, "非对象步")
        o["steps"].insert(1, {"caption": "空口播被跳", "narration": "   "})
        o["steps"].append({"caption": "", "narration": "空字幕补哨兵"})
        o["steps"].append({"caption": "长" * (MC.MAX_CAPTION_LEN + 30),
                           "narration": "字" * (MC.STEP_NARR_MAX + 100)})
        out = MC.validate_scene_content("explain", json.dumps(o, ensure_ascii=False))
        self.assertEqual(len(out["steps"]), 6)  # 4 有效 + 2 补齐，脏步骤跳过不作废
        self.assertEqual(out["steps"][4]["caption"], "第 5 步")  # 空字幕补齐（按当前序号）
        self.assertEqual(len(out["steps"][5]["caption"]), MC.MAX_CAPTION_LEN)
        self.assertEqual(len(out["steps"][5]["narration"]), MC.STEP_NARR_MAX)
        # 步内 narration 同走剥符号清洗
        self.assertNotIn("$", out["steps"][0]["narration"])

    def test_steps_over_max_truncated(self):
        out = MC.validate_scene_content(
            "explain", json.dumps(_canvas_steps(MC.MAX_STEPS + 3), ensure_ascii=False))
        self.assertEqual(len(out["steps"]), MC.MAX_STEPS)  # 超出截断不作废（二期宽容纪律）


class TestCanvasDomRefGate(unittest.TestCase):
    """2026-11-10 实弹：qwen36 生成的原理动画首帧即崩
    （getElementById('r'+(i||'')) 拼出悬空 id → null.classList TypeError）。
    闸门口径：canvas_html 里 getElementById 只允许纯字面量且 id 已声明（带/不带
    引号属性都算声明）；拼接/变量形态取 id 直接拒（无法静态验证 = 崩溃高发区）；
    querySelector('#id') 同检，类选择器不误杀。"""

    def _canvas(self, body_html, js):
        return ("<!DOCTYPE html><html><body>" + body_html +
                "<script>" + js + "</script></body></html>")

    def test_dynamic_concat_lookup_rejected(self):
        # 今晚真实崩型：'r'+(i||'') 拼出 'r' 悬空 id
        canvas = self._canvas('<div id="r1"></div><div id="r2"></div>',
                              "for(var i=0;i<5;i++){document.getElementById('r'+(i||''))."
                              "classList.remove('active');}")
        o = _canvas_steps(canvas=canvas)
        with self.assertRaises(ValueError):
            MC.validate_scene_content("explain", json.dumps(o, ensure_ascii=False))

    def test_literal_ghost_id_rejected(self):
        canvas = self._canvas('<div id="real"></div>',
                              "document.getElementById('ghost').classList.add('x');")
        o = _canvas_steps(canvas=canvas)
        with self.assertRaises(ValueError) as cm:
            MC.validate_scene_content("explain", json.dumps(o, ensure_ascii=False))
        self.assertIn("ghost", str(cm.exception))

    def test_variable_id_rejected(self):
        canvas = self._canvas('<div id="a1"></div>',
                              "var k='a1';document.getElementById(k).classList.add('x');")
        o = _canvas_steps(canvas=canvas)
        with self.assertRaises(ValueError):
            MC.validate_scene_content("explain", json.dumps(o, ensure_ascii=False))

    def test_unquoted_id_declared_passes(self):
        # 今晚产物里 id=valBox 不带引号是合法声明，不得误杀
        canvas = self._canvas('<div class=val-box id=valBox>v1</div>',
                              "document.getElementById('valBox').textContent='v2';")
        out = MC.validate_scene_content(
            "explain", json.dumps(_canvas_steps(canvas=canvas), ensure_ascii=False))
        self.assertIn("valBox", out["canvas_html"])

    def test_query_selector_id_and_class_ok(self):
        canvas = self._canvas('<div id="cap1" class="op"></div>',
                              "document.querySelector('#cap1').classList.add('active');"
                              "document.querySelectorAll('.op').forEach(function(e){});")
        MC.validate_scene_content(
            "explain", json.dumps(_canvas_steps(canvas=canvas), ensure_ascii=False))

    def test_query_selector_ghost_id_rejected(self):
        canvas = self._canvas('<div id="here"></div>',
                              "document.querySelector('#there').style.display='none';")
        o = _canvas_steps(canvas=canvas)
        with self.assertRaises(ValueError) as cm:
            MC.validate_scene_content("explain", json.dumps(o, ensure_ascii=False))
        self.assertIn("there", str(cm.exception))

    def test_query_selector_concat_rejected(self):
        # 评审 Minor-2 补齐漏杀：'#c'+i 拼接选择器同会 null 崩，与 getElementById 对称
        canvas = self._canvas('<div id="c1"></div>',
                              "document.querySelector('#c'+i).classList.add('x');")
        o = _canvas_steps(canvas=canvas)
        with self.assertRaises(ValueError) as cm:
            MC.validate_scene_content("explain", json.dumps(o, ensure_ascii=False))
        self.assertIn("拼接/变量取 id", str(cm.exception))

    def test_query_selector_complex_and_class_not_killed(self):
        # 复杂选择器/类选择器一律不参与判定（静态判不准 ≠ 非法，不得误杀付费页）
        canvas = self._canvas('<div id="wrap"><p class="ln">x</p></div>',
                              "document.querySelector('#wrap .ln').style.color='red';"
                              "document.querySelectorAll('.ln').forEach(function(e){});"
                              "document.querySelector('div > p').textContent='y';")
        MC.validate_scene_content(
            "explain", json.dumps(_canvas_steps(canvas=canvas), ensure_ascii=False))


class TestFifthPeriodPrompts(unittest.TestCase):
    """五期 prompt 防漂移：画布页含 mc-step 舞台协议；四期字样（has_widget/500~2000 字/
    旧 body_md・problem_md 契约）不得残留；页级朗读规则只注入非画布页。"""

    def _sp(self, st):
        return MC.build_scene_prompt(subject="s", course_title="c",
                                     section={"title": "t", "scene_type": st, "intent": "i"},
                                     point_name="p", core_desc="", outline_brief="x",
                                     notes_material="", errors_material="")

    def test_canvas_prompts_carry_step_stage_protocol(self):
        for st in ("explain", "example"):
            p = self._sp(st)
            self.assertIn("mc-step", p)
            self.assertIn(MC._STEP_STAGE_RULES, p)
            self.assertIn(MC._HTML_HARD_RULES_CORE, p)  # 与实验页同源硬性规则
            self.assertIn("canvas_html", p)
            self.assertNotIn("500~2000 字", p)
            self.assertNotIn("body_md", p)
            self.assertNotIn("problem_md", p)
            self.assertNotIn("has_widget", p)

    def test_page_narration_rule_only_non_canvas_pages(self):
        for st, expect in (("explain", False), ("example", False),
                           ("quiz", True), ("summary", True), ("interactive", True)):
            self.assertEqual("朗读讲稿（narration 字段）要求" in self._sp(st), expect, st)

    def test_outline_prompt_widget_rule_retired(self):
        p = MC.build_outline_prompt(subject="s", point_name="p", core_desc="c",
                                    mastery_view="1", notes_material="", errors_material="")
        self.assertNotIn("has_widget", p)

    def test_outline_legacy_widget_field_dropped_not_rejected(self):
        # 存量课 regenerate 重读旧大纲：残留 has_widget 静默丢弃，不再消费也不报错
        secs = [{"title": "a", "scene_type": "explain", "intent": "i", "has_widget": True},
                {"title": "b", "scene_type": "quiz", "intent": "i"},
                {"title": "c", "scene_type": "summary", "intent": "i"}]
        out = MC.validate_outline(_outline(secs))
        self.assertNotIn("has_widget", out["sections"][0])

    def test_widget_pipeline_deleted(self):
        import inspect
        self.assertEqual(list(inspect.signature(MC.estimate_credits).parameters), ["page_count"])
        for gone in ("build_widget_prompt", "validate_widget_html"):
            self.assertFalse(hasattr(MC, gone), f"四期 A2 链路未退役：{gone}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
