"""
Low-coupling similarity matcher for mapping questions to knowledge points.
- No external dependencies
- Pluggable and replaceable in the future

Primary API:
    best_match(question: str, knowledge_points: list[dict]) -> dict | None
        knowledge_points item example:
            {"id": 1, "point_name": "HTTP协议", "core_description": "超文本传输协议..."}

Returns:
    A dict {"id": int, "score": float} if a suitable match is found, else None

Notes:
- Current scoring combines normalized token Jaccard overlap and SequenceMatcher ratio
- Simple CN/EN tokenization by splitting on non-word characters and CJK boundaries
- Thresholds are conservative to avoid misclassification; tune via kwargs if needed
"""
from __future__ import annotations
from typing import List, Dict, Optional, Tuple
import re
from difflib import SequenceMatcher

_CJK_RANGE = (
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x20000, 0x2A6DF), # CJK Extension B
)

def _is_cjk(char: str) -> bool:
    code = ord(char)
    for lo, hi in _CJK_RANGE:
        if lo <= code <= hi:
            return True
    return False

def _normalize(text: str) -> str:
    text = text.lower().strip()
    # remove markdown/code fences and angle-think tags
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"<think>[\s\S]*?</think>", " ", text, flags=re.IGNORECASE)
    return text

def _tokenize(text: str) -> List[str]:
    text = _normalize(text)
    # Split into tokens: keep CJK as single-char tokens; split others by non-word
    tokens: List[str] = []
    buff = []
    for ch in text:
        if _is_cjk(ch):
            if buff:
                tokens.extend(re.findall(r"\w+", "".join(buff)))
                buff = []
            tokens.append(ch)
        else:
            buff.append(ch)
    if buff:
        tokens.extend(re.findall(r"\w+", "".join(buff)))
    # Remove very short tokens
    tokens = [t for t in tokens if len(t) >= 2 or _is_cjk(t[:1])]
    return tokens

def _jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0

def _seqratio(a: str, b: str) -> float:
    a_n, b_n = _normalize(a), _normalize(b)
    return SequenceMatcher(a=a_n, b=b_n).ratio()

def score_similarity(query: str, point_name: str, core_desc: str) -> float:
    # Token-based Jaccard on question vs (name + desc)
    q_tokens = _tokenize(query)
    p_tokens = _tokenize(f"{point_name} {core_desc}")
    jacc = _jaccard(q_tokens, p_tokens)

    # Sequence ratio on whole strings
    seq = _seqratio(query, f"{point_name} {core_desc}")

    # Weighted combination; tune weights as needed
    score = 0.6 * seq + 0.4 * jacc
    return score

def best_match(question: str, knowledge_points: List[Dict], *, min_score: float = 0.35) -> Optional[Dict]:
    """Return best matching knowledge point by simple similarity.

    Args:
        question: question text (or error question content)
        knowledge_points: list of {id, point_name, core_description}
        min_score: minimum score to accept a match
    Returns:
        {"id": int, "score": float} or None
    """
    if not question or not knowledge_points:
        return None

    best_id = None
    best_score = 0.0
    for kp in knowledge_points:
        pid = kp.get("id")
        name = kp.get("point_name", "")
        desc = kp.get("core_description", "")
        s = score_similarity(question, name, desc)
        if s > best_score:
            best_score = s
            best_id = pid

    if best_id is None or best_score < min_score:
        return None
    return {"id": best_id, "score": best_score}
