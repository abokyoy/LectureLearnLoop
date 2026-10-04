# -*- coding: utf-8 -*-
"""PaddleOCR-VL 文档解析 Job API 客户端（文件导入 PDF→MD 专用）。

提炼自 AIFinFlowX 生产验证实现 services/coordinate_fusion/paddle_client.py，
同形三段：submit_job / query_job / download_jsonl。差异（方案文档 3.1）：
- optionalPayload 面向讲义场景：关旋转/畸变/图表/印章，formatBlockContent 开；
- 轮询由 import_service worker 驱动（进度需回写任务表），本模块不提供阻塞 wait；
- jobId 校验字符集后才允许拼入查询 URL（评审优化项 6）。
仅依赖 requests；不依赖 Flask/DB，可在 worker 线程安全使用。
"""
from __future__ import annotations

import json
import os
import re
import time

import requests

import config

# 提交重试：瞬时错误（队列满 400/10010、5xx、限流、网络抖动）指数退避；鉴权类永久失败即抛。
SUBMIT_RETRIES = 3
SUBMIT_BACKOFF_BASE = 5.0

_JOB_ID_RE = re.compile(r"[\w-]{1,128}")


class PaddleDocError(Exception):
    """永久失败（鉴权/响应结构非法/参数非法），不重试。"""


class PaddleDocTransientError(PaddleDocError):
    """瞬时失败（队列满/5xx/网络抖动），worker 可择机重投。"""


def _headers():
    return {"Authorization": f"bearer {config.PADDLE_OCR_TOKEN}"}


def _retryable_status(status_code):
    if status_code in (400, 408, 409, 422, 429):
        return True
    return status_code is not None and status_code >= 500


def build_payload():
    # PDF 讲义天然正位：旋转分类/去畸变/图表/印章均关（与发票场景取舍不同，见方案 3.1）
    return {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
        "useSealRecognition": False,
        "formatBlockContent": True,
    }


def submit_job(file_path):
    """提交本地 PDF，返回 job_id。瞬时错误指数退避重试 SUBMIT_RETRIES 次。"""
    if not config.PADDLE_OCR_TOKEN:
        raise PaddleDocError("未配置 PADDLE_OCR_TOKEN（.env）")
    name = os.path.basename(file_path)
    payload = json.dumps(build_payload())
    last_error = PaddleDocTransientError("未知错误")
    for attempt in range(SUBMIT_RETRIES + 1):
        try:
            with open(file_path, "rb") as fp:
                resp = requests.post(
                    config.PADDLE_OCR_JOB_URL,
                    headers=_headers(),
                    data={"model": config.PADDLE_OCR_MODEL, "optionalPayload": payload},
                    files={"file": (name, fp)},
                    timeout=120,
                )
            if resp.status_code == 200:
                try:
                    job_id = resp.json()["data"]["jobId"]
                except (ValueError, KeyError, TypeError):
                    raise PaddleDocError(f"提交响应结构异常: {resp.text[:200]}")
                if not _JOB_ID_RE.fullmatch(str(job_id)):
                    raise PaddleDocError(f"非法 jobId: {job_id!r}")
                return job_id
            if not _retryable_status(resp.status_code):
                raise PaddleDocError(f"PaddleOCR 返回 {resp.status_code}: {resp.text[:200]}")
            last_error = PaddleDocTransientError(
                f"PaddleOCR 返回 {resp.status_code}: {resp.text[:200]}"
            )
        except requests.RequestException as e:
            last_error = PaddleDocTransientError(f"提交 PaddleOCR 失败: {e}")
        if attempt >= SUBMIT_RETRIES:
            break
        time.sleep(SUBMIT_BACKOFF_BASE * (2 ** attempt))
    raise last_error


def query_job(job_id):
    """查询 Job 状态，返回 data dict（state / extractProgress / resultUrl / errorMsg）。"""
    if not _JOB_ID_RE.fullmatch(str(job_id)):
        raise PaddleDocError(f"非法 jobId: {job_id!r}")
    try:
        resp = requests.get(f"{config.PADDLE_OCR_JOB_URL}/{job_id}", headers=_headers(), timeout=30)
        return resp.json().get("data") or {}
    except (requests.RequestException, ValueError) as e:
        raise PaddleDocTransientError(f"状态查询暂时失败: {e}")


def download_jsonl(json_url):
    """下载 JSONL 结果全文（官方 resultUrl 为带签名的 https 直链）。"""
    if not str(json_url).startswith("https://"):
        raise PaddleDocError(f"非法结果地址: {json_url!r}")
    try:
        resp = requests.get(json_url, timeout=120)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        raise PaddleDocTransientError(f"下载结果失败: {e}")
