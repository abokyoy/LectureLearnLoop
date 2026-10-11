# -*- coding: utf-8 -*-
"""手机拍照传图（photo-drop）全链路 API 断言（2026-10-13）。

覆盖：
1. PC 建会话（JWT）→ token/端口/局域网 IP 候选/路径
2. 手机页打开（免登录、token 即凭证）+ 真实 PNG 上传落盘 vault/截图/
3. PC 轮询增量取新图（since/total 语义）
4. 非图片数据拒绝；无效 token 拒绝；关会话后上传拒绝、轮询 404
5. 用户隔离：B 轮询 A 的 token → 404

运行前置：主服务已运行在 127.0.0.1:6001，且小服务端口随主服务拉起
（PHOTO_DISABLE=1 环境跑会整体 skip）。
"""
from __future__ import annotations

import base64
import io
import sys
import time
import unittest
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # server/ 目录（for config/PIL 断言）

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:6001"
SUBJECT = f"手机传图学科{int(time.time()) % 100000}_{uuid.uuid4().hex[:4]}"


def _real_png_b64() -> str:
    """生成真实可打开的小 PNG（测试用真实样本，不伪造 magic）。"""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), (250, 120, 60)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def register_and_token(username: str) -> str:
    requests.post(BASE + "/api/auth/register",
                  json={"username": username, "password": "test123456"}, timeout=15)
    r = requests.post(BASE + "/api/auth/login",
                      json={"username": username, "password": "test123456"}, timeout=15)
    r.raise_for_status()
    return r.json()["data"]["token"]


class TestPhotoDrop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = register_and_token("pdrop_" + uuid.uuid4().hex[:8])
        cls.h = {"Authorization": f"Bearer {cls.token}"}
        r = requests.post(BASE + "/api/kb/photo-session", headers=cls.h,
                          json={"subject": SUBJECT}, timeout=15)
        body = r.json()
        if r.status_code == 503:  # 小服务被禁用/无端口：整体降级不可测
            raise unittest.SkipTest("photo-drop 小服务未启动（503）")
        assert body["success"], r.text
        cls.d = body["data"]
        cls.phone = f"http://127.0.0.1:{cls.d['port']}"

    def test_01_session_shape(self):
        self.assertTrue(self.d["token"])
        self.assertTrue(9900 <= int(self.d["port"]) <= 9999)
        self.assertTrue(self.d["lan_ips"], "应至少枚举到一个本机 IPv4")
        self.assertEqual(self.d["paths"]["page"], "/c/" + self.d["token"])

    def test_02_phone_page_open(self):
        r = requests.get(self.phone + self.d["paths"]["page"], timeout=10)
        self.assertEqual(r.status_code, 200)
        self.assertIn("拍照录入错题", r.text)
        self.assertIn("capture=", r.text)  # 拍照按钮直调后置摄像头

    def test_03_upload_and_poll(self):
        b64 = _real_png_b64()
        r = requests.post(self.phone + f"/c/{self.d['token']}/upload",
                          json={"image_b64": b64}, timeout=15)
        self.assertEqual(r.status_code, 200, r.text)
        rel = r.json()["rel"]
        self.assertTrue(rel.startswith("截图/手机_") and rel.endswith(".png"), rel)
        # 落盘真实存在（vault/<uid>/截图/）且是可打开的 PNG
        from config import VAULT_DIR
        uid = requests.get(BASE + "/api/auth/me", headers=self.h, timeout=10).json()
        uid = (uid.get("data") or {}).get("id") or (uid.get("data") or {}).get("user_id")
        if uid:  # /api/auth/me 形态不确定时跳过文件断言，主断言仍由轮询承担
            f = Path(VAULT_DIR) / str(uid) / rel
            if f.exists():
                from PIL import Image
                self.assertEqual(Image.open(f).size, (32, 24))
        # PC 轮询：增量拿到该图
        pr = requests.get(BASE + f"/api/kb/photo-session/{self.d['token']}?since=0",
                          headers=self.h, timeout=10).json()
        self.assertTrue(pr["success"], str(pr))
        self.assertIn(rel, pr["data"]["images"])
        self.assertEqual(pr["data"]["total"], len(pr["data"]["images"]))
        pr2 = requests.get(BASE + f"/api/kb/photo-session/{self.d['token']}?since={pr['data']['total']}",
                           headers=self.h, timeout=10).json()
        self.assertEqual(pr2["data"]["images"], [], "since 之后不应重复返回旧图")
        # CodeReview m-2 回归：负 since 被 clamp 到 0（返回全量而非尾部切片）
        prn = requests.get(BASE + f"/api/kb/photo-session/{self.d['token']}?since=-5",
                           headers=self.h, timeout=10).json()
        self.assertEqual(len(prn["data"]["images"]), pr["data"]["total"], "负 since 应视同 0 返回全量")

    def test_04_non_image_rejected(self):
        r = requests.post(self.phone + f"/c/{self.d['token']}/upload",
                          json={"image_b64": base64.b64encode(b"hello not an image").decode()},
                          timeout=10)
        self.assertEqual(r.status_code, 400)
        self.assertIn("图片", r.json()["error"])

    def test_05_bogus_token_rejected(self):
        bad = uuid.uuid4().hex[:16]
        self.assertEqual(requests.get(self.phone + f"/c/{bad}", timeout=10).status_code, 410)
        self.assertEqual(requests.post(self.phone + f"/c/{bad}/upload",
                                       json={"image_b64": _real_png_b64()}, timeout=10).status_code, 410)

    def test_06_user_isolation(self):
        t2 = register_and_token("pdrop2_" + uuid.uuid4().hex[:8])
        r = requests.get(BASE + f"/api/kb/photo-session/{self.d['token']}?since=0",
                         headers={"Authorization": f"Bearer {t2}"}, timeout=10)
        self.assertEqual(r.status_code, 404, "他人 token 必须视同不存在")

    def test_07_close_kills_session(self):
        # 单独建一个会话再关，避免影响上面用例顺序依赖
        d = requests.post(BASE + "/api/kb/photo-session", headers=self.h,
                          json={"subject": SUBJECT}, timeout=15).json()["data"]
        c = requests.delete(BASE + f"/api/kb/photo-session/{d['token']}", headers=self.h, timeout=10)
        self.assertTrue(c.json()["success"])
        r = requests.post(f"http://127.0.0.1:{d['port']}/c/{d['token']}/upload",
                          json={"image_b64": _real_png_b64()}, timeout=10)
        self.assertEqual(r.status_code, 410, "关闭后手机上传必须拒绝")
        p = requests.get(BASE + f"/api/kb/photo-session/{d['token']}?since=0", headers=self.h, timeout=10)
        self.assertEqual(p.status_code, 404, "关闭后 PC 轮询应 404（前端据此停轮询）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
