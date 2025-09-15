"""
ErrorImportDialog - 从任意评估报告中提取错题，允许用户校对并入库。

依赖：
- PySide6
- knowledge_management.KnowledgeManagementSystem
- enhanced_practice_integration.ErrorQuestionSlicer, KnowledgePointMatcher
- similarity_matcher（已在 KnowledgePointMatcher 使用）

功能：
- 展示切片出的错题（题干片段、用户答案、匹配的知识点）
- 用户可逐题调整知识点（下拉框）
- 支持“全部入库”和“入库选中”

低耦合：仅做展示与调用保存API，不引入LLM调用。
"""
from __future__ import annotations
from typing import List, Dict, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt

from knowledge_management import KnowledgeManagementSystem
from enhanced_practice_integration import ErrorQuestionSlicer, KnowledgePointMatcher


class ErrorImportDialog(QDialog):
    def __init__(self, config: dict, practice_content: str, evaluation_result: str, note_content: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("错题入库")
        self.resize(900, 600)

        self.config = config
        self.practice_content = practice_content or ""
        self.evaluation_result = evaluation_result or ""
        self.note_content = note_content or ""

        self.km_system = KnowledgeManagementSystem(config)
        self.slicer = ErrorQuestionSlicer(config)
        self.matcher = KnowledgePointMatcher(config)

        self.all_knowledge_points: List[Dict] = []  # [{id, display, subject_name, point_name}]
        self.error_questions: List[Dict] = []

        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("从评估报告中提取到的错题：可调整知识点后入库")
        title.setStyleSheet("font-weight: bold; padding: 6px;")
        layout.addWidget(title)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["序号", "题目片段", "用户答案", "匹配知识点"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.btn_import_selected = QPushButton("入库选中")
        self.btn_import_all = QPushButton("全部入库")
        self.btn_close = QPushButton("关闭")
        btn_layout.addWidget(self.btn_import_selected)
        btn_layout.addWidget(self.btn_import_all)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self.btn_import_selected.clicked.connect(self._import_selected)
        self.btn_import_all.clicked.connect(self._import_all)
        self.btn_close.clicked.connect(self.reject)

    def _load_data(self):
        # 1) 加载知识点全集（按学科聚合）
        try:
            subjects = self.km_system.get_subjects()
            for subject in subjects:
                points = self.km_system.get_knowledge_points_by_subject(subject)
                for p in points:
                    self.all_knowledge_points.append({
                        "id": p["id"],
                        "subject_name": subject,
                        "point_name": p["point_name"],
                        "core_description": p.get("core_description", ""),
                        "display": f"{subject} - {p['point_name']}"
                    })
        except Exception as e:
            QMessageBox.warning(self, "提示", f"加载知识点失败：{e}")

        # 2) 错题切片
        self.error_questions = self.slicer.slice_error_questions(self.practice_content, self.evaluation_result)

        # 3) 预匹配知识点
        self.table.setRowCount(len(self.error_questions))
        for i, err in enumerate(self.error_questions):
            idx_item = QTableWidgetItem(str(err.get("question_index", i) + 1))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 0, idx_item)

            q_text = (err.get("question_content") or "").strip()
            q_text_short = (q_text[:80] + "...") if len(q_text) > 80 else q_text
            q_item = QTableWidgetItem(q_text_short)
            q_item.setToolTip(q_text)
            q_item.setFlags(q_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 1, q_item)

            a_text = (err.get("user_answer") or "").strip()
            a_text_short = (a_text[:80] + "...") if len(a_text) > 80 else a_text
            a_item = QTableWidgetItem(a_text_short)
            a_item.setToolTip(a_text)
            a_item.setFlags(a_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, 2, a_item)

            # Combo for knowledge points
            combo = QComboBox()
            for kp in self.all_knowledge_points:
                combo.addItem(kp["display"], kp["id"])
            # Try match
            matched_id = self._match_point_for_error(err)
            if matched_id:
                idx = self._index_of_point(matched_id)
                if idx is not None:
                    combo.setCurrentIndex(idx)
            self.table.setCellWidget(i, 3, combo)

    def _index_of_point(self, pid: int) -> Optional[int]:
        for i, kp in enumerate(self.all_knowledge_points):
            if kp["id"] == pid:
                return i
        return None

    def _match_point_for_error(self, err: Dict) -> Optional[int]:
        try:
            subject = self.matcher._infer_subject(self.note_content, [
                {
                    "question_content": err.get("question_content", ""),
                    "knowledge_point_hint": err.get("knowledge_point_hint", "")
                }
            ])
            points = self.km_system.get_knowledge_points_by_subject(subject)
            # 回退：若该学科无点，则用全集
            if not points:
                points = [
                    {
                        "id": kp["id"],
                        "point_name": kp["point_name"],
                        "core_description": kp.get("core_description", "")
                    } for kp in self.all_knowledge_points
                ]
            return self.matcher._match_single_question(err, points)
        except Exception:
            return None

    def _collect_selection(self) -> List[int]:
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        return sorted(list(rows))

    def _import_selected(self):
        rows = self._collect_selection()
        if not rows:
            QMessageBox.information(self, "提示", "请先选择需要入库的错题行。")
            return
        self._import_rows(rows)

    def _import_all(self):
        rows = list(range(self.table.rowCount()))
        if not rows:
            QMessageBox.information(self, "提示", "没有可入库的错题。")
            return
        self._import_rows(rows)

    def _import_rows(self, rows: List[int]):
        try:
            records = []
            for r in rows:
                err = self.error_questions[r]
                combo: QComboBox = self.table.cellWidget(r, 3)  # type: ignore
                kp_id = combo.currentData()
                if not kp_id:
                    continue
                subject_name = None
                for kp in self.all_knowledge_points:
                    if kp["id"] == kp_id:
                        subject_name = kp["subject_name"]
                        break
                records.append({
                    "subject_name": subject_name or "通用学科",
                    "knowledge_point_id": kp_id,
                    "question_content": err.get("question_content", ""),
                    "user_answer": err.get("user_answer", ""),
                    "is_correct": False
                })

            if not records:
                QMessageBox.information(self, "提示", "无有效记录可入库。")
                return

            saved_ids = self.km_system.save_practice_results(records)
            QMessageBox.information(self, "成功", f"已保存 {len(saved_ids) if saved_ids else 0} 条错题到知识库。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"入库失败：{e}")
