# 批6 验证：设置页重设计（真实数据渲染 + 交互 + SPA 日志跳转 + 无桥依赖）
# 注意：不点击"清空日志"（llm_call_logger 为全局记录，清空影响所有账号观察日志），仅验证按钮与端点契约
from playwright.sync_api import sync_playwright
import requests

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b6_verify.txt"

errs = []
lines = []

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append("pageerror:" + str(e)))
    pg.on("console", lambda m: errs.append("console.error:" + m.text) if m.type == "error" else None)
    pg.goto(BASE + "/login", wait_until="domcontentloaded")
    pg.evaluate("t => localStorage.setItem('ll_token', t)", TOKEN)
    pg.goto(BASE + "/", wait_until="networkidle")
    pg.wait_for_timeout(2500)

    pg.evaluate("() => handleMenuClick('settings')")
    pg.wait_for_timeout(3000)

    # 1. 积分卡：真实数字（非占位 --）且接口已回填
    bal = pg.locator("#cr-balance").inner_text()
    used = pg.locator("#cr-used").inner_text()
    lines.append(f"credits: balance='{bal}' used='{used}' placeholder_cleared={bal != '--' and used != '--'}")

    # 2. 流水表已加载（非"加载中…"残留；行数可为 0 → 显示暂无）
    tx = pg.locator("#cr-tx-body").inner_text()
    lines.append(f"tx_table: loading_residue={'加载中' not in tx} rows={pg.locator('#cr-tx-body tr').count()}")

    # 3. AI 配置区：当前状态文案 + 系统状态文案（均来自真实接口）
    cur = pg.locator("#llm-current").inner_text()
    sys_ = pg.locator("#llm-sys-state").inner_text()
    lines.append(f"llm: current='{cur[:30]}' sys_state_non_empty={len(sys_) > 0}")

    # 4. 总结设置真实回填
    interval = pg.locator("#auto-interval").input_value()
    mode = pg.locator("#summary-mode").input_value()
    lines.append(f"summary_cfg: interval='{interval}' mode='{mode}' filled={interval != ''}")

    # 5. 开关交互：点 peer switch 切换启用状态
    before = pg.evaluate("() => document.getElementById('llm-enabled').checked")
    pg.click("#llm-enabled + span")
    after = pg.evaluate("() => document.getElementById('llm-enabled').checked")
    lines.append(f"switch_toggle: before={before} after={after} works={before != after}")
    pg.click("#llm-enabled + span")  # 还原

    # 6. 空卡密兑换反馈（不真正消耗卡密）
    pg.click("#cr-redeem-btn")
    pg.wait_for_timeout(500)
    m = pg.locator("#cr-redeem-msg").inner_text()
    lines.append(f"redeem_empty_guard: msg='{m}' ok=('请输入卡密' in m)")

    # 7. 查看日志 → SPA 跳转 llm_logs（旧 Qt 桥依赖已移除）
    pg.click("#st-open-logs")
    pg.wait_for_timeout(2500)
    gone = pg.locator("#cr-balance").count() == 0
    lines.append(f"go_llm_logs: navigated={gone}")
    pg.evaluate("() => handleMenuClick('settings')")
    pg.wait_for_timeout(2000)

    # 8. 清空日志按钮存在（不点击：全局日志清空调用会破坏所有账号的观察数据）
    lines.append(f"clear_btn_present={pg.locator('#st-clear-logs').count() == 1} [NOT clicked by design]")

    # 9. 旧手写 CSS 与桥依赖确认下线（针对 settings 片段源文件断言，pg.content() 含壳层于扰）
    frag = requests.get(BASE + "/fragments/settings", headers={"Authorization": "Bearer " + TOKEN}, timeout=15).text
    lines.append(f"legacy_removed: config_group={'config-group' not in frag} bridge_call={'window.bridge' not in frag} material_icon={'material-icons' not in frag} native_style_block={'<style>' not in frag}")

    pg.screenshot(path=r"e:\LLM\LectureLearnLoop\design\walkthrough\b6_settings.png", full_page=True)

    lines.append("JS_ERRORS: " + (str(errs[:6]) if errs else "NONE"))
    b.close()

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
