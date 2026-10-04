# -*- coding: utf-8 -*-
"""文件导入任务服务（2026-09-30 导入功能，方案文档 §3.2）。

职责：import_tasks 任务表读写 + PDF 转换 worker（PaddleOCR-VL Job 驱动）。

Worker 线程显式约束（评审 MF-3）：
- 不触碰 Flask g / 请求上下文，user_id 等全部显式传参；
- DB 连接一律 get_kms().db_manager.get_connection() + try/finally 归还池；
- 全局信号量限并发 2（Paddle 队列满 400/10010 时排队而非打爆）；
- 进程重启时 pending/running 遗留任务由 recover_tasks_on_startup 置 failed。

产物规则（用户确认）：
- MD 转出 <名>.md 到目标目录；原 PDF 与切图均存 <目标>/附件/；
- 写盘后一律 upsert_note_content 同步入库（MF-5，笔记面板可见）；
- 图片重命名 img_<task>_<页>_<序><ext>，MD 引用同步替换（含 URL 编码变体）。
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import json
import re
import socket
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests

from logger_module import debug_logger as log
from services import paddle_doc_client as paddle

ATTACH_DIR_NAME = "附件"
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 20 * 60          # 讲义场景一般 <3min，留足余量
POLL_TRANSIENT_MAX_FAILS = 12     # 连续网络抖动容忍上限（×5s=1分钟），超过才判死
MAX_FILES_PER_JOB = 200           # 页数无硬限，超 200 页提示耗时较长（由前端展示）
PDF_TEXT_MIN_CHARS = 300          # 文本层判定下限：低于此视为扫描件回落 OCR
PDF_IMG_MIN_SIDE = 120            # 文本层插图过滤：短边小于此尺寸视为图标/头像噪声
PDF_IMG_QR_MIN = 250              # 近似正方形且边长≥此值视为二维码/公众号名片图（打印页广告位）
PDF_IMG_NOISE_FILTER = False      # 噪声过滤总开关（用户 2026-10-01 确认：保留所有内嵌图，默认关）
_SEM = threading.Semaphore(2)     # 转换并发预算（评审优化项 5）

_ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _now() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _db():
    from routes_knowledge import get_kms
    return get_kms().db_manager.get_connection()


# ---------------------------------------------------------------- 任务表 CRUD

def create_task(user_id: str, file_name: str, folder_path: str, kind: str,
                result_md: str = "", result_pdf: str = "", status: str = "pending",
                parent_task_id: str = "", seg_from: int | None = None, seg_to: int | None = None) -> str:
    """创建任务，返回对外业务键 task_id（非自增 id，适配层兼容见 schema_import 注释）。

    2026-10-04 大PDF分段：新增 status/parent_task_id/seg_from/seg_to，支持主任务与段子任务登记。
    """
    tid = uuid.uuid4().hex[:16]
    now = _now()
    # 必须 with 上下文（__exit__ commit）；close() 对 PG 是 rollback 归还，写入会丢失
    with _db() as conn:
        conn.execute(
            "INSERT INTO import_tasks (task_id, user_id, file_name, folder_path, kind, status,"
            " progress_json, result_md, result_pdf, remote_job_id, error, parent_task_id, seg_from, seg_to, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, user_id, file_name, folder_path, kind, status, "", result_md, result_pdf, "", "",
             parent_task_id, seg_from, seg_to, now, now),
        )
    return tid


def update_task(task_id: str, **fields) -> None:
    """字段名限定为表列（代码内常量使用，不接受外部输入作列名）。"""
    allowed = {"status", "progress_json", "result_md", "result_pdf", "remote_job_id", "error",
               "updated_at", "parent_task_id", "seg_from", "seg_to"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _db() as conn:
        conn.execute(f"UPDATE import_tasks SET {cols} WHERE task_id = ?", (*fields.values(), task_id))


def get_task(task_id: str, user_id: str) -> dict | None:
    """按 (id, user_id) 查询——强制用户隔离，防横向越权（评审优化项 2）。

    列索引访问，避免 sqlite/psycopg2 两种 row 形态差异。
    """
    with _db() as conn:
        row = conn.execute(
            "SELECT status, progress_json, result_md, error, file_name FROM import_tasks WHERE task_id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "status": row[0],
        "progress_json": row[1] or "",
        "result_md": row[2] or "",
        "error": row[3] or "",
        "file_name": row[4] or "",
    }


def recover_tasks_on_startup(conn_factory) -> None:
    """启动恢复：中断任务置 failed；顺带懒清理 30 天前记录。"""
    try:
        with conn_factory() as conn:
            conn.execute(
                "UPDATE import_tasks SET status = 'failed', error = '服务重启中断，请重新导入', updated_at = ?"
                " WHERE status IN ('pending', 'running')", (_now(),))
            cutoff = (dt.datetime.utcnow() - dt.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            # 2026-10-04 大PDF分段：书籍主任务永不删（产物文件在，但主任务聚合依赖此行）；
            # 有 error 的失败行也不删（保留标红供用户重转）；仅清理正常完成/取消的早期普通导入。
            conn.execute(
                "DELETE FROM import_tasks WHERE created_at < ?"
                " AND NOT (kind = 'pdf_book' OR error <> '')", (cutoff,))
    except Exception as e:  # noqa: BLE001 建表失败不阻断启动（与 schema 初始化同层级容错）
        log.log_error("import", "startup_recover_failed", e)


# ---------------------------------------------------------------- 工具

def uniquify_name(directory: Path, name: str) -> str:
    """重名自动加 _1/_2 后缀（对齐页面既有"新建笔记N"风格）。"""
    p = Path(name)
    stem, ext = p.stem, p.suffix
    candidate, i = name, 1
    while (directory / candidate).exists():
        candidate = f"{stem}_{i}{ext}"
        i += 1
    return candidate


def decode_text_bytes(data: bytes) -> str:
    """TXT/MD 解码：BOM 识别 utf-8/utf-16 → utf-8 → gb18030 回退（Windows 记事本常见）。"""
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gb18030", errors="replace")


# ---------------------------------------------------------------- 文本层后处理（2026-10-01 二轮修复）
#
# pypdf 直读的文本层有三类版面噪声，必须清洗后才能作为笔记正文：
# 1) 康熙部首变体字（⼈⾼⽉⻚…，网页字体 ToUnicode 映射到部首码点）→ NFKC 归一；
# 2) 硬换行断句（打印版式按栏宽折行，句子被腰斩）→ 软换行合并重排；
# 3) 网页打印装饰（公众号侧栏/推荐位/广告）→ 已知特征行整行剔除。

_END_PUNCT = "。！？；!?;:"          # 段落收束标点
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
# 康熙部首 U+2F00-2FDF / CJK 部首补充 U+2E80-2EFF / 兼容表意文字 U+F900-FAFF
_RADICAL_RANGES = ((0x2E80, 0x2FDF), (0xF900, 0xFAFF))
# 公众号打印页典型装饰行（行首匹配即整行丢弃；只收高置信特征，防误杀正文）
_CHROME_RE = re.compile(
    r"^(喜欢此内容的人还喜欢|收录于合集|#[^#\s]+\d+#|【腾讯云】|腾讯云福利|关注公众号|支持小薇|"
    r"觉得不错[，,]请点个|版权声明[：:]|学习交流之用|送免费机器|买云服务器|发表于|Java知音|"
    r"DotNet开发跳槽|\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})"
)
# 尾部推荐位区特征：命中后丢弃本页剩余行（打印页侧栏标题串流尾，空行/分页重置）
_TAIL_RE = re.compile(r"^(上[一二]篇[·・]|下[一二]篇[·・]|推荐\d+[个大])")
# CJK 部首补充区（U+2ED0-2EF3）NFKC 无映射，手工还原简体正字
_RADICAL_SRS = {"⻓": "长", "⻢": "马", "⻔": "门", "⻚": "页", "⻜": "飞", "⻝": "食",
                "⻉": "贝", "⻩": "黄", "⻰": "龙", "⻛": "风", "⻣": "骨", "⻦": "鸟",
                "⻥": "鱼", "⻄": "西", "⻅": "见", "⻋": "车", "⻝": "食", "⻑": "长"}


def _normalize_layer_chars(text: str) -> str:
    out = []
    for ch in text:
        cp = ord(ch)
        if any(a <= cp <= b for a, b in _RADICAL_RANGES):
            n = unicodedata.normalize("NFKC", ch)
            out.append(_RADICAL_SRS.get(n, n) if n != ch else _RADICAL_SRS.get(ch, ch))
        else:
            out.append(ch)
    return "".join(out)


def _join_wrapped(prev: str, nxt: str) -> str:
    """软换行拼接：ASCII 词边界补空格（英文单词跨行），中文直接连写；URL 跨行不加空格。"""
    a, b = prev[-1], nxt[0]
    if "http" in prev:
        return prev + nxt
    if a.isascii() and a.isalnum() and b.isascii() and b.isalnum():
        return prev + " " + nxt
    return prev + nxt


def postprocess_pdf_text_layer(text: str, images: dict[int, str] | None = None) -> str:
    """文本层清洗：部首归一 + 断行重排成段落 + 装饰行剔除。纯函数，便于单测。

    images：标记序号→附件内相对文件名；正文中 \x00IMG{n} 标记行在重排时断段并替换为图片引用。
    """
    text = _normalize_layer_chars(text)
    paragraphs: list[str] = []
    cur = ""
    tail = False

    def flush():
        nonlocal cur
        if cur:
            paragraphs.append(cur)
            cur = ""

    for raw in text.split("\n"):
        s = raw.strip()
        if s.startswith("\x00IMG"):
            flush()
            if images:
                n = int(s[4:] or 0)
                name = images.get(n)
                if name:
                    paragraphs.append(f"![图片]({ATTACH_DIR_NAME}/{name})")
            continue
        if not s:
            flush()
            tail = False       # 分页/空行重置推荐位区状态，防误杀后续页正文
            continue
        if tail or _TAIL_RE.match(s):
            flush()
            tail = True        # 进入尾部推荐位：本页剩余全弃
            continue
        if _CHROME_RE.match(s) or "cps_key" in s or "tencent.com/act" in s or "本公众号立即删除" in s:
            flush()
            continue
        if cur and not _CJK_RE.search(cur) and _CJK_RE.search(s):
            flush()          # 纯英文短标题行（如 "Read uncommitted"）独立成段
        if len(s) <= 2:
            flush()          # 折行尾悬字（"目""呀"）/代码行号：独立成段，不上下文粘连
            paragraphs.append(s)
            continue
        if not cur:
            cur = s
        else:
            cur = _join_wrapped(cur, s)
        if cur[-1] in _END_PUNCT:
            flush()
    flush()
    # 碎片过滤：悬空 1-2 字（数字行号保留）；纯 ASCII 的 hex 长串/hash 残片、短 URL 参数串
    def _junk(p: str) -> bool:
        if len(p) <= 2 and not p.isdigit():
            return True
        if p.isascii() and re.search(r"[0-9a-fA-F]{16,}", p):
            return True
        if p.isascii() and " " not in p and len(p) <= 12 and any(c in p for c in "?=&%+"):
            return True
        return bool(re.fullmatch(r"[^\s]*[=&][^\s]*", p)) and not _CJK_RE.search(p) and " " not in p
    kept = [p for p in paragraphs if not _junk(p)]
    return "\n\n".join(kept)


# ---------------------------------------------------------------- PDF 内嵌图片提取（2026-10-01 文本层路径插图）

def _mat_mul(m1, m2):
    """PDF 行向量约定矩阵乘法 [a,b,c,d,e,f]：返回 m1×m2（m1 先作用于单元空间）。"""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _cs_name(x) -> str:
    """pypdf 6.x 内容流操作符/名字对象可能是 bytes（如 b'Do'），统一归一为 str。"""
    return x.decode("latin-1") if isinstance(x, (bytes, bytearray)) else str(x)


def _walk_image_events(cs, resources, ctm, depth, events, seen_ids):
    """遍历内容流，跟踪 q/Q/cm 栈，收集图片放置事件 (xobj, top_y, 缩放宽a, 缩放高d)；Form 递归。"""
    from pypdf.generic import ContentStream
    stack = []
    cur = ctm
    for operands, operator in cs.operations:
        op = _cs_name(operator)
        if op == "q":
            stack.append(cur)
        elif op == "Q":
            if stack:
                cur = stack.pop()
        elif op == "cm" and len(operands) == 6:
            try:
                cur = _mat_mul(tuple(float(x) for x in operands), cur)
            except (TypeError, ValueError):
                pass
        elif op == "Do" and operands:
            name = _cs_name(operands[-1])
            if not name.startswith("/"):
                name = "/" + name
            try:
                xobj = resources["/XObject"][name].get_object()
            except (KeyError, TypeError):
                continue
            if xobj is None:
                continue
            subtype = str(xobj.get("/Subtype") or "")
            if subtype == "/Image":
                a, b, c, d, e, f = cur
                if id(xobj) not in seen_ids:      # 同一图多次放置只取首次
                    seen_ids.add(id(xobj))
                    events.append((xobj, b + d + f, abs(a), abs(d)))
            elif subtype == "/Form" and depth < 4:
                child_res = xobj.get("/Resources") or resources
                try:
                    _walk_image_events(ContentStream(xobj, xobj),
                                       child_res, cur, depth + 1, events, seen_ids)
                except Exception:  # noqa: BLE001 单页解析失败不致命，调用方兜底
                    pass


def _save_pdf_image(xob: object, att_dir: Path, base_name: str) -> str | None:
    """解码单张内嵌图存附件目录，返回文件名；不支持的编码/颜空间返回 None。"""
    try:
        from PIL import Image
        filt = str(xob.get("/Filter") or "")  # noqa: SLF001
        w, h = int(xob["/Width"]), int(xob["/Height"])
        att_dir.mkdir(parents=True, exist_ok=True)
        try:
            data = xob.get_data(apply_predictor=True)  # 处理 PNG 预测器
        except TypeError:
            data = xob.get_data()
        if "DCTDecode" in filt:
            name = base_name + ".jpg"
            (att_dir / name).write_bytes(data)
            return name
        if "JPXDecode" in filt:
            name = base_name + ".jp2"
            (att_dir / name).write_bytes(data)
            return name
        cs_obj = xob.get("/ColorSpace")
        cs_obj = cs_obj.get_object() if hasattr(cs_obj, "get_object") else cs_obj
        cs_s = str(cs_obj)
        if cs_s.startswith("[") or "ICCBased" in cs_s:   # ICC 数组：按通道数推模式
            n = int((cs_obj[1].get_object() if "[" in cs_s else cs_obj).get("/N", 3)) if hasattr(cs_obj, "__getitem__") else 3
            mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(n)
        elif "Gray" in cs_s:
            mode = "L"
        elif "RGB" in cs_s:
            mode = "RGB"
        elif "CMYK" in cs_s:
            mode = "CMYK"
        else:
            return None
        if mode is None or int(xob.get("/BitsPerComponent", 8)) != 8:
            return None
        img = Image.frombytes(mode, (w, h), data)
        name = base_name + ".png"
        img.save(att_dir / name)
        return name
    except Exception as e:  # noqa: BLE001 单图失败不影响正文与其他图
        log.log_error("import", "pdf_image_save_failed", e, {"base": base_name})
        return None


def _pdf_img_noise(xob: object) -> bool:
    """噪声过滤：小尺寸图标/头像；近似正方形大图（公众号二维码/名片图，打印页广告位特征）。

    总开关 PDF_IMG_NOISE_FILTER=False 时一律不过滤（用户 2026-10-01 确认保留所有内嵌图）。
    """
    if not PDF_IMG_NOISE_FILTER:
        return False
    try:
        w, h = int(xob["/Width"]), int(xob["/Height"])
    except (KeyError, ValueError, TypeError):
        return True
    if min(w, h) < PDF_IMG_MIN_SIDE:
        return True
    return 0.9 <= w / h <= 1.11 and min(w, h) >= PDF_IMG_QR_MIN


# ---------------------------------------------------------------- PDF worker

def start_pdf_task(task_id: str, user_id: str, pdf_path: Path, target_md: Path) -> None:
    """启动 daemon 线程执行全流程；立即返回。pdf_path 为已落附件目录的原件（保留不删）。"""
    t = threading.Thread(
        target=_pdf_worker, args=(task_id, user_id, pdf_path, target_md), daemon=True,
        name=f"import-pdf-{task_id}",
    )
    t.start()


def extract_pdf_text_layer(pdf_path: Path, att_dir: Path | None = None, task_id: str = "") -> str | None:
    """文本层优先（2026-10-01）：网页打印导出 PDF 内嵌完整文本，视觉 OCR 对超长单页大幅降采样会严重丢字。

    返回可用正文（足够长）；None 表示文本层不足（扫描/拍照版），调用方回落 PaddleOCR。
    att_dir+task_id 提供时同步提取内嵌图片：按内容流坐标交织进正文，图存附件目录。
    """
    try:
        from pypdf import PdfReader
        from pypdf.generic import ContentStream
        reader = PdfReader(str(pdf_path))
        page_blocks: list[str] = []
        images_map: dict[int, str] = {}
        img_seq = 0
        for pno, pg in enumerate(reader.pages):
            run_ys: list[float] = []

            def vt(text, cm, tm, fd, fs, _ys=run_ys):
                # 页面真实 y = 文本空间 y 经 CTM 变换（行向量约定：tm[5]*cm[3]+cm[5]）
                try:
                    _ys.append(float(tm[5]) * float(cm[3]) + float(cm[5]))
                except (TypeError, ValueError, IndexError):
                    pass

            txt = (pg.extract_text(visitor_text=vt) or "").strip()
            if not txt:
                continue
            if att_dir is not None and task_id:
                events: list = []
                try:
                    cs = ContentStream(pg["/Contents"].get_object(), pg)
                    _walk_image_events(cs, pg["/Resources"], (1, 0, 0, 1, 0, 0), 0, events, set())
                except Exception as e:  # noqa: BLE001
                    log.log_error("import", "pdf_img_events_failed", e, {"page": pno})
                    events = []
                events = [(y, x) for (x, y, _a, _d) in events if not _pdf_img_noise(x)]
                if events:
                    lines = txt.split("\n")
                    # 文本 run 的 y 降序分桶（2pt 合并同一行），用比例秩把图插到最近行前
                    buckets: list[float] = []
                    for y in sorted(run_ys, reverse=True):
                        if not buckets or abs(buckets[-1] - y) > 2.0:
                            buckets.append(y)
                    B = len(buckets)
                    ok = B >= max(3, len(lines) // 4)
                    if not ok:
                        log.log("import", "pdf_img_pos_fallback", "warn",
                                {"page": pno, "lines": len(lines), "buckets": B})
                    slots: dict[int, list[str]] = {}

                    def emit(xobj, idx):
                        nonlocal img_seq
                        img_seq += 1
                        fname = _save_pdf_image(xobj, att_dir, f"img_{task_id}_{pno}_{img_seq}")
                        if fname:
                            images_map[img_seq] = fname
                            slots.setdefault(idx, []).append(f"\x00IMG{img_seq}")
                        else:
                            img_seq -= 1

                    for top_y, xobj in sorted(events, key=lambda t: -t[0]):
                        if ok:
                            rank = sum(1 for by in buckets if by > top_y + 2.0)
                            idx = min(len(lines), round(rank * len(lines) / B))
                        else:
                            idx = len(lines)          # 兜底：页尾追加，不失败整单
                        emit(xobj, idx)
                    markers: list[str] = []
                    for i, line in enumerate(lines):
                        markers.extend(slots.pop(i, []))
                        markers.append(line)
                    for extra in slots.values():
                        markers.extend(extra)
                    txt = "\n".join(markers)
            page_blocks.append(txt)
        text = "\n\n".join(x for x in page_blocks if x.strip())
        if len(text) >= PDF_TEXT_MIN_CHARS:
            return postprocess_pdf_text_layer(text, images=images_map)
        return None
    except Exception as e:  # noqa: BLE001 解析失败不致命，回落 OCR
        log.log_error("import", "pdf_text_layer_failed", e, {"pdf": pdf_path.name})
        return None


def _pdf_worker(task_id: str, user_id: str, pdf_path: Path, target_md: Path) -> None:
    jsonl_text = None
    try:
        update_task(task_id, status="running")
        md_text = None
        # 文本层优先：命中则不耗远端额度、全文零丢失；内嵌图同步提取；本地解析不占转换并发信号量
        layer_text = extract_pdf_text_layer(pdf_path, target_md.parent / ATTACH_DIR_NAME, task_id)
        if layer_text is not None:
            md_text = layer_text
            log.log("import", "pdf_text_layer_hit", "success", {"task": task_id, "chars": len(md_text)})
        else:
            with _SEM:
                job_id = paddle.submit_job(str(pdf_path))
                update_task(task_id, remote_job_id=job_id)
                deadline = time.time() + POLL_TIMEOUT_S
                transient_fails = 0
                while time.time() < deadline:
                    try:
                        data = paddle.query_job(job_id)
                        state = data.get("state")
                        if state == "done":
                            json_url = (data.get("resultUrl") or {}).get("jsonUrl")
                            if not json_url:
                                raise paddle.PaddleDocError("结果中没有 jsonUrl")
                            jsonl_text = paddle.download_jsonl(json_url)
                        elif state == "failed":
                            raise paddle.PaddleDocError(f"解析任务失败: {data.get('errorMsg') or '未知原因'}")
                    except paddle.PaddleDocTransientError as e:
                        # 2026-10-01 用户误报根因：外网瞬时抖动（V2RAYN SSL 失败）不得一次判死整单
                        transient_fails += 1
                        log.log("import", "pdf_poll_transient", "warn",
                                {"task": task_id, "consecutive": transient_fails, "err": str(e)[:150]})
                        if transient_fails >= POLL_TRANSIENT_MAX_FAILS:
                            raise paddle.PaddleDocError(
                                f"网络连续 {transient_fails} 次不可用，任务终止，请检查网络后重新导入")
                        time.sleep(POLL_INTERVAL_S)
                        continue
                    if jsonl_text is not None:
                        break
                    transient_fails = 0
                    ep = data.get("extractProgress") or {}
                    update_task(task_id, progress_json=json.dumps({
                        "done": ep.get("extractedPages") or 0,
                        "total": ep.get("totalPages") or 0,
                    }))
                    time.sleep(POLL_INTERVAL_S)
                if jsonl_text is None:
                    raise paddle.PaddleDocError(f"转换超时（>{POLL_TIMEOUT_S // 60} 分钟），请稍后重试")
            md_text = _jsonl_to_markdown(jsonl_text, target_md.parent / ATTACH_DIR_NAME, task_id)
        if not md_text.strip():
            raise paddle.PaddleDocError("PDF 无有效内容（可能为空白文档）")
        target_md.parent.mkdir(parents=True, exist_ok=True)
        target_md.write_text(md_text, encoding="utf-8")
        # 评审 MF-1：入库失败不得报假 done（笔记面板看不到正文=业务未完成）
        if sync_note_content(user_id, target_md, md_text):
            update_task(task_id, status="done", error="")
            log.log("import", "pdf_task_done", "success", {"task": task_id, "md": target_md.name})
        else:
            update_task(task_id, status="failed",
                        error="文件已落盘但正文入库失败，笔记面板不可见，请删除后重新导入")
            log.log_error("import", "pdf_task_db_sync_failed", "upsert_note_content failed", {"task": task_id})
    except Exception as e:  # noqa: BLE001
        update_task(task_id, status="failed", error=str(e)[:300])
        log.log_error("import", "pdf_task_failed", e, {"task": task_id})
        # 失败时清掉上传预占的空 .md（O-2 遗留），避免用户看到空笔记；原件不动
        try:
            if target_md.exists() and target_md.stat().st_size == 0:
                target_md.unlink()
        except OSError:
            pass


def sync_note_content(user_id: str, md_path: Path, content: str) -> bool:
    """MF-5：任何写 .md 都必须同步正文入库（与 PUT /api/vault/rawfile 语义一致）。

    公开函数：routes 层 MD/TXT 直落与 worker 共用同一入库路径。
    返回是否入库成功（评审 MF-1：调用方据此区分 done/failed，不得报假成功）。
    """
    try:
        from routes_knowledge import get_kms
        r = get_kms().upsert_note_content(user_id, str(md_path), content)
        if r.get("error"):
            log.log_error("import", "note_db_sync_failed", r["error"], {"path": md_path.name})
            return False
        return True
    except Exception as e:  # noqa: BLE001 入库失败不抛，反馈给调用方降级处理
        log.log_error("import", "note_db_sync_failed", e, {"path": md_path.name})
        return False


def _jsonl_to_markdown(jsonl_text: str, att_dir: Path, task_id: str) -> str:
    """JSONL → 完整 Markdown。

    结构（评审优化项 3/4）：逐行 × 逐 result.layoutParsingResults[] 两级循环；
    markdown.images = {MD内相对路径: 可下载URL}，图片下载重命名为
    img_<task>_<页>_<序><ext> 存附件目录，并把 MD 中引用（原样 + URL 编码变体）替换。
    """
    att_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    page = 0
    bad_lines = 0
    for line in jsonl_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:  # 评审 O-3：单行畸形不毁整篇，跳过并计数
            bad_lines += 1
            continue
        res_list = ((obj.get("result") or {}).get("layoutParsingResults")) or []
        for res in res_list:
            md_block = res.get("markdown") or {}
            md = md_block.get("text") or ""
            for idx, (rel_key, img_url) in enumerate((md_block.get("images") or {}).items()):
                new_name = _save_remote_image(img_url, att_dir, task_id, page, idx, rel_key)
                if new_name is None:
                    continue  # 单图失败：保留原引用（渲染占位），不 abort 整任务
                ref = f"{ATTACH_DIR_NAME}/{new_name}"
                for variant in {rel_key, quote(rel_key), rel_key.lstrip("./"), quote(rel_key.lstrip("./"))}:
                    md = md.replace(variant, ref)
            parts.append(md)
            page += 1
    if bad_lines:
        log.log("import", "jsonl_partial_skip", "warn", {"task": task_id, "bad_lines": bad_lines})
    return "\n\n".join(parts)


def _save_remote_image(img_url: str, att_dir: Path, task_id: str, page: int, idx: int, rel_key: str) -> str | None:
    """下载单张切图到附件目录，返回本地文件名；失败返回 None（记录日志）。

    评审 O-1：仅 https、不跟随重定向、拒绝回环/私网/链路本地 IP 字面量与 localhost（SSRF 加固，
    主机校验逻辑与 URL 导入共用 is_safe_http_url）。
    """
    try:
        u = str(img_url)
        if not is_safe_http_url(u, allow_http=False):
            return None
        ext = Path(rel_key).suffix.lower()
        if ext not in _ALLOWED_IMG_EXT:
            ext = ".png"
        name = f"img_{task_id}_{page}_{idx}{ext}"
        resp = requests.get(img_url, timeout=60, allow_redirects=False)
        resp.raise_for_status()
        (att_dir / name).write_bytes(resp.content)
        return name
    except Exception as e:  # noqa: BLE001
        log.log_error("import", "image_download_failed", e, {"url": str(img_url)[:120]})
        return None


# ---------------------------------------------------------------- 公共：URL 安全校验（第七轮追加需求抽公共）

def is_safe_http_url(u: str, allow_http: bool = False) -> bool:
    """SSRF 护栏：协议白名单 + 拒内网/回环/链路本地/保留 IP 字面量与 localhost/.local/.internal。

    PDF 切图下载（仅 https）与 URL 导入（http/https）共用，避免两套逻辑漂移。
    """
    try:
        p = urlparse(str(u))
        schemes = ("http", "https") if allow_http else ("https",)
        if p.scheme not in schemes:
            return False
        host = (p.hostname or "").lower()
        if not host or host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
            return False
        try:
            ip = ipaddress.ip_address(host)
            return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
        except ValueError:
            # 2026-10-02 评审 Major：域名不得直接放行（nip.io 等泛解析可指向内网 IP）。
            # 连接前解析全部 A/AAAA 记录逐条复检，任一命中内网/回环/链路本地/保留即拒绝。
            try:
                port = p.port or (443 if p.scheme == "https" else 80)
                infos = socket.getaddrinfo(host, port)
            except OSError:
                return False
            for info in infos:
                try:
                    ip = ipaddress.ip_address(info[4][0])
                except ValueError:
                    return False
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return False
            return True
    except (ValueError, TypeError):
        return False


def _safe_get(url: str, timeout: int, headers: dict | None = None, max_redirects: int = 5):
    """GET + 重定向逐跳 SSRF 校验（评审 R1 必改）。

    allow_redirects=True 时 requests 不会复检跳转目标，公开 URL 可 302 到内网地址
    绕过首 URL 预检；故重定向一律自己处理，每跳 Location 先过 is_safe_http_url 再跟。
    """
    resp = requests.get(url, timeout=timeout, allow_redirects=False, headers=headers)
    hops = 0
    while getattr(resp, "status_code", 200) in (301, 302, 303, 307, 308):
        loc = (getattr(resp, "headers", None) or {}).get("Location")
        if not loc:
            break  # 无 Location 的 3xx：终止跟随，交由调用方按最终响应处理
        hops += 1
        if hops > max_redirects:
            raise ValueError("链接重定向次数过多，已停止抓取")
        nxt = urljoin(getattr(resp, "url", "") or url, loc)
        if not is_safe_http_url(nxt, allow_http=True):
            raise ValueError("链接重定向指向内网/非法地址，已拒绝访问")
        resp = requests.get(nxt, timeout=timeout, allow_redirects=False, headers=headers)
    return resp


_IMG_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                      "image/bmp": ".bmp", "image/webp": ".webp"}


# ---------------------------------------------------------------- DOCX 转换（第七轮追加需求：纯本地路径，不耗远端额度）

def start_docx_task(task_id: str, user_id: str, docx_path: Path, target_md: Path) -> None:
    """后台线程 DOCX→MD；与 PDF 同模式：失败清理空占位，原件不动。"""
    threading.Thread(target=_docx_worker, args=(task_id, user_id, docx_path, target_md),
                     daemon=True, name=f"import-docx-{task_id}").start()


def docx_to_markdown(docx_path: Path, att_dir: Path, task_id: str) -> str:
    """mammoth（DOCX→HTML，内嵌图解码存附件）→ markdownify（HTML→MD，表格转 MD 表格）。

    已知限制：文本框/艺术字等复杂排版可能丢版式，文字与图片不丢。
    """
    import mammoth
    from markdownify import markdownify as mdfy

    seq = 0

    def _save_image(image):
        nonlocal seq
        seq += 1
        ext = _IMG_CONTENT_TYPES.get((image.content_type or "").lower()) or (
            f".{image.file_extension}" if getattr(image, "file_extension", "") else ".png")
        if ext not in _ALLOWED_IMG_EXT:
            ext = ".png"
        name = f"img_{task_id}_0_{seq}{ext}"
        att_dir.mkdir(parents=True, exist_ok=True)
        with image.open() as ih:  # mammoth Image 提供 open() 上下文，无直接 read()
            (att_dir / name).write_bytes(ih.read())
        return {"src": f"{ATTACH_DIR_NAME}/{name}"}

    with open(docx_path, "rb") as fh:
        result = mammoth.convert_to_html(fh, convert_image=mammoth.images.img_element(_save_image))
    if result.messages:
        log.log("import", "docx_mammoth_warnings", "warn",
                {"task": task_id, "n": len(result.messages)})
    md = mdfy(result.value, heading_style="ATX", bullets="-")
    md = re.sub(r"\n{3,}", "\n\n", md)
    if seq:
        log.log("import", "docx_images_saved", "success", {"task": task_id, "count": seq})
    return md.strip()


def _docx_worker(task_id: str, user_id: str, docx_path: Path, target_md: Path) -> None:
    try:
        update_task(task_id, status="running")
        md_text = docx_to_markdown(docx_path, target_md.parent / ATTACH_DIR_NAME, task_id)
        if not md_text.strip():
            raise ValueError("DOCX 无有效内容（可能为空白文档）")
        target_md.parent.mkdir(parents=True, exist_ok=True)
        target_md.write_text(md_text, encoding="utf-8")
        if sync_note_content(user_id, target_md, md_text):
            update_task(task_id, status="done", error="")
            log.log("import", "docx_task_done", "success", {"task": task_id, "md": target_md.name, "chars": len(md_text)})
        else:
            update_task(task_id, status="failed", error="文件已落盘但正文入库失败，笔记面板不可见，请删除后重新导入")
            log.log_error("import", "docx_task_db_sync_failed", "upsert_note_content failed", {"task": task_id})
    except Exception as e:  # noqa: BLE001
        update_task(task_id, status="failed", error=str(e)[:300])
        log.log_error("import", "docx_task_failed", e, {"task": task_id})
        try:  # 沿用 PDF 教训：失败不留空占位
            if target_md.exists() and target_md.stat().st_size == 0:
                target_md.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- URL 抓网页转笔记（第七轮追加需求）

URL_MIN_TEXT_CHARS = 50          # 正文下限：低于此视为纯视频页/登录墙，按失败给本地导入提示
URL_FETCH_TIMEOUT_S = 30
URL_MAX_HTML_BYTES = 20 * 1024 * 1024   # 评审 R-4：页面抓取体积上限，防异常大页打满内存
PAGE_IMG_MAX_BYTES = 20 * 1024 * 1024   # 评审 R-4：单张远程图下载体积上限
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# 微信反爬/验证页特征（命中即失败提示，不反复重试）
_URL_BLOCK_MARKS = ("当前环境异常", "完成验证后即可继续访问")
# 微信图床尺寸后缀：.../640?wx_fmt=png 是缩放版，去后缀取原图
_MMBIZ_RESIZE_RE = re.compile(r"(https://mmbiz\.qpic\.cn/.+?)/(\d{3,5})(\?wx_fmt=(\w+))?$", re.I)


def start_url_task(task_id: str, user_id: str, url: str, folder: Path) -> None:
    """后台线程抓取 URL→MD；产物文件名取文章标题（故 result_md 在 worker 内回填）。"""
    threading.Thread(target=_url_worker, args=(task_id, user_id, url, folder),
                     daemon=True, name=f"import-url-{task_id}").start()


def _decode_response_html(resp) -> str:
    """HTTP 响应→HTML 文本：服务端明确声明非 latin 系charset 时照用；否则 UTF-8 严格解码优先，
    再试探测结果与 gb18030，最后 UTF-8 replace 兜底。

    在线端到端实测（2026-10 pingcap 文档）：无 charset 声明时 requests 默认 iso-8859-1，
    直接改 apparent_encoding 仍可能被误判为 latin 系产生乱码，必须按字节优先试 UTF-8。
    """
    raw = resp.content
    declared = (resp.encoding or "").lower()
    if declared and declared not in ("iso-8859-1", "ascii", "windows-1252", "latin-1"):
        try:
            return raw.decode(declared, "replace")
        except LookupError:
            pass
    tried = ["utf-8"]
    for cand in (getattr(resp, "apparent_encoding", None) or "", "gb18030"):
        c = (cand or "").lower()
        if c and c not in tried and c not in ("iso-8859-1", "windows-1252", "latin-1", "ascii"):
            tried.append(c)
    for enc in tried:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _fetch_html(url: str) -> str:
    # 评审 R1：重定向不交 requests 自动跟（会绕过 SSRF 预检），走 _safe_get 逐跳校验
    resp = _safe_get(url, timeout=URL_FETCH_TIMEOUT_S, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    })
    resp.raise_for_status()
    if len(resp.content) > URL_MAX_HTML_BYTES:
        raise ValueError("页面内容过大（超 20MB），请改用本地导入")
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if ctype and not ctype.startswith(("text/html", "application/xhtml")):
        raise ValueError("链接不是网页（可能是文件直链），请改用本地导入")
    return _decode_response_html(resp)


def _markdownify_node(node) -> str:
    from markdownify import markdownify as mdfy
    return re.sub(r"\n{3,}", "\n\n", mdfy(str(node), heading_style="ATX", bullets="-")).strip()


def html_to_markdown_note(html: str) -> tuple[str, str]:
    """HTML → (Markdown 正文, 标题)。

    预处理：懒加载 img data-src 回填 src（公众号正文图全懒加载，不回填则提不到图）。
    正文双通道择优：trafilatura 去噪最强，但实测 2.2 对正文图启发式丢弃（markdown/html
    输出均不提图）；故与正文容器（#js_content/article）markdownify 版比较，图片引用多
    且长度达标者胜，否则取 trafilatura；标题优先 meta，再 #activity-name/h1/title。
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        if not (img.get("src") or "").startswith("http"):
            ds = img.get("data-src") or img.get("data-backsrc")
            if ds:
                img["src"] = ds
    cleaned = str(soup)

    tf_md: str | None = None
    title = ""
    try:
        import trafilatura
        tf_md = trafilatura.extract(cleaned, output_format="markdown", include_images=True,
                                    include_tables=True, include_links=True, include_comments=False)
        meta = trafilatura.extract_metadata(cleaned)
        if meta and meta.title:
            title = meta.title
    except Exception as e:  # noqa: BLE001 trafilatura 异常不致命，走兜底容器提取
        log.log_error("import", "trafilatura_failed", e, {})
    if not title:
        t = soup.select_one("#activity-name") or soup.find("h1") or soup.find("title")
        title = t.get_text(strip=True) if t else ""

    container = soup.select_one("#js_content") or soup.find("article") or soup.find("body")
    c_md = _markdownify_node(container) if container is not None else ""
    tf_md = (tf_md or "").strip()

    def _n_imgs(s: str) -> int:
        return len(re.findall(r"!\[[^\]]*\]\(https?://", s))

    if len(c_md) >= URL_MIN_TEXT_CHARS and _n_imgs(c_md) > _n_imgs(tf_md):
        md = c_md
    else:
        md = tf_md or c_md
    return md, (title or "").strip()


def _download_page_image(img_url: str, att_dir: Path, task_id: str, idx: int) -> str | None:
    """下载 MD 中单张远程图存附件；微信图床优先去尺寸后缀取原图，失败回落原 URL。"""
    cands = [img_url]
    ext = None
    m = _MMBIZ_RESIZE_RE.match(img_url)
    if m:
        ext = "." + (m.group(4) or "png").lower().replace("jpeg", "jpg")
        if ext not in _ALLOWED_IMG_EXT:
            ext = ".png"
        cands.insert(0, m.group(1) + (m.group(3) or ""))   # 原图优先，缩放版兜底
    for u in cands:
        try:
            if not is_safe_http_url(u, allow_http=True):
                continue
            resp = _safe_get(u, timeout=60, headers={"User-Agent": _UA, "Referer": "https://mp.weixin.qq.com/"})
            resp.raise_for_status()
            if not resp.content:
                continue
            if len(resp.content) > PAGE_IMG_MAX_BYTES:   # 评审 R-4：超大图跳过，保留远程 URL
                log.log("import", "page_image_too_large", "warn", {"url": u[:120], "bytes": len(resp.content)})
                continue
            if ext is None:
                ctype = (resp.headers.get("Content-Type") or "").lower().split(";")[0]
                ext = _IMG_CONTENT_TYPES.get(ctype) or Path(urlparse(u).path).suffix.lower()
            if ext not in _ALLOWED_IMG_EXT:
                ext = ".png"
            name = f"img_{task_id}_0_{idx}{ext}"
            att_dir.mkdir(parents=True, exist_ok=True)
            (att_dir / name).write_bytes(resp.content)
            return name
        except Exception as e:  # noqa: BLE001 单图失败不整单失败
            log.log_error("import", "page_image_download_failed", e, {"url": u[:120]})
    return None


def _localize_md_images(md: str, att_dir: Path, task_id: str) -> str:
    """MD 中远程图逐张本地化改写为 附件/ 引用；下载失败保留原 URL（与 PDF 单图策略一致）。"""
    n = 0

    def repl(m):
        nonlocal n
        alt, u = m.group(1), m.group(2)
        n += 1
        name = _download_page_image(u, att_dir, task_id, n)
        if not name:
            return m.group(0)
        return f"![{alt}]({ATTACH_DIR_NAME}/{name})"

    return re.sub(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)", repl, md)


def _safe_note_name(title: str) -> str:
    """文章标题→笔记文件名：去非法字符、限长 60、空标题兜底（与上传文件名清洗同字符集）。"""
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", title or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:60] or "网页笔记"


def _url_worker(task_id: str, user_id: str, url: str, folder: Path) -> None:
    try:
        update_task(task_id, status="running")
        if not is_safe_http_url(url, allow_http=True):
            raise ValueError("链接不合法或指向内网地址，仅支持公网 http(s) 网页")
        try:
            html = _fetch_html(url)
        except requests.RequestException as e:
            raise ValueError(f"网页无法访问（{type(e).__name__}），请检查链接或稍后重试") from e
        if any(mk in html for mk in _URL_BLOCK_MARKS):
            raise ValueError("该页面需微信内验证，暂无法抓取；请在电脑浏览器打开该文章→另存为网页/PDF→用本地导入")
        md, title = html_to_markdown_note(html)
        if len(md) < URL_MIN_TEXT_CHARS:
            raise ValueError("未能提取到正文（可能是纯视频页或需登录），请改用本地导入")
        md = _localize_md_images(md, folder / ATTACH_DIR_NAME, task_id)
        # 正文加标题行：无 front-matter，与导入 PDF 产物同构（首行 # 标题）
        if title and not md.startswith("#"):
            md = f"# {title}\n\n{md}"
        name = uniquify_name(folder, _safe_note_name(title or urlparse(url).path.rstrip('/').split('/')[-1] or "网页笔记") + ".md")
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(md, encoding="utf-8")
        update_task(task_id, result_md=str(target))
        if sync_note_content(user_id, target, md):
            update_task(task_id, status="done", error="")
            log.log("import", "url_task_done", "success", {"task": task_id, "md": name, "chars": len(md)})
        else:
            update_task(task_id, status="failed", error="文件已落盘但正文入库失败，请删除后重新导入")
            log.log_error("import", "url_task_db_sync_failed", "upsert_note_content failed", {"task": task_id})
    except Exception as e:  # noqa: BLE001
        update_task(task_id, status="failed", error=str(e)[:300])
        log.log_error("import", "url_task_failed", e, {"task": task_id})
