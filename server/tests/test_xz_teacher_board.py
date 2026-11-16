# -*- coding: utf-8 -*-
"""小智云端讲师黑板 P1 断言测试（2026-11-04）。

三块覆盖，零真实小智云调用（接入点指向 127.0.0.1 进程内假云）：
1. MCP 桥协议面：假小智云 websockets server 扮云端，向桥收发
   initialize / tools/list / tools/call / ping / 通知 / 未知方法，逐条对照协议应答；
2. 黑板工具业务面：board_write / board_highlight / board_clear / board_show_problem /
   get_lesson_material（真 PG，独立测试用户，测后清理；素材链复用六期 _error_explain_pack）；
3. HTTP 与页面挂接：/api/board/state rev 轮询、/api/board/clear、鉴权 401、
   用户隔离、/fragments/teacher_board 白名单、/teacher_board 页面路由。
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import websockets  # noqa: E402

import config  # noqa: E402
import credits_service as cr  # noqa: E402
import llm_provider_factory as LP  # noqa: E402
import routes_micro_course as RMC  # noqa: E402
from app import create_app  # noqa: E402
from knowledge_management import DatabaseManager, PracticeRecordManager  # noqa: E402
from services import board_explainer as BE  # noqa: E402
from services import board_lesson as BL  # noqa: E402
from services import board_plot as BP  # noqa: E402
from services import lecture_board as LB  # noqa: E402
from services import mcp_bridge as MB  # noqa: E402
from services import xz_device as XD  # noqa: E402

APP = create_app()


class FakeCloud:
    """进程内假小智云：WebSocket server 等桥来连，测试线程从云端视角发 JSON-RPC。"""

    def __init__(self):
        self.loop = None
        self.thread = None
        self.port = None
        self.ws = None           # 桥（客户端）连进来后的会话
        self.orphan = 0          # 桥不该回的应答计数（如对通知回话）
        self._pending = {}
        self._id = 0
        self._ready = threading.Event()

    def start(self):
        self.thread = threading.Thread(target=self._boot, daemon=True,
                                       name="fake-xz-cloud")
        self.thread.start()
        assert self._ready.wait(15) and self.port, "假云未起来"

    def _boot(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._serve())
        except Exception:  # noqa: BLE001 测停/断链均正常
            pass

    async def _serve(self):
        srv = await websockets.serve(self._handler, "127.0.0.1", 0)
        self.port = srv.sockets[0].getsockname()[1]
        self._ready.set()
        await asyncio.Future()  # 常驻，直到 loop 被停

    async def _handler(self, ws, path=None):
        self.ws = ws
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    self.orphan += 1
                    continue
                rid = msg.get("id")
                fut = self._pending.pop(rid, None) if rid is not None else None
                if fut is not None:
                    if not fut.done():
                        fut.set_result(msg)
                else:
                    self.orphan += 1  # 无主应答（通知被回话等协议违例）
        except Exception:  # noqa: BLE001 测停/断链均正常
            pass

    def wait_bridge(self, timeout=60):
        t0 = time.time()
        while self.ws is None and time.time() - t0 < timeout:
            time.sleep(0.05)
        return self.ws is not None

    def request(self, method, params=None, timeout=40):
        self._id += 1
        rid = self._id
        fut = self.loop.create_future()
        self._pending[rid] = fut
        asyncio.run_coroutine_threadsafe(
            self.ws.send(json.dumps({"jsonrpc": "2.0", "id": rid,
                                     "method": method, "params": params or {}})),
            self.loop).result(15)
        return asyncio.run_coroutine_threadsafe(self._await(fut, timeout),
                                                self.loop).result(timeout + 15)

    async def _await(self, fut, timeout):
        return await asyncio.wait_for(fut, timeout)

    def notify(self, method):
        asyncio.run_coroutine_threadsafe(
            self.ws.send(json.dumps({"jsonrpc": "2.0", "method": method})),
            self.loop).result(15)

    def call_tool(self, name, arguments):
        r = self.request("tools/call", {"name": name, "arguments": arguments})
        return r["result"]["content"][0]["text"]

    def stop(self):
        # 先关与桥的会话：否则桥线程 async for 挂在读上无法退出，
        # 后续类 start 时旧桥可能复活抢连新云（跨类生命周期竞争）
        if self.ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop).result(5)
            except Exception:  # noqa: BLE001
                pass
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)


def _wait_bridge_thread_gone(timeout=15):
    """等 xz-mcp-bridge 线程真退出（stop 后最迟经 RETRY_S 醒来 break）。
    多测试类共用进程时防止旧桥僵尸重连。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not [t for t in threading.enumerate() if t.name == "xz-mcp-bridge"]:
            return True
        time.sleep(0.05)
    return False


_LIVE_OTHER = [None]   # 真活着的「别的进程」（单桥闸门 2026-11-10 查活后必需）


def _live_other_pid():
    """起一个全程存活的子进程充当另一实例持有者，本模块退出时自动收尾。
    闸门现在只认「心跳新鲜 且 pid 真活着」，拿假 pid 冒充活桥已不再成立。"""
    if _LIVE_OTHER[0] is None:
        import atexit
        import subprocess
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        _LIVE_OTHER[0] = p

        def _reap():
            try:
                p.kill()
                p.wait(timeout=5)
            except OSError:
                pass
        atexit.register(_reap)
    return _LIVE_OTHER[0].pid


def _dead_pid():
    """确已退出的子进程 pid：模拟被 kill 后残留桥锁的持有者。"""
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=60)
    return p.pid


class XzTeacherBoardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.uidA, cls.tokA = cls._register("xzA_" + cls.suffix)
        cls.uidB, cls.tokB = cls._register("xzB_" + cls.suffix)
        cls.userA = "xzA_" + cls.suffix
        cls.hA = {"Authorization": "Bearer " + cls.tokA}
        cls.hB = {"Authorization": "Bearer " + cls.tokB}
        # A 造一道真错题（kp → practice_records → error_questions 三连）
        db = DatabaseManager(str(config.DB_PATH))
        cls.conn = db.get_connection()
        cur = cls.conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
            "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (cls.uidA, "测试学科XZ" + cls.suffix, "极限", "数列极限定义", 40))
        cls.kp = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
            "question_content, user_answer, is_correct, options_json) "
            "VALUES (?, ?, ?, ?, ?, 0, ?) RETURNING id",
            (cls.uidA, "测试学科XZ" + cls.suffix, cls.kp,
             "lim(n→∞) (1+1/n)^n = ? A.1 B.e C.∞ D.0", "A",
             json.dumps(["1", "e", "∞", "0"], ensure_ascii=False)))
        cls.pr = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
            "practice_record_id, current_proficiency, correct_answer, explanation) "
            "VALUES (?, ?, ?, ?, 20, 'B', '重要极限 (1+1/n)^n→e') RETURNING id",
            (cls.uidA, "测试学科XZ" + cls.suffix, cls.kp, cls.pr))
        cls.err = cur.fetchone()[0]
        # 五期 C 案第二题：题干含「函数/图象」关键词，验写题返回的建议图型行
        cur = cls.conn.execute(
            "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
            "question_content, user_answer, is_correct, options_json) "
            "VALUES (?, ?, ?, ?, ?, 0, ?) RETURNING id",
            (cls.uidA, "测试学科XZ" + cls.suffix, cls.kp,
             "二次函数 y=x^2-2x 的图象开口方向与顶点坐标是什么？", "A",
             json.dumps(["向上 (1,1)", "向上 (1,-1)", "向下 (-1,-1)", "向下 (0,0)"],
                        ensure_ascii=False)))
        pr_fn = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
            "practice_record_id, current_proficiency, correct_answer, explanation) "
            "VALUES (?, ?, ?, ?, 20, 'B', '配方法求顶点，抛物线开口向上') RETURNING id",
            (cls.uidA, "测试学科XZ" + cls.suffix, cls.kp, pr_fn))
        cls.err_fn = cur.fetchone()[0]
        cls.conn.commit()
        # 起假云 → 桥指假云 → 拉桥（重连间隔缩到 1s 防测试拖沓）
        cls.cloud = FakeCloud()
        cls.cloud.start()
        cls._orig_ep = config.XZ_MCP_ENDPOINT
        cls._orig_user = config.XZ_MCP_USER
        config.XZ_MCP_ENDPOINT = f"ws://127.0.0.1:{cls.cloud.port}/mcp"
        config.XZ_MCP_USER = cls.userA
        cls._orig_dbget = MB._db_get
        MB._db_get = lambda key: ""   # 隔离共享库里设置页真实接入点，防误连真云
        # 本机单桥闸门隔离：正式 9992 在跑时不得被活锁拒起假桥（2026-11-09 双桥事故）
        cls._orig_lock = MB._LOCK_FILE
        MB._LOCK_FILE = config.DATA_DIR / f"xz_mcp_bridge.test_{cls.suffix}.lock"
        MB.RETRY_S = 1
        assert MB.start_in_background()
        assert cls.cloud.wait_bridge(), "桥未连上假小智云"

    @classmethod
    def tearDownClass(cls):
        MB.stop()
        _wait_bridge_thread_gone(timeout=10)  # 评审 N3：线程未退就恢复路径会踩真锁
        MB._db_get = cls._orig_dbget
        MB._LOCK_FILE = cls._orig_lock
        cls._cleanup_test_lock()
        cls.cloud.stop()
        config.XZ_MCP_ENDPOINT = cls._orig_ep
        config.XZ_MCP_USER = cls._orig_user
        for uid in (cls.uidA, cls.uidB):
            cls.conn.execute("DELETE FROM error_questions WHERE user_id = ?", (uid,))
            cls.conn.execute("DELETE FROM practice_records WHERE user_id = ?", (uid,))
            cls.conn.execute("DELETE FROM knowledge_points WHERE user_id = ?", (uid,))
            cls.conn.execute("DELETE FROM user_credits WHERE user_id = ?", (uid,))
        cls.conn.execute("DELETE FROM users WHERE user_id IN (?, ?)", (cls.uidA, cls.uidB))
        cls.conn.commit()
        cls.conn.close()

    @classmethod
    def _cleanup_test_lock(cls):
        try:
            os.remove(config.DATA_DIR / f"xz_mcp_bridge.test_{cls.suffix}.lock")
        except OSError:
            pass

    @classmethod
    def _register(cls, username):
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        return uid, tok

    # ---- 工具 ----
    def _state(self, h, since=-1):
        r = self.client.get(f"/api/board/state?since={since}", headers=h)
        self.assertEqual(r.status_code, 200)
        return r.get_json()["data"]

    # ============================================================ 协议面
    def test_01_initialize(self):
        r = self.cloud.request("initialize", {"protocolVersion": "2025-06-18",
                                              "capabilities": {}})
        res = r["result"]
        self.assertEqual(res["protocolVersion"], "2025-06-18")  # 回显云端版本
        self.assertIn("tools", res["capabilities"])
        self.assertEqual(res["serverInfo"]["name"], MB.SERVER_INFO["name"])

    def test_02_tools_list(self):
        r = self.cloud.request("tools/list")
        tools = r["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertEqual(names, LB._TOOL_NAMES)
        self.assertEqual(len(tools), 12)   # 十张板书工具 + 备课双工具（阶段四）
        self.assertIn("lesson_prepare", names)
        self.assertIn("lesson_list_preps", names)
        for t in tools:
            self.assertLessEqual(len(t["description"]), 400, t["name"] + " 描述超长")
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_03_board_write_via_bridge(self):
        text = self.cloud.call_tool("board_write",
                                    {"content": r"\lim_{n\to\infty}(1+1/n)^n=e",
                                     "kind": "formula"})
        self.assertIn("已写上黑板：#1", text)
        st = self._state(self.hA)
        kinds = [i["kind"] for i in st["items"]]
        self.assertIn("formula", kinds)

    def test_04_highlight_and_missing(self):
        ids = [i["id"] for i in self._state(self.hA)["items"]]
        text = self.cloud.call_tool("board_highlight", {"item_id": ids[0]})
        self.assertIn("已点亮", text)
        it = [i for i in self._state(self.hA)["items"] if i["id"] == ids[0]][0]
        self.assertTrue(it["highlighted"])
        text = self.cloud.call_tool("board_highlight", {"item_id": 99999})
        self.assertIn("没有卡", text)

    def test_05_lesson_material_list_and_pack(self):
        text = self.cloud.call_tool("get_lesson_material", {})
        self.assertIn("最近错题清单", text)
        self.assertIn(str(self.err), text)
        text = self.cloud.call_tool("get_lesson_material", {"error_id": "999999"})
        self.assertIn("没找到", text)
        text = self.cloud.call_tool("get_lesson_material", {"error_id": str(self.err)})
        self.assertIn("【题目】", text)
        self.assertIn("【正确答案】", text)

    def test_06_show_problem_writes_board(self):
        before = len(self._state(self.hA)["items"])
        text = self.cloud.call_tool("board_show_problem", {"error_id": str(self.err)})
        self.assertIn("已写上黑板", text)
        self.assertIn("【题目】", text)
        st = self._state(self.hA)
        # 讲义化拆卡：题干卡 + 选项卡两张（题干不再与选项揉成一段文字墙）
        self.assertEqual(len(st["items"]), before + 3)  # topic \u4e3b\u5e72 + \u9898\u5e72 + \u9009\u9879
        tops = [i for i in st["items"] if i["kind"] == "topic"]
        self.assertTrue(tops)
        prob0 = [i for i in st["items"] if i["kind"] == "problem"][-1]
        self.assertEqual(prob0["parent_id"], tops[-1]["id"])
        self.assertEqual(str(st["source_error_id"]), str(self.err))
        prob = [i for i in st["items"] if i["kind"] == "problem"]
        self.assertTrue(prob and "lim" in prob[-1]["text"])
        opts = [i for i in st["items"] if i["kind"] == "options"]
        self.assertEqual(opts[-1]["data"], ["1", "e", "∞", "0"])

    def test_07_unknown_tool_and_ping_and_notify(self):
        # 真云实测行为：云端会把 play_music 等官方工具例行下发到本接入点；
        # 应中性应答“不归我管”（非故障句），且不炸链、后续工具照常可用
        text = self.cloud.call_tool("play_music", {})
        self.assertIn("不提供 play_music", text)
        self.assertIn("没有出错", text)
        self.assertNotIn("出了点问题", text)
        t2 = self.cloud.call_tool("board_write", {"content": "未知工具后链路仍健康"})
        self.assertIn("已写上黑板", t2)
        r = self.cloud.request("ping")
        self.assertEqual(r["result"], {})
        orphan0 = self.cloud.orphan
        self.cloud.notify("notifications/initialized")  # 通知不得被回话
        r = self.cloud.request("ping")  # 管道仍健康
        self.assertEqual(r["result"], {})
        self.assertEqual(self.cloud.orphan, orphan0)
        r = self.cloud.request("some/unknown_method")  # 未知方法礼貌回空
        self.assertEqual(r["result"], {})

    def test_08_clear_via_bridge(self):
        text = self.cloud.call_tool("board_clear", {})
        self.assertIn("擦干净", text)
        st = self._state(self.hA)
        self.assertEqual(st["items"], [])
        self.assertIsNone(st["source_error_id"])

    # ============================================================ HTTP 面
    def test_09_state_requires_auth(self):
        r = self.client.get("/api/board/state")
        self.assertEqual(r.status_code, 401)

    def test_10_user_isolation(self):
        self.cloud.call_tool("board_write", {"content": "只属于A的板书"})
        stB = self._state(self.hB)
        self.assertEqual([i["text"] for i in stB["items"]].count("只属于A的板书"), 0)
        stA = self._state(self.hA)
        self.assertIn("只属于A的板书", [i["text"] for i in stA["items"]])

    def test_11_rev_polling(self):
        st = self._state(self.hA, since=-1)
        r = self.client.get(f"/api/board/state?since={st['rev']}", headers=self.hA)
        self.assertFalse(r.get_json()["data"]["changed"])
        self.cloud.call_tool("board_write", {"content": "触发改动"})
        r = self.client.get(f"/api/board/state?since={st['rev']}", headers=self.hA)
        d = r.get_json()["data"]
        self.assertTrue(d["changed"])
        self.assertGreater(d["rev"], st["rev"])

    def test_12_http_clear(self):
        r = self.client.post("/api/board/clear", json={}, headers=self.hA)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["data"]["items"], [])

    def test_13_fragment_and_page_registered(self):
        r = self.client.get("/fragments/teacher_board", headers=self.hA)
        self.assertEqual(r.status_code, 200)
        self.assertIn("tb-board", r.get_json()["data"])
        r = self.client.get("/teacher_board")
        self.assertEqual(r.status_code, 200)
        self.assertIn("AI 老师黑板", r.get_data(as_text=True))

    def test_14_resolve_uid(self):
        self.assertEqual(LB.resolve_uid_by_username(self.userA), str(self.uidA))
        self.assertIsNone(LB.resolve_uid_by_username("no_such_user_" + self.suffix))

    # ---- 讲义版式新契约（2026-11-04 用户裁定：分块短句，拒文字墙） ----
    def test_15_reject_overlong_step(self):
        """超长卡拒收且不上板：这是「每块只许短句」铁律的代码化。"""
        before = len(self._state(self.hA)["items"])
        text = self.cloud.call_tool("board_write", {"content": "长" * 55, "kind": "step"})
        self.assertIn("超长", text)
        self.assertIn("拆成多张卡", text)
        self.assertEqual(len(self._state(self.hA)["items"]), before)
        # 边界：恰好 40 字收
        ok = self.cloud.call_tool("board_write", {"content": "字" * 40, "kind": "step"})
        self.assertIn("已写上黑板", ok)

    def test_16_replace_and_remove_single_card(self):
        """被打断时改写/擦掉单卡，其余卡不受影响（实时变板的核心动作）。"""
        wid = self.cloud.call_tool("board_write", {"content": "错了的一步", "kind": "step"})
        cid = int(wid.split("#")[1].split("（")[0])
        t = self.cloud.call_tool("board_replace",
                                 {"item_id": cid, "content": "改对的一步", "kind": "step"})
        self.assertIn("已改写", t)
        it = [i for i in self._state(self.hA)["items"] if i["id"] == cid][0]
        self.assertEqual(it["text"], "改对的一步")
        # 改写也限长：超长拒
        t = self.cloud.call_tool("board_replace",
                                 {"item_id": cid, "content": "长" * 60})
        self.assertIn("超长", t)
        t = self.cloud.call_tool("board_remove", {"item_id": cid})
        self.assertIn("已擦掉", t)
        ids = [i["id"] for i in self._state(self.hA)["items"]]
        self.assertNotIn(cid, ids)
        t = self.cloud.call_tool("board_remove", {"item_id": 99999})
        self.assertIn("没有卡", t)

    def test_17_highlight_is_exclusive_spotlight(self):
        """聚焦灯排他：点亮新卡时旧卡自动熄灭（正在讲哪张一眼可见）。"""
        a = int(self.cloud.call_tool("board_write", {"content": "卡A"})
                .split("#")[1].split("（")[0])
        b = int(self.cloud.call_tool("board_write", {"content": "卡B"})
                .split("#")[1].split("（")[0])
        self.cloud.call_tool("board_highlight", {"item_id": a})
        self.cloud.call_tool("board_highlight", {"item_id": b})
        items = {i["id"]: i for i in self._state(self.hA)["items"]}
        self.assertFalse(items[a]["highlighted"])
        self.assertTrue(items[b]["highlighted"])

    def test_18_formula_dollar_stripped(self):
        """大脑习惯性包 $ 定界：后端剥掉，前端 KaTeX 拿纯公式。"""
        self.cloud.call_tool("board_write",
                             {"content": "$x^2$", "kind": "formula"})
        f = [i for i in self._state(self.hA)["items"] if i["kind"] == "formula"][-1]
        self.assertEqual(f["text"], "x^2")

    def test_19_board_draw_via_bridge(self):
        """B 期 board_draw：合法图形上板成 plot 卡（data 为渲染契约）；非法拒收。"""
        t = self.cloud.call_tool("board_draw", {
            "title": "抛物线", "spec": {"plot_type": "function",
                                        "curves": [{"expr": "x^2"}]}})
        self.assertIn("已画上黑板", t)
        self.assertIn("plot·function", t)
        plots = [i for i in self._state(self.hA)["items"] if i["kind"] == "plot"]
        self.assertTrue(plots)
        d = plots[-1]["data"]
        self.assertEqual(d["plot_type"], "function")
        self.assertEqual(len(d["curves"][0]["segs"][0]), 121)
        bad = self.cloud.call_tool("board_draw", {
            "spec": {"plot_type": "function",
                     "curves": [{"expr": "foo(x)"}]}})
        self.assertIn("图没画上", bad)
        # 数轴：解集区间 + 标注点
        t2 = self.cloud.call_tool("board_draw", {"spec": {
            "plot_type": "numberline", "range": [-5, 5],
            "points": [{"v": 2, "label": "A"}],
            "intervals": [{"from": -1, "to": 3, "label": "解集"}]}})
        self.assertIn("numberline", t2)

    def test_30_show_problem_suggests_plot_for_function(self):
        """五期 C 案：函数题写板返回追加建议图型行，三层结构（确认+状态行）不破坏。"""
        text = self.cloud.call_tool("board_show_problem", {"error_id": str(self.err_fn)})
        self.assertIn("已写上黑板", text)
        self.assertIn("建议 board_draw", text)
        self.assertIn("plot_type=function", text)
        self.assertIn("#", text)                      # 状态行仍在
        text2 = self.cloud.call_tool("get_lesson_material", {"error_id": str(self.err_fn)})
        self.assertIn("plot_type=function", text2)    # 取素材路径同样给建议

    def test_31_no_suggestion_when_no_keyword_hit(self):
        """种子题（lim 重要极限）不在关键词表 → 绝不误报建议行。"""
        text = self.cloud.call_tool("board_show_problem", {"error_id": str(self.err)})
        self.assertIn("已写上黑板", text)
        self.assertNotIn("建议 board_draw", text)


class BoardSuggestPlotTest(unittest.TestCase):
    """五期 C 案纯函数：关键词表匹配、表序优先、大小写、空输入。"""

    def test_hit_function(self):
        self.assertIn("plot_type=function", LB._suggest_plot("求曲线 y=x^2 围成的面积"))

    def test_enclosed_area_beats_geometry(self):
        # 「面积」同时命中两组：曲线信号（围成）先行，不被 geometry 抢走
        self.assertIn("function", LB._suggest_plot("求与曲线围成的面积"))
        self.assertIn("geometry", LB._suggest_plot("三角形的面积公式"))

    def test_case_insensitive(self):
        self.assertIn("function", LB._suggest_plot("SIN x 与 COS x 的图象"))

    def test_stats_and_diagram(self):
        self.assertIn("stats", LB._suggest_plot("求这组数据的平均值与中位数"))
        self.assertIn("diagram", LB._suggest_plot("细胞分裂流程"))

    def test_miss_returns_empty(self):
        self.assertEqual(LB._suggest_plot("默写古诗两首", None, ""), "")


class BoardPlotDslTest(unittest.TestCase):
    """B 期图形 DSL 纯单元测试：表达式安全解析 + 三类图校验，不碰桥/库。"""

    # ---- 表达式 ----
    def test_eval_basic(self):
        self.assertEqual(BP.compile_expr("x^2")(3), 9)
        self.assertEqual(BP.compile_expr("2x")(3), 6)            # 隐式乘
        self.assertEqual(BP.compile_expr("3sin(x)")(0), 0)
        self.assertAlmostEqual(BP.compile_expr("pi")(0), 3.14159, 4)
        self.assertEqual(BP.compile_expr("(x+1)(x-1)")(3), 8)
        self.assertEqual(BP.compile_expr("-x^2")(2), -4)         # 负号优先级
        self.assertEqual(BP.compile_expr("2^3^2")(0), 512)       # 右结合
        self.assertTrue(math.isnan(BP.compile_expr("1/x")(0)))   # 除零→nan 断线

    def test_expr_rejects(self):
        for bad in ("evil(x)", "x!", "", "a" * 70, "((x)", "x +", "1 2+"):
            with self.assertRaises(BP._ExprError, msg=bad):
                BP.compile_expr(bad)

    # ---- function 图 ----
    def test_function_contract(self):
        ok, d = BP.validate_plot({"plot_type": "function",
                                  "curves": [{"expr": "x^2"}]})
        self.assertTrue(ok)
        self.assertEqual(d["x_range"], [-5, 5])
        self.assertLess(d["y_range"][0], 0.5)      # 含谷底
        self.assertGreater(d["y_range"][1], 20)     # 含两端高点
        # 渐近线断线：1/x 在 0 附近裂成多段
        ok2, d2 = BP.validate_plot({"plot_type": "function",
                                    "curves": [{"expr": "1/x"}],
                                    "x_range": [-1, 1]})
        self.assertTrue(ok2)
        self.assertGreaterEqual(len(d2["curves"][0]["segs"]), 1)

    def test_function_rejects(self):
        for spec in ({"plot_type": "function"},
                     {"plot_type": "function", "curves": [{"expr": "x"}] * 4},
                     {"plot_type": "function", "curves": [{"expr": "tan(x)"}],
                      "x_range": [0, 1000]},
                     {"plot_type": "function", "curves": [{"expr": "sqrt(x)"}],
                      "x_range": [-5, -1]}):   # 区间内全无效点
            ok, msg = BP.validate_plot(spec)
            self.assertFalse(ok, msg=msg)

    # ---- 数轴 ----
    def test_numberline(self):
        ok, d = BP.validate_plot({"plot_type": "numberline", "range": [-3, 3],
                                  "points": [{"v": 1, "label": "a" * 20}]})
        self.assertTrue(ok)
        self.assertEqual(len(d["points"][0]["label"]), 10)   # 标签限长截断（v0.2.6: 6→10，装得下真实术语）
        for spec in ({"plot_type": "numberline", "range": [0, 1]},           # 无点无区间
                     {"plot_type": "numberline", "range": [0, 5],
                      "points": [{"v": 9}]},                                  # 超范围
                     {"plot_type": "numberline", "range": [0, 5],
                      "intervals": [{"from": 3, "to": 1}]}):                  # from>to
            self.assertFalse(BP.validate_plot(spec)[0])

    # ---- 几何 ----
    def test_geometry(self):
        ok, d = BP.validate_plot({"plot_type": "geometry",
                                  "points": [{"x": 0, "y": 0, "label": "O"},
                                             {"x": 3, "y": 4, "label": "A"}],
                                  "segments": [{"a": "O", "b": "A"}],
                                  "circles": [{"center": "O", "r": 2}]})
        self.assertTrue(ok)
        self.assertLessEqual(d["view"]["xmin"], -2)   # 圆并入视野
        self.assertGreaterEqual(d["view"]["ymax"], 4)
        for spec in ({"plot_type": "geometry", "points": []},
                     {"plot_type": "geometry",
                      "points": [{"x": 1, "y": 1, "label": "A"},
                                 {"x": 2, "y": 2, "label": "A"}]},     # 重复点名
                     {"plot_type": "geometry",
                      "points": [{"x": 0, "y": 0, "label": "A"}],
                      "segments": [{"a": "A", "b": "Z"}]},             # 未定义引用
                     {"plot_type": "geometry",
                      "points": [{"x": 0, "y": 0}], "circles": [{"cx": 0, "cy": 0, "r": 0}]}):
            self.assertFalse(BP.validate_plot(spec)[0])

    def test_geometry_unknown_key_rejected(self):
        # 中位线定理事故：老师把线段写成 elements 键，过去被静默丢弃→只剩孤点还报成功
        ok, msg = BP.validate_plot({"plot_type": "geometry",
                                    "points": [{"x": 0, "y": 0, "label": "A"},
                                               {"x": 3, "y": 0, "label": "B"},
                                               {"x": 1, "y": 2, "label": "C"}],
                                    "elements": [{"a": "A", "b": "B"}]})
        self.assertFalse(ok)
        self.assertIn("elements", msg)
        self.assertIn("segments", msg)          # 拒收必带正确写法指导
        # 多 bad 键合并披露；派生键 view/marks/step_total 同拒（评审 Major）；
        # bad 键闸先于点数闸（2 点也拦）
        ok2, m2 = BP.validate_plot({"plot_type": "geometry",
                                    "points": [{"x": 0, "y": 0, "label": "A"}],
                                    "colors": [], "view": {"xmin": 0}})
        self.assertFalse(ok2)
        self.assertIn("colors", m2)
        self.assertIn("view", m2)
        ok3, m3 = BP.validate_plot({"plot_type": "geometry",
                                    "points": [{"x": 0, "y": 0, "label": "A"},
                                               {"x": 1, "y": 1, "label": "B"}],
                                    "marks": [{"name": "M"}]})
        self.assertFalse(ok3)
        self.assertIn("marks", m3)

    def test_geometry_points_only_rejected(self):
        ok, msg = BP.validate_plot({"plot_type": "geometry",
                                    "points": [{"x": 0, "y": 0, "label": "A"},
                                               {"x": 3, "y": 0, "label": "B"},
                                               {"x": 1, "y": 2, "label": "C"}]})
        self.assertFalse(ok)
        self.assertIn("segments", msg)
        # 两点的极简场景不设限；三点+圆/多边形（自带线）合法
        self.assertTrue(BP.validate_plot({"plot_type": "geometry",
                    "points": [{"x": 0, "y": 0, "label": "A"},
                               {"x": 3, "y": 0, "label": "B"}]})[0])
        self.assertTrue(BP.validate_plot({"plot_type": "geometry",
                    "points": [{"x": 0, "y": 0, "label": "A"},
                               {"x": 3, "y": 0, "label": "B"},
                               {"x": 1, "y": 2, "label": "C"}],
                    "polygons": [{"pts": ["A", "B", "C"]}]})[0])
        # 3 点 + 只有圆 / 只有尺寸标注（自带可见线）合法（评审 Minor-3）
        self.assertTrue(BP.validate_plot({"plot_type": "geometry",
                    "points": [{"x": 0, "y": 0, "label": "A"},
                               {"x": 3, "y": 0, "label": "B"},
                               {"x": 1, "y": 2, "label": "C"}],
                    "circles": [{"cx": 1.5, "cy": 0, "r": 1.5}]})[0])
        self.assertTrue(BP.validate_plot({"plot_type": "geometry",
                    "points": [{"x": 0, "y": 0, "label": "A"},
                               {"x": 3, "y": 0, "label": "B"},
                               {"x": 1, "y": 2, "label": "C"}],
                    "dims": [{"a": "A", "b": "B", "label": "3"}]})[0])

    # ---- 中点派生 + 线段身份镜子（中位线画成中线事故）----
    _MID_TRI = {"plot_type": "geometry",
                "points": [{"x": 0, "y": 0, "label": "A"},
                           {"x": 4, "y": 0, "label": "B"},
                           {"x": 1, "y": 3, "label": "C"},
                           {"mid": ["B", "C"], "label": "D"},
                           {"mid": ["A", "C"], "label": "E"}],
                "segments": [{"a": "A", "b": "D"},
                             {"a": "B", "b": "E"},
                             {"a": "D", "b": "E"},
                             {"a": "A", "b": "B"}]}

    def test_geometry_midpoint_derivation(self):
        ok, d = BP.validate_plot(dict(self._MID_TRI))
        self.assertTrue(ok)
        pts = {p["label"]: p for p in d["points"]}
        self.assertEqual((pts["D"]["x"], pts["D"]["y"]), (2.5, 1.5))
        self.assertEqual((pts["E"]["x"], pts["E"]["y"]), (0.5, 1.5))
        self.assertEqual(pts["D"]["mid_of"], ["B", "C"])
        self.assertNotIn("mid_of", pts["A"])
        # 拒绝：引用未定义点 / mid 格式错 / 两参考点同点
        for bad in ({"plot_type": "geometry",
                     "points": [{"mid": ["A", "Z"], "label": "D"}]},
                    {"plot_type": "geometry",
                     "points": [{"mid": "B", "label": "D"}]},
                    {"plot_type": "geometry",
                     "points": [{"x": 0, "y": 0, "label": "A"},
                                {"mid": ["A", "A"], "label": "D"}]}):
            self.assertFalse(BP.validate_plot(bad)[0], bad)

    def test_geometry_segment_role_mirror(self):
        # 镜子：AD/BE 一头已给点→中线；DE 两中点→中位线+数值复核；全已给点不产噪声
        ok, d = BP.validate_plot(dict(self._MID_TRI))
        live = BP.describe(d)
        self.assertIn("线段身份", live)
        self.assertIn("已给点—中点（中线）", live)
        self.assertIn("中点—中点（中位线）", live)
        self.assertIn("DE∥AB 且 DE=½AB", live)
        self.assertIn("以此实况身份为准核对连线", live)
        plain = BP.validate_plot({"plot_type": "geometry",
                                  "points": [{"x": 0, "y": 0, "label": "A"},
                                             {"x": 3, "y": 0, "label": "B"}],
                                  "segments": [{"a": "A", "b": "B"}]})
        self.assertNotIn("线段身份", BP.describe(plain[1]))

    def test_geometry_mirror_tolerance(self):
        # 评审 Major 回归：非整数大坐标下中点 round 3 位的舍入误差
        # 不得让数值复核误报「图有误」（数学上恒成立的构造）
        spec = {"plot_type": "geometry",
                "points": [{"x": 0.123, "y": 0.456, "label": "A"},
                           {"x": 98.765, "y": 72.321, "label": "B"},
                           {"x": -65.432, "y": 40.789, "label": "C"},
                           {"mid": ["B", "C"], "label": "D"},
                           {"mid": ["A", "C"], "label": "E"}],
                "segments": [{"a": "D", "b": "E"}, {"a": "A", "b": "B"}]}
        ok, d = BP.validate_plot(spec)
        self.assertTrue(ok)
        live = BP.describe(d)
        self.assertNotIn("图有误", live)
        self.assertIn("中位线", live)

    # ---- 声明式关系核验（通用镜子：任何数学关系同一套数值核验）----
    _RECT = {"plot_type": "geometry",
             "points": [{"x": 0, "y": 0, "label": "A"},
                        {"x": 4, "y": 0, "label": "B"},
                        {"x": 4, "y": 3, "label": "C"},
                        {"x": 0, "y": 3, "label": "D"},
                        {"mid": ["B", "C"], "label": "M"},
                        {"mid": ["A", "D"], "label": "N"}],
             "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"},
                          {"a": "C", "b": "D"}, {"a": "D", "b": "A"},
                          {"a": "N", "b": "M"}],
             "relations": [
                 {"kind": "parallel", "a": ["N", "M"], "b": ["A", "B"]},
                 {"kind": "perpendicular", "a": ["A", "D"], "b": ["A", "B"]},
                 {"kind": "equal", "a": ["A", "D"], "b": ["B", "C"]},
                 {"kind": "collinear", "points": ["A", "N", "D"]},
                 {"kind": "midpoint", "m": "M", "of": ["B", "C"]}]}

    def test_relations_pass_and_report(self):
        # 五种关系全对：通过，黑板实况报「关系核验通过」清单
        ok, d = BP.validate_plot(dict(self._RECT))
        self.assertTrue(ok, msg=d)
        live = BP.describe(d)
        self.assertIn("关系核验通过", live)
        self.assertIn("NM∥AB", live)
        self.assertIn("AD⊥AB", live)
        self.assertIn("AND 共线", live)
        self.assertIn("M=BC 中点", live)

    def test_relations_reject_with_numbers(self):
        # 不符拒收+量化退货单：概念错在坐标上必留痕，五类关系逐个照妖
        def with_rel(rel):
            s = dict(pts_off)
            s["relations"] = [rel]
            return s
        pts_off = {"plot_type": "geometry",
                   "points": [{"x": 0, "y": 0, "label": "A"},
                              {"x": 4, "y": 0, "label": "B"},
                              {"x": 3, "y": 3, "label": "C"},
                              {"x": 1, "y": 2.6, "label": "D"}],
                   "segments": [{"a": "A", "b": "B"}, {"a": "C", "b": "D"}]}
        ok, msg = BP.validate_plot(with_rel({
            "kind": "parallel", "a": ["A", "B"], "b": ["C", "D"]}))
        self.assertFalse(ok)
        self.assertIn("不平行", msg)
        ok, msg = BP.validate_plot(with_rel({
            "kind": "perpendicular", "a": ["A", "B"], "b": ["C", "D"]}))
        self.assertFalse(ok)
        self.assertIn("不垂直", msg)
        ok, msg = BP.validate_plot(with_rel({
            "kind": "equal", "a": ["A", "B"], "b": ["C", "D"]}))
        self.assertFalse(ok)
        self.assertIn("等长", msg)
        ok, msg = BP.validate_plot(with_rel({
            "kind": "collinear", "points": ["A", "B", "D"]}))
        self.assertFalse(ok)
        self.assertIn("不共线", msg)

    def test_relations_collinear_horizontal_baseline(self):
        # 评审 Critical 回归：曾把叉积第二项写成减基线终点 x（by[0]），
        # 竖直基线 vx=0 恰好掩盖，水平基线真共线被误拒——这里正/反都验数值
        horiz = {"plot_type": "geometry",
                 "points": [{"x": 0, "y": 0, "label": "B"},
                            {"x": 4, "y": 0, "label": "C"},
                            {"x": 2, "y": 0, "label": "D"},
                            {"x": 2, "y": 3, "label": "A"}],
                 "segments": [{"a": "A", "b": "D"}, {"a": "B", "b": "C"}]}
        s = dict(horiz)
        s["relations"] = [{"kind": "collinear", "points": ["B", "D", "C"]}]
        ok, d = BP.validate_plot(s)
        self.assertTrue(ok, msg=d)
        self.assertIn("BDC 共线", BP.describe(d))
        # 反例：D 略偏离基线，退货单偏差数值应为真实垂直距离≈0.5
        s2 = dict(horiz)
        s2["points"] = [{"x": 0, "y": 0, "label": "B"},
                        {"x": 4, "y": 0, "label": "C"},
                        {"x": 2, "y": 0.5, "label": "D"},
                        {"x": 2, "y": 3, "label": "A"}]
        s2["relations"] = [{"kind": "collinear", "points": ["B", "D", "C"]}]
        ok, msg = BP.validate_plot(s2)
        self.assertFalse(ok)
        self.assertIn("0.500", msg)

    def test_relations_midpoint_raw_coords(self):
        # 裸坐标也能上闸（堵住「老师不用 mid 镜子照不出」的洞）：
        # 声明的中点坐标写错→拒收并给真中点与 mid 写法；写对→通过
        base = {"plot_type": "geometry",
                "points": [{"x": 0, "y": 0, "label": "B"},
                           {"x": 5, "y": 0, "label": "C"},
                           {"x": 2, "y": 4, "label": "A"}],
                "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"},
                             {"a": "C", "b": "A"}],
                "relations": [{"kind": "midpoint", "m": "M", "of": ["B", "C"]}]}
        wrong = dict(base)
        wrong["points"] = list(base["points"]) + [{"x": 2.1, "y": 0.4, "label": "M"}]
        ok, msg = BP.validate_plot(wrong)
        self.assertFalse(ok)
        self.assertIn("真中点", msg)
        self.assertIn('mid:["B","C"]', msg)
        right = dict(base)
        right["points"] = list(base["points"]) + [{"x": 2.5, "y": 0, "label": "M"}]
        ok, d = BP.validate_plot(right)
        self.assertTrue(ok, msg=d)

    def test_relations_bad_form(self):
        # 形式错也拒：未知 kind、引用未定义点、非列表
        def one(rel):
            s = dict(self._RECT)
            s["relations"] = [rel]
            return BP.validate_plot(s)
        self.assertFalse(one({"kind": "similar"})[0])
        self.assertFalse(one({"kind": "parallel", "a": ["Z", "B"],
                              "b": ["A", "C"]})[0])
        self.assertFalse(one({"kind": "parallel", "a": ["A"],
                              "b": ["B", "C"]})[0])
        s = dict(self._RECT)
        s["relations"] = {"kind": "parallel"}
        self.assertFalse(BP.validate_plot(s)[0])
        s2 = dict(self._RECT)
        s2["relations"] = [{"kind": "equal", "a": ["A", "B"],
                            "b": ["B", "C"]}] * 9
        self.assertFalse(BP.validate_plot(s2)[0])

    def test_unknown_type_and_shape(self):
        self.assertFalse(BP.validate_plot(None)[0])
        self.assertFalse(BP.validate_plot("function")[0])
        ok, msg = BP.validate_plot({"plot_type": "pie"})
        self.assertFalse(ok)
        self.assertIn("plot_type", msg)


class BoardPlotDslV4Test(unittest.TestCase):
    """四期 DSL 扩容纯单元测试：阴影/切线/极坐标/单位圆/时间轴/
    直方图/箱线/回归线/树/桑基/漏斗，以及「超限拒收 + 中文指导」纪律。"""

    def _bad(self, spec, hint=""):
        ok, msg = BP.validate_plot(spec)
        self.assertFalse(ok, msg=msg)
        if hint:
            self.assertIn(hint, msg)

    # ---- 阴影区域 + 切线 ----
    def test_function_shades_tangents(self):
        ok, d = BP.validate_plot({
            "plot_type": "function", "x_range": [0, 2],
            "curves": [{"expr": "x"}, {"expr": "x^2"}],
            "shades": [{"x_from": 0, "x_to": 1, "top": "curve:0",
                        "bottom": "curve:1", "label": "夹区"},
                       {"x_from": 0, "x_to": 1}],      # 缺省：top=curve:0 bottom=axis
            "tangents": [{"curve": 1, "x": 1, "label": "切点"}]})
        self.assertTrue(ok)
        sh = d["shades"][0]
        self.assertEqual(len(sh["upper"]), BP._SHADE_SAMPLES)
        self.assertEqual(sh["upper"][0], [0.0, 0.0])
        self.assertEqual(sh["lower"][-1], [1.0, 1.0])
        self.assertEqual(d["shades"][1]["upper"][-1], [1.0, 1.0])
        self.assertEqual(d["shades"][1]["lower"][-1], [1.0, 0.0])
        tg = d["tangents"][0]
        self.assertAlmostEqual(tg["k"], 2.0, 3)          # (x^2)' 在 x=1 为 2
        self.assertEqual(tg["seg"][0][0], round(1 - 0.36, 4))
        # 切点自动成为可指认标记；步号接着阴影往后排
        self.assertEqual(d["marks"][-1]["name"], "切点")
        self.assertEqual(d["marks"][-1]["step"], 3)
        self.assertEqual(d["step_total"], 3)
        self._bad({"plot_type": "function", "curves": [{"expr": "x"}],
                   "x_range": [0, 2], "shades": [{"x_from": 1, "x_to": 1}]})
        self._bad({"plot_type": "function", "curves": [{"expr": "x"}],
                   "shades": [{"x_from": -1, "x_to": 9}]}, "x_range")
        self._bad({"plot_type": "function", "curves": [{"expr": "x"}],
                   "shades": [{"x_from": 0, "x_to": 1, "top": "y=0"}]}, "axis")
        self._bad({"plot_type": "function", "curves": [{"expr": "x"}],
                   "shades": [{"x_from": 0, "x_to": 1, "top": "curve:3"}]}, "区域边界")
        self._bad({"plot_type": "function", "curves": [{"expr": "1/x"}],
                   "x_range": [-1, 1],
                   "shades": [{"x_from": -1, "x_to": 1}]}, "没有值")
        self._bad({"plot_type": "function", "curves": [{"expr": "x"}],
                   "tangents": [{"curve": 0, "x": 9}]}, "x_range")
        self._bad({"plot_type": "function", "curves": [{"expr": "x"}] * 3,
                   "shades": [{"x_from": 0, "x_to": 1}] * 5})

    def test_tangent_vertical_handled(self):
        # 1/x 在 x=0.0005 处斜率 -4e6（近竖直）→ 改纵向延伸，不报错
        ok, d = BP.validate_plot({"plot_type": "function",
                                  "curves": [{"expr": "1/x"}],
                                  "x_range": [-1, 1],
                                  "tangents": [{"curve": 0, "x": 0.0005}]})
        self.assertTrue(ok)
        self.assertEqual(d["tangents"][0]["seg"][0][0], d["tangents"][0]["seg"][1][0])
        self.assertLess(d["tangents"][0]["seg"][0][1], d["tangents"][0]["y"])

    # ---- 极坐标 ----
    def test_polar(self):
        ok, d = BP.validate_plot({"plot_type": "polar",
                                  "curves": [{"expr": "1+cos(x)", "name": "心形"}],
                                  "theta_range": [0, 360]})
        self.assertTrue(ok)
        self.assertEqual(d["curves"][0]["segs"][0][0], [2.0, 0.0])   # x=角度度数
        self.assertEqual(len(d["curves"][0]["segs"][0]), BP._POLAR_SAMPLES)
        self.assertIsNone(d["marks"][0]["x"])                      # 自动布局无坐标
        self.assertEqual(d["marks"][0]["item"], "心形")
        self._bad({"plot_type": "polar"}, "曲线")
        self._bad({"plot_type": "polar", "theta_range": [360, 0],
                   "curves": [{"expr": "x"}]})
        self._bad({"plot_type": "polar", "curves": [{"expr": "1"}] * 4})

    # ---- 单位圆 ----
    def test_unitcircle(self):
        ok, d = BP.validate_plot({"plot_type": "unitcircle",
                                  "angles": [30, {"deg": 120, "label": "二象"}],
                                  "show": ["sin", "cos", "tan"]})
        self.assertTrue(ok)
        self.assertAlmostEqual(d["rays"][0]["sin"], 0.5, 4)
        self.assertEqual(d["rays"][1]["label"], "二象")
        self.assertEqual({ln["kind"] for ln in d["rays"][0]["lines"]},
                         {"sin", "cos", "tan"})
        cos_ln = [ln for ln in d["rays"][0]["lines"] if ln["kind"] == "cos"][0]
        self.assertEqual(cos_ln["from"], [0.0, 0.0])               # 余弦线在 x 轴上
        self.assertAlmostEqual(cos_ln["to"][0], math.cos(math.radians(30)), 4)
        self.assertEqual(len(d["marks"]), 2)
        self._bad({"plot_type": "unitcircle"}, "angles")
        self._bad({"plot_type": "unitcircle", "angles": [90], "show": ["tan"]}, "竖直")
        self._bad({"plot_type": "unitcircle", "angles": [30],
                   "show": ["sec"]}, "sin/cos/tan")
        self._bad({"plot_type": "unitcircle", "angles": [1, 2, 3, 4, 5]})

    # ---- 时间轴 ----
    def test_timeline(self):
        ok, d = BP.validate_plot({"plot_type": "timeline", "events": [
            {"t": 1912, "label": "民国"}, {"t": 1949, "label": "建国"},
            {"t": 1978, "label": "改革", "note": "转折点"}]})
        self.assertTrue(ok)
        self.assertEqual([e["side"] for e in d["events"]], [1, -1, 1])
        self.assertLess(d["range"][0], 1912)
        self.assertGreater(d["range"][1], 1978)
        self.assertEqual(d["step_total"], 3)
        self._bad({"plot_type": "timeline", "events": [{"t": 1}]})
        self._bad({"plot_type": "timeline", "range": [2000, 2010],
                   "events": [{"t": 1912, "label": "a"}, {"t": 2020, "label": "b"}]},
                  "超出 range")
        self._bad({"plot_type": "timeline",
                   "events": [{"t": i} for i in range(9)]})

    # ---- 直方图 / 箱线图 ----
    def test_stats_histogram_box(self):
        ok, d = BP.validate_plot({"plot_type": "stats", "shape": "histogram",
                                  "values": [12, 15, 12, 19, 21, 8, 30], "bins": 4})
        self.assertTrue(ok)
        self.assertEqual(len(d["categories"]), 4)
        self.assertEqual(len(d["bin_edges"]), 5)
        self.assertEqual(sum(d["series"][0]["values"]), 7.0)
        self.assertEqual(d["y_range"][0], 0)
        self._bad({"plot_type": "stats", "shape": "histogram", "values": [3]}, "values")
        self._bad({"plot_type": "stats", "shape": "histogram",
                   "values": [5, 5, 5]}, "全相等")
        self._bad({"plot_type": "stats", "shape": "histogram",
                   "values": [1, 2, 3], "bins": 11})
        ok2, d2 = BP.validate_plot({"plot_type": "stats", "shape": "box",
                                    "series": [{"name": "甲班",
                                                "values": [1, 2, 3, 4]},
                                               {"name": "乙班", "values": [2, 4]}]})
        self.assertTrue(ok2)
        b0 = d2["boxes"][0]
        self.assertEqual((b0["min"], b0["q1"], b0["med"], b0["q3"], b0["max"], b0["n"]),
                         (1, 1.75, 2.5, 3.25, 4, 4))
        self.assertEqual(d2["categories"], ["甲班", "乙班"])
        self._bad({"plot_type": "stats", "shape": "box",
                   "series": [{"name": "a", "values": [1]}]}, "2~")
        self._bad({"plot_type": "stats", "shape": "box",
                   "series": [{"values": [1, 2]}] * 4})

    # ---- 散点回归线（v0.2.7 起散点每系列至少一个点带标注，本组用例全部带真 label
    # 抵达 trend 拒收路径——新闸在前，不给真名就先撞标注闸，测不到本意）----
    def test_scatter_trend(self):
        ok, d = BP.validate_plot({"plot_type": "stats", "shape": "scatter",
                                  "series": [{"name": "s",
                                               "points": [{"x": 0, "y": 0, "label": "样本点"},
                                                          [1, 2], [2, 4]]}],
                                  "trend": "lin"})
        self.assertTrue(ok)
        self.assertAlmostEqual(d["trend"]["a"], 2.0, 5)
        self.assertAlmostEqual(d["trend"]["b"], 0.0, 5)
        self.assertEqual(len(d["trend"]["seg"]), 2)
        ok2, d2 = BP.validate_plot({"plot_type": "stats", "shape": "scatter",
                                    "series": [{"points": [{"x": -1, "y": 1, "label": "样本点"},
                                                            [0, 0], [1, 1], [2, 4]]}],
                                    "trend": "quad"})
        self.assertTrue(ok2)
        self.assertAlmostEqual(d2["trend"]["a"], 1.0, 5)
        self.assertAlmostEqual(d2["trend"]["b"], 0.0, 5)
        self.assertAlmostEqual(d2["trend"]["c"], 0.0, 5)
        self.assertIn("x²", d2["trend"]["equation"])
        self._bad({"plot_type": "stats", "shape": "scatter",
                   "series": [{"points": [{"x": 0, "y": 0, "label": "样本点"},
                                              [1, 1]]}], "trend": "cubic"},
                  "lin")
        self._bad({"plot_type": "stats", "shape": "scatter",
                   "series": [{"points": [{"x": 1, "y": 1, "label": "样本点"}]}],
                   "trend": "lin"}, "至少")
        self._bad({"plot_type": "stats", "shape": "scatter",
                   "series": [{"points": [{"x": 0, "y": 1, "label": "甲"},
                                              {"x": 0, "y": 3, "label": "乙"}]}],
                   "trend": "lin"})

    # ---- 树 / 桑基 / 漏斗 ----
    def test_diagram_tree(self):
        ok, d = BP.validate_plot({"plot_type": "diagram", "shape": "tree", "nodes": [
            {"id": "a", "text": "函数"},
            {"id": "b", "text": "定义域", "parent": "a"},
            {"id": "c", "text": "值域", "parent": "a"},
            {"id": "d", "text": "区间", "parent": "b"}]})
        self.assertTrue(ok)
        self.assertEqual(d["root"]["name"], "函数")
        self.assertEqual([c["name"] for c in d["root"]["children"]], ["定义域", "值域"])
        self.assertEqual(d["root"]["children"][0]["children"][0]["depth"], 2)
        self.assertEqual(d["count"], 4)
        self.assertIsNone(d["marks"][0]["x"])
        self._bad({"plot_type": "diagram", "shape": "tree",
                   "nodes": [{"id": "a", "text": "甲"}, {"id": "b", "text": "乙"}]},
                  "一个根")
        self._bad({"plot_type": "diagram", "shape": "tree",
                   "nodes": [{"id": "a", "text": "甲"},
                             {"id": "b", "text": "乙", "parent": "z"}]}, "不是已定义")
        self._bad({"plot_type": "diagram", "shape": "tree",
                   "nodes": [{"id": "a", "text": "甲"},
                             {"id": "b", "text": "乙", "parent": "b"}]})
        self._bad({"plot_type": "diagram", "shape": "tree",
                   "nodes": [{"id": "r", "text": "根"},
                             {"id": "n1", "text": "层1", "parent": "r"}] +
                            [{"id": "n%d" % i, "text": "层%d" % i, "parent": "n%d" % (i - 1)}
                             for i in range(2, 6)]}, "层级")
        self._bad({"plot_type": "diagram", "shape": "tree",
                   "nodes": [{"id": "a", "text": "甲", "parent": "b"},
                             {"id": "b", "text": "乙", "parent": "a"}]}, "环")
        self._bad({"plot_type": "diagram", "shape": "tree",
                   "nodes": [{"id": "r", "text": "根"}] +
                            [{"id": "c%d" % i, "text": "叶%d" % i, "parent": "r"}
                             for i in range(14)]}, "节点最多")

    def test_diagram_sankey_funnel(self):
        ok, d = BP.validate_plot({"plot_type": "diagram", "shape": "sankey", "links": [
            {"from": "入口", "to": "合格", "value": 70},
            {"from": "入口", "to": "返工", "value": 30}]})
        self.assertTrue(ok)
        self.assertEqual([n["name"] for n in d["nodes"]], ["入口", "合格", "返工"])
        self.assertEqual(d["step_total"], 2)
        self._bad({"plot_type": "diagram", "shape": "sankey",
                   "links": [{"from": "a", "to": "b", "value": 1}]}, "两条流")
        self._bad({"plot_type": "diagram", "shape": "sankey",
                   "links": [{"from": "a", "to": "a", "value": 1},
                             {"from": "a", "to": "b", "value": 1}]}, "自环")
        self._bad({"plot_type": "diagram", "shape": "sankey",
                   "links": [{"from": "a", "to": "b", "value": 0},
                             {"from": "b", "to": "c", "value": 1}]}, "正数")
        self._bad({"plot_type": "diagram", "shape": "sankey",
                   "links": [{"from": "a", "to": "b%d" % i, "value": 1}
                             for i in range(10)]})
        ok2, d2 = BP.validate_plot({"plot_type": "diagram", "shape": "funnel", "slices": [
            {"label": "曝光", "value": 100}, {"label": "点进", "value": 40},
            {"label": "成交", "value": 8}]})
        self.assertTrue(ok2)
        self.assertEqual([s["label"] for s in d2["slices"]], ["曝光", "点进", "成交"])
        self.assertEqual(d2["marks"][0]["item"], "曝光")
        self._bad({"plot_type": "diagram", "shape": "funnel",
                   "slices": [{"label": "只有一层", "value": 1}]})
        # v0.2.6：语义名字槽空名 / 占位名双拒（漏斗先验名字，再验数值）
        self._bad({"plot_type": "diagram", "shape": "funnel",
                   "slices": [{"value": 100}, {"value": 40}]}, "不能空")
        self._bad({"plot_type": "diagram", "shape": "funnel",
                   "slices": [{"label": "节点1", "value": 100},
                              {"label": "成交", "value": 40}]}, "占位名")
        self._bad({"plot_type": "diagram", "shape": "funnel",
                   "slices": [{"label": "曝光%d" % (i + 1), "value": i - 3}
                              for i in range(2)]}, "正数")
        self._bad({"plot_type": "diagram", "shape": "funnel",
                   "slices": [{"label": "入口%d" % (i + 1), "value": 9 - i}
                              for i in range(7)]}, "最多")

    # ---- 新图型走 board_draw 也要能上板 ----
    def test_unknown_plot_type_guidance_lists_all(self):
        ok, msg = BP.validate_plot({"plot_type": "wiggle"})
        self.assertFalse(ok)
        for name in ("function", "numberline", "geometry", "polar", "unitcircle",
                     "timeline", "stats", "diagram"):
            self.assertIn(name, msg)


class NamedSlotDisciplineTest(unittest.TestCase):
    """v0.2.6 图上标注纪律：语义名字槽（树/流程节点、扇区、事件、分段、类别）
    空名与「节点一 / 步二 / 第3层」这类占位名一起拒收，指导语里给真实术语。"""

    def _bad(self, spec, hint):
        ok, msg = BP.validate_plot(spec)
        self.assertFalse(ok, msg=msg)
        self.assertIn(hint, msg)

    def _tree(self, texts):
        return {"plot_type": "diagram", "shape": "tree", "nodes": [
            {"id": "r", "text": texts[0]},
            {"id": "c", "text": texts[1] if len(texts) > 1 else "叶子", "parent": "r"}]}

    def test_tree_empty_and_placeholder(self):
        self._bad(self._tree(["回归", ""]), "不能空")
        self._bad(self._tree(["回归", "节点一"]), "占位名")
        self._bad(self._tree(["回归", "步二"]), "占位名")
        self._bad(self._tree(["回归", "步骤 2"]), "占位名")
        self._bad(self._tree(["回归", "第3层"]), "占位名")

    def test_flow_nodes(self):
        f = lambda ts: {"plot_type": "diagram", "shape": "flow",
                        "nodes": [{"id": str(i), "text": t}
                                  for i, t in enumerate(ts)], "edges": []}
        self._bad(f(["审题", ""]), "不能空")
        self._bad(f(["审题", "步一"]), "占位名")
        self._bad(f(["审题", "环节2"]), "占位名")
        # 真术语照常上板，10 字内的长术语不被 6 字时代误伤
        ok, d = BP.validate_plot(f(["整理条件", "结构化学习方法"]))
        self.assertTrue(ok, msg=d)
        self.assertEqual(d["nodes"][1]["text"], "结构化学习方法")

    def test_pie_and_timeline(self):
        self._bad({"plot_type": "stats", "shape": "pie",
                   "slices": [{"label": "优秀", "value": 3},
                              {"value": 7}]}, "不能空")
        self._bad({"plot_type": "stats", "shape": "pie",
                   "slices": [{"label": "类1", "value": 3},
                              {"label": "及格", "value": 7}]}, "占位名")
        self._bad({"plot_type": "timeline", "events": [
            {"t": 1912, "label": "民国"}, {"t": 1949}]}, "不能空")
        # 纯数字也算占位面：「第2段」这类写法看不出在讲什么
        self._bad({"plot_type": "timeline", "events": [
            {"t": 1912, "label": "民国"},
            {"t": 1949, "label": "第2段"}]}, "占位名")

    def test_barmodel_and_stats_cats(self):
        self._bad({"plot_type": "diagram", "shape": "barmodel",
                   "parts": [{"label": "已行路程", "value": 3},
                             {"value": 5}], "total": 8}, "不能空")
        self._bad({"plot_type": "diagram", "shape": "barmodel",
                   "parts": [{"label": "第1段", "value": 3},
                             {"label": "剩余", "value": 5}], "total": 8}, "占位名")
        self._bad({"plot_type": "stats", "shape": "bar",
                   "categories": ["一班", ""],
                   "series": [{"name": "x", "values": [1, 2]}]}, "不能空")
        self._bad({"plot_type": "stats", "shape": "bar",
                   "categories": ["一班", "类2"],
                   "series": [{"name": "x", "values": [1, 2]}]}, "占位名")


class ScatterDisciplineTest(unittest.TestCase):
    """v0.2.7 散点标注纪律（监督/无监督事故根因修复）：
    多系列系列名必填真术语（空名/占位名双拒）；每系列至少一个点带 label；
    点标注不许用占位词面；多系列 marks 前几位是系列级（series=N + 重心坐标）。"""

    def _bad(self, spec, hint):
        ok, msg = BP.validate_plot(spec)
        self.assertFalse(ok, msg=msg)
        self.assertIn(hint, msg)

    def _two_series(self, lab_a="分类A", lab_b="散沙无标签", name_a="监督学习",
                    name_b="无监督学习"):
        return {"plot_type": "stats", "shape": "scatter", "series": [
            {"name": name_a, "points": [{"x": 1, "y": 2, "label": lab_a},
                                         [2, 3], [3, 5]]},
            {"name": name_b, "points": [{"x": 5, "y": 1, "label": lab_b},
                                         [6, 2], [7, 1]]}]}

    def test_multi_series_name_rules(self):
        self._bad(self._two_series(name_b=""), "不能空")
        self._bad(self._two_series(name_b="系列2"), "占位名")

    def test_every_series_needs_point_label(self):
        # 乙系列全裸点零标注——正是事故现场：讲稿说「点带着答案」图上什么也没有
        self._bad(self._two_series(lab_b=""), "没有一个点带标注")
        # 单系列同样要求至少一个点带标注
        self._bad({"plot_type": "stats", "shape": "scatter",
                   "series": [{"name": "样本", "points": [[1, 2], [2, 3]]}]},
                  "没有一个点带标注")

    def test_point_label_placeholder_rejected(self):
        self._bad(self._two_series(lab_a="第1类"), "占位名")
        # 「分类A」不匹配数字词面，天然合法
        ok, d = BP.validate_plot(self._two_series())
        self.assertTrue(ok, msg=d)

    def test_series_marks_head_marks(self):
        ok, d = BP.validate_plot(self._two_series())
        self.assertTrue(ok, msg=d)
        m = d["marks"]
        # 前两位系列级：name=系列名、series=1/2（曾有 si 泄漏 bug 全写 2，此处锁死）
        self.assertEqual(m[0]["name"], "监督学习")
        self.assertEqual(m[0]["series"], 1)
        self.assertEqual(m[1]["name"], "无监督学习")
        self.assertEqual(m[1]["series"], 2)
        # 系列级 mark 落重心：在各自点坐标范围内
        self.assertLessEqual(1, m[0]["x"]); self.assertLessEqual(m[0]["x"], 3)
        self.assertLessEqual(2, m[0]["y"]); self.assertLessEqual(m[0]["y"], 5)
        self.assertLessEqual(5, m[1]["x"]); self.assertLessEqual(m[1]["x"], 7)
        # 点级 marks 在后（不带 series 字段）
        self.assertNotIn("series", m[2])
        self.assertEqual(m[2]["name"], "分类A")
        # 单系列不生成系列级 mark（图题兜底，point 全指点级）
        ok2, d2 = BP.validate_plot({"plot_type": "stats", "shape": "scatter",
                                    "series": [{"points": [
                                        {"x": 1, "y": 1, "label": "样本点"}, [2, 2]]}]})
        self.assertTrue(ok2, msg=d2)
        self.assertNotIn("series", d2["marks"][0])

    def test_single_series_name_rules(self):
        # 单系列空名放行（图题兜底），但非空占位名拒收
        ok, d = BP.validate_plot({"plot_type": "stats", "shape": "scatter",
                                  "series": [{"points": [
                                      {"x": 1, "y": 1, "label": "样本点"}]}]})
        self.assertTrue(ok, msg=d)
        self._bad({"plot_type": "stats", "shape": "scatter",
                   "series": [{"name": "系列1", "points": [
                       {"x": 1, "y": 1, "label": "样本点"}]}]}, "占位名")


class InterruptScenarioTest(unittest.TestCase):
    """实时打断/并发/断线恢复三场景（2026-11-04 用户要求实测）：
    用假云按真实云端会话节奏串发工具调用，断言黑板状态机全路径正确。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.uidC, cls.tokC = cls._register("xzC_" + cls.suffix)
        cls.hC = {"Authorization": "Bearer " + cls.tokC}
        db = DatabaseManager(str(config.DB_PATH))
        cls.conn = db.get_connection()
        cls.kp = cls._insert(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
            "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (cls.uidC, "测试学科XZI" + cls.suffix, "导数", "导数定义", 30))
        # 两道错题：模拟“换题打断”时云端按清单选题
        cls.err1 = cls._err_row("函数 f(x)=x² 在 x=1 处导数？ A.1 B.2 C.0 D.不存在", "A")
        cls.err2 = cls._err_row(" lim(x→0) sin x / x = ? A.0 B.1 C.∞ D.不存在", "D")
        # 桥指向新假云（独立端口，与第一类互不干扰）
        cls.cloud = FakeCloud()
        cls.cloud.start()
        cls._orig_ep = config.XZ_MCP_ENDPOINT
        cls._orig_user = config.XZ_MCP_USER
        config.XZ_MCP_ENDPOINT = f"ws://127.0.0.1:{cls.cloud.port}/mcp"
        config.XZ_MCP_USER = "xzC_" + cls.suffix
        cls._orig_dbget = MB._db_get
        MB._db_get = lambda key: ""   # 隔离共享库里设置页真实接入点，防误连真云
        # 本机单桥闸门隔离（同 BridgeProtocolTest，防正式实例活锁拒起假桥）
        cls._orig_lock = MB._LOCK_FILE
        MB._LOCK_FILE = config.DATA_DIR / f"xz_mcp_bridge.test_{cls.suffix}.lock"
        MB.RETRY_S = 1
        assert _wait_bridge_thread_gone(), "旧桥线程未退出，场景测试会互串"
        assert MB.start_in_background()
        assert cls.cloud.wait_bridge(), "桥未连上假小智云（场景类）"

    @classmethod
    def _insert(cls, sql, params):
        cur = cls.conn.execute(sql, params)
        cls.conn.commit()
        rid = cur.fetchone()[0]
        cls.conn.commit()
        return rid

    @classmethod
    def _err_row(cls, stem, answered):
        pr = cls._insert(
            "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
            "question_content, user_answer, is_correct, options_json) "
            "VALUES (?, ?, ?, ?, ?, 0, ?) RETURNING id",
            (cls.uidC, "测试学科XZI" + cls.suffix, cls.kp, stem, answered,
             json.dumps(["1", "2", "0", "不存在"], ensure_ascii=False)))
        return cls._insert(
            "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
            "practice_record_id, current_proficiency, correct_answer, explanation) "
            "VALUES (?, ?, ?, ?, 20, 'B', '导数定义limΔy/Δx') RETURNING id",
            (cls.uidC, "测试学科XZI" + cls.suffix, cls.kp, pr))

    @classmethod
    def _register(cls, username):
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        return uid, tok

    @classmethod
    def tearDownClass(cls):
        MB.stop()
        _wait_bridge_thread_gone(timeout=10)  # 评审 N3：同上，等桥线程真退再恢复路径
        MB._db_get = cls._orig_dbget
        MB._LOCK_FILE = cls._orig_lock
        cls._cleanup_test_lock()
        cls.cloud.stop()
        config.XZ_MCP_ENDPOINT = cls._orig_ep
        config.XZ_MCP_USER = cls._orig_user
        cls.conn.execute("DELETE FROM error_questions WHERE user_id = ?", (cls.uidC,))
        cls.conn.execute("DELETE FROM practice_records WHERE user_id = ?", (cls.uidC,))
        cls.conn.execute("DELETE FROM knowledge_points WHERE user_id = ?", (cls.uidC,))
        cls.conn.execute("DELETE FROM user_credits WHERE user_id = ?", (cls.uidC,))
        cls.conn.execute("DELETE FROM users WHERE user_id = ?", (cls.uidC,))
        cls.conn.commit()
        cls.conn.close()

    @classmethod
    def _cleanup_test_lock(cls):
        try:
            os.remove(config.DATA_DIR / f"xz_mcp_bridge.test_{cls.suffix}.lock")
        except OSError:
            pass

    def _state(self, since=-1):
        r = self.client.get(f"/api/board/state?since={since}", headers=self.hC)
        self.assertEqual(r.status_code, 200)
        return r.get_json()["data"]

    def test_20_lecture_then_interrupt_switch_topic(self):
        """场景A「讲到一半被打断换题」：完整课堂工具序列 + 打断切换，
        逐节点断言 HTTP 轮询看到的黑板与云端意图一致。"""
        c = self.cloud
        # 备课：取清单（应按 id 倒序包含两道题）
        t = c.call_tool("get_lesson_material", {})
        self.assertIn(str(self.err1), t)
        self.assertIn(str(self.err2), t)
        # 讲第 1 题：上题 → 板书两步 → 高亮答案
        t = c.call_tool("board_show_problem", {"error_id": str(self.err1)})
        self.assertIn("已写上黑板", t)
        id1 = c.call_tool("board_write", {"content": "导数定义：lim Δy/Δx", "kind": "step"})
        self.assertIn("已写上黑板：#", id1)
        step_no = int(id1.split("#")[1].split("（")[0])
        c.call_tool("board_write", {"content": "f'(1)=2x|_{x=1}=2", "kind": "formula"})
        t = c.call_tool("board_highlight", {"item_id": step_no})
        self.assertIn("已点亮", t)
        st = self._state()
        self.assertEqual(len(st["items"]), 5)  # 题干卡+选项卡+step+formula
        self.assertTrue([i for i in st["items"] if i["id"] == step_no][0]["highlighted"])
        self.assertEqual(str(st["source_error_id"]), str(self.err1))
        # ——学生打断：“这题我会了，看 sinx/x 那道”——
        t = c.call_tool("board_clear", {})
        self.assertIn("擦干净", t)
        self.assertEqual(self._state()["items"], [])
        t = c.call_tool("board_show_problem", {"error_id": str(self.err2)})
        self.assertIn("已写上黑板", t)
        st = self._state()
        self.assertEqual(len(st["items"]), 3)  # 题干卡+选项卡
        self.assertEqual(str(st["source_error_id"]), str(self.err2))
        self.assertEqual(st["items"][0]["kind"], "topic")

    def test_21_concurrent_write_and_capacity(self):
        """场景B「连珠板书 + HTTP 并发读」：容量封顶、rev 单调、不死锁。"""
        self.cloud.call_tool("board_clear", {})   # v3: \u4ece\u7a7a\u677f\u8d77\u7b97\uff0c\u907f\u514d\u7ee7\u627f\u524d\u5e8f topic \u679d\u6dd8\u6c70\u8bed\u4e49
        import threading as _th
        stop_ev = _th.Event()
        seen = []

        def watcher():
            while not stop_ev.is_set():
                st = self._state(since=-1)
                seen.append((st["rev"], len(st["items"])))
                time.sleep(0.01)

        th = _th.Thread(target=watcher, daemon=True)
        th.start()
        try:
            for n in range(LB.MAX_ITEMS + 10):  # 50 条 > 封顶 40
                self.cloud.call_tool("board_write", {"content": f"步骤 {n}"})
        finally:
            stop_ev.set()
            th.join(5)
        st = self._state()
        self.assertEqual(len(st["items"]), LB.MAX_ITEMS)
        texts = [i["text"] for i in st["items"]]
        self.assertNotIn("步骤 0", texts)      # 最旧的被擦掉
        self.assertIn(f"步骤 {LB.MAX_ITEMS + 9}", texts)
        revs = [r for r, _ in seen if r is not None]
        self.assertEqual(revs, sorted(revs))   # 并发读到的 rev 无回退

    def test_22_disconnect_reconnect_board_survives(self):
        """场景C「讲课中途网络掉线」：云端主动断连 → 桥 1s 重连 →
        重新握手拉工具表 → 内存黑板不丢，工具继续可接。
        自包含：先清板再写两条，不依赖前序用例的板面残留。"""
        self.cloud.call_tool("board_clear", {})
        self.cloud.call_tool("board_write", {"content": "掉线前板书1"})
        self.cloud.call_tool("board_write", {"content": "掉线前板书2"})
        before = self._state()
        self.assertEqual(len(before["items"]), 2)
        # 云端强制断开
        asyncio.run_coroutine_threadsafe(self.cloud.ws.close(), self.cloud.loop).result(10)
        self.cloud.ws = None
        self.assertTrue(self.cloud.wait_bridge(timeout=30), "桥未在重连窗口内回来")
        # 重连后云端重新拉工具表并继续调用（真实云端会话如连接后先 initialize）
        r = self.cloud.request("tools/list")
        self.assertEqual(len(r["result"]["tools"]), 12)
        t = self.cloud.call_tool("board_write", {"content": "重启后继续板书"})
        self.assertIn("已写上黑板", t)
        after = self._state()
        self.assertEqual(len(after["items"]), 3)
        texts = [i["text"] for i in after["items"]]
        self.assertIn("掉线前板书1", texts)   # 断线不丢内存黑板（临时草稿语义：服务端存活即在）
        self.assertIn("重启后继续板书", texts)
        self.assertTrue(after["bridge_connected"])

    def test_23_anim_async_pipeline(self):
        """C 期异步动画管线（用户裁定的衔接节奏）：开工立即返回不阻塞→
        生成期间 A/B 照常讲课→就绪后首次工具返回宣布「准备好了，我们来看这个」
        （一次性）→board_anim_step 逐步推进声画同源；擦板保住舞台
        （融合轮 2026-11-09 用户裁定：原理图是课级资产，与指派同口径）。
        假 LLM 用 Event 门控，消时序竞态；不碰真云不扣积分。"""
        import llm_provider_factory as LP
        import credits_service as cr
        canvas = ('<!DOCTYPE html><html><head></head><body><p>stage</p>'
                  '<script>window.addEventListener("message",function(){});'
                  '</script></body></html>')
        obj = {"title": "极限动画", "canvas_html": canvas,
               "steps": [{"caption": "字幕" + str(i),
                          "narration": f"这是第{i}步的口播稿文字，需要足够长一点。"}
                         for i in range(5)]}
        release = threading.Event()
        orig_llm, orig_pre = LP.call_llm_for_user, cr.precheck
        LP.call_llm_for_user = lambda *a, **k: (release.wait(15),
                                                json.dumps(obj, ensure_ascii=False))[1]
        cr.precheck = lambda uid: {"allowed": True, "balance": 999}
        try:
            self.cloud.call_tool("board_clear", {})
            t = self.cloud.call_tool("board_render_anim", {"topic": "数列极限"})
            self.assertIn("已后台开工", t)
            st = self._state()
            self.assertEqual(st["anim"]["state"], "generating")
            # 生成期间：A/B 衔接照常；重复开工拒；未就绪推进拒
            self.assertIn("已写上黑板",
                          self.cloud.call_tool("board_write", {"content": "衔接讲课卡"}))
            dup = self.cloud.call_tool("board_render_anim", {"topic": "再开"})
            self.assertIn("已经在后台生成中", dup)
            early = self.cloud.call_tool("board_anim_step", {"step": 0})
            self.assertIn("还没就绪", early)
            release.set()
            for _ in range(100):
                st = self._state()
                if st["anim"] and st["anim"]["state"] == "ready":
                    break
                time.sleep(0.1)
            self.assertEqual(st["anim"]["state"], "ready")
            self.assertEqual(len(st["anim"]["steps"]), 5)
            self.assertNotIn("gen", st["anim"])          # 内部令牌不外泄
            # 就绪宣布：一次性消费（首条 ready 后的工具调用才带尾注）
            t2 = self.cloud.call_tool("board_write", {"content": "宣布卡"})
            self.assertIn("准备好了，我们来看这个", t2)
            self.assertNotIn("准备好了",
                             self.cloud.call_tool("board_write", {"content": "再一张"}))
            # 逐步推进：返回字幕+口播，前端靠 state.anim.current 同步画面
            s0 = self.cloud.call_tool("board_anim_step", {"step": 0})
            self.assertIn("舞台已推进到第 0 步", s0)
            self.assertIn("口播稿", s0)
            self.assertIn("超出范围", self.cloud.call_tool("board_anim_step", {"step": 9}))
            self.assertEqual(self._state()["anim"]["current"], 0)
            # 擦板保住舞台（融合轮语义：只清板书卡，anim 留着学生随时可看）
            self.cloud.call_tool("board_clear", {})
            st2 = self._state()
            self.assertEqual(st2["anim"]["state"], "ready")
            self.assertEqual(st2["anim"]["current"], 0)
        finally:
            LP.call_llm_for_user, cr.precheck = orig_llm, orig_pre
            release.set()


class Phase3ContractTest(unittest.TestCase):
    """v3 contract direct asserts (no bridge): anchors strip / point hitchhike /
    focus single-slot exclusion+cleanup / topic lifecycle / reveal steps /
    stats+diagram+geometry extensions / spec size gate / status_line summary."""

    def setUp(self):
        self.uid = "p3_" + uuid.uuid4().hex[:10]

    def _tool(self, name, args=None):
        return LB.execute_tool(name, args or {}, self.uid)

    def _st(self):
        return LB.get_state(self.uid, since_rev=-1)

    def _last_id(self):
        return self._st()["items"][-1]["id"]

    # ---------------- anchors & hitchhike params
    def test_p3_01_anchor_strip_and_store(self):
        t = self._tool("board_write", {"kind": "step",
                                       "content": "\u5148\u770b\u3014\u6781\u9650\u5b9a\u4e49\u3015\u518d\u770b\u3014\u7ed3\u8bba\u3015"})
        self.assertIn("\u5df2\u5199\u4e0a\u9ed1\u677f", t)
        it = self._st()["items"][-1]
        self.assertEqual(it["text"], "\u5148\u770b\u6781\u9650\u5b9a\u4e49\u518d\u770b\u7ed3\u8bba")
        self.assertEqual(it["anchors"], ["\u6781\u9650\u5b9a\u4e49", "\u7ed3\u8bba"])
        self.assertIsNone(it["parent_id"])

    def test_p3_02_write_point_hitchhiker(self):
        t = self._tool("board_write", {"kind": "note",
                                       "content": "\u6bd4\u8f83\u3014\u7532\u3015\u4e0e\u3014\u4e59\u3015\u4f18\u52a3",
                                       "point": 2})
        self.assertIn("\u7ea2\u70b9\u6307\u7740\u300c\u4e59\u300d", t)
        st = self._st()
        f = st["focus"]
        self.assertEqual(f["item_id"], st["items"][-1]["id"])
        self.assertEqual(f["anchor"], 2)
        self.assertIsNone(f["mark"])
        self.assertIsNone(f["reveal"])
        self.assertTrue(f["seq"] >= 1)
        self.assertEqual([i["id"] for i in st["items"] if i["highlighted"]],
                         [f["item_id"]])

    def test_p3_03_point_out_of_range_still_lights_card(self):
        self._tool("board_write", {"kind": "step",
                                   "content": "\u5148\u770b\u3014\u4e01\u3015\u518d\u770b\u3014\u4e0e\u3015"})
        cid = self._last_id()
        t = self._tool("board_write", {"kind": "note",
                                       "content": "\u53ea\u6709\u3014\u4e24\u3015\u4e2a\u951a\u70b9",
                                       "point": 5})
        self.assertIn("\u6307\u4e0d\u5230", t)
        self.assertIn("\u5df2\u6574\u5361\u70b9\u4eae", t)
        f = self._st()["focus"]
        self.assertEqual(f["item_id"], self._last_id())  # newest card
        self.assertIsNone(f["anchor"])
        self.assertTrue(f["item_id"] != cid)
        self.assertTrue([i for i in self._st()["items"]
                         if i["id"] == f["item_id"]][0]["highlighted"])

    def test_p3_04_formula_rejects_anchor_note(self):
        t = self._tool("board_write", {"kind": "formula",
                                       "content": "e^x", "point": 1})
        self.assertIn("\u4e0d\u652f\u6301\u951a\u70b9\u6307\u8ba4", t)
        st = self._st()
        self.assertIsNone(st["focus"]["anchor"])
        self.assertTrue(st["items"][-1]["highlighted"])

    def test_p3_05_highlight_old_card_repoints(self):
        self._tool("board_write", {"kind": "step",
                                   "content": "\u770b\u3014\u7532\u3015\u548c\u3014\u4e59\u3015"})
        old = self._last_id()
        self._tool("board_write", {"kind": "step", "content": "\u65b0\u5361"})
        t = self._tool("board_highlight", {"item_id": old, "point": 1})
        self.assertIn("\u5df2\u70b9\u4eae\u5361", t)
        self.assertIn("\u5176\u4f59\u7184\u706d", t)
        self.assertIn("\u7ea2\u70b9\u6307\u7740\u300c\u7532\u300d", t)
        f = self._st()["focus"]
        self.assertEqual(f["item_id"], old)
        self.assertEqual(f["anchor"], 1)

    # ---------------- focus single-slot: exclusion & cleanup timing
    def test_p3_06_focus_exclusion_and_seq_monotonic(self):
        self._tool("board_write", {"kind": "step", "content": "A\u5361"})
        a = self._last_id()
        self._tool("board_write", {"kind": "step", "content": "B\u5361"})
        seq1 = self._st()["focus"]["seq"]
        self._tool("board_highlight", {"item_id": a})
        st = self._st()
        self.assertEqual(st["focus"]["item_id"], a)
        self.assertGreater(st["focus"]["seq"], seq1)
        lit = [i["id"] for i in st["items"] if i["highlighted"]]
        self.assertEqual(lit, [a])

    def test_p3_07_focus_cleanup_on_remove_replace_clear_evict(self):
        self._tool("board_write", {"kind": "step", "content": "\u7126\u70b9\u5361"})
        cid = self._last_id()
        self._tool("board_highlight", {"item_id": cid})
        self._tool("board_remove", {"item_id": cid})
        self.assertIsNone(self._st()["focus"])
        self._tool("board_write", {"kind": "step", "content": "\u6539\u5199\u5361"})
        cid = self._last_id()
        self._tool("board_highlight", {"item_id": cid})
        self._tool("board_replace", {"item_id": cid, "content": "\u6362\u4e86"})
        self.assertIsNone(self._st()["focus"])
        self._tool("board_write", {"kind": "step", "content": "\u6e05\u677f\u5361"})
        self._tool("board_clear", {})
        self.assertIsNone(self._st()["focus"])
        # eviction of the focused card also clears focus (append directly:
        # board_write would move focus to each new card and mask the check)
        self._tool("board_write", {"kind": "step", "content": "\u6700\u65e7\u5361"})
        first = self._st()["items"][0]["id"]
        self._tool("board_highlight", {"item_id": first})
        with LB._lock:
            b = LB._board(self.uid)
            for n in range(LB.MAX_ITEMS):
                LB._append_locked(b, "step", "n%d" % n)
        self.assertIsNone(self._st()["focus"])

    # ---------------- topic lifecycle
    def test_p3_08_topic_cascade_remove(self):
        self._tool("board_write", {"kind": "topic", "content": "\u51fd\u6570\u5355\u5143"})
        tid = self._last_id()
        self._tool("board_write", {"kind": "step", "content": "\u5b50\u5361\u4e00"})
        kid = self._last_id()
        self.assertEqual(self._st()["items"][-1]["parent_id"], tid)
        t = self._tool("board_remove", {"item_id": tid})
        self.assertIn("\u5df2\u64e6\u6389\u4e3b\u5e72", t)
        self.assertIn("2 \u5f20", t)
        self.assertEqual(self._st()["items"], [])
        self.assertNotIn(kid, [i["id"] for i in self._st()["items"]])

    def test_p3_09_replace_rejects_plot_and_kindflip(self):
        self._tool("board_draw", {"spec": {"plot_type": "numberline", "range": [0, 5],
                                           "points": [{"v": 1, "label": "A", "step": 1}]}})
        pid = self._last_id()
        t = self._tool("board_replace", {"item_id": pid, "content": "x"})
        self.assertIn("\u56fe\u5361\u4e0d\u80fd\u6539\u5199", t)     # plot refuse
        self.assertIn("board_draw", t)
        self.assertIsNotNone([i for i in self._st()["items"]
                              if i["id"] == pid][0].get("data"))    # data intact
        self._tool("board_write", {"kind": "topic", "content": "\u4e3b\u5e72"})
        tid = self._last_id()
        t = self._tool("board_replace", {"item_id": tid, "kind": "step",
                                         "content": "\u964d\u7ea7"})
        self.assertIn("\u4e0d\u80fd\u4e92\u8f6c", t)               # kindflip refuse
        t = self._tool("board_replace", {"item_id": tid, "kind": "topic",
                                         "content": "\u65b0\u4e3b\u5e72\u540d"})
        self.assertIn("\u5df2\u6539\u5199\u4e3a", t)
        # review Major-1: plot cards are born only via board_draw (no dead data-less plot)
        t = self._tool("board_write", {"kind": "plot", "content": "\u4f2a\u56fe"})
        self.assertIn("board_draw", t)
        self.assertNotIn("plot", [i["kind"] for i in self._st()["items"]
                                 if i["text"] == "\u4f2a\u56fe"])
        t = self._tool("board_replace", {"item_id": tid, "kind": "plot",
                                         "content": "x"})
        self.assertIn("\u56fe\u5361\u4e0d\u80fd\u6539\u5199", t)

    # ---------------- reveal & plot marks via hitchhike
    def test_p3_10_reveal_steps(self):
        spec = {"plot_type": "numberline", "range": [0, 5],
                "points": [{"v": 1, "label": "A", "step": 1},
                           {"v": 3, "label": "B", "step": 2},
                           {"v": 4, "label": "C", "step": 3}]}
        t = self._tool("board_draw", {"spec": spec, "reveal": 2})
        self.assertIn("\u53ea\u663e\u793a\u5230\u7b2c 2 \u6b65", t)
        st = self._st()
        self.assertEqual(st["focus"]["reveal"], 2)
        pid = st["items"][-1]["id"]
        t = self._tool("board_draw", {"spec": spec, "reveal": 9})
        self.assertIn("\u8d85\u4e86", t)
        self.assertIsNone(self._st()["focus"]["reveal"])
        self._tool("board_write", {"kind": "step", "content": "\u6587\u672c\u5361"})
        sid = self._last_id()
        t = self._tool("board_highlight", {"item_id": sid, "reveal": 1})
        self.assertIn("reveal \u53ea\u5728\u56fe\u5361\u4e0a\u5206\u6b65", t)
        self.assertEqual(self._st()["focus"]["item_id"], sid)
        t = self._tool("board_highlight", {"item_id": pid, "reveal": 1})
        self.assertIn("\u56fe\u53ea\u663e\u793a\u5230\u7b2c 1 \u6b65", t)

    def test_p3_11_plot_marks_laser(self):
        spec = {"plot_type": "function", "curves": [{"expr": "sin(x)"}],
                "x_range": [0, 6.3],
                "marks": [{"name": "\u96f6\u70b9", "x": 3.14},
                          {"name": "\u7aef\u70b9", "x": 6.3}]}
        t = self._tool("board_draw", {"spec": spec})
        self.assertIn("\u53ef\u6307\u8ba4\u6807\u8bb0", t)
        pid = self._last_id()
        t = self._tool("board_highlight", {"item_id": pid, "point": 2})
        self.assertIn("\u6fc0\u5149\u6307\u5230\u56fe\u4e0a\u7684\u300c\u7aef\u70b9\u300d", t)
        self.assertEqual(self._st()["focus"]["mark"], 2)
        t = self._tool("board_highlight", {"item_id": pid, "point": 7})
        self.assertIn("point \u8981\u5728 1~2", t)
        self.assertIsNone(self._st()["focus"]["mark"])
        self.assertTrue(self._st()["items"][-1]["highlighted"])

    # ---------------- DSL extensions: stats / diagram / geometry / size gate
    def test_p3_12_stats(self):
        t = self._tool("board_draw", {"spec": {
            "plot_type": "stats", "shape": "bar",
            "categories": ["a", "b", "c"],
            "series": [{"name": "x", "values": [1, 2, 3]}]}})
        self.assertIn("\u5df2\u753b\u4e0a\u9ed1\u677f", t)
        d = self._st()["items"][-1]["data"]
        self.assertEqual(d["plot_type"], "stats")
        self.assertEqual(d["shape"], "bar")
        t = self._tool("board_draw", {"spec": {
            "plot_type": "stats", "shape": "pie",
            "slices": [{"label": "p", "value": 30}, {"label": "q", "value": 70}]}})
        self.assertIn("\u5df2\u753b\u4e0a\u9ed1\u677f", t)
        self.assertEqual(len(self._st()["items"][-1]["data"]["slices"]), 2)
        t = self._tool("board_draw", {"spec": {
            "plot_type": "stats", "shape": "bar",
            "categories": [str(i) for i in range(9)],
            "series": [{"values": [1] * 9}]}})
        self.assertIn("\u56fe\u6ca1\u753b\u4e0a", t)
        self.assertIn("1~8", t)
        t = self._tool("board_draw", {"spec": {
            "plot_type": "stats", "shape": "hist",
            "categories": ["a"], "series": [{"values": [1]}]}})
        self.assertIn("\u7edf\u8ba1\u56fe", t)

    def test_p3_13_diagram(self):
        t = self._tool("board_draw", {"spec": {
            "plot_type": "diagram", "shape": "flow",
            "nodes": [{"id": "a", "text": "\u5f00\u59cb"},
                      {"id": "b", "text": "\u7ed3\u675f", "shape": "ellipse"}],
            "edges": [{"from": "a", "to": "b", "label": "go"}]}})
        self.assertIn("\u5df2\u753b\u4e0a\u9ed1\u677f", t)
        d = self._st()["items"][-1]["data"]
        for nd in d["nodes"]:
            self.assertTrue(all(k in nd for k in ("x", "y", "w", "h", "step")))
        self.assertGreaterEqual(len(d["edges"][0]["path"]), 2)
        self.assertEqual(len(d["marks"]), 2)
        # review Major-2: documented cap (8 nodes) must stay inside the 240-tall canvas
        t = self._tool("board_draw", {"spec": {
            "plot_type": "diagram", "shape": "flow",
            "nodes": [{"id": str(i), "text": "n%d" % i} for i in range(8)],
            "edges": []}})
        self.assertIn("\u5df2\u753b\u4e0a\u9ed1\u677f", t)
        nds = self._st()["items"][-1]["data"]["nodes"]
        self.assertLessEqual(max(nd["y"] + nd["h"] for nd in nds), 230.5)
        t = self._tool("board_draw", {"spec": {
            "plot_type": "diagram", "shape": "flow",
            "nodes": [{"id": str(i), "text": "n%d" % i} for i in range(9)],
            "edges": []}})
        self.assertIn("\u8282\u70b9\u6700\u591a 8 \u4e2a", t)
        t = self._tool("board_draw", {"spec": {
            "plot_type": "diagram", "shape": "barmodel",
            "parts": [{"label": "r", "value": 3}, {"label": "b", "value": 5}],
            "total": 8}})
        self.assertIn("\u5df2\u753b\u4e0a\u9ed1\u677f", t)
        self.assertEqual(len(self._st()["items"][-1]["data"]["parts"]), 2)

    def test_p3_14_geometry_extensions(self):
        spec = {"plot_type": "geometry",
                "points": [{"x": 0, "y": 0, "label": "A"},
                           {"x": 4, "y": 0, "label": "B"},
                           {"x": 4, "y": 3, "label": "C"}],
                "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}],
                "polygons": [{"pts": ["A", "B", "C"], "fill": True}],
                "angles": [{"at": "B", "from": "A", "to": "C", "label": "90"}],
                "ticks": [{"segs": ["AB", "BC"], "n": 2}],
                "dims": [{"a": "A", "b": "B", "label": "4"}],
                "notes": [{"x": 1, "y": 2, "text": "note"}]}
        t = self._tool("board_draw", {"spec": spec})
        self.assertIn("\u5df2\u753b\u4e0a\u9ed1\u677f", t)
        d = self._st()["items"][-1]["data"]
        v = d["view"]
        ar = (v["xmax"] - v["xmin"]) / (v["ymax"] - v["ymin"])
        # review Minor-6: aspect now matches frontend drawable area (332x212 with PAD 14)
        self.assertAlmostEqual(ar, 332.0 / 212.0, places=2)   # equal-ratio projection
        self.assertTrue(d["angles"][0]["square"])   # right-angle marker
        self.assertEqual(len(d["ticks"]), 1)
        self.assertEqual(len(d["dims"]), 1)
        names = [m["name"] for m in d["marks"]]
        self.assertIn("90", names)
        pid = self._last_id()
        t = self._tool("board_highlight", {"item_id": pid,
                                          "point": len(d["marks"])})
        self.assertIn("\u6fc0\u5149\u6307\u5230\u56fe\u4e0a\u7684\u300c90\u300d", t)

    def test_p3_15_spec_size_gate(self):
        # 四期闸提到 4000（图型变复杂），这里造一个确实超限的散点描述
        big = {"plot_type": "stats", "shape": "scatter",
               "series": [{"name": "\u7cfb\u5217%d" % k,
                           "points": [{"x": i, "y": i * 2,
                                       "label": "\u7b2c%d\u7ec4\u7b2c%d\u4e2a\u6570\u636e\u70b9\uff08\u533a\u95f4\u5185\uff09" % (k, i)}
                                      for i in range(30)]}
                          for k in range(3)]}
        self.assertGreater(len(json.dumps(big, ensure_ascii=False)), BP._SPEC_JSON_MAX)
        t = self._tool("board_draw", {"spec": big})
        self.assertIn("\u56fe\u6ca1\u753b\u4e0a", t)
        self.assertIn("\u56fe\u5f62\u63cf\u8ff0\u592a\u5927", t)

    # ---------------- status_line two-level summary
    def test_p3_16_status_line(self):
        self.assertEqual(LB.status_line(self.uid), "\u5f53\u524d\u9ed1\u677f\u662f\u7a7a\u7684")
        self._tool("board_write", {"kind": "step", "content": "\u6563\u5361"})
        self._tool("board_write", {"kind": "topic", "content": "\u51fd\u6570\u5355\u5143"})
        tid = self._last_id()
        self._tool("board_write", {"kind": "step", "content": "\u5b50\u5361"})
        sid = self._last_id()
        line = LB.status_line(self.uid)
        self.assertIn("\u6563\u5361 #1", line)
        self.assertIn("#%d\u3014\u51fd\u6570\u5355\u5143\u3015\u2192#%d" % (tid, sid), line)
        self.assertLessEqual(len(line), LB._STATUS_MAX)


class McpSettingsApiTest(unittest.TestCase):
    """设置页 MCP 接入配置 API（2026-11-05）：粘贴接入点→连接→状态/断开。
    _db_get/_db_set 用内存假存储不碰共享库；_spawn/stop 桩化不起真实线程。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.user = "xzm_" + uuid.uuid4().hex[:8]
        cls.client.post("/api/auth/register",
                        json={"username": cls.user, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": cls.user, "password": "test123456"})
        cls.h = {"Authorization": "Bearer " + r.get_json()["data"]["token"]}

    def setUp(self):
        self.store = {}
        self.spawned = []
        self.stop_calls = []
        self._orig = (MB._db_get, MB._db_set, MB._spawn, MB.stop)
        MB._db_get = lambda key: self.store.get(key, "")
        MB._db_set = lambda key, value, desc="": self.store.__setitem__(key, value)
        MB._spawn = lambda ep, user: (self.spawned.append((ep, user)), True)[1]
        MB.stop = lambda: self.stop_calls.append(1)
        # connect() 新增 _held_by_other 预检会读真锁：指向不存在的唯一路径隔离，
        # 防正式 9992 在跑时本机活锁把预期成功的用例误拒
        self._orig_lock = MB._LOCK_FILE
        MB._LOCK_FILE = (config.DATA_DIR /
                         f"xz_mcp_bridge.set_{uuid.uuid4().hex[:8]}.lock")
        # .env 可能带真实接入点（server/.env），同样隔离，优先级断言才确定
        self._orig_cfg = (config.XZ_MCP_ENDPOINT, config.XZ_MCP_USER)
        config.XZ_MCP_ENDPOINT = ""
        config.XZ_MCP_USER = ""

    def tearDown(self):
        MB._db_get, MB._db_set, MB._spawn, MB.stop = self._orig
        MB._LOCK_FILE = self._orig_lock
        config.XZ_MCP_ENDPOINT, config.XZ_MCP_USER = self._orig_cfg

    def test_status_requires_auth(self):
        r = self.client.get("/api/board/mcp/status")
        self.assertEqual(r.status_code, 401)

    def test_connect_refused_when_local_bridge_live(self):
        """评审 W3 回归：本机已有活桥时 connect 拒绝，且不得留下 enabled='1' 假象。
        pid 用真活着的子进程——闸门 2026-11-10 起会查活，假 pid 不再算持有者。"""
        with open(MB._LOCK_FILE, "w", encoding="utf-8") as f:
            json.dump({"pid": _live_other_pid(), "beat": time.time()}, f)
        try:
            ok, msg = MB.connect("wss://x.example/mcp?token=t", "someone")
            self.assertFalse(ok)
            self.assertIn("本机另一实例", msg)
            self.assertNotIn("xz_mcp.enabled", self.store)   # 预检拒后不写库不起桥
            self.assertEqual(self.spawned, [])
        finally:
            os.remove(MB._LOCK_FILE)

    def test_connect_allowed_when_holder_dead(self):
        """实弹回归：残留锁的持有者已退出 → 设置页 connect 照常放行（桥必须能起）。"""
        with open(MB._LOCK_FILE, "w", encoding="utf-8") as f:
            json.dump({"pid": _dead_pid(), "beat": time.time()}, f)
        try:
            ok, msg = MB.connect("wss://x.example/mcp?token=t", "someone")
            self.assertTrue(ok, msg)
            self.assertEqual(len(self.spawned), 1)
        finally:
            os.remove(MB._LOCK_FILE)

    def test_effective_config_priority(self):
        # 键未设且 .env 未配 → 空
        self.assertEqual(MB.effective_config(), ("", ""))
        # 键未设 → 回退 .env
        config.XZ_MCP_ENDPOINT = "wss://env.test/mcp/?token=ENV"
        config.XZ_MCP_USER = "envUser"
        self.assertEqual(MB.effective_config(), ("wss://env.test/mcp/?token=ENV", "envUser"))
        # 页面断开（'0'）→ 即便 .env 配了也不生效（显式覆盖）
        self.store[MB.CFG_ON] = "0"
        self.assertEqual(MB.effective_config(), ("", ""))
        # 页面连接（'1'）→ 取页面保存值
        self.store[MB.CFG_ON] = "1"
        self.store[MB.CFG_EP] = "wss://api.xiaozhi.me/mcp/?token=t0k3n"
        self.store[MB.CFG_USER] = "someTeacher"
        self.assertEqual(MB.effective_config(),
                         ("wss://api.xiaozhi.me/mcp/?token=t0k3n", "someTeacher"))

    def test_mask_endpoint(self):
        self.assertEqual(MB.mask_endpoint("wss://h/mcp/?token=SECRETVALUE"),
                         "wss://h/mcp/?token=****")
        self.assertEqual(MB.mask_endpoint("wss://h/mcp/?token=AB&x=1"),
                         "wss://h/mcp/?token=****&x=1")
        self.assertEqual(MB.mask_endpoint("wss://h/mcp/"), "wss://h/mcp/")

    def test_connect_rejects_bad_scheme(self):
        r = self.client.post("/api/board/mcp/connect",
                             json={"endpoint": "http://example.com"}, headers=self.h)
        j = r.get_json()
        self.assertFalse(j["success"])
        self.assertIn("wss", j["error"])
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.store, {})   # 非法地址不得落盘

    def test_connect_persists_spawns_and_masks(self):
        ep = "wss://api.xiaozhi.me/mcp/?token=SECRETVALUE"
        r = self.client.post("/api/board/mcp/connect", json={"endpoint": ep},
                             headers=self.h)
        j = r.get_json()
        self.assertTrue(j["success"])
        self.assertEqual(self.spawned, [(ep, self.user)])   # 黑板绑定为点连接的用户
        self.assertEqual(self.store[MB.CFG_ON], "1")
        self.assertEqual(self.store[MB.CFG_EP], ep)
        self.assertNotIn("SECRETVALUE", j["data"]["endpoint_masked"])
        self.assertIn("token=****", j["data"]["endpoint_masked"])
        self.assertFalse(j["data"]["connected"])   # 线程被桩化，状态仍未连接

    def test_disconnect_sets_off_and_stops(self):
        self.store[MB.CFG_ON] = "1"
        r = self.client.post("/api/board/mcp/disconnect", json={}, headers=self.h)
        j = r.get_json()
        self.assertTrue(j["success"])
        self.assertEqual(self.store[MB.CFG_ON], "0")
        self.assertEqual(self.stop_calls, [1])
        self.assertFalse(j["data"]["configured"])


class XzDeviceTest(unittest.TestCase):
    """小智设备账号级绑定（2026-11-05）：表读写走独立测试用户隔离，
    OTA probe 全部桩化（注入 post），绝不碰真小智云。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.user = "xzdev_" + uuid.uuid4().hex[:8]
        cls.client.post("/api/auth/register",
                        json={"username": cls.user, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": cls.user, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        cls.h = {"Authorization": "Bearer " + tok}
        seg = tok.split(".")[1]
        cls.uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])

    def setUp(self):
        XD._delete(self.uid)

    @staticmethod
    def _post_code(code="654321"):
        calls = []
        def post(url, json=None, headers=None, timeout=None):
            calls.append({"url": url, "body": json, "headers": headers})
            return type("R", (), {"status_code": 200, "json": lambda s: {
                "activation": {"code": code, "message": "请输码"}}})()
        post.calls = calls
        return post

    @staticmethod
    def _post_bound():
        def post(url, json=None, headers=None, timeout=None):
            return type("R", (), {"status_code": 200, "json": lambda s: {
                "websocket": {"url": "wss://x.test/ws", "token": "tk", "version": 1}}})()
        return post

    def test_norm_mac_variants(self):
        self.assertEqual(XD.norm_mac("FE:11:22:33:44:55"), "fe:11:22:33:44:55")
        self.assertEqual(XD.norm_mac("fe1122334455"), "fe:11:22:33:44:55")
        self.assertEqual(XD.norm_mac("fe-11-22-33-44-55"), "fe:11:22:33:44:55")
        self.assertEqual(XD.norm_mac("abc"), "")
        self.assertEqual(XD.norm_mac("zz:a9:76:83:9f:15"), "")

    def test_mac_from_seed_matches_js_derivation(self):
        # 与 desktop/xz_voice.js macFromSeed 同款：确定性 + 小写冒号 + 首字节本地位
        m1 = XD.mac_from_seed("deadbeef")
        m2 = XD.mac_from_seed("deadbeef")
        self.assertEqual(m1, m2)
        self.assertRegex(m1, r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
        b0 = int(m1.split(":")[0], 16)
        self.assertEqual(b0 & 0x03, 0x02)  # 单播位清 0 + 本地位置 1

    def test_probe_ota_shapes(self):
        p = XD.probe_ota("fe:11:22:33:44:55", "u1", post=self._post_bound())
        self.assertTrue(p["ok"]); self.assertTrue(p["bound"]); self.assertEqual(p["ws_url"], "wss://x.test/ws")
        p = XD.probe_ota("fe:11:22:33:44:55", "u1", post=self._post_code())
        self.assertTrue(p["ok"]); self.assertFalse(p["bound"]); self.assertEqual(p["code"], "654321")
        def bad(url, json=None, headers=None, timeout=None):
            return type("R", (), {"status_code": 400, "json": lambda s: {}})()
        p = XD.probe_ota("fe:11:22:33:44:55", "u1", post=bad)
        self.assertFalse(p["ok"]); self.assertIn("400", p["error"])
        def boom(url, json=None, headers=None, timeout=None):
            raise OSError("net down")
        p = XD.probe_ota("fe:11:22:33:44:55", "u1", post=boom)
        self.assertFalse(p["ok"]); self.assertIn("net down", p["error"])

    def test_generate_returns_code_and_persists_pending(self):
        ok, message = XD.generate(self.uid, post=self._post_code("123456"))
        self.assertTrue(ok)
        self.assertEqual(message, "123456")
        row = XD.get_row(self.uid)
        self.assertEqual(row["dev_type"], "virtual")
        self.assertEqual(row["state"], "pending_code")
        self.assertEqual(row["last_code"], "123456")
        self.assertRegex(row["mac"], r"^[0-9a-f:]{17}$")
        # 再点生成 → 拒绝（每账号至多一台）
        ok2, msg2 = XD.generate(self.uid, post=self._post_code())
        self.assertFalse(ok2)
        self.assertIn("解绑", msg2)

    def test_generate_instant_bound_collision(self):
        ok, message = XD.generate(self.uid, post=self._post_bound())
        self.assertTrue(ok)
        self.assertEqual(XD.get_row(self.uid)["state"], "bound")

    def test_bind_real_validation_and_states(self):
        ok, msg = XD.bind_real(self.uid, "not-a-mac", post=self._post_bound())
        self.assertFalse(ok); self.assertIn("格式", msg)
        self.assertIsNone(XD.get_row(self.uid))  # 非法不得落盘
        ok, msg = XD.bind_real(self.uid, "FE1122334455", post=self._post_bound())
        self.assertTrue(ok)
        row = XD.get_row(self.uid)
        self.assertEqual(row["dev_type"], "real")
        self.assertEqual(row["state"], "bound")
        self.assertEqual(row["mac"], "fe:11:22:33:44:55")
        XD._delete(self.uid)
        ok, msg = XD.bind_real(self.uid, "11:22:33:44:55:66", post=self._post_code())
        self.assertTrue(ok)  # 未激活也可登记，文案引导先激活
        self.assertIn("激活", msg)
        self.assertEqual(XD.get_row(self.uid)["state"], "pending_code")

    def test_recheck_state_machine(self):
        XD.generate(self.uid, post=self._post_code())
        mac = XD.get_row(self.uid)["mac"]
        seen = []
        def post(url, json=None, headers=None, timeout=None):
            seen.append(json["mac_address"])
            return type("R", (), {"status_code": 200, "json": lambda s: {
                "websocket": {"url": "wss://x", "token": "t", "version": 1}}})()
        ok, msg = XD.recheck(self.uid, post=post)
        self.assertTrue(ok); self.assertIn("认领成功", msg)
        self.assertEqual(seen, [mac])  # 用存档 MAC 复查
        self.assertEqual(XD.get_row(self.uid)["state"], "bound")
        # 已 bound 再 recheck → 幂等成功
        ok, msg = XD.recheck(self.uid, post=post)
        self.assertTrue(ok)
        XD._delete(self.uid)
        ok, msg = XD.recheck(self.uid, post=post)
        self.assertFalse(ok)  # 无绑定

    def test_migrate_idempotent_and_conflict(self):
        ok, msg = XD.migrate(self.uid, "FE:11:22:33:44:55", "uuid-old")
        self.assertTrue(ok)
        row = XD.get_row(self.uid)
        self.assertEqual(row["mac"], "fe:11:22:33:44:55")
        self.assertEqual(row["state"], "bound")
        self.assertEqual(row["client_uuid"], "uuid-old")
        ok, _ = XD.migrate(self.uid, "fe:11:22:33:44:55", "uuid-new")  # 同 MAC 幂等，不覆盖
        self.assertTrue(ok)
        self.assertEqual(XD.get_row(self.uid)["client_uuid"], "uuid-old")
        ok, msg = XD.migrate(self.uid, "aa:bb:cc:dd:ee:ff", "u")  # 另一台 → 拒
        self.assertFalse(ok); self.assertIn("已经绑定", msg)
        ok, msg = XD.migrate(self.uid, "xyz", "u")  # 非法格式 → 拒
        self.assertFalse(ok)

    def test_pending_row_blocks_rebind_and_mac_owner_guard(self):
        # CodeReview P2-5：pending 记录也要求先解绑（与 generate 同口径，防 API 直调静默覆盖）
        XD.generate(self.uid, post=self._post_code())
        ok, msg = XD.bind_real(self.uid, "FE:11:22:33:44:55", post=self._post_bound())
        self.assertFalse(ok); self.assertIn("先解绑", msg)
        self.assertEqual(XD.get_row(self.uid)["dev_type"], "virtual")  # 未被覆盖
        # CodeReview P2-3：MAC 已在别人名下 → bind_real/migrate 均拒（先绑者得）。
        # MAC 每次随机生成＋addCleanup 清痕：避免万一中途失败时污染其它用例。
        import random
        rest = "".join(random.choice("0123456789abcdef") for _ in range(10))
        mine = "02:" + ":".join(rest[i:i + 2] for i in range(0, 10, 2))
        other = "xzdevo_" + uuid.uuid4().hex[:8]
        self.addCleanup(XD._delete, other)
        ok, msg = XD.migrate(other, mine, "u-o")
        self.assertTrue(ok, msg)
        XD._delete(self.uid)
        ok, msg = XD.migrate(self.uid, mine, "u-me")
        self.assertFalse(ok); self.assertIn("别的账号", msg)
        ok, msg = XD.bind_real(self.uid, mine, post=self._post_bound())
        self.assertFalse(ok); self.assertIn("别的账号", msg)
        self.assertIsNone(XD.get_row(self.uid))  # 拒绝后不落盘

    def test_unbind_and_status_views(self):
        XD.migrate(self.uid, "fe:11:22:33:44:55", "u1")
        v = XD.status(self.uid)
        self.assertTrue(v["bound"]); self.assertTrue(v["has_device"])
        self.assertEqual(v["dev_type"], "virtual")
        ident = XD.identity(self.uid)
        self.assertEqual(ident["client_uuid"], "u1")  # bound 才给身份
        XD.unbind(self.uid)
        self.assertEqual(XD.status(self.uid), {"has_device": False, "bound": False,
                                               "dev_type": "", "mac": "", "state": "",
                                               "code": "", "message": ""})
        self.assertNotIn("client_uuid", XD.identity(self.uid))  # 未绑不发身份

    def test_api_flows_with_patched_ota(self):
        r = self.client.get("/api/board/xzdevice/status")
        self.assertEqual(r.status_code, 401)  # 鉴权
        import types
        orig = XD.requests
        XD.requests = types.SimpleNamespace(post=self._post_code("606060"))
        try:
            r = self.client.post("/api/board/xzdevice/generate", json={}, headers=self.h)
            j = r.get_json()
            self.assertTrue(j["success"])
            self.assertEqual(j["data"]["code"], "606060")
            self.assertFalse(j["data"]["bound"])
            r = self.client.post("/api/board/xzdevice/bind_real",
                                 json={"mac": "bad"}, headers=self.h)
            j = r.get_json()
            self.assertFalse(j["success"]); self.assertIn("格式", j["error"])
            r = self.client.get("/api/board/xzdevice/identity", headers=self.h)
            j = r.get_json()
            self.assertFalse(j["data"]["bound"])
            self.assertNotIn("client_uuid", j["data"])
        finally:
            XD.requests = orig
        r = self.client.post("/api/board/xzdevice/migrate",
                             json={"mac": "fe:11:22:33:44:55", "client_uuid": "u"},
                             headers=self.h)
        # 已有 pending 虚拟设备 → 迁移被拒（保护已绑定路径）
        self.assertFalse(r.get_json()["success"])
        r = self.client.post("/api/board/xzdevice/unbind", json={}, headers=self.h)
        self.assertTrue(r.get_json()["success"])


class BoardSpeechLessonTest(unittest.TestCase):
    """字幕流 + 图卡闭窗 + 课件入库与导出（黑板两段式版式轮 2026-11-05）。

    只走 HTTP 与 lecture_board 公开 API（内部写卡用 _write_focus_card 等价于 board_draw 入板）；
    课件表复用真 PG 的 micro_courses/micro_scenes，测后按课件键清理。零外网。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.user = "xzsl_" + uuid.uuid4().hex[:8]
        cls.client.post("/api/auth/register",
                        json={"username": cls.user, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": cls.user, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        cls.h = {"Authorization": "Bearer " + tok}
        seg = tok.split(".")[1]
        cls.uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        cls.keys = []

    @classmethod
    def tearDownClass(cls):
        for k in cls.keys:
            c = BL.get_course(cls.uid, k)
            if c:
                db = DatabaseManager(str(config.DB_PATH))
                conn = db.get_connection()
                conn.execute("DELETE FROM micro_scenes WHERE course_id = ?", (c["id"],))
                conn.execute("DELETE FROM micro_courses WHERE id = ?", (c["id"],))
                conn.commit()
                conn.close()
                d = BL._lesson_dir(cls.uid, k)
                if d and d.is_dir():
                    for f in d.iterdir():
                        try:
                            f.unlink()
                        except OSError:
                            pass
                    try:
                        d.rmdir()
                    except OSError:
                        pass

    def setUp(self):
        LB._boards.pop(self.uid, None)

    def _png(self, w=64, h=48):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (w, h), (20, 60, 50)).save(buf, format="PNG")
        return buf.getvalue()

    def _post(self, path, body):
        return self.client.post(path, json=body, headers=self.h).get_json()

    def _post2(self, h, path, body):
        return self.client.post(path, json=body, headers=h).get_json()

    def _new_plot(self, title):
        return LB._write_focus_card(self.uid, "plot", title,
                                    data={"plot_type": "function"})

    # ---- 字幕上报 ----
    def test_speech_visible_in_state(self):
        j = self._post("/api/board/speech", {"role": "teacher", "text": "先看这条曲线"})
        self.assertTrue(j["success"])
        self.assertEqual(j["data"]["id"], 1)
        st = self.client.get("/api/board/state", headers=self.h).get_json()["data"]
        self.assertEqual(len(st["speech"]), 1)
        self.assertEqual(st["speech"][0]["text"], "先看这条曲线")
        self.assertEqual(st["speech"][0]["role"], "teacher")

    def test_speech_guards(self):
        self.assertFalse(self._post("/api/board/speech", {"role": "ghost", "text": "x"})["success"])
        self.assertFalse(self._post("/api/board/speech", {"role": "teacher", "text": "  "})["success"])
        self.assertFalse(self._post("/api/board/speech", {"role": "teacher", "text": "\u0000\u0001"})["success"])
        long_text = "句" * 260
        j = self._post("/api/board/speech", {"role": "teacher", "text": long_text})
        self.assertTrue(j["success"])
        self.assertEqual(len(j["data"]["text"]), LB._SPEECH_TEXT_MAX + 1)   # 截断 + …
        self.assertTrue(j["data"]["text"].endswith("…"))

    def test_speech_works_before_first_plot(self):
        # 有意偏离计划：不硬拦「必须上课中」——EXE 只在课中上报，服务端拦不到也无害
        self.assertTrue(self._post("/api/board/speech",
                                   {"role": "student", "text": "老师这一步没听懂"})["success"])
        self.assertIsNone(LB.get_lesson_key(self.uid))

    # ---- 图卡闭窗 ----
    def test_plot_window_captions_only_own_speech(self):
        self._new_plot("图一")                       # 课前寒暄不属于任何图
        self._post("/api/board/speech", {"role": "teacher", "text": "这是第一条边"})
        self._post("/api/board/speech", {"role": "student", "text": "我懂了"})
        self._post("/api/board/speech", {"role": "teacher", "text": "斜率在这里是正的"})
        b = LB._boards[self.uid]
        card = [i for i in b["items"] if i["kind"] == "plot"][0]
        self.assertEqual(card["cap_from"], 1)
        self.assertNotIn("caption", card)            # 窗还开着（图仍在板上）
        self.assertEqual(len(b["outbox"]), 0)
        self._new_plot("图二")                        # 新图入板 → 旧图闭窗进出件箱
        self.assertEqual(card["caption"], "这是第一条边，斜率在这里是正的")
        self.assertEqual(card["cap_to"], 3)
        self.assertEqual(b["claim_upto"], 3)
        self.assertEqual(len(b["outbox"]), 1)
        self.assertEqual(b["outbox"][0]["plot_id"], card["id"])
        self.assertTrue(BL.valid_key(b["outbox"][0]["lesson_key"]))
        self.assertEqual(b["items"][-1]["cap_from"], 4)   # 第二张图不重复烧同一句

    def test_caption_flags_dropped_speech(self):
        """字幕缓冲是滚动淘汰的：一段讲解长过缓冲时，讲稿必须明写缺了几句，
        不得把残缺讲稿静默烧进课件图（白盒评审意见 #1）。"""
        self._new_plot("图一")
        for i in range(LB._SPEECH_MAX + 40):
            self.assertIsNotNone(LB.append_speech(self.uid, "teacher", f"第{i + 1}句"))
        self._new_plot("图二")
        cap = [i for i in LB._boards[self.uid]["items"] if i["kind"] == "plot"][0]["caption"]
        self.assertTrue(cap.startswith("［"), cap[:40])
        self.assertIn("已超出字幕缓冲", cap)
        self.assertLessEqual(len(cap), LB._CAPTION_MAX + 1)      # 限长闸仍然生效

    def test_clear_board_archives_open_plot(self):
        self._new_plot("图一")
        self._post("/api/board/speech", {"role": "teacher", "text": "看这里"})
        snap = LB.clear_board(self.uid)
        self.assertEqual(len(snap["items"]), 0)
        self.assertEqual(len(snap["outbox"]), 1)
        self.assertEqual(snap["outbox"][0]["caption"], "看这里")
        self.assertEqual(snap["outbox"][0]["title"], "图一")
        oid = snap["outbox"][0]["oid"]
        self.assertEqual(LB.drop_outbox(self.uid, [oid, oid, 999]), 0)   # 幂等

    def test_lesson_key_rotates_on_new_problem(self):
        self._new_plot("图一")
        self._post("/api/board/speech", {"role": "teacher", "text": "讲完"})
        k1 = LB.get_lesson_key(self.uid)
        BoardSpeechLessonTest.keys.append(k1)
        LB.rotate_lesson(self.uid)
        k2 = LB.get_lesson_key(self.uid)
        self.assertNotEqual(k1, k2)
        self.assertEqual(LB._boards[self.uid]["outbox"][0]["lesson_key"], k1)   # 旧页算上一课

    # ---- 课件入库与导出 ----
    def _archived_key(self):
        k = LB.rotate_lesson(self.uid)
        BoardSpeechLessonTest.keys.append(k)
        j = self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": base64.b64encode(self._png()).decode(),
            "caption": "这条曲线在零点穿过 x 轴", "title": "零点图",
            "plot_json": {"plot_type": "function"}})
        self.assertTrue(j["success"], j.get("error"))
        self.assertEqual(j["data"]["seq"], 1)
        self.assertTrue(j["data"]["image_rel"].startswith(f"课件/{k}/"))
        return k

    def test_slide_image_persisted_and_listed(self):
        k = self._archived_key()
        slides = BL.list_slides(self.uid, k)
        self.assertEqual(len(slides), 1)
        self.assertTrue(slides[0]["has_image"])
        self.assertEqual(slides[0]["caption"], "这条曲线在零点穿过 x 轴")
        j = self.client.get(f"/api/board/lesson?lesson_key={k}", headers=self.h).get_json()
        self.assertTrue(j["success"])
        self.assertEqual(j["data"]["pages"], 1)
        s0 = j["data"]["slides"][0]
        self.assertNotIn("image_path", s0)      # 绝对路径不出服务
        self.assertNotIn("plot_spec", s0)
        self.assertEqual(s0["caption"], "这条曲线在零点穿过 x 轴")
        lessons = self.client.get("/api/board/lessons", headers=self.h).get_json()["data"]["lessons"]
        self.assertIn(k, [x["lesson_key"] for x in lessons])

    def test_slide_dedup_identical_reupload(self):
        """方案 A（k-NN 课事故 2026-11-07）：同一页重复上传（多实例并发下课）
        → 幂等返回已有页号，课件不双页。"""
        k = LB.rotate_lesson(self.uid)
        BoardSpeechLessonTest.keys.append(k)
        body = {"lesson_key": k, "image_b64": base64.b64encode(self._png()).decode(),
                "caption": "投票定多数", "title": "k-NN 分类流程"}
        j1 = self._post("/api/board/slide_image", body)
        self.assertTrue(j1["success"], j1.get("error"))
        self.assertEqual(j1["data"]["seq"], 1)
        self.assertFalse(j1["data"]["deduped"])
        j2 = self._post("/api/board/slide_image", dict(body))   # 第二个实例同内容再传
        self.assertTrue(j2["success"], j2.get("error"))
        self.assertTrue(j2["data"]["deduped"])
        self.assertEqual(j2["data"]["seq"], 1)
        self.assertEqual(len(BL.list_slides(self.uid, k)), 1)

    def test_slide_dedup_not_overreach(self):
        """去重只认「最新一页且标题讲稿全同且图字节同」：讲稿不同→照常存新页。"""
        k = LB.rotate_lesson(self.uid)
        BoardSpeechLessonTest.keys.append(k)
        p1 = base64.b64encode(self._png()).decode()
        self.assertTrue(self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": p1, "caption": "第一页", "title": "t"})["success"])
        j = self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": p1, "caption": "同图不同讲稿", "title": "t"})
        self.assertTrue(j["success"], j.get("error"))
        self.assertFalse(j["data"]["deduped"])
        self.assertEqual(j["data"]["seq"], 2)
        self.assertEqual(len(BL.list_slides(self.uid, k)), 2)

    def test_slide_image_guards(self):
        k = "0123456789abcdef"
        self.assertFalse(self._post("/api/board/slide_image", {
            "lesson_key": "../../etc", "image_b64": base64.b64encode(self._png()).decode()})["success"])
        self.assertFalse(self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": base64.b64encode(b"not a png").decode()})["success"])
        self.assertFalse(self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": "@@@"})["success"])
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (BL._IMG_MAX + 1024)   # 过 PNG 魔数、超体积闸
        self.assertFalse(self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": base64.b64encode(big).decode()})["success"])
        self.assertIsNone(BL.get_course(self.uid, k))   # 非法上传不留课

    def test_slide_image_plot_json_gate(self):
        """plot_json 是浏览器直写 micro_scenes 的字段：超长拒收、非对象不阻断归档
        （白盒评审意见 #2）。"""
        k = LB.rotate_lesson(self.uid)
        BoardSpeechLessonTest.keys.append(k)
        bad = self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": base64.b64encode(self._png()).decode(),
            "plot_json": {"blob": "x" * (BL._PLOT_JSON_MAX + 1000)}})
        self.assertFalse(bad["success"])
        self.assertIn("plot_json", bad.get("error") or "")
        self.assertIsNone(BL.get_course(self.uid, k))            # 拒收的上传不留课
        ok = self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": base64.b64encode(self._png()).decode(),
            "caption": "还能归档", "plot_json": "这不是对象"})
        self.assertTrue(ok["success"], ok.get("error"))
        self.assertIsNone(BL.list_slides(self.uid, k)[0]["plot_spec"])

    def test_export_pdf_and_pptx_downloadable(self):
        k = self._archived_key()
        a = self._post("/api/board/archive", {"lesson_key": k, "title": "极限一课"})
        self.assertTrue(a["success"], a.get("error"))
        self.assertEqual(a["data"]["title"], "极限一课")
        for fmt, ctype in (("pdf", b"%PDF"), ("pptx", b"PK")):
            e = self._post("/api/board/export", {"lesson_key": k, "fmt": fmt})
            self.assertTrue(e["success"], e.get("error"))
            self.assertEqual(e["data"]["pages"], 1)
            r = self.client.get(e["data"]["url"])
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.data.startswith(ctype), fmt)
            if fmt == "pdf":
                self.assertTrue(e["data"]["with_text"])   # simhei 候选命中（本机）
        self.assertFalse(self._post("/api/board/export", {"lesson_key": k, "fmt": "exe"})["success"])

    def test_export_skips_oversize_file_on_disk(self):
        """课件目录里被人撑大的图不进导出链（不然 PDF/PPTX 会把它整张吃进内存）。"""
        k = self._archived_key()
        self.assertTrue(self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": base64.b64encode(self._png(80, 60)).decode(),
            "caption": "第二页正常", "title": "图二"})["success"])
        slides = BL.list_slides(self.uid, k)
        self.assertEqual(len(slides), 2)
        Path(slides[0]["image_path"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (BL._IMG_MAX + 16))
        e = self._post("/api/board/export", {"lesson_key": k, "fmt": "pdf"})
        self.assertTrue(e["success"], e.get("error"))
        self.assertEqual(e["data"]["pages"], 1)               # 撑大的那一页被跳过
        Path(slides[1]["image_path"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (BL._IMG_MAX + 16))
        all_bad = self._post("/api/board/export", {"lesson_key": k, "fmt": "pptx"})
        self.assertFalse(all_bad["success"])
        self.assertIn("已归档的课件图", all_bad.get("error") or "")

    def test_asset_token_guard(self):
        k = self._archived_key()
        sg = self.client.get(f"/api/board/asset/sign?rel=课件/{k}/nope.png", headers=self.h).get_json()
        self.assertFalse(sg["success"])                      # 文件不存在
        j = self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": base64.b64encode(self._png()).decode(),
            "caption": "第二页", "title": "图二"})
        rel = j["data"]["image_rel"]
        sg = self.client.get(f"/api/board/asset/sign?rel={rel}", headers=self.h).get_json()
        self.assertTrue(sg["success"])
        d = sg["data"]
        url = f"/api/board/asset?u={d['u']}&rel={rel}&exp={d['exp']}&t={d['t']}"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url.replace(d["t"], "deadbeef")).status_code, 403)
        self.assertEqual(self.client.get(
            f"/api/board/asset?u={d['u']}&rel={rel}&exp=1&t={d['t']}").status_code, 401)
        # 篡改 rel 必带签名失效（rel 已纳入签名串）：防拿合法 token 换路径
        self.assertEqual(self.client.get(
            f"/api/board/asset?u={self.uid}&rel=课件/{k}/other.png&exp={d['exp']}&t={d['t']}").status_code, 403)

    def test_lesson_isolation_between_users(self):
        k = self._archived_key()
        other = "xzsl2_" + uuid.uuid4().hex[:8]
        self.client.post("/api/auth/register", json={"username": other, "password": "test123456"})
        r = self.client.post("/api/auth/login", json={"username": other, "password": "test123456"})
        tok2 = r.get_json()["data"]["token"]
        h2 = {"Authorization": "Bearer " + tok2}
        seg2 = tok2.split(".")[1]
        uid2 = str(json.loads(base64.urlsafe_b64decode(seg2 + "=" * (-len(seg2) % 4)))["uid"])
        j = self.client.get(f"/api/board/lesson?lesson_key={k}", headers=h2).get_json()
        self.assertTrue(j["success"])
        self.assertEqual(j["data"]["pages"], 0)              # 看不到别人的课件
        self.assertEqual(BL.list_slides(uid2, k), [])
        self.assertEqual(BL.list_lessons(uid2), [])
        self.assertFalse(self._post2(h2, "/api/board/archive", {"lesson_key": k})["success"])


class BoardSpaGuardTest(unittest.TestCase):
    """SPA 重入单实例守卫静态契约（k-NN 课板书重复事故）：黑板脚本必须持
    令牌，poll/paint/语音状态回调/定时器都要验令牌归属，否则重进黑板页新旧实例
    并存、板书双份、下课链双跑。"""
    SRC = (Path(__file__).resolve().parents[1] / "templates" / "pages" /
           "teacher_board.html").read_text(encoding="utf-8")

    def test_boot_guard_markers_present(self):
        for marker in ("window.__tbBoot", "function alive()",
                       "if (!alive()) return;", "boot.timer = timer",
                       "if (!alive()) { clearInterval(timer);"):
            self.assertIn(marker, self.SRC)

    def test_async_continuations_guarded(self):
        """CodeReview Major-1（11-07）：同步入口之外，归档链异步续体（件箱泵/
        截图定时回调/下课链/挂接探测/banner 渲染）也必须验令牌，否则旧实例
        跑完归档链、kill() 抹新实例宿主 → 丢页。"""
        self.assertGreaterEqual(self.SRC.count("if (!alive())"), 10)
        for fn in ("function pumpOutbox()", "function doArchive()",
                   "function renderBanner()", "function checkAssign()"):
            i = self.SRC.index(fn)
            self.assertIn("alive()", self.SRC[i:i + 260], fn)
        self.assertIn("if (!alive()) { try { inst.dispose(); }", self.SRC)


class BoardPrepAdoptTest(unittest.TestCase):
    """备课双入口 + 接课 + 闭窗端点（黑板两段式版式轮 阶段一/阶段四 2026-11-05）。

    只把生成链路的 _run_generation 换成桩（真 LLM 逐页生成已由 test_micro_course_api 覆盖），
    这里验的是黑板侧契约：自写主题建课行、在飞去重不双扣分、接单闸（不属于你/生成中拒）、
    接课后板书页往同一门课同表同页追加、两个 MCP 工具秒回不阻塞。
    真 PG（独立测试用户，测后按 uid 整清），零外网、零真 LLM。"""

    @staticmethod
    def _stub_gen(calls):
        """生成桩：直接收好课并补一页 explain（让 pages>0，接单链走得到底）。"""
        def fake(uid, course_key, kp_row, notes_text, errors_text, weakness_name,
                 error_mode=False):
            calls.append({"uid": uid, "course_key": course_key, "kp_row": tuple(kp_row),
                          "error_mode": error_mode})
            conn = DatabaseManager(str(config.DB_PATH)).get_connection()
            try:
                row = conn.execute("SELECT id FROM micro_courses "
                                   "WHERE course_key = ? AND user_id = ?",
                                   (course_key, uid)).fetchone()
                if not row:
                    return
                title = (kp_row[1] or "新课")[:40]
                conn.execute("INSERT INTO micro_scenes (course_id, seq, scene_type, kp_id, "
                             "title, status, content_json) VALUES (?, 1, 'explain', ?, ?, 'done', '')",
                             (row[0], kp_row[0], title))
                conn.execute("UPDATE micro_courses SET status = 'ready', title = ? WHERE id = ?",
                             (title, row[0]))
                conn.commit()
            finally:
                conn.close()
        return fake

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.user = "xzprep_" + cls.suffix
        cls.client.post("/api/auth/register",
                        json={"username": cls.user, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": cls.user, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        cls.h = {"Authorization": "Bearer " + tok}
        seg = tok.split(".")[1]
        cls.uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        cls.conn = DatabaseManager(str(config.DB_PATH)).get_connection()
        # 备课走真 create 同一积分预检闸：懒建号后发余额（同六期微课测口径）
        cr.get_balance(cls.uid)
        cls.conn.execute("UPDATE user_credits SET balance = 2000 WHERE user_id = ?", (cls.uid,))
        cls.conn.commit()
        cls.gen_calls = []
        cls._orig_gen = RMC._run_generation
        RMC._run_generation = cls._stub_gen(cls.gen_calls)
        cls.keys = []

    @classmethod
    def tearDownClass(cls):
        RMC._run_generation = cls._orig_gen
        for k in cls.keys:
            d = BL._lesson_dir(cls.uid, k)
            if d and d.is_dir():
                for f in d.iterdir():
                    try:
                        f.unlink()
                    except OSError:
                        pass
                try:
                    d.rmdir()
                except OSError:
                    pass
        cls.conn.execute("DELETE FROM micro_scenes WHERE course_id IN "
                         "(SELECT id FROM micro_courses WHERE user_id = ?)", (cls.uid,))
        cls.conn.execute("DELETE FROM micro_courses WHERE user_id = ?", (cls.uid,))
        cls.conn.execute("DELETE FROM knowledge_points WHERE user_id = ?", (cls.uid,))
        cls.conn.execute("DELETE FROM user_credits WHERE user_id = ?", (cls.uid,))
        cls.conn.execute("DELETE FROM users WHERE user_id = ?", (cls.uid,))
        cls.conn.commit()
        cls.conn.close()
        LB._boards.pop(cls.uid, None)

    def setUp(self):
        LB._boards.pop(self.uid, None)

    def _pending(self):
        """把生成桩换成「只登记调用、不动课件库」：课留在 generating，
        验在飞去重/接单闸时免线程竞态，同时仍留下供料链路的证据可断言。"""
        def fake(uid, course_key, kp_row, notes_text, errors_text, weakness_name,
                 error_mode=False):
            BoardPrepAdoptTest.gen_calls.append(
                {"uid": uid, "course_key": course_key, "kp_row": tuple(kp_row),
                 "error_mode": error_mode})
        RMC._run_generation = fake

    def _restore_gen(self):
        RMC._run_generation = BoardPrepAdoptTest._stub_gen(BoardPrepAdoptTest.gen_calls)

    def _gen_call(self, course_key, timeout=8):
        """后台线程才登记，轮询取这一节课的供料记录（同 uid 多课共用一个 calls 列表，按课键取）。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            for c in self.gen_calls:
                if c["course_key"] == course_key:
                    return c
            time.sleep(0.05)
        self.fail(f"备课没把供料交给生成链路：{course_key}")

    def _post(self, path, body):
        return self.client.post(path, json=body, headers=self.h).get_json()

    def _png(self, w=64, h=48):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (w, h), (20, 60, 50)).save(buf, format="PNG")
        return buf.getvalue()

    def _wait_gen(self, key, timeout=8):
        """桩在后台线程里跑：等课程离开 generating（等不到直接判失败，不留挂起）。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            c = BL.get_course(self.uid, key)
            if c and c["status"] != "generating":
                return c
            time.sleep(0.05)
        self.fail(f"备课生成没收尾：{key}")

    def _course_ref(self, key):
        row = self.conn.execute("SELECT source_type, status, title, source_ref "
                                "FROM micro_courses WHERE course_key = ?", (key,)).fetchone()
        return row

    # ---- 闭窗端点（下课第一步：只闭窗不收课）----
    def test_close_caption_closes_window_without_archiving(self):
        LB._write_focus_card(self.uid, "plot", "图一", data={"plot_type": "function"})
        self._post("/api/board/speech", {"role": "teacher", "text": "这张图讲斜率"})
        j = self._post("/api/board/close_caption", {})
        self.assertTrue(j["success"], j.get("error"))
        ob = j["data"]["outbox"]
        self.assertEqual(len(ob), 1)
        self.assertEqual(ob[0]["caption"], "这张图讲斜率")
        self.assertEqual(ob[0]["title"], "图一")
        self.assertIsNone(BL.get_course(self.uid, j["data"]["lesson_key"]))   # 只闭窗不收课
        # 再闭一次：已无挂窗的图，出件箱不增长（幂等）
        self.assertEqual(len(self._post("/api/board/close_caption", {})["data"]["outbox"]), 1)

    # ---- 自写主题备课（黑板页按钮入口）----
    def test_prep_endpoint_creates_prep_course(self):
        topic = "函数 sin x / x 的极限与夹逼"
        self._pending()
        try:
            j = self._post("/api/board/prep", {"topic": topic,
                                               "subject": "测试学科P" + self.suffix})
        finally:
            self._restore_gen()
        self.assertTrue(j["success"], j.get("error"))
        d = j["data"]
        self.assertEqual(d["track"], "prep")
        self.assertTrue(BL.valid_key(d["course_key"]))
        BoardPrepAdoptTest.keys.append(d["course_key"])
        row = self._course_ref(d["course_key"])
        self.assertEqual(row[0], "prep")
        self.assertEqual(row[1], "generating")          # 秒回时还在后台生成，不阻塞请求
        self.assertEqual(json.loads(row[3])["topic"], topic)
        self.assertIsNone(json.loads(row[3]).get("anchor_kp_id"))   # 无锚轨不伪挂知识点
        # 自写主题供料给大纲链：合成锚行（id=None，point_name=主题）——与六期独立错题同一先例
        call = self._gen_call(d["course_key"])
        self.assertEqual(call["kp_row"][1], topic)
        self.assertIsNone(call["kp_row"][0])
        self.assertFalse(call["error_mode"])

    def test_prep_guards_and_inflight_dedupe(self):
        self.assertFalse(self._post("/api/board/prep", {"topic": "  "})["success"])
        self.assertFalse(self._post("/api/board/prep", {})["success"])
        topic = "向量组的线性相关性"
        self._pending()
        try:
            j1 = self._post("/api/board/prep", {"topic": topic})
            j2 = self._post("/api/board/prep", {"topic": topic})
        finally:
            self._restore_gen()
        self.assertTrue(j1["success"], j1.get("error"))
        k = j1["data"]["course_key"]
        BoardPrepAdoptTest.keys.append(k)
        self.assertTrue(j2["success"], j2.get("error"))
        self.assertTrue(j2["data"].get("reused"))
        self.assertEqual(j2["data"]["course_key"], k)   # 同主题不双开双扣分
        # 只数「这个主题」的在飞行：同 uid 其它用例各备各的主题，不该串到这里
        n = self.conn.execute("SELECT COUNT(1) FROM micro_courses WHERE user_id = ? "
                              "AND source_type = 'prep' "
                              "AND (source_ref)::jsonb ->> 'topic_token' = ?",
                              (self.uid, RMC._prep_token(topic))).fetchone()[0]
        self.assertEqual(int(n), 1)

    def test_prep_hits_existing_knowledge_point(self):
        name = "数列极限定义复习"
        cur = self.conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
            "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (self.uid, "测试学科P" + self.suffix, name, "ε-N 语言", 55))
        kp = cur.fetchone()[0]
        self.conn.commit()
        self._pending()
        try:
            j = self._post("/api/board/prep", {"topic": name})
        finally:
            self._restore_gen()
        self.assertTrue(j["success"], j.get("error"))
        self.assertEqual(j["data"]["track"], "kp")      # 命中已有知识点 → 标 kp 轨（带笔记/错题素材）
        BoardPrepAdoptTest.keys.append(j["data"]["course_key"])
        ref = json.loads(self._course_ref(j["data"]["course_key"])[3])
        self.assertEqual(ref["anchor_kp_id"], kp)

    # ---- 接课（adopt）----
    def test_adopt_guards(self):
        self.assertFalse(self._post("/api/board/adopt", {"lesson_key": "zzzz" * 4})["success"])
        self.assertFalse(self._post("/api/board/adopt", {"lesson_key": "0" * 16})["success"])
        self._pending()
        try:
            j = self._post("/api/board/prep", {"topic": "还在生成中的那节课"})
        finally:
            self._restore_gen()
        k = j["data"]["course_key"]
        BoardPrepAdoptTest.keys.append(k)
        a = self._post("/api/board/adopt", {"lesson_key": k})
        self.assertFalse(a["success"])                    # 生成中接单会与逐页插页撞页序
        self.assertIn("生成中", a["error"])
        self.assertIsNone(LB.get_lesson_key(self.uid))
        # 别人的课接不上（user_id 双条件隔隔）
        other = "xzprep2_" + self.suffix
        self.client.post("/api/auth/register", json={"username": other, "password": "test123456"})
        r2 = self.client.post("/api/auth/login", json={"username": other, "password": "test123456"})
        seg2 = r2.get_json()["data"]["token"].split(".")[1]
        uid2 = str(json.loads(base64.urlsafe_b64decode(seg2 + "=" * (-len(seg2) % 4)))["uid"])
        k2 = uuid.uuid4().hex[:16]
        self.conn.execute("INSERT INTO micro_courses (course_key, user_id, subject_name, title, "
                          "source_type, source_ref, status) VALUES (?, ?, '测试学科', '别人的课', "
                          "'prep', '{}', 'ready')", (k2, uid2))
        self.conn.commit()
        b = self._post("/api/board/adopt", {"lesson_key": k2})
        self.assertFalse(b["success"])
        self.assertIn("没找到", b["error"])
        self.conn.execute("DELETE FROM micro_courses WHERE user_id = ?", (uid2,))
        self.conn.execute("DELETE FROM users WHERE user_id = ?", (uid2,))
        self.conn.commit()

    def test_adopt_appends_board_pages_to_prepared_course(self):
        j = self._post("/api/board/prep", {"topic": "泰勒展开的余项估计"})
        self.assertTrue(j["success"], j.get("error"))
        k = j["data"]["course_key"]
        BoardPrepAdoptTest.keys.append(k)
        c = self._wait_gen(k)
        self.assertEqual(c["status"], "ready")
        self.assertEqual(BL.list_slides(self.uid, k), [])   # 备课页不是 board 页
        a = self._post("/api/board/adopt", {"lesson_key": k})
        self.assertTrue(a["success"], a.get("error"))
        self.assertEqual(a["data"]["lesson_key"], k)
        self.assertEqual(LB.get_lesson_key(self.uid), k)
        s = self._post("/api/board/slide_image", {
            "lesson_key": k, "image_b64": base64.b64encode(self._png()).decode(),
            "caption": "余项这样估", "title": "余项图", "plot_json": {"plot_type": "function"}})
        self.assertTrue(s["success"], s.get("error"))
        self.assertEqual(s["data"]["seq"], 2)               # 同表同页：接在备课页后面
        slides = BL.list_slides(self.uid, k)
        self.assertEqual(len(slides), 1)
        self.assertEqual(slides[0]["caption"], "余项这样估")
        self.assertTrue(self._post("/api/board/archive",
                                   {"lesson_key": k, "title": "泰勒一课"})["success"])
        e = self._post("/api/board/export", {"lesson_key": k, "fmt": "pdf"})
        self.assertTrue(e["success"], e.get("error"))       # 导出与浏览天然共用
        self.assertEqual(self.client.get(e["data"]["url"]).status_code, 200)

    # ---- 语音备课双工具 ----
    def test_lesson_prepare_tool_returns_fast_and_dedupes(self):
        topic = "夹逼准则怎么用"
        self._pending()
        try:
            t0 = time.time()
            text = LB.execute_tool("lesson_prepare", {"topic": topic}, self.uid)
            spent = time.time() - t0
            text2 = LB.execute_tool("lesson_prepare", {"topic": topic}, self.uid)
            empty = LB.execute_tool("lesson_prepare", {"topic": "  "}, self.uid)
        finally:
            self._restore_gen()
        self.assertIn("已后台开工备课", text)
        self.assertIn("[在备课件]", text)                # 三层：确认句 + 清单状态行 + 导演指令
        self.assertLess(spent, 5)                        # 秒回：生成全在后台线程
        self.assertIn("已经在备课中", text2)             # 重复开工拒收
        self.assertIn("备课要说清主题", empty)

    def test_lesson_list_preps_lists_and_adopts(self):
        j = self._post("/api/board/prep", {"topic": "特征值的几何意义"})
        k = j["data"]["course_key"]
        BoardPrepAdoptTest.keys.append(k)
        self._wait_gen(k)
        text = LB.execute_tool("lesson_list_preps", {}, self.uid)
        self.assertIn("[已备好的课]", text)
        self.assertIn(k[:8], text)                       # 课号前 8 位可引用
        text2 = LB.execute_tool("lesson_list_preps", {"lesson_key": k}, self.uid)
        self.assertIn("已接上", text2)
        self.assertEqual(LB.get_lesson_key(self.uid), k)
        self.assertIn("已经在用", LB.execute_tool("lesson_list_preps", {"title": "特征值"}, self.uid))
        # 生成中的课列得出、但接不上（同 /api/board/adopt 闸门口径）
        self._pending()
        try:
            g = self._post("/api/board/prep", {"topic": "二次型的标准化"})
        finally:
            self._restore_gen()
        BoardPrepAdoptTest.keys.append(g["data"]["course_key"])
        out = LB.execute_tool("lesson_list_preps", {"lesson_key": g["data"]["course_key"]}, self.uid)
        self.assertIn("接不上", out)
        self.assertEqual(LB.get_lesson_key(self.uid), k)  # 没被误接走


class AiTeachAssignTest(unittest.TestCase):
    """v0.2.8「AI老师讲」多入口指派（无桥直测）：指派生命周期（内存面）、
    POST/GET /api/board/assign（真 PG + 鉴权 + 归属校验）、get_lesson_material
    一次性指导语注入、kp_teach_pack 素材面、get_error_id_for_record 判分回查分支。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.uidA, cls.tokA = cls._register("v28A_" + cls.suffix)
        cls.uidB, cls.tokB = cls._register("v28B_" + cls.suffix)
        cls.hA = {"Authorization": "Bearer " + cls.tokA}
        cls.hB = {"Authorization": "Bearer " + cls.tokB}
        db = DatabaseManager(str(config.DB_PATH))
        cls.conn = db.get_connection()
        cur = cls.conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
            "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (cls.uidA, "测试学科V28" + cls.suffix, "极限", "数列极限定义", 40))
        cls.kp = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
            "question_content, user_answer, is_correct, options_json) "
            "VALUES (?, ?, ?, ?, ?, 0, ?) RETURNING id",
            (cls.uidA, "测试学科V28" + cls.suffix, cls.kp,
             "lim(n→∞) (1+1/n)^n = ? A.1 B.e C.∞ D.0", "A",
             json.dumps(["1", "e", "∞", "0"], ensure_ascii=False)))
        cls.pr = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
            "practice_record_id, current_proficiency, correct_answer, explanation) "
            "VALUES (?, ?, ?, ?, 20, 'B', '重要极限 (1+1/n)^n→e') RETURNING id",
            (cls.uidA, "测试学科V28" + cls.suffix, cls.kp, cls.pr))
        cls.err = cur.fetchone()[0]
        cls.conn.commit()
        cls.pm = PracticeRecordManager(db)

    @classmethod
    def tearDownClass(cls):
        for uid in (cls.uidA, cls.uidB):
            cls.conn.execute("DELETE FROM error_questions WHERE user_id = ?", (uid,))
            cls.conn.execute("DELETE FROM practice_records WHERE user_id = ?", (uid,))
            cls.conn.execute("DELETE FROM knowledge_points WHERE user_id = ?", (uid,))
        cls.conn.execute("DELETE FROM users WHERE user_id IN (?, ?)",
                         (cls.uidA, cls.uidB))
        cls.conn.commit()
        cls.conn.close()

    @classmethod
    def _register(cls, username):
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        return uid, tok

    def _reset(self):
        with LB._lock:
            LB._board(self.uidA)["assign"] = None

    def tearDown(self):
        self._reset()

    # ---------------- 生命周期（纯内存，随机 uid 隔离）
    def test_a01_set_get_not_consuming_and_overwrite(self):
        u = "v28mem_" + uuid.uuid4().hex[:8]
        LB.set_assign(u, "error", 7, "题干甲")
        a1 = LB.get_assign(u)
        a2 = LB.get_assign(u)          # get 不消费：读两次都在
        self.assertEqual(a1, a2)
        self.assertEqual(a1["kind"], "error")
        self.assertEqual(a1["id"], 7)
        self.assertEqual(a1["label"], "题干甲")
        LB.set_assign(u, "kp", 9, "知识点乙")   # 重复指派覆写（学生改口）
        a3 = LB.get_assign(u)
        self.assertEqual((a3["kind"], a3["id"]), ("kp", 9))

    def test_a02_take_consumes_once(self):
        u = "v28mem_" + uuid.uuid4().hex[:8]
        LB.set_assign(u, "error", 7, "x")
        self.assertIsNotNone(LB._take_assign(u))
        self.assertIsNone(LB._take_assign(u))    # 取到即清
        self.assertIsNone(LB.get_assign(u))

    def test_a02b_drop_assign_ts_accounting(self):
        # 评审 Minor-2：条件消费按 ts 认账——覆写后的新指派不被旧 ts 的 drop 误伤
        u = "v28mem_" + uuid.uuid4().hex[:8]
        a1 = LB.set_assign(u, "error", 7, "旧")
        time.sleep(0.003)  # ts=毫秒墙钟：满量同毫秒跑会让 a1==a2，断言前提消失（flaky）
        a2 = LB.set_assign(u, "kp", 9, "新")     # 学生改口覆写
        LB._drop_assign(u, a1)                   # 旧 ts 不清
        self.assertEqual(LB.get_assign(u)["id"], 9)
        LB._drop_assign(u, a2)                   # 现 ts 清得掉
        self.assertIsNone(LB.get_assign(u))
        LB._drop_assign(u, a2)                   # 幂等不炸

    def test_a03_ttl_expiry(self):
        u = "v28mem_" + uuid.uuid4().hex[:8]
        LB.set_assign(u, "error", 7, "x")
        with LB._lock:
            LB._board(u)["assign"]["ts"] -= (LB._ASSIGN_TTL_S + 5) * 1000
        self.assertIsNone(LB.get_assign(u))      # 过期即清，学生没真上课静默作废

    def test_a04_clear_board_keeps_assign(self):
        """契约反转（中位线定理误杀事故 2026-11-07，用户裁定 A）：擦板只整理
        板面内容，不清指派——常见流「点指派开新课→先擦旧板书→请老师上课」，
        旧语义擦板连带作废刚下发的指派，老师取料落回错题清单。指派只被
        取料消费/TTL 过期/新指派覆写终结。"""
        u = "v28mem_" + uuid.uuid4().hex[:8]
        LB.set_assign(u, "error", 7, "x")
        LB.clear_board(u)                         # 擦板不再弃指派
        a = LB.get_assign(u)
        self.assertIsNotNone(a)
        self.assertEqual(a["id"], 7)

    def test_a04b_assign_take_logged(self):
        """取料消费留痕：有指派时 assign_take 落 injected/miss，排查不再靠反推。"""
        from unittest import mock
        u = "v28mem_" + uuid.uuid4().hex[:8]
        LB.set_assign(u, "error", 7, "题干短标")
        with mock.patch.object(LB.log, "log") as m:
            LB.execute_tool("get_lesson_material", {}, u)   # error 型恒注入
        ev = [c.args for c in m.call_args_list
              if len(c.args) >= 3 and c.args[0] == "xz_board" and c.args[1] == "assign_take"]
        self.assertEqual([e[2] for e in ev], ["injected"])
        self.assertEqual(ev[0][3]["kind"], "error")
        self.assertIsNone(LB.get_assign(u))                 # 注入成功即消费

    def test_a04c_assign_take_miss_logged(self):
        """kp 素材落空（不存在/非本人）：留痕 miss 且不清指派（条件消费不变）。"""
        from unittest import mock
        u = "v28mem_" + uuid.uuid4().hex[:8]
        LB.set_assign(u, "kp", 999999, "不存在知识点")
        with mock.patch.object(LB.log, "log") as m:
            LB.execute_tool("get_lesson_material", {}, u)
        ev = [c.args for c in m.call_args_list
              if len(c.args) >= 3 and c.args[0] == "xz_board" and c.args[1] == "assign_take"]
        self.assertEqual([e[2] for e in ev], ["miss"])
        self.assertIsNotNone(LB.get_assign(u))    # miss 不消费，留待重试/TTL 兑底

    # ---------------- HTTP 指派端点（真 PG + 鉴权 + 归属）
    def test_a05_post_error_ok_and_label_gate(self):
        self._reset()
        r = self.client.post("/api/board/assign",
                             json={"kind": "error", "error_id": self.err},
                             headers=self.hA)
        j = r.get_json()
        self.assertTrue(j["success"], j.get("error"))
        self.assertEqual(j["data"]["kind"], "error")
        self.assertLessEqual(len(j["data"]["label"]), 25)   # 24 限长 + 省略号
        a = LB.get_assign(self.uidA)
        self.assertEqual(a["id"], self.err)

    def test_a06_post_kp_ok(self):
        self._reset()
        r = self.client.post("/api/board/assign",
                             json={"kind": "kp", "kp_id": self.kp},
                             headers=self.hA)
        j = r.get_json()
        self.assertTrue(j["success"], j.get("error"))
        self.assertEqual(j["data"]["kind"], "kp")
        self.assertEqual(j["data"]["label"], "极限")

    def test_a07_post_rejections(self):
        self._reset()
        j = self.client.post("/api/board/assign",
                             json={"kind": "error", "error_id": "abc"},
                             headers=self.hA).get_json()
        self.assertFalse(j["success"])
        j = self.client.post("/api/board/assign",
                             json={"kind": "error", "error_id": 99999999},
                             headers=self.hA).get_json()
        self.assertFalse(j["success"])
        self.assertIn("没找到", j["error"])
        j = self.client.post("/api/board/assign",   # B 指派 A 的错题：归属拒止
                             json={"kind": "error", "error_id": self.err},
                             headers=self.hB).get_json()
        self.assertFalse(j["success"])
        j = self.client.post("/api/board/assign",
                             json={"kind": "video", "error_id": self.err},
                             headers=self.hA).get_json()
        self.assertFalse(j["success"])
        self.assertIn("kind", j["error"])
        self.assertIsNone(LB.get_assign(self.uidA))  # 拒收不落指派

    def test_a08_get_endpoint_and_auth(self):
        r = self.client.get("/api/board/assign", headers=self.hA)
        self.assertIsNone(r.get_json()["data"]["assign"])   # 无指派回 None
        self._reset()
        self.client.post("/api/board/assign",
                         json={"kind": "error", "error_id": self.err},
                         headers=self.hA)
        d = self.client.get("/api/board/assign", headers=self.hA).get_json()["data"]
        self.assertEqual(d["assign"]["id"], self.err)       # get 不消费
        d2 = self.client.get("/api/board/assign", headers=self.hA).get_json()["data"]
        self.assertEqual(d2["assign"]["id"], self.err)
        r401 = self.client.get("/api/board/assign")          # 未鉴权 401
        self.assertEqual(r401.status_code, 401)

    # ---------------- 取料注入（一次性指导语）
    def test_a09_error_assign_injects_then_gone(self):
        self._reset()
        self.client.post("/api/board/assign",
                         json={"kind": "error", "error_id": self.err},
                         headers=self.hA)
        text = LB.execute_tool("get_lesson_material", {}, self.uidA)
        self.assertTrue(text.startswith("📌网页指定讲解"), text[:60])
        self.assertIn(f"board_show_problem(error_id={self.err})", text)
        self.assertIn("最近错题清单", text)                  # 清单照常带上（兜底口径）
        text2 = LB.execute_tool("get_lesson_material", {}, self.uidA)
        self.assertNotIn("📌", text2)                        # 消费后不再注入

    def test_a10_kp_assign_injects_pack_material(self):
        self._reset()
        self.client.post("/api/board/assign",
                         json={"kind": "kp", "kp_id": self.kp}, headers=self.hA)
        # 带 error_id 取料的分支同样要盖到（两分支都注入）；
        # 评审 Minor-2：kp 命中路径同步锁 assign_take/injected 留痕（与 a04b 同形）
        from unittest import mock
        with mock.patch.object(LB.log, "log") as m:
            text = LB.execute_tool("get_lesson_material",
                                   {"error_id": str(self.err)}, self.uidA)
        ev = [c.args for c in m.call_args_list
              if len(c.args) >= 3 and c.args[0] == "xz_board"
              and c.args[1] == "assign_take"]
        self.assertEqual([e[2] for e in ev], ["injected"])
        self.assertEqual((ev[0][3]["kind"], ev[0][3]["id"]), ("kp", self.kp))
        self.assertTrue(text.startswith("📌网页指定讲解"), text[:60])
        self.assertIn("极限", text)
        self.assertIn("数列极限定义", text)
        self.assertIn("40%", text)                            # 掌握度
        self.assertIn(f"错题id {self.err}", text)             # 名下错题素材
        text2 = LB.execute_tool("get_lesson_material", {}, self.uidA)
        self.assertNotIn("📌", text2)

    def test_a11_kp_deleted_directive_falls_empty(self):
        # 指派后知识点被删：指导语落空返空串，绝不把老师往不存在的内容上引；
        # 评审 Minor-2 新语义：kp 落空不消费指派（留待 TTL 作废），错题照常重取也不注入
        cur = self.conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
            "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (self.uidA, "测试学科V28" + self.suffix, "临时点", "将被删除", 10))
        ghost = cur.fetchone()[0]
        self.conn.commit()
        self._reset()
        j = self.client.post("/api/board/assign",
                             json={"kind": "kp", "kp_id": ghost},
                             headers=self.hA).get_json()
        self.assertTrue(j["success"], j.get("error"))
        self.conn.execute("DELETE FROM knowledge_points WHERE id = ?", (ghost,))
        self.conn.commit()
        text = LB.execute_tool("get_lesson_material", {}, self.uidA)
        self.assertNotIn("📌", text)
        self.assertIsNotNone(LB.get_assign(self.uidA))   # 未消费：瞬抖不误吞
        text2 = LB.execute_tool("get_lesson_material", {}, self.uidA)
        self.assertNotIn("📌", text2)                     # 重试仍落空，指派仍在
        self.assertIsNotNone(LB.get_assign(self.uidA))

    def test_a11b_kp_pack_transient_error_retries_then_consumes(self):
        # 评审 Minor-2：kp 素材瞬抖（DB 异常）→ 不注入不消费；恢复后重试→注入且消费
        import routes_micro_course as rmc
        self._reset()
        j = self.client.post("/api/board/assign",
                             json={"kind": "kp", "kp_id": self.kp},
                             headers=self.hA).get_json()
        self.assertTrue(j["success"], j.get("error"))
        orig = rmc.kp_teach_pack
        calls = {"n": 0}

        def flaky(uid, kpid):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db hiccup")   # 首次瞬抖
            return orig(uid, kpid)
        rmc.kp_teach_pack = flaky
        try:
            t1 = LB.execute_tool("get_lesson_material", {}, self.uidA)
            self.assertNotIn("📌", t1)                   # 瞬抖：无指导语
            self.assertIsNotNone(LB.get_assign(self.uidA))  # 指派幸存
            t2 = LB.execute_tool("get_lesson_material", {}, self.uidA)
            self.assertIn("📌网页指定讲解", t2)          # 恢复：重试成功
            self.assertIn("极限", t2)
        finally:
            rmc.kp_teach_pack = orig
        self.assertIsNone(LB.get_assign(self.uidA))      # 注入成功后才消费

    # ---------------- kp_teach_pack 素材面
    def test_a12_kp_teach_pack_own_and_foreign(self):
        from routes_micro_course import kp_teach_pack
        pack = kp_teach_pack(self.uidA, self.kp)
        self.assertEqual(pack["name"], "极限")
        self.assertEqual(pack["desc"], "数列极限定义")
        self.assertEqual(pack["mastery"], 40)
        self.assertIn(self.err, [e[0] for e in pack["errors"]])
        self.assertIsNone(kp_teach_pack(self.uidB, self.kp))    # 非本人
        self.assertIsNone(kp_teach_pack(self.uidA, 99999999))   # 不存在

    # ---------------- 判分回查（manager 级三分支 + 空）
    def test_b01_error_id_lookup_four_branches(self):
        subj = "测试学科V28" + self.suffix
        # ① 新题干答错入池：新行靠 practice_record_id 关联
        q1 = "v28独有题干 " + uuid.uuid4().hex[:8]
        rec1 = self.pm.save_practice_record(subj, self.kp, q1, "A", False,
                                           user_id=self.uidA, correct_answer="B")
        eid1 = self.pm.get_error_id_for_record(rec1, self.uidA)
        self.assertIsNotNone(eid1)
        # ② 同题干堆行：不新建，流水挂原行 → 回查走 error_question_id 兜底
        rec2 = self.pm.save_practice_record(subj, self.kp, q1, "C", False,
                                            user_id=self.uidA, correct_answer="B")
        self.assertEqual(self.pm.get_error_id_for_record(rec2, self.uidA), eid1)
        # ③ 举一反三派生题（新题干 + 流水挂 root）：回查取新行而非 root
        q3 = "v28派生题干 " + uuid.uuid4().hex[:8]
        rec3 = self.pm.save_practice_record(subj, self.kp, q3, "A", False,
                                            user_id=self.uidA, correct_answer="B",
                                            error_question_id=eid1,
                                            pool_new_on_wrong=True)
        eid3 = self.pm.get_error_id_for_record(rec3, self.uidA)
        self.assertIsNotNone(eid3)
        self.assertNotEqual(eid3, eid1)
        # ④ 答对不入池且无挂接：回查 None
        rec4 = self.pm.save_practice_record(subj, self.kp,
                                            "v28答对题干 " + uuid.uuid4().hex[:8],
                                            "B", True, user_id=self.uidA)
        self.assertIsNone(self.pm.get_error_id_for_record(rec4, self.uidA))
        # ⑤ 查不存在的流水：None
        self.assertIsNone(self.pm.get_error_id_for_record(99999999, self.uidA))


class SecondaryInstanceFuseTest(unittest.TestCase):
    """v0.2.8 八期出件轮：app.py 单实例熔断。
    僵尸第二实例会自起小智桥分流工具调用（串板事故根因），
    端口被占时必须拒绝启动：退出码 2，不建桥不进 create_app。"""

    def test_f21_exit_when_port_busy(self):
        import os as _os
        import socket as _sock
        import subprocess
        srv = _sock.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            env = dict(_os.environ, SERVER_PORT=str(port))
            p = subprocess.run([sys.executable, "app.py"],
                               cwd=str(Path(__file__).resolve().parents[1]),
                               env=env, capture_output=True, text=True,
                               timeout=180, encoding="utf-8", errors="replace")
            self.assertEqual(p.returncode, 2,
                             "端口被占时第二实例应退出码 2，实际 %s\n%s" %
                             (p.returncode, (p.stderr or "")[-400:]))
        finally:
            srv.close()

    def test_f22_probe_logic_busy_and_free(self):
        """探活口径同熔断：connect_ex==0 才算忙；无人监听/已退出都不误拦。"""
        import socket as _sock

        def busy(p):
            s = _sock.socket()
            s.settimeout(1)
            try:
                return s.connect_ex(("127.0.0.1", p)) == 0
            finally:
                s.close()
        srv = _sock.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        self.assertTrue(busy(port))          # 有人在听 → 熔断
        srv.close()
        self.assertFalse(busy(port))         # 监听者退出 → 不拦正主


class DrawLogTrailTest(unittest.TestCase):
    """八期降维课复盘：13 连发 board_draw 只 1 张上板，拒收在日志里全无痕迹。
    口径：draw/draw_reject 都必须进 debug_trace，且带 spec「收据」摘要
    （类型/元素条数/序列化长度）与拒收原因，事后排查可印证老师嘴里的图。"""

    def setUp(self):
        self.uid = "v28trail_" + uuid.uuid4().hex[:8]

    def _draw_events(self, name, args):
        from unittest import mock
        with mock.patch.object(LB.log, "log") as m:
            LB.execute_tool(name, args, self.uid)
        return [c.args for c in m.call_args_list
                if len(c.args) >= 3 and c.args[0] == "xz_board"
                and c.args[1] in ("draw", "draw_reject")]

    def test_reject_leaves_trail_with_reason(self):
        ev = self._draw_events("board_draw", {"spec": {"plot_type": "wiggle"}})
        self.assertEqual([e[1] for e in ev], ["draw_reject"])   # 拒收不再静默
        self.assertEqual(ev[0][2], "error")
        p = ev[0][3]
        self.assertEqual(p["uid"], self.uid)
        self.assertEqual(p["plot_type"], "wiggle")
        self.assertTrue(p["reason"])                             # 指导文案落盘

    def test_success_log_carries_spec_receipt(self):
        ev = self._draw_events("board_draw", {"spec": {
            "plot_type": "numberline", "range": [0, 5],
            "points": [{"v": 1, "label": "A"}, {"v": 3, "label": "B"}]}})
        self.assertEqual([e[1] for e in ev], ["draw"])
        p = ev[0][3]
        self.assertEqual(p["plot_type"], "numberline")
        self.assertEqual(p["elems"]["points"], 2)                # 画了几个点可查
        self.assertGreater(p["json_len"], 0)
        self.assertIn("n_marks", p)

    def test_oversize_spec_reject_records_json_len(self):
        big = {"plot_type": "numberline", "range": [0, 5],
               "points": [{"v": i % 6, "label": "点%d" % i} for i in range(220)]}
        ev = self._draw_events("board_draw", {"spec": big})
        self.assertEqual([e[1] for e in ev], ["draw_reject"])    # 超 4000 字符闸
        self.assertGreater(ev[0][3]["json_len"], 4000)


class ColorChannelTellTest(unittest.TestCase):
    """八期方案 A（降维课复盘）：老师要能「看见」黑板——
    1) spec 可写受控颜色，契约总回写真色（hex+中文名，与 tb_charts.js 渲染同源）；
    2) board_draw 成功回「黑板实况」，颜色/数量以此为准，嘴上说的=屏幕上画的。"""

    def setUp(self):
        self.uid = "v28color_" + uuid.uuid4().hex[:8]

    def _scatter(self, multi=True):
        series = [{"name": "样本点",
                   "points": [{"x": 0, "y": 0, "label": "分类A"}, [1, 1]]}]
        if multi:
            series.append({"name": "落点", "color": "蓝",
                           "points": [{"x": 2, "y": 1, "label": "投影点"}]})
        return {"plot_type": "stats", "shape": "scatter", "series": series}

    def test_scatter_named_color_and_default_order(self):
        ok, res = BP.validate_plot(self._scatter())
        self.assertTrue(ok, res)
        s0, s1 = res["series"]
        self.assertEqual((s0["color"], s0["color_name"]), ("#fcd34d", "黄"))  # 不写=序号色
        self.assertEqual((s1["color"], s1["color_name"]), ("#7dd3fc", "蓝"))  # 写指定用指定

    def test_bad_color_rejected_with_choices(self):
        spec = self._scatter()
        spec["series"][0]["color"] = "霓虹绿"
        ok, res = BP.validate_plot(spec)
        self.assertFalse(ok)
        self.assertIn("霓虹绿", res)
        for n in ("黄", "蓝", "深绿"):                      # 可选清单回得全
            self.assertIn(n, res)

    def test_english_alias_and_green_disambiguation(self):
        spec = self._scatter()
        spec["series"][0]["color"] = "blue"      # 撞名：系列1 也写蓝
        spec["series"][1]["color"] = "深绿"
        ok, res = BP.validate_plot(spec)
        self.assertTrue(ok, res)
        self.assertEqual(res["series"][0]["color"], "#7dd3fc")
        self.assertEqual(res["series"][1]["color"], "#4ade80")
        ok2, pie = BP.validate_plot({"plot_type": "stats", "shape": "pie", "slices": [
            {"label": "优秀", "value": 30, "color": "mint"},
            {"label": "及格", "value": 70}]})
        self.assertTrue(ok2, pie)
        self.assertEqual((pie["slices"][0]["color"], pie["slices"][0]["color_name"]),
                         ("#6ee7b7", "浅绿"))

    def test_bar_series_color_written(self):
        ok, res = BP.validate_plot({"plot_type": "stats", "shape": "bar",
                                    "categories": ["一班", "二班"],
                                    "series": [{"name": "期中考", "values": [80, 90]},
                                               {"name": "期末考", "values": [85, 92]}]})
        self.assertTrue(ok, res)
        self.assertEqual([s["color_name"] for s in res["series"]], ["黄", "蓝"])

    def test_describe_tells_screen_truth(self):
        ok, res = BP.validate_plot(self._scatter())
        self.assertTrue(ok, res)
        d = BP.describe(res)
        self.assertIn("样本点", d)
        self.assertIn("黄", d)
        self.assertIn("落点", d)
        self.assertIn("蓝", d)
        self.assertIn("2 个点", d)
        ok2, g = BP.validate_plot({"plot_type": "geometry",
                                   "points": [{"x": 0, "y": 0, "label": "A"},
                                              {"x": 1, "y": 1, "label": "B"}],
                                   "segments": [{"a": "A", "b": "B"}]})
        self.assertTrue(ok2, g)
        self.assertIn("点2个", BP.describe(g))
        self.assertIn("线段1个", BP.describe(g))

    def test_board_draw_reply_carries_blackboard_live_report(self):
        r = LB.execute_tool("board_draw", {"spec": self._scatter()}, self.uid)
        self.assertIn("黑板实况", r)
        self.assertIn("蓝", r)                       # 老师拿到的是屏幕真色
        self.assertIn("以此为准", r)


class ProblemImageCardTest(unittest.TestCase):
    """题目原图上板（C 方案 2026-11-08 用户裁定：原图打底+老师自由补画）：
    原图提取闸（存在/穿越/外链/上限）、原图卡上板、题干剥死引用、
    board_draw 伪造 image 型安全闸。原图落真实 vault 附件目录，测后清理。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.uid, cls.tok = cls._register("xzimg_" + cls.suffix)
        cls.h = {"Authorization": "Bearer " + cls.tok}
        db = DatabaseManager(str(config.DB_PATH))
        cls.conn = db.get_connection()
        cur = cls.conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
            "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (cls.uid, "测试学科XZM" + cls.suffix, "图形", "正方形内部线", 30))
        cls.kp = cur.fetchone()[0]
        cls.att = Path(config.VAULT_DIR) / str(cls.uid) / "附件"
        cls.att.mkdir(parents=True, exist_ok=True)
        cls._made = []

        def _png(name):
            p = cls.att / name
            p.write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode()[:8])
            cls._made.append(p)
            return "附件/" + name

        cls.rel1, cls.rel2 = _png("mfig1.png"), _png("mfig2.png")
        cls.rel3, cls.rel4 = _png("mfig3.png"), _png("mfig4.png")

        def _raw(p, data):
            p.write_bytes(data)
            cls._made.append(p)

        # 评审 Major-1 修复：坏引用必须排在有效图之前，否则上限 break 后
        # 三道闸（穿越/存在性/后缀）根本没被评估，断言是假绿。
        # 越界图：真实存在但落在本用户 vault root 之外（专门验 parents 闸）
        cls.evil_out_name = "xzimg_outsider_" + cls.suffix + ".png"
        _raw(Path(config.VAULT_DIR) / cls.evil_out_name, b"\x89PNG\r\n\x1a\nout")
        # 存在但非图后缀：专门验白名单闸（不存在的话会被 is_file 顺带挡掉）
        _raw(cls.att / "notimg.txt", b"not an image")
        # 题1：4 个坏引用在前 + 4 张真图在后（验保序+上限 3 截断）
        stem = ("如图，正方形内部有若干线段与阴影。"
                "![图形](../evil.png)"                      # 穿越且不存在
                f"![图形](../{cls.evil_out_name})"           # 存在但越界
                "![图形](附件/notimg.txt)"                   # 存在但非图后缀
                "![图形](附件/missing.png)"                  # 缺失
                "![图形](https://example.com/x.png)"         # 外链（md_image_paths 层拦）
                f"![图形]({cls.rel1}) ![图形]({cls.rel2})"
                f"![图形]({cls.rel3}) ![图形]({cls.rel4})")
        cls.err = cls._err(stem)
        # 题2：无图题（旧行为对照组）
        cls.err_plain = cls._err("lim(n→∞) (1+1/n)^n = ?")

    @classmethod
    def _register(cls, username):
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        return uid, tok

    @classmethod
    def _err(cls, stem):
        cur = cls.conn.execute(
            "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
            "question_content, user_answer, is_correct, options_json) "
            "VALUES (?, ?, ?, ?, ?, 0, ?) RETURNING id",
            (cls.uid, "测试学科XZM" + cls.suffix, cls.kp, stem, "A", "[]"))
        pr = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
            "practice_record_id, current_proficiency, correct_answer, explanation) "
            "VALUES (?, ?, ?, ?, 20, 'B', '一半模型') RETURNING id",
            (cls.uid, "测试学科XZM" + cls.suffix, cls.kp, pr))
        eid = cur.fetchone()[0]
        cls.conn.commit()   # PG 连接池按连接隔离：不提交则服务端另一连接看不到
        return eid

    @classmethod
    def tearDownClass(cls):
        for tbl in ("error_questions", "practice_records", "knowledge_points"):
            cls.conn.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (cls.uid,))
        cls.conn.commit()
        cls.conn.close()
        for p in cls._made:
            try:
                p.unlink()
            except OSError:
                pass
        try:
            cls.att.rmdir()
        except OSError:
            pass
        with LB._lock:
            LB._boards.pop(cls.uid, None)

    def tearDown(self):
        LB.execute_tool("board_clear", {}, self.uid)

    def _items(self):
        # since=-1 强制全量快照（默认 since=0 时空板只回 {changed:false}，无 items）
        st = self.client.get("/api/board/state?since=-1",
                             headers=self.h).get_json()["data"]
        return st["items"]

    def test_pack_images_gate_order_and_cap(self):
        """提取闸：只收真实落在本用户 vault 内的图，保序、上限 3；
        穿越/越界/非图后缀/缺失/外链坏引用全部静默丢弃（坏引用排前，
        确保每道闸都被真实评估，评审 Major-1）。"""
        pack = LB._lesson_pack_text(self.uid, str(self.err))
        self.assertEqual(pack["images"], [self.rel1, self.rel2, self.rel3])
        pack2 = LB._lesson_pack_text(self.uid, str(self.err_plain))
        self.assertEqual(pack2["images"], [])

    def test_show_problem_pushes_image_cards(self):
        """写题即上原图：plot 卡型 image 变体；题干/主干卡剥死引用换成提示。"""
        r = LB.execute_tool("board_show_problem",
                            {"error_id": str(self.err)}, self.uid)
        self.assertIn("原图卡", r)
        self.assertIn("对照原图", r)
        items = self._items()
        imgs = [c for c in items if c["kind"] == "plot"
                and (c.get("data") or {}).get("plot_type") == "image"]
        self.assertEqual([c["data"]["rel"] for c in imgs],
                         [self.rel1, self.rel2, self.rel3])
        self.assertEqual(imgs[0]["text"], "题目原图1")
        prob = [c for c in items if c["kind"] == "problem"][0]
        self.assertNotIn("![", prob["text"])
        self.assertNotIn("evil", prob["text"])
        self.assertNotIn("missing", prob["text"])
        self.assertEqual(prob["text"].count("（原图已上黑板）"), 3)  # 第4张被截断不声称已上板
        self.assertIn("（原图已上黑板）", prob["text"])
        topic = [c for c in items if c["kind"] == "topic"][0]
        self.assertNotIn("![", topic["text"])

    def test_get_material_mentions_image(self):
        """取料面：带图题的指导语预告「原图会自动上屏」，无图题不提。"""
        r = LB.execute_tool("get_lesson_material",
                            {"error_id": str(self.err)}, self.uid)
        self.assertIn("本题带原图", r)
        r2 = LB.execute_tool("get_lesson_material",
                             {"error_id": str(self.err_plain)}, self.uid)
        self.assertNotIn("本题带原图", r2)

    def test_plain_problem_behavior_unchanged(self):
        """无图题零变化：不产生图卡、返回文本不提原图（旧行为对照组）。"""
        r = LB.execute_tool("board_show_problem",
                            {"error_id": str(self.err_plain)}, self.uid)
        self.assertIn("已写上黑板", r)
        self.assertNotIn("原图卡", r)
        items = self._items()
        self.assertEqual([c for c in items if c["kind"] == "plot"], [])

    def test_board_draw_cannot_forge_image(self):
        """安全闸：老师侧 board_draw 绝不接受 plot_type=image（rel 只能由
        服务端校验后生成，防伪造路径让前端去读 vault 任意文件）。"""
        LB.execute_tool("board_draw",
                        {"spec": {"plot_type": "image",
                                  "rel": "../../knowledge_management.db"}},
                        self.uid)
        items = self._items()
        self.assertEqual([c for c in items if c["kind"] == "plot"], [])


class MermaidPlotTest(unittest.TestCase):
    """mermaid 思路图（2026-11-09 用户任务：讲思路/拆原理用 mermaid，题面事实用普通绘图）：
    服务端图型白名单/大小写正字纠偏/危险语法拒收/分步字段拒收 + board_draw 端到端上板。
    渲染引擎是 mermaid-js 官方项目（前端 vendor 10.6.1，strict+纯SVG），
    服务端只保证送进去的 DSL 合法安全；真实出图面在浏览器验收。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.uid, cls.tok = cls._register("xzmm_" + cls.suffix)
        cls.h = {"Authorization": "Bearer " + cls.tok}

    @classmethod
    def _register(cls, username):
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        return uid, tok

    @classmethod
    def tearDownClass(cls):
        with LB._lock:
            LB._boards.pop(cls.uid, None)

    def tearDown(self):
        LB.execute_tool("board_clear", {}, self.uid)

    def _items(self):
        # since=-1 强制全量快照（默认分支空板只回 {changed:false}，无 items）
        st = self.client.get("/api/board/state?since=-1",
                             headers=self.h).get_json()["data"]
        return st["items"]

    def test_mermaid_gate_accept_and_canon(self):
        """合法面：graph/mindmap 接受；sequencediagram 大小写纠成正字，
        不给渲染器甩不透明解析错。"""
        ok, res = BP.validate_plot({"plot_type": "mermaid", "code": "graph TD\n  A-->B"})
        self.assertTrue(ok)
        self.assertEqual(res["plot_type"], "mermaid")
        self.assertEqual(res["diagram"], "graph")
        self.assertEqual(res["lines"], 2)
        ok2, res2 = BP.validate_plot({"plot_type": "mermaid",
                                      "code": "sequencediagram\n  A->>B: hi"})
        self.assertTrue(ok2)
        self.assertTrue(res2["code"].startswith("sequenceDiagram"))
        self.assertEqual(res2["diagram"], "sequenceDiagram")
        ok3, _ = BP.validate_plot({"plot_type": "mermaid",
                                   "code": "mindmap\n  root((摩擦力))\n    方向\n    大小"})
        self.assertTrue(ok3)

    def test_mermaid_gate_rejects(self):
        """拒收面：缺 code/未知图型/click 交互/%%{init} 注入/HTML 脚本/超长行/
        超行数/分步字段——每种坏 spec 都断言命中指定闸口的指导关键字，
        防止落到 validate_plot 兜底 Exception 也算「拒收带指导」的假绿
        （十一轮评审 Major：删闸后断言必须变红才算闸被真正测到）。"""
        bad = [
            ({"plot_type": "mermaid"}, "需要 code"),
            ({"plot_type": "mermaid", "code": "whatevergraph\n A-->B"}, "首行要图型声明"),
            ({"plot_type": "mermaid", "code": "graph TD\n click\tA evil"}, "click/link"),
            ({"plot_type": "mermaid", "code": "graph TD %%{init:{x}}%%\n A-->B"}, "配置注入"),
            ({"plot_type": "mermaid",
              "code": 'graph TD\n A["<script>alert(1)</script>"]'}, "HTML/脚本"),
            ({"plot_type": "mermaid", "code": "graph TD\n" + "".join(
                "  A%d-->B\n" % i for i in range(45))}, "最多 40 行"),
            ({"plot_type": "mermaid", "code": "graph TD\n A-->" + "x" * 300}, "单行太长"),
            ({"plot_type": "mermaid", "code": "graph TD\n A-->B", "step": 2}, "不支持分步"),
        ]
        for spec, kw in bad:
            ok, guide = BP.validate_plot(spec)
            self.assertFalse(ok, spec)
            self.assertIsInstance(guide, str)
            self.assertIn(kw, guide, spec)  # 闸口归因：删该闸即变红
            self.assertNotIn("图形描述有异常", guide, spec)  # 禁走兜底 Exception 通道

    def test_board_draw_mermaid_end_to_end(self):
        """端到端：老师 mermaid spec 经 board_draw 上板成 plot 卡，
        data 透出 plot_type/code 供前端渲染；标题落卡文本。"""
        r = LB.execute_tool("board_draw", {"title": "一半模型思路", "spec": {
            "plot_type": "mermaid",
            "code": "graph TD\n  A[读题] --> B[找条件]\n  B --> C{哪个模型}?\n"
                    "  C -->|一半模型| D[连中点]"}}, self.uid)
        self.assertNotIn("图没画上", r)
        items = self._items()
        mm = [c for c in items if c["kind"] == "plot"
              and (c.get("data") or {}).get("plot_type") == "mermaid"]
        self.assertEqual(len(mm), 1)
        self.assertEqual(mm[0]["text"], "一半模型思路")
        self.assertEqual(mm[0]["data"]["lines"], 4)
        self.assertIn("一半模型", mm[0]["data"]["code"])

    def test_board_draw_mermaid_reject_leaves_no_card(self):
        """拒收零痕迹：非法 mermaid 不产生任何 plot 卡（与画图失败留痕纪律一致：
        拒收有日志、板上无残卡）。"""
        r = LB.execute_tool("board_draw", {"spec": {
            "plot_type": "mermaid", "code": "graph TD\n click A evil"}}, self.uid)
        self.assertIn("图没画上", r)
        self.assertEqual([c for c in self._items() if c["kind"] == "plot"], [])


class AutoFocusLaserTest(unittest.TestCase):
    """旁白驱动激光跟随（2026-11-09 用户裁定方案 B）：老师刚落的一句里命中
    板上〔〕锚文本/图卡 marks 名，焦点自动落到命中对象（靠句尾者赢）；
    学生的话不动、无命中不动（不伪造老师手势）；短词/纯数字不进自动通道。
    前端激光常驻属于浏览器面，本类只拓服务端焦点机器。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.uid, cls.tok = cls._register("xzaf_" + cls.suffix)
        cls.h = {"Authorization": "Bearer " + cls.tok}

    @classmethod
    def _register(cls, username):
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        return uid, tok

    @classmethod
    def tearDownClass(cls):
        with LB._lock:
            LB._boards.pop(cls.uid, None)

    def tearDown(self):
        LB.execute_tool("board_clear", {}, self.uid)

    def _focus(self):
        st = self.client.get("/api/board/state?since=-1",
                             headers=self.h).get_json()["data"]
        return st.get("focus"), st["items"]

    def _say(self, t, role="teacher"):
        self.assertIsNotNone(LB.append_speech(self.uid, role, t))

    def _draw_tri(self):
        # geometry 的 marks 由服务端从点标派生（A/B/C 裸单字，输入写 marks 会被
        # 派生键闸拒收）——自动跟随对单字只认「点A」/「A点」形式
        r = LB.execute_tool("board_draw", {"title": "三角形", "spec": {
            "plot_type": "geometry",
            "points": [{"label": "A", "x": 0, "y": 0},
                       {"label": "B", "x": 4, "y": 0},
                       {"label": "C", "x": 2, "y": 3}],
            "segments": [{"a": "A", "b": "B"}, {"a": "B", "b": "C"}]}}, self.uid)
        self.assertNotIn("图没画上", r)
        plots = [c for c in self._focus()[1] if c["kind"] == "plot"]
        self.assertEqual(len(plots), 1)
        return plots[0]["id"]

    def test_narration_hits_text_anchor(self):
        """旁白命中文本锚：写卡整卡点亮→讲到哪个锚激光就推进到哪个锚。"""
        LB.execute_tool("board_write", {"kind": "note",
                                        "content": "看〔斜率等于2〕和〔中点坐标〕"}, self.uid)
        f, _ = self._focus()
        self.assertIsNotNone(f)
        self.assertIsNone(f["anchor"])          # 写卡即点亮但还没指
        nid = f["item_id"]
        self._say("同学们注意，这里斜率等于2表示什么")
        f = self._focus()[0]
        self.assertEqual((f["item_id"], f["anchor"]), (nid, 1))
        self._say("我们再算一下中点坐标")
        f = self._focus()[0]
        self.assertEqual((f["item_id"], f["anchor"]), (nid, 2))

    def test_narration_hits_plot_mark_tail_wins(self):
        """旁白命中图卡派生 marks：裸单字无「点」形式不进自动通道；
        两个都带「点」形式时靠句尾者赢（十一轮评审 Minor：句子必须真造出
        竞争——迭代序 A先命中、句尾 C 后命中，退化成 first-hit 的实现才必红）。"""
        pid = self._draw_tri()
        self._say("先看A再看B")                 # 裸单字：无命中，焦点仍在图卡未指认
        f = self._focus()[0]
        self.assertEqual(f["item_id"], pid)
        self.assertIsNone(f["mark"])
        self._say("点A是直角顶点，再把线连到点C")  # 点A 句首/点C 句尾，迭代序 A 在先
        f = self._focus()[0]
        self.assertEqual(f["item_id"], pid)
        self.assertEqual(f["mark"], 3)          # 句尾 点C 赢；错选迭代首 A 即红
        self.assertIsNone(f["anchor"])

    def test_student_and_miss_do_not_move_focus(self):
        """学生的话即使命中锚也不动激光；老师的话无命中同样不动——
        自动跟随只是兜底，不伪造老师手势。"""
        LB.execute_tool("board_write", {"kind": "note",
                                        "content": "重点：〔垂径定理〕"}, self.uid)
        nid = self._focus()[0]["item_id"]
        self._say("垂径定理是什么？", role="student")
        f = self._focus()[0]
        self.assertEqual((f["item_id"], f["anchor"]), (nid, None))
        self._say("我们继续看下一题的条件")       # 无命中
        f = self._focus()[0]
        self.assertEqual((f["item_id"], f["anchor"]), (nid, None))

    def test_follow_preserves_reveal_on_same_plot(self):
        """已在台上的图被旁白命中 marks：分步进度 reveal 不得被顶掉；
        三命中句尾决胜（十一轮评审 Minor：句中序 C→A→B，迭代尾=C、
        迭代首=A、句尾=B 三方彼此可证伪，reveal=1 同时断住）。"""
        pid = self._draw_tri()
        LB.execute_tool("board_highlight", {"item_id": pid, "reveal": 1}, self.uid)
        f = self._focus()[0]
        self.assertEqual((f["item_id"], f["reveal"]), (pid, 1))
        self._say("先看点C，再连点A，最后过点B")
        f = self._focus()[0]
        self.assertEqual(f["item_id"], pid)
        self.assertEqual(f["mark"], 2)           # 句尾 点B（派生序第 2 个点）赢
        self.assertEqual(f["reveal"], 1)         # 分步进度保住

    def test_pure_number_anchor_excluded(self):
        """纯数字/标点锚（如〔1/2〕）误命中面大，不进自动通道；
        老师显式 point=N 不受此限（只限自动跟嘴）。"""
        LB.execute_tool("board_write", {"kind": "note", "content": "答案是〔1/2〕"},
                        self.uid)
        nid = self._focus()[0]["item_id"]
        self._say("所以答案是 1/2 没错")
        f = self._focus()[0]
        self.assertEqual((f["item_id"], f["anchor"]), (nid, None))


class LessonContinuityTest(unittest.TestCase):
    """讲课连续性（2026-11-09 实弹事故：老师连写 #5~#9 不讲解直接道别，
    学生求重讲再无反应）三道服务端闸门：
    ① 进度镜 _explain_mirror：连写 ≥2 张卡未开口，每次工具返回拦嘴；
       口径=写卡进队、老师一句口播即清（讲到哪写到到哪永不触发）；
    ② kp 素材课内常驻：指派一次性消费后 lesson_kp 仍在，取料可重放——
       学生说「继续/没听懂」时老师拿得回内容，不再空口道别；
    ③ 状态行带卡正文摘要：老师能「照板重讲」。纯内存部分用随机 uid 隔离。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.uid, cls.tok = cls._register("xzlq_" + cls.suffix)
        cls.db = DatabaseManager(str(config.DB_PATH))
        cls.conn = cls.db.get_connection()
        cur = cls.conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
            "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (cls.uid, "测试学科LQ" + cls.suffix, "梯度下降", "沿梯度反方向更新参数", 30))
        cls.kp = cur.fetchone()[0]
        cls.conn.commit()

    @classmethod
    def _register(cls, username):
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        return uid, tok

    @classmethod
    def tearDownClass(cls):
        cls.conn.execute("DELETE FROM knowledge_points WHERE id = ?", (cls.kp,))
        cls.conn.execute("DELETE FROM users WHERE user_id = ?", (cls.uid,))
        cls.conn.commit()
        cls.conn.close()
        with LB._lock:
            LB._boards.pop(cls.uid, None)

    def setUp(self):
        LB.execute_tool("board_clear", {}, self.uid)

    # ---------------- ① 进度镜（纯内存，独立随机 uid）
    def _mem(self):
        return "xzlqmem_" + uuid.uuid4().hex[:8]

    def test_mirror_fires_on_second_consecutive_card(self):
        u = self._mem()
        t1 = LB.execute_tool("board_write", {"content": "核心思想：沿梯度反方向走"}, u)
        self.assertNotIn("你已连续写了", t1)     # 首张不拦：建卡开口前本来就要写
        t2 = LB.execute_tool("board_write", {"content": "更新公式 θ=θ−α∇J"}, u)
        self.assertIn("你已连续写了 2 张卡", t2)
        self.assertIn("板书不等于讲解", t2)
        LB._boards.pop(u, None)

    def test_speech_clears_mirror_never_interrupts_normal_lecture(self):
        u = self._mem()
        try:
            LB.execute_tool("board_write", {"content": "定义卡一句"}, u)
            LB.append_speech(u, "teacher", "先看这张定义卡")   # 一句口播即算讲过
            t = LB.execute_tool("board_write", {"content": "下一步推演卡"}, u)
            self.assertNotIn("你已连续写了", t)               # 讲到哪写到到哪：不拦
            LB.append_speech(u, "student", "听懂了一点")       # 学生的话不清队列
            LB.execute_tool("board_write", {"content": "第三张"}, u)
            t2 = LB.execute_tool("board_write", {"content": "第四张"}, u)
            self.assertIn("你已连续写了", t2)
        finally:
            LB._boards.pop(u, None)

    def test_mirror_survives_across_other_tools_and_dies_on_clear(self):
        u = self._mem()
        try:
            LB.execute_tool("board_write", {"content": "卡一"}, u)
            LB.execute_tool("board_write", {"content": "卡二"}, u)
            # 其他工具返回也拦得住（镜检挂在 execute_tool 总出口）
            self.assertIn("你已连续写了", LB.execute_tool("board_write", {"content": "卡三"}, u))
            LB.execute_tool("board_clear", {}, u)             # 擦板重开：队列归零
            self.assertNotIn("你已连续写了", LB.execute_tool("board_write", {"content": "新卡"}, u))
        finally:
            LB._boards.pop(u, None)

    def test_replaced_card_leaves_mirror_queue(self):
        # 改写=正在重讲那张卡，不该被镜检当「堆卡不说」误拦
        u = self._mem()
        try:
            LB.execute_tool("board_write", {"content": "易错点：学习率太大跳最优"}, u)
            t = LB.execute_tool("board_write", {"content": "学习率太小收敛慢"}, u)
            self.assertIn("你已连续写了 2 张卡", t)
            cid = [i["id"] for i in LB.get_state(u)["items"]][-1]
            t2 = LB.execute_tool("board_replace",
                                 {"item_id": cid, "content": "换个说法：步子大小要适中"}, u)
            self.assertNotIn("你已连续写了", t2)   # 剩那张仍待讲，但改写卡出队后不足 2 张
        finally:
            LB._boards.pop(u, None)

    # ---------------- ③ 状态行带正文（照板重讲的字源）
    def test_status_line_carries_card_text(self):
        u = self._mem()
        try:
            LB.execute_tool("board_write", {"kind": "topic", "content": "梯度下降"}, u)
            t = LB.execute_tool("board_write", {"content": "核心思想：沿梯度反方向走损失变小"}, u)
            self.assertIn("梯度下降", t)                      # 主干摘要（既有口径）
            self.assertIn("〔核心思想：沿梯度反方", t)        # 子卡正文摘要（新）
        finally:
            LB._boards.pop(u, None)

    # ---------------- ② kp 素材课内常驻（真 DB：knowledge_points）
    def test_kp_material_replayable_after_consumed(self):
        LB.set_assign(self.uid, "kp", self.kp, "梯度下降")
        t1 = LB.execute_tool("get_lesson_material", {}, self.uid)
        self.assertIn("📌网页指定讲解", t1)                # 首次：注入开讲指导
        self.assertIn("讲课纪律：一张卡讲透再写下一张", t1)  # 纪律句随指导语下发
        self.assertNotIn("续讲：本课正在讲", t1)            # 首 call 不叠续讲（十一轮评审：双份指令口吻相反）
        LB._board(self.uid)["assign"] = None                # 模拟已消费后的常态
        LB._drop_assign(self.uid, LB.get_assign(self.uid))
        t2 = LB.execute_tool("get_lesson_material", {}, self.uid)
        self.assertNotIn("📌", t2)                          # 不再重复注入
        self.assertIn("续讲：本课正在讲学生点名的知识点「梯度下降」", t2)
        self.assertIn("沿梯度反方向更新参数", t2)          # 素材正文重放
        self.assertIn("严禁结课道别", t2)

    def test_kp_replay_dropped_when_material_deleted(self):
        LB.set_assign(self.uid, "kp", self.kp, "梯度下降")
        LB.execute_tool("get_lesson_material", {}, self.uid)   # 消费+常驻
        LB._drop_assign(self.uid, None)
        self.conn.execute("DELETE FROM knowledge_points WHERE id = ?", (self.kp,))
        self.conn.commit()
        try:
            t = LB.execute_tool("get_lesson_material", {}, self.uid)
            self.assertNotIn("续讲：本课正在讲", t)         # 素材已删：不把老师往空处引
            self.assertIsNone(LB._board(self.uid).get("lesson_kp"))  # 常驻同步摘除
        finally:
            cur = self.conn.execute(
                "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
                "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (self.uid, "测试学科LQ" + self.suffix, "梯度下降", "沿梯度反方向更新参数", 30))
            self.kp = cur.fetchone()[0]
            self.conn.commit()

    def test_error_assign_overwrites_kp_context(self):
        LB.set_assign(self.uid, "kp", self.kp, "梯度下降")
        LB.execute_tool("get_lesson_material", {}, self.uid)
        LB._drop_assign(self.uid, None)
        self.assertIsNotNone(LB._board(self.uid).get("lesson_kp"))
        LB.set_assign(self.uid, "error", 999999, "新错题题干")   # 错题型恒注入即消费
        LB.execute_tool("get_lesson_material", {}, self.uid)
        self.assertIsNone(LB._board(self.uid).get("lesson_kp"))  # 新课覆盖旧知识点语境
        self.conn.execute("UPDATE knowledge_points SET point_name = ? WHERE id = ?",
                          ("梯度下降", self.kp))
        self.conn.commit()


class MachineBridgeLockTest(unittest.TestCase):
    """本机单桥闸门（2026-11-09 双桥抢接入点致老师不应答事故）：
    已有活桥（心跳新鲜且持有者进程真活着）拒起；心跳陈旧接管；持有者已死立即接管
    （2026-11-10 重启残留锁致桥永久未连事故）；本进程热重启放行；非持有者不得删锁。
    纯文件操作，endpoint 指向必拒端口，不碰任何真云。"""

    def setUp(self):
        self._orig_lock = MB._LOCK_FILE
        self.lock_path = (config.DATA_DIR /
                          f"xz_mcp_bridge.ut_{uuid.uuid4().hex[:8]}.lock")
        MB._LOCK_FILE = self.lock_path
        self._orig_retry = MB.RETRY_S
        MB.RETRY_S = 1                     # 评审 N1：接管类用例里线程要能快速退
        self._orig_thread = MB._thread     # 可能被前序测试类遗留，只断言不新增

    def tearDown(self):
        MB.stop()
        if MB._thread is not None and MB._thread is not self._orig_thread:
            MB._thread.join(timeout=5)
        MB.RETRY_S = self._orig_retry
        MB._thread = self._orig_thread
        MB._LOCK_FILE = self._orig_lock
        try:
            os.remove(self.lock_path)
        except OSError:
            pass

    def _write_lock(self, pid, beat):
        with open(self.lock_path, "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "beat": beat}, f)

    def test_refused_when_other_live_bridge(self):
        """别的活进程占着桥：_spawn 必须拒绝，且不得碰别人的锁。
        pid 必须是真活着的进程（2026-11-10 起闸门查活，假 pid 不再算持有者）。"""
        other = _live_other_pid()
        self._write_lock(other, time.time())
        self.assertFalse(MB._spawn("ws://127.0.0.1:1/mcp", ""))
        self.assertEqual(MB._lock_info().get("pid"), other)
        self.assertIs(MB._thread, self._orig_thread)   # 拒绝时不得拉起新线程

    def test_dead_holder_fresh_lock_taken_over(self):
        """实弹回归：restart kill 旧进程后锁文件残留且心跳还新鲜（<45s）——
        新进程绝不能再拒起桥，否则小智桥永久未连、云端老师调不到本地工具。"""
        self._write_lock(_dead_pid(), time.time())
        self.assertTrue(MB._spawn("ws://127.0.0.1:1/mcp", ""))
        self.assertEqual(MB._lock_info().get("pid"), os.getpid())

    def test_pid_alive_conservative_branches(self):
        """查活保守口径：坏锁占位 pid(-1)/0 与自身 pid 都按「别冒双桥」处理。"""
        self.assertTrue(MB._pid_alive(-1))
        self.assertTrue(MB._pid_alive(os.getpid()))
        self.assertTrue(MB._pid_alive(_live_other_pid()))
        self.assertFalse(MB._pid_alive(_dead_pid()))

    def test_stale_lock_taken_over(self):
        """持有者心跳死了（进程被 kill 未清锁）：超时后可接管。"""
        self._write_lock(os.getpid() + 999999,
                         time.time() - MB._LOCK_STALE_S - 10)
        self.assertTrue(MB._spawn("ws://127.0.0.1:1/mcp", ""))
        self.assertEqual(MB._lock_info().get("pid"), os.getpid())

    def test_own_pid_passes_hot_restart(self):
        """本进程自己的锁（含心跳早停的残留）：设置页热重启照常放行。"""
        self._write_lock(os.getpid(), time.time() - 9999)
        self.assertTrue(MB._spawn("ws://127.0.0.1:1/mcp", ""))

    def test_release_only_by_holder(self):
        """非持有进程退出时不得误删别人的锁。"""
        self._write_lock(os.getpid() + 999999, time.time())
        MB._lock_release()
        self.assertTrue(self.lock_path.exists())

    def test_no_lock_file_starts_clean(self):
        """无锁文件（首次启动）：正常起桥并登记本进程。"""
        self.assertFalse(self.lock_path.exists())
        self.assertTrue(MB._spawn("ws://127.0.0.1:1/mcp", ""))
        self.assertEqual(MB._lock_info().get("pid"), os.getpid())


class PrincipleStageFuseTest(unittest.TestCase):
    """原理图×分步舞台融合轮（2026-11-09 用户裁定 A+默认开+「概念讲完就上舞台」）：
    ① 指派自动开工 auto_open_stage（同源复用/改口覆写/error 重开/无料静默）；
    ② 擦板保住舞台（课级资产，与指派同口径）；
    ③ 提示词守画布契约（mc-step 消息协议 + steps 口播稿）；
    ④ 开讲/续讲指导语定式（先讲完概念→切入舞台推步）。
    假 LLM Event 门控不碰真云；随机 uid + 独立测试用户隔离。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.uid, cls.tok = cls._register("xzst_" + cls.suffix)
        cls.db = DatabaseManager(str(config.DB_PATH))
        cls.conn = cls.db.get_connection()
        cur = cls.conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
            "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (cls.uid, "测试学科ST" + cls.suffix, "三角形中位线定理",
             "连接三角形两边中点的线段平行于第三边且等于第三边的一半", 40))
        cls.kp = cur.fetchone()[0]
        cls.conn.commit()

    @classmethod
    def _register(cls, username):
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        return uid, tok

    @classmethod
    def tearDownClass(cls):
        cls.conn.execute("DELETE FROM knowledge_points WHERE id = ?", (cls.kp,))
        cls.conn.execute("DELETE FROM users WHERE user_id = ?", (cls.uid,))
        cls.conn.commit()
        cls.conn.close()
        with LB._lock:
            LB._boards.pop(cls.uid, None)

    CANVAS = ('<!DOCTYPE html><html><head></head><body><p>stage</p>'
              '<script>window.addEventListener("message",function(){});'
              '</script></body></html>')

    def _obj(self):
        return {"title": "中位线原理图", "canvas_html": self.CANVAS,
                "steps": [{"caption": "字幕" + str(i),
                           "narration": f"这是第{i}步的口播稿文字，需要足够长一点。"}
                          for i in range(5)]}

    def setUp(self):
        with LB._lock:
            LB._boards.pop(self.uid, None)
        self._wipe_pc()   # 成本轮：库产物跨用例会泄漏，每条用例从「库里没有」出发
        self.prompts = []
        self.release = threading.Event()
        self._orig = (LP.call_llm_for_user, cr.precheck, cr.get_user_llm_config,
                      RMC.error_explain_pack, LB._lesson_pack_text)
        cr.precheck = lambda uid: {"allowed": True, "balance": 999}
        cr.get_user_llm_config = lambda uid: None

    def tearDown(self):
        LP.call_llm_for_user, cr.precheck, cr.get_user_llm_config, \
            RMC.error_explain_pack, LB._lesson_pack_text = self._orig
        self.release.set()
        for _ in range(100):   # 后台线程收干：不让假 LLM 泄到下条用例
            a = (LB.get_state(self.uid) or {}).get("anim")
            if not a or a["state"] != "generating":
                break
            time.sleep(0.1)
        LB._boards.pop(self.uid, None)

    def _wipe_pc(self):
        """清本用户 principle 伪课程行（micro_scenes 外键序：先页后课）。
        成本轮：上条用例后台线程的成功归档可能在 tearDown 之后才落库
        （put 在落位之后），单次清挡不住这条迟到的幽灵归档——这里清到
        「连续两轮查不到行」才算静默，否则本用例库回源会误命中旧产物，
        把「该开工」变成「该复用」。"""
        q = ("SELECT 1 FROM micro_scenes WHERE course_id IN (SELECT id FROM "
             "micro_courses WHERE user_id = ? AND source_type = 'principle') LIMIT 1")
        streak = 0
        for _ in range(60):
            self.conn.execute(
                "DELETE FROM micro_scenes WHERE course_id IN (SELECT id FROM micro_courses "
                "WHERE user_id = ? AND source_type = 'principle')", (self.uid,))
            self.conn.execute(
                "DELETE FROM micro_courses WHERE user_id = ? AND source_type = 'principle'",
                (self.uid,))
            self.conn.commit()
            if not self.conn.execute(q, (self.uid,)).fetchone():
                streak += 1
                if streak >= 2:
                    return
            else:
                streak = 0
            time.sleep(0.05)
        self.fail("principle 库清不静默：后台线程持续归档？")

    def _wait_archived(self, kind, ref):
        """等 _anim_worker 成功落位后的 PC.put 真正落库（ready 与归档异步）。"""
        from services import principle_cache as PC
        for _ in range(100):
            if PC.latest(self.uid, kind, ref):
                return
            time.sleep(0.05)
        self.fail(f"舞台产物未归档：{kind}/{ref}")

    def _fake_llm(self, fail=False):
        def _f(uid, prompt, **kw):
            self.prompts.append((prompt, kw.get("scene")))
            if fail:
                raise RuntimeError("模型探底")
            self.release.wait(15)
            return json.dumps(self._obj(), ensure_ascii=False)
        LP.call_llm_for_user = _f

    def _anim(self):
        # 白盒读内部态：style/src 是服务端去重标记，公开快照（_anim_pub）已剥除
        #（评审融合轮 M-1）；内部字段名变更属实现细节，本类跟着改即可
        with LB._lock:
            a = LB._board(self.uid).get("anim")
            return dict(a) if a else None

    def _wait_ready(self, want="ready"):
        for _ in range(100):
            a = self._anim()
            if a and a["state"] == want:
                return a
            time.sleep(0.1)
        self.fail(f"舞台未进入 {want}：{self._anim()}")

    # ---------------- ③ 提示词契约（不碰 DB）
    def test_stage_prompt_carries_canvas_contract_and_discipline(self):
        p = BE.build_stage_prompt(label="三角形中位线定理", subject="数学",
                                  material="中位线平行于第三边且等于一半")
        self.assertIn('mc-step', p)              # 宿主推步消息协议（舞台听得懂老师）
        self.assertIn('narration', p)            # 分步口播契约（validate 同构）
        self.assertIn('CSS 变量', p)             # html-explainer 方法论纪律在位
        self.assertIn('术语与给定素材严格一致', p)
        self.assertIn('9000', p)                 # 紧凑篇幅纪律（原理图轮立的双保险）
        self.assertIn('中位线平行于第三边', p)   # 素材进料

    # ---------------- ④ 指导语定式
    def test_assign_directives_mention_auto_stage(self):
        kp_txt = LB._assign_directive(self.uid, {"kind": "kp", "id": self.kp,
                                                 "label": "三角形中位线定理"})
        self.assertIn("已自动后台生成", kp_txt)
        self.assertIn("board_anim_step(0)", kp_txt)
        self.assertIn("先把基本概念卡讲完", kp_txt)   # 用户裁定的节奏定式
        err_txt = LB._assign_directive(self.uid, {"kind": "error", "id": 88,
                                                  "label": "一道题"})
        self.assertIn("原理图已自动后台生成", err_txt)

    # ---------------- ① 自动开工：起→复用→就绪→宣布
    def test_auto_open_kp_start_reuse_ready_announce(self):
        self._fake_llm()
        r = LB.auto_open_stage(self.uid, "kp", self.kp, "三角形中位线定理")
        self.assertTrue(r["started"])
        a = self._anim()
        self.assertEqual(a["state"], "generating")
        self.assertEqual(a["style"], "principle")
        self.assertEqual(a["src"], {"kind": "kp", "id": self.kp})
        self.assertIn("三角形中位线定理·原理图", a["title"])
        # 同源重复指派（用户反复点入口）：复用不重开不双扣分
        r2 = LB.auto_open_stage(self.uid, "kp", self.kp, "三角形中位线定理")
        self.assertFalse(r2["started"])
        self.assertEqual(r2["reused"], "generating")
        # 生成期间照常讲课不阻塞
        self.assertIn("已写上黑板",
                      LB.execute_tool("board_write", {"content": "概念卡"}, self.uid))
        self.assertEqual(len(self.prompts), 1)   # 没多烧一次 LLM
        self.assertIn("中位线", self.prompts[0][0])   # 素材进了提示词
        self.release.set()
        a = self._wait_ready()
        self.assertEqual(len(a["steps"]), 5)
        t = LB.execute_tool("board_write", {"content": "另一张"}, self.uid)
        self.assertIn("[舞台就绪]", t)            # 确定性信号：老师看得见就绪
        self.assertIn("board_anim_step", t)
        # 就绪后同源再指派：仍复用（不重置不重扣）
        self.assertFalse(LB.auto_open_stage(self.uid, "kp", self.kp,
                                            "三角形中位线定理")["started"])

    def test_concurrent_same_src_assign_single_bill(self):
        """评审融合轮 I-1 回归：两路同源指派并发到达→只开工一次只扣一次费。"""
        self._fake_llm()                     # 不放门：先起线程停在假 LLM 里占住 generating
        results = []
        ts = [threading.Thread(target=lambda: results.append(LB.auto_open_stage(
            self.uid, "kp", self.kp, "三角形中位线定理"))) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(1 for r in results if r["started"]), 1)   # 恰一路开工
        self.release.set()
        self._wait_ready()
        self.assertEqual(len(self.prompts), 1)   # 模型只被调一次，无双扣费

    def test_stage_step_then_clear_keeps_ready_stage(self):
        """擦板保住舞台（用户裁定 A）：只清板书卡，current/ready 原封不动。"""
        self._fake_llm()
        LB.auto_open_stage(self.uid, "kp", self.kp, "三角形中位线定理")
        self.release.set()
        self._wait_ready()
        LB.execute_tool("board_anim_step", {"step": 2}, self.uid)
        LB.execute_tool("board_clear", {}, self.uid)
        st = LB.get_state(self.uid)
        self.assertEqual(st["items"], [])            # 板干净了
        self.assertEqual(st["anim"]["state"], "ready")   # 舞台还在
        self.assertEqual(st["anim"]["current"], 2)

    def test_error_src_override_starts_new_gen(self):
        """指派改口（src 不符）：覆写重开，旧结果由 gen 令牌自然丢弃。"""
        self._fake_llm()
        RMC.error_explain_pack = lambda uid, eid: {
            "stem": "已知三角形两边中点，求证中位线性质", "subject": "数学"}
        # 评审融合轮 M-4：所有猴子补丁集中进 setUp/tearDown 还原，用例内不再手写 finally
        LB._lesson_pack_text = lambda uid, eid: {
            "text": "【题目】中位线求证", "subject": "数学"}
        r1 = LB.auto_open_stage(self.uid, "kp", self.kp, "三角形中位线定理")
        self.release.set()
        self._wait_ready()
        r2 = LB.auto_open_stage(self.uid, "error", 66, "另一课")
        self.assertTrue(r2["started"])
        a = self._anim()
        # 假 LLM 门已开（release 早 set），后台线程可能瞬到 ready：
        # 覆写证据以 src 变化为准，state 只要求不是旧 ready+旧 src 组合
        self.assertIn(a["state"], ("generating", "ready"))
        self.assertEqual(a["src"], {"kind": "error", "id": 66})
        # title 不作覆写证据：就绪后 _finish_anim 用生成结果的 title 覆写，
        # 假 LLM 两轮返回同一固定标题属正常业务行为；src 变化即铁证

    def test_failed_stage_restarts_and_falls_silent(self):
        """生成失败：静默回落现有讲法（失败尾注可选）；同源指派可重开。"""
        self._fake_llm(fail=True)
        self.assertTrue(LB.auto_open_stage(self.uid, "kp", self.kp, "中位线")["started"])
        self._wait_ready("error")
        t = LB.execute_tool("board_write", {"content": "照常讲课"}, self.uid)
        self.assertIn("已写上黑板", t)
        self.assertIn("[舞台失败]", t)   # 一次性尾注：不阻断不惩罚，老师可转述可不转
        # 失败后同源指派：重开（再给一次机会，与弹窗版 failed 不缓存同口径）
        self.release.set()
        self._fake_llm()
        self.assertTrue(LB.auto_open_stage(self.uid, "kp", self.kp, "中位线")["started"])
        self.release.set()
        self._wait_ready()

    def test_no_material_and_credits_skip_silently(self):
        """素材取不到/积分不足：不开工不留假 anim，讲课链路零痕迹。"""
        self._fake_llm()
        RMC.error_explain_pack = lambda uid, eid: None
        LB._lesson_pack_text = lambda uid, eid: None
        r = LB.auto_open_stage(self.uid, "error", 99, "没这题")
        self.assertFalse(r["started"])
        self.assertEqual(r["reason"], "no_material")
        self.assertIsNone(self._anim())
        # 积分不足且无自带模型配置：静默 skip（先清库，模拟「无现成产物可复用」——
        # 成本轮规则 2：有库产物时根本不预检积分，秒回才是预期行为）
        self.release.set()
        LB.auto_open_stage(self.uid, "kp", self.kp, "三角形中位线定理")
        self._wait_ready()
        cr.precheck = lambda uid: {"allowed": False, "balance": 0}
        LB._boards.pop(self.uid, None)
        self._wait_archived("kp", self.kp)   # 等上一轮归档落库再清，不撞写库窗口
        self._wipe_pc()
        r2 = LB.auto_open_stage(self.uid, "kp", self.kp, "三角形中位线定理")
        self.assertFalse(r2["started"])
        self.assertEqual(r2["reason"], "credits")

    # ---------------- ①b 库回源复用（成本优化轮 2026-11-10，规则 2）
    def test_stage_cache_reuse_after_restart(self):
        """同 kp 库中已有产物 → 内存清空（=重启）后再指派：零外呼零扣分直接 ready。"""
        self._fake_llm()
        self.assertTrue(LB.auto_open_stage(self.uid, "kp", self.kp, "中位线")["started"])
        self.release.set()
        self._wait_ready()
        self._wait_archived("kp", self.kp)   # 归档落库后才能回源，同样避开写库窗口
        n0 = len(self.prompts)
        LB._boards.pop(self.uid, None)          # 模拟服务重启：内存舞台丢，库里还有
        r = LB.auto_open_stage(self.uid, "kp", self.kp, "中位线")
        self.assertFalse(r["started"])
        self.assertEqual(r["reused"], "cache")
        self.assertEqual(len(self.prompts), n0)  # 全程零新外呼
        a = self._anim()
        self.assertEqual(a["state"], "ready")
        self.assertEqual(a["canvas_html"], self.CANVAS)
        # 回源行确实是 _anim_worker 成功落位时归档的（mode 已归档口径）
        from services import principle_cache as PC
        hit = PC.latest(self.uid, "kp", self.kp)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["content"]["mode"], "off")


class LessonResumeAfterReconnectTest(unittest.TestCase):
    """断线失忆防（2026-11-15 用户裁定：没点下课=同一堂课）：
    小智云待机/重连后老师记忆清零，但黑板一直在——取料/上题的工具返回
    必须以板面为权威：黑板非空绝不引导重新上题、清板、从头重讲。"""

    @classmethod
    def setUpClass(cls):
        cls.client = APP.test_client()
        cls.suffix = uuid.uuid4().hex[:8]
        username = "xzrs_" + cls.suffix
        cls.client.post("/api/auth/register",
                        json={"username": username, "password": "test123456"})
        r = cls.client.post("/api/auth/login",
                            json={"username": username, "password": "test123456"})
        tok = r.get_json()["data"]["token"]
        seg = tok.split(".")[1]
        cls.uid = str(json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))["uid"])
        db = DatabaseManager(str(config.DB_PATH))
        cls.conn = db.get_connection()
        subj = "测试学科XZR" + cls.suffix
        cur = cls.conn.execute(
            "INSERT INTO knowledge_points (user_id, subject_name, point_name, "
            "core_description, mastery_score) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (cls.uid, subj, "导数", "链式法则", 30))
        cls.kp = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
            "question_content, user_answer, is_correct, options_json) "
            "VALUES (?, ?, ?, ?, ?, 0, ?) RETURNING id",
            (cls.uid, subj, cls.kp, "(2x+1)^2 的导数是？", "A", "[]"))
        pr = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
            "practice_record_id, current_proficiency, correct_answer, explanation) "
            "VALUES (?, ?, ?, ?, 20, 'B', '先外层再内层') RETURNING id",
            (cls.uid, subj, cls.kp, pr))
        cls.err = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO practice_records (user_id, subject_name, knowledge_point_id, "
            "question_content, user_answer, is_correct, options_json) "
            "VALUES (?, ?, ?, ?, ?, 0, ?) RETURNING id",
            (cls.uid, subj, cls.kp, "ln(1+x) 的等价无穷小是？", "A", "[]"))
        pr2 = cur.fetchone()[0]
        cur = cls.conn.execute(
            "INSERT INTO error_questions (user_id, subject_name, knowledge_point_id, "
            "practice_record_id, current_proficiency, correct_answer, explanation) "
            "VALUES (?, ?, ?, ?, 20, 'B', 'x→0 时 ln(1+x)~x') RETURNING id",
            (cls.uid, subj, cls.kp, pr2))
        cls.err2 = cur.fetchone()[0]
        cls.conn.commit()   # PG 连接池按连接隔离：不提交服务端另一连接看不到

    @classmethod
    def tearDownClass(cls):
        for tbl in ("error_questions", "practice_records", "knowledge_points"):
            cls.conn.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (cls.uid,))
        cls.conn.commit()
        cls.conn.close()
        LB._boards.pop(cls.uid, None)

    def setUp(self):
        LB._boards.pop(self.uid, None)

    def tearDown(self):
        LB.execute_tool("board_clear", {}, self.uid)
        LB._boards.pop(self.uid, None)

    def test_r1_material_list_resume_when_board_full(self):
        """黑板非空：取料清单不再「选题开讲」，换续讲定式。"""
        LB.execute_tool("board_show_problem", {"error_id": str(self.err)}, self.uid)
        LB.execute_tool("board_write", {"kind": "step", "content": "先外层 2(2x+1)"}, self.uid)
        t = LB.execute_tool("get_lesson_material", {}, self.uid)
        self.assertIn("【课堂进行中】", t)
        self.assertIn("严禁 board_clear", t)
        self.assertNotIn("选一道题，用 board_show_problem 把它写上黑板后开始讲解", t)

    def test_r2_pack_error_id_on_board(self):
        """题已在板上：重取素材不引导「写上黑板开始讲解」。"""
        LB.execute_tool("board_show_problem", {"error_id": str(self.err)}, self.uid)
        t = LB.execute_tool("get_lesson_material", {"error_id": str(self.err)}, self.uid)
        self.assertIn("已在黑板上", t)
        self.assertIn("【课堂进行中】", t)
        self.assertNotIn("用 board_show_problem 把这题写上黑板", t)

    def test_r3_show_problem_twice_no_rotate(self):
        """断线重连后重 show 同题=拒且不得触发换题重开（板卡张数/序号不变）。"""
        LB.execute_tool("board_show_problem", {"error_id": str(self.err)}, self.uid)
        LB.execute_tool("board_write", {"kind": "step", "content": "再乘内层导数 2"}, self.uid)
        with LB._lock:
            b0 = LB._board(self.uid)
            n0, seq0 = len(b0["items"]), b0["seq"]
        t = LB.execute_tool("board_show_problem", {"error_id": str(self.err)}, self.uid)
        self.assertIn("不需要重新上题", t)
        with LB._lock:
            b1 = LB._board(self.uid)
            self.assertEqual(len(b1["items"]), n0)
            self.assertEqual(b1["seq"], seq0)   # 没重铺卡

    def test_r4_empty_board_normal_flow(self):
        """对照组：空板取料照旧「开新课」引导，不叠续讲定式。"""
        t = LB.execute_tool("get_lesson_material", {}, self.uid)
        self.assertIn("选一道题，用 board_show_problem 把它写上黑板后开始讲解", t)
        self.assertNotIn("【课堂进行中】", t)

    def test_r5_clear_then_show_is_fresh_lesson(self):
        """擦板=明确结课：之后 show 同题走正常上题流程，不被防抖拦。"""
        LB.execute_tool("board_show_problem", {"error_id": str(self.err)}, self.uid)
        LB.execute_tool("board_clear", {}, self.uid)
        t = LB.execute_tool("board_show_problem", {"error_id": str(self.err)}, self.uid)
        self.assertIn("已写上黑板", t)
        self.assertNotIn("不需要重新上题", t)

    def test_r6_fresh_assign_outranks_resume(self):
        """刚消费学生网页点名指派（pre=开讲新题）：清单不叠续讲定式
        （评审 W2：相反指令同屏会吞掉学生合法的换题请求）。"""
        LB.execute_tool("board_show_problem", {"error_id": str(self.err)}, self.uid)
        LB.set_assign(self.uid, "error", self.err2, "等价无穷小")
        t = LB.execute_tool("get_lesson_material", {}, self.uid)
        self.assertIn("📌网页指定讲解", t)
        self.assertNotIn("【课堂进行中】", t)


class QUnboardedMirrorTest(unittest.TestCase):
    """讲了没写镜（2026-11-16 实弹轮用户报障：追问阶段板书一直不更新）：
    学生连问 ≥2 句而黑板没添一笔，下次工具返回拦嘴；任何上板/改写/擦板
    动作清零。纯板面状态机不碰 DB；探针用 board_highlight（不存在卡）：
    既不写板又能带出镜尾——写板类工具执行时已归零，自身不会带镜。"""

    def setUp(self):
        self.uid = "qmir_" + uuid.uuid4().hex[:10]

    def tearDown(self):
        LB._boards.pop(self.uid, None)

    def _probe(self):
        return LB.execute_tool("board_highlight", {"item_id": -1}, self.uid)

    def test_q1_single_question_no_mirror(self):
        """对照口径：只问了一句不拦嘴（镜只盯连续只说不写）。"""
        LB.append_speech(self.uid, "student", "矩阵乘法怎么算")
        self.assertNotIn("你已经答了学生", self._probe())

    def test_q2_two_questions_mirror(self):
        LB.append_speech(self.uid, "student", "矩阵乘法怎么算")
        LB.append_speech(self.uid, "student", "转置是啥")
        self.assertIn("你已经答了学生 2 次追问", self._probe())

    def test_q3_teacher_speech_not_counted(self):
        """老师口播不计数：正课讲解中镜不得误伤。"""
        for i in range(3):
            LB.append_speech(self.uid, "teacher", f"讲课第{i + 1}句")
        self.assertNotIn("你已经答了学生", self._probe())

    def test_q4_board_write_clears(self):
        """两问后写一卡：写卡自身不带镜（执行时已归零），后续探针也不带。"""
        LB.append_speech(self.uid, "student", "问一")
        LB.append_speech(self.uid, "student", "问二")
        t = LB.execute_tool("board_write", {"kind": "step", "content": "关键结论上板"}, self.uid)
        self.assertNotIn("你已经答了学生", t)
        self.assertNotIn("你已经答了学生", self._probe())

    def test_q5_refire_after_clear_then_replace(self):
        """归零不翻旧账也不终身制：再问两句重新拦；改写卡（board_replace）同样清零。"""
        LB.execute_tool("board_write", {"kind": "step", "content": "结论卡"}, self.uid)
        with LB._lock:
            cid = LB._board(self.uid)["items"][-1]["id"]
        LB.append_speech(self.uid, "student", "追问一")
        LB.append_speech(self.uid, "student", "追问二")
        self.assertIn("你已经答了学生 2 次追问", self._probe())
        t = LB.execute_tool("board_replace",
                            {"item_id": cid, "content": "改写后的结论"}, self.uid)
        self.assertNotIn("你已经答了学生", t)
        self.assertNotIn("你已经答了学生", self._probe())

    def test_q6_clear_board_resets(self):
        """擦板=重开一页：追问没上板的旧账一并清零。"""
        LB.append_speech(self.uid, "student", "问一")
        LB.append_speech(self.uid, "student", "问二")
        LB.execute_tool("board_clear", {}, self.uid)
        self.assertNotIn("你已经答了学生", self._probe())

    def test_q7_count_capped(self):
        """计数上限 9：镜只需量级不需精确数，长问不乱累加。"""
        for i in range(12):
            LB.append_speech(self.uid, "student", f"追问{i + 1}")
        self.assertIn("你已经答了学生 9 次追问", self._probe())


class TalkUnboardedMirrorTest(unittest.TestCase):
    """说了没写镜（2026-11-17 用户报障「面板一直说话、板书不更新」）：
    老师连续口播 ≥_TALK_UNBOARDED_MIN 字而黑板一笔没添，下次工具返回拦嘴；
    任何上板/改写/擦板清零。与讲了没写镜（盯学生追问）互补：这镜盯老师
    自己干讲。纯板面状态机不碰 DB；探针同 QUnboardedMirrorTest 口径。"""

    def setUp(self):
        self.uid = "tmir_" + uuid.uuid4().hex[:10]

    def tearDown(self):
        LB._boards.pop(self.uid, None)

    def _probe(self):
        return LB.execute_tool("board_highlight", {"item_id": -1}, self.uid)

    def _talk(self, n, role="teacher", tag="讲"):
        """报 n 字口播：单句受 _SPEECH_TEXT_MAX=200 截断，分多句报。"""
        sent = 0
        while sent < n:
            chunk = min(150, n - sent)
            LB.append_speech(self.uid, role, tag * chunk)
            sent += chunk

    def test_t1_below_threshold_no_mirror(self):
        """正常边讲边写节奏量级（约 200 字）不拦嘴。"""
        self._talk(200)
        self.assertNotIn("黑板一笔没添", self._probe())

    def test_t2_over_threshold_mirror(self):
        self._talk(300)
        self.assertIn("黑板一笔没添", self._probe())
        self.assertIn("board_draw", self._probe())

    def test_t3_board_write_clears(self):
        """写卡动作清零：写卡自身不带镜，后续探针也不带。"""
        self._talk(300)
        t = LB.execute_tool("board_write", {"kind": "step", "content": "收拢上板"}, self.uid)
        self.assertNotIn("黑板一笔没添", t)
        self.assertNotIn("黑板一笔没添", self._probe())

    def test_t4_replace_and_clear_also_reset(self):
        """改写卡/擦板同清零口径（板在跟着嘴动就不拦）。"""
        LB.execute_tool("board_write", {"kind": "step", "content": "卡一"}, self.uid)
        with LB._lock:
            cid = LB._board(self.uid)["items"][-1]["id"]
        self._talk(300)
        self.assertIn("黑板一笔没添", self._probe())
        LB.execute_tool("board_replace", {"item_id": cid, "content": "改写"}, self.uid)
        self.assertNotIn("黑板一笔没添", self._probe())
        self._talk(300)
        LB.execute_tool("board_clear", {}, self.uid)
        self.assertNotIn("黑板一笔没添", self._probe())

    def test_t5_student_speech_not_counted(self):
        """学生的话不记账：这镜只盯老师嘴，学生长段发言不得误伤。"""
        self._talk(300, role="student", tag="我")
        self.assertNotIn("黑板一笔没添", self._probe())

    def test_t6_cumulative_across_sentences(self):
        """跨句累计：单句都在阈下，累加过阈仍拦（镜盯的是总口播量）。"""
        for _ in range(2):
            LB.append_speech(self.uid, "teacher", "讲" * 100)
        self.assertNotIn("黑板一笔没添", self._probe())
        LB.append_speech(self.uid, "teacher", "讲" * 70)
        self.assertIn("黑板一笔没添", self._probe())


class TnDropMirrorTest(unittest.TestCase):
    """吞字镜（2026-11-18 实弹轮用户报障：字幕「所有形如 的向量」「再看 这个向量」
    ——坐标式被云端 TTS 归一化吞成空格，下发即残、客户端无法回补）：
    老师句中现「汉字 空格 汉字」即记账，下次工具返回递一次指名提醒并消费。
    纯内存状态机不碰 DB；探针同 TalkUnboardedMirrorTest 口径。"""

    def setUp(self):
        self.uid = "tnmir_" + uuid.uuid4().hex[:10]

    def tearDown(self):
        LB._boards.pop(self.uid, None)

    def _probe(self):
        return LB.execute_tool("board_highlight", {"item_id": -1}, self.uid)

    def test_u1_normal_speech_no_mirror(self):
        """正常中文句无句中空格：不触发。"""
        LB.append_speech(self.uid, "teacher", "第三个分量永远是零，这个方向就废了")
        self.assertNotIn("凭空消失", self._probe())

    def test_u2_residue_triggers_once_with_sample(self):
        """吞字残骸：镜带上残句样本指名道姓，且只递一次（消费即清，不反复唠）。"""
        LB.append_speech(self.uid, "teacher", "所有形如 的向量，第三个分量锁死是零")
        t = self._probe()
        self.assertIn("凭空消失", t)
        self.assertIn("所有形如 的向量", t)  # 残句样本同屏
        self.assertNotIn("凭空消失", self._probe())  # 第二次不重复递

    def test_u3_latin_spacing_not_counted(self):
        """中英混排的正常空格不误触：空格两侧必挨字母，不是「汉字 空格 汉字」。"""
        LB.append_speech(self.uid, "teacher", "在 R3 空间里有三个基，每一个都靠它们搭")
        self.assertNotIn("凭空消失", self._probe())

    def test_u3b_pure_latin_spacing_clean(self):
        LB.append_speech(self.uid, "teacher", "矩阵 A 和 B 相乘不满足交换律")
        self.assertNotIn("凭空消失", self._probe())

    def test_u4_student_speech_not_counted(self):
        """学生的话不记账：这镜盯的是老师的嘴。"""
        LB.append_speech(self.uid, "student", "形如 的向量是什么意思")
        self.assertNotIn("凭空消失", self._probe())

    def test_u5_clear_board_resets(self):
        """擦板重开：吞字提醒旧账清零。"""
        LB.append_speech(self.uid, "teacher", "再看 这个向量")
        LB.execute_tool("board_clear", {}, self.uid)
        self.assertNotIn("凭空消失", self._probe())

    def test_u6_refire_after_consumed(self):
        """消费后可重犯重递：不是终身制沉默。"""
        LB.append_speech(self.uid, "teacher", "形如 的向量是一类")
        self.assertIn("凭空消失", self._probe())
        self.assertNotIn("凭空消失", self._probe())
        LB.append_speech(self.uid, "teacher", "等于 的那个式子")
        self.assertIn("凭空消失", self._probe())


if __name__ == "__main__":
    unittest.main(verbosity=2)
