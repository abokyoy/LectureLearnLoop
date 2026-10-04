# Material Icons Outlined 字体本地化（走查 G4：去 CDN 依赖，Electron 离线可用）
# 1) 拉取 Google Fonts CSS（带 woff2 UA） 2) 下载 woff2 到 static/fonts 3) 生成本地 CSS
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import requests, re, os

PROXY = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
STATIC = r"e:\LLM\LectureLearnLoop\server\static"

r = requests.get("https://fonts.googleapis.com/icon?family=Material+Icons+Outlined", headers=UA, proxies=PROXY, timeout=30)
r.raise_for_status()
css = r.text
m = re.search(r'url\((https://[^)]+\.woff2)\)', css)
if not m:
    print("NO woff2 url found:", css[:300]); sys.exit(1)
font_url = m.group(1)
fr = requests.get(font_url, headers=UA, proxies=PROXY, timeout=60)
assert fr.status_code == 200 and len(fr.content) > 10000, (fr.status_code, len(fr.content))
os.makedirs(os.path.join(STATIC, "fonts"), exist_ok=True)
open(os.path.join(STATIC, "fonts", "MaterialIconsOutlined.woff2"), "wb").write(fr.content)

local_css = css.replace(font_url, "../fonts/MaterialIconsOutlined.woff2")
os.makedirs(os.path.join(STATIC, "css"), exist_ok=True)
open(os.path.join(STATIC, "css", "material-icons-outlined.css"), "w", encoding="utf-8").write(local_css)
print("OK font bytes:", len(fr.content))
print("OK css:", local_css[:200].replace("\n", " "))
