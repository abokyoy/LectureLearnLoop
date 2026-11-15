# -*- coding: utf-8 -*-
"""course_service 题包生成/校验 + 详略判定断言（LLM 全 monkeypatch）。

运行方式（server/ 目录）：python -m pytest tests/test_course_quiz.py -v
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import course_service as cs  # noqa: E402


def _qs(n=4):
    return [{"stem": f"题干{i}", "options": [f"甲{i}", f"乙{i}", f"丙{i}", f"丁{i}"],
             "answer_index": i % 4, "kp_name": f"知识点{i}", "explanation": f"解析{i}"}
            for i in range(n)]


def _pack(n=4):
    return json.dumps({"questions": _qs(n)}, ensure_ascii=False)


def test_validate_ok():
    out = cs.validate_questions(_qs())
    assert len(out) == 4
    assert out[0]["answer_index"] == 0 and len(out[0]["options"]) == 4
    # dict 包装形态同样接受
    assert len(cs.validate_questions({"questions": _qs()})) == 4


@pytest.mark.parametrize("bad", [
    [],                     # 题数不足 n_min
    _qs(3),                 # 3 < 4
    [{"stem": "", "options": ["a", "b", "c", "d"], "answer_index": 0,
      "kp_name": "k", "explanation": "e"}] * 4,             # stem 空
    [dict(_qs()[0], options=["a", "b", "c"])] + _qs()[1:],   # 选项数 != 4
    [dict(_qs()[0], answer_index=4)] + _qs()[1:],            # answer_index 越界
    [dict(_qs()[0], answer_index="1")] + _qs()[1:],          # answer_index 非 int
    [dict(_qs()[0], answer_index=True)] + _qs()[1:],         # bool 不算 int
    [dict(_qs()[0], kp_name="  ")] + _qs()[1:],              # kp_name 空
    "not a list",
])
def test_validate_reject(bad):
    with pytest.raises(cs.CourseError):
        cs.validate_questions(bad)


def test_validate_n_max():
    with pytest.raises(cs.CourseError):
        cs.validate_questions(_qs(11), n_min=4, n_max=10)


def test_decide_mode():
    assert cs.decide_mode(1.0) == "concise"
    assert cs.decide_mode(0.75) == "full"
    assert cs.decide_mode(0.0) == "full"


def test_generate_retry_once(monkeypatch):
    calls = []

    def fake(prompt, scene=""):
        calls.append(prompt)
        return "垃圾" if len(calls) == 1 else _pack()
    monkeypatch.setattr(cs, "_llm", fake)
    out = cs.generate_test_pack("pretest", "课文主题内容块", 4)
    assert len(out) == 4 and len(calls) == 2


def test_generate_fail_twice(monkeypatch):
    monkeypatch.setattr(cs, "_llm", lambda prompt, scene="": "垃圾")
    with pytest.raises(cs.CourseError):
        cs.generate_test_pack("postquiz", "全文", 4)


def test_generate_kind_templates(monkeypatch):
    cap = []

    def fake(prompt, scene=""):
        cap.append(prompt)
        return _pack(8)
    monkeypatch.setattr(cs, "_llm", fake)
    # moduleexam 题量下限 6：n=8 通过
    out = cs.generate_test_pack("moduleexam", "模块下课文标题清单", 8)
    assert len(out) == 8
    assert "模块下课文标题清单" in cap[0]
    with pytest.raises(ValueError):
        cs.generate_test_pack("unknown_kind", "x", 4)
