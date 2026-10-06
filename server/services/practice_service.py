# -*- coding: utf-8 -*-

"""
练习服务模块
负责练习历史的数据库存储和查询。

- 连接统一走 database.db_adapter 适配层（PG 连接池 + 方言屏蔽）；
- 表结构由主库 schema 初始化（DatabaseManager）统一负责，本服务不重复建表；
- 所有查询/写入强制绑定 user_id。
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

import config
from database import db_adapter


class PracticeService:
    """练习服务类，负责练习数据的数据库操作（全部方法显式携带 user_id）"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or ""  # 保留字段兼容历史调用签名
        self.logger = logging.getLogger('PracticeService')
        self.logger.info("✅ 练习表由统一 schema 管理（PostgreSQL）")

    def _conn(self):
        return db_adapter.get_connection()


    def get_practice_history_list(self, user_id: str, limit: int = 50) -> Dict[str, Any]:
        """获取练习历史列表（当前用户）

        Args:
            user_id: 用户ID（隔离键）
            limit: 限制返回的数量

        Returns:
            包含练习历史列表的字典
        """
        conn = self._conn()
        try:
            cursor = conn.cursor()

            # 查询练习历史，按时间倒序，包含完整数据（包括answer_history）
            cursor.execute('''
                SELECT practice_id, timestamp, selected_text, questions, user_answers,
                       evaluation_result, answer_history, status,
                       CASE WHEN evaluation_result IS NOT NULL AND evaluation_result != '' 
                            THEN 1 ELSE 0 END as has_evaluation
                FROM practice_sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
            ''', (user_id, limit))

            rows = cursor.fetchall()

            practices = []
            for row in rows:
                practice_id, timestamp, selected_text, questions, user_answers, evaluation_result, answer_history, status, has_evaluation = row

                # 安全处理字段
                if selected_text is None:
                    selected_text = ""
                if questions is None:
                    questions = ""
                if user_answers is None:
                    user_answers = ""
                if evaluation_result is None:
                    evaluation_result = ""
                if answer_history is None:
                    answer_history = ""

                # 优先使用questions字段，回退到selected_text
                question_content = questions if questions else selected_text

                # 截取预览文本（120字符）
                text_preview = question_content[:120] if len(question_content) > 120 else question_content
                if len(question_content) > 120:
                    text_preview += "..."

                practices.append({
                    "id": practice_id,
                    "practice_id": practice_id,  # 兼容字段
                    "timestamp": timestamp,
                    "status": status or "unknown",
                    "selected_text": selected_text,  # 完整的原始学习材料内容
                    "selected_text_preview": text_preview,  # 预览文本（120字符）
                    "questions": questions,         # 完整题目内容
                    "question": questions,          # 兼容字段
                    "user_answers": user_answers,   # 用户答案
                    "answer": user_answers,         # 兼容字段
                    "evaluation_result": evaluation_result,  # 评估结果
                    "evaluation": evaluation_result,         # 兼容字段
                    "answer_history": answer_history,        # 答案历史 - 关键字段！
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
        finally:
            conn.close()

    def load_practice_detail(self, user_id: str, practice_id: str) -> Dict[str, Any]:
        """加载练习详情（仅本人记录）

        Args:
            user_id: 用户ID（隔离键）
            practice_id: 练习ID

        Returns:
            包含练习详情的字典
        """
        # 清理practice_id前缀
        clean_practice_id = practice_id
        if practice_id.startswith('practice_'):
            clean_practice_id = practice_id[9:]

        conn = self._conn()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT practice_id, timestamp, selected_text, questions,
                       user_answers, evaluation_result, answer_history, status
                FROM practice_sessions
                WHERE (practice_id = ? OR practice_id = ?) AND user_id = ?
            ''', (practice_id, clean_practice_id, user_id))

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
        finally:
            conn.close()

    def save_complete_practice_data(self, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """保存完整的练习数据（upsert，status=evaluated）

        Args:
            user_id: 用户ID（隔离键）
            data: 包含练习数据的字典

        Returns:
            保存结果
        """
        practice_id = data.get('practice_id')

        # 清理practice_id前缀
        if practice_id and practice_id.startswith('practice_'):
            practice_id = practice_id[9:]

        if not practice_id:
            practice_id = datetime.now().strftime('%Y%m%d_%H%M%S')

        conn = self._conn()
        try:
            cursor = conn.cursor()

            # 检查是否已存在（同用户内）
            cursor.execute('SELECT id FROM practice_sessions WHERE practice_id = ? AND user_id = ?', (practice_id, user_id))
            existing = cursor.fetchone()

            if existing:
                # 更新现有记录
                cursor.execute('''
                    UPDATE practice_sessions
                    SET selected_text = ?, questions = ?, user_answers = ?,
                        evaluation_result = ?, answer_history = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE practice_id = ? AND user_id = ?
                ''', (
                    data.get('selected_text', ''),
                    data.get('questions', ''),
                    data.get('user_answers', ''),
                    data.get('evaluation_result', ''),
                    data.get('answer_history', ''),
                    'evaluated',
                    practice_id,
                    user_id
                ))
                self.logger.info(f"✅ 更新练习记录: {practice_id}")
            else:
                # 插入新记录
                cursor.execute('''
                    INSERT INTO practice_sessions 
                    (practice_id, user_id, timestamp, selected_text, questions, user_answers, evaluation_result, answer_history, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    practice_id,
                    user_id,
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
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            conn.close()

    def migrate_from_json_files(self, user_id: str, json_dir: str) -> Dict[str, Any]:
        """从JSON文件迁移数据到数据库

        Args:
            user_id: 用户ID（隔离键）
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
                    result = self.save_complete_practice_data(user_id, practice_data)
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

    def save_practice_history(self, user_id: str, practice_data: Dict[str, Any]) -> Dict[str, Any]:
        """保存练习历史（用户提交答案时调用）

        Args:
            user_id: 用户ID（隔离键）
            practice_data: 练习数据，包含practice_id, questions, selected_text等
        Returns:
            Dict: 包含success状态和相关信息
        """
        conn = self._conn()
        try:
            cursor = conn.cursor()

            # 检查练习是否已存在（同用户内）
            cursor.execute(
                "SELECT id FROM practice_sessions WHERE practice_id = ? AND user_id = ?",
                (practice_data.get('practice_id'), user_id)
            )
            existing = cursor.fetchone()

            if existing:
                # 更新现有记录
                cursor.execute('''
                    UPDATE practice_sessions 
                    SET selected_text = ?, questions = ?, user_answers = ?, 
                        answer_history = ?, evaluation_result = ?,
                        status = 'submitted', updated_at = CURRENT_TIMESTAMP
                    WHERE practice_id = ? AND user_id = ?
                ''', (
                    practice_data.get('selected_text', ''),
                    practice_data.get('questions', ''),
                    practice_data.get('user_answers', ''),
                    practice_data.get('answer_history', ''),
                    practice_data.get('evaluation_result', ''),
                    practice_data.get('practice_id'),
                    user_id
                ))
                self.logger.info(f"✅ 更新练习历史: {practice_data.get('practice_id')}")
            else:
                # 插入新记录
                cursor.execute('''
                    INSERT INTO practice_sessions 
                    (practice_id, user_id, timestamp, selected_text, questions, user_answers, answer_history, evaluation_result, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'submitted')
                ''', (
                    practice_data.get('practice_id'),
                    user_id,
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
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            conn.close()

    def update_practice_evaluation(self, user_id: str, practice_id: str, evaluation_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新练习评估结果（AI评估完成时调用）

        Args:
            user_id: 用户ID（隔离键）
            practice_id: 练习ID
            evaluation_data: 评估数据，包含evaluation_result, score等
        Returns:
            Dict: 包含success状态和相关信息
        """
        conn = self._conn()
        try:
            cursor = conn.cursor()

            # 更新练习会话状态为已评估（仅限本人记录）
            cursor.execute('''
                UPDATE practice_sessions 
                SET evaluation_result = ?, answer_history = ?, status = 'evaluated', updated_at = CURRENT_TIMESTAMP
                WHERE practice_id = ? AND user_id = ?
            ''', (
                evaluation_data.get('evaluation_result', ''),
                evaluation_data.get('answer_history', ''),
                practice_id,
                user_id
            ))

            # 插入评估记录到评估表
            cursor.execute('''
                INSERT INTO practice_evaluations 
                (user_id, practice_id, evaluation_content, score)
                VALUES (?, ?, ?, ?)
            ''', (
                user_id,
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
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            conn.close()
