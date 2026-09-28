# -*- coding: utf-8 -*-
"""四期 HTTP 自证验收：对运行中的服务（127.0.0.1:6001）全链路验证 A/B/C/D 四组交付。

链路（plan 验证节）：注册→免登录 TTL 契约→改密→stats 与 DB 一致→
batch-save 不 auto-create 科目→cleanup 脚本幂等→页面 HTTP 静态断言
（音源两项 / 四项右键 / 练习链路 / 全局录音单例）→清理测试数据。

运行（server/ 目录）：python tests/p4_check.py    退出码 0=全过
"""
import base64
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

BASE = "http://127.0.0.1:6001"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PASS = [0]
FAIL = []
USER = "p4chk_" + uuid.uuid4().hex[:6]
PW = "pass1234"
PW2 = "newpass99"


def check(cond, msg, detail=""):
    if cond:
        PASS[0] += 1
        print(f"PASS  {msg}")
    else:
        FAIL.append(msg)
        print(f"FAIL  {msg}  {detail[:200]}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # noqa: ANN002
        return None


def req(method, path, body=None, token=None, follow=True, timeout=90):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return 0, str(e), {}


def jbody(s):
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return {}


def jwt_exp_days(token):
    p = token.split(".")[1]
    p += "=" * (-len(p) % 4)
    claims = json.loads(base64.urlsafe_b64decode(p))
    return (claims["exp"] - time.time()) / 86400


def main():
    # ---------- 0. 服务健康 ----------
    st, b, _ = req("GET", "/api/health")
    check(st == 200, "服务健康 /api/health 200", b)
    if st != 200:
        print("服务未运行，先执行 tests/restart_server.ps1")
        return 1

    # ---------- 1. A组：注册 / 免登录契约 / 昵称 / 改密 ----------
    st, b, _ = req("POST", "/api/auth/register", {"username": USER, "password": PW})
    d = jbody(b).get("data") or {}
    tk = d.get("token", "")
    check(st == 200 and tk, "注册新用户并下发 token")
    check(d.get("expires_in_days") == 7, "免登录默认 7 天（API 契约 expires_in_days）", str(d))
    check(tk and 6.5 <= jwt_exp_days(tk) <= 7.5, "JWT 实际有效期≈7 天")

    st, b, _ = req("POST", "/api/auth/login", {"username": USER, "password": PW})
    d = jbody(b).get("data") or {}
    check(st == 200 and "display_name" in d and d.get("expires_in_days") == 7,
          "登录响应含 display_name/expires_in_days（前端 sessionStorage 语义依据）", str(d))
    tk = d.get("token", tk)

    st, b, _ = req("POST", "/api/auth/profile", {"display_name": "四期自证昵称"}, tk)
    check(st == 200, "设置昵称 200", b)
    st, b, _ = req("GET", "/api/auth/me", token=tk)
    me = jbody(b).get("data") or {}
    check(me.get("display_name") == "四期自证昵称" and me.get("token_exp", 0) > time.time(),
          "me 返回昵称与 token 到期时间", str(me))

    st, _, _ = req("POST", "/api/auth/password", {"old_password": "wrong", "new_password": PW2}, tk)
    check(st == 401, "改密：旧密码错误被拒 401")
    st, b, _ = req("POST", "/api/auth/password", {"old_password": PW, "new_password": PW2}, tk)
    check(st == 200 and (jbody(b).get("data") or {}).get("changed"), "改密成功")
    st, _, _ = req("POST", "/api/auth/login", {"username": USER, "password": PW})
    check(st == 401, "旧密码登录失效 401")
    st, b, _ = req("POST", "/api/auth/login", {"username": USER, "password": PW2})
    tk = (jbody(b).get("data") or {}).get("token", tk)
    check(st == 200, "新密码登录成功")

    # ---------- 2. B组：stats 真数据 + 与 DB 交叉核对 ----------
    st, b, _ = req("GET", "/api/dashboard/stats", token=tk)
    s = jbody(b).get("data") or {}
    check(st == 200 and s.get("materials_this_week") == 0 and s.get("practice_accuracy") is None
          and s.get("knowledge_total") == 0, "新用户 stats 全为真实 0/None（无 12/85%/156 假兜底）", str(s))

    subject = "P4CHk学科_" + uuid.uuid4().hex[:4]
    st, _, _ = req("POST", "/api/subjects", {"subject_name": subject}, tk)
    check(st == 200, "显式创建科目")
    st, b, _ = req("POST", "/api/knowledge/batch-save", {
        "filePath": f"p4chk_{subject}.md", "subject": subject,
        "knowledgePoints": [{"name": "自证点甲", "description": "d1"},
                            {"name": "自证点乙", "description": "d2"}]}, tk)
    saved = (jbody(b).get("data") or {}).get("saved_count", 0)
    check(st == 200 and saved == 2, "batch-save 保存 2 个知识点", b[:200])

    st, b, _ = req("GET", "/api/dashboard/stats", token=tk)
    s = jbody(b).get("data") or {}
    check(s.get("knowledge_total") == 2 and s.get("subjects") == 1
          and s.get("materials_this_week") == 1 and s.get("knowledge_mastered") == 0,
          "stats 随真实写入联动", str(s))

    # DB 交叉核对（同一 SQL 口径直查）
    from app import create_app
    app = create_app()
    uid = None
    import datetime as _dt
    _now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    _ws = (_now - _dt.timedelta(days=_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    _ws = _ws.strftime("%Y-%m-%d %H:%M:%S")
    with app.app_context():
        from flask import current_app
        conn = current_app.config["DB_CONN_FACTORY"]()
        uid = conn.execute("SELECT user_id FROM users WHERE username = ?", (USER,)).fetchone()[0]
        db_kp = conn.execute("SELECT COUNT(*) FROM knowledge_points WHERE user_id = ?", (uid,)).fetchone()[0]
        db_sub = conn.execute("SELECT COUNT(*) FROM user_subjects WHERE user_id = ?", (uid,)).fetchone()[0]
        q = conn.execute(
            "SELECT COUNT(DISTINCT id) FROM notes WHERE user_id = ? AND "
            "(created_time >= ? OR updated_time >= ?)", (uid, _ws, _ws),
        ).fetchone()[0]
        conn.close()
    check(db_kp == s.get("knowledge_total") and db_sub == s.get("subjects"),
          "stats 数值与 DB 直查一致（knowledge_total/subjects）", f"db={db_kp},{db_sub} api={s}")
    check(q == s.get("materials_this_week"), "materials_this_week 与 DB notes 计数一致", f"db={q} api={s.get('materials_this_week')}")

    # ---------- 3. B组：batch-save 不再 auto-create 科目 ----------
    ghost = "P4CHk幽灵_" + uuid.uuid4().hex[:4]
    st, b, _ = req("POST", "/api/knowledge/batch-save", {
        "filePath": "ghost.md", "subject": ghost,
        "knowledgePoints": [{"name": "n", "description": "d"}]}, tk)
    dg = jbody(b).get("data") or {}
    check(st == 200 and dg.get("success") is False and "不存在" in dg.get("error", ""),
          "幽灵科目 batch-save 被拒（桥协议 data.success=False+中文错误）", f"st={st} {b[:120]}")
    with app.app_context():
        from flask import current_app
        conn = current_app.config["DB_CONN_FACTORY"]()
        n = conn.execute("SELECT COUNT(*) FROM user_subjects WHERE user_id = ? AND subject_name = ?",
                         (uid, ghost)).fetchone()[0]
        conn.close()
    check(n == 0, "幽灵科目未被 auto-create（DB 复核 0 行）")

    # ---------- 4. B组：cleanup 脚本幂等 ----------
    r = subprocess.run([sys.executable,
                        os.path.join(os.path.dirname(os.path.abspath(__file__)), "p4_cleanup.py")],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    check(r.returncode == 0 and "Traceback" not in out
          and __import__("re").search(r"[1-9]\d* FAIL", out) is None,
          "p4_cleanup.py 再次执行幂等（exit 0 且无非零 FAIL 计数）",
          out.replace("\n", " | ")[:250])

    # ---------- 5. C/D组：页面 HTTP 静态断言 ----------
    st, html, _ = req("GET", "/overlay")
    check(st == 200 and 'value="loopback"' in html and 'value="mic"' in html
          and 'value="file"' not in html and "选择音频" not in html,
          "悬浮窗音源仅两项（系统声音/麦克风），演示文件音源已下线", f"st={st}")

    st, html, _ = req("GET", "/fragments/online_course_notes", token=tk)
    frag = jbody(html).get("data", "")
    check(st == 200 and frag, "网课笔记片段加载 200")
    check("llGlobalRec" in frag and "p2RestoreFromGlobal" in frag,
          "全局录音单例 llGlobalRec + 片段恢复逻辑存在（切菜单不断录）")
    import re as _re
    frag_dom = _re.sub(r"<!--.*?-->", "", frag, flags=_re.S)  # 说明注释非 UI
    frag_dom = _re.sub(r"<script.*?</script>", "", frag_dom, flags=_re.S)  # UI 层：排除常驻 JS 死代码字符串
    check('value="mic"' in frag_dom and "系统声音" in frag_dom
          and "刷新并检测活跃设备" not in frag_dom and "录制测试" not in frag_dom,
          "主面板音源二选一 UI，设备检测/录制测试按钮已下线")
    for item in ["深入学习", "开始练习", "重命名", "删除"]:
        check(item in frag, f"统一右键菜单四项之一：{item}")
    check("测试文本" not in frag, "演示假文本兜底已删除")

    st, html, _ = req("GET", "/")
    check(st == 200 and "openUserSettings" in html and "llRefreshUserBadge" in html,
          "工作台壳含用户设置模态入口")
    check("柯基的主人" not in html and "Lv.5" not in html
          and "\">从资料学习<" not in html and "handleMenuClick('learn_materials')" not in html,
          "假数据头像/『从资料学习』菜单项已删除（注释文案不算残留）")
    check("abortChat" in html and "practice-main-container" in html,
          "AI 聊天中断（abortChat）与练习面板在壳层交付")

    # ---------- 6. D组：练习生成 API 真实可用（含服务端兜底题目） ----------
    st, b, _ = req("POST", "/api/practice/generate-questions",
                   {"selected_text": "过拟合是指模型在训练集表现好但在新数据上表现差。"}, tk, timeout=120)
    data = jbody(b).get("data")
    txt = data if isinstance(data, str) else json.dumps(data or {}, ensure_ascii=False)
    check(st == 200 and len(txt.strip()) > 50 and "1." in txt,
          "练习助手出题链路可用（生成/兜底题目非空）", f"st={st} {b[:150]}")

    # ---------- 7. D组：菜单路由合并 ----------
    st, _, hdr = req("GET", "/learn_materials", follow=False)
    check(st == 302 and "/online_course" in hdr.get("Location", ""),
          "/learn_materials 302 → /online_course", f"st={st} loc={hdr.get('Location')}")
    st, b, _ = req("GET", "/fragments/learn_from_materials", token=tk)
    check(st == 404, "/fragments/learn_from_materials 白名单已移除（404）", f"st={st}")

    # ---------- 8. 清理测试数据 ----------
    with app.app_context():
        from flask import current_app
        conn = current_app.config["DB_CONN_FACTORY"]()
        for tbl in ("knowledge_points", "user_subjects", "practice_records",
                    "error_questions", "notes", "users"):
            try:
                conn.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (uid,))
            except Exception:  # noqa: BLE001
                conn.rollback()  # PG 事务 aborted：回滚后继续删其余表
        conn.commit()
        left = conn.execute("SELECT COUNT(*) FROM users WHERE username = ?", (USER,)).fetchone()[0]
        conn.close()
    check(left == 0, "测试账号及关联数据已清理")

    print("\n----")
    print(f"P4 HTTP 自证: {PASS[0]} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for m in FAIL:
            print("  FAILED:", m)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
