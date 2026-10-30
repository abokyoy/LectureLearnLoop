# -*- coding: utf-8 -*-
"""错题批量录入（2026-10-14，知识库「新增错题 → 批量新增错题」页签）。

链路：前端多图上传（本地多选 / 手机拍照，均先落 vault 截图/）→ 逐图全屏框选题目
（归一化坐标 0~1）→ 提交 {image, boxes:[{id,x,y,w,h}]} → 后端按原图分辨率逐框裁剪
（截图/原名_q{框号}_{任务前6位}.png，任务前缀防跨批覆盖旧题干引用的切片）→
同源图裁剪图分组（每组≤3 题）走 error_analyze.recognize_group「切片图一次全给大模型，
返回一组题」（2026-10-15 用户裁定）；组内单题失败逐题回退 run_pipeline 单题管线，
几何图经 Paddle 版面切片完整保留进题干的规则不变（回退一次的题另计一次积分）。
进度经 TaskRegistry update 上报（total/finished/results），前端轮询展示进度条；
单题失败不拖垮整批——该题标记 error，前端置灰不可勾选。
入库复用前端逐题 POST /api/kb/errors（架构收敛：不新建入库链路，独立错题口径）。
任务瞬态重启丢失可接受（同 error_ocr 约定）；批量任务全局单并发（一批十几次 VL 调用，
防并发批量挤爆计费链与 Paddle 额度）。
"""
from __future__ import annotations

import glob as _glob
import os
import threading
import time

from PIL import Image

from logger_module import debug_logger as log
from services import error_analyze
from services.task_registry import TaskRegistry

MAX_IMAGES = 20               # 单批图片数上限（路由层校验）
MAX_BOXES_PER_IMAGE = 10      # 单图框数上限
MAX_BOXES_TOTAL = 50          # 单批总题数上限
PER_QUESTION_WAIT_S = error_analyze.BASE_WAIT_S  # 单题超时预算（与单题智能分析一致）
GROUP_WAIT_S = error_analyze.BASE_WAIT_S + 2 * error_analyze.PER_EXTRA_IMAGE_S  # 组预算：逐题 Paddle + 一次大输出 VL 调用
MAX_PROBLEMS_PER_CALL = 3     # 一次 VL 调用最多几道题（vl_max_tokens 默认 4096，每题全量输出约 500~1000 token；再大易截断→整组回退得不偿失）
TASK_TTL_S = 1800.0           # 结果保留窗口（批量整体耗时长于单任务，TTL 放宽）
MIN_EDGE_PX = 32              # 裁剪最短边下限：Qwen3-VL 要求宽高均 >28px，27px 实测被 400 拒；取 32 留余量，过小在服务层拦截（零外呼零扣分）

# 任务表：task_id -> {status, total, finished, results:[{image, box_id, ok, stem_md, ...}]}
_registry = TaskRegistry(TASK_TTL_S)
_SEM = threading.Semaphore(1)  # 全局单并发（评审沿用 import_service 限并发惯例）


def start_batch(items: list, user_id: str = "") -> str:
    """提交批量识别。items: [{image: rel, abs: 绝对路径, boxes:[{id,x,y,w,h}]}]，
    坐标为相对原图宽高的 0~1 比例；路径安全已由路由层 _safe_vault_path 校验。"""
    task_id = _registry.create(user_id=user_id)
    total = sum(len(it["boxes"]) for it in items)
    _registry.update(task_id, total=total, finished=0, results=[])
    threading.Thread(target=_run, args=(task_id, user_id, items), daemon=True).start()
    log.log("batch", "batch_start", "success", {"task": task_id, "imgs": len(items), "boxes": total})
    return task_id


def get_result(task_id: str, user_id: str = ""):
    """读取进度/结果；done 后 TTL 内可重复读取（前端异常可重试，同 error_analyze 口径）。"""
    return _registry.get(task_id, user_id=user_id, consume=False)


def _crop_box(im: Image.Image, box: dict, rel: str, abs_path: str, task_id: str):
    """归一化框 → 原图分辨率裁剪落盘。返回 (crop_rel, crop_abs)；过小抛 ValueError。"""
    lw, lh = im.size
    x1 = max(0.0, min(1.0, float(box["x"])))
    y1 = max(0.0, min(1.0, float(box["y"])))
    x2 = max(0.0, min(1.0, float(box["x"]) + float(box["w"])))
    y2 = max(0.0, min(1.0, float(box["y"]) + float(box["h"])))
    px = (int(x1 * lw), int(y1 * lh), int(x2 * lw), int(y2 * lh))
    if px[2] - px[0] < MIN_EDGE_PX or px[3] - px[1] < MIN_EDGE_PX:
        raise ValueError("框选区域过小，无法识别，请框选稍大区域")
    stem, ext = os.path.splitext(rel)
    crop_rel = f"{stem}_q{int(box['id'])}_{task_id[:6]}{(ext or '.png').lower()}"
    crop_abs = os.path.join(os.path.dirname(abs_path), os.path.basename(crop_rel))
    im.convert("RGB").crop(px).save(crop_abs)
    log.log("batch", "box_cropped", "success", {"src": rel, "box": box["id"], "crop": crop_rel, "px": list(px)})
    return crop_rel, crop_abs


def _fail_entry(rel: str, box: dict, err: str) -> dict:
    return {"image": rel, "box_id": box.get("id"), "ok": False, "error": err[:200],
            "stem_md": "", "correct_answer": "", "explanation": ""}


def _done_entry(rel: str, box: dict, crop_rel: str, res: dict) -> dict:
    return {"image": rel, "box_id": box.get("id"), "ok": True, "error": None,
            "crop": crop_rel, "stem_md": res["stem_md"],
            "correct_answer": res["correct_answer"], "explanation": res["explanation"]}


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _purge_crop(crop_abs: str) -> None:
    """删除失败题裁片及其 Paddle 派生 _figN 图形切片（防孤儿，CodeReview Minor-3：
    版面阶段成功但内容装配失败的题，切片已落盘却不会被任何题干引用）。"""
    stem = os.path.splitext(crop_abs)[0]
    for p in _glob.glob(stem + "_fig*") + [crop_abs]:
        try:
            os.remove(p)
        except OSError:
            pass


def _run_group(task_id: str, uid: str, rel: str, group: list, results: list, finished: int) -> int:
    """一张同源图的≤N题裁剪：一次 recognize_group 分组识别，组内失败/缺题的逐题回退
    run_pipeline（用户裁定：失败逐题回退，不拖垮同组已识别成功的题）。逐题追加 results
    并上报进度，返回新 finished。group 元素：(box, crop_rel, crop_abs)。"""
    mapped = {}
    try:
        outs = error_analyze.recognize_group(
            uid, [(cr, ca) for _, cr, ca in group], time.time() + GROUP_WAIT_S,
            scene="批量识别错题")
        mapped = dict(zip([cr for _, cr, _ca in group], outs))
        log.log("batch", "batch_group_done", "success",
                {"image": rel, "n": len(group), "ok": sum(1 for o in outs if o.get("ok"))})
    except Exception as e:  # noqa: BLE001 整组失败（调用异常/数组不可解）：全组逐题回退
        log.log("batch", "batch_group_failed", "warn", {"image": rel, "err": str(e)[:160]})
    for b, crop_rel, crop_abs in group:
        out = mapped.get(crop_rel) or {}
        if out.get("ok"):
            results.append(_done_entry(rel, b, crop_rel, out))
            finished += 1
            _registry.update(task_id, finished=finished, results=list(results))
            continue
        # 单题回退：走原逐题管线（分组已扣一次，回退题再扣一次，用户裁定速度优先、失败才回退）
        try:
            res = error_analyze.run_pipeline(
                uid, "", [(crop_rel, crop_abs)], time.time() + PER_QUESTION_WAIT_S,
                scene="批量识别错题")
            results.append(_done_entry(rel, b, crop_rel, res))
            log.log("batch", "batch_q_fallback_ok", "success", {"image": rel, "box": b["id"]})
        except Exception as e:  # noqa: BLE001 单题失败隔离：标记该题 error，继续下一题
            if crop_abs:  # 失败题裁片与派生切片均无引用，删除防孤儿（CodeReview Minor-5/Minor-3）
                _purge_crop(crop_abs)
            err = str(e)
            if out.get("error"):  # 保留分组阶段的失败原因，便于定位（如截断/缺题）
                err = f"{out['error']}；单题重识别也失败: {err}"
            results.append(_fail_entry(rel, b, err))
            log.log_error("batch", "batch_q_failed", e)
        finished += 1
        _registry.update(task_id, finished=finished, results=list(results))
    return finished


def _run(task_id: str, uid: str, items: list) -> None:
    with _SEM:
        results: list = []
        finished = 0
        total = sum(len(it["boxes"]) for it in items)
        try:
            for it in items:
                rel, abs_path, boxes = it["image"], it["abs"], it["boxes"]
                try:
                    im = Image.open(abs_path)
                    im.load()  # 截断/损坏文件在这里抛，不留到逐框循环反复失败
                except Exception as e:  # noqa: BLE001 原图不可读：该图所有框逐题失败，不毁整批
                    for b in boxes:
                        results.append(_fail_entry(rel, b, f"原图无法打开：{e}"))
                        finished += 1
                    _registry.update(task_id, finished=finished, results=list(results))
                    continue
                entries = []  # 裁剪成功的 (box, crop_rel, crop_abs)，按题序待分组
                try:
                    for b in boxes:
                        try:
                            crop_rel, crop_abs = _crop_box(im, b, rel, abs_path, task_id)
                            entries.append((b, crop_rel, crop_abs))
                        except Exception as e:  # noqa: BLE001 裁剪即失败（如框选过小）：不送识别不扣分
                            results.append(_fail_entry(rel, b, str(e)))
                            finished += 1
                            log.log_error("batch", "box_crop_failed", e)
                            _registry.update(task_id, finished=finished, results=list(results))
                finally:
                    im.close()  # Windows 文件锁窗口（CodeReview Minor-4）：批跑期间不滞留句柄
                for g in _chunks(entries, MAX_PROBLEMS_PER_CALL):
                    finished = _run_group(task_id, uid, rel, g, results, finished)
            ok_n = sum(1 for r in results if r.get("ok"))
            _registry.finish(task_id, "done", total=len(results), finished=finished, results=results)
            log.log("batch", "batch_done", "success", {"task": task_id, "total": len(results), "ok": ok_n})
        except Exception as e:  # noqa: BLE001 兜底：任何未预期异常落 error，已完成的题目仍随附
            _registry.finish(task_id, "error", error=str(e)[:200],
                             total=total, finished=finished, results=results)
            log.log_error("batch", "batch_failed", e)
