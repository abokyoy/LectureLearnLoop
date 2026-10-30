# -*- coding: utf-8 -*-
"""填空题拍照判分（2026-10-12 用户反馈：填空答案可能是手写公式）契约单测。

覆盖 _grade_practice_set fill 分支新增行为（LLM/视觉全部打桩，零真实调用）：
- 纯文字填空保持本地精确匹配（不触发视觉/LLM）；
- 作答含 vault 有效图片引用 → 与简答同链路走视觉看图批改；
- 坏图/不可读图 → 忽略并回落本地文字匹配口径，不阻断判分；
- 视觉失败 → 整批失败不落库；积分不足透传（与简答同语义，共用 vision 通道）。

运行方式（server/ 目录）：python -m pytest tests/test_fill_photo_grade.py -v
"""
import shutil
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

UID = "fill_photo_" + uuid.uuid4().hex[:8]
REL_IMG = "截图/填空手写.png"
REL_BAD = "截图/不存在.png"


def _make_img(rel_path: str):
    from PIL import Image
    from config import VAULT_DIR
    p = Path(VAULT_DIR) / UID / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (60, 40), (255, 255, 255)).save(p)


@pytest.fixture(scope="module", autouse=True)
def _vault_img():
    _make_img(REL_IMG)
    yield
    from config import VAULT_DIR
    vault_root = Path(VAULT_DIR) / UID
    if vault_root.exists():
        shutil.rmtree(vault_root, ignore_errors=True)


@pytest.fixture()
def calls(monkeypatch):
    """打桩两条判分通道并记录调用；返回 {llm: [], vision: []}"""
    import routes_bridge
    rec = {"llm": [], "vision": []}
    monkeypatch.setattr(routes_bridge, "_llm_call",
                        lambda prompt, context="": (rec["llm"].append(prompt), "[]")[1])

    def fake_vision(uid, prompt, images, scene):
        rec["vision"].append({"uid": uid, "prompt": prompt, "images": images, "scene": scene})
        return '[{"index": 0, "is_correct": true, "comment": "看图判对"}]'
    monkeypatch.setattr(routes_bridge, "_call_vision", fake_vision)
    return rec


def _grade(qs, ans):
    import routes_bridge
    return routes_bridge._grade_practice_set(UID, qs, ans, "test_fill_grade", "unit")


def _q(question, correct="H2O", expl=""):
    return {"type": "fill", "question": question, "correct_answer": correct, "explanation": expl}


def test_01_fill_text_local_match_no_vision(calls):
    # 纯文字：多写法精确匹配口径不变，零模型调用
    res, err = _grade([_q("水的化学式是 ______。", "H2O|水")], ["H2O"])
    assert err is None and res[0]["is_correct"] is True
    assert calls["llm"] == [] and calls["vision"] == []
    res2, _ = _grade([_q("水的化学式是 ______。", "H2O|水")], ["CO2"])
    assert res2[0]["is_correct"] is False and calls["vision"] == []


def test_02_fill_photo_routes_vision(calls):
    ans = f"手写推导过程见照片\n![手写解答]({REL_IMG})"
    res, err = _grade([_q("某反应产物是 ______。", "H2O")], [ans])
    assert err is None and res[0]["comment"] == "看图判对"
    assert calls["llm"] == [] and len(calls["vision"]) == 1
    v = calls["vision"][0]
    assert v["uid"] == UID and len(v["images"]) == 1 and v["images"][0].get("b64")
    assert v["scene"] == "填空题拍照判分"  # 评审 S-1：场景名区分填空与简答
    # 标准答案与作答文字都要进视觉批改 prompt
    assert "H2O" in v["prompt"] and "手写推导过程见照片" in v["prompt"]


def test_03_fill_broken_image_falls_back_local(calls):
    # 坏图引用：忽略 → 回落本地口径，按残留文字与正确答案比对（不匹配判错，不阻断）
    ans = f"H2O\n![手写解答]({REL_BAD})"
    res, err = _grade([_q("水的化学式是 ______。")], [ans])
    assert err is None and calls["vision"] == [] and calls["llm"] == []
    assert res[0]["is_correct"] is False


def test_04_fill_unreadable_image_falls_back_local(calls):
    # 文件存在但不可解码：payload 过滤后为空 → 回落本地口径，残留图引用串不匹配判错、不阻断
    from config import VAULT_DIR
    p = Path(VAULT_DIR) / UID / "截图" / "坏数据.png"
    p.write_bytes(b"not-a-real-png")
    try:
        ans = f"H2O\n![手写解答](截图/坏数据.png)"
        res, err = _grade([_q("水的化学式是 ______。")], [ans])
        assert err is None and calls["vision"] == []
        assert res[0]["is_correct"] is False  # 残留文字含图引用串，本地口径不匹配
    finally:
        p.unlink(missing_ok=True)


def test_05_fill_vision_failure_whole_batch(calls, monkeypatch):
    import routes_bridge

    def boom(uid, prompt, images, scene):
        raise RuntimeError("视觉服务无响应")
    monkeypatch.setattr(routes_bridge, "_call_vision", boom)
    res, err = _grade([_q("题 ______。")], [f"![手写解答]({REL_IMG})"])
    assert res is None and err["success"] is False


def test_06_fill_insufficient_credits_passthrough(calls, monkeypatch):
    import routes_bridge
    from credits_service import InsufficientCreditsError

    def boom(uid, prompt, images, scene):
        raise InsufficientCreditsError(9.9)
    monkeypatch.setattr(routes_bridge, "_call_vision", boom)
    res, err = _grade([_q("题 ______。")], [f"![手写解答]({REL_IMG})"])
    assert res is None and err["credits_insufficient"] is True and err["credit_balance"] == 9.9


def test_07_mixed_fill_and_short_vision_alignment(calls):
    # 混合卷：填空拍照 + 简答拍照 + 纯文填空，结果按题序对齐、各走各通道
    qs = [_q("填空文字 ______。", "A"), _q("填空拍照 ______。", "B"),
          {"type": "short", "question": "简答拍照", "correct_answer": "要点", "explanation": ""}]
    ans = ["A", f"![手写解答]({REL_IMG})", f"![手写解答]({REL_IMG})"]
    res, err = _grade(qs, ans)
    assert err is None
    assert res[0]["is_correct"] is True and res[0]["comment"] == ""
    assert res[1]["comment"] == "看图判对" and res[2]["comment"] == "看图判对"
    assert len(calls["vision"]) == 2
