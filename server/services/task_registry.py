# -*- coding: utf-8 -*-
"""内存异步任务表公共件（2026-10-13，CodeReview A2：error_ocr / error_analyze 共用，
禁止两套近似实现）。

模式：create 登记 running → daemon 线程处理 → finish 写终态 → 前端轮询 get。
TTL 回收：以条目 ts 起算，过期清理防永久驻留；finish 刷新 ts（结果保留窗口从终态时刻起算）。
任务瞬态，服务重启丢失可接受（同 error_ocr 既有约定）。
"""
from __future__ import annotations

import threading
import time
import uuid


class TaskRegistry:
    def __init__(self, ttl_s: float = 600.0):
        self.ttl_s = float(ttl_s)
        self._tasks: dict = {}
        self._lock = threading.Lock()

    def create(self, user_id: str = "") -> str:
        """登记 running 任务，返回 task_id（绑发起者防跨用户读取）。"""
        task_id = uuid.uuid4().hex[:16]
        now = time.time()
        with self._lock:
            self._sweep_locked(now)
            self._tasks[task_id] = {"status": "running", "user": user_id, "ts": now}
        return task_id

    def finish(self, task_id: str, status: str, user_id: str = "", **fields) -> None:
        """写终态（done/error 等）；未显式给 user_id 时保留 create 时绑定的发起者。"""
        with self._lock:
            prev = self._tasks.get(task_id) or {}
            entry = {"status": status, "user": user_id or prev.get("user", ""),
                     "ts": time.time()}
            entry.update(fields)
            self._tasks[task_id] = entry

    def get(self, task_id: str, user_id: str = "", consume: bool = False):
        """读取任务状态；非发起者视同不存在。

        consume=True：done/error 读取即弃（error_ocr 既有语义）；
        consume=False：TTL 内可重复读取（前端处理异常后可重试，error_analyze 采用）。
        """
        now = time.time()
        with self._lock:
            self._sweep_locked(now)
            t = self._tasks.get(task_id)
            if not t or t.get("user") != user_id:
                return None
            if consume and t.get("status") != "running":
                self._tasks.pop(task_id, None)
            return {k: v for k, v in t.items() if k not in ("user", "ts")}

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for v in self._tasks.values() if v.get("status") == "running")

    def _sweep_locked(self, now: float) -> None:
        """过期任务回收（调用方持锁）。"""
        dead = [k for k, v in self._tasks.items() if now - v.get("ts", now) > self.ttl_s]
        for k in dead:
            self._tasks.pop(k, None)
