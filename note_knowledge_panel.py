"""
笔记知识管理面板 - 专门用于笔记中的知识点提取和管理
简化版本，专注于知识提取和合并功能
"""

import sys
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QComboBox, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QGroupBox, QSplitter, QCheckBox, QLineEdit, QTextBrowser, QWidget
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, QThread, Signal, QObject, QSize
import json
import requests
from knowledge_management import KnowledgeManagementSystem


class KnowledgeExtractionWorker(QObject):
    """知识点提取工作线程"""
    extractionReady = Signal(dict)  # 提取结果
    status = Signal(str)
    finished = Signal()
    
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.note_content = ""
        self.subject_name = ""
    
    def extract_knowledge_points(self, note_content: str, subject_name: str):
        """提取知识点"""
        self.note_content = note_content
        self.subject_name = subject_name
        self._start_extraction()
    
    def _start_extraction(self):
        """开始提取知识点"""
        try:
            print(f"[工作线程] 开始提取知识点，学科: {self.subject_name}")
            self.status.emit("正在分析笔记内容...")
            
            # 使用知识管理系统进行提取
            km_system = KnowledgeManagementSystem(self.config)
            result = km_system.extract_knowledge_points(self.subject_name, self.note_content)
            
            print(f"[工作线程] 知识管理系统返回结果: {result}")
            
            # 检查结果结构
            if result and isinstance(result, dict):
                if result.get("success", False):
                    print(f"[工作线程] 提取成功，准备发送结果到UI")
                    self.extractionReady.emit(result)
                else:
                    error_msg = result.get("error", "提取结果异常")
                    print(f"[工作线程] 提取失败: {error_msg}")
                    self.extractionReady.emit({"success": False, "error": error_msg})
            else:
                print(f"[工作线程] 返回结果格式异常: {result}")
                self.extractionReady.emit({"success": False, "error": "提取结果为空或格式异常"})
            
        except Exception as e:
            import traceback
            error_details = f"提取失败: {str(e)}\n详细错误: {traceback.format_exc()}"
            print(f"[工作线程] {error_details}")
            self.status.emit(f"提取失败: {e}")
            # 发送错误结果
            error_result = {"success": False, "error": str(e)}
            self.extractionReady.emit(error_result)
        finally:
            print(f"[工作线程] 提取过程完成，发送finished信号")
            self.finished.emit()


class NoteKnowledgePanel(QDialog):
    """笔记知识管理面板"""
    
    def __init__(self, note_content: str, config: dict, parent=None):
        super().__init__(parent)
        self.note_content = note_content
        self.config = config
        self.km_system = KnowledgeManagementSystem(config)
        self.extraction_result = None
        self.current_subject = None
        
        self.setWindowTitle("知识点提取与管理")
        self.setModal(True)
        self.resize(800, 600)
        
        self._setup_ui()
        self._load_subjects()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        
        # 标题
        title_label = QLabel("学科核心概念提取与管理")
        title_label.setFont(QFont("微软雅黑", 14, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # 学科选择区域
        subject_group = QGroupBox("1. 选择学科")
        subject_layout = QVBoxLayout(subject_group)
        
        subject_row = QHBoxLayout()
        subject_row.addWidget(QLabel("学科:"))
        
        self.subject_combo = QComboBox()
        self.subject_combo.setEditable(True)
        self.subject_combo.setToolTip("选择已有学科或输入新学科名称")
        subject_row.addWidget(self.subject_combo)
        # 动态刷新：切换学科时刷新右侧已有知识点
        try:
            self.subject_combo.currentTextChanged.connect(self._on_subject_changed)
        except Exception:
            pass
        
        self.btn_add_subject = QPushButton("添加学科")
        self.btn_add_subject.clicked.connect(self._add_subject)
        subject_row.addWidget(self.btn_add_subject)
        
        subject_layout.addLayout(subject_row)
        layout.addWidget(subject_group)
        
        # 核心概念提取区域
        extract_group = QGroupBox("2. 核心概念提取")
        extract_layout = QVBoxLayout(extract_group)
        
        extract_row = QHBoxLayout()
        self.btn_extract = QPushButton("提取核心概念")
        self.btn_extract.clicked.connect(self._extract_knowledge_points)
        extract_row.addWidget(self.btn_extract)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 无限进度条
        self.progress_bar.hide()
        extract_row.addWidget(self.progress_bar)
        
        extract_layout.addLayout(extract_row)
        
        self.status_label = QLabel("请先选择学科，然后点击提取核心概念")
        extract_layout.addWidget(self.status_label)
        
        layout.addWidget(extract_group)
        
        # 核心概念确认区域
        confirm_group = QGroupBox("3. 核心概念确认与合并")
        confirm_layout = QVBoxLayout(confirm_group)
        
        # 分割器：左侧提取的概念，右侧“核心概念的操作”
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧：提取的核心概念
        left_widget = QGroupBox("提取的核心概念")
        left_layout = QVBoxLayout(left_widget)
        
        self.extracted_list = QListWidget()
        self.extracted_list.itemSelectionChanged.connect(self._on_extracted_selection_changed)
        left_layout.addWidget(self.extracted_list)
        
        splitter.addWidget(left_widget)
        
        # 右侧：核心概念的操作（推荐相似知识点 + 合并/新增）
        right_ops = QGroupBox("核心概念的操作")
        right_ops_layout = QVBoxLayout(right_ops)
        tips = QLabel("选择左侧核心概念后，将在此显示与之最相似的3-4个已有知识点")
        tips.setStyleSheet("color:#555;")
        right_ops_layout.addWidget(tips)
        # 推荐列表
        self.recommend_list = QListWidget()
        self.recommend_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        right_ops_layout.addWidget(self.recommend_list)
        # 操作按钮
        op_row = QHBoxLayout()
        self.btn_merge = QPushButton("合并到上方选中推荐")
        self.btn_merge.setEnabled(False)
        self.btn_merge.clicked.connect(self._merge_to_recommended)
        self.btn_add_new = QPushButton("新增知识点（用该核心概念）")
        self.btn_add_new.setEnabled(False)
        self.btn_add_new.clicked.connect(self._add_as_new_knowledge_point)
        op_row.addWidget(self.btn_merge)
        op_row.addStretch()
        op_row.addWidget(self.btn_add_new)
        right_ops_layout.addLayout(op_row)

        # 推荐列表选择变化，控制合并按钮可用
        self.recommend_list.itemSelectionChanged.connect(
            lambda: self.btn_merge.setEnabled(len(self.recommend_list.selectedItems()) > 0)
        )

        splitter.addWidget(right_ops)
        confirm_layout.addWidget(splitter)
        
        # 使用垂直分割器，控制“已有知识点”高度为“确认与合并”的一半左右
        v_split = QSplitter(Qt.Orientation.Vertical)
        v_split.addWidget(confirm_group)
        # 底部：已有知识点（原右侧区域整体下移）
        bottom_existing_group = QGroupBox("已有知识点")
        bottom_existing_layout = QVBoxLayout(bottom_existing_group)
        self.existing_list = QListWidget()
        bottom_existing_layout.addWidget(self.existing_list)
        v_split.addWidget(bottom_existing_group)
        # 设置默认比例：上部两份、下部一份（使下部约为上部一半高）
        try:
            v_split.setSizes([200, 100])
        except Exception:
            pass
        layout.addWidget(v_split)
        
        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        button_layout.addWidget(self.btn_close)
        
        layout.addLayout(button_layout)
        
        # 工作线程
        self.worker = None
        self.worker_thread = None
    
    def _load_subjects(self):
        """加载已有学科"""
        try:
            subjects = self.km_system.get_subjects()
            self.subject_combo.clear()
            self.subject_combo.addItems(subjects)
            
            if subjects:
                self.subject_combo.setCurrentIndex(0)
                self._load_existing_knowledge_points()
        except Exception as e:
            self.status_label.setText(f"加载学科失败: {e}")
    
    def _add_subject(self):
        """添加新学科"""
        subject_name = self.subject_combo.currentText().strip()
        if not subject_name:
            QMessageBox.warning(self, "警告", "请输入学科名称")
            return
        
        try:
            success = self.km_system.add_subject(subject_name)
            if success:
                self.status_label.setText(f"学科 '{subject_name}' 添加成功")
                self._load_subjects()
                self.subject_combo.setCurrentText(subject_name)
            else:
                self.status_label.setText(f"学科 '{subject_name}' 已存在")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"添加学科失败: {e}")
    
    def _extract_knowledge_points(self):
        """提取知识点"""
        subject_name = self.subject_combo.currentText().strip()
        if not subject_name:
            QMessageBox.warning(self, "警告", "请先选择或添加学科")
            return
        
        if not self.note_content.strip():
            QMessageBox.warning(self, "警告", "笔记内容为空")
            return
        
        # 确保学科存在
        self.km_system.add_subject(subject_name)
        self.current_subject = subject_name
        
        # 启动工作线程
        self.worker = KnowledgeExtractionWorker(self.config)
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        
        # 连接信号
        self.worker.extractionReady.connect(self._on_extraction_ready)
        self.worker.status.connect(self._on_status_update)
        self.worker.finished.connect(self._on_worker_finished)
        
        # 启动线程
        self.worker_thread.started.connect(
            lambda: self.worker.extract_knowledge_points(self.note_content, subject_name)
        )
        
        # 更新UI状态
        self.btn_extract.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText("正在提取核心概念...")
        
        self.worker_thread.start()
    
    def _on_extraction_ready(self, result: dict):
        """处理提取结果"""
        print(f"[UI更新] 收到提取结果: {result}")
        self.extraction_result = result
        
        if result.get("success", False):
            processed_points = result.get("processed_points", [])
            print(f"[UI更新] 处理的知识点数量: {len(processed_points)}")
            
            # 显示提取的知识点（自定义小部件：左侧标题蓝色）
            self.extracted_list.clear()
            for i, point_data in enumerate(processed_points):
                print(f"[UI更新] 处理第{i+1}个知识点: {point_data}")
                extracted_point = point_data.get("extracted_point", {})
                # 支持两种数据格式
                point_name = extracted_point.get("point_name") or extracted_point.get("concept_name", "")
                core_description = extracted_point.get("core_description") or extracted_point.get("core_definition", "")
                if point_name or core_description:
                    item = QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, point_data)
                    w = QWidget()
                    vl = QVBoxLayout(w)
                    vl.setContentsMargins(6, 4, 6, 4)
                    title = QLabel(point_name)
                    title.setStyleSheet("color: #1e88e5; font-weight: 600; font-size: 13px;")  # 蓝色
                    desc = QLabel(core_description)
                    desc.setStyleSheet("color: #666; font-size: 12px;")
                    desc.setWordWrap(True)
                    vl.addWidget(title)
                    vl.addWidget(desc)
                    self.extracted_list.addItem(item)
                    self.extracted_list.setItemWidget(item, w)
                    item.setSizeHint(QSize(0, 48))
                else:
                    print(f"[UI更新] 概念数据不完整，跳过: {extracted_point}")
            
            actual_count = self.extracted_list.count()
            self.status_label.setText(f"成功提取 {actual_count} 个核心概念")
            print(f"[UI更新] UI列表中实际显示 {actual_count} 个核心概念")
            
            # 加载该学科的已有知识点
            self._load_existing_knowledge_points()
        else:
            error_msg = result.get("error", "未知错误")
            print(f"[UI更新] 提取失败: {error_msg}")
            self.status_label.setText(f"提取失败: {error_msg}")
    
    def _load_existing_knowledge_points(self):
        """加载已有知识点"""
        subject_name = self.subject_combo.currentText().strip()
        if not subject_name:
            return
        
        try:
            knowledge_points = self.km_system.get_knowledge_points_by_subject(subject_name)
            
            self.existing_list.clear()
            for point in knowledge_points:
                # 使用自定义小部件实现双色展示
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, point)
                # 小部件
                w = QWidget()
                vl = QVBoxLayout(w)
                vl.setContentsMargins(6, 4, 6, 4)
                title = QLabel(point.get('point_name', ''))
                title.setStyleSheet("color: #d97706; font-weight: 600; font-size: 13px;")  # 橙黄色
                desc = QLabel(point.get('core_description', ''))
                desc.setStyleSheet("color: #666; font-size: 12px;")
                desc.setWordWrap(True)
                vl.addWidget(title)
                vl.addWidget(desc)
                self.existing_list.addItem(item)
                self.existing_list.setItemWidget(item, w)
                # 预估高度
                item.setSizeHint(QSize(0, 48))
                
        except Exception as e:
            self.status_label.setText(f"加载已有知识点失败: {e}")

    def _on_subject_changed(self, _text: str):
        """学科切换：刷新右侧已有知识点列表"""
        self.current_subject = self.subject_combo.currentText().strip()
        self._load_existing_knowledge_points()
    
    def _on_extracted_selection_changed(self):
        """提取的知识点选择改变"""
        selected_items = self.extracted_list.selectedItems()
        enable = len(selected_items) > 0
        self.btn_add_new.setEnabled(enable)
        # 刷新推荐列表
        self._refresh_recommendations()
    
    def _on_existing_selection_changed(self):
        """已有知识点选择改变（底部列表，仅展示，不参与操作）"""
        return
    
    def _update_merge_button_state(self):
        # 保留占位，不再依赖底部列表
        pass
    
    def _add_as_new_knowledge_point(self):
        """添加为新知识点"""
        selected_items = self.extracted_list.selectedItems()
        if not selected_items:
            return
        
        try:
            # 仅处理第一个选中项（单选逻辑）
            item = selected_items[0]
            point_data = item.data(Qt.ItemDataRole.UserRole)
            extracted_point = point_data.get("extracted_point", {})
            normalized = {
                "point_name": extracted_point.get("point_name") or extracted_point.get("concept_name", ""),
                "core_description": extracted_point.get("core_description") or extracted_point.get("core_definition", ""),
            }
            confirmations = [{
                "action": "new",
                "point_data": normalized,
                "subject_name": self.current_subject
            }]
            saved_ids = self.km_system.confirm_knowledge_points(confirmations)
            
            if saved_ids:
                self.status_label.setText("成功添加 1 个新知识点")
                # 移除已处理的核心概念
                row = self.extracted_list.row(item)
                self.extracted_list.takeItem(row)
                
                # 刷新已有知识点列表
                self._load_existing_knowledge_points()
                # 清空推荐
                self.recommend_list.clear()
            else:
                self.status_label.setText("添加知识点失败")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"添加知识点失败: {e}")
    
    def _merge_to_recommended(self):
        """合并到右侧选中的推荐知识点"""
        extracted_items = self.extracted_list.selectedItems()
        if not extracted_items:
            return
        # 按你的要求：不做后端合并，仅移除左侧被选中的概念，并清空推荐
        item = extracted_items[0]
        row = self.extracted_list.row(item)
        self.extracted_list.takeItem(row)
        self.recommend_list.clear()
        self.btn_merge.setEnabled(False)
        self.btn_add_new.setEnabled(False)
        self.status_label.setText("已从左侧列表移除该核心概念")

    def _refresh_recommendations(self):
        """根据左侧选中概念，计算推荐的相似知识点（前3-4）"""
        self.recommend_list.clear()
        items = self.extracted_list.selectedItems()
        if not items:
            self.btn_merge.setEnabled(False)
            self.btn_add_new.setEnabled(False)
            return
        self.btn_add_new.setEnabled(True)
        try:
            point_data = items[0].data(Qt.ItemDataRole.UserRole)
            extracted_point = point_data.get("extracted_point", {})
            query = extracted_point.get("point_name") or extracted_point.get("concept_name", "")
            if not query:
                query = extracted_point.get("core_description") or extracted_point.get("core_definition", "")
            kps = self.km_system.get_knowledge_points_by_subject(self.subject_combo.currentText().strip())
            # 计算相似度
            from similarity_matcher import rank_matches
            ranked = rank_matches(query, kps, cfg=getattr(self.km_system, 'config', {}), top_k=4, min_score=0.0)
            # 渲染
            for r in ranked:
                kp = next((p for p in kps if p.get('id') == r.get('id')), None)
                if not kp:
                    continue
                name = kp.get('point_name','')
                desc = kp.get('core_description','')
                score = float(r.get('score') or 0.0)
                # 自定义小部件：右侧标题默认橙色，若score>0.4则为蓝色
                li = QListWidgetItem()
                li.setData(Qt.ItemDataRole.UserRole, {"id": kp.get('id'), "score": score})
                w = QWidget()
                vl = QVBoxLayout(w)
                vl.setContentsMargins(6, 4, 6, 4)
                title = QLabel(f"{name}  |  相似度: {score:.2f}")
                if score > 0.4:
                    title.setStyleSheet("color: #1e88e5; font-weight: 600; font-size: 13px;")  # 蓝色（高相似）
                else:
                    title.setStyleSheet("color: #d97706; font-weight: 600; font-size: 13px;")  # 橙黄色
                desc_lbl = QLabel(desc)
                desc_lbl.setStyleSheet("color: #666; font-size: 12px;")
                desc_lbl.setWordWrap(True)
                vl.addWidget(title)
                vl.addWidget(desc_lbl)
                self.recommend_list.addItem(li)
                self.recommend_list.setItemWidget(li, w)
                li.setSizeHint(QSize(0, 48))
            # 控制合并按钮
            self.btn_merge.setEnabled(self.recommend_list.count() > 0)
        except Exception as e:
            self.status_label.setText(f"推荐计算失败: {e}")
    
    def _on_status_update(self, status: str):
        """状态更新"""
        self.status_label.setText(status)
    
    def _on_worker_finished(self):
        """工作线程完成"""
        self.progress_bar.hide()
        self.btn_extract.setEnabled(True)
        
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
    
    def closeEvent(self, event):
        """关闭事件"""
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait()
        event.accept()


def open_note_knowledge_panel(note_content: str, config: dict, parent=None):
    """打开笔记知识管理面板的便捷函数"""
    panel = NoteKnowledgePanel(note_content, config, parent)
    return panel.exec()
