#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
现代化学习笔记软件 - 主界面框架
基于您提供的UI设计风格，采用单界面布局
"""

import sys
import os
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

class ModernSidebarWidget(QWidget):
    """现代化侧边栏菜单"""
    menuClicked = Signal(str, str)  # 菜单项点击信号 (category, item)
    
    def __init__(self):
        super().__init__()
        self.current_category = "工作台"
        self.current_item = "今日概览"
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 应用标题
        title_widget = QWidget()
        title_widget.setFixedHeight(60)
        title_widget.setStyleSheet("""
            QWidget {
                background-color: #4A90E2;
                color: white;
            }
        """)
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(20, 0, 20, 0)
        
        title_label = QLabel("🧠 智能学习助手")
        title_label.setFont(QFont("微软雅黑", 14, QFont.Weight.Bold))
        title_label.setStyleSheet("color: white;")
        title_layout.addWidget(title_label)
        
        layout.addWidget(title_widget)
        
        # 菜单区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #F7FAFC;
            }
        """)
        
        menu_widget = QWidget()
        menu_layout = QVBoxLayout(menu_widget)
        menu_layout.setContentsMargins(0, 10, 0, 10)
        menu_layout.setSpacing(5)
        
        # 菜单数据
        menu_data = {
            "🏠 工作台": ["📊 今日概览", "📈 学习进度", "🎯 待办事项"],
            "📝 笔记管理": ["📄 新建笔记", "📂 我的笔记", "🔍 搜索笔记", "📤 导出笔记"],
            "🎙️ 录制转写": ["🎤 开始录制", "⏹️ 停止录制", "📝 手动总结", "📸 截图笔记"],
            "🤖 AI助手": ["💬 深入学习", "📝 智能练习", "🧠 知识提取", "📋 对话历史"],
            "📚 知识库": ["🧠 知识点管理", "❌ 错题本", "⭐ 收藏题目", "🔍 全局搜索"],
            "📊 学习统计": ["📈 学习报告", "🎯 掌握度分析", "📅 学习日历", "📊 数据导出"],
            "⚙️ 系统设置": ["🎨 界面设置", "🤖 AI配置", "🎙️ 音频设置", "📁 数据管理"]
        }
        
        # 创建菜单项
        for category, items in menu_data.items():
            category_widget = self.create_category_widget(category, items)
            menu_layout.addWidget(category_widget)
        
        menu_layout.addStretch()
        scroll_area.setWidget(menu_widget)
        layout.addWidget(scroll_area)
        
    def create_category_widget(self, category, items):
        """创建分类菜单组件"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # 分类标题
        category_btn = QPushButton(category)
        category_btn.setFixedHeight(45)
        category_btn.setStyleSheet(self.get_category_style(category == self.current_category))
        category_btn.clicked.connect(lambda: self.toggle_category(category, widget))
        layout.addWidget(category_btn)
        
        # 子菜单容器
        items_widget = QWidget()
        items_layout = QVBoxLayout(items_widget)
        items_layout.setContentsMargins(20, 0, 0, 0)
        items_layout.setSpacing(2)
        
        for item in items:
            item_btn = QPushButton(item)
            item_btn.setFixedHeight(35)
            is_current = (category == self.current_category and item == self.current_item)
            item_btn.setStyleSheet(self.get_item_style(is_current))
            item_btn.clicked.connect(lambda checked, c=category, i=item: self.select_item(c, i))
            items_layout.addWidget(item_btn)
        
        # 初始状态：只展开当前分类
        items_widget.setVisible(category == self.current_category)
        layout.addWidget(items_widget)
        
        return widget
        
    def get_category_style(self, is_current):
        """获取分类按钮样式"""
        if is_current:
            return """
                QPushButton {
                    background-color: #4A90E2;
                    color: white;
                    border: none;
                    text-align: left;
                    padding-left: 15px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #357ABD;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: transparent;
                    color: #2D3748;
                    border: none;
                    text-align: left;
                    padding-left: 15px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #EDF2F7;
                }
            """
    
    def get_item_style(self, is_current):
        """获取子菜单项样式"""
        if is_current:
            return """
                QPushButton {
                    background-color: #EBF8FF;
                    color: #2C5282;
                    border: none;
                    border-left: 3px solid #4A90E2;
                    text-align: left;
                    padding-left: 15px;
                    font-size: 12px;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: transparent;
                    color: #4A5568;
                    border: none;
                    text-align: left;
                    padding-left: 15px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #F7FAFC;
                    color: #2D3748;
                }
            """
    
    def toggle_category(self, category, widget):
        """切换分类展开/收起"""
        items_widget = widget.findChild(QWidget)
        if items_widget:
            items_widget.setVisible(not items_widget.isVisible())
    
    def select_item(self, category, item):
        """选择菜单项"""
        self.current_category = category
        self.current_item = item
        self.menuClicked.emit(category, item)
        # 刷新样式
        self.setup_ui()

class ModernContentWidget(QWidget):
    """现代化内容区域"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 内容堆栈
        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet("""
            QStackedWidget {
                background-color: white;
                border: none;
            }
        """)
        
        # 添加各个功能页面
        self.add_dashboard_page()
        self.add_notes_page()
        self.add_recording_page()
        self.add_ai_assistant_page()
        self.add_knowledge_page()
        self.add_statistics_page()
        self.add_settings_page()
        
        layout.addWidget(self.content_stack)
        
    def add_dashboard_page(self):
        """添加工作台页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 页面标题
        title = QLabel("📊 今日学习概览")
        title.setFont(QFont("微软雅黑", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #2D3748; margin-bottom: 20px;")
        layout.addWidget(title)
        
        # 统计卡片区域
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(20)
        
        stats_data = [
            ("📝 今日笔记", "3篇", "#48BB78"),
            ("🎯 练习完成", "15题", "#4A90E2"),
            ("🧠 新增知识点", "8个", "#ED8936"),
            ("⏱️ 学习时长", "2h 35m", "#9F7AEA")
        ]
        
        for title_text, value, color in stats_data:
            card = self.create_stat_card(title_text, value, color)
            cards_layout.addWidget(card)
        
        layout.addLayout(cards_layout)
        
        # 学习计划区域
        plan_widget = self.create_learning_plan_widget()
        layout.addWidget(plan_widget)
        
        layout.addStretch()
        self.content_stack.addWidget(page)
        
    def create_stat_card(self, title, value, color):
        """创建统计卡片"""
        card = QWidget()
        card.setFixedHeight(120)
        card.setStyleSheet(f"""
            QWidget {{
                background-color: white;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                border-left: 4px solid {color};
            }}
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 15, 20, 15)
        
        title_label = QLabel(title)
        title_label.setFont(QFont("微软雅黑", 11))
        title_label.setStyleSheet("color: #718096;")
        
        value_label = QLabel(value)
        value_label.setFont(QFont("微软雅黑", 24, QFont.Weight.Bold))
        value_label.setStyleSheet(f"color: {color};")
        
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addStretch()
        
        return card
        
    def create_learning_plan_widget(self):
        """创建学习计划组件"""
        widget = QWidget()
        widget.setStyleSheet("""
            QWidget {
                background-color: white;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
            }
        """)
        
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(25, 20, 25, 20)
        
        # 标题
        title = QLabel("🎯 今日学习计划")
        title.setFont(QFont("微软雅黑", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #2D3748; margin-bottom: 15px;")
        layout.addWidget(title)
        
        # 计划项目
        plans = [
            ("✅", "机器学习基础概念复习", "已完成 09:30", "#48BB78"),
            ("✅", "神经网络练习题 (15题)", "已完成 11:15", "#48BB78"),
            ("🔄", "深度学习论文阅读", "进行中 14:20", "#ED8936"),
            ("⏳", "数据预处理实践", "待开始 16:00", "#A0AEC0")
        ]
        
        for status, task, time, color in plans:
            plan_item = self.create_plan_item(status, task, time, color)
            layout.addWidget(plan_item)
        
        return widget
        
    def create_plan_item(self, status, task, time, color):
        """创建计划项目"""
        item = QWidget()
        item.setFixedHeight(50)
        
        layout = QHBoxLayout(item)
        layout.setContentsMargins(0, 10, 0, 10)
        
        status_label = QLabel(status)
        status_label.setFixedWidth(30)
        status_label.setFont(QFont("微软雅黑", 14))
        
        task_label = QLabel(task)
        task_label.setFont(QFont("微软雅黑", 12))
        task_label.setStyleSheet("color: #2D3748;")
        
        time_label = QLabel(time)
        time_label.setFont(QFont("微软雅黑", 11))
        time_label.setStyleSheet(f"color: {color};")
        
        layout.addWidget(status_label)
        layout.addWidget(task_label)
        layout.addStretch()
        layout.addWidget(time_label)
        
        return item
        
    def add_notes_page(self):
        """添加笔记管理页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("📝 笔记管理")
        title.setFont(QFont("微软雅黑", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #2D3748;")
        layout.addWidget(title)
        
        placeholder = QLabel("笔记管理功能正在开发中...")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #A0AEC0; font-size: 14px;")
        layout.addWidget(placeholder)
        
        self.content_stack.addWidget(page)
        
    def add_recording_page(self):
        """添加录制转写页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("🎙️ 录制转写")
        title.setFont(QFont("微软雅黑", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #2D3748;")
        layout.addWidget(title)
        
        placeholder = QLabel("录制转写功能正在开发中...")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #A0AEC0; font-size: 14px;")
        layout.addWidget(placeholder)
        
        self.content_stack.addWidget(page)
        
    def add_ai_assistant_page(self):
        """添加AI助手页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("🤖 AI助手")
        title.setFont(QFont("微软雅黑", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #2D3748;")
        layout.addWidget(title)
        
        placeholder = QLabel("AI助手功能正在开发中...")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #A0AEC0; font-size: 14px;")
        layout.addWidget(placeholder)
        
        self.content_stack.addWidget(page)
        
    def add_knowledge_page(self):
        """添加知识库页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("📚 知识库")
        title.setFont(QFont("微软雅黑", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #2D3748;")
        layout.addWidget(title)
        
        placeholder = QLabel("知识库功能正在开发中...")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #A0AEC0; font-size: 14px;")
        layout.addWidget(placeholder)
        
        self.content_stack.addWidget(page)
        
    def add_statistics_page(self):
        """添加学习统计页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("📊 学习统计")
        title.setFont(QFont("微软雅黑", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #2D3748;")
        layout.addWidget(title)
        
        placeholder = QLabel("学习统计功能正在开发中...")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #A0AEC0; font-size: 14px;")
        layout.addWidget(placeholder)
        
        self.content_stack.addWidget(page)
        
    def add_settings_page(self):
        """添加系统设置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("⚙️ 系统设置")
        title.setFont(QFont("微软雅黑", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #2D3748;")
        layout.addWidget(title)
        
        placeholder = QLabel("系统设置功能正在开发中...")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #A0AEC0; font-size: 14px;")
        layout.addWidget(placeholder)
        
        self.content_stack.addWidget(page)
        
    def show_page(self, category, item):
        """显示指定页面"""
        page_map = {
            "工作台": 0,
            "笔记管理": 1,
            "录制转写": 2,
            "AI助手": 3,
            "知识库": 4,
            "学习统计": 5,
            "系统设置": 6
        }
        
        category_key = category.split(" ", 1)[1] if " " in category else category
        page_index = page_map.get(category_key, 0)
        self.content_stack.setCurrentIndex(page_index)

class ModernLearningApp(QMainWindow):
    """现代化学习笔记软件主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.setup_window()
        
    def setup_window(self):
        """设置窗口属性"""
        self.setWindowTitle("智能学习笔记助手 v2.0")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # 设置窗口图标
        self.setWindowIcon(QIcon())
        
        # 居中显示
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        
    def setup_ui(self):
        """设置用户界面"""
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 侧边栏
        self.sidebar = ModernSidebarWidget()
        self.sidebar.setFixedWidth(250)
        self.sidebar.menuClicked.connect(self.on_menu_clicked)
        
        # 内容区域
        self.content_widget = ModernContentWidget()
        
        # 添加到主布局
        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.content_widget)
        
        # 状态栏
        self.setup_statusbar()
        
        # 应用样式
        self.apply_global_styles()
        
    def setup_statusbar(self):
        """设置状态栏"""
        statusbar = self.statusBar()
        statusbar.setStyleSheet("""
            QStatusBar {
                background-color: #F7FAFC;
                border-top: 1px solid #E2E8F0;
                color: #4A5568;
                font-size: 11px;
            }
        """)
        
        # 状态信息
        self.status_label = QLabel("📄 当前文档: 机器学习笔记.md")
        self.recording_label = QLabel("⚪ 未录制")
        self.save_label = QLabel("💾 已保存")
        self.api_label = QLabel("🌐 API已连接")
        
        statusbar.addWidget(self.status_label)
        statusbar.addPermanentWidget(self.recording_label)
        statusbar.addPermanentWidget(self.save_label)
        statusbar.addPermanentWidget(self.api_label)
        
    def apply_global_styles(self):
        """应用全局样式"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F7FAFC;
            }
            
            QWidget {
                font-family: "微软雅黑", "Microsoft YaHei", sans-serif;
            }
            
            QScrollBar:vertical {
                background-color: #F7FAFC;
                width: 8px;
                border: none;
            }
            
            QScrollBar::handle:vertical {
                background-color: #CBD5E0;
                border-radius: 4px;
                min-height: 20px;
            }
            
            QScrollBar::handle:vertical:hover {
                background-color: #A0AEC0;
            }
            
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
        """)
        
    def on_menu_clicked(self, category, item):
        """处理菜单点击事件"""
        print(f"菜单点击: {category} -> {item}")
        self.content_widget.show_page(category, item)
        
        # 更新状态栏
        self.status_label.setText(f"📄 当前功能: {item}")

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用属性
    app.setApplicationName("智能学习笔记助手")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("Learning Assistant")
    
    # 创建主窗口
    window = ModernLearningApp()
    window.show()
    
    # 运行应用
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
