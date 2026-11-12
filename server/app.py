"""
LectureLearnLoop 服务端入口（Flask 3.x，端口 6001）。

阶段说明：本文件当前包含 P0/P1 基础设施（认证、调试日志通道、健康检查）；
知识/练习/笔记等蓝图按迁移计划在后续阶段注册。
"""
from __future__ import annotations

import os
import sys

# Windows GBK 控制台加固：旧模块 print 含 emoji 会崩（UnicodeEncodeError）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, jsonify, request
from flask_cors import CORS

import config
from auth import auth_bp, init_auth_table, require_auth
from database.schema_credits import init_credits_tables
from database.schema_import import init_import_tables
from knowledge_management import DatabaseManager
from logger_module import debug_logger
from routes_bridge import bridge_bp
from routes_board import board_bp
from routes_courses import courses_bp  # 2026-11-11：目标导向学习（体系化课程）
from routes_credits import credits_bp
from routes_admin import admin_bp
from routes_knowledge import kb_bp
from routes_memory import memory_bp
from routes_micro_course import mc_bp
from routes_notes import notes_bp
from routes_pages import pages_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = config.get_flask_secret_key()  # D3：持久化 SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = config.IMPORT_MAX_BYTES  # 文件导入单文件上限 200MB（2026-10-04 大PDF分段）
    app.config["TEMPLATES_AUTO_RELOAD"] = True  # 开发模式：模板修改即时生效
    # cl.css 缓存版本号：启动时取文件 mtime，Tailwind 重建后随服务重启更新；
    # 无版本参数时 Electron/浏览器长缓存会吞掉新增类（2026-10-14 批量错题 z-[92] 被旧缓存吞的回归）
    _clcss = os.path.join(app.static_folder or "", "css", "cl.css")
    app.jinja_env.globals["cl_css_ver"] = (
        str(int(os.path.getmtime(_clcss))) if os.path.exists(_clcss) else "0")
    CORS(app)  # Electron 客户端与本机调试页均需跨域

    # 单一 DatabaseManager：users 表与业务表同库，避免多库碎片化（D5 收敛方向）
    db_manager = DatabaseManager(str(config.DB_PATH))
    app.config["DB_CONN_FACTORY"] = db_manager.get_connection
    app.config["DB_MANAGER"] = db_manager

    init_auth_table(db_manager.get_connection)
    # 积分体系建表 + 存量大模型密钥迁移（2026-09-28 积分功能）
    init_credits_tables(db_manager.get_connection)
    # 文件导入任务表 + 启动恢复：上次进程中断时 running 任务置 failed（2026-09-30 导入功能）
    init_import_tables(db_manager.get_connection)
    from services import import_service
    import_service.recover_tasks_on_startup(db_manager.get_connection)
    # 微课生成启动恢复：上次进程中断时 generating 页置 failed、课程归位（2026-10-30 S1）
    from routes_micro_course import init_micro_course_recovery
    init_micro_course_recovery(db_manager.get_connection)

    # 积分功能：请求入口清理上一请求的计费上下文（worker 线程复用，防缓存命中路径串读旧 billing）
    import credits_service as _credits

    @app.before_request
    def _reset_billing_ctx():
        _credits.set_last_billing(None)

    app.register_blueprint(pages_bp)  # P2c 页面路由（SPA 壳 + 登录页 + fragments）
    app.register_blueprint(auth_bp)
    app.register_blueprint(kb_bp)  # P3 业务 API（科目/提取/确认/错题/收藏/脑图/练习/笔记）
    app.register_blueprint(bridge_bp)  # P2 桥方法兼容层 B 类端点（规格文档映射）
    app.register_blueprint(notes_bp)  # 二期：笔记正文入库/实时自动保存/录制状态
    app.register_blueprint(credits_bp)  # 2026-09-28 积分：余额/流水/兑换/ASR扣分/用户级Key
    app.register_blueprint(admin_bp)  # 2026-09-28 积分：管理后台（仅管理员）
    app.register_blueprint(memory_bp)  # 记忆库卡片（集成线回归 2026-10-01）
    app.register_blueprint(mc_bp)  # 2026-10-30 S1：知识点→微课两阶段生成
    app.register_blueprint(board_bp)  # 2026-11-04：小智云端讲师黑板（状态轮询/擦黑板）
    app.register_blueprint(courses_bp)  # 2026-11-11：目标导向学习（学习目标→体系化课程）

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"success": True, "data": {"service": "lecturelearnloop-server", "port": config.SERVER_PORT}})

    # API 未控异常统一回 JSON 500（追问笔记树轮 2026-11-12）：默认 HTML 错误页会让
    # 前端 r.json() 炸「Unexpected token '<'」，真因（如 LLM 外呼失败）被解析器术语掩盖。
    # 仅限 /api/ 前缀，页面路由不受影响；异常照旧进统一调试日志留痕。
    @app.errorhandler(Exception)
    def _api_error_json(e):
        if request.path.startswith("/api/"):
            try:
                debug_logger.log_error("api", "unhandled_exception", e, {"path": request.path})
            except Exception:  # noqa: BLE001 留痕失败不阻断报错
                pass
            from werkzeug.exceptions import HTTPException
            if isinstance(e, HTTPException):  # 404/405 等标准错误也回 JSON 形
                return jsonify({"success": False, "error": e.description or str(e)}), e.code
            return jsonify({"success": False, "error": f"服务内部错误: {e}"}), 500
        raise e

    # 统一调试日志通道（客户端/前端上报；与旧工程 app_flask 相同语义：静默失败）
    @app.route("/api/debug/log", methods=["POST"])
    def debug_log():
        try:
            payload = request.get_json(silent=True) or {}
            for item in payload.get("logs", []):
                if isinstance(item, dict):
                    debug_logger.log_frontend(
                        module=item.get("module", "unknown"),
                        action=item.get("action", "unknown"),
                        status=item.get("status", "info"),
                        data=item.get("data"),
                        source=item.get("source", "frontend"),
                    )
            return jsonify({"success": True})
        except Exception:  # noqa: BLE001
            return jsonify({"success": False}), 200  # 调试通道刻意静默失败

    @app.route("/api/debug/recent", methods=["GET"])
    @require_auth
    def debug_recent():
        n = request.args.get("n", default=20, type=int)
        return jsonify({"success": True, "data": debug_logger.read_recent(n=n)})

    return app


if __name__ == "__main__":
    # 单实例熔断（v0.2.8 八期出件轮，掉坑 P045/P051 族再复发）：本机残留裸 `python app.py`
    # 僵尸实例会各自起一条小智 MCP 桥，云端把工具调用分发到多连接——卡片号 6→3→4 串板，
    # 画好的图静默落在没人看的板上。检测到 9992 已有监听者就直接退出，双绑定机会都不给；
    # 真要让位请先杀旧实例（标准入口 server/tests/restart_9992.ps1）。
    import socket as _sock
    _probe = _sock.socket()
    _probe.settimeout(1)
    _port_busy = _probe.connect_ex(("127.0.0.1", config.SERVER_PORT)) == 0
    _probe.close()
    if _port_busy:
        debug_logger.log("server", "secondary_instance_exit", "error",
                         {"port": config.SERVER_PORT,
                          "hint": "端口已有服务监听，第二实例退出（防僵尸桥/串板）"})
        sys.exit(2)
    application = create_app()
    debug_logger.log("server", "starting", data={"port": config.SERVER_PORT})
    # 手机拍照传图独立小服务（0.0.0.0:9991，占用则 9900-9999 自适应）；与主服务同进程共享会话表
    if not config.PHOTO_DISABLE:
        from services import photo_drop
        photo_drop.start_in_background()
    # 小智云端 MCP 接入点桥（2026-11-04；2026-11-05 起支持设置页配置）：
    # 生效配置=设置页(system_config) > .env，未接入不启动；建表已在 create_app 完成
    from services import mcp_bridge
    if mcp_bridge.start_in_background():
        debug_logger.log("xz_mcp", "bridge_thread_started", "info", {})
    # P006 曾只监听回环；2026-10-15 用户裁定改 0.0.0.0：贝锐穿透 9992 线经局域网 IP 回源，
    # 验收口径 192.168.0.113:9992 可访问；暴露面由 JWT 认证 + 开放注册业务自行控制
    application.run(host="0.0.0.0", port=config.SERVER_PORT, debug=False, threaded=True)
