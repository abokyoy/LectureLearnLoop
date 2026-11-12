# -*- coding: utf-8 -*-
"""微课生成服务（S1 知识点→微课，2026-10-30，用户裁定：薄弱点驱动/单知识点粒度）。

设计（与 weakness_report.py 同风格：纯函数 + 注入 llm_call(prompt)->str，路由层负责
取材料、计费与落库；测试注入 fake llm_call 断言 prompt 与校验分支，零真实消耗）：

- 两阶段生成：Stage1 大纲（1 次 LLM）→ Stage2 逐页正文（每页 1 次 LLM）。
  页型五种：explain 讲解 / example 例题 / quiz 随堂题 / summary 小结 / interactive
  交互实验页（二期：LLM 生成自包含 HTML，安全边界在渲染端 iframe sandbox）。
  五期（2026-11-03 用户反馈重做）：explain/example 改为 PPT 式分步画布——
  canvas_html 动画舞台 + steps[{caption, narration}]，宿主逐朗读一步就向舞台
  推一条 mc-step 消息，声画由同一 step 序号驱动（根除四期比例映射的声画错位）；
  四期 A2 has_widget 附加链路退役（存量 content.widget 仅保留前端兜底渲染）。
  仍不做：多 agent 课堂、导出。
- quiz 页 questions 与现有结构化出题契约完全同构（type/question/options/
  correct_answer/difficulty/explanation），判分/入池/FSRS 复用
  /api/knowledge/points/<pid>/practice-submit 链路（评审 M-1：quiz 页强制绑 kp_id）；
  二期起 quiz 页返回 {"narration", "questions"} 对象（断档升级，存量 0 行，不留兼容分支）。
- 严格校验：结构非法 → 抛 ValueError，调用方据此把该页置 failed，
  **绝不重发请求**（防已扣分重复消耗，业务规则 15.4 同口径）。
- 媒体规则统一文案 _MEDIA_RULE_FOR_PROMPT 注入每页 prompt（单一文案防口径漂移）。
- 本模块不碰积分、不碰数据库。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile

SCENE_TYPES = ("explain", "example", "quiz", "summary", "interactive")
MIN_SECTIONS = 3
MAX_SECTIONS = 8
QUIZ_COUNT = 2               # 每个 quiz 页固定 2 题（闭环判分题量小而聚焦）
MAX_BODY_LEN = 6000          # 单页正文上限（字符），超长判非法防模型跑飞
MAX_TITLE_LEN = 60
MAX_HTML_LEN = 12000         # 实验页 HTML 上限（字符）：控输出时长在超时预算内（二期评审 C1）；
                             # 烟测实测 6.7k~8.9k 字/页生成 67~87s，留余量防贴边拒页
NARRATION_MAX = 600          # 页级讲稿清洗后上限（约 2 分钟朗读；quiz/summary/interactive 用）
MAX_CAPTION_LEN = 40         # 分步字幕上限（五期：画布页每步唯一页面文字）
STEP_NARR_MAX = 160          # 分步讲稿单步上限（一句朗读单位，不再切句）
MIN_STEPS = 3                # 画布页最少有效步（低于即非法：模型只出 2 步基本是没画只出文）
MAX_STEPS = 8                # 超出截断（prompt 要求 5~8，宽容截不作废，二期不作废纪律）

# JSON 解析复用薄弱点报告件的实现（公共函数注册制，禁止再造轮子）
from services.weakness_report import extract_json_object  # noqa: E402


def _media_rule() -> str:
    """统一媒体规则常量（运行期从 routes_bridge 取，避免模块级循环导入）。"""
    from routes_bridge import _MEDIA_RULE_FOR_PROMPT
    return _MEDIA_RULE_FOR_PROMPT


def build_outline_prompt(*, subject: str, point_name: str, core_desc: str,
                         mastery_view: str, notes_material: str,
                         errors_material: str) -> str:
    """Stage1 大纲 prompt。材料块由路由层用既有公共函数打包后传入
    （notes_material：_collect_point_notes_text 产物；errors_material：
    _collect_point_errors_text 产物；无材料时传空串）。"""
    notes_block = (f"\n**关联笔记原文（讲课内容的事实来源，禁止超出其范畴）：**\n{notes_material}\n"
                   if notes_material else "")
    errors_block = (f"\n**该知识点的错题记录（薄弱考查点，须安排随堂题覆盖）：**\n{errors_material}\n"
                    if errors_material else "")
    return f"""你是全科教师，请为下面的知识点设计一堂 3~{MAX_SECTIONS} 页微课的教学大纲（学生掌握度：{mastery_view}）。

**知识点：**「{point_name}」（学科：{subject}）
**知识点描述：**{core_desc}
{notes_block}{errors_block}
**页型定义（每页 scene_type 只能取其一）：**
- explain：讲解页，讲清一个概念/原理/要点
- example：例题页，讲解式演算一道典型题（学生只看不作答）
- quiz：随堂题页，出 {QUIZ_COUNT} 道题让学生当场作答
- summary：小结页，收束全课并给出后续学习建议
- interactive：交互实验页，让学生动手调参数、观察动态过程（自包含 HTML 仿真实验）

**大纲要求：**
1. 共 {MIN_SECTIONS}~{MAX_SECTIONS} 页，顺序符合教学逻辑：先讲是什么、再讲为什么、举例、穿插随堂题、最后小结；
2. 至少 1 个 quiz 页（若提供了错题记录，quiz 页的考查点必须优先对准这些错题暴露的薄弱处）；
3. 必须恰好安排 1 页 interactive，放在最相关的讲解/例题之后——本页正文留待学生翻开时再生成，此刻只需定下实验主题与位置；
4. 同时判断该知识点是否真适合动手探究，结果写入 interactive_worthy：适合=true（学生翻到即自动生成实验），
   纯概念推演类不适合=false（页面保留，由学生主动点击才生成），并用 interactive_note 一句话说明理由；
5. 最后一页建议是 summary；同页内容聚焦，一个大纲节只承载一个教学目标；
6. 每节 title 不超过 30 字，intent 用一句话写明本页要达成什么。

只返回一个 JSON 对象，不要任何其他文字：
{{"title": "课程标题（不超过{MAX_TITLE_LEN}字）", "interactive_worthy": true, "interactive_note": "一句话理由（30字内）", "sections": [{{"title": "页标题", "scene_type": "explain", "intent": "本页教学目标"}}]}}"""


def build_error_outline_prompt(*, subject: str, point_name: str, core_desc: str,
                               mastery_view: str, error_material: str) -> str:
    """错题深度讲解大纲 prompt（六期：单题锚定小课，3~5 页，比知识点课小）。
    材料块由路由层 _error_explain_pack 打包后传入（题干/选项/学生错答/正确答案/解析/答错史）；
    输出契约与 build_outline_prompt 完全一致，复用 validate_outline 校验不另写；
    point_name 传空串即独立错题（无关联知识点）形态（六期用户裁定补丁）：
    线索①改为从题干自行归纳知识点，不引用掌握度。"""
    # 「教学大纲」四字是生产/测试假 LLM 分流大纲调用的判别词，任何变体文案必须携带
    if point_name:
        head = (f"请围绕它设计一堂 4~6 页「错题深度讲解」小课的教学大纲"
                f"（学生对该知识点的掌握度：{mastery_view}）。")
        anchor = (f"**这道错题关联的知识点：**「{point_name}」（学科：{subject}）\n"
                  f"**知识点描述：**{core_desc}")
        clue1 = ("1. 至少 1 页 explain：拆解「这道题考哪些知识点、每个条件起什么作用」，"
                 "把题和知识点连起来；")
    else:
        head = (f"请围绕它设计一堂 4~6 页「错题深度讲解」小课的教学大纲"
                f"（学科：{subject}；这道题尚未关联知识点，无掌握度数据）。")
        anchor = ("**这道错题的归属：**尚未关联知识点——请先从题干本身归纳它考查的核心概念，"
                  "整堂课围绕这个归纳结果展开（归纳写在第一页，后续页以它为准）")
        clue1 = ("1. 第一页 explain：先从题干归纳「这道题在考哪些知识点」并点名关键概念，"
                 "再拆「每个条件起什么作用」——这道题没有预置知识点，归纳本身就是讲解的第一步；")
    return f"""你是全科教师。学生做错了下面这道题，{head}

{anchor}

**错题全貌（讲解的事实依据，禁止超出其范畴；注意「你的作答」就是学生出错现场）：**
{error_material}

**页型定义（每页 scene_type 只能取其一）：**
- explain：讲解页，PPT 式分步画布讲解
- example：例题页，分步板书演示同类题（学生只看不作答）
- quiz：随堂题页，出 2 道变式题让学生当场作答
- summary：小结页，收束全课并给出后续学习建议
- interactive：交互实验页，学生动手调参数、观察动态过程

**这堂小课的硬性结构（必须全部具备）：**
{clue1}
2. 至少 1 页 explain：对照「你的作答与正确答案」讲清错在哪一步、为什么错、暴露了哪个薄弱点——这是本课的灵魂，本页目标必须写明具体错点；
3. 至多 1 页 example：用同类题分步板书演示来巩固；
4. 恰好 1 页 quiz：2 道变式题，考查点对准这道题的错因根因（同考点、变化表述，不得照抄原题）；
5. 恰好 1 页 interactive：把本题的关键动态过程（如参数变化、范围移动）做成学生可调参数的动手实验，
   放在相关讲解/例题之后——本页正文留待学生翻开时再生成，此刻只需定下实验主题与位置；
   同时判断这道题是否真适合实验，结果写入 interactive_worthy（适合=true，学生翻到即自动生成；
   纯文字推演类=false，页面保留由学生主动点击才生成），并用 interactive_note 一句话说明理由；
6. 可选 1 页 summary 收尾。每节 title 不超过 30 字，intent 用一句话写明本页要达成什么。

只返回一个 JSON 对象，不要任何其他文字：
{{"title": "课程标题（不超过{MAX_TITLE_LEN}字）", "interactive_worthy": true, "interactive_note": "一句话理由（30字内）", "sections": [{{"title": "页标题", "scene_type": "explain", "intent": "本页教学目标"}}]}}"""


def validate_outline(obj: dict) -> dict:
    """大纲严格校验：sections 数量/页型/必填字段；非法抛 ValueError（不落库、不重发）。"""
    if not isinstance(obj, dict):
        raise ValueError("大纲必须为 JSON 对象")
    title = str(obj.get("title") or "").strip()
    if not title or len(title) > MAX_TITLE_LEN * 2:
        raise ValueError("课程 title 缺失或过长")
    sections = obj.get("sections")
    if not isinstance(sections, list) or not (MIN_SECTIONS <= len(sections) <= MAX_SECTIONS):
        raise ValueError(f"sections 必须为 {MIN_SECTIONS}~{MAX_SECTIONS} 项数组")
    cleaned, quiz_cnt, inter_cnt = [], 0, 0
    for s in sections:
        if not isinstance(s, dict):
            raise ValueError("大纲节必须为对象")
        st = s.get("scene_type")
        if st not in SCENE_TYPES:
            raise ValueError(f"scene_type 非法：{st!r}")
        t = str(s.get("title") or "").strip()
        if not t or len(t) > MAX_TITLE_LEN:
            raise ValueError("大纲节 title 非法（空或超长）")
        intent = str(s.get("intent") or "").strip()[:200]
        if st == "quiz":
            quiz_cnt += 1
        if st == "interactive":
            # 至多 1 页（二期评审 Major：多余降级为讲解而非整单作废，不浪费已扣的大纲分）
            inter_cnt += 1
            if inter_cnt > 1:
                st = "explain"
                intent = intent or "补充讲解"
        # 五期：旧大纲可能残留 has_widget 字段（存量课 regenerate 重读），静默丢弃不再消费
        cleaned.append({"title": t, "scene_type": st, "intent": intent})
    if quiz_cnt < 1:
        raise ValueError("大纲必须至少包含 1 个 quiz 页")
    # 七期（用户裁定）：每课固定 1 页互动实验页，正文 standby 待用户翻开才生成。
    # LLM 漏排互动页 → 末尾补位；此时其 worthy 判断不可信（违了约），一律保守走 false
    # （防误烧积分：用户主动点按钮才生成）；补位页不参与 MAX_SECTIONS 复核
    worthy = obj.get("interactive_worthy") is True
    note = str(obj.get("interactive_note") or "").strip()[:60]
    if inter_cnt == 0:
        cleaned.append({"title": "互动实验", "scene_type": "interactive",
                        "intent": "围绕本课内容动手调参数、观察动态变化"})
        worthy, note = False, note or "大纲未安排实验页，可由你手动生成"
    return {"title": title, "sections": cleaned,
            "interactive_worthy": worthy, "interactive_note": note}


def build_scene_prompt(*, subject: str, course_title: str, section: dict,
                       point_name: str, core_desc: str, outline_brief: str,
                       notes_material: str, errors_material: str) -> str:
    """Stage2 单页 prompt。scene_type=quiz 时题目契约与既有结构化出题完全同构。"""
    st = section["scene_type"]
    material = ""
    if notes_material:
        material += f"\n**讲课材料·关联笔记原文（内容的事实来源，禁止编造超出其范畴的内容）：**\n{notes_material}\n"
    if errors_material:
        material += f"\n**讲课材料·错题记录（学生曾出错的确切位置）：**\n{errors_material}\n"
    anchor_line = (f"**主讲知识点：**「{point_name}」描述：{core_desc}" if point_name else
                   "**题目锚定：**本课深度讲解一道尚未关联知识点的独立错题，"
                   "以讲课材料中的【题目】为事实锚，知识点按整课目录第一页的归纳口径")
    common = f"""你在为一堂微课写其中一页。课程：「{course_title}」（学科：{subject}）。
本页在整课中的位置——整课目录：
{outline_brief}

**本页：** 页型={st}｜标题=「{section['title']}」｜本页目标：{section['intent']}
{anchor_line}
{material}
"""
    # 二期语音旁白：页级讲稿可读性规则注入仍带 narration 字段的页型（quiz/summary/interactive）；
    # 五期：explain/example 改分步契约，讲稿可读性规则已写入其 fmt，文案口径一致
    if st in ("quiz", "summary", "interactive"):
        common += ("**朗读讲稿（narration 字段）要求：** 讲稿将由浏览器朗读给学生听，必须能直接念："
                   "100~300 字，像老师开口讲课；禁止 LaTeX 与代码符号（不得出现 $、反斜杠命令、"
                   "反引号、表格竖线），公式与符号口语化（如「a 平方」「E 等于 m c 平方」「大于等于」）；"
                   "纯数字与年份可保留。\n\n")
    if st == "explain":
        fmt = ('生成一页「讲解驱动画面」的 PPT 式动画课堂。返回 JSON 对象：'
               '{"title": "页标题", "canvas_html": "动画舞台（完整 HTML 文档）", '
               '"steps": [{"caption": "一句话字幕", "narration": "一步讲解口播"}]}，'
               'steps 共 5~8 步。本页硬性要求：\n'
               'A. 禁止大段文字！画面是主体，每步只配一句字幕（≤40字）与一句口播讲解（30~120字），'
               '舞台画面文字只留本页一句标题与图内必要标注，靠图形/动画/高亮讲透概念，不得把讲解写成段落文字；\n'
               'B. steps 是页面骨架：第 i 步的 narration 就是老师那句口播，canvas_html 收到第 i 步消息时'
               '画面必须做出与之对应的可见变化（指过去/亮起来/动起来）；\n'
               'C. 面向曾在此处出错的学生，讲清本页目标；内容事实来源限讲课材料，禁止编造。\n\n'
               'canvas_html 分步舞台规则：\n' + _STEP_STAGE_RULES + '\n'
               'canvas_html 硬性要求（实验页同源）：\n' + _HTML_HARD_RULES_CORE)
    elif st == "example":
        fmt = ('生成一页「讲解驱动画面」的 PPT 式分步推导课堂。返回 JSON 对象：'
               '{"title": "页标题", "canvas_html": "动画舞台（完整 HTML 文档）", '
               '"steps": [{"caption": "一句话字幕", "narration": "一步讲解口播"}]}，'
               'steps 共 5~8 步。本页硬性要求：\n'
               'A. 第 0 步呈现完整题干（题干文字在舞台内显示，学生先看清题），之后逐步推导：每推一步、'
               '画面对应位置亮一步/动一步；禁止大段文字，每步只配一句字幕（≤40字）与一句口播（30~120字）；\n'
               'B. 每步 narration 像老师板书时开口讲的那句话，与画面变化严格对应；\n'
               'C. 例题与本页目标及知识点直接相关，优先改编材料中出现的真实题目。\n\n'
               'canvas_html 分步舞台规则：\n' + _STEP_STAGE_RULES + '\n'
               'canvas_html 硬性要求（实验页同源）：\n' + _HTML_HARD_RULES_CORE)
    elif st == "quiz":
        # 二期断档升级：数组 → 对象（含 narration）；防漂移：不得再要求「只返回 JSON 数组」
        fmt = (f'出恰好 {QUIZ_COUNT} 道题让学生作答，以选择题为主，可含判断题/填空题；'
               '只返回 JSON 对象：{"narration": "开场讲稿（说明本随堂题要考察什么）", '
               '"questions": [题目数组]}，每题字段：type(single/judge/fill), question, '
               'options(仅 single，4 个选项), correct_answer(single 为 A/B/C/D；judge 为 "正确"/"错误"；'
               'fill 为答案文本，可接受写法用 | 分隔), difficulty(容易/中等/困难), '
               'explanation(答案解析)。题目须对准材料中错题暴露的薄弱考查点（同考点、可变化表述，'
               '不得照抄原题题干）。')
    elif st == "interactive":
        fmt = ('生成一个可交互实验页。返回 JSON 对象：{"title": "页标题", '
               '"html": "完整 HTML 文档", "narration": "实验引导讲稿"}。html 硬性要求：\n'
               + _HTML_HARD_RULES_CORE + '\n'
               '6. narration 用口语讲清这个实验演示什么、建议学生调整什么、观察什么。')
    else:  # summary
        fmt = ('返回 JSON 对象：{"title": "页标题", "body_md": "小结正文（Markdown，梳理本课要点，'
               '并给出下一步学习/练习建议）", "narration": "本页朗读讲稿"}；body_md 200~800 字。')
    return common + f"\n{_media_rule()}\n\n{fmt}\n禁止输出 JSON 之外的任何解释文字。"


# 分步动画舞台协议（五期：explain/example 的 canvas_html 专用，与宿主 stepPlay 消息格式一致；
# 协议字段改动必须同步 pm_pages.js stepPlay 的 postMessage 形状，两边同一口径）
_STEP_STAGE_RULES = (
    '1. 舞台脚本用 window.addEventListener("message", ...) 监听宿主消息，只处理形如 '
    '{t:"mc-step", i:序号, n:总步数, caption:"字幕"} 的消息（宿主初始化推 i=0，逐朗读一步推进一步，'
    '学生手动跳步可能任意序）；\n'
    '2. 收到第 i 步立即把画面切到该步对应状态：i=0 是总览/初始态，第 i 步相对第 i-1 步必须有可见'
    '新变化（激光笔式光标指到关键处/元素高亮/图形逐步绘出/参数动画过渡），且与 steps[i] 口播语义严格对应；\n'
    '3. 长时间收不到消息保持当前状态不报错；禁止依赖任何外部资源（同下方硬性要求第 4 条）；\n'
    '4. DOM 引用纪律（2026-11-10 实弹崩溃轮，服务端 validate_scene_content 会硬拒违规页）：'
    'getElementById("x") / querySelector("#x") 里的 id 必须是本页 HTML 中已写死的 id 属性，'
    '且只能写成纯字符串字面量——禁止 ' + "'r'+i" + ' 这类拼接、禁止用变量当 id；'
    '要操作一组元素就把它们全部逐个声明、逐个引用（或统一用 querySelectorAll 的类选择器）；'
    '取到元素后再用，任何取元素的地方都要先判空（var el=document.getElementById("a"); if(!el) return;）。')

# 实验页/分步舞台共用的 html 硬性规则（单一文案防口径漂移，二期制定）
_HTML_HARD_RULES_CORE = (
    '1. 完整 HTML5 文档，以 </html> 结尾；CSS/JS 全部内联（vanilla JS，无框架、'
    '无任何外部 CDN/字体/图片引用），总长不超过 250 行；\n'
    '2. html 字段是 JSON 字符串：换行必须转义为 \\n，引号转义为 \\"，'
    '禁止输出代码围栏；\n'
    '3. 交互：学生可通过滑杆/按钮/动画改变条件并即时观察结果（可用 canvas/svg 绘图）；'
    '控件支持键盘与触摸；\n'
    '4. 页面不得联网（禁 fetch/XMLHttpRequest/WebSocket），不用 localStorage/cookie；'
    '内联 SVG 的 xmlns 命名空间（www.w3.org）允许保留；\n'
    '5. 浅色背景、深色文字，宽度自适应 360~900px，高度由宿主自动调整；')


def _clean_narration(v, maxlen: int = NARRATION_MAX) -> str:
    """讲稿清洗（二期评审 Major-2：可修复瑕疵一律清洗不作废，误杀代价是付费废页）：
    剥除 TTS 读不出的 LaTeX/代码符号 → strip → 空才非法 → 上限截断（maxlen：页级/单步各自上限）。"""
    s = re.sub(r"[$`\\|]", "", str(v or "")).strip()
    if not s:
        raise ValueError("narration 缺失或清洗后为空（讲稿必须可读）")
    return s[:maxlen]


# ---- canvas_html DOM 引用完整性闸（2026-11-10 原理动画首帧崩溃轮）----
# 背景：qwen36 自备模型生成的舞台里 getElementById('r'+(i||'')) 拼出悬空 id，
# 首帧 render(0) 即 null.classList TypeError，而旧校验只查非空+长度——坏产物
# 直接入库并被「同知识点永远复用」缓存永久回放。口径：凡能静态判定的崩溃
# 一律做进服务端闸门，不依赖模型自觉（黑板连续性轮同纪律）。
_ID_DECL_RE = re.compile(r"""\bid\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>"'/]+))""")
_GEBI_RE = re.compile(r"""getElementById\(\s*([^)]*)\)""")
_JS_LIT_RE = re.compile(r"^(['\"])([^'\"]+)\1$")
_QS_RE = re.compile(r"""querySelector(?:All)?\(\s*([^)]*)\)""")
# 复杂选择器（后代/组合/类/属性伪类）不做静态 id 判定，免得误杀合法写法
_QS_COMPLEX_RE = re.compile(r"[\s>.,:\[\]()|+~*]")


def _canvas_dom_ref_check(canvas: str) -> None:
    """画布舞台 DOM 引用闸：getElementById / querySelector('#id') 只允许
    纯字面量且 id 已在 HTML 声明（带/不带引号属性都算）；拼接/变量形态
    无法静态验证，直接拒。非法抛 ValueError（调用方置 error，不入缓存）。

    已知取舍（评审 Minor-2，2026-11-10）：「createElement 后动态赋 id 再取回」
    这类合法写法会被误拒——宁可拒一张需重生成的页，不放一张首帧就崩、崩了
    还会被「同知识点永远复用」当真产物永久回放的页（提示词纪律已明令逐个声明）。
    方向性保守：只做「引用必须能静态对应到声明」，复杂选择器一律不参与判定。"""
    ids = {(m.group(1) or m.group(2) or m.group(3) or "")
           for m in _ID_DECL_RE.finditer(canvas)}
    bad_lit, bad_dyn = [], []
    for m in _GEBI_RE.finditer(canvas):
        sm = _JS_LIT_RE.match(m.group(1).strip())
        if not sm:
            bad_dyn.append(m.group(1).strip()[:24])
        elif sm.group(2) not in ids:
            bad_lit.append(sm.group(2))
    for m in _QS_RE.finditer(canvas):
        arg = m.group(1).strip()
        # 只管「引号紧跟 #」的 id 选择器（类/标签选择器不参评）
        if len(arg) < 3 or arg[0] not in "'\"" or arg[1] != "#":
            continue
        sm = _JS_LIT_RE.match(arg)
        if not sm:
            bad_dyn.append(arg[:24])          # '#x'+i 拼接选择器同样会 null 崩
            continue
        sel = sm.group(2)[1:]
        if _QS_COMPLEX_RE.search(sel):
            continue                          # 复杂选择器不静态判，避免误杀
        if sel not in ids:
            bad_lit.append(sel)
    if bad_lit or bad_dyn:
        parts = []
        if bad_lit:
            parts.append("引用未声明 id: " + ", ".join(sorted(set(bad_lit))[:6]))
        if bad_dyn:
            parts.append("拼接/变量取 id: " + "; ".join(list(dict.fromkeys(bad_dyn))[:4]))
        raise ValueError("canvas_html DOM 引用不完整（" + "；".join(parts) + "）")


def _html_js_syntax_check(html: str) -> None:
    """产物内联 JS 语法闸（追问 mermaid 同日实弹轮 2026-11-12：实验台产物写了
    `(+W.value*4++B.value)` —— SyntaxError 使整个 <script> 不执行，canvas 永久空白，
    且被「同键永远复用」当真产物回放；舞台轮 _canvas_dom_ref_check 只查 DOM 引用，
    语法层是盲区）。逐 <script> 块用 node --check 编译检查（只编译不执行）；
    node 不可用（未安装/超时）优雅降级不拦——坏产物代价比误杀业务小（同舞台闸门
    保守拒收的反向取舍：语法闸是附加防御，环境缺件不能把生成链卡死）。
    非法抛 ValueError（调用方置 failed 不重发，防双扣分同纪律）。"""
    for idx, body in _js_blocks(html):
        fd, path = tempfile.mkstemp(suffix=".js", prefix="mcjschk_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
            try:
                r = subprocess.run(["node", "--check", path],
                                   capture_output=True, timeout=15)
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                return  # 环境无 node：全部跳过（降级不拦，见 docstring 取舍）
            if r.returncode != 0:
                msg = r.stderr.decode("utf-8", "replace").strip()[-200:]
                raise ValueError(
                    f"内联脚本块 {idx + 1} 语法错误（整页脚本会静默不执行）: {msg}")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def _js_blocks(html: str):
    """产出 (序号, 代码) —— 只取无 src、传统脚本型的内联块；type=module 跳过
    （node --check 按 CommonJS 解析，import 会误报），JSON/template 等非 JS 型跳过。"""
    n = 0
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html or "", re.I | re.S):
        attrs, body = m.group(1), m.group(2)
        if re.search(r"\bsrc\s*=", attrs, re.I):
            continue
        tm = re.search(r"\btype\s*=\s*[\"']?([\w/-]+)", attrs, re.I)
        if tm and tm.group(1).lower() not in ("text/javascript", "application/javascript",
                                              "application/ecmascript", "text/ecmascript"):
            continue
        if body.strip():
            yield n, body
        n += 1


def external_ref_note(html: str) -> str | None:
    """实验页外链检测（二期评审 C2：只警告不置败——安全边界在渲染端 sandbox，
    服务端黑名单硬拒会误杀 xmlns/注释导致付费废页）。只看属性/url() 上下文，
    allowlist www.w3.org（内联 SVG 命名空间）。"""
    refs = re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']|url\(\s*["']?([^"')]+)""", html, re.I)
    bad = [u[:60] for pair in refs for u in pair
           if u and u.startswith(("http://", "https://", "//")) and "www.w3.org" not in u]
    if not bad:
        return None
    return "实验页引用了外部资源，离线可能不完整：" + "、".join(bad[:3])


def validate_scene_content(scene_type: str, raw: str) -> dict | list:
    """按页型解析+严格校验模型返回；非法抛 ValueError（调用方置 failed，不重发）。

    quiz 页返回 {"narration", "questions"} 对象（questions 用既有
    _validate_practice_questions 同口径校验）；interactive 页返回
    {"title", "html", "narration"}（html 只硬校验非空+长度，外链仅警告）；
    其余页型返回内容对象（均含 narration）。
    """
    if scene_type == "quiz":
        from routes_bridge import _validate_practice_questions
        obj = extract_json_object(raw)
        if not isinstance(obj, dict):
            raise ValueError("quiz 页必须为 {narration, questions} 对象")
        narration = _clean_narration(obj.get("narration"))
        qs = _validate_practice_questions(obj.get("questions"), QUIZ_COUNT)
        if not qs:
            raise ValueError("quiz 页题目数组为空")
        return {"narration": narration, "questions": qs}
    obj = extract_json_object(raw)
    if not isinstance(obj, dict):
        raise ValueError("页内容必须为 JSON 对象")
    title = str(obj.get("title") or "").strip()[:MAX_TITLE_LEN]

    if scene_type in ("explain", "example"):
        # 五期：PPT 式分步画布页（声画同源：第 i 步 narration 驱动舞台第 i 个视觉态）；
        # 可修复瑕疵逐步清洗跳步，不作废整页（二期 Major-2 纪律）；canvas 缺失/超长非法
        # 同 interactive 口径（非法置 failed 不重发，可手动重生成单页）
        canvas = str(obj.get("canvas_html") or "").strip()
        if not canvas:
            raise ValueError("画布页缺少 canvas_html 舞台")
        if len(canvas) > MAX_HTML_LEN:
            raise ValueError(f"canvas_html 超过 {MAX_HTML_LEN} 字")
        _canvas_dom_ref_check(canvas)
        _html_js_syntax_check(canvas)
        steps_raw = obj.get("steps")
        if not isinstance(steps_raw, list):
            raise ValueError("steps 必须为数组")
        steps = []
        for s in steps_raw:
            if not isinstance(s, dict):
                continue
            try:
                narr = _clean_narration(s.get("narration"), STEP_NARR_MAX)
            except ValueError:
                continue  # 空口播步骤跳过（页面剩余步仍可用，少于下限才非法）
            cap = str(s.get("caption") or "").strip()[:MAX_CAPTION_LEN]
            steps.append({"caption": cap or f"第 {len(steps) + 1} 步", "narration": narr})
        if len(steps) < MIN_STEPS:
            raise ValueError(f"有效步骤数不足：{len(steps)} < {MIN_STEPS}")
        return {"title": title, "canvas_html": canvas, "steps": steps[:MAX_STEPS]}

    narration = _clean_narration(obj.get("narration"))

    def _md(v) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("页内容缺少必需的正文字段")
        if len(s) > MAX_BODY_LEN:
            raise ValueError(f"页正文超过 {MAX_BODY_LEN} 字")
        return s

    if scene_type == "summary":
        return {"title": title, "body_md": _md(obj.get("body_md")), "narration": narration}
    if scene_type == "interactive":
        # 二期烟测实测约束：长度上限控超时风险；结构非法（截断 JSON）自然解析失败
        html = str(obj.get("html") or "").strip()
        if not html:
            raise ValueError("实验页 html 缺失")
        if len(html) > MAX_HTML_LEN:
            raise ValueError(f"实验页 html 超过 {MAX_HTML_LEN} 字")
        _html_js_syntax_check(html)  # 语法闸：SyntaxError 产物入库＝永久回放空白页（实弹轮 2026-11-12）
        return {"title": title, "html": html, "narration": narration}
    raise ValueError(f"未知页型：{scene_type!r}")


def outline_brief(sections: list[dict]) -> str:
    """目录摘要行（注入每页 prompt，让模型知道本页在整课中的位置）。"""
    return "\n".join(f"{i + 1}. [{s['scene_type']}] {s['title']}"
                     for i, s in enumerate(sections))


def _token_ratio() -> int:
    """积分换算比例（公共口径：estimate_credits 与 estimate_scene_cost 共用，防双处漂移）。"""
    import credits_service as cr
    try:
        return max(1, int(cr.get_number("credits_token_ratio", 4000)))
    except Exception:  # noqa: BLE001
        return 4000


def estimate_credits(page_count: int) -> float:
    """积分预估（去术语化展示用，业务规则 15.5 口径：只报积分，不报调用次数）。

    粗估口径：1 次大纲 + N 页正文；五期：explain/example 单调用含分步画布+分步讲稿，
    输出变大，每次约 1.3 万 token（含注入材料）按当前换算比例折积分。
    仅用于生成前弹窗提示，实际按 token 计量扣分。
    """
    calls = 1 + int(page_count)
    tokens_per_call = 13000
    return round(calls * tokens_per_call / _token_ratio(), 1)


def estimate_scene_cost() -> float:
    """单页正文生成成本预估（七期：互动页按需生成同屏提示口径）。
    走 regenerate 链路只烧 1 次 LLM 调用，不含大纲调用——不得拿
    estimate_credits(1) 冒充单页价（评审 N-1：会把提示抬高约一倍）。"""
    return round(13000 / _token_ratio(), 1)
