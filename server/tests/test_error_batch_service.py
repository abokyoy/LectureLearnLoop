# -*- coding: utf-8 -*-
"""错题批量识别服务层断言测试（2026-10-14，离线：mock 管线不打外网、不依赖 Flask 进程）。

覆盖：
1. TaskRegistry.update：running 期增量更新 + ts 刷新防 TTL 误回收；终态/不存在任务忽略
2. error_batch._crop_box：归一化坐标 → 像素换算、x+w 越界夹紧、过小抛错、q{框号}_{任务前6} 命名
3. error_batch._run：多图多框全链路（mock recognize_group 整组失败→逐题回退 run_pipeline）
   ——进度上报、done 终态、单题失败隔离、原图损坏该图全框失败不毁整批、失败题孤儿裁剪删除
4. error_analyze._run_inner 回归：抽公共 run_pipeline 后单题任务链行为不变
分组编排与回退的专项断言见 test_error_batch_group.py（2026-10-15 用户裁定：切片一次全给大模型）。
"""
from __future__ import annotations

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
from services.task_registry import TaskRegistry  # noqa: E402

CONTRACT = {"stem_md": "计算 $2+3$ 的值。", "correct_answer": "5", "explanation": "加法"}


def _make_png(path, w, h):
    Image.new("RGB", (w, h), "white").save(path)


def _wait_done(read, timeout=10.0):
    """轮询任务至终态；read() 返回任务 dict 或 None。"""
    end = time.time() + timeout
    while time.time() < end:
        r = read()
        if r and r.get("status") != "running":
            return r
        time.sleep(0.05)
    raise AssertionError("任务未在时限内进入终态")


class TestRegistryUpdate(unittest.TestCase):
    def test_update_running_and_ts_refresh(self):
        reg = TaskRegistry(ttl_s=600)
        tid = reg.create(user_id="u1")
        with reg._lock:
            reg._tasks[tid]["ts"] = time.time() - 300  # 模拟陈旧
        reg.update(tid, total=5, finished=2, results=[{"ok": True}])
        r = reg.get(tid, user_id="u1")
        self.assertEqual(r["status"], "running")
        self.assertEqual((r["total"], r["finished"]), (5, 2))
        self.assertEqual(len(r["results"]), 1)
        with reg._lock:
            self.assertGreater(reg._tasks[tid]["ts"], time.time() - 5)  # ts 已刷新

    def test_update_ignored_after_finish_or_missing(self):
        reg = TaskRegistry(ttl_s=600)
        tid = reg.create(user_id="u1")
        reg.finish(tid, "done", results=[{"ok": True}])
        reg.update(tid, results=[{"ok": False, "hack": 1}])  # 终态后拒绝更新
        self.assertEqual(reg.get(tid, user_id="u1")["results"], [{"ok": True}])
        reg.update("no_such_task", finished=9)  # 不存在任务不崩溃
        self.assertIsNone(reg.get("no_such_task", user_id="u1"))


class TestCropBox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "截图")
        os.makedirs(self.dir)
        self.abs = os.path.join(self.dir, "手机_a.png")
        _make_png(self.abs, 200, 100)

    def test_norm_to_pixel_and_naming(self):
        im = Image.open(self.abs)
        rel = "截图/手机_a.png"
        crop_rel, crop_abs = error_batch._crop_box(
            im, {"id": 3, "x": 0.1, "y": 0.2, "w": 0.5, "h": 0.6}, rel, self.abs, "abcdef123456")
        self.assertEqual(crop_rel, "截图/手机_a_q3_abcdef.png")  # 任务前6位防跨批覆盖
        self.assertTrue(os.path.isfile(crop_abs))
        with Image.open(crop_abs) as c:
            self.assertEqual(c.size, (100, 60))  # (0.6-0.1)*200 x (0.8-0.2)*100

    def test_clamp_overflow_then_too_small(self):
        im = Image.open(self.abs)
        # x+w 越界夹紧后实际宽仅 20px（<24）→ 视为误操作抛错
        with self.assertRaises(ValueError):
            error_batch._crop_box(im, {"id": 1, "x": 0.9, "y": 0.0, "w": 0.5, "h": 0.9},
                                  "截图/手机_a.png", self.abs, "t123456")

    def test_tiny_box_rejected(self):
        im = Image.open(self.abs)
        with self.assertRaises(ValueError):
            error_batch._crop_box(im, {"id": 1, "x": 0.0, "y": 0.0, "w": 0.05, "h": 0.05},
                                  "截图/手机_a.png", self.abs, "t123456")  # 10x5px


class TestBatchRun(unittest.TestCase):
    """_run 全链路：mock run_pipeline，验证进度/隔离/孤儿清理，全程零外呼。"""

    def _setup_dir(self):
        tmp = tempfile.mkdtemp()
        d = os.path.join(tmp, "截图")
        os.makedirs(d)
        return tmp, d

    def _wait(self, tid, uid, timeout=10.0):
        return _wait_done(lambda: error_batch.get_result(tid, user_id=uid), timeout)

    def test_success_with_one_box_failure_isolated(self):
        tmp, d = self._setup_dir()
        good = os.path.join(d, "g.png")
        _make_png(good, 200, 100)
        calls = []

        def fake_pipeline(uid, md, items, deadline, scene="x"):
            calls.append((uid, md, items, scene))
            if "q2" in items[0][0]:  # 第 2 框：管线抛错 → 该题失败但不毁整批
                raise RuntimeError("模型返回的题干为空")
            return dict(CONTRACT)

        def fake_group(uid, items, deadline, scene="x"):
            # 分组阶段：两题都报内容失败 → 逐题回退 run_pipeline
            return [{"ok": False, "error": "分组失败(测试场景)"} for _ in items]

        items = [{"image": "截图/g.png", "abs": good, "boxes": [
            {"id": 1, "x": 0.0, "y": 0.0, "w": 0.8, "h": 0.8},
            {"id": 2, "x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5},
        ]}]
        with mock.patch.object(error_analyze, "recognize_group", side_effect=fake_group), \
             mock.patch.object(error_analyze, "run_pipeline", side_effect=fake_pipeline):
            tid = error_batch.start_batch(items, user_id="ub")
            r = self._wait(tid, "ub")
        self.assertEqual(r["status"], "done")
        self.assertEqual((r["total"], r["finished"]), (2, 2))
        self.assertEqual(r["results"][0]["ok"], True)
        self.assertEqual(r["results"][1]["ok"], False)
        self.assertIn("题干为空", r["results"][1]["error"])
        self.assertIn("分组失败", r["results"][1]["error"])  # 保留分组阶段失败原因便于定位
        # 成功题裁剪落盘保留；失败题孤儿裁剪已清理（CodeReview Minor-5）
        stem = Path(r["results"][0]["crop"]).name
        self.assertTrue(os.path.isfile(os.path.join(d, stem)))
        fail_crops = [f for f in os.listdir(d) if "_q2_" in f]
        self.assertEqual(fail_crops, [])
        # 回退调用契约：scene=批量识别错题、单图 items、md 为空串
        self.assertEqual(len(calls), 2)  # 两题都走了逐题回退
        self.assertEqual(calls[0][1], "")
        self.assertEqual(calls[0][3], "批量识别错题")

    def test_broken_source_image_fails_all_its_boxes_only(self):
        tmp, d = self._setup_dir()
        bad = os.path.join(d, "bad.png")
        with open(bad, "wb") as f:
            f.write(b"not-an-image")
        good = os.path.join(d, "g.png")
        _make_png(good, 200, 100)
        items = [
            {"image": "截图/bad.png", "abs": bad, "boxes": [
                {"id": 1, "x": 0, "y": 0, "w": 0.5, "h": 0.5},
                {"id": 2, "x": 0, "y": 0, "w": 0.5, "h": 0.5}]},
            {"image": "截图/g.png", "abs": good, "boxes": [
                {"id": 1, "x": 0, "y": 0, "w": 0.5, "h": 0.5}]},
        ]
        with mock.patch.object(error_analyze, "recognize_group",
                               side_effect=lambda uid, items, deadline, scene="x":
                               [{"ok": True, **CONTRACT} for _ in items]), \
             mock.patch.object(error_analyze, "run_pipeline", return_value=dict(CONTRACT)):
            tid = error_batch.start_batch(items, user_id="ub2")
            r = self._wait(tid, "ub2")
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["total"], 3)
        bads = [x for x in r["results"] if x["image"] == "截图/bad.png"]
        self.assertEqual(len(bads), 2)
        self.assertTrue(all(not x["ok"] and "原图无法打开" in x["error"] for x in bads))
        goods = [x for x in r["results"] if x["image"] == "截图/g.png"]
        self.assertTrue(all(x["ok"] for x in goods))  # 坏图不毁好图

    def test_progress_reported_while_running(self):
        tmp, d = self._setup_dir()
        p1 = os.path.join(d, "p1.png")
        _make_png(p1, 200, 100)
        gate = {"n": 0, "tid": None}
        seen_running = []

        def slow_pipeline(uid, md, items, deadline, scene="x"):
            # 工作线程可能先于 start_batch 返回拿到 task_id：短暂等待绑定完成
            for _ in range(100):
                if gate["tid"]:
                    break
                time.sleep(0.01)
            gate["n"] += 1
            if gate["n"] == 1:
                # 第 1 题进行中：偷看进度（update 上报 finished/results 快照）
                r = error_batch.get_result(gate["tid"], user_id="ub3")
                seen_running.append((r["status"], r["finished"], len(r["results"])))
            return dict(CONTRACT)

        items = [{"image": "截图/p1.png", "abs": p1, "boxes": [
            {"id": i, "x": 0, "y": 0, "w": 0.5, "h": 0.5} for i in (1, 2)]}]
        with mock.patch.object(error_analyze, "recognize_group",
                               side_effect=lambda uid, items, deadline, scene="x":
                               [{"ok": False, "error": "分组失败(测试场景)"} for _ in items]), \
             mock.patch.object(error_analyze, "run_pipeline", side_effect=slow_pipeline):
            tid = error_batch.start_batch(items, user_id="ub3")
            gate["tid"] = tid
            r = self._wait(tid, "ub3")
        self.assertEqual(seen_running[0][0], "running")
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["finished"], 2)


class TestAnalyzeSingleRegression(unittest.TestCase):
    """抽公共 run_pipeline 后，单题任务链 _run_inner 行为回归（任务表 done + 契约字段）。"""

    def test_run_inner_done_contract_unchanged(self):
        tid = error_analyze._registry.create(user_id="u1")
        with mock.patch.object(error_analyze, "run_pipeline",
                               side_effect=lambda uid, md, items, deadline, scene="x": dict(CONTRACT)):
            error_analyze._run_inner(tid, "u1", "题干文字", [("截图/a.png", "abs/a.png")])
        r = error_analyze.get_result(tid, user_id="u1")
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["stem_md"], CONTRACT["stem_md"])
        self.assertEqual(r["correct_answer"], CONTRACT["correct_answer"])
        self.assertEqual(r["explanation"], CONTRACT["explanation"])

    def test_run_inner_error_path(self):
        tid = error_analyze._registry.create(user_id="u1")
        with mock.patch.object(error_analyze, "run_pipeline",
                               side_effect=ValueError("模型返回的题干为空")):
            error_analyze._run_inner(tid, "u1", "x", [])
        r = error_analyze.get_result(tid, user_id="u1")
        self.assertEqual(r["status"], "error")
        self.assertIn("题干为空", r["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
