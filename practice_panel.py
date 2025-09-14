import sys
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QScrollArea, QSplitter, QMessageBox, QProgressBar, QGroupBox
)
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject
import requests
import json
from datetime import datetime


class PracticeWorker(QObject):
    """Worker thread for generating practice questions and evaluating answers"""
    questionsReady = Signal(str)  # Generated questions in markdown format
    evaluationReady = Signal(str)  # Evaluation results in markdown format
    status = Signal(str)
    finished = Signal()
    
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.selected_text = ""
        self.user_answers = ""
        self.mode = "generate"  # "generate" or "evaluate"
    
    def generate_questions(self, selected_text: str):
        """Generate practice questions based on selected text"""
        self.selected_text = selected_text
        self.mode = "generate"
        self.start_work()
    
    def evaluate_answers(self, selected_text: str, user_answers: str):
        """Evaluate user answers and provide explanations"""
        self.selected_text = selected_text
        self.user_answers = user_answers
        self.mode = "evaluate"
        self.start_work()
    
    def start_work(self):
        """Start the work based on mode"""
        try:
            if self.mode == "generate":
                self._generate_practice_questions()
            elif self.mode == "evaluate":
                self._evaluate_user_answers()
        except Exception as e:
            self.status.emit(f"处理错误: {e}")
        finally:
            self.finished.emit()
    
    def _generate_practice_questions(self):
        """Generate practice questions using LLM"""
        self.status.emit("正在生成练习题目...")
        
        prompt = f"""请基于以下内容生成一套技术面试/笔试题目。要求：

1. 生成5-8道题目，包含不同类型：选择题、简答题、编程题、案例分析题
2. 题目要有一定难度梯度，从基础到进阶
3. 只提供题目，不要提供答案
4. 使用Markdown格式输出
5. 每道题目之间留出足够的答题空间

基础内容：
{self.selected_text}

请生成练习题目："""

        try:
            # Use Gemini API
            api_key = self.config.get("gemini_api_key", "")
            if not api_key:
                self.status.emit("错误: 未配置Gemini API密钥")
                return
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.7,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 2048,
                }
            }
            
            headers = {"Content-Type": "application/json"}
            
            self.status.emit("正在调用Gemini API生成题目...")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                    self.questionsReady.emit(content)
                    self.status.emit("题目生成完成")
                else:
                    self.status.emit("API返回格式异常")
            else:
                self.status.emit(f"API调用失败: {response.status_code}")
                
        except Exception as e:
            self.status.emit(f"生成题目时发生错误: {e}")
    
    def _evaluate_user_answers(self):
        """Evaluate user answers using LLM"""
        self.status.emit("正在评估答案...")
        
        prompt = f"""请作为专业技术面试官，对以下用户答案进行评估和讲解。

原始学习内容：
{self.selected_text}

用户的答题内容：
{self.user_answers}

请按以下格式提供评估：

## 答题评估报告

### 整体评价
[对用户整体答题情况的评价]

### 逐题分析
[对每道题目进行详细分析，包括：]
- 题目要点
- 用户答案分析
- 正确答案要点
- 改进建议

### 学习建议
[基于答题情况提供的学习建议]

请用Markdown格式输出，内容要专业、详细、有建设性。"""

        try:
            # Use Gemini API
            api_key = self.config.get("gemini_api_key", "")
            if not api_key:
                self.status.emit("错误: 未配置Gemini API密钥")
                return
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
            
            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.3,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 3072,
                }
            }
            
            headers = {"Content-Type": "application/json"}
            
            self.status.emit("正在调用Gemini API评估答案...")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                    self.evaluationReady.emit(content)
                    self.status.emit("答案评估完成")
                else:
                    self.status.emit("API返回格式异常")
            else:
                self.status.emit(f"API调用失败: {response.status_code}")
                
        except Exception as e:
            self.status.emit(f"评估答案时发生错误: {e}")


class PracticePanel(QWidget):
    """Practice panel for generating and solving practice questions"""
    
    def __init__(self, selected_text: str, insert_position: int, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("技术练习面板")
        self.resize(1000, 800)
        
        # Set window flags to make it a proper window (like ChatbotPanel)
        self.setWindowFlags(Qt.WindowType.Window)
        
        # Set background color to avoid transparency
        self.setStyleSheet("QWidget { background-color: #f0f0f0; }")
        
        self.selected_text = selected_text
        self.insert_position = insert_position
        self.config = config
        self.practice_id = self._generate_practice_id()
        
        # Setup UI
        self._setup_ui()
        
        # Start generating questions
        self._generate_questions()
    
    def _generate_practice_id(self):
        """Generate unique practice ID"""
        return datetime.now().strftime('%Y%m%d_%H%M%S')
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Toolbar with controls (similar to ChatbotPanel)
        toolbar_layout = QHBoxLayout()
        
        self.regenerate_btn = QPushButton("重新生成题目")
        self.regenerate_btn.clicked.connect(self._regenerate_questions)
        self.regenerate_btn.setEnabled(False)
        toolbar_layout.addWidget(self.regenerate_btn)
        
        self.submit_btn = QPushButton("提交练习")
        self.submit_btn.clicked.connect(self._submit_practice)
        self.submit_btn.setEnabled(False)
        toolbar_layout.addWidget(self.submit_btn)
        
        toolbar_layout.addStretch()
        
        self.practice_label = QLabel(f"练习ID: {self.practice_id}")
        self.practice_label.setStyleSheet("color: #666; font-size: 10px;")
        toolbar_layout.addWidget(self.practice_label)
        
        layout.addLayout(toolbar_layout)
        
        # Status bar
        self.status_label = QLabel("正在生成练习题目...")
        self.status_label.setStyleSheet("color: #666; padding: 5px;")
        layout.addWidget(self.status_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        layout.addWidget(self.progress_bar)
        
        # Main practice area (similar to ChatbotPanel's chat area)
        practice_group = QGroupBox("技术练习")
        practice_layout = QVBoxLayout(practice_group)
        
        # Practice editor with proper styling
        self.practice_editor = QTextEdit()
        self.practice_editor.setPlaceholderText("练习题目将在这里显示，您可以在题目下方填写答案...")
        self.practice_editor.setFont(QFont("微软雅黑", 11))
        practice_layout.addWidget(self.practice_editor)
        
        layout.addWidget(practice_group)
        
        # Original content display (moved to bottom, smaller)
        content_group = QGroupBox("学习内容")
        content_layout = QVBoxLayout(content_group)
        
        self.content_display = QTextEdit()
        self.content_display.setReadOnly(True)
        self.content_display.setPlainText(self.selected_text)
        self.content_display.setMaximumHeight(150)  # Limit height instead of width
        self.content_display.setFont(QFont("微软雅黑", 9))
        content_layout.addWidget(self.content_display)
        
        layout.addWidget(content_group)
        
        # Bottom buttons (similar to ChatbotPanel)
        bottom_layout = QHBoxLayout()
        
        save_button = QPushButton("保存练习")
        save_button.clicked.connect(self._save_practice)
        bottom_layout.addWidget(save_button)
        
        bottom_layout.addStretch()
        
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        bottom_layout.addWidget(close_button)
        
        layout.addLayout(bottom_layout)
        
        # Setup worker thread
        self.worker_thread = QThread()
        self.worker = PracticeWorker(self.config)
        self.worker.moveToThread(self.worker_thread)
        
        # Connect signals
        self.worker.questionsReady.connect(self._on_questions_ready)
        self.worker.evaluationReady.connect(self._on_evaluation_ready)
        self.worker.status.connect(self._on_status_update)
        self.worker.finished.connect(self._on_worker_finished)
        
        self.worker_thread.started.connect(self.worker.start_work)
    
    def _generate_questions(self):
        """Generate practice questions"""
        self.status_label.setText("正在生成练习题目...")
        self.progress_bar.show()
        self.regenerate_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)
        
        if not self.worker_thread.isRunning():
            self.worker.generate_questions(self.selected_text)
            self.worker_thread.start()
    
    def _regenerate_questions(self):
        """Regenerate practice questions"""
        self._generate_questions()
    
    def _submit_practice(self):
        """Submit practice for evaluation"""
        user_answers = self.practice_editor.toPlainText().strip()
        if not user_answers:
            QMessageBox.warning(self, "提示", "请先完成练习题目再提交。")
            return
        
        self.status_label.setText("正在评估答案...")
        self.progress_bar.show()
        self.regenerate_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)
        
        if not self.worker_thread.isRunning():
            self.worker.evaluate_answers(self.selected_text, user_answers)
            self.worker_thread.start()
    
    def _on_questions_ready(self, questions: str):
        """Handle generated questions"""
        self.practice_editor.setPlainText(questions)
        
    def _on_evaluation_ready(self, evaluation: str):
        """Handle evaluation results"""
        # Show evaluation in a new window or replace current content
        self.practice_editor.setPlainText(evaluation)
        
        # Add option to start new practice
        self.regenerate_btn.setText("开始新练习")
        self.submit_btn.setText("保存评估结果")
        
    def _save_practice(self):
        """Save practice content"""
        try:
            import os
            import json
            from datetime import datetime
            
            # Create practice directory if it doesn't exist
            practice_dir = "practice_sessions"
            os.makedirs(practice_dir, exist_ok=True)
            
            # Save practice data
            practice_data = {
                "practice_id": self.practice_id,
                "timestamp": datetime.now().isoformat(),
                "selected_text": self.selected_text,
                "practice_content": self.practice_editor.toPlainText(),
                "status": "completed" if "评估结果" in self.practice_editor.toPlainText() else "in_progress"
            }
            
            filename = os.path.join(practice_dir, f"practice_{self.practice_id}.json")
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(practice_data, f, ensure_ascii=False, indent=2)
            
            self.status_label.setText(f"练习已保存: {filename}")
            
        except Exception as e:
            self.status_label.setText(f"保存失败: {e}")
    
    def _on_status_update(self, status: str):
        """Handle status updates"""
        self.status_label.setText(status)
    
    def _on_worker_finished(self):
        """Handle worker finished"""
        self.progress_bar.hide()
        self.regenerate_btn.setEnabled(True)
        self.submit_btn.setEnabled(True)
        
        if self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
    
    def closeEvent(self, event):
        """Handle window close event"""
        if self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
        super().closeEvent(event)
