# Stitch 生成 3 套工作台主题候选（批0 设计系统定稿用）
# 调用登记：2026-10-01 本脚本共 1 次 create_project + 3 次 generate_screen_from_text = 4 次
import json, sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stitch_client import rpc
import requests

PROXY = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}
OUTDIR = r"e:\LLM\LectureLearnLoop\design\stitch_candidates"
os.makedirs(OUTDIR, exist_ok=True)

LAYOUT = """设计一个在线学习 SaaS 产品的「工作台」页面（桌面端，1280x900，中文界面）。
产品名称：柯基的学习乐园（面向学生的 AI 学习助手，学-练-记闭环）。
布局要求：
- 左侧窄图标侧边栏：工作台、学、练、记、知识库、设置 六个导航项（图标+文字），底部用户头像
- 顶部简洁标题栏
- 主区域：三张功能卡片（学习模块/练习模块/记忆模块），每张含图标、标题、一句说明、一个关键数字、一个操作按钮
- 卡片下方：「最近学习活动」列表区（含 2-3 条示例活动）
- 现代极简 SaaS 风格：大留白、圆角卡片(rounded-xl)、极细边框、微弱阴影、清晰字号层级，拒绝后台管理系统感
"""

THEMES = [
    ("A_corgi_orange", "配色方向A：温暖柯基橙。主色柔和橙色(#F97316系)用于主按钮与强调数字，背景米白暖灰，整体明快友好略带可爱，辅助文字低对比灰。"),
    ("B_indigo_calm", "配色方向B：冷静靛蓝。主色靛蓝/indigo(#4F46E5系)克制使用于主按钮与进度，整体无彩色黑白灰基调，专业专注感。"),
    ("C_mint_fresh", "配色方向C：清新薄荷绿。主色薄荷/翠绿(#10B981系)用于主按钮与徽标，背景浅冷灰白，护眼轻松的学习氛围。"),
]

import re
st, j = rpc("tools/call", {"name": "list_projects", "arguments": {}}, timeout=90)
txt = json.dumps(j, ensure_ascii=False)
pid = None
tp = txt.find('"CorgiStudy UI Redesign"')
if tp >= 0:
    seg = txt[:tp]
    pm = re.search(r'projects/(\d+)(?!.*projects/\d+)', seg, re.S)
    if pm:
        pid = pm.group(1)
if not pid:
    st, j = rpc("tools/call", {"name": "create_project", "arguments": {"title": "CorgiStudy UI Redesign"}})
    txt = json.dumps(j, ensure_ascii=False)
    print("create_project HTTP", st, txt[:300])
    m = re.search(r'"projectId"\s*:\s*"?(\d+)', txt) or re.search(r'projects/(\d+)', txt)
    if not m:
        print("!! projectId not found, abort"); sys.exit(1)
    pid = m.group(1)
else:
    print("reuse existing project")
print("projectId =", pid)

results = []
for tag, theme in THEMES:
    prompt = LAYOUT + "\n" + theme
    st = None
    for attempt in range(3):  # 代理瞬断自动重试（CONNECT 阶段失败不计入服务端额度）
        try:
            st, j = rpc("tools/call", {"name": "generate_screen_from_text",
                                       "arguments": {"projectId": pid, "prompt": prompt, "deviceType": "DESKTOP"}},
                        timeout=240)
            break
        except Exception as e:
            print(tag, "attempt", attempt + 1, "failed:", str(e)[:100])
            time.sleep(5)
    else:
        results.append({"tag": tag, "urls": [], "raw_head": "ALL RETRIES FAILED"})
        continue
    txt = json.dumps(j, ensure_ascii=False)
    print(tag, "HTTP", st, "len", len(txt))
    # 尝试找截图/输出 URL
    urls = re.findall(r'https://[^\s"\\]+', txt)
    dl = [u for u in urls if any(k in u.lower() for k in ("png", "jpg", "jpeg", "download", "screenshot", "storage"))]
    results.append({"tag": tag, "urls": list(dict.fromkeys(dl))[:5], "raw_head": txt[:800]})
    with open(os.path.join(OUTDIR, f"{tag}_resp.json"), "w", encoding="utf-8") as f:
        f.write(txt)
    time.sleep(2)

sess = requests.Session(); sess.proxies = PROXY
for r in results:
    for i, u in enumerate(r["urls"]):
        try:
            resp = sess.get(u, timeout=60)
            if resp.status_code == 200 and len(resp.content) > 5000:
                ext = ".png" if u.lower().find("png") >= 0 else ".jpg"
                p = os.path.join(OUTDIR, r["tag"] + f"_{i}" + ext)
                open(p, "wb").write(resp.content)
                print("saved", p, len(resp.content))
                break
        except Exception as e:
            print("dl err", str(e)[:80])
print("DONE project", pid)
