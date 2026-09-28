"""诊断：上传 p6_audio 到 Deepgram，打印完整响应结构（去掉冗长 words）。"""
import json
import sys
from pathlib import Path
import httpx

DG_KEY = "a88b5a5a7e9a750bcc8f984ac48a2c9f62bcaef4"
FIX = Path(__file__).parent / "fixtures"
audio = sorted(FIX.glob("p6_audio.*"))[0]
ctype = {"mp4": "audio/mp4", "m4a": "audio/mp4", "webm": "audio/webm"}.get(audio.suffix.lstrip("."), "application/octet-stream")
r = httpx.post("https://api.deepgram.com/v1/listen?model=nova-2&language=multi&punctuate=true",
               headers={"Authorization": f"Token {DG_KEY}", "Content-Type": ctype},
               content=audio.read_bytes(), timeout=600)
b = r.json()
b.get("results", {}).pop("utterances", None)
if "results" in b and "channels" in b["results"]:
    for ch in b["results"]["channels"]:
        for alt in ch.get("alternatives", []):
            alt["words"] = f"<{len(alt.get('words', []))} words>"
print("status", r.status_code)
print(json.dumps(b, ensure_ascii=False, indent=2)[:3000])
