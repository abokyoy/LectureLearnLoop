"""对照诊断：1) 上传已知英文 wav (multi) 应非空；2) 上传视频 wav 用 zh-CN / 不同模型。"""
from pathlib import Path
import httpx

DG = "a88b5a5a7e9a750bcc8f984ac48a2c9f62bcaef4"
FIX = Path(__file__).parent / "fixtures"


def call(fn, query, ctype):
    r = httpx.post(f"https://api.deepgram.com/v1/listen?{query}",
                   headers={"Authorization": f"Token {DG}", "Content-Type": ctype},
                   content=(FIX / fn).read_bytes(), timeout=600)
    if r.status_code != 200:
        return f"HTTP{r.status_code} {r.text[:120]}"
    b = r.json()
    alt = b["results"]["channels"][0]["alternatives"][0]
    return f"dur={b['metadata'].get('duration')} len={len(alt.get('transcript',''))} head={alt.get('transcript','')[:60]}"


print("[control EN/multi]", call("lecture_sample.wav", "model=nova-2&language=multi", "audio/wav"))
print("[video zh-CN]", call("p6_audio.wav", "model=nova-2&language=zh-CN", "audio/wav"))
print("[video multi detect]", call("p6_audio.wav", "model=nova-2&language=multi&detect_language=true", "audio/wav"))
