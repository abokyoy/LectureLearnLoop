# -*- coding: utf-8 -*-
"""课堂板书记入课件库（黑板两段式版式轮 2026-11-05）。

架构收敛：不新建课件表——课堂归档课复用微课那两张表
- micro_courses：source_type='live'、course_key=黑板的 lesson_key（^[0-9a-f]{16}$）
- micro_scenes ：scene_type='board'、content_json={title, caption, image_rel, plot_spec}

adopt（接备好的课来上）时 lesson_key = 备课程的 course_key（kp/error/prep 轨），
板书页往同一门课追加——ensure_course 对已存在的课不分轨都接受（见其 docstring）。

为什么不进 generating：在飞唯一索引 uq_mcourse_inflight 只管生成中的课，
课堂归档页是「来一张存一张」的增量写，状态直接 ready/partial，天然不与其互撞。

用户隔离：一切 SQL 带 user_id 双条件（同 routes_micro_course 纪律）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from pathlib import Path

from config import VAULT_DIR
from database.db_adapter import IntegrityError
from logger_module import debug_logger as log

_LESSON_KEY_RE = re.compile(r"^[0-9a-f]{16}$")
_CTRL_RE = re.compile(r"[^\w\u4e00-\u9fa5.-]")
_UID_RE = re.compile(r"^[\w\u4e00-\u9fa5-]{1,64}$")   # uid 只许字母数字下划线中文短横，堵掉 . 与分隔符
_IMG_MAX = 2 * 1024 * 1024      # 单页 PNG 上限（base64 上传侧同闸）
_PAGES_MAX = 40                 # 一节课件页上限（与黑板 MAX_ITEMS 同量级）
_PLOT_JSON_MAX = 200_000        # 单页 plot_json 上限（字符）：正常绘图契约带采样点，实测几 KB 量级
_COURSE_STATUS = ("ready", "partial")
_SLIDE_NAME_RE = re.compile(r"^slide_\d{3}(_\d+)?\.png$")   # 去重取名的格式闸（防 image_rel 被脏数据带出目录）


def _db():
    from routes_knowledge import get_kms
    return get_kms().db_manager.get_connection()


def valid_key(lesson_key) -> bool:
    return bool(lesson_key) and bool(_LESSON_KEY_RE.match(str(lesson_key)))


def valid_uid(uid) -> bool:
    """uid 参与磁盘路径拼接，必须先过字符闸（堵 .. 与分隔符穿越）。"""
    return bool(uid) and bool(_UID_RE.match(str(uid)))


def _lesson_dir(uid: str, lesson_key: str) -> Path | None:
    """课件落盘目录 vault/<uid>/课件/<lesson_key>/；键或 uid 非法 → None（防路径穿越）。"""
    if not valid_key(lesson_key) or not valid_uid(uid):
        return None
    root = (VAULT_DIR / str(uid) / "课件").resolve()
    p = (root / str(lesson_key)).resolve(strict=False)
    if root != p.parent:
        return None
    return p


def _now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def get_course(uid: str, lesson_key: str) -> dict | None:
    if not valid_key(lesson_key):
        return None
    with _db() as conn:
        row = conn.execute(
            "SELECT id, course_key, title, source_type, source_ref, status, export_rel "
            "FROM micro_courses WHERE course_key = ? AND user_id = ?",
            (lesson_key, uid)).fetchone()
    if row is None:
        return None
    return {"id": row[0], "course_key": row[1], "title": row[2] or "",
            "source_type": row[3], "source_ref": row[4] or "", "status": row[5],
            "export_rel": row[6] if len(row) > 6 else ""}


def ensure_course(uid: str, lesson_key: str, title: str = "",
                  source_error_id: str | None = None,
                  course_lesson_id=None) -> dict:
    """幂等建课：存在即回行，不存在按 live 建档（status=ready，绝不进 generating）。

    已存在的课不管是哪一轨建的（live/kp/error/prep）都接受：「接老师备好的课来上」
    （/api/board/adopt）就是把备课课的 course_key 交给上板链路，课堂板书页往同一门课
    追加 scene_type='board' 页——同表同页，导出与浏览逻辑天然共用（用户裁定「课件入库」）。

    course_lesson_id（画图硬纪律轮 2026-11-18）：从课程页「让 AI 老师讲课」开的课，
    建课时把目标导向课文 id 记进 source_ref，让课文页能回查这堂课的历史课件。"""
    if not valid_key(lesson_key):
        return {"success": False, "error": "课件键非法（要 16 位小写十六进制）"}
    exist = get_course(uid, lesson_key)
    if exist:
        return {"success": True, "course": exist, "created": False}
    ref_obj = {"origin": "blackboard", "error_ids": [source_error_id]
               if source_error_id else []}
    if course_lesson_id:
        ref_obj["course_lesson_id"] = str(course_lesson_id)
    ref = json.dumps(ref_obj, ensure_ascii=False)
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO micro_courses (course_key, user_id, subject_name, title, "
                "source_type, source_ref, status) "
                "VALUES (?, ?, ?, ?, 'live', ?, 'ready')",
                (lesson_key, uid, "课堂", (title or "")[:60], ref))
    except IntegrityError:
        # 并发首张页同时建课：回读已存在的行即可（course_key UNIQUE 兜底）
        exist = get_course(uid, lesson_key)
        if not exist:
            return {"success": False, "error": "建课失败"}
        return {"success": True, "course": exist, "created": False}
    log.log("xz_board", "lesson_course", "success",
            {"uid": uid, "lesson_key": lesson_key})
    return {"success": True, "course": get_course(uid, lesson_key), "created": True}


def _check_image(image_bytes) -> str:
    """图片入口闸（建课前先校，非法上传不留脏课）。返回错误串，空＝通过。"""
    if not image_bytes:
        return "空图片数据"
    if len(image_bytes) > _IMG_MAX:
        return f"单页图片超限（{len(image_bytes)} > {_IMG_MAX} 字节），请降低分辨率重拍"
    if image_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        return "只收 PNG 数据"
    return ""


def save_slide_image(uid: str, lesson_key: str, seq: int, image_bytes: bytes) -> dict:
    """把一页 PNG 落到课件目录，返回 {rel, path}。同名冲突用序号后缀排他（同 vault 截图口径）。"""
    d = _lesson_dir(uid, lesson_key)
    if d is None:
        return {"success": False, "error": "课件键非法"}
    err = _check_image(image_bytes)
    if err:
        return {"success": False, "error": err}
    try:
        d.mkdir(parents=True, exist_ok=True)
        stem = f"slide_{int(seq):03d}"
        for i in range(1000):
            name = f"{stem}.png" if i == 0 else f"{stem}_{i + 1}.png"
            try:
                with open(d / name, "xb") as f:
                    f.write(image_bytes)
                return {"success": True, "rel": f"课件/{lesson_key}/{name}",
                        "path": str(d / name)}
            except FileExistsError:
                continue
        return {"success": False, "error": "课件目录序号冲突过多"}
    except Exception as e:  # noqa: BLE001
        log.log_error("xz_board", "lesson_image_save_failed", str(e))
        return {"success": False, "error": f"课件图片保存失败: {e}"}


def _dedup_latest(course_id, uid: str, lesson_key: str, title: str,
                  caption: str, digest: str, n: int) -> dict | None:
    """内容级去重闸（方案 A，k-NN 课事故 2026-11-07）：最新 board 页标题/讲稿/图字节
    sha256 三者全同 → 幂等返回已有页号；否则 None（照常存新页）。

    多前端实例并发下课会把同一 outbox 页重复上传——seq 防撞只错开页序，
    挡不住双页（课件里「板书内容重复两次」）。只比最新一页，不做历史全量扫描：
    重复源自并发双写，必然落在相邻的最新页上。

    注：返回的 pages 是全课场景数 COUNT(1)（adopt 轨含 explain 页），与 board 页的
    seq 口径不同，仅供前端 pagesDone 进度展示，不当页号用。
    """
    with _db() as conn:
        top = conn.execute(
            "SELECT seq, content_json FROM micro_scenes "
            "WHERE course_id = ? AND scene_type = 'board' "
            "ORDER BY seq DESC LIMIT 1", (course_id,)).fetchone()
    if not top:
        return None
    try:
        prev = json.loads(top[1] or "{}")
    except (TypeError, ValueError):
        prev = {}
    if ((prev.get("title") or "") != title
            or (prev.get("caption") or "") != caption
            or not prev.get("image_rel")):
        return None
    d = _lesson_dir(uid, lesson_key)
    name = str(prev["image_rel"]).rsplit("/", 1)[-1]
    if d is None or not _SLIDE_NAME_RE.match(name):
        return None    # 格式闸：目录不合法或文件名不像本页序号的截图 → 不去重
    try:
        fp = d / name
        if fp.is_file() and hashlib.sha256(fp.read_bytes()).hexdigest() == digest:
            log.log("xz_board", "lesson_slide_dedup", "success",
                    {"uid": uid, "lesson_key": lesson_key, "seq": int(top[0])})
            return {"success": True, "seq": int(top[0]),
                    "image_rel": prev["image_rel"],
                    "pages": int(n or 0), "deduped": True}
    except OSError:
        pass    # 读不到旧文件就不去重，照常存新页
    return None


def append_slide(uid: str, lesson_key: str, plot_spec, caption: str,
                 image_bytes: bytes, title: str = "",
                 source_error_id: str | None = None,
                 course_lesson_id=None) -> dict:
    """一页定稿课件入库：先验图再落 PNG，再挂 micro_scenes 行（seq=max+1，撞车重试）。
    course_lesson_id 透传给 ensure_course（首张页建课时记归属，后续页不覆写）。"""
    err = _check_image(image_bytes)
    if err:
        return {"success": False, "error": err}
    if not valid_uid(uid) or not valid_key(lesson_key):
        return {"success": False, "error": "课件键或用户非法"}
    # plot_json 是浏览器直写 micro_scenes.content_json 的唯一字段，服务端必须有闸：
    # 非对象直接丢空（不阻断归档），超长拒收（挡刷屏式 payload，正常契约远在此线以下）。
    if plot_spec is not None and not isinstance(plot_spec, (dict, list)):
        plot_spec = None
    if isinstance(plot_spec, (dict, list)):
        try:
            pj_len = len(json.dumps(plot_spec, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            plot_spec = None
            pj_len = 0
        if pj_len > _PLOT_JSON_MAX:
            return {"success": False, "error": f"plot_json 超限（{pj_len} > {_PLOT_JSON_MAX} 字符）"}
    c = ensure_course(uid, lesson_key, title=title, source_error_id=source_error_id,
                      course_lesson_id=course_lesson_id)
    if not c.get("success"):
        return c
    course = c["course"]
    caption = (caption or "").strip()[:1200]
    title = (title or "").strip()[:60]
    with _db() as conn:
        n = conn.execute("SELECT COUNT(1) FROM micro_scenes WHERE course_id = ?",
                         (course["id"],)).fetchone()[0]
    if int(n or 0) >= _PAGES_MAX:
        return {"success": False, "error": f"本课课件页已达上限 {_PAGES_MAX} 页"}
    # 内容级去重闸：同图同文重复上传 → 幂等返回已有页，不写文件不插行
    digest = hashlib.sha256(image_bytes).hexdigest()
    dup = _dedup_latest(course["id"], uid, lesson_key, title, caption, digest, n)
    if dup:
        return dup
    seq_err = ""
    for attempt in range(3):
        seq = int(n or 0) + 1
        img = save_slide_image(uid, lesson_key, seq, image_bytes)
        if not img.get("success"):
            return img
        content = json.dumps({"title": title, "caption": caption,
                              "image_rel": img["rel"],
                              "plot_spec": plot_spec if isinstance(plot_spec, (dict, list)) else None},
                             ensure_ascii=False)
        try:
            with _db() as conn:
                conn.execute(
                    "INSERT INTO micro_scenes (course_id, seq, scene_type, title, "
                    "content_json, status) VALUES (?, ?, 'board', ?, ?, 'done')",
                    (course["id"], seq, title, content))
            log.log("xz_board", "lesson_slide", "success",
                    {"uid": uid, "lesson_key": lesson_key, "seq": seq,
                     "bytes": len(image_bytes)})
            return {"success": True, "seq": seq, "image_rel": img["rel"],
                    "pages": int(n or 0) + 1}
        except IntegrityError as e:
            # 并发上传撞 UNIQUE(course_id, seq)：重算 seq 再试。重试前先回跑去重闸
            # 闭环 TOCTOU：对手方刚插成功时，本页就是它的重复，幂等返回不再双存。
            seq_err = str(e)
            with _db() as conn:
                n = conn.execute("SELECT COUNT(1) FROM micro_scenes WHERE course_id = ?",
                                 (course["id"],)).fetchone()[0]
            dup = _dedup_latest(course["id"], uid, lesson_key, title, caption, digest, n)
            if dup:
                return dup
    log.log_error("xz_board", "lesson_slide_seq_conflict", seq_err)
    return {"success": False, "error": "页序冲突，请稍后重试"}


def list_slides(uid: str, lesson_key: str) -> list[dict]:
    """本课课件页（正序）：{seq, title, caption, image_rel, image_path, plot_spec}。"""
    course = get_course(uid, lesson_key)
    if not course:
        return []
    out = []
    with _db() as conn:
        rows = conn.execute(
            "SELECT seq, title, content_json FROM micro_scenes "
            "WHERE course_id = ? AND scene_type = 'board' ORDER BY seq",
            (course["id"],)).fetchall()
    for r in rows:
        try:
            c = json.loads(r[2] or "{}")
        except (ValueError, TypeError):
            c = {}
        rel = c.get("image_rel") or ""
        p = (VAULT_DIR / uid / rel) if rel else None
        out.append({"seq": r[0], "title": r[1] or c.get("title") or "",
                    "caption": c.get("caption") or "", "image_rel": rel,
                    "image_path": str(p) if p else "",
                    "has_image": bool(p and p.is_file()),
                    "plot_spec": c.get("plot_spec")})
    return out


def list_lessons(uid: str, limit: int = 20) -> list[dict]:
    """本账号的课堂课件列表（含备课产物）：{lesson_key, title, pages, status, updated_time}。"""
    with _db() as conn:
        rows = conn.execute(
            "SELECT course_key, title, status, export_rel, updated_time, source_type, "
            "(SELECT COUNT(1) FROM micro_scenes s WHERE s.course_id = c.id) "
            "FROM micro_courses c WHERE user_id = ? AND source_type IN ('live', 'kp', 'error', 'prep') "
            "ORDER BY updated_time DESC, id DESC LIMIT ?",
            (uid, int(limit))).fetchall()
    return [{"lesson_key": r[0], "course_key": r[0], "title": r[1] or "",
             "status": r[2], "export_rel": r[3] or "", "updated_time": r[4] or "",
             "source_type": r[5], "pages": int(r[6] or 0)} for r in rows]


def list_preps(uid: str, limit: int = 8, only_ready: bool = True) -> list[dict]:
    """备课清单（备课三轨 kp/error/prep，不含当堂归档 live）。

    only_ready=True（默认）只回已有页的课：供 lesson_list_preps 接单与黑板页
    「已备好一节课」提示条——生成中的课还没页，接了会空对空；且板页追加与
    大纲逐页插页共用 UNIQUE(course_id, seq)，生成中接单会撞页序。
    only_ready=False 连生成中一起回（工具返回里的「在备课件清单状态行」用）。"""
    sql = ("SELECT course_key, title, status, updated_time, source_type, "
           "(SELECT COUNT(1) FROM micro_scenes s WHERE s.course_id = c.id) "
           "FROM micro_courses c WHERE user_id = ? AND source_type IN ('kp', 'error', 'prep') ")
    if only_ready:
        sql += "AND c.status IN ('ready', 'partial') "
    sql += "ORDER BY c.updated_time DESC, c.id DESC LIMIT ?"
    with _db() as conn:
        rows = conn.execute(sql, (uid, int(limit))).fetchall()
    out = [{"lesson_key": r[0], "course_key": r[0], "title": r[1] or "",
            "status": r[2], "updated_time": r[3] or "", "source_type": r[4],
            "pages": int(r[5] or 0)} for r in rows]
    return [o for o in out if o["pages"] > 0] if only_ready else out


def close_course(uid: str, lesson_key: str, title: str = "") -> dict:
    """收课：补标题并刷新 updated_time（归档课状态在建课时已定，这里只做收尾留痕）。"""
    course = get_course(uid, lesson_key)
    if not course:
        return {"success": False, "error": "本课还没有课件页"}
    title = (title or "").strip()[:60] or course["title"]
    with _db() as conn:
        conn.execute(
            "UPDATE micro_courses SET title = ?, updated_time = ? "
            "WHERE course_key = ? AND user_id = ?",
            (title, _now(), lesson_key, uid))
    log.log("xz_board", "lesson_close", "success",
            {"uid": uid, "lesson_key": lesson_key, "title": title})
    return {"success": True, "title": title,
            "pages": len(list_slides(uid, lesson_key))}


def set_export_rel(uid: str, lesson_key: str, rel: str) -> None:
    """导出文件落库引用（幂等覆盖，供课件抽屉直接下载同一份）。"""
    with _db() as conn:
        conn.execute("UPDATE micro_courses SET export_rel = ?, updated_time = ? "
                     "WHERE course_key = ? AND user_id = ?",
                     (rel, _now(), lesson_key, uid))


def find_live_key_for_error(uid: str, error_id: str) -> str | None:
    """某错题是否已有课堂课件（备课入口/上课续档用，取最近一课的键）。"""
    if not error_id:
        return None
    with _db() as conn:
        row = conn.execute(
            "SELECT course_key FROM micro_courses WHERE user_id = ? AND source_type = 'live' "
            "AND source_ref LIKE ? ORDER BY updated_time DESC, id DESC LIMIT 1",
            (uid, f'%"{error_id}"%')).fetchone()
    return row[0] if row else None


def new_lesson_key() -> str:
    return uuid.uuid4().hex[:16]


# 建课 ref 写入用 json.dumps 默认分隔符（': ' 冒号后带空格），查询模式必须同格式；
# 键后跟 ',' 或 '}' 两种闭包形态都匹配，避免课文 id 前缀撞号（12 误中 123）
_CL_REF_PAT = '"course_lesson_id": "%s"'


def list_lesson_courses(uid: str, course_lesson_id, limit: int = 10) -> list[dict]:
    """某堂目标导向课文的历史课件（画图硬纪律轮 2026-11-18，课程页上课历史数据源）：
    按建课时记进 source_ref 的 course_lesson_id 匹配，新课在前；只回有页的课。"""
    lid = str(course_lesson_id or "").strip()
    if not lid.isdigit():
        return []
    core = _CL_REF_PAT % lid
    with _db() as conn:
        rows = conn.execute(
            "SELECT course_key, title, status, export_rel, updated_time, "
            "(SELECT COUNT(1) FROM micro_scenes s WHERE s.course_id = c.id) "
            "FROM micro_courses c WHERE user_id = ? AND source_type = 'live' "
            "AND (source_ref LIKE ? OR source_ref LIKE ?) "
            "ORDER BY updated_time DESC, id DESC LIMIT ?",
            (uid, '%' + core + ',%', '%' + core + '}%', int(limit))).fetchall()
    return [{"lesson_key": r[0], "title": r[1] or "", "status": r[2],
             "export_rel": r[3] or "", "updated_time": r[4] or "",
             "pages": int(r[5] or 0)} for r in rows if int(r[5] or 0) > 0]
