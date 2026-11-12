# -*- coding: utf-8 -*-
"""黑板「原理图」按需生成（v0.2.8 Demo 轮，2026-11-09）。

方法论来源：开源项目 github.com/OneMoh/html-explainer（Agent Skill）。
调研结论（README/SKILL.md 实读）：该项目产出的是带配音的 MP4 讲解视频，
完整流水线含 TTS/逐帧渲染/ffmpeg——本模块**不搬视频链**，只移植它最核心、
也最适合本场景的方法论：「模型不生成像素，而是现写一份自包含 HTML/CSS 画面，
由浏览器渲染」——文字永远清晰、可复现、可改；配套纪律（一场景一焦点、
颜色只取 CSS 变量、系统字体栈、禁外链、节拍分步）本地化为提示词硬约束。

交付形态与微课 interactive 实验页同口径（架构收敛，复用而非另造）：
- 产物校验走 micro_course.validate_scene_content("interactive", raw)；
- 外链只警告不拦截，安全边界在渲染端 iframe sandbox（微课二期评审 C2 口径）；
- LLM 调用走 call_llm_for_user 显式 uid 计费链（微课页面生成同款），
  后台 daemon 线程 + 前端轮询状态（黑板备课 _run_generation 同模式，
  同步请求会长时间占线程波及全站轮询）。

作业注册表内存态 + 产物落库复用（成本优化轮 2026-11-10，用户裁定）：
- 同知识点永远复用：复用键 = 本课 lesson_key，库里有 done 产物 → 零外呼零扣分秒回；
- 「重新生成」（refresh）才再花钱：显式开思考 thinking="on" 深度重画，新版本行覆盖；
- 日常首次生成：不传 thinking，由 llm_provider_factory 场景策略表接管（白名单默认关）。
同一用户同时只允许一个在飞作业（防双击双扣分）；内存态重启即丢但库表仍在，
入口先查库（routes 层 /api/board/explain/latest）。
"""
from __future__ import annotations

import threading
import time
import uuid

import credits_service as cr
from llm_provider_factory import call_llm_for_user
from logger_module import debug_logger as log
from services import lecture_board as LB
from services import micro_course as MC
from services import principle_cache as PC

# ---------------------------------------------------------------- 常量
_LLM_TIMEOUT = 240          # 原理图输出比微课实验页更长：2026-11-09 实测 deepseek-flash 产 14k 字耗 154s，留量防贴脸超时
_SCENE = "原理图生成"
_LAB_SCENE = "课文实验图生成"   # 图文结合轮（2026-11-12 A 方案）：课级交互实验台独立计量场景
_LESSON_MAT_MAX = 9000         # 课级产物素材上限：课文正文比板卡快照长，单独定量
_MAT_TEXT_MAX = 120          # 单张板卡正文截断
_MAT_CARDS_MAX = 30          # 进提示词的板卡上限（超取最新）
_MAT_SPEECH_MAX = 40         # 进提示词的老师旁白上限（超取最新）
_MAT_TOTAL_MAX = 6000        # 素材区总长上限（保板书优先，旁白截尾）

# ---------------------------------------------------------------- 作业注册表
_LOCK = threading.Lock()
_JOBS: dict = {}             # job_id -> 内部 dict（含 uid，对外回公开视图）


def _public(j: dict) -> dict:
    """对外视图：剥 uid/提示词等内部字段；done 才带产物。"""
    out = {"job_id": j["job_id"], "state": j["state"],
           "created_ts": j["created_ts"]}
    if j["state"] == "done":
        out.update({"title": j["title"], "html": j["html"],
                    "narration": j.get("narration") or "",
                    "warning": j.get("warning")})
    elif j["state"] == "failed":
        out["error"] = j.get("error") or "生成失败，请稍后再试"
    return out


def get_job(uid: str, job_id: str) -> dict | None:
    """按 id 查作业（跨用户不可见，返回公开视图；查无 None）。"""
    with _LOCK:
        j = _JOBS.get(job_id)
        if not j or j["uid"] != str(uid):
            return None
        return _public(j)


def running_job(uid: str) -> dict | None:
    """该用户是否有在飞黑板作业（前端进页/误关弹窗后找回用）。
    排除带 _ref 的课级作业（图文结合轮）：黑板找回不该拿到课文页产物作业。"""
    with _LOCK:
        for j in _JOBS.values():
            if j["uid"] == str(uid) and j["state"] == "generating" and "_ref" not in j:
                return _public(j)
    return None


def _gc_locked() -> None:
    """轻量回收：只留最近 20 条终态作业（防内存无界增长，Demo 级够用）。"""
    if len(_JOBS) <= 40:
        return
    done = sorted((j for j in _JOBS.values() if j["state"] != "generating"),
                  key=lambda j: j["created_ts"])
    for j in done[:max(0, len(done) - 20)]:
        _JOBS.pop(j["job_id"], None)


# ---------------------------------------------------------------- 素材序列化与提示词
def _material_lines(snap: dict) -> list:
    """板面快照 → 素材行（板书卡 + 图卡摘要；顺序即板面顺序）。"""
    lines = []
    for c in (snap.get("items") or [])[-_MAT_CARDS_MAX:]:
        kind = str(c.get("kind") or "")
        text = str(c.get("text") or "").strip()[:_MAT_TEXT_MAX]
        if kind == "plot":
            d = c.get("data") or {}
            names = "/".join(str(m.get("name") or "")
                             for m in (d.get("marks") or [])[:12]
                             if isinstance(m, dict) and m.get("name"))
            seg = f"- [图·{d.get('plot_type') or kind}] {text}"
            if d.get("title"):
                seg += f"（{d['title']}）"
            if names:
                seg += f" 图上标记：{names}"
            lines.append(seg[:200])
        elif text:
            anchor = "、".join(str(a) for a in (c.get("anchors") or [])[:6])
            seg = f"- [{kind}] {text}"
            if anchor:
                seg += f"（可指认短语：{anchor}）"
            lines.append(seg[:200])
    return lines


def _speech_lines(snap: dict) -> list:
    """老师旁白摘录（只取 teacher 行，学生的话不进素材）。"""
    return [str(s.get("text") or "").strip()[:_MAT_TEXT_MAX]
            for s in (snap.get("speech") or [])[-_MAT_SPEECH_MAX:]
            if s.get("role") == "teacher" and str(s.get("text") or "").strip()]


def build_prompt(snap: dict, assign_label: str = "") -> str:
    """课堂信息 → html-explainer 纪律化的生成提示词。

    输出契约复用微课 interactive 页 JSON（title/narration/html），
    这样 validate_scene_content("interactive") 可直接复用。
    """
    cards = _material_lines(snap)
    speech = _speech_lines(snap)
    mat = []
    if assign_label:
        mat.append(f"本课主题：{assign_label}")
    if cards:
        mat.append("板书内容（按板面顺序）：\n" + "\n".join(cards))
    body = "\n\n".join(mat)
    if len(body) > _MAT_TOTAL_MAX:
        body = body[:_MAT_TOTAL_MAX]
    if speech:
        tail = "\n\n老师课堂讲解摘录（辅助理解语境，可截断）：\n" + "\n".join(speech)
        room = max(0, _MAT_TOTAL_MAX - len(body))
        if room > 80:
            body += tail[:room]
    return f"""你是学习软件的「原理图」制作高手。请根据下面正在课堂上的内容，制作一页**自包含、可交互的 HTML 原理讲解页**，帮学生一眼看懂本课的核心原理。

【画面纪律】（源自开源项目 html-explainer 的方法论：模型不生成像素，而是写画面代码交给浏览器渲染——文字必须永远清晰、可复现）
1. 画面全部用 HTML/CSS/原生 JS 完成，禁止引用任何外部资源（无 CDN/网络字体/外链图片，沙箱环境离线渲染）；
2. 一场景一焦点：把原理拆成 3~6 个步骤逐步展开，每步只有一个视觉主角，配角不加高亮；视觉主角必须是真图形（内联 <svg>/<canvas>/CSS 图形）：讲曲线、区域、图形、结构就画出形，公式条、进度条、纯文字卡不算图；
3. 所有颜色定义为 CSS 变量（:root）再引用：明亮清爽的教学配色（浅色底、一个主色、一个强调色），禁止色值散落；
4. 只用系统字体栈：-apple-system, "Segoe UI", "Microsoft YaHei", sans-serif；
5. 动效只用 CSS transition/@keyframes + 原生 JS；页面必须至少含两种交互：步骤按钮（上一步/下一步/自动播放）+ 悬停标注或参数滑杆（让学生动手改一改、看图形/数值随它变）；JS 要写完整可运行的语法（语法错误会让整页静默只剩文字，图全部空白）；
6. 术语与板书严格一致：图上的点名（如「点A」）、概念名词（如「中位线」）直接沿用素材原文，不生造名词；
7. 只依据给定素材讲解，不得虚构事实；核心公式/结论必须作为清晰文字出现在画面上（可用 Unicode 符号，不许用外链公式渲染器）。

【输出格式】只输出一个 JSON 对象，不要任何解释或代码围栏：
{{"title": "不超过20字的原理图标题", "narration": "弹出本页时老师朗读的一句导语", "html": "完整 HTML 文档字符串（<!DOCTYPE html> 开头，内联全部样式与脚本）"}}
写 html 务必紧凑：不写注释、不留多余空行、选择器与变量名简短；总篇幅控制在 9000 字以内（硬上限 {MC.MAX_HTML_LEN} 字，超长整页作废）。

【课堂素材】
{body}
"""


# ---------------------------------------------------------------- 生成
def build_stage_prompt(*, label: str, material: str, subject: str = "通用") -> str:
    """原理图方法论 → 分步动画舞台画布契约（融合轮 2026-11-09 用户裁定）。

    输出形状与校验完全复用 MC.validate_scene_content("explain")：
    {title, canvas_html, steps[{caption, narration}]}——老师侧 board_anim_step
    推步/字幕/口播稿全链天然可用；画面纪律换用本文件上方 html-explainer
    方法论（用户实弹验证效果好于微课原提示词），舞台消息协议与硬规则
    直接引 MC 单文案常量，防口径漂移（同 _HTML_HARD_RULES_CORE 立法初衷）。
    """
    return f"""你是学习软件的「原理图」制作高手。请为课程主题「{label}」（学科：{subject}）制作一页**分步动画原理课堂**：画面由 HTML/CSS/JS 写成，讲解由分步字幕与口播稿驱动，学生跟着老师一句一句看原理展开。

【画面纪律】（源自 html-explainer 方法论：模型不生成像素，而是写画面代码交给浏览器渲染——文字必须永远清晰、可复现）
1. 一场景一焦点：把原理拆成 5~8 步逐步展开，每步只有一个视觉主角，配角不加高亮；
2. 所有颜色定义为 CSS 变量（:root）再引用：明亮清爽的教学配色（浅色底、一个主色、一个强调色），禁止色值散落；
3. 只用系统字体栈：-apple-system, "Segoe UI", "Microsoft YaHei", sans-serif；
4. 术语与给定素材严格一致：图上的点名（如「点A」）、概念名词（如「中位线」）直接沿用素材原文，不生造名词；
5. 只依据给定素材讲解，不得虚构事实；核心公式/结论必须作为清晰文字出现在画面上（可用 Unicode 符号，不许用外链公式渲染器）；
6. 禁止大段文字！每步只配一句字幕（≤40字）与一句口播讲解（30~120字，像老师开口讲课，不得出现 $、反斜杠命令等读不出的符号），靠图形/动画/高亮讲透概念。

【输出格式】只返回一个 JSON 对象，不要任何解释或代码围栏：
{{"title": "不超过20字的原理图标题", "canvas_html": "动画舞台（完整 HTML 文档）", "steps": [{{"caption": "一句话字幕", "narration": "一步讲解口播"}}]}}，steps 共 5~8 步；第 i 步的 narration 就是老师那句口播，canvas_html 收到第 i 步消息时画面必须做出与之对应的可见变化（指过去/亮起来/动起来）；可额外加学生可玩的悬停标注/参数滑杆（不得干扰分步主线）。

canvas_html 分步舞台规则：
{MC._STEP_STAGE_RULES}

canvas_html 硬性要求：
{MC._HTML_HARD_RULES_CORE}
写 canvas_html 务必紧凑：不写注释、不留多余空行，总篇幅控制在 9000 字以内（硬上限 {MC.MAX_HTML_LEN} 字，超长整页作废）。

【课程素材】
{material[:_MAT_TOTAL_MAX]}
"""


def _has_material(snap: dict) -> bool:
    return bool((snap.get("items") or [])) or any(
        s.get("role") == "teacher" and str(s.get("text") or "").strip()
        for s in (snap.get("speech") or []))


def _cache_ref(uid: str):
    """复用键锚：本课 lesson_key（未建档课堂返回 None，库链路整体降级为旧行为）。"""
    try:
        return LB.get_lesson_key(str(uid))
    except Exception:  # noqa: BLE001 缓存只是加速路径，坏了不拦生成
        return None


def _pub_hit(hit: dict) -> dict:
    """库行 → 对外 done 视图（与 _public(done) 同形状 + seq/mode 版本信息）。"""
    c = hit["content"]
    return {"state": "done", "title": c.get("title") or hit.get("title") or "",
            "html": c.get("html") or "", "narration": c.get("narration") or "",
            "warning": c.get("warning") or "", "seq": hit["seq"],
            "mode": c.get("mode") or "off"}


def latest(uid: str) -> dict | None:
    """查库中本课最新原理图产物（重启后前端进页仍能秒出旧图）。无则 None。"""
    ref = _cache_ref(uid)
    if not ref:
        return None
    hit = PC.latest(str(uid), "lesson", ref)
    return _pub_hit(hit) if hit else None


def versions(uid: str) -> list:
    """本课历史版本档案 [{seq,title,mode,created_time}]（最新在前）；纯读库。"""
    ref = _cache_ref(uid)
    if not ref:
        return []
    return PC.versions(str(uid), "lesson", ref)


def view(uid: str, seq) -> dict | None:
    """看指定旧版产物（零外呼零扣分）：同 latest 的 done 视图；无则 None。"""
    ref = _cache_ref(uid)
    if not ref:
        return None
    hit = PC.get(str(uid), "lesson", ref, int(seq))
    return _pub_hit(hit) if hit else None


def promote(uid: str, seq) -> dict:
    """旧版设为当前版：库内拷贝成新版本（不碰 LLM、零扣分）；已是最新则 noop。"""
    ref = _cache_ref(uid)
    if not ref:
        return {"success": False, "error": "还没有本课，无历史版本"}
    r = PC.promote(str(uid), "lesson", ref, int(seq))
    log.log("xz_board", "explain_promote", "success" if r.get("success") else "fail",
            {"uid": str(uid), "seq": int(seq), "new_seq": r.get("seq"),
             "noop": bool(r.get("noop"))})
    return r


def start(uid: str, refresh: bool = False) -> dict:
    """开一页原理图作业（点击即调）。返回 {success, job|error, reused?}。

    板上没内容 → 拒收（不开工不扣分）；已有在飞作业 → 直接复用（防双开双扣分）；
    非 refresh 且库中有同课 done 产物 → 挂成 done job 秒回（规则 2：永远复用，零成本）；
    refresh → 开思考深度重画（规则 1，多花积分、更慢），成功写新版本行。
    素材取当前快照定格进提示词（生成期间继续上课不改已发出的请求）。
    """
    uid = str(uid)
    run = running_job(uid)  # 快速短路；权威判定在下方持锁处（防 check-then-act 竞态）
    if run:
        return {"success": True, "job": run, "reused": True}
    ref = _cache_ref(uid)
    if not refresh and ref:
        hit = PC.latest(uid, "lesson", ref)
        if hit:
            c = hit["content"]
            job = {"job_id": "cache-" + uuid.uuid4().hex[:12], "uid": uid,
                   "state": "done", "created_ts": int(time.time() * 1000),
                   "title": c.get("title") or "", "html": c.get("html") or "",
                   "narration": c.get("narration") or "",
                   "warning": c.get("warning") or "", "error": None}
            with _LOCK:
                _JOBS[job["job_id"]] = job
                _gc_locked()
            log.log("xz_board", "explain_cache_hit", "success",
                    {"uid": uid, "seq": hit["seq"], "mode": c.get("mode") or "off"})
            return {"success": True, "job": _public(job), "reused": "cache"}
    snap = LB.get_state(uid)
    a = LB.get_assign(uid) or {}
    label = a.get("label") or ""
    if not _has_material(snap):
        return {"success": False,
                "error": "黑板上还没有本课内容：先请老师开讲，再点「原理图」"}
    prompt = build_prompt(snap, label)
    mode = "on" if refresh else "off"
    job = {"job_id": uuid.uuid4().hex[:16], "uid": uid, "state": "generating",
           "created_ts": int(time.time() * 1000), "title": None, "html": None,
           "narration": None, "warning": None, "error": None}
    with _LOCK:
        # 查在飞 + 挂新 job 同一次持锁完成：并发双击不会各起一线程双扣分；
        # 只认黑板自身作业（排除带 _ref 的课级链，评审 Major-1：防跨轨劫持——
        # 课文页在飞时黑板复用会拿到基于课文正文而非板书快照的产物）
        for x in _JOBS.values():
            if x["uid"] == uid and x["state"] == "generating" and "_ref" not in x:
                return {"success": True, "job": _public(x), "reused": True}
        _JOBS[job["job_id"]] = job
        _gc_locked()
    threading.Thread(target=_run, args=(job["job_id"], uid, prompt, mode, ref),
                     daemon=True, name="board-explain").start()
    log.log("xz_board", "explain_start", "success",
            {"uid": uid, "job": job["job_id"], "prompt_len": len(prompt),
             "mode": mode})
    return {"success": True, "job": _public(job)}


def _finish(job_id: str, **fields) -> None:
    with _LOCK:
        j = _JOBS.get(job_id)
        if j:
            j.update(fields)


def _run(job_id: str, uid: str, prompt: str, mode: str = "off",
         cache_ref=None, pc_kind: str = "lesson", scene: str = _SCENE) -> None:
    """后台线程：LLM → interactive 校验 → 外链警告 → 终态 → 产物落库。
    任何失败只置 failed 不重发（微课纪律：防双扣分）；无请求上下文故走显式 uid 计费链。
    mode="on"（重新生成）显式开思考；mode="off" 显式关思考（与场景策略表同口径，
    显式传参不依赖表命中，测试桩/调用方行为可预测）。
    pc_kind/scene：归档轨道与计量场景（黑板链默认 "lesson"/原理图；课文页走
    "course_lesson" 与实验台场景，两轨互不串，图文结合轮 2026-11-12）。"""
    try:
        raw = call_llm_for_user(uid, prompt, scene=scene, timeout=_LLM_TIMEOUT,
                                thinking=mode)
        obj = MC.validate_scene_content("interactive", raw)
        warn = MC.external_ref_note(obj.get("html") or "")
        # 先归档再置 done（同 board_lesson 评审 M-3「先落盘再记账」）：轮询到 done 的
        # 那一刻库行必已在——否则前端「秒回旧图」与测试断言都会撞进写库窗口
        if cache_ref:
            try:
                PC.put(uid, pc_kind, cache_ref,
                       {"title": obj.get("title") or "", "html": obj.get("html") or "",
                        "narration": obj.get("narration") or "",
                        "warning": warn or ""}, mode=mode)
            except Exception as e:  # noqa: BLE001 落库失败不影响本次交付
                log.log("xz_board", "explain_cache_put", "fail",
                        {"uid": uid, "job": job_id, "err": str(e)[:120]})
        _finish(job_id, state="done", title=obj.get("title"),
                html=obj.get("html"), narration=obj.get("narration"),
                warning=warn)
        log.log("xz_board", "explain_done", "success",
                {"uid": uid, "job": job_id, "html_len": len(obj.get("html") or ""),
                 "warn": bool(warn), "mode": mode})
    except cr.InsufficientCreditsError as e:
        _finish(job_id, state="failed", error=str(e) or "积分不足")
        log.log("xz_board", "explain_done", "fail",
                {"uid": uid, "job": job_id, "reason": "credits"})
    except Exception as e:  # noqa: BLE001 生成失败不影响黑板主流程
        _finish(job_id, state="failed",
                error=("模型返回的内容不完整或不合格式，再点一次试试"
                       if isinstance(e, ValueError) else
                       f"生成失败：{str(e)[:80]}"))
        log.log("xz_board", "explain_done", "fail",
                {"uid": uid, "job": job_id, "err": str(e)[:120]})


# ---------------------------------------------------------------- 课文级视觉产物（图文结合轮 2026-11-12，用户裁定 A 方案）
# 课文页两个常驻展示位（原理图/交互实验）的后端链：与黑板 start() 同纪律——
# 有 done 产物零成本秒回、同槽位防双开、refresh 才深度重画、产物进 principle_cache。
# 归档轨 ("course_lesson", f"{lid}:{kind}") 与黑板 "lesson" 轨完全隔离，互不劫持；
# 在飞去重按「同用户+同课文同类型」细粒度判定（原理图与实验互不阻塞，
# 区别于黑板的全局限一单：展示位天然一课两槽）。
LESSON_VIS_KINDS = ("principle", "lab")   # 公开：路由层遍历展示位/校验 kind 用
_LESSON_PC_KIND = "course_lesson"


def _lesson_ref(lid, kind: str) -> str:
    return f"{int(lid)}:{kind}"


def lesson_latest(uid: str, lid, kind: str) -> dict | None:
    """该课文该类最新 done 产物视图（进页直显；纯读库零外呼零扣分）。无则 None。"""
    hit = PC.latest(str(uid), _LESSON_PC_KIND, _lesson_ref(lid, kind))
    return _pub_hit(hit) if hit else None


def build_lesson_prompt(ctx: dict, kind: str) -> str:
    """课文标题+概要+正文 → 原理图/交互实验生成提示词。

    输出契约与 build_prompt 同形（interactive JSON，validate_scene_content
    直接复用）；事实源只有课文本身，术语/结论沿课文原文。素材截进
    _LESSON_MAT_MAX（课级单独定量，比黑板快照宽）。"""
    body = (f"课文标题：{ctx.get('title') or ''}\n"
            f"学科：{ctx.get('subject_name') or ''}\n"
            f"课文概要：{ctx.get('description') or '（无）'}\n\n"
            f"课文正文（Markdown 原文，讲解事实的唯一来源）：\n"
            f"{str(ctx.get('content_md') or '')[:_LESSON_MAT_MAX]}")
    fmt = ("【输出格式】只输出一个 JSON 对象，不要任何解释或代码围栏：\n"
           '{"title": "不超过20字的标题", "narration": "打开本页时朗读的一句导语", '
           '"html": "完整 HTML 文档字符串（<!DOCTYPE html> 开头，内联全部样式与脚本）"}\n'
           f"写 html 务必紧凑：不写注释、不留多余空行、选择器与变量名简短；"
           f"总篇幅控制在 9000 字以内（硬上限 {MC.MAX_HTML_LEN} 字，超长整页作废）。")
    if kind == "lab":
        return f"""你是学习软件的「交互实验」制作高手。请根据下面这篇课文，制作一页**自包含、可动手操作的 HTML 实验台**：学生拨动参数就能立刻看到图形/数值/状态跟着变，在做实验中把课文的核心概念亲手验一遍。

【实验纪律】
1. 画面全部用 HTML/CSS/原生 JS 完成，禁止引用任何外部资源（无 CDN/网络字体/外链图片，沙箱环境离线渲染）；
2. 设 2~4 个可调参数（滑杆/数字输入/开关），每个参数必须有肉眼可见的对应反馈（曲线、数值表或示意动画），参数范围要有意义、防无意义极值；页面至少有一处真图形（<svg> 或 <canvas>）随参数联动，只有数值与文字不算实验台；JS 要写完整可运行的语法（语法错误会让绘图脚本静默不执行，画布全白）；
3. 每个实验配一句「观察要点」，用课文里的概念直接说人话；术语与课文原文严格一致，不生造名词；
4. 所有颜色定义为 CSS 变量（:root）再引用：明亮清爽的教学配色（浅色底、一个主色、一个强调色），禁止色值散落；只用系统字体栈 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif；
5. 只依据给定课文讲解，不得虚构事实；核心结论必须作为清晰文字出现在页面上（可用 Unicode 符号，不许用外链公式渲染器）。

{fmt}

【课文素材】
{body}
"""
    return f"""你是学习软件的「原理图」制作高手。请根据下面这篇课文，制作一页**自包含、可交互的 HTML 原理讲解页**，帮学生一眼看懂这篇课文的核心原理。

【画面纪律】（源自 html-explainer 方法论：模型不生成像素，而是写画面代码交给浏览器渲染——文字必须永远清晰、可复现）
1. 画面全部用 HTML/CSS/原生 JS 完成，禁止引用任何外部资源（无 CDN/网络字体/外链图片，沙箱环境离线渲染）；
2. 一场景一焦点：把原理拆成 3~6 个步骤逐步展开，每步只有一个视觉主角，配角不加高亮；视觉主角必须是真图形（内联 <svg>/<canvas>/CSS 图形）：讲曲线、区域、图形、结构就画出形，公式条、进度条、纯文字卡不算图；JS 要写完整可运行的语法（语法错误会让整页静默只剩文字，图全部空白）；
3. 所有颜色定义为 CSS 变量（:root）再引用：明亮清爽的教学配色（浅色底、一个主色、一个强调色），禁止色值散落；
4. 只用系统字体栈：-apple-system, "Segoe UI", "Microsoft YaHei", sans-serif；
5. 动效只用 CSS transition/@keyframes + 原生 JS；页面必须至少含两种交互：步骤按钮（上一步/下一步/自动播放）+ 悬停标注或参数滑杆；
6. 术语与课文严格一致：图上的概念名词直接沿用课文原文，不生造名词；
7. 只依据给定课文讲解，不得虚构事实；核心公式/结论必须作为清晰文字出现在画面上（可用 Unicode 符号，不许用外链公式渲染器）。

{fmt}

【课文素材】
{body}
"""


def start_for_lesson(uid: str, ctx: dict, kind: str, refresh: bool = False) -> dict:
    """开一单课文级原理图/交互实验（课文页展示位点击即调）。

    与 start() 同纪律：库有 done 产物→秒回 reused="cache"（零成本）；
    同槽位（uid+lid+kind）在飞→复用防双击双扣分；refresh→开思考深度重画。
    课文正文未生成→拒收（不开工不扣分）。ctx 由调用方做过归属校验。
    """
    if kind not in LESSON_VIS_KINDS:
        return {"success": False, "error": "未知的视觉产物类型"}
    uid = str(uid)
    if not str(ctx.get("content_md") or "").strip():
        return {"success": False, "error": "这篇课文还没有正文：先生成课文，再来配图"}
    ref = _lesson_ref(ctx["id"], kind)
    if not refresh:
        hit = PC.latest(uid, _LESSON_PC_KIND, ref)
        if hit:
            c = hit["content"]
            job = {"job_id": "cache-" + uuid.uuid4().hex[:12], "uid": uid,
                   "state": "done", "created_ts": int(time.time() * 1000),
                   "title": c.get("title") or "", "html": c.get("html") or "",
                   "narration": c.get("narration") or "",
                   "warning": c.get("warning") or "", "error": None}
            with _LOCK:
                _JOBS[job["job_id"]] = job
                _gc_locked()
            log.log("course", "lesson_visual_cache_hit", "success",
                    {"uid": uid, "ref": ref, "seq": hit["seq"]})
            return {"success": True, "job": _public(job), "reused": "cache"}
    prompt = build_lesson_prompt(ctx, kind)
    mode = "on" if refresh else "off"
    job = {"job_id": uuid.uuid4().hex[:16], "uid": uid, "state": "generating",
           "created_ts": int(time.time() * 1000), "title": None, "html": None,
           "narration": None, "warning": None, "error": None, "_ref": ref}
    scene = _SCENE if kind == "principle" else _LAB_SCENE
    with _LOCK:
        # 同槽位在飞去重（查+挂在一次持锁内，同黑板纪律）
        for x in _JOBS.values():
            if x["uid"] == uid and x["state"] == "generating" and x.get("_ref") == ref:
                return {"success": True, "job": _public(x), "reused": True}
        _JOBS[job["job_id"]] = job
        _gc_locked()
    threading.Thread(target=_run,
                     args=(job["job_id"], uid, prompt, mode, ref),
                     kwargs={"pc_kind": _LESSON_PC_KIND, "scene": scene},
                     daemon=True, name="lesson-visual").start()
    log.log("course", "lesson_visual_start", "success",
            {"uid": uid, "job": job["job_id"], "ref": ref, "mode": mode,
             "prompt_len": len(prompt)})
    return {"success": True, "job": _public(job)}
