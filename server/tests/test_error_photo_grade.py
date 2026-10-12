# -*- coding: utf-8 -*-
"""简答题拍照判分（2026-10-15 用户需求）契约单测：判分分流与视觉通道。

覆盖 _grade_practice_set 新增行为（LLM/视觉全部打桩，零真实调用）：
- 纯文字简答仍走 LLM 批量文本判分（不触发视觉）；
- 作答或题干含 vault 有效图片 → 逐题走视觉通道（call_llm_vision 同链路，scene/prompt/images 契约）；
- 混合卷结果按题序对齐；
- 任一视觉题失败 → 整批失败不落库（与文字通道同口径）；积分不足透传；
- 坏图引用（文件不存在）→ 忽略并回落文字通道，不阻断判分。

运行方式（server/ 目录）：python -m pytest tests/test_error_photo_grade.py -v
"""
import shutil
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

UID = "photo_grade_" + uuid.uuid4().hex[:8]
REL_IMG = "截图/手写过程.png"
REL_BAD = "截图/不存在图.png"


def _make_img(rel_path: str):
    from PIL import Image
    from config import VAULT_DIR  # 与 _user_vault_root 同源，保证测试图落在真实解析路径上
    p = Path(VAULT_DIR) / UID / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (60, 40), (255, 255, 255)).save(p)


def _ans_md(text=""):
    return (text + "\n" if text else "") + f"![手写解答]({REL_IMG})"


def _llm_arr(n, correct=True):
    import json
    return json.dumps([{"index": i, "is_correct": correct, "comment": f"批{ i}"} for i in range(n)],
                      ensure_ascii=False)


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
                        lambda prompt, context="": (rec["llm"].append(prompt), _llm_arr(1))[1])
    def fake_vision(uid, prompt, images, scene):
        rec["vision"].append({"uid": uid, "prompt": prompt, "images": images, "scene": scene})
        return '[{"index": 0, "is_correct": true, "comment": "看图判对"}]'
    monkeypatch.setattr(routes_bridge, "_call_vision", fake_vision)
    return rec


def _grade(qs, ans):
    import routes_bridge
    return routes_bridge._grade_practice_set(UID, qs, ans, "test_grade", "unit")


def _q(type_, question, correct, expl=""):
    return {"type": type_, "question": question, "correct_answer": correct, "explanation": expl}


def test_01_text_short_not_vision(calls):
    res, err = _grade([_q("short", "何为行列式？", "按行展开")], ["按行展开"])
    assert err is None
    assert res[0]["is_correct"] is True
    assert len(calls["llm"]) == 1 and calls["vision"] == []


def test_02_photo_answer_routes_vision(calls):
    res, err = _grade([_q("short", "求解 $x+1=2$", "x=1")], [_ans_md("")])
    assert err is None and res[0]["comment"] == "看图判对"
    assert calls["llm"] == [] and len(calls["vision"]) == 1
    v = calls["vision"][0]
    assert v["uid"] == UID and v["scene"] == "简答题拍照判分"
    assert len(v["images"]) == 1 and v["images"][0].get("b64")
    assert "1 张附图" in v["prompt"] and "x=1" in v["prompt"]


def test_03_stem_image_also_vision(calls):
    # 复题图片在题干（错题重组常见），作答纯文字也须看图批改
    qs = [_q("short", f"如图求角 $B$ ![题图]({REL_IMG})", "70°")]
    res, err = _grade(qs, ["70度"])
    assert err is None and len(calls["vision"]) == 1 and calls["llm"] == []
    assert "70°" in calls["vision"][0]["prompt"]


def test_04_mixed_alignment(calls):
    qs = [_q("single", "选A?", "A"), _q("short", "简答文字", "要点"),
          _q("short", "简答拍照", "要点2", "解析二"), _q("judge", "对?", "正确")]
    ans = ["A", "答了要点", _ans_md("补充一句"), "正确"]
    res, err = _grade(qs, ans)
    assert err is None
    assert res[0]["is_correct"] is True and res[3]["is_correct"] is True
    assert len(calls["llm"]) == 1 and len(calls["vision"]) == 1
    assert res[1]["comment"] == "批0"  # 文字批量通道结果
    assert res[2]["comment"] == "看图判对"  # 视觉通道覆盖到正确题序
    assert "解析二" in calls["vision"][0]["prompt"]
    assert "补充一句" in calls["vision"][0]["prompt"]


def test_05_vision_failure_whole_batch(calls, monkeypatch):
    import routes_bridge
    def boom(uid, prompt, images, scene):
        raise RuntimeError("视觉服务无响应")
    monkeypatch.setattr(routes_bridge, "_call_vision", boom)
    res, err = _grade([_q("short", "拍照题", "答")], [_ans_md()])
    assert res is None and err["success"] is False
    assert "拍照答案判分失败" in err["error"]


def test_06_insufficient_credits_passthrough(calls, monkeypatch):
    import routes_bridge
    from credits_service import InsufficientCreditsError
    def boom(uid, prompt, images, scene):
        raise InsufficientCreditsError(12.5)
    monkeypatch.setattr(routes_bridge, "_call_vision", boom)
    res, err = _grade([_q("short", "拍照题", "答")], [_ans_md()])
    assert res is None and err["credits_insufficient"] is True
    assert err["credit_balance"] == 12.5


def test_07_broken_image_falls_back_text(calls):
    # 图片引用文件不存在 → 忽略坏图、按文字通道判分，不阻断整批
    res, err = _grade([_q("short", "题", "答")], [f"我的答案\n![手写解答]({REL_BAD})"])
    assert err is None and calls["vision"] == [] and len(calls["llm"]) == 1


def test_08_no_answer_photo_only_ok(calls):
    # 纯照片作答（无文字）不应被当作未作答
    res, err = _grade([_q("short", "题", "答")], [f"![手写解答]({REL_IMG})"])
    assert err is None and len(calls["vision"]) == 1
    assert "解答以照片为准" in calls["vision"][0]["prompt"]


def test_09_unreadable_image_falls_back_text(calls):
    # 评审 m2：文件存在但不可解码（坏图）→ 丢弃不阻断，回落文字通道
    from config import VAULT_DIR
    p = Path(VAULT_DIR) / UID / "截图" / "坏数据.png"
    p.write_bytes(b"not-a-real-png")
    try:
        res, err = _grade([_q("short", "题", "答")], [f"我的答案\n![手写解答](截图/坏数据.png)"])
        assert err is None and res[0]["is_correct"] is True
        assert calls["vision"] == [] and len(calls["llm"]) == 1
    finally:
        p.unlink(missing_ok=True)
