# -*- coding: utf-8 -*-
"""T9 全链路功能串联验收（HTTP 层自证，不依赖浏览器点击）。

覆盖用户反馈问题：
1) 登录大小写归一化：注册 ABOYKOY 后用小写 aboykoy 能登录（旧 bug：401）
2) 重复注册大小写不敏感：同用户名不同大小写 → 409
3) JWT 有效期 7 天（四期修正，原 57）
4) 登录前置：/ 页面含 ll_token 守卫脚本；登录页含 记住登录/确认密码
5) 悬浮窗关闭=销毁：/overlay 含 overlayClose 调用，不再 body.display=none
6) 调试面板删除：/practice 不再含页内调试日志 DOM
7) 练页面嵌入主框架：/fragments/practice_materials 返回 iframe 片段
8) 知识库真实数据页：/fragments/knowledge_base 含 kb-subject-grid（无假"156"）
"""
import base64
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:6001"
PASS = [0]
FAIL = []


def req(method, path, body=None, token=None, expect_status=None, contains=None, absent=None, label=""):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    status = None
    text = ""
    try:
        with urllib.request.urlopen(r) as resp:
            status = resp.status
            text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        text = e.read().decode("utf-8", "replace")
    ok = True
    msgs = []
    if expect_status is not None and status != expect_status:
        ok = False
        msgs.append(f"状态码 {status} != 期望 {expect_status}")
    for c in contains or []:
        if c not in text:
            ok = False
            msgs.append(f"缺少内容: {c!r}")
    for a in absent or []:
        if a in text:
            ok = False
            msgs.append(f"不应存在: {a!r}")
    tag = label or f"{method} {path}"
    if ok:
        PASS[0] += 1
        print(f"PASS  {tag}")
    else:
        FAIL.append(tag)
        print(f"FAIL  {tag} -> {'; '.join(msgs)}")
    return text, status


def jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


uname = "LlT9CaseTest" + str(int(time.time()))[-4:]
upw = "coco8888"

# 1. 注册（大写开头用户名）
text, st = req("POST", "/api/auth/register", {"username": uname, "password": upw},
               expect_status=200, label="注册（混合大小写用户名）")
token = json.loads(text)["data"]["token"]

# 2. 大小写变体登录必须成功（旧 bug：用户不存在/密码错误）
lower_name = uname.lower()
text, st = req("POST", "/api/auth/login", {"username": lower_name, "password": upw},
               expect_status=200, label="登录（同名小写变体）")
token2 = json.loads(text)["data"]["token"]

# 3. 大小写变体重复注册必须 409
req("POST", "/api/auth/register", {"username": uname.upper(), "password": upw},
    expect_status=409, label="重复注册（同名大写变体）应 409")

# 4. JWT 有效期 ≈7 天（四期修正）
claims = jwt_claims(token2)
days = (claims["exp"] - time.time()) / 86400
if 6.5 <= days <= 7.5:
    PASS[0] += 1
    print(f"PASS  JWT 有效期 {days:.1f} 天 ≈ 7 天")
else:
    FAIL.append("JWT TTL")
    print(f"FAIL  JWT 有效期 {days:.1f} 天（期望 7）")

# 5. 登录前置守卫 + 统一弹窗在壳页面注入
req("GET", "/", expect_status=200,
    contains=["localStorage.getItem('ll_token')", "/login?next=", "__llAlertInstalled"],
    absent=["global-debug-panel", "本周学习资料数"],
    label="工作台：登录守卫+统一弹窗+假数据已删")

# 6. 登录页：记住登录 + 确认密码 + 会话级 token 语义（sessionStorage）
req("GET", "/login", expect_status=200,
    contains=["记住登录", "确认密码", "ll_remember", "sessionStorage", "7 天内免登录"],
    label="登录页：双密码+记住7天+会话级存储")

# 7. 悬浮窗：关闭走销毁，不再隐藏 body
req("GET", "/overlay", expect_status=200,
    contains=["overlayClose"],
    absent=["document.body.style.display = 'none'"],
    label="悬浮窗：关闭=销毁窗口")

# 8. 练页（整页）：调试面板已删 + 返回按钮脚本 + 全科目加载
req("GET", "/practice", expect_status=200,
    contains=["ll-back-btn", "getAllSubjects()", "__llAlertInstalled", "暂无知识点"],
    absent=["🖥️ 调试日志", "id=\"debugLog\"", "getSubjectsWithKnowledgeCount()"],
    label="练页：调试面板删除+返回键+0分科目可见")

# 9. 练页面 SPA 片段（iframe 嵌入，左菜单不丢）
req("GET", "/fragments/practice_materials", token=token2, expect_status=200,
    contains=["iframe", "/practice"], label="练页片段：iframe 嵌入主框架")

# 10. 知识库真实数据片段（无假数据）
req("GET", "/fragments/knowledge_base", token=token2, expect_status=200,
    contains=["kb-subject-grid", "getAllSubjects"],
    absent=["156", "87%", "个主要分类"],
    label="知识库：真实数据版")

# 11. 科目 stats API 带 token 正常
req("GET", "/api/subjects/stats", token=token2, expect_status=200,
    contains=["success"], label="科目统计 API")

# 12. online_course：调试/测试按钮已删
req("GET", "/fragments/online_course_notes", token=token2, expect_status=200,
    absent=["debug-toggle-btn", "id=\"debug-panel\"", "测试Bridge连接"],
    label="在线课程页：调试 UI 已删")

print(f"\n结果: {PASS[0]} PASS / {len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)
