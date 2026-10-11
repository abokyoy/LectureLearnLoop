# -*- coding: utf-8 -*-
"""错题图片 OCR 识别（知识库独立错题录入，2026-10-12）。

链路：本地图 → Pillow 包装单页 PDF → paddle_doc_client 提交/轮询/下载 →
提取 layoutParsingResults[].markdown.text → 去掉远程签名图片引用后返回纯文本。
内存任务表 + daemon 线程：前端轮询取结果；服务不可用/超时任务以 error 结束，
前端降级为「只插图、手填文字」（用户裁定的兜底）。任务为瞬态，重启丢失可接受。
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import threading
import time

from PIL import Image

from logger_module import debug_logger as log
from services import paddle_doc_client as paddle
from services.task_registry import TaskRegistry

POLL_INTERVAL_S = 3.0
MAX_WAIT_S = 180.0
TASK_TTL_S = 600.0  # 客户端放弃轮询后的回收窗口，防任务表永久驻留（CodeReview Major-2）

# 任务表：task_id -> {status: running|done|error, text?, error?, user, ts}
# 2026-10-13 收敛：改用公共 TaskRegistry（与 error_analyze 同源，consume 保留既有“读取即弃”语义）
_registry = TaskRegistry(TASK_TTL_S)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def is_image(rel_name: str) -> bool:
    return str(rel_name).lower().endswith(_IMAGE_EXTS)


def _extract_md(jsonl_text: str) -> str:
    """jsonl → 拼接 MD 文本；剔除会过期的远程签名图片 URL 引用（题干原图由用户自行上传）。"""
    texts = []
    for line in (jsonl_text or "").strip().splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # 单行畸形不毁整篇（同 import_service 口径）
        for res in ((obj.get("result") or {}).get("layoutParsingResults")) or []:
            md = ((res.get("markdown") or {}).get("text") or "").strip()
            if md:
                texts.append(md)
    joined = "\n\n".join(texts)
    joined = re.sub(r"!\[[^\]]*\]\(https?://[^)]+\)", "", joined)
    return joined.strip()


def start_ocr(image_path: str, user_id: str = "") -> str:
    """提交识别任务，返回 task_id（异步，结果经 get_result 轮询读取；绑发起者防跨用户读取）。"""
    task_id = _registry.create(user_id=user_id)
    threading.Thread(target=_run, args=(task_id, image_path), daemon=True).start()
    return task_id


def get_result(task_id: str, user_id: str = ""):
    """读取任务结果；done/error 读取即弃（running 可反复查）。非发起者视同不存在。"""
    return _registry.get(task_id, user_id=user_id, consume=True)


def _image_to_pdf_bytes(image_path: str) -> bytes:
    im = Image.open(image_path)
    im = im.convert("RGB")  # 统一色域，PNG 透明/调色板均可
    buf = io.BytesIO()
    im.save(buf, format="PDF")
    return buf.getvalue()


# 公共别名：error_analyze 复用同一包装逻辑（公共函数注册制）
image_to_pdf_bytes = _image_to_pdf_bytes


def _run(task_id: str, image_path: str) -> None:
    tmp_pdf = None
    try:
        data = _image_to_pdf_bytes(image_path)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(data)
            tmp_pdf = tf.name
        job_id = paddle.submit_job(tmp_pdf)
        deadline = time.time() + MAX_WAIT_S
        while time.time() < deadline:
            try:
                st = paddle.query_job(job_id)
            except paddle.PaddleDocTransientError as e:
                # 外网瞬时抖动（V2RAYN）不一次判死，继续轮询到超时（同书籍导入教训）
                log.log("ocr", "error_ocr_poll_transient", "warn", {"err": str(e)[:120]})
                time.sleep(POLL_INTERVAL_S)
                continue
            state = st.get("state")
            if state == "done":
                json_url = (st.get("resultUrl") or {}).get("jsonUrl")
                if not json_url:
                    raise paddle.PaddleDocError("结果中没有 jsonUrl")
                text = _extract_md(paddle.download_jsonl(json_url))
                _registry.finish(task_id, "done", text=text)
                log.log("ocr", "error_ocr_done", "success", {"chars": len(text)})
                return
            if state == "failed":
                raise paddle.PaddleDocError(f"识别任务失败: {st.get('errorMsg') or '未知原因'}")
            time.sleep(POLL_INTERVAL_S)
        _registry.finish(task_id, "error", error="识别超时，请手动补录文字")
    except Exception as e:  # noqa: BLE001 后台线程兜底：任何异常转为任务 error，前端降级手填
        _registry.finish(task_id, "error", error=str(e)[:200])
        log.log_error("ocr", "error_ocr_failed", e)
    finally:
        if tmp_pdf:
            try:
                os.unlink(tmp_pdf)
            except OSError:
                pass
