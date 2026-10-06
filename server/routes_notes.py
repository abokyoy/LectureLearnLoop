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


def _extract_mindmap(raw: str, style: str = "mindmap"):
    """从 LLM 输出提取合法 mermaid 代码；不合法返回 None。

    兼容：```mermaid 围栏 / 裸 ``` 围栏 / 直接以声明行开头。
    根据 style 校验不同语法头：mindmap 需 root 行；graph_td/lr 需 graph TD/LR 行。
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    m = re.search(r"```(?:mermaid)?\s*\n([\s\S]*?)```", text, re.I)
    if m:
        text = m.group(1).strip()
    lines = [ln for ln in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return None
    body = "\n".join(lines)
    if style in ("graph_td", "graph_lr"):
        # graph 语法校验：第一行应为 graph TD/LR
        if not re.search(r"^\s*graph\s+(TD|LR|TB|RL|BT)", body, re.I):
            return None
    else:
        # mindmap 语法校验
        lowered = [ln.strip().lower() for ln in lines]
        if "mindmap" not in lowered[:3]:
            if any(ln.startswith("root") for ln in lowered[:2]):
                body = "mindmap\n" + body
            else:
                return None
        if not re.search(r"^\s*root\b", body, re.M):
            return None
    return body


def _mindmap_section(mermaid_code: str, style: str = "mindmap") -> str:
    """生成一个脑图块（追加到文末，多次生成保留多个）。"""
    label = {"mindmap": "放射状脑图", "graph_td": "树形脑图", "graph_lr": "横向树脑图"}.get(style, "知识脑图")
    return (f"{_MMAP_BEGIN}\n## {label}\n\n"
            f"```mermaid\n{mermaid_code}\n```\n"
            f"{_MMAP_END}")


def _splice_mindmap(content: str, mermaid_code: str, style: str = "mindmap"):
    """追加脑图段到正文末尾；返回 (新正文, False)。"""
    section = _mindmap_section(mermaid_code, style)
    base = content.rstrip()
    new = (base + "\n\n" + section + "\n") if base else (section + "\n")
    return new, False


@notes_bp.route("/api/notes/mindmap", methods=["POST"])
@require_auth
def notes_mindmap():
    """为文档生成 Mermaid 脑图并追加到 MD 结尾。

    body: {path, title?, points: [{name, description}], style?: "mindmap|graph_td|graph_lr"}
    多次生成追加多个脑图块到文末。
    """
    body = request.get_json(silent=True) or {}
    target = _bridge_path(g.user_id, body.get("path") or "")
    if target is None:
        return _err("非法路径", 403)
    points = body.get("points") or []
    points = [p for p in points if isinstance(p, dict) and (p.get("name") or "").strip()]
    if not points:
        return _err("至少需要一个知识点", 400)
    style = body.get("style", "mindmap")
    if style not in ("mindmap", "graph_td", "graph_lr"):
        style = "mindmap"
    rec = get_kms().get_note_record(g.user_id, str(target))
    if rec is not None and rec[5]:
        return _err("该笔记正在录音保存中，请先完成录音再生成脑图", 409)
    title = (body.get("title") or "").strip() or target.stem
    title = re.sub(r'[\[\](){}"`:]', "", title).strip() or target.stem

    # 当前正文：库优先，回退文件
    content = ""
    if rec is not None and rec[3] is not None:
        content = rec[3]
    elif target.is_file():
        content = target.read_text(encoding="utf-8", errors="replace")

    plist = "\n".join(
        f"{i + 1}. {p['name'].strip()}：{(p.get('description') or '').strip()[:200]}"
        for i, p in enumerate(points[:60]))

    # 根据样式生成不同 prompt
    if style in ("graph_td", "graph_lr"):
        direction = "TD" if style == "graph_td" else "LR"
        prompt = f"""请为学习文档《{title}》生成一张树形脑图，输出 Mermaid graph {direction} 语法代码。

知识点清单（名称：讲解）：
{plist}

严格要求：
1. 第一行必须是 graph {direction}
2. 定义根节点 root["{title}"]，用 -->连接各知识点节点
3. 每个知识点格式: p1["知识点名"]，连线: root --> p1
4. 每个知识点下挂一个子节点概括说明（不超过15字），格式: p1 --> p1d["概括"]
5. 节点文本禁止出现 [ ] ( ) {{ }} 等破坏语法的字符（方括号只用于节点定义外层）
6. 只输出代码块，不要任何解释文字
"""
    else:
        prompt = f"""请为学习文档《{title}》生成一张知识脑图，输出 Mermaid mindmap 语法代码。

知识点清单（名称：讲解）：
{plist}

严格要求：
1. 第一行必须是 mindmap，第二行必须是 root(("{title}"))
2. root 下第二层为知识点节点（用知识点名称，可适当归类分组）
3. 每个知识点下挂一个第三层子节点，用自己语言概括（不超过 20 字）
4. 层级用两个空格缩进表示；最多四层
5. 节点文本必须单行，禁止出现 [ ] ( ) {{ }} " ` 冒号 等破坏语法的字符
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
    code = _extract_mindmap(raw, style)
    if not code:
        log.log_error("notes", "mindmap_llm_invalid",
                      f"输出无法解析为 {style}：{(raw or '')[:300]}")
        return _err(f"脑图生成失败：模型未返回合法 {style} 代码", 500)

    new_content, _ = _splice_mindmap(content, code, style)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.log_error("notes", "mindmap_write_failed", str(e))
        return _err(f"写入笔记失败: {e}", 500)
    r = get_kms().upsert_note_content(g.user_id, str(target), new_content, title=title)
    if r.get("error"):
        log.log_error("notes", "mindmap_db_failed", r["error"])
        return _err(f"入库失败: {r['error']}", 500)
    log.log("notes", "mindmap_generated",
            data={"user": g.user_id, "path": str(target), "points": len(points), "style": style})
    return _ok({"success": True, "mermaid": code, "style": style,
                "path": str(target),
                "rel_path": _rel_to_root(target, g.user_id),
                "updated_time": r["updated_time"], "note_id": r["note_id"]},
               **cr.billing_for_response())


# ---------------------------------------------------------------- 摘录插入（深入学习后插入子段）

@notes_bp.route("/api/notes/insert-after", methods=["POST"])
@require_auth
def notes_insert_after():
    """在笔记 MD 文件中找到 after_text 段落，在其后插入 insert_content。

    body: {path, after_text, insert_content}
    - after_text: 原文中选中的段落文本（前80字用于定位）
    - insert_content: 要插入的 MD 格式内容（blockquote 子段）
    返回: 成功时包含新内容长度。
    """
    body = request.get_json(silent=True) or {}
    target = _bridge_path(g.user_id, body.get("path") or "")
    if target is None:
        return _err("非法路径", 403)
    after_text = (body.get("after_text") or "").strip()
    insert_content = (body.get("insert_content") or "").strip()
    if not insert_content:
        return _err("缺少插入内容", 400)

    # 读取当前正文
    rec = get_kms().get_note_record(g.user_id, str(target))
    content = ""
    if rec is not None and rec[3] is not None:
        content = rec[3]
    elif target.is_file():
        content = target.read_text(encoding="utf-8", errors="replace")
    else:
        return _err("文件不存在", 404)

    # 定位 after_text：空则追加文末，非空则精确插入
    if not after_text:
        new_content = content.rstrip() + "\n\n" + insert_content + "\n"
    else:
        search_key = after_text[:80]
        idx = content.find(search_key)
        if idx == -1:
            # 回退尝试纯文本匹配（去除 MD 标记后）
            import re as _re
            plain_key = _re.sub(r'[#*_`>\-\[\]()!]', '', search_key).strip()[:40]
            plain_content = _re.sub(r'[#*_`>\-\[\]()!]', '', content)
            pidx = plain_content.find(plain_key)
            if pidx == -1:
                # 找不到原段落，回退追加到文末
                new_content = content.rstrip() + "\n\n" + insert_content + "\n"
            else:
                # 粗略定位原文位置（偏差可接受）
                ratio = pidx / max(len(plain_content), 1)
                approx = int(ratio * len(content))
                end = content.find("\n", approx)
                if end == -1:
                    end = len(content)
                new_content = content[:end] + "\n\n" + insert_content + "\n" + content[end:]
        else:
            # 找到 after_text 所在段落的末尾
            para_end = idx + len(search_key)
            while para_end < len(content):
                nl = content.find("\n", para_end)
                if nl == -1:
                    para_end = len(content)
                    break
                next_line_start = nl + 1
                next_nl = content.find("\n", next_line_start)
                if next_nl == -1:
                    next_nl = len(content)
                next_line = content[next_line_start:next_nl].strip()
                if not next_line or next_line.startswith("#") or next_line.startswith("```"):
                    para_end = nl
                    break
                para_end = next_nl
            new_content = content[:para_end] + "\n\n" + insert_content + "\n" + content[para_end:]

    # 写文件 + 同步 DB
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.log_error("notes", "insert_after_write_failed", str(e))
        return _err(f"写入失败: {e}", 500)
    title = target.stem
    r = get_kms().upsert_note_content(g.user_id, str(target), new_content, title=title)
    if r.get("error"):
        log.log_error("notes", "insert_after_db_failed", r["error"])
        return _err(f"入库失败: {r['error']}", 500)
    log.log("notes", "insert_after_ok",
            data={"user": g.user_id, "path": str(target), "insert_len": len(insert_content)})
    return _ok({"success": True, "new_length": len(new_content),
                "updated_time": r["updated_time"], "note_id": r["note_id"]})


# ---------------------------------------------------------------- 小工具
def _user_vault_root_safe(user_id: str) -> Path:
    from routes_knowledge import _user_vault_root
    try:
        return _user_vault_root(user_id)
    except Exception:  # noqa: BLE001
        return Path(".")
