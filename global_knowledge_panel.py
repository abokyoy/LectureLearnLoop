from __future__ import annotations
from typing import List, Dict, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QComboBox, QLineEdit, QGroupBox, QMessageBox, QRadioButton
)
from PySide6.QtCharts import QChart, QChartView, QBarSet, QBarSeries, QBarCategoryAxis, QValueAxis
from PySide6.QtCore import Qt

from knowledge_management import KnowledgeManagementSystem
from error_question_ui import ErrorQuestionDetailDialog


class GlobalKnowledgeManagerDialog(QDialog):
    """题库管理：全局知识管理面板
    - 视图1：科目统计（知识点数、错题数、收藏数）+ 条形图
    - 视图2：查询筛选（学科、知识点、类型：错题/收藏、关键词），列表结果，双击打开详情
    """
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("全局知识管理")
        self.resize(1000, 700)

        self.config = config
        self.km = KnowledgeManagementSystem(config)

        self._setup_ui()
        self._load_subject_stats()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 统计视图
        stat_group = QGroupBox("科目统计")
        stat_layout = QVBoxLayout(stat_group)

        self.stat_table = QTableWidget(0, 4)
        self.stat_table.setHorizontalHeaderLabels(["学科", "知识点数", "错题数", "收藏数"])
        self.stat_table.horizontalHeader().setStretchLastSection(True)
        stat_layout.addWidget(self.stat_table)

        # 条形图
        self.chart = QChart()
        self.chart.setTitle("")
        self.chart_view = QChartView(self.chart)
        stat_layout.addWidget(self.chart_view)

        layout.addWidget(stat_group)

        # 查询视图
        query_group = QGroupBox("查询筛选")
        ql = QVBoxLayout(query_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("学科："))
        self.subject_combo = QComboBox()
        self.subject_combo.currentTextChanged.connect(self._on_subject_changed)
        row1.addWidget(self.subject_combo)

        row1.addWidget(QLabel("知识点："))
        self.kp_combo = QComboBox()
        row1.addWidget(self.kp_combo)

        self.type_error = QRadioButton("错题")
        self.type_fav = QRadioButton("收藏题")
        self.type_error.setChecked(True)
        row1.addWidget(self.type_error)
        row1.addWidget(self.type_fav)
        row1.addStretch()
        ql.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("关键词："))
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("输入关键词搜索…")
        row2.addWidget(self.keyword_edit)
        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self._do_search)
        row2.addWidget(search_btn)
        row2.addStretch()
        ql.addLayout(row2)

        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["题目片段", "时间/创建", "类型", "知识点ID"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.cellDoubleClicked.connect(self._open_detail_for_row)
        ql.addWidget(self.result_table)

        layout.addWidget(query_group)

        # 底部
        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

    def _load_subject_stats(self):
        try:
            stats = self.km.get_subject_stats()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载统计失败：{e}")
            stats = []

        # 填表
        self.stat_table.setRowCount(len(stats))
        subjects = []
        for i, s in enumerate(stats):
            subjects.append(s["subject_name"])  # for chart categories
            self.stat_table.setItem(i, 0, QTableWidgetItem(s["subject_name"]))
            self.stat_table.setItem(i, 1, QTableWidgetItem(str(s["kp_count"])) )
            self.stat_table.setItem(i, 2, QTableWidgetItem(str(s["error_count"])) )
            self.stat_table.setItem(i, 3, QTableWidgetItem(str(s["favorite_count"])) )

        # 填充查询学科下拉
        self.subject_combo.blockSignals(True)
        self.subject_combo.clear()
        self.subject_combo.addItems([s["subject_name"] for s in stats])
        self.subject_combo.blockSignals(False)
        if self.subject_combo.count() > 0:
            self._on_subject_changed(self.subject_combo.currentText())

        # 图表
        self.chart.removeAllSeries()
        set_kp = QBarSet("知识点")
        set_err = QBarSet("错题")
        set_fav = QBarSet("收藏")
        set_kp.append([s["kp_count"] for s in stats])
        set_err.append([s["error_count"] for s in stats])
        set_fav.append([s["favorite_count"] for s in stats])

        series = QBarSeries()
        series.append(set_kp)
        series.append(set_err)
        series.append(set_fav)
        self.chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(subjects)
        axis_y = QValueAxis(); axis_y.setRange(0, max([s["kp_count"]+s["error_count"]+s["favorite_count"] for s in stats] + [1]))
        self.chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x); series.attachAxis(axis_y)

    def _on_subject_changed(self, subject: str):
        # 加载该学科知识点
        try:
            points = self.km.get_knowledge_points_by_subject(subject)
        except Exception:
            points = []
        self.kp_combo.clear()
        self.kp_combo.addItem("全部", None)
        for p in points:
            self.kp_combo.addItem(p["point_name"], p["id"])

    def _do_search(self):
        subject = self.subject_combo.currentText().strip()
        kp_id = self.kp_combo.currentData()
        keyword = self.keyword_edit.text().strip()
        is_error = self.type_error.isChecked()
        try:
            if is_error:
                rows = self.km.search_error_questions(subject, kp_id, keyword)
            else:
                rows = self.km.get_favorite_questions(subject, kp_id, keyword)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"搜索失败：{e}")
            return
        # 填表
        self.result_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            frag = (r.get("question_content") or "").strip()
            self.result_table.setItem(i, 0, QTableWidgetItem(frag))
            ts = r.get("practice_time") or r.get("created_time") or ""
            self.result_table.setItem(i, 1, QTableWidgetItem(str(ts)))
            self.result_table.setItem(i, 2, QTableWidgetItem("错题" if is_error else "收藏"))
            self.result_table.setItem(i, 3, QTableWidgetItem(str(r.get("knowledge_point_id") or "")))
            # 存储整行数据
            self.result_table.setRowHeight(i, 48)
            self.result_table.setItem(i, 0, self.result_table.item(i,0))
            self.result_table.item(i,0).setData(Qt.ItemDataRole.UserRole, {"type": ("error" if is_error else "favorite"), **r})

    def _open_detail_for_row(self, row: int, col: int):
        item = self.result_table.item(row, 0)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        typ = data.get("type")
        if typ == "error":
            # 打开错题详情
            # 需要 subject 和 kp id，这里从当前筛选条件拿
            subject = self.subject_combo.currentText().strip()
            kp_id = self.kp_combo.currentData() or data.get("knowledge_point_id")
            err = {
                "id": data.get("id"),
                "question_content": data.get("question_content"),
                "user_answer": data.get("user_answer"),
                "correct_answer": data.get("correct_answer"),
                "explanation": data.get("explanation"),
                "current_proficiency": data.get("current_proficiency", 20),
            }
            dlg = ErrorQuestionDetailDialog(self.km, subject, kp_id, err, self)
            dlg.setWindowTitle("题目详情")
            try:
                dlg.dataChanged.connect(lambda _:
                    self._do_search()
                )
            except Exception:
                pass
            dlg.exec()
        else:
            # 收藏题：简单预览
            QMessageBox.information(self, "收藏题目", (data.get("question_content") or "").strip()[:2000])
