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

        # 笔记表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '0001',
                note_uuid TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                title TEXT,
                content_hash TEXT,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 知识点来源关联表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_point_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_point_id INTEGER NOT NULL,
                note_id INTEGER NOT NULL,
                extraction_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points (id),
                FOREIGN KEY (note_id) REFERENCES notes (id),
                UNIQUE(knowledge_point_id, note_id)
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
        
        # 知识脑图表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_mindmaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '0001',
                subject_name TEXT NOT NULL,
                mindmap_data TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, subject_name)
            )
        ''')
        
        # 学习路径图表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS learning_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '0001',
                subject_name TEXT NOT NULL,
                path_data TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, subject_name)
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
               (user_id, subject_name, point_name, core_description, mastery_score) 
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, subject_name, point_name, core_description, -1)
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
        self.mindmap_manager = MindmapManager(self.db_manager, config)

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
            # 安全地获取知识点名称，处理不同的数据格式
            if isinstance(point, dict):
                point_name = point.get('point_name', '') or point.get('concept_name', '')
            else:
                point_name = str(point)
                print(f"[知识处理] 警告：第{i+1}个知识点不是字典格式: {type(point)}")
            
            print(f"[知识处理] 处理第{i+1}个知识点: {point_name}")
            print(f"[知识处理] 知识点数据: {point}")
            
            try:
                # 只有当point是字典时才查找相似点
                if isinstance(point, dict):
                    similar_points = self.knowledge_manager.find_similar_knowledge_points(subject_name, point)
                    print(f"[知识处理] 找到 {len(similar_points)} 个相似知识点")
                else:
                    similar_points = []
                    print(f"[知识处理] 跳过相似度匹配，因为知识点格式不正确")
                
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
    
    def register_note(self, file_name: str, file_path: str, title: str = None, content_hash: str = None) -> int:
        """注册笔记到数据库，返回笔记ID"""
        import uuid
        import hashlib
        
        # 生成唯一的笔记UUID
        note_uuid = str(uuid.uuid4())
        
        # 如果没有提供content_hash，使用文件路径生成
        if not content_hash:
            content_hash = hashlib.md5(file_path.encode('utf-8')).hexdigest()
        
        # 如果没有提供title，使用文件名
        if not title:
            title = file_name.replace('.md', '').replace('.txt', '')
        
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            # 检查是否已存在相同路径的笔记
            cursor.execute("SELECT id FROM notes WHERE file_path = ?", (file_path,))
            existing = cursor.fetchone()
            
            if existing:
                # 更新现有笔记
                cursor.execute("""
                    UPDATE notes SET 
                        file_name = ?, title = ?, content_hash = ?, updated_time = CURRENT_TIMESTAMP
                    WHERE file_path = ?
                """, (file_name, title, content_hash, file_path))
                note_id = existing[0]
            else:
                # 插入新笔记
                cursor.execute("""
                    INSERT INTO notes (note_uuid, file_name, file_path, title, content_hash)
                    VALUES (?, ?, ?, ?, ?)
                """, (note_uuid, file_name, file_path, title, content_hash))
                note_id = cursor.lastrowid
            
            conn.commit()
            return note_id
            
        except Exception as e:
            conn.rollback()
            print(f"注册笔记失败: {e}")
            return None
        finally:
            conn.close()
    
    def link_knowledge_point_to_note(self, knowledge_point_id: int, note_id: int) -> bool:
        """建立知识点与笔记的关联"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO knowledge_point_sources (knowledge_point_id, note_id)
                VALUES (?, ?)
            """, (knowledge_point_id, note_id))
            
            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"建立知识点来源关联失败: {e}")
            return False
        finally:
            conn.close()
    
    def get_knowledge_point_sources(self, knowledge_point_id: int) -> List[Dict]:
        """获取知识点的来源笔记"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT n.id, n.note_uuid, n.file_name, n.file_path, n.title, kps.extraction_time
                FROM knowledge_point_sources kps
                JOIN notes n ON n.id = kps.note_id
                WHERE kps.knowledge_point_id = ?
                ORDER BY kps.extraction_time DESC
            """, (knowledge_point_id,))
            
            sources = []
            for row in cursor.fetchall():
                sources.append({
                    "note_id": row[0],
                    "note_uuid": row[1],
                    "file_name": row[2],
                    "file_path": row[3],
                    "title": row[4],
                    "extraction_time": row[5]
                })
            
            return sources
            
        except Exception as e:
            print(f"获取知识点来源失败: {e}")
            return []
        finally:
            conn.close()
    
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
    
    # ---- 知识脑图相关方法 ----
    def get_mindmap(self, subject_name: str) -> Optional[Dict]:
        """获取学科的知识脑图"""
        return self.mindmap_manager.get_mindmap(subject_name)
    
    def generate_or_get_mindmap(self, subject_name: str) -> Optional[Dict]:
        """生成或获取学科的知识脑图（带缓存优化）"""
        print(f"🔍 检查学科 '{subject_name}' 的脑图缓存...")
        
        # 首先尝试获取现有脑图缓存
        existing_mindmap = self.mindmap_manager.get_mindmap(subject_name)
        if existing_mindmap:
            print(f"✅ 找到缓存脑图 - 版本: {existing_mindmap.get('version', 1)}, 更新时间: {existing_mindmap.get('updated_time', 'unknown')}")
            return existing_mindmap
        
        print(f"❌ 未找到缓存，开始生成新脑图...")
        
        # 获取知识点数据
        knowledge_points = self.get_knowledge_points_by_subject(subject_name)
        if not knowledge_points:
            print(f"⚠️ 学科 '{subject_name}' 没有知识点数据")
            return None
        
        print(f"📊 找到 {len(knowledge_points)} 个知识点，调用LLM生成脑图...")
        
        # 使用LLM生成脑图
        mindmap_data = self.mindmap_manager.generate_mindmap_with_llm(subject_name, knowledge_points)
        if mindmap_data:
            print(f"🎯 LLM生成成功，保存到缓存...")
            # 保存生成的脑图到缓存
            save_success = self.mindmap_manager.save_mindmap(subject_name, mindmap_data)
            if save_success:
                print(f"💾 脑图缓存保存成功")
            else:
                print(f"⚠️ 脑图缓存保存失败")
            
            return {
                "data": mindmap_data,
                "version": 1,
                "updated_time": datetime.now().isoformat(),
                "cache_status": "newly_generated"
            }
        else:
            print(f"❌ LLM生成脑图失败")
            return None
    
    def save_mindmap(self, subject_name: str, mindmap_data: Dict) -> bool:
        """保存知识脑图"""
        return self.mindmap_manager.save_mindmap(subject_name, mindmap_data)
    
    def clear_mindmap_cache(self, subject_name: str) -> bool:
        """清除学科的脑图缓存"""
        print(f"🗑️ 开始清除学科 '{subject_name}' 的脑图缓存...")
        return self.mindmap_manager.clear_mindmap_cache(subject_name)
    
    # ---- 学习路径相关方法 ----
    def get_or_generate_learning_path(self, subject_name: str) -> Optional[Dict]:
        """获取或生成学科的学习路径图"""
        return self.mindmap_manager.get_or_generate_learning_path(subject_name)
    
    def clear_learning_path_cache(self, subject_name: str) -> bool:
        """清除学科的学习路径缓存"""
        return self.mindmap_manager.clear_learning_path_cache(subject_name)


class MindmapManager:
    """知识脑图管理器"""
    
    def __init__(self, db_manager: DatabaseManager, config: Dict):
        self.db_manager = db_manager
        self.config = config
    
    def get_mindmap(self, subject_name: str, user_id: str = "0001") -> Optional[Dict]:
        """获取学科的知识脑图（从缓存）"""
        print(f"🔍 从数据库查询学科 '{subject_name}' 的脑图缓存...")
        
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT mindmap_data, version, updated_time FROM knowledge_mindmaps WHERE user_id = ? AND subject_name = ?",
            (user_id, subject_name)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            try:
                mindmap_data = json.loads(result[0])
                cache_info = {
                    "data": mindmap_data,
                    "version": result[1],
                    "updated_time": result[2],
                    "cache_status": "from_cache"
                }
                print(f"✅ 缓存命中 - 版本: {result[1]}, 节点数: {len(mindmap_data.get('nodes', []))}, 更新时间: {result[2]}")
                return cache_info
            except json.JSONDecodeError as e:
                print(f"❌ 缓存数据解析失败: {e}")
                return None
        else:
            print(f"❌ 缓存未命中 - 数据库中没有找到该学科的脑图")
            return None
    
    def save_mindmap(self, subject_name: str, mindmap_data: Dict, user_id: str = "0001") -> bool:
        """保存知识脑图"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            mindmap_json = json.dumps(mindmap_data, ensure_ascii=False)
            
            # 尝试更新现有记录
            cursor.execute(
                """UPDATE knowledge_mindmaps 
                   SET mindmap_data = ?, version = version + 1, updated_time = CURRENT_TIMESTAMP 
                   WHERE user_id = ? AND subject_name = ?""",
                (mindmap_json, user_id, subject_name)
            )
            
            # 如果没有更新任何记录，则插入新记录
            if cursor.rowcount == 0:
                cursor.execute(
                    "INSERT INTO knowledge_mindmaps (user_id, subject_name, mindmap_data) VALUES (?, ?, ?)",
                    (user_id, subject_name, mindmap_json)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"保存脑图失败: {e}")
            conn.close()
            return False
    
    def generate_mindmap_with_llm(self, subject_name: str, knowledge_points: List[Dict]) -> Optional[Dict]:
        """使用LLM生成知识脑图"""
        if not knowledge_points:
            return None
        
        # 准备知识点信息，包含ID和名称
        point_info = []
        for point in knowledge_points:
            point_info.append(f"- ID:{point.get('id', 'unknown')} {point.get('point_name', '')}")
        
        # 构建LLM提示词
        prompt = f"""请分析以下{subject_name}学科的知识点，生成一个有向知识关系脑图。

知识点列表：
{chr(10).join(point_info)}

请按照以下JSON格式返回脑图数据：
{{
    "nodes": [
        {{
            "id": "center",
            "name": "{subject_name}",
            "type": "center",
            "level": 0,
            "x": 400,
            "y": 300
        }},
        {{
            "id": "category_1", 
            "name": "基础概念",
            "type": "category",
            "level": 1,
            "x": 200,
            "y": 200
        }},
        {{
            "id": "kp_1",
            "name": "知识点名称",
            "type": "knowledge_point",
            "level": 2,
            "x": 100,
            "y": 100
        }}
    ],
    "edges": [
        {{
            "source": "center",
            "target": "category_1",
            "relation": "包含",
            "direction": "forward"
        }},
        {{
            "source": "category_1",
            "target": "kp_1",
            "relation": "细分为",
            "direction": "forward"
        }},
        {{
            "source": "kp_1",
            "target": "kp_2",
            "relation": "依赖于",
            "direction": "forward"
        }}
    ]
}}

要求：
1. 必须包含一个中心节点，id为"center"，name为学科名称，type为"center"
2. 知识点节点的id必须使用"kp_"前缀加上实际的知识点ID（如kp_1, kp_2等）
3. 分类节点的id使用"category_"前缀，用于归类相关知识点
4. 每条边必须包含relation字段，描述两个节点的具体关系
5. 关系类型要具体化，如：包含、细分为、依赖于、前置条件、应用于、扩展为等
6. direction字段表示关系方向，"forward"表示从source指向target
7. 设置合理的坐标位置，形成层次化布局
8. 分析知识点的逻辑关系，构建有意义的学习路径
9. 只返回JSON数据，不要其他说明文字"""

        try:
            # 使用与学习资料相同的方式调用LLM
            from llm_provider_factory import LLMProviderFactory
            
            factory = LLMProviderFactory()
            llm_provider = factory.get_provider()
            
            print(f"📡 调用LLM生成脑图，提示词长度: {len(prompt)}")
            response = llm_provider.call(prompt)
            print(f"📝 LLM原始响应: {response[:200]}...")
            
            # 解析JSON响应
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                print(f"🔍 提取的JSON: {json_str[:200]}...")
                mindmap_data = json.loads(json_str)
                
                # 验证数据结构
                if 'nodes' in mindmap_data and 'edges' in mindmap_data:
                    print(f"✅ 脑图数据解析成功: {len(mindmap_data['nodes'])}个节点, {len(mindmap_data['edges'])}条边")
                    
                    # 将原始知识点的熟练度信息合并到生成的节点中
                    self._merge_mastery_scores(mindmap_data, knowledge_points)
                    
                    return mindmap_data
                else:
                    print("❌ 脑图数据缺少必要字段")
                    return None
            else:
                print("❌ LLM响应中未找到有效的JSON数据")
                print(f"完整响应: {response}")
                return None
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析失败: {e}")
            print(f"尝试解析的内容: {json_match.group() if 'json_match' in locals() else 'N/A'}")
            return None
        except Exception as e:
            print(f"❌ 生成脑图失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _merge_mastery_scores(self, mindmap_data: Dict, knowledge_points: List[Dict]) -> None:
        """将原始知识点的熟练度信息合并到脑图节点中"""
        # 获取知识点数据并构建熟练度映射和名称映射
        mastery_map = {}
        name_to_id_map = {}  # 名称到真实ID的映射
        for point in knowledge_points:
            point_id = str(point.get('id', ''))
            point_name = point.get('point_name', '')
            mastery_score = point.get('mastery_score', -1)
            mastery_map[point_id] = mastery_score
            # 同时支持kp_前缀的ID
            mastery_map[f"kp_{point_id}"] = mastery_score
            # 建立名称到ID的映射
            name_to_id_map[point_name] = point_id
        
        print(f"🔗 熟练度映射表: {mastery_map}")
        
        # 为脑图中的知识点节点添加熟练度信息并修正ID映射
        nodes_updated = 0
        old_to_new_id_map = {}  # 记录ID变更映射
        
        for node in mindmap_data.get('nodes', []):
            if node.get('type') == 'knowledge_point':
                node_id = node.get('id', '')
                node_name = node.get('name', '')
                
                # 首先尝试直接匹配ID
                if node_id in mastery_map:
                    node['mastery_score'] = mastery_map[node_id]
                    nodes_updated += 1
                    print(f"✅ 节点 {node_id} 熟练度: {mastery_map[node_id]}")
                # 如果直接匹配失败，尝试通过名称匹配真实ID
                elif node_name in name_to_id_map:
                    real_id = name_to_id_map[node_name]
                    real_mastery = mastery_map.get(real_id, -1)
                    
                    # 记录ID变更
                    old_id = node_id
                    new_id = f"kp_{real_id}"
                    old_to_new_id_map[old_id] = new_id
                    
                    # 更新节点ID为真实ID
                    node['id'] = new_id
                    node['mastery_score'] = real_mastery
                    nodes_updated += 1
                    print(f"🔧 节点名称匹配: {node_name} | {old_id} -> {new_id} | 熟练度: {real_mastery}")
                else:
                    # 设置默认熟练度
                    node['mastery_score'] = -1
                    print(f"⚠️ 节点 {node_id}({node_name}) 未找到匹配，设为默认值 -1")
        
        # 更新边的引用
        edges_updated = 0
        for edge in mindmap_data.get('edges', []):
            source_updated = False
            target_updated = False
            
            if edge.get('source') in old_to_new_id_map:
                old_source = edge['source']
                edge['source'] = old_to_new_id_map[old_source]
                source_updated = True
                
            if edge.get('target') in old_to_new_id_map:
                old_target = edge['target']
                edge['target'] = old_to_new_id_map[old_target]
                target_updated = True
                
            if source_updated or target_updated:
                edges_updated += 1
                print(f"🔗 更新边引用: {edge.get('source')} -> {edge.get('target')}")
        
        print(f"📊 更新了 {nodes_updated} 个知识点节点，{edges_updated} 条边")
    
    def clear_mindmap_cache(self, subject_name: str, user_id: str = "0001") -> bool:
        """清除学科的脑图缓存"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            # 先检查是否存在缓存
            cursor.execute(
                "SELECT COUNT(*) FROM knowledge_mindmaps WHERE user_id = ? AND subject_name = ?",
                (user_id, subject_name)
            )
            count = cursor.fetchone()[0]
            
            if count == 0:
                print(f"⚠️ 没有找到需要清除的缓存")
                conn.close()
                return False
            
            # 删除缓存
            cursor.execute(
                "DELETE FROM knowledge_mindmaps WHERE user_id = ? AND subject_name = ?",
                (user_id, subject_name)
            )
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted_count > 0:
                print(f"✅ 成功删除 {deleted_count} 条缓存记录")
                return True
            else:
                print(f"⚠️ 没有删除任何缓存记录")
                return False
                
        except Exception as e:
            print(f"❌ 清除缓存失败: {e}")
            conn.close()
            return False
    
    def get_or_generate_learning_path(self, subject_name: str, user_id: str = "0001") -> Optional[Dict]:
        """获取或生成学科的学习路径图"""
        print(f"🌳 开始获取/生成学科 '{subject_name}' 的学习路径")
        
        # 先尝试从缓存获取
        cached_path = self._get_cached_learning_path(subject_name, user_id)
        if cached_path:
            print(f"✅ 找到缓存学习路径")
            return cached_path
        
        # 缓存不存在，生成新的学习路径
        print(f"🔍 缓存不存在，开始生成新的学习路径")
        
        # 获取学科的所有知识点
        knowledge_points = self._get_knowledge_points_by_subject(subject_name)
        if not knowledge_points:
            print(f"⚠️ 学科 '{subject_name}' 没有知识点，无法生成学习路径")
            return None
        
        print(f"📊 获取到 {len(knowledge_points)} 个知识点")
        
        # 使用LLM生成学习路径
        learning_path_data = self._generate_learning_path_with_llm(subject_name, knowledge_points)
        if not learning_path_data:
            print(f"❌ LLM生成学习路径失败")
            return None
        
        # 保存到缓存
        success = self._save_learning_path_cache(subject_name, learning_path_data, user_id)
        if success:
            print(f"✅ 学习路径已保存到缓存")
        else:
            print(f"⚠️ 学习路径保存失败，但仍返回生成的数据")
        
        return {
            "data": learning_path_data,
            "cache_status": "newly_generated",
            "version": 1,
            "updated_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def _get_cached_learning_path(self, subject_name: str, user_id: str = "0001") -> Optional[Dict]:
        """从缓存获取学习路径"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT path_data, version, updated_time FROM learning_paths WHERE user_id = ? AND subject_name = ?",
            (user_id, subject_name)
        )
        result = cursor.fetchone()
        conn.close()
        
        if result:
            path_data_json, version, updated_time = result
            try:
                path_data = json.loads(path_data_json)
                return {
                    "data": path_data,
                    "cache_status": "from_cache",
                    "version": version,
                    "updated_time": updated_time
                }
            except json.JSONDecodeError as e:
                print(f"❌ 学习路径缓存数据解析失败: {e}")
                return None
        
        return None
    
    def _generate_learning_path_with_llm(self, subject_name: str, knowledge_points: List[Dict]) -> Optional[Dict]:
        """使用LLM生成学习路径图"""
        print(f"🤖 使用LLM生成 '{subject_name}' 的学习路径图")
        
        # 构建知识点列表（包含ID信息）
        kp_list = []
        kp_id_map = {}  # 保存ID映射关系
        for i, kp in enumerate(knowledge_points, 1):
            kp_id = f"kp_{kp['id']}"  # 使用数据库ID生成节点ID
            kp_info = f"{i}. {kp['point_name']} (ID: {kp_id}): {kp['core_description']}"
            kp_list.append(kp_info)
            kp_id_map[kp_id] = kp  # 保存ID到知识点的映射
        
        kp_text = "\n".join(kp_list)
        
        prompt = f"""作为一名{subject_name}领域的专家教师，请为学生制定一个**详细的线性学习计划**，类似鱼骨图结构。

**学生现有知识点：**
{kp_text}

**任务要求：**
1. **设计详细主线**：制定10-20个学习阶段，形成详细的线性路径，每个阶段专注一个具体学习目标
2. **细化学习进程**：将学习过程分解为更多细粒度的阶段，确保循序渐进
3. **知识点归类**：将学生的现有知识点归类到相应的学习阶段中
4. **补充缺失知识**：为每个阶段补充必要的前置知识或核心概念
5. **鱼骨图结构**：主线是学习阶段，知识点作为每个阶段的子节点

**设计原则：**
- **详细主线**：设计10-20个学习阶段，确保主线足够长，覆盖完整学习路径
- **细粒度阶段**：每个阶段专注1-2个核心概念，避免阶段过于宽泛
- **渐进式学习**：从最基础到最高级，每个阶段都是前一阶段的自然延续
- **知识归类**：现有知识点必须归属到某个stage
- **查漏补缺**：为缺少知识点的阶段补充必要内容
- **鱼骨结构**：主干是阶段，分支是具体知识点

**阶段设计建议：**
- 基础准备阶段可以分为：数学基础、编程基础、统计基础等多个阶段
- 核心概念可以分为：监督学习基础、无监督学习基础、深度学习基础等
- 算法学习可以分为：线性模型、树模型、集成方法、神经网络等多个阶段
- 实践应用可以分为：数据预处理、模型训练、模型评估、模型部署等阶段

**节点类型说明：**
- **stage**: 学习阶段（主线节点，如"基础阶段"、"核心阶段"）
- **existing_kp**: 学生已有知识点（归类到某个阶段下）
- **supplement_kp**: LLM补充的知识点（填补阶段缺失）
- **start**: 学习起点
- **end**: 学习终点

**输出格式：**
请返回鱼骨图结构的JSON，包含：
1. 线性主线：start → stage1 → stage2 → ... → end
2. 知识点分支：每个stage下挂载相关的知识点
3. 现有知识点归类：标注为existing_kp类型
4. 补充知识点：标注为supplement_kp类型

JSON格式示例：
{{
  "nodes": [
    {{"id": "start", "name": "开始学习{subject_name}", "type": "start", "level": 0, "description": "学习起点"}},
    {{"id": "stage1", "name": "基础准备阶段", "type": "stage", "level": 1, "description": "掌握必要的基础知识"}},
    {{"id": "stage2", "name": "核心概念阶段", "type": "stage", "level": 2, "description": "学习核心理论和方法"}},
    {{"id": "stage3", "name": "实践应用阶段", "type": "stage", "level": 3, "description": "动手实践和项目应用"}},
    {{"id": "end", "name": "掌握{subject_name}", "type": "end", "level": 4, "description": "完成学习目标"}},
    
    {{"id": "kp_math", "name": "数学基础", "type": "supplement_kp", "level": 1, "parent_stage": "stage1", "description": "LLM补充：线性代数、概率统计"}},
    {{"id": "kp_123", "name": "现有知识点名称", "type": "existing_kp", "level": 2, "parent_stage": "stage2", "description": "学生已掌握的概念"}},
    {{"id": "kp_project", "name": "项目实践", "type": "supplement_kp", "level": 3, "parent_stage": "stage3", "description": "LLM补充：综合项目练习"}}
  ],
  "edges": [
    {{"source": "start", "target": "stage1", "relationship": "开始学习"}},
    {{"source": "stage1", "target": "stage2", "relationship": "进入下一阶段"}},
    {{"source": "stage2", "target": "stage3", "relationship": "进入下一阶段"}},
    {{"source": "stage3", "target": "end", "relationship": "完成学习"}},
    
    {{"source": "stage1", "target": "kp_math", "relationship": "包含知识点"}},
    {{"source": "stage2", "target": "kp_123", "relationship": "包含知识点"}},
    {{"source": "stage3", "target": "kp_project", "relationship": "包含知识点"}}
  ]
}}

**重要要求：**
1. **主线必须线性**：start → stage1 → stage2 → ... → end
2. **知识点归类**：每个现有知识点必须归属到某个stage
3. **使用正确ID**：现有知识点必须使用提供的ID（如kp_123），不要自己编造
4. **补充缺失**：从严谨的学习路径设计角度，必须掌握的知识点必须要补充
5. **鱼骨结构**：stage是主干，knowledge_point是分支
6. **只返回JSON**：不要其他说明文字

请确保学习计划具有清晰的线性进阶路径！"""

        try:
            # 使用LLM提供者工厂（和知识脑图相同的机制）
            from llm_provider_factory import call_llm
            
            response = call_llm(prompt, context="generate_learning_path")
            
            if not response:
                print(f"❌ LLM返回空响应")
                return None
            
            print(f"🤖 LLM原始响应: {response[:500]}...")
            
            # 解析JSON响应（和知识脑图相同的解析逻辑）
            try:
                # 提取JSON部分
                json_start = response.find('{')
                json_end = response.rfind('}') + 1
                
                if json_start == -1 or json_end == 0:
                    print(f"❌ 响应中未找到JSON格式")
                    return None
                
                json_str = response[json_start:json_end]
                learning_path_data = json.loads(json_str)
                
                # 验证数据格式
                if not self._validate_learning_path_data(learning_path_data):
                    print(f"❌ 学习路径数据格式验证失败")
                    return None
                
                # 将原始知识点信息合并到生成的节点中
                self._merge_knowledge_point_info(learning_path_data, knowledge_points, kp_id_map)
                
                print(f"✅ 学习路径生成成功: {len(learning_path_data.get('nodes', []))}个节点, {len(learning_path_data.get('edges', []))}条路径")
                return learning_path_data
                
            except json.JSONDecodeError as e:
                print(f"❌ JSON解析失败: {e}")
                return None
                
        except Exception as e:
            print(f"❌ LLM调用失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _validate_learning_path_data(self, data: Dict) -> bool:
        """验证学习路径数据格式"""
        if not isinstance(data, dict):
            return False
        
        if 'nodes' not in data or 'edges' not in data:
            return False
        
        nodes = data['nodes']
        edges = data['edges']
        
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return False
        
        # 验证节点格式
        for node in nodes:
            if not isinstance(node, dict):
                return False
            required_fields = ['id', 'name', 'type']
            if not all(field in node for field in required_fields):
                return False
        
        # 验证边格式
        for edge in edges:
            if not isinstance(edge, dict):
                return False
            required_fields = ['source', 'target']
            if not all(field in edge for field in required_fields):
                return False
        
        return True
    
    def _save_learning_path_cache(self, subject_name: str, path_data: Dict, user_id: str = "0001") -> bool:
        """保存学习路径到缓存"""
        try:
            conn = self.db_manager.get_connection()
            cursor = conn.cursor()
            
            path_json = json.dumps(path_data, ensure_ascii=False)
            
            # 尝试更新现有记录
            cursor.execute(
                """UPDATE learning_paths 
                   SET path_data = ?, version = version + 1, updated_time = CURRENT_TIMESTAMP 
                   WHERE user_id = ? AND subject_name = ?""",
                (path_json, user_id, subject_name)
            )
            
            # 如果没有更新任何记录，则插入新记录
            if cursor.rowcount == 0:
                cursor.execute(
                    "INSERT INTO learning_paths (user_id, subject_name, path_data) VALUES (?, ?, ?)",
                    (user_id, subject_name, path_json)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ 保存学习路径缓存失败: {e}")
            return False
    
    def clear_learning_path_cache(self, subject_name: str, user_id: str = "0001") -> bool:
        """清除学科的学习路径缓存"""
        print(f"🗑️ 开始清除学科 '{subject_name}' 的学习路径缓存...")
        
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        try:
            # 先检查是否存在缓存
            cursor.execute(
                "SELECT COUNT(*) FROM learning_paths WHERE user_id = ? AND subject_name = ?",
                (user_id, subject_name)
            )
            count = cursor.fetchone()[0]
            
            if count == 0:
                print(f"⚠️ 没有找到学科 '{subject_name}' 的学习路径缓存")
                conn.close()
                return False
            
            # 删除缓存
            cursor.execute(
                "DELETE FROM learning_paths WHERE user_id = ? AND subject_name = ?",
                (user_id, subject_name)
            )
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted_count > 0:
                print(f"✅ 成功删除 {deleted_count} 条学习路径缓存记录")
                return True
            else:
                print(f"⚠️ 没有删除任何学习路径缓存记录")
                return False
                
        except Exception as e:
            print(f"❌ 清除学习路径缓存失败: {e}")
            conn.close()
            return False
    
    def _get_knowledge_points_by_subject(self, subject_name: str, user_id: str = "0001") -> List[Dict]:
        """获取学科下的知识点（内部方法）"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, point_name, core_description, mastery_score, created_time
                   FROM knowledge_points
                   WHERE user_id = ? AND subject_name = ?
                   ORDER BY created_time DESC""",
            (user_id, subject_name)
        )
        points: List[Dict] = []
        for row in cursor.fetchall():
            points.append({
                "id": row[0],
                "point_name": row[1],
                "core_description": row[2],
                "mastery_score": row[3],
                "created_time": row[4]
            })
        conn.close()
        return points
    
    def _merge_knowledge_point_info(self, learning_path_data: Dict, knowledge_points: List[Dict], kp_id_map: Dict) -> None:
        """将原始知识点信息合并到学习路径节点中"""
        print(f"📊 开始合并知识点信息，共有{len(kp_id_map)}个已有知识点")
        merged_count = 0
        
        # 更新学习路径中的知识点节点
        for node in learning_path_data.get('nodes', []):
            # 处理已有知识点和补充知识点
            if node.get('type') in ['existing_kp', 'supplement_kp', 'knowledge_point']:
                node_id = node.get('id', '')
                node_name = node.get('name', '')
                print(f"🔍 处理节点: {node_name} (ID: {node_id}, 类型: {node.get('type')})")
                
                # 优先通过ID匹配
                if node_id in kp_id_map:
                    kp_info = kp_id_map[node_id]
                    # 保存原始类型
                    original_type = node.get('type')
                    # 更新节点信息
                    node['original_kp_id'] = kp_info.get('id')
                    node['mastery_score'] = kp_info.get('mastery_score', 50)
                    node['point_name'] = kp_info.get('point_name')
                    if not node.get('description') or len(node.get('description', '')) < 20:
                        node['description'] = kp_info.get('core_description', '')[:100]
                    
                    # 如果是LLM补充的知识点，保持其supplement_kp类型，但添加标记
                    if original_type == 'supplement_kp':
                        node['is_llm_supplement'] = True
                        print(f"  ✅ ID匹配成功(LLM补充): {node_name} (ID: {node_id}) → 保持淡绿色显示")
                    else:
                        print(f"  ✅ ID匹配成功: {node_name} (ID: {node_id}) → 熟练度: {kp_info.get('mastery_score', 50)}")
                    merged_count += 1
                else:
                    # 如果ID匹配失败，尝试名称匹配（兼容性）
                    matched = False
                    for kp_id, kp_info in kp_id_map.items():
                        kp_name = kp_info.get('point_name', '')
                        
                        # 清理特殊字符的函数
                        def clean_text(text):
                            import re
                            # 移除常见特殊字符：反引号、斜杠、空格等
                            cleaned = re.sub(r'[`/\s\-_()（）【】\[\]{}]', '', text.lower())
                            return cleaned
                        
                        # 清理后的文本进行匹配
                        clean_kp_name = clean_text(kp_name)
                        clean_node_name = clean_text(node_name)
                        
                        # 多种匹配策略
                        if (kp_name.lower() in node_name.lower() or 
                            node_name.lower() in kp_name.lower() or
                            clean_kp_name in clean_node_name or
                            clean_node_name in clean_kp_name or
                            kp_name.replace(' ', '').lower() in node_name.replace(' ', '').lower()):
                            
                            # 保存原始类型
                            original_type = node.get('type')
                            # 更新节点信息
                            node['original_kp_id'] = kp_info.get('id')
                            node['mastery_score'] = kp_info.get('mastery_score', 50)
                            node['point_name'] = kp_info.get('point_name')
                            if not node.get('description') or len(node.get('description', '')) < 20:
                                node['description'] = kp_info.get('core_description', '')[:100]
                            
                            # 如果是LLM补充的知识点，保持其supplement_kp类型，但添加标记
                            if original_type == 'supplement_kp':
                                node['is_llm_supplement'] = True
                                print(f"  ✅ 名称匹配成功(LLM补充): {node_name} → {kp_name} → 保持淡绿色显示")
                            else:
                                print(f"  ✅ 名称匹配成功: {node_name} → {kp_name} (熟练度: {kp_info.get('mastery_score', 50)})")
                            merged_count += 1
                            matched = True
                            break
                    
                    if not matched:
                        # 对于已有知识点类型但没有匹配到的，设置默认熟练度
                        if node.get('type') == 'existing_kp':
                            node['mastery_score'] = 50  # 默认中等熟练度
                            print(f"  ⚠️ 未匹配到具体信息，设置默认熟练度: {node_name} (熟练度: 50)")
                        else:
                            node['mastery_score'] = -1  # 补充知识点默认未评估
                            print(f"  ℹ️ 补充知识点，设置未评估: {node_name} (熟练度: -1)")
        
        print(f"🔗 已合并知识点信息到学习路径节点，成功匹配 {merged_count} 个节点")
