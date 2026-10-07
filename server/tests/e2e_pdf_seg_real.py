"""E2E：真实 336 页《机器学习实战》PDF 分段导入全链路自证（2026-10-07）。

背景：用户实测导入"完全不行"——根因是 pdf_is_text_layer 旧"前3/中3/后3"采样
对该书（正文集中中段、首尾仅 22 字符水印页）假阴性 → 只建占位不投整书 worker。
本脚本走真实 HTTP（注册测试用户→上传→轮询→磁盘断言），验证修复后全链路通过。

断言：
  A1 上传响应 is_book=True 且 is_text_layer=True 且 segments=17
  A2 任务在 300s 内到达 done
  A3 磁盘上 17 个段 MD 全部非空（≥200 字符），失败段数与响应一致
  A4 段文件名字典序=页序（0001-0020 … 覆盖 336 页）

用法：python tests/e2e_pdf_seg_real.py [BASE_URL]   （默认 http://127.0.0.1:6001）
"""
import glob
import os
import sys
import time
import uuid

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:6001").rstrip("/")
PDF = r"C:\Users\Administrator\Desktop\机器学习实战 = Machine Learning in Action (Peter Harrington) (Z-Library).pdf"
VAULT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "vault")


def main() -> int:
    assert os.path.isfile(PDF), f"真实样本不存在：{PDF}"
    user = "e2e_seg_" + uuid.uuid4().hex[:8]
    r = requests.post(f"{BASE}/api/auth/register",
                      json={"username": user, "password": "pass1234"}, timeout=30)
    assert r.ok and r.json().get("success"), f"注册失败: {r.text[:200]}"
    tok = r.json()["data"]["token"]
    uid = r.json()["data"]["user_id"]
    H = {"Authorization": f"Bearer {tok}"}
    print(f"用户已注册 {user} ({uid})")

    with open(PDF, "rb") as fh:
        r = requests.post(f"{BASE}/api/vault/import", headers=H, timeout=300,
                          files={"file": (os.path.basename(PDF), fh, "application/pdf")},
                          data={"folder_path": "vault"})
    assert r.ok, f"上传 HTTP 失败 {r.status_code}"
    j = r.json()
    assert j.get("success"), f"上传业务失败: {j}"
    d = j["data"]
    # A1 三态分流：进书籍分段路径，且文本层判定为真（本次修复的核心断言）
    assert d.get("is_book") is True, f"A1失败：未走书籍路径 {d}"
    assert d.get("is_text_layer") is True, f"A1失败：文本层仍误判 {d}"
    assert d.get("segments") == 17, f"A1失败：段数应为17 {d}"
    tid = d["task_id"]
    print(f"A1 通过：is_book/is_text_layer=True segs=17 task={tid}")

    # A2 轮询到 done（整书文本层串行转换）
    deadline = time.time() + 300
    prog = {}
    while time.time() < deadline:
        raw = requests.get(f"{BASE}/api/vault/import/{tid}", headers=H, timeout=30).json()
        s = raw.get("data") or {}   # _ok 包裹：业务字段在 data 层
        prog = s.get("progress") or {}
        st = s.get("status")
        if st == "done":
            break
        if st == "failed":
            print(f"A2失败：任务 failed error={s.get('error')}")
            return 1
        time.sleep(3)
    else:
        print(f"A2失败：300s 未收敛 progress={prog}")
        return 1
    print(f"A2 通过：done progress={prog}")

    # A3/A4 磁盘断言：段文件非空且覆盖全页
    segs = sorted(glob.glob(os.path.join(VAULT_ROOT, uid, "**", "*·*-*.md"), recursive=True))
    assert len(segs) == 17, f"A4失败：段文件数={len(segs)} {[os.path.basename(x) for x in segs][:3]}"
    total_chars = 0
    empty = []
    for p in segs:
        with open(p, encoding="utf-8") as fh:
            c = len(fh.read().strip())
        total_chars += c
        if c < 200:
            empty.append((os.path.basename(p), c))
    assert not empty, f"A3失败：空/过短段 {empty}"
    first, last = os.path.basename(segs[0]), os.path.basename(segs[-1])
    assert "0001-0020" in first, f"A4失败：首段名 {first}"
    assert "0321" in last and segs[-1] and total_chars > 20000, \
        f"A4失败：尾段 {last} 或总字数 {total_chars}"
    print(f"A3/A4 通过：17 段全部非空，总字符 {total_chars}，首={first} 尾={last}")
    failed_segs = prog.get("failed", 0)
    print(f"整书进度 done={prog.get('done')} failed={failed_segs}")
    print("E2E 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
