"""
练习历史数据访问层 (DAO)
负责练习会话、提交记录、评估结果的数据库操作
"""
import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path


class PracticeDAO:
    """练习历史数据访问对象"""
    
    def __init__(self, db_path: str = "practice_history.db"):
        """
        初始化数据访问对象
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表结构"""
        try:
            # 确保数据库目录存在
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(exist_ok=True)
            
            # 读取并执行SQL创建脚本
            sql_file = Path(__file__).parent.parent / "database" / "create_practice_tables.sql"
            if sql_file.exists():
                with open(sql_file, 'r', encoding='utf-8') as f:
                    sql_script = f.read()
                
                with sqlite3.connect(self.db_path) as conn:
                    conn.executescript(sql_script)
                    conn.commit()
                
                self.logger.info(f"✅ 数据库初始化成功: {self.db_path}")
            else:
                self.logger.warning(f"⚠️ SQL脚本文件不存在: {sql_file}")
                self._create_tables_fallback()
                
        except Exception as e:
            self.logger.error(f"❌ 数据库初始化失败: {e}")
            raise
    
    def _create_tables_fallback(self):
        """备用的表创建方法"""
        with sqlite3.connect(self.db_path) as conn:
            # 创建基本表结构
            conn.execute("""
                CREATE TABLE IF NOT EXISTS practice_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    practice_id VARCHAR(50) UNIQUE NOT NULL,
                    selected_text TEXT NOT NULL,
                    questions TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(20) DEFAULT 'created'
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS practice_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    practice_id VARCHAR(50) NOT NULL,
                    submission_id VARCHAR(50) UNIQUE NOT NULL,
                    user_answers TEXT NOT NULL,
                    submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS practice_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    practice_id VARCHAR(50) NOT NULL,
                    submission_id VARCHAR(50) NOT NULL,
                    evaluation_id VARCHAR(50) UNIQUE NOT NULL,
                    evaluation_result TEXT NOT NULL,
                    evaluation_score REAL,
                    evaluated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
    
    def create_practice_session(self, practice_id: str, selected_text: str, 
                              questions: str = None, topic: str = None,
                              difficulty_level: int = 1) -> bool:
        """
        创建练习会话
        
        Args:
            practice_id: 练习ID
            selected_text: 选中的文本
            questions: 练习题目
            topic: 练习主题
            difficulty_level: 难度等级
            
        Returns:
            bool: 是否创建成功
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO practice_sessions 
                    (practice_id, selected_text, questions, topic, difficulty_level, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (practice_id, selected_text, questions, topic, difficulty_level))
                
                conn.commit()
                self.logger.info(f"✅ 创建练习会话成功: {practice_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"❌ 创建练习会话失败: {e}")
            return False
    
    def submit_practice_answers(self, practice_id: str, submission_id: str,
                              user_answers: str, time_spent: int = 0) -> bool:
        """
        提交练习答案
        
        Args:
            practice_id: 练习ID
            submission_id: 提交ID
            user_answers: 用户答案
            time_spent: 答题用时(秒)
            
        Returns:
            bool: 是否提交成功
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 插入提交记录
                conn.execute("""
                    INSERT OR REPLACE INTO practice_submissions 
                    (practice_id, submission_id, user_answers, time_spent, is_complete)
                    VALUES (?, ?, ?, ?, 1)
                """, (practice_id, submission_id, user_answers, time_spent))
                
                # 更新练习会话状态
                conn.execute("""
                    UPDATE practice_sessions 
                    SET status = 'submitted', updated_at = CURRENT_TIMESTAMP
                    WHERE practice_id = ?
                """, (practice_id,))
                
                conn.commit()
                self.logger.info(f"✅ 提交练习答案成功: {practice_id} -> {submission_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"❌ 提交练习答案失败: {e}")
            return False
    
    def save_practice_evaluation(self, practice_id: str, submission_id: str,
                               evaluation_id: str, evaluation_result: str,
                               evaluation_score: float = None,
                               evaluation_level: str = None) -> bool:
        """
        保存练习评估结果
        
        Args:
            practice_id: 练习ID
            submission_id: 提交ID
            evaluation_id: 评估ID
            evaluation_result: 评估结果
            evaluation_score: 评估分数
            evaluation_level: 评估等级
            
        Returns:
            bool: 是否保存成功
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                # 插入评估记录
                conn.execute("""
                    INSERT OR REPLACE INTO practice_evaluations 
                    (practice_id, submission_id, evaluation_id, evaluation_result, 
                     evaluation_score, evaluation_level)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (practice_id, submission_id, evaluation_id, evaluation_result,
                      evaluation_score, evaluation_level))
                
                # 更新练习会话状态
                conn.execute("""
                    UPDATE practice_sessions 
                    SET status = 'evaluated', updated_at = CURRENT_TIMESTAMP
                    WHERE practice_id = ?
                """, (practice_id,))
                
                conn.commit()
                self.logger.info(f"✅ 保存练习评估成功: {practice_id} -> {evaluation_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"❌ 保存练习评估失败: {e}")
            return False
    
    def get_practice_history(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        """
        获取练习历史列表
        
        Args:
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            List[Dict]: 练习历史列表
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
                
                cursor = conn.execute("""
                    SELECT 
                        practice_id,
                        selected_text,
                        questions,
                        created_at,
                        status,
                        topic,
                        difficulty_level,
                        total_submissions,
                        total_evaluations,
                        average_score,
                        best_score,
                        last_submitted_at,
                        last_evaluated_at,
                        latest_answers,
                        latest_evaluation,
                        latest_score
                    FROM practice_history_overview
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                
                practices = []
                for row in cursor.fetchall():
                    practice = {
                        "id": row["practice_id"],
                        "timestamp": row["created_at"],
                        "status": row["status"],
                        "selected_text": (row["selected_text"] or "")[:200] + "..." if row["selected_text"] else "",
                        "has_evaluation": bool(row["latest_evaluation"]),
                        "has_submission": bool(row["latest_answers"]),
                        "topic": row["topic"],
                        "difficulty_level": row["difficulty_level"],
                        "total_submissions": row["total_submissions"] or 0,
                        "total_evaluations": row["total_evaluations"] or 0,
                        "latest_score": row["latest_score"],
                        "average_score": row["average_score"],
                        "best_score": row["best_score"]
                    }
                    practices.append(practice)
                
                self.logger.info(f"✅ 获取练习历史成功: {len(practices)} 条记录")
                return practices
                
        except Exception as e:
            self.logger.error(f"❌ 获取练习历史失败: {e}")
            return []
    
    def get_practice_detail(self, practice_id: str) -> Optional[Dict]:
        """
        获取练习详情
        
        Args:
            practice_id: 练习ID
            
        Returns:
            Optional[Dict]: 练习详情，不存在时返回None
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                
                # 获取练习基本信息
                cursor = conn.execute("""
                    SELECT * FROM practice_sessions WHERE practice_id = ?
                """, (practice_id,))
                
                session_row = cursor.fetchone()
                if not session_row:
                    return None
                
                # 获取最新的提交记录
                cursor = conn.execute("""
                    SELECT * FROM practice_submissions 
                    WHERE practice_id = ? 
                    ORDER BY submitted_at DESC LIMIT 1
                """, (practice_id,))
                
                submission_row = cursor.fetchone()
                
                # 获取最新的评估记录
                cursor = conn.execute("""
                    SELECT * FROM practice_evaluations 
                    WHERE practice_id = ? 
                    ORDER BY evaluated_at DESC LIMIT 1
                """, (practice_id,))
                
                evaluation_row = cursor.fetchone()
                
                # 组装结果
                practice_detail = {
                    "practice_id": session_row["practice_id"],
                    "selected_text": session_row["selected_text"],
                    "questions": session_row["questions"],
                    "user_answers": submission_row["user_answers"] if submission_row else "",
                    "evaluation_result": evaluation_row["evaluation_result"] if evaluation_row else "",
                    "timestamp": session_row["created_at"],
                    "status": session_row["status"],
                    "topic": session_row["topic"],
                    "difficulty_level": session_row["difficulty_level"],
                    "evaluation_score": evaluation_row["evaluation_score"] if evaluation_row else None
                }
                
                self.logger.info(f"✅ 获取练习详情成功: {practice_id}")
                return practice_detail
                
        except Exception as e:
            self.logger.error(f"❌ 获取练习详情失败: {e}")
            return None
    
    def migrate_from_json_files(self, json_dir: str) -> int:
        """
        从JSON文件迁移数据到数据库
        
        Args:
            json_dir: JSON文件目录
            
        Returns:
            int: 迁移的记录数
        """
        migrated_count = 0
        json_path = Path(json_dir)
        
        if not json_path.exists():
            self.logger.warning(f"⚠️ JSON目录不存在: {json_dir}")
            return 0
        
        try:
            for json_file in json_path.glob("practice_*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    practice_id = data.get("practice_id", "")
                    if not practice_id:
                        continue
                    
                    # 创建练习会话
                    self.create_practice_session(
                        practice_id=practice_id,
                        selected_text=data.get("selected_text", ""),
                        questions=data.get("questions", ""),
                        topic=data.get("topic", "")
                    )
                    
                    # 如果有答案，创建提交记录
                    if data.get("user_answers"):
                        submission_id = f"{practice_id}_submission"
                        self.submit_practice_answers(
                            practice_id=practice_id,
                            submission_id=submission_id,
                            user_answers=data.get("user_answers", "")
                        )
                        
                        # 如果有评估结果，创建评估记录
                        if data.get("evaluation_result"):
                            evaluation_id = f"{practice_id}_evaluation"
                            self.save_practice_evaluation(
                                practice_id=practice_id,
                                submission_id=submission_id,
                                evaluation_id=evaluation_id,
                                evaluation_result=data.get("evaluation_result", "")
                            )
                    
                    migrated_count += 1
                    self.logger.info(f"✅ 迁移记录: {json_file.name}")
                    
                except Exception as e:
                    self.logger.error(f"❌ 迁移文件失败 {json_file.name}: {e}")
                    continue
            
            self.logger.info(f"✅ 数据迁移完成: {migrated_count} 条记录")
            return migrated_count
            
        except Exception as e:
            self.logger.error(f"❌ 数据迁移失败: {e}")
            return migrated_count
    
    def get_practice_statistics(self) -> Dict:
        """
        获取练习统计信息
        
        Returns:
            Dict: 统计信息
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT 
                        COUNT(*) as total_practices,
                        COUNT(CASE WHEN status = 'evaluated' THEN 1 END) as evaluated_practices,
                        AVG(total_submissions) as avg_submissions_per_practice,
                        AVG(best_score) as avg_best_score
                    FROM practice_history_overview
                """)
                
                row = cursor.fetchone()
                
                stats = {
                    "total_practices": row[0] or 0,
                    "evaluated_practices": row[1] or 0,
                    "avg_submissions_per_practice": round(row[2] or 0, 2),
                    "avg_best_score": round(row[3] or 0, 2)
                }
                
                return stats
                
        except Exception as e:
            self.logger.error(f"❌ 获取统计信息失败: {e}")
            return {
                "total_practices": 0,
                "evaluated_practices": 0,
                "avg_submissions_per_practice": 0,
                "avg_best_score": 0
            }