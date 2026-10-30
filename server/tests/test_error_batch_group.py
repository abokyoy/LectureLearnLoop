# -*- coding: utf-8 -*-
"""「切片图一次全给大模型，返回一组题」专项断言（2026-10-15 用户裁定，离线零外呼）。

覆盖：
1. extract_json_array：裸数组/围栏/前后杂质/尾逗号修复/不可解析抛错
2. error_analyze.recognize_group：一次 VL 调用识别全组（调用次数=1 为核心断言）、
   q 号乱序重绑定、缺题元素标失败不抛错、数组不可解析整组抛错、版面失败题降级仅发裁片、
   题干引用原裁片被规范化替换为切片、附图数量=裁片+切片
3. error_batch._run 分组编排：4 框分 2 组（≤3/组）各一次调用；组内单题失败仅该题回退；
   整组抛异常全组逐题回退；全组成功时零逐题调用
"""
from __future__ import annotations

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

from services import error_analyze, error_batch  # noqa: E402


def _make_png(path, w=100, h=80):
    Image.new("RGB", (w, h), "white").save(path)


def _q_obj(q, tag):
    return {"q": q, "stem_md": f"第{tag}题 $1+1$", "user_solution_md": "",
            "error_analysis": "计算错", "correct_answer": "2", "explanation": "加法"}


def _layout(rel):
    return {"image": rel, "page_size": [100, 80],
            "texts": [{"bbox": [0, 0, 50, 20], "content": "计算 1+1"}], "figures": []}


def _wait_done(read, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        r = read()
        if r and r.get("status") != "running":
            return r
        time.sleep(0.05)
    raise AssertionError("任务未在时限内进入终态")


class TestExtractJsonArray(unittest.TestCase):
    def test_plain_fence_noise_trailing_comma(self):
        payload = json.dumps([_q_obj(1, "一"), _q_obj(2, "二")], ensure_ascii=False)
        self.assertEqual(len(error_analyze.extract_json_array(payload)), 2)
        self.assertEqual(len(error_analyze.extract_json_array("```json\n" + payload + "\n```")), 2)
        self.assertEqual(len(error_analyze.extract_json_array("整理结果如下：" + payload + " 以上。")), 2)
        self.assertEqual(len(error_analyze.extract_json_array('[{"a": 1,}, {"a": 2,}]')), 2)  # 尾逗号修复

    def test_unparseable_raises(self):
        with self.assertRaises(ValueError):
            error_analyze.extract_json_array("完全不是数组")
        with self.assertRaises(ValueError):
            error_analyze.extract_json_array('{"q": 1}')  # 顶层对象不是数组（单题契约）→ 组解析失败


class TestRecognizeGroup(unittest.TestCase):
    """recognize_group：mock 版面 + mock VL，核心断言「一组题只调用一次 VL」。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p1 = os.path.join(self.tmp, "截图_q1_x.png")
        self.p2 = os.path.join(self.tmp, "截图_q2_x.png")
        _make_png(self.p1)
        _make_png(self.p2)
        self.items = [("截图/截图_q1_x.png", self.p1), ("截图/截图_q2_x.png", self.p2)]

    def _run_group(self, vl_ret, layout_side=None):
        la = layout_side or (lambda rel, abs_p, dl: _layout(rel))
        calls = []

        def spy_vl(uid, prompt, images, context="", scene="x"):
            calls.append((uid, prompt, images, scene))
            if isinstance(vl_ret, Exception):
                raise vl_ret
            return vl_ret
        with mock.patch.object(error_analyze, "_analyze_one_image", side_effect=la), \
             mock.patch("llm_provider_factory.call_llm_vision", side_effect=spy_vl):
            outs = error_analyze.recognize_group("u1", self.items, time.time() + 60)
        return outs, calls

    def test_one_call_for_whole_group(self):
        ret = json.dumps([_q_obj(1, "一"), _q_obj(2, "二")], ensure_ascii=False)
        outs, calls = self._run_group(ret)
        self.assertEqual(len(calls), 1)  # 全组一次 VL 调用（用户裁定核心）
        self.assertEqual(calls[0][3], "批量识别错题")
        self.assertEqual(len(calls[0][2]), 2)  # 附图=两张裁片
        self.assertIn("【第1题】", calls[0][1])
        self.assertIn("【第2题】", calls[0][1])
        self.assertIn("JSON 数组", calls[0][1])
        self.assertTrue(outs[0]["ok"] and outs[1]["ok"])
        self.assertIn("一", outs[0]["stem_md"])  # 逐题不错位
        self.assertIn("二", outs[1]["stem_md"])

    def test_q_number_rebinds_out_of_order(self):
        ret = json.dumps([_q_obj(2, "二"), _q_obj(1, "一")], ensure_ascii=False)
        outs, _ = self._run_group(ret)
        self.assertIn("一", outs[0]["stem_md"])  # q 号乱序 → 按 q 归位
        self.assertIn("二", outs[1]["stem_md"])

    def test_missing_question_marked_not_raise(self):
        ret = json.dumps([_q_obj(1, "一")], ensure_ascii=False)  # 只回 1 个元素（截断场景）
        outs, _ = self._run_group(ret)
        self.assertTrue(outs[0]["ok"])
        self.assertFalse(outs[1]["ok"])
        self.assertIn("缺少对应题目", outs[1]["error"])

    def test_q_duplicate_extra_elements_no_crossbind(self):
        # CodeReview Major-1 场景：回 3 个元素含重复 q → 重复声明丢弃，绝不把「一」塞进题 2
        arr = [_q_obj(1, "一"), _q_obj(1, "一再"), _q_obj(2, "二")]
        outs, _ = self._run_group(json.dumps(arr, ensure_ascii=False))
        self.assertIn("一", outs[0]["stem_md"])
        self.assertNotIn("一再", outs[0]["stem_md"])
        self.assertTrue(outs[1]["ok"])
        self.assertIn("二", outs[1]["stem_md"])

    def test_q_missing_first_not_positional_crossbind(self):
        # 漏首题只回 q2 → q 落自己声明的槽，题 1 落缺走回退（不得把「二」按位塞给题 1）
        outs, _ = self._run_group(json.dumps([_q_obj(2, "二")], ensure_ascii=False))
        self.assertFalse(outs[0]["ok"])
        self.assertIn("缺少对应题目", outs[0]["error"])
        self.assertTrue(outs[1]["ok"])
        self.assertIn("二", outs[1]["stem_md"])

    def test_q_zero_based_shift_trusted_to_positional(self):
        # 0 起编号（非全集）→ 不采信 q：e0 按位归题 1，e1 声明 q1 与已占槽冲突丢弃走回退
        arr = [{"q": 0, "stem_md": "第零题", "user_solution_md": "", "error_analysis": "",
                "correct_answer": "1", "explanation": "e"}, _q_obj(1, "一")]
        outs, _ = self._run_group(json.dumps(arr, ensure_ascii=False))
        self.assertTrue(outs[0]["ok"])
        self.assertIn("零", outs[0]["stem_md"])  # 不整排位移
        self.assertFalse(outs[1]["ok"])  # 宁可缺题回退，不拿错内容冒充成功

    def test_unparseable_raises_whole_group(self):
        with self.assertRaises(ValueError):
            self._run_group("这不是 JSON 数组")

    def test_group_call_exception_propagates(self):
        # 整组调用异常向上抛（由 error_batch 决定逐题回退），这里不吞
        with self.assertRaises(RuntimeError):
            self._run_group(RuntimeError("视觉模型 API调用失败: HTTP 500"))

    def test_layout_failure_still_recognized(self):
        def la(rel, abs_p, dl):
            if "q1" in rel:
                raise RuntimeError("版面分析超时")
            return _layout(rel)
        ret = json.dumps([{"stem_md": "第一题", "correct_answer": "a", "explanation": "x",
                           "user_solution_md": "", "error_analysis": ""},
                          _q_obj(2, "二")], ensure_ascii=False)
        outs, calls = self._run_group(ret, layout_side=la)
        self.assertTrue(outs[0]["ok"])  # 版面失败降级：仍凭裁片识别成功
        self.assertIn("版面分析失败", calls[0][1])

    def test_stem_image_normalized_to_fig_crop(self):
        # 题干引用原裁片且该题有图形切片 → 确定性替换为切片路径（沿用单题保底机制）
        fig_rel = "截图/截图_q1_x_fig0.png"
        fig_abs = os.path.join(self.tmp, os.path.basename(fig_rel))
        _make_png(fig_abs, 30, 30)

        def la(rel, abs_p, dl):
            info = _layout(rel)
            if "q1" in rel:
                info["figures"] = [{"bbox": [10, 10, 40, 40], "crop_rel": fig_rel}]
            return info
        arr = [_q_obj(1, "一"), _q_obj(2, "二")]
        arr[0]["stem_md"] = f"如图 ![几何]({self.items[0][0]}) 求值"
        outs, calls = self._run_group(json.dumps(arr, ensure_ascii=False), layout_side=la)
        self.assertIn(fig_rel, outs[0]["stem_md"])
        self.assertNotIn("![几何](" + self.items[0][0] + ")", outs[0]["stem_md"])
        self.assertEqual(len(calls[0][2]), 3)  # 附图=2 裁片 + 1 切片


class TestBatchGroupOrchestration(unittest.TestCase):
    """error_batch._run：分组切分（≤3/组）+ 组内失败逐题回退 + 整组异常全组回退。"""

    def _mk(self, n_boxes):
        tmp = tempfile.mkdtemp()
        d = os.path.join(tmp, "截图")
        os.makedirs(d)
        p = os.path.join(d, "g.png")
        Image.new("RGB", (400, 100 * n_boxes + 40), "white").save(p)
        boxes = [{"id": i, "x": 0.0, "y": 0.01 * i, "w": 0.9, "h": 0.5} for i in range(1, n_boxes + 1)]
        return p, [{"image": "截图/g.png", "abs": p, "boxes": boxes}]

    def _run_batch(self, items, group_side, pipeline_ret=None):
        pipe_calls = []

        def fake_pipeline(uid, md, its, deadline, scene="x"):
            pipe_calls.append(its[0][0])
            if isinstance(pipeline_ret, Exception):
                raise pipeline_ret
            return dict(pipeline_ret or {"stem_md": "回退题", "correct_answer": "1", "explanation": "e"})
        with mock.patch.object(error_analyze, "recognize_group", side_effect=group_side), \
             mock.patch.object(error_analyze, "run_pipeline", side_effect=fake_pipeline):
            tid = error_batch.start_batch(items, user_id="ug")
            r = _wait_done(lambda: error_batch.get_result(tid, user_id="ug"))
        return r, pipe_calls

    def test_four_boxes_two_groups_one_call_each(self):
        group_calls = []

        def gs(uid, its, deadline, scene="x"):
            group_calls.append(len(its))
            return [{"ok": True, "stem_md": f"组题{len(its)}", "correct_answer": "1",
                     "explanation": "e"} for _ in its]
        p, items = self._mk(4)
        r, pipe_calls = self._run_batch(items, gs)
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["total"], 4)
        self.assertEqual(group_calls, [3, 1])  # 4 框切成 3+1 两组
        self.assertEqual(pipe_calls, [])  # 全组成功 → 零逐题回退
        self.assertTrue(all(x["ok"] for x in r["results"]))

    def test_partial_group_failure_falls_back_only_that_question(self):
        def gs(uid, its, deadline, scene="x"):
            return [{"ok": True, "stem_md": "好题", "correct_answer": "1", "explanation": "e"}
                    if "q2" not in rel else {"ok": False, "error": "模型输出缺少对应题目"}
                    for rel, _a in its]
        p, items = self._mk(2)
        r, pipe_calls = self._run_batch(items, gs)
        self.assertEqual(len(pipe_calls), 1)  # 仅 q2 回退
        self.assertIn("q2", pipe_calls[0])
        self.assertEqual(r["results"][0]["stem_md"], "好题")  # 组成功题不被回退覆盖
        self.assertTrue(r["results"][1]["ok"])  # 回退成功

    def test_whole_group_exception_falls_back_every_question(self):
        def gs(uid, its, deadline, scene="x"):
            raise RuntimeError("视觉模型 API调用失败: HTTP 500")
        p, items = self._mk(3)
        r, pipe_calls = self._run_batch(items, gs)
        self.assertEqual(len(pipe_calls), 3)  # 全组逐题回退
        self.assertEqual(r["status"], "done")
        self.assertTrue(all(x["ok"] for x in r["results"]))

    def test_fallback_failure_keeps_group_reason(self):
        def gs(uid, its, deadline, scene="x"):
            return [{"ok": False, "error": "无法从模型返回中解析 JSON 数组"} for _ in its]
        p, items = self._mk(1)
        r, pipe_calls = self._run_batch(items, gs, pipeline_ret=RuntimeError("模型返回的题干为空"))
        self.assertEqual(len(pipe_calls), 1)
        self.assertFalse(r["results"][0]["ok"])
        self.assertIn("解析 JSON 数组", r["results"][0]["error"])  # 分组阶段原因保留
        self.assertIn("题干为空", r["results"][0]["error"])  # 回退失败原因也在


if __name__ == "__main__":
    unittest.main(verbosity=2)
