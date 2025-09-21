"""
练习结果与知识管理系统集成模块
自动分析练习题目，关联知识点，保存练习记录和错题
"""

import json
import re
from typing import List, Dict, Optional, Tuple
from knowledge_management import KnowledgeManagementSystem
import requests


class PracticeAnalyzer:
    """练习分析器 - 分析练习题目并关联知识点"""
    
    def __init__(self, config: dict):
        self.config = config
        self.km_system = KnowledgeManagementSystem(config)
    
    def analyze_practice_results(self, practice_content: str, evaluation_result: str, 
                               subject_name: str = None) -> List[Dict]:
        """
        分析练习结果，提取每道题目及其对应的知识点
        
        Args:
            practice_content: 练习内容（题目+用户答案）
            evaluation_result: AI评估结果
            subject_name: 学科名称（可选，如果未提供则尝试从内容推断）
        
        Returns:
            List[Dict]: 每道题目的分析结果
        """
        try:
            # 1. 解析题目和答案
            questions_and_answers = self._parse_questions_and_answers(practice_content)
            
            # 2. 解析评估结果中的正误判断
            correctness_results = self._parse_evaluation_correctness(evaluation_result)
            
            # 3. 如果没有提供学科，尝试推断
            if not subject_name:
                subject_name = self._infer_subject(practice_content)
            
            # 4. 为每道题目匹配知识点
            analyzed_results = []
            for i, (question, user_answer) in enumerate(questions_and_answers):
                # 获取该题的正误判断
                is_correct = correctness_results.get(i, True)  # 默认正确
                
                # 匹配知识点
                knowledge_point_id = self._match_knowledge_point(question, subject_name)
                
                analyzed_results.append({
                    "question_index": i,
                    "question_content": question,
                    "user_answer": user_answer,
                    "is_correct": is_correct,
                    "subject_name": subject_name,
                    "knowledge_point_id": knowledge_point_id
                })
            
            return analyzed_results
            
        except Exception as e:
            print(f"分析练习结果失败: {e}")
            return []
    
    def _parse_questions_and_answers(self, practice_content: str) -> List[Tuple[str, str]]:
        """解析练习内容中的题目和用户答案"""
        questions_and_answers = []
        
        # 尝试多种解析模式
        patterns = [
            # 模式1: 题目X: ... 答案: ...
            r'题目\s*(\d+)[：:]\s*(.*?)\n.*?答案[：:]\s*(.*?)(?=\n题目|\n\n|$)',
            # 模式2: X. ... 我的答案: ...
            r'(\d+)\.\s*(.*?)\n.*?我的答案[：:]\s*(.*?)(?=\n\d+\.|\n\n|$)',
            # 模式3: 问题X ... 回答: ...
            r'问题\s*(\d+)[：:]?\s*(.*?)\n.*?回答[：:]\s*(.*?)(?=\n问题|\n\n|$)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, practice_content, re.DOTALL | re.IGNORECASE)
            if matches:
                for match in matches:
                    if len(match) >= 3:
                        question = match[1].strip()
                        answer = match[2].strip()
                        if question and answer:
                            questions_and_answers.append((question, answer))
                break
        
        # 如果没有匹配到，尝试简单分割
        if not questions_and_answers:
            lines = practice_content.split('\n')
            current_question = ""
            current_answer = ""
            in_answer = False
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                if re.match(r'^\d+[\.、]', line) or line.startswith('题目'):
                    if current_question and current_answer:
                        questions_and_answers.append((current_question, current_answer))
                    current_question = line
                    current_answer = ""
                    in_answer = False
                elif '答案' in line or '回答' in line or in_answer:
                    in_answer = True
                    if '答案' in line or '回答' in line:
                        current_answer = line.split(':', 1)[-1].split('：', 1)[-1].strip()
                    else:
                        current_answer += " " + line
            
            if current_question and current_answer:
                questions_and_answers.append((current_question, current_answer))
        
        return questions_and_answers
    
    def _parse_evaluation_correctness(self, evaluation_result: str) -> Dict[int, bool]:
        """解析评估结果中的正误判断"""
        correctness = {}
        
        # 查找正误标记的模式
        patterns = [
            r'题目\s*(\d+)[：:].*?([正确错误✓✗对错])',
            r'第\s*(\d+)\s*题.*?([正确错误✓✗对错])',
            r'(\d+)[\.、]\s*.*?([正确错误✓✗对错])',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, evaluation_result, re.IGNORECASE)
            for match in matches:
                try:
                    question_num = int(match[0]) - 1  # 转换为0基索引
                    result_text = match[1]
                    
                    # 判断正误
                    is_correct = any(word in result_text for word in ['正确', '✓', '对'])
                    correctness[question_num] = is_correct
                except:
                    continue
        
        return correctness
    
    def _infer_subject(self, practice_content: str) -> str:
        """从练习内容推断学科"""
        # 学科关键词映射
        subject_keywords = {
            "机器学习": ["机器学习", "深度学习", "神经网络", "算法", "模型", "训练", "梯度", "损失函数"],
            "Python编程": ["python", "编程", "代码", "函数", "类", "模块", "库", "语法"],
            "数据结构": ["数据结构", "算法", "链表", "树", "图", "排序", "查找", "复杂度"],
            "数学": ["数学", "微积分", "线性代数", "概率", "统计", "函数", "方程", "矩阵"],
            "计算机网络": ["网络", "协议", "TCP", "HTTP", "IP", "路由", "交换", "OSI"],
        }
        
        content_lower = practice_content.lower()
        
        for subject, keywords in subject_keywords.items():
            if any(keyword.lower() in content_lower for keyword in keywords):
                return subject
        
        return "通用学科"  # 默认学科
    
    def _match_knowledge_point(self, question: str, subject_name: str) -> Optional[int]:
        """为题目匹配最相关的知识点"""
        try:
            # 获取该学科下的所有知识点
            knowledge_points = self.km_system.get_knowledge_points_by_subject(subject_name)
            
            if not knowledge_points:
                return None
            
            # 使用AI匹配最相关的知识点
            best_match_id = self._ai_match_knowledge_point(question, knowledge_points)
            
            return best_match_id
            
        except Exception as e:
            print(f"匹配知识点失败: {e}")
            return None
    
    def _ai_match_knowledge_point(self, question: str, knowledge_points: List[Dict]) -> Optional[int]:
        """使用AI匹配最相关的知识点"""
        if not knowledge_points:
            return None
        
        # 构建知识点列表
        points_text = "\n".join([
            f"{i+1}. {point['point_name']} - {point['core_description']}"
            for i, point in enumerate(knowledge_points)
        ])
        
        prompt = f"""请分析以下题目，从给定的知识点列表中选择最相关的一个。

题目：{question}

知识点列表：
{points_text}

请只返回最相关知识点的序号（1-{len(knowledge_points)}），如果都不相关请返回0。"""

        try:
            api_key = self.config.get("gemini_api_key", "")
            if not api_key:
                return knowledge_points[0]["id"]  # 默认返回第一个
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "topK": 10,
                    "topP": 0.8,
                    "maxOutputTokens": 50,
                }
            }
            
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    
                    # 提取数字
                    import re
                    numbers = re.findall(r'\d+', content)
                    if numbers:
                        index = int(numbers[0]) - 1  # 转换为0基索引
                        if 0 <= index < len(knowledge_points):
                            return knowledge_points[index]["id"]
            
            # 默认返回第一个知识点
            return knowledge_points[0]["id"]
            
        except Exception as e:
            print(f"AI匹配知识点失败: {e}")
            return knowledge_points[0]["id"] if knowledge_points else None
    
    def save_practice_results(self, analyzed_results: List[Dict]) -> List[int]:
        """保存练习结果到知识管理系统"""
        saved_record_ids = []
        
        for result in analyzed_results:
            if result["knowledge_point_id"]:
                try:
                    record_id = self.km_system.save_practice_results([{
                        "subject_name": result["subject_name"],
                        "knowledge_point_id": result["knowledge_point_id"],
                        "question_content": result["question_content"],
                        "user_answer": result["user_answer"],
                        "is_correct": result["is_correct"]
                    }])
                    
                    if record_id:
                        saved_record_ids.extend(record_id)
                        
                except Exception as e:
                    print(f"保存练习记录失败: {e}")
        
        return saved_record_ids


class EnhancedPracticePanel:
    """增强的练习面板集成类"""
    
    def __init__(self, config: dict):
        self.config = config
        self.analyzer = PracticeAnalyzer(config)
    
    def process_completed_practice(self, practice_content: str, evaluation_result: str, 
                                 subject_name: str = None) -> Dict:
        """
        处理完成的练习，自动分析并保存到知识管理系统
        
        Returns:
            Dict: 处理结果统计
        """
        try:
            # 分析练习结果
            analyzed_results = self.analyzer.analyze_practice_results(
                practice_content, evaluation_result, subject_name
            )
            
            if not analyzed_results:
                return {"success": False, "message": "无法解析练习内容"}
            
            # 保存到知识管理系统
            saved_record_ids = self.analyzer.save_practice_results(analyzed_results)
            
            # 统计结果
            total_questions = len(analyzed_results)
            correct_count = sum(1 for r in analyzed_results if r["is_correct"])
            error_count = total_questions - correct_count
            saved_count = len(saved_record_ids)
            
            return {
                "success": True,
                "total_questions": total_questions,
                "correct_count": correct_count,
                "error_count": error_count,
                "saved_records": saved_count,
                "analyzed_results": analyzed_results,
                "message": f"成功处理 {total_questions} 道题目，其中 {error_count} 道错题已保存到知识库"
            }
            
        except Exception as e:
            return {"success": False, "message": f"处理练习失败: {e}"}


def integrate_with_practice_panel():
    """
    集成函数 - 在现有练习面板中调用此函数来启用知识管理集成
    
    使用方法：
    在 practice_panel.py 的 _on_evaluation_ready 方法中添加：
    
    from practice_integration import integrate_with_practice_panel
    
    # 在评估完成后调用
    integration_result = integrate_with_practice_panel()
    if integration_result["success"]:
        print(integration_result["message"])
    """
    pass  # 这个函数将在实际集成时实现
