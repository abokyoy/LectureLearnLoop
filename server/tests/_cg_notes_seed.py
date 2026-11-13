# -*- coding: utf-8 -*-
"""课文追问笔记树 E2E 断言 seed（仅测试用户数据，用后即删，零 LLM）。

argv: username out_json
建 goal→module→lesson（content_ready 正文在库 → openLesson 直进阅读步），灌 5 条 lesson_notes：
n1 顶层（锚文本在正文中，可锚定；回答含 mermaid 思路图与哨兵 ANSWER1）、
n2 追问的追问（parent=n1，锚=父回答里的「步长」段 → 九追断言：落在该段之后）、
n2c 追问的追问（parent=n1，锚=选区噪声形态：同一段文本但夹带换行/零宽字符——
    KaTeX 堆叠/表格选区入库即此形态，九追二铁证必须仍命中落位）、
n2b 追问的追问（parent=n1，锚在父回答中不存在 → 降级落节末 kids 容器，内容不丢）、
n3 顶层锚文本不存在（降级右栏「未定位笔记」索引断言用）。
输出 {uid,gid,mid,lid,n1,n2,n2c,n2b,n3} 供 node 断言与清理。"""
import json
import sys

sys.path.insert(0, r"e:\LLM\LectureLearnLoop\server")
from database.db_adapter import get_connection  # noqa: E402

username, out_path = sys.argv[1], sys.argv[2]
conn = get_connection()
urow = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
if not urow:
    raise SystemExit("user not found: " + username)
uid = urow[0]

CONTENT = """# 梯度下降入门

## 核心概念
- 预备知识：导数刻画变化率，为方向选择提供依据。
- 梯度下降通过沿负梯度方向迭代更新参数，学习率决定每步步长。
- 实践中常配合动量项使用，以减缓震荡、加快收敛。
- 正则化改变损失面形状，最优解位置随之移动。

## 范例
设 f(x)=x^2，从 x0=3、eta=0.1 出发迭代三步，逐步靠近极小点的数值演练。

## 小结
方向、步长、迭代三要素构成梯度下降的完整理解链条，缺一不可。
"""

ANS1 = ("损失函数的下降方向由梯度决定，例如负梯度分量含残差导数项 $2e_i$。\n\n"
        "```mermaid\ngraph TB\n  A[损失] --> B[负梯度方向]\n  B --> C[参数更新]\n```\n\n"
        "ANSWER1SENTINEL 步长由学习率控制，过大震荡、过小龟速。")

gid = conn.execute(
    "INSERT INTO learning_goals (user_id, subject_name, goal_text, status) "
    "VALUES (?,?,?,'ready')",
    (uid, "笔记断言学科", "追问笔记树断言专用目标")).lastrowid
mid = conn.execute(
    "INSERT INTO course_modules (goal_id, ord, title, description) "
    "VALUES (?,1,'断言模块N','断言用')", (gid,)).lastrowid
lid = conn.execute(
    "INSERT INTO course_lessons (module_id, ord, title, description, status, content_md, content_mode, pretest_score) "
    "VALUES (?,1,'笔记轮课文','概要N','content_ready',?,'concise',0.8)",
    (mid, CONTENT)).lastrowid


def _note(parent, anchor, q, a):
    return conn.execute(
        "INSERT INTO lesson_notes (user_id, lesson_id, parent_id, anchor_text, question, answer_md) "
        "VALUES (?,?,?,?,?,?) RETURNING id",
        (uid, lid, parent, anchor, q, a)).fetchone()[0]


n1 = _note(None, "梯度下降通过沿负梯度方向迭代更新参数", "Q1SENTINEL 为什么方向取负？", ANS1)
n2 = _note(n1, "步长", "Q2SENTINEL 那步长取多大合适？", "ANSWER2SENTINEL 经验值 0.01~0.1，配学习率衰减。")
n2c = _note(n1, "ANSWER1SENTINEL 步长\n由学习率\u200b控制，过大\n震荡", "Q2CSENTINEL 噪声锚也要归位", "ANSWER2CSENTINEL 去空白归一后命中落段后。")
n2b = _note(n1, "ZZZ父回答里不存在的锚", "Q2BSENTINEL 降级用例", "ANSWER2BSENTINEL 锚不中落节末不丢内容。")
n3 = _note(None, "ZZZ正文里根本不存在的锚点片段", "Q3SENTINEL 这条会降级到索引", "ANSWER3SENTINEL 内容不丢可编辑。")
conn.commit()

res = {"uid": uid, "gid": gid, "mid": mid, "lid": lid, "n1": n1, "n2": n2, "n2c": n2c, "n2b": n2b, "n3": n3}
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False)
print("SEEDED", res)
