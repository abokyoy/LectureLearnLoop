# 补生成 B_indigo_calm 单主题候选（A/C 已成功，避免重复耗额度）
# 调用登记：2026-10-01 本脚本 1 次 generate_screen_from_text
import sys, io, os, json, re, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stitch_client import rpc
import requests

PROXY = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}
OUTDIR = r"e:\LLM\LectureLearnLoop\design\stitch_candidates"
PID = "16843602892954821186"
TAG = "B_indigo_calm"

LAYOUT = """设计一个在线学习 SaaS 产品的「工作台」页面（桌面端，1280x900，中文界面）。
产品名称：柯基的学习乐园（面向学生的 AI 学习助手，学-练-记闭环）。
布局要求：
- 左侧窄图标侧边栏：工作台、学、练、记、知识库、设置 六个导航项（图标+文字），底部用户头像
- 顶部简洁标题栏
- 主区域：三张功能卡片（学习模块/练习模块/记忆模块），每张含图标、标题、一句说明、一个关键数字、一个操作按钮
- 卡片下方：「最近学习活动」列表区（含 2-3 条示例活动）
- 现代极简 SaaS 风格：大留白、圆角卡片(rounded-xl)、极细边框、微弱阴影、清晰字号层级，拒绝后台管理系统感
"""
THEME = "配色方向B：冷静靛蓝。主色靛蓝/indigo(#4F46E5系)克制使用于主按钮与进度，整体无彩色黑白灰基调，专业专注感。"

prompt = LAYOUT + "\n" + THEME
for attempt in range(4):
    try:
        st, j = rpc("tools/call", {"name": "generate_screen_from_text",
                                   "arguments": {"projectId": PID, "prompt": prompt, "deviceType": "DESKTOP"}},
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
urls = re.findall(r'https://[^\s"\\]+', txt)
dl = [u for u in urls if any(k in u.lower() for k in ("png", "jpg", "jpeg", "download", "screenshot", "storage"))]
sess = requests.Session(); sess.proxies = PROXY
for i, u in enumerate(dl[:5]):
    try:
        resp = sess.get(u, timeout=60)
        if resp.status_code == 200 and len(resp.content) > 5000:
            ext = ".png" if u.lower().find("png") >= 0 else ".jpg"
            p = os.path.join(OUTDIR, TAG + f"_{i}" + ext)
            open(p, "wb").write(resp.content)
            print("saved", p, len(resp.content))
            break
    except Exception as e:
        print("dl err", str(e)[:80])
print("DONE")
