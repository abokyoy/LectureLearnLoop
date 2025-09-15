"""
错题复习和新题生成UI组件
"""

import sys
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QComboBox,
    QLineEdit, QGroupBox, QCheckBox, QSpinBox, QTextBrowser, QProgressBar,
    QMessageBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject
from knowledge_management import KnowledgeManagementSystem


class ErrorQuestionReviewDialog(QDialog):
    """错题复习对话框"""
    
    def __init__(self, km_system, parent=None):
        super().__init__(parent)
        self.km_system = km_system
        self.current_subject = None
        self.current_knowledge_point = None
        self.error_questions = []
        
        self.setWindowTitle("错题复习")
        self.resize(900, 700)
        self._setup_ui()
        self._load_subjects()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("错题复习与针对性练习")
        title_label.setFont(QFont("微软雅黑", 14, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # 选择区域
        selection_group = QGroupBox("选择学科和知识点")
        selection_layout = QVBoxLayout(selection_group)
        
        # 学科选择
        subject_layout = QHBoxLayout()
        subject_layout.addWidget(QLabel("学科:"))
        
        self.subject_combo = QComboBox()
        self.subject_combo.setPlaceholderText("请选择学科...")
        self.subject_combo.currentTextChanged.connect(self._on_subject_changed)
        subject_layout.addWidget(self.subject_combo)
        
        selection_layout.addLayout(subject_layout)
        
        # 知识点选择
        point_layout = QHBoxLayout()
        point_layout.addWidget(QLabel("知识点:"))
        
        self.point_combo = QComboBox()
        self.point_combo.setPlaceholderText("请先选择学科...")
        self.point_combo.currentTextChanged.connect(self._on_knowledge_point_changed)
        point_layout.addWidget(self.point_combo)
        
        selection_layout.addLayout(point_layout)
        
        # 查看错题按钮
        self.view_errors_button = QPushButton("查看该知识点错题")
        self.view_errors_button.clicked.connect(self._load_error_questions)
        self.view_errors_button.setEnabled(False)
        selection_layout.addWidget(self.view_errors_button)
        
        layout.addWidget(selection_group)
        
        # 主要内容区域
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 错题列表
        error_group = QGroupBox("错题列表")
        error_layout = QVBoxLayout(error_group)
        
        self.error_table = QTableWidget()
        self.error_table.setColumnCount(4)
        self.error_table.setHorizontalHeaderLabels(["题目内容", "错误答案", "练习时间", "复习状态"])
        self.error_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.error_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.itemSelectionChanged.connect(self._on_error_selected)
        error_layout.addWidget(self.error_table)
        
        # 错题操作按钮
        error_button_layout = QHBoxLayout()
        
        self.mark_reviewed_button = QPushButton("标记为已复习")
        self.mark_reviewed_button.clicked.connect(self._mark_as_reviewed)
        self.mark_reviewed_button.setEnabled(False)
        error_button_layout.addWidget(self.mark_reviewed_button)
        
        error_button_layout.addStretch()
        error_layout.addLayout(error_button_layout)
        
        main_splitter.addWidget(error_group)
        
        # 新题生成区域
        generation_group = QGroupBox("针对性新题生成")
        generation_layout = QVBoxLayout(generation_group)
        
        # 生成设置
        gen_settings_layout = QHBoxLayout()
        gen_settings_layout.addWidget(QLabel("生成题数:"))
        
        self.question_count_spin = QSpinBox()
        self.question_count_spin.setRange(1, 5)
        self.question_count_spin.setValue(2)
        gen_settings_layout.addWidget(self.question_count_spin)
        
        self.generate_button = QPushButton("生成针对性新题")
        self.generate_button.clicked.connect(self._generate_new_questions)
        self.generate_button.setEnabled(False)
        gen_settings_layout.addWidget(self.generate_button)
        
        gen_settings_layout.addStretch()
        generation_layout.addLayout(gen_settings_layout)
        
        # 新题显示
        self.new_questions_browser = QTextBrowser()
        self.new_questions_browser.setPlaceholderText("生成的新题将在这里显示...")
        generation_layout.addWidget(self.new_questions_browser)
        
        main_splitter.addWidget(generation_group)
        
        # 设置分割比例
        main_splitter.setSizes([400, 500])
        layout.addWidget(main_splitter)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        
        layout.addLayout(button_layout)
    
    def _load_subjects(self):
        """加载学科列表"""
        subjects = self.km_system.get_subjects()
        self.subject_combo.addItems(subjects)
    
    def _on_subject_changed(self, subject_name):
        """学科选择改变"""
        if not subject_name:
            return
        
        self.current_subject = subject_name
        self.point_combo.clear()
        self.point_combo.setPlaceholderText("正在加载知识点...")
        
        # 加载知识点
        try:
            knowledge_points = self.km_system.get_knowledge_points_by_subject(subject_name)
            
            self.point_combo.setPlaceholderText("请选择知识点...")
            for point in knowledge_points:
                self.point_combo.addItem(f"{point['point_name']} - {point['core_description']}", point['id'])
        
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载知识点失败: {e}")
            self.point_combo.setPlaceholderText("加载失败")
    
    def _on_knowledge_point_changed(self, point_text):
        """知识点选择改变"""
        if not point_text or not self.point_combo.currentData():
            self.view_errors_button.setEnabled(False)
            self.generate_button.setEnabled(False)
            return
        
        self.current_knowledge_point = self.point_combo.currentData()
        self.view_errors_button.setEnabled(True)
        self.generate_button.setEnabled(True)
    
    def _load_error_questions(self):
        """加载错题"""
        if not self.current_subject or not self.current_knowledge_point:
            return
        
        try:
            self.error_questions = self.km_system.get_error_questions(
                self.current_subject, self.current_knowledge_point
            )
            
            # 更新表格
            self.error_table.setRowCount(len(self.error_questions))
            
            for row, error in enumerate(self.error_questions):
                # 题目内容
                question_item = QTableWidgetItem(error['question_content'][:100] + "..." if len(error['question_content']) > 100 else error['question_content'])
                question_item.setToolTip(error['question_content'])
                self.error_table.setItem(row, 0, question_item)
                
                # 错误答案
                answer_item = QTableWidgetItem(error['user_answer'][:50] + "..." if len(error['user_answer']) > 50 else error['user_answer'])
                answer_item.setToolTip(error['user_answer'])
                self.error_table.setItem(row, 1, answer_item)
                
                # 练习时间
                time_item = QTableWidgetItem(error['practice_time'][:16])  # 只显示日期和时间
                self.error_table.setItem(row, 2, time_item)
                
                # 复习状态
                status_text = "已复习" if error['review_status'] else "未复习"
                status_item = QTableWidgetItem(status_text)
                if error['review_status']:
                    status_item.setBackground(Qt.GlobalColor.lightGray)
                self.error_table.setItem(row, 3, status_item)
            
            if not self.error_questions:
                QMessageBox.information(self, "提示", "该知识点暂无错题记录")
        
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载错题失败: {e}")
    
    def _on_error_selected(self):
        """错题选择改变"""
        current_row = self.error_table.currentRow()
        if current_row >= 0 and current_row < len(self.error_questions):
            error = self.error_questions[current_row]
            self.mark_reviewed_button.setEnabled(error['review_status'] == 0)
        else:
            self.mark_reviewed_button.setEnabled(False)
    
    def _mark_as_reviewed(self):
        """标记为已复习"""
        current_row = self.error_table.currentRow()
        if current_row < 0 or current_row >= len(self.error_questions):
            return
        
        error = self.error_questions[current_row]
        
        try:
            success = self.km_system.mark_error_reviewed(error['id'])
            if success:
                # 更新本地数据
                self.error_questions[current_row]['review_status'] = 1
                
                # 更新表格显示
                status_item = QTableWidgetItem("已复习")
                status_item.setBackground(Qt.GlobalColor.lightGray)
                self.error_table.setItem(current_row, 3, status_item)
                
                self.mark_reviewed_button.setEnabled(False)
                QMessageBox.information(self, "成功", "已标记为已复习")
            else:
                QMessageBox.warning(self, "失败", "标记失败")
        
        except Exception as e:
            QMessageBox.warning(self, "错误", f"标记失败: {e}")
    
    def _generate_new_questions(self):
        """生成新题"""
        if not self.current_subject or not self.current_knowledge_point:
            return
        
        question_count = self.question_count_spin.value()
        
        self.generate_button.setEnabled(False)
        self.generate_button.setText("正在生成...")
        
        try:
            # 读取最新配置并下发到 KMS，确保使用用户当前选择的 LLM 提供商
            try:
                import json
                with open('app_config.json', 'r', encoding='utf-8') as f:
                    latest = json.load(f)
                if hasattr(self.km_system, 'update_config'):
                    self.km_system.update_config(latest)
                print(f"[配置][针对性新题] llm_provider={latest.get('llm_provider')} fallback={latest.get('enable_llm_fallback')}")
            except Exception as cfg_err:
                print(f"[配置][针对性新题] 加载最新配置失败，使用现有配置: {cfg_err}")

            new_questions = self.km_system.generate_new_questions(
                self.current_subject, self.current_knowledge_point, question_count
            )
            
            if new_questions:
                # 格式化显示新题
                formatted_questions = self._format_questions(new_questions)
                self.new_questions_browser.setHtml(formatted_questions)
            else:
                self.new_questions_browser.setPlainText("生成失败或该知识点暂无错题记录")
        
        except Exception as e:
            self.new_questions_browser.setPlainText(f"生成失败: {e}")
        
        finally:
            self.generate_button.setEnabled(True)
            self.generate_button.setText("生成针对性新题")
    
    def _format_questions(self, questions):
        """格式化题目显示"""
        html_parts = []
        html_parts.append("<style>")
        html_parts.append("body { font-family: '微软雅黑', sans-serif; line-height: 1.6; }")
        html_parts.append("h3 { color: #2c3e50; margin-top: 20px; }")
        html_parts.append(".question { background: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 5px; }")
        html_parts.append(".options { margin: 10px 0; }")
        html_parts.append(".option { margin: 5px 0; }")
        html_parts.append(".answer { color: #27ae60; font-weight: bold; }")
        html_parts.append(".explanation { background: #e8f5e8; padding: 10px; margin: 10px 0; border-radius: 3px; }")
        html_parts.append("</style>")
        
        for i, question in enumerate(questions, 1):
            html_parts.append(f"<div class='question'>")
            html_parts.append(f"<h3>题目 {i}</h3>")
            html_parts.append(f"<p><strong>题干：</strong>{question.get('question', '')}</p>")
            
            if 'options' in question:
                html_parts.append("<div class='options'><strong>选项：</strong>")
                for key, value in question['options'].items():
                    html_parts.append(f"<div class='option'>{key}. {value}</div>")
                html_parts.append("</div>")
            
            html_parts.append(f"<p class='answer'><strong>正确答案：</strong>{question.get('correct_answer', '')}</p>")
            
            if 'explanation' in question:
                html_parts.append(f"<div class='explanation'><strong>解析：</strong>{question['explanation']}</div>")
            
            html_parts.append("</div>")
        
        return "".join(html_parts)


class QuestionGenerationWorker(QObject):
    """新题生成工作线程"""
    generation_finished = Signal(list)
    status_update = Signal(str)
    error_occurred = Signal(str)
    
    def __init__(self, km_system, subject_name, knowledge_point_id, count):
        super().__init__()
        self.km_system = km_system
        self.subject_name = subject_name
        self.knowledge_point_id = knowledge_point_id
        self.count = count
    
    def generate_questions(self):
        """生成题目"""
        try:
            self.status_update.emit("正在生成针对性新题...")
            questions = self.km_system.generate_new_questions(
                self.subject_name, self.knowledge_point_id, self.count
            )
            self.generation_finished.emit(questions)
        except Exception as e:
            self.error_occurred.emit(str(e))
