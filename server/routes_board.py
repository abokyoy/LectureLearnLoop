# -*- coding: utf-8 -*-
"""黑板 HTTP 蓝图（2026-11-04 小智云端讲师 P1）。

前端黑板页两条通道（决策：轮询而非 SSE——全站无 SSE 先例，rev 比较轮询最简且够实时）：
- GET  /api/board/state?since=<rev>：rev 未变时只回 {changed:false}，变了回全量条目；
- POST /api/board/clear：学生手动擦黑板（与云端 board_clear 工具同一条底层实现）。
用户隔离：一切读写按 g.user_id，与桥绑定 uid 相同才可见同一块板。

两段式版式轮（2026-11-05）新增：字幕上报、课件页归档、收课、导出与签名下载、
备课双入口（/prep 自写主题、/adopt 接备好的课来上）。全部返 {success,data} 双层契约，
失败走 error 字段（pmUtil/api.js 把它抛为异常消息）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file

from auth import require_auth
from config import VAULT_DIR
from logger_module import debug_logger as log
from services import board_export as BX
from services import board_explainer as BE
from services import board_lesson as BL
from services import lecture_board as LB
from services import mcp_bridge as MB
from services import xz_device

board_bp = Blueprint("board", __name__)


@board_bp.route("/api/board/state", methods=["GET"])
@require_auth
def board_state():
    since = request.args.get("since", default=0, type=int) or 0
    return jsonify({"success": True, "data": LB.get_state(g.user_id, since)})


@board_bp.route("/api/board/clear", methods=["POST"])
@require_auth
def board_clear():
    return jsonify({"success": True, "data": LB.clear_board(g.user_id)})


# ---------------------------------------------------------------- 「AI老师讲」多入口指派（v0.2.8）
# 入口按钮（错题行/知识点卡/判分结果）先 POST 记指派再跳黑板页；黑板页 GET 到指派
# 后弹提示条并自动开课；老师首次 get_lesson_material 拿到注入指导语（一次性消费）。

_ASSIGN_LABEL_MAX = 24  # 提示条标题限长（题干压成一行后的字符数）
_ASSIGN_MD_RE = re.compile(r"[#*`$\n\r\t]+")


def _assign_label(stem: str) -> str:
    """题干→提示条短标题：剥 MD/LaTeX 记号后截断（与前端讲解错题标签同口径）。"""
    s = _ASSIGN_MD_RE.sub(" ", str(stem or "")).strip()
    return (s[:_ASSIGN_LABEL_MAX] + "…") if len(s) > _ASSIGN_LABEL_MAX else s


@board_bp.route("/api/board/assign", methods=["POST"])
@require_auth
def board_assign():
    """记指派：body {kind:'error', error_id} / {kind:'kp', kp_id} /
    {kind:'text', text}（课文框选原文，追问笔记树轮 2026-11-12）。
    error/kp 归属校验走素材唯一实现（错题 error_explain_pack / 知识点 kp_teach_pack），
    查无此料即拒，不在指派层另开 SQL；text 无归属问题（文本来自本人页面操作）。"""
    body = request.get_json(silent=True) or {}
    kind = str(body.get("kind") or "").strip().lower()
    if kind == "error":
        try:
            eid = int(body.get("error_id"))
        except (TypeError, ValueError, OverflowError):   # 1e999→inf 抛 OverflowError，入口口径齐（评审 Minor-3）
            return jsonify({"success": False, "error": "error_id 非法"})
        try:
            from routes_micro_course import error_explain_pack
            pack = error_explain_pack(str(g.user_id), eid)
        except Exception as e:  # noqa: BLE001 入口异常不能把页面带坑
            log.log_error("xz_board", "board_assign", f"uid={g.user_id} err={e}")
            return jsonify({"success": False, "error": "错题素材读取失败，稍后再试"})
        if not pack:
            return jsonify({"success": False, "error": "没找到这道错题（或它不属于你）"})
        a = LB.set_assign(g.user_id, "error", eid, _assign_label(pack.get("stem") or ""))
        # 融合轮 2026-11-09 用户裁定：指派时刻即自动开工本课原理图舞台（默认开，
        # 后台线程不阻塞指派响应）；失败只静默留痕，讲课照常回落讲义卡链
        try:
            LB.auto_open_stage(str(g.user_id), "error", eid, a["label"])
        except Exception as e:  # noqa: BLE001
            log.log_error("xz_board", "stage_auto", f"uid={g.user_id} err={e}")
        return jsonify({"success": True, "data": {"kind": "error", "label": a["label"]}})
    if kind == "kp":
        try:
            kpid = int(body.get("kp_id"))
        except (TypeError, ValueError, OverflowError):
            return jsonify({"success": False, "error": "kp_id 非法"})
        try:
            from routes_micro_course import kp_teach_pack
            pack = kp_teach_pack(g.user_id, kpid)
        except Exception as e:  # noqa: BLE001
            log.log_error("xz_board", "board_assign", f"uid={g.user_id} err={e}")
            return jsonify({"success": False, "error": "知识点素材读取失败，稍后再试"})
        if not pack:
            return jsonify({"success": False, "error": "没找到这个知识点（或它不属于你）"})
        a = LB.set_assign(g.user_id, "kp", kpid, _assign_label(pack["name"]))
        try:   # 同上：kp 指派自动开工原理图舞台（同源重复指派在 auto_open_stage 内复用不重开）
            LB.auto_open_stage(str(g.user_id), "kp", kpid, a["label"])
        except Exception as e:  # noqa: BLE001
            log.log_error("xz_board", "stage_auto", f"uid={g.user_id} err={e}")
        return jsonify({"success": True, "data": {"kind": "kp", "label": a["label"]}})
    if kind == "text":
        # 课文阅读「请老师讲课」：选中原文直接作题目（限 600 字防超长把指导语撑爆）；
        # id 存文本稳定哈希（md5 前 6 字节，跨进程/重启同源可去重；built-in hash 有随机盐不可用），
        # 供 auto_open_stage/principle_cache 同源去重（同文再点复用图）
        text = str(body.get("text") or "").strip()
        if not text:
            return jsonify({"success": False, "error": "text 不能为空"})
        text = text[:600]
        tid = int.from_bytes(hashlib.md5(text.encode("utf-8")).digest()[:6], "big") or 1
        a = LB.set_assign(g.user_id, "text", tid, _assign_label(text), raw_text=text)
        try:   # 同 error/kp：指派时刻自动开工原理图舞台，失败静默不影响指派
            LB.auto_open_stage(str(g.user_id), "text", tid, a["label"], raw_text=text)
        except Exception as e:  # noqa: BLE001
            log.log_error("xz_board", "stage_auto", f"uid={g.user_id} err={e}")
        return jsonify({"success": True, "data": {"kind": "text", "label": a["label"]}})
    return jsonify({"success": False, "error": "kind 只支持 error/kp/text"})


@board_bp.route("/api/board/assign", methods=["GET"])
@require_auth
def board_assign_get():
    """查当前指派（黑板页进页提示条/自动开课判断用，不消费）。"""
    a = LB.get_assign(g.user_id)
    data = {"kind": a["kind"], "id": a["id"], "label": a["label"]} if a else None
    return jsonify({"success": True, "data": {"assign": data}})


# ---------------------------------------------------------------- 小智 MCP 接入配置（2026-11-05 设置页）
# 单桥设计：最后一次「连接」生效，绑定黑板归属为点连接的用户；status 只回脱敏地址。

@board_bp.route("/api/board/mcp/status", methods=["GET"])
@require_auth
def mcp_status():
    return jsonify({"success": True, "data": MB.status()})


@board_bp.route("/api/board/mcp/connect", methods=["POST"])
@require_auth
def mcp_connect():
    body = request.get_json(silent=True) or {}
    ok, message = MB.connect(body.get("endpoint", ""), g.username)
    # pmUtil.postJSON 双层契约：失败文案走 error 字段（前端抛为异常消息）
    if not ok:
        return jsonify({"success": False, "error": message, "data": MB.status()})
    return jsonify({"success": True, "data": MB.status()})


@board_bp.route("/api/board/mcp/disconnect", methods=["POST"])
@require_auth
def mcp_disconnect():
    ok, message = MB.disconnect()
    return jsonify({"success": ok, "message": message, "data": MB.status()})


# ---------------------------------------------------------------- 小智设备账号级绑定（2026-11-05）
# 身份跟账号走：设置页生成虚拟小智/绑真 ESP32；EXE 领身份上课；失败文案走 error 字段（pmUtil 双层契约）。

@board_bp.route("/api/board/xzdevice/status", methods=["GET"])
@require_auth
def xzdevice_status():
    return jsonify({"success": True, "data": xz_device.status(g.user_id)})


@board_bp.route("/api/board/xzdevice/generate", methods=["POST"])
@require_auth
def xzdevice_generate():
    ok, message = xz_device.generate(g.user_id)
    data = xz_device.status(g.user_id)
    data["message"] = message
    if not ok:
        return jsonify({"success": False, "error": message, "data": data})
    return jsonify({"success": True, "data": data})


@board_bp.route("/api/board/xzdevice/bind_real", methods=["POST"])
@require_auth
def xzdevice_bind_real():
    body = request.get_json(silent=True) or {}
    ok, message = xz_device.bind_real(g.user_id, body.get("mac", ""))
    data = xz_device.status(g.user_id)
    data["message"] = message
    if not ok:
        return jsonify({"success": False, "error": message, "data": data})
    return jsonify({"success": True, "data": data})


@board_bp.route("/api/board/xzdevice/recheck", methods=["POST"])
@require_auth
def xzdevice_recheck():
    ok, message = xz_device.recheck(g.user_id)
    data = xz_device.status(g.user_id)
    data["message"] = message
    if not ok:
        return jsonify({"success": False, "error": message, "data": data})
    return jsonify({"success": True, "data": data})


@board_bp.route("/api/board/xzdevice/unbind", methods=["POST"])
@require_auth
def xzdevice_unbind():
    ok, message = xz_device.unbind(g.user_id)
    return jsonify({"success": ok, "message": message, "data": xz_device.status(g.user_id)})


@board_bp.route("/api/board/xzdevice/identity", methods=["GET"])
@require_auth
def xzdevice_identity():
    # EXE 领身份：仅 bound 回 mac/client_uuid；旧包兼容也走此契约
    return jsonify({"success": True, "data": xz_device.identity(g.user_id)})


@board_bp.route("/api/board/xzdevice/migrate", methods=["POST"])
@require_auth
def xzdevice_migrate():
    body = request.get_json(silent=True) or {}
    ok, message = xz_device.migrate(g.user_id, body.get("mac", ""), body.get("client_uuid", ""))
    if not ok:
        return jsonify({"success": False, "error": message, "data": xz_device.identity(g.user_id)})
    return jsonify({"success": True, "data": xz_device.identity(g.user_id)})


# ---------------------------------------------------------------- 课堂字幕与课件归档（两段式版式轮）
# 数据契约沿用全站双层 {success, data}/{success, error}；EXE 上报失败必须静默，绝不阻断讲课。

_IMG_MIME = {
    ".png": ("image/png", False),
    ".pdf": ("application/pdf", False),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", True),
}


def _asset_secret() -> bytes:
    s = current_app.secret_key
    return s.encode() if isinstance(s, str) else (s or b"")


def _asset_sign(uid: str, rel: str, exp: int) -> str:
    msg = f"{uid}|{rel}|{exp}"
    return hmac.new(_asset_secret(), msg.encode(), hashlib.sha256).hexdigest()


def _asset_path(uid: str, rel: str):
    """把 rel 解析到 vault/<uid>/课件/<lesson_key>/文件名；不合闸一律 None。

    硬闸三层：uid 字符闸 + 课件键格式闸（^[0-9a-f]{16}$）+ 后缀白名单，
    另验证解析后仍在该用户 vault 目录内（防 .. 与符号链穿越）。
    """
    if not BL.valid_uid(uid) or not rel:
        return None
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) != 3 or parts[0] != "课件" or not BL.valid_key(parts[1]):
        return None
    name = parts[2]
    if name != Path(name).name or name.startswith("."):
        return None
    ext = Path(name).suffix.lower()
    if ext not in _IMG_MIME:
        return None
    root = (VAULT_DIR / str(uid)).resolve()
    p = (root / "课件" / parts[1] / name).resolve(strict=False)
    if root not in p.parents or not p.is_file():
        return None
    return p


@board_bp.route("/api/board/speech", methods=["POST"])
@require_auth
def board_speech():
    """EXE 虚拟小智上报一句口播（role=teacher 云端 tts sentence / student stt）。

    不做「必须处于上课中」硬拦：只有课中 EXE 才会上报，服务端拦不到也无害；
    黑板内存没初始化时 append_speech 会自行建板（与写卡同一入口）。
    """
    body = request.get_json(silent=True) or {}
    line = LB.append_speech(g.user_id, body.get("role"), body.get("text"))
    if line is None:
        return jsonify({"success": False, "error": "字幕无效：role 要 teacher/student，text 不能为空"})
    return jsonify({"success": True, "data": line})


@board_bp.route("/api/board/slide_image", methods=["POST"])
@require_auth
def board_slide_image():
    """前端把一页定稿板书（图 + 烧进去的讲稿）合成 PNG 上传 → 落 vault + micro_scenes。

    body: {lesson_key?, image_b64, caption?, title?, plot_json?, source_error_id?}
    前端逐张串行上传（页序 seq 由服务端 max+1，撞车重试）。单页 PNG 上限 2MB（服务层闸）。
    """
    body = request.get_json(silent=True) or {}
    lk = (body.get("lesson_key") or "").strip() or (LB.get_lesson_key(g.user_id) or "")
    if not BL.valid_key(lk):
        return jsonify({"success": False, "error": "课件键非法：要 16 位小写十六进制"})
    b64 = body.get("image_b64") or ""
    if isinstance(b64, str) and b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    try:
        raw = base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        return jsonify({"success": False, "error": "图片不是合法 base64"})
    r = BL.append_slide(g.user_id, lk, body.get("plot_json"), body.get("caption") or "",
                        raw, body.get("title") or "", body.get("source_error_id"))
    if not r.get("success"):
        return jsonify({"success": False, "error": r.get("error") or "课件页入库失败"})
    return jsonify({"success": True, "data": {"lesson_key": lk, "seq": r["seq"],
                                             "image_rel": r["image_rel"],
                                             "pages": r["pages"],
                                             "deduped": bool(r.get("deduped"))}})


@board_bp.route("/api/board/outbox_drop", methods=["POST"])
@require_auth
def board_outbox_drop():
    """前端已把某页 PNG 传上来 → 回执删除 outbox 条目（否则下次轮询又重传一次）。

    只有 slide_image 入库成功才回执（上传失败保留在件箱，下一轮重试）。
    """
    body = request.get_json(silent=True) or {}
    oids = body.get("oids") or []
    if not isinstance(oids, list):
        return jsonify({"success": False, "error": "oids 要写成数组"})
    return jsonify({"success": True, "data": {"remaining": LB.drop_outbox(g.user_id, oids)}})


@board_bp.route("/api/board/archive", methods=["POST"])
@require_auth
def board_archive():
    """收课（下课/擦板且出件箱已排空）：最后一张挂着讲稿窗的图先闭窗，再补标题定档。"""
    body = request.get_json(silent=True) or {}
    lk = (body.get("lesson_key") or "").strip() or (LB.get_lesson_key(g.user_id) or "")
    if not BL.valid_key(lk):
        return jsonify({"success": False, "error": "本课还没画图，没有可收的课件"})
    LB.close_caption(g.user_id)
    r = BL.close_course(g.user_id, lk, body.get("title") or "")
    if not r.get("success"):
        return jsonify({"success": False, "error": r.get("error") or "收课失败"})
    return jsonify({"success": True, "data": {"lesson_key": lk, "title": r["title"],
                                             "pages": r["pages"]}})


@board_bp.route("/api/board/close_caption", methods=["POST"])
@require_auth
def board_close_caption():
    """下课第一步：只给还挂着讲稿窗的那张图闭窗定稿（进 outbox），不收课。

    前端顺序必须是 close_caption → 逐张出 PNG 上传 slide_image → archive 收课：
    archive 会立刻定档，而最后一页的 PNG 只有浏览器渲染得出来，不能等它。
    """
    return jsonify({"success": True, "data": LB.close_caption(g.user_id)})


@board_bp.route("/api/board/lesson", methods=["GET"])
@require_auth
def board_lesson():
    """本课课件页列表（黑板页「本课课件」抽屉）。不传 lesson_key 那么用当前板的课键。"""
    lk = (request.args.get("lesson_key") or "").strip() or (LB.get_lesson_key(g.user_id) or "")
    if not BL.valid_key(lk):
        return jsonify({"success": True, "data": {"lesson_key": None, "pages": 0, "slides": []}})
    course = BL.get_course(g.user_id, lk) or {}
    slides = []
    for s in BL.list_slides(g.user_id, lk):
        s.pop("image_path", None)          # 绝对路径不出服务，预览走签名 asset
        s.pop("plot_spec", None)           # 抽屉只展示图与讲稿，不回传绘图为份 spec
        s["has_image"] = bool(s.get("image_rel"))
        slides.append(s)
    return jsonify({"success": True, "data": {
        "lesson_key": lk, "title": course.get("title") or "", "status": course.get("status") or "",
        "export_rel": course.get("export_rel") or "", "pages": len(slides), "slides": slides}})


@board_bp.route("/api/board/lessons", methods=["GET"])
@require_auth
def board_lessons():
    """本账号的课件列表（备课入口与「已备好一节课」提示条数据源）。"""
    return jsonify({"success": True, "data": {"lessons": BL.list_lessons(g.user_id)}})


@board_bp.route("/api/board/prep", methods=["POST"])
@require_auth
def board_prep():
    """黑板页「请老师备课」的自写主题分支（与语音工具 lesson_prepare 同一底层实现）。

    body: {topic, subject?}。只做建课行 + 派后台线程（LLM 全在线程里），秒回课键；
    黑板页靠 /api/board/lessons 轮询出「已备好一节课」提示条。命中已有知识点则走 kp 轨。
    """
    body = request.get_json(silent=True) or {}
    try:
        from routes_micro_course import prep_topic_course
        r = prep_topic_course(str(g.user_id), body.get("topic"), body.get("subject") or "")
    except Exception as e:  # noqa: BLE001 开工异常不能把黑板页带坑
        log.log_error("xz_board", "board_prep", f"uid={g.user_id} err={e}")
        return jsonify({"success": False, "error": "备课暂时开不了工，稍后再试"})
    if not r.get("success"):
        return jsonify({"success": False, "error": r.get("error") or "备课开工失败"})
    return jsonify({"success": True, "data": r})


@board_bp.route("/api/board/adopt", methods=["POST"])
@require_auth
def board_adopt():
    """接一节备好的课来上：把本课课件键指到该课，之后画的板书页存进同一门课。

    只接「已存在且不在生成中」的课：micro_scenes 的 UNIQUE(course_id, seq) 是板书页
    追加与大纲逐页插页共用的，生成中接单会撞页序。返回最新板 state（前端 paint 直接吃）。
    """
    body = request.get_json(silent=True) or {}
    lk = str(body.get("lesson_key") or "").strip().lower()
    if not BL.valid_key(lk):
        return jsonify({"success": False, "error": "课件键非法：要 16 位小写十六进制"})
    course = BL.get_course(g.user_id, lk)
    if not course:
        return jsonify({"success": False, "error": "没找到这份课件（或它不属于你）"})
    if course["status"] in ("generating", "regenerating"):
        return jsonify({"success": False, "error": "这节课还在生成中，备好后再来上"})
    return jsonify({"success": True, "data": LB.set_lesson_key(g.user_id, lk)})


@board_bp.route("/api/board/export", methods=["POST"])
@require_auth
def board_export():
    """导出本课课件为 PDF/PPTX（用已归档的 PNG 拼装），回签名下载 URL。"""
    body = request.get_json(silent=True) or {}
    lk = (body.get("lesson_key") or "").strip() or (LB.get_lesson_key(g.user_id) or "")
    if not BL.valid_key(lk):
        return jsonify({"success": False, "error": "本课还没有课件页可导出"})
    r = BX.export(g.user_id, lk, body.get("fmt") or "pdf", body.get("title") or "")
    if not r.get("success"):
        return jsonify({"success": False, "error": r.get("error") or "导出失败"})
    exp = int(time.time()) + 3600
    token = _asset_sign(g.user_id, r["rel"], exp)
    url = (f"/api/board/asset?u={g.user_id}&rel={r['rel']}"
           f"&exp={exp}&t={token}&dl=1")
    return jsonify({"success": True, "data": {"rel": r["rel"], "name": r["name"],
                                             "fmt": r["fmt"], "pages": r["pages"],
                                             "with_text": r.get("with_text"), "url": url}})


@board_bp.route("/api/board/asset/sign", methods=["GET"])
@require_auth
def board_asset_sign():
    """给某件课件产物（PNG/PDF/PPTX）签发 60 分钟访问 token（图片/下载链接带不了 Authorization）。"""
    rel = (request.args.get("rel") or "").strip()
    p = _asset_path(g.user_id, rel)
    if p is None:
        return jsonify({"success": False, "error": "路径非法（仅本用户 vault 课件目录）"})
    exp = int(time.time()) + 3600
    return jsonify({"success": True, "data": {"u": g.user_id, "rel": rel, "exp": exp,
                                             "t": _asset_sign(g.user_id, rel, exp)}})


@board_bp.route("/api/board/asset", methods=["GET"])
def board_asset():
    """签名 token 鉴权的课件产物下载（无 Authorization 头，供 <img> 与 <a download> 直用）。"""
    u = (request.args.get("u") or "").strip()
    rel = (request.args.get("rel") or "").strip()
    t = (request.args.get("t") or "").strip()
    try:
        exp = int(request.args.get("exp") or "0")
    except ValueError:
        exp = 0
    if not u or not rel or not t or exp <= 0:
        return jsonify({"error": "签名参数缺失"}), 400
    if exp < int(time.time()):
        return jsonify({"error": "签名已过期，请重新打开课件抽屉"}), 401
    if not hmac.compare_digest(_asset_sign(u, rel, exp), t):
        return jsonify({"error": "签名无效"}), 403
    p = _asset_path(u, rel)
    if p is None:
        return jsonify({"error": "文件不存在"}), 404
    mime, force_dl = _IMG_MIME[p.suffix.lower()]
    return send_file(str(p), mimetype=mime, as_attachment=force_dl or (request.args.get("dl") == "1"),
                     download_name=p.name, conditional=True)


# ---------------------------------------------------------------- 黑板「原理图」按需生成（Demo 轮 2026-11-09）
# 入口在黑板页「板·书」区顶部；方法论移植自开源项目 html-explainer（模型写自包含
# HTML 画面而非生成像素），实现与产物校验链见 services/board_explainer。
# POST 开工秒回作业（后台线程跑 LLM，同备课异步模式），GET 轮询终态。

@board_bp.route("/api/board/explain", methods=["POST"])
@require_auth
def board_explain():
    """点一下：把当前课堂信息交给大模型，产一页可交互的原理图 HTML。

    body 可选 {refresh: true}：跳过库复用、开思考模式深度重画（更慢、更耗积分，
    成本优化轮 2026-11-10 用户裁定规则 1）；缺省非 refresh 时同课已有库产物秒回。
    """
    body = request.get_json(silent=True) or {}
    refresh = bool(body.get("refresh"))
    try:
        r = BE.start(g.user_id, refresh=refresh)
    except Exception as e:  # noqa: BLE001 开工异常不能把黑板页带坑（同 board_prep 纪律）
        log.log_error("xz_board", "board_explain", f"uid={g.user_id} err={e}")
        return jsonify({"success": False, "error": "原理图暂时开不了工，稍后再试"})
    if not r.get("success"):
        return jsonify({"success": False, "error": r.get("error") or "开工位失败"})
    return jsonify({"success": True, "data": {"job": r["job"],
                                              "reused": r.get("reused") or False}})


@board_bp.route("/api/board/explain/latest", methods=["GET"])
@require_auth
def board_explain_latest():
    """查本课库中最新原理图产物（重启/换浏览器进页秒出旧图）；无则 data.job=None。"""
    j = BE.latest(g.user_id)
    return jsonify({"success": True, "data": {"job": j}})


@board_bp.route("/api/board/explain/versions", methods=["GET"])
@require_auth
def board_explain_versions():
    """本课历史版本档案（回看旧版入口，纯读库零外呼）：最新在前，含 thinking 标记。"""
    return jsonify({"success": True, "data": {"versions": BE.versions(g.user_id)}})


@board_bp.route("/api/board/explain/version/<int:seq>", methods=["GET"])
@require_auth
def board_explain_version(seq):
    """看指定旧版产物（零外呼零扣分）；无此版→错误。"""
    j = BE.view(g.user_id, int(seq))
    if j is None:
        return jsonify({"success": False, "error": "该版本不存在或已过期"}), 404
    return jsonify({"success": True, "data": {"job": j}})


@board_bp.route("/api/board/explain/promote", methods=["POST"])
@require_auth
def board_explain_promote():
    """旧版设为当前版：库内拷贝成新版本（不碰 LLM、零扣分零外呼）。body {seq}。"""
    body = request.get_json(silent=True) or {}
    seq = body.get("seq")
    # bool 是 int 子类（评审 Nit）：{"seq": true} 不得穿透成 promote 版 1
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        return jsonify({"success": False, "error": "缺少版本号 seq"})
    r = BE.promote(g.user_id, seq)
    if not r.get("success"):
        return jsonify({"success": False, "error": r.get("error") or "切换失败"})
    return jsonify({"success": True, "data": {"seq": r.get("seq"),
                                              "noop": bool(r.get("noop"))}})


@board_bp.route("/api/board/explain/<job_id>", methods=["GET"])
@require_auth
def board_explain_job(job_id):
    """查作业状态：generating / done（带 title+html+warning）/ failed（带 error）。"""
    j = BE.get_job(g.user_id, (job_id or "").strip())
    if j is None:
        return jsonify({"success": False, "error": "作业不存在或已过期"})
    return jsonify({"success": True, "data": {"job": j}})
