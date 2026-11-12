# -*- coding: utf-8 -*-
"""课文图文结合 E2E 断言 seed（仅测试用户数据，用后即删）。

argv: username out_json
建 goal→module→lesson（content_md 含 2 个合法 mermaid 块 + 1 个坏语法块 + 公式），
再经 principle_cache 预置该课文 principle 轨 done 产物（展示位直显断言，零 LLM）。
输出 {uid,gid,mid,lid} 供 node 断言与清理。"""
import json
import sys

sys.path.insert(0, r"e:\LLM\LectureLearnLoop\server")
from database.db_adapter import get_connection  # noqa: E402
from services import principle_cache as PC  # noqa: E402

username, out_path = sys.argv[1], sys.argv[2]
conn = get_connection()
urow = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
if not urow:
    raise SystemExit("user not found: " + username)
uid = urow[0]

MD = """# 梯度下降入门

## 概览
这是图文结合断言专用课文，含两张合法思路图、一张坏语法图与公式 $f(x) = x^2$。学习率记作 $\\eta$。

```mermaid
graph TD
A[损失函数] --> B[求梯度]
B --> C[更新参数]
C --> A
```

## 核心概念
沿负梯度方向迭代更新，学习率决定步长：$x_{k+1} = x_k - \\eta \\nabla f(x_k)$。步长过大震荡，过小迟缓。

```mermaid
graph LR
输入 --> 步长计算
步长计算 --> 收敛判定
收敛判定 --> 输出
```

## 范例
下面这张图语法非法，前端必须降级保留原文，不得炸整篇课文：

```mermaid
BADGRAPH ### ThisIsNotAType
```

## 重点摘要
概念、图示、公式三者互不侵犯：公式 $\\eta=0.1$ 只出现在正文，图块只画流程。
"""

gid = conn.execute(
    "INSERT INTO learning_goals (user_id, subject_name, goal_text, status) "
    "VALUES (?,?,?,'ready')",
    (uid, "图文断言学科", "课文图文结合断言专用目标")).lastrowid
mid = conn.execute(
    "INSERT INTO course_modules (goal_id, ord, title, description) "
    "VALUES (?,1,'断言模块V','断言用')", (gid,)).lastrowid
lid = conn.execute(
    "INSERT INTO course_lessons (module_id, ord, title, description, status, content_md, pretest_score, content_mode) "
    "VALUES (?,1,'梯度下降入门','概要V','content_ready',?,0.5,'full')",
    (mid, MD)).lastrowid
conn.commit()

r = PC.put(str(uid), "course_lesson", f"{lid}:principle", {
    "title": "断言原理图", "narration": "直显断言用",
    "html": "<!DOCTYPE html><html><body><h1>SENTINEL_VIS_PRINCIPLE</h1></body></html>",
    "warning": ""}, mode="off")
if not r.get("success"):
    raise SystemExit("principle_cache seed 失败: " + json.dumps(r, ensure_ascii=False))

res = {"uid": uid, "gid": gid, "mid": mid, "lid": lid}
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False)
print("SEEDED", res)
