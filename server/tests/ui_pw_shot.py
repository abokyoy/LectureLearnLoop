# Playwright headless 批量截图：UI 走查/重设计验证的稳定通道（不依赖任何窗口状态）
# 页面主体走 /fragments/<cid>（绕开 SPA 直访 URL 被 dashboard 覆盖的产品 bug）
# 用法: python ui_pw_shot.py
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\design\walkthrough"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

PAGES = [
    ("01_dashboard", "/"),
    ("06_practice", "/practice"),
    ("09_note_picker", "/note-picker"),
    ("10_capture", "/capture"),
    ("11_overlay", "/overlay"),
]
# SPA 壳内切换页（真实产品路径：loadContent 替换 content-area，保留壳+样式）
SPA_PAGES = [
    ("02_online_course", "online_course_notes"),
    # 批1 UX 验证补：练 落地页截图缺失，补上
    ("12_practice_materials", "practice_materials"),
    ("03_knowledge_base", "knowledge_base"),
    ("04_settings", "settings"),
    ("05_llm_logs", "llm_logs"),
    ("08_admin_credits", "admin_credits"),
    ("13_memory_knowledge", "memory_knowledge"),
    ("14_memory_errors", "memory_errors"),
    ("15_practice_knowledge", "practice_knowledge"),
    ("16_practice_errors", "practice_errors"),
]

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=[
        "--force-device-scale-factor=1",
        "--proxy-server=http://127.0.0.1:10808",
        "--ignore-certificate-errors",
    ])
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(f"try{{localStorage.setItem('ll_token','{TOKEN}')}}catch(e){{}}")
    pg = ctx.new_page()
    for name, path in PAGES:
        try:
            pg.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
            try:
                pg.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            pg.wait_for_timeout(2500)
            pg.screenshot(path=rf"{OUT}\{name}.png", full_page=False)
            print("OK ", name)
        except Exception as e:
            print("ERR", name, str(e)[:120])
    # SPA 壳内切换截图：先回 '/'，再 loadContent(cid)
    for name, cid in SPA_PAGES:
        try:
            pg.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(2000)
            pg.evaluate(f"window.bridge.loadContent('{cid}')")
            pg.wait_for_timeout(3500)
            pg.screenshot(path=rf"{OUT}\{name}.png", full_page=False)
            print("OK ", name)
        except Exception as e:
            print("ERR", name, str(e)[:120])
    # 登录页（无 token 场景）
    ctx2 = b.new_context(viewport={"width": 1280, "height": 900})
    pg2 = ctx2.new_page()
    pg2.goto(BASE + "/login", wait_until="domcontentloaded", timeout=30000)
    pg2.wait_for_timeout(2000)
    pg2.screenshot(path=rf"{OUT}\07_login.png")
    print("OK  07_login")
    b.close()
print("done")
