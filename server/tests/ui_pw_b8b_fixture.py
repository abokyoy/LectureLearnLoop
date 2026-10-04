# 批8b：llm_logs 有数据渲染路径验证
# 背景：/api/llm/logs 记录存于 Flask 进程内存，服务重启后为空；真实 LLM 调用受测试账号积分限制（402）。
# 方法：Playwright 网络层 mock /api/llm/logs 与 /api/llm/stats 返回 fixture（页面代码路径完全真实），
#       验证表格渲染、统计回填、行点击展开详情、搜索过滤、刷新重载、CSV 字段转义渲染安全（含恶意字符防注入）。
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:6001"
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b8b_verify.txt"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()

FIXTURE_LOGS = [
    {
        "call_id": "c1", "timestamp": "2026-10-01 10:00:00", "provider": "DeepSeek",
        "model": "deepseek-chat", "context": "知识点提取", "success": True,
        "total_duration": 1.2, "time_to_first_byte": 0.3, "prompt_length": 500,
        "response_length": 800, "api_endpoint": "https://api.deepseek.com/x",
        "status_code": 200, "prompt_preview": "p1", "response_preview": "r1", "error_message": "",
    },
    {
        # 慢调用 + 失败 + 恶意注入串（验证 esc 全覆盖）
        "call_id": "c2<img src=x onerror=alert(1)>", "timestamp": "2026-10-01 10:01:00", "provider": "Gemini",
        "model": "gemini-2.0-flash", "context": "笔记追问\"><script>alert(2)</script>", "success": False,
        "total_duration": 6.5, "time_to_first_byte": 5.1, "prompt_length": 300,
        "response_length": 0, "api_endpoint": "/v1/chat", "status_code": 500,
        "prompt_preview": "<b>bold</b>", "response_preview": "", "error_message": "timeout '<x'>",
    },
    {
        "call_id": "c3", "timestamp": "2026-10-01 10:02:00", "provider": "Ollama",
        "model": "qwen2.5", "context": None, "success": True,
        "total_duration": 3.0, "time_to_first_byte": 1.0, "prompt_length": 10,
        "response_length": 20, "api_endpoint": "/api/generate", "status_code": 200,
        "prompt_preview": "p3", "response_preview": "r3", "error_message": None,
    },
]
FIXTURE_STATS = {"total_calls": 3, "successful_calls": 2, "success_rate": 66.7,
                 "avg_duration": 3.57, "avg_first_byte_time": 2.13}

lines = []
errs = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror:" + str(e)))
    pg.on("console", lambda m: errs.append("console.error:" + m.text) if m.type == "error" else None)

    def route_logs(route):
        route.fulfill(status=200, content_type="application/json",
                      body='{"success": true, "data": %s}' % __import__("json").dumps(FIXTURE_LOGS))

    def route_stats(route):
        route.fulfill(status=200, content_type="application/json",
                      body='{"success": true, "data": %s}' % __import__("json").dumps(FIXTURE_STATS))

    pg.route("**/api/llm/logs*", route_logs)
    pg.route("**/api/llm/stats*", route_stats)

    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/llm_logs", wait_until="networkidle")
    pg.wait_for_timeout(1200)

    rows = pg.locator("tr[data-call-id]").count()
    lines.append(f"render_rows_eq3: {rows == 3}")
    lines.append(f"stats_filled: total={pg.locator('#st-total').inner_text()} "
                 f"ok={pg.locator('#st-ok').inner_text()} rate={pg.locator('#st-rate').inner_text()}")
    # 空 context 行显示"未知"
    lines.append(f"context_null_fallback: {'未知' in pg.locator('#logs-container').inner_text()}")
    # 注入防护：页面 DOM 中不应出现可执行的 img/script 注入节点
    injected = pg.locator("#logs-container img[src='x']").count() + pg.locator("#logs-container script").count()
    lines.append(f"xss_escaped(no injected nodes): {injected == 0}")
    # 详情展开
    pg.click("tr[data-call-id^='c2']")
    pg.wait_for_timeout(300)
    detail_vis = pg.evaluate("document.querySelector('tr[id^=\"detail-c2\"]').className.indexOf('hidden') < 0")
    lines.append(f"detail_expand: {detail_vis}")
    # 过滤
    pg.fill("#filter-input", "ollama")
    pg.wait_for_timeout(400)
    lines.append(f"filter_ollama_1row: {pg.locator('tr[data-call-id]').count() == 1}")
    pg.fill("#filter-input", "不存在zzz")
    pg.wait_for_timeout(400)
    lines.append(f"filter_empty_state: {'暂无日志记录' in pg.locator('#logs-container').inner_text()}")
    pg.fill("#filter-input", "")
    pg.wait_for_timeout(400)
    # 刷新（重新走 mock）
    pg.click("#refresh-btn")
    pg.wait_for_timeout(1000)
    lines.append(f"refresh_rows: {pg.locator('tr[data-call-id]').count() == 3}")
    # 耗时颜色分级：c2>5s 应为 danger 类
    cls_slow = pg.evaluate("document.querySelector('tr[data-call-id^=\"c2\"] td:nth-child(6)').className")
    lines.append(f"slow_duration_class: {'text-cl-danger' in cls_slow}")
    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\design\walkthrough\b8b_llm_logs_data.png", full_page=True)
    b.close()

lines.append("JS_ERRORS: " + (str(errs[:6]) if errs else "NONE"))
open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
