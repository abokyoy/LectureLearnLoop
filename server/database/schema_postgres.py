# -*- coding: utf-8 -*-
"""PostgreSQL 全量表结构（与 SQLite 现存 schema 逐列对齐）。

设计决策：
1. 时间列统一用 TEXT，默认值 to_char(UTC now)——与 SQLite 历史存储格式
   （CURRENT_TIMESTAMP 为 UTC 'YYYY-MM-DD HH:MM:SS'）逐字节兼容，
   存量数据可直接拷贝，读取后 JSON 序列化行为不变；
2. 不建 FOREIGN KEY 约束：SQLite 默认未启用外键（PRAGMA foreign_keys 未开），
   业务从未依赖其强制；PG 建 FK 反而会阻断含孤儿行的存量迁移，保持语义一致；
3. UNIQUE 约束完整保留：INSERT OR IGNORE（→ ON CONFLICT DO NOTHING）依赖它们；
4. practice_* 四表新增 user_id 列：替代旧"每用户一个 sqlite 文件"的隔离方式，
   隔离收敛到列级（配套索引）；practice_id 的唯一性从全局改为按用户。
"""

# 主库 12 表（users + 11 业务表）+ practice 4 表，按依赖顺序执行
PG_TABLES = [
    # 用户
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_users_lower_username ON users (lower(username))",

    # 学科
    """
    CREATE TABLE IF NOT EXISTS user_subjects (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        subject_name TEXT NOT NULL,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        UNIQUE(user_id, subject_name)
    )
    """,

    # 知识点
    """
    CREATE TABLE IF NOT EXISTS knowledge_points (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        subject_name TEXT NOT NULL,
        point_name TEXT NOT NULL,
        core_description TEXT NOT NULL,
        mastery_score INTEGER DEFAULT 50,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        updated_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_kp_user_subject ON knowledge_points (user_id, subject_name)",

    # 练习记录
    """
    CREATE TABLE IF NOT EXISTS practice_records (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        subject_name TEXT NOT NULL,
        knowledge_point_id BIGINT NOT NULL,
        question_content TEXT NOT NULL,
        user_answer TEXT NOT NULL,
        is_correct INTEGER NOT NULL,
        practice_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pr_user ON practice_records (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_pr_kp ON practice_records (knowledge_point_id)",

    # 错题
    """
    CREATE TABLE IF NOT EXISTS error_questions (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        subject_name TEXT NOT NULL,
        knowledge_point_id BIGINT NOT NULL,
        practice_record_id BIGINT NOT NULL,
        review_status INTEGER DEFAULT 0,
        current_proficiency INTEGER DEFAULT 20,
        correct_answer TEXT DEFAULT NULL,
        explanation TEXT DEFAULT NULL,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_eq_user ON error_questions (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_eq_kp ON error_questions (knowledge_point_id)",

    # 笔记登记（二期：正文入库，MD 文件与库双向同步，库为轮询权威源）
    """
    CREATE TABLE IF NOT EXISTS notes (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        note_uuid TEXT NOT NULL UNIQUE,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        title TEXT,
        content_hash TEXT,
        content TEXT,
        recording INTEGER DEFAULT 0,
        word_count INTEGER DEFAULT 0,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        updated_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_notes_user_path ON notes (user_id, file_path)",
    # 存量库幂等补列（二期新增）
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS content TEXT",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS recording INTEGER DEFAULT 0",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS word_count INTEGER DEFAULT 0",
    "CREATE INDEX IF NOT EXISTS idx_notes_recording ON notes (user_id, recording)",

    # 知识点来源
    """
    CREATE TABLE IF NOT EXISTS knowledge_point_sources (
        id BIGSERIAL PRIMARY KEY,
        knowledge_point_id BIGINT NOT NULL,
        note_id BIGINT NOT NULL,
        extraction_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        note_uuid TEXT,
        UNIQUE(knowledge_point_id, note_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_kps_note_uuid ON knowledge_point_sources (note_uuid)",

    # 错题熟练度历史
    """
    CREATE TABLE IF NOT EXISTS error_proficiency_history (
        id BIGSERIAL PRIMARY KEY,
        error_question_id BIGINT NOT NULL,
        timestamp TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        proficiency INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_eph_eq ON error_proficiency_history (error_question_id)",

    # 收藏题目
    """
    CREATE TABLE IF NOT EXISTS favorite_questions (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        subject_name TEXT NOT NULL,
        knowledge_point_id BIGINT NOT NULL,
        question_content TEXT NOT NULL,
        correct_answer TEXT DEFAULT NULL,
        explanation TEXT DEFAULT NULL,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_fq_user ON favorite_questions (user_id)",

    # 知识脑图
    """
    CREATE TABLE IF NOT EXISTS knowledge_mindmaps (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        subject_name TEXT NOT NULL,
        mindmap_data TEXT NOT NULL,
        version INTEGER DEFAULT 1,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        updated_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        UNIQUE(user_id, subject_name)
    )
    """,

    # 学习路径
    """
    CREATE TABLE IF NOT EXISTS learning_paths (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        subject_name TEXT NOT NULL,
        path_data TEXT NOT NULL,
        version INTEGER DEFAULT 1,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        updated_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        UNIQUE(user_id, subject_name)
    )
    """,

    # ---- 练习历史四表（PracticeService；user_id 列化隔离）----
    """
    CREATE TABLE IF NOT EXISTS practice_sessions (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        practice_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        selected_text TEXT,
        questions TEXT,
        user_answers TEXT,
        evaluation_result TEXT,
        answer_history TEXT,
        status TEXT DEFAULT 'created',
        created_at TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        updated_at TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        UNIQUE(user_id, practice_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ps_user_updated ON practice_sessions (user_id, updated_at DESC)",

    """
    CREATE TABLE IF NOT EXISTS practice_submissions (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        practice_id TEXT NOT NULL,
        submission_content TEXT,
        submission_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_psub_user ON practice_submissions (user_id, practice_id)",

    """
    CREATE TABLE IF NOT EXISTS practice_evaluations (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        practice_id TEXT NOT NULL,
        evaluation_content TEXT,
        score DOUBLE PRECISION,
        evaluation_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pev_user ON practice_evaluations (user_id, practice_id)",

    """
    CREATE TABLE IF NOT EXISTS practice_statistics (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        practice_id TEXT NOT NULL,
        total_questions INTEGER DEFAULT 0,
        correct_answers INTEGER DEFAULT 0,
        completion_time DOUBLE PRECISION DEFAULT 0,
        created_at TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pst_user ON practice_statistics (user_id, practice_id)",
]

# 主库拷贝顺序（外键虽未建，仍按依赖序保证数据语义）
MAIN_TABLES = [
    "users", "user_subjects", "knowledge_points", "practice_records",
    "error_questions", "notes", "knowledge_point_sources",
    "error_proficiency_history", "favorite_questions",
    "knowledge_mindmaps", "learning_paths",
]
# practice 每用户库合并迁移的表（需注入 user_id）
PRACTICE_TABLES_WITH_USER = [
    "practice_sessions", "practice_submissions",
    "practice_evaluations", "practice_statistics",
]


def init_postgres_schema(conn):
    """在（已是 lecturelearnloop 库的）PG 连接上幂等建表。"""
    cur = conn.cursor()
    for ddl in PG_TABLES:
        cur.execute(ddl)
    cur.close()
