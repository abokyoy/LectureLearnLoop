"""
增强的练习集成系统 - 专门处理错题切片和知识点归集
根据用户需求实现：错题自动切片、知识点匹配、手动归集兜底
"""

import json
import re
from typing import List, Dict, Optional, Tuple
from knowledge_management import KnowledgeManagementSystem
import requests
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox, QMessageBox, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt


class ErrorQuestionSlicer:
    """错题切片器 - 从完整练习结果中提取错题"""
    
    def __init__(self, config: dict):
        self.config = config
        self.km_system = KnowledgeManagementSystem(config)
    
    def slice_error_questions(self, practice_content: str, evaluation_result: str) -> List[Dict]:
        """
        从练习结果中切片错题
        
        Args:
            practice_content: 完整的练习内容（包含所有题目和用户答案）
            evaluation_result: AI评估结果
        
        Returns:
            List[Dict]: 错题列表，每个错题包含题目内容、用户答案、正确答案等信息
        """
        try:
            # 1. 解析评估结果，识别每题正误
            error_analysis = self._parse_error_analysis(evaluation_result)

            # 2. 优先从结构化评估报告中解析“原题/用户答案”以获得完整题干；否则回退到练习内容
            structured_questions = self._parse_questions_from_evaluation(evaluation_result)
            all_questions = structured_questions if structured_questions else self._parse_all_questions(practice_content)
            if not all_questions:
                # 若无法从 practice_content 恢复，尝试解析用户答案的简单行号映射
                answers_by_index = self._parse_user_answers_simple(practice_content)
                # 构造占位题目，至少保证索引与用户答案可用
                max_idx = max(error_analysis.keys(), default=-1)
                for i in range(max_idx + 1):
                    ua = answers_by_index.get(i, "")
                    all_questions.append({
                        "question": f"问题{i+1}",
                        "user_answer": ua
                    })

            # 3. 提取错题（以 error_analysis 为准，索引从0计）
            error_questions: List[Dict] = []
            for idx, info in error_analysis.items():
                if not info.get("is_correct", False):
                    q_data = all_questions[idx] if 0 <= idx < len(all_questions) else {"question": f"问题{idx+1}", "user_answer": "", "full_block": f"问题{idx+1}"}
                    error_questions.append({
                        "question_index": idx,
                        # 使用完整题块作为题目内容，包含选项/用户答案/判定/分析与要点
                        "question_content": q_data.get("full_block") or q_data.get("question", f"问题{idx+1}"),
                        "user_answer": q_data.get("user_answer", ""),
                        "correct_answer": info.get("correct_answer", ""),
                        "explanation": info.get("explanation", ""),
                        "knowledge_point_hint": info.get("knowledge_point", "")
                    })

            return error_questions

        except Exception as e:
            print(f"错题切片失败: {e}")
            return []
    
    def _parse_all_questions(self, practice_content: str) -> List[Dict]:
        """解析所有题目和用户答案"""
        questions = []
        
        # 多种解析模式
        patterns = [
            # 模式1: 题目X: ... 答案: ...
            r'题目\s*(\d+)[：:]\s*(.*?)\n.*?(?:我的)?答案[：:]\s*(.*?)(?=\n题目|\n\n|$)',
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
                        questions.append({
                            "question": match[1].strip(),
                            "user_answer": match[2].strip()
                        })
                break
        
        # 如果没有匹配到，尝试简单分割
        if not questions:
            questions = self._simple_parse_questions(practice_content)
        
        return questions

    def _parse_questions_from_evaluation(self, evaluation_result: str) -> List[Dict]:
        """从结构化评估报告中解析每题块（完整原文片段）及用户答案。
        预期格式（每题）：
        1. 原题：<题干全文>
        [可选]选项：...
        用户答案：...
        判定：正确/错误/无法判断
        分析与要点：...
        [分隔线 ---- 或 下一题号 或 整体评价 或 文末]
        返回的每个元素包含：
          - index: 题号(0基)
          - full_block: 从“原题：”开始到下一个分隔边界的完整文本
          - question: 尽力提取的题干文本（不含选项/答案部分，尽量用于兜底）
          - user_answer: 解析到的用户答案文本
        """
        try:
            blocks: List[Dict] = []
            # 使用 finditer 拿到整段 span 实现完整切片
            pattern = r"(?ms)^\s*(\d+)\.[ \t]*原题[：:][ \t]*\n?(.*?)(?=(?:\n----\s*$|\n\d+\.[ \t]*原题[：:]|\n整体评价|\Z))"
            for m in re.finditer(pattern, evaluation_result):
                try:
                    idx = int(m.group(1)) - 1
                except Exception:
                    continue
                full_block = m.group(0).strip()
                inner = m.group(2) or ""
                # 提取用户答案
                ua_match = re.search(r"用户答案[：:][ \t]*(.*)", full_block)
                user_answer = ua_match.group(1).strip() if ua_match else ""
                # 提取题干（尽量取到“选项/用户答案”之前）
                q_text = inner
                cut_points = []
                for tag in [r"\n选项[：:]", r"\n用户答案[：:]", r"\n判定[：:]", r"\n分析与要点[：:]"]:
                    mm = re.search(tag, inner)
                    if mm:
                        cut_points.append(mm.start())
                if cut_points:
                    q_text = inner[:min(cut_points)].strip()
                blocks.append({
                    "index": idx,
                    "full_block": full_block,
                    "question": q_text,
                    "user_answer": user_answer,
                })
            # 按索引排序，组装成顺序列表（缺失位置以空占位）
            if not blocks:
                return []
            max_idx = max(b["index"] for b in blocks)
            by_idx = {b["index"]: b for b in blocks}
            result: List[Dict] = []
            for i in range(max_idx + 1):
                b = by_idx.get(i)
                if b:
                    result.append({"question": b["question"], "user_answer": b["user_answer"], "full_block": b["full_block"]})
                else:
                    result.append({"question": f"问题{i+1}", "user_answer": "", "full_block": f"问题{i+1}"})
            return result
        except Exception:
            return []

    def _parse_user_answers_simple(self, practice_content: str) -> Dict[int, str]:
        """从 practice_content 中尽量提取 "题目和答案" 区域的按序号的用户答案映射。
        返回 {index0: answer_text, ...}
        """
        try:
            section = practice_content
            # 定位“题目和答案:”或其后内容
            m = re.search(r"题目和答案[:：]\s*(.*)$", practice_content, flags=re.DOTALL)
            if m:
                section = m.group(1)

            answers_by_index: Dict[int, str] = {}
            lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
            for ln in lines:
                # 匹配形如 "1.", "1、", "1:" 作为题号开头
                mm = re.match(r"^(\d+)[\.、:：]?\s*(.*)$", ln)
                if mm:
                    idx = int(mm.group(1)) - 1
                    val = mm.group(2).strip()
                    # 累积（多行情况）
                    prev = answers_by_index.get(idx, "")
                    answers_by_index[idx] = (prev + " " + val).strip() if prev else val
            return answers_by_index
        except Exception:
            return {}
    
    def _simple_parse_questions(self, content: str) -> List[Dict]:
        """简单解析题目（兜底方案）"""
        questions = []
        lines = content.split('\n')
        current_question = ""
        current_answer = ""
        in_answer = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if re.match(r'^\d+[\.、]', line) or '题目' in line or '问题' in line:
                if current_question and current_answer:
                    questions.append({
                        "question": current_question,
                        "user_answer": current_answer
                    })
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
            questions.append({
                "question": current_question,
                "user_answer": current_answer
            })
        
        return questions
    
    def _parse_error_analysis(self, evaluation_result: str) -> Dict[int, Dict]:
        """解析评估结果中的错题分析"""
        error_analysis = {}
        
        # 先尝试解析新格式：按“原题/用户答案/判定/分析与要点”结构
        try:
            pattern = r"(?ms)^\s*(\d+)\.[ \t]*原题[：:][ \t]*\n?(.*?)(?:\n选项[：:].*?)?\n用户答案[：:][ \t]*(.*?)\n判定[：:][ \t]*([^\n]+)\n(?:分析与要点[：:][ \t]*(.*?))?(?=(?:\n----|\n\d+\.|\n整体评价|$))"
            matches = re.findall(pattern, evaluation_result)
            for m in matches:
                try:
                    idx = int(m[0]) - 1
                    verdict = (m[3] or "").strip()
                    analysis_text = (m[4] or "").strip()
                    text_norm = (verdict + " " + analysis_text).replace('\n', ' ')
                    wrong_keywords = ['错误', '不正确', '答错', '×']
                    right_keywords = ['正确', '答对', '✓']
                    unknown_keywords = ['无法评估', '无法判断', '无法确定']

                    is_unknown = any(kw in verdict for kw in unknown_keywords)
                    is_wrong = any(kw in verdict for kw in wrong_keywords)
                    is_right = (not is_wrong) and any(kw in verdict for kw in right_keywords)
                    if is_unknown:
                        continue
                    is_correct = bool(is_right)

                    # 尝试在分析中抽取正确答案
                    correct_answer = ""
                    for cp in [r'正确答案[是为：:]\s*([^\n。]+)', r'应该[是为：:]\s*([^\n。]+)', r'答案[是为：:]\s*([^\n。]+)']:
                        ca = re.search(cp, analysis_text)
                        if ca:
                            correct_answer = ca.group(1).strip()
                            break

                    # 知识点提示提取
                    knowledge_point = ""
                    for kp in [r'知识点[：:]\s*([^\n。]+)', r'涉及[：:]\s*([^\n。]+)', r'考查[：:]\s*([^\n。]+)']:
                        kpm = re.search(kp, analysis_text)
                        if kpm:
                            knowledge_point = kpm.group(1).strip()
                            break

                    error_analysis[idx] = {
                        "is_correct": is_correct,
                        "correct_answer": correct_answer,
                        "explanation": analysis_text if analysis_text else verdict,
                        "knowledge_point": knowledge_point
                    }
                except Exception:
                    continue
        except Exception:
            pass

        # 兼容旧格式：题目X/第X题/X.
        if not error_analysis:
            patterns = [
                r'题目\s*(\d+)[：:]\s*(.*?)(?=题目\s*\d+|$)',
                r'第\s*(\d+)\s*题[：:]\s*(.*?)(?=第\s*\d+\s*题|$)',
                r'(\d+)\.\s*(.*?)(?=\d+\.|$)',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, evaluation_result, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    try:
                        question_num = int(match[0]) - 1
                        analysis_text = match[1].strip()
                        text_norm = analysis_text.replace('\n', ' ')
                        wrong_keywords = ['错误', '不正确', '答错', '×']
                        right_keywords = ['正确', '答对', '✓']
                        unknown_keywords = ['无法评估', '无法判断', '无法确定']
                        is_unknown = any(kw in text_norm for kw in unknown_keywords)
                        is_wrong = any(kw in text_norm for kw in wrong_keywords)
                        is_right = (not is_wrong) and any(kw in text_norm for kw in right_keywords)
                        if is_unknown:
                            continue
                        is_correct = bool(is_right)

                        correct_answer = ""
                        for cp in [r'正确答案[是为：:]\s*([^\n。]+)', r'应该[是为：:]\s*([^\n。]+)', r'答案[是为：:]\s*([^\n。]+)']:
                            ca_match = re.search(cp, analysis_text)
                            if ca_match:
                                correct_answer = ca_match.group(1).strip()
                                break
                        knowledge_point = ""
                        for kp in [r'知识点[：:]\s*([^\n。]+)', r'涉及[：:]\s*([^\n。]+)', r'考查[：:]\s*([^\n。]+)']:
                            kp_match = re.search(kp, analysis_text)
                            if kp_match:
                                knowledge_point = kp_match.group(1).strip()
                                break
                        error_analysis[question_num] = {
                            "is_correct": is_correct,
                            "correct_answer": correct_answer,
                            "explanation": analysis_text,
                            "knowledge_point": knowledge_point
                        }
                    except Exception:
                        continue
        
        return error_analysis


class KnowledgePointMatcher:
    """知识点匹配器 - 为错题匹配知识点"""
    
    def __init__(self, config: dict):
        self.config = config
        self.km_system = KnowledgeManagementSystem(config)
    
    def match_knowledge_points(self, error_questions: List[Dict], note_content: str = "") -> List[Dict]:
        """
        为错题匹配知识点
        
        Args:
            error_questions: 错题列表
            note_content: 原始笔记内容（用于推断学科）
        
        Returns:
            List[Dict]: 带有知识点匹配信息的错题列表
        """
        try:
            # 1. 推断学科
            subject_name = self._infer_subject(note_content, error_questions)
            
            # 2. 获取该学科的所有知识点
            knowledge_points = self.km_system.get_knowledge_points_by_subject(subject_name)
            
            # 3. 为每道错题匹配知识点
            matched_errors = []
            for error in error_questions:
                matched_point_id = self._match_single_question(error, knowledge_points)
                
                error_with_match = error.copy()
                error_with_match.update({
                    "subject_name": subject_name,
                    "matched_knowledge_point_id": matched_point_id,
                    "match_confidence": "high" if matched_point_id else "low"
                })
                
                matched_errors.append(error_with_match)
            
            return matched_errors
            
        except Exception as e:
            print(f"知识点匹配失败: {e}")
            return error_questions
    
    def _infer_subject(self, note_content: str, error_questions: List[Dict]) -> str:
        """推断学科"""
        # 学科关键词映射
        subject_keywords = {
            "机器学习": ["机器学习", "深度学习", "神经网络", "算法", "模型", "训练", "梯度", "损失函数", "回归", "分类"],
            "Python编程": ["python", "编程", "代码", "函数", "类", "模块", "库", "语法", "变量", "循环"],
            "数据结构": ["数据结构", "算法", "链表", "树", "图", "排序", "查找", "复杂度", "栈", "队列"],
            "数学": ["数学", "微积分", "线性代数", "概率", "统计", "函数", "方程", "矩阵", "导数", "积分"],
            "计算机网络": ["网络", "协议", "TCP", "HTTP", "IP", "路由", "交换", "OSI", "socket"],
            "操作系统": ["操作系统", "进程", "线程", "内存", "文件系统", "调度", "同步", "死锁"],
        }
        
        # 合并所有文本内容
        all_text = note_content + " " + " ".join([
            q.get("question_content", "") + " " + q.get("knowledge_point_hint", "")
            for q in error_questions
        ])
        all_text_lower = all_text.lower()
        
        # 计算匹配分数
        best_subject = "通用学科"
        best_score = 0
        
        for subject, keywords in subject_keywords.items():
            score = sum(1 for keyword in keywords if keyword.lower() in all_text_lower)
            if score > best_score:
                best_score = score
                best_subject = subject
        
        return best_subject
    
    def _match_single_question(self, error_question: Dict, knowledge_points: List[Dict]) -> Optional[int]:
        """为单个错题匹配知识点"""
        if not knowledge_points:
            return None
        
        question_content = error_question.get("question_content", "")
        knowledge_hint = error_question.get("knowledge_point_hint", "")
        
        # 如果有知识点提示，优先使用提示匹配
        if knowledge_hint:
            for point in knowledge_points:
                if (knowledge_hint.lower() in point["point_name"].lower() or 
                    knowledge_hint.lower() in point["core_description"].lower()):
                    return point["id"]
        
        # 先使用轻量相似度匹配（低耦合，可替换）
        try:
            from similarity_matcher import best_match
            bm = best_match(question_content, knowledge_points)
            if bm and bm.get("id"):
                return bm["id"]
        except Exception as e:
            print(f"相似度匹配失败（忽略，继续AI/兜底）: {e}")

        # 再尝试可选的AI匹配（如果开启并且有API密钥）
        ai_match_id = self._ai_match_knowledge_point(question_content, knowledge_points)
        if ai_match_id:
            return ai_match_id
        
        # 兜底：返回第一个知识点
        return knowledge_points[0]["id"] if knowledge_points else None
    
    def _ai_match_knowledge_point(self, question: str, knowledge_points: List[Dict]) -> Optional[int]:
        """使用AI匹配知识点"""
        try:
            # 默认关闭逐题AI匹配以避免N次LLM调用，可在配置中通过 enable_ai_match_knowledge_point 开启
            if not self.config.get("enable_ai_match_knowledge_point", False):
                # 可选：打印一次说明，帮助排查
                # print("[知识点匹配] 已禁用逐题AI匹配（enable_ai_match_knowledge_point=false）")
                return None
            api_key = self.config.get("gemini_api_key", "")
            if not api_key:
                return None
            
            # 构建知识点列表
            points_text = "\n".join([
                f"{i+1}. {point['point_name']} - {point['core_description']}"
                for i, point in enumerate(knowledge_points)
            ])
            
            prompt = f"""请分析以下错题，从给定的知识点列表中选择最相关的一个。

错题：{question}

知识点列表：
{points_text}

请只返回最相关知识点的序号（1-{len(knowledge_points)}），如果都不相关请返回0。"""

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
                    numbers = re.findall(r'\d+', content)
                    if numbers:
                        index = int(numbers[0]) - 1  # 转换为0基索引
                        if 0 <= index < len(knowledge_points):
                            return knowledge_points[index]["id"]
            
            return None
            
        except Exception as e:
            print(f"AI匹配知识点失败: {e}")
            return None


class ManualKnowledgePointSelector(QDialog):
    """手动知识点选择对话框 - 当自动匹配失败时使用"""
    
    def __init__(self, error_questions: List[Dict], config: dict, parent=None):
        super().__init__(parent)
        self.error_questions = error_questions
        self.config = config
        self.km_system = KnowledgeManagementSystem(config)
        self.selected_mappings = {}  # {error_index: knowledge_point_id}
        
        self.setWindowTitle("手动选择知识点")
        self.setModal(True)
        self.resize(700, 500)
        
        self._setup_ui()
        self._load_data()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("以下错题无法自动匹配知识点，请手动选择：")
        title_label.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # 错题列表
        self.error_list = QListWidget()
        self.error_list.itemSelectionChanged.connect(self._on_error_selection_changed)
        layout.addWidget(self.error_list)
        
        # 知识点选择
        selection_layout = QHBoxLayout()
        selection_layout.addWidget(QLabel("选择知识点:"))
        
        self.knowledge_combo = QComboBox()
        selection_layout.addWidget(self.knowledge_combo)
        
        self.btn_assign = QPushButton("分配")
        self.btn_assign.clicked.connect(self._assign_knowledge_point)
        self.btn_assign.setEnabled(False)
        selection_layout.addWidget(self.btn_assign)
        
        layout.addLayout(selection_layout)
        
        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.btn_ok = QPushButton("确定")
        self.btn_ok.clicked.connect(self.accept)
        button_layout.addWidget(self.btn_ok)
        
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(button_layout)
    
    def _load_data(self):
        """加载数据"""
        # 加载错题
        for i, error in enumerate(self.error_questions):
            if not error.get("matched_knowledge_point_id"):
                question_text = error.get("question_content", "")[:100] + "..."
                item = QListWidgetItem(f"题目 {i+1}: {question_text}")
                item.setData(Qt.ItemDataRole.UserRole, i)
                self.error_list.addItem(item)
        
        # 加载知识点
        try:
            subjects = self.km_system.get_subjects()
            all_knowledge_points = []
            
            for subject in subjects:
                points = self.km_system.get_knowledge_points_by_subject(subject)
                for point in points:
                    all_knowledge_points.append({
                        "id": point["id"],
                        "display_name": f"{subject} - {point['point_name']}"
                    })
            
            self.knowledge_combo.clear()
            for point in all_knowledge_points:
                self.knowledge_combo.addItem(point["display_name"], point["id"])
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载知识点失败: {e}")
    
    def _on_error_selection_changed(self):
        """错题选择改变"""
        selected_items = self.error_list.selectedItems()
        self.btn_assign.setEnabled(len(selected_items) > 0)
    
    def _assign_knowledge_point(self):
        """分配知识点"""
        selected_items = self.error_list.selectedItems()
        if not selected_items:
            return
        
        knowledge_point_id = self.knowledge_combo.currentData()
        if not knowledge_point_id:
            return
        
        for item in selected_items:
            error_index = item.data(Qt.ItemDataRole.UserRole)
            self.selected_mappings[error_index] = knowledge_point_id
            
            # 更新显示
            item.setText(item.text() + " [已分配]")
            item.setBackground(Qt.GlobalColor.lightGray)
    
    def get_mappings(self) -> Dict[int, int]:
        """获取映射结果"""
        return self.selected_mappings


class EnhancedPracticeProcessor:
    """增强的练习处理器 - 完整的错题处理流程"""
    
    def __init__(self, config: dict):
        self.config = config
        self.slicer = ErrorQuestionSlicer(config)
        self.matcher = KnowledgePointMatcher(config)
        self.km_system = KnowledgeManagementSystem(config)
    
    def process_practice_results(self, practice_content: str, evaluation_result: str, 
                               note_content: str = "", parent_widget=None) -> Dict:
        """
        处理练习结果的完整流程
        
        Args:
            practice_content: 练习内容
            evaluation_result: 评估结果
            note_content: 原始笔记内容
            parent_widget: 父窗口（用于显示对话框）
        
        Returns:
            Dict: 处理结果
        """
        try:
            # 1. 切片错题
            error_questions = self.slicer.slice_error_questions(practice_content, evaluation_result)
            
            if not error_questions:
                return {
                    "success": True,
                    "message": "本次练习没有错题，表现优秀！",
                    "error_count": 0,
                    "saved_count": 0
                }
            
            # 2. 匹配知识点
            matched_errors = self.matcher.match_knowledge_points(error_questions, note_content)
            
            # 3. 处理无法匹配的错题
            unmatched_errors = [e for e in matched_errors if not e.get("matched_knowledge_point_id")]
            
            if unmatched_errors and parent_widget:
                # 显示手动选择对话框
                selector = ManualKnowledgePointSelector(unmatched_errors, self.config, parent_widget)
                if selector.exec() == QDialog.DialogCode.Accepted:
                    mappings = selector.get_mappings()
                    
                    # 应用手动映射
                    for i, error in enumerate(matched_errors):
                        if i in mappings:
                            error["matched_knowledge_point_id"] = mappings[i]
                            error["match_confidence"] = "manual"
            
            # 4. 保存错题到知识库
            saved_count = 0
            for error in matched_errors:
                if error.get("matched_knowledge_point_id"):
                    try:
                        practice_results = [{
                            "subject_name": error.get("subject_name", "通用学科"),
                            "knowledge_point_id": error["matched_knowledge_point_id"],
                            "question_content": error["question_content"],
                            "user_answer": error["user_answer"],
                            "is_correct": False,
                            "correct_answer": error.get("correct_answer"),
                            "explanation": error.get("explanation"),
                        }]
                        
                        record_ids = self.km_system.save_practice_results(practice_results)
                        if record_ids:
                            saved_count += len(record_ids)
                            
                    except Exception as e:
                        print(f"保存错题失败: {e}")
            
            return {
                "success": True,
                "message": f"处理完成：共 {len(error_questions)} 道错题，成功保存 {saved_count} 道到知识库",
                "error_count": len(error_questions),
                "saved_count": saved_count,
                "unmatched_count": len([e for e in matched_errors if not e.get("matched_knowledge_point_id")])
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"处理练习结果失败: {e}",
                "error_count": 0,
                "saved_count": 0
            }
