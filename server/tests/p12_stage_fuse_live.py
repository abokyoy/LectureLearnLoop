# -*- coding: utf-8 -*-
"""融合轮 rp7 实弹（2026-11-09）：指派自动开工 → 真 DeepSeek 生成原理图舞台。

与断言测试（假 LLM）互补：这里不打桩，真实计费链路，验证两件事——
  ① build_stage_prompt 的真实产出确实守画布契约（MC.validate_scene_content
     "explain" 通过：steps 3~8 / caption≤40 / narration≤160 / canvas≤12000）；
  ② 产出的 canvas_html 里 mc-step 消息监听在位，board_anim_step 推步可用。
一次性测试用户（注册+login 触发每日赠分，另 admin_adjust 兜底），测后删。
产物 canvas_html 落 _p12_canvas.html 供人工目检；结论落 _p12_result.txt。
"""
import base64
import json
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
import credits_service as cr  # noqa: E402
from app import create_app  # noqa: E402
from knowledge_management import DatabaseManager  # noqa: E402
from services import lecture_board as LB  # noqa: E402
from services import micro_course as MC  # noqa: E402

OUT = HERE / "_p12_result.txt"
lines = []
fails = []


def check(cond, label, detail=""):
    lines.append(("PASS  " if cond else "FAIL  ") + label + (f" -> {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(label)


def dump():
    OUT.write_text("\n".join(lines) + f"\n==== {'ALL PASS' if not fails else str(len(fails)) + ' FAIL'} ====\n",
                   encoding="utf-8")


APP = create_app()
client = APP.test_client()

# ---- 一次性测试用户：注册 + login（赠分钩子）----
suffix = uuid.uuid4().hex[:6]
uname = "p12live_" + suffix
client.post("/api/auth/register", json={"username": uname, "password": "test123456"})
r = client.post("/api/auth/login", json={"username": uname, "password": "test123456"})
tok = r.get_json()["data"]["token"]
seg = tok.split(".")[1]
uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
cr.admin_adjust(uid, 300, "融合轮 rp7 实弹充值", "p12live")
bal = cr.get_balance(uid)
check(bal.get("balance", 0) > 0, "H0 测试用户积分就位", str(bal))

# ---- 种子知识点：描述给足证明思路，素材才有料可画 ----
db = DatabaseManager(str(config.DB_PATH))
conn = db.get_connection()
core = ("三角形中位线定理：连接三角形两边中点的线段叫中位线，中位线平行于第三边，"
        "且等于第三边的一半。证明思路：延长中位线 DF 到 G 使 FG=DF，连 CG，"
        "由 SAS 证 △ADE≌△CGE 得四边形 DBCG 是平行四边形，从而 DE∥BC 且 DE=½BC。"
        "常用辅助线还有：过 C 作平行线、取三边中点构造中点四边形。")
cur = conn.execute(
    "INSERT INTO knowledge_points (user_id, subject_name, point_name, core_description, mastery_score)"
    " VALUES (?, ?, ?, ?, ?) RETURNING id",
    (uid, "测试学科P12" + suffix, "三角形中位线定理", core, 40))
kp = cur.fetchone()[0]
conn.commit()

try:
    # ---- H1 指派即自动开工 ----
    res = LB.auto_open_stage(uid, "kp", kp, "三角形中位线定理")
    check(res.get("started"), "H1 auto_open_stage 开工", str(res))
    a = (LB.get_state(uid) or {}).get("anim")
    check(bool(a) and a["state"] == "generating", "H1b 开工即在生成中", json.dumps(a or {}, ensure_ascii=False)[:200])

    # ---- H2 真模型限时出画布 ----
    t0 = time.time()
    a = None
    while time.time() - t0 < 300:
        a = (LB.get_state(uid) or {}).get("anim")
        if a and a["state"] != "generating":
            break
        time.sleep(2)
    cost = round(time.time() - t0, 1)
    check(a and a["state"] == "ready", f"H2 舞台就绪（{cost}s）",
          json.dumps(a or {}, ensure_ascii=False)[:300])
    if a and a["state"] == "ready":
        steps = a["steps"]
        check(3 <= len(steps) <= 8, "H2a steps 数量合规", str(len(steps)))
        check(all(len(s["caption"]) <= MC.MAX_CAPTION_LEN for s in steps), "H2b caption 均≤40")
        check(all(len(s["narration"]) <= MC.STEP_NARR_MAX for s in steps), "H2c narration 均≤160")
        ch = a["canvas_html"]
        check(len(ch) <= MC.MAX_HTML_LEN, "H2d canvas 长度≤12000", str(len(ch)))
        check("addEventListener" in ch and "message" in ch, "H2e canvas 监听 mc-step 消息在位")
        (HERE / "_p12_canvas.html").write_text(ch, encoding="utf-8")
        lines.append("STEP 摘要: " + " | ".join(f"{i}.{s['caption']}" for i, s in enumerate(steps)))

        # ---- H3 就绪信号 + 推步可用 ----
        t = LB.execute_tool("board_write", {"content": "中位线 DE∥BC 且 DE=½BC"}, uid)
        check("[舞台就绪]" in t, "H3a 工具返回带一次性就绪尾注", t[:200])
        t2 = LB.execute_tool("board_anim_step", {"step": 0}, uid)
        check("推进到第 0 步" in t2 and "口播稿" in t2, "H3b 推步返回字幕+口播稿", t2[:200])
        st = LB.get_state(uid)["anim"]
        check(st["current"] == 0, "H3c current 已推进", str(st["current"]))
finally:
    conn.execute("DELETE FROM knowledge_points WHERE id = ?", (kp,))
    conn.execute("DELETE FROM users WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()
    LB._boards.pop(uid, None)
    dump()
print("DONE fails=" + str(len(fails)))
