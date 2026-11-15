# -*- coding: utf-8 -*-
"""course_service 课程结构生成与校验断言（LLM 全部 monkeypatch，不烧积分）。

运行方式（server/ 目录）：python -m pytest tests/test_course_gen.py -v
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import course_service as cs  # noqa: E402


def _mods(nm=4, nl=4):
    return {"modules": [{"title": f"模块{i}", "description": f"说明{i}",
                         "lessons": [{"title": f"课文{i}-{j}", "description": "d",
                                      "est_minutes": 30} for j in range(nl)]}
                        for i in range(nm)]}


def test_validate_ok():
    out = cs.validate_course_structure(_mods())
    assert len(out["modules"]) == 4
    assert out["modules"][0]["lessons"][0]["est_minutes"] == 30
    assert out["modules"][0]["description"] == "说明0"


def test_validate_defaults():
    d = {"modules": [{"title": "m%d" % i,
                      "lessons": [{"title": "l%d-%d" % (i, j)} for j in range(3)]} for i in range(3)]}
    out = cs.validate_course_structure(d)
    assert out["modules"][0]["lessons"][0]["est_minutes"] == 30
    assert out["modules"][0]["lessons"][0]["description"] == ""
    assert out["modules"][0]["description"] == ""


@pytest.mark.parametrize("bad", [
    {},
    {"modules": []},
    {"modules": [{"title": "m", "lessons": []}] * 3},
    {"modules": [{"title": "", "lessons": [{"title": "l", "est_minutes": 30}] * 3}] * 3},
    {"modules": [{"title": "m%d" % i, "lessons": [{"title": "l%d" % i}] * 2} for i in range(3)]},
    {"modules": [{"title": "m%d" % i, "lessons": [{"title": "l%d" % i}] * 3} for i in range(9)]},
    "not a dict",
])
def test_validate_reject(bad):
    with pytest.raises(cs.CourseError):
        cs.validate_course_structure(bad)


def test_validate_est_whitelist():
    d = _mods()
    d["modules"][0]["lessons"][0]["est_minutes"] = 37
    with pytest.raises(cs.CourseError):
        cs.validate_course_structure(d)


def test_validate_dup_title():
    d = _mods()
    d["modules"][1]["lessons"][0]["title"] = d["modules"][0]["lessons"][0]["title"]
    with pytest.raises(cs.CourseError):
        cs.validate_course_structure(d)


def test_extract_json_fenced():
    assert cs.extract_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert cs.extract_json("前缀废话\n{\"a\": 2}\n后缀废话") == {"a": 2}
    with pytest.raises(ValueError):
        cs.extract_json("彻底不是 JSON")


def test_generate_retry_then_fail(monkeypatch):
    calls = []

    def fake(prompt, scene=""):
        calls.append(prompt)
        return "not json"
    monkeypatch.setattr(cs, "_llm", fake)
    with pytest.raises(cs.CourseError):
        cs.generate_course_structure("学机器学习", "机器学习", [])
    assert len(calls) == 2  # 重试 1 次后放弃


def test_generate_fenced_json(monkeypatch):
    def fake(prompt, scene=""):
        return "```json\n" + json.dumps(_mods()) + "\n```"
    monkeypatch.setattr(cs, "_llm", fake)
    out = cs.generate_course_structure("学机器学习", "机器学习", ["过拟合"])
    assert out["modules"][0]["title"] == "模块0"
    assert len(out["modules"][0]["lessons"]) == 4


def test_generate_prompt_contains_context(monkeypatch):
    cap = []

    def fake(prompt, scene=""):
        cap.append(prompt)
        return json.dumps(_mods())
    monkeypatch.setattr(cs, "_llm", fake)
    cs.generate_course_structure("我想学X", "X科", ["知识点甲"])
    assert "我想学X" in cap[0] and "X科" in cap[0] and "知识点甲" in cap[0]
