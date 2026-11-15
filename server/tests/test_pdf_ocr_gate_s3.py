# -*- coding: utf-8 -*-
"""PDF 文本层乱码率门槛 → 整份自动回落 Paddle OCR（2026-11-02 三段，用户裁定方案A+自动触发）。

背景：文本层优先策略下，CMap 残缺的数学 PDF「命中文本层但产物大量 \ufffd」，旧逻辑不会再走
OCR。真机实测：《测试.pdf》文本层产物 3477 字符含 57 个 \ufffd（1.87%），同文件 Paddle OCR
产物零乱码、40 个 LaTeX 分数（含文本层配对不中的 1/2）。对照《大书.pdf》69917 字符 0 乱码。

规则（_text_layer_garbled，双口径防误杀）：\ufffd 绝对数 ≥ 20 且 占非空白字符比 ≥ 0.5%
才判不可用；worker 命中门槛 → 弃文本层产物，整份回落 Paddle（既有路径）。

运行（server/ 目录）：python -m pytest tests/test_pdf_ocr_gate_s3.py -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import import_service as imp  # noqa: E402


# ---------------------------------------------------------------- 纯函数：判定

def test_clean_text_not_garbled():
    assert imp._text_layer_garbled("") is False
    assert imp._text_layer_garbled("普通笔记，没有乱码。" * 50) is False


def test_real_case_triggers():
    # 《测试.pdf》实测：3477 字符、57 个 \ufffd → 必须判不可用
    body = "北京" * 1700 + "\ufffd" * 57
    assert imp._text_layer_garbled(body) is True


def test_few_scattered_not_triggered():
    # 大文档零星乱码（70000 字符仅 10 个）：占比过低，不误杀
    body = "x" * 69990 + "\ufffd" * 10
    assert imp._text_layer_garbled(body) is False


def test_many_but_low_ratio_not_triggered():
    # 绝对数达标但占比 <0.5%：仍属可用范围（双口径缺一不可）
    body = "y" * 40000 + "\ufffd" * 25
    assert imp._text_layer_garbled(body) is False


def test_threshold_boundary():
    # 恰好 20 个且占比过线 → 触发；19 个 → 不触发
    body20 = "z" * 500 + "\ufffd" * 20
    body19 = "z" * 500 + "\ufffd" * 19
    assert imp._text_layer_garbled(body20) is True
    assert imp._text_layer_garbled(body19) is False


# ---------------------------------------------------------------- worker 接入

def _fake_jsonl(text: str) -> str:
    return json.dumps({"result": {"layoutParsingResults": [
        {"markdown": {"text": text, "images": {}}}]}}) + "\n"


def _run_worker(tmp_path, monkeypatch, layer_ret, jsonl_text):
    """跑 _pdf_worker，返回 (落盘 md 文本, paddle 提交次数)。"""
    import services.paddle_doc_client as paddle
    calls = {"submit": 0}

    def fake_submit(path):
        calls["submit"] += 1
        return "fake-job-g"

    monkeypatch.setattr(paddle, "submit_job", fake_submit)
    monkeypatch.setattr(paddle, "query_job",
                        lambda jid: {"state": "done",
                                     "resultUrl": {"jsonUrl": "http://x.invalid/r.jsonl"}})
    monkeypatch.setattr(paddle, "download_jsonl", lambda url: jsonl_text)
    monkeypatch.setattr(imp, "POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(imp, "extract_pdf_text_layer", lambda *a, **kw: layer_ret)
    monkeypatch.setattr(imp, "update_task", lambda tid, **kw: None)
    monkeypatch.setattr(imp, "sync_note_content", lambda uid, p, c: True)

    pdf = tmp_path / "附件" / "测试.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 fake")
    target = tmp_path / "测试.md"
    imp._pdf_worker("t1", "u1", pdf, target)
    return (target.read_text(encoding="utf-8") if target.exists() else None), calls["submit"]


def test_garbled_layer_falls_back_to_ocr(tmp_path, monkeypatch):
    garbled = "\ufffd" * 30 + "正文" * 100          # ≥20 且占比高 → 门槛触发
    _, submits = _run_worker(tmp_path, monkeypatch, (garbled, 4),
                             _fake_jsonl("则 $\\frac{a}{x}=\\frac{x}{a-x}$，即可求解"))
    target = tmp_path / "测试.md"
    md = target.read_text(encoding="utf-8")
    assert submits == 1, "乱码文本层未回落 Paddle"
    assert "\\frac{a}{x}" in md and "\ufffd" not in md


def test_clean_layer_still_skips_ocr(tmp_path, monkeypatch):
    clean = "内嵌文本层充足的普通讲义，零乱码，不该耗远端额度。" * 10
    _, submits = _run_worker(tmp_path, monkeypatch, (clean, 2), _fake_jsonl("不该被用到"))
    assert submits == 0, "正常文本层被误回落 OCR（回退不零 diff）"
    md = (tmp_path / "测试.md").read_text(encoding="utf-8")
    assert md == clean
