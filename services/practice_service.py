# -*- coding: utf-8 -*-

"""
练习服务模块
负责练习历史的数据库存储和查询
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

class PracticeService:
    """练习服务类，负责练习数据的数据库操作"""
    
    def __init__(self, db_path: str = "practice_data.db"):
        """初始化练习服务
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.logger = logging.getLogger('PracticeService')
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表结构"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 创建练习会话表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS practice_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        practice_id TEXT UNIQUE NOT NULL,
                        timestamp TEXT NOT NULL,
                        selected_text TEXT,
                        questions TEXT,
                        user_answers TEXT,
                        evaluation_result TEXT,
                        answer_history TEXT,
                        status TEXT DEFAULT 'created',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 检查并添加 answer_history 字段（用于已存在的数据库）
                try:
                    cursor.execute("ALTER TABLE practice_sessions ADD COLUMN answer_history TEXT")
                    self.logger.info("✅ 成功添加 answer_history 字段")
                except sqlite3.OperationalError as e:
                    if "duplicate column name" in str(e).lower():
                        self.logger.info("ℹ️ answer_history 字段已存在")
                    else:
                        self.logger.warning(f"⚠️ 添加 answer_history 字段时出现问题: {e}")
                
                # 创建练习提交表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS practice_submissions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        practice_id TEXT NOT NULL,
                        submission_content TEXT,
                        submission_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (practice_id) REFERENCES practice_sessions (practice_id)
                    )
                ''')
                
                # 创建练习评估表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS practice_evaluations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        practice_id TEXT NOT NULL,
                        evaluation_content TEXT,
                        score REAL,
                        evaluation_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (practice_id) REFERENCES practice_sessions (practice_id)
                    )
                ''')
                
                # 创建练习统计表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS practice_statistics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        practice_id TEXT NOT NULL,
                        total_questions INTEGER DEFAULT 0,
                        correct_answers INTEGER DEFAULT 0,
                        completion_time REAL DEFAULT 0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (practice_id) REFERENCES practice_sessions (practice_id)
                    )
                ''')
                
                conn.commit()
                self.logger.info("✅ 数据库表结构初始化完成")
                
        except Exception as e:
            self.logger.error(f"❌ 数据库初始化失败: {e}")
            raise
    
    def get_practice_history_list(self, limit: int = 50) -> Dict[str, Any]:
        """获取练习历史列表
        
        Args:
            limit: 限制返回的数量
            
        Returns:
            包含练习历史列表的字典
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 查询练习历史，按时间倒序，包含questions字段
                cursor.execute('''
                    SELECT practice_id, timestamp, selected_text, questions, status,
                           CASE WHEN evaluation_result IS NOT NULL AND evaluation_result != '' 
                                THEN 1 ELSE 0 END as has_evaluation
                    FROM practice_sessions
                    ORDER BY updated_at DESC
                    LIMIT ?
                ''', (limit,))
                
                rows = cursor.fetchall()
                
                practices = []
                for row in rows:
                    practice_id, timestamp, selected_text, questions, status, has_evaluation = row
                    
                    # 安全处理字段
                    if selected_text is None:
                        selected_text = ""
                    if questions is None:
                        questions = ""
                    
                    # 优先使用questions字段，回退到selected_text
                    question_content = questions if questions else selected_text
                    
                    # 截取预览文本（120字符）
                    text_preview = question_content[:120] if len(question_content) > 120 else question_content
                    if len(question_content) > 120:
                        text_preview += "..."
                    
                    practices.append({
                        "id": practice_id,
                        "timestamp": timestamp,
                        "status": status or "unknown",
                        "selected_text": text_preview,  # 保持兼容性
                        "questions": questions,         # 新增字段
                        "has_evaluation": bool(has_evaluation)
                    })
                
                self.logger.info(f"✅ 从数据库获取练习历史: {len(practices)} 条")
                
                return {
                    "success": True,
                    "practices": practices
                }
                
        except Exception as e:
            self.logger.error(f"❌ 获取练习历史列表失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def load_practice_detail(self, practice_id: str) -> Dict[str, Any]:
        """加载练习详情
        
        Args:
            practice_id: 练习ID
            
        Returns:
            包含练习详情的字典
        """
        try:
            # 清理practice_id前缀
            clean_practice_id = practice_id
            if practice_id.startswith('practice_'):
                clean_practice_id = practice_id[9:]
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 查询练习详情
                cursor.execute('''
                    SELECT practice_id, timestamp, selected_text, questions,
                           user_answers, evaluation_result, answer_history, status
                    FROM practice_sessions
                    WHERE practice_id = ? OR practice_id = ?
                ''', (practice_id, clean_practice_id))
                
                row = cursor.fetchone()
                
                if row:
                    practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, answer_history, status = row
                    
                    practice_detail = {
                        "practice_id": practice_id,
                        "timestamp": timestamp,
                        "selected_text": selected_text or "",
                        "questions": questions or "",
                        "user_answers": user_answers or "",
                        "evaluation_result": evaluation_result or "",
                        "answer_history": answer_history or "",
                        "status": status or "unknown"
                    }
                    
                    self.logger.info(f"✅ 成功加载练习详情: {practice_id}")
                    
                    return {
                        "success": True,
                        "practice": practice_detail
                    }
                else:
                    error_msg = f"练习记录不存在: {practice_id}"
                    self.logger.warning(f"⚠️ {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }
                    
        except Exception as e:
            self.logger.error(f"❌ 加载练习详情失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def save_complete_practice_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """保存完整的练习数据
        
        Args:
            data: 包含练习数据的字典
            
        Returns:
            保存结果
        """
        try:
            practice_id = data.get('practice_id')
            
            # 清理practice_id前缀
            if practice_id and practice_id.startswith('practice_'):
                practice_id = practice_id[9:]
            
            if not practice_id:
                practice_id = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 检查是否已存在
                cursor.execute('SELECT id FROM practice_sessions WHERE practice_id = ?', (practice_id,))
                existing = cursor.fetchone()
                
                if existing:
                    # 更新现有记录
                    cursor.execute('''
                        UPDATE practice_sessions
                        SET selected_text = ?, questions = ?, user_answers = ?,
                            evaluation_result = ?, answer_history = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE practice_id = ?
                    ''', (
                        data.get('selected_text', ''),
                        data.get('questions', ''),
                        data.get('user_answers', ''),
                        data.get('evaluation_result', ''),
                        data.get('answer_history', ''),
                        'evaluated',
                        practice_id
                    ))
                    self.logger.info(f"✅ 更新练习记录: {practice_id}")
                else:
                    # 插入新记录
                    cursor.execute('''
                        INSERT INTO practice_sessions 
                        (practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, answer_history, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        practice_id,
                        datetime.now().isoformat(),
                        data.get('selected_text', ''),
                        data.get('questions', ''),
                        data.get('user_answers', ''),
                        data.get('evaluation_result', ''),
                        data.get('answer_history', ''),
                        'evaluated'
                    ))
                    self.logger.info(f"✅ 插入新练习记录: {practice_id}")
                
                conn.commit()
                
                return {
                    "success": True,
                    "message": "练习数据保存成功",
                    "practice_id": practice_id
                }
                
        except Exception as e:
            self.logger.error(f"❌ 保存练习数据失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def migrate_from_json_files(self, json_dir: str) -> Dict[str, Any]:
        """从JSON文件迁移数据到数据库
        
        Args:
            json_dir: JSON文件目录
            
        Returns:
            迁移结果
        """
        try:
            if not os.path.exists(json_dir):
                return {"success": True, "message": "JSON目录不存在，无需迁移"}
            
            json_files = [f for f in os.listdir(json_dir) if f.endswith('.json') and 'practice' in f]
            
            migrated_count = 0
            
            for filename in json_files:
                filepath = os.path.join(json_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        practice_data = json.load(f)
                    
                    # 保存到数据库
                    result = self.save_complete_practice_data(practice_data)
                    if result["success"]:
                        migrated_count += 1
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ 迁移文件失败 {filename}: {e}")
                    continue
            
            self.logger.info(f"✅ 数据迁移完成，成功迁移 {migrated_count} 条记录")
            
            return {
                "success": True,
                "message": f"成功迁移 {migrated_count} 条记录",
                "migrated_count": migrated_count
            }
            
        except Exception as e:
            self.logger.error(f"❌ 数据迁移失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def save_practice_history(self, practice_data: Dict[str, Any]) -> Dict[str, Any]:
        """保存练习历史（用户提交答案时调用）
        
        Args:
            practice_data: 练习数据，包含practice_id, questions, selected_text等
        Returns:
            Dict: 包含success状态和相关信息
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 检查练习是否已存在
                cursor.execute(
                    "SELECT id FROM practice_sessions WHERE practice_id = ?",
                    (practice_data.get('practice_id'),)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # 更新现有记录
                    cursor.execute('''
                        UPDATE practice_sessions 
                        SET selected_text = ?, questions = ?, user_answers = ?, 
                            answer_history = ?, evaluation_result = ?,
                            status = 'submitted', updated_at = CURRENT_TIMESTAMP
                        WHERE practice_id = ?
                    ''', (
                        practice_data.get('selected_text', ''),
                        practice_data.get('questions', ''),
                        practice_data.get('user_answers', ''),
                        practice_data.get('answer_history', ''),
                        practice_data.get('evaluation_result', ''),
                        practice_data.get('practice_id')
                    ))
                    self.logger.info(f"✅ 更新练习历史: {practice_data.get('practice_id')}")
                else:
                    # 插入新记录
                    cursor.execute('''
                        INSERT INTO practice_sessions 
                        (practice_id, timestamp, selected_text, questions, user_answers, answer_history, evaluation_result, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted')
                    ''', (
                        practice_data.get('practice_id'),
                        practice_data.get('timestamp', datetime.now().isoformat()),
                        practice_data.get('selected_text', ''),
                        practice_data.get('questions', ''),
                        practice_data.get('user_answers', ''),
                        practice_data.get('answer_history', ''),
                        practice_data.get('evaluation_result', ''),
                    ))
                    self.logger.info(f"✅ 保存新练习历史: {practice_data.get('practice_id')}")
                
                conn.commit()
                
                return {
                    "success": True,
                    "message": "练习历史保存成功",
                    "practice_id": practice_data.get('practice_id')
                }
                
        except Exception as e:
            self.logger.error(f"❌ 保存练习历史失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def update_practice_evaluation(self, practice_id: str, evaluation_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新练习评估结果（AI评估完成时调用）
        
        Args:
            practice_id: 练习ID
            evaluation_data: 评估数据，包含evaluation_result, score等
        Returns:
            Dict: 包含success状态和相关信息
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 更新练习会话状态为已评估
                cursor.execute('''
                    UPDATE practice_sessions 
                    SET evaluation_result = ?, answer_history = ?, status = 'evaluated', updated_at = CURRENT_TIMESTAMP
                    WHERE practice_id = ?
                ''', (
                    evaluation_data.get('evaluation_result', ''),
                    evaluation_data.get('answer_history', ''),
                    practice_id
                ))
                
                # 插入评估记录到评估表
                cursor.execute('''
                    INSERT INTO practice_evaluations 
                    (practice_id, evaluation_content, score)
                    VALUES (?, ?, ?)
                ''', (
                    practice_id,
                    evaluation_data.get('evaluation_result', ''),
                    evaluation_data.get('score', 0)
                ))
                
                conn.commit()
                self.logger.info(f"✅ 更新练习评估: {practice_id}, 得分: {evaluation_data.get('score', 'N/A')}")
                
                return {
                    "success": True,
                    "message": "练习评估更新成功",
                    "practice_id": practice_id
                }
                
        except Exception as e:
            self.logger.error(f"❌ 更新练习评估失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }