"""P6 证据层1：真实 YouTube 视频 → 音频下载 → Deepgram 转写（预录 REST，language=multi）。
产物：tests/fixtures/p6_audio.<ext> + p6_transcript.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

import yt_dlp

VIDEO_URL = "https://www.youtube.com/watch?v=aJydWxn2zRk"
FIX = Path(__file__).parent / "fixtures"
FIX.mkdir(exist_ok=True)
OUT_TMPL = str(FIX / "p6_audio.%(ext)s")


def download_audio() -> Path:
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": OUT_TMPL,
        "quiet": True,
        "noplaylist": True,
        # 不依赖 ffmpeg：直接落原始流容器
        "merge_output_format": None,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(VIDEO_URL, download=True)
        ext = info.get("ext")
        title = info.get("title")
        dur = info.get("duration")
    print(f"title: {title}\nduration: {dur}s ext: {ext}")
    p = FIX / f"p6_audio.{ext}"
    if not p.exists():
        cands = list(FIX.glob("p6_audio.*"))
        assert cands, "音频下载失败：未找到产物"
        p = cands[0]
    print("saved:", p, p.stat().st_size, "bytes")
    return p


if __name__ == "__main__":
    try:
        download_audio()
    except Exception as e:  # noqa: BLE001
        print("DOWNLOAD FAIL:", e)
        sys.exit(1)
