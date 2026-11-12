# -*- coding: utf-8 -*-
"""小智云端讲师黑板（2026-11-04 P1；11-04 晚「讲义分块版式」；三期=脑图+跟讲指认）。

形态铁律（用户裁定 + 项目五期契约同源）：黑板严禁大段文字流水账，内容必须是
分块讲义卡——主干卡/题干卡/选项卡/一句话推演卡(≤40字)/公式卡/短注卡；被打断时
老师用 board_replace/board_remove 改写单卡，而不是只会往下堆。超限**拒收**（强制
大脑拆短句），这是与微课「禁大段文字」规范同源的口径。

三期契约（评审四大地基修正落地，见开发日志）：
- items 保持扁平 + parent_id（树由前端拼装）：status_line/replace/remove/容量淘汰
  全部按扁平卡号工作，嵌套树会打穿既有引用链；
- 焦点单槽持续态 b["focus"]={item_id,anchor,mark,reveal,seq}：1.2s 轮询合并快照
  装不下逐句事件，用单调 seq 事件号 + 持续态消竞态；highlighted 由 focus 派生；
- 指认搭现有工具顺风车（point/reveal 参数），不新增第 11 个工具——每句多一次
  云端往返就慢一拍；
- 锚点预埋：写卡正文用〔…〕标可指片段，后端解析成 anchors[]、正文剥锚存储，
  point=N 指第 N 个锚；图卡 point=N 命中渲染契约 marks 序号，reveal=N 分步作图。

分工铁律（来自 ROG-K 两通电话取证结论，详见 _tmp_review/phone/rogk_recon6/7.json）：
- 小智云端会把 tools/call 返回文本转述/压缩改写（无逐字念稿协议），所以教学内容
  只进黑板卡片（本系统屏幕渲染），返回文本保持三层：确认句 + 状态行 + 导演指令；
- 素材文本必须进返回（云端大脑要"知道"讲什么才能讲），但限长 _MATERIAL_MAX 防
  上下文拥挤（ROG 侧 v1.9.139 外部工具描述统一截 400 字符同源纪律）；
- 工具命名全部带 board_/lesson 前缀，绝不撞小智官方工具名——撞名会让云端把
  整包工具列表丢弃（取证铁律）。

状态不落库：黑板是临时草稿，进程重启即失（物理直觉一致，可接受行为）。
用户隔离：_boards 以 uid 为键；桥侧 uid 启动时按 XZ_MCP_USER 解析一次，
HTTP 侧按 g.user_id 读取，两端只有同一用户才看得见同一块板。
"""
from __future__ import annotations

import copy
import re
import threading
import time
import uuid
from pathlib import Path

from config import VAULT_DIR
from services import board_plot as BP
from logger_module import debug_logger as log

# ---------------------------------------------------------------- 状态容器

MAX_ITEMS = 40          # 黑板容量，超限丢最旧（物理黑板擦写行为；主干连同子卡整枝淘汰）
_MATERIAL_MAX = 800     # 返回文本里素材块限长（字符）
# ---- 题目原图上板（C 方案 2026-11-08 用户裁定：原图打底 + 老师自由补画）----
_IMG_MAX_PER_PROBLEM = 3      # 单题最多几张原图（防批量 OCR 图海淹板）
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_MD_IMG_REF_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")   # MD 图片引用整体（剥引用用）
_LIST_TOP_N = 10        # 错题菜单一次列几道
_STATUS_MAX = 380       # 状态行限长（评审 2026-11-09：带卡正文摘要后放宽，老师要能
                        # 照板重讲；仍防长板把返回文本撑爆）
_UNEXPLAINED_MAX = 24   # 「写了还没讲」卡队列保留上限（镜检只需尾部若干张）

# ---- 「AI老师讲」网页指派（v0.2.8 多入口进黑板）----
# 前端入口按钮 POST /api/board/assign 记一条待讲目标（错题/知识点），老师首次
# get_lesson_material 时拿到注入指导语并条件消费（kp 素材瞬抖读不到时不误清，
# 留给下次取料重试；评审 Minor-2）；
# 超时未被取用自动作废（点了没上课的陈旧指派不会误开讲）。
# 指派不被擦板作废（中位线定理误杀事故 2026-11-07 用户裁定 A）：擦板只整理板
# 面内容，指派是学生换课意图，只被取料消费/TTL 过期/新指派覆写三件事终结。
_ASSIGN_TTL_S = 600     # 指派有效期（秒）：超时视为学生没真上课，静默作废
# text 型=课文框选原文指派（追问笔记树轮 2026-11-12）：target_id=文本稳定哈希（同源去重用），
# raw_text 随指派存内存（进程重启即失，指派本就是 TTL 分钟级短命语义）。
_ASSIGN_KINDS = ("error", "kp", "text")
_ASSIGN_STORE_MAX = 40  # 指派标题存储硬顶（防绕过展示层限长直调 set_assign 塞长文；
                        # 必须 ≥ routes_board._ASSIGN_LABEL_MAX 展示层限长，评审 Minor-4）

# ---- 口播字幕流与课件归档（黑板两段式版式轮 2026-11-05）----
# 字幕来源唯一：EXE 虚拟小智把云端下发的 tts sentence / stt 文本上报
# /api/board/speech（真机 ESP32 那条路文本只到设备，服务端拿不到 → 前端退化为卡片流）。
_SPEECH_MAX = 400       # 内存里保留的字幕条数（滚动淘汰；太短会把长讲解的讲稿烧缺）
_SPEECH_OUT = 160       # state 一次回传给前端的条数（前端按 id 去重增量渲染）
_SPEECH_TEXT_MAX = 200  # 单句限长（超长截断，不上文字墙）
_CAPTION_MAX = 400      # 烧进图里的讲稿限长（一图的解说不宜长）
_OUTBOX_MAX = 40        # 待归档页上限（前端逐张出 PNG 后回执删除）
_SPEECH_ROLES = ("teacher", "student")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _now_ms() -> int:
    return int(time.time() * 1000)

# 讲义卡限长（字符）：超限拒收并回拆卡指导——"每块只许短句"的代码化铁律。
# 该表同时是 kind 白名单：登记 topic=脑图主干卡（三期），叶子卡挂在主干下面。
_CARD_LIMITS = {"step": 40, "note": 40, "formula": 80, "options": 160,
                "problem": 200, "plot": 60, "topic": 20}
_KIND_ALIAS = {"text": "note"}          # 大脑惯性写 text → 归一为 note
_FORMULA_KINDS = ("formula",)
# 支持〔〕锚点指认的文本卡型；plot 走契约 marks 序号指认；formula/options 整卡高亮
_POINT_TEXT_KINDS = ("topic", "problem", "step", "note")
_ANCHOR_RE = re.compile(r"〔([^〕]{1,40})〕")   # 正文内可指片段（≤40 字/个）

_lock = threading.Lock()
_boards: dict[str, dict] = {}   # uid -> {rev, seq, items, focus, focus_seq, ...}
_bridge_uid: str | None = None  # 桥绑定的用户（启动时解析，routes_board 展示用）


def _board(uid: str) -> dict:
    """取/建该用户黑板。调用方必须持有 _lock。"""
    b = _boards.get(uid)
    if b is None:
        b = {"rev": 0, "seq": 0, "items": [], "source_error_id": None,
             "bridge_connected": False, "anim": None,
             "focus": None, "focus_seq": 0,
             # 字幕流与归档出件箱：speech_seq 单调发号；claim_upto=已分配给某张图的
             # 最大字幕号（闭窗时整段认领，保证一句话不会被两张图重复烧）；
             # lesson_key=本课键（换题即轮换，一张题=一份课件）；outbox=待出 PNG 的定稿页
             "speech": [], "speech_seq": 0, "claim_upto": 0,
             "lesson_key": None, "outbox": [], "outbox_seq": 0,
             # 网页「AI老师讲」指派：{kind, id, label, ts}，一次性消费（见上常量区）
             "assign": None,
             # 讲课连续性（2026-11-09「讲课不连续」事故）：
             # lesson_kp=本课在讲的指定知识点 {id,label}——指派一次性消费后素材
             # 仍须课内可重放（学生说「继续/没听懂」时老师取料拿得回内容）；
             # unexplained=写上板但老师还没开口讲过的卡号队列（老师一句口播即清零）
             "lesson_kp": None, "unexplained": []}
        _boards[uid] = b
    return b


def set_bridge_status(connected: bool, uid: str | None = None) -> None:
    """桥连接态回写（前端指示灯数据源）；uid 给定时同时记录桥绑定用户。
    评审 Major-4：桥只绑定一个用户，只写它自己的板——不串别的用户的板，
    且写板必升 rev，否则前端 changed=False 早退指示灯永远不更新。"""
    global _bridge_uid
    with _lock:
        if not uid:
            return
        _bridge_uid = uid
        b = _board(uid)
        b["bridge_connected"] = connected
        b["rev"] += 1


def get_state(uid: str, since_rev: int = 0) -> dict:
    """HTTP 轮询出口：since 与当前 rev 一致时只回 changed=False（省全量 items）。"""
    with _lock:
        b = _boards.get(uid)
        rev = b["rev"] if b else 0
        if rev == since_rev:
            return {"rev": rev, "changed": False}
        b = _board(uid)
        return _snapshot(b)


def _anim_pub(a):
    """对外快照：去掉服务端内部字段（前端只需 state/title/canvas_html/steps/current）。
    评审融合轮 M-1：gen/style/src 都是服务端去重专用标记，新增内部字段务必进此集合。
    steps 是内层可变列表，深拷贝后才出锁，保持「内层不漏」纪律。"""
    if not a:
        return None
    out = {k: v for k, v in a.items() if k not in ("gen", "style", "src")}
    if isinstance(out.get("steps"), list):
        out["steps"] = copy.deepcopy(out["steps"])
    return out


def _snapshot(b: dict) -> dict:
    """持锁内的 state 快照（clear/write 等变更后直接回给调用方）。
    deepcopy：卡内 data 是嵌套列表（curves/segs/points），浅拷贝会把内部可变对象
    漏给调用方；卡内 data 约定只整体替换、不改内层。"""
    return {
        "rev": b["rev"], "changed": True,
        "items": copy.deepcopy(b["items"]),
        "source_error_id": b["source_error_id"],
        "bridge_connected": b["bridge_connected"],
        "anim": _anim_pub(b.get("anim")),
        "focus": dict(b["focus"]) if b.get("focus") else None,
        # 字幕流只回最近 _SPEECH_OUT 条（前端按 id 增量渲染，整页不滚只内区滚）
        "speech": copy.deepcopy(b["speech"][-_SPEECH_OUT:]),
        "lesson_key": b.get("lesson_key"),
        # 出件箱：已被新图顶走/擦板定稿的页，前端逐张离屏渲染成 PNG 上传后回执删除
        "outbox": copy.deepcopy(b.get("outbox") or []),
    }


def clear_board(uid: str) -> dict:
    """擦黑板（HTTP 与 board_clear 工具共用），返回擦后的 state。
    擦板=这一页板书讲完：先把还挂着的那张图的口播闭窗入库（outbox），
    再把板上全部图卡送进出件箱，前端随后逐张出 PNG 归档成课件页。"""
    with _lock:
        b = _board(uid)
        n = len(b["items"])
        _close_open_caption_locked(b)          # 最后一张图的口播先定稿
        for i in b["items"]:
            if i["kind"] == "plot":
                _outbox_push_locked(b, i)
        b["items"] = []
        b["unexplained"] = []       # 板空了进度镜同步归零（lesson_kp 与 assign 同理保留）
        b["source_error_id"] = None
        # 擦板不清指派（中位线定理误杀事故 2026-11-07）：常见流是「点指派开新课 →
        # 先擦旧板书 → 请老师上课」，旧语义把刚下发的指派连带作废，老师取料落回
        # 错题清单。指派只被取料消费/TTL 过期/新指派覆写终结。
        # 擦板不清舞台（融合轮 2026-11-09 用户裁定）：原理图是课级资产与指派同口径，
        # 旧语义「擦板连舞台一起收」是为换题设计，但换题由新指派覆写重开工；
        # 同课重讲流里擦板不该把刚生成的画面丢弃（学生随时可看）。
        if b.get("focus"):
            b["focus"] = None
            b["focus_seq"] += 1   # 焦点消失也是事件：seq 单调，前端才认这一帧
        b["rev"] += 1
        snap = _snapshot(b)
    log.log("xz_board", "clear", "success", {"uid": uid, "removed": n,
                                             "outbox": len(snap.get("outbox") or [])})  # 日志 I/O 锁外（评审 Minor-3）
    return snap


# ---------------------------------------------------------------- 网页「AI老师讲」指派（v0.2.8）

def set_assign(uid: str, kind: str, target_id, label: str, raw_text: str = "") -> dict:
    """记一条网页指派讲解目标（入口按钮→跳黑板→老师取料时注入开讲指导）。
    归属校验由调用方（routes_board）走素材唯一实现把关；重复指派覆写（学生改口）。
    raw_text：text 型指派的选中原文全文（label 只是提示条短标题，指导语要用原文）。"""
    if kind not in _ASSIGN_KINDS:  # 白名单在此生效，防绕过路由直调时 _assign_directive 落到错误文案分支（CodeReview Suggest-5）
        raise ValueError(f"unknown assign kind: {kind}")
    a = {"kind": kind, "id": target_id, "label": str(label or "")[:_ASSIGN_STORE_MAX],
         "ts": _now_ms()}
    if kind == "text" and raw_text:
        a["raw_text"] = str(raw_text)[:600]
    with _lock:
        _board(uid)["assign"] = a
    log.log("xz_board", "assign_set", "success",
            {"uid": uid, "kind": kind, "id": target_id})
    return a


def _fresh_assign_locked(b: dict):
    """取未过期指派；过期即清（调用方持锁）。"""
    a = b.get("assign")
    if not a:
        return None
    if _now_ms() - int(a.get("ts") or 0) > _ASSIGN_TTL_S * 1000:
        b["assign"] = None
        return None
    return dict(a)


def get_assign(uid: str):
    """查当前指派（黑板页提示条/自动开课用），不消费。无/过期回 None。"""
    with _lock:
        return _fresh_assign_locked(_board(uid))


def _take_assign(uid: str):
    """消费指派（取到即清）。无/过期回 None。现仅供测试/应急；
    取料主流程已改条件消费（get_assign + _drop_assign，评审 Minor-2）。"""
    with _lock:
        b = _board(uid)
        a = _fresh_assign_locked(b)
        if a:
            b["assign"] = None
        return a


def _drop_assign(uid: str, a: dict) -> None:
    """按 ts 认账清除指派（评审 Minor-2）：只清自己读过的那一条，
    并发间被学生改口覆写的新指派不误伤。幂等。"""
    with _lock:
        b = _board(uid)
        cur = b.get("assign")
        if cur and a and cur.get("ts") == a.get("ts"):
            b["assign"] = None


def _assign_directive(uid: str, a: dict) -> str:
    """「📌网页指定讲解」指导语（注入 get_lesson_material 头部，调用方已消费）。
    kp 型现取素材（知识点描述/掌握度/名下错题）；素材已删则指导语落空返空串，
    绝不把老师往不存在的内容上引。"""
    if a["kind"] == "text":
        t = str(a.get("raw_text") or "").strip()
        if not t:
            return ""
        return (f"📌网页指定讲解：学生刚从课文里框选了这段内容，点名要你讲：\n「{t}」\n"
                "先 board_write 建 topic 主干卡把这段内容讲透（它在说什么→为什么→"
                "关键处拆开讲），适合画图的地方 board_draw 配图。\n"
                "讲课纪律：一张卡讲透再写下一张（写完就停嘴连写多张=没上课）；"
                "板上所有卡都讲完、学生点头之前，不要结课道别。\n")
    if a["kind"] == "kp":
        try:
            from routes_micro_course import kp_teach_pack
            pack = kp_teach_pack(uid, a["id"])
        except Exception as e:  # noqa: BLE001 素材采集失败不阻断取料主流程
            log.log("xz_board", "assign_kp_pack", f"error:{e}", {"uid": uid, "kp": a["id"]})
            pack = None
        if not pack:
            return ""
        errs = "；".join(f"错题id {e[0]}：{e[1]}" for e in (pack.get("errors") or [])) \
            or "（该知识点下暂时没有错题，举日常例子讲）"
        m = pack.get("mastery")
        prof = "尚未评估" if m is None or int(m) < 0 else f"{int(m)}%"
        return (f"📌网页指定讲解：学生点名要你讲知识点「{pack['name']}」"
                f"（学科 {pack.get('subject') or '未分类'}，当前掌握度 {prof}）。"
                f"知识点描述：{pack.get('desc') or '（无描述）'}。"
                "先 board_write 建 topic 主干卡把概念讲透（定义→关键点→易错处），"
                f"再从下面清单挑该知识点最有代表性的 1-2 道错题用 board_show_problem "
                f"上黑板配例讲（学生刚答错过，敲例子最管用）：{errs}。\n"
                "讲课纪律：一张卡讲透再写下一张（写完就停嘴连写多张=没上课）；"
                "板上所有卡都讲完、学生点头之前，不要结课道别。\n"
                "本课原理图已自动后台生成中（不用你开工，再调 board_render_anim 只会重复扣费）："
                "先把基本概念卡讲完；工具返回提示舞台就绪后，调 board_anim_step(0) 切入舞台，"
                "之后每讲一段推一步，照口播稿念，画面跟着变。\n")
    return (f"📌网页指定讲解：学生刚从网页点名要讲错题 id {a['id']}（{a['label']}）。"
            f"不用翻清单选题，第一步就 board_show_problem(error_id={a['id']}) "
            "把它写上黑板开讲错因。\n"
            "本课原理图已自动后台生成中（不用你开工，再调 board_render_anim 会覆写"
            "刚开工的舞台还重复扣费）：先把错因概念讲完，"
            "舞台就绪提示出现后调 board_anim_step(0) 切入，每讲一段推一步。\n")


def _kp_replay_text(uid: str, lk: dict) -> str:
    """课内指定知识点素材重放（讲课连续性）：指派已消费，但本课在讲的知识点
    还在——学生说「继续/没听懂」时老师重新取料，拿回描述与板面进度接着讲。
    素材已被删则摘除常驻，回落正常取料流程（绝不把老师往不存在的内容上引）。"""
    try:
        from routes_micro_course import kp_teach_pack
        pack = kp_teach_pack(uid, lk.get("id"))
    except Exception as e:  # noqa: BLE001 重放失败不阻断取料主流程
        log.log("xz_board", "kp_replay", f"error:{e}", {"uid": uid, "kp": lk.get("id")})
        return ""
    if not pack:
        with _lock:
            b = _board(uid)
            if (b.get("lesson_kp") or {}).get("id") == lk.get("id"):
                b["lesson_kp"] = None
        return ""
    return (f"续讲：本课正在讲学生点名的知识点「{pack['name']}」"
            f"（学科 {pack.get('subject') or '未分类'}，素材全课有效）。"
            f"知识点描述：{pack.get('desc') or '（无描述）'}。\n"
            + status_line(uid) + "\n"
            "照着板面从上往下讲：先对照状态行找出还没讲过的卡，从最旧那张起一张一张讲透；"
            "学生说「继续/没听懂/再讲一下」时，就照那几张卡的正文换个例子或更直白的说法重讲，"
            "需要改写某张卡用 board_replace；原理图舞台若已就绪，也可用 board_anim_step 重推一步带学生再看一遍。"
            "板上卡片没讲完之前，严禁结课道别。")


def _extract_anchors(text: str) -> tuple[str, list[str]]:
    """正文剥锚：〔片段〕→ 片段（正文干净），片段按出现顺序进 anchors[]。"""
    anchors: list[str] = []
    for m in _ANCHOR_RE.finditer(text or ""):
        frag = m.group(1).strip()
        if frag:
            anchors.append(frag)
    clean = _ANCHOR_RE.sub(lambda m: m.group(1).strip(), text or "").strip()
    return clean, anchors


def _prune_focus_locked(b: dict) -> None:
    """焦点引用的卡已不在板上（淘汰/删除后调用）：清焦点，防前端追着幽灵指认。"""
    f = b.get("focus")
    if f and not any(i["id"] == f["item_id"] for i in b["items"]):
        b["focus"] = None
        b["focus_seq"] += 1


def _set_focus_locked(b: dict, item_id: int, anchor=None, mark=None, reveal=None) -> None:
    """焦点单槽：写持续态 + 单调事件号；highlighted 全部由 focus 派生。
    调用方必须已持 _lock。"""
    b["focus_seq"] += 1
    b["focus"] = {"item_id": item_id, "anchor": anchor, "mark": mark,
                  "reveal": reveal, "seq": b["focus_seq"]}
    for i in b["items"]:
        i["highlighted"] = (i["id"] == item_id)
    b["rev"] += 1


# 旁白自动跟随的目标词门槛：裸单字母点标（geometry 派生 marks 就是 A/B/C 单字）
# 只认「点A」/「A点」形式命中，防英文缩写/ABCD 连写误拖激光；纯数字/标点短语
# 不参与（误命中面大）；老师显式 point=N 仍可指认任何锚/marks，只限自动通道。
_FOLLOW_SKIP_RE = re.compile(r"^[\s\d.,%/\-+×÷()（）]+$")


def _follow_pos(sentence: str, word: str) -> int:
    """目标词在旁白句中的命中位置（最新一次），未命中 -1。"""
    w = str(word or "").strip()
    if not w or _FOLLOW_SKIP_RE.match(w):
        return -1
    if len(w) == 1:
        p = -1
        for cand in ("点" + w, w + "点"):
            q = sentence.rfind(cand)
            if q > p:
                p = q
        return p
    return sentence.rfind(w)


def _auto_follow_locked(b: dict, uid: str, sentence: str) -> bool:
    """激光跟嘴：老师刚落的一句旁白，扫全板可指对象（文本卡〔〕锚、图卡命名
    marks），取句中**最靠句尾**的命中（句尾是新信息：「先看A再连到B」指B）。
    老师的显式指认与旁白本同源，后事件赢即可；自动跟随只是老师「忘指」时的
    兜底，不伪造老师手势（无命中不动焦点）。命中后前端激光常驻追着焦点走。"""
    best = None    # (pos, item_id, anchor, mark, reveal)
    for c in b["items"]:
        k = c.get("kind")
        if k in _POINT_TEXT_KINDS:
            for idx, a in enumerate(c.get("anchors") or []):
                p = _follow_pos(sentence, str(a or ""))
                if p >= 0 and (best is None or p > best[0]):
                    best = (p, c["id"], idx + 1, None, None)
        elif k == "plot":
            for idx, m in enumerate((c.get("data") or {}).get("marks") or []):
                p = _follow_pos(sentence, str((m or {}).get("name") or ""))
                if p >= 0 and (best is None or p > best[0]):
                    rv = None
                    f0 = b.get("focus")
                    if f0 and f0.get("item_id") == c["id"]:
                        rv = f0.get("reveal")   # 已在台上的图：保住分步进度
                    best = (p, c["id"], None, idx + 1, rv)
    if not best:
        return False
    _set_focus_locked(b, best[1], anchor=best[2], mark=best[3], reveal=best[4])
    log.log("xz_board", "auto_focus", "hit",
            {"uid": uid, "item_id": best[1], "anchor": best[2], "mark": best[3],
             "pos": best[0]})
    return True


def _append_locked(b: dict, kind: str, text: str, data=None, anchors=None) -> int:
    """持锁内追加讲义卡并升 rev，返回卡号。调用方必须已持 _lock。
    扁平存储 + parent_id 挂主干（树前端拼）；容量淘汰按「枝」：主干出局连子卡一起。
    二期升级：每卡带 ts（毫秒）；plot 卡入板即「上一张图讲完」→ 闭窗定稿进 outbox。"""
    if kind == "plot":
        _close_open_caption_locked(b)          # 先收上一张图的口播（窗尾=当前字幕号）
        if not b.get("lesson_key"):
            b["lesson_key"] = uuid.uuid4().hex[:16]
    b["seq"] += 1
    card = {"id": b["seq"], "kind": kind, "text": text,
            "highlighted": False, "ts": _now_ms()}
    if kind == "plot":
        # cap_from：本图从哪条字幕起算（上一张图闭窗后的下一条，一句话不会被两张图重复烧）
        card["cap_from"] = b["speech_seq"] + 1
    if kind == "topic":
        card["parent_id"] = None
    else:
        cur_topic = next((i["id"] for i in reversed(b["items"])
                          if i["kind"] == "topic"), None)
        card["parent_id"] = cur_topic
    if anchors:
        card["anchors"] = list(anchors)
    if data is not None:
        card["data"] = data
    b["items"].append(card)
    while len(b["items"]) > MAX_ITEMS:
        head = b["items"][0]
        if head["kind"] == "topic":
            drop = {head["id"]} | {i["id"] for i in b["items"]
                                   if i.get("parent_id") == head["id"]}
            gone = [i for i in b["items"] if i["id"] in drop]
            b["items"] = [i for i in b["items"] if i["id"] not in drop]
        else:
            gone = [b["items"].pop(0)]
        for i in gone:   # 被淘汰的旧图也是一页讲过的板书 → 补收口后送进出件箱
            if i["kind"] == "plot":
                if "caption" not in i:
                    _fill_caption_locked(b, i)
                _outbox_push_locked(b, i)
    _prune_focus_locked(b)
    # 讲课进度镜：新卡进「写了没讲」队列，被淘汰出板的卡号一并剔除
    uq = b.setdefault("unexplained", [])
    uq.append(b["seq"])
    live = {i["id"] for i in b["items"]}
    b["unexplained"] = [x for x in uq if x in live][-_UNEXPLAINED_MAX:]
    b["rev"] += 1
    return b["seq"]


_SENT_END = ("。", "！", "？", "；", "，", "、", ".", "!", "?", "…", ")", "）", "”")


def _join_lines(lines) -> str:
    """字幕句子串成一段讲稿：缺句末标点的补个逗号，不让字粘成一团。"""
    out = ""
    for s in lines:
        s = (s or "").strip()
        if not s:
            continue
        if out and not out.endswith(_SENT_END):
            out += "，"
        out += s
    return out


def _fill_caption_locked(b: dict, card: dict, upto_id=None) -> str:
    """给一张图卡收口讲稿：把 [cap_from, 窗尾] 内的老师口播整段认下来。
    窗尾默认当前已发的最大字幕号（即「到目前为止老师针对这张图说过的全部话」）。"""
    frm = int(card.get("cap_from") or 1)
    end = int(b["speech_seq"] if upto_id is None else upto_id)
    if end < frm:
        end = frm - 1
    cap = _join_lines([s["text"] for s in b["speech"]
                       if s["role"] == "teacher" and frm <= s["id"] <= end])
    # 字幕缓冲是滚动淘汰的：窗开头的话可能已被挤掉。宁可明写「缺了 N 句」，
    # 也好过把一段残缺讲稿静默烧进课件图里（老师事后无从察觉）。
    if b["speech"]:
        lost = b["speech"][0]["id"] - frm
        if lost > 0:
            cap = f"［前 {lost} 句已超出字幕缓冲，未记入］" + cap
    if len(cap) > _CAPTION_MAX:
        cap = cap[:_CAPTION_MAX] + "…"
    card["caption"] = cap
    card["cap_to"] = end
    b["claim_upto"] = max(int(b.get("claim_upto") or 0), end)
    return cap


def _outbox_push_locked(b: dict, card: dict) -> None:
    """定稿页进 outbox（前端逐张离屏渲染成 PNG 上传后回执删除），按图卡号幂等。"""
    out = b.setdefault("outbox", [])
    if any(o.get("plot_id") == card["id"] for o in out):
        return
    b["outbox_seq"] = int(b.get("outbox_seq") or 0) + 1
    out.append({"oid": b["outbox_seq"],
                "lesson_key": b.get("lesson_key"),
                "plot_id": card["id"],
                "ts": card.get("ts"),
                "title": card.get("text") or "",
                "caption": card.get("caption") or "",
                "data": copy.deepcopy(card.get("data")),
                "source_error_id": b.get("source_error_id")})
    while len(out) > _OUTBOX_MAX:
        out.pop(0)


def _open_caption_card(b: dict):
    """当前挂着讲稿窗的那张图卡（已有 cap_from 但还没 caption），取最新一张。"""
    for i in reversed(b["items"]):
        if i["kind"] == "plot" and "caption" not in i:
            return i
    return None


def _close_open_caption_locked(b: dict):
    """把挂着的那张图定稿（闭窗 + 进 outbox）；没挂着图则无事发生。"""
    card = _open_caption_card(b)
    if card is None:
        return None
    _fill_caption_locked(b, card)
    _outbox_push_locked(b, card)
    b["rev"] += 1
    return card


def _rotate_lesson_locked(b: dict) -> str:
    """换课：先给挂着的那张图闭窗定稿（仍算上一节课的页），再换新课键。"""
    _close_open_caption_locked(b)
    b["lesson_key"] = uuid.uuid4().hex[:16]
    b["rev"] += 1
    return b["lesson_key"]


def append_speech(uid: str, role: str, text: str):
    """EXE 上报一句课堂口播（teacher=云端 tts sentence，student=stt 识别的学生话）。
    返回该行 {id, role, text, ts}；role 非法或洗完全空 → None（调用方回错误句）。
    限长与去控制字符在入口做（字幕也是不可信外部输入，与卡片同口径）。"""
    r = str(role or "").strip().lower()
    if r not in _SPEECH_ROLES:
        return None
    t = _CTRL_RE.sub(" ", str(text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return None
    if len(t) > _SPEECH_TEXT_MAX:
        t = t[:_SPEECH_TEXT_MAX] + "…"
    with _lock:
        b = _board(uid)
        b["speech_seq"] += 1
        line = {"id": b["speech_seq"], "role": r, "text": t, "ts": _now_ms()}
        b["speech"].append(line)
        while len(b["speech"]) > _SPEECH_MAX:
            b["speech"].pop(0)
        # 老师的话落地即带一次自动跟随（学生的话不动激光）；结果记进同一行
        # 日志的 follow 字段——实弹「激光没跟」时能分清是没匹配还是机制坏了
        followed = _auto_follow_locked(b, uid, t) if r == "teacher" else False
        if r == "teacher":
            # 进度镜口径：老师开口=开始讲了，「写了没讲」队列清零；
            # 连写卡不说话时才累积（见 _explain_mirror）
            b["unexplained"] = []
        b["rev"] += 1
    log.log("xz_board", "speech", "success",
           {"uid": uid, "role": r, "id": line["id"], "len": len(t),
            "follow": 1 if followed else 0})
    return dict(line)


def close_caption(uid: str) -> dict:
    """下课/收课入口用：把还挂着讲稿窗的那张图定稿，返回最新 state。"""
    with _lock:
        b = _board(uid)
        closed = _close_open_caption_locked(b)
        snap = _snapshot(b)
    log.log("xz_board", "close_caption", "success",
            {"uid": uid, "plot_id": (closed or {}).get("id") if closed else 0,
             "outbox": len(snap.get("outbox") or [])})
    return snap


def drop_outbox(uid: str, oids) -> int:
    """前端已把某页 PNG 传上来→ 回执删除，返回剩下的条数（幂等：不存在的 oid 忽略）。"""
    want = {int(o) for o in (oids or []) if isinstance(o, int) or str(o).isdigit()}
    with _lock:
        b = _board(uid)
        before = len(b.get("outbox") or [])
        b["outbox"] = [o for o in (b.get("outbox") or []) if o["oid"] not in want]
        if before != len(b["outbox"]):
            b["rev"] += 1
        return len(b["outbox"])


def rotate_lesson(uid: str) -> str:
    """换课（换题/开新课）：闭窗 + 换新 lesson_key，返回新键。"""
    with _lock:
        key = _rotate_lesson_locked(_board(uid))
    log.log("xz_board", "rotate_lesson", "success", {"uid": uid, "lesson_key": key})
    return key


def get_lesson_key(uid: str):
    """本课课件键（未画过图＝None）。归档/收课端点定位课件用。"""
    with _lock:
        b = _boards.get(uid)
        return (b or {}).get("lesson_key")


def set_lesson_key(uid: str, lesson_key: str) -> dict:
    """接课（adopt）：把本课课件键指到已备好的那节课上，之后的板书页追加进同一门课。

    先闭窗再换键：板上还挂着讲稿窗的那张图属于「上一段讲解」，它进 outbox 时已各自
    带着当时写入的 lesson_key（见 _outbox_push_locked），换键只影响之后画的新图。
    调用方（routes_board / lesson_list_preps）必须先确认该键归属本用户且不在生成中。
    """
    with _lock:
        b = _board(uid)
        _close_open_caption_locked(b)
        b["lesson_key"] = lesson_key
        b["rev"] += 1
        snap = _snapshot(b)
    log.log("xz_board", "adopt_lesson", "success", {"uid": uid, "lesson_key": lesson_key})
    return snap


def _write_focus_card(uid: str, kind: str, text: str, data=None, anchors=None,
                      anchor=None, mark=None, reveal=None) -> int:
    """写卡 + 即时点亮（可带锚/图标记/分步）：一次锁内完成，返回卡号。
    「写卡即点亮」= 跟讲语义：讲到哪写到哪，焦点永远在新卡上。"""
    with _lock:
        b = _board(uid)
        item_id = _append_locked(b, kind, text, data, anchors)
        _set_focus_locked(b, item_id, anchor=anchor, mark=mark, reveal=reveal)
        return item_id


def replace_card(uid: str, item_id: int, kind: str, text: str, data=None,
                 anchors=None) -> str:
    """改写单卡（被打断/换说法时用）。返回码：
    ok / missing / plot（图卡拒改，防 data 被擦——二期既有缺陷顺带修复）
    / kindflip（主干↔叶子互转拒收，防挂树引用链被打断）。
    被改写卡若正被焦点指着：清焦点（锚点数可能已变，宁缺不假）。"""
    with _lock:
        b = _board(uid)
        card = next((i for i in b["items"] if i["id"] == item_id), None)
        if card is None:
            return "missing"
        if card["kind"] == "plot":
            return "plot"
        if (card["kind"] == "topic") != (kind == "topic"):
            return "kindflip"
        card["kind"] = kind
        card["text"] = text
        if anchors:
            card["anchors"] = list(anchors)
        else:
            card.pop("anchors", None)
        if data is not None:
            card["data"] = data
        else:
            card.pop("data", None)
        f = b.get("focus")
        if f and f["item_id"] == item_id:
            b["focus"] = None
            b["focus_seq"] += 1
        card["highlighted"] = False
        # 改写即在重讲这张卡：从「写了没讲」队列剔除，防镜检误伤重讲动作
        b["unexplained"] = [x for x in (b.get("unexplained") or []) if x != item_id]
        b["rev"] += 1
        return "ok"


def remove_card(uid: str, item_id: int) -> tuple[str, int]:
    """擦卡。主干 topic 级联擦其全部子卡。返回 ("ok", 删除张数) 或 ("missing", 0)。"""
    with _lock:
        b = _board(uid)
        card = next((i for i in b["items"] if i["id"] == item_id), None)
        if card is None:
            return "missing", 0
        ids = {item_id}
        if card["kind"] == "topic":
            ids |= {i["id"] for i in b["items"] if i.get("parent_id") == item_id}
        b["items"] = [i for i in b["items"] if i["id"] not in ids]
        # 被擦卡同步出进度镜队列，防镜检报幽灵卡号
        b["unexplained"] = [x for x in (b.get("unexplained") or []) if x not in ids]
        f = b.get("focus")
        if f and f["item_id"] in ids:
            b["focus"] = None
            b["focus_seq"] += 1
        b["rev"] += 1
        return "ok", len(ids)


def focus_card(uid: str, item_id: int, point=None, reveal=None) -> tuple[str, dict]:
    """点亮某卡并（可选）指认：文本卡 point=第 N 个〔〕锚、图卡 point=第 N 个 marks、
    图卡 reveal=只显示到第 N 步。指认参数无效时**仍整卡点亮**并回 note 指导
    （顺风车不拦路：老师的手势比参数纠错重要）。返回 ("ok"|"missing", info)。"""
    with _lock:
        b = _board(uid)
        card = next((i for i in b["items"] if i["id"] == item_id), None)
        if card is None:
            return "missing", {}
        kind = card["kind"]
        anchor = mark = rv = None
        info = {"kind": kind, "note": ""}
        if point is not None:
            if kind == "plot":
                marks = (card.get("data") or {}).get("marks") or []
                info["nmarks"] = len(marks)
                info["names"] = [m.get("name") or "" for m in marks][:8]
                if 1 <= point <= len(marks):
                    mark = point
                    info["mark_name"] = marks[point - 1].get("name") or ""
                else:
                    info["note"] = "nomarks"
            elif kind in _POINT_TEXT_KINDS:
                ans = card.get("anchors") or []
                info["nanch"] = len(ans)
                info["list"] = list(ans)
                if 1 <= point <= len(ans):
                    anchor = point
                    info["anchor_text"] = ans[point - 1]
                else:
                    info["note"] = "noanchor"
            else:
                info["note"] = "nokind"
        if reveal is not None:
            total = ((card.get("data") or {}).get("step_total") or 0
                     if kind == "plot" else 0)
            info["total"] = total
            if 1 <= reveal <= total:
                rv = reveal
            else:
                info["note"] = info["note"] or "noreveal"
        _set_focus_locked(b, item_id, anchor=anchor, mark=mark, reveal=rv)
        info["anchor"], info["mark"], info["reveal"] = anchor, mark, rv
        return "ok", info


def status_line(uid: str) -> str:
    """状态行：两级摘要——主干#号+其子卡号（云端按编号在脑图坐标系里引用卡），
    限长 _STATUS_MAX 防长板撑爆返回。无主干的散卡单列一组（扁平退化兼容）。
    评审 Minor-9：锁内只取轻量元组快照，拼字符串移到锁外（锁纪律口径一致）。"""
    with _lock:
        b = _board(uid)
        snap = [(i["id"], i["kind"], i["text"], i.get("parent_id")) for i in b["items"]]
    n = len(snap)
    if not n:
        return "当前黑板是空的"
    topics, loose, kids = [], [], {}
    tids = {sid for sid, k, _t, _p in snap if k == "topic"}
    for sid, k, txt, pid in snap:
        if k == "topic":
            topics.append((sid, txt))
        elif pid in tids:
            kids.setdefault(pid, []).append((sid, txt))
        else:
            loose.append((sid, txt))
    # 状态行带卡正文摘要（2026-11-09 讲课连续性）：学生求重讲时老师要能
    # 「照板重讲」——只有卡号没正文，老师对着板也说不出讲了什么
    segs = []
    for sid, txt in topics:
        sub = "，".join(f"#{x}〔{(t or '')[:10]}〕" for x, t in kids.get(sid, []))
        segs.append(f"#{sid}〔{txt[:8]}〕→{sub or '（无子卡）'}")
    if loose:
        segs.append("散卡 " + "，".join(f"#{x}〔{(t or '')[:10]}〕" for x, t in loose))
    return ("当前黑板共 " + str(n) + " 张：" + "；".join(segs))[:_STATUS_MAX]


# ---------------------------------------------------------------- 动画舞台（C 期）
# 硬约束：小智实时对话等不了 1~3 分钟画布生成 → 异步补位：
# board_render_anim 立即返回，后台线程走微课五期同一画布管线；生成期间老师
# 用 A/B 讲义卡继续讲；就绪后的下一次工具返回里宣布「准备好了 我们来看这个」（一次性消费）。

def _finish_anim(uid: str, gen: str, fields: dict) -> bool:
    """后台线程回写舞台结果：gen 令牌失配（期间被覆写重发/换课重开）则丢弃结果。
    擦板不再丢令牌（融合轮 2026-11-09：擦板不清舞台）。"""
    with _lock:
        b = _board(uid)
        a = b.get("anim")
        if not a or a.get("gen") != gen:
            return False
        a.update(fields)
        b["rev"] += 1
        return True


def _anim_notice(uid: str) -> str:
    """一次性衔接触发器：generating 静默；ready/error 首次读取时拼进返回文本。"""
    with _lock:
        a = _board(uid).get("anim")
        if not a or a["state"] == "generating" or a.get("announced"):
            return ""
        a["announced"] = True
        if a["state"] == "ready":
            return ("\n[舞台就绪]《" + a["title"] + "》画面已生成好（共 "
                    + str(len(a["steps"])) + " 步）。先对学生说：准备好了，我们来看这个！"
                    "再用 board_anim_step 从第 0 步起逐步推进，每步照返回里的口播念。")
        return ("\n[舞台失败] 动画没生成出来（" + (a.get("error") or "未知原因")
                + "），不影响讲课；需要可重试 board_render_anim。")


def _anim_worker(uid: str, gen: str, stype: str, title: str, material: str,
                 subject: str, point_name: str, core_desc: str,
                 style: str = "micro", cache_ref=None) -> None:
    """后台生成：复用微课五期唯一实现（prompt 构建/画布校验/计费链路），不落微课库。
    style="principle"（融合轮 2026-11-09）：提示词换 html-explainer 方法论版
    （board_explainer.build_stage_prompt），输出契约/校验与微课画布页同源，
    老师侧 board_anim_step 全链不变。
    cache_ref=(kind, ref)（成本优化轮 2026-11-10）：原理图舞台成功落位后同步归档
    产物到 principle_cache（指派同源再次到达 → 零成本秒复用）。"""
    try:
        from services import micro_course as MC
        from llm_provider_factory import call_llm_for_user
        if style == "principle":
            from services import board_explainer as BE
            prompt = BE.build_stage_prompt(label=title, material=material,
                                           subject=subject)
            raw = call_llm_for_user(uid, prompt, scene="黑板原理图舞台", timeout=300)
            content = MC.validate_scene_content("explain", raw)
        else:
            prompt = MC.build_scene_prompt(
                subject=subject, course_title=title,
                section={"title": title, "scene_type": stype,
                         "intent": "用分步动画把本题/本主题讲透，对准学生易错处"},
                point_name=point_name, core_desc=core_desc,
                outline_brief=f"1. [{stype}] {title}",
                notes_material="", errors_material=material)
            raw = call_llm_for_user(uid, prompt, scene="黑板动画舞台", timeout=300)
            content = MC.validate_scene_content(stype, raw)
        note = MC.external_ref_note(content.get("canvas_html", ""))
    except Exception as e:  # noqa: BLE001 后台线程绝不外抛：失败回写状态由老师转述
        log.log("xz_board", "anim_gen", "error", {"uid": uid, "err": str(e)[:200]})
        _finish_anim(uid, gen, {"state": "error", "error": str(e)[:120],
                               "announced": False})
        return
    # 评审融合轮 M-3：先落盘再记账——被令牌丢弃的一轮不得再写 success，
    # 否则事后排障会误判「这份结果生效了」
    if _finish_anim(uid, gen, {"state": "ready",
                               "title": content.get("title") or title,
                               "canvas_html": content["canvas_html"],
                               "steps": content["steps"], "note": note or "",
                               "announced": False}):
        log.log("xz_board", "anim_gen", "success",
                {"uid": uid, "style": style, "steps": len(content["steps"]), "note": note or ""})
        if style == "principle" and cache_ref:   # 完成即归档（失败不影响已落位舞台）
            try:
                from services import principle_cache as PC
                PC.put(uid, str(cache_ref[0]), cache_ref[1],
                       {"title": content.get("title") or title,
                        "canvas_html": content["canvas_html"],
                        "steps": content["steps"], "note": note or ""}, mode="off")
            except Exception as e:  # noqa: BLE001
                log.log("xz_board", "anim_cache_put", "fail",
                        {"uid": uid, "err": str(e)[:120]})
    else:
        log.log("xz_board", "anim_gen", "stale", {"uid": uid, "style": style})


def auto_open_stage(uid: str, kind: str, target_id, label: str, raw_text: str = "") -> dict:
    """指派时刻自动开工本课原理图舞台（融合轮 2026-11-09 用户裁定：默认开）。

    与老师手动 board_render_anim 共用 b["anim"] 与同一条后台链，只是提示词
    换原理图方法论版；去重口径：同源且 generating/ready → 复用不重开（防
    重复点指派双扣分），error 或指派改口（src 不符）→ 覆写重开（旧结果由
    gen 令牌自然丢弃）；素材取不到/积分不足 → 静默不开工，讲课照常。
    入口：routes_board 指派成功处（唯一指派落点）；不在 set_assign 内调，
    免影响测试/应急路径的指派语义。"""
    uid = str(uid)
    src = {"kind": kind, "id": target_id}
    # 快速短路：同源已 ready 零成本复用（不必再取素材）；generating 的权威去重
    # 在落位锁内复检（评审融合轮 I-1：防同源并发指派双扣积分）
    with _lock:
        a = _board(uid).get("anim")
        if (a and a.get("style") == "principle" and a.get("src") == src
                and a["state"] == "ready"):
            return {"started": False, "reused": "ready"}
    # 库回源（成本优化轮 2026-11-10，规则 2）：内存没有但库里存过同 src 产物
    # → 直接置 ready 零外呼零扣分（重启后再指派同一知识点不再重画）
    try:
        from services import principle_cache as PC
        hit = PC.latest(uid, str(kind), target_id)
    except Exception as e:  # noqa: BLE001 库链路异常不拦生成老路
        hit = None
        log.log("xz_board", "stage_cache", "fail", {"uid": uid, "err": str(e)[:120]})
    if hit:
        c = hit["content"]
        with _lock:
            b = _board(uid)
            a = b.get("anim")
            if (a and a.get("style") == "principle" and a.get("src") == src
                    and a["state"] in ("ready", "generating")):
                return {"started": False, "reused": a["state"]}
            b["anim"] = {"gen": uuid.uuid4().hex, "state": "ready",
                         "title": c.get("title") or "",
                         "canvas_html": c.get("canvas_html") or "",
                         "steps": c.get("steps") or [], "current": -1,
                         "error": "", "note": c.get("note") or "",
                         "announced": False, "style": "principle", "src": dict(src)}
            b["rev"] += 1
        log.log("xz_board", "stage_cache", "hit",
                {"uid": uid, "kind": kind, "id": target_id, "seq": hit["seq"]})
        return {"started": False, "reused": "cache"}
    subject, material = "通用", ""
    try:
        if kind == "kp":
            from routes_micro_course import kp_teach_pack
            pack = kp_teach_pack(uid, target_id)
            if pack:
                subject = pack.get("subject") or "通用"
                errs = "；".join(f"{e[1]}" for e in (pack.get("errors") or [])[:3])
                material = (f"知识点「{pack['name']}」：{pack.get('desc') or ''}"
                            + (f"。学生易错处：{errs}" if errs else ""))
        elif kind == "error":
            pack = _lesson_pack_text(uid, str(target_id))
            if pack:
                material = pack["text"]
                subject = pack.get("subject") or "通用"
        elif kind == "text":
            # 课文框选轮 2026-11-12：选中原文即素材，零库查；同源去重靠 src id=文本哈希
            material = str(raw_text or "").strip()
            if material and target_id and int(target_id) > 0:
                src = {"kind": kind, "id": int(target_id)}
    except Exception as e:  # noqa: BLE001 自动开工失败不影响指派主流程
        log.log("xz_board", "stage_auto", "error",
                {"uid": uid, "err": str(e)[:120]})
        return {"started": False, "reason": "material_error"}
    if not (material or "").strip():
        log.log("xz_board", "stage_auto", "skip",
                {"uid": uid, "kind": kind, "id": target_id, "reason": "no_material"})
        return {"started": False, "reason": "no_material"}
    import credits_service as cr
    try:
        pre = cr.precheck(uid)
        if not pre["allowed"] and not cr.get_user_llm_config(uid):
            log.log("xz_board", "stage_auto", "skip",
                    {"uid": uid, "kind": kind, "id": target_id, "reason": "credits"})
            return {"started": False, "reason": "credits"}
    except Exception:  # noqa: BLE001 预检异常不拦路（render_anim 同口径）
        pass
    title = (str(label or "").strip()[:20] or "本课") + "·原理图"
    with _lock:
        b = _board(uid)
        # 权威去重（I-1 + 成本轮评审）：锁内复检同源在飞/已就绪——两路指派并发
        # 到达时，后落位者绝不覆写绝不双起线程双扣费；ready 也回（前一轮可能
        # 刚经库回源落位，此时再起一轮 = 违反「永远复用」硬约束）
        a = b.get("anim")
        if (a and a.get("style") == "principle" and a.get("src") == src
                and a["state"] in ("ready", "generating")):
            return {"started": False, "reused": a["state"]}
        gen = uuid.uuid4().hex
        b["anim"] = {"gen": gen, "state": "generating", "title": title,
                     "steps": [], "current": -1, "error": "", "note": "",
                     "announced": True, "style": "principle", "src": dict(src)}
        b["rev"] += 1
    threading.Thread(target=_anim_worker,
                     args=(uid, gen, "explain", title, material, subject, "", ""),
                     kwargs={"style": "principle", "cache_ref": (kind, target_id)},
                     daemon=True, name="xz-stage-gen").start()
    log.log("xz_board", "stage_auto", "started",
            {"uid": uid, "kind": kind, "id": target_id, "gen": gen})
    return {"started": True}


# ---------------------------------------------------------------- 卡片写入校验
# 超限拒收（不回截断版内容上板）：让大脑学会拆短句，这是讲义版式的生命线。

def _norm_kind(kind) -> str:
    k = str(kind or "note").strip().lower()
    k = _KIND_ALIAS.get(k, k)
    return k if k in _CARD_LIMITS else "note"


def _strip_dollar(t: str) -> str:
    """LaTeX 卡剥掉 $/$$ 定界（渲染端拿纯公式，防大脑习惯性包美元符）。"""
    t = t.strip()
    for pat in ("$$", "$"):
        if t.startswith(pat) and t.endswith(pat) and len(t) > 2 * len(pat):
            t = t[len(pat):-len(pat)].strip()
            break
    return t


def _clip(t: str, n: int) -> tuple[str, bool]:
    t = (t or "").strip()
    return (t[:n] + "…" if len(t) > n else t), len(t) > n


def _reject_too_long(kind: str, text: str):
    """返回 (ok, 指导文案)。超限拒收：给出限长与拆卡指导（状态行由调用方拼）。"""
    lim = _CARD_LIMITS.get(kind, 60)
    if len(text) > lim:
        return False, (f"这张{kind}卡超长（{len(text)}字 > 限{lim}字）。黑板是讲义版式，"
                       f"不许长句：压缩成一句或拆成多张卡分别写。")
    return True, ""


def _parse_nn(v, what: str):
    """point/reveal 入参：正整数或 (None, 错误句)。"""
    if v is None:
        return None, ""
    try:
        n = int(v)
    except (TypeError, ValueError, OverflowError):   # 评审 Minor-8：inf/1e999 走拒收指导
        return None, f"{what}要写成从 1 起的整数。"
    if n < 1:
        return None, f"{what}要从 1 起数。"
    return n, ""


# ---- 画图建议（五期 C 案）：题干/素材命中关键词时在工具返回里追加一行建议。
# 只是建议不是命令——调用权在小智云大脑，我们只抬概率；误伤无害（大脑可忽略）。
# 表序即优先级（首个命中取胜）：曲线面积类信号先于普通几何，避免「三角形面积」被抢成 function。
_PLOT_HINTS = (
    ("function", "函数曲线图", ("围成", "曲边", "函数", "图像", "图象", "曲线", "单调",
                              "极值", "导数", "切线", "反比例", "sin", "cos", "tan")),
    ("numberline", "数轴图", ("数轴", "区间表示")),
    ("unitcircle", "单位圆图", ("单位圆", "三角函数线")),
    ("polar", "极坐标图", ("极坐标", "参数方程")),
    ("geometry", "几何图", ("几何", "三角形", "四边形", "圆", "面积", "体积", "垂直",
                           "平行", "全等", "相似", "角度")),
    ("stats", "统计图", ("统计", "平均", "中位数", "众数", "方差", "概率", "频数", "数据")),
    ("timeline", "时间轴", ("时间轴", "年代", "发展历程")),
    ("diagram", "流程/框图", ("流程", "层次", "分类", "结构图", "思维导图")),
)


def _suggest_plot(*texts: str) -> str:
    """按关键词表匹配文本片段，返回一行建议（无命中返回空串）。"""
    blob = " ".join(t or "" for t in texts).lower()
    for ptype, label, kws in _PLOT_HINTS:
        if any(k in blob for k in kws):
            extra = "（把题干里的式子写进 expr）" if ptype == "function" else ""
            return (f"\n这题适合配图讲：建议 board_draw 画{label}（spec.plot_type={ptype}）"
                    + extra + "，图会显示在下方主板书区；图上的名字写讲解的真实术语"
                    "（如「回归」「分类」），「节点1」「步一」这类占位名会被拒收。")
    return ""


# ---------------------------------------------------------------- MCP 工具定义
# 命名空间纪律：board_/lesson 前缀，绝不与小智官方工具撞名（撞名=整包丢弃）。
# description ≤400 字符纪律（上下文拥挤取证）；新 DSL 细节走拒收渐进披露。

TOOLS = [
    {
        "name": "get_lesson_material",
        "description":
            "取学习材料。不填 error_id＝列出该用户最近的错题清单（含错题id，供选择讲解哪道）；"
            "填 error_id＝返回该题完整素材（题干/选项/你的作答/正确答案/解析）。"
            "内容开头若有「📌网页指定讲解」指导语，是学生刚在界面上点名要讲的内容，必须优先照办。"
            "素材是备课资料：消化后用自己的话讲解，不要整段照念；适合画图的内容"
            "（函数/几何/统计）写上黑板后第一步就 board_draw 配图讲。",
        "inputSchema": {"type": "object", "properties": {
            "error_id": {"type": "string", "description": "错题id；省略＝只列清单"}},
        },
    },
    {
        "name": "board_show_problem",
        "description":
            "把指定 error_id 的错题写上黑板：自动建 topic 主干卡（脑图根，建好即点亮）"
            "+题干卡+选项卡（如有），题干板书在下方主板书区。返回文本附本题素材供你备课。"
            "之后 board_write 写的卡自动挂在这道题主干下面。写题后直接讲关键点，不要把"
            "题干再念一遍；返回里有建议配图时，第一步就 board_draw 画图。",
        "inputSchema": {"type": "object", "properties": {
            "error_id": {"type": "string", "description": "要上黑板的错题id"}},
            "required": ["error_id"],
        },
    },
    {
        "name": "board_write",
        "description":
            "往黑板写一张讲义卡，写完自动点亮（讲到哪写到哪）。kind：step=一步推演（限40字），"
            "formula=公式（LaTeX，限80字），note=短提醒（限40字），options=自编选项组（限160字，"
            "；分隔），topic=脑图主干（限20字，新起一道题/一个大话题时用，之后的卡自动挂其下）。"
            "想指着讲：正文里用〔〕包住关键片段，如「〔斜率等于2〕」，配 point=N 写卡即指第N个〔〕。"
            "每张卡只写一句话，长内容拆多张卡，超长拒收。"
            "能画成图的内容（函数/几何/统计/流程）用 board_draw 画，不要用文字卡描述图形。",
        "inputSchema": {"type": "object", "properties": {
            "content": {"type": "string", "description": "卡片文字（短句或 LaTeX），可埋〔〕锚点"},
            "kind": {"type": "string", "enum": ["step", "formula", "note", "options", "topic"],
                     "description": "卡类型，默认 step"},
            "point": {"type": "number", "description": "写完红点指到第几个〔〕锚（从1起，可省）"}},
            "required": ["content"],
        },
    },
    {
        "name": "board_replace",
        "description":
            "改写黑板上某张卡（学生质疑或换说法时用，别整块黑板重做）。item_id 是状态行里"
            "的卡号，content/kind 同 board_write 限长规则（〔〕锚点可重新埋）。"
            "图卡 plot 不能改写——要改图请重新 board_draw；主干 topic 与普通卡不能互转（拒收）。"
            "只动这一张卡，其余保持不变。",
        "inputSchema": {"type": "object", "properties": {
            "item_id": {"type": "number", "description": "要改写的卡号"},
            "content": {"type": "string", "description": "新文字"},
            "kind": {"type": "string", "enum": ["step", "formula", "note", "options", "topic"],
                     "description": "新卡类型，省略＝保持原类型"}},
            "required": ["item_id", "content"],
        },
    },
    {
        "name": "board_remove",
        "description":
            "擦掉黑板上某张卡（讲错的步骤、不再需要的推演）。item_id 是卡号。"
            "擦主干 topic 会把它挂着的子卡一起擦掉（返回删除张数）。"
            "换题时如果只擦部分旧内容用它，全擦用 board_clear。",
        "inputSchema": {"type": "object", "properties": {
            "item_id": {"type": "number", "description": "要擦掉的卡号"}},
            "required": ["item_id"],
        },
    },
    {
        "name": "board_highlight",
        "description":
            "点亮黑板上某张卡（聚焦灯：正在讲哪张就点亮哪张），其余卡自动熄灭，"
            "学生端自动滚到该卡。item_id 用状态行/写卡返回里的卡号（如 #3 填 3）。"
            "回看旧卡想指着讲：point=N 指该卡第 N 个〔〕锚点（文本卡）或第 N 个图上标记（图卡）；"
            "图卡 reveal=N 只显示到第 N 步（分步作图）。formula/options 只支持整卡点亮。",
        "inputSchema": {"type": "object", "properties": {
            "item_id": {"type": "number", "description": "黑板卡号"},
            "point": {"type": "number", "description": "指第几个锚点/图上标记（从1起，可省）"},
            "reveal": {"type": "number", "description": "图卡分步：显示到第 N 步（可省）"}},
            "required": ["item_id"],
        },
    },
    {
        "name": "board_draw",
        "description":
            "必须画图：能画成图的别用文字卡。spec.plot_type：function=函数曲线（curves≤3，"
            "expr 只用 x 与初等函数，可带 shades/tangents）；numberline=数轴；"
            "geometry=几何（中点写 mid:['B','C']，关系写 relations 供核验）；polar=极坐标；"
            "unitcircle=单位圆；timeline=时间轴；stats=统计（shape=bar|pie|line|"
            "scatter|box|histogram，scatter 可带 trend）；diagram=框图（flow|barmodel|tree|sankey）；"
            "mermaid=思路图（讲思路/拆原理，code 写 mermaid DSL）。"
            "元素带 step 供 reveal=N 分步；成功回黑板实况，照此说；"
            "marks 供 point=N 指认；非法拒收重试",
        "inputSchema": {"type": "object", "properties": {
            "title": {"type": "string", "description": "图名（短，显示在图上方）"},
            "spec": {"type": "object",
                     "description": "图形描述：{plot_type, ...} 见工具说明"},
            "point": {"type": "number", "description": "画完激光指到第几个标记（从1起，可省）"},
            "reveal": {"type": "number", "description": "分步作图：只显示到第N步（可省）"}},
            "required": ["spec"],
        },
    },
    {
        "name": "board_render_anim",
        "description":
            "手动开工生成「分步动画舞台」（学生端动画课件）：网页指派开课时已自动"
            "生成原理图舞台，本工具只用于没指派的自由课或舞台失败后重试；黑板上有错题"
            "自动用其素材，否则用 topic 文字。立即返回不阻塞对话：生成要几分钟，期间"
            "照常 board_write/board_draw 讲课；完成后的工具返回会提示你舞台就绪，那时"
            "对学生说「准备好了，我们来看这个」，再用 board_anim_step 逐步讲。生成中"
            "重复提交会被拒；舞台就绪后擦板不收舞台。",
        "inputSchema": {"type": "object", "properties": {
            "topic": {"type": "string", "description": "黑板无题时的主题/题目文字（可省）"}},
        },
    },
    {
        "name": "board_anim_step",
        "description":
            "把动画舞台推进到第 i 步（从 0 起，0=总览/题干）。返回该步字幕与口播稿："
            "照那句口播讲（别自己编内容），前端舞台同步切到该步画面。仅舞台就绪后可用。",
        "inputSchema": {"type": "object", "properties": {
            "step": {"type": "number", "description": "步序号，从 0 开始"}},
            "required": ["step"],
        },
    },
    {
        "name": "board_clear",
        "description": "擦黑板：清空全部卡片。换题/重讲前整理版面，擦后可用 board_write 重新板书。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "lesson_prepare",
        "description":
            "帮学生备一节新课（后台生成整份课件，不是当场讲课）。学生说「帮我备一节关于X的课」"
            "「再备一课」时用它。topic 写清要备什么（命中他已有知识点就自动拿该点素材出大纲）。"
            "立即返回「已开工」不阻塞对话：生成要几分钟，期间照常 board_write/board_draw 讲课；"
            "备好后学生端黑板页会出现提示条。同一主题重复调不会重复开工（回已在备课中）。",
        "inputSchema": {"type": "object", "properties": {
            "topic": {"type": "string", "description": "要备的主题或知识点名（必填，≤80字）"},
            "subject": {"type": "string", "description": "学科（可省；省了就在全学科里找同名知识点）"}},
            "required": ["topic"]},
    },
    {
        "name": "lesson_list_preps",
        "description":
            "列出这个学生已备好的课（标题/页数/课号）。问「备好了吗/上哪节」时用它。"
            "学生点名要上某一节时，带上 lesson_key（或该课标题里的词）再调一次就直接接上这节课："
            "之后画的板书页就存进这份课件。不带参数＝只列清单不接单。",
        "inputSchema": {"type": "object", "properties": {
            "lesson_key": {"type": "string", "description": "要上的课件课号（清单里给的 16 位键）"},
            "title": {"type": "string", "description": "记不清课号时的标题关键词（包含即可）"}}},
    },
]

_TOOL_NAMES = {t["name"] for t in TOOLS}


def is_known_tool(name: str) -> bool:
    """工具名是否属于黑板端。真云实测（2026-11-04）会把 play_music 等官方
    工具例行下发到本接入点，桥据此区分“不归我管”与“我方工具出错”。"""
    return name in _TOOL_NAMES


# ---------------------------------------------------------------- 工具执行

def _conn_factory():
    """桥线程的 DB 连接来源：复用全站唯一 kms.db_manager（公共函数注册制）。"""
    from routes_knowledge import get_kms
    return get_kms().db_manager.get_connection


def resolve_uid_by_username(username: str):
    """把 XZ_MCP_USER 解析成 user_id（users.user_id 为 TEXT 主键）。
    查询口径与 auth._find_user 同源：lower(username) 匹配（注册时用户名已小写归一）。"""
    conn = _conn_factory()()
    try:
        row = conn.execute("SELECT user_id FROM users WHERE lower(username) = ?",
                           ((username or "").strip().lower(),)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def execute_tool(name: str, args: dict, uid: str) -> str:
    """MCP tools/call 统一入口：核心执行 + 舞台衔接触发器（就绪/失败一次性尾注）
    + 讲课进度镜（连写未讲卡拦嘴，见 _explain_mirror）。"""
    return _execute_core(name, args, uid) + _anim_notice(uid) + _explain_mirror(uid)


def _explain_mirror(uid: str) -> str:
    """讲课进度镜（2026-11-09「讲完卡不讲解」事故）：老师连写 ≥2 张卡却一句
    没讲，每次工具返回都拦嘴。口径：写卡进 unexplained、老师一句口播即清（见
    append_speech）——讲到哪写到到哪时永远不触发，只拦「堆卡不说」。"""
    with _lock:
        ids = list(_board(uid).get("unexplained") or [])
    if len(ids) < 2:
        return ""
    return ("\n你已连续写了 " + str(len(ids)) + " 张卡（"
            + "、".join(f"#{x}" for x in ids[-6:]) + "）却一句还没讲。"
            "先停笔：把最近这张卡讲透——举个例子、问一句学生懂没懂，"
            "确认懂了再写下一张；板书不等于讲解，没讲的卡学生看不见也不会。")


def _execute_core(name: str, args: dict, uid: str) -> str:
    """实际工具执行。返回文本三层：确认句+状态行+导演指令。
    只走短事务（用完即还），异常向上抛由桥层兜底成口语错误句。
    锁纪律铁律：with _lock 内只改状态，返回文案（含 status_line）一律锁外拼。"""
    args = args or {}
    if name == "get_lesson_material":
        error_id = str(args.get("error_id") or "").strip()
        # v0.2.8「AI老师讲」：网页指派条件消费（评审 Minor-2）——kp 素材瞬抖/已删
        # 时指导语落空，不清指派（留给下次取料重试，TTL 过期兑底）；其余注入成功即清
        a = get_assign(uid)
        pre = _assign_directive(uid, a) if a else ""
        if a:   # 消费留痕（中位线定理事故排查面）：注入成功/落空都可从日志定性，
                # 不再靠老师行为反推指派去向（kp 素材落空返空串历史上全静默）
            log.log("xz_board", "assign_take", "injected" if pre else "miss",
                    {"uid": uid, "kind": a["kind"], "id": a["id"]})
        if a and (pre or a["kind"] != "kp"):
            _drop_assign(uid, a)
            # 指派消费后素材课内常驻（讲课连续性）：kp 型注入成功即记 lesson_kp，
            # 学生说「继续/没听懂」时重调本工具可重放素材；错题新指派覆盖知识点语境
            with _lock:
                b = _board(uid)
                if a["kind"] == "kp" and pre:
                    b["lesson_kp"] = {"id": a["id"], "label": a["label"]}
                elif a["kind"] == "error":
                    b["lesson_kp"] = None
        if not error_id:
            # 课内指定知识点重放（事故主因：指派一次性消费后素材再也拿不回，
            # 老师被学生追问时无料可讲，只能空口收尾道别）；本次刚消费 kp 指派
            # 的不算——开讲指导语（pre）已带全素材，再拼「续讲」就是双份指令
            #（十一轮评审 Warning：首 call 开讲+续讲同屏、口吻相反）
            if not (a and a["kind"] == "kp" and pre):
                with _lock:
                    lk = dict(_board(uid).get("lesson_kp") or {})
                if lk:
                    replay = _kp_replay_text(uid, lk)
                    if replay:
                        return pre + replay
            conn = _conn_factory()()
            try:
                rows = conn.execute(
                    "SELECT eq.id, SUBSTRING(pr.question_content, 1, 40), eq.subject_name "
                    "FROM error_questions eq JOIN practice_records pr "
                    "ON eq.practice_record_id = pr.id AND pr.user_id = eq.user_id "
                    "WHERE eq.user_id = ? ORDER BY eq.id DESC LIMIT " + str(_LIST_TOP_N),
                    (uid,)).fetchall()
            finally:
                conn.close()
            if not rows:
                return pre + ("你还没有错题记录。可以先带学生出一道题：口述题目后用 board_write 写上黑板。"
                              + status_line(uid))
            menu = "\n".join(f"- 错题id {r[0]}（{r[2] or '未分类'}）：{(r[1] or '').strip()}"
                             for r in rows)
            return pre + (f"最近错题清单：\n{menu}\n"
                          "选一道题，用 board_show_problem 把它写上黑板后开始讲解。"
                          + status_line(uid))
        pack = _lesson_pack_text(uid, error_id)
        if pack is None:
            return pre + (f"没找到 id 为 {error_id} 的错题，可能不属于该用户。"
                          "先调 get_lesson_material 不带参数拿清单，再按清单里的 id 操作。"
                          + status_line(uid))
        return pre + (f"第 {error_id} 题素材：\n{pack['text']}\n"
                      "用 board_show_problem 把这题写上黑板，然后一步一张 step 卡讲清错因，"
                      "关键结论用 formula 卡。"
                      + ("本题带原图，写上黑板时原图会自动上屏，对照图讲。"
                         if pack.get("images") else "")
                      + _suggest_plot(pack.get("stem") or "", pack["text"])
                      + status_line(uid))

    if name == "board_show_problem":
        error_id = str(args.get("error_id") or "").strip()
        pack = _lesson_pack_text(uid, error_id)
        if pack is None:
            return (f"没找到 id 为 {error_id} 的错题。先用 get_lesson_material 不带参数取清单。"
                    + status_line(uid))
        # 讲义化拆卡：topic 主干（脑图根）+ 题干卡 + 选项卡（有则加），答案/解析绝不上板
        # C 方案（2026-11-08 用户裁定）：题干里的图片死引用换成提示，原图另上独立图卡
        images = pack.get("images") or []
        stem_src = _strip_img_refs(pack.get("stem") or "", images)
        stem, _ = _clip(stem_src, _CARD_LIMITS["problem"])
        opts = [str(o)[:60] for o in (pack.get("options") or [])][:8]
        topic_name = stem_src.strip()[:_CARD_LIMITS["topic"]] \
            or f"第 {error_id} 题"
        with _lock:
            b = _board(uid)
            _rotate_lesson_locked(b)   # 换题=开新课：上一题的图先闭窗归档，新课键从此起算
            tid = _append_locked(b, "topic", topic_name)
            ids = [_append_locked(b, "problem", stem)]
            if opts:
                opt_text = "；".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(opts))
                ids.append(_append_locked(b, "options", opt_text, data=opts))
            # 原图卡：plot 卡型的 image 变体（图轨/缩略条/口播窗/归档全线天然复用）；
            # rel 只能由服务端校验后生成，老师无法经 board_draw/board_write 伪造路径
            img_ids = []
            for i, rel in enumerate(images, 1):
                tag = "题目原图" if len(images) == 1 else f"题目原图{i}"
                img_ids.append(_append_locked(b, "plot", tag,
                                              data={"plot_type": "image", "rel": rel}))
            b["source_error_id"] = error_id
            # 上题一次性铺素材卡≠连写未讲：进度镜归零，从首张讲解卡起算
            b["unexplained"] = []
            _set_focus_locked(b, tid)   # 换题焦点落在新主干（清理时机之一：换题）
        log.log("xz_board", "show_problem", "success",
                {"uid": uid, "error_id": error_id, "cards": [tid] + ids + img_ids,
                 "images": len(img_ids)})
        return (f"第 {error_id} 题已写上黑板：主干卡 #{tid}（脑图根，已点亮）、题干卡 #{ids[0]}"
                + (f"、选项卡 #{ids[1]}" if len(ids) > 1 else "")
                + (f"、原图卡 #{'、#'.join(str(i) for i in img_ids)}" if img_ids else "")
                + "）。备课素材：\n"
                + pack["text"] + "\n"
                + ("本题原图已上黑板图区：对照原图讲解，不要凭文字复述图里的内容；"
                   "要讲辅助线可再 board_draw 画示意图，示意画不准没关系——学生手边有原图可对照。"
                   if img_ids else "")
                + "直接讲关键点与错因，不要照念题干；每讲一步写一张 step 卡（自动挂在这道题"
                "主干下），讲到关键片段用〔〕包住它。"
                + _suggest_plot(stem, pack.get("analysis") or "", pack["text"])
                + status_line(uid))

    if name == "board_write":
        kind = _norm_kind(args.get("kind") or "step")
        if kind == "plot":   # 评审 Major-1：plot 只能由 board_draw 产生，防造出无 data 的死卡
            return ("plot 卡只能由 board_draw 画出来（board_write 不接 kind=plot）。" 
                    + status_line(uid))
        content = str(args.get("content") or "").strip()
        if not content:
            return "content 不能为空，黑板写不上东西。" + status_line(uid)
        point, err = _parse_nn(args.get("point"), "point（指第几个〔〕锚）")
        if err:
            return err + status_line(uid)
        data = None
        if kind == "formula":
            content = _strip_dollar(content)
        anchors: list[str] = []
        if kind in _POINT_TEXT_KINDS:
            content, anchors = _extract_anchors(content)
        if kind == "options":
            data = [s.strip() for s in content.replace("；", ";").split(";") if s.strip()][:8]
            content = "；".join(data)
        ok, why = _reject_too_long(kind, content)
        if not ok:
            return why + status_line(uid)
        if not content:
            return "剥掉〔〕锚点后没剩正文，至少写一句要讲的话。" + status_line(uid)
        anchor = None
        note = ""
        if point is not None:
            if kind not in _POINT_TEXT_KINDS:
                note = ("formula/options 卡不支持锚点指认（只支持整卡点亮），"
                        "已整卡点亮。")
            elif not anchors:
                note = ("这张卡正文没埋〔〕锚点，已整卡点亮。想指着讲：把关键片段"
                        "用〔〕包起来重写这张卡。")
            elif point > len(anchors):
                note = (f"这张卡只有 {len(anchors)} 个〔〕锚点（编号 1~{len(anchors)}："
                        + "、".join(anchors) + f"），point={point} 指不到，已整卡点亮。")
            else:
                anchor = point
        item_id = _write_focus_card(uid, kind, content, data=data,
                                    anchors=anchors, anchor=anchor)
        # 写卡留痕（事故复盘时一度找不齐「哪张卡几点写的」：全链 16 个动作独缺 write）
        log.log("xz_board", "write", "success",
                {"uid": uid, "id": item_id, "kind": kind, "len": len(content)})
        txt = f"已写上黑板：#{item_id}（{kind}），已点亮"
        if anchor is not None:
            txt += f"，红点指着「{anchors[anchor - 1]}」"
        txt += "。" + (("\n注意：" + note) if note else "") + status_line(uid)
        return txt + "口头保持一句短句，与这张卡对应。"

    if name == "board_replace":
        try:
            item_id = int(args.get("item_id"))
        except (TypeError, ValueError, OverflowError):
            return "item_id 要是数字（状态行里 # 后面的卡号）。" + status_line(uid)
        # 省略 kind ＝保持原卡类型
        cur = None
        with _lock:
            for i in _board(uid)["items"]:
                if i["id"] == item_id:
                    cur = i["kind"]
                    break
        if cur is None:
            return f"黑板上没有卡 #{item_id}。" + status_line(uid)
        kind = _norm_kind(args.get("kind") or cur)
        if kind == "plot":   # 评审 Major-1：无论原卡还是目标 kind 是 plot，都拒改写
            return ("图卡不能改写（改写会把图的数据弄丢）：要改图请重新 board_draw "
                    "画一张新的，旧图卡用 board_remove 擦掉。" + status_line(uid))
        content = str(args.get("content") or "").strip()
        if not content:
            return "content 不能为空。" + status_line(uid)
        if kind == "formula":
            content = _strip_dollar(content)
        anchors = []
        if kind in _POINT_TEXT_KINDS:
            content, anchors = _extract_anchors(content)
        data = None
        if kind == "options":
            data = [s.strip() for s in content.replace("；", ";").split(";") if s.strip()][:8]
            content = "；".join(data)
        ok, why = _reject_too_long(kind, content)
        if not ok:
            return why + status_line(uid)
        if not content:   # 评审 Minor-7：与 write 同口径，剥锚后空正文不落卡
            return "剥掉〔〕锚点后没剩正文，这张卡没改成。" + status_line(uid)
        code = replace_card(uid, item_id, kind, content, data=data, anchors=anchors)
        if code == "missing":   # 锁间被并发擦板 → 不虚报成功（评审 Minor-5）
            return f"卡 #{item_id} 已不在黑板上，没改写成。" + status_line(uid)
        if code == "plot":
            return ("图卡不能改写（改写会把图的数据弄丢）：要改图请重新 board_draw "
                    "画一张新的，旧图卡用 board_remove 擦掉。" + status_line(uid))
        if code == "kindflip":
            return ("主干（topic）卡和普通卡不能互转：改主干名请保持 kind=topic；"
                    "普通卡想升主干，请新写一张 topic 卡再挂内容。" + status_line(uid))
        return (f"卡 #{item_id} 已改写为（{kind}）。" + status_line(uid)
                + "口头补一句为什么改，学生才知道板上的话变了。")

    if name == "board_remove":
        try:
            item_id = int(args.get("item_id"))
        except (TypeError, ValueError, OverflowError):
            return "item_id 要是数字（状态行里 # 后面的卡号）。" + status_line(uid)
        code, n = remove_card(uid, item_id)
        if code != "ok":
            return f"黑板上没有卡 #{item_id}。" + status_line(uid)
        if n > 1:
            return (f"已擦掉主干 #{item_id} 连同它的 {n - 1} 张子卡（共删 {n} 张）。"
                    + status_line(uid))
        return f"已擦掉卡 #{item_id}。" + status_line(uid)

    if name == "board_highlight":
        try:
            item_id = int(args.get("item_id"))
        except (TypeError, ValueError, OverflowError):
            return "item_id 要是数字（状态行里 # 后面的卡号）。" + status_line(uid)
        point, err = _parse_nn(args.get("point"), "point（指第几个锚/标记）")
        if err:
            return err + status_line(uid)
        reveal, err = _parse_nn(args.get("reveal"), "reveal（显示到第几步）")
        if err:
            return err + status_line(uid)
        code, info = focus_card(uid, item_id, point=point, reveal=reveal)
        if code == "missing":
            return f"黑板上没有卡 #{item_id}。" + status_line(uid)
        txt = f"已点亮卡 #{item_id}（其余熄灭）"
        if info.get("anchor") is not None:
            txt += f"，红点指着「{info.get('anchor_text')}」"
        if info.get("mark") is not None:
            txt += f"，激光指到图上的「{info.get('mark_name')}」"
        if info.get("reveal") is not None:
            txt += f"，图只显示到第 {info['reveal']} 步"
        txt += "。"
        note = info.get("note") or ""
        if note == "noanchor":
            if info.get("nanch"):
                txt += (f"\n注意：这张卡共 {info['nanch']} 个锚点（1~{info['nanch']}："
                        + "、".join(info.get("list") or []) + "），point 指不到，已整卡点亮。")
            else:
                txt += ("\n注意：这张卡正文没埋〔〕锚点，只能整卡点亮；"
                        "想指着讲先 board_replace 用〔〕包住关键片段。")
        elif note == "nomarks":
            if info.get("nmarks"):
                txt += (f"\n注意：这张图可指认 {info['nmarks']} 个标记："
                        + "、".join(f"{i + 1}.{nm}" for i, nm in enumerate(info.get("names") or []))
                        + f"，point 要在 1~{info['nmarks']}，已整卡点亮。")
            else:
                txt += "\n注意：这张图没有可指认标记，只能整卡点亮（画图时给关键元素带 name）。"
        elif note == "nokind":
            txt += "\n注意：formula/options 卡只支持整卡点亮（没有可指片段）。"
        elif note == "noreveal":
            total = info.get("total") or 0
            txt += (f"\n注意：reveal 只在图卡上分步（这张图共 {total} 步，reveal=1~{total}）。"
                    if total else "\n注意：reveal 只在图卡上分步，这张卡不是图。")
        return txt + status_line(uid)

    if name == "board_draw":
        ok, res = BP.validate_plot(args.get("spec"))
        brief = BP.spec_brief(args.get("spec"))
        if not ok:
            # 拒收必须留痕（降维课复盘：12 连拒无线索，事后无从印证老师嘴里的图）
            log.log("xz_board", "draw_reject", "error",
                    {"uid": uid, "reason": str(res)[:160], **brief})
            return (f"图没画上：{res}" + status_line(uid)
                    + "按指导修改 spec 后重试 board_draw。")
        point, err = _parse_nn(args.get("point"), "point（指到第几个标记）")
        if err:
            return err + status_line(uid)
        reveal, err = _parse_nn(args.get("reveal"), "reveal（显示到第几步）")
        if err:
            return err + status_line(uid)
        marks = res.get("marks") or []
        total = res.get("step_total") or 0
        mark = rv = None
        note = ""
        if point is not None:
            if point <= len(marks):
                mark = point
            else:
                note = (f"这张图可指认 {len(marks)} 个标记，point={point} 指不到，"
                        "已整卡点亮。" if marks else "这张图没有可指认标记，已整卡点亮。")
        if reveal is not None:
            if reveal <= total:
                rv = reveal
            else:
                note += f"这张图共 {total} 步，reveal={reveal} 超了，已全量显示。"
        title, _ = _clip(str(args.get("title") or "").strip(),
                         _CARD_LIMITS["plot"])
        item_id = _write_focus_card(uid, "plot", title or f"{res['plot_type']} 图",
                                    data=res, mark=mark, reveal=rv)
        log.log("xz_board", "draw", "success",
                {"uid": uid, "item_id": item_id, "plot_type": res["plot_type"],
                 "n_marks": len(marks), **brief})
        txt = f"已画上黑板：#{item_id}（plot·{res['plot_type']}），已点亮"
        if mark is not None:
            txt += f"，激光指到「{marks[mark - 1].get('name') or '标记'}」"
        if rv is not None:
            txt += f"，只显示到第 {rv} 步（共 {total} 步）"
        txt += "。"
        live = BP.describe(res)
        if live:
            # 八期方案 A：学生看到的颜色/数量以契约为准回报，老师说话照此报，
            # 不再拿 spec 臆想（降维课事故：嘴上「蓝点」，屏幕上只有黄点）
            txt += f"\n黑板实况：{live}。颜色和数量以此为准，说话照此报，别说图上没有的东西。"
        if marks:
            txt += ("可指认标记："
                    + "、".join(f"{i + 1}.{m.get('name') or '标记'}"
                                for i, m in enumerate(marks[:8]))
                    + "（point=N 指认）。")
            # v0.2.7 讲稿贴图纪律：拒收管得住 spec，管不住嘴——用返回指导语渐进调教
            txt += ("讲的时候只引用图上真写着的词（系列名/点标注）和真有的位置，"
                    "讲到哪组/哪个点就 point=N 指过去，学生跟着光标走。")
        if total > 1:
            txt += f"这张图分 {total} 步（reveal=N 分步显示）。"
        if note:
            txt += "\n注意：" + note
        return txt + status_line(uid) + "对着图一步一步讲，关键结论另写 step/formula 卡。"

    if name == "board_render_anim":
        with _lock:
            b = _board(uid)
            a = b.get("anim")
            busy = bool(a and a["state"] == "generating")
            eid = b["source_error_id"]
        if busy:   # 锁外再拼状态行：Lock 不可重入，锁内调 status_line 必自锁死
            return ("动画舞台已经在后台生成中（要几分钟），不用重复提交；"
                    "继续用讲义卡讲课。" + status_line(uid))
        topic = str(args.get("topic") or "").strip()
        material, subject = "", "通用"
        stype = "explain"
        if eid:
            pack = _lesson_pack_text(uid, str(eid))
            if pack:
                material = pack["text"]
                subject = pack.get("subject") or "通用"
                stype = "example"
        if not material and topic:
            material = "学生当前主题（来自老师口述）： " + topic[:600]
        if not material:
            return ("还没有生成素材：先 board_show_problem 上题，或带 topic 文字再调。"
                    + status_line(uid))
        import credits_service as cr
        try:
            pre = cr.precheck(uid)
            if not pre["allowed"] and not cr.get_user_llm_config(uid):
                return ("积分不够，动画舞台开不了工；先用讲义卡照常讲课。"
                        + status_line(uid))
        except Exception:  # noqa: BLE001 预检异常不拦路：真扣费在 call_llm_for_user 内自保护
            pass
        title = (str(args.get("topic") or "").strip()[:20] or "本题") + "·动画讲解"
        gen = uuid.uuid4().hex
        with _lock:
            b = _board(uid)
            b["anim"] = {"gen": gen, "state": "generating", "title": title,
                         "steps": [], "current": -1, "error": "", "note": "",
                         "announced": True}
            b["rev"] += 1
        threading.Thread(target=_anim_worker, daemon=True, name="xz-anim-gen",
                         args=(uid, gen, stype, title, material, subject,
                               "", "")).start()
        log.log("xz_board", "render_anim", "success",
                {"uid": uid, "stype": stype, "gen": gen})
        return (f"已后台开工生成动画舞台《{title}》（要几分钟）。不阻塞：这段时间继续用 "
                "board_write/board_draw 讲课；完成后工具返回会提示你，那时对学生说"
                "「准备好了，我们来看这个」。" + status_line(uid))

    if name == "board_anim_step":
        try:
            i = int(args.get("step"))
        except (TypeError, ValueError, OverflowError):
            return "step 要是数字（从 0 开始）。" + status_line(uid)
        with _lock:   # 持锁内只改状态，返回文案（含 status_line）一律锁外拼
            b = _board(uid)
            a = b.get("anim")
            if not a or a["state"] != "ready":
                code = "notready"
            elif not (0 <= i < len(a["steps"])):
                code, n = "range", len(a["steps"])
            else:
                a["current"] = i
                b["rev"] += 1
                s = a["steps"][i]
                code = "ok"
        if code == "notready":
            return ("舞台还没就绪（生成中或没开工）；继续用讲义卡讲课，"
                    "好了工具返回会提示你。" + status_line(uid))
        if code == "range":
            return (f"步序号超出范围：本舞台共 {n} 步（0~{n - 1}）。" + status_line(uid))
        return (f"舞台已推进到第 {i} 步。字幕「{s['caption']}」。"
                f"口播稿（照这句念，前端画面同步变化）：{s['narration']}" + status_line(uid))

    if name == "board_clear":
        clear_board(uid)
        # 擦板不清指派（中位线定理误杀事故）：有指派在位时指路 get_lesson_material，
        # 避免老师被旧文案引导直接 board_show_problem 绕过指派（评审 Minor-3）。
        if get_assign(uid):
            return ("黑板已擦干净。" + status_line(uid)
                    + "学生网页已指派待讲内容，先调 get_lesson_material 取指导语。")
        return ("黑板已擦干净。" + status_line(uid)
                + "开始新讲解前先用 board_show_problem 上题。")

    if name == "lesson_prepare":
        return _tool_lesson_prepare(uid, args)

    if name == "lesson_list_preps":
        return _tool_lesson_list_preps(uid, args)

    raise ValueError(f"未知工具: {name}")


def _pack_images(uid: str, stem_md: str) -> list:
    """题干 MD 里的题目原图（vault 相对路径清单，保序）。
    提取复用错题分析唯一实现 md_image_paths（公共函数注册制；延迟导入避开 PIL
    等重依赖）；服务端亲自校验真实落在本用户 vault 目录内才放行——路径来自
    错题数据，绝不能把坏路径/穿越路径递给前端去读。坏引用静默丢弃：缺图不阻断讲题。"""
    try:
        from services.error_analyze import md_image_paths
        rels = md_image_paths(stem_md or "")
    except Exception:  # noqa: BLE001 提取失败＝当没图，讲题照常
        return []
    from services.board_lesson import valid_uid
    if not rels or not valid_uid(uid):
        return []
    root = (VAULT_DIR / str(uid)).resolve()
    out = []
    for rel in rels:
        try:
            p = (root / rel).resolve(strict=False)
        except (OSError, ValueError):
            continue
        if not p.is_file() or root not in p.parents:
            continue
        if p.suffix.lower() not in _IMG_EXTS:
            continue
        out.append(rel)
        if len(out) >= _IMG_MAX_PER_PROBLEM:
            break
    return out


def _strip_img_refs(md: str, kept: list) -> str:
    """题干图片引用处置（评审 Minor-2）：已上板的图换成提示文案，
    其余死引用（被截断/校验失败）一律剥净——避免「声称已上板但实际没有」
    或裸 MD 语法漏给前端。"""
    out = md or ""
    for rel in kept:
        out = re.sub(r"!\[[^\]]*\]\(" + re.escape(rel) + r"\)",
                     "（原图已上黑板）", out)
    return _MD_IMG_REF_RE.sub("", out)


def _lesson_pack_text(uid: str, error_id: str):
    """取单题素材（复用微课六期唯一实现），限长防上下文拥挤。返回 None=无此题。"""
    from routes_micro_course import error_explain_pack
    try:
        eid = int(error_id)
    except (TypeError, ValueError, OverflowError):
        return None
    pack = error_explain_pack(uid, eid)
    if not pack:
        return None
    text, trunc = _clip(pack.get("text") or "", _MATERIAL_MAX)
    pack["text"] = text + ("（素材过长已截断，剩余部分在系统里）" if trunc else "")
    pack["images"] = _pack_images(uid, pack.get("stem") or "")
    return pack


# ---------------------------------------------------------------- 备课双入口（黑板两段式轮 2026-11-05）
# 语音入口（本工具）与黑板页「请老师备课」按钮共用同一条微课生成链路
# （routes_micro_course.prep_topic_course）：那里只登记课程行 + 派后台线程，LLM 全在线程里跑，
# 所以工具侧天然秒回不阻塞——与 board_render_anim 同一异步纪律（小智实时对话等不了几分钟）。

_PREP_LIST_MAX = 5      # 工具返回里一次列几节课（防上下文拥挤）
_PREP_BUSY = ("generating", "regenerating")


def _prep_line(rows: list) -> str:
    """备课清单压成一行（课号只给前 8 位，大脑引用够用且不撑爆返回）。"""
    if not rows:
        return "（还没有已备好的课）"
    parts = []
    for r in rows[:_PREP_LIST_MAX]:
        st = r.get("status") or ""
        mark = "生成中" if st in _PREP_BUSY else ("可上" if r.get("pages") else "还没出页")
        parts.append(f"《{r.get('title') or '未命名'}》{r.get('pages') or 0}页/{st}/{mark}"
                     f"/课号{(r.get('lesson_key') or '')[:8]}")
    return "；".join(parts)


def _prep_rows(uid: str, only_ready: bool = True) -> list:
    """读备课清单（异常不抖：备课是加菜，读不到不能把课砸了）。"""
    from services import board_lesson as BL
    try:
        return BL.list_preps(uid, limit=8, only_ready=only_ready)
    except Exception as e:  # noqa: BLE001
        log.log_error("xz_board", "list_preps", f"uid={uid} err={e}")
        return []


def _tool_lesson_prepare(uid: str, args: dict) -> str:
    topic = str(args.get("topic") or "").strip()[:80]
    subject = str(args.get("subject") or "").strip()[:40]
    if not topic:
        return ("备课要说清主题：topic 填要备什么（如「sin x / x 的极限与夹逼」）。"
                + status_line(uid))
    try:
        from routes_micro_course import prep_topic_course
        r = prep_topic_course(uid, topic, subject)
    except Exception as e:  # noqa: BLE001 开工异常绝不断讲课
        log.log_error("xz_board", "lesson_prepare", f"uid={uid} topic={topic} err={e}")
        return ("备课这会儿开不了工（服务暂时读不到你的资料），不影响讲课："
                "照常 board_write/board_draw 往下讲。" + status_line(uid))
    if not r.get("success"):
        return (f"备课没开工：{r.get('error') or '未知原因'}。"
                "不影响讲课，照常往下讲；换个主题再试就说一声。" + status_line(uid))
    track = ("已按你已有的知识点备课（含笔记与错题素材）"
             if r.get("track") == "kp" else "已按自拟主题备课")
    head = ("这节已经在备课中了（不重复开工、不重复扣积分）"
            if r.get("reused") else f"已后台开工备课（{track}）")
    return (f"{head}：《{topic}》，生成要几分钟。"
            + "\n[在备课件] " + _prep_line(_prep_rows(uid, only_ready=False))
            + "\n现在继续讲黑板上的内容，别干等着；备好后学生会看到「已备好一节课」的提示条，"
              "那时你说一句「已经给你备好一节课了，我们待会儿上」。" + status_line(uid))


def _tool_lesson_list_preps(uid: str, args: dict) -> str:
    key = str(args.get("lesson_key") or "").strip().lower()
    hint = str(args.get("title") or "").strip()
    rows = _prep_rows(uid, only_ready=False)
    # 接单只接「已有页且不在生成中」的课：micro_scenes 的 UNIQUE(course_id, seq) 是
    # 板书页追加与大纲逐页插页共用的，生成中接单会撞页序（同 /api/board/adopt 口径）
    ready = [r for r in rows if r.get("pages") and r.get("status") not in _PREP_BUSY]
    if not key and not hint:
        if not rows:
            return ("你还没有备好的课。要备一节就说「帮我备一节关于X的课」。"
                    + status_line(uid))
        return ("[已备好的课] " + _prep_line(rows)
                + "\n要上哪一节让学生说一声；他点名后你带着那节课的课号再调一次本工具，"
                  "就直接接上这节课。" + status_line(uid))
    hit = None
    for r in ready:
        k = (r.get("lesson_key") or "").lower()
        if (key and (k == key or k.startswith(key))) or (hint and hint in (r.get("title") or "")):
            hit = r
            break
    if hit is None:
        return ("那节课接不上（还没备好、还在生成中、或找不到同名课）。可上的有："
                + _prep_line(ready) + status_line(uid))
    if get_lesson_key(uid) == hit["lesson_key"]:
        return (f"本课已经在用《{hit.get('title') or '未命名'}》这份课件了。"
                + status_line(uid))
    set_lesson_key(uid, hit["lesson_key"])
    return (f"已接上《{hit.get('title') or '未命名'}》（已备好 {hit.get('pages')} 页）："
            "这节课你画的每一张板书图，都会连老师针对它说的话一起存进这份课件。"
            + status_line(uid)
            + "现在开讲：先 board_show_problem 上题，或直接 board_write/board_draw。")
