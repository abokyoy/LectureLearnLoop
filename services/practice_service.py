"""
练习历史业务逻辑层
负责处理练习相关的业务逻辑
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional
from dal.practice_dao import PracticeDAO


class PracticeService:
    """练习历史服务类"""
    
    def __init__(self, db_path: str = "practice_history.db"):
        """
        初始化练习服务
        
        Args:
            db_path: 数据库路径
        """
        self.dao = PracticeDAO(db_path)
        self.logger = logging.getLogger(__name__)
    
    def create_new_practice(self, selected_text: str, questions: str = None,
                          topic: str = None, difficulty_level: int = 1) -> str:
        """
        创建新的练习会话
        
        Args:
            selected_text: 选中文本
            questions: 练习题目
            topic: 练习主题
            difficulty_level: 难度等级
            
        Returns:
            str: 练习ID
        """
        try:
            # 生成练习ID
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            practice_id = f"practice_{timestamp}"
            
            # 从选中文本中提取主题（如果未提供）
            if not topic and selected_text:
                topic = self._extract_topic_from_text(selected_text)
            
            # 创建练习会话
            success = self.dao.create_practice_session(
                practice_id=practice_id,
                selected_text=selected_text,
                questions=questions,
                topic=topic,
                difficulty_level=difficulty_level
            )
            
            if success:
                self.logger.info(f"✅ 创建新练习成功: {practice_id}")
                return practice_id
            else:
                raise Exception("数据库操作失败")
                
        except Exception as e:
            self.logger.error(f"❌ 创建新练习失败: {e}")
            raise
    
    def submit_practice_answers(self, practice_id: str, user_answers: str,
                              time_spent: int = 0) -> str:
        """
        提交练习答案
        
        Args:
            practice_id: 练习ID
            user_answers: 用户答案
            time_spent: 答题用时
            
        Returns:
            str: 提交ID
        """
        try:
            # 生成提交ID
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            submission_id = f"{practice_id}_sub_{timestamp}"
            
            # 提交答案
            success = self.dao.submit_practice_answers(
                practice_id=practice_id,
                submission_id=submission_id,
                user_answers=user_answers,
                time_spent=time_spent
            )
            
            if success:
                self.logger.info(f"✅ 提交练习答案成功: {submission_id}")
                return submission_id
            else:
                raise Exception("数据库操作失败")
                
        except Exception as e:
            self.logger.error(f"❌ 提交练习答案失败: {e}")
            raise
    
    def save_evaluation_result(self, practice_id: str, submission_id: str,
                             evaluation_result: str, evaluation_score: float = None) -> str:
        """
        保存评估结果
        
        Args:
            practice_id: 练习ID
            submission_id: 提交ID
            evaluation_result: 评估结果
            evaluation_score: 评估分数
            
        Returns:
            str: 评估ID
        """
        try:
            # 生成评估ID
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            evaluation_id = f"{practice_id}_eval_{timestamp}"
            
            # 从评估结果中提取分数（如果未提供）
            if evaluation_score is None:
                evaluation_score = self._extract_score_from_result(evaluation_result)
            
            # 确定评估等级
            evaluation_level = self._determine_evaluation_level(evaluation_score)
            
            # 保存评估结果
            success = self.dao.save_practice_evaluation(
                practice_id=practice_id,
                submission_id=submission_id,
                evaluation_id=evaluation_id,
                evaluation_result=evaluation_result,
                evaluation_score=evaluation_score,
                evaluation_level=evaluation_level
            )
            
            if success:
                self.logger.info(f"✅ 保存评估结果成功: {evaluation_id}")
                return evaluation_id
            else:
                raise Exception("数据库操作失败")
                
        except Exception as e:
            self.logger.error(f"❌ 保存评估结果失败: {e}")
            raise
    
    def get_practice_history_list(self, limit: int = 50, offset: int = 0) -> Dict:
        """
        获取练习历史列表
        
        Args:
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            Dict: 包含练习历史列表的响应
        """
        try:
            practices = self.dao.get_practice_history(limit=limit, offset=offset)
            
            # 格式化时间显示
            for practice in practices:
                practice["formatted_time"] = self._format_timestamp(practice["timestamp"])
                practice["status_text"] = self._get_status_text(practice["status"])
            
            result = {
                "success": True,
                "practices": practices,
                "total": len(practices)
            }
            
            self.logger.info(f"✅ 获取练习历史列表成功: {len(practices)} 条")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ 获取练习历史列表失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "practices": []
            }
    
    def load_practice_detail(self, practice_id: str) -> Dict:
        """
        加载练习详情
        
        Args:
            practice_id: 练习ID
            
        Returns:
            Dict: 练习详情响应
        """
        try:
            # 清理practice_id前缀
            clean_practice_id = practice_id
            if practice_id.startswith('practice_'):
                clean_practice_id = practice_id[9:]
                practice_id = f"practice_{clean_practice_id}"
            
            practice_detail = self.dao.get_practice_detail(practice_id)
            
            if practice_detail:
                # 格式化时间显示
                practice_detail["formatted_time"] = self._format_timestamp(practice_detail["timestamp"])
                practice_detail["status_text"] = self._get_status_text(practice_detail["status"])
                
                result = {
                    "success": True,
                    "practice": practice_detail
                }
                
                self.logger.info(f"✅ 加载练习详情成功: {practice_id}")
                return result
            else:
                result = {
                    "success": False,
                    "error": f"练习记录不存在: {practice_id}"
                }
                
                self.logger.warning(f"⚠️ 练习记录不存在: {practice_id}")
                return result
                
        except Exception as e:
            self.logger.error(f"❌ 加载练习详情失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def save_complete_practice_data(self, practice_data: Dict) -> Dict:
        """
        保存完整的练习数据（包含会话、提交、评估）
        
        Args:
            practice_data: 完整的练习数据
            
        Returns:
            Dict: 保存结果响应
        """
        try:
            practice_id = practice_data.get("practice_id", "")
            if not practice_id:
                # 生成新的练习ID
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                practice_id = f"practice_{timestamp}"
                practice_data["practice_id"] = practice_id
            
            # 创建练习会话
            session_success = self.dao.create_practice_session(
                practice_id=practice_id,
                selected_text=practice_data.get("selected_text", ""),
                questions=practice_data.get("questions", ""),
                topic=practice_data.get("topic", "")
            )
            
            submission_id = None
            evaluation_id = None
            
            # 如果有用户答案，创建提交记录
            if practice_data.get("user_answers"):
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                submission_id = f"{practice_id}_sub_{timestamp}"
                
                submission_success = self.dao.submit_practice_answers(
                    practice_id=practice_id,
                    submission_id=submission_id,
                    user_answers=practice_data.get("user_answers", "")
                )
                
                # 如果有评估结果，创建评估记录
                if practice_data.get("evaluation_result") and submission_success:
                    evaluation_id = f"{practice_id}_eval_{timestamp}"
                    evaluation_score = self._extract_score_from_result(
                        practice_data.get("evaluation_result", "")
                    )
                    
                    self.dao.save_practice_evaluation(
                        practice_id=practice_id,
                        submission_id=submission_id,
                        evaluation_id=evaluation_id,
                        evaluation_result=practice_data.get("evaluation_result", ""),
                        evaluation_score=evaluation_score
                    )
            
            result = {
                "success": True,
                "message": "练习数据保存成功",
                "practice_id": practice_id,
                "submission_id": submission_id,
                "evaluation_id": evaluation_id
            }
            
            self.logger.info(f"✅ 保存完整练习数据成功: {practice_id}")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ 保存完整练习数据失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def migrate_from_json_files(self, json_dir: str = "practice_sessions") -> Dict:
        """
        从JSON文件迁移数据
        
        Args:
            json_dir: JSON文件目录
            
        Returns:
            Dict: 迁移结果
        """
        try:
            migrated_count = self.dao.migrate_from_json_files(json_dir)
            
            return {
                "success": True,
                "message": f"数据迁移完成，共迁移 {migrated_count} 条记录",
                "migrated_count": migrated_count
            }
            
        except Exception as e:
            self.logger.error(f"❌ 数据迁移失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "migrated_count": 0
            }
    
    def get_practice_statistics(self) -> Dict:
        """
        获取练习统计信息
        
        Returns:
            Dict: 统计信息
        """
        try:
            stats = self.dao.get_practice_statistics()
            
            return {
                "success": True,
                "statistics": stats
            }
            
        except Exception as e:
            self.logger.error(f"❌ 获取统计信息失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "statistics": {}
            }
    
    def _extract_topic_from_text(self, text: str) -> str:
        """从文本中提取主题"""
        if not text:
            return "未知主题"
        
        # 简单的主题提取逻辑，可以后续改进
        words = text.strip().split()[:5]
        return " ".join(words) + "..." if len(words) >= 5 else " ".join(words)
    
    def _extract_score_from_result(self, evaluation_result: str) -> Optional[float]:
        """从评估结果中提取分数"""
        if not evaluation_result:
            return None
        
        import re
        # 寻找类似 "85分" 或 "score: 85" 的模式
        patterns = [
            r'(\d+)分',
            r'得分[：:]\s*(\d+)',
            r'score[：:]\s*(\d+)',
            r'(\d+)/100'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, evaluation_result, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        
        return None
    
    def _determine_evaluation_level(self, score: Optional[float]) -> str:
        """根据分数确定评估等级"""
        if score is None:
            return "unknown"
        
        if score >= 90:
            return "excellent"
        elif score >= 80:
            return "good"
        elif score >= 60:
            return "fair"
        else:
            return "poor"
    
    def _format_timestamp(self, timestamp: str) -> str:
        """格式化时间戳"""
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M')
        except:
            return timestamp
    
    def _get_status_text(self, status: str) -> str:
        """获取状态文本"""
        status_map = {
            "created": "已创建",
            "submitted": "已提交",
            "evaluated": "已评估"
        }
        return status_map.get(status, status)