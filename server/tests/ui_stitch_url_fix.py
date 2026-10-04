# 分析 A/C 响应中的 URL，并测试下载（不走代理直连 lh3 vs 走代理）
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import requests

for tag in ("B_indigo_calm",):
    p = rf"e:\LLM\LectureLearnLoop\design\stitch_candidates\{tag}_resp.json"
    t = open(p, encoding="utf-8").read()
    us = list(dict.fromkeys(re.findall(r'https://[^"\s\\]+', t)))
    print("==", tag, "urls:", len(us))
    for u in us[:8]:
        print("  ", u[:150])
    # 试下载第一个疑似图片 URL，两种网络方式对比
    cand = [u for u in us if "googleusercontent" in u or ".png" in u or ".jpg" in u]
    if cand:
        u = cand[0]
        for name, px in (("proxy", {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}), ("direct", {})):
            try:
                r = requests.get(u, proxies=px, timeout=30)
                print("  dl", name, r.status_code, len(r.content), r.content[:12])
                if r.status_code == 200 and r.content[:3] != b"<!D" and len(r.content) > 5000:
                    open(rf"e:\LLM\LectureLearnLoop\design\stitch_candidates\{tag}_fix_{name}.img", "wb").write(r.content)
                    print("  saved img via", name)
                    break
            except Exception as e:
                print("  dl", name, "err", str(e)[:80])
