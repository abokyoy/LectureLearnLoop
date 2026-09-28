"""探测：DeepSeek 不经代理是否直连可用（决定服务端网络配置）。"""
import sys
sys.path.insert(0, r"e:\LLM\LectureLearnLoop\server")
import httpx
import config

body = {
    "model": config.load_config()["deepseek_model"],
    "messages": [{"role": "user", "content": "回答：1+1=? 只输出数字"}],
    "max_tokens": 8,
}
headers = {"Authorization": "Bearer " + config.load_config()["deepseek_api_key"]}
url = config.load_config()["deepseek_api_url"]

# 直连（无代理）
try:
    r = httpx.post(url, headers=headers, json=body, timeout=25, trust_env=False)
    print("NO-PROXY:", r.status_code, r.json()["choices"][0]["message"]["content"][:30] if r.status_code == 200 else r.text[:100])
except Exception as e:
    print("NO-PROXY FAIL:", type(e).__name__, str(e)[:100])
