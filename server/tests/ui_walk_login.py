# 走查账号注册/登录，输出 token 供浏览器注入
import json, sys, requests

BASE = "http://127.0.0.1:6001"
U, P = "ui_walk_2026", "Walkpass123"

requests.post(BASE + "/api/auth/register", json={"username": U, "password": P}, timeout=15)
r = requests.post(BASE + "/api/auth/login", json={"username": U, "password": P}, timeout=15)
r.raise_for_status()
tok = r.json()["data"]["token"]
with open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", "w", encoding="utf-8") as f:
    f.write(tok)
print("OK token_len=", len(tok))
