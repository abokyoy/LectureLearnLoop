"""
LectureLearnLoop 服务端入口（Flask 3.x，端口 6001）。

阶段说明：本文件当前包含 P0/P1 基础设施（认证、调试日志通道、健康检查）；
知识/练习/笔记等蓝图按迁移计划在后续阶段注册。
"""
from __future__ import annotations

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
from routes_credits import credits_bp
from routes_admin import admin_bp
from routes_knowledge import kb_bp
from routes_memory import memory_bp
from routes_notes import notes_bp
from routes_pages import pages_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = config.get_flask_secret_key()  # D3：持久化 SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = config.IMPORT_MAX_BYTES  # 文件导入单文件上限 200MB（2026-10-04 大PDF分段）
    app.config["TEMPLATES_AUTO_RELOAD"] = True  # 开发模式：模板修改即时生效
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

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"success": True, "data": {"service": "lecturelearnloop-server", "port": config.SERVER_PORT}})

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
    application = create_app()
    debug_logger.log("server", "starting", data={"port": config.SERVER_PORT})
    # P006 修复：debug=False + 仅监听回环地址
    application.run(host="127.0.0.1", port=config.SERVER_PORT, debug=False, threaded=True)
