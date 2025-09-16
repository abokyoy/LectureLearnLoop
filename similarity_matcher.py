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
import json
import hashlib
import requests
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

# -------- Embedding-based matching (Ollama or configurable) --------

_KP_EMBED_CACHE: Dict[str, Tuple[List[float], str]] = {}
# cache key: f"{model}|{url}|{kp_id}", value: (embedding_vector, version_hash)

def _cfg(cfg: Dict, key: str, default):
    try:
        return cfg.get(key, default) if isinstance(cfg, dict) else default
    except Exception:
        return default

def _points_version(point: Dict) -> str:
    base = f"{point.get('point_name','')}||{point.get('core_description','')}"
    return hashlib.md5(base.encode('utf-8')).hexdigest()

def _embed_ollama(texts: List[str], model: str, url: str, timeout: int = 20) -> List[List[float]]:
    vectors: List[List[float]] = []
    for t in texts:
        payload = {"model": model, "prompt": t}
        resp = requests.post(f"{url.rstrip('/')}/embeddings", json=payload, timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama embeddings API error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        vec = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
        if not vec:
            raise RuntimeError("Invalid embeddings response format")
        vectors.append(vec)
    return vectors

def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    import math
    dot = sum(x*y for x,y in zip(a,b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(y*y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)

def _ensure_kp_embeddings(knowledge_points: List[Dict], cfg: Dict) -> Tuple[Dict[int, List[float]], str, str]:
    """Return mapping {kp_id: vector} and (model, url) used."""
    provider = _cfg(cfg, "embedding_provider", "ollama")
    if provider != "ollama":
        raise RuntimeError("Only 'ollama' provider is currently implemented")
    model = _cfg(cfg, "embedding_model", "nomic-embed-text:latest")
    url = _cfg(cfg, "embedding_api_url", "http://localhost:11434/api")

    # build texts and check cache
    kp_map: Dict[int, List[float]] = {}
    to_compute: List[Tuple[int, str, str]] = []  # (kp_id, text, cache_key)
    for kp in knowledge_points:
        pid = kp.get("id")
        name = kp.get("point_name", "")
        desc = kp.get("core_description", "")
        text = f"{name}\n{desc}".strip()
        version = _points_version(kp)
        key = f"{model}|{url}|{pid}"
        cached = _KP_EMBED_CACHE.get(key)
        if cached and cached[1] == version:
            kp_map[pid] = cached[0]
        else:
            to_compute.append((pid, text, key))
    if to_compute:
        texts = [t for _, t, _ in to_compute]
        vectors = _embed_ollama(texts, model=model, url=url)
        for (pid, _text, key), vec in zip(to_compute, vectors):
            version = _points_version(next(k for k in knowledge_points if k.get("id") == pid))
            _KP_EMBED_CACHE[key] = (vec, version)
            kp_map[pid] = vec
    return kp_map, model, url

def rank_matches(question: str, knowledge_points: List[Dict], cfg: Optional[Dict] = None,
                 top_k: Optional[int] = None, min_score: float = 0.0) -> List[Dict]:
    """Return ranked matches using embeddings if available; fallback to heuristic.
    Returns list of {id, score, point_name} sorted by score desc.
    """
    cfg = cfg or {}
    try:
        kp_embeds, model, url = _ensure_kp_embeddings(knowledge_points, cfg)
        # embed question
        q_vec = _embed_ollama([question], model=model, url=url)[0]
        scored = []
        for kp in knowledge_points:
            pid = kp.get("id")
            vec = kp_embeds.get(pid)
            if not vec:
                continue
            s = _cosine(q_vec, vec)
            if s >= min_score:
                scored.append({
                    "id": pid,
                    "score": float(s),
                    "point_name": kp.get("point_name", "")
                })
        scored.sort(key=lambda x: x["score"], reverse=True)
        if top_k is not None:
            scored = scored[:top_k]
        return scored
    except Exception:
        # fallback
        scored = []
        for kp in knowledge_points:
            s = score_similarity(question, kp.get("point_name", ""), kp.get("core_description", ""))
            if s >= min_score:
                scored.append({"id": kp.get("id"), "score": float(s), "point_name": kp.get("point_name", "")})
        scored.sort(key=lambda x: x["score"], reverse=True)
        if top_k is not None:
            scored = scored[:top_k]
        return scored
