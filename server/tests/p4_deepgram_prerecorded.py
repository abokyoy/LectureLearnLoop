"""P4 步骤1：用 Deepgram 预录 REST 接口转写 lecture_sample.wav，验证 key/网络/转写质量。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

API_KEY = "a88b5a5a7e9a750bcc8f984ac48a2c9f62bcaef4"
WAV = Path(__file__).parent / "fixtures" / "lecture_sample.wav"


def main() -> int:
    data = WAV.read_bytes()
    print(f"wav bytes: {len(data)}")
    url = "https://api.deepgram.com/v1/listen?model=nova-2&language=multi&punctuate=true&smart_format=true"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Token {API_KEY}", "Content-Type": "audio/wav"},
        content=data,
        timeout=120,
    )
    print("http status:", resp.status_code)
    if resp.status_code != 200:
        print(resp.text[:2000])
        return 1
    body = resp.json()
    try:
        alt = body["results"]["channels"][0]["alternatives"][0]
        transcript = alt["transcript"]
        words = alt.get("words", [])
    except (KeyError, IndexError):
        print(json.dumps(body, ensure_ascii=False)[:2000])
        return 1
    print(f"word_count: {len(words)}")
    print(f"is_final: {body['results'].get('is_final')}")
    print("transcript head:", transcript[:300])
    ok = ("eigenvalue" in transcript.lower() or "eigen" in transcript.lower()) and len(words) > 50
    print("RESULT:", "PASS" if ok else "FAIL")
    (Path(__file__).parent / "fixtures" / "lecture_transcript.txt").write_text(
        transcript, encoding="utf-8")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
