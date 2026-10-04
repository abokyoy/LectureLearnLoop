# 批1 UX 交互验证：真实点击窄栏导航，断言内容区切换 + 激活态同步（Playwright headless）
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
OUTFILE = r"e:\LLM\LectureLearnLoop\server\logs\ui_interact_out.txt"
OUT = r"e:\LLM\LectureLearnLoop\design\walkthrough"

# (点击的窄栏项 data-cid, 期望内容区出现的关键词, 期望激活的 data-cid)
CASES = [
    ("online_course_notes", "文件结构", "online_course_notes"),
    ("practice_materials", "练", "practice_materials"),
    ("memory_knowledge", "记", "memory_knowledge"),
    ("knowledge_base", "知识库管理", "knowledge_base"),
    ("settings", "我的积分", "settings"),
    ("dashboard", "学习模块", "dashboard"),
]

lines = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=["--force-device-scale-factor=1"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(f"try{{localStorage.setItem('ll_token','{TOKEN}')}}catch(e){{}}")
    pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
    pg.wait_for_timeout(3000)
    for cid, kw, active in CASES:
        try:
            pg.click(f".cl-nav-item[data-cid='{cid}']", timeout=5000)
            pg.wait_for_timeout(3000)
            body = pg.inner_text("#content-area")
            has_kw = kw in body
            is_active = pg.eval_on_selector(
                f".cl-nav-item[data-cid='{active}']",
                "el => el.classList.contains('cl-active')")
            lines.append(f"click {cid}: keyword '{kw}'={'OK' if has_kw else 'MISSING'} active={is_active}")
        except Exception as e:
            lines.append(f"click {cid}: ERROR {str(e)[:100]}")
    # 悬浮窗按钮存在且可见（不点击：非 Electron 环境会 alert）
    btn = pg.query_selector("#btn-open-overlay")
    lines.append(f"overlay_btn visible={btn.is_visible() if btn else False}")
    # 用户头像按钮点击打开用户设置面板
    try:
        pg.click("#user-avatar-btn", timeout=5000)
        pg.wait_for_timeout(1000)
        vis = pg.evaluate("!!document.querySelector('#user-settings-modal, .user-settings-modal, [id*=user-settings]')")
        lines.append(f"avatar click -> settings modal present={vis}")
    except Exception as e:
        lines.append(f"avatar click ERROR {str(e)[:80]}")
    pg.screenshot(path=OUT + r"\b1_after_interact.png")
    b.close()
open(OUTFILE, "w", encoding="utf-8").write("\n".join(lines))
print("written", OUTFILE)
