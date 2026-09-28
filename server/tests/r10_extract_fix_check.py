# -*- coding: utf-8 -*-
"""R10 验收：知识点提取空白 bug 修复自证（真实 DeepSeek，端到端复刻用户操作链）。

覆盖用户反馈（2026-09-28）：
- 提取提示成功 N 个但列表全空白（根因：extract-file 未解包 processed_points.extracted_point）
- 编辑弹窗名称/描述为空
- 保存后左侧全空
- 新增知识点报"知识点名称不能为空"
验证方式：注册临时用户 → 落盘笔记 → extract-file → batch-save → 列表回查 → point-new。
"""
import base64
import json
import os
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:6001"
VAULT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "vault")
PASS = [0]
FAIL = []

NOTE_TEXT = """# 机器学习听课笔记
本节课讲解三个核心概念。第一个是过拟合：指模型在训练数据上表现很好，但在未见过的测试数据上表现明显变差的现象，本质是模型 memorized 了噪声。
第二个是正则化：通过在损失函数中加入权重惩罚项（如 L1、L2 范数）来限制模型复杂度，从而缓解过拟合的技术。
第三个是梯度下降：一种迭代优化算法，通过沿损失函数梯度的反方向更新参数，逐步最小化目标函数，是训练神经网络最基础的方法。
"""


def req(method, path, body=None, token=None, timeout=120):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")


def check(cond, label, detail=""):
    if cond:
        PASS[0] += 1
        print(f"PASS  {label}")
    else:
        FAIL.append(label)
        print(f"FAIL  {label} -> {detail}")


ts = str(int(time.time()))[-6:]
uname = "qa_extract_" + ts
upw = "QaTest12345"

# 1. 注册临时用户，再 login 一次拿 token（每日赠分挂在 login 钩子，LLM 端点积分预检才放行）
st, body = req("POST", "/api/auth/register", {"username": uname, "password": upw})
check(st == 200 and body.get("success"), "注册临时用户", f"st={st} body={body}")
st, lbody = req("POST", "/api/auth/login", {"username": uname, "password": upw})
check(st == 200 and lbody.get("data", {}).get("token"), "登录获得 token", f"st={st} body={lbody}")
body = lbody
token = body["data"]["token"]
uid = body["data"].get("user_id")
if not uid:  # 从 JWT 里取
    payload = token.split(".")[1] + "=="
    uid = str(json.loads(base64.urlsafe_b64decode(payload)).get("uid"))
print(f"      user_id={uid}")

# 2. 直接落盘笔记文件到用户 vault（模拟录音→听课笔记保存后的状态）
note_name = f"qa_extract_note_{ts}.md"
note_path = os.path.join(VAULT_ROOT, str(uid), note_name)
os.makedirs(os.path.dirname(note_path), exist_ok=True)
with open(note_path, "w", encoding="utf-8") as f:
    f.write(NOTE_TEXT)

# 3. extract-file：核心断言——每个知识点 name/description 必须非空
st, body = req("POST", "/api/knowledge/extract-file", {"file_path": note_name, "subject": "QA测试学科" + ts}, token)
check(st == 200 and body.get("success"), "extract-file 返回 success", f"st={st} body={str(body)[:200]}")
pts = (body.get("data") or {}).get("knowledge_points") or []
check(len(pts) >= 1, "extract-file 至少返回 1 个知识点", f"count={len(pts)}")
empty = [i for i, p in enumerate(pts) if not (p.get("name") or "").strip()]
check(not empty, "所有知识点 name 非空（旧 bug：全为空字符串）", f"empty_idx={empty} sample={str(pts[:2])[:300]}")
empty_desc = [i for i, p in enumerate(pts) if not (p.get("description") or "").strip()]
check(not empty_desc, "所有知识点 description 非空（编辑弹窗不再为空）", f"empty_idx={empty_desc}")
print(f"      提取结果: {[p['name'] for p in pts]}")

# 3.5 四期后 batch-save 不再 auto-create 科目（串写 bug 根因修复），显式建科=真实用户流程
st, body = req("POST", "/api/subjects", {"subject_name": "QA测试学科" + ts}, token)
check(st == 200 and body.get("success"), "创建科目（/api/subjects）", f"st={st} body={str(body)[:120]}")

# 4. batch-save：保存知识点（旧 bug：name 为空被过滤 → 保存 0 个，左侧全空）
st, body = req("POST", "/api/knowledge/batch-save", {
    "filePath": note_path, "subject": "QA测试学科" + ts, "knowledgePoints": pts}, token)
d = body.get("data") or {}
check(st == 200 and d.get("success") and d.get("saved_count", 0) == len(pts),
      "batch-save 全部保存成功", f"body={str(body)[:200]}")

# 5. 列表回查：知识点球已入库且名称正确
st, body = req("GET", "/api/knowledge/points?subject=" + urllib.parse.quote("QA测试学科" + ts), token=token)
rows = body.get("data") or []
names_saved = {r.get("point_name") for r in rows}
names_extracted = {p["name"] for p in pts}
check(st == 200 and names_extracted <= names_saved, "科目知识点列表回查包含全部提取名称",
      f"saved={names_saved} extracted={names_extracted}")

# 6. point-new：新增知识点不再报"知识点名称不能为空"
st, body = req("POST", "/api/knowledge/point-new", {
    "point": {"name": "QA手动新增概念" + ts, "description": "手动新增验证"},
    "subject": "QA测试学科" + ts,
    "noteInfo": {"filePath": note_path},
}, token)
d = body.get("data") or {}
check(st == 200 and d.get("success"), "新增知识点（point-new）成功", f"body={str(body)[:200]}")

# 清理落盘笔记（数据库测试数据保留，用户名带 qa_extract_ 前缀可识别）
try:
    os.remove(note_path)
except OSError:
    pass

print(f"\n===== R10 提取修复验收: {PASS[0]} PASS / {len(FAIL)} FAIL =====")
sys.exit(1 if FAIL else 0)
