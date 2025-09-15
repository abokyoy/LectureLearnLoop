import sys
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QScrollArea, QSplitter, QMessageBox, QProgressBar, QGroupBox,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QTextBrowser
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

### 知识点掌握程度评估
请对以下知识点的掌握程度进行评估（1-5分，5分为完全掌握）：
- 基础概念理解: [分数]/5 - [简要说明]
- 实际应用能力: [分数]/5 - [简要说明]
- 深度思考能力: [分数]/5 - [简要说明]
- 综合运用能力: [分数]/5 - [简要说明]

### 学习建议
[基于答题情况和掌握程度评估提供的学习建议]

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


class PracticeHistoryDialog(QDialog):
    """Dialog for managing practice history"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("练习历史")
        self.resize(800, 600)
        self.selected_practice = None
        
        self._setup_ui()
        self._load_practice_history()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("选择要加载的练习历史:")
        title_label.setFont(QFont("微软雅黑", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # Practice list
        self.practice_list = QListWidget()
        self.practice_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.practice_list)
        
        # Preview area
        preview_group = QGroupBox("预览")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_browser = QTextBrowser()
        self.preview_browser.setMaximumHeight(200)
        preview_layout.addWidget(self.preview_browser)
        
        layout.addWidget(preview_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.load_button = QPushButton("加载练习")
        self.load_button.clicked.connect(self._load_selected_practice)
        self.load_button.setEnabled(False)
        
        self.delete_button = QPushButton("删除练习")
        self.delete_button.clicked.connect(self._delete_selected_practice)
        self.delete_button.setEnabled(False)
        
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.load_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Connect list selection
        self.practice_list.itemSelectionChanged.connect(self._on_selection_changed)
    
    def _load_practice_history(self):
        """Load practice history from files"""
        try:
            practice_dir = "practice_sessions"
            if not os.path.exists(practice_dir):
                return
            
            practice_files = [f for f in os.listdir(practice_dir) if f.startswith("practice_") and f.endswith(".json")]
            practice_files.sort(reverse=True)  # Most recent first
            
            for filename in practice_files:
                filepath = os.path.join(practice_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        practice_data = json.load(f)
                    
                    # Create list item
                    timestamp = practice_data.get("timestamp", "")
                    practice_id = practice_data.get("practice_id", "")
                    status = practice_data.get("status", "unknown")
                    
                    # Format display text
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            time_str = timestamp
                    else:
                        time_str = "未知时间"
                    
                    status_text = {"completed": "已完成", "in_progress": "进行中", "evaluated": "已评估"}.get(status, status)
                    
                    display_text = f"[{status_text}] {time_str} - ID: {practice_id}"
                    
                    item = QListWidgetItem(display_text)
                    item.setData(Qt.ItemDataRole.UserRole, practice_data)
                    self.practice_list.addItem(item)
                    
                except Exception as e:
                    print(f"加载练习文件失败 {filename}: {e}")
                    
        except Exception as e:
            print(f"加载练习历史失败: {e}")
    
    def _on_selection_changed(self):
        """Handle list selection change"""
        current_item = self.practice_list.currentItem()
        if current_item:
            practice_data = current_item.data(Qt.ItemDataRole.UserRole)
            self._show_preview(practice_data)
            self.load_button.setEnabled(True)
            self.delete_button.setEnabled(True)
        else:
            self.preview_browser.clear()
            self.load_button.setEnabled(False)
            self.delete_button.setEnabled(False)
    
    def _show_preview(self, practice_data):
        """Show preview of selected practice"""
        if not practice_data:
            return
        
        selected_text = practice_data.get("selected_text", "")[:200]
        user_answers = practice_data.get("user_answers", practice_data.get("answers", ""))[:300]
        evaluation_result = practice_data.get("evaluation_result", "")[:300]
        
        preview_html = f"""
        <h3>学习内容预览:</h3>
        <p>{selected_text}...</p>
        <h3>用户答案预览:</h3>
        <p>{user_answers}...</p>
        """
        
        if evaluation_result:
            preview_html += f"""
            <h3>评估结果预览:</h3>
            <p>{evaluation_result}...</p>
            """
        
        self.preview_browser.setHtml(preview_html)
    
    def _on_item_double_clicked(self, item):
        """Handle double click on item"""
        self._load_selected_practice()
    
    def _load_selected_practice(self):
        """Load selected practice"""
        current_item = self.practice_list.currentItem()
        if current_item:
            self.selected_practice = current_item.data(Qt.ItemDataRole.UserRole)
            self.accept()
    
    def _delete_selected_practice(self):
        """Delete selected practice"""
        current_item = self.practice_list.currentItem()
        if not current_item:
            return
        
        practice_data = current_item.data(Qt.ItemDataRole.UserRole)
        practice_id = practice_data.get("practice_id", "")
        
        reply = QMessageBox.question(
            self, "确认删除", 
            f"确定要删除练习 {practice_id} 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Delete file
                filename = f"practice_{practice_id}.json"
                filepath = os.path.join("practice_sessions", filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
                
                # Remove from list
                row = self.practice_list.row(current_item)
                self.practice_list.takeItem(row)
                
            except Exception as e:
                QMessageBox.warning(self, "删除失败", f"删除练习失败: {e}")
    
    def get_selected_practice(self):
        """Get selected practice data"""
        return self.selected_practice


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
        self.practice_history = []
        self.evaluation_result = ""
        self.current_questions = ""
        self.current_answers = ""
        self.user_answers_before_evaluation = ""
        
        # Setup UI
        self._setup_ui()
        
        # Only start generating questions if not loading from history
        self._loading_from_history = False
        if not self._loading_from_history:
            self._generate_questions()
    
    def _generate_practice_id(self):
        """Generate unique practice ID"""
        return datetime.now().strftime('%Y%m%d_%H%M%S')
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Toolbar with controls (similar to ChatbotPanel)
        toolbar_layout = QHBoxLayout()
        
        self.history_button = QPushButton("练习历史")
        self.history_button.clicked.connect(self._show_history)
        toolbar_layout.addWidget(self.history_button)
        
        self.new_practice_button = QPushButton("新练习")
        self.new_practice_button.clicked.connect(self._start_new_practice)
        toolbar_layout.addWidget(self.new_practice_button)
        
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
        
        # Original content display (collapsible, collapsed by default)
        self.content_group = QGroupBox("学习内容 (点击展开/收缩)")
        self.content_group.setCheckable(True)
        self.content_group.setChecked(False)  # Collapsed by default
        content_layout = QVBoxLayout(self.content_group)
        
        self.content_display = QTextEdit()
        self.content_display.setReadOnly(True)
        self.content_display.setPlainText(self.selected_text)
        self.content_display.setMaximumHeight(150)  # Limit height when expanded
        self.content_display.setFont(QFont("微软雅黑", 9))
        content_layout.addWidget(self.content_display)
        
        # Connect toggle signal
        self.content_group.toggled.connect(self._toggle_content_display)
        
        layout.addWidget(self.content_group)
        
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
    
    def _toggle_content_display(self, checked):
        """Toggle the visibility of content display"""
        self.content_display.setVisible(checked)
        if checked:
            self.content_group.setTitle("学习内容 (点击收缩)")
        else:
            self.content_group.setTitle("学习内容 (点击展开)")
    
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
        
        # Save user answers before evaluation
        self.user_answers_before_evaluation = user_answers
        
        self.status_label.setText("正在评估答案...")
        self.progress_bar.show()
        self.regenerate_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)
        
        if not self.worker_thread.isRunning():
            self.worker.evaluate_answers(self.selected_text, user_answers)
            self.worker_thread.start()
    
    def _on_questions_ready(self, questions: str):
        """Handle generated questions"""
        self.current_questions = questions
        self.practice_editor.setPlainText(questions)
        
    def _on_evaluation_ready(self, evaluation: str):
        """Handle evaluation results"""
        self.evaluation_result = evaluation
        
        # Show evaluation in a new window or replace current content
        self.practice_editor.setPlainText(evaluation)
        
        # Add option to start new practice
        self.regenerate_btn.setText("开始新练习")
        self.submit_btn.setText("保存评估结果")
        
        # Auto-save the evaluation result
        self._save_practice_with_evaluation()
        
    def _save_practice(self):
        """Save practice content"""
        try:
            import os
            import json
            from datetime import datetime
            
            # Create practice directory if it doesn't exist
            practice_dir = "practice_sessions"
            os.makedirs(practice_dir, exist_ok=True)
            
            # Determine status and current answers
            current_content = self.practice_editor.toPlainText()
            status = "in_progress"
            current_answers = ""
            
            if self.evaluation_result:
                status = "evaluated"
                # Use the saved user answers from before evaluation
                current_answers = self.user_answers_before_evaluation or self.current_answers
            elif self.current_questions and current_content != self.current_questions:
                status = "completed"
                current_answers = current_content
            else:
                current_answers = current_content if current_content != self.current_questions else ""
            
            # Save practice data with both user answers and evaluation results
            practice_data = {
                "practice_id": self.practice_id,
                "timestamp": datetime.now().isoformat(),
                "selected_text": self.selected_text,
                "questions": self.current_questions,
                "user_answers": current_answers,  # Always save user's original answers
                "evaluation_result": self.evaluation_result,  # Always save evaluation if exists
                "practice_content": current_content,  # Current display content
                "status": status
            }
            
            filename = os.path.join(practice_dir, f"practice_{self.practice_id}.json")
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(practice_data, f, ensure_ascii=False, indent=2)
            
            self.status_label.setText(f"练习已保存: {filename}")
            
        except Exception as e:
            self.status_label.setText(f"保存失败: {e}")
    
    def _save_practice_with_evaluation(self):
        """Save practice with evaluation results"""
        # Keep the user answers that were submitted for evaluation
        self.current_answers = self.user_answers_before_evaluation
        self._save_practice()
    
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
    
    def _show_history(self):
        """Show practice history dialog"""
        dialog = PracticeHistoryDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_practice = dialog.get_selected_practice()
            if selected_practice:
                self._load_practice(selected_practice)
    
    def _load_practice(self, practice_data):
        """Load a practice from history"""
        self._loading_from_history = True
        
        # Update practice data
        self.practice_id = practice_data.get("practice_id", self._generate_practice_id())
        self.selected_text = practice_data.get("selected_text", "")
        self.current_questions = practice_data.get("questions", "")
        self.current_answers = practice_data.get("user_answers", practice_data.get("answers", ""))  # Support both old and new format
        self.evaluation_result = practice_data.get("evaluation_result", "")
        self.user_answers_before_evaluation = self.current_answers
        
        # Update UI
        self.practice_label.setText(f"练习ID: {self.practice_id}")
        self.content_display.setPlainText(self.selected_text)
        
        # Load appropriate content based on status
        status = practice_data.get("status", "")
        if status == "evaluated" and self.evaluation_result:
            self.practice_editor.setPlainText(self.evaluation_result)
            self.regenerate_btn.setText("开始新练习")
            self.submit_btn.setText("保存评估结果")
        elif self.current_questions:
            # Show questions with any existing answers
            content = self.current_questions
            if self.current_answers:
                content += "\n\n" + self.current_answers
            self.practice_editor.setPlainText(content)
            self.regenerate_btn.setEnabled(True)
            self.submit_btn.setEnabled(True)
        else:
            # Load practice content as fallback
            practice_content = practice_data.get("practice_content", "")
            self.practice_editor.setPlainText(practice_content)
        
        self.status_label.setText(f"已加载练习: {self.practice_id}")
    
    def _start_new_practice(self):
        """Start a new practice session"""
        # Save current practice if it has content
        if self.practice_editor.toPlainText().strip():
            self._save_practice()
        
        # Reset practice state
        self.practice_id = self._generate_practice_id()
        self.practice_label.setText(f"练习ID: {self.practice_id}")
        self.current_questions = ""
        self.current_answers = ""
        self.evaluation_result = ""
        self.user_answers_before_evaluation = ""
        
        # Clear editors
        self.practice_editor.clear()
        
        # Reset buttons
        self.regenerate_btn.setText("重新生成题目")
        self.submit_btn.setText("提交练习")
        
        # Start new practice with selected text
        if self.selected_text.strip():
            self._generate_questions()
    
    def closeEvent(self, event):
        """Handle window close event"""
        # Auto-save before closing if there's content
        if self.practice_editor.toPlainText().strip():
            self._save_practice()
        
        if self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
        super().closeEvent(event)
