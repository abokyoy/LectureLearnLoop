"""
P2 桥方法兼容层后端蓝图 —— 规格文档《2026-09-27-桥方法兼容层规格.md》中的 B 类端点。

设计原则：
- 响应统一 {success: bool, data|error}，`data` 内放置与旧 Qt 桥返回值同构的载荷，
  前端兼容层（static/js/api.js）只需剥壳即可 1:1 还原 callback 值；
- vault 路径接受两种形态：服务端绝对路径（嵌套树返回的 path）或相对 root 的路径，
  一律校验必须位于当前用户 vault root 内（多用户隔离，P1 语义延续）；
- 科目/提取/确认等已有端点不在此重复，见 routes_knowledge.py。
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import shutil
from pathlib import Path

from flask import Blueprint, g, jsonify, request

from auth import require_auth
from config import DATA_DIR, VAULT_DIR, load_config, save_runtime_config
from logger_module import debug_logger as log
import credits_service as cr
from routes_knowledge import _ok, _err, get_kms, _user_vault_root

bridge_bp = Blueprint("bridge", __name__)

# ---------------------------------------------------------------- 路径工具

_MD_EXT = {".md", ".markdown", ".txt"}
_IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
}


def _bridge_path(user_id: str, raw: str) -> Path | None:
    """把桥方法传入的路径解析到用户 vault root 内；非法返回 None。

    兼容三种形态（与旧 Qt 行为对齐）：
    - "vault" / "vault\\子目录" / "vault/xxx.md"（Qt 的 CWD 相对写法）；
    - 服务端绝对路径（嵌套树返回后原样传回）；
    - 相对 root 的路径（"子目录/xxx.md"）。
    """
    if not raw:
        return None
    root = _user_vault_root(user_id)
    raw = raw.replace("/", "\\") if "\\" in raw else raw
    p = Path(raw)
    if p.is_absolute():
        target = p.resolve()
    else:
        # 去掉 Qt 风格的 "vault" 首段
        parts = list(p.parts)
        if parts and parts[0].lower() == "vault":
            parts = parts[1:]
        target = (root.joinpath(*parts)).resolve() if parts else root.resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _rel_to_root(target: Path, user_id: str) -> str:
    root = _user_vault_root(user_id).resolve()
    return str(target.relative_to(root))


def _note_uuid_for_path(user_id: str, file_path: str) -> tuple[int | None, str | None]:
    """find-or-create：按文件路径登记 notes 记录并回读 uuid（对齐 Qt _findOrCreateNoteRecord）。"""
    p = _bridge_path(user_id, file_path)
    if p is None:
        return None, None
    kms = get_kms()
    note_id = kms.register_note(file_name=p.name, file_path=str(p), user_id=user_id)
    if note_id is None:
        return None, None
    conn = kms.db_manager.get_connection()
    try:
        row = conn.execute("SELECT note_uuid FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id)).fetchone()
    finally:
        conn.close()
    return note_id, (row[0] if row else None)


# ---------------------------------------------------------------- 一、文件树 / vault 操作

@bridge_bp.route("/api/vault/tree-nested", methods=["GET"])
@require_auth
def vault_tree_nested():
    """getFileStructure：嵌套树（name/type/path/level/children|is_markdown/extension）。"""

    def scan(directory: Path, level: int):
        items = []
        try:
            entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), str(e).lower()))
        except OSError:
            return items
        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir():
                items.append({
                    "name": e.name, "type": "folder", "path": str(e), "level": level,
                    "children": scan(e, level + 1),
                })
            else:
                ext = e.suffix.lower()
                items.append({
                    "name": e.name, "type": "file", "path": str(e), "level": level,
                    "is_markdown": ext in _MD_EXT, "extension": ext,
                })
        return items

    return _ok(scan(_user_vault_root(g.user_id), 0))


@bridge_bp.route("/api/vault/note", methods=["POST"])
@require_auth
def vault_create_note():
    """createNewNote：返回纯文件名（如 "新建笔记1.md"）。"""
    body = request.get_json(silent=True) or {}
    folder = _bridge_path(g.user_id, body.get("folder_path") or "vault") or _user_vault_root(g.user_id)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        counter = 1
        while (folder / f"新建笔记{counter}.md").exists():
            counter += 1
        name = f"新建笔记{counter}.md"
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        (folder / name).write_text(
            f"# 新建笔记\n\n## 概述\n\n在这里输入概述...\n\n## 内容\n\n在这里输入内容...\n\n创建时间: {now}\n",
            encoding="utf-8",
        )
        return _ok(name)
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "create_note_failed", str(e))
        return _ok("")  # Qt 语义：失败返回空串而非报错


@bridge_bp.route("/api/vault/folder", methods=["POST"])
@require_auth
def vault_create_folder():
    """createNewFolder：返回纯文件夹名（如 "新文件夹1"）。"""
    body = request.get_json(silent=True) or {}
    parent = _bridge_path(g.user_id, body.get("parent_path") or "vault") or _user_vault_root(g.user_id)
    try:
        parent.mkdir(parents=True, exist_ok=True)
        counter = 1
        while (parent / f"新文件夹{counter}").exists():
            counter += 1
        name = f"新文件夹{counter}"
        (parent / name).mkdir()
        return _ok(name)
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "create_folder_failed", str(e))
        return _ok("")


@bridge_bp.route("/api/vault/rename", methods=["POST"])
@require_auth
def vault_rename():
    """renameFileOrFolder：返回 bool。"""
    body = request.get_json(silent=True) or {}
    old = _bridge_path(g.user_id, body.get("old_path") or "")
    new_name = (body.get("new_name") or "").strip()
    if old is None or not new_name or not old.exists():
        return _ok(False)
    new = old.parent / new_name
    if new.exists():
        return _ok(False)
    try:
        old.rename(new)
        return _ok(new.exists() and not old.exists())
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "rename_failed", str(e))
        return _ok(False)


@bridge_bp.route("/api/vault/move", methods=["POST"])
@require_auth
def vault_move():
    """moveFileOrFolder：返回 bool。"""
    body = request.get_json(silent=True) or {}
    src = _bridge_path(g.user_id, body.get("source_path") or "")
    dst_dir = _bridge_path(g.user_id, body.get("target_folder") or "")
    if src is None or dst_dir is None or not src.exists():
        return _ok(False)
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        if dst.exists():
            return _ok(False)
        shutil.move(str(src), str(dst))
        return _ok(dst.exists() and not src.exists())
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "move_failed", str(e))
        return _ok(False)


@bridge_bp.route("/api/vault/delete", methods=["POST"])
@require_auth
def vault_delete():
    """deleteFileOrFolder：返回 bool；目录递归删除。"""
    body = request.get_json(silent=True) or {}
    target = _bridge_path(g.user_id, body.get("path") or "")
    if target is None or not target.exists():
        return _ok(False)
    # 拒绝删除 root 本身
    if target == _user_vault_root(g.user_id).resolve():
        return _ok(False)
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return _ok(True)
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "delete_failed", str(e))
        return _ok(False)


@bridge_bp.route("/api/vault/copy", methods=["POST"])
@require_auth
def vault_copy():
    """copyFileOrFolder（桥类未定义但页面调用）：补齐实现，返回 bool。"""
    body = request.get_json(silent=True) or {}
    src = _bridge_path(g.user_id, body.get("source_path") or "")
    dst_dir = _bridge_path(g.user_id, body.get("target_folder") or "")
    if src is None or dst_dir is None or not src.exists():
        return _ok(False)
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        if dst.exists():
            stem, suf = dst.stem, dst.suffix
            i = 1
            while (dst_dir / f"{stem}_{i}{suf}").exists():
                i += 1
            dst = dst_dir / f"{stem}_{i}{suf}"
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return _ok(True)
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "copy_failed", str(e))
        return _ok(False)


@bridge_bp.route("/api/vault/image", methods=["GET"])
@require_auth
def vault_image_base64():
    """getImageAsBase64：{dataUrl, mimeType, size}；失败时 error 文案对齐 Qt。"""
    raw = request.args.get("path") or ""
    target = _bridge_path(g.user_id, raw)
    if target is None:
        return jsonify({"success": False, "data": {"error": "非法路径"}})
    if not target.is_file():
        return jsonify({"success": False, "data": {"error": "图片文件不存在"}})
    try:
        data = target.read_bytes()
        mime = _IMAGE_MIME.get(target.suffix.lower(), "image/png")
        b64 = base64.b64encode(data).decode("ascii")
        return _ok({"success": True, "dataUrl": f"data:{mime};base64,{b64}", "mimeType": mime, "size": len(data)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"success": False, "data": {"error": f"图片转换失败: {e}"}})


@bridge_bp.route("/api/vault/rawfile", methods=["GET"])
@require_auth
def vault_read_abs():
    """loadMarkdownRaw：接受嵌套树返回的绝对路径；失败时前端剥出空串。"""
    target = _bridge_path(g.user_id, request.args.get("path") or "")
    if target is None or not target.is_file():
        return _ok("")
    return _ok(target.read_text(encoding="utf-8", errors="replace"))


@bridge_bp.route("/api/vault/rawfile", methods=["PUT"])
@require_auth
def vault_write_abs():
    """saveMarkdownFile/save_file：文件写入；MD 类同步正文入库（二期，库为轮询权威源）；返回 bool。"""
    body = request.get_json(silent=True) or {}
    target = _bridge_path(g.user_id, body.get("path") or "")
    if target is None:
        return _ok(False)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        content = body.get("content") or ""
        target.write_text(content, encoding="utf-8")
        if target.suffix.lower() in _MD_EXT:
            r = get_kms().upsert_note_content(g.user_id, str(target), content)
            if r.get("error"):
                log.log_error("bridge", "rawfile_db_sync_failed", r["error"])
        return _ok(target.exists())
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "rawfile_write_failed", str(e))
        return _ok(False)


# ---------------------------------------------------------------- 一·五、悬浮窗截图落库

@bridge_bp.route("/api/vault/screenshot", methods=["POST"])
@require_auth
def vault_screenshot():
    """悬浮窗框选截屏：保存 base64 PNG 到用户 vault 的 截图/ 目录。

    body: {image_b64: str(不含或含 data: 前缀), name?: str, note_path?: str}
    - 保存图片文件；若给了 note_path 且存在，则在笔记末尾追加 ![](相对路径) 引用。
    返回 {success, data:{path, rel, markdown}}。
    """
    body = request.get_json(silent=True) or {}
    b64 = body.get("image_b64") or ""
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    if not b64:
        return _ok({"success": False, "error": "空图片数据"})
    root = _user_vault_root(g.user_id)
    shot_dir = root / "截图"
    try:
        shot_dir.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(b64)
        name = re.sub(r"[^\w\u4e00-\u9fa5.-]", "_", body.get("name") or "")
        if not name:
            name = f"截屏_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        if not name.lower().endswith(".png"):
            name += ".png"
        target = shot_dir / name
        target.write_bytes(raw)
        rel = f"截图/{name}"
        markdown = f"![截屏]({rel})"
        # 可选：追加到指定笔记
        note_path = body.get("note_path")
        appended = False
        if note_path:
            np = _bridge_path(g.user_id, note_path)
            if np and np.is_file():
                try:
                    cur = np.read_text(encoding="utf-8", errors="replace")
                    new_text = cur.rstrip() + "\n\n" + markdown + "\n"
                    np.write_text(new_text, encoding="utf-8")
                    appended = True
                    # 二期：追加后同步正文入库，使主面板轮询能实时看到截图嵌入
                    r = get_kms().upsert_note_content(g.user_id, str(np), new_text)
                    if r.get("error"):
                        log.log_error("bridge", "screenshot_db_sync_failed", r["error"])
                except Exception as e:  # noqa: BLE001
                    log.log_error("bridge", "screenshot_append_failed", str(e))
        return _ok({"success": True, "path": str(target), "rel": rel,
                    "markdown": markdown, "appended_to_note": appended})
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "screenshot_save_failed", str(e))
        return _ok({"success": False, "error": f"截图保存失败: {e}"})


# ---------------------------------------------------------------- 二、知识提取 / 相似 / 合并 / 批量

@bridge_bp.route("/api/knowledge/extract-file", methods=["POST"])
@require_auth
def extract_from_file():
    """extractKnowledgePoints(file_path)：读文件→提取→规整为四键结构。"""
    body = request.get_json(silent=True) or {}
    target = _bridge_path(g.user_id, body.get("file_path") or "")
    if target is None or not target.is_file():
        return _ok({"success": False, "error": "文件不存在"})
    content = target.read_text(encoding="utf-8", errors="replace").strip()
    if not content:
        return _ok({"success": False, "error": "文件内容为空"})
    subject = (body.get("subject") or "通用学科").strip()
    try:
        result = get_kms().extract_knowledge_points(subject, content, user_id=g.user_id)
    except cr.InsufficientCreditsError as e:
        return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "extract_file_failed", str(e))
        return _err(f"知识管理模块不可用: {e}", 500)
    if not result.get("success"):
        return _ok({"success": False, "error": result.get("error", "提取失败")})
    points = []
    for p in result.get("processed_points", []):
        if not isinstance(p, dict):
            continue
        # BUGFIX(2026-09-27): processed_points 元素是包装结构 {extracted_point, similar_points, match_status}，
        # 真实字段（concept_name/core_definition）在 extracted_point 内层；直接读包装层会使前端列表全空白。
        ep = p.get("extracted_point")
        if not isinstance(ep, dict):
            ep = p
        points.append({
            "name": (ep.get("point_name") or ep.get("concept_name") or ep.get("name") or "").strip(),
            "description": (ep.get("core_description") or ep.get("core_definition") or ep.get("description") or "").strip(),
            "category": ep.get("category") or "核心概念",
            "importance": ep.get("importance") or "中等",
            "match_status": p.get("match_status") or "",
            "similar_count": len(p.get("similar_points") or []),
        })
    points = [pt for pt in points if pt["name"]]
    if not points:
        return _ok({"success": False, "error": "未能提取到有效知识点，请检查笔记内容后重试"})
    return _ok({"success": True, "knowledge_points": points, "total_count": len(points),
                **cr.billing_for_response()})


@bridge_bp.route("/api/knowledge/similar", methods=["POST"])
@require_auth
def similar_points():
    """findSimilarKnowledgePoints：顶层数组。"""
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject") or "").strip()
    point_name = (body.get("point_name") or (body.get("point") or {}).get("name") or "").strip()
    limit = int(body.get("limit") or 10)
    kms = get_kms()
    try:
        from similarity_matcher import rank_matches
        all_points = kms.get_knowledge_points_by_subject(subject, user_id=g.user_id)
        if not all_points:
            return _ok([])
        ranked = rank_matches(question=point_name, knowledge_points=all_points,
                              cfg=load_config(), top_k=limit, min_score=0.0)
        by_id = {p.get("id"): p for p in all_points}
        out = []
        for r in ranked:
            src = by_id.get(r.get("id"), {})
            out.append({
                "id": r.get("id"),
                "name": src.get("point_name") or r.get("point_name") or "",
                "description": src.get("core_description") or src.get("description") or "",
                "similarity": float(r.get("score", 0.5)),
                "mastery_score": src.get("mastery_score", 50),
                "sources": kms.get_knowledge_point_sources(r.get("id"), user_id=g.user_id),
            })
        return _ok(out)
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "similar_failed", str(e))
        return _ok([])


@bridge_bp.route("/api/knowledge/merge", methods=["POST"])
@require_auth
def merge_point():
    """mergeKnowledgePoint：目标知识点存在则关联笔记并返回 updated_point。"""
    body = request.get_json(silent=True) or {}
    target_id = body.get("target_knowledge_id") or body.get("targetKnowledgeId")
    file_path = ((body.get("noteInfo") or {}).get("filePath")) or body.get("file_path") or ""
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        row = conn.execute(
            "SELECT id, subject_name, point_name, core_description, mastery_score "
            "FROM knowledge_points WHERE id = ? AND user_id = ?", (target_id, g.user_id)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return _ok({"success": False, "error": "目标知识点不存在"})
    _, note_uuid = _note_uuid_for_path(g.user_id, file_path)
    if note_uuid:
        kms.link_knowledge_point_to_note(int(row[0]), note_uuid, user_id=g.user_id)
    return _ok({
        "success": True,
        "message": "知识点合并成功",
        "merged_knowledge_id": row[0],
        "updated_point": {
            "id": row[0], "name": row[2], "description": row[3], "mastery_score": row[4],
            "sources": kms.get_knowledge_point_sources(int(row[0]), user_id=g.user_id),
        },
    })


@bridge_bp.route("/api/knowledge/point-new", methods=["POST"])
@require_auth
def create_point_new():
    """createNewKnowledgePoint：DB mastery_score=-1，返回体回填 50（Qt 语义）。"""
    body = request.get_json(silent=True) or {}
    point = body.get("point") or {}
    subject = (body.get("subject") or "通用学科").strip()
    file_path = ((body.get("noteInfo") or {}).get("filePath")) or body.get("file_path") or ""
    name = (point.get("name") or point.get("point_name") or "").strip()
    desc = (point.get("description") or point.get("core_description") or "").strip()
    if not name:
        return _ok({"success": False, "error": "知识点名称不能为空"})
    kms = get_kms()
    kms.add_subject(subject, user_id=g.user_id)
    _, note_uuid = _note_uuid_for_path(g.user_id, file_path) if file_path else (None, None)
    saved = kms.confirm_knowledge_points(
        [{"action": "new",
          "point_data": {"point_name": name, "core_description": desc, "mastery_score": -1},
          "subject_name": subject}],
        note_uuid=note_uuid, user_id=g.user_id,
    )
    if not saved:
        return _ok({"success": False, "error": "数据库保存失败"})
    kid = saved[0]
    return _ok({
        "success": True,
        "message": "新知识点创建成功",
        "knowledge_id": kid,
        "knowledge_point": {
            "id": kid, "name": name, "description": desc, "subject": subject,
            "mastery_score": 50,
            "sources": kms.get_knowledge_point_sources(kid, user_id=g.user_id),
        },
    })


@bridge_bp.route("/api/knowledge/batch-save", methods=["POST"])
@require_auth
def batch_save_points():
    """batchSaveKnowledgePoints：filePath → note_uuid find-or-create 后批量入库。

    四期修正（串写 bug 根因）：不再自动 add_subject 创建科目；subject 必须为用户
    已有科目，否则拒绝——避免旧流程硬编码“机器学习”被 auto-create 导致知识点重复写入意外科目。
    """
    body = request.get_json(silent=True) or {}
    file_path = body.get("filePath") or body.get("file_path") or ""
    subject = (body.get("subject") or "").strip()
    points = body.get("knowledgePoints") or body.get("knowledge_points") or []
    if not subject:
        return _ok({"success": False, "error": "必须指定科目（subject）"})
    kms = get_kms()
    if subject not in (kms.get_subjects(user_id=g.user_id) or []):
        return _ok({"success": False, "error": f"科目「{subject}」不存在，请先在科目管理创建"})
    _, note_uuid = _note_uuid_for_path(g.user_id, file_path)
    if not note_uuid:
        return _ok({"success": False, "error": "无法获取笔记UUID"})
    confirmations = [{
        "action": "new",
        "point_data": {
            "point_name": p.get("name") or p.get("point_name") or "",
            "core_description": p.get("description") or p.get("core_description") or "",
            "mastery_score": 50,
        },
        "subject_name": subject,
    } for p in points if isinstance(p, dict)]
    confirmations = [c for c in confirmations if c["point_data"]["point_name"]]
    saved = kms.confirm_knowledge_points(confirmations, note_uuid=note_uuid, user_id=g.user_id)
    return _ok({
        "success": True,
        "message": f"成功保存 {len(saved)} 个知识点",
        "saved_count": len(saved),
        "saved_ids": saved,
        "note_uuid": note_uuid,
    })


@bridge_bp.route("/api/notes/mapping", methods=["POST"])
@require_auth
def save_note_mapping():
    """saveNoteKnowledgeMapping：noteId 或缺省时按 filePath find-or-create。"""
    body = request.get_json(silent=True) or {}
    kms = get_kms()
    note_id = body.get("noteId")
    file_path = body.get("filePath") or body.get("file_path") or ""
    note_uuid = None
    if note_id:
        conn = kms.db_manager.get_connection()
        try:
            row = conn.execute("SELECT note_uuid FROM notes WHERE id = ? AND user_id = ?", (note_id, g.user_id)).fetchone()
            note_uuid = row[0] if row else None
        finally:
            conn.close()
    if note_uuid is None:
        _, note_uuid = _note_uuid_for_path(g.user_id, file_path)
    if not note_uuid:
        return _ok({"success": False, "error": "无法解析笔记记录"})
    points = body.get("processedPoints") or body.get("processed_points") or []
    saved = 0
    for p in points:
        pid = p.get("id") if isinstance(p, dict) else None
        if pid is None:
            continue
        if kms.link_knowledge_point_to_note(int(pid), note_uuid, user_id=g.user_id):
            saved += 1
    return _ok({
        "success": True,
        "message": f"笔记知识点映射保存成功，共保存 {saved} 个映射关系",
        "note_id": note_id, "saved_count": saved, "total_count": len(points),
    })


@bridge_bp.route("/api/notes/knowledge-points", methods=["GET"])
@require_auth
def note_knowledge_points():
    """getNoteKnowledgePoints(path)：顶层数组。"""
    raw = request.args.get("path") or ""
    target = _bridge_path(g.user_id, raw)
    if target is None:
        return _ok([])
    kms = get_kms()
    _, note_uuid = _note_uuid_for_path(g.user_id, str(target))
    if not note_uuid:
        return _ok([])
    conn = kms.db_manager.get_connection()
    try:
        rows = conn.execute(
            "SELECT kp.id, kp.point_name, kp.core_description, kp.subject_name, kp.mastery_score, "
            "kp.created_time FROM knowledge_points kp "
            "JOIN knowledge_point_sources kps ON kps.knowledge_point_id = kp.id "
            "WHERE kps.note_uuid = ?", (note_uuid,)
        ).fetchall()
    finally:
        conn.close()
    return _ok([
        {"id": r[0], "name": r[1], "description": r[2], "subject": r[3],
         "mastery_score": r[4] if r[4] is not None else 50, "created_time": r[5],
         "type": "existing"}
        for r in rows
    ])


# ---------------------------------------------------------------- 三、知识点详情 / 笔记 / 题目

@bridge_bp.route("/api/knowledge/points/<int:pid>/detail", methods=["GET"])
@require_auth
def point_detail(pid):
    """getKnowledgePointDetail：{detail:{...counts, recent_practices}}。"""
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        row = conn.execute(
            "SELECT id, point_name, core_description, mastery_score, subject_name, created_time "
            "FROM knowledge_points WHERE id = ? AND user_id = ?", (pid, g.user_id)
        ).fetchone()
        if not row:
            return _ok({"success": False, "error": "未找到该知识点"})
        error_count = conn.execute(
            "SELECT COUNT(*) FROM error_questions WHERE knowledge_point_id = ? AND user_id = ?",
            (pid, g.user_id)).fetchone()[0]
        favorite_count = conn.execute(
            "SELECT COUNT(*) FROM favorite_questions WHERE knowledge_point_id = ? AND user_id = ?",
            (pid, g.user_id)).fetchone()[0]
        notes_count = conn.execute(
            "SELECT COUNT(*) FROM knowledge_point_sources kps "
            "JOIN notes n ON n.note_uuid = kps.note_uuid "
            "WHERE kps.knowledge_point_id = ? AND n.user_id = ?", (pid, g.user_id)).fetchone()[0]
        practices = conn.execute(
            "SELECT question_content, user_answer, is_correct, practice_time "
            "FROM practice_records WHERE knowledge_point_id = ? AND user_id = ? "
            "ORDER BY practice_time DESC LIMIT 5", (pid, g.user_id)).fetchall()
    finally:
        conn.close()
    return _ok({"success": True, "detail": {
        "id": row[0], "name": row[1], "description": row[2], "mastery_score": row[3],
        "subject_name": row[4], "created_time": row[5],
        "error_count": error_count, "favorite_count": favorite_count, "notes_count": notes_count,
        "recent_practices": [
            {"question": q, "answer": a, "is_correct": bool(c), "time": t} for q, a, c, t in practices
        ],
    }})


@bridge_bp.route("/api/knowledge/points/<int:pid>/notes", methods=["GET"])
@require_auth
def point_notes(pid):
    """getKnowledgePointNotes：content 为占位串（Qt 原语义）。"""
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        exists = conn.execute(
            "SELECT 1 FROM knowledge_points WHERE id = ? AND user_id = ?", (pid, g.user_id)).fetchone()
        if not exists:
            return _ok({"success": False, "error": "未找到该知识点"})
        rows = conn.execute(
            "SELECT n.id, n.title, n.file_name, n.created_time, n.updated_time, kps.extraction_time "
            "FROM knowledge_point_sources kps JOIN notes n ON n.note_uuid = kps.note_uuid "
            "WHERE kps.knowledge_point_id = ? AND n.user_id = ? "
            "ORDER BY kps.extraction_time DESC LIMIT 5", (pid, g.user_id)).fetchall()
    finally:
        conn.close()
    return _ok({"success": True, "notes": [
        {"id": r[0], "title": r[1], "content": f"文件: {r[2]}",
         "created_time": r[3], "updated_time": r[4], "extraction_time": r[5]} for r in rows
    ]})


@bridge_bp.route("/api/notes/by-path", methods=["GET"])
@require_auth
def note_by_path():
    """按路径查笔记登记信息（兼容层解析 note_uuid 用）。"""
    raw = request.args.get("path") or ""
    target = _bridge_path(g.user_id, raw)
    if target is None:
        return _err("非法路径", 403)
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        row = conn.execute(
            "SELECT id, note_uuid, title FROM notes WHERE file_path = ? AND user_id = ?",
            (str(target), g.user_id)).fetchone()
    finally:
        conn.close()
    if not row:
        return _ok(None)
    return _ok({"note_id": row[0], "note_uuid": row[1], "title": row[2]})


@bridge_bp.route("/api/notes/<int:nid>/content", methods=["GET"])
@require_auth
def note_content(nid):
    """getNoteContent：正文超 1000 字符截断；关联知识点列表。"""
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        row = conn.execute(
            "SELECT id, title, file_name, file_path, created_time, updated_time "
            "FROM notes WHERE id = ? AND user_id = ?", (nid, g.user_id)).fetchone()
        if not row:
            return _ok({"success": False, "error": "未找到该笔记"})
        kps = conn.execute(
            "SELECT kp.id, kp.point_name, kps.extraction_time FROM knowledge_point_sources kps "
            "JOIN knowledge_points kp ON kp.id = kps.knowledge_point_id "
            "JOIN notes n ON n.note_uuid = kps.note_uuid "
            "WHERE n.id = ? AND n.user_id = ?", (nid, g.user_id)).fetchall()
    finally:
        conn.close()
    file_path = row[3]
    try:
        p = Path(file_path)
        content = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else "笔记文件不存在或路径无效"
    except Exception:  # noqa: BLE001
        content = "笔记文件不存在或路径无效"
    clipped = content if len(content) <= 1000 else content[:1000] + "..."
    return _ok({"success": True, "note": {
        "id": row[0], "title": row[1], "file_name": row[2], "file_path": file_path,
        "content": clipped, "content_length": len(content),
        "created_time": row[4], "updated_time": row[5],
        "related_knowledge_points": [
            {"id": k[0], "name": k[1], "extraction_time": k[2]} for k in kps
        ],
    }})


@bridge_bp.route("/api/knowledge/points/<int:pid>/questions", methods=["GET"])
@require_auth
def point_questions(pid):
    """getKnowledgePointQuestions：按题干聚合练习记录 + 收藏标记。"""
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        rows = conn.execute(
            "SELECT question_content, COUNT(*) AS practice_count, "
            "SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct_count, "
            "MAX(practice_time) AS last_time, "
            "(SELECT is_correct FROM practice_records p2 "
            " WHERE p2.knowledge_point_id = p1.knowledge_point_id "
            "   AND p2.question_content = p1.question_content AND p2.user_id = p1.user_id "
            " ORDER BY p2.practice_time DESC LIMIT 1) AS last_correct "
            "FROM practice_records p1 WHERE knowledge_point_id = ? AND user_id = ? "
            "GROUP BY question_content ORDER BY last_time DESC", (pid, g.user_id)).fetchall()
        favorites = {r[0] for r in conn.execute(
            "SELECT question_content FROM favorite_questions WHERE knowledge_point_id = ? AND user_id = ?",
            (pid, g.user_id)).fetchall()}
    finally:
        conn.close()

    def _qtype(text: str) -> str:
        if re.search(r"[A-D][.、）)]", text or "") or "选择" in (text or ""):
            return "选择题"
        if "_" in (text or "") or "（　）" in (text or "") or "填空" in (text or ""):
            return "填空题"
        return "简答题"

    out = []
    for content, practice_count, correct_count, last_time, last_correct in rows:
        correct_count = correct_count or 0
        rate = (correct_count / practice_count) if practice_count else 0
        out.append({
            "content": content,
            "type": _qtype(content),
            "practice_count": practice_count,
            "correct_count": correct_count,
            "mastery_stars": min(5, max(1, int(rate * 5) + 1)),
            "last_practice_time": last_time,
            "last_result": "正确" if last_correct else "错误",
            "is_favorite": content in favorites,
        })
    return _ok({"success": True, "questions": out})


# ---------------------------------------------------------------- 四、脑图保存 / 掌握度评估

@bridge_bp.route("/api/mindmap/save", methods=["POST"])
@require_auth
def mindmap_save():
    """saveMindmap：返回 bool。"""
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject_name") or "").strip()
    data = body.get("mindmap_data")
    if not subject or data is None:
        return _ok(False)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:  # noqa: BLE001
            return _ok(False)
    ok = get_kms().save_mindmap(subject, data, user_id=g.user_id)
    return _ok(bool(ok))


@bridge_bp.route("/api/knowledge/points/<int:pid>/assessment", methods=["POST"])
@require_auth
def mastery_assessment(pid):
    """submitMasteryAssessment：难度加权评分 → UPDATE mastery_score → 失效脑图缓存。"""
    body = request.get_json(silent=True) or {}
    questions = body.get("questions") or []
    answers = body.get("answers") or []
    if len(questions) != len(answers):
        return _ok({"success": False, "error": "题目和答案数量不匹配"})
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        row = conn.execute(
            "SELECT subject_name FROM knowledge_points WHERE id = ? AND user_id = ?",
            (pid, g.user_id)).fetchone()
        if not row:
            return _ok({"success": False, "error": "未找到该知识点"})
        subject = row[0]
        weights = {"容易": 1.0, "中等": 1.2, "困难": 1.5}
        total_w = 0.0
        earned_w = 0.0
        correct_count = 0
        detailed = []
        for i, (q, a) in enumerate(zip(questions, answers)):
            difficulty = q.get("difficulty") or "中等"
            w = weights.get(difficulty, 1.2)
            total_w += w
            user_ans = (a or "").strip()
            correct_ans = (q.get("correct_answer") or "").strip()
            is_correct = bool(user_ans) and user_ans.upper() == correct_ans.upper()
            if is_correct:
                earned_w += w
                correct_count += 1
            detailed.append({
                "question_index": i,
                "question": q.get("question", ""),
                "user_answer": user_ans,
                "correct_answer": correct_ans,
                "is_correct": is_correct,
                "difficulty": difficulty,
                "explanation": q.get("explanation", ""),
            })
        accuracy = (correct_count / len(questions)) if questions else 0.0
        mastery_score = int(round((earned_w / total_w) * 100)) if total_w else 0
        conn.execute(
            "UPDATE knowledge_points SET mastery_score = ?, updated_time = CURRENT_TIMESTAMP "
            "WHERE id = ? AND user_id = ?", (mastery_score, pid, g.user_id))
        conn.commit()
    finally:
        conn.close()
    # 掌握度已变化：失效该学科脑图缓存（下次访问按新分数重建）
    try:
        kms.clear_mindmap_cache(subject, user_id=g.user_id)
    except Exception:  # noqa: BLE001
        pass
    return _ok({
        "success": True, "mastery_score": mastery_score,
        "correct_count": correct_count, "total_count": len(questions),
        "accuracy": accuracy, "detailed_results": detailed,
    })


# ---------------------------------------------------------------- 五、配置 / LLM 测试 / 日志清理

# 设置页允许保存的非敏感键
_CONFIG_TEXT_KEYS = {
    "summary_mode", "whisper_language", "selected_audio_device_name",
    "deepseek_model", "deepseek_api_url", "ollama_model", "gemini_model", "qwen_model", "qwen_api_url",
}
_CONFIG_NUM_KEYS = {
    "auto_summary_interval", "auto_summary_max_chars", "manual_summary_max_chars",
    "selected_audio_device_index", "similarity_min_score",
}
_CONFIG_BOOL_KEYS = {"llm_call_logging_enabled"}


@bridge_bp.route("/api/config", methods=["PUT"])
@require_auth
def config_save():
    """saveConfig：bool 返回（Qt 语义）；掩码密钥值一律忽略（防覆盖）。"""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return _ok(False)
    updates: dict = {}
    for k, v in body.items():
        if k in _CONFIG_TEXT_KEYS and isinstance(v, str):
            updates[k] = v.strip()
        elif k in _CONFIG_NUM_KEYS:
            try:
                updates[k] = float(v) if isinstance(v, str) else v
            except (TypeError, ValueError):
                continue
        elif k in _CONFIG_BOOL_KEYS:
            updates[k] = bool(v)
        elif k in ("deepseek_api_key", "gemini_api_key", "qwen_api_key"):
            # 2026-09-28 积分系统：系统级密钥仅管理员可改（管理后台 /api/admin/llm-config），普通用户禁止经此端点写入
            if not cr.is_admin_user(g.user_id):
                continue
            # 含掩码字符（• 或 ***）说明未修改，跳过
            if isinstance(v, str) and v.strip() and "•" not in v and "***" not in v:
                updates[k] = v.strip()
    if not updates:
        return _ok(True)
    ok = save_runtime_config(updates)
    if ok and any(k.endswith("api_key") or k.endswith("model") or k.endswith("api_url") for k in updates):
        try:
            import llm_provider_factory
            llm_provider_factory.llm_factory.get_provider(force_reload=True)
        except Exception as e:  # noqa: BLE001
            log.log("bridge", "llm_reload_failed", status="warn", data={"error": str(e)})
    return _ok(ok)


@bridge_bp.route("/api/llm/test", methods=["POST"])
@require_auth
def llm_test():
    """testLLMConnection：纯文本返回（Qt 语义），文案分支保留。"""
    body = request.get_json(silent=True) or {}
    # 2026-09-28 积分系统：测试连接会真实调用系统 Key（微量 token），余额不足同样拦截；
    # 属只读探测不记扣分流水（成本可忽略，与 _call_legacy 同口径）
    _pre = cr.precheck(g.user_id)
    if not _pre["allowed"]:
        return _ok("⚠️ 积分不足，无法进行连接测试，请先充值")
    provider = (body.get("provider") or "").strip()
    cfg = load_config()
    current = cfg.get("llm_provider", "DeepSeek")
    if provider and provider != current:
        return _ok(
            f"⚠️ 配置不一致检测:\n📋 当前配置的提供商: {current}\n🔍 正在测试的提供商: {provider}\n"
            f"💡 建议: 请先保存配置或选择正确的提供商再测试"
        )
    try:
        from llm_provider_factory import test_llm_connection
        ok, message = test_llm_connection()
        model = cfg.get("deepseek_model", "")
        return _ok(f"{message}\n📋 当前配置: {current} (模型: {model})")
    except Exception as e:  # noqa: BLE001
        return _ok(f"❌ {current} 连接测试异常: {e}")


@bridge_bp.route("/api/llm/logs", methods=["DELETE"])
@require_auth
def llm_logs_clear():
    """clearLLMLogs：bool 返回。"""
    try:
        from llm_call_logger import llm_call_logger
        llm_call_logger.clear_records()
        return _ok(True)
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "clear_llm_logs_failed", str(e))
        return _ok(False)


# ---------------------------------------------------------------- 六、对话历史（按用户目录隔离）

_CONV_ID_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fa5]{1,80}$")


def _conv_dir(user_id: str) -> Path:
    d = DATA_DIR / "conversations" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


@bridge_bp.route("/api/conversations", methods=["POST"])
@require_auth
def conversation_save():
    """saveConversation：写 data/conversations/<user>/conversation_<id>.json。"""
    body = request.get_json(silent=True) or {}
    data = body.get("conversation_data") if "conversation_data" in body else body
    try:
        cid = str(data.get("id") or dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        if not _CONV_ID_RE.match(cid):
            return _err("非法对话ID", 400)
        data["id"] = cid
        data["timestamp"] = dt.datetime.now().isoformat()
        (_conv_dir(g.user_id) / f"conversation_{cid}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return _ok({"success": True, "message": "对话已保存", "id": cid})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": f"保存失败: {e}"})


@bridge_bp.route("/api/conversations", methods=["GET"])
@require_auth
def conversation_list():
    """loadConversationHistory：列表（timestamp 逆序，只含摘要字段）。"""
    try:
        out = []
        for f in _conv_dir(g.user_id).glob("conversation_*.json"):
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
                out.append({
                    "id": obj.get("id", f.stem.replace("conversation_", "")),
                    "timestamp": obj.get("timestamp", ""),
                    "title": obj.get("title", "未命名对话"),
                    "message_count": len(obj.get("conversation_history", []) or []),
                })
            except Exception:  # noqa: BLE001
                continue
        out.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
        return _ok({"success": True, "conversations": out})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": f"加载失败: {e}"})


@bridge_bp.route("/api/conversations/<cid>", methods=["GET"])
@require_auth
def conversation_get(cid):
    """loadConversationById：整个存储对象。"""
    if not _CONV_ID_RE.match(cid):
        return _err("非法对话ID", 400)
    f = _conv_dir(g.user_id) / f"conversation_{cid}.json"
    if not f.is_file():
        return _ok({"success": False, "error": "对话文件不存在"})
    try:
        obj = json.loads(f.read_text(encoding="utf-8"))
        return _ok({"success": True, "conversation": obj})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": f"加载失败: {e}"})


# ---------------------------------------------------------------- 七、练习历史（PracticeService，主库 user_id 列隔离）

_practice_svc = None


def _practice_service():
    """共享单例：PG 改造后不再每用户一库，隔离由服务层 user_id 参数保证。"""
    global _practice_svc
    if _practice_svc is None:
        from services.practice_service import PracticeService
        _practice_svc = PracticeService()
    return _practice_svc


@bridge_bp.route("/api/practice/history", methods=["GET"])
@require_auth
def practice_history_list():
    """getPracticeHistory：{practices:[...]}（含别名字段，原样保留）。"""
    result = _practice_service().get_practice_history_list(g.user_id, limit=50)
    return _ok(result)


@bridge_bp.route("/api/practice/history/<pid>", methods=["GET"])
@require_auth
def practice_history_detail(pid):
    """loadPracticeHistory：{practice:{...}}。"""
    result = _practice_service().load_practice_detail(g.user_id, pid)
    return _ok(result)


@bridge_bp.route("/api/practice/history", methods=["POST"])
@require_auth
def practice_history_save():
    """savePracticeHistory：status=submitted。"""
    body = request.get_json(silent=True) or {}
    result = _practice_service().save_practice_history(g.user_id, body)
    return _ok(result)


@bridge_bp.route("/api/practice/evaluation", methods=["POST"])
@require_auth
def practice_evaluation_save():
    """savePracticeEvaluation：完整数据 upsert，status=evaluated。"""
    body = request.get_json(silent=True) or {}
    result = _practice_service().save_complete_practice_data(g.user_id, body)
    return _ok(result)


@bridge_bp.route("/api/practice/history/<pid>/evaluation", methods=["PUT"])
@require_auth
def practice_evaluation_update(pid):
    """updatePracticeEvaluation：会话置 evaluated + 插评估记录。"""
    body = request.get_json(silent=True) or {}
    result = _practice_service().update_practice_evaluation(g.user_id, pid, body)
    return _ok(result)


# ---------------------------------------------------------------- 八、LLM 提示词端点（桥方法 1:1 语义）
#
# 提示词与本地 fallback 均照抄 Qt 版 overlay_drag_corgi_app.py 原文：
# - generatePracticeQuestions / evaluatePracticeAnswers：LLM 失败时返回固定模板
#   备用文本（与旧前端展示行为一致）；
# - chatWithAIAsync：无论成败都 success:true，失败给随机柯基文案；
# - 其余端点失败按 Q6 语义返回 success:false + 错误信息。


def _llm_call(prompt: str, context: str = "") -> str:
    from llm_provider_factory import call_llm
    return call_llm(prompt, context)


@bridge_bp.route("/api/practice/generate-questions", methods=["POST"])
@require_auth
def practice_generate_questions():
    """generatePracticeQuestions：纯文本题目（失败→备用题目模板）。"""
    body = request.get_json(silent=True) or {}
    selected_text = body.get("selected_text") or ""

    prompt = f"""请基于以下内容生成一套练习题目：

**学习内容：**
{selected_text}

**要求：**
1. 生成5-8道不同类型的题目（选择题、填空题、简答题、应用题等）
2. 题目要有一定的难度梯度，从基础理解到深入应用
3. 每道题目都要紧密围绕给定的学习内容
4. 题目表述要清晰明确，便于理解
5. 使用纯文本格式，题目编号使用数字格式：1. 2. 3. 等
6. 选择题的选项使用 A) B) C) D) 格式
7. 只提供题目，不要提供答案

请生成练习题目："""

    def _fallback_questions():
        return f"""基于学习内容的练习题目：

1. 请简要概括以下内容的主要观点：
"{selected_text[:200]}{'...' if len(selected_text) > 200 else ''}"

2. 这个内容中提到的核心概念有哪些？请列举并简要说明。

3. 请分析这些概念在实际应用中的重要性。

4. 如果要向他人解释这个内容，你会如何组织语言？

5. 基于这个内容，你认为还有哪些相关知识点值得深入学习？

请认真思考后作答，每道题目都要结合具体内容来回答。"""

    try:
        response = _llm_call(prompt, "生成练习题目")
        if response:
            return _ok(response, **cr.billing_for_response())
        return _ok(_fallback_questions())
    except cr.InsufficientCreditsError as e:
        return _ok(_fallback_questions(), credits_insufficient=True, credit_balance=e.balance,
                   credit_note="积分不足，请充值后使用 AI 出题")
    except Exception:  # noqa: BLE001
        return _ok(_fallback_questions())


@bridge_bp.route("/api/practice/evaluate-answers", methods=["POST"])
@require_auth
def practice_evaluate_answers():
    """evaluatePracticeAnswers(questions, answers)：纯文本评判（失败→备用报告模板）。"""
    body = request.get_json(silent=True) or {}
    questions = body.get("questions") or ""
    answers = body.get("answers") or ""

    prompt = f"""请对以下练习答案进行专业评判：

**练习题目：**
{questions}

**学生答案：**
{answers}

**评判要求：**
1. 对每道题目的回答进行具体分析
2. 评估答案的准确性、完整性和深度
3. 给出具体的改进建议
4. 评估学生对知识点的掌握程度
5. 使用星级评分（1-5星）评价不同维度
6. 提供鼓励性的反馈和学习建议

**评判维度：**
- 概念理解：对基本概念的理解程度
- 应用能力：将知识应用到实际情况的能力
- 分析深度：分析问题的深度和广度
- 表达清晰：答案表达的清晰度和逻辑性

请生成详细的评判报告："""

    fallback = """📊 练习评估报告

✅ 整体表现：良好
感谢您认真完成了这次练习，您的回答显示了对学习内容的基本理解。

📝 评价维度：
• 概念理解：★★★☆☆ (3/5)
  - 基本概念掌握情况良好
  - 建议加强对细节的理解

• 应用能力：★★★☆☆ (3/5)
  - 能够进行基本的应用分析
  - 可以尝试更多实际案例

• 分析深度：★★☆☆☆ (2/5)
  - 分析较为表面
  - 建议深入思考问题的本质

• 表达清晰：★★★★☆ (4/5)
  - 表达清晰，逻辑较好
  - 继续保持这种表达方式

💡 学习建议：
1. 加强对核心概念的深入理解
2. 多结合实际案例进行思考
3. 尝试从多个角度分析问题
4. 继续保持学习的积极性

🎯 总体掌握程度：65%
继续努力，相信您会取得更好的成绩！"""

    try:
        response = _llm_call(prompt, "评判练习答案")
        if response:
            return _ok(response, **cr.billing_for_response())
        return _ok(fallback)
    except cr.InsufficientCreditsError as e:
        return _ok(fallback, credits_insufficient=True, credit_balance=e.balance,
                   credit_note="积分不足，请充值后使用 AI 评判")
    except Exception:  # noqa: BLE001
        return _ok(fallback)


@bridge_bp.route("/api/practice/evaluate-answer", methods=["POST"])
@require_auth
def practice_evaluate_answer_single():
    """evaluatePracticeAnswer(JSON)：结构化评估 {score,feedback,evaluation_text,suggestions}。"""
    body = request.get_json(silent=True) or {}
    question = body.get("question", "")
    answer = body.get("answer", "")

    prompt_template = """请作为专业技术面试官，对以下"技术练习答卷"进行严格的逐题评估，并务必按规定的结构化纯文本格式输出。

【试卷原题（严格按原文逐条列出）】
{question}

【用户作答（按题号或题目前缀对应）】
{answer}

【重要的输出要求——务必完全遵守】
1) 全部输出使用纯文本，不要使用任何HTML或Markdown标记。
2) 严格按"逐题报告"结构列出每一道题，且每题包含以下小节，并使用这些准确的小节标题：
   - 原题：
   - 用户答案：
   - 判定：（只能是"正确"/"错误"/"无法判断"三选一）
   - 分析与要点：
3) 每题之间使用一行仅包含"----"的分隔线。
4) 在所有题目之后，给出"整体评价"与"知识点掌握程度评估"，掌握程度评估需包含：
   基础概念理解、实际应用能力、深度思考能力、综合运用能力 四项，各用1-5分表示，并给出一句简要说明。

【请输出】
先输出逐题报告（每题按照"原题/用户答案/判定/分析与要点"的顺序完整展示原题文本），然后输出整体评价与知识点掌握程度评估。"""

    prompt = prompt_template.format(question=question, answer=answer)
    try:
        response = _llm_call(prompt, "评估练习答案")
        if response:
            score = 75
            score_match = re.search(r'基础概念理解[：:]\s*(\d+)', response)
            if score_match:
                try:
                    score = min(100, int(score_match.group(1)) * 20)
                except Exception:  # noqa: BLE001
                    pass
            # data 内放置完整 Qt 协议对象（页面 callback 拿到 {success,data:{score,...}}）
            return _ok({
                "success": True,
                "data": {
                    "score": score,
                    "feedback": response,
                    "evaluation_text": response,  # 完整评估文本，用于错题入库
                    "suggestions": ["根据评估结果进行针对性学习", "重点关注错误题目的知识点"],
                },
                **cr.billing_for_response(),
            })
        return _ok({"success": False, "error": "AI评估服务暂时不可用"})
    except cr.InsufficientCreditsError as e:
        return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": str(e)})


def _extract_question_from_evaluation(evaluation_result: str, question_number: int) -> str:
    """从评估结果中提取指定题目完整内容（Qt _extract_question_from_evaluation 1:1）。"""
    try:
        patterns = [
            rf"(?ms){question_number}\.[ \t]*原题[：:][ \t]*\n?(.*?)(?=(?:\n----|\n{question_number + 1}\.[ \t]*原题[：:]|\n整体评价|\Z))",
            rf"(?ms){question_number}\.[ \t]*原题[：:][ \t]*(.*?)(?=(?:\n{question_number + 1}\.[ \t]*原题[：:]|\n整体评价|\Z))",
        ]
        for pattern in patterns:
            match = re.search(pattern, evaluation_result)
            if match:
                content = match.group(1).strip()
                question_match = re.search(r"(.*?)(?=\n用户答案[：:]|$)", content, re.DOTALL)
                if question_match:
                    return question_match.group(1).strip()
                return content
        return ""
    except Exception:  # noqa: BLE001
        return ""


@bridge_bp.route("/api/practice/slice-errors", methods=["POST"])
@require_auth
def practice_slice_errors():
    """addToErrorBank：错题切片 + 学科列表（知识点匹配留待用户选学科后）。"""
    body = request.get_json(silent=True) or {}
    practice_content = body.get("practice_content", "")
    evaluation_result = body.get("evaluation_result", "")
    selected_text = body.get("selected_text", "")
    questions = body.get("questions", "")
    answers = body.get("answers", "")

    if not practice_content:
        practice_content = (
            f"学习内容: {selected_text}\n\n"
            f"题目:\n{questions}\n\n"
            f"题目和答案:\n{answers}"
        )

    try:
        from services.error_slicer import ErrorQuestionSlicer
        slicer = ErrorQuestionSlicer(load_config())
        error_questions = slicer.slice_error_questions(practice_content, evaluation_result)

        kms = get_kms()
        available_subjects = []
        try:
            for subject in kms.get_subjects(user_id=g.user_id):
                points = kms.get_knowledge_points_by_subject(subject, user_id=g.user_id)
                if points:  # 只显示有知识点的学科
                    available_subjects.append({"name": subject, "point_count": len(points)})
        except Exception as e:  # noqa: BLE001
            log.log_error("bridge", "slice_load_subjects_failed", str(e))

        processed_errors = []
        for i, err in enumerate(error_questions):
            processed_errors.append({
                "question_index": err.get("question_index", i),
                "question_content": err.get("question_content", ""),
                "user_answer": err.get("user_answer", ""),
                "correct_answer": err.get("correct_answer", ""),
                "explanation": err.get("explanation", ""),
                "knowledge_point_hint": err.get("knowledge_point_hint", ""),
                "knowledge_options": [],
                "default_knowledge_point": None,
            })

        return _ok({
            "success": True,
            "message": "错题切片完成",
            "data": {
                "error_questions": processed_errors,
                "available_subjects": available_subjects,
                "practice_content": practice_content,
                "evaluation_result": evaluation_result,
                "selected_text": selected_text,
            },
        })
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "slice_errors_failed", str(e))
        return _ok({"success": False, "error": f"错题处理失败: {e}"})


@bridge_bp.route("/api/practice/match-points", methods=["POST"])
@require_auth
def practice_match_points():
    """matchKnowledgePointsForSubject：为选定学科的每题排名全部知识点选项。"""
    body = request.get_json(silent=True) or {}
    selected_subject = body.get("selected_subject", "")
    error_questions = body.get("error_questions", []) or []
    evaluation_result = body.get("evaluation_result", "")

    try:
        kms = get_kms()
        subject_points = kms.get_knowledge_points_by_subject(selected_subject, user_id=g.user_id)

        from similarity_matcher import rank_matches
        cfg = load_config()

        matched_errors = []
        for err in error_questions:
            question_index = err.get("question_index", 0)
            question_content = _extract_question_from_evaluation(evaluation_result, question_index + 1)
            if not question_content:
                question_content = err.get("question_content", f"题目{question_index + 1}")

            try:
                ranked = rank_matches(question=question_content, knowledge_points=subject_points,
                                      cfg=cfg, min_score=0.0)
            except Exception as e:  # noqa: BLE001
                log.log_error("bridge", "match_points_rank_failed", str(e))
                ranked = []

            score_map = {r["id"]: r["score"] for r in ranked}
            ordered_points = sorted(subject_points, key=lambda p: score_map.get(p["id"], -1.0), reverse=True)

            knowledge_options = []
            for kp in ordered_points:
                pid = kp["id"]
                score = score_map.get(pid, 0.0)
                knowledge_options.append({
                    "id": pid,
                    "display": f"{selected_subject} - {kp['point_name']} ({score:.3f})",
                    "subject": selected_subject,
                    "point_name": kp["point_name"],
                    "score": score,
                    "core_description": kp.get("core_description", ""),
                })

            matched_error = dict(err)
            matched_error.update({
                "question_content": question_content,
                "knowledge_options": knowledge_options,
                "default_knowledge_point": knowledge_options[0] if knowledge_options else None,
            })
            matched_errors.append(matched_error)

        return _ok({
            "success": True,
            "message": f"已为学科 {selected_subject} 匹配知识点",
            "data": {"matched_errors": matched_errors, "selected_subject": selected_subject},
        })
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "match_points_failed", str(e))
        return _ok({"success": False, "error": f"知识点匹配失败: {e}"})


@bridge_bp.route("/api/practice/save-errors", methods=["POST"])
@require_auth
def practice_save_errors():
    """saveErrorsToKnowledgeBase：选中的错题按知识点入库（无 id 的跳过）。"""
    body = request.get_json(silent=True) or {}
    selected_errors = body.get("selected_errors", []) or []

    try:
        kms = get_kms()
        records = []
        for error in selected_errors:
            knowledge_point = error.get("selected_knowledge_point", {}) or {}
            if not knowledge_point.get("id"):
                continue
            records.append({
                "subject_name": knowledge_point.get("subject", "通用学科"),
                "knowledge_point_id": knowledge_point.get("id"),
                "question_content": error.get("question_content", ""),
                "user_answer": error.get("user_answer", ""),
                "is_correct": False,
                "correct_answer": error.get("correct_answer"),
                "explanation": error.get("explanation"),
            })

        if not records:
            return _ok({"success": False, "error": "无有效记录可入库"})

        saved_ids = kms.save_practice_results(records, user_id=g.user_id)
        n = len(saved_ids) if saved_ids else 0
        return _ok({"success": True, "message": f"已保存 {n} 条错题到知识库", "saved_count": n})
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "save_errors_failed", str(e))
        return _ok({"success": False, "error": f"保存错题失败: {e}"})


_NEW_PRACTICE_CONTENT = """机器学习基础概念：
机器学习是人工智能的一个分支，它是一种让计算机系统能够自动地从数据中学习和改善性能的方法。
主要包括监督学习、无监督学习和强化学习三大类别。
常见的算法包括线性回归、决策树、随机森林、支持向量机等。"""


@bridge_bp.route("/api/practice/new", methods=["POST"])
@require_auth
def practice_new():
    """generateNewPractice：基于内置最近学习内容生成练习（Qt 版即硬编码内容）。"""
    import time
    body = request.get_json(silent=True) or {}
    recent_content = body.get("selected_text") or _NEW_PRACTICE_CONTENT

    def _gen(text):
        prompt = f"""请基于以下内容生成一套练习题目：

**学习内容：**
{text}

**要求：**
1. 生成5-8道不同类型的题目（选择题、填空题、简答题、应用题等）
2. 题目要有一定的难度梯度，从基础理解到深入应用
3. 每道题目都要紧密围绕给定的学习内容
4. 题目表述要清晰明确，便于理解
5. 使用纯文本格式，题目编号使用数字格式：1. 2. 3. 等
6. 选择题的选项使用 A) B) C) D) 格式
7. 只提供题目，不要提供答案

请生成练习题目："""
        return _llm_call(prompt, "生成练习题目")

    try:
        try:
            questions = _gen(recent_content)
        except cr.InsufficientCreditsError as e:
            return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
        except Exception:  # noqa: BLE001
            questions = _gen_fallback(recent_content)
        if questions:
            return _ok({
                "id": f"TECH-{int(time.time())}",
                "question": questions,
                "questions": questions,  # 兼容两种字段名
                "related_content": "基于最近学习的机器学习基础概念生成",
                "selectedText": recent_content,
                **cr.billing_for_response(),
            })
        return _ok({"success": False, "error": "生成练习题目失败"})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": str(e)})


def _gen_fallback(selected_text: str) -> str:
    return f"""基于学习内容的练习题目：

1. 请简要概括以下内容的主要观点：
"{selected_text[:200]}{'...' if len(selected_text) > 200 else ''}"

2. 这个内容中提到的核心概念有哪些？请列举并简要说明。

3. 请分析这些概念在实际应用中的重要性。

4. 如果要向他人解释这个内容，你会如何组织语言？

5. 基于这个内容，你认为还有哪些相关知识点值得深入学习？

请认真思考后作答，每道题目都要结合具体内容来回答。"""


@bridge_bp.route("/api/llm/chat", methods=["POST"])
@require_auth
def llm_chat():
    """chatWithAIAsync：无论成败都 success:true，失败给随机柯基 fallback（Qt 1:1）。"""
    import random
    body = request.get_json(silent=True) or {}
    message = body.get("message", "")
    conversation_history = body.get("conversation_history") or []

    system_prompt = """你是柯基学习小助手的AI伙伴，一个友善、聪明、有耐心的学习助手。
你的特点：
1. 像柯基犬一样活泼友好，偶尔会用"汪！"表达兴奋
2. 专注于帮助用户学习和解决问题
3. 回答简洁明了，但不失温暖
4. 善于将复杂概念用简单易懂的方式解释
5. 鼓励用户积极学习，给予正面反馈

请用友好、鼓励的语气回答用户的问题。记住之前的对话内容，保持对话的连贯性。"""

    full_prompt = system_prompt + "\n\n"
    try:
        if conversation_history:
            full_prompt += "对话历史：\n"
            for msg in conversation_history[-10:]:  # 只保留最近10条消息
                role = "用户" if msg.get("role") == "user" else "AI助手"
                full_prompt += f"{role}: {msg.get('content', '')}\n"
            full_prompt += "\n"
        full_prompt += f"用户: {message}\nAI助手: "

        try:
            ai_response = _llm_call(full_prompt, "AI聊天对话")
            if ai_response:
                return _ok({"success": True, "message": ai_response, **cr.billing_for_response()})
        except cr.InsufficientCreditsError as e:
            return _ok({"success": False, "message": "积分不足，请充值后继续对话。",
                        "credits_insufficient": True, "credit_balance": e.balance})
        except Exception:  # noqa: BLE001
            pass
        fallback_responses = [
            "汪！我现在有点累了，稍后再聊好吗？",
            "抱歉，我的小脑瓜现在有点转不过来，请稍后再试试。",
            "哎呀，我好像走神了，能再说一遍吗？",
            "我需要先去充充电，等会儿再来帮你！",
        ]
        return _ok({"success": True, "message": random.choice(fallback_responses)})
    except Exception:  # noqa: BLE001
        return _ok({"success": True, "message": "汪！我现在有点忙，稍后再来找我聊天吧！"})


@bridge_bp.route("/api/llm/summarize-conversation", methods=["POST"])
@require_auth
def llm_summarize_conversation():
    """summarizeConversation：{success,summary} / {success:false,error}。"""
    body = request.get_json(silent=True) or {}
    conversation_history = body.get("conversation_history") or []
    if not conversation_history:
        return _ok({"success": False, "error": "没有对话内容可以总结"})

    conversation_text = "\n\n".join([
        f"{'用户' if msg.get('role') == 'user' else 'AI助手'}: {msg.get('content', '')}"
        for msg in conversation_history
    ])

    summary_prompt = f"""请用中文对以下对话进行知识点总结，要求：
1. 使用中文回答
2. 提取关键知识点和要点
3. 结构化展示，使用标题和列表
4. 突出重要概念和原理
5. 保持简洁明了

对话内容：
{conversation_text}

请生成总结："""

    try:
        summary = _llm_call(summary_prompt, "对话总结")
        if summary:
            return _ok({"success": True, "summary": summary, **cr.billing_for_response()})
        return _ok({"success": False, "error": "总结生成失败"})
    except cr.InsufficientCreditsError as e:
        return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": f"总结生成失败: {e}"})


@bridge_bp.route("/api/llm/summarize-text", methods=["POST"])
@require_auth
def llm_summarize_text():
    """summarizeText：{success,message,summary}；空文本/失败按 Qt 原文返回错误。"""
    body = request.get_json(silent=True) or {}
    text = body.get("text") or ""
    if not text.strip():
        return _ok({"success": False, "error": "文本内容为空"})

    summary_prompt = f"""请对以下文本进行总结，提取关键信息和要点：

{text}

请用简洁的Markdown格式输出总结，重点突出核心内容。

总结内容："""

    try:
        summary_result = _llm_call(summary_prompt, "文本总结")
        if summary_result and not summary_result.startswith("LLM调用失败"):
            return _ok({"success": True, "message": "总结完成", "summary": summary_result,
                        **cr.billing_for_response()})
        return _ok({"success": False, "error": f"总结失败: {summary_result}"})
    except cr.InsufficientCreditsError as e:
        return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": f"文本总结失败: {str(e)}"})


@bridge_bp.route("/api/knowledge/points/<int:pid>/generate-assessment", methods=["POST"])
@require_auth
def knowledge_generate_assessment(pid):
    """generateAssessmentQuestions：为知识点出10道选择题（严格校验 10 题×4 选项）。"""
    kms = get_kms()
    try:
        conn = kms.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT point_name, core_description, subject_name FROM knowledge_points WHERE id = ? AND user_id = ?",
                       (pid, g.user_id))
        result = cursor.fetchone()
        conn.close()
        if not result:
            return _ok({"success": False, "error": "未找到该知识点"})
        point_name, core_description, subject_name = result[0], result[1], result[2]

        prompt = f"""请为以下知识点生成10道选择题，用于评估学生的掌握程度。

知识点信息：
- 名称：{point_name}
- 描述：{core_description}
- 学科：{subject_name}

要求：
1. 生成10道选择题，难度从容易到困难递增
2. 每道题有4个选项（A、B、C、D）
3. 题目要准确测试对该知识点的理解
4. 包含不同层次的认知要求：记忆、理解、应用、分析
5. 返回JSON格式，包含以下字段：
   - question: 题目内容
   - options: 选项数组（4个选项）
   - correct_answer: 正确答案（A/B/C/D）
   - difficulty: 难度等级（容易/中等/困难）
   - explanation: 答案解释

请直接返回JSON数组格式，不要包含其他文字：
[
  {{
    "question": "题目内容",
    "options": ["选项A", "选项B", "选项C", "选项D"],
    "correct_answer": "A",
    "difficulty": "容易",
    "explanation": "答案解释"
  }}
]"""

        try:
            response = _llm_call(prompt, "熟练度评估题目生成")
        except cr.InsufficientCreditsError as e:
            return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
        except Exception as e:  # noqa: BLE001
            return _ok({"success": False, "error": f"LLM调用失败: {e}"})
        if not response:
            return _ok({"success": False, "error": "LLM调用失败"})

        try:
            response = response.strip()
            if response.startswith('```json'):
                response = response[7:]
            if response.endswith('```'):
                response = response[:-3]
            response = response.strip()

            questions = json.loads(response)
            if not isinstance(questions, list) or len(questions) != 10:
                raise ValueError("题目数量不正确")
            for i, q in enumerate(questions):
                if not all(key in q for key in ['question', 'options', 'correct_answer', 'difficulty']):
                    raise ValueError(f"题目{i + 1}格式不完整")
                if len(q['options']) != 4:
                    raise ValueError(f"题目{i + 1}选项数量不正确")
            return _ok({"success": True, "questions": questions, **cr.billing_for_response()})
        except json.JSONDecodeError:
            return _ok({"success": False, "error": "题目格式解析失败"})
        except ValueError as e:
            return _ok({"success": False, "error": str(e)})
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "generate_assessment_failed", str(e))
        return _ok({"success": False, "error": str(e)})
