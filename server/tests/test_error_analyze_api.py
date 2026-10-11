# -*- coding: utf-8 -*-
"""错题智能分析 API 参数校验断言（2026-10-13，真实全链路见 tests/integ_error_analyze_e2e.py）。

覆盖：
1. POST 纯空白内容 → 400
2. POST 引用目录穿越图片路径 → 400（消息含非法路径）
3. POST 引用不存在的 vault 图片 → 400
4. POST 仅含 http/data 远程图引用 → 不当作图片处理，不报路径错
5. GET 不存在任务 → 404；跨用户任务 → 404

运行前置：服务端已在 127.0.0.1:6001 运行。
"""
from __future__ import annotations

import sys
import time
import unittest
import uuid

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:6001"


def register_and_token(username: str) -> str:
    requests.post(BASE + "/api/auth/register",
                  json={"username": username, "password": "test123456"}, timeout=15)
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["token"]


class TestAnalyzeApiValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = register_and_token("aapi_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}

    def _post(self, path, **kw):
        return requests.post(BASE + path, headers=self.h, timeout=30, **kw)

    def _get(self, path, **kw):
        return requests.get(BASE + path, headers=self.h, timeout=30, **kw)

    def test_01_empty_content(self):
        r = self._post("/api/kb/error-analyze", json={"content": "   "})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("没有可分析的内容", r.json().get("error", ""))

    def test_02_traversal_path_rejected(self):
        # 非图片扩展名会被 md_image_paths 过滤，因此穿越测试必须用 .png 后缀才能真正走到校验分支
        r = self._post("/api/kb/error-analyze",
                       json={"content": "题 ![a](../../outside_vault.png)"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("非法", r.json().get("error", ""))

    def test_03_missing_image_rejected(self):
        r = self._post("/api/kb/error-analyze",
                       json={"content": "题 ![a](截图/不存在_abc.png)"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("截图/不存在_abc.png", r.json().get("error", ""))

    def test_04_remote_urls_not_treated_as_images(self):
        # http/data 引用被 md_image_paths 剔除，不会触发 400「引用的图片非法」；
        # 剩余文本内容仍属合法分析对象（剔除行为本身已在服务层测试离线断言）
        r = self._post("/api/kb/error-analyze", json={
            "content": "![](https://evil.example/x.png) ![](data:image/png;base64,AAAA)"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("task_id", r.json().get("data", {}))

    def test_05_get_unknown_task_404(self):
        r = self._get("/api/kb/error-analyze/nonexistent_task_xyz")
        self.assertEqual(r.status_code, 404, r.text)

    def test_06_cross_user_task_404(self):
        # 用户 A 建任务（内容合法：写一张 1x1 png 进 A 的 vault），用户 B 查询该 task → 404。
        # 任务会真实提交后台分析，但立即被 B 的越权断言覆盖；A 侧不做轮询等待，管线自行结束。
        import pathlib
        import sys as _sys
        _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        from config import VAULT_DIR
        from PIL import Image

        tok_a = register_and_token("aapiA_" + uuid.uuid4().hex[:8])
        me = requests.get(BASE + "/api/auth/me", headers={"Authorization": f"Bearer {tok_a}"},
                          timeout=15).json()["data"]
        uid_a = str(me.get("user_id") or me.get("id") or me.get("username"))
        rel_dir = pathlib.Path(VAULT_DIR) / uid_a / "截图"
        rel_dir.mkdir(parents=True, exist_ok=True)
        png = rel_dir / f"cross_{int(time.time())}.png"
        Image.new("RGB", (4, 4), "white").save(png)

        r = requests.post(BASE + "/api/kb/error-analyze", headers={"Authorization": f"Bearer {tok_a}"},
                          json={"content": f"题 ![a](截图/{png.name})"}, timeout=30)
        self.assertEqual(r.status_code, 200, r.text)
        tid = r.json()["data"]["task_id"]
        r2 = self._get(f"/api/kb/error-analyze/{tid}")  # 本测试类是另一个用户
        self.assertEqual(r2.status_code, 404, "跨用户必须视同不存在")
        png.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
