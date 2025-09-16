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
    QScrollArea, QAbstractItemView, QSizePolicy
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject, QPoint
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QDateTimeAxis, QValueAxis
from PySide6.QtCore import QDateTime
from knowledge_management import KnowledgeManagementSystem


class ErrorQuestionReviewDialog(QDialog):
    """错题复习对话框"""
    
    def __init__(self, km_system, parent=None):
        super().__init__(parent)
        self.km_system = km_system
        self.current_subject = None
        self.current_knowledge_point = None
        self.error_questions = []
        self._time_sort_asc = True
        self._prof_sort_asc = True
        
        self.setWindowTitle("错题复习")
        self.resize(900, 700)
        self._setup_ui()
        self._load_subjects()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 标题（缩小占用）
        title_label = QLabel("错题复习与针对性练习")
        title_label.setFont(QFont("微软雅黑", 11, QFont.Weight.DemiBold))
        title_label.setStyleSheet("padding: 2px 6px; color: #333;")
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
        
        # 取消“查看错题”按钮，改为自动刷新
        
        layout.addWidget(selection_group)
        
        # 主要内容区域：直接使用错题列表占据主体
        error_group = QGroupBox("错题列表")
        error_layout = QVBoxLayout(error_group)
        
        self.error_table = QTableWidget()
        self.error_table.setColumnCount(4)
        self.error_table.setHorizontalHeaderLabels(["题目内容", "答案（用户/正确）", "练习时间", "熟练度"])
        self.error_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.error_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        # 禁止编辑，行选择
        self.error_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.error_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.error_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.error_table.verticalHeader().setVisible(False)
        self.error_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.error_table.itemSelectionChanged.connect(self._on_error_selected)
        self.error_table.cellDoubleClicked.connect(self._open_detail_for_row)
        # 双击表头排序
        self.error_table.horizontalHeader().sectionDoubleClicked.connect(self._on_header_double_clicked)
        error_layout.addWidget(self.error_table)

        layout.addWidget(error_group)
        
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
        # 默认选中最近一次配置的学科
        try:
            import json
            with open('app_config.json', 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            last_subject = cfg.get('last_selected_subject')
            if last_subject and last_subject in subjects:
                idx = self.subject_combo.findText(last_subject)
                if idx >= 0:
                    self.subject_combo.setCurrentIndex(idx)
        except Exception:
            pass
    
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
            counts_map = {}
            try:
                counts_map = self.km_system.get_error_counts_map(subject_name)
            except Exception:
                counts_map = {}
            self.point_combo.setPlaceholderText("请选择知识点...")
            for point in knowledge_points:
                cnt = counts_map.get(point['id'], 0)
                self.point_combo.addItem(f"{point['point_name']} ({cnt}题)", point['id'])

            # 写回最近使用的学科
            try:
                import json
                with open('app_config.json', 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
            cfg['last_selected_subject'] = subject_name
            try:
                with open('app_config.json', 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载知识点失败: {e}")
            self.point_combo.setPlaceholderText("加载失败")
    
    def _on_knowledge_point_changed(self, point_text):
        """知识点选择改变"""
        if not point_text or not self.point_combo.currentData():
            return
        self.current_knowledge_point = self.point_combo.currentData()
        # 自动刷新错题列表
        self._load_error_questions()
    
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
                # 题目内容（尽量显示全，tooltip 原文）
                q_text = error.get('question_content', '')
                question_item = QTableWidgetItem(q_text)
                question_item.setToolTip(q_text)
                self.error_table.setItem(row, 0, question_item)

                # 答案（用户/正确）
                user_ans = error.get('user_answer', '') or '-'
                corr_ans = error.get('correct_answer', None)
                corr_ans = corr_ans if corr_ans else '-'
                ans_text = f"用户: {user_ans} | 正确: {corr_ans}"
                answer_item = QTableWidgetItem(ans_text)
                self.error_table.setItem(row, 1, answer_item)

                # 练习时间
                time_item = QTableWidgetItem(str(error.get('practice_time', ''))[:19])
                self.error_table.setItem(row, 2, time_item)

                # 熟练度
                prof = int(error.get('current_proficiency', 20) or 20)
                prof_item = QTableWidgetItem(str(prof))
                prof_item.setData(Qt.ItemDataRole.UserRole, prof)
                self.error_table.setItem(row, 3, prof_item)

            if not self.error_questions:
                QMessageBox.information(self, "提示", "该知识点暂无错题记录")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"加载错题失败: {e}")
    
    def _on_error_selected(self):
        """错题选择改变"""
        # 保留占位，当前无额外操作
        return
    
    def _on_header_double_clicked(self, section: int):
        """表头双击排序：时间、熟练度"""
        if section == 2:
            # 时间排序
            self.error_table.sortItems(2, Qt.SortOrder.AscendingOrder if self._time_sort_asc else Qt.SortOrder.DescendingOrder)
            self._time_sort_asc = not self._time_sort_asc
        elif section == 3:
            # 熟练度排序（根据UserRole中的数值）
            # 将所有单元格的显示文本替换为带前导零的，以便字符串排序；更稳妥方式是自定义排序，但这里简化处理
            for r in range(self.error_table.rowCount()):
                item = self.error_table.item(r, 3)
                if item:
                    val = int(item.data(Qt.ItemDataRole.UserRole) or 0)
                    item.setText(f"{val:03d}")
            self.error_table.sortItems(3, Qt.SortOrder.AscendingOrder if self._prof_sort_asc else Qt.SortOrder.DescendingOrder)
            # 恢复显示为正常数字
            for r in range(self.error_table.rowCount()):
                item = self.error_table.item(r, 3)
                if item:
                    val = int(item.text())
                    item.setText(str(val))
            self._prof_sort_asc = not self._prof_sort_asc

    def _open_detail_for_row(self, row: int, col: int):
        if row < 0 or row >= len(self.error_questions):
            return
        error = self.error_questions[row]
        dlg = ErrorQuestionDetailDialog(self.km_system, self.current_subject, self.current_knowledge_point, error, self)
        try:
            dlg.dataChanged.connect(lambda _:
                self._load_error_questions()
            )
        except Exception:
            pass
        dlg.exec()
    
    # 生成新题逻辑迁移到详情面板
    
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


class ErrorQuestionDetailDialog(QDialog):
    """错题复习详情面板"""
    dataChanged = Signal(dict)  # {'action': 'update'|'delete', 'id': int}
    def __init__(self, km_system, subject_name: str, knowledge_point_id: int, error: dict, parent=None):
        super().__init__(parent)
        self.km_system = km_system
        self.subject_name = subject_name
        self.knowledge_point_id = knowledge_point_id
        self.error = error
        self._slider_adjusted = False
        self._history = []
        self._changed = False
        self.setWindowTitle("错题复习")
        self.resize(900, 700)
        self._setup_ui()
        self._load_history()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 顶部原始信息
        info_group = QGroupBox("题目信息")
        info_layout = QVBoxLayout(info_group)
        # 可编辑题干
        self._original_question_text = self.error.get('question_content', '') or ''
        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("题干："))
        info_layout.addLayout(qrow)
        from PySide6.QtWidgets import QTextEdit
        self.question_edit = QTextEdit()
        self.question_edit.setPlainText(self._original_question_text)
        self.question_edit.setReadOnly(True)
        self.question_edit.setMinimumHeight(80)
        info_layout.addWidget(self.question_edit)

        

        # 操作按钮（修改/删除）
        op_row = QHBoxLayout()
        self.btn_edit = QPushButton("修改")
        self.btn_edit.clicked.connect(self._on_edit_or_save)
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        op_row.addStretch()
        op_row.addWidget(self.btn_edit)
        op_row.addWidget(self.btn_delete)
        info_layout.addLayout(op_row)
        layout.addWidget(info_group)

        # 题目归属与类型
        kp_group = QGroupBox("题目归属与类型")
        kp_layout = QVBoxLayout(kp_group)
        # 所属知识点
        row_kp = QHBoxLayout()
        row_kp.addWidget(QLabel("所属知识点："))
        self.kp_combo2 = QComboBox()
        try:
            points = self.km_system.get_knowledge_points_by_subject(self.subject_name)
        except Exception:
            points = []
        self._kp_id_to_index = {}
        for p in points:
            idx = self.kp_combo2.count()
            self.kp_combo2.addItem(p.get('point_name',''), p.get('id'))
            self._kp_id_to_index[p.get('id')] = idx
        # 设置当前选中
        try:
            cur_idx = self._kp_id_to_index.get(int(self.knowledge_point_id))
            if cur_idx is not None:
                self.kp_combo2.setCurrentIndex(cur_idx)
        except Exception:
            pass
        row_kp.addWidget(self.kp_combo2)
        self.btn_save_kp = QPushButton("保存归属更改")
        self.btn_save_kp.clicked.connect(self._on_save_kp)
        row_kp.addWidget(self.btn_save_kp)
        row_kp.addStretch()
        kp_layout.addLayout(row_kp)

        # 类型切换（当前为错题，支持转为收藏）
        row_type = QHBoxLayout()
        row_type.addWidget(QLabel("题目类型："))
        self.type_combo = QComboBox()
        self.type_combo.addItem("错题", "error")
        self.type_combo.addItem("收藏", "favorite")
        # 详情面板当前仅针对错题打开，默认选择错题
        self.type_combo.setCurrentIndex(0)
        row_type.addWidget(self.type_combo)
        self.btn_apply_type = QPushButton("执行转换")
        self.btn_apply_type.setToolTip("将错题转换为收藏；（从收藏切回错题暂不支持）")
        self.btn_apply_type.clicked.connect(self._on_apply_type_change)
        row_type.addWidget(self.btn_apply_type)
        row_type.addStretch()
        kp_layout.addLayout(row_type)

        layout.addWidget(kp_group)

        # 熟练度滑杆
        prof_group = QGroupBox("熟练度调整（0-100，默认20；不调整则+1）")
        prof_layout = QHBoxLayout(prof_group)
        self.prof_slider = QSpinBox()  # 使用SpinBox更直观存取精确值
        self.prof_slider.setRange(0, 100)
        self.prof_slider.setValue(int(self.error.get('current_proficiency', 20) or 20))
        self.prof_slider.valueChanged.connect(self._on_slider_changed)
        prof_layout.addWidget(QLabel("熟练度："))
        prof_layout.addWidget(self.prof_slider)
        prof_layout.addStretch()
        self.save_prof_button = QPushButton("记录本次熟练度")
        self.save_prof_button.clicked.connect(self._save_proficiency)
        prof_layout.addWidget(self.save_prof_button)
        layout.addWidget(prof_group)

         # 针对性新题生成
        gen_group = QGroupBox("针对性新题生成")
        gen_layout = QVBoxLayout(gen_group)
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("生成题数:"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 10)
        self.count_spin.setValue(2)
        control_layout.addWidget(self.count_spin)
        self.gen_btn = QPushButton("生成类似题目")
        self.gen_btn.clicked.connect(self._generate_similar_questions)
        control_layout.addStretch()
        control_layout.addWidget(self.gen_btn)
        gen_layout.addLayout(control_layout)
        
        layout.addWidget(gen_group)

        # 曲线图
        chart_group = QGroupBox("熟练度随时间变化曲线")
        chart_v = QVBoxLayout(chart_group)
        self.chart = QChart()
        self.chart.setTitle("")
        self.series = QLineSeries()
        self.chart.addSeries(self.series)
        self.axis_x = QDateTimeAxis()
        self.axis_x.setFormat("MM-dd HH:mm")
        self.axis_x.setTitleText("时间")
        self.axis_y = QValueAxis()
        self.axis_y.setRange(0, 100)
        self.axis_y.setTitleText("熟练度")
        self.chart.addAxis(self.axis_x, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignmentFlag.AlignLeft)
        self.series.attachAxis(self.axis_x)
        self.series.attachAxis(self.axis_y)
        self.chart_view = QChartView(self.chart)
        chart_v.addWidget(self.chart_view)
        layout.addWidget(chart_group)

       

        # 关闭按钮
        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

    def _on_slider_changed(self, _):
        self._slider_adjusted = True

    def _on_edit_or_save(self):
        """切换编辑/保存题干"""
        try:
            if self.question_edit.isReadOnly():
                # 进入编辑模式
                self.question_edit.setReadOnly(False)
                self.btn_edit.setText("保存")
                return
            # 保存模式
            new_text = (self.question_edit.toPlainText() or '').strip()
            if not new_text:
                QMessageBox.warning(self, "提示", "题干不能为空。")
                return
            ok = self.km_system.update_error_question_content(int(self.error.get('id')), new_text)
            if ok:
                self._original_question_text = new_text
                self.error['question_content'] = new_text
                self.question_edit.setReadOnly(True)
                self.btn_edit.setText("修改")
                QMessageBox.information(self, "成功", "题干已更新。")
                self._changed = True
                try:
                    self.dataChanged.emit({'action': 'update', 'id': int(self.error.get('id'))})
                except Exception:
                    pass
            else:
                QMessageBox.warning(self, "错误", "更新失败，请稍后再试。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"更新异常：{e}")

    def _on_delete(self):
        """删除当前错题（二次确认）"""
        try:
            ret = QMessageBox.question(self, "确认删除", "确定要删除这道错题吗？该操作不可恢复。",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
            ok = self.km_system.delete_error_question(int(self.error.get('id')))
            if ok:
                QMessageBox.information(self, "成功", "已删除该错题。")
                self._changed = True
                try:
                    self.dataChanged.emit({'action': 'delete', 'id': int(self.error.get('id'))})
                except Exception:
                    pass
                try:
                    self.accept()
                except Exception:
                    self.close()
            else:
                QMessageBox.warning(self, "错误", "删除失败，请稍后再试。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除异常：{e}")

    def _on_save_kp(self):
        """保存知识点归属更改"""
        try:
            kp_id = int(self.kp_combo2.currentData())
            if kp_id == int(self.knowledge_point_id):
                QMessageBox.information(self, "提示", "知识点未变化。")
                return
            ok = self.km_system.update_error_knowledge_point(int(self.error.get('id')), kp_id)
            if ok:
                self.knowledge_point_id = kp_id
                QMessageBox.information(self, "成功", "已更新题目所属知识点。")
                try:
                    self.dataChanged.emit({'action': 'update', 'id': int(self.error.get('id'))})
                except Exception:
                    pass
            else:
                QMessageBox.warning(self, "错误", "更新失败，请稍后再试。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"更新异常：{e}")

    def _on_apply_type_change(self):
        """应用题目类型变更（错题 -> 收藏）"""
        try:
            typ = self.type_combo.currentData()
            if typ == 'error':
                QMessageBox.information(self, "提示", "当前已是错题，无需转换。")
                return
            # 转为收藏
            fav_id = self.km_system.convert_error_to_favorite(int(self.error.get('id')))
            if fav_id is not None:
                QMessageBox.information(self, "成功", "已将此题转换为收藏，并从错题中移除。")
                try:
                    self.dataChanged.emit({'action': 'delete', 'id': int(self.error.get('id'))})
                except Exception:
                    pass
                try:
                    self.accept()
                except Exception:
                    self.close()
            else:
                QMessageBox.warning(self, "错误", "转换失败，请稍后再试。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"转换异常：{e}")

    def _load_history(self):
        try:
            history = self.km_system.get_proficiency_history(self.error['id'])
        except Exception:
            history = []
        self._history = history
        self._refresh_series()

    def _refresh_series(self):
        self.series.clear()
        if not self._history:
            # 初始点
            dt = QDateTime.currentDateTime()
            self.series.append(dt.toMSecsSinceEpoch(), int(self.error.get('current_proficiency', 20) or 20))
        else:
            for ts, prof in self._history:
                try:
                    dt = QDateTime.fromString(ts.replace('T', ' ').replace('Z', ''), 'yyyy-MM-dd HH:mm:ss')
                    if not dt.isValid():
                        dt = QDateTime.fromString(ts.split('.')[0], 'yyyy-MM-dd HH:mm:ss')
                    if not dt.isValid():
                        dt = QDateTime.currentDateTime()
                except Exception:
                    dt = QDateTime.currentDateTime()
                self.series.append(dt.toMSecsSinceEpoch(), int(prof))
        # 调整X轴范围
        if self.series.count() >= 1:
            x_values = [int(self.series.at(i).x()) for i in range(self.series.count())]
            x_min = min(x_values)
            x_max = max(x_values)
            # 避免相等导致范围无效
            if x_min == x_max:
                x_min -= 60_000  # -1分钟
                x_max += 60_000  # +1分钟
            # 限制到有效的int范围并设置范围
            self.axis_x.setRange(QDateTime.fromMSecsSinceEpoch(int(x_min)), QDateTime.fromMSecsSinceEpoch(int(x_max)))

    def _save_proficiency(self):
        try:
            current = int(self.error.get('current_proficiency', 20) or 20)
            if self._slider_adjusted:
                new_prof = int(self.prof_slider.value())
            else:
                new_prof = min(100, current + 1)
            self.km_system.append_proficiency(self.error['id'], new_prof)
            # 更新本地状态
            self.error['current_proficiency'] = new_prof
            self.prof_slider.setValue(new_prof)
            # 重新加载历史
            self._load_history()
            QMessageBox.information(self, "成功", "已记录本次熟练度")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"记录失败: {e}")

    def _generate_similar_questions(self):
        try:
            # 同步配置
            try:
                import json
                with open('app_config.json', 'r', encoding='utf-8') as f:
                    latest = json.load(f)
                if hasattr(self.km_system, 'update_config'):
                    self.km_system.update_config(latest)
            except Exception:
                pass

            count = int(self.count_spin.value())
            ref_text = self.error.get('question_content', '') if isinstance(self.error, dict) else ''

            questions = self.km_system.generate_new_questions(
                self.subject_name,
                self.knowledge_point_id,
                count,
                reference_text=ref_text
            )
            if not questions:
                self.questions_browser.setPlainText("暂无可生成的新题或生成失败")
                return

            # 将题目转换为练习面板所需的“纯文本题目”格式（不包含答案）
            lines = []
            for i, q in enumerate(questions, 1):
                stem = (q.get('question') or '').strip()
                if not stem:
                    continue
                lines.append(f"{i}. {stem}")
                opts = q.get('options') or {}
                # 使用 A) B) C) D) 风格
                for key in ["A", "B", "C", "D"]:
                    if key in opts and (opts.get(key) or '').strip():
                        lines.append(f"{key}) {opts[key].strip()}")
                # 题目间空行
                lines.append("")
            questions_text = "\n".join(lines).strip()

            # 打开技术练习面板并注入题目
            mw = self._find_main_window()
            if not mw or not hasattr(mw, 'open_practice_panel'):
                self.questions_browser.setPlainText("无法打开练习面板：主窗口不可用")
                return
            # 通过open_practice_panel传入空selected_text，避免自动生成
            try:
                mw.open_practice_panel("", 0)
                panel = getattr(mw, '_practice_panels', [])[-1]
            except Exception:
                # 回退：通过菜单打开
                if hasattr(mw, 'open_practice_panel_from_menu'):
                    mw.open_practice_panel_from_menu()
                    panel = getattr(mw, '_practice_panels', [])[-1]
                else:
                    self.questions_browser.setPlainText("无法创建练习面板")
                    return

            try:
                # 设置学习内容为原错题文本，便于用户溯源
                panel.selected_text = ref_text or panel.selected_text
                if hasattr(panel, 'content_display'):
                    panel.content_display.setPlainText(panel.selected_text)
                # 注入题目并更新面板状态
                if hasattr(panel, '_on_questions_ready'):
                    panel._on_questions_ready(questions_text)
                else:
                    # 最小注入以保证后续评估流程可用
                    panel.current_questions = questions_text
                    if hasattr(panel, 'practice_display'):
                        panel.practice_display.setPlainText(questions_text)
                    if hasattr(panel, '_set_submit_mode_evaluate'):
                        panel._set_submit_mode_evaluate()
                # 给出状态提示
                if hasattr(panel, 'status_label'):
                    panel.status_label.setText("已载入相似题目（来自错题复习）")
                # 关闭当前详情对话框，避免模态阻塞导致练习面板被遮挡
                try:
                    self.accept()
                except Exception:
                    pass
                # 不最小化父窗口，避免影响用户在练习面板的输入焦点
                # 为释放可能存在的应用级模态阻塞，尝试关闭上一层“错题复习与针对性练习”窗口
                try:
                    p = self.parent()
                    from PySide6.QtWidgets import QDialog
                    # 延链向上查找 ErrorQuestionReviewDialog 实例
                    review_dialog = None
                    while p is not None:
                        if isinstance(p, QDialog) and p.__class__.__name__ == 'ErrorQuestionReviewDialog':
                            review_dialog = p
                            break
                        p = p.parent()
                    if review_dialog is not None and hasattr(review_dialog, 'accept'):
                        review_dialog.accept()
                except Exception:
                    pass
            except Exception as e:
                self.questions_browser.setPlainText(f"注入练习面板失败: {e}")
        except Exception as e:
            self.questions_browser.setPlainText(f"生成失败: {e}")

    def _on_anchor_clicked(self, url):
        try:
            spec = url.toString()
            if spec.startswith('show://'):
                idx = spec.split('://')[-1]
                frame = self.questions_browser.page()
                # 简单方式：重新注入一段脚本隐藏/显示答案
                js = f"""
                    var a=document.getElementById('ans_{idx}'); if(a) a.style.display='block';
                    var b=document.getElementById('exp_{idx}'); if(b) b.style.display='block';
                """
                # QTextBrowser 不执行JS，这里通过替换HTML中对应段落的display属性实现逐条展开
                html = self.questions_browser.toHtml()
                html = html.replace(f"id=\"ans_{idx}\" class='ans' style='display:none;'", f"id=\"ans_{idx}\" class='ans' style='display:block;'")
                html = html.replace(f"id=\"exp_{idx}\" style='display:none;'", f"id=\"exp_{idx}\" style='display:block;'")
                self.questions_browser.setHtml(html)
        except Exception:
            pass

    def _on_questions_context_menu(self, pos: QPoint):
        menu = self.questions_browser.createStandardContextMenu()
        menu.addSeparator()
        act_deep = QPushButton  # type: ignore
        from PySide6.QtWidgets import QAction
        deep_action = QAction("深入学习", self)
        deep_action.triggered.connect(lambda: self._deep_learn_selected_question(pos))
        menu.addAction(deep_action)

        fav_action = QAction("收藏这道题", self)
        fav_action.triggered.connect(lambda: self._favorite_selected_question(pos))
        menu.addAction(fav_action)

        menu.exec(self.questions_browser.mapToGlobal(pos))

    def _locate_question_index_at_pos(self, pos: QPoint) -> int:
        """根据点选位置，向上查找最近的“题目 N”标题，返回N（1基），找不到返回-1"""
        cursor = self.questions_browser.cursorForPosition(pos)
        block = cursor.block()
        while block.isValid():
            text = block.text().strip()
            if text.startswith("题目 "):
                try:
                    num = int(''.join(ch for ch in text if ch.isdigit()))
                    return num
                except Exception:
                    return -1
            block = block.previous()
        return -1

    def _get_question_text_by_index(self, idx: int) -> str:
        html = self.questions_browser.toHtml()
        # 粗略提取题块：以 <h3>题目 idx</h3> 为起点，到下一个 <h3> 或结束
        start_tag = f"<h3>题目 {idx}</h3>"
        start = html.find(start_tag)
        if start < 0:
            return ""
        end = html.find("<h3>题目 ", start + len(start_tag))
        block_html = html[start:end] if end > start else html[start:]
        # 去掉HTML标签，得到纯文本用于传递到AI助手
        from re import sub
        text = sub(r"<[^>]+>", "", block_html)
        return text.strip()

    def _find_main_window(self):
        w = self
        while w:
            if hasattr(w, 'open_chatbot_panel'):
                return w
            w = w.parent()
        return None

    def _deep_learn_selected_question(self, pos: QPoint):
        idx = self._locate_question_index_at_pos(pos)
        if idx <= 0:
            QMessageBox.information(self, "提示", "请在某一道题目区域内右键以使用深入学习。")
            return
        text = self._get_question_text_by_index(idx)
        if not text:
            QMessageBox.warning(self, "提示", "未能获取题目文本。")
            return
        mw = self._find_main_window()
        if not mw or not hasattr(mw, 'open_chatbot_panel'):
            QMessageBox.warning(self, "提示", "无法打开AI深入学习助手面板。")
            return
        try:
            mw.open_chatbot_panel(text, 0)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开深入学习失败: {e}")

    def _favorite_selected_question(self, pos: QPoint):
        idx = self._locate_question_index_at_pos(pos)
        if idx <= 0:
            QMessageBox.information(self, "提示", "请在某一道题目区域内右键以收藏。")
            return
        # 提取题干与解析
        text = self._get_question_text_by_index(idx)
        if not text:
            QMessageBox.warning(self, "提示", "未能获取题目文本。")
            return
        # 简单切分出 题干/选项/答案/解析（若存在）
        q = {"question": "", "options": {}, "correct_answer": "", "explanation": ""}
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        mode = "question"
        for ln in lines:
            if ln.startswith("题干："):
                q["question"] = ln.replace("题干：", "", 1).strip()
                mode = "options"
            elif ln.startswith("选项："):
                mode = "options"
            elif ln.startswith("正确答案："):
                q["correct_answer"] = ln.replace("正确答案：", "", 1).strip()
                mode = "explain"
            elif ln.startswith("解析："):
                q["explanation"] = ln.replace("解析：", "", 1).strip()
                mode = "done"
            else:
                if mode == "options" and len(ln) >= 3 and ln[1] == '.' or (ln[:2] in ["A ", "B ", "C ", "D "]):
                    # 兼容 "A. xxx" 或 "A xxx"
                    key = ln[0]
                    val = ln[2:].strip() if ln[1] == '.' else ln[1:].strip()
                    q["options"][key] = val
                elif mode == "question" and not q["question"]:
                    q["question"] = ln
        # 打开收藏对话框
        dlg = FavoriteQuestionDialog(self.km_system, self.subject_name, self.knowledge_point_id, q, self)
        dlg.exec()


class FavoriteQuestionDialog(QDialog):
    """收藏题目对话框（单题，自动匹配知识点，允许用户调整后保存）"""
    def __init__(self, km_system, subject_name: str, knowledge_point_id: int, question: dict, parent=None):
        super().__init__(parent)
        self.km_system = km_system
        self.subject_name = subject_name
        self.knowledge_point_id = knowledge_point_id
        self.question = question
        self.setWindowTitle("收藏题目")
        self.resize(700, 500)
        self._setup_ui()
        self._load_points_and_rank()

    def _setup_ui(self):
        from PySide6.QtWidgets import QVBoxLayout, QLabel, QTextEdit, QHBoxLayout, QPushButton, QComboBox
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(QLabel("题目预览："))
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        # 构建预览
        parts = [f"题干：{self.question.get('question','')}"]
        if self.question.get('options'):
            parts.append("选项：")
            for k, v in self.question['options'].items():
                parts.append(f"{k}. {v}")
        self.preview.setPlainText("\n".join(parts))
        self.layout.addWidget(self.preview)

        row = QHBoxLayout()
        row.addWidget(QLabel("匹配知识点："))
        self.combo = QComboBox()
        row.addWidget(self.combo)
        self.layout.addLayout(row)

        btns = QHBoxLayout()
        save = QPushButton("收藏")
        cancel = QPushButton("取消")
        save.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(save)
        btns.addWidget(cancel)
        self.layout.addLayout(btns)

    def _load_points_and_rank(self):
        try:
            from similarity_matcher import rank_matches
            points = self.km_system.get_knowledge_points_by_subject(self.subject_name)
            ranked = rank_matches(self.question.get('question',''), points, cfg=getattr(self.km_system, 'config', {}) , min_score=0.0)
            score_map = {r['id']: r['score'] for r in ranked}
            ordered = sorted(points, key=lambda p: score_map.get(p['id'], -1.0), reverse=True)
            self.combo.clear()
            for p in ordered:
                self.combo.addItem(f"{p['point_name']} ({score_map.get(p['id'],0.0):.2f})", p['id'])
            if ordered:
                self.combo.setCurrentIndex(0)
        except Exception as e:
            QMessageBox.warning(self, "提示", f"匹配知识点失败：{e}")

    def _save(self):
        try:
            kp_id = self.combo.currentData()
            qtext = self.question.get('question','')
            correct = self.question.get('correct_answer','')
            expl = self.question.get('explanation','')
            self.km_system.save_favorite_question(self.subject_name, kp_id, qtext, correct, expl)
            QMessageBox.information(self, "成功", "已收藏该题目。")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"收藏失败：{e}")

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
