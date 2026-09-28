# -*- coding: utf-8 -*-
"""二期：学习笔记正文入库 + 实时自动保存 + 录制状态端点。

设计（对应方案《悬浮窗与主面板录音笔记二期》）：
- MD 文件仍落盘（回退保险），正文同时 upsert 进用户隔离的 notes 表，**库为轮询权威源**；
- 悬浮窗/主面板录音端防抖调用 /api/notes/autosave；主面板每 4s 轮询 /api/notes/content；
- /api/notes/recording 置/清录制中标识，横幅与 /api/notes/active 据此显示"正在保存到 <doc>"；
- 所有路径经 _bridge_path 校验必须位于当前用户 vault root 内（P1 隔离语义延续）。
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from flask import Blueprint, g, request

from auth import require_auth
import credits_service as cr
from logger_module import debug_logger as log
from routes_bridge import _bridge_path, _llm_call, _rel_to_root
from routes_knowledge import _ok, _err, get_kms

notes_bp = Blueprint("notes", __name__)

_MD_EXT = {".md", ".markdown", ".txt"}


@notes_bp.route("/api/notes/autosave", methods=["POST"])
@require_auth
def notes_autosave():
    """实时自动保存：写 MD 文件 + 正文入库。body {path, content, title?}。"""
    body = request.get_json(silent=True) or {}
    target = _bridge_path(g.user_id, body.get("path") or "")
    if target is None:
        return _err("非法路径", 403)
    content = body.get("content") or ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.log_error("notes", "autosave_write_failed", str(e))
        return _ok({"success": False, "error": f"文件写入失败: {e}"})
    r = get_kms().upsert_note_content(g.user_id, str(target), content, title=body.get("title"))
    if r.get("error"):
        log.log_error("notes", "autosave_db_failed", r["error"])
        return _ok({"success": False, "error": r["error"]})
    return _ok({"success": True, "rel_path": _rel_to_root(target, g.user_id),
                "updated_time": r["updated_time"], "note_id": r["note_id"],
                "note_uuid": r.get("note_uuid")})


@notes_bp.route("/api/notes/content", methods=["GET"])
@require_auth
def notes_content():
    """轮询读取笔记正文（库优先，无记录回退文件）。?path= 绝对或 vault 相对。"""
    target = _bridge_path(g.user_id, request.args.get("path") or "")
    if target is None:
        return _err("非法路径", 403)
    rec = get_kms().get_note_record(g.user_id, str(target))
    if rec is not None and rec[3] is not None:
        # (id, note_uuid, title, content, word_count, recording, updated_time)
        return _ok({"exists": True, "content": rec[3], "title": rec[2],
                    "word_count": rec[4] or 0, "recording": bool(rec[5]),
                    "updated_time": rec[6], "source": "db"})
    if target.is_file():
        text = target.read_text(encoding="utf-8", errors="replace")
        mtime = dt.datetime.fromtimestamp(target.stat().st_mtime, dt.timezone.utc)\
            .strftime("%Y-%m-%d %H:%M:%S")
        return _ok({"exists": True, "content": text, "title": target.stem,
                    "word_count": len("".join(text.split())), "recording": False,
                    "updated_time": mtime, "source": "file"})
    return _ok({"exists": False, "content": "", "updated_time": ""})


@notes_bp.route("/api/notes/list", methods=["GET"])
@require_auth
def notes_list():
    """用户笔记清单（DB ∪ vault 磁盘 .md），供选择/新建窗口。"""
    kms = get_kms()
    items, seen = [], set()
    for r in kms.list_note_records(g.user_id):
        # (note_uuid, file_name, file_path, title, word_count, recording, updated_time)
        rel = ""
        try:
            rel = _rel_to_root(Path(r[2]), g.user_id)
        except Exception:  # noqa: BLE001
            pass
        seen.add(str(r[2]).replace("\\", "/").lower())
        items.append({"name": r[1], "title": r[3] or Path(r[1]).stem, "path": r[2], "rel": rel,
                      "word_count": r[4] or 0, "recording": bool(r[5]), "updated_time": r[6] or ""})
    root = _user_vault_root_safe(g.user_id)
    if root.exists():
        for fp in sorted(root.rglob("*")):
            if fp.is_file() and fp.suffix.lower() in _MD_EXT and not fp.name.startswith("."):
                if str(fp).replace("\\", "/").lower() in seen:
                    continue
                mtime = dt.datetime.fromtimestamp(fp.stat().st_mtime, dt.timezone.utc)\
                    .strftime("%Y-%m-%d %H:%M:%S")
                items.append({"name": fp.name, "title": fp.stem, "path": str(fp),
                              "rel": _rel_to_root(fp, g.user_id), "word_count": 0,
                              "recording": False, "updated_time": mtime})
    items.sort(key=lambda x: x["updated_time"], reverse=True)
    return _ok({"items": items})


@notes_bp.route("/api/notes/recording", methods=["POST"])
@require_auth
def notes_recording():
    """置/清"录制中"标识。body {path, on: bool}。"""
    body = request.get_json(silent=True) or {}
    target = _bridge_path(g.user_id, body.get("path") or "")
    if target is None:
        return _err("非法路径", 403)
    on = bool(body.get("on"))
    ok = get_kms().set_note_recording(g.user_id, str(target), on)
    log.log("notes", "recording_flag", data={"user": g.user_id, "path": str(target), "on": on, "ok": ok})
    return _ok({"success": ok})


@notes_bp.route("/api/notes/active", methods=["GET"])
@require_auth
def notes_active():
    """当前用户录制中的笔记（横幅：正在保存到 <doc>）。"""
    rows = get_kms().get_active_recording(g.user_id)
    return _ok({"items": [{"note_uuid": r[0], "name": r[1], "path": r[2],
                           "title": r[3] or Path(r[1]).stem, "updated_time": r[4] or ""}
                          for r in rows]})


# ---------------------------------------------------------------- 三期：知识脑图（Mermaid）生成

_MMAP_BEGIN = "<!-- LL:MMAP:BEGIN -->"
_MMAP_END = "<!-- LL:MMAP:END -->"


def _extract_mindmap(raw: str):
    """从 LLM 输出提取合法 mindmap 代码；不合法返回 None。

    兼容：```mermaid 围栏 / 裸 ``` 围栏 / 直接以 mindmap 或 root 行开头。
    硬校验：必须含 mindmap 声明行与 root 节点行（外部 LLM 必须断言内容非空）。
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    m = re.search(r"```(?:mermaid)?\s*\n([\s\S]*?)```", text, re.I)
    if m:
        text = m.group(1).strip()
    lines = [ln for ln in text.splitlines()]
    # 去掉行首空行
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return None
    body = "\n".join(lines)
    lowered = [ln.strip().lower() for ln in lines]
    if "mindmap" not in lowered[:3]:
        # 缺声明行则自动补齐（模型常只给 root 开始的缩进树）
        if any(ln.startswith("root") for ln in lowered[:2]):
            body = "mindmap\n" + body
        else:
            return None
    if not re.search(r"^\s*root\b", body, re.M):
        return None
    return body


def _mindmap_section(mermaid_code: str) -> str:
    return (f"{_MMAP_BEGIN}\n## 知识脑图\n\n"
            f"```mermaid\n{mermaid_code}\n```\n"
            f"{_MMAP_END}")


def _splice_mindmap(content: str, mermaid_code: str):
    """幂等插入/替换脑图段；返回 (新正文, replaced: bool)。"""
    section = _mindmap_section(mermaid_code)
    pattern = re.compile(re.escape(_MMAP_BEGIN) + r"[\s\S]*?" + re.escape(_MMAP_END))
    if pattern.search(content):
        return pattern.sub(lambda _m: section, content), True
    base = content.rstrip()
    new = (base + "\n\n" + section + "\n") if base else (section + "\n")
    return new, False


@notes_bp.route("/api/notes/mindmap", methods=["POST"])
@require_auth
def notes_mindmap():
    """为文档生成 Mermaid mindmap 脑图并插入 MD 结尾。

    body: {path, title?, points: [{name, description}]}
    - 录音中（notes.recording=1）拒绝 409：避免被录音端全量 autosave 覆盖；
    - LLM 失败/输出不合法 500；成功写文件 + 同步 upsert DB（幂等替换标记段）。
    """
    body = request.get_json(silent=True) or {}
    target = _bridge_path(g.user_id, body.get("path") or "")
    if target is None:
        return _err("非法路径", 403)
    points = body.get("points") or []
    points = [p for p in points if isinstance(p, dict) and (p.get("name") or "").strip()]
    if not points:
        return _err("至少需要一个知识点", 400)
    rec = get_kms().get_note_record(g.user_id, str(target))
    if rec is not None and rec[5]:
        return _err("该笔记正在录音保存中，请先完成录音再生成脑图", 409)
    title = (body.get("title") or "").strip() or target.stem
    # 标题清洗后再写进 prompt，避免模型把引号/括号带进 root 行破坏 mindmap 语法
    title = re.sub(r'[\[\](){}"`:]', "", title).strip() or target.stem

    # 当前正文：库优先，回退文件（与 /api/notes/content 同口径）
    content = ""
    if rec is not None and rec[3] is not None:
        content = rec[3]
    elif target.is_file():
        content = target.read_text(encoding="utf-8", errors="replace")

    plist = "\n".join(
        f"{i + 1}. {p['name'].strip()}：{(p.get('description') or '').strip()[:200]}"
        for i, p in enumerate(points[:60]))
    prompt = f"""请为学习文档《{title}》生成一张知识脑图，输出 Mermaid mindmap 语法代码。

知识点清单（名称：讲解）：
{plist}

严格要求：
1. 第一行必须是 mindmap，第二行必须是 root(("{title}"))
2. root 下第二层为知识点节点（用知识点名称，可适当归类分组）
3. 每个知识点下挂一个第三层子节点，是用自己语言概括的一句话讲解（不超过 20 字）
4. 层级用两个空格缩进表示；可以有第三层补充子节点，最多四层
5. 节点文本必须单行，禁止出现 [ ] ( ) {{ }} " ` 冒号 等破坏 Mermaid 语法的字符
6. 只输出代码块，不要任何解释文字
"""
    try:
        raw = _llm_call(prompt, "知识脑图生成")
    except cr.InsufficientCreditsError as e:
        from flask import jsonify
        return jsonify({"success": False, "error": str(e), "credits_insufficient": True,
                        "credit_balance": e.balance}), 402
    except Exception as e:  # noqa: BLE001
        log.log_error("notes", "mindmap_llm_exception", str(e))
        return _err(f"脑图生成失败: {e}", 500)
    code = _extract_mindmap(raw)
    if not code:
        log.log_error("notes", "mindmap_llm_invalid",
                      f"输出无法解析为 mindmap：{(raw or '')[:300]}")
        return _err("脑图生成失败：模型未返回合法 Mermaid mindmap 代码", 500)

    new_content, replaced = _splice_mindmap(content, code)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.log_error("notes", "mindmap_write_failed", str(e))
        return _err(f"写入笔记失败: {e}", 500)
    r = get_kms().upsert_note_content(g.user_id, str(target), new_content, title=title)
    if r.get("error"):
        log.log_error("notes", "mindmap_db_failed", r["error"])
        return _err(f"笔记入库失败: {r['error']}", 500)
    log.log("notes", "mindmap_generated",
            data={"user": g.user_id, "path": str(target), "points": len(points),
                  "replaced": replaced})
    return _ok({"success": True, "mermaid": code, "path": str(target),
                "rel_path": _rel_to_root(target, g.user_id), "replaced": replaced,
                "updated_time": r["updated_time"], "note_id": r["note_id"]},
               **cr.billing_for_response())


# ---------------------------------------------------------------- 小工具
def _user_vault_root_safe(user_id: str) -> Path:
    from routes_knowledge import _user_vault_root
    try:
        return _user_vault_root(user_id)
    except Exception:  # noqa: BLE001
        return Path(".")
