"""
个性化学习系统 - 知识点与错题管理模块
包含数据库模型、知识点提取、错题管理等核心功能
"""

import sqlite3
import json
import requests
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from llm_logger import log_gemini_call
from dataclasses import dataclass


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, db_path: str = "knowledge_management.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 用户学科表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '0001',
                subject_name TEXT NOT NULL,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, subject_name)
            )
        ''')
        
        # 知识点表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '0001',
                subject_name TEXT NOT NULL,
                point_name TEXT NOT NULL,
                core_description TEXT NOT NULL,
                mastery_score INTEGER DEFAULT 50,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id, subject_name) REFERENCES user_subjects (user_id, subject_name)
            )
        ''')
        
        # 练习记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS practice_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '0001',
                subject_name TEXT NOT NULL,
                knowledge_point_id INTEGER NOT NULL,
                question_content TEXT NOT NULL,
                user_answer TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                practice_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points (id)
            )
        ''')
        
        # 错题表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS error_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '0001',
                subject_name TEXT NOT NULL,
                knowledge_point_id INTEGER NOT NULL,
                practice_record_id INTEGER NOT NULL,
                review_status INTEGER DEFAULT 0,
                current_proficiency INTEGER DEFAULT 20,
                correct_answer TEXT DEFAULT NULL,
                explanation TEXT DEFAULT NULL,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points (id),
                FOREIGN KEY (practice_record_id) REFERENCES practice_records (id)
            )
        ''')

        # 轻量级迁移：为已存在的表增加新列（如果缺失）
        try:
            cursor.execute("ALTER TABLE error_questions ADD COLUMN current_proficiency INTEGER DEFAULT 20")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE error_questions ADD COLUMN correct_answer TEXT DEFAULT NULL")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE error_questions ADD COLUMN explanation TEXT DEFAULT NULL")
        except Exception:
            pass

        # 错题熟练度历史表（时间序列）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS error_proficiency_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_question_id INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                proficiency INTEGER NOT NULL,
                FOREIGN KEY (error_question_id) REFERENCES error_questions (id)
            )
        ''')

        # 收藏题目表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS favorite_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '0001',
                subject_name TEXT NOT NULL,
                knowledge_point_id INTEGER NOT NULL,
                question_content TEXT NOT NULL,
                correct_answer TEXT DEFAULT NULL,
                explanation TEXT DEFAULT NULL,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    # 注意：与错题相关的业务方法在 ErrorQuestionManager 中实现


class SubjectManager:
    """学科管理器"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def get_user_subjects(self, user_id: str = "0001") -> List[str]:
        """获取用户所有学科"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT subject_name FROM user_subjects WHERE user_id = ? ORDER BY created_time DESC",
            (user_id,)
        )
        subjects = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return subjects
    
    def add_subject(self, subject_name: str, user_id: str = "0001") -> bool:
        """添加新学科"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "INSERT INTO user_subjects (user_id, subject_name) VALUES (?, ?)",
                (user_id, subject_name)
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            # 学科已存在
            conn.close()
            return False

    def update_error_kp(self, error_question_id: int, new_kp_id: int) -> bool:
        """更新错题的知识点归属。"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE error_questions SET knowledge_point_id = ? WHERE id = ?",
                (int(new_kp_id), int(error_question_id))
            )
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return success
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return False


class KnowledgePointManager:
    """知识点管理器"""
    
    def __init__(self, db_manager: DatabaseManager, config: dict):
        self.db_manager = db_manager
        self.config = config
    
    def extract_knowledge_points(self, subject_name: str, note_content: str) -> List[Dict]:
        """从笔记中提取学科核心概念"""
        prompt = f"""请从提供的**{subject_name}学习材料**中，仅提取该学科的**核心概念**，提取需严格遵循以下规则：

学习材料：
{note_content}

提取规则：
1. 概念范围：仅选取材料中涉及的学科核心术语、关键原理或基础方法论（例如：若为数学则可能是"微积分基本定理""矩阵秩"，若为物理则可能是"牛顿第二定律""楞次定律"，若为计算机则可能是"过拟合""HTTP协议"），排除案例、数据、公式推导、代码片段及概念的延伸解释内容。

2. 呈现形式：每个概念需以"概念术语 + 1-2句精准核心定义"格式呈现，定义仅提炼该概念最本质、最基础的内涵，不添加额外扩展说明。

3. 数量控制：若材料篇幅较短（如单篇知识点讲解），概念数量控制在1-7个以内；若材料篇幅较长（如章节内容），概念数量不超过8个，优先保留材料中反复提及或作为逻辑起点的核心概念。

请按以下JSON格式输出：
[
    {{"concept_name": "概念术语", "core_definition": "1-2句精准核心定义"}},
    {{"concept_name": "概念术语", "core_definition": "1-2句精准核心定义"}}
]"""

        # 根据用户配置选择模型
        llm_provider = self.config.get("llm_provider", "DeepSeek")
        print(f"[模型选择] 用户配置的LLM提供商: {llm_provider}")
        
        if llm_provider == "DeepSeek":
            print(f"[模型选择] 使用DeepSeek模型: {self.config.get('deepseek_model', 'deepseek-chat')}")
            try:
                return self._extract_with_deepseek(prompt)
            except Exception as deepseek_error:
                print(f"[LLM调用] DeepSeek API失败: {deepseek_error}")
                print(f"[模型选择] DeepSeek失败，尝试Gemini作为备用")
                try:
                    return self._extract_with_gemini(prompt)
                except Exception as gemini_error:
                    print(f"[LLM调用] Gemini API也失败: {gemini_error}")
                    print(f"[模型选择] Gemini失败，尝试Ollama作为备用")
                    try:
                        return self._extract_with_ollama(prompt)
                    except Exception as ollama_error:
                        print(f"[LLM调用] Ollama API也失败: {ollama_error}")
                        return self._extract_with_rules(subject_name, note_content)
        elif llm_provider == "Gemini":
            print(f"[模型选择] 使用Gemini模型: {self.config.get('gemini_model', 'gemini-1.5-flash-latest')}")
            try:
                return self._extract_with_gemini(prompt)
            except Exception as gemini_error:
                print(f"[LLM调用] Gemini API失败: {gemini_error}")
                print(f"[模型选择] Gemini失败，尝试Ollama作为备用")
                try:
                    return self._extract_with_ollama(prompt)
                except Exception as ollama_error:
                    print(f"[LLM调用] Ollama API也失败: {ollama_error}")
                    return self._extract_with_rules(subject_name, note_content)
        else:
            print(f"[模型选择] 使用Ollama模型: {self.config.get('ollama_model', 'deepseek-coder')}")
            try:
                return self._extract_with_ollama(prompt)
            except Exception as ollama_error:
                print(f"[LLM调用] Ollama API失败: {ollama_error}")
                print(f"[模型选择] Ollama失败，尝试Gemini作为备用")
                try:
                    return self._extract_with_gemini(prompt)
                except Exception as gemini_error:
                    print(f"[LLM调用] Gemini API也失败: {gemini_error}")
                    return self._extract_with_rules(subject_name, note_content)
    
    def _extract_with_deepseek(self, prompt: str) -> List[Dict]:
        """使用DeepSeek API提取知识点"""
        try:
            # 调用DeepSeek API
            api_key = self.config.get("deepseek_api_key", "")
            if not api_key:
                error_msg = "未配置DeepSeek API密钥"
                from llm_logger import log_ollama_call
                log_ollama_call("extract_knowledge_points", "deepseek-chat", prompt, error=error_msg)
                raise Exception(error_msg)
            
            # 使用用户配置的DeepSeek模型
            deepseek_model = self.config.get("deepseek_model", "deepseek-chat")
            deepseek_url = self.config.get("deepseek_api_url", "https://api.deepseek.com/v1/chat/completions")
            print(f"[模型调用] 实际调用的DeepSeek模型: {deepseek_model}")
            
            payload = {
                "model": deepseek_model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 2048,
                "stream": False
            }
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            start_time = time.time()
            
            # 记录请求开始
            print(f"[LLM调用] 开始调用DeepSeek API提取知识点")
            print(f"[LLM调用] 输入prompt长度: {len(prompt)}")
            print(f"[LLM调用] 输入内容: {prompt[:500]}...")
            
            response = requests.post(deepseek_url, json=payload, headers=headers, timeout=60)
            response_time = time.time() - start_time
            
            print(f"[LLM调用] API响应状态码: {response.status_code}")
            print(f"[LLM调用] 响应时间: {response_time:.2f}秒")
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                print(f"[LLM调用] DeepSeek原始响应内容: {content[:500]}...")
                
                # 记录成功的API调用
                from llm_logger import log_ollama_call
                log_ollama_call("extract_knowledge_points", deepseek_model, prompt, content, response_time=response_time)
                
                # 解析JSON响应
                return self._parse_json_response(content)
                
            else:
                error_msg = f"DeepSeek API调用失败: {response.status_code} - {response.text}"
                from llm_logger import log_ollama_call
                log_ollama_call("extract_knowledge_points", deepseek_model, prompt, error=error_msg, response_time=response_time)
                raise Exception(error_msg)
                
        except Exception as e:
            print(f"[LLM调用] DeepSeek API调用异常: {e}")
            raise

    def _extract_with_gemini(self, prompt: str) -> List[Dict]:
        """使用Gemini API提取知识点"""
        try:
            # 调用Gemini API
            api_key = self.config.get("gemini_api_key", "")
            if not api_key:
                error_msg = "未配置Gemini API密钥"
                log_gemini_call("extract_knowledge_points", prompt, error=error_msg)
                raise Exception(error_msg)
            
            # 使用用户配置的Gemini模型
            gemini_model = self.config.get("gemini_model", "gemini-1.5-flash-latest")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
            print(f"[模型调用] 实际调用的Gemini模型: {gemini_model}")
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.3,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 2048,
                }
            }
            
            headers = {"Content-Type": "application/json"}
            start_time = time.time()
            
            # 记录请求开始
            print(f"[LLM调用] 开始调用Gemini API提取知识点")
            print(f"[LLM调用] 输入prompt长度: {len(prompt)}")
            print(f"[LLM调用] 输入内容: {prompt[:500]}...")
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response_time = time.time() - start_time
            
            print(f"[LLM调用] API响应状态码: {response.status_code}")
            print(f"[LLM调用] 响应时间: {response_time:.2f}秒")
            
            if response.status_code == 200:
                data = response.json()
                print(f"[LLM调用] 响应数据结构: {list(data.keys())}")
                
                # 检查是否有错误信息
                if "error" in data:
                    error_info = data["error"]
                    error_msg = f"Gemini API错误: {error_info.get('message', '未知错误')}"
                    if "QUOTA_EXCEEDED" in str(error_info):
                        error_msg += " (配额已用完，请检查API使用限制)"
                    print(f"[LLM调用] {error_msg}")
                    log_gemini_call("extract_knowledge_points", prompt, error=error_msg, response_time=response_time)
                    raise Exception(error_msg)
                
                if "candidates" in data and len(data["candidates"]) > 0:
                    content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    print(f"[LLM调用] 原始响应内容: {content}")
                    
                    # 记录成功的API调用
                    log_gemini_call("extract_knowledge_points", prompt, content, 
                                  response_time=response_time, config=payload["generationConfig"])
                    
                    # 尝试解析JSON
                    try:
                        # 清理可能的markdown格式
                        content = content.strip()
                        if content.startswith("```json"):
                            content = content[7:]
                        if content.endswith("```"):
                            content = content[:-3]
                        content = content.strip()
                        
                        print(f"[LLM调用] 清理后的JSON内容: {content}")
                        
                        concepts = json.loads(content)
                        print(f"[LLM调用] 解析成功，提取到 {len(concepts)} 个核心概念")
                        
                        # 转换为统一的数据格式（保持向后兼容）
                        knowledge_points = []
                        for concept in concepts:
                            if "concept_name" in concept and "core_definition" in concept:
                                knowledge_points.append({
                                    "point_name": concept["concept_name"],
                                    "core_description": concept["core_definition"]
                                })
                            elif "point_name" in concept and "core_description" in concept:
                                # 兼容旧格式
                                knowledge_points.append(concept)
                        
                        print(f"[LLM调用] 转换后的知识点格式: {len(knowledge_points)} 个")
                        return knowledge_points
                    except json.JSONDecodeError as json_error:
                        print(f"[LLM调用] JSON解析失败: {json_error}")
                        print(f"[LLM调用] 尝试备用解析方法")
                        # 如果JSON解析失败，尝试简单解析
                        fallback_result = self._parse_knowledge_points_fallback(content)
                        print(f"[LLM调用] 备用解析结果: {fallback_result}")
                        return fallback_result
                else:
                    error_msg = f"API返回格式异常: {data}"
                    print(f"[LLM调用] {error_msg}")
                    log_gemini_call("extract_knowledge_points", prompt, error=error_msg, response_time=response_time)
                    raise Exception(error_msg)
            else:
                error_msg = f"API调用失败: {response.status_code}, 响应: {response.text[:500]}"
                print(f"[LLM调用] {error_msg}")
                log_gemini_call("extract_knowledge_points", prompt, error=error_msg, response_time=response_time)
                raise Exception(error_msg)
                
        except Exception as e:
            error_msg = f"知识点提取失败: {e}"
            print(f"[LLM调用] {error_msg}")
            if 'response_time' not in locals():
                log_gemini_call("extract_knowledge_points", prompt, error=error_msg)
            raise Exception(error_msg)
    
    def _extract_with_ollama(self, prompt: str) -> List[Dict]:
        """使用Ollama API提取知识点"""
        try:
            from llm_logger import log_ollama_call
            
            ollama_url = self.config.get("ollama_url", "http://localhost:11434")
            model = self.config.get("ollama_model", "deepseek-coder")
            
            print(f"[LLM调用] 尝试使用Ollama API: {ollama_url}")
            print(f"[LLM调用] 使用模型: {model}")
            
            url = f"{ollama_url}/api/generate"
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "top_p": 0.9
                }
            }
            
            start_time = time.time()
            response = requests.post(url, json=payload, timeout=60)
            response_time = time.time() - start_time
            
            print(f"[LLM调用] Ollama响应状态码: {response.status_code}")
            print(f"[LLM调用] 响应时间: {response_time:.2f}秒")
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("response", "")
                print(f"[LLM调用] Ollama原始响应内容: {content[:500]}...")
                
                # 处理DeepSeek特有的think标签
                content = self._filter_deepseek_think_content(content)
                print(f"[LLM调用] 过滤think后的内容: {content[:300]}...")
                
                log_ollama_call("extract_knowledge_points", model, prompt, content, response_time=response_time)
                
                # 尝试解析JSON
                try:
                    # 清理可能的markdown格式
                    content = content.strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                    
                    knowledge_points = json.loads(content)
                    print(f"[LLM调用] Ollama解析成功，提取到 {len(knowledge_points)} 个知识点")
                    return knowledge_points
                except json.JSONDecodeError:
                    print(f"[LLM调用] Ollama JSON解析失败，使用备用解析")
                    return self._parse_knowledge_points_fallback(content)
            else:
                error_msg = f"Ollama API调用失败: {response.status_code}"
                log_ollama_call("extract_knowledge_points", model, prompt, error=error_msg, response_time=response_time)
                raise Exception(error_msg)
                
        except Exception as e:
            error_msg = f"Ollama API调用失败: {e}"
            print(f"[LLM调用] {error_msg}")
            raise Exception(error_msg)
    
    def _extract_with_rules(self, subject_name: str, note_content: str) -> List[Dict]:
        """基于规则的知识点提取（兜底方案）"""
        print(f"[LLM调用] 使用基于规则的知识点提取")
        
        # 基于关键词和句子结构提取知识点
        points = []
        sentences = note_content.split('。')
        
        # 关键词模式
        knowledge_patterns = [
            r'(.{2,20}?)是(.{5,30})',  # X是Y的模式
            r'(.{2,20}?)包含(.{5,30})',  # X包含Y的模式
            r'(.{2,20}?)具有(.{5,30})',  # X具有Y的模式
            r'(.{2,20}?)可以(.{5,30})',  # X可以Y的模式
            r'(.{2,20}?)方法(.{5,30})',  # X方法Y的模式
        ]
        
        import re
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:
                continue
                
            for pattern in knowledge_patterns:
                matches = re.findall(pattern, sentence)
                for match in matches:
                    if len(match) >= 2:
                        point_name = match[0].strip()
                        description = match[1].strip()
                        
                        if point_name and description and len(point_name) <= 20:
                            points.append({
                                "point_name": point_name,
                                "core_description": description[:25]
                            })
                            
                            if len(points) >= 3:  # 限制数量
                                break
                if len(points) >= 3:
                    break
        
        # 如果没有提取到，创建一个通用知识点
        if not points:
            points = [{
                "point_name": f"{subject_name}基础概念",
                "core_description": "从笔记中提取的核心知识点"
            }]
        
        print(f"[LLM调用] 规则提取完成，提取到 {len(points)} 个知识点")
        return points
    
    def _filter_deepseek_think_content(self, content: str) -> str:
        """过滤DeepSeek模型返回的think标签内容"""
        import re
        
        print(f"[内容过滤] 原始内容前200字符: {content[:200]}")
        
        # DeepSeek模型会返回<think>...</think>标签，需要过滤掉
        # 使用更强的正则表达式来匹配think内容
        think_patterns = [
            r'<think>.*?</think>',  # 标准think标签
            r'<thinking>.*?</thinking>',  # thinking标签
            r'思考过程：.*?(?=\n\n|\n[^\n]|$)',  # 中文思考过程
            r'分析：.*?(?=\n\n|\n[^\n]|$)',  # 中文分析
        ]
        
        original_length = len(content)
        filtered_content = content
        
        for pattern in think_patterns:
            matches = re.findall(pattern, filtered_content, flags=re.DOTALL | re.IGNORECASE)
            if matches:
                print(f"[内容过滤] 找到think内容: {len(matches)} 个匹配")
                for match in matches:
                    print(f"[内容过滤] 匹配内容前100字符: {match[:100]}")
            filtered_content = re.sub(pattern, '', filtered_content, flags=re.DOTALL | re.IGNORECASE)
        
        # 特殊处理：如果内容以<think>开头，直接查找第一个</think>后的内容
        if content.strip().startswith('<think>'):
            think_end = content.find('</think>')
            if think_end != -1:
                filtered_content = content[think_end + 8:].strip()
                print(f"[内容过滤] 检测到内容以<think>开头，直接截取</think>后的内容")
        
        # 清理多余的空行和空格
        filtered_content = re.sub(r'\n\s*\n\s*\n', '\n\n', filtered_content)
        filtered_content = filtered_content.strip()
        
        # 记录过滤结果
        if len(filtered_content) != original_length:
            print(f"[内容过滤] 过滤完成，原长度: {original_length}, 过滤后: {len(filtered_content)}")
            print(f"[内容过滤] 过滤后内容前200字符: {filtered_content[:200]}")
        else:
            print(f"[内容过滤] 未检测到think内容，内容未改变")
        
        return filtered_content
    
    def _parse_knowledge_points_fallback(self, content: str) -> List[Dict]:
        """备用解析方法 - 支持概念提取格式"""
        print(f"[LLM调用] 启用备用解析，内容长度: {len(content)}")
        points = []
        lines = content.split('\n')
        
        # 尝试多种解析模式，优先支持概念格式
        patterns = [
            # 模式1: 概念术语 - 核心定义
            r'([^-\n:]+)\s*-\s*(.+)',
            # 模式2: 概念术语: 核心定义  
            r'([^:\n]+):\s*(.+)',
            # 模式3: 1. 概念术语 - 核心定义
            r'(\d+)\.\s*([^-]+)\s*-\s*(.+)',
            # 模式4: - 概念术语: 核心定义
            r'-\s*([^:]+):\s*(.+)',
        ]
        
        import re
        for pattern in patterns:
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):  # 跳过标题行
                    match = re.match(pattern, line)
                    if match:
                        if len(match.groups()) == 3:
                            # 带序号的格式
                            concept_name = match.group(2).strip()
                            core_definition = match.group(3).strip()
                        else:
                            # 简单格式
                            concept_name = match.group(1).strip()
                            core_definition = match.group(2).strip()
                        
                        # 清理概念名称和定义
                        concept_name = concept_name.strip('""''()（）')
                        core_definition = core_definition.strip('""''()（）')
                        
                        if concept_name and core_definition and len(concept_name) <= 50:
                            points.append({
                                "point_name": concept_name,
                                "core_description": core_definition
                            })
                            
                            if len(points) >= 7:  # 概念提取限制为7个
                                break
                if len(points) >= 7:
                    break
        
        # 如果没有提取到，尝试从内容中提取关键术语
        if not points:
            # 查找可能的概念术语（大写开头的词组、专业术语等）
            import re
            concept_candidates = re.findall(r'[A-Z][a-zA-Z\u4e00-\u9fff]{2,15}', content)
            if concept_candidates:
                for candidate in concept_candidates[:3]:  # 最多3个
                    points.append({
                        "point_name": candidate,
                        "core_description": "从学习材料中识别的核心概念"
                    })
            else:
                # 最后的备用方案
                points = [{
                    "point_name": "核心概念",
                    "core_description": "从学习材料中提取的重要概念"
                }]
        
        print(f"[LLM调用] 备用解析完成，提取到 {len(points)} 个概念")
        return points
    
    def find_similar_knowledge_points(self, subject_name: str, new_point: Dict, user_id: str = "0001") -> List[Dict]:
        """查找相似知识点 - 简化版本"""
        print(f"[相似度查找] 开始查找相似知识点: {new_point.get('point_name', '')}")
        
        # 为了提高性能和简化逻辑，暂时跳过相似度匹配
        # 直接返回空列表，让所有概念都作为新概念处理
        print(f"[相似度查找] 跳过相似度匹配，所有概念作为新概念处理")
        return []
    
    def _calculate_similarity(self, new_point: Dict, existing_point: Dict) -> int:
        """计算知识点相似度"""
        prompt = f"""请计算以下两个知识点的语义相似度，返回0-100的分数。

新知识点：
名称：{new_point['point_name']}
描述：{new_point['core_description']}

已有知识点：
名称：{existing_point['point_name']}
描述：{existing_point['core_description']}

请只返回一个0-100之间的整数分数，表示相似度。"""

        try:
            api_key = self.config.get("gemini_api_key", "")
            if not api_key:
                return 0
            
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
                        similarity = int(numbers[0])
                        return min(100, max(0, similarity))
            
            return 0
        except:
            return 0
    
    def save_knowledge_point(self, subject_name: str, point_name: str, core_description: str, user_id: str = "0001") -> int:
        """保存新知识点"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT INTO knowledge_points 
               (user_id, subject_name, point_name, core_description) 
               VALUES (?, ?, ?, ?)""",
            (user_id, subject_name, point_name, core_description)
        )
        
        point_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        
        return point_id
    
    def merge_to_existing_point(self, existing_point_id: int, new_point: Dict) -> bool:
        """合并到已有知识点"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        # 获取已有知识点信息
        cursor.execute(
            "SELECT point_name, core_description FROM knowledge_points WHERE id = ?",
            (existing_point_id,)
        )
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return False
        
        existing_name, existing_desc = result
        
        # 生成合并后的描述
        merged_desc = self._merge_descriptions(existing_desc, new_point['core_description'])
        merged_name = self._merge_names(existing_name, new_point['point_name'])
        
        # 更新知识点
        cursor.execute(
            """UPDATE knowledge_points 
               SET point_name = ?, core_description = ?, updated_time = CURRENT_TIMESTAMP 
               WHERE id = ?""",
            (merged_name, merged_desc, existing_point_id)
        )
        
        conn.commit()
        conn.close()
        return True


class PracticeRecordManager:
    """练习记录管理器"""
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def save_practice_record(self, subject_name: str, knowledge_point_id: int,
                             question_content: str, user_answer: str, is_correct: bool,
                             user_id: str = "0001",
                             correct_answer: Optional[str] = None,
                             explanation: Optional[str] = None) -> int:
        """保存练习记录，并在错误时写入错题表（含正确答案与解析）"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """INSERT INTO practice_records 
               (user_id, subject_name, knowledge_point_id, question_content, user_answer, is_correct) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, subject_name, knowledge_point_id, question_content, user_answer, int(is_correct))
        )
        record_id = cursor.lastrowid

        if not is_correct:
            cursor.execute(
                """INSERT INTO error_questions 
                   (user_id, subject_name, knowledge_point_id, practice_record_id, correct_answer, explanation) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, subject_name, knowledge_point_id, record_id, correct_answer, explanation)
            )

        conn.commit()
        conn.close()
        return record_id


class ErrorQuestionManager:
    """错题管理器"""
    def __init__(self, db_manager: DatabaseManager, config: dict):
        self.db_manager = db_manager
        self.config = config

    def get_error_questions_by_knowledge_point(self, subject_name: str, knowledge_point_id: int, 
                                               user_id: str = "0001") -> List[Dict]:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT eq.id, pr.question_content, pr.user_answer, pr.practice_time, eq.review_status, eq.current_proficiency, eq.correct_answer, eq.explanation
               FROM error_questions eq
               JOIN practice_records pr ON eq.practice_record_id = pr.id
               WHERE eq.user_id = ? AND eq.subject_name = ? AND eq.knowledge_point_id = ?
               ORDER BY pr.practice_time DESC""",
            (user_id, subject_name, knowledge_point_id)
        )
        errors = []
        for row in cursor.fetchall():
            errors.append({
                "id": row[0],
                "question_content": row[1],
                "user_answer": row[2],
                "practice_time": row[3],
                "review_status": row[4],
                "current_proficiency": row[5] if row[5] is not None else 20,
                "correct_answer": row[6] if len(row) > 6 else None,
                "explanation": row[7] if len(row) > 7 else None,
            })
        conn.close()
        return errors

    def get_error_counts_by_knowledge_points(self, subject_name: str, user_id: str = "0001") -> Dict[int, int]:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT knowledge_point_id, COUNT(*) as cnt
            FROM error_questions
            WHERE user_id = ? AND subject_name = ?
            GROUP BY knowledge_point_id
            """,
            (user_id, subject_name)
        )
        result = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        return result

    def update_error_question_content(self, error_question_id: int, new_content: str) -> bool:
        """根据错题ID更新其关联的题干（practice_records.question_content）。"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            # 找到关联的练习记录ID
            cursor.execute(
                "SELECT practice_record_id FROM error_questions WHERE id = ?",
                (error_question_id,)
            )
            row = cursor.fetchone()
            if not row:
                conn.close()
                return False
            rec_id = int(row[0])
            # 更新题干
            cursor.execute(
                "UPDATE practice_records SET question_content = ? WHERE id = ?",
                (new_content or "", rec_id)
            )
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return success
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return False

    def delete_error_question(self, error_question_id: int) -> bool:
        """删除一条错题及其熟练度历史记录（不删除原始练习记录）。"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            # 先删除历史
            cursor.execute(
                "DELETE FROM error_proficiency_history WHERE error_question_id = ?",
                (error_question_id,)
            )
            # 再删除错题
            cursor.execute(
                "DELETE FROM error_questions WHERE id = ?",
                (error_question_id,)
            )
            success = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return success
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            return False
    def mark_as_reviewed(self, error_question_id: int) -> bool:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE error_questions SET review_status = 1 WHERE id = ?", (error_question_id,))
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success

    def get_proficiency_history(self, error_question_id: int) -> List[Tuple[str, int]]:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT timestamp, proficiency FROM error_proficiency_history
            WHERE error_question_id = ?
            ORDER BY timestamp ASC
            """,
            (error_question_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [(r[0], int(r[1])) for r in rows]

    def append_proficiency(self, error_question_id: int, proficiency: int) -> None:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        p = int(max(0, min(100, proficiency)))
        cursor.execute(
            "INSERT INTO error_proficiency_history (error_question_id, proficiency) VALUES (?, ?)",
            (error_question_id, p)
        )
        cursor.execute(
            "UPDATE error_questions SET current_proficiency = ? WHERE id = ?",
            (p, error_question_id)
        )
        conn.commit()
        conn.close()

    def generate_targeted_questions(self, subject_name: str, knowledge_point_id: int, 
                                    question_count: int = 2, user_id: str = "0001",
                                    reference_text: Optional[str] = None) -> List[Dict]:
        # 1) 获取知识点信息
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT point_name, core_description FROM knowledge_points WHERE id = ?",
            (knowledge_point_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return []
        point_name, core_description = row[0], row[1]

        # 2) 获取该知识点最近错题（作为参考）
        cursor.execute(
            """
            SELECT pr.question_content
            FROM error_questions eq
            JOIN practice_records pr ON pr.id = eq.practice_record_id
            WHERE eq.subject_name = ? AND eq.knowledge_point_id = ?
            ORDER BY pr.practice_time DESC
            LIMIT 3
            """,
            (subject_name, knowledge_point_id)
        )
        err_rows = cursor.fetchall()
        conn.close()
        ref_errors = "\n".join([f"错题{i+1}: {r[0]}" for i, r in enumerate(err_rows)]) if err_rows else "(无参考错题，按知识点说明生成)"

        # 3) 组装提示词
        ref_original = reference_text.strip() if reference_text else ""
        ref_block = f"\n原题：\n{ref_original}\n" if ref_original else ""
        prompt = f"""基于以下信息生成{question_count}道针对性练习题：\n\n学科：{subject_name}\n知识点：{point_name}\n知识点描述：{core_description}{ref_block}\n参考错题：\n{ref_errors}\n\n要求：\n1. 新题与原题考点一致，但题干和表述需有明显变化\n2. 题目使用中文表述，尽量提供客观问法\n3. 输出以清晰编号列出每道题目\n仅输出题目文本，不要包含解析。"""

        provider = (self.config or {}).get("llm_provider", "Ollama")
        # 将 None 视作 True，保证有回退
        enable_fallback = (self.config or {}).get("enable_llm_fallback", True)
        enable_fallback = True if enable_fallback is None else bool(enable_fallback)

        # 4) 优先使用 Ollama
        try:
            if provider == "Ollama":
                text = self._ollama_generate(prompt)
            elif provider == "Gemini":
                text = self._gemini_generate(prompt)
            else:  # DeepSeek 等未实现则先走 Ollama
                text = self._ollama_generate(prompt)
        except Exception as e:
            text = ""

        # 清洗 think/思考 标签
        def _clean_text(t: str) -> str:
            try:
                import re
                patterns = [r"<think>.*?</think>", r"<thinking>.*?</thinking>", r"<Thought>.*?</Thought>"]
                for p in patterns:
                    t = re.sub(p, "", t, flags=re.DOTALL | re.IGNORECASE)
                # 常见中文思考块（简单裁剪）
                t = re.sub(r"(?s)^\s*思考[:：].*?\n", "", t)
                return t.strip()
            except Exception:
                return t

        # 5) 回退：另一个提供商
        if not text and enable_fallback:
            try:
                if provider == "Ollama":
                    text = self._gemini_generate(prompt)
                else:
                    text = self._ollama_generate(prompt)
            except Exception:
                text = ""

        # 6) 最终兜底：规则生成
        if not text:
            text = self._rule_based_generate(point_name, core_description, question_count, reference_text or "")
        text = _clean_text(text)

        # 7) 解析为题目列表（按编号切分 + 提取题干/选项/答案/解析）
        items: List[Dict] = []
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        buf: list[str] = []

        import re
        def _flush_buf():
            if not buf:
                return
            q_text_lines: list[str] = []
            options: dict[str, str] = {}
            correct = ""
            expl = ""
            for ln in buf:
                # 选项
                m = re.match(r"^([A-D])[).．。\s]\s*(.+)$", ln)
                if m:
                    options[m.group(1)] = m.group(2).strip()
                    continue
                # 正确答案
                if ln.startswith("正确答案") or ln.startswith("答案"):
                    part = ln.split("：", 1)
                    if len(part) == 2:
                        correct = part[1].strip()
                    else:
                        part = ln.split(":", 1)
                        if len(part) == 2:
                            correct = part[1].strip()
                    continue
                # 解析
                if ln.startswith("解析"):
                    part = ln.split("：", 1)
                    expl = part[1].strip() if len(part) == 2 else ""
                    continue
                q_text_lines.append(ln)
            q_text = "\n".join(q_text_lines).strip()
            items.append({
                "question": q_text,
                "options": options,
                "correct_answer": correct,
                "explanation": expl,
                "knowledge_point_id": knowledge_point_id,
                "subject_name": subject_name,
                "source": provider,
            })
            buf.clear()

        for ln in lines:
            if re.match(r"^(\d+)[).、.]\s*", ln):
                _flush_buf()
                ln = re.sub(r"^(\d+)[).、.]\s*", "", ln)
                buf.append(ln)
            else:
                buf.append(ln)
        _flush_buf()

        # 截断到需求数量
        if len(items) > question_count:
            items = items[:question_count]
        return items

    # ---- LLM helpers ----
    def _ollama_generate(self, prompt: str) -> str:
        try:
            import requests
            model = (self.config or {}).get("ollama_model", "qwen2.5:14b")
            # 兼容用户只填主机或 /api 前缀的情况
            base = (self.config or {}).get("ollama_api_url", "http://localhost:11434")
            url = base.rstrip('/')
            if url.endswith('/api/generate'):
                pass
            elif url.endswith('/api'):
                url = url + '/generate'
            else:
                url = url + '/api/generate'
            payload = {"model": model, "prompt": prompt, "stream": False}
            resp = requests.post(url, json=payload, timeout=60)
            if not resp.ok:
                return ""
            data = resp.json()
            return (data.get("response") or "").strip()
        except Exception:
            return ""

    def _gemini_generate(self, prompt: str) -> str:
        try:
            import requests
            api_key = (self.config or {}).get("gemini_api_key", "")
            model = (self.config or {}).get("gemini_model", "gemini-1.5-flash")
            if not api_key:
                return ""
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            resp = requests.post(url, json=payload, timeout=60)
            if not resp.ok:
                return ""
            data = resp.json()
            cands = data.get("candidates", [])
            if cands:
                parts = cands[0].get("content", {}).get("parts", [])
                if parts and "text" in parts[0]:
                    return (parts[0]["text"] or "").strip()
            return ""
        except Exception:
            return ""

    def _rule_based_generate(self, point_name: str, core_desc: str, count: int, reference_text: str = "") -> str:
        stems = [
            (f"改写原题表达，保持考点‘{point_name}’不变：{reference_text[:120]}" if reference_text else f"请解释概念‘{point_name}’的核心要点，并举一个简单例子。"),
            f"围绕‘{point_name}’，给出一道判断题（不出现‘对/错’字样），使其与原题表述不同。",
            f"针对‘{point_name}’的应用场景，给出一道简答题，要求能区分是否真正理解该概念。",
        ]
        items = stems[:max(1, count)]
        return "\n".join([f"{i+1}. {s}" for i, s in enumerate(items)])


class LegacyKnowledgeManagementSystem:
    """已废弃：请使用新的 KnowledgeManagementSystem(config)"""
    def __init__(self, db_manager: DatabaseManager, config: dict):
        self.db_manager = db_manager
        self.config = config
    
    def get_error_questions_by_knowledge_point(self, subject_name: str, knowledge_point_id: int, 
                                             user_id: str = "0001") -> List[Dict]:
        """根据知识点获取错题"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT eq.id, pr.question_content, pr.user_answer, pr.practice_time, eq.review_status, eq.current_proficiency, eq.correct_answer, eq.explanation
               FROM error_questions eq
               JOIN practice_records pr ON eq.practice_record_id = pr.id
               WHERE eq.user_id = ? AND eq.subject_name = ? AND eq.knowledge_point_id = ?
               ORDER BY pr.practice_time DESC""",
            (user_id, subject_name, knowledge_point_id)
        )
        
        errors = []
        for row in cursor.fetchall():
            errors.append({
                "id": row[0],
                "question_content": row[1],
                "user_answer": row[2],
                "practice_time": row[3],
                "review_status": row[4],
                "current_proficiency": row[5] if row[5] is not None else 20,
                "correct_answer": row[6] if len(row) > 6 else None,
                "explanation": row[7] if len(row) > 7 else None,
            })

        conn.close()
        return errors

    def get_error_counts_by_knowledge_points(self, subject_name: str, user_id: str = "0001") -> Dict[int, int]:
        """返回某学科下每个知识点的错题数量映射: {knowledge_point_id: count}"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT knowledge_point_id, COUNT(*) as cnt
            FROM error_questions
            WHERE user_id = ? AND subject_name = ?
            GROUP BY knowledge_point_id
            """,
            (user_id, subject_name)
        )
        result = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        return result

    def get_proficiency_history(self, error_question_id: int) -> List[Tuple[str, int]]:
        """获取某错题的熟练度时间序列 [(timestamp_iso, proficiency), ...]"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT timestamp, proficiency FROM error_proficiency_history
            WHERE error_question_id = ?
            ORDER BY timestamp ASC
            """,
            (error_question_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [(r[0], int(r[1])) for r in rows]

    def append_proficiency(self, error_question_id: int, proficiency: int) -> None:
        """追加一条熟练度记录，并更新当前熟练度"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO error_proficiency_history (error_question_id, proficiency) VALUES (?, ?)",
            (error_question_id, int(max(0, min(100, proficiency))))
        )
        cursor.execute(
            "UPDATE error_questions SET current_proficiency = ? WHERE id = ?",
            (int(max(0, min(100, proficiency))), error_question_id)
        )
        conn.commit()
        conn.close()
    
    def generate_targeted_questions(self, subject_name: str, knowledge_point_id: int, 
                                  question_count: int = 2, user_id: str = "0001") -> List[Dict]:
        """基于错题生成针对性新题"""
        # 获取该知识点的错题
        error_questions = self.get_error_questions_by_knowledge_point(subject_name, knowledge_point_id, user_id)
        
        if not error_questions:
            return []
        
        # 获取知识点信息
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT point_name, core_description FROM knowledge_points WHERE id = ?",
            (knowledge_point_id,)
        )
        point_info = cursor.fetchone()
        conn.close()
        
        if not point_info:
            return []
        
        point_name, core_description = point_info
        
        # 构建错题内容
        error_content = "\n".join([f"错题{i+1}：{eq['question_content']}" 
                                 for i, eq in enumerate(error_questions[:3])])  # 最多使用3道错题作为参考
        
        prompt = f"""基于以下信息生成{question_count}道针对性练习题：

学科：{subject_name}
知识点：{point_name}
知识点描述：{core_description}

参考错题：
{error_content}

要求：
1. 新题考点与错题完全一致
2. 题干、选项不与历史题目重复
3. 每题包含：题干、4个选项(A/B/C/D)、正确答案、解析
4. 解析需关联知识点核心内容

请按以下JSON格式输出：
[
    {{
        "question": "题干内容",
        "options": {{"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}},
        "correct_answer": "A",
        "explanation": "解析内容"
    }}
]"""

        # 构建统一的生成流程，遵循 llm_provider 选择与 enable_llm_fallback
        llm_provider = str(self.config.get("llm_provider", "Gemini")).strip()
        provider_norm = llm_provider.lower()
        allow_fallback = bool(self.config.get("enable_llm_fallback", False))
        print(f"[模型选择][针对性新题] 提供商: {llm_provider} (fallback={'on' if allow_fallback else 'off'})")

        def _gen_with_gemini() -> List[Dict]:
            api_key = self.config.get("gemini_api_key", "")
            if not api_key:
                raise Exception("未配置Gemini API密钥")
            gemini_model = self.config.get("gemini_model", "gemini-1.5-flash-latest")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.7,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 3072,
                }
            }
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    content = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                    return json.loads(content)
                raise Exception("API返回格式异常")
            raise Exception(f"API调用失败: {response.status_code}, 响应: {response.text[:300]}")

        def _gen_with_ollama() -> List[Dict]:
            # 兼容两种配置键：ollama_api_url 或 ollama_url
            base_url = self.config.get("ollama_api_url") or (self.config.get("ollama_url", "http://localhost:11434") + "/api/generate")
            url = base_url if base_url.endswith("/api/generate") else base_url
            model = self.config.get("ollama_model", "deepseek-coder")
            print(f"[LLM调用][Ollama] url={url}, model={model}")
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.7, "top_p": 0.9}
            }
            response = requests.post(url, json=payload, timeout=60)
            if response.status_code == 200:
                data = response.json()
                content = data.get("response", "").strip()
                # 清理可能的 think 标签
                content = self._filter_deepseek_think_content(content)
                try:
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                    return json.loads(content)
                except Exception as je:
                    print(f"[Ollama] JSON解析失败: {je}，内容前200: {content[:200]}")
                    raise
            raise Exception(f"Ollama API调用失败: {response.status_code}, 响应: {response.text[:300]}")

        def _gen_with_deepseek() -> List[Dict]:
            api_key = self.config.get("deepseek_api_key", "")
            if not api_key:
                raise Exception("未配置DeepSeek API密钥")
            deepseek_model = self.config.get("deepseek_model", "deepseek-chat")
            deepseek_url = self.config.get("deepseek_api_url", "https://api.deepseek.com/v1/chat/completions")
            payload = {
                "model": deepseek_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 3072,
                "stream": False
            }
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            response = requests.post(deepseek_url, json=payload, headers=headers, timeout=60)
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if not content:
                    raise Exception("DeepSeek响应空内容")
                if content.startswith("```json"):
                    content = content[7:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                return json.loads(content)
            raise Exception(f"DeepSeek API调用失败: {response.status_code}, 响应: {response.text[:300]}")

        # 执行选择与回退
        try:
            if provider_norm == "ollama":
                try:
                    return _gen_with_ollama()
                except Exception as ollama_error:
                    print(f"[LLM调用][针对性新题] Ollama失败: {ollama_error}")
                    if not allow_fallback:
                        raise
                    # 回退到Gemini
                    try:
                        return _gen_with_gemini()
                    except Exception as gemini_error:
                        print(f"[LLM调用][针对性新题] Gemini失败: {gemini_error}")
                        # 最后再尝试DeepSeek
                        return _gen_with_deepseek()
            elif provider_norm == "deepseek":
                try:
                    return _gen_with_deepseek()
                except Exception as deepseek_error:
                    print(f"[LLM调用][针对性新题] DeepSeek失败: {deepseek_error}")
                    if not allow_fallback:
                        raise
                    try:
                        return _gen_with_gemini()
                    except Exception as gemini_error:
                        print(f"[LLM调用][针对性新题] Gemini失败: {gemini_error}")
                        return _gen_with_ollama()
            else:  # 默认Gemini
                try:
                    return _gen_with_gemini()
                except Exception as gemini_error:
                    print(f"[LLM调用][针对性新题] Gemini失败: {gemini_error}")
                    if not allow_fallback:
                        raise
                    try:
                        return _gen_with_ollama()
                    except Exception as ollama_error:
                        print(f"[LLM调用][针对性新题] Ollama失败: {ollama_error}")
                        return _gen_with_deepseek()
        except Exception as final_error:
            print(f"生成新题失败（最终）: {final_error}")
            return []

    def _filter_deepseek_think_content(self, content: str) -> str:
        """过滤DeepSeek/类DeepSeek模型返回的think标签及分析段落，保留纯输出正文"""
        try:
            import re
            text = content or ""
            # 快速截断：若以<think>开头，截取</think>之后
            if text.strip().startswith('<think>'):
                end = text.find('</think>')
                if end != -1:
                    text = text[end + len('</think>'):]
            # 通用去除 think/thinking 块
            patterns = [r'<think>.*?</think>', r'<thinking>.*?</thinking>']
            for p in patterns:
                text = re.sub(p, '', text, flags=re.DOTALL | re.IGNORECASE)
            # 清理多余空行
            text = re.sub(r'\n\s*\n\s*\n', '\n\n', text).strip()
            return text
        except Exception:
            return content


# 确保在使用前已定义 FavoriteQuestionManager（避免导入时 NameError）
try:
    FavoriteQuestionManager
except NameError:
    class FavoriteQuestionManager:
        """收藏题目管理器（保障定义顺序）"""
        def __init__(self, db_manager: DatabaseManager):
            self.db_manager = db_manager

        def save_favorite_question(self, subject_name: str, knowledge_point_id: int,
                                   question_content: str, correct_answer: Optional[str] = None,
                                   explanation: Optional[str] = None, user_id: str = "0001") -> int:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO favorite_questions
                       (user_id, subject_name, knowledge_point_id, question_content, correct_answer, explanation)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, subject_name, knowledge_point_id, question_content, correct_answer, explanation)
            )
            fav_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return fav_id

class KnowledgeManagementSystem:
    """知识管理系统主类"""
    
    def __init__(self, config: dict):
        self.config = config
        self.db_manager = DatabaseManager()
        self.subject_manager = SubjectManager(self.db_manager)
        self.knowledge_manager = KnowledgePointManager(self.db_manager, config)
        self.practice_manager = PracticeRecordManager(self.db_manager)
        self.error_manager = ErrorQuestionManager(self.db_manager, config)
        self.favorite_manager = FavoriteQuestionManager(self.db_manager)

    def update_config(self, new_config: dict):
        """更新配置并下发至子管理器（用于动态切换LLM提供商等）"""
        try:
            self.config = new_config
            if hasattr(self, 'knowledge_manager') and self.knowledge_manager:
                self.knowledge_manager.config = new_config
            if hasattr(self, 'error_manager') and self.error_manager:
                self.error_manager.config = new_config
            print(f"[配置更新][KMS] llm_provider={new_config.get('llm_provider')} fallback={new_config.get('enable_llm_fallback')}")
        except Exception as e:
            print(f"[配置更新][KMS] 更新失败: {e}")
    
    def get_subjects(self) -> List[str]:
        """获取用户所有学科"""
        return self.subject_manager.get_user_subjects()

    # ---- 错题复习 & 熟练度 相关外部接口 ----
    def get_error_questions(self, subject_name: str, knowledge_point_id: int) -> List[Dict]:
        """获取错题（包含当前熟练度等扩展信息）"""
        return self.error_manager.get_error_questions_by_knowledge_point(subject_name, knowledge_point_id)

    def get_knowledge_points_by_subject(self, subject_name: str) -> List[Dict]:
        """获取学科下的知识点（直接查询数据库）"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, point_name, core_description, mastery_score, created_time
                   FROM knowledge_points
                   WHERE user_id = ? AND subject_name = ?
                   ORDER BY created_time DESC""",
            ("0001", subject_name)
        )
        points: List[Dict] = []
        for row in cursor.fetchall():
            points.append({
                "id": row[0],
                "point_name": row[1],
                "core_description": row[2],
                "mastery_score": row[3],
                "created_time": row[4],
            })
        conn.close()
        return points

    def get_error_counts_map(self, subject_name: str) -> Dict[int, int]:
        """获取某学科下每个知识点的错题数量映射"""
        return self.error_manager.get_error_counts_by_knowledge_points(subject_name)

    def mark_error_reviewed(self, error_question_id: int) -> bool:
        """标记错题为已复习"""
        return self.error_manager.mark_as_reviewed(error_question_id)

    def save_favorite_question(self, subject_name: str, knowledge_point_id: int,
                               question_content: str, correct_answer: Optional[str] = None,
                               explanation: Optional[str] = None, user_id: str = "0001") -> int:
        """收藏题目写入数据库"""
        return self.favorite_manager.save_favorite_question(subject_name, knowledge_point_id,
                                                           question_content, correct_answer, explanation, user_id)

    def save_practice_results(self, records: List[Dict]) -> List[int]:
        """批量保存练习结果，并对错误项写入错题库。
        传入 records = [{
            'subject_name', 'knowledge_point_id', 'question_content',
            'user_answer', 'is_correct', 'correct_answer'?, 'explanation'?
        }]
        返回写入的 practice_record_id 列表（仅对处理成功的条目）。
        """
        saved_ids: List[int] = []
        for r in records or []:
            try:
                subject_name = r.get('subject_name', '通用学科')
                kp_id = int(r.get('knowledge_point_id') or 0)
                q = r.get('question_content', '')
                a = r.get('user_answer', '')
                is_correct = bool(r.get('is_correct', False))
                correct = r.get('correct_answer')
                expl = r.get('explanation')
                rec_id = self.practice_manager.save_practice_record(
                    subject_name, kp_id, q, a, is_correct, "0001", correct, expl
                )
                saved_ids.append(rec_id)
            except Exception as e:
                # 单条失败不影响其它记录
                print(f"[KMS] save_practice_results 单条保存失败: {e}")
                continue
        return saved_ids

    def get_proficiency_history(self, error_question_id: int) -> List[Tuple[str, int]]:
        return self.error_manager.get_proficiency_history(error_question_id)

    def append_proficiency(self, error_question_id: int, proficiency: int) -> None:
        self.error_manager.append_proficiency(error_question_id, proficiency)
    
    def add_subject(self, subject_name: str) -> bool:
        """添加新学科"""
        return self.subject_manager.add_subject(subject_name)
    
    # ---- 题库管理支持API ----
    def get_subject_stats(self) -> List[Dict]:
        """返回每个学科的知识点数量与错题/收藏数量: [{subject_name, kp_count, error_count, favorite_count}]"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        # 知识点数量
        cursor.execute("SELECT subject_name, COUNT(*) FROM knowledge_points GROUP BY subject_name")
        kp_map = {row[0]: row[1] for row in cursor.fetchall()}
        # 错题数量
        cursor.execute("SELECT subject_name, COUNT(*) FROM error_questions GROUP BY subject_name")
        err_map = {row[0]: row[1] for row in cursor.fetchall()}
        # 收藏数量
        cursor.execute("SELECT subject_name, COUNT(*) FROM favorite_questions GROUP BY subject_name")
        fav_map = {row[0]: row[1] for row in cursor.fetchall()}
        # 所有学科
        subjects = set(kp_map) | set(err_map) | set(fav_map)
        result = []
        for s in sorted(subjects):
            result.append({
                "subject_name": s,
                "kp_count": kp_map.get(s, 0),
                "error_count": err_map.get(s, 0),
                "favorite_count": fav_map.get(s, 0),
            })
        conn.close()
        return result

    def search_error_questions(self, subject_name: str, knowledge_point_id: Optional[int] = None,
                               keyword: str = "") -> List[Dict]:
        """查询错题，按学科/可选知识点/关键词过滤"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        base_sql = (
            "SELECT eq.id, pr.question_content, pr.user_answer, pr.practice_time, eq.current_proficiency, eq.correct_answer, eq.explanation, eq.knowledge_point_id "
            "FROM error_questions eq JOIN practice_records pr ON eq.practice_record_id = pr.id "
            "WHERE eq.subject_name = ?"
        )
        params: List = [subject_name]
        if knowledge_point_id:
            base_sql += " AND eq.knowledge_point_id = ?"
            params.append(knowledge_point_id)
        if keyword:
            base_sql += " AND pr.question_content LIKE ?"
            params.append(f"%{keyword}%")
        base_sql += " ORDER BY pr.practice_time DESC"
        cursor.execute(base_sql, params)
        rows = cursor.fetchall()
        conn.close()
        return [{
            "id": r[0],
            "question_content": r[1],
            "user_answer": r[2],
            "practice_time": r[3],
            "current_proficiency": r[4],
            "correct_answer": r[5],
            "explanation": r[6],
            "knowledge_point_id": r[7],
        } for r in rows]

    def get_favorite_questions(self, subject_name: str, knowledge_point_id: Optional[int] = None,
                               keyword: str = "") -> List[Dict]:
        """查询收藏题，按学科/可选知识点/关键词过滤"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        sql = (
            "SELECT id, question_content, correct_answer, explanation, knowledge_point_id, created_time "
            "FROM favorite_questions WHERE subject_name = ?"
        )
        params: List = [subject_name]
        if knowledge_point_id:
            sql += " AND knowledge_point_id = ?"
            params.append(knowledge_point_id)
        if keyword:
            sql += " AND question_content LIKE ?"
            params.append(f"%{keyword}%")
        sql += " ORDER BY created_time DESC"
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        return [{
            "id": r[0],
            "question_content": r[1],
            "correct_answer": r[2],
            "explanation": r[3],
            "knowledge_point_id": r[4],
            "created_time": r[5],
        } for r in rows]
    
    def extract_knowledge_points(self, subject_name: str, note_content: str) -> Dict:
        """提取知识点（简化接口）"""
        try:
            result = self.extract_and_process_knowledge_points(subject_name, note_content)
            # 确保返回格式正确
            if result and "processed_points" in result:
                result["success"] = True
                return result
            else:
                return {"success": False, "error": "提取结果格式异常"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def extract_and_process_knowledge_points(self, subject_name: str, note_content: str) -> Dict:
        """提取并处理知识点"""
        print(f"[知识处理] 开始处理知识点，学科: {subject_name}")
        
        # 提取知识点
        extracted_points = self.knowledge_manager.extract_knowledge_points(subject_name, note_content)
        print(f"[知识处理] 提取到 {len(extracted_points)} 个知识点")
        
        # 为每个知识点查找相似项
        processed_points = []
        for i, point in enumerate(extracted_points):
            print(f"[知识处理] 处理第{i+1}个知识点: {point.get('point_name', '')}")
            try:
                similar_points = self.knowledge_manager.find_similar_knowledge_points(subject_name, point)
                print(f"[知识处理] 找到 {len(similar_points)} 个相似知识点")
                
                processed_points.append({
                    "extracted_point": point,
                    "similar_points": similar_points,
                    "match_status": "已存在相似知识点" if similar_points else "无相似知识点（新知识点）"
                })
            except Exception as e:
                print(f"[知识处理] 查找相似知识点失败: {e}")
                # 即使查找相似点失败，也要添加知识点
                processed_points.append({
                    "extracted_point": point,
                    "similar_points": [],
                    "match_status": "无相似知识点（新知识点）"
                })
        
        result = {
            "subject_name": subject_name,
            "processed_points": processed_points
        }
        print(f"[知识处理] 处理完成，返回 {len(processed_points)} 个处理后的知识点")
        return result
    
    def confirm_knowledge_points(self, confirmations: List[Dict]) -> List[int]:
        """确认知识点并保存
        confirmations: List of items with fields:
          - action: 'merge' | 'new' | 'skip'
          - point_data: {point_name, core_description}
          - existing_id: int (when action == 'merge')
          - subject_name: str (when action == 'new')
        返回保存/合并后的知识点ID列表。
        """
        saved_point_ids: List[int] = []
        for confirmation in confirmations:
            action = confirmation.get("action")
            point_data = confirmation.get("point_data", {})
            if action == "merge":
                existing_id = confirmation.get("existing_id")
                if existing_id:
                    if self.knowledge_manager.merge_to_existing_point(existing_id, point_data):
                        saved_point_ids.append(existing_id)
            elif action == "new":
                subject_name = confirmation.get("subject_name", "通用学科")
                pid = self.knowledge_manager.save_knowledge_point(
                    subject_name,
                    point_data.get("point_name", "未命名知识点"),
                    point_data.get("core_description", "")
                )
                saved_point_ids.append(pid)
            else:
                # skip
                continue
        return saved_point_ids
    
    def get_error_questions(self, subject_name: str, knowledge_point_id: int) -> List[Dict]:
        """获取错题"""
        return self.error_manager.get_error_questions_by_knowledge_point(subject_name, knowledge_point_id)

    def update_error_question_content(self, error_question_id: int, new_content: str) -> bool:
        """修改错题题干内容（更新其对应的练习记录题目文本）。"""
        return self.error_manager.update_error_question_content(error_question_id, new_content)

    def delete_error_question(self, error_question_id: int) -> bool:
        """删除错题（同时清理熟练度历史）。"""
        return self.error_manager.delete_error_question(error_question_id)

    def update_error_knowledge_point(self, error_question_id: int, new_kp_id: int) -> bool:
        """修改错题的知识点归属。"""
        return self.error_manager.update_error_kp(error_question_id, new_kp_id)

    def convert_error_to_favorite(self, error_question_id: int) -> Optional[int]:
        """将一条错题转存为收藏题：复制题干/答案/解析到 favorite_questions 并删除错题。
        返回新建收藏ID，失败返回 None。
        """
        # 读取错题详情
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT eq.subject_name, eq.knowledge_point_id, pr.question_content, eq.correct_answer, eq.explanation
                FROM error_questions eq
                JOIN practice_records pr ON pr.id = eq.practice_record_id
                WHERE eq.id = ?
                """,
                (error_question_id,)
            )
            row = cursor.fetchone()
            conn.close()
            if not row:
                return None
            subject_name, kp_id, q_text, correct, expl = row
            # 保存到收藏
            fav_id = self.favorite_manager.save_favorite_question(
                subject_name, int(kp_id), q_text or "", correct, expl
            )
            # 删除错题
            self.error_manager.delete_error_question(error_question_id)
            return fav_id
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            return None
    
    def mark_error_reviewed(self, error_question_id: int) -> bool:
        """标记错题为已复习"""
        return self.error_manager.mark_as_reviewed(error_question_id)
    
    def generate_new_questions(self, subject_name: str, knowledge_point_id: int, count: int = 2,
                               reference_text: Optional[str] = None) -> List[Dict]:
        """生成新题（可选传入原题文本以增强相似度）"""
        return self.error_manager.generate_targeted_questions(
            subject_name, knowledge_point_id, count, reference_text=reference_text
        )
