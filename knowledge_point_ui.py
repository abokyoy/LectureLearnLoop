"""
知识点管理UI组件
包含学科指定界面、知识点确认界面、错题复习界面等
"""

import sys
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QComboBox,
    QLineEdit, QGroupBox, QCheckBox, QSpinBox, QTextBrowser, QProgressBar,
    QMessageBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject
from knowledge_management import KnowledgeManagementSystem
from datetime import datetime


class KnowledgeExtractionWorker(QObject):
    """知识点提取工作线程"""
    extraction_finished = Signal(dict)
    status_update = Signal(str)
    error_occurred = Signal(str)
    
    def __init__(self, km_system, subject_name, note_content):
        super().__init__()
        self.km_system = km_system
        self.subject_name = subject_name
        self.note_content = note_content
    
    def extract_knowledge_points(self):
        """提取知识点"""
        try:
            self.status_update.emit("正在提取知识点...")
            result = self.km_system.extract_and_process_knowledge_points(
                self.subject_name, self.note_content
            )
            self.extraction_finished.emit(result)
        except Exception as e:
            self.error_occurred.emit(str(e))


class SubjectSelectionDialog(QDialog):
    """学科指定对话框"""
    
    def __init__(self, km_system, parent=None):
        super().__init__(parent)
        self.km_system = km_system
        self.selected_subject = None
        self.setWindowTitle("学科指定")
        self.resize(400, 300)
        self._setup_ui()
        self._load_subjects()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("请指定笔记所属学科")
        title_label.setFont(QFont("微软雅黑", 14, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # 已有学科选择
        existing_group = QGroupBox("选择已有学科")
        existing_layout = QVBoxLayout(existing_group)
        
        self.subject_combo = QComboBox()
        self.subject_combo.setPlaceholderText("请选择学科...")
        existing_layout.addWidget(self.subject_combo)
        
        layout.addWidget(existing_group)
        
        # 新增学科
        new_group = QGroupBox("或新增学科")
        new_layout = QVBoxLayout(new_group)
        
        self.new_subject_input = QLineEdit()
        self.new_subject_input.setPlaceholderText("输入新学科名称...")
        new_layout.addWidget(self.new_subject_input)
        
        layout.addWidget(new_group)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        self.next_button = QPushButton("下一步")
        self.next_button.clicked.connect(self._on_next_clicked)
        
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(self.next_button)
        
        layout.addLayout(button_layout)
    
    def _load_subjects(self):
        """加载已有学科"""
        subjects = self.km_system.get_subjects()
        self.subject_combo.addItems(subjects)
    
    def _on_next_clicked(self):
        """下一步按钮点击"""
        # 检查选择
        selected_subject = self.subject_combo.currentText()
        new_subject = self.new_subject_input.text().strip()
        
        if new_subject:
            # 使用新学科
            self.selected_subject = new_subject
            # 添加到系统
            self.km_system.add_subject(new_subject)
        elif selected_subject:
            # 使用已有学科
            self.selected_subject = selected_subject
        else:
            QMessageBox.warning(self, "提示", "请选择或输入学科名称")
            return
        
        self.accept()
    
    def get_selected_subject(self):
        """获取选择的学科"""
        return self.selected_subject


class KnowledgePointConfirmationDialog(QDialog):
    """知识点确认对话框"""
    
    def __init__(self, extraction_result, km_system, parent=None):
        super().__init__(parent)
        self.extraction_result = extraction_result
        self.km_system = km_system
        self.confirmations = []
        
        self.setWindowTitle("知识点确认")
        self.resize(800, 600)
        self._setup_ui()
        self._load_knowledge_points()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 标题
        subject_name = self.extraction_result["subject_name"]
        title_label = QLabel(f"学科：{subject_name} - 知识点确认")
        title_label.setFont(QFont("微软雅黑", 14, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # 知识点列表
        self.points_widget = QWidget()
        self.points_layout = QVBoxLayout(self.points_widget)
        
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.points_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        self.submit_button = QPushButton("提交")
        self.submit_button.clicked.connect(self._on_submit_clicked)
        
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(self.submit_button)
        
        layout.addLayout(button_layout)
    
    def _load_knowledge_points(self):
        """加载知识点"""
        processed_points = self.extraction_result["processed_points"]
        
        for i, point_info in enumerate(processed_points):
            point_widget = self._create_point_widget(i, point_info)
            self.points_layout.addWidget(point_widget)
    
    def _create_point_widget(self, index, point_info):
        """创建知识点确认组件"""
        extracted_point = point_info["extracted_point"]
        similar_points = point_info["similar_points"]
        match_status = point_info["match_status"]
        
        group = QGroupBox(f"知识点 {index + 1}")
        layout = QVBoxLayout(group)
        
        # 提取的知识点信息
        point_label = QLabel(f"名称：{extracted_point['point_name']}")
        point_label.setFont(QFont("微软雅黑", 10, QFont.Weight.Bold))
        layout.addWidget(point_label)
        
        desc_label = QLabel(f"描述：{extracted_point['core_description']}")
        layout.addWidget(desc_label)
        
        # 匹配状态
        status_label = QLabel(f"匹配状态：{match_status}")
        status_label.setStyleSheet("color: #666; font-style: italic;")
        layout.addWidget(status_label)
        
        # 相似知识点
        if similar_points:
            similar_label = QLabel("相似知识点：")
            layout.addWidget(similar_label)
            
            for similar in similar_points[:3]:  # 最多显示3个
                similar_text = f"• {similar['point_name']} - {similar['core_description']} (相似度: {similar['similarity']}%)"
                similar_item = QLabel(similar_text)
                similar_item.setStyleSheet("margin-left: 20px; color: #444;")
                layout.addWidget(similar_item)
        
        # 操作选择
        action_layout = QHBoxLayout()
        
        if similar_points:
            # 有相似知识点
            merge_checkbox = QCheckBox("合并至已有知识点")
            new_checkbox = QCheckBox("作为新知识点")
            skip_checkbox = QCheckBox("取消添加")
            
            # 互斥选择
            def on_merge_checked():
                if merge_checkbox.isChecked():
                    new_checkbox.setChecked(False)
                    skip_checkbox.setChecked(False)
            
            def on_new_checked():
                if new_checkbox.isChecked():
                    merge_checkbox.setChecked(False)
                    skip_checkbox.setChecked(False)
            
            def on_skip_checked():
                if skip_checkbox.isChecked():
                    merge_checkbox.setChecked(False)
                    new_checkbox.setChecked(False)
            
            merge_checkbox.toggled.connect(on_merge_checked)
            new_checkbox.toggled.connect(on_new_checked)
            skip_checkbox.toggled.connect(on_skip_checked)
            
            # 默认选择合并
            merge_checkbox.setChecked(True)
            
            action_layout.addWidget(merge_checkbox)
            action_layout.addWidget(new_checkbox)
            action_layout.addWidget(skip_checkbox)
            
            # 存储组件引用
            setattr(group, 'merge_checkbox', merge_checkbox)
            setattr(group, 'new_checkbox', new_checkbox)
            setattr(group, 'skip_checkbox', skip_checkbox)
            setattr(group, 'similar_points', similar_points)
        else:
            # 无相似知识点
            new_checkbox = QCheckBox("确认新增")
            skip_checkbox = QCheckBox("取消添加")
            
            def on_new_checked():
                if new_checkbox.isChecked():
                    skip_checkbox.setChecked(False)
            
            def on_skip_checked():
                if skip_checkbox.isChecked():
                    new_checkbox.setChecked(False)
            
            new_checkbox.toggled.connect(on_new_checked)
            skip_checkbox.toggled.connect(on_skip_checked)
            
            # 默认选择新增
            new_checkbox.setChecked(True)
            
            action_layout.addWidget(new_checkbox)
            action_layout.addWidget(skip_checkbox)
            
            # 存储组件引用
            setattr(group, 'new_checkbox', new_checkbox)
            setattr(group, 'skip_checkbox', skip_checkbox)
        
        layout.addLayout(action_layout)
        
        # 存储知识点数据
        setattr(group, 'point_data', extracted_point)
        setattr(group, 'point_index', index)
        
        return group
    
    def _on_submit_clicked(self):
        """提交确认"""
        self.confirmations = []
        
        for i in range(self.points_layout.count()):
            widget = self.points_layout.itemAt(i).widget()
            if isinstance(widget, QGroupBox):
                confirmation = self._get_widget_confirmation(widget)
                if confirmation:
                    self.confirmations.append(confirmation)
        
        if not self.confirmations:
            QMessageBox.warning(self, "提示", "请至少确认一个知识点")
            return
        
        self.accept()
    
    def _get_widget_confirmation(self, widget):
        """获取组件的确认信息"""
        point_data = getattr(widget, 'point_data')
        
        if hasattr(widget, 'merge_checkbox'):
            # 有相似知识点的情况
            if widget.merge_checkbox.isChecked():
                similar_points = getattr(widget, 'similar_points')
                return {
                    "action": "merge",
                    "point_data": point_data,
                    "existing_id": similar_points[0]["id"],  # 选择相似度最高的
                    "subject_name": self.extraction_result["subject_name"]
                }
            elif widget.new_checkbox.isChecked():
                return {
                    "action": "new",
                    "point_data": point_data,
                    "subject_name": self.extraction_result["subject_name"]
                }
        else:
            # 无相似知识点的情况
            if widget.new_checkbox.isChecked():
                return {
                    "action": "new",
                    "point_data": point_data,
                    "subject_name": self.extraction_result["subject_name"]
                }
        
        return None
    
    def get_confirmations(self):
        """获取确认结果"""
        return self.confirmations


class KnowledgePointExtractionPanel(QDialog):
    """知识点提取主面板"""
    
    def __init__(self, selected_text, config, parent=None):
        super().__init__(parent)
        self.selected_text = selected_text
        self.config = config
        self.km_system = KnowledgeManagementSystem(config)
        
        self.setWindowTitle("知识点提取")
        self.resize(600, 400)
        self._setup_ui()
        
        # 启动学科选择流程
        QTimer.singleShot(100, self._start_subject_selection)
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 状态显示
        self.status_label = QLabel("准备开始知识点提取...")
        layout.addWidget(self.status_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # 内容预览
        content_group = QGroupBox("学习内容预览")
        content_layout = QVBoxLayout(content_group)
        
        self.content_preview = QTextEdit()
        self.content_preview.setReadOnly(True)
        self.content_preview.setPlainText(self.selected_text[:500] + "..." if len(self.selected_text) > 500 else self.selected_text)
        self.content_preview.setMaximumHeight(150)
        content_layout.addWidget(self.content_preview)
        
        layout.addWidget(content_group)
        
        # 按钮
        button_layout = QHBoxLayout()
        
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.close)
        
        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
    
    def _start_subject_selection(self):
        """开始学科选择"""
        self.status_label.setText("请选择学科...")
        
        dialog = SubjectSelectionDialog(self.km_system, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            subject_name = dialog.get_selected_subject()
            if subject_name:
                self._start_knowledge_extraction(subject_name)
        else:
            self.close()
    
    def _start_knowledge_extraction(self, subject_name):
        """开始知识点提取"""
        self.status_label.setText(f"正在从学科'{subject_name}'中提取知识点...")
        self.progress_bar.show()
        
        # 创建工作线程
        self.worker_thread = QThread()
        self.worker = KnowledgeExtractionWorker(self.km_system, subject_name, self.selected_text)
        self.worker.moveToThread(self.worker_thread)
        
        # 连接信号
        self.worker.extraction_finished.connect(self._on_extraction_finished)
        self.worker.status_update.connect(self._on_status_update)
        self.worker.error_occurred.connect(self._on_error_occurred)
        
        self.worker_thread.started.connect(self.worker.extract_knowledge_points)
        self.worker_thread.start()
    
    def _on_extraction_finished(self, result):
        """提取完成"""
        self.progress_bar.hide()
        self.status_label.setText("知识点提取完成，请确认...")
        
        # 停止工作线程
        if hasattr(self, 'worker_thread'):
            self.worker_thread.quit()
            self.worker_thread.wait()
        
        # 打开确认对话框
        dialog = KnowledgePointConfirmationDialog(result, self.km_system, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            confirmations = dialog.get_confirmations()
            self._save_knowledge_points(confirmations)
        else:
            self.status_label.setText("已取消知识点提取")
    
    def _save_knowledge_points(self, confirmations):
        """保存知识点"""
        self.status_label.setText("正在保存知识点...")
        self.progress_bar.show()
        
        try:
            saved_ids = self.km_system.confirm_knowledge_points(confirmations)
            self.progress_bar.hide()
            self.status_label.setText(f"成功保存 {len(saved_ids)} 个知识点")
            
            QMessageBox.information(self, "成功", f"已成功保存 {len(saved_ids)} 个知识点到知识库")
            
        except Exception as e:
            self.progress_bar.hide()
            self.status_label.setText(f"保存失败: {e}")
            QMessageBox.critical(self, "错误", f"保存知识点失败: {e}")
    
    def _on_status_update(self, status):
        """状态更新"""
        self.status_label.setText(status)
    
    def _on_error_occurred(self, error):
        """错误处理"""
        self.progress_bar.hide()
        self.status_label.setText(f"提取失败: {error}")
        
        if hasattr(self, 'worker_thread'):
            self.worker_thread.quit()
            self.worker_thread.wait()
        
        QMessageBox.critical(self, "错误", f"知识点提取失败: {error}")
    
    def closeEvent(self, event):
        """关闭事件"""
        if hasattr(self, 'worker_thread') and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
        super().closeEvent(event)
