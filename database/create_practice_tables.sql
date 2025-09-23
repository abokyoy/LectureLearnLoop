-- 练习历史数据库表设计
-- 创建时间: 2025-09-23

-- 1. 练习会话表 - 存储练习的基本信息
CREATE TABLE IF NOT EXISTS practice_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id VARCHAR(50) UNIQUE NOT NULL,           -- 练习ID (如: practice_20250923_143022)
    user_id VARCHAR(50),                               -- 用户ID (可选，为多用户支持预留)
    selected_text TEXT NOT NULL,                       -- 选中的学习文本
    questions TEXT,                                    -- 生成的练习题目
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,    -- 创建时间
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,    -- 最后更新时间
    status VARCHAR(20) DEFAULT 'created',             -- 状态: created, submitted, evaluated
    source_type VARCHAR(20) DEFAULT 'manual',         -- 来源类型: manual, auto, import
    difficulty_level INTEGER DEFAULT 1,               -- 难度等级 1-5
    topic VARCHAR(100),                               -- 练习主题
    notes TEXT                                        -- 备注信息
);

-- 2. 练习提交记录表 - 存储用户的答题记录
CREATE TABLE IF NOT EXISTS practice_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id VARCHAR(50) NOT NULL,                 -- 关联练习ID
    submission_id VARCHAR(50) UNIQUE NOT NULL,        -- 提交ID
    user_answers TEXT NOT NULL,                       -- 用户答案
    submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 提交时间
    submission_type VARCHAR(20) DEFAULT 'manual',     -- 提交类型: manual, auto_save
    time_spent INTEGER DEFAULT 0,                     -- 答题用时(秒)
    answer_count INTEGER DEFAULT 0,                   -- 答案数量
    is_complete BOOLEAN DEFAULT 0,                    -- 是否完整提交
    FOREIGN KEY (practice_id) REFERENCES practice_sessions(practice_id)
);

-- 3. 练习评估记录表 - 存储AI评估结果
CREATE TABLE IF NOT EXISTS practice_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id VARCHAR(50) NOT NULL,                 -- 关联练习ID
    submission_id VARCHAR(50) NOT NULL,               -- 关联提交ID
    evaluation_id VARCHAR(50) UNIQUE NOT NULL,        -- 评估ID
    evaluation_result TEXT NOT NULL,                  -- 评估结果(HTML格式)
    evaluation_score REAL,                           -- 评估分数 (0-100)
    evaluation_level VARCHAR(20),                    -- 评估等级: excellent, good, fair, poor
    strengths TEXT,                                   -- 优点分析
    weaknesses TEXT,                                  -- 不足分析
    suggestions TEXT,                                 -- 改进建议
    evaluated_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- 评估时间
    evaluator_type VARCHAR(20) DEFAULT 'ai',         -- 评估者类型: ai, human
    evaluation_model VARCHAR(50),                    -- 使用的AI模型
    is_final BOOLEAN DEFAULT 1,                      -- 是否为最终评估
    FOREIGN KEY (practice_id) REFERENCES practice_sessions(practice_id),
    FOREIGN KEY (submission_id) REFERENCES practice_submissions(submission_id)
);

-- 4. 练习统计表 - 存储练习相关统计信息
CREATE TABLE IF NOT EXISTS practice_statistics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id VARCHAR(50) NOT NULL,                 -- 关联练习ID
    total_submissions INTEGER DEFAULT 0,              -- 总提交次数
    total_evaluations INTEGER DEFAULT 0,              -- 总评估次数
    average_score REAL DEFAULT 0,                     -- 平均分数
    best_score REAL DEFAULT 0,                        -- 最佳分数
    total_time_spent INTEGER DEFAULT 0,               -- 总用时(秒)
    first_submitted_at DATETIME,                      -- 首次提交时间
    last_submitted_at DATETIME,                       -- 最后提交时间
    last_evaluated_at DATETIME,                       -- 最后评估时间
    view_count INTEGER DEFAULT 0,                     -- 查看次数
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,    -- 统计更新时间
    FOREIGN KEY (practice_id) REFERENCES practice_sessions(practice_id)
);

-- 创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_practice_sessions_created_at ON practice_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_practice_sessions_status ON practice_sessions(status);
CREATE INDEX IF NOT EXISTS idx_practice_sessions_user_id ON practice_sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_practice_submissions_practice_id ON practice_submissions(practice_id);
CREATE INDEX IF NOT EXISTS idx_practice_submissions_submitted_at ON practice_submissions(submitted_at);

CREATE INDEX IF NOT EXISTS idx_practice_evaluations_practice_id ON practice_evaluations(practice_id);
CREATE INDEX IF NOT EXISTS idx_practice_evaluations_submission_id ON practice_evaluations(submission_id);
CREATE INDEX IF NOT EXISTS idx_practice_evaluations_evaluated_at ON practice_evaluations(evaluated_at);

CREATE INDEX IF NOT EXISTS idx_practice_statistics_practice_id ON practice_statistics(practice_id);

-- 创建视图：练习历史概览
CREATE VIEW IF NOT EXISTS practice_history_overview AS
SELECT 
    ps.practice_id,
    ps.selected_text,
    ps.questions,
    ps.created_at,
    ps.status,
    ps.topic,
    ps.difficulty_level,
    pst.total_submissions,
    pst.total_evaluations,
    pst.average_score,
    pst.best_score,
    pst.last_submitted_at,
    pst.last_evaluated_at,
    -- 获取最新的提交和评估信息
    (SELECT user_answers FROM practice_submissions WHERE practice_id = ps.practice_id ORDER BY submitted_at DESC LIMIT 1) as latest_answers,
    (SELECT evaluation_result FROM practice_evaluations WHERE practice_id = ps.practice_id ORDER BY evaluated_at DESC LIMIT 1) as latest_evaluation,
    (SELECT evaluation_score FROM practice_evaluations WHERE practice_id = ps.practice_id ORDER BY evaluated_at DESC LIMIT 1) as latest_score
FROM practice_sessions ps
LEFT JOIN practice_statistics pst ON ps.practice_id = pst.practice_id
ORDER BY ps.created_at DESC;

-- 创建触发器：自动更新统计信息
CREATE TRIGGER IF NOT EXISTS update_practice_statistics_on_submission
AFTER INSERT ON practice_submissions
BEGIN
    INSERT OR REPLACE INTO practice_statistics (
        practice_id, 
        total_submissions, 
        first_submitted_at, 
        last_submitted_at,
        updated_at
    )
    SELECT 
        NEW.practice_id,
        COUNT(*),
        MIN(submitted_at),
        MAX(submitted_at),
        CURRENT_TIMESTAMP
    FROM practice_submissions 
    WHERE practice_id = NEW.practice_id;
END;

CREATE TRIGGER IF NOT EXISTS update_practice_statistics_on_evaluation
AFTER INSERT ON practice_evaluations
BEGIN
    UPDATE practice_statistics 
    SET 
        total_evaluations = (
            SELECT COUNT(*) FROM practice_evaluations 
            WHERE practice_id = NEW.practice_id
        ),
        average_score = (
            SELECT AVG(evaluation_score) FROM practice_evaluations 
            WHERE practice_id = NEW.practice_id AND evaluation_score IS NOT NULL
        ),
        best_score = (
            SELECT MAX(evaluation_score) FROM practice_evaluations 
            WHERE practice_id = NEW.practice_id AND evaluation_score IS NOT NULL
        ),
        last_evaluated_at = NEW.evaluated_at,
        updated_at = CURRENT_TIMESTAMP
    WHERE practice_id = NEW.practice_id;
END;