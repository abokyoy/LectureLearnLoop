# -*- coding: utf-8 -*-
"""错题批量识别 API 参数校验断言（2026-10-14，HTTP 黑盒，模式同 test_error_analyze_api.py）。

覆盖：
1. POST items 空/非列表/超 20 图 → 400
2. 图片不存在、目录穿越、非图片扩展名 → 400
3. boxes 空/超 10 框/编号重复/编号 <1/坐标非法/坐标越界 → 400
4. 单批总框数 > 50 → 400
5. GET 不存在任务 → 404；跨用户任务 → 404
6. 真实提交任务：4x4 小图整框提交 → 服务侧「框选区域过小」失败隔离，任务 done 且 0 成功
   （校验失败路径全在 400 前拦下，小图裁剪不达标 → 全程零大模型调用、零扣分）

运行前置：服务端已在 127.0.0.1:6001 运行。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import unittest
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 默认 6001；本机 WinNAT 偶发排除该段时可用 LL_TEST_BASE 环境变量改端口（掉坑笔记 P0xx）
BASE = os.getenv("LL_TEST_BASE", "http://127.0.0.1:6001")
API = "/api/kb/error-batch"


def register_and_token(username: str):
    requests.post(BASE + "/api/auth/register",
                  json={"username": username, "password": "test123456"}, timeout=15)
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    tok = r.json()["data"]["token"]
    seg = tok.split(".")[1]
    uid = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"]
    return tok, str(uid)


def _box(bid=1, x=0.1, y=0.1, w=0.5, h=0.5):
    return {"id": bid, "x": x, "y": y, "w": w, "h": h}


class TestBatchApiValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from config import VAULT_DIR
        from PIL import Image
        cls.token, cls.uid = register_and_token("ebapi_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}
        d = Path(VAULT_DIR) / cls.uid / "截图"
        d.mkdir(parents=True, exist_ok=True)
        cls.dir = d
        cls.png = d / f"eb_{int(time.time())}.png"
        Image.new("RGB", (300, 200), "white").save(cls.png)
        cls.rel = f"截图/{cls.png.name}"
        cls.created = [cls.png]

    @classmethod
    def tearDownClass(cls):
        for p in cls.created:
            p.unlink(missing_ok=True)

    def _post(self, payload):
        return requests.post(BASE + API, headers=self.h, json=payload, timeout=30)

    def _item(self, boxes, rel=None):
        return {"image": rel or self.rel, "boxes": boxes}

    def _assert400(self, payload, keyword):
        r = self._post(payload)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn(keyword, r.json().get("error", ""), r.text)

    # ---- 1. items 基础校验 ----
    def test_01_items_empty_or_bad(self):
        self._assert400({}, "不能为空")
        self._assert400({"items": []}, "不能为空")
        self._assert400({"items": "字符串"}, "不能为空")

    def test_02_too_many_images(self):
        # 图数上限在逐条校验前拦截，占位路径即可
        items = [self._item([_box()], rel=f"截图/占位{i}.png") for i in range(21)]
        self._assert400({"items": items}, "20")

    # ---- 2. 图片路径校验 ----
    def test_03_image_missing(self):
        self._assert400({"items": [self._item([_box()], rel="截图/不存在_xyz.png")]},
                        "不存在或路径非法")

    def test_04_traversal_rejected(self):
        self._assert400({"items": [self._item([_box()], rel="../../outside.png")]}, "非法")

    def test_05_non_image_extension(self):
        txt = self.dir / f"eb_txt_{int(time.time())}.txt"
        txt.write_text("not image", encoding="utf-8")
        self.created.append(txt)
        self._assert400({"items": [self._item([_box()], rel=f"截图/{txt.name}")]}, "仅支持图片")

    # ---- 3. boxes 校验 ----
    def test_06_boxes_empty(self):
        self._assert400({"items": [self._item([])]}, "至少一个框")

    def test_07_boxes_per_image_limit(self):
        self._assert400({"items": [self._item([_box(i) for i in range(1, 12)])]}, "10")

    def test_08_box_id_duplicate(self):
        self._assert400({"items": [self._item([_box(1), _box(1, x=0.2)])]}, "编号重复")

    def test_09_box_id_illegal(self):
        self._assert400({"items": [self._item([_box(0)])]}, "编号非法")
        self._assert400({"items": [self._item([_box(-3)])]}, "编号非法")

    def test_10_coord_bad_format(self):
        self._assert400({"items": [self._item([{"id": 1, "x": "abc", "y": 0, "w": 0.5, "h": 0.5}])]},
                        "坐标格式")
        self._assert400({"items": [self._item([_box(1, w=0)])]}, "超出范围")  # w<=0 走范围分支

    def test_11_coord_out_of_range(self):
        self._assert400({"items": [self._item([_box(1, x=0.8, w=0.5)])]}, "超出范围")
        self._assert400({"items": [self._item([_box(1, y=-0.5)])]}, "超出范围")

    def test_12_total_boxes_limit(self):
        # 6 图 × 9 框 = 54 > 50：需要真实存在的图
        from PIL import Image
        items = []
        for k in range(6):
            p = self.dir / f"eb_multi_{int(time.time())}_{k}.png"
            Image.new("RGB", (100, 100), "white").save(p)
            self.created.append(p)
            items.append(self._item([_box(i, x=0.05, y=0.05 * i, w=0.4, h=0.4)
                                     for i in range(1, 10)], rel=f"截图/{p.name}"))
        self._assert400({"items": items}, "50")

    # ---- 4. GET 语义 ----
    def test_13_get_unknown_404(self):
        r = requests.get(BASE + API + "/nonexistent_task", headers=self.h, timeout=15)
        self.assertEqual(r.status_code, 404, r.text)

    def test_14_cross_user_404_and_small_box_fail_done(self):
        """真实提交（零大模型调用）：4x4 小图整框 → 服务侧裁剪不达标 →
        A 轮询到 done 且该题 ok=False；B 视角 GET → 404。"""
        from PIL import Image
        p = self.dir / f"eb_tiny_{int(time.time())}.png"
        Image.new("RGB", (4, 4), "white").save(p)
        self.created.append(p)
        r = self._post({"items": [{"image": f"截图/{p.name}",
                                   "boxes": [_box(1, x=0, y=0, w=1.0, h=1.0)]}]})
        self.assertEqual(r.status_code, 200, r.text)
        tid = r.json()["data"]["task_id"]
        self.assertEqual(r.json()["data"]["total"], 1)
        # 跨用户不可见
        tok_b, _ = register_and_token("ebapiB_" + uuid.uuid4().hex[:8])
        rb = requests.get(BASE + API + f"/{tid}", headers={"Authorization": f"Bearer {tok_b}"},
                          timeout=15)
        self.assertEqual(rb.status_code, 404, "跨用户必须视同不存在")
        # 本用户轮询到终态：done + 唯一题失败（框过小），零成功不毁任务
        end = time.time() + 20
        res = None
        while time.time() < end:
            j = requests.get(BASE + API + f"/{tid}", headers=self.h, timeout=15).json()
            res = j["data"]
            if res.get("status") != "running":
                break
            time.sleep(0.5)
        self.assertEqual(res.get("status"), "done", str(res))
        self.assertEqual(len(res.get("results") or []), 1)
        entry = res["results"][0]
        self.assertFalse(entry["ok"])
        self.assertIn("过小", entry["error"])
        # done 后 TTL 内可重复读（consume=False 语义）
        j2 = requests.get(BASE + API + f"/{tid}", headers=self.h, timeout=15)
        self.assertEqual(j2.status_code, 200, j2.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
