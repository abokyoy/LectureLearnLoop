"""
题目复习面板 - 完全复刻HTML设计的Qt版本
"""

import sys
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QComboBox, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QGroupBox, QSplitter, QCheckBox, QLineEdit, QTextBrowser, QWidget,
    QScrollArea, QFrame, QSpacerItem, QSizePolicy, QGridLayout, QSpinBox
)
from PySide6.QtGui import QFont, QPixmap, QPainter, QColor, QIcon
from PySide6.QtCore import Qt, QSize, QTimer
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib
matplotlib.use('Qt5Agg')


class QuestionReviewPanel(QDialog):
    """题目复习面板"""
    
    def __init__(self, parent=None, question_data=None):
        super().__init__(parent)
        self.question_data = question_data or self._get_default_question_data()
        
        self.setWindowTitle("错题复习")
        self.setModal(True)
        self.resize(1200, 800)
        
        # 设置样式
        self.setStyleSheet("""
            QDialog {
                background-color: #F5F7F9;
                font-family: "Microsoft YaHei", sans-serif;
            }
            QGroupBox {
                background-color: white;
                border-radius: 12px;
                padding: 20px;
                margin: 8px;
                font-size: 14px;
                font-weight: bold;
                color: #715D46;
            }
            QGroupBox::title {
                color: #715D46;
                font-size: 16px;
                font-weight: bold;
                padding: 0 10px;
            }
            QPushButton {
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 14px;
                font-weight: 600;
                border: none;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
            .primary-btn {
                background-color: #32C77F;
                color: white;
            }
            .secondary-btn {
                background-color: #FF9B27;
                color: white;
            }
            .gray-btn {
                background-color: #E5E7EB;
                color: #715D46;
            }
            QLabel {
                color: #715D46;
            }
            QComboBox, QLineEdit, QSpinBox {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 8px;
                background-color: white;
            }
        """)
        
        self._setup_ui()
    
    def _get_default_question_data(self):
        """获取默认的题目数据"""
        return {
            "question": "在社会主义改造基本完成后，中国共产党提出的主要任务是（）。",
            "user_answer": "A. 实行\"一化三改\"",
            "correct_answer": "B",
            "is_correct": False,
            "analysis": "1956年社会主义改造基本完成后，国内主要矛盾已经转变为人民对于经济文化迅速发展的需要同当前经济文化不能满足人民需要的状况之间的矛盾，党和国家的主要任务是集中力量来解决这个矛盾，把我国尽快地从落后的农业国变为先进的工业国。",
            "knowledge_point": "毛泽东思想和中国特色社会主义理论体系概论",
            "question_type": "单选题",
            "proficiency": "60%"
        }
    
    def _setup_ui(self):
        """设置UI"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建左侧菜单面板
        self._create_sidebar()
        
        # 创建主内容区域
        self._create_main_content()
        
        main_layout.addWidget(self.sidebar_frame)
        main_layout.addWidget(self.main_content_area, 1)
    
    def _create_sidebar(self):
        """创建左侧菜单栏"""
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setFixedWidth(256)
        self.sidebar_frame.setStyleSheet("""
            QFrame {
                background-color: white;
                border-right: 1px solid #E5E7EB;
            }
        """)
        
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(0)
        
        # Logo和标题
        header_layout = QHBoxLayout()
        logo_label = QLabel("🐕")
        logo_label.setStyleSheet("""
            QLabel {
                background-color: #32C77F;
                border-radius: 20px;
                color: white;
                font-size: 16px;
                padding: 8px;
            }
        """)
        logo_label.setFixedSize(40, 40)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        title_label = QLabel("柯基学习小助手")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #715D46;
                margin-left: 12px;
            }
        """)
        
        header_layout.addWidget(logo_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        sidebar_layout.addLayout(header_layout)
        
        sidebar_layout.addSpacing(32)
        
        # 用户信息
        user_widget = QWidget()
        user_layout = QVBoxLayout(user_widget)
        user_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        avatar_label = QLabel()
        avatar_label.setFixedSize(80, 80)
        avatar_label.setStyleSheet("""
            QLabel {
                border-radius: 40px;
                background-color: #E5E7EB;
                border: 2px solid #D1D5DB;
            }
        """)
        avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_label.setText("👤")
        
        name_label = QLabel("柯基的主人")
        name_label.setStyleSheet("font-weight: bold; color: #715D46;")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        level_label = QLabel("学习等级: Lv.5 ⭐")
        level_label.setStyleSheet("color: #9B8D7D; font-size: 12px;")
        level_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        user_layout.addWidget(avatar_label)
        user_layout.addWidget(name_label)
        user_layout.addWidget(level_label)
        
        sidebar_layout.addWidget(user_widget)
        sidebar_layout.addSpacing(32)
        
        # 菜单项
        menu_items = [
            ("工作台", "🏢", False),
            ("笔记本", "📝", False),
            ("录音室", "🎤", False),
            ("AI伙伴", "🤖", False),
            ("知识库", "📚", True),  # 当前选中
            ("学习报告", "📊", False),
            ("设置", "⚙️", False),
        ]
        
        for text, icon, is_active in menu_items:
            btn = self._create_menu_button(text, icon, is_active)
            sidebar_layout.addWidget(btn)
        
        sidebar_layout.addStretch()
        
        # 收缩按钮
        self.collapse_btn = QPushButton("◀")
        self.collapse_btn.setFixedSize(40, 40)
        self.collapse_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #828282;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #F2F0ED;
                border-radius: 20px;
            }
        """)
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        sidebar_layout.addWidget(self.collapse_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.sidebar_collapsed = False
    
    def _create_menu_button(self, text, icon, is_active):
        """创建菜单按钮"""
        btn = QPushButton(f"{icon}  {text}")
        btn.setFixedHeight(44)
        
        if is_active:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #32C77F;
                    color: white;
                    border-radius: 8px;
                    text-align: left;
                    padding-left: 16px;
                    font-size: 14px;
                }
            """)
        else:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #828282;
                    border-radius: 8px;
                    text-align: left;
                    padding-left: 16px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #F2F0ED;
                }
            """)
        
        return btn
    
    def _toggle_sidebar(self):
        """切换侧边栏收缩状态"""
        if self.sidebar_collapsed:
            self.sidebar_frame.setFixedWidth(256)
            self.collapse_btn.setText("◀")
            # 显示文字
            for i in range(self.sidebar_frame.layout().count()):
                item = self.sidebar_frame.layout().itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, QPushButton) and widget != self.collapse_btn:
                        text = widget.text()
                        if "  " in text:
                            widget.setText(text)
        else:
            self.sidebar_frame.setFixedWidth(72)
            self.collapse_btn.setText("▶")
            # 隐藏文字，只显示图标
            for i in range(self.sidebar_frame.layout().count()):
                item = self.sidebar_frame.layout().itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if isinstance(widget, QPushButton) and widget != self.collapse_btn:
                        text = widget.text()
                        if "  " in text:
                            icon = text.split("  ")[0]
                            widget.setText(icon)
        
        self.sidebar_collapsed = not self.sidebar_collapsed
    
    def _create_main_content(self):
        """创建主内容区域"""
        self.main_content_area = QWidget()
        self.main_content_area.setStyleSheet("background-color: #F5F7F9;")
        
        main_layout = QVBoxLayout(self.main_content_area)
        main_layout.setContentsMargins(32, 32, 32, 32)
        main_layout.setSpacing(24)
        
        # 标题栏
        self._create_header(main_layout)
        
        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(24)
        
        # 题目信息
        self._create_question_info(scroll_layout)
        
        # 底部网格布局
        grid_layout = QGridLayout()
        grid_layout.setSpacing(24)
        
        # 题目归属与类型
        self._create_question_category(grid_layout, 0, 0)
        
        # 熟练度调整
        self._create_proficiency_adjustment(grid_layout, 0, 1)
        
        # 针对性新题生成
        self._create_question_generation(grid_layout, 1, 0, 1, 2)
        
        # 熟练度图表
        self._create_proficiency_chart(grid_layout, 2, 0, 1, 2)
        
        scroll_layout.addLayout(grid_layout)
        
        # 底部按钮
        self._create_bottom_buttons(scroll_layout)
        
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)
    
    def _create_header(self, layout):
        """创建标题栏"""
        header_layout = QHBoxLayout()
        
        title_label = QLabel("错题复习")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 32px;
                font-weight: bold;
                color: #715D46;
            }
        """)
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        # 右侧按钮组
        notification_btn = QPushButton("🔔")
        notification_btn.setFixedSize(40, 40)
        notification_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border-radius: 20px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #E5E7EB;
            }
        """)
        
        # 状态指示器
        status_layout = QHBoxLayout()
        for color in ["#D1D5DB", "#FF9B27", "#ED4B4B"]:
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"""
                QLabel {{
                    background-color: {color};
                    border-radius: 6px;
                }}
            """)
            status_layout.addWidget(dot)
        
        header_layout.addWidget(notification_btn)
        header_layout.addLayout(status_layout)
        
        layout.addLayout(header_layout)
    
    def _create_question_info(self, layout):
        """创建题目信息区域"""
        group = QGroupBox("题目信息")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(16)
        
        # 题干
        question_label = QLabel("题干")
        question_label.setStyleSheet("font-weight: bold; color: #715D46; font-size: 14px;")
        question_text = QLabel(self.question_data["question"])
        question_text.setStyleSheet("color: #9B8D7D; font-size: 14px;")
        question_text.setWordWrap(True)
        
        group_layout.addWidget(question_label)
        group_layout.addWidget(question_text)
        
        # 你的答案
        answer_label = QLabel("你的答案")
        answer_label.setStyleSheet("font-weight: bold; color: #715D46; font-size: 14px;")
        answer_text = QLabel(self.question_data["user_answer"])
        answer_text.setStyleSheet("color: #ED4B4B; font-size: 14px;")
        
        group_layout.addWidget(answer_label)
        group_layout.addWidget(answer_text)
        
        # 判定
        judgment_label = QLabel("判定")
        judgment_label.setStyleSheet("font-weight: bold; color: #715D46; font-size: 14px;")
        
        judgment_layout = QHBoxLayout()
        status_icon = QLabel("❌" if not self.question_data["is_correct"] else "✅")
        status_text = QLabel("错误" if not self.question_data["is_correct"] else "正确")
        status_text.setStyleSheet("color: #ED4B4B;" if not self.question_data["is_correct"] else "color: #32C77F;")
        
        correct_answer = QLabel(f"正确答案：{self.question_data['correct_answer']}")
        correct_answer.setStyleSheet("color: #9B8D7D; margin-left: 16px;")
        
        judgment_layout.addWidget(status_icon)
        judgment_layout.addWidget(status_text)
        judgment_layout.addWidget(correct_answer)
        judgment_layout.addStretch()
        
        group_layout.addWidget(judgment_label)
        group_layout.addLayout(judgment_layout)
        
        # 分析与要点
        analysis_label = QLabel("分析与要点")
        analysis_label.setStyleSheet("font-weight: bold; color: #715D46; font-size: 14px;")
        analysis_text = QLabel(self.question_data["analysis"])
        analysis_text.setStyleSheet("color: #9B8D7D; font-size: 14px;")
        analysis_text.setWordWrap(True)
        
        group_layout.addWidget(analysis_label)
        group_layout.addWidget(analysis_text)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        
        mastered_btn = QPushButton("👍 我已掌握")
        mastered_btn.setStyleSheet("""
            QPushButton {
                background-color: #32C77F;
                color: white;
                padding: 12px 16px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2BA86F;
            }
        """)
        
        error_book_btn = QPushButton("📚 加入错题本")
        error_book_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9B27;
                color: white;
                padding: 12px 16px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E8891E;
            }
        """)
        
        ai_explain_btn = QPushButton("❓ 请求AI讲解")
        ai_explain_btn.setStyleSheet("""
            QPushButton {
                background-color: #E5E7EB;
                color: #715D46;
                padding: 12px 16px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D1D5DB;
            }
        """)
        
        button_layout.addWidget(mastered_btn)
        button_layout.addWidget(error_book_btn)
        button_layout.addWidget(ai_explain_btn)
        button_layout.addStretch()
        
        group_layout.addLayout(button_layout)
        
        layout.addWidget(group)
    
    def _create_question_category(self, layout, row, col):
        """创建题目归属与类型区域"""
        group = QGroupBox("题目归属与类型")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(16)
        
        # 所属知识点
        kp_label = QLabel("所属知识点")
        kp_label.setStyleSheet("font-size: 12px; color: #828282; font-weight: normal;")
        kp_combo = QComboBox()
        kp_combo.addItems([
            self.question_data["knowledge_point"],
            "马克思主义基本原理"
        ])
        
        group_layout.addWidget(kp_label)
        group_layout.addWidget(kp_combo)
        
        # 题目类型
        type_label = QLabel("题目类型")
        type_label.setStyleSheet("font-size: 12px; color: #828282; font-weight: normal;")
        type_combo = QComboBox()
        type_combo.addItems([
            self.question_data["question_type"],
            "多选题",
            "判断题"
        ])
        
        group_layout.addWidget(type_label)
        group_layout.addWidget(type_combo)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        
        save_btn = QPushButton("💾 保存")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #32C77F;
                color: white;
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: bold;
            }
        """)
        
        convert_btn = QPushButton("🔄 转换")
        convert_btn.setStyleSheet("""
            QPushButton {
                background-color: #E5E7EB;
                color: #715D46;
                padding: 8px 16px;
                border-radius: 8px;
                font-weight: bold;
            }
        """)
        
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(convert_btn)
        
        group_layout.addLayout(btn_layout)
        
        layout.addWidget(group, row, col)
    
    def _create_proficiency_adjustment(self, layout, row, col):
        """创建熟练度调整区域"""
        group = QGroupBox("熟练度调整")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(16)
        
        # 当前熟练度
        prof_label = QLabel("当前熟练度")
        prof_label.setStyleSheet("font-size: 12px; color: #828282; font-weight: normal;")
        prof_input = QLineEdit(self.question_data["proficiency"])
        prof_input.setPlaceholderText("例如: 60%")
        
        group_layout.addWidget(prof_label)
        group_layout.addWidget(prof_input)
        
        group_layout.addStretch()
        
        # 记录按钮
        record_btn = QPushButton("✅ 记录熟练度")
        record_btn.setStyleSheet("""
            QPushButton {
                background-color: #32C77F;
                color: white;
                padding: 12px 16px;
                border-radius: 8px;
                font-weight: bold;
            }
        """)
        
        group_layout.addWidget(record_btn)
        
        layout.addWidget(group, row, col)
    
    def _create_question_generation(self, layout, row, col, rowspan, colspan):
        """创建针对性新题生成区域"""
        group = QGroupBox("针对性新题生成")
        group_layout = QHBoxLayout(group)
        group_layout.setSpacing(16)
        
        # 生成题数
        num_label = QLabel("生成题数")
        num_label.setStyleSheet("font-size: 12px; color: #828282; font-weight: normal;")
        num_input = QSpinBox()
        num_input.setMinimum(1)
        num_input.setMaximum(20)
        num_input.setValue(5)
        
        input_layout = QVBoxLayout()
        input_layout.addWidget(num_label)
        input_layout.addWidget(num_input)
        
        group_layout.addLayout(input_layout)
        
        # 生成按钮
        generate_btn = QPushButton("🧠 生成新题")
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #32C77F;
                color: white;
                padding: 16px 24px;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
            }
        """)
        
        group_layout.addWidget(generate_btn)
        
        layout.addWidget(group, row, col, rowspan, colspan)
    
    def _create_proficiency_chart(self, layout, row, col, rowspan, colspan):
        """创建熟练度图表区域"""
        group = QGroupBox("熟练度随时间变化")
        group_layout = QVBoxLayout(group)
        
        # 创建matplotlib图表
        figure = Figure(figsize=(8, 4), dpi=100)
        canvas = FigureCanvas(figure)
        
        ax = figure.add_subplot(111)
        
        # 示例数据
        dates = ['2024-08-01', '2024-08-15', '2024-09-01', '2024-09-17', '2024-10-01']
        proficiency = [20, 45, 40, 65, 80]
        
        ax.plot(dates, proficiency, color='#32C77F', linewidth=2, marker='o', markersize=6)
        ax.fill_between(dates, proficiency, alpha=0.2, color='#32C77F')
        
        ax.set_ylabel('熟练度 (%)')
        ax.set_ylim(0, 100)
        ax.grid(True, alpha=0.3)
        
        # 设置x轴标签旋转
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
        
        figure.tight_layout()
        
        group_layout.addWidget(canvas)
        
        layout.addWidget(group, row, col, rowspan, colspan)
    
    def _create_bottom_buttons(self, layout):
        """创建底部按钮"""
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #9CA3AF;
                color: white;
                padding: 12px 24px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6B7280;
            }
        """)
        close_btn.clicked.connect(self.accept)
        
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)


def open_question_review_panel(parent=None, question_data=None):
    """打开题目复习面板的便捷函数"""
    panel = QuestionReviewPanel(parent, question_data)
    return panel.exec()


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    panel = QuestionReviewPanel()
    panel.show()
    sys.exit(app.exec())
