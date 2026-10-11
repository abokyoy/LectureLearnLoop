"""薄弱点分析报告服务（错题学习单元升级 P4）。

输入错题集素材（题干/我的答案/正确答案/解析 + 所属知识点名），LLM 输出一份
结构化 JSON 报告：
    {summary_md: str, nodes: [{name, kind:'kp'|'point', status:'ok'|'weak',
                               evidence:[error_id], children:[...]}]}
- 知识点维度（kind=kp）+ 错题总结点维度（kind=point）；解析步骤中掌握的标 ok、
  丢分环节标 weak（计划裁定）；
- 严格校验：结构非法/summary 空/nodes 空/层级或数量超限 → 抛 ValueError，
  调用方据此**不落库**（失败不产生半成品报告，也不 Retry 重发请求）；
- evidence 只保留素材中真实存在的错题 ID（过滤幻觉 ID，防「针对练习」闭环
  拿不存在的 error_id 组卷）；
- 计费走调用方 LLM 链路现有口径（billing_for_response），本模块不碰积分。

设计为纯函数 + 注入 llm_call(prompt)->str，路由层负责取素材、计费与落库；
测试可注入 fake llm_call 断言 prompt 与校验分支，不产生真实消耗。
"""
from __future__ import annotations

import json
import re

MAX_ITEMS = 60          # 送分析的错题上限（超限取排序前 60，防 prompt 爆长）
MAX_DEPTH = 5           # 脑图树最大层数（防 LLM 无限套娃）
MAX_NODES = 200         # 节点总数上限
_NODE_KINDS = ("kp", "point")
_NODE_STATUSES = ("ok", "weak")

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def build_prompt(subject: str, items: list[dict]) -> str:
    """错题集 → 分析 prompt。items 元素键：error_id/kp_name/question/user_answer/correct/explanation。"""
    lines = []
    for it in items:
        lines.append(
            f"- 错题ID {it['error_id']}｜知识点：{it.get('kp_name') or '（独立错题）'}\n"
            f"  题干：{str(it.get('question') or '')[:400]}\n"
            f"  我的答案：{str(it.get('user_answer') or '')[:200]}\n"
            f"  正确答案：{str(it.get('correct') or '')[:200]}\n"
            f"  解析：{str(it.get('explanation') or '')[:400]}")
    material = "\n".join(lines)
    return f"""你是学习诊断专家。请根据以下学科「{subject}」的错题记录，输出一份薄弱点分析报告。

**错题记录（共 {len(items)} 条，每条含我的错误答案与正解解析）：**
{material}

**输出要求：**
1. summary_md：Markdown 文字报告，包含：总体情况、错误模式与共性错因、薄弱点优先级排序、每个薄弱点的复习建议；数学公式用 $...$ 标注；
2. nodes：脑图树根节点数组（第一层为知识点维度或错题总结维度），每个节点字段：
   - name：节点名（不超过 20 字）
   - kind："kp"（知识点）或 "point"（错因/总结点，如"符号展开失误"）
   - status："ok"（掌握尚可）或 "weak"（薄弱丢分）——依据解析步骤判断：解析中做对的环节标 ok，丢分环节标 weak
   - evidence：支撑该节点结论的错题ID数组（只能取上面列出的错题ID，可为空数组）
   - children：同结构子节点数组（可为空），第二层建议为从解析拆出的总结点

只返回一个 JSON 对象，不要任何其他文字：
{{"summary_md": "...", "nodes": [{{"name": "...", "kind": "kp", "status": "weak", "evidence": [1], "children": []}}]}}"""


def extract_json_object(text: str) -> dict:
    """剥围栏取首个 JSON 对象；本地修复（尾逗号）后仍失败抛 ValueError，绝不重发请求。"""
    t = (text or "").strip()
    m = _JSON_FENCE_RE.search(t)
    if m:
        t = m.group(1).strip()
    elif t.startswith("```"):
        nl = t.find("\n")
        if nl >= 0:
            t = t[nl + 1:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    candidates = [t]
    s, e = t.find("{"), t.rfind("}")
    if s >= 0 and e > s:
        cand = t[s:e + 1]
        candidates += [cand, _TRAILING_COMMA_RE.sub(r"\1", cand)]
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("模型返回不可解析为 JSON 对象")


def validate_report(obj: dict, valid_ids: set[int]) -> dict:
    """严格结构校验 + 归一；非法抛 ValueError（调用方不落库）。"""
    summary = obj.get("summary_md")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("报告缺少 summary_md")
    nodes = obj.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("nodes 必须为非空数组")
    budget = {"n": 0}

    def _walk(arr, depth):
        if depth > MAX_DEPTH:
            raise ValueError(f"脑图层级超过 {MAX_DEPTH} 层")
        out = []
        for nd in arr:
            if not isinstance(nd, dict):
                raise ValueError("脑图节点必须为对象")
            budget["n"] += 1
            if budget["n"] > MAX_NODES:
                raise ValueError(f"脑图节点数超过 {MAX_NODES}")
            name = str(nd.get("name") or "").strip()
            if not name or len(name) > 50:
                raise ValueError("节点 name 非法（空或超长）")
            if nd.get("kind") not in _NODE_KINDS:
                raise ValueError(f"节点 kind 非法：{nd.get('kind')!r}")
            if nd.get("status") not in _NODE_STATUSES:
                raise ValueError(f"节点 status 非法：{nd.get('status')!r}")
            ev_raw = nd.get("evidence")
            if ev_raw is None:
                ev_raw = []
            if not isinstance(ev_raw, list):
                raise ValueError("节点 evidence 必须为数组")
            ev = []
            for x in ev_raw:
                try:
                    xi = int(x)
                except (TypeError, ValueError):
                    raise ValueError("evidence 含非整数项")
                if xi not in valid_ids:
                    continue  # 幻觉 ID 过滤：闭环只允许针对真实错题
                if xi not in ev:
                    ev.append(xi)
            ch = nd.get("children")
            if ch is None:
                ch = []
            if not isinstance(ch, list):
                raise ValueError("节点 children 必须为数组")
            out.append({"name": name, "kind": nd["kind"], "status": nd["status"],
                        "evidence": ev, "children": _walk(ch, depth + 1)})
        return out

    cleaned = _walk(nodes, 1)
    has_node = budget["n"] > 0
    if not has_node:
        raise ValueError("脑图无有效节点")
    return {"summary_md": summary.strip(), "nodes": cleaned}


def generate_report(subject: str, items: list[dict], llm_call) -> dict:
    """素材 → LLM → 校验后报告 {summary_md, nodes, error_count}；LLM/校验异常原样上抛。"""
    if not items:
        raise ValueError("没有可用于分析的错题")
    items = items[:MAX_ITEMS]
    raw = llm_call(build_prompt(subject, items))
    if not raw:
        raise RuntimeError("LLM调用失败")
    rep = validate_report(extract_json_object(raw), {int(it["error_id"]) for it in items})
    rep["error_count"] = len(items)
    return rep
