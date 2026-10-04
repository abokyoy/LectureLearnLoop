# 批8 验证：admin_credits + llm_logs 重设计
# HTTP 断言（主题残留/新结构）+ Playwright 真实交互（统计回填/详情展开/过滤/403 提示路径）
import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b8_verify.txt"
SHOT = r"e:\LLM\LectureLearnLoop\design\walkthrough"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
HDR = {"Authorization": "Bearer " + TOKEN}

lines = []
errs = []


def chk(name, cond):
    lines.append(f"{name}: {cond}")


# ---------- HTTP 断言 ----------
# 残留检查作用域：页面片段源文件（整页 HTML 含壳层侧边栏 onclick，会误报）
adm_src = open(r"e:\LLM\LectureLearnLoop\server\templates\pages\admin_credits.html", encoding="utf-8").read()
lg_src = open(r"e:\LLM\LectureLearnLoop\server\templates\pages\llm_logs.html", encoding="utf-8").read()
adm = requests.get(BASE + "/admin/credits", headers=HDR, timeout=15).text
lg = requests.get(BASE + "/llm_logs", headers=HDR, timeout=15).text
chk("adm_new_system", "cl-page" in adm and 'data-adm-page="credits"' in adm and "pm_pages.js" in adm)
chk("adm_no_legacy_purple", "#7048e8" not in adm_src and "adm-btn" not in adm_src)
chk("adm_all_blocks", all(x in adm for x in ["credit-config-rows", "llm-config-rows", "users-body", "codes-body"]))
chk("logs_new_system", "cl-page" in lg and 'data-log-page="llm"' in lg and "pm_pages.js" in lg)
chk("logs_no_legacy", "#32C77F" not in lg_src and "onkeyup" not in lg_src and "log-viewer" not in lg_src)
chk("logs_no_unsafe_inline", "onclick=" not in lg_src and "window.toggleLogDetail" not in lg_src)
r1 = requests.get(BASE + "/api/llm/logs?limit=5", headers=HDR, timeout=20).json()
chk("api_llm_logs_ok", r1.get("success") is True and isinstance(r1.get("data"), list))
r2 = requests.get(BASE + "/api/llm/stats", headers=HDR, timeout=20).json()
chk("api_llm_stats_ok", r2.get("success") is True and isinstance(r2.get("data"), dict))
r3 = requests.get(BASE + "/api/admin/users", headers=HDR, timeout=20).json()
is_admin = r3.get("success") is True
lines.append(f"account_is_admin: {is_admin}")
# best-effort：日志记录存在进程内存，重启后为空；触发一次最小 LLM 调用制造真实数据（失败不算证）
try:
    rc = requests.post(BASE + "/api/llm/call", headers=HDR,
                       json={"prompt": "reply OK", "context": "b8_smoke"}, timeout=60)
    lines.append(f"seed_llm_call: status={rc.status_code} ok={rc.json().get('success')}")
except Exception as e:
    lines.append(f"seed_llm_call: skipped ({e})")

# ---------- Playwright 交互 ----------
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror:" + str(e)))
    # 非管理员访问 admin 端点返回 403 属预期路径，不计入 JS 错误
    pg.on("console", lambda m: errs.append("console.error:" + m.text)
          if m.type == "error" and "403" not in m.text else None)
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)

    # llm_logs：HTTP 回落通路（浏览器无 bridge）
    pg.goto(BASE + "/llm_logs", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    st_total = pg.locator("#st-total").inner_text()
    chk("logs_stats_filled", st_total not in ("--", "", "加载中…"))
    container_txt = pg.locator("#logs-container").inner_text()
    has_rows = pg.locator("tr[data-call-id]").count()
    chk("logs_rows_or_empty", has_rows > 0 or ("暂无日志" in container_txt) or ("加载日志失败" in container_txt))
    if has_rows > 0:
        first_detail_id = pg.locator("tr[data-call-id]").first.get_attribute("data-call-id")
        pg.click(f"tr[data-call-id='{first_detail_id}']")
        pg.wait_for_timeout(300)
        detail_visible = pg.locator(f"#detail-{first_detail_id}").is_visible()
        chk("logs_detail_expand", detail_visible)
        # 过滤：输入不存在的串 → 空态
        pg.fill("#filter-input", "zzz_不存在_zzz")
        pg.wait_for_timeout(400)
        chk("logs_filter_empty", pg.locator("tr[data-call-id]").count() == 0)
        pg.fill("#filter-input", "")
        pg.wait_for_timeout(400)
        # 刷新
        pg.click("#refresh-btn")
        pg.wait_for_timeout(1200)
        chk("logs_after_refresh", pg.locator("#st-total").inner_text() not in ("--", ""))
    pg.screenshot(path=SHOT + r"\b8_llm_logs.png", full_page=True)

    # admin_credits：非管理员 → 顶部 403 提示；管理员 → 数据回填。页面都必须完整渲染
    pg.goto(BASE + "/admin/credits", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    cards = pg.locator(".cl-card").count()
    chk("adm_cards_4", cards == 4)
    top_msg = pg.locator("#adm-top-msg").inner_text()
    if is_admin:
        users_rows = pg.locator("#users-body tr").count()
        chk("adm_admin_data_filled", users_rows >= 1)
    else:
        chk("adm_403_hint", ("失败" in top_msg) or ("管理员" in top_msg))
        chk("adm_no_loading_residue", "加载中" not in pg.locator("#users-body").inner_text()
            and "加载中" not in pg.locator("#codes-body").inner_text())
    pg.screenshot(path=SHOT + r"\b8_admin.png", full_page=True)

    b.close()

lines.append("JS_ERRORS: " + (str(errs[:8]) if errs else "NONE"))
open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
