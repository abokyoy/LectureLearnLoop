# 生成 A/C 混合主题定稿候选（橙主行动+薄荷绿辅助）
# 调用登记：2026-10-01 本脚本 1 次 generate_screen_from_text
import sys, io, os, json, re, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stitch_client import rpc
import requests

PROXY = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}
OUTDIR = r"e:\LLM\LectureLearnLoop\design\stitch_candidates"
PID = "16843602892954821186"
TAG = "D_orange_mint_mix"

PROMPT = """设计一个在线学习 SaaS 产品的「工作台」页面（桌面端，1280x900，中文界面）。
产品名称：柯基的学习乐园（面向学生的 AI 学习助手，学-练-记闭环）。
布局要求：
- 左侧窄图标侧边栏：工作台、学、练、记、知识库、设置 六个导航项（图标+文字），底部用户头像
- 顶部简洁标题栏
- 主区域：三张功能卡片（学习模块/练习模块/记忆模块），每张含图标、标题、一句说明、一个关键数字、一个操作按钮
- 卡片下方：「最近学习活动」列表区（含 2-3 条示例活动）
- 现代极简 SaaS 风格：大留白、圆角卡片(rounded-xl)、极细边框、微弱阴影、清晰字号层级，拒绝后台管理系统感
配色方案（混合主题）：背景米白暖灰；主行动色用柔和橙(#F97316系)只用于主按钮与关键数字强调；辅助色用薄荷绿(#10B981系)用于进度条、成功徽标与「记」模块点缀；整体明快轻松、略带小可爱、面向学生。橙色为主、绿色为辅，不得两色同权重打架。
"""

for attempt in range(4):
    try:
        st, j = rpc("tools/call", {"name": "generate_screen_from_text",
                                   "arguments": {"projectId": PID, "prompt": PROMPT, "deviceType": "DESKTOP"}},
                    timeout=240)
        break
    except Exception as e:
        print("attempt", attempt + 1, "failed:", str(e)[:100])
        time.sleep(8)
else:
    print("ALL FAILED"); sys.exit(1)

txt = json.dumps(j, ensure_ascii=False)
print(TAG, "HTTP", st, "len", len(txt))
with open(os.path.join(OUTDIR, TAG + "_resp.json"), "w", encoding="utf-8") as f:
    f.write(txt)
urls = [u for u in re.findall(r'https://[^"\s\\]+', txt) if "lh3.googleusercontent" in u]
sess = requests.Session(); sess.proxies = PROXY
ok = False
for u in urls[:2]:
    try:
        r = sess.get(u, timeout=60)
        if r.status_code == 200 and r.content[:4] == b"\x89PNG":
            p = os.path.join(OUTDIR, TAG + ".png")
            open(p, "wb").write(r.content)
            print("saved", p, len(r.content)); ok = True; break
    except Exception as e:
        print("dl err", str(e)[:80])
print("DONE", ok)
