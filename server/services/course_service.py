# -*- coding: utf-8 -*-
"""目标导向学习（体系化课程）LLM 编排服务。

设计权威源：docs/superpowers/specs/2026-11-11-goal-driven-learning-design.md §6
职责：课程结构 / 题包 / 课文 三类 LLM 生成 + 严格校验（LLM 输出不可信原则：
校验失败重试 1 次，仍败抛 CourseError，绝不落脏数据）。

口径约定（AGENTS.md / 计划 Global Constraints）：
- LLM 只走本模块 _llm() 单缝（内部统一 call_llm，自动走积分计费链；
  余额不足抛 credits_service.InsufficientCreditsError，原样上抛由路由层转 402，
  不视为可重试错误）；测试 monkeypatch cs._llm，不烧积分。
- JSON 剥围栏复用 services.weakness_report.extract_json_object（公共函数注册制，不另造）。
- 落库与判分不在本模块（归 routes_courses / course 练习链复用现有 save_practice_record）。
"""
from __future__ import annotations

from services.weakness_report import extract_json_object

# 课程结构规模白名单（spec §6：模块 3~8，每模块课文 3~8；est 四档）
MODULE_MIN, MODULE_MAX = 3, 8
LESSON_MIN, LESSON_MAX = 3, 8
EST_CHOICES = (15, 30, 45, 60)
EST_DEFAULT = 30
_TITLE_MAX = 60


class CourseError(Exception):
    """课程生成链业务错误（校验失败/结构非法/LLM 返回不可用）。路由层转 400/502。"""


def _llm(prompt: str, scene: str) -> str:
    """LLM 唯一出口缝。计费/Provider 选择全部收敛在 call_llm（请求上下文有用户即计费）。"""
    from llm_provider_factory import call_llm
    return call_llm(prompt, scene=scene)


# 对外别名：与既有编排服务同名同义（剥围栏取 JSON 对象，失败抛 ValueError）
extract_json = extract_json_object


def _clean_title(v) -> str:
    t = str(v or "").strip()
    if not t or len(t) > _TITLE_MAX:
        raise CourseError(f"标题非法（空或超{_TITLE_MAX}字）: {v!r}")
    return t


def _read_lesson_item(l, seen) -> dict:
    """单篇课文条目归一化（标题去重入 seen + est 白名单），违规抛 CourseError。

    validate_course_structure 与 validate_extension 共用（公共函数注册制，防口径漂移）。"""
    if not isinstance(l, dict):
        raise CourseError("课文必须是 JSON 对象")
    lt = _clean_title(l.get("title"))
    if lt in seen:
        raise CourseError(f"标题重复: {lt}")
    seen.add(lt)
    est = l.get("est_minutes", EST_DEFAULT)
    if est is None:
        est = EST_DEFAULT
    if est not in EST_CHOICES:
        raise CourseError(f"est_minutes 非法: {est!r}（只允许 {EST_CHOICES}）")
    return {"title": lt,
            "description": str(l.get("description") or "").strip(),
            "est_minutes": est}


def validate_course_structure(data) -> dict:
    """LLM 返回 → 归一化课程结构 {"modules":[{title,description,lessons:[...]}]}。

    违规一律抛 CourseError（不修补、不截断、不落脏数据）：
    - data 必须为 dict 且 modules 为 3~8 条，每模块 lessons 3~8 条；
    - 模块/课文标题非空 ≤60 字，且全部标题跨模块全局去重；
    - est_minutes 缺省 30，仅允许 {15,30,45,60}（非法值不纠正、直接拒收）；
    - description 缺省补 ""。
    """
    if not isinstance(data, dict):
        raise CourseError("课程结构必须是 JSON 对象")
    mods = data.get("modules")
    if not isinstance(mods, list) or not (MODULE_MIN <= len(mods) <= MODULE_MAX):
        raise CourseError(f"模块数须在 {MODULE_MIN}~{MODULE_MAX} 之间")
    seen: set[str] = set()
    out = []
    for m in mods:
        if not isinstance(m, dict):
            raise CourseError("模块必须是 JSON 对象")
        mt = _clean_title(m.get("title"))
        if mt in seen:
            raise CourseError(f"标题重复: {mt}")
        seen.add(mt)
        lessons = m.get("lessons")
        if not isinstance(lessons, list) or not (LESSON_MIN <= len(lessons) <= LESSON_MAX):
            raise CourseError(f"模块「{mt}」课文数须在 {LESSON_MIN}~{LESSON_MAX} 之间")
        ls = [_read_lesson_item(l, seen) for l in lessons]
        out.append({
            "title": mt,
            "description": str(m.get("description") or "").strip(),
            "lessons": ls,
        })
    return {"modules": out}


def _build_structure_prompt(goal_text: str, subject_name: str, kp_overview) -> str:
    kp_line = "、".join(str(k) for k in (kp_overview or []) if str(k).strip()) or "（该学科暂无已有知识点）"
    return f"""你是课程体系设计专家。请为学习目标是「{goal_text}」的学习者，在学科「{subject_name}」下设计一门体系化课程。

学习者在本学科已有知识点（编排新课时应衔接、避免重复教学）：
{kp_line}

**结构要求：**
1. 课程由若干「模块」组成（3~8 个），模块之间按由浅入深的学习顺序排列；
2. 每个模块由若干「课文」组成（3~8 篇），课文是最小学习单位；
3. 每篇课文给出 title（不超过 30 字）、description（1~2 句内容概要）、est_minutes（预计学习分钟数，只允许 15、30、45、60 四档）；
4. 所有模块名与课文名不得重复，紧扣学习目标，不跑题。

只返回一个 JSON 对象，不要任何其他文字，格式：
{{"modules": [{{"title": "模块名", "description": "模块概述", "lessons": [{{"title": "课文名", "description": "课文概要", "est_minutes": 30}}]}}]}}"""


def generate_course_structure(goal_text: str, subject_name: str, kp_overview) -> dict:
    """学习目标 → 课程结构（spec §6）。解析/校验失败重试 1 次，仍败抛 CourseError。

    kp_overview：该学科已有知识点名称列表（可空），用于提示词衔接。
    LLM 原始调用异常（网络/积分不足）不重试、原样上抛（防已扣费重呼双扣）。
    """
    goal_text = str(goal_text or "").strip()
    if not goal_text:
        raise CourseError("学习目标不能为空")
    prompt = _build_structure_prompt(goal_text, subject_name, kp_overview)
    last_err: Exception | None = None
    for attempt in (1, 2):
        raw = _llm(prompt, scene="生成课程结构")
        try:
            return validate_course_structure(extract_json(raw))
        except (ValueError, CourseError) as e:
            last_err = e
            if attempt == 1:
                # 重试附纠正提示（LLM 输出不可信，第二次明确要求只输出合法 JSON）
                prompt += "\n\n注意：上一次输出不合法（%s）。请严格按要求重新输出完整 JSON 对象。" % e
    raise CourseError(f"课程结构生成失败（重试后仍不合法）: {last_err}")


# ---------------------------------------------------------------- 题包生成/校验（spec §6）

_Q_STEM_MAX = 600
_Q_OPT_MAX = 200
_Q_KP_MAX = 60
_Q_HINT_MAX = 300


def validate_questions(data, n_min: int = 4, n_max: int = 10) -> list:
    """LLM 题包返回 → 规整 [{stem, options[4], answer_index, kp_name, explanation, hint}]。

    接受裸 list 或 {"questions": [...]}；违规一律抛 CourseError（不落脏题包）：
    题数 [n_min, n_max]；stem/kp_name 非空；options 恰 4 个且非空；
    answer_index 为 0~3 的 int（bool 拒）；explanation 缺省补 ""。
    hint（查看提示，题包提示轮 2026-11-12）为软字段：缺失/非法一律降为空串不拒收
    ——模型漏写不该报废整包已合法的重试成本，前端空 hint 静默不渲染提示按钮。"""
    if isinstance(data, dict):
        data = data.get("questions")
    if not isinstance(data, list):
        raise CourseError("题包必须是 JSON 数组（或含 questions 数组的对象）")
    if not (n_min <= len(data) <= n_max):
        raise CourseError(f"题数须在 {n_min}~{n_max} 之间，实际 {len(data)}")
    out = []
    for i, q in enumerate(data, 1):
        if not isinstance(q, dict):
            raise CourseError(f"第{i}题必须是 JSON 对象")
        stem = str(q.get("stem") or "").strip()
        if not stem or len(stem) > _Q_STEM_MAX:
            raise CourseError(f"第{i}题 stem 非法（空或超{_Q_STEM_MAX}字）")
        opts = q.get("options")
        if not isinstance(opts, list) or len(opts) != 4:
            raise CourseError(f"第{i}题选项须恰为 4 个")
        opts = [str(o or "").strip() for o in opts]
        if any(not o or len(o) > _Q_OPT_MAX for o in opts):
            raise CourseError(f"第{i}题选项非法（空或超{_Q_OPT_MAX}字）")
        ai = q.get("answer_index")
        if isinstance(ai, bool) or not isinstance(ai, int) or not (0 <= ai <= 3):
            raise CourseError(f"第{i}题 answer_index 须为 0~3 的整数")
        kp = str(q.get("kp_name") or "").strip()
        if not kp or len(kp) > _Q_KP_MAX:
            raise CourseError(f"第{i}题 kp_name 非法（空或超{_Q_KP_MAX}字）")
        out.append({"stem": stem, "options": opts, "answer_index": ai, "kp_name": kp,
                    "explanation": str(q.get("explanation") or "").strip(),
                    "hint": str(q.get("hint") or "").strip()[:_Q_HINT_MAX]})
    return out


def decide_mode(score: float) -> str:
    """前测详略判定（R2 裁定）：全对（得分率 1.0）→ concise 精简课文，否则 full 完整课文。"""
    return "concise" if float(score) >= 1.0 else "full"


_TEST_KINDS = {"pretest", "postquiz", "moduleexam"}

_TEST_PROMPTS = {
    "pretest": """你是学习诊断专家。学习者准备学习课文《{title}》（学科：{subject}），请基于课文主题出 {n} 道前测题，用于摸底概念理解程度。

课文主题与概要：
{source}

**出题要求：**
1. 考核心概念理解，不考记忆性细节；每题四个选项，只有一个正确答案；
2. 每题标注 kp_name：该题考察的知识点名（用课文主题内的概念术语，不超过 30 字）；
3. 每题给 explanation 解析（讲解为什么对、错项错在哪）；数学公式用 $...$ 标注；
4. 每题给 hint 提示：解释题干里的关键术语（各一句人话），再提示该从哪个知识点方向思考；**严禁指出或暗示哪个选项正确，严禁写入能推出答案的结论**（提示只帮读懂题目，不替答题）。

只返回一个 JSON 对象，不要任何其他文字：
{{"questions": [{{"stem": "题干", "options": ["选项A", "选项B", "选项C", "选项D"], "answer_index": 0, "kp_name": "知识点名", "explanation": "解析", "hint": "术语解释与思考提示"}}]}}""",
    "postquiz": """你是命题专家。请基于以下课文全文出 {n} 道课后练习题，检验学习者对课文内容的掌握。

课文全文：
{source}

**出题要求：**
1. 覆盖课文各核心小节，难度与课文一致；每题四个选项，只有一个正确答案；
2. 每题标注 kp_name：该题考察的知识点名（优先用课文中出现的小标题/概念术语，不超过 30 字）；
3. 每题给 explanation 解析（引用课文关键结论帮助巩固）；数学公式用 $...$ 标注；
4. 每题给 hint 提示：解释题干里的关键术语（各一句人话），再提示该从课文哪个小节/概念方向思考；**严禁指出或暗示哪个选项正确，严禁写入能推出答案的结论**。

只返回一个 JSON 对象，不要任何其他文字：
{{"questions": [{{"stem": "题干", "options": ["选项A", "选项B", "选项C", "选项D"], "answer_index": 0, "kp_name": "知识点名", "explanation": "解析", "hint": "术语解释与思考提示"}}]}}""",
    "moduleexam": """你是命题专家。请对以下模块的全部课文出 {n} 道综合考试题，覆盖模块内每篇课文的核心内容。

模块课文清单与概要：
{source}

**出题要求：**
1. 每篇课文至少 1 题，鼓励跨课文综合题；每题四个选项，只有一个正确答案；
2. 每题标注 kp_name：该题考察的知识点名（不超过 30 字）；
3. 每题给 explanation 解析；数学公式用 $...$ 标注；
4. 每题给 hint 提示：解释题干里的关键术语（各一句人话），再提示该从哪篇课文/哪个概念方向思考；**严禁指出或暗示哪个选项正确，严禁写入能推出答案的结论**。

只返回一个 JSON 对象，不要任何其他文字：
{{"questions": [{{"stem": "题干", "options": ["选项A", "选项B", "选项C", "选项D"], "answer_index": 0, "kp_name": "知识点名", "explanation": "解析", "hint": "术语解释与思考提示"}}]}}""",
}


def generate_test_pack(kind: str, source_text: str, n: int, title: str = "", subject: str = "") -> list:
    """生成题包（kind∈pretest|postquiz|moduleexam）。解析/校验失败重试 1 次，仍败抛 CourseError。

    source_text：pretest 传课文主题概要，postquiz 传课文全文，moduleexam 传课文清单。
    LLM 原始调用异常（网络/积分不足）不重试、原样上抛（防已扣费重呼双扣）。
    kind 非法属编程错误，直接抛 ValueError（不消耗 LLM）。
    """
    if kind not in _TEST_KINDS:
        raise ValueError(f"未知题包类型: {kind}")
    n_min, n_max = (6, 10) if kind == "moduleexam" else (4, 10)
    prompt = _TEST_PROMPTS[kind].format(n=n, source=source_text, title=title or source_text[:30],
                                        subject=subject or "未指定学科")
    last_err: Exception | None = None
    for attempt in (1, 2):
        raw = _llm(prompt, scene={"pretest": "课程前测出题", "postquiz": "课程后练出题",
                                  "moduleexam": "模块考试出题"}[kind])
        try:
            return validate_questions(extract_json(raw), n_min=n_min, n_max=n_max)
        except (ValueError, CourseError) as e:
            last_err = e
            if attempt == 1:
                prompt += "\n\n注意：上一次输出不合法（%s）。请严格按要求重新输出完整 JSON 对象。" % e
    raise CourseError(f"题包生成失败（重试后仍不合法）: {last_err}")


# ---------------------------------------------------------------- 课文生成 + 状态机（spec §6/§5）

MD_MIN, MD_MAX = 200, 12000  # 12000：课文图文结合轮（2026-11-12 用户裁定 A 方案）给内嵌 mermaid 图留出字数空间

# 课文状态机（spec §4 course_lessons.status）：只允许按链前进一步或原地幂等
LESSON_FLOW = {"new": "pretested", "pretested": "content_ready",
               "content_ready": "learned", "learned": "done"}


def validate_lesson_md(text) -> str:
    """课文正文校验：剥 ```markdown 围栏，去首尾空白，长度 200~12000；违规抛 CourseError。

    只剥最外层整篇围栏；正文内部的 ```mermaid 围栏块不受影响（图文结合轮）。"""
    t = str(text or "").strip()
    if t.startswith("```"):
        nl = t.find("\n")
        if nl >= 0:
            t = t[nl + 1:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    t = t.strip()
    if not (MD_MIN <= len(t) <= MD_MAX):
        raise CourseError(f"课文长度须 {MD_MIN}~{MD_MAX} 字，实际 {len(t)}")
    return t


_MODE_RULES = {
    "full": "前测显示学习者基础薄弱：前测答错的概念置顶独立章节详细讲解并举例，再按固定四节结构展开全篇。",
    "concise": "前测显示学习者已全部答对：以要点摘要为主，每节短小精悍，不展开基础推导，重在高阶串联与易错点点拨。",
}


def _build_md_prompt(subject, title, description, mode, wrong_points) -> str:
    wrong = "、".join(str(w) for w in (wrong_points or []) if str(w).strip()) or "（暂无错题记录）"
    return f"""你是学科写作专家。请为学科「{subject}」的课文《{title}》撰写完整 Markdown 正文。

课文概要：{description or "（无）"}
薄弱点概念（前测/模块考错题）：{wrong}

**详略要求（{mode} 模式）：**
{_MODE_RULES[mode]}

**结构要求（固定四节，## 二级标题）：**
1. 概览：本篇解决什么问题、在课程中的位置；
2. 核心概念：定义 + 直观解释；
3. 范例：至少一个带步骤的典型例题；
4. 重点摘要：3~5 条要点回顾。

**图文结合要求（必须执行）：**
- 凡有流程、结构、因果、对比、时间线或知识层次的内容，必须配 1~3 个 mermaid 围栏块
  （```mermaid 开头、``` 结尾），紧跟所配段落之后；纯定义/纯计算段落可不配。
- 写图纪律（违反会导致前端渲染失败）：围栏首行必须是图型声明（graph TD / graph LR /
  sequenceDiagram 为主）；节点文字用简短中文；块内禁止出现 $、<、>、click、%%{{init%%}}；
  每张图不超过 12 个节点。

数学公式用 $...$ 标注（只用于正文，不要写进 mermaid 块）；只输出 Markdown 正文本身，不要解释、不要在首尾包整篇围栏。"""


def generate_lesson_md(subject: str, title: str, description: str, mode: str, wrong_points) -> str:
    """生成针对性课文（mode=full|concise 由 decide_mode 前测分判定）。

    解析/校验失败重试 1 次，仍败抛 CourseError；LLM 原始调用异常不重试原样上抛。"""
    if mode not in _MODE_RULES:
        raise ValueError(f"未知课文模式: {mode}")
    prompt = _build_md_prompt(subject, title, description, mode, wrong_points)
    last_err: Exception | None = None
    for attempt in (1, 2):
        raw = _llm(prompt, scene="生成课程课文")
        try:
            return validate_lesson_md(raw)
        except CourseError as e:
            last_err = e
            if attempt == 1:
                prompt += "\n\n注意：上一次输出不合格（%s）。请重新输出完整合格的 Markdown 正文。" % e
    raise CourseError(f"课文生成失败（重试后仍不合格）: {last_err}")


# ---------------------------------------------------------------- 扩展课程（spec §6/§5，Task 11）

EXT_MODULE_MAX = 2  # 追加只出 1~2 个新模块（一次扩太多质量塌）


def validate_extension(data, action: str, existing_titles) -> dict:
    """扩展 LLM 返回 → 归一化（与主结构同口径校验，但规模收紧且与现有标题去重）。

    action=add_module：{"modules": [...]} 1~EXT_MODULE_MAX 个，每模块课文 1~LESSON_MAX 篇；
    action=add_lesson：{"lessons": [...]} 1~LESSON_MAX 篇；
    existing_titles：课程现有全部模块/课文标题，新标题撞车一律 CourseError（不落脏）。
    返回 {"modules": [...]} 或 {"lessons": [...]}。"""
    if not isinstance(data, dict):
        raise CourseError("扩展结果必须是 JSON 对象")
    seen: set[str] = {str(t).strip() for t in (existing_titles or []) if str(t).strip()}
    if action == "add_module":
        mods = data.get("modules")
        if not isinstance(mods, list) or not (1 <= len(mods) <= EXT_MODULE_MAX):
            raise CourseError(f"扩展模块数须在 1~{EXT_MODULE_MAX} 之间")
        out = []
        for m in mods:
            if not isinstance(m, dict):
                raise CourseError("模块必须是 JSON 对象")
            mt = _clean_title(m.get("title"))
            if mt in seen:
                raise CourseError(f"标题重复: {mt}")
            seen.add(mt)
            lessons = m.get("lessons")
            if not isinstance(lessons, list) or not (1 <= len(lessons) <= LESSON_MAX):
                raise CourseError(f"模块「{mt}」课文数须在 1~{LESSON_MAX} 之间")
            out.append({"title": mt,
                        "description": str(m.get("description") or "").strip(),
                        "lessons": [_read_lesson_item(l, seen) for l in lessons]})
        return {"modules": out}
    if action == "add_lesson":
        lessons = data.get("lessons")
        if not isinstance(lessons, list) or not (1 <= len(lessons) <= LESSON_MAX):
            raise CourseError(f"扩展课文数须在 1~{LESSON_MAX} 之间")
        return {"lessons": [_read_lesson_item(l, seen) for l in lessons]}
    raise ValueError(f"未知扩展动作: {action}")


def _build_extension_prompt(goal_text, subject_name, existing_titles, action, module_title) -> str:
    titles_line = "、".join(str(t) for t in (existing_titles or []) if str(t).strip()) or "（暂无）"
    if action == "add_module":
        rule = (f"新增 {EXT_MODULE_MAX} 个以内的模块（1~{EXT_MODULE_MAX} 个），每个模块含 "
                f"1~{LESSON_MAX} 篇课文，作为现有课程的延伸或补强；")
        shape = '{{"modules": [{{"title": "模块名", "description": "模块概述", "lessons": [{{"title": "课文名", "description": "课文概要", "est_minutes": 30}}]}}]}}'
    else:
        rule = (f"只针对模块《{module_title}》新增 1~{LESSON_MAX} 篇课文，补齐该模块知识链；")
        shape = '{"lessons": [{"title": "课文名", "description": "课文概要", "est_minutes": 30}]}'
    return f"""你是课程体系设计专家。学习目标是「{goal_text}」（学科「{subject_name}」），现需扩展已有课程。

**扩展要求：**
1. {rule}
2. 标题不得与现有内容重复，现有模块与课文标题如下：
{titles_line}
3. 课文 est_minutes 只允许 15、30、45、60 四档；只输出新增部分，不要重复输出已有课程。

只返回一个 JSON 对象，不要任何其他文字，格式：
{shape}"""


def generate_course_extension(goal_text: str, subject_name: str, existing_titles,
                              action: str, module_title: str = "") -> dict:
    """扩展课程生成（scene=课程扩展生成）。解析/校验失败重试 1 次，仍败抛 CourseError。

    LLM 原始调用异常不重试原样上抛（防已扣费重呼双扣）。"""
    prompt = _build_extension_prompt(goal_text, subject_name, existing_titles, action, module_title)
    last_err: Exception | None = None
    for attempt in (1, 2):
        raw = _llm(prompt, scene="课程扩展生成")
        try:
            return validate_extension(extract_json(raw), action, existing_titles)
        except (ValueError, CourseError) as e:
            last_err = e
            if attempt == 1:
                prompt += "\n\n注意：上一次输出不合法（%s）。请严格按要求重新输出完整 JSON 对象。" % e
    raise CourseError(f"课程扩展生成失败（重试后仍不合法）: {last_err}")


# ---------------------------------------------------------------- 课内AI问答（spec §6，Task 11）

_CHAT_HIST_MAX = 10


def generate_lesson_chat(subject: str, title: str, content_md: str, history, question: str) -> str:
    """基于课文全文 + 最近问答历史回答学习者问题（scene=课内AI问答）。

    问答无结构校验，空回答视为失败直接抛 CourseError（不重试，防已扣费双扣）。"""
    hist = history or []
    hist_line = "\n".join(
        f"问：{str(h.get('q') or '').strip()}\n答：{str(h.get('a') or '').strip()}"
        for h in hist[-_CHAT_HIST_MAX:] if isinstance(h, dict)) or "（尚无历史对话）"
    prompt = f"""你是学科「{subject}」的课文辅导老师。学习者正在学习课文《{title}》，请基于课文内容回答问题。

课文全文：
{str(content_md or '')[:6000]}

历史对话：
{hist_line}

学习者当前问题：{question}

请用中文简洁回答，优先引用课文中的概念与例子；课文没覆盖的内容要说明并给出延伸解释。直接输出回答本身。"""
    raw = _llm(prompt, scene="课内AI问答")
    ans = str(raw or "").strip()
    if not ans:
        raise CourseError("问答返回为空")
    return ans


# ---------------------------------------------------------------- 课文追问笔记树生成（追问笔记树轮 2026-11-12）

_FOLLOW_PARENT_MAX = 3     # 父链上下文最多几层（追问的追问往上追）
_FOLLOW_PARENT_TXT_MAX = 800  # 父链单条问答截断（防上下文膨胀）


def generate_followup_chat(subject: str, title: str, content_md: str, anchor_text: str,
                           question: str, parent_ctx=None) -> str:
    """针对框选原文的追问回答（scene=课文追问讲解，同课内问答自动计费单缝）。

    parent_ctx：由近及远的父链问答 [{q, a}]，最多取 _FOLLOW_PARENT_MAX 层、各截断。
    prompt 纪律：尽可能图文并茂（用户裁定）——mermaid 围栏思路图/流程、表格对照、$公式$。
    空回答视为失败直接抛 CourseError（不重试，防已扣费双扣，同 generate_lesson_chat 口径）。"""
    lines = []
    for c in (parent_ctx or [])[:_FOLLOW_PARENT_MAX]:
        if isinstance(c, dict):
            lines.append(f"问：{str(c.get('q') or '').strip()[:_FOLLOW_PARENT_TXT_MAX]}\n"
                         f"答：{str(c.get('a') or '').strip()[:_FOLLOW_PARENT_TXT_MAX]}")
    ctx_line = "\n".join(lines) or "（无上级追问）"
    prompt = f"""你是学科「{subject}」的课文辅导老师。学习者正在学习课文《{title}》，对课文中框选的一段内容发起了追问。

课文全文：
{str(content_md or '')[:6000]}

学习者框选的原文：
「{str(anchor_text or '').strip()[:600]}」

这条追问的上级问答链（由近及远，可能没有）：
{ctx_line}

学习者当前追问：{question}

要求：
1. 紧扣框选原文与课文内容回答，优先引用课文中的概念与例子；
2. **尽可能图文并茂**：适合用结构表达的内容用 ```mermaid 围栏画思路图/流程/对照关系，
   多项比较用 Markdown 表格，数学式子用 $...$ 标注；图宁少勿滥，画了就要对应讲清；
3. 用中文回答，直接输出回答本身（Markdown）。"""
    raw = _llm(prompt, scene="课文追问讲解")
    ans = str(raw or "").strip()
    if not ans:
        raise CourseError("追问回答为空")
    return ans


def advance_lesson(conn, lesson_id, user_id, to_status: str) -> str:
    """课文状态机前进一步（或原地幂等返回），返回推进后状态。

    隔离：经 goals.user_id 双条件定位课文，越权/不存在抛 CourseError；
    跳步、回退、done 后再推进均拒绝；→ done 时写 done_time（UTC 秒级，同库内口径）。
    调用方负责 commit。"""
    row = conn.execute(
        "SELECT l.status FROM course_lessons l "
        "JOIN course_modules m ON l.module_id = m.id "
        "JOIN learning_goals g ON m.goal_id = g.id "
        "WHERE l.id = ? AND g.user_id = ?", (lesson_id, str(user_id))).fetchone()
    if not row:
        raise CourseError("课文不存在或无权访问")
    cur_st = row[0]
    if cur_st == to_status:  # 幂等：重复提交同状态直接放行
        return cur_st
    if LESSON_FLOW.get(cur_st) != to_status:
        raise CourseError(f"非法状态跳转: {cur_st} → {to_status}")
    if to_status == "done":
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE course_lessons SET status = ?, done_time = ? WHERE id = ?",
                     (to_status, now, lesson_id))
    else:
        conn.execute("UPDATE course_lessons SET status = ? WHERE id = ?", (to_status, lesson_id))
    return to_status
