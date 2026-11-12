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
        question_type TEXT DEFAULT '',
        options_json TEXT,
        practice_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pr_user ON practice_records (user_id)",
    "CREATE INDEX IF NOT EXISTS idx_pr_kp ON practice_records (knowledge_point_id)",
    # 存量库幂等补列（错题翻卡：选择题选项需随流水留存，否则复习时无选项可看）
    "ALTER TABLE practice_records ADD COLUMN IF NOT EXISTS question_type TEXT DEFAULT ''",
    "ALTER TABLE practice_records ADD COLUMN IF NOT EXISTS options_json TEXT",

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

    # ---- 练/记记忆内核（FSRS-5，2026-09-28 集成线回归）：状态列+星值，全部可空、旧代码前向兼容 ----
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS difficulty_score NUMERIC(3,1) DEFAULT 5.0",
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS importance_score NUMERIC(3,1) DEFAULT 5.0",
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS fsrs_stability DOUBLE PRECISION",
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS fsrs_difficulty DOUBLE PRECISION",
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS fsrs_state INTEGER DEFAULT 0",
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS fsrs_reps INTEGER DEFAULT 0",
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS fsrs_lapses INTEGER DEFAULT 0",
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS last_review_time TEXT",
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS due_time TEXT",
    "ALTER TABLE knowledge_points ADD COLUMN IF NOT EXISTS mastery_manual INTEGER DEFAULT 0",

    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS difficulty_score NUMERIC(3,1) DEFAULT 5.0",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS importance_score NUMERIC(3,1) DEFAULT 5.0",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS fsrs_stability DOUBLE PRECISION",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS fsrs_difficulty DOUBLE PRECISION",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS fsrs_state INTEGER DEFAULT 0",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS fsrs_reps INTEGER DEFAULT 0",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS fsrs_lapses INTEGER DEFAULT 0",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS last_review_time TEXT",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS due_time TEXT",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS mastery_manual INTEGER DEFAULT 0",

    # ---- 独立错题（手动录入，2026-10-12）：知识点绑定放宽为可空 + 来源标记 ----
    # 影子练习记录架构：手动错题也写 practice_records（题干存那里），kp 置 NULL 表示不依附知识点
    "ALTER TABLE practice_records ALTER COLUMN knowledge_point_id DROP NOT NULL",
    "ALTER TABLE error_questions ALTER COLUMN knowledge_point_id DROP NOT NULL",
    "ALTER TABLE error_questions ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'practice'",

    # ---- 错题学习单元升级（2026-10-14）：重练/举一反三流水挂回来源错题 + 薄弱点分析报告 ----
    # error_question_id：练这道错题的历史（每错题一份，类似知识点学习历史）；
    # 举一反三新题携带 root_error_id 语义同列（新题行存于派生题自己的流水上）
    "ALTER TABLE practice_records ADD COLUMN IF NOT EXISTS error_question_id BIGINT",
    "CREATE INDEX IF NOT EXISTS idx_pr_error ON practice_records (error_question_id)",
    """
    CREATE TABLE IF NOT EXISTS weakness_reports (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        subject_name TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT 'global',
        error_ids TEXT,
        report_md TEXT NOT NULL,
        mindmap_json TEXT,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_wr_user_subject ON weakness_reports (user_id, subject_name)",

    # 知识点熟练度历史（FSRS 曲线，与错题 error_proficiency_history 对称）
    """
    CREATE TABLE IF NOT EXISTS kp_proficiency_history (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        knowledge_point_id BIGINT NOT NULL,
        timestamp TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        mastery INTEGER NOT NULL,
        retrievability DOUBLE PRECISION
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_kph_kp_time ON kp_proficiency_history (knowledge_point_id, timestamp)",

    # 记忆库卡片（用户标注入池；正/反面为标注时快照）
    """
    CREATE TABLE IF NOT EXISTS memory_cards (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        card_type TEXT NOT NULL,
        ref_id BIGINT NOT NULL,
        subject_name TEXT NOT NULL,
        front_text TEXT NOT NULL,
        back_text TEXT NOT NULL,
        added_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        UNIQUE(user_id, card_type, ref_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mc_user_type ON memory_cards (user_id, card_type, subject_name)",

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
    # 解绑后的错题允许转收藏（无知识点归属），收藏表同步放宽——必须在建表之后（fresh install 时 ALTER 不存在表会整体 abort）
    "ALTER TABLE favorite_questions ALTER COLUMN knowledge_point_id DROP NOT NULL",

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

    # ---- 微课生成（S1 知识点→微课，2026-10-30；一表一课/一表一页，逐页增量落库）----
    """
    CREATE TABLE IF NOT EXISTS micro_courses (
        id BIGSERIAL PRIMARY KEY,
        course_key TEXT NOT NULL UNIQUE,              -- 请求线程生成（后台线程按 key 定位，免回读自增 id 竞态）
        user_id TEXT NOT NULL,
        subject_name TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        source_type TEXT NOT NULL DEFAULT 'kp',      -- 一期仅 kp（薄弱点驱动），留位不建其它适配器
        source_ref TEXT NOT NULL DEFAULT '',          -- JSON：{kp_ids:[], error_ids:[], weakness_name, report_id}
        outline_json TEXT NOT NULL DEFAULT '',        -- 校验后的大纲 JSON
        status TEXT NOT NULL DEFAULT 'generating',    -- generating | ready | partial | failed
        error_note TEXT,                              -- 整课级失败原因（大纲失败留痕，评审 R1-7）
        version INTEGER DEFAULT 1,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        updated_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mcourse_user ON micro_courses (user_id, updated_time DESC)",
    # 幂等增量列（既有约定，评审 R2-4）：已按旧版建表的库重跑 DDL 时补列
    "ALTER TABLE micro_courses ADD COLUMN IF NOT EXISTS error_note TEXT",
    # 黑板两段式轮（2026-11-05）：课堂归档课（source_type='live'）导出的 PDF/PPTX 相对路径
    "ALTER TABLE micro_courses ADD COLUMN IF NOT EXISTS export_rel TEXT",
    # 在飞唯一索引（评审 R1-5）：同一用户同一锚定只允许一节 generating 课，
    # 并发 create 由 INSERT 冲突拦截，杜绝 TOCTOU 双开双扣分。
    # 六期改造：错题深度讲解课（source_type='error'）按 error_ids 去重、知识点课按 anchor_kp_id，
    # 两轨互不劫持（旧版仅按 anchor_kp_id，同 kp 的错题课会与知识点课互撞）；
    # 黑板两段式轮（2026-11-05）再加 prep 轨（自写主题备课，无 anchor_kp_id）按 topic_token 去重，
    # 否则该列取 NULL 在唯一索引里不参与判重，同主题可双开双扣分；
    # DROP+CREATE 幂等：新库直接新版，旧库重跑迁移
    "DROP INDEX IF EXISTS uq_mcourse_inflight",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_mcourse_inflight ON micro_courses "
    "(user_id, source_type, (CASE WHEN source_type = 'error' "
    "THEN (source_ref)::jsonb->>'error_ids' "
    "WHEN source_type = 'prep' "
    "THEN (source_ref)::jsonb->>'topic_token' "
    "ELSE (source_ref)::jsonb->>'anchor_kp_id' END)) WHERE status = 'generating'",

    """
    CREATE TABLE IF NOT EXISTS micro_scenes (
        id BIGSERIAL PRIMARY KEY,
        course_id BIGINT NOT NULL,
        seq INTEGER NOT NULL,                         -- 页序（1 起）
        scene_type TEXT NOT NULL,                     -- explain | example | quiz | summary | interactive
        kp_id BIGINT,                                 -- 归属知识点（quiz 页必填，判分入池靠它）
        title TEXT NOT NULL DEFAULT '',
        content_json TEXT NOT NULL DEFAULT '',        -- 页型契约 JSON（quiz/interactive 为对象，其余含 narration）
        status TEXT NOT NULL DEFAULT 'pending',       -- pending | generating | done | failed | standby（七期：互动页占位待用户翻开生成）
        error_note TEXT,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        updated_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')),
        UNIQUE(course_id, seq)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mscene_course ON micro_scenes (course_id, seq)",

    # ---- 目标导向学习（体系化课程，2026-11-11；设计 docs/superpowers/specs/2026-11-11-goal-driven-learning-design.md）----
    """
    CREATE TABLE IF NOT EXISTS learning_goals (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        subject_name TEXT NOT NULL,
        goal_text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',          -- draft|ready（生成成功=ready）
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cgoal_user_subject ON learning_goals (user_id, subject_name)",

    """
    CREATE TABLE IF NOT EXISTS course_modules (
        id BIGSERIAL PRIMARY KEY,
        goal_id BIGINT NOT NULL,
        ord INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cmodule_goal ON course_modules (goal_id)",

    """
    CREATE TABLE IF NOT EXISTS course_lessons (
        id BIGSERIAL PRIMARY KEY,
        module_id BIGINT NOT NULL,
        ord INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        est_minutes INTEGER NOT NULL DEFAULT 30,
        status TEXT NOT NULL DEFAULT 'new',            -- new|pretested|content_ready|learned|done
        content_md TEXT,
        content_mode TEXT,                             -- full|concise（前测分判定）
        pretest_score REAL,
        regen_count INTEGER NOT NULL DEFAULT 0,
        done_time TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_clesson_module ON course_lessons (module_id)",

    """
    CREATE TABLE IF NOT EXISTS course_tests (
        id BIGSERIAL PRIMARY KEY,
        kind TEXT NOT NULL,                            -- pretest|postquiz|moduleexam
        lesson_id BIGINT,
        module_id BIGINT,
        questions_json TEXT NOT NULL,
        generated_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ctest_lesson ON course_tests (lesson_id, kind)",
    "CREATE INDEX IF NOT EXISTS idx_ctest_module ON course_tests (module_id, kind)",

    """
    CREATE TABLE IF NOT EXISTS course_attempts (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT '0001',
        goal_id BIGINT NOT NULL,
        test_id BIGINT NOT NULL,
        kind TEXT NOT NULL,
        lesson_title TEXT NOT NULL DEFAULT '',
        score REAL NOT NULL,
        detail_json TEXT NOT NULL,
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cattempt_user_goal ON course_attempts (user_id, goal_id)",

    # 课文追问笔记树（追问笔记树轮 2026-11-12）：parent_id 组树（NULL=锚在课文正文，
    # 非NULL=追问的追问，无限嵌套）；anchor_text=选中原文（前端文本匹配锚定，
    # 锚失效降级右栏索引）；服务端持久化，跨会话不丢（用户裁定「学习笔记本」定位）。
    """
    CREATE TABLE IF NOT EXISTS lesson_notes (
        id BIGSERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        lesson_id BIGINT NOT NULL,
        parent_id BIGINT,
        anchor_text TEXT NOT NULL DEFAULT '',
        question TEXT NOT NULL,
        answer_md TEXT NOT NULL DEFAULT '',
        created_time TEXT DEFAULT (to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_lesson_notes_lesson ON lesson_notes (lesson_id, parent_id)",
]

# 主库拷贝顺序（外键虽未建，仍按依赖序保证数据语义）
MAIN_TABLES = [
    "users", "user_subjects", "knowledge_points", "practice_records",
    "error_questions", "notes", "knowledge_point_sources",
    "error_proficiency_history", "kp_proficiency_history", "memory_cards",
    "favorite_questions", "knowledge_mindmaps", "learning_paths",
    "micro_courses", "micro_scenes",
    "learning_goals", "course_modules", "course_lessons", "course_tests", "course_attempts",
    "lesson_notes",
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
