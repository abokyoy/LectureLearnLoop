# -*- coding: utf-8 -*-
"""错题「智能分析」（2026-10-13，用户需求：编辑错题时图片+文字一键整理成规范错题）。

管线（用户已裁定的方案 B：真能看图的大模型 + Paddle 版面切片）：
  A. 逐图 PaddleOCR-VL 版面分析 → 文字块（bbox+内容）与图形块（bbox），
     图形块按比例映射到本地原图 PIL 裁剪成切片存 vault（"图就用 Paddle 识别的矩形切片"）；
  B. 原始 MD + Paddle 结构化结果 + 图片（原图与切片，OpenAI image_url dataURL）
     统一发给视觉大模型（用户配置优先、系统 SiliconFlow Qwen3-VL 兜底，走 call_llm_vision 计费链）；
  C. 对比防错在 prompt 内约束：题干文字逐字采用 Paddle OCR 结果，VL 只负责排版/理解/错因分析。
回填契约：{stem_md, correct_answer, explanation}；用户解答按裁定并入 explanation 开头小节。

降级兜底（核心功能必须有兜底，同 error_ocr 约定）：
  Paddle 失败 → 该图跳过版面分析，原图全量发 VL；VL 失败/JSON 不可解析 → 任务 error，前端手填；
  不重发 VL 请求（防重复扣积分）。任务瞬态，重启丢失可接受。
网络口径：paddle/siliconflow 均国内直连通道，服务进程环境不设代理（实测 V2RAYN 代理链路 SSL 握手失败）；
  VL 侧已 session.trust_env=False，Paddle 侧沿用 paddle_doc_client（进程环境无代理变量，天然直连）。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import threading
import time

from PIL import Image

from logger_module import debug_logger as log
from services import paddle_doc_client as paddle
from services.error_ocr import image_to_pdf_bytes, is_image
from services.task_registry import TaskRegistry

POLL_INTERVAL_S = 3.0
BASE_WAIT_S = 180.0            # 单图任务基准超时（同 error_ocr）
PER_EXTRA_IMAGE_S = 60.0       # 每多一张图的追加预算（评审 L2：多图 180s 不够）
TASK_TTL_S = 600.0
MAX_IMG_BYTES = 6 * 1024 * 1024   # 原图 dataURL 上限，超限等比压缩（防网关拒收）
MAX_IMG_EDGE = 2048               # 压缩目标边长

_registry = TaskRegistry(TASK_TTL_S)
_SEM = threading.Semaphore(2)  # 后台重任务限并发（同 import_service 惯例，评审 L6）
# 在飞去重（评审 Major1）：前端轮询窗口可能早于服务端最坏耗时收尾，用户超时后再点
# 会起第二个任务、第二次扣分；同一 (用户+草稿+图清单) 命中运行中任务时复用 task_id 杜绝双扣
_inflight_lock = threading.Lock()
_inflight: dict = {}  # dedup_key -> task_id（仅运行期间持有）

_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)\s*\)")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")

_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".bmp": "image/bmp"}


def _mime_of(path: str) -> str:
    return _MIME_BY_EXT.get(os.path.splitext(path)[1].lower(), "image/png")


def md_image_paths(md_text: str) -> list:
    """提取 MD 中 vault 相对图片路径（去重保序）；拒绝 http/https/data URL（评审 L4，
    本地路径合法性另由路由层 _safe_vault_path 把关）。"""
    out, seen = [], set()
    for m in _MD_IMG_RE.finditer(md_text or ""):
        rel = m.group(1).strip().strip("<>")
        if rel.lower().startswith(("http:", "https:", "data:", "ftp:")):
            continue
        if not is_image(rel) or rel in seen:
            continue
        seen.add(rel)
        out.append(rel)
    return out


# ---------------------------------------------------------------- A. Paddle 版面分析

def _crop_filename(rel: str, idx: int) -> str:
    stem, ext = os.path.splitext(rel)
    return f"{stem}_fig{idx}{ext.lower() or '.png'}"


def _analyze_one_image(rel: str, abs_path: str, deadline: float) -> dict:
    """单图：提交 Paddle → 轮询 → 解析版面块 → 图形块本地裁剪存 vault（与 rel 同目录）。"""
    pdf_bytes = image_to_pdf_bytes(abs_path)
    tmp_pdf = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(pdf_bytes)
            tmp_pdf = tf.name
        job_id = paddle.submit_job(tmp_pdf)
        json_url = None
        while time.time() < deadline:
            try:
                st = paddle.query_job(job_id)
            except paddle.PaddleDocTransientError as e:
                log.log("analyze", "paddle_poll_transient", "warn", {"err": str(e)[:120]})
                time.sleep(POLL_INTERVAL_S)
                continue
            state = st.get("state")
            if state == "done":
                json_url = (st.get("resultUrl") or {}).get("jsonUrl")
                if not json_url:
                    raise paddle.PaddleDocError("结果中没有 jsonUrl")
                break
            if state == "failed":
                raise paddle.PaddleDocError(f"版面分析失败: {st.get('errorMsg') or '未知原因'}")
            time.sleep(POLL_INTERVAL_S)
        if not json_url:
            raise paddle.PaddleDocError("版面分析超时")
        return _parse_jsonl_and_crop(paddle.download_jsonl(json_url), rel, abs_path)
    finally:
        if tmp_pdf:
            try:
                os.unlink(tmp_pdf)
            except OSError:
                pass


def _parse_jsonl_and_crop(jsonl_text: str, rel: str, abs_path: str) -> dict:
    """jsonl 文本 → {image, page_size, texts:[{bbox,content}], figures:[{bbox,crop_rel}]}。
    bbox 坐标系=prunedResult.width/height（与本地像素尺寸比例不定），逐页动态换算（评审 L1）。"""
    texts, figures, page_size = [], [], None
    for line in (jsonl_text or "").strip().splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # 单行畸形不毁整篇（同 error_ocr 口径）
        for res in ((obj.get("result") or {}).get("layoutParsingResults")) or []:
            pr = res.get("prunedResult") or {}
            w, h = pr.get("width"), pr.get("height")
            if w and h:
                page_size = [w, h]
            for b in pr.get("parsing_res_list") or []:
                if not isinstance(b, dict):
                    continue
                bbox = b.get("block_bbox")
                label = str(b.get("block_label") or "")
                content = (b.get("block_content") or "").strip()
                if label == "image" and isinstance(bbox, list) and len(bbox) == 4:
                    figures.append({"bbox": bbox})
                elif label != "image" and content:
                    texts.append({"bbox": bbox, "content": content})
    # 图形块本地裁剪（Paddle 切片仅文件名不给下载 URL，本地 PIL 按 bbox 裁，用户裁定的"矩形切片"）
    if figures and page_size:
        im = Image.open(abs_path)
        lw, lh = im.size
        sx, sy = lw / page_size[0], lh / page_size[1]
        base_dir = os.path.dirname(abs_path)
        for i, fig in enumerate(figures):
            x1, y1, x2, y2 = fig["bbox"]
            box = (max(0, int(x1 * sx)), max(0, int(y1 * sy)),
                   min(lw, int(x2 * sx)), min(lh, int(y2 * sy)))
            crop_rel = _crop_filename(rel, i)
            if box[2] > box[0] and box[3] > box[1]:
                im.crop(box).save(os.path.join(base_dir, os.path.basename(crop_rel)))
                fig["crop_rel"] = crop_rel
                log.log("analyze", "figure_cropped", "success",
                        {"src": rel, "crop": crop_rel, "box": list(box)})
    return {"image": rel, "page_size": page_size, "texts": texts, "figures": figures}


# ---------------------------------------------------------------- B. VL 请求组装

def _image_payload_items(path: str, mime: str) -> dict:
    """本地图 → {mime, b64}；超大图等比压缩后以 JPEG 携带（防 dataURL 过限）。"""
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) > MAX_IMG_BYTES:
        im = Image.open(path).convert("RGB")
        if max(im.size) > MAX_IMG_EDGE:
            ratio = MAX_IMG_EDGE / max(im.size)
            im = im.resize((max(1, int(im.width * ratio)), max(1, int(im.height * ratio))))
        import io
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        raw = buf.getvalue()
        mime = "image/jpeg"
    return {"mime": mime, "b64": base64.b64encode(raw).decode("ascii")}


_PROMPT_HEADER = """你是"错题整理器"。用户提供了一道错题的草稿（可能含图片：题目照片/手写解答）。你将收到：
① 草稿原始 Markdown 文本；② PaddleOCR 版面分析结果（文字块 bbox+识别内容、图形块 bbox 及已裁剪好的图形切片文件路径）；③ 附图（每张原图与各图形切片，编号与清单对应）。
任务：把这道题重新整理成规范错题，只输出一个 JSON 对象（不带任何围栏或额外文字）。

硬性规则：
1. 题干文字必须逐字取自"版面分析文字块内容"与用户手输文字，禁止改写、补全、翻译、自行润色；若你从附图中看到明显与 OCR 不一致之处，以图中实际内容为准并在题干中修正（OCR 与视觉互为防错校对）。
2. 题目中的图形一律用给定的“切片路径”引用（切片清单里列出的 _figN 文件），格式 ![图形](切片相对路径)；禁止引用原始图片文件路径（原图仅供你通读全貌），禁止用文字描述代替图形，禁止虚构路径。用户手写解答中的图不属于题干。
3. user_solution_md：如实转录学生的解题过程（含错误步骤、涂改后的最终写法），不得修正或简化；图中没有学生解答则返回空字符串。
4. error_analysis：指出错在哪一步、为什么错、大概率是哪个知识点薄弱。
5. correct_answer：简洁的最终答案；explanation：完整的正确推导过程。若图中本身印有标准答案/解析，逐字转录到对应字段。
6. 版面分析失败的图片，依据附图自行判断，其余规则不变。
7. 所有字段里的数学公式必须用定界符包裹：行内用 $…$，独立成行的算式用 $$…$$；公式内容本身仍逐字如实，不得增删改；纯中文叙述文字不包裹。禁止输出没有定界符的裸 LaTeX。本规则只加定界、不改任何内容文字，与规则 1/3 的“逐字如实转录”不冲突。

输出 JSON 结构：
{"stem_md": "题干Markdown（含图形切片引用）", "user_solution_md": "学生解答转录", "error_analysis": "错因分析", "correct_answer": "正确答案", "explanation": "解析"}"""


def _build_vl_request(md_text: str, per_image: list, rel_to_abs: dict) -> tuple:
    """→ (prompt 文本, images payload)。prompt 不含 base64（日志防膨胀，评审 M2）。"""
    lines = [_PROMPT_HEADER, "", "【用户草稿原始内容】", md_text or "(空，仅有图片)", "", "【版面分析结果与附图清单】"]
    images = []
    for pi in per_image:
        rel = pi["image"]
        if pi.get("error"):
            lines.append(f"- 图片 {rel}：版面分析失败（{pi['error']}），请仅凭附图整理。")
            images.append(_image_payload_items(rel_to_abs[rel], _mime_of(rel)))
            continue
        figures_desc = [{"bbox": f["bbox"], "切片路径": f.get("crop_rel")} for f in pi["figures"]]
        lines.append(f"- 图片 {rel}（附图编号 {len(images) + 1}）page_size={pi['page_size']}")
        images.append(_image_payload_items(rel_to_abs[rel], _mime_of(rel)))
        lines.append("  文字块：" + json.dumps(pi["texts"], ensure_ascii=False))
        lines.append("  图形块：" + json.dumps(figures_desc, ensure_ascii=False))
        for f in pi["figures"]:
            if f.get("crop_rel"):
                lines.append(f"  切片附图编号 {len(images) + 1}：{f['crop_rel']}")
                images.append(_image_payload_items(rel_to_abs[f["crop_rel"]], _mime_of(f["crop_rel"])))
    return "\n".join(lines), images


# ---------------------------------------------------------------- C. VL 输出解析与装配

def extract_json(text: str) -> dict:
    """从模型返回中提取首个 JSON 对象；本地修复（围栏/尾逗号）后仍失败则抛错，绝不重发请求。"""
    t = (text or "").strip()
    m = _JSON_FENCE_RE.search(t)
    if m:
        t = m.group(1).strip()
    try:
        return _as_object(json.loads(t))
    except ValueError:
        pass
    s, e = t.find("{"), t.rfind("}")
    if s >= 0 and e > s:
        cand = t[s:e + 1]
        for variant in (cand, _TRAILING_COMMA_RE.sub(r"\1", cand)):
            try:
                return _as_object(json.loads(variant))
            except ValueError:
                continue
    raise ValueError("无法从模型返回中解析 JSON")


def _as_object(obj):
    if isinstance(obj, dict):
        return obj
    raise ValueError("返回不是 JSON 对象")


def assemble_result(contract: dict) -> dict:
    """JSON 契约 → 弹窗三字段回填。用户裁定：解答并入「解析」字段开头，题干只留题目本身。
    公式定界保底：模型偶发输出无 $ 包裹的裸 LaTeX（尤其“如实转录”学生解答），
    逐行确定性包裹，不依赖模型自觉（与 _normalize_stem_images 同思路的防错双保险）。"""
    stem = _wrap_bare_latex(str(contract.get("stem_md") or "").strip())
    parts = []
    sol = _wrap_bare_latex(str(contract.get("user_solution_md") or "").strip())
    if sol:
        parts.append("## 我的解答（如实转录）\n" + sol)
    ea = _wrap_bare_latex(str(contract.get("error_analysis") or "").strip())
    if ea:
        parts.append("## 错在哪里\n" + ea)
    ex = _wrap_bare_latex(str(contract.get("explanation") or "").strip())
    if ex:
        parts.append("## 解析\n" + ex)
    return {"stem_md": stem,
            "correct_answer": _wrap_bare_latex(str(contract.get("correct_answer") or "").strip()),
            "explanation": "\n\n".join(parts)}


# 裸 LaTeX 行识别（命中任一强特征即包）：
#   a) \命令（≥2字母）且含数学痕迹（= ^ _ {）——常规推导行
#   b) 上下标结构 ^{ / _{ ——无命令的推导续行（如 =m^{2}+4m）
#   c) 数学命令白名单——无痕迹的短答案（如 m\geq-1）；白名单外不凭裸 \单词包裹（防 Windows 路径误判）
_BARE_LATEX_CMD_RE = re.compile(r"\\[A-Za-z]{2,}")
_BARE_LATEX_STRUCT_RE = re.compile(r"[\^_]\{")
_MATH_CMD_WHITELIST_RE = re.compile(
    r"\\(?:geq|leq|neq|approx|equiv|sim|pm|mp|times|cdot|div|frac|dfrac|tfrac|sqrt|root"
    r"|Delta|delta|alpha|beta|gamma|theta|lambda|mu|pi|sigma|omega|Phi|phi|circ|angle"
    r"|therefore|because|Rightarrow|rightarrow|leftarrow|letrightarrow|to|in|notin"
    r"|subset|subseteq|cup|cap|emptyset|infty|forall|exists|cdots|ldots|dots"
    r"|text|mathrm|mathbf|mathit|hat|bar|overline|underline|vec"
    r"|lvert|rvert|langle|rangle|begin|end)(?![A-Za-z])")
# ^ 尾部 (?![A-Za-z])：命令名必须完整结束，防 \textbackslash 等被 text 前缀误命中
_MATH_HINT_CHARS = ("=", "^", "_", "{")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")  # 中文含标点/全角符号一并计入（防“由…得…。 ”短叙述行被包）
_BRACE_CONTENT_RE = re.compile(r"\{[^{}]*\}")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s+)")  # Markdown 列表/引用行不参与整行包裹（marker 不得混入公式体）


def _prose_chars_outside_math(s: str) -> int:
    """行内“公式外”的中文字数：剥掉所有 {…} 内容（含 \text{} 包裹的叙述）与 \命令名后
    统计。裸 LaTeX 转录行的中文都在 \text{} 里（结果≈ 0）；而“设函数 f(x) 在 x=3 处可导…”
    这类 Unicode 写法中文题干（无 \命令但含 lim_{…}）结果很大 → 不包（迁移抽查发现的真误判）。"""
    t = _BRACE_CONTENT_RE.sub("", s)
    t = re.sub(r"\\[A-Za-z]+", "", t)
    return len(_CJK_RE.findall(t))


def _wrap_bare_latex(text: str) -> str:
    r"""逐行把“整行裸 LaTeX”包成 $$…$$ 块级公式；其余内容一字不动。
    保守判定（宁漏不错包）：已有定界的行（含 $、\(、\[）、## 标题、![图](路径) 引用、
    无强特征（\命令+痕迹 / ^{_ {结构 / 白名单命令）的普通文字（如 Windows 路径 C:\Users）均不包；
    跨行 \[…\] / $$…$$ 块内部行用状态跟踪跳过（防把已定界公式二次包裹）。
    包裹不改变公式内容本身，仅加定界符，与“如实转录”规则不冲突。"""
    if not text:
        return text
    out_lines = []
    in_block = False  # 处于跨行 \[…\] 或 $$…$$ 块内
    for line in text.split("\n"):
        s = line.strip()
        if in_block:
            out_lines.append(line)
            if "\\]" in s or "$$" in s:  # 块收尾行
                in_block = False
            continue
        if (not s or "$" in s or "\\(" in s or "\\[" in s
                or s.startswith("#") or s.startswith("![") or "](" in s
                or _LIST_MARKER_RE.match(line)):
            out_lines.append(line)
            # 已带定界行仍可能是跨行块 opener：行内 \[ 比 \] 多、或 $$ 出现奇数次 → 块未闭合
            # （评审 Major-1 修复：旧口径只认行首 opener，foo \[ 这类行中部开块漏跟踪，
            #  会让块内裸 LaTeX 行被二次 $$…$$ 包裹砸坏结构）
            if s.count("\\[") > s.count("\\]") or s.count("$$") % 2 == 1:
                in_block = True
            continue
        has_feature = (_BARE_LATEX_STRUCT_RE.search(s)
                       or _MATH_CMD_WHITELIST_RE.search(s)
                       or (_BARE_LATEX_CMD_RE.search(s)
                           and any(h in s for h in _MATH_HINT_CHARS)))
        # 公式外中文（含标点）≥2 字 = 叙述主体行（非整行裸 LaTeX），保守不动
        # （评审 Minor-3 修复：阈值 4→2 + CJK 计入中文标点，“由 \Delta=0 得 m=-2。”不再被误包）
        if has_feature and _prose_chars_outside_math(s) >= 2:
            has_feature = False
        if has_feature:
            # 评审 Minor-5 修复：包裹保留行首/行尾空白，不砸坏缩进结构
            m = re.match(r"(\s*)(.*?)(\s*)$", line)
            out_lines.append(m.group(1) + "$$" + s + "$$" + m.group(3))
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def _normalize_stem_images(stem_md: str, per_image: list) -> str:
    """用户裁定“图就用 Paddle 切片”的确定性保底机制：题干若引用了某原图且该图已裁出切片，
    则把该引用替换为首个切片路径（VL 偶发直接引原图，此处硬保证“图=切片”）；无切片则原样保留。"""
    if not stem_md:
        return stem_md
    first_crop = {}
    for pi in per_image:
        if pi.get("error"):
            continue
        crops = [f["crop_rel"] for f in pi.get("figures", []) if f.get("crop_rel")]
        if crops:
            first_crop[pi["image"]] = crops[0]
    if not first_crop:
        return stem_md

    def _repl(m):
        alt, path = m.group(1), m.group(2).strip().strip("<>")
        tgt = first_crop.get(path)
        return f"![{alt}]({tgt})" if tgt else m.group(0)

    return re.sub(r"!\[([^\]]*)\]\(\s*([^)\s]+)\s*\)", _repl, stem_md)


# ---------------------------------------------------------------- 任务入口

def _strip_remote_images(stem_md: str) -> str:
    """输出侧确定性清洗（评审 Major2）：模型返回的远程图片引用一律剔除，
    与输入侧 md_image_paths 的拒绝口径一致，保证入库内容只引用 vault 内文件。"""
    return re.sub(r"!\[[^\]]*\]\(\s*(?:https?:|data:|ftp:)[^)\s]*\s*\)", "", stem_md or "")


def _dedup_key(user_id: str, md_text: str, items: list) -> str:
    h = hashlib.sha256()
    h.update((user_id or "").encode("utf-8"))
    h.update(b"\0")
    h.update((md_text or "").encode("utf-8"))
    h.update(b"\0")
    for rel, _ in items:
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def start_analyze(md_text: str, items: list, user_id: str = "") -> str:
    """提交智能分析任务（异步，同内容命中运行中任务时复用）。

    items: [(rel_path, abs_path), …]——rel 用于 MD 引用与切片命名，abs 由路由层
    _safe_vault_path 校验后传入（路径安全全部在路由层，服务不反查 vault，无全局态）。"""
    key = _dedup_key(user_id, md_text, items)
    with _inflight_lock:
        old = _inflight.get(key)
        if old:
            st = _registry.get(old, user_id=user_id, consume=False)
            if st and st.get("status") == "running":
                log.log("analyze", "dedup_reuse", "success", {"task_id": old})
                return old
        task_id = _registry.create(user_id=user_id)
        _inflight[key] = task_id
    t = threading.Thread(target=_run, args=(task_id, user_id, md_text, list(items), key), daemon=True)
    t.start()
    return task_id


def get_result(task_id: str, user_id: str = ""):
    """读取结果；done/error 后 TTL 内可重复读取（前端异常可重试，评审 M5）。"""
    return _registry.get(task_id, user_id=user_id, consume=False)


def _run(task_id: str, uid: str, md_text: str, items: list, key: str = "") -> None:
    try:
        _run_inner(task_id, uid, md_text, items)
    finally:
        if key:
            with _inflight_lock:
                if _inflight.get(key) == task_id:
                    _inflight.pop(key, None)


def _run_inner(task_id: str, uid: str, md_text: str, items: list) -> None:
    with _SEM:
        deadline = time.time() + BASE_WAIT_S + PER_EXTRA_IMAGE_S * max(0, len(items) - 1)
        try:
            rel_to_abs = {rel: abs_p for rel, abs_p in items}
            per_image = []
            for rel, abs_path in items:
                try:
                    info = _analyze_one_image(rel, abs_path, deadline)
                    per_image.append(info)
                    log.log("analyze", "paddle_layout_done", "success",
                            {"image": rel, "texts": len(info["texts"]),
                             "figures": len(info["figures"])})
                    for f in info["figures"]:
                        if f.get("crop_rel"):  # 切片与同目录兄弟文件同样受路由校验保护（仅新文件）
                            rel_to_abs[f["crop_rel"]] = os.path.join(
                                os.path.dirname(abs_path), os.path.basename(f["crop_rel"]))
                except Exception as e:  # noqa: BLE001 单图版面失败不拖垮整任务（降级：仅原图发 VL）
                    log.log("analyze", "paddle_layout_failed", "warn",
                            {"image": rel, "err": str(e)[:120]})
                    per_image.append({"image": rel, "error": str(e)[:120]})
            prompt, images = _build_vl_request(md_text, per_image, rel_to_abs)
            from llm_provider_factory import call_llm_vision  # 延迟导入避免启动环
            raw = call_llm_vision(uid, prompt, images, scene="错题智能分析")
            contract = extract_json(raw)
            result = assemble_result(contract)
            result["stem_md"] = _strip_remote_images(_normalize_stem_images(result["stem_md"], per_image))
            if not result["stem_md"]:
                raise ValueError("模型返回的题干为空")
            _registry.finish(task_id, "done", **result)
            log.log("analyze", "error_analyze_done", "success",
                    {"chars": len(result["stem_md"]), "images": len(images)})
        except Exception as e:  # noqa: BLE001 兜底：任何异常转 error，前端降级手填
            _registry.finish(task_id, "error", error=str(e)[:200])
            log.log_error("analyze", "error_analyze_failed", e)
