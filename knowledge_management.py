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
                created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points (id),
                FOREIGN KEY (practice_record_id) REFERENCES practice_records (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)


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
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
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
    
    def _merge_descriptions(self, existing_desc: str, new_desc: str) -> str:
        """合并知识点描述"""
        # 简单合并逻辑，可以后续优化为AI合并
        if len(new_desc) > len(existing_desc):
            return new_desc
        return existing_desc
    
    def _merge_names(self, existing_name: str, new_name: str) -> str:
        """合并知识点名称"""
        # 简单合并逻辑，保持较短的名称
        if len(new_name) < len(existing_name):
            return new_name
        return existing_name
    
    def get_subject_knowledge_points(self, subject_name: str, user_id: str = "0001") -> List[Dict]:
        """获取学科下的所有知识点"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT id, point_name, core_description, mastery_score, created_time 
               FROM knowledge_points 
               WHERE user_id = ? AND subject_name = ? 
               ORDER BY created_time DESC""",
            (user_id, subject_name)
        )
        
        points = []
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


class PracticeRecordManager:
    """练习记录管理器"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def save_practice_record(self, subject_name: str, knowledge_point_id: int, 
                           question_content: str, user_answer: str, is_correct: bool,
                           user_id: str = "0001") -> int:
        """保存练习记录"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT INTO practice_records 
               (user_id, subject_name, knowledge_point_id, question_content, user_answer, is_correct) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, subject_name, knowledge_point_id, question_content, user_answer, int(is_correct))
        )
        
        record_id = cursor.lastrowid
        
        # 如果答错了，自动创建错题记录
        if not is_correct:
            cursor.execute(
                """INSERT INTO error_questions 
                   (user_id, subject_name, knowledge_point_id, practice_record_id) 
                   VALUES (?, ?, ?, ?)""",
                (user_id, subject_name, knowledge_point_id, record_id)
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
        """根据知识点获取错题"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            """SELECT eq.id, pr.question_content, pr.user_answer, pr.practice_time, eq.review_status
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
                "review_status": row[4]
            })
        
        conn.close()
        return errors
    
    def mark_as_reviewed(self, error_question_id: int) -> bool:
        """标记错题为已复习"""
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE error_questions SET review_status = 1 WHERE id = ?",
            (error_question_id,)
        )
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return success
    
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

        try:
            api_key = self.config.get("gemini_api_key", "")
            if not api_key:
                raise Exception("未配置Gemini API密钥")
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
            
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
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                    
                    # 清理和解析JSON
                    content = content.strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()
                    
                    questions = json.loads(content)
                    return questions
                else:
                    raise Exception("API返回格式异常")
            else:
                raise Exception(f"API调用失败: {response.status_code}")
                
        except Exception as e:
            print(f"生成新题失败: {e}")
            return []


class KnowledgeManagementSystem:
    """知识管理系统主类"""
    
    def __init__(self, config: dict):
        self.config = config
        self.db_manager = DatabaseManager()
        self.subject_manager = SubjectManager(self.db_manager)
        self.knowledge_manager = KnowledgePointManager(self.db_manager, config)
        self.practice_manager = PracticeRecordManager(self.db_manager)
        self.error_manager = ErrorQuestionManager(self.db_manager, config)
    
    def get_subjects(self) -> List[str]:
        """获取用户所有学科"""
        return self.subject_manager.get_user_subjects()
    
    def add_subject(self, subject_name: str) -> bool:
        """添加新学科"""
        return self.subject_manager.add_subject(subject_name)
    
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
        """确认知识点并保存"""
        saved_point_ids = []
        
        for confirmation in confirmations:
            action = confirmation["action"]  # "merge", "new", "skip"
            point_data = confirmation["point_data"]
            
            if action == "merge":
                # 合并到已有知识点
                existing_id = confirmation["existing_id"]
                success = self.knowledge_manager.merge_to_existing_point(existing_id, point_data)
                if success:
                    saved_point_ids.append(existing_id)
            
            elif action == "new":
                # 创建新知识点
                subject_name = confirmation["subject_name"]
                point_id = self.knowledge_manager.save_knowledge_point(
                    subject_name, 
                    point_data["point_name"], 
                    point_data["core_description"]
                )
                saved_point_ids.append(point_id)
        
        return saved_point_ids
    
    def get_knowledge_points_by_subject(self, subject_name: str) -> List[Dict]:
        """获取学科下的知识点"""
        return self.knowledge_manager.get_subject_knowledge_points(subject_name)
    
    def save_practice_results(self, practice_results: List[Dict]) -> List[int]:
        """保存练习结果"""
        record_ids = []
        
        for result in practice_results:
            record_id = self.practice_manager.save_practice_record(
                result["subject_name"],
                result["knowledge_point_id"],
                result["question_content"],
                result["user_answer"],
                result["is_correct"]
            )
            record_ids.append(record_id)
        
        return record_ids
    
    def get_error_questions(self, subject_name: str, knowledge_point_id: int) -> List[Dict]:
        """获取错题"""
        return self.error_manager.get_error_questions_by_knowledge_point(subject_name, knowledge_point_id)
    
    def mark_error_reviewed(self, error_question_id: int) -> bool:
        """标记错题为已复习"""
        return self.error_manager.mark_as_reviewed(error_question_id)
    
    def generate_new_questions(self, subject_name: str, knowledge_point_id: int, count: int = 2) -> List[Dict]:
        """生成新题"""
        return self.error_manager.generate_targeted_questions(subject_name, knowledge_point_id, count)
