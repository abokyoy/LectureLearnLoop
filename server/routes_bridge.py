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
import hashlib
import hmac
import json
import re
import shutil
import time as _walltime
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file

from auth import require_auth
from config import DATA_DIR, VAULT_DIR, load_config, save_runtime_config
from knowledge_management import difficulty_label_to_score
from logger_module import debug_logger as log
import credits_service as cr
from services import fsrs_service as F
from routes_knowledge import _ok, _err, get_kms, _user_vault_root

bridge_bp = Blueprint("bridge", __name__)

# ---------------------------------------------------------------- 路径工具

_MD_EXT = {".md", ".markdown", ".txt"}
import re as _re_mod
_SEG_EMPTY_RE = _re_mod.compile(r"\u00b7\d{4}-\d{4}\.md$")
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
                # 大PDF分段（S5）：仅隐藏书籍文件夹内“段命名且 0 字节”的空段（·NNNN-NNNN.md）；
                # 该命名仅书籍段文件使用，不影响 ≤20 页普通占位（审核 P2-11）。
                if ext == ".tmp":
                    continue  # 原子写盘崩溃残留的 .md.tmp 不在树中暴露（评审 m5）
                if ext == ".md" and _SEG_EMPTY_RE.search(e.name):
                    try:
                        if e.stat().st_size == 0:
                            continue
                    except OSError:
                        continue
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
        from services import import_service as imp

        def _purge_books(t):
            # 书籍任务同存同删（2026-10-07）：任务行回收失败不得把已成功的删除报成失败
            try:
                imp.purge_book_tasks_under(g.user_id, t)
            except Exception as pe:  # noqa: BLE001
                log.log_error("bridge", "book_purge_failed", str(pe))

        if target.is_dir():
            shutil.rmtree(target)
            # 删文件夹时回收其下书籍主任务及段子任务，防僵尸行遮蔽同名新书
            _purge_books(target)
        elif target.suffix.lower() in imp.NOTE_SCAN_EXTS:
            # 同存同删（2026-10-06）：删笔记回收其独占附件图片，仍被存留笔记引用的保留
            ok, removed_att = imp.delete_md_with_attachment_cleanup(target)
            if removed_att:
                log.log("bridge", "vault_delete_md_att", "success",
                        {"path": str(body.get("path")), "removed_attachments": removed_att})
            return _ok(ok)
        else:
            target.unlink()
            if target.suffix.lower() == ".pdf":
                _purge_books(target)  # 直删原件即拆书：同步回收任务行
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


# ---------------------------------------------------------------- 一·六、文件导入（PDF/DOCX/MD/TXT/图片 + URL，2026-09-30；第七轮扩展）

_IMPORT_TEXT_EXTS = {".md", ".txt"}
_IMPORT_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_IMPORT_EXTS = {".pdf", ".docx"} | _IMPORT_TEXT_EXTS | _IMPORT_IMG_EXTS


@bridge_bp.route("/api/vault/import", methods=["POST"])
@require_auth
def vault_import():
    """文件导入：上传 PDF/DOCX/MD/TXT/图片 到用户 vault 指定目录（方案 §3.3）。

    multipart: file + folder_path（嵌套树返回的绝对路径或相对 root 路径，经 _bridge_path 校验）。
    - MD/TXT：解码直接落盘+入库，任务即时 done；
    - 图片：原图存 <目标>/附件/，新建同名 .md 嵌入图片引用（用户确认：不做 OCR），即时 done；
    - PDF：原件存 <目标>/附件/，后台 worker 文本层优先/OCR 回落转 MD；
    - DOCX：原件存附件/，后台 worker 本地 mammoth+markdownify 转 MD（不耗远端额度）。
    前端轮询状态端点。返回 {success, task_id, file_name}。
    """
    from services import import_service as imp

    f = request.files.get("file")
    if f is None or not f.filename:
        return _ok({"success": False, "error": "未选择文件"})
    folder = _bridge_path(g.user_id, request.form.get("folder_path") or "vault")
    if folder is None or (folder.exists() and not folder.is_dir()) or folder == _user_vault_root(g.user_id).parent:
        return _ok({"success": False, "error": "目标位置不合法"})
    # 文件名清洗（MF-2）：先取 basename 去路径分隔符注入，再白名单字符；不用 secure_filename（会清空纯中文名）
    raw_name = Path(f.filename.replace("\\", "/")).name
    name = re.sub(r"[^\w\u4e00-\u9fa5. -]", "_", raw_name).strip(" .") or "文件"
    ext = Path(name).suffix.lower()
    if ext not in _IMPORT_EXTS:
        return _ok({"success": False, "error": f"不支持的文件类型：{ext or '无扩展名'}（仅 PDF/DOCX/MD/TXT/图片）"})
    data = f.read()
    if not data:
        return _ok({"success": False, "error": "文件内容为空"})
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if ext in _IMPORT_TEXT_EXTS:
            target_name = imp.uniquify_name(folder, name)
            target = folder / target_name
            content = imp.decode_text_bytes(data)
            if not content.strip():
                return _ok({"success": False, "error": "文件内容为空"})
            target.write_text(content, encoding="utf-8")
            tid = imp.create_task(g.user_id, target_name, str(folder), ext[1:], result_md=str(target))
            # 评审 MF-1：入库失败不得报假成功（任务置 failed，前端可见原因）
            if imp.sync_note_content(g.user_id, target, content):
                imp.update_task(tid, status="done", progress_json='{"done": 1, "total": 1}')
                log.log("import", "text_imported", "success", {"task": tid, "name": target_name})
                return _ok({"success": True, "task_id": tid, "file_name": target_name})
            imp.update_task(tid, status="failed", error="正文入库失败，笔记列表可能不可见，请删除后重新导入")
            return _ok({"success": False, "error": "正文入库失败（文件已落盘），请删除后重新导入"})
        if ext in _IMPORT_IMG_EXTS:
            # 图片导入（用户确认）：仅嵌入建新笔记，不做 OCR；原图存附件保留
            att_dir = folder / imp.ATTACH_DIR_NAME
            att_dir.mkdir(parents=True, exist_ok=True)
            img_name = imp.uniquify_name(att_dir, name)
            (att_dir / img_name).write_bytes(data)
            md_name = imp.uniquify_name(folder, Path(img_name).stem + ".md")
            target = folder / md_name
            # 评审 R2 必改：文件名含空格/括号等会使 MD link destination 不合法、marked 不渲染；
            # 仅百分号编码这些不安全字符（中文不动，与既有附件引用形态一致）
            safe_ref = re.sub(r"[ \t\r\n()<>\"']", lambda m: f"%{ord(m.group(0)):02X}", img_name)
            content = f"![图片]({imp.ATTACH_DIR_NAME}/{safe_ref})"
            target.write_text(content, encoding="utf-8")
            tid = imp.create_task(g.user_id, md_name, str(folder), "img", result_md=str(target))
            if imp.sync_note_content(g.user_id, target, content):
                imp.update_task(tid, status="done", progress_json='{"done": 1, "total": 1}')
                log.log("import", "image_imported", "success", {"task": tid, "name": md_name})
                return _ok({"success": True, "task_id": tid, "file_name": md_name})
            imp.update_task(tid, status="failed", error="正文入库失败，笔记列表可能不可见，请删除后重新导入")
            return _ok({"success": False, "error": "正文入库失败（文件已落盘），请删除后重新导入"})
        # PDF/DOCX：原件落附件目录，同名 .md 为目标产物，后台 worker 转换（两路径同模式）
        # 2026-10-04 大PDF分段：PDF 先按“页数+体积”三态分流（≤20 页分支代码路径零改动）
        if ext == ".pdf":
            try:
                total = imp.pdf_page_count(data)
            except Exception:  # noqa: BLE001 打不开（异常 PDF）→当作小文件走现状流程，由 worker 兑错
                total = None
            from config import PDF_BOOK_PAGE_MIN, PDF_BOOK_EXEMPT_PAGES, PDF_BOOK_EXEMPT_SIZE_MB
            size_mb = len(data) / 1024 / 1024
            is_small = (total is None) or (total <= PDF_BOOK_PAGE_MIN) or \
                (total <= PDF_BOOK_EXEMPT_PAGES and size_mb <= PDF_BOOK_EXEMPT_SIZE_MB)
            if not is_small:
                return _import_pdf_book(imp, g.user_id, folder, name, data, total)
        att_dir = folder / imp.ATTACH_DIR_NAME
        att_dir.mkdir(parents=True, exist_ok=True)
        orig_name = imp.uniquify_name(att_dir, name)
        (att_dir / orig_name).write_bytes(data)
        md_name = imp.uniquify_name(folder, Path(orig_name).stem + ".md")
        target_md = folder / md_name
        target_md.write_text("", encoding="utf-8")  # 评审 O-2：占位预先占名，防并发同名导入互相覆盖
        tid = imp.create_task(g.user_id, md_name, str(folder), ext[1:],
                              result_md=str(target_md), result_pdf=str(att_dir / orig_name))
        if ext == ".docx":
            imp.start_docx_task(tid, g.user_id, att_dir / orig_name, target_md)
            log.log("import", "docx_task_started", "success", {"task": tid, "docx": orig_name})
        else:
            imp.start_pdf_task(tid, g.user_id, att_dir / orig_name, target_md)
            log.log("import", "pdf_task_started", "success", {"task": tid, "pdf": orig_name})
        return _ok({"success": True, "task_id": tid, "file_name": md_name})
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "import_failed", e)
        return _ok({"success": False, "error": f"导入失败: {e}"})


def _import_pdf_book(imp, user_id: str, folder: Path, name: str, data: bytes, total: int):
    """大 PDF（>20 页且非小文件豁免）→ 建书籍文件夹（方案 §4.1/§4.2）。

    结构：<落点>/<书>/<书>.pdf + <书>·0001-0020.md…预生成空占位 + 附件/。
    文本层→投递整书串行 worker；扫描件→主任务即置 done（等前端逐段手动转）。
    """
    from config import PDF_SEG_PAGE_SIZE
    import shutil
    base = imp.uniquify_name(folder, Path(name).stem)
    book_dir = folder / base
    book_dir.mkdir(parents=True, exist_ok=True)
    try:
        orig = book_dir / (base + ".pdf")
        orig.write_bytes(data)
        (book_dir / imp.ATTACH_DIR_NAME).mkdir(parents=True, exist_ok=True)
        is_text = imp.pdf_is_text_layer(data)
        segs = imp.compute_pdf_segments(total, PDF_SEG_PAGE_SIZE)
        for sf, st in segs:
            (book_dir / imp.segment_md_name(base, sf, st)).write_text("", encoding="utf-8")
        init_prog = json.dumps({"done": 0, "total": len(segs), "is_text_layer": is_text, "pages": total})
        # 文本层：主任务 pending，投递整书 worker；扫描：占位建好即 done（审核 P2-G）
        tid = imp.create_task(user_id, base + ".pdf", str(book_dir), "pdf_book",
                              result_pdf=str(orig), status=("pending" if is_text else "done"),
                              progress_json=init_prog)
        if is_text:
            imp.start_pdf_book_task(tid, user_id, orig, book_dir, base, total)
    except Exception:  # noqa: BLE001 落盘/建任务中途失败 → 不留半截书籍文件夹（评审 m7）
        shutil.rmtree(book_dir, ignore_errors=True)
        raise
    log.log("import", "pdf_book_created", "success",
            {"task": tid, "pages": total, "segs": len(segs), "is_text": is_text})
    return _ok({"success": True, "task_id": tid, "file_name": base + ".pdf", "is_book": True,
                "total_pages": total, "segments": len(segs), "is_text_layer": is_text})


def _load_book(imp, main_task_id: str, user_id: str):
    """加载书籍主任务并定位原件/文件夹/base/总页数；非法返回 None。"""
    task = imp.get_book_task(main_task_id, user_id)
    if not task or task["kind"] != "pdf_book" or not task["result_pdf"]:
        return None
    orig = Path(task["result_pdf"])
    if not orig.is_file():
        return None
    from config import PDF_SEG_PAGE_SIZE  # noqa: F401 段大小由 compute_pdf_segments 默认取
    prog = json.loads(task["progress_json"] or "{}")
    total = prog.get("pages") or imp.pdf_page_count(orig)
    return {"task": task, "prog": prog, "orig": orig, "book_dir": orig.parent,
            "base": orig.stem, "total": total}


def _seg_index_pairs(imp, bk, segs_idx) -> list[tuple[int, int]]:
    """将前端传入的 1-based 段序号解析为 (seg_from, seg_to) 物理页区间。"""
    segs = imp.compute_pdf_segments(bk["total"])
    out: list[tuple[int, int]] = []
    for idx in (segs_idx or []):
        try:
            i = int(idx) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(segs):
            out.append(segs[i])
    return out


def _book_convert_plan(imp, bk, main_task_id: str, user_id: str, segs_idx, force_ocr: bool, force: bool = False):
    """算出待转段与方法（text/ocr），并识别“正在转换中”的段（防重复投递，方案 §6）。

    force_ocr 仅决定方法（强制走 OCR）；force 才允许对已转段重转覆盖（文本层重转不额外耗 OCR，评审 m2）。
    running 段列入 busy、不重复建任务。返回 (method, to_convert[(sf,st)], ocr_pages, busy[(sf,st)])。
    """
    is_text = bk["prog"].get("is_text_layer")
    method = "text" if (is_text and not force_ocr) else "ocr"
    acts = imp.active_segment_states(main_task_id, user_id)
    to_convert: list[tuple[int, int]] = []
    busy: list[tuple[int, int]] = []
    for sf, st in _seg_index_pairs(imp, bk, segs_idx):
        state = (acts.get((sf, st)) or ("pending", ""))[0]
        if state == "running":
            busy.append((sf, st))
            continue
        p = bk["book_dir"] / imp.segment_md_name(bk["base"], sf, st)
        converted = p.exists() and p.stat().st_size > 0
        if converted and not force and state != "failed":
            continue
        to_convert.append((sf, st))
    ocr_pages = sum(st - sf + 1 for sf, st in to_convert) if method == "ocr" else 0
    return method, to_convert, ocr_pages, busy


@bridge_bp.route("/api/import/pdf/book")
@require_auth
def pdf_book_status():
    """书籍段状态列表（前端轮询）：文件系统为已转权威，叠加活跃 convert 任务行 running/failed 态。"""
    from services import import_service as imp
    main = (request.args.get("main_task_id") or "").strip()
    if not main:
        # 树中只有 pdf 路径时反查主任务（viewer/转换面板从笔记树直接打开）
        raw = (request.args.get("path") or "").strip()
        p = _bridge_path(g.user_id, raw) if raw else None
        found = imp.find_book_task_by_pdf(g.user_id, str(p)) if p else None
        if found:
            main = found["task_id"]
    bk = _load_book(imp, main, g.user_id)
    if not bk:
        return _ok({"success": False, "error": "书籍任务不存在或原件缺失"})
    fs = imp.book_segment_status(bk["book_dir"], bk["base"], bk["total"])
    acts = imp.active_segment_states(main, g.user_id)
    for i, it in enumerate(fs, start=1):
        it["index"] = i
        if it["converted"]:
            it["state"] = "converted"
        else:
            av = acts.get((it["from"], it["to"]))
            it["state"] = av[0] if av else "pending"
            if it["state"] == "failed" and av and av[1]:
                it["error"] = av[1]  # 失败原因回传面板（评审 m3）
    return _ok({"success": True,
        "main_task_id": main, "status": bk["task"]["status"], "error": bk["task"]["error"],
        "is_text_layer": bk["prog"].get("is_text_layer"), "total_pages": bk["total"],
        "pdf_path": _rel_to_root(bk["orig"], g.user_id), "segments": fs, "progress": bk["prog"]})


@bridge_bp.route("/api/import/pdf/segments/estimate", methods=["POST"])
@require_auth
def pdf_segments_estimate():
    """转换前估算（不落任务，确认3=B）：返回待转段数/需 OCR 页数/方法。"""
    from services import import_service as imp
    body = request.get_json(silent=True) or {}
    main = (body.get("main_task_id") or "").strip()
    bk = _load_book(imp, main, g.user_id)
    if not bk:
        return _ok({"success": False, "error": "书籍任务不存在"})
    _fo = bool(body.get("force_ocr"))
    method, to_convert, ocr_pages, busy = _book_convert_plan(imp, bk, main, g.user_id, body.get("segs"), _fo, bool(body.get("force")) or _fo)
    return _ok({"success": True,
        "method": method, "segs": len(to_convert), "ocr_pages": ocr_pages, "busy": len(busy),
        "need_confirm": method == "ocr",
        "note": "扫描段将调用云端 OCR（消耗官方免费额度，不扣积分）" if method == "ocr" else "本地文本层提取，无额外消耗"})


@bridge_bp.route("/api/import/pdf/segments/convert", methods=["POST"])
@require_auth
def pdf_segments_convert():
    """段转换（确认3=B）：不带 confirm 返回消耗预估；带 confirm=true 才建 convert_segment 任务投递 worker。"""
    from services import import_service as imp
    body = request.get_json(silent=True) or {}
    main = (body.get("main_task_id") or "").strip()
    bk = _load_book(imp, main, g.user_id)
    if not bk:
        return _ok({"success": False, "error": "书籍任务不存在"})
    _fo = bool(body.get("force_ocr"))
    method, to_convert, ocr_pages, busy = _book_convert_plan(imp, bk, main, g.user_id, body.get("segs"), _fo, bool(body.get("force")) or _fo)
    if not to_convert:
        if busy:
            return _ok({"success": False, "error": "该段正在转换中，请稍候"})
        return _ok({"success": False, "error": "无待转段（已转或无选中）"})
    if not body.get("confirm"):
        return _ok({"success": True,
            "need_confirm": method == "ocr", "method": method, "segs": len(to_convert), "ocr_pages": ocr_pages, "busy": len(busy),
            "note": "扫描段将调用云端 OCR（消耗官方免费额度，不扣积分）" if method == "ocr" else "本地文本层提取，无额外消耗"})
    created = []
    for sf, st in to_convert:
        nm = imp.segment_md_name(bk["base"], sf, st)
        tid = imp.create_task(g.user_id, nm, str(bk["book_dir"]), "convert_segment",
                              parent_task_id=main, seg_from=sf, seg_to=st)
        imp.start_segment_convert(tid, g.user_id, main, bk["orig"], bk["book_dir"], bk["base"], sf, st, method)
        created.append({"task_id": tid, "from": sf, "to": st, "method": method})
    log.log("import", "pdf_segments_convert", "success", {"main": main, "n": len(created), "method": method})
    return _ok({"success": True, "created": created})


# ---------------------------------------------------------------- PDF 原件阅读（签名 token + 流式 Range，方案 §4.6）

def _pdf_secret() -> bytes:
    s = current_app.secret_key
    return s.encode() if isinstance(s, str) else (s or b"")


def _pdf_sign(user_id: str, path_str: str, exp: int) -> str:
    msg = f"{user_id}|{path_str}|{exp}"
    return hmac.new(_pdf_secret(), msg.encode(), hashlib.sha256).hexdigest()


@bridge_bp.route("/api/vault/pdf/sign")
@require_auth
def pdf_sign():
    """为当前用户签发某 vault PDF 的 60 分钟阅读 token（iframe 无法带 Authorization 头，审核 P0-2）。"""
    raw = (request.args.get("path") or "").strip()
    p = _bridge_path(g.user_id, raw)
    if not p or p.suffix.lower() != ".pdf":
        return _ok({"success": False, "error": "路径非法（仅 vault 内 .pdf）"})
    path_str = str(p)
    exp = int(_walltime.time()) + 3600
    return _ok({"success": True, "u": g.user_id, "path": path_str, "exp": exp, "t": _pdf_sign(g.user_id, path_str, exp)})


@bridge_bp.route("/api/vault/pdf")
def pdf_stream():
    """流式返回 vault 内 PDF（支持 HTTP Range，供 pdf.js 分片）。鉴权=签名 token（非 Authorization）。

    新路径，不复用 routes_knowledge 的 /api/vault/file（审核 P0-1）；校验签名+过期+用户隔离子。
    """
    u = (request.args.get("u") or "").strip()
    path = (request.args.get("path") or "").strip()
    t = (request.args.get("t") or "").strip()
    try:
        exp = int(request.args.get("exp") or "0")
    except ValueError:
        exp = 0
    if not u or not path or not t or exp <= 0:
        return jsonify({"error": "签名参数缺失"}), 400
    if exp < int(_walltime.time()):
        return jsonify({"error": "签名已过期，请重新打开"}), 401
    if not hmac.compare_digest(_pdf_sign(u, path, exp), t):
        return jsonify({"error": "签名无效"}), 403
    p = _bridge_path(u, path)
    if not p or p.suffix.lower() != ".pdf" or not p.is_file():
        return jsonify({"error": "文件不存在"}), 404
    return send_file(str(p), mimetype="application/pdf", conditional=True)


@bridge_bp.route("/api/vault/import-url", methods=["POST"])
@require_auth
def vault_import_url():
    """URL 导入：抓取网页（重点：公众号文章）转 MD 笔记（第七轮追加需求）。

    JSON: {url, folder_path}。任务即时返回，后台 worker 抓取/提取/图本地化，
    产物文件名取文章标题（创建时无法预知），前端沿用 /api/vault/import/<task_id> 轮询。
    """
    from urllib.parse import urlparse

    from services import import_service as imp

    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return _ok({"success": False, "error": "请输入 http(s) 网页链接"})
    if not imp.is_safe_http_url(url, allow_http=True):
        return _ok({"success": False, "error": "链接指向内网地址，不支持"})
    folder = _bridge_path(g.user_id, body.get("folder_path") or "vault")
    if folder is None or (folder.exists() and not folder.is_dir()) or folder == _user_vault_root(g.user_id).parent:
        return _ok({"success": False, "error": "目标位置不合法"})
    p = urlparse(url)
    display = (p.netloc or "url") + (p.path or "")[:40]
    try:
        tid = imp.create_task(g.user_id, display[:80], str(folder), "url")
        imp.start_url_task(tid, g.user_id, url, folder)
        log.log("import", "url_task_started", "success", {"task": tid, "url": url[:150]})
        return _ok({"success": True, "task_id": tid, "file_name": display})
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "import_url_failed", e)
        return _ok({"success": False, "error": f"URL 导入失败: {e}"})


@bridge_bp.route("/api/vault/import/<task_id>", methods=["GET"])
@require_auth
def vault_import_status(task_id):
    """导入任务状态（前端轮询）；get_task 内部强制 user_id 隔离。"""
    from services import import_service as imp

    t = imp.get_task(re.sub(r"[^\w-]", "", task_id), g.user_id)
    if t is None:
        return _ok({"success": False, "error": "任务不存在"})
    try:
        progress = json.loads(t["progress_json"] or "{}")
    except ValueError:
        progress = {}
    return _ok({
        "success": True,
        "status": t["status"],
        "progress": progress,
        "file_name": t["file_name"],
        "result_name": Path(t["result_md"]).name if t["result_md"] else "",
        "error": t["error"],
    })


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
        # FSRS 两阶段口径：先按涉及行惰性回写衰减后的 mastery，再取数
        F.decay_flush(g.user_id, ref_ids={"kp": [p.get("id") for p in all_points if p.get("id") is not None]})
        all_points = kms.get_knowledge_points_by_subject(subject, user_id=g.user_id)
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
    """getKnowledgePointNotes：content 为占位串（Qt 原语义）。
    P1 落地页统一（2026-10-09）：去掉 LIMIT 5，落地页全量展示关联笔记。"""
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
            "ORDER BY kps.extraction_time DESC", (pid, g.user_id)).fetchall()
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
    """getNoteContent：P4 去 1000 字符截断，完整返回正文供落地页 MD 预览；关联知识点列表。"""
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
    # P4 评审 m-3：去截断后补响应体闸门，防误挂超大文件拖垮前端同步渲染
    try:
        p = Path(file_path)
        if p.is_file() and p.stat().st_size > 2 * 1024 * 1024:
            return _ok({"success": False, "error": "笔记文件过大（>2MB），请拆分后再预览"})
        content = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else "笔记文件不存在或路径无效"
    except Exception:  # noqa: BLE001
        content = "笔记文件不存在或路径无效"
    return _ok({"success": True, "note": {
        "id": row[0], "title": row[1], "file_name": row[2], "file_path": file_path,
        "content": content, "content_length": len(content),
        "created_time": row[4], "updated_time": row[5],
        "related_knowledge_points": [
            {"id": k[0], "name": k[1], "extraction_time": k[2]} for k in kps
        ],
    }})


def _qtype_guess(text: str) -> str:
    """无独立题库表：按题干启发式猜题型中文标签（P2 前为 point_questions 嵌套函数，提级供详情端点复用）。"""
    if re.search(r"[A-D][.、）)]", text or "") or "选择" in (text or ""):
        return "选择题"
    if "_" in (text or "") or "（　）" in (text or "") or "填空" in (text or ""):
        return "填空题"
    return "简答题"


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
            "GROUP BY question_content, p1.knowledge_point_id, p1.user_id "
            "ORDER BY last_time DESC", (pid, g.user_id)).fetchall()
        favorites = {r[0] for r in conn.execute(
            "SELECT question_content FROM favorite_questions WHERE knowledge_point_id = ? AND user_id = ?",
            (pid, g.user_id)).fetchall()}
    finally:
        conn.close()

    out = []
    for content, practice_count, correct_count, last_time, last_correct in rows:
        correct_count = correct_count or 0
        rate = (correct_count / practice_count) if practice_count else 0
        out.append({
            "content": content,
            "type": _qtype_guess(content),
            "practice_count": practice_count,
            "correct_count": correct_count,
            "mastery_stars": min(5, max(1, int(rate * 5) + 1)),
            "last_practice_time": last_time,
            "last_result": "正确" if last_correct else "错误",
            "is_favorite": content in favorites,
        })
    return _ok({"success": True, "questions": out})


@bridge_bp.route("/api/knowledge/points/<int:pid>/question-detail", methods=["GET"])
@require_auth
def point_question_detail(pid):
    """P2 关联题目（2026-10-09）：按题干查题目详情——全部作答流水 + 错题信息 + 重练参考答案。

    query: content=题干（与 point_questions 聚合行一一对应）。
    reference_answer 口径：错题行 correct_answer 优先；无非错题流水时回退最近一次答对的 user_answer
    （无独立题库表，历史正确作答即重练判分基准）。
    """
    content = request.args.get("content") or ""
    if not content.strip():
        return _ok({"success": False, "error": "缺少题干"})
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        recs = conn.execute(
            "SELECT id, user_answer, is_correct, question_type, options_json, practice_time "
            "FROM practice_records WHERE knowledge_point_id = ? AND user_id = ? AND question_content = ? "
            "ORDER BY practice_time DESC, id DESC", (pid, g.user_id, content)).fetchall()
        if not recs:
            return _ok({"success": False, "error": "未找到该题的练习记录"})
        err = conn.execute(
            "SELECT eq.id, eq.correct_answer, eq.explanation, eq.current_proficiency "
            "FROM error_questions eq JOIN practice_records pr ON eq.practice_record_id = pr.id "
            "WHERE pr.knowledge_point_id = ? AND pr.user_id = ? AND pr.question_content = ? "
            "AND eq.user_id = ? "  # P2 评审修复 m-3：错题表自身也按用户隔离（纵深防御）
            "ORDER BY eq.created_time DESC, eq.id DESC LIMIT 1", (pid, g.user_id, content, g.user_id)).fetchone()
        fav = conn.execute(
            "SELECT 1 FROM favorite_questions WHERE knowledge_point_id = ? AND user_id = ? AND question_content = ? LIMIT 1",
            (pid, g.user_id, content)).fetchone()
    finally:
        conn.close()
    # 题型：流水里存的是生成时的英文 type，取最近一条非空；缺失退回题干启发式
    qtype = _qtype_norm(next((r[3] for r in recs if r[3]), ""), content)
    options = None
    for r in recs:
        if r[4]:
            try:
                parsed = json.loads(r[4])
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, list) and parsed:
                options = parsed
                break
    correct_answer = (err[1] if err and err[1] else "") or next((r[1] for r in recs if r[2]), "")
    return _ok({"success": True, "question": {
        "content": content,
        "type": qtype,
        "options": options or [],
        "practice_count": len(recs),
        "correct_count": sum(1 for r in recs if r[2]),
        "is_favorite": bool(fav),
        "records": [{"time": r[5], "user_answer": r[1], "is_correct": bool(r[2])} for r in recs],
        "error": None if not err else {
            "error_id": err[0], "correct_answer": err[1] or "", "explanation": err[2] or "",
            "current_proficiency": err[3],
        },
        "reference_answer": correct_answer,
        "explanation": (err[2] if err and err[2] else ""),
    }})


def _qtype_norm(qtype_raw, content):
    """题型归一：英文 type 直取；缺失/非法按题干启发式映射（question-detail 与 P5 错题练习共用）。"""
    t = (qtype_raw or "").strip()
    if t in _PRAC_TYPES:
        return t
    return {"选择题": "single", "填空题": "fill", "简答题": "short"}.get(_qtype_guess(content or ""), "single")


def _parse_options_json(opts_json):
    """选项 JSON 容错解析：损坏/非数组一律视为无选项（与 search_error_questions 同口径）。"""
    if not opts_json:
        return []
    try:
        o = json.loads(opts_json)
    except (TypeError, ValueError):
        return []
    return o if isinstance(o, list) else []


@bridge_bp.route("/api/knowledge/points/<int:pid>/error-practice", methods=["POST"])
@require_auth
def point_error_practice(pid):
    """P5 错题练习（2026-10-08）：直接取本知识点错题行组卷，不经 LLM（零积分消耗）。

    body: {mode: 'smart', count: N}  按熟练度升序（与练首页错题推荐同口径）取前 N 题
          {mode: 'manual', error_ids: [eid]}  勾选指定错题行
    同一题干多条错题行时去重，取熟练度最低的代表行；无判分基准（correct_answer 空）的行
    跳过并计数返回。题目结构对齐 practice-submit 入参，判分/落库走既有通道。
    """
    body = request.get_json(silent=True) or {}
    raw_mode = body.get("mode")
    if raw_mode is None:
        mode = "smart"
    elif not isinstance(raw_mode, str):  # CodeReview Minor-2：非字符串 mode 返 400 语义而非 500
        return _ok({"success": False, "error": "mode 必须为字符串"})
    else:
        mode = raw_mode.strip()
    if mode not in ("smart", "manual"):
        return _ok({"success": False, "error": "mode 必须为 smart 或 manual"})
    ids = None
    if mode == "smart":
        try:
            n = int(body.get("count", 5))
        except (TypeError, ValueError):
            return _ok({"success": False, "error": "count 必须为整数"})
        n = max(1, min(n, 20))
    else:
        raw_ids = body.get("error_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            return _ok({"success": False, "error": "手动模式需勾选至少一道错题"})
        try:
            ids = [int(x) for x in raw_ids][:20]
        except (TypeError, ValueError):
            return _ok({"success": False, "error": "error_ids 含非法项"})
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        if not conn.execute("SELECT 1 FROM knowledge_points WHERE id = ? AND user_id = ?",
                            (pid, g.user_id)).fetchone():
            return _ok({"success": False, "error": "未找到该知识点"})
        base = ("SELECT eq.id, pr.question_content, pr.question_type, pr.options_json, "
                "eq.correct_answer, eq.explanation, COALESCE(eq.current_proficiency, 0) "
                "FROM error_questions eq JOIN practice_records pr ON eq.practice_record_id = pr.id "
                "WHERE eq.user_id = ? AND eq.knowledge_point_id = ?")
        if ids is not None:
            ph = ",".join("?" * len(ids))
            rows = conn.execute(base + f" AND eq.id IN ({ph}) ORDER BY 7 ASC",
                                (g.user_id, pid, *ids)).fetchall()
        else:
            # 多取一些再 python 层按题干去重，保证去重后仍凑得满 n 题
            rows = conn.execute(base + " ORDER BY 7 ASC, eq.created_time DESC LIMIT 200",
                                (g.user_id, pid)).fetchall()
    finally:
        conn.close()
    seen, questions, skipped = set(), [], 0
    for eid, content, qtype_raw, opts_json, ans, expl, prof in rows:
        content = content or ""
        if content in seen:
            continue  # 同题干只出一题（行已按熟练度升序，先到的是最弱的代表行）
        if mode == "smart" and len(questions) >= n:
            break
        seen.add(content)
        if not (ans or "").strip():
            skipped += 1
            continue
        questions.append({
            "error_id": eid, "question": content,
            "type": _qtype_norm(qtype_raw, content),
            "options": _parse_options_json(opts_json),
            "correct_answer": str(ans).strip(), "explanation": expl or "",
            "difficulty": "中等",
        })
    if not questions:
        return _ok({"success": False, "no_errors": True,
                    "error": "该知识点暂无可判分的错题，先做一轮练习产生错题后再来"})
    return _ok({"success": True, "questions": questions, "skipped_no_answer": skipped})


# ---------------------------------------------------------------- P3 知识点描述编辑（2026-10-09）

DESC_MAX_LEN = 5000  # 手动保存长度上限（防超长脏数据）


@bridge_bp.route("/api/knowledge/points/<int:pid>/description", methods=["PUT"])
@require_auth
def point_description_update(pid):
    """P3 方式1 手动输入：保存 core_description。

    注意：core_description 参与 similarity_matcher 题→知识点匹配，用户改写后匹配口径随之变化。
    """
    body = request.get_json(silent=True) or {}
    desc = body.get("description")
    if not isinstance(desc, str):
        return _ok({"success": False, "error": "description 需为字符串"})
    desc = desc.strip()
    if len(desc) > DESC_MAX_LEN:
        return _ok({"success": False, "error": f"描述过长（上限 {DESC_MAX_LEN} 字）"})
    conn = get_kms().db_manager.get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM knowledge_points WHERE id = ? AND user_id = ?", (pid, g.user_id)).fetchone()
        if not row:
            return _ok({"success": False, "error": "未找到该知识点"})
        conn.execute(
            "UPDATE knowledge_points SET core_description = ? WHERE id = ? AND user_id = ?",
            (desc, pid, g.user_id))
        conn.commit()
    finally:
        conn.close()
    return _ok({"success": True, "core_description": desc})


def _point_note_texts(pid, uid, limit_per_note=20000):
    """知识点关联笔记全文（P3 generate 上下文 / extract 摘取源），读原始 md 文件。"""
    conn = get_kms().db_manager.get_connection()
    try:
        rows = conn.execute(
            "SELECT n.title, n.file_path FROM knowledge_point_sources kps "
            "JOIN notes n ON n.note_uuid = kps.note_uuid "
            "WHERE kps.knowledge_point_id = ? AND n.user_id = ? "
            "ORDER BY kps.extraction_time DESC", (pid, uid)).fetchall()
    finally:
        conn.close()
    texts = []
    for title, fp in rows:
        try:
            p = Path(fp or "")
            if not p.is_file():
                continue
            t = p.read_text(encoding="utf-8", errors="replace")[:limit_per_note]
            if t.strip():
                texts.append({"title": title or "", "text": t})
        except OSError:
            continue
    return texts


def _extract_keyword_paragraphs(point_name, texts, max_paras=8, max_chars=2000):
    """P3 方式3：纯字符串匹配从笔记原文摘含知识点关键字的段落（不调 LLM，忠实原文）。

    关键字 = 知识点名 + 其名切分出的≥ 2 字词段；段落命中任一关键字即摘入，限量防失控。
    """
    kws = [point_name] + [w for w in re.split(r"[\s,，、/()（）\-·]+", point_name or "")
                          if len(w) >= 2 and w != point_name]
    out, total = [], 0
    for item in texts:
        for para in re.split(r"\n\s*\n", item["text"]):
            p = para.strip()
            if len(p) < 10:
                continue
            if any(k and k in p for k in kws):
                out.append(p)
                total += len(p)
                if len(out) >= max_paras or total >= max_chars:
                    return out
    return out


@bridge_bp.route("/api/knowledge/points/<int:pid>/description-assist", methods=["POST"])
@require_auth
def point_description_assist(pid):
    """P3 方式2/3/4：generate=LLM 按名+笔记上下文生成 / extract=笔记关键字摘取（无 LLM）/ polish=LLM 润色。

    只返回建议文本回填前端编辑框，保存仍走 PUT description（用户确认后才写库）。
    """
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action not in ("generate", "extract", "polish"):
        return _ok({"success": False, "error": "action 需为 generate/extract/polish"})
    conn = get_kms().db_manager.get_connection()
    try:
        row = conn.execute(
            "SELECT point_name, core_description, subject_name FROM knowledge_points WHERE id = ? AND user_id = ?",
            (pid, g.user_id)).fetchone()
    finally:
        conn.close()
    if not row:
        return _ok({"success": False, "error": "未找到该知识点"})
    point_name, cur_desc, subject = row[0], (row[1] or ""), (row[2] or "")
    if action == "extract":
        paras = _extract_keyword_paragraphs(point_name, _point_note_texts(pid, g.user_id))
        if not paras:
            return _ok({"success": False, "error": "关联笔记中未找到包含该知识点关键字的段落，可先确认关联笔记或改用其它方式"})
        return _ok({"success": True, "text": "\n\n".join(paras), "llm": False})
    if action == "generate":
        notes = _point_note_texts(pid, g.user_id, limit_per_note=4000)
        ctx = "\n\n".join(f"【{n['title']}】\n{n['text']}" for n in notes)[:8000]
        prompt = (f"请为{subject}学科知识点「{point_name}」写一段简洁明了的核心描述（2-4 句话，纯文本，"
                  f"不要标题/列表/markdown 标记）。可参考以下笔记材料，不要求忠实原文：\n\n{ctx}")
        scene = "知识点描述生成"
    else:
        # 润色基底：前端可传编辑框当前内容（未保存也能量身润色），缺省回退库内描述
        base = body.get("description") if isinstance(body.get("description"), str) and body.get("description").strip() else cur_desc
        if not base.strip():
            return _ok({"success": False, "error": "当前描述为空，请先手动输入或摘取一段内容后再整理"})
        prompt = (f"请润色整理以下知识点「{point_name}」的描述，使其更通顺、结构清晰，保留原意，"
                  f"只输出整理后的描述正文（纯文本）：\n\n{base}")
        scene = "知识点描述润色"
    try:
        resp = _llm_call(prompt, scene)
    except cr.InsufficientCreditsError as e:
        return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
    except Exception as e:  # noqa: BLE001
        # P3 评审：不透传异常原文（LLM 层报错含提供商名/内部 api_url/HTTP 状态码），只落日志
        log.log_error("bridge", "desc_assist_llm_failed", str(e))
        return _ok({"success": False, "error": "AI 处理失败，请稍后重试"})
    if not resp or resp.startswith("LLM调用失败"):
        return _ok({"success": False, "error": "生成失败，请稍后重试"})
    return _ok({"success": True, "text": resp.strip(), "llm": True, **cr.billing_for_response()})


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
    """submitMasteryAssessment：整批折叠为一次 FSRS 复习 → 失效脑图缓存。

    集成线回归（2026-10-01）：不再难度加权直写 mastery_score；每题按 is_correct +
    可选 answer_quality 映射 rating(1-4)，同一知识点一次测评折叠为一次 apply_review
    （批内取最保守 rating，有答错必 Again），避免同日逐题短期路径互相抵消；
    实测正确率封顶 mastery（0929 A 方案：到期前 R≈100 时 0/8 仍显示精通与感知不符）。
    留痕（0929 A 方案补履）：逐题写入练习记录，答错自动入错题池，选项随流水留存。
    """
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
        correct_count = 0
        detailed = []
        ratings = []
        now = F.utcnow()  # 同一批题共用时钟，保证状态机链式推演一致
        for i, (q, a) in enumerate(zip(questions, answers)):
            difficulty = q.get("difficulty") or "中等"
            user_ans = (a or "").strip()
            correct_ans = (q.get("correct_answer") or "").strip()
            is_correct = bool(user_ans) and user_ans.upper() == correct_ans.upper()
            if is_correct:
                correct_count += 1
            rating = F.rating_from_practice(is_correct, q.get("answer_quality"))
            ratings.append(rating)
            detailed.append({
                "question_index": i,
                "question": q.get("question", ""),
                "user_answer": user_ans,
                "correct_answer": correct_ans,
                "is_correct": is_correct,
                "difficulty": difficulty,
                "explanation": q.get("explanation", ""),
                "rating": rating,
            })
            # 9-29 A 方案补履：评估通道同样全量留痕（答对进流水，答错自动入错题池）；选项随流水留存供翻卡复习
            try:
                kms.practice_manager.save_practice_record(
                    subject, pid, q.get("question", ""), user_ans, is_correct,
                    g.user_id, correct_ans, q.get("explanation", ""),
                    question_type="single", options=q.get("options") if isinstance(q.get("options"), list) else None)
            except Exception as e:  # noqa: BLE001
                log.log_error("bridge", "assessment_persist", f"pid={pid} i={i} err={e}")
        # 整批折叠为一次复习（取批内最保守 rating）：有答错→Again，全对按最低质量档
        accuracy = (correct_count / len(questions)) if questions else 0.0
        if ratings:
            F.apply_review("kp", pid, g.user_id, min(ratings), now=now, conn=conn,
                           mastery_cap=round(100 * accuracy))
        conn.commit()
        r2 = conn.execute(
            "SELECT mastery_score FROM knowledge_points WHERE id = ? AND user_id = ?",
            (pid, g.user_id)).fetchone()
        mastery_score = F.mastery_view(r2[0] if r2 else None)
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
            # u7 修复：前端 base.html generateNewPractice 契约要求内层 {success:true, data:{...}}
            # （与 getPracticeHistory 等 Qt 桥方法一致）；旧形状无 success 字段导致成功时也弹
            # “生成新练习失败: 未知错误”并停留空白练习面板（白页）。
            return _ok({
                "success": True,
                "data": {
                    "id": f"TECH-{int(time.time())}",
                    "question": questions,
                    "questions": questions,  # 兼容两种字段名
                    "related_content": "基于最近学习的机器学习基础概念生成",
                    "selectedText": recent_content,
                },
                **cr.billing_for_response(),
            })
        return _ok({"success": False, "error": "生成练习题目失败"})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": str(e) or f"未知异常: {type(e).__name__}"})


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


# ---------------------------------------------------------------- 七、知识点结构化练习（多题型答题模板）
# 业务规则（2026-10-02 用户裁定）：
# - 「基于笔记练习」「举一反三」生成 8 道混合题型题（单选3/判断2/填空2/简答1），
#   页内逐题作答；客观题服务端自动判分，简答题走 LLM 批量判分。
# - 三通道（含熟练度评估）提交后全部落 practice_records，答错经 save_practice_record
#   自动写 error_questions 错题池（2026-09-29 A 方案全量留痕口径）。
# - 掌握度 = 难度加权正确率（与评估同一公式），天然满足实测正确率封顶。

_PRAC_TYPES = {"single", "judge", "fill", "short"}
_JUDGE_TRUE = {"正确", "对", "√", "true", "t", "yes"}
_JUDGE_FALSE = {"错误", "错", "×", "x", "false", "f", "no"}


def _fill_norm(s):
    """填空题答案归一：去空白、小写、全角括号/冒号转半角，便于宽松匹配。"""
    t = "".join(str(s or "").split()).lower()
    return t.translate(str.maketrans("（）：；，－", "():;,-"))


def _judge_norm(s):
    v = "".join(str(s or "").split()).lower()
    if v in _JUDGE_TRUE:
        return "正确"
    if v in _JUDGE_FALSE:
        return "错误"
    return None


def _parse_llm_json_array(response: str):
    """剥 ```json 围栏并解析为数组（与 generate-assessment 同一口径）。"""
    r = (response or "").strip()
    if r.startswith("```json"):
        r = r[7:]
    elif r.startswith("```"):
        r = r[3:]
    if r.endswith("```"):
        r = r[:-3]
    return json.loads(r.strip())


def _validate_practice_questions(questions, expected_n=8):
    """严格校验 N 题逐题结构，归一 correct_answer；非法抛 ValueError。"""
    if not isinstance(questions, list) or len(questions) != expected_n:
        raise ValueError(f"题目数量不正确（应为 {expected_n} 题）")
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ValueError(f"题目{i + 1}格式不完整")
        for key in ("type", "question", "correct_answer", "difficulty", "explanation"):
            if key not in q or not str(q.get(key) or "").strip():
                raise ValueError(f"题目{i + 1}缺少字段 {key}")
        t = q["type"]
        if t not in _PRAC_TYPES:
            raise ValueError(f"题目{i + 1}题型非法: {t}")
        ans = str(q["correct_answer"]).strip()
        if t == "single":
            opts = q.get("options")
            if not isinstance(opts, list) or len(opts) != 4:
                raise ValueError(f"题目{i + 1}选项数量不正确（应为 4 个）")
            if ans[:1].upper() not in "ABCD" or not ans[:1].strip():
                raise ValueError(f"题目{i + 1}正确答案应为 A/B/C/D")
            q["correct_answer"] = ans[:1].upper()
        elif t == "judge":
            nv = _judge_norm(ans)
            if nv is None:
                raise ValueError(f"题目{i + 1}判断题答案非法（应为 正确/错误）")
            q["correct_answer"] = nv
        elif t == "fill":
            if "____" not in str(q["question"]):
                raise ValueError(f"题目{i + 1}填空题干应包含空格 ______")
            if not ans.strip("| ｜").strip():
                raise ValueError(f"题目{i + 1}填空答案为空")
        # short：correct_answer 即参考答案要点，仅要求非空（开头已校验）
    return questions


def _collect_point_notes_text(kms, pid):
    """组装知识点关联笔记正文（最多 5 篇，每篇截 3000 字）；无笔记返回 None。"""
    conn = kms.db_manager.get_connection()
    try:
        rows = conn.execute(
            "SELECT n.title, n.file_name, n.file_path "
            "FROM knowledge_point_sources kps JOIN notes n ON n.note_uuid = kps.note_uuid "
            "WHERE kps.knowledge_point_id = ? AND n.user_id = ? "
            "ORDER BY kps.extraction_time DESC LIMIT 5", (pid, g.user_id)).fetchall()
    finally:
        conn.close()
    blocks = []
    for title, file_name, file_path in rows:
        try:
            p = Path(file_path)
            body = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
        except Exception:  # noqa: BLE001
            body = ""
        body = body.strip()
        if not body:
            continue
        blocks.append(f"【笔记标题】: {title or file_name}\n【笔记内容】:\n{body[:3000]}")
    return "\n\n---\n\n".join(blocks) if blocks else None


def _collect_point_errors_text(kms, pid, error_ids=None, limit=10):
    """组装举一反三错题参考（P5 改造 2026-10-08）。

    默认：本知识点错题按熟练度升序（与错题练习/练首页推荐同口径）取前 limit 题；
    error_ids 指定时：只取勾选行（跨知识点/跨用户的 id 自动被过滤）。
    同题干多行去重；无错题返回 None。
    """
    conn = kms.db_manager.get_connection()
    try:
        head = ("SELECT pr.question_content, COUNT(*) AS practice_count, "
                "SUM(CASE WHEN pr.is_correct = 1 THEN 1 ELSE 0 END) AS correct_count "
                "FROM error_questions eq JOIN practice_records pr ON eq.practice_record_id = pr.id "
                "WHERE eq.user_id = ? AND eq.knowledge_point_id = ?")
        if error_ids:
            ph = ",".join("?" * len(error_ids))
            sql = head + f" AND eq.id IN ({ph}) GROUP BY pr.question_content"
            params = [g.user_id, pid] + list(error_ids)
        else:
            # 按题干聚合后以该题最低熟练度行升序（最弱先复习），取前 limit 题
            sql = (head + " GROUP BY pr.question_content"
                   " ORDER BY MIN(COALESCE(eq.current_proficiency, 0)) ASC LIMIT ?")
            params = [g.user_id, pid, max(1, min(int(limit), 20))]
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    seen, errs = set(), []
    for q, pc, cc in rows:
        pc = pc or 0
        cc = cc or 0
        if not pc or (pc - cc) <= 0 or q in seen:  # 未全对的才算错题；手工模式下聚合行天然含错次
            continue
        seen.add(q)
        errs.append((q, pc, cc))
        if error_ids and len(errs) >= 20:
            break
    if not errs:
        return None
    return "\n\n".join(
        f"【错题{i + 1}】\n题目内容: {q}\n该题曾错 {pc - cc} 次"
        for i, (q, pc, cc) in enumerate(errs))


@bridge_bp.route("/api/knowledge/points/<int:pid>/generate-practice", methods=["POST"])
@require_auth
def point_generate_practice(pid):
    """generatePointPractice：结构化多题型出题（source=notes|analogy），严格 JSON 校验。

    P5 举一反三改造（2026-10-08）：count 参数化题量（默认 8，兼容旧调用）；
    analogy 支持 error_ids 指定错题来源（缺省按熟练度升序智能取前 10 题）。
    """
    body = request.get_json(silent=True) or {}
    source = (body.get("source") or "notes").strip()
    if source not in ("notes", "analogy"):
        return _ok({"success": False, "error": "source 必须为 notes 或 analogy"})
    try:
        n = int(body.get("count", 8))
    except (TypeError, ValueError):
        return _ok({"success": False, "error": "count 必须为整数"})
    n = max(1, min(n, 20))
    err_ids = None
    if source == "analogy" and body.get("error_ids"):
        raw = body.get("error_ids")
        if not isinstance(raw, list):
            return _ok({"success": False, "error": "error_ids 必须为列表"})
        try:
            err_ids = [int(x) for x in raw][:20]
        except (TypeError, ValueError):
            return _ok({"success": False, "error": "error_ids 含非法项"})
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        row = conn.execute(
            "SELECT point_name, core_description, subject_name FROM knowledge_points "
            "WHERE id = ? AND user_id = ?", (pid, g.user_id)).fetchone()
    finally:
        conn.close()
    if not row:
        return _ok({"success": False, "error": "未找到该知识点"})
    point_name, core_desc, subject_name = row[0], row[1], row[2]

    if source == "notes":
        ref_text = _collect_point_notes_text(kms, pid)
        if not ref_text:
            return _ok({"success": False, "no_notes": True,
                        "error": "该知识点暂无关联笔记，无法生成练习"})
        material = ("**关联笔记内容（出题必须严格基于以下原文，不超出范畴）：**\n" + ref_text)
        extra = "题目考点须覆盖笔记中的关键概念与结论。"
    else:
        ref_text = _collect_point_errors_text(kms, pid, error_ids=err_ids)
        if not ref_text:
            return _ok({"success": False, "no_errors": True,
                        "error": "该知识点暂无错题记录，无需举一反三"})
        material = ("**该知识点的错题记录（保持与错题相同的考查点与难度，出类似但不相同的题）：**\n" + ref_text)
        extra = "优先针对错题暴露的薄弱考点设计题目。"

    prompt = f"""请为知识点「{point_name}」（学科：{subject_name}；描述：{core_desc}）生成一套 {n} 道练习题。

{material}

**题型构成（共 {n} 题，按此顺序排列）：**
以选择题为主（约占四成），兼顾判断题、填空题与简答题；任选题型至少 1 道，具体题量按 {n} 酌定。
- 选择题：type="single"，必须有 options 数组（4 个选项），correct_answer 为 A/B/C/D
- 判断题：type="judge"，correct_answer 只能是 "正确" 或 "错误"
- 填空题：type="fill"，题干必须包含一个空格 "______"，correct_answer 为答案文本（若可接受多种写法用 | 分隔，如 "A|B"）
- 简答题：type="short"，correct_answer 为参考答案要点（3-5 个要点）

**每题 JSON 字段：** type, question, options（仅选择题）, correct_answer, difficulty（容易/中等/困难）, explanation（答案解析）
{extra}

只返回 JSON 数组（元素个数必须恰好为 {n}），不要任何其他文字：
[
  {{"type": "single", "question": "...", "options": ["...", "...", "...", "..."], "correct_answer": "A", "difficulty": "容易", "explanation": "..."}}
]"""

    try:
        response = _llm_call(prompt, "知识点结构化练习出题")
    except cr.InsufficientCreditsError as e:
        return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": f"LLM调用失败: {e}"})
    if not response:
        return _ok({"success": False, "error": "LLM调用失败"})
    try:
        questions = _validate_practice_questions(_parse_llm_json_array(response), n)
        return _ok({"success": True, "questions": questions, **cr.billing_for_response()})
    except json.JSONDecodeError:
        log.log_error("bridge", "generate_practice_badjson", f"source={source} pid={pid}")
        return _ok({"success": False, "error": "题目格式解析失败，请重试"})
    except ValueError as e:
        return _ok({"success": False, "error": f"题目格式校验失败: {e}"})


def _call_vision(uid, prompt, images, scene):
    """判分视觉通道包装（2026-10-15 用户裁定：拍照答案判分与错题智能分析同链路）：
    call_llm_vision 统一路由——用户视觉端点优先不扣分 → 系统 VL 兜底扣分，同一计费链。
    独立模块级函数便于单测注入（模式同 _llm_call）。"""
    from llm_provider_factory import call_llm_vision  # 延迟导入避免启动环（同 error_analyze 约定）
    return call_llm_vision(uid, prompt, images, context=scene, scene=scene)


def _resolve_vault_images(uid, *md_texts):
    """从 MD 文本提取 vault 内有效图片并构建 payload（相对路径去重保序）：
    与错题分析同口径 md_image_paths 提取 → _bridge_path 防穿越并校验真实存在；
    2026-10-15 评审 m2/m3/n1：返回 [(rel, payload)] 消下游二次解析与重复 stat，
    空文件/PIL 不可解码的坏图丢弃并留痕（grade_img_unreadable），避免坏图阻断整批判分。"""
    from services import error_analyze as _ea  # 延迟导入（PIL 等重依赖不在启动期加载）
    out, seen = [], set()
    for md in md_texts:
        for rel in _ea.md_image_paths(md or ""):
            if rel in seen:
                continue
            seen.add(rel)
            p = _bridge_path(uid, rel)
            if p is None or not p.is_file():
                log.log_error("bridge", "grade_img_unresolved", f"uid={uid} rel={rel}")
                continue
            try:
                if p.stat().st_size == 0:
                    raise ValueError("空文件")
                _ea.Image.open(p).verify()  # 坏图探测（verify 只校验不解全图）
                payload = _ea._image_payload_items(str(p), _ea._mime_of(rel))
            except Exception as e:  # noqa: BLE001
                log.log_error("bridge", "grade_img_unreadable", f"uid={uid} rel={rel} err={e}")
                continue
            out.append((rel, payload))
    return out


def _grade_short_vision(uid, q, ua, imgs):
    """单题拍照判分（视觉模型看图批改手写过程）：题干/作答内图片附进请求，
    返回 {is_correct, comment}；失败抛异常由调用方整批失败处理（与文本通道同口径，
    判分不成功不落库）。imgs 为 _resolve_vault_images 已解析的 [(rel, payload)]
    （评审 m3/n1：payload 在分流时一次构建，此处直接使用，图片 payload 复用
    error_analyze._image_payload_items 超大图压缩同口径）。"""
    stem = str(q.get("question") or "")[:500]
    ref = str(q.get("correct_answer") or "")[:500]
    expl = str(q.get("explanation") or "")[:500]
    # 文字作答剔除图片引用行（图片已另附 payload，prompt 内留原始 MD 对模型是噪声）；
    # 剔完为空 = 纯照片作答，明确告知以照片为准
    clean = re.sub(r"^\s*!\[[^\]]*\]\(\s*(?:截图|attachments)/[^)\s]*\s*\)\s*$", "",
                   str(ua or ""), flags=re.M).strip()
    ans = (clean or "（无文字作答，解答以照片为准）")[:500]
    images = [pl for _rel, pl in imgs]
    expl_line = ("解析: " + expl + "\n") if expl else ""
    prompt = f"""你是判题助手。学生提交了作答（可能含手写解题过程的照片，共 {len(images)} 张附图，请逐张看清照片中的过程与结论）。
题目: {stem}
参考答案: {ref}
{expl_line}学生文字作答: {ans}
请结合照片内容与文字作答，判断学生答案是否答对（结论与参考答案要点一致即判对，措辞可不同；过程严重不完整或答非所问判错）。
只返回 JSON 数组，例如: [{{"index": 0, "is_correct": true, "comment": "一句中文点评"}}]，不要其他文字："""
    resp = _call_vision(uid, prompt, images, "简答题拍照判分")
    graded = _parse_llm_json_array(resp)
    graded_list = [x for x in graded if isinstance(x, dict)] if isinstance(graded, list) else []
    if not graded_list:
        raise ValueError("判分结果为空")
    return {"is_correct": bool(graded_list[0].get("is_correct")),
            "comment": str(graded_list[0].get("comment") or "")}


def _grade_practice_set(uid, questions, answers, log_tag, ident):
    """判分公共函数（错题学习单元升级 P3 抽取，2026-10-14，计划：禁止复制粘贴；
    2026-10-15 增拍照判分分支）：客观题本地判分 + 简答题分流——
    作答/题干含 vault 图片时走视觉模型看图批改（与错题智能分析同一条 call_llm_vision
    链路与路由计费口径，用户裁定）；纯文字简答仍走 LLM 批量文本判分。
    practice-submit 与 error-set-submit 共用。
    返回 (results, None)；失败返回 (None, err_payload)，调用方 _ok(err_payload) 原样返回。"""
    results = []
    short_items = []
    vision_items = []
    for i, (q, a) in enumerate(zip(questions, answers)):
        t = (q.get("type") or "single") if isinstance(q, dict) else "single"
        user_ans = str(a if a is not None else "").strip()
        correct_raw = str((q.get("correct_answer") if isinstance(q, dict) else "") or "").strip()
        if t == "single":
            ok = bool(user_ans) and user_ans[:1].upper() == correct_raw[:1].upper()
            results.append({"is_correct": ok, "comment": ""})
        elif t == "judge":
            ok = _judge_norm(user_ans) is not None and _judge_norm(user_ans) == _judge_norm(correct_raw)
            results.append({"is_correct": ok, "comment": ""})
        elif t == "fill":
            un = _fill_norm(user_ans)
            ok = bool(un) and any(un == _fill_norm(v) for v in correct_raw.replace("｜", "|").split("|") if v.strip())
            results.append({"is_correct": ok, "comment": ""})
        else:
            # 分流：作答或题干含有效图片引用 → 视觉逐题看图批改；否则文字批量判分
            # （payload 在此一次解析，随 vision_items 下传，避免重复提图/解码）
            imgs = _resolve_vault_images(uid, user_ans, str(q.get("question") or ""))
            if imgs:
                vision_items.append((i, q, user_ans, imgs))
            else:
                short_items.append((i, q, user_ans))
            results.append({"is_correct": False, "comment": ""})  # 占位，稍后由 LLM 判分覆盖

    # 拍照判分（评审 m1：视觉先跑）：逐题视觉批改，任一题失败即整批失败不落库。
    # 先于文字批量是为了：若文本通道已扣分后视觉才失败，已扣不退会造成计费泄漏；
    # 视觉先失败则整批未进文字通道，与「整批失败不落库」语义一致。
    for idx, q, ua, imgs in vision_items:
        try:
            results[idx] = _grade_short_vision(uid, q, ua, imgs)
        except cr.InsufficientCreditsError as e:
            return None, {"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance}
        except Exception as e:  # noqa: BLE001
            log.log_error("bridge", log_tag, f"{ident} vision idx={idx} err={e}")
            return None, {"success": False, "error": f"拍照答案判分失败，请重试: {e}"}

    if short_items:
        lines = "\n\n".join(
            f"[题序{j}]\n题目: {str(q.get('question') or '')[:500]}\n参考答案: {str(q.get('correct_answer') or '')[:500]}\n学生答案: {(ua or '（未作答）')[:500]}"
            for j, (idx, q, ua) in enumerate([(si[0], si[1], si[2]) for si in short_items]))
        grade_prompt = f"""你是判题助手。请逐题判断简答题学生答案是否答对（与参考答案要点一致即可，措辞可不同；漏掉多数要点或答非所问判错）。

{lines}

只返回 JSON 数组（每项含 index=题序、is_correct=布尔、comment=一句中文点评），不要其他文字：
[{{"index": 0, "is_correct": true, "comment": "..."}}]"""
        try:
            resp = _llm_call(grade_prompt, "简答题LLM判分")
            graded = _parse_llm_json_array(resp)
            graded_list = [g for g in graded if isinstance(g, dict)] if isinstance(graded, list) else []
            # m-1: LLM 返回的 index 可能错位（1 基/越界/缺失），按 index 排序后按位置对齐回写，避免静默判错
            try:
                graded_list.sort(key=lambda g: int(g.get("index", 0)))
            except (TypeError, ValueError):
                pass
            if len(graded_list) < len(short_items):
                raise ValueError("判分结果不完整")
            for (idx, _q, _ua), g_item in zip(short_items, graded_list):
                results[idx] = {"is_correct": bool(g_item.get("is_correct")),
                                "comment": str(g_item.get("comment") or "")}
        except cr.InsufficientCreditsError as e:
            return None, {"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance}
        except Exception as e:  # noqa: BLE001
            log.log_error("bridge", log_tag, f"{ident} err={e}")
            return None, {"success": False, "error": f"简答题判分失败，请重试: {e}"}

    return results, None


@bridge_bp.route("/api/knowledge/points/<int:pid>/practice-submit", methods=["POST"])
@require_auth
def point_practice_submit(pid):
    """submitPointPractice：多题型判分（客观题本地、简答题 LLM）→ 全量落库 → 整批折叠一次 FSRS 复习更新掌握度。"""
    body = request.get_json(silent=True) or {}
    questions = body.get("questions") or []
    answers = body.get("answers") or []
    if not isinstance(questions, list) or not questions or len(questions) != len(answers):
        return _ok({"success": False, "error": "题目和答案数量不匹配"})
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        # 错题学习单元升级 P2：随学科一并取知识点重要度，答错入池时继承（用户裁定）
        row = conn.execute(
            "SELECT subject_name, importance_score FROM knowledge_points WHERE id = ? AND user_id = ?",
            (pid, g.user_id)).fetchone()
    finally:
        conn.close()
    if not row:
        return _ok({"success": False, "error": "未找到该知识点"})
    subject = row[0]
    kp_importance = float(row[1]) if len(row) > 1 and row[1] is not None else 5.0

    # ---- 1)+2) 判分（P3 抽公共函数：客观题本地 + 简答题 LLM 批量，与 error-set-submit 同一实现） ----
    results, grade_err = _grade_practice_set(g.user_id, questions, answers, "practice_short_grade", f"pid={pid}")
    if grade_err is not None:
        return _ok(grade_err)

    # ---- 3) 全量落库：practice_records 流水 + 答错自动入 error_questions 错题池；逐题收集 rating ----
    correct_count = 0
    detailed = []
    ratings = []
    now = F.utcnow()  # 同一批题共用时钟（整批折叠为一次复习）
    for i, (q, a) in enumerate(zip(questions, answers)):
        difficulty = (q.get("difficulty") if isinstance(q, dict) else "") or "中等"
        ok = results[i]["is_correct"]
        if ok:
            correct_count += 1
        ratings.append(F.rating_from_practice(ok))
        user_ans = str(a if a is not None else "").strip()
        q_text = str((q.get("question") if isinstance(q, dict) else "") or "")
        c_ans = str((q.get("correct_answer") if isinstance(q, dict) else "") or "")
        expl = str((q.get("explanation") if isinstance(q, dict) else "") or "")
        try:
            kms.practice_manager.save_practice_record(
                subject, pid, q_text, user_ans, ok, g.user_id, c_ans, expl,
                question_type=(q.get("type") if isinstance(q, dict) else "") or "",
                options=(q.get("options") if isinstance(q, dict) and isinstance(q.get("options"), list) else None),
                # P2 继承（用户裁定）：难度按出题标注映射、重要度取知识点当前值；入池同题不堆行由同一函数内部处理
                difficulty_score=difficulty_label_to_score(difficulty),
                importance_score=kp_importance)
        except Exception as e:  # noqa: BLE001
            log.log_error("bridge", "practice_persist", f"pid={pid} i={i} err={e}")
        detailed.append({
            "question_index": i, "question": q_text, "type": (q.get("type") if isinstance(q, dict) else "single"),
            "user_answer": user_ans, "correct_answer": c_ans, "is_correct": ok,
            "difficulty": difficulty, "explanation": expl, "comment": results[i]["comment"],
            "rating": ratings[i],
        })

    # ---- 4) 整批折叠为一次 FSRS 复习（与评估同口径）：取批内最保守 rating，实测正确率封顶 ----
    accuracy = (correct_count / len(questions)) if questions else 0.0
    mastery_updated = True
    mastery_score = -1
    conn = kms.db_manager.get_connection()
    try:
        if ratings:
            F.apply_review("kp", pid, g.user_id, min(ratings), now=now, conn=conn,
                           mastery_cap=round(100 * accuracy))
        conn.commit()
        r2 = conn.execute(
            "SELECT mastery_score FROM knowledge_points WHERE id = ? AND user_id = ?",
            (pid, g.user_id)).fetchone()
        mastery_score = F.mastery_view(r2[0] if r2 else None)
    except Exception as e:  # noqa: BLE001
        # m-4: 留痕已逐题提交，掌握度写回失败不冒泡 500（否则用户重试会双留痕），标记降级供前端辨识
        mastery_updated = False
        log.log_error("bridge", "practice_mastery_update", f"pid={pid} err={e}")
    finally:
        conn.close()
    try:
        kms.clear_mindmap_cache(subject, user_id=g.user_id)
    except Exception:  # noqa: BLE001
        pass
    log.log("api", "practice_submit", "success",
            {"pid": pid, "source_types": [q.get("type") for q in questions if isinstance(q, dict)],
             "correct": correct_count, "total": len(questions), "mastery": mastery_score})
    return _ok({
        "success": True, "mastery_score": mastery_score, "mastery_updated": mastery_updated,
        "correct_count": correct_count, "total_count": len(questions),
        "accuracy": accuracy, "detailed_results": detailed,
        **cr.billing_for_response(),
    })


# ---------------------------------------------------------------- 错题学习单元升级 P3（2026-10-14）：科目级错题练习闭环
# 与 pid 版 error-practice/generate-practice/practice-submit 并存，pid 版行为不动（计划兼容裁定）。

def _difficulty_label(score):
    """0-10 存储分 → 出题标注标签（difficulty_label_to_score 的逆映射，按 P2 裁定三档）。"""
    v = float(score) if score is not None else 5.0
    if v <= 4.0:
        return "容易"
    if v <= 6.5:
        return "中等"
    return "困难"


def _fetch_error_pool_rows(kms, uid, subject=None, ids=None, limit=200):
    """错题池候选行（与错题列表同构：行 JOIN 其首条流水取题干），含 FSRS 状态与双星。
    返回 dict 列表：eid/content/qtype/options/correct/expl/prof/kp_id/subject/difficulty_score/importance_score/state。"""
    conn = kms.db_manager.get_connection()
    try:
        base = ("SELECT eq.id, pr.question_content, pr.question_type, pr.options_json, "
                "eq.correct_answer, eq.explanation, COALESCE(eq.current_proficiency, 0), "
                "eq.knowledge_point_id, eq.subject_name, eq.difficulty_score, eq.importance_score, "
                "pr.user_answer "
                "FROM error_questions eq JOIN practice_records pr ON eq.practice_record_id = pr.id "
                "WHERE eq.user_id = ?")
        params = [uid]
        if subject:
            base += " AND eq.subject_name = ?"
            params.append(subject)
        if ids is not None:
            ph = ",".join("?" * len(ids))
            base += f" AND eq.id IN ({ph})"
            params.extend(ids)
        base += " ORDER BY eq.id DESC LIMIT ?"
        params.append(int(limit))
        rows = conn.execute(base, tuple(params)).fetchall()
        out = []
        for r in rows:
            out.append({
                "eid": r[0], "content": r[1] or "", "qtype": r[2], "options": _parse_options_json(r[3]),
                "correct": str(r[4] or "").strip(), "expl": r[5] or "", "prof": r[6],
                "kp_id": r[7], "subject": r[8],
                "difficulty_score": float(r[9]) if r[9] is not None else 5.0,
                "importance_score": float(r[10]) if r[10] is not None else 5.0,
                "user_answer": r[11] or "",
                "state": F.load_state(conn, "error", r[0], uid),
            })
        return out
    finally:
        conn.close()


def _pool_question(row):
    """错题行 → 练习题目结构（对齐 practice-submit/error-set-submit 入参，携 error_id/kp_id）。"""
    return {
        "error_id": row["eid"], "kp_id": row["kp_id"], "question": row["content"],
        "type": _qtype_norm(row["qtype"], row["content"]), "options": row["options"],
        "correct_answer": row["correct"], "explanation": row["expl"],
        "difficulty": _difficulty_label(row["difficulty_score"]),
        "difficulty_score": row["difficulty_score"], "importance_score": row["importance_score"],
    }


@bridge_bp.route("/api/practice/error-pool", methods=["POST"])
@require_auth
def practice_error_pool():
    """科目级错题组卷（零积分）：mode smart|manual|single。

    smart：FSRS 三因子排序组卷（R 升→重要度降→难度升，用户裁定替代熟练度升序），复用
           F.build_sprint_pool；同题干去重取排序首位代表行；
    manual：勾选 error_ids（≤20 题）；single：error_id 单题「练这题」。
    题目结构对齐 error-set-submit 入参（每题带 error_id、kp_id）；无判分基准行跳过并计数。"""
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject") or body.get("subject_name") or "").strip()
    if not subject:
        return _ok({"success": False, "error": "subject 必填"})
    mode = (body.get("mode") or "smart").strip()
    if mode not in ("smart", "manual", "single"):
        return _ok({"success": False, "error": "mode 必须为 smart、manual 或 single"})
    kms = get_kms()
    ids = None
    n = 5
    if mode == "smart":
        try:
            n = max(1, min(int(body.get("count", 5)), 20))
        except (TypeError, ValueError):
            return _ok({"success": False, "error": "count 必须为整数"})
    elif mode == "manual":
        raw = body.get("error_ids")
        if not isinstance(raw, list) or not raw:
            return _ok({"success": False, "error": "手动模式需勾选至少一道错题"})
        try:
            ids = [int(x) for x in raw][:20]
        except (TypeError, ValueError):
            return _ok({"success": False, "error": "error_ids 含非法项"})
    else:
        try:
            ids = [int(body.get("error_id"))]
        except (TypeError, ValueError):
            return _ok({"success": False, "error": "error_id 必须为整数"})
    rows = _fetch_error_pool_rows(kms, g.user_id, subject, ids)
    if ids is not None and len({r["eid"] for r in rows}) != len(set(ids)):
        return _ok({"success": False, "error": "部分错题不存在或不属于该学科/用户"})
    if mode == "smart":
        rows = F.build_sprint_pool(rows, len(rows))  # 三因子全量排序，去重后取前 n
    seen, questions, skipped = set(), [], 0
    for row in rows:
        if row["content"] in seen:
            continue
        seen.add(row["content"])
        if mode == "smart" and len(questions) >= n:
            break
        if not row["correct"]:
            skipped += 1
            continue
        questions.append(_pool_question(row))
    if not questions:
        return _ok({"success": False, "no_errors": True,
                    "error": "该学科暂无可判分的错题，先做一轮练习产生错题后再来"})
    log.log("api", "error_pool", "success", {"mode": mode, "picked": len(questions), "skipped": skipped})
    return _ok({"success": True, "questions": questions, "skipped_no_answer": skipped})


@bridge_bp.route("/api/practice/error-set-submit", methods=["POST"])
@require_auth
def practice_error_set_submit():
    """跨知识点错题混合卷提交（P3）：判分复用 _grade_practice_set，禁止复制。

    questions[] 携 error_id（重练=该行本身；举一反三派生=root_error_id）与可选 kp_id。
    逐题：流水挂回错题（save_practice_record error_question_id）+ 错题行 FSRS 更新（'error' 逐题 apply，
    练和记都调熟练度：对→升错→降）；答错按裁定：重练不重复入池，派生新题干照常入池（pool_new_on_wrong）；
    kp 掌握度按知识点分组折叠更新（与 pid 版同口径：min(ratings) + 组内实测正确率封顶）。"""
    body = request.get_json(silent=True) or {}
    questions = body.get("questions") or []
    answers = body.get("answers") or []
    if not isinstance(questions, list) or not questions or len(questions) != len(answers):
        return _ok({"success": False, "error": "题目和答案数量不匹配"})
    subject = (body.get("subject_name") or body.get("subject") or "").strip()
    kms = get_kms()
    # root 行缓存：一次查清本批涉及的错题行，供学科/kp/继承值/重练 vs 派生判定
    root_ids = []
    for q in questions:
        if isinstance(q, dict):
            try:
                v = q.get("error_id") or q.get("root_error_id")
                if v is not None:
                    root_ids.append(int(v))
            except (TypeError, ValueError):
                continue
    roots = {r["eid"]: r for r in _fetch_error_pool_rows(kms, g.user_id, None, root_ids or None)} if root_ids else {}
    if not root_ids and not subject:
        return _ok({"success": False, "error": "无错题归属时 subject_name 必填"})
    # 评审 m-2：提供的 error_id 必须全部归属本人（与 error-pool 非法 id 拦截同口径），
    # 防全为 foreign eid 时落入 subject_name="" 的孤儿流水
    if root_ids and len(roots) != len(set(root_ids)):
        return _ok({"success": False, "error": "部分错题不存在或不属于当前用户"})

    results, grade_err = _grade_practice_set(g.user_id, questions, answers, "error_set_grade", f"subject={subject}")
    if grade_err is not None:
        return _ok(grade_err)

    correct_count = 0
    detailed = []
    now = F.utcnow()
    kp_groups = {}  # kp_id -> {ratings, correct, total}（整组折叠一次复习，与 pid 版同口径）
    for i, (q, a) in enumerate(zip(questions, answers)):
        q = q if isinstance(q, dict) else {}
        ok = results[i]["is_correct"]
        if ok:
            correct_count += 1
        try:
            eid = int(q.get("error_id") or q.get("root_error_id") or 0) or None
        except (TypeError, ValueError):
            eid = None
        root = roots.get(eid)
        kp_id = q.get("kp_id")
        if kp_id is None and root is not None:
            kp_id = root["kp_id"]
        q_text = str(q.get("question") or "")
        # 派生判定：题干与 root 原题不同 ⇒ 举一反三派生题（答错照常入池；重练则同题不堆行）
        derived = bool(root) and q_text.strip() != root["content"].strip()
        rating = F.rating_from_practice(ok)
        user_ans = str(a if a is not None else "").strip()
        c_ans = str(q.get("correct_answer") or "")
        expl = str(q.get("explanation") or "")
        q_subj = root["subject"] if root else subject
        try:
            kms.practice_manager.save_practice_record(
                q_subj, kp_id, q_text, user_ans, ok, g.user_id, c_ans, expl,
                question_type=str(q.get("type") or ""),
                options=q.get("options") if isinstance(q.get("options"), list) else None,
                # 入池继承：难度按题目标注映射，重要度继承来源错题行（=所属知识点链路）；无 root 时缺省 5.0
                difficulty_score=difficulty_label_to_score(q.get("difficulty")),
                importance_score=root["importance_score"] if root else None,
                error_question_id=eid,
                pool_new_on_wrong=derived)
        except Exception as e:  # noqa: BLE001
            log.log_error("bridge", "error_set_persist", f"i={i} eid={eid} err={e}")
        # 错题行 FSRS：重练/派生题都算对 root 记忆的提取（举一反三为复习 root 而生）
        if eid is not None:
            try:
                F.apply_review("error", eid, g.user_id, rating, now=now)
            except Exception as e:  # noqa: BLE001
                log.log_error("bridge", "error_set_error_fsrs", f"eid={eid} err={e}")
        if kp_id is not None:
            # 评审 M-1：kp_id 客户端可控，非法值不走 kp 分组（流水照常），避免裸 int() 炸 500 半批提交
            try:
                kp_key = int(kp_id)
            except (TypeError, ValueError):
                kp_key = None
            if kp_key is not None:
                grp = kp_groups.setdefault(kp_key, {"ratings": [], "correct": 0, "total": 0})
                grp["ratings"].append(rating)
                grp["total"] += 1
                grp["correct"] += 1 if ok else 0
        detailed.append({
            "question_index": i, "question": q_text, "type": str(q.get("type") or "single"),
            "user_answer": user_ans, "correct_answer": c_ans, "is_correct": ok,
            "difficulty": str(q.get("difficulty") or ""), "explanation": expl,
            "comment": results[i]["comment"], "rating": rating,
            "error_id": eid, "derived": derived,
        })

    # ---- kp 分组折叠更新 + 回读展示值 ----
    # 评审 m-1：不共享事务（与 error FSRS 循环同口径）：单条失败不污染 PG aborted 事务、
    # 不回滚同批已成功的 kp 更新；回读用独立连接
    kp_mastery = {}
    for kp_id, grp in kp_groups.items():
        if not grp["ratings"]:
            continue
        acc = grp["correct"] / grp["total"]
        try:
            F.apply_review("kp", kp_id, g.user_id, min(grp["ratings"]), now=now,
                           mastery_cap=round(100 * acc))
        except Exception as e:  # noqa: BLE001
            log.log_error("bridge", "error_set_kp_update", f"kp={kp_id} err={e}")
    if kp_groups:
        conn = kms.db_manager.get_connection()
        try:
            for kp_id in kp_groups:
                r2 = conn.execute(
                    "SELECT mastery_score FROM knowledge_points WHERE id = ? AND user_id = ?",
                    (kp_id, g.user_id)).fetchone()
                kp_mastery[str(kp_id)] = F.mastery_view(r2[0] if r2 else None)
        finally:
            conn.close()
    touched_subjects = {roots[e]["subject"] for e in root_ids if e in roots} | ({subject} if subject else set())
    for s in touched_subjects:
        try:
            kms.clear_mindmap_cache(s, user_id=g.user_id)
        except Exception:  # noqa: BLE001
            pass
    accuracy = correct_count / len(questions)
    log.log("api", "error_set_submit", "success",
            {"subject": subject, "correct": correct_count, "total": len(questions), "kps": len(kp_groups)})
    return _ok({
        "success": True, "correct_count": correct_count, "total_count": len(questions),
        "accuracy": accuracy, "detailed_results": detailed, "kp_mastery": kp_mastery,
        **cr.billing_for_response(),
    })


@bridge_bp.route("/api/practice/analogy", methods=["POST"])
@require_auth
def practice_analogy():
    """举一反三统一出题（行级/页级/报告薄弱点复用，耗积分同现有出题口径）。

    body {subject, error_ids?, count?(默认 5，上限 10), point?, source_text?}
    - error_ids：素材=错题题干+正确答案+解析+所属知识点描述（独立错题 kp 留 NULL）；
    - point/source_text：报告薄弱点节点直接传素材（P4 闭环），root 归属置空。
    每题回填 root_error_id（优先 LLM 标注的合法 source_error_id，否则轮转分配）+ kp_id（root 的知识点）；
    提交复用 error-set-submit（派生题答错照常入池）。"""
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject") or body.get("subject_name") or "").strip()
    if not subject:
        return _ok({"success": False, "error": "subject 必填"})
    try:
        n = max(1, min(int(body.get("count", 5)), 10))
    except (TypeError, ValueError):
        return _ok({"success": False, "error": "count 必须为整数"})
    raw_ids = body.get("error_ids")
    ids = None
    if raw_ids:
        if not isinstance(raw_ids, list):
            return _ok({"success": False, "error": "error_ids 必须为列表"})
        try:
            ids = [int(x) for x in raw_ids][:10]
        except (TypeError, ValueError):
            return _ok({"success": False, "error": "error_ids 含非法项"})
    kms = get_kms()
    rows, roots, row_map = [], [], {}
    if ids:
        rows = _fetch_error_pool_rows(kms, g.user_id, subject, ids)
        if len({r["eid"] for r in rows}) != len(set(ids)):
            return _ok({"success": False, "error": "部分错题不存在或不属于该学科"})
        conn = kms.db_manager.get_connection()
        try:
            kp_ids = sorted({r["kp_id"] for r in rows if r["kp_id"] is not None})
            kp_info = {}
            if kp_ids:
                ph = ",".join("?" * len(kp_ids))
                for kid, name, desc in conn.execute(
                        f"SELECT id, point_name, COALESCE(core_description, '') FROM knowledge_points "
                        f"WHERE user_id = ? AND id IN ({ph})", (g.user_id, *kp_ids)):
                    kp_info[kid] = (name, desc)
        finally:
            conn.close()
        lines = []
        for r in rows:
            name, desc = kp_info.get(r["kp_id"], ("（独立错题，无所属知识点）", ""))
            lines.append(f"- 错题ID {r['eid']}｜知识点：{name}｜{str(desc)[:200]}\n"
                         f"  题干：{r['content'][:500]}\n  正确答案：{r['correct'][:300]}\n  解析：{str(r['expl'])[:500]}")
        roots = [r["eid"] for r in rows]
        row_map = {r["eid"]: r for r in rows}
        material = ("**错题记录（保持与错题相同的考查点与难度，出类似但不相同的题，禁止抄原题题干）：**\n"
                    + "\n".join(lines))
        extra = "优先针对错题暴露的薄弱考查点设计题目；每题必须用 source_error_id 标注它针对上面哪道错题ID举一反三。"
        # P4 报告闭环：薄弱点节点「针对练习」同时带 point，素材前置该薄弱点聚焦出题
        pt = (body.get("point") or "").strip()
        if pt:
            material = f"**针对薄弱点：**{pt[:200]}\n" + material
    else:
        point = (body.get("point") or "").strip()
        st = (body.get("source_text") or "").strip()
        if not point and not st:
            return _ok({"success": False, "error": "error_ids 与 point/source_text 至少给一组"})
        material = f"**薄弱点：**{point[:200]}\n**相关素材（错题题干与解析）：**\n{st[:4000]}"
        extra = "围绕该薄弱点出类似但不同的针对性练习题；可省略 source_error_id。"

    sid_line = "，并额外包含 source_error_id（整数，取自素材中的错题ID）" if roots else ""
    prompt = f"""请基于以下素材，为学科「{subject}」举一反三生成 {n} 道针对性练习题。

{material}

**题型构成（共 {n} 题，按此顺序排列）：**
以选择题为主（约占四成），兼顾判断题、填空题与简答题；任选题型至少 1 道，具体题量按 {n} 酌定。
- 选择题：type="single"，必须有 options 数组（4 个选项），correct_answer 为 A/B/C/D
- 判断题：type="judge"，correct_answer 只能是 "正确" 或 "错误"
- 填空题：type="fill"，题干必须包含一个空格 "______"，correct_answer 为答案文本（若可接受多种写法用 | 分隔，如 "A|B"）
- 简答题：type="short"，correct_answer 为参考答案要点（3-5 个要点）

**每题 JSON 字段：** type, question, options（仅选择题）, correct_answer, difficulty（容易/中等/困难）, explanation（答案解析）{sid_line}
{extra}

只返回 JSON 数组（元素个数必须恰好为 {n}），不要任何其他文字：
[
  {{"type": "single", "question": "...", "options": ["...", "...", "...", "..."], "correct_answer": "A", "difficulty": "容易", "explanation": "..."}}
]"""
    try:
        response = _llm_call(prompt, "举一反三针对性出题")
    except cr.InsufficientCreditsError as e:
        return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
    except Exception as e:  # noqa: BLE001
        return _ok({"success": False, "error": f"LLM调用失败: {e}"})
    if not response:
        return _ok({"success": False, "error": "LLM调用失败"})
    try:
        questions = _validate_practice_questions(_parse_llm_json_array(response), n)
    except json.JSONDecodeError:
        log.log_error("bridge", "analogy_badjson", f"subject={subject} ids={bool(ids)}")
        return _ok({"success": False, "error": "题目格式解析失败，请重试"})
    except ValueError as e:
        return _ok({"success": False, "error": f"题目格式校验失败: {e}"})
    # root 归属回填：LLM 标注合法优先，否则按题序轮转分配（页面级多错题时均匀覆盖）
    for i, q in enumerate(questions):
        try:
            rid = int(q.pop("source_error_id", None))
        except (TypeError, ValueError):
            rid = None
        if rid not in row_map:
            rid = roots[i % len(roots)] if roots else None
        q["root_error_id"] = rid
        q["error_id"] = rid  # error-set-submit 统一入参字段（语义=root）
        q["kp_id"] = row_map[rid]["kp_id"] if rid in row_map else None
    log.log("api", "analogy", "success", {"subject": subject, "count": n, "roots": len(roots)})
    return _ok({"success": True, "questions": questions, **cr.billing_for_response()})


# ---------------- P4：薄弱点分析报告（生成/列表/详情） ----------------

def _report_material_items(kms, uid, rows):
    """错题行 → 报告素材（题干/我的答案/正确答案/解析 + 知识点名）。"""
    conn = kms.db_manager.get_connection()
    try:
        kp_ids = sorted({r["kp_id"] for r in rows if r["kp_id"] is not None})
        names = {}
        if kp_ids:
            ph = ",".join("?" * len(kp_ids))
            for kid, nm in conn.execute(
                    f"SELECT id, point_name FROM knowledge_points WHERE user_id = ? AND id IN ({ph})",
                    (uid, *kp_ids)):
                names[kid] = nm
    finally:
        conn.close()
    return [{"error_id": r["eid"], "kp_name": names.get(r["kp_id"], ""),
             "question": r["content"], "user_answer": r["user_answer"],
             "correct": r["correct"], "explanation": r["expl"]} for r in rows]


@bridge_bp.route("/api/practice/weakness-report", methods=["POST"])
@require_auth
def practice_weakness_report():
    """生成薄弱点分析报告：scope=global 全学科错题 / selected 勾选 error_ids。

    LLM 结构化输出严格校验（services.weakness_report），校验失败**不落库**；
    耗积分同现有 LLM 口径（billing_for_response）；报告范围=当前学科（裁定）。"""
    body = request.get_json(silent=True) or {}
    subject = (body.get("subject") or body.get("subject_name") or "").strip()
    if not subject:
        return _ok({"success": False, "error": "subject 必填"})
    scope = (body.get("scope") or "global").strip()
    if scope not in ("global", "selected"):
        return _ok({"success": False, "error": "scope 只能是 global 或 selected"})
    ids = None
    if scope == "selected":
        raw_ids = body.get("error_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            return _ok({"success": False, "error": "scope=selected 需 error_ids 列表"})
        try:
            ids = [int(x) for x in raw_ids][:60]
        except (TypeError, ValueError):
            return _ok({"success": False, "error": "error_ids 含非法项"})
    kms = get_kms()
    rows = _fetch_error_pool_rows(kms, g.user_id, subject, ids)
    if ids is not None and len({r["eid"] for r in rows}) != len(set(ids)):
        return _ok({"success": False, "error": "部分错题不存在或不属于该学科"})
    if not rows:
        return _ok({"success": False, "error": "该学科还没有可用于分析的错题"})
    items = _report_material_items(kms, g.user_id, rows)
    from services import weakness_report as WR  # 延迟导入避免启动环
    try:
        rep = WR.generate_report(subject, items, lambda p: _llm_call(p, "错题薄弱点分析报告"))
    except cr.InsufficientCreditsError as e:
        return _ok({"success": False, "error": str(e), "credits_insufficient": True, "credit_balance": e.balance})
    except ValueError as e:  # JSON/结构校验失败：诚实报错，不产生半成品报告
        log.log_error("bridge", "weakness_report_badjson", f"subject={subject}: {e}")
        return _ok({"success": False, "error": f"解析结果格式校验失败：{e}"})
    except Exception as e:  # noqa: BLE001
        log.log_error("bridge", "weakness_report_failed", e)
        return _ok({"success": False, "error": f"生成失败，请稍后重试：{str(e)[:120]}"})
    conn = kms.db_manager.get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO weakness_reports (user_id, subject_name, scope, error_ids, report_md, mindmap_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(g.user_id), subject, scope, json.dumps([it["error_id"] for it in items]),
             rep["summary_md"], json.dumps(rep["nodes"], ensure_ascii=False)))
        rid = cur.lastrowid
        conn.commit()
        cur.close()
    finally:
        conn.close()
    log.log("api", "weakness_report", "success", {"subject": subject, "scope": scope, "errors": len(items)})
    return _ok({"success": True, "report_id": rid, "report_md": rep["summary_md"],
                "nodes": rep["nodes"], "error_count": len(items), **cr.billing_for_response()})


@bridge_bp.route("/api/practice/weakness-reports", methods=["GET"])
@require_auth
def practice_weakness_reports():
    """报告列表（科目内按分析日期倒序）：id/范围/来源错题数/摘要/时间。"""
    subject = (request.args.get("subject") or "").strip()
    if not subject:
        return _ok({"success": False, "error": "subject 必填"})
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, scope, error_ids, report_md, created_time FROM weakness_reports "
            "WHERE user_id = ? AND subject_name = ? ORDER BY created_time DESC, id DESC LIMIT 100",
            (str(g.user_id), subject)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            nerr = len(json.loads(r[2] or "[]"))
        except (TypeError, ValueError):
            nerr = 0
        preview = re.sub(r"[#*`>\-]+", "", str(r[3] or "")).strip().replace("\n", " ")[:80]
        out.append({"id": r[0], "scope": r[1], "error_count": nerr,
                    "preview": preview, "created_time": r[4]})
    return _ok({"success": True, "reports": out})


@bridge_bp.route("/api/practice/weakness-report/<int:report_id>", methods=["GET"])
@require_auth
def practice_weakness_report_detail(report_id):
    """报告详情：文字报告 MD + 脑图 nodes（双重隔离：id+user_id）。"""
    kms = get_kms()
    conn = kms.db_manager.get_connection()
    try:
        r = conn.execute(
            "SELECT id, subject_name, scope, error_ids, report_md, mindmap_json, created_time "
            "FROM weakness_reports WHERE id = ? AND user_id = ?", (report_id, str(g.user_id))).fetchone()
    finally:
        conn.close()
    if not r:
        return _ok({"success": False, "error": "报告不存在"})
    try:
        nodes = json.loads(r[5] or "[]")
    except (TypeError, ValueError):
        nodes = []
    try:
        eids = json.loads(r[3] or "[]")
    except (TypeError, ValueError):
        eids = []
    return _ok({"success": True, "report": {"id": r[0], "subject": r[1], "scope": r[2],
                "error_ids": eids, "report_md": r[4], "nodes": nodes, "created_time": r[6]}})
